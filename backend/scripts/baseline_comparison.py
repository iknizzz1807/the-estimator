"""Estimator baseline comparison on the synthetic walk-forward replay.

Compares, on the same 218 steps (train on rows[:i], predict row i, recorded
features):
  - ridge_style : the deployed Ridge + out-of-fold residual quantiles + tail
                  widening (conformal-style; the current product interval)
  - ridge_split : Ridge + true split conformal (fit 80% / calibrate 20%)
  - gbm_split   : HistGradientBoosting + split conformal
  - gbm_quant   : gradient-boosted quantile regression (q10/q50/q90)
  - median      : constant median with empirical 10/90 quantiles

Metric: MAE of P50 (days), empirical P10-P90 coverage, relative width.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features import FEATURES  # noqa: E402
from app.services.estimation import estimate, train_model  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.ensemble import GradientBoostingRegressor  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
OUT_PATH = REPO_ROOT / "data" / "baseline_comparison.json"
MIN_TRAIN = 10
CALIB_FRACTION = 0.2


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
                "features": {name: int(row[f"feat_{name}"]) for name in FEATURES},
            }
        )
    return rows


def x_of(row: dict) -> list[float]:
    return [float(row["features"][name]) for name in FEATURES]


def conformal_quantiles(residuals: np.ndarray, q_levels=(0.1, 0.9)) -> tuple[float, float]:
    n = len(residuals)
    out = []
    for q in q_levels:
        q_adj = min(1.0, q * (n + 1) / n)
        out.append(float(np.quantile(residuals, q_adj, method="higher")))
    return out[0], out[1]


def record(pred: dict, actual: float, bucket: dict) -> None:
    bucket["err"].append(abs(pred["p50"] - actual))
    bucket["cov"].append(int(pred["p10"] <= actual <= pred["p90"]))
    bucket["width"].append((pred["p90"] - pred["p10"]) / max(pred["p50"], 1e-9))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = load_rows()
    if args.limit:
        rows = rows[: args.limit]
    names = ["ridge_style", "ridge_split", "gbm_split", "gbm_quant", "median"]
    buckets = {n: {"err": [], "cov": [], "width": []} for n in names}

    for i in range(MIN_TRAIN, len(rows)):
        train, test = rows[:i], rows[i]
        actual = test["actual_days"]
        x_test = np.array([x_of(test)], dtype=float)

        # 1) deployed method (OOF residuals + tail widening)
        model = train_model(train)
        record(estimate(model, test["features"]), actual, buckets["ridge_style"])

        # split the training window into fit / calibration (chronological)
        n_cal = max(2, int(round(CALIB_FRACTION * len(train))))
        fit, cal = train[:-n_cal], train[-n_cal:]
        x_fit = np.array([x_of(r) for r in fit], dtype=float)
        y_fit_log = np.log(np.array([r["actual_days"] for r in fit], dtype=float))
        x_cal = np.array([x_of(r) for r in cal], dtype=float)
        y_cal_log = np.log(np.array([r["actual_days"] for r in cal], dtype=float))

        # 2) Ridge + true split conformal
        ridge = Ridge(alpha=0.3)
        ridge.fit(x_fit, y_fit_log)
        pred_cal = ridge.predict(x_cal)
        lo, hi = conformal_quantiles(y_cal_log - pred_cal)
        pred_log = float(ridge.predict(x_test)[0])
        record(
            {"p10": float(np.exp(pred_log + lo)), "p50": float(np.exp(pred_log)),
             "p90": float(np.exp(pred_log + hi))},
            actual, buckets["ridge_split"],
        )

        # 3) HistGradientBoosting + split conformal
        gbm = HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, max_depth=3, random_state=42
        )
        gbm.fit(x_fit, y_fit_log)
        pred_cal = gbm.predict(x_cal)
        lo, hi = conformal_quantiles(y_cal_log - pred_cal)
        pred_log = float(gbm.predict(x_test)[0])
        record(
            {"p10": float(np.exp(pred_log + lo)), "p50": float(np.exp(pred_log)),
             "p90": float(np.exp(pred_log + hi))},
            actual, buckets["gbm_split"],
        )

        # 4) gradient-boosted quantile regression (no conformal)
        qpreds = {}
        for alpha in (0.1, 0.5, 0.9):
            q = GradientBoostingRegressor(
                loss="quantile", alpha=alpha, n_estimators=200, max_depth=2,
                learning_rate=0.05, random_state=42,
            )
            q.fit(x_fit, y_fit_log)
            qpreds[alpha] = float(q.predict(x_test)[0])
        record(
            {
                "p10": float(np.exp(qpreds[0.1])),
                "p50": float(np.exp(qpreds[0.5])),
                "p90": float(np.exp(qpreds[0.9])),
            },
            actual, buckets["gbm_quant"],
        )

        # 5) constant median with empirical 10/90 quantiles
        med_log = float(np.median(y_fit_log))
        lo, hi = conformal_quantiles(y_fit_log - med_log)
        record(
            {"p10": float(np.exp(med_log + lo)), "p50": float(np.exp(med_log)),
             "p90": float(np.exp(med_log + hi))},
            actual, buckets["median"],
        )

    print(f"steps={max(0, len(rows) - MIN_TRAIN)}")
    print(f"{'method':12s} {'MAE':>8s} {'coverage':>9s} {'rel.width':>10s}")
    summary = {}
    for name in names:
        b = buckets[name]
        if not b["err"]:
            continue
        summary[name] = {
            "mae": round(float(np.mean(b["err"])), 2),
            "coverage_pct": round(100.0 * float(np.mean(b["cov"])), 1),
            "rel_width": round(float(np.mean(b["width"])), 2),
        }
        print(
            f"{name:12s} {summary[name]['mae']:8.2f} "
            f"{summary[name]['coverage_pct']:8.1f}% "
            f"{summary[name]['rel_width']:10.2f}"
        )

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "steps": max(0, len(rows) - MIN_TRAIN),
        "results": summary,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
