"""End-to-end replay: train on recorded features, predict on LLM-extracted ones.

The standard walk-forward replay (``services/replay.py``) predicts each row from
its *recorded* feature vector, i.e. with oracle features. This script measures
the real deployment path instead:

1. every customer email is passed through the production extraction
   (``extract_features`` with the configured provider, expected: deepseek);
2. the extracted feature vector (with ``null`` for unresolved features) is used
   to predict that project, with Monte Carlo handling of the unknowns;
3. the model is trained only on earlier rows, using their recorded features
   (leakage-free, same order as the replay).

Extraction is cached per ``project_id`` in ``data/endtoend_extractions.json`` so
an interrupted run resumes without repeating API calls. The cache is small and
is meant to be committed for reproducibility.

Usage (from backend/)::

    PYTHONPATH=. /root/venvs/estimator/bin/python scripts/endtoend_replay.py --limit 3
    PYTHONPATH=. /root/venvs/estimator/bin/python scripts/endtoend_replay.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Allow `python scripts/endtoend_replay.py` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features import FEATURES  # noqa: E402
from app.services.estimation import estimate, estimate_mc, train_model  # noqa: E402
from app.services.extraction import extract_features  # noqa: E402
from app.services.providers import get_provider  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
CACHE_PATH = REPO_ROOT / "data" / "endtoend_extractions.json"
RESULT_PATH = REPO_ROOT / "data" / "endtoend_replay_results.json"
MIN_TRAIN = 10


def load_rows() -> list[dict]:
    frame = pd.read_csv(CSV_PATH)
    frame = frame[frame["actual_days"].notna() & (frame["actual_days"] > 0)].copy()
    frame = frame.sort_values(["date", "project_id"]).reset_index(drop=True)
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "project_id": row["project_id"],
                "date": row["date"],
                "actual_days": float(row["actual_days"]),
                "team_estimate": (
                    float(row["team_estimate"])
                    if pd.notna(row["team_estimate"])
                    else None
                ),
                "email_text": str(row["email_text"]),
                "features": {name: int(row[f"feat_{name}"]) for name in FEATURES},
            }
        )
    return rows


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def extract_all(rows: list[dict], provider_name: str, refresh: bool) -> dict:
    provider, actual_name = get_provider(provider_name)
    if actual_name != provider_name:
        print(f"WARNING: requested provider {provider_name!r}, using {actual_name!r}")
    cache = {} if refresh else load_cache()
    cache.setdefault("_meta", {})
    cache["_meta"] = {
        "provider": actual_name,
        "csv_sha1": hashlib.sha1(CSV_PATH.read_bytes()).hexdigest(),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    todo = [r for r in rows if r["project_id"] not in cache]
    print(f"rows={len(rows)} cached={len(rows) - len(todo)} to_extract={len(todo)}")
    for index, row in enumerate(todo, start=1):
        pid = row["project_id"]
        started = time.time()
        try:
            result = extract_features(row["email_text"], provider)
            features = {
                finding.name: (None if finding.value is None else int(finding.value))
                for finding in result.findings
            }
            cache[pid] = {
                "features": features,
                "provider": result.provider,
                "warnings": list(result.warnings),
                "seconds": round(time.time() - started, 1),
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }
        except Exception as exc:  # noqa: BLE001 - one failed email must not abort
            cache[pid] = {
                "features": {name: None for name in FEATURES},
                "error": str(exc)[:300],
                "seconds": round(time.time() - started, 1),
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }
        save_cache(cache)
        if index % 10 == 0 or index == len(todo):
            print(f"  {index}/{len(todo)} extracted (last: {pid}, {cache[pid]['seconds']}s)")
    return cache


def replay(
    rows: list[dict], cache: dict, use_extracted: bool, draws: int, resolve_k: int = 0
) -> dict:
    ordered = sorted(rows, key=lambda r: (str(r["date"]), str(r["project_id"])))
    errors, hits, widths, unknowns, failed_rows = [], 0, [], 0, 0
    resolved_total = 0
    steps = 0
    for i in range(MIN_TRAIN, len(ordered)):
        row = ordered[i]
        model = train_model(ordered[:i])
        if use_extracted:
            entry = cache.get(row["project_id"]) or {}
            features = {
                name: (entry.get("features") or {}).get(name) for name in FEATURES
            }
            unknown_now = [name for name in FEATURES if features[name] is None]
            # "Questions answered" ablation: resolve the top-k unknowns by impact
            # using the true values (an oracle answerer; upper bound on the loop).
            if resolve_k > 0 and unknown_now:
                impacts = []
                for name in unknown_now:
                    base = {n: (0 if features[n] is None else features[n]) for n in FEATURES}
                    with_ = dict(base)
                    with_[name] = 1
                    without = dict(base)
                    without[name] = 0
                    swing = abs(
                        estimate(model, with_)["p50"] - estimate(model, without)["p50"]
                    )
                    impacts.append((swing, name))
                impacts.sort(reverse=True)
                for _, name in impacts[:resolve_k]:
                    features[name] = row["features"][name]
                    resolved_total += 1
            if any(features.get(name) is None for name in FEATURES):
                unknowns += sum(1 for name in FEATURES if features.get(name) is None)
                if all(features.get(name) is None for name in FEATURES):
                    failed_rows += 1
                predicted = estimate_mc(model, features, n=draws, seed=42)
            else:
                predicted = estimate(model, features)
        else:
            predicted = estimate(model, row["features"])

        actual = row["actual_days"]
        errors.append(abs(actual - predicted["p50"]))
        hits += int(predicted["p10"] <= actual <= predicted["p90"])
        widths.append((predicted["p90"] - predicted["p10"]) / max(predicted["p50"], 1e-9))
        steps += 1

    if steps == 0:
        return {
            "steps": 0,
            "mae": None,
            "median_ae": None,
            "coverage_pct": None,
            "mean_rel_width": None,
            "unknown_features": unknowns,
            "failed_rows": failed_rows,
        }

    return {
        "steps": steps,
        "mae": round(float(np.mean(errors)), 2),
        "median_ae": round(float(np.median(errors)), 2),
        "coverage_pct": round(100.0 * hits / max(steps, 1), 1),
        "mean_rel_width": round(float(np.mean(widths)), 2),
        "unknown_features": unknowns,
        "failed_rows": failed_rows,
        "answered_questions": resolved_total,
    }


def extraction_metrics(rows: list[dict], cache: dict) -> dict:
    tp = fp = fn = tn = unknown = 0
    all_null = 0
    per_feature = {name: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "unknown": 0} for name in FEATURES}
    for row in rows:
        entry = cache.get(row["project_id"]) or {}
        features = entry.get("features") or {}
        if all(features.get(name) is None for name in FEATURES):
            all_null += 1
        for name in FEATURES:
            truth = row["features"][name]
            predicted = features.get(name)
            cell = per_feature[name]
            if predicted is None:
                unknown += 1
                cell["unknown"] += 1
            else:
                predicted = int(predicted)
                if predicted == 1 and truth == 1:
                    tp += 1
                    cell["tp"] += 1
                elif predicted == 1 and truth == 0:
                    fp += 1
                    cell["fp"] += 1
                elif predicted == 0 and truth == 1:
                    fn += 1
                    cell["fn"] += 1
                else:
                    tn += 1
                    cell["tn"] += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "micro_precision": round(precision, 3),
        "micro_recall": round(recall, 3),
        "micro_f1": round(f1, 3),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "unknown": unknown,
        "unknown_pct": round(100.0 * unknown / (len(rows) * len(FEATURES)), 1),
        "all_null_rows": all_null,
        "per_feature": per_feature,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--limit", type=int, default=0, help="limit rows (smoke test)")
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument(
        "--answers", type=int, nargs="+", default=[0, 5, 10, 15],
        help="oracle answers to simulate per row (upper bound on the question loop)",
    )
    parser.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = parser.parse_args()

    rows = load_rows()
    if args.limit:
        rows = rows[: args.limit]
    cache = extract_all(rows, args.provider, args.refresh)

    print("\n=== extraction quality vs recorded features ===")
    extraction = extraction_metrics(rows, cache)
    print(
        f"micro P/R/F1 = {extraction['micro_precision']:.3f}/"
        f"{extraction['micro_recall']:.3f}/{extraction['micro_f1']:.3f}  "
        f"unknown={extraction['unknown_pct']:.1f}%  all-null rows={extraction['all_null_rows']}"
    )

    print("\n=== walk-forward replay ===")
    oracle = replay(rows, cache, use_extracted=False, draws=args.draws)
    print(f"oracle features        : {oracle}")
    answers = {}
    for k in args.answers:
        result = replay(rows, cache, use_extracted=True, draws=args.draws, resolve_k=k)
        answers[k] = result
        print(f"extracted + {k:>2} answers : {result}")

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "provider": cache.get("_meta", {}).get("provider"),
        "n_rows": len(rows),
        "oracle": oracle,
        "end_to_end": answers.get(0),
        "answers": answers,
        "extraction": extraction,
    }
    RESULT_PATH.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {RESULT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
