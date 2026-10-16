"""Extraction quality evaluation vs ground truth (docs/EXTRACTION_EVAL.md).

The estimator model is trained on clean ground-truth feature vectors, but at
runtime those features come from an extraction step (offline stub rules or a
real LLM). This script measures that step directly against the labels we own
(``data/ground_truth.json``) on the emails in ``data/synthetic_history.csv``,
so the extractor's noise can be isolated from model error.

Run from ``backend/`` with ``PYTHONPATH=.`` and the project venv:

    /root/venvs/estimator/bin/python scripts/extraction_eval.py --provider stub --limit 240 --write
    /root/venvs/estimator/bin/python scripts/extraction_eval.py --provider deepseek --limit 240 --write

``--write`` merges the current provider's result block into
``docs/EXTRACTION_EVAL.md``; earlier blocks are recovered from an HTML comment
payload in that file, so stub + deepseek runs render one two-table report.
The stub run executes twice in-process and refuses a non-identical rerun
(determinism guard). The evaluation uses the production call path
(``extract_features``) with the same provider factory as the API.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from app.features import FEATURES
from app.services.extraction import extract_features
from app.services.providers import get_provider, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
GT_PATH = REPO_ROOT / "data" / "ground_truth.json"
DOC_PATH = REPO_ROOT / "docs" / "EXTRACTION_EVAL.md"

CHARS_PER_TOKEN = 4.0  # rough heuristic, labelled as such in the report
PRICING_PEAK_USD = (0.30, 1.20)  # USD per 1M tokens, in/out, DeepSeek Flash peak
PRICING_OFFPEAK_USD = (0.15, 0.60)  # USD per 1M tokens, in/out, off-peak
FAILURE_MARKER = "Không thể trích xuất"  # extraction.py degrade-to-null warning
PAYLOAD_RE = re.compile(r"<!-- extraction-eval-data\s*(\{.*\})\s*-->", re.DOTALL)
MAX_REPORT_LINES = 120


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def load_projects(limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Emails (CSV) joined with ground truth, in ground-truth order, capped."""
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    with CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        rows = {record["project_id"]: record for record in csv.DictReader(handle)}
    projects: list[dict[str, Any]] = []
    missing_csv: list[str] = []
    mismatches = 0
    for project_id, entry in gt["projects"].items():
        record = rows.get(project_id)
        if record is None:
            missing_csv.append(project_id)
            continue
        truth = {name: int(entry["features"][name]) for name in FEATURES}
        mismatches += sum(
            1 for name in FEATURES if truth[name] != int(record[f"feat_{name}"])
        )
        projects.append(
            {
                "project_id": project_id,
                "email": record["email_text"],
                "truth": truth,
                "mentioned": list(entry.get("mentioned", [])),
                "omitted": list(entry.get("omitted", [])),
                "negated": list(entry.get("negated", [])),
            }
        )
    notes = {
        "n_gt_projects": len(gt["projects"]),
        "n_csv_rows": len(rows),
        "missing_csv": missing_csv,
        "csv_gt_mismatch_cells": mismatches,
    }
    return projects[:limit], notes


class MeteredProvider:
    """Wraps an LLMProvider and counts prompt/response characters."""

    def __init__(self, inner: Any, name: str) -> None:
        self.inner = inner
        self.name = name
        self.calls = 0
        self.errors = 0
        self.in_chars = 0
        self.out_chars = 0

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        self.calls += 1
        self.in_chars += len(prompt) + (len(system) if system else 0)
        try:
            data = self.inner.complete_json(prompt, system)
        except BaseException:
            self.errors += 1
            raise
        self.out_chars += len(json.dumps(data, ensure_ascii=False))
        return data


