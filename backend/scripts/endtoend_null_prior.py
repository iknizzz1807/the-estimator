"""End-to-end replay v2: null-handling mechanisms.

Arms:
  zero        : unknown -> 0
  global      : current estimate_mc (global prevalence)
  conditional : walk-forward P(true | null) per feature, computed from history
  oracle      : true features (upper bound)

Also reports the extraction null-conditional prior and a question-loop ablation
for the conditional arm (oracle answers).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/sdcard/Documents/the-estimator/backend")
from app.features import FEATURES
from app.services.estimation import (
    QUANTILE_LEVELS, _finish, _residual_draws, estimate, estimate_mc, train_model,
)

REPO = Path("/sdcard/Documents/the-estimator")
CSV = REPO / "data" / "synthetic_history.csv"
CACHE = REPO / "data" / "endtoend_extractions.json"
DRAWS = 2000
MIN_TRAIN = 10


def load():
    cache = json.loads(CACHE.read_text())
    frame = pd.read_csv(CSV)
    frame = frame[frame["actual_days"].notna() & (frame["actual_days"] > 0)].copy()
    frame = frame.sort_values(["date", "project_id"]).reset_index(drop=True)
    rows = []
    for _, r in frame.iterrows():
        rows.append({
            "project_id": r["project_id"],
            "date": r["date"],
            "actual_days": float(r["actual_days"]),
            "features": {f: int(r[f"feat_{f}"]) for f in FEATURES},
            "extracted": (cache.get(r["project_id"], {}).get("features") or {}),
        })
    return rows


def null_prior(history):
    """Per-feature P(true | null) over history; smoothed fallback to overall."""
    totals = {f: 0 for f in FEATURES}
    positives = {f: 0 for f in FEATURES}
    for row in history:
        ext = row["extracted"]
        for f in FEATURES:
            if ext.get(f) is None:
                totals[f] += 1
                positives[f] += row["features"][f]
    total = sum(totals.values())
    pos = sum(positives.values())
    overall = pos / total if total else 0.0
    out = {}
    for f in FEATURES:
        out[f] = (positives[f] / totals[f]) if totals[f] >= 5 else overall
    return out, overall, total


def mc_with_prior(model, feats, prior, rng, draws=DRAWS):
    unknown = [f for f in FEATURES if feats.get(f) is None]
    if not unknown:
        return estimate(model, feats)
    base = np.array([0 if feats.get(f) is None else int(feats[f]) for f in FEATURES], dtype=float)
    x = np.tile(base, (draws, 1))
    idx = {f: i for i, f in enumerate(FEATURES)}
    for f in unknown:
        x[:, idx[f]] = rng.random(draws) < prior.get(f, 0.0)
    logp = np.asarray(model.model.predict(x), dtype=float).ravel()
    samples = np.exp(logp + _residual_draws(model, rng, draws))
    q10, q50, q90 = (float(v) for v in np.quantile(samples, QUANTILE_LEVELS))
    return _finish(q10, q50, q90, "calibrated")


def record(pred, actual, bucket):
    bucket["err"].append(abs(pred["p50"] - actual))
    bucket["cov"].append(int(pred["p10"] <= actual <= pred["p90"]))
    bucket["width"].append((pred["p90"] - pred["p10"]) / max(pred["p50"], 1e-9))


def run(rows, arm, k=0):
    bucket = {"err": [], "cov": [], "width": []}
    priors = []
    for i in range(MIN_TRAIN, len(rows)):
        train, test = rows[:i], rows[i]
        model = train_model(train)
        ext = dict(test["extracted"])
        if arm == "conditional":
            prior, overall, total = null_prior(train)
            priors.append((overall, total))
            # resolve top-k unknowns with oracle answers (question loop)
            unknown = [f for f in FEATURES if ext.get(f) is None]
            if k > 0 and unknown:
                impacts = []
                for f in unknown:
                    base = {x: (0 if ext.get(x) is None else ext[x]) for x in FEATURES}
                    w = dict(base); w[f] = 1
                    wo = dict(base); wo[f] = 0
                    imp = abs(estimate(model, w)["p50"] - estimate(model, wo)["p50"])
                    impacts.append((imp, f))
                impacts.sort(reverse=True)
                for _, f in impacts[:k]:
                    ext[f] = test["features"][f]
            pred = mc_with_prior(model, ext, prior, np.random.default_rng(42))
        elif arm == "zero":
            pred = estimate(model, {f: (0 if ext.get(f) is None else int(ext[f])) for f in FEATURES})
        elif arm == "global":
            pred = estimate_mc(model, {f: (None if ext.get(f) is None else int(ext[f])) for f in FEATURES}, n=DRAWS, seed=42)
        elif arm == "oracle":
            pred = estimate(model, test["features"])
        else:
            raise ValueError(arm)
        record(pred, test["actual_days"], bucket)
    n = len(bucket["err"])
    return {
        "mae": round(float(np.mean(bucket["err"])), 2),
        "coverage": round(100 * float(np.mean(bucket["cov"])), 1),
        "width": round(float(np.mean(bucket["width"])), 2),
        "steps": n,
        "priors": priors,
    }


rows = load()
print(f"rows={len(rows)}")
for arm in ["zero", "global", "conditional", "oracle"]:
    r = run(rows, arm)
    print(f"{arm:12s} MAE={r['mae']:6.2f}  coverage={r['coverage']:5.1f}%  width={r['width']:.2f}")
print("\n=== conditional + oracle answers ===")
for k in [0, 5, 10, 15]:
    r = run(rows, "conditional", k=k)
    print(f"k={k:2d}  MAE={r['mae']:6.2f}  coverage={r['coverage']:5.1f}%  width={r['width']:.2f}")

# report the final walk-forward conditional prior
prior, overall, total = null_prior(rows[:-1])
print(f"\noverall P(true|null)={overall:.3f} over {total} null cells")
for f in FEATURES:
    print(f"  {f:26s} {prior[f]:.3f}")
