"""Build ``data/null_prior.json``: P(feature=1 | extraction left it null).

An extraction ``null`` means "the request did not mention this feature", which
is not the same event as "a feature drawn at its marginal prevalence". This
script estimates the null-conditioned rate per feature from the committed
extraction cache and the recorded feature vectors, and writes the prior that
``estimate_mc`` uses at prediction time.

Run from backend/:

    PYTHONPATH=. python scripts/build_null_prior.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features import FEATURES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
CACHE_PATH = REPO_ROOT / "data" / "endtoend_extractions.json"
OUT_PATH = REPO_ROOT / "data" / "null_prior.json"
MIN_NULLS_PER_FEATURE = 5


def main() -> None:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    frame = pd.read_csv(CSV_PATH)
    frame = frame[frame["actual_days"].notna() & (frame["actual_days"] > 0)]

    totals = {name: 0 for name in FEATURES}
    positives = {name: 0 for name in FEATURES}
    rows = 0
    for _, row in frame.iterrows():
        entry = cache.get(row["project_id"]) or {}
        extracted = entry.get("features") or {}
        for name in FEATURES:
            truth = int(row[f"feat_{name}"])
            if extracted.get(name) is None:
                totals[name] += 1
                positives[name] += truth
        rows += 1

    total = sum(totals.values())
    overall = (sum(positives.values()) / total) if total else 0.0
    features = {
        name: round(
            (positives[name] / totals[name])
            if totals[name] >= MIN_NULLS_PER_FEATURE
            else overall,
            4,
        )
        for name in FEATURES
    }
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "data/endtoend_extractions.json + data/synthetic_history.csv",
        "rows": rows,
        "null_cells": total,
        "overall": round(overall, 4),
        "min_nulls_per_feature": MIN_NULLS_PER_FEATURE,
        "features": features,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"overall P(true|null)={overall:.4f} over {total} null cells")
    for name in FEATURES:
        print(f"  {name:26s} {features[name]:.4f}  (nulls={totals[name]})")
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