def evaluate_once(
    projects: list[dict[str, Any]], provider_name: str
) -> tuple[list[dict[str, Any]], list[str], MeteredProvider, str, float]:
    """Run the production extraction path over every project, one outer retry."""
    provider, actual_name = get_provider(provider_name)
    if provider_name == "deepseek" and actual_name != "deepseek":
        raise SystemExit(
            f"Requested 'deepseek' but the factory fell back to '{actual_name}' "
            "(missing/unusable key). Refusing to evaluate the wrong provider."
        )
    metered = MeteredProvider(provider, actual_name)
    per_project: list[dict[str, Any]] = []
    skipped: list[str] = []
    started = time.perf_counter()
    for index, project in enumerate(projects, 1):
        t0 = time.perf_counter()
        result = extract_features(project["email"], provider=(metered, actual_name))
        failed = any(FAILURE_MARKER in warning for warning in result.warnings)
        if failed:  # exactly one outer retry, then skip + note
            result = extract_features(project["email"], provider=(metered, actual_name))
            failed = any(FAILURE_MARKER in warning for warning in result.warnings)
        if failed:
            skipped.append(project["project_id"])
            print(
                f"[{index}/{len(projects)}] {project['project_id']} FAILED (skipped)",
                file=sys.stderr,
                flush=True,
            )
            continue
        elapsed = time.perf_counter() - t0
        per_project.append(
            {
                "project_id": project["project_id"],
                "truth": project["truth"],
                "mentioned": project["mentioned"],
                "omitted": project["omitted"],
                "negated": project["negated"],
                "pred": {finding.name: finding.value for finding in result.findings},
                "seconds": elapsed,
                "email_chars": len(project["email"]),
            }
        )
        print(
            f"[{index}/{len(projects)}] {project['project_id']} ok ({elapsed:.2f}s)",
            file=sys.stderr,
            flush=True,
        )
    return per_project, skipped, metered, actual_name, time.perf_counter() - started


def _div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def compute_metrics(per_project: list[dict[str, Any]]) -> dict[str, Any]:
    """All per-feature / micro / macro metrics for one evaluated run."""
    per_feature: dict[str, dict[str, Any]] = {}
    micro_tp = micro_fp = micro_fn = 0
    for name in FEATURES:
        tp = fp = fn = n_true = 0
        for row in per_project:
            if row["truth"][name] == 1:
                n_true += 1
                if row["pred"].get(name) is True:
                    tp += 1
                else:  # None (unknown) or False both miss a present feature
                    fn += 1
            elif row["pred"].get(name) is True:
                fp += 1
        precision = _div(tp, tp + fp)
        recall = _div(tp, n_true)
        per_feature[name] = {
            "n_true": n_true,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
        }
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn

    micro_precision = _div(micro_tp, micro_tp + micro_fp)
    micro_recall = _div(micro_tp, micro_tp + micro_fn)

    def macro(key: str) -> tuple[float | None, int]:
        values = [per_feature[n][key] for n in FEATURES if per_feature[n][key] is not None]
        return (fmean(values) if values else None, len(values))

    macro_precision, macro_precision_n = macro("precision")
    macro_recall, macro_recall_n = macro("recall")
    macro_f1, macro_f1_n = macro("f1")

    omitted_total = sum(len(row["omitted"]) for row in per_project)
    omitted_unknown = sum(
        1 for row in per_project for n in row["omitted"] if row["pred"].get(n) is None
    )
    omitted_asserted_false = sum(
        1 for row in per_project for n in row["omitted"] if row["pred"].get(n) is False
    )
    omitted_asserted_true = sum(
        1 for row in per_project for n in row["omitted"] if row["pred"].get(n) is True
    )

    negated_total = sum(len(row["negated"]) for row in per_project)
    negated_correct_zero = sum(
        1 for row in per_project for n in row["negated"] if row["pred"].get(n) is False
    )
    negated_unknown = sum(
        1 for row in per_project for n in row["negated"] if row["pred"].get(n) is None
    )
    negated_asserted_true = sum(
        1 for row in per_project for n in row["negated"] if row["pred"].get(n) is True
    )

    mentioned_total = sum(len(row["mentioned"]) for row in per_project)
    mentioned_false = sum(
        1 for row in per_project for n in row["mentioned"] if row["pred"].get(n) is False
    )
    mentioned_unknown = sum(
        1 for row in per_project for n in row["mentioned"] if row["pred"].get(n) is None
    )

    return {
        "per_feature": per_feature,
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": _f1(micro_precision, micro_recall),
            "tp": micro_tp,
            "fp": micro_fp,
            "fn": micro_fn,
        },
        "macro": {
            "precision": macro_precision,
            "recall": macro_recall,
            "f1": macro_f1,
            "n_defined_precision": macro_precision_n,
            "n_defined_recall": macro_recall_n,
            "n_defined_f1": macro_f1_n,
        },
        "unknown": {
            "omitted_total": omitted_total,
            "correctly_unknown": omitted_unknown,
            "accuracy": _div(omitted_unknown, omitted_total),
            "asserted_false": omitted_asserted_false,
            "asserted_true": omitted_asserted_true,
            "asserted_fraction": _div(
                omitted_total - omitted_unknown, omitted_total
            ),
        },
        "negation": {
            "negated_total": negated_total,
            "correct_zero": negated_correct_zero,
            "accuracy": _div(negated_correct_zero, negated_total),
            "answered_unknown": negated_unknown,
            "asserted_one": negated_asserted_true,
        },
        "wrongly_absent": {
            "mentioned_total": mentioned_total,
            "predicted_false": mentioned_false,
            "fraction": _div(mentioned_false, mentioned_total),
            "predicted_unknown": mentioned_unknown,
        },
    }


def run_provider(
    provider_name: str, projects: list[dict[str, Any]], settings: Any
) -> dict[str, Any]:
    per_project, skipped, metered, actual_name, total_seconds = evaluate_once(
        projects, provider_name
    )
    if not per_project:
        raise SystemExit(f"No emails evaluated for provider '{provider_name}' - aborting.")

    metrics = compute_metrics(per_project)
    n_eval = len(per_project)
    in_tokens_total = metered.in_chars / CHARS_PER_TOKEN
    out_tokens_total = metered.out_chars / CHARS_PER_TOKEN

    repeat_check = "not_applicable"
    if provider_name == "stub":  # determinism guard: identical rerun required
        rerun, rerun_skipped, _, _, _ = evaluate_once(projects, provider_name)
        repeat_check = (
            "identical"
            if compute_metrics(rerun) == metrics and rerun_skipped == skipped
            else "MISMATCH"
        )

    return {
        "provider": actual_name,
        "model": settings.deepseek_model if provider_name == "deepseek" else "offline rules",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "n_evaluated": n_eval,
        "n_skipped": len(skipped),
        "skipped_ids": skipped,
        "csv_sha1": sha1(CSV_PATH),
        "gt_sha1": sha1(GT_PATH),
        "repeat_check": repeat_check,
        "metrics": metrics,
        "timing": {
            "total_seconds": total_seconds,
            "avg_seconds": total_seconds / n_eval,
            "provider_calls": metered.calls,
            "provider_errors": metered.errors,
            "in_tokens_total": in_tokens_total,
            "out_tokens_total": out_tokens_total,
            "in_tokens_avg": in_tokens_total / n_eval,
            "out_tokens_avg": out_tokens_total / n_eval,
            "email_tokens_avg": fmean(row["email_chars"] for row in per_project)
            / CHARS_PER_TOKEN,
        },
        "est": {
            "cost_peak_usd": in_tokens_total / 1e6 * PRICING_PEAK_USD[0]
            + out_tokens_total / 1e6 * PRICING_PEAK_USD[1],
            "cost_offpeak_usd": in_tokens_total / 1e6 * PRICING_OFFPEAK_USD[0]
            + out_tokens_total / 1e6 * PRICING_OFFPEAK_USD[1],
        },
    }


def _f(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(
    blocks: dict[str, Any], data_notes: dict[str, Any], include_payload: bool
) -> str:
    providers = [p for p in ("stub", "deepseek") if p in blocks]
    cells_total = data_notes["n_gt_projects"] * len(FEATURES)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "# Extraction Quality vs Ground Truth",
        "",
        f"Generated by `backend/scripts/extraction_eval.py` on {now}.",
        "Motivation (reviewer critique): the estimator trains on clean ground-truth features",
        "but runs on noisy extracted features; extraction quality was never measured per",
        "feature. We own the labels, so precision/recall of the extraction step is measurable.",
        "",
    ]

    def cell(provider: str, render) -> str:
        block = blocks.get(provider)
        return render(block) if block else "—"

    def row(label: str, render) -> str:
        return "| " + label + " | " + " | ".join(cell(p, render) for p in providers) + " |"

    def cost(block: dict[str, Any]) -> str:
        if block["provider"] == "stub":
            return "n/a (offline)"
        return (
            f"${block['est']['cost_peak_usd']:.4f} / "
            f"${block['est']['cost_offpeak_usd']:.4f}"
        )

    lines += [
        "## Method",
        "",
        f"- Inputs: {data_notes['n_gt_projects']} ground-truth projects joined with "
        f"`data/synthetic_history.csv` emails (feature cells disagreeing with ground "
        f"truth: {data_notes['csv_gt_mismatch_cells']}/{cells_total}). For each email the production path",
        "  `extract_features(email, provider=(p, name))` predicts `1 | 0 | null` per feature.",
        "- Present detection: predicted `1` vs truth `features == 1`. `null` counts as a miss",
        "  (not an assertion), so precision penalises asserted-but-absent claims, recall counts hits.",
        "- Unknown-accuracy (b): of truth `omitted` features (really present, absent from the email)",
        "  the fraction the extractor correctly leaves `null`; below it, the wrongly-asserted split.",
        "- Negation accuracy (c): of truth `negated` features (email explicitly denies an absent",
        "  feature) the fraction predicted exactly `0`.",
        "- Wrongly-asserted-absent (d): predicted `0` on truth `mentioned` features (should be `1`).",
        "- Micro pools TP/FP/FN over all cells; macro averages per-feature P/R/F1 (undefined excluded).",
        "- Stub is deterministic: the full run executes twice in-process and must compare identical.",
        "- DeepSeek: temperature 0 + thinking disabled, but LLM output is not bit-stable; single sample.",
        "",
        "## Headline metrics",
        "",
        "| metric | " + " | ".join(providers) + " |",
        "|---|" + "---:|" * len(providers),
        row("emails evaluated (skipped)", lambda b: f"{b['n_evaluated']} ({b['n_skipped']})"),
        row("micro precision", lambda b: _f(b["metrics"]["micro"]["precision"])),
        row("micro recall", lambda b: _f(b["metrics"]["micro"]["recall"])),
        row("micro F1", lambda b: _f(b["metrics"]["micro"]["f1"])),
        row("macro precision", lambda b: _f(b["metrics"]["macro"]["precision"])),
        row("macro recall", lambda b: _f(b["metrics"]["macro"]["recall"])),
        row("macro F1", lambda b: _f(b["metrics"]["macro"]["f1"])),
        row(
            f"TP / FP / FN ({cells_total} cells)",
            lambda b: f"{b['metrics']['micro']['tp']} / {b['metrics']['micro']['fp']} / "
            f"{b['metrics']['micro']['fn']}",
        ),
        row(
            "unknown-accuracy on omitted",
            lambda b: f"{_pct(b['metrics']['unknown']['accuracy'])} "
            f"({b['metrics']['unknown']['correctly_unknown']}/{b['metrics']['unknown']['omitted_total']})",
        ),
        row(
            "omitted wrongly asserted 0 / 1",
            lambda b: f"{b['metrics']['unknown']['asserted_false']} / "
            f"{b['metrics']['unknown']['asserted_true']}",
        ),
        row(
            "negation accuracy (negated -> 0)",
            lambda b: f"{_pct(b['metrics']['negation']['accuracy'])} "
            f"({b['metrics']['negation']['correct_zero']}/{b['metrics']['negation']['negated_total']})",
        ),
        row(
            "negated answered unknown / asserted 1",
            lambda b: f"{b['metrics']['negation']['answered_unknown']} / "
            f"{b['metrics']['negation']['asserted_one']}",
        ),
        row(
            "wrongly asserted 0 on mentioned",
            lambda b: f"{_pct(b['metrics']['wrongly_absent']['fraction'])} "
            f"({b['metrics']['wrongly_absent']['predicted_false']}/"
            f"{b['metrics']['wrongly_absent']['mentioned_total']}); "
            f"+{b['metrics']['wrongly_absent']['predicted_unknown']} left unknown",
        ),
        row("avg seconds / email", lambda b: _f(b["timing"]["avg_seconds"])),
        row(
            "est. tokens/email (prompt / response, chars/4)",
            lambda b: f"{b['timing']['in_tokens_avg']:.0f} / {b['timing']['out_tokens_avg']:.0f}",
        ),
        row("rough cost all emails, peak / off-peak", cost),
        "",
    ]

    for provider in providers:
        block = blocks[provider]
        lines += [
            f"### Per-feature present detection — {provider}"
            f" ({block['provider']}, {block['model']}, {block['date']})",
            "",
            "| feature | n_true | TP | FP | FN | precision | recall | F1 |",
            "|---|--:|--:|--:|--:|--:|--:|--:|",
        ]
        for name in FEATURES:
            feat = block["metrics"]["per_feature"][name]
            lines.append(
                f"| {name} | {feat['n_true']} | {feat['tp']} | {feat['fp']} | {feat['fn']} "
                f"| {_f(feat['precision'])} | {_f(feat['recall'])} | {_f(feat['f1'])} |"
            )
        lines.append("")

    sha_pairs = {
        (b["csv_sha1"], b["gt_sha1"]) for b in blocks.values() if b is not None
    }
    if len(sha_pairs) > 1:
        lines += [
            "**Note: provider blocks were recorded on different data revisions (sha1 mismatch,"
            " per-block sha1s below). Extraction metrics stay comparable only if emails and"
            " feature labels are unchanged between revisions (verify with `git diff data/`),"
            " otherwise re-run both blocks on the same revision.**",
            "",
        ]

    stub_block = blocks.get("stub")
    lines += [
        "## Notes (honest caveats)",
        "",
        *[
            f"- Data sha1 ({name} block): csv `{block['csv_sha1']}` / "
            f"ground_truth `{block['gt_sha1']}`."
            for name, block in blocks.items()
            if block
        ],
        "- Stub determinism: "
        + (
            "two full runs produced identical metrics (verified `repeat_check=identical`)."
            if stub_block and stub_block["repeat_check"] == "identical"
            else "not verified in this rendering (stub block absent or mismatch)."
        ),
        "- DeepSeek is one sample: `temperature=0` and thinking disabled do not make LLM output",
        "  bit-stable; reruns may move a few cells. Only the stub table is reproducible.",
        "- Cost is a rough estimate from prompt/response chars / 4 at DeepSeek Flash list prices",
        "  ($0.30/$1.20 per 1M in/out peak, $0.15/$0.60 off-peak); actual billing differs.",
        "- A `null`-only extractor would score 100% unknown-accuracy while failing recall; read the",
        "  present-detection table and unknown-accuracy together.",
        "- Skipped projects (provider failure after one retry): "
        + (
            "; ".join(
                f"{p}: {', '.join(str(i) for i in b['skipped_ids'])}"
                for p, b in blocks.items()
                if b and b["n_skipped"]
            )
            or "none"
        )
        + ".",
        "- Failure mode seen on skipped rows: provider returned unparseable (non-JSON) output;",
        "  in the app `extract_features` degrades to all-null findings with a review warning.",
        "- Data may be regenerated by a parallel task; sha1s above anchor this report - rerun after changes.",
    ]
    if include_payload:
        lines += [
            "",
            "<!-- extraction-eval-data "
            + json.dumps(blocks, ensure_ascii=False, sort_keys=True)
            + " -->",
        ]
    return "\n".join(lines)


def load_existing_blocks() -> dict[str, Any]:
    if not DOC_PATH.exists():
        return {}
    match = PAYLOAD_RE.search(DOC_PATH.read_text(encoding="utf-8"))
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=["stub", "deepseek"], default="stub")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument(
        "--write", action="store_true", help=f"merge results into {DOC_PATH.name}"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    projects, data_notes = load_projects(args.limit)
    settings = get_settings()
    print(
        f"data: {CSV_PATH.name} sha1={sha1(CSV_PATH)} ground_truth sha1={sha1(GT_PATH)}",
        flush=True,
    )
    print(
        f"provider={args.provider} projects={len(projects)} "
        f"(gt={data_notes['n_gt_projects']}, csv={data_notes['n_csv_rows']})",
        flush=True,
    )
    if data_notes["missing_csv"]:
        print(f"ground-truth projects missing from CSV: {data_notes['missing_csv']}")
    if data_notes["csv_gt_mismatch_cells"]:
        print(f"WARNING: {data_notes['csv_gt_mismatch_cells']} CSV/ground-truth cells disagree")

    block = run_provider(args.provider, projects, settings)
    blocks = load_existing_blocks()
    blocks[args.provider] = block

    print()
    print(render_markdown(blocks, data_notes, include_payload=False))

    exit_code = 0
    if args.write:
        markdown = render_markdown(blocks, data_notes, include_payload=True)
        line_count = len(markdown.splitlines())
        DOC_PATH.write_text(markdown + "\n", encoding="utf-8")
        print(f"wrote {DOC_PATH.relative_to(REPO_ROOT)} ({line_count} lines)")
        if line_count > MAX_REPORT_LINES:
            print(f"WARNING: report has {line_count} lines (> {MAX_REPORT_LINES})")

    if block["repeat_check"] == "MISMATCH":
        print("ERROR: stub rerun produced different metrics (non-deterministic).", file=sys.stderr)
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
