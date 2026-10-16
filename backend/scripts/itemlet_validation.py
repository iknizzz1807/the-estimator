"""Itemlet project-level validation (see docs/ITEMLET_VALIDATION.md).

The product's estimation math (``backend/app/services/estimation.py``) is:
Ridge(alpha=0.3) on ``log(target)`` + split-conformal residual quantiles at
0.1 / 0.5 / 0.9 with the x1.10 tail widening and the 3.0 floor.

That math is written for the product's 15 *binary* RFP features, so this
script is a small, generic, clearly-documented **mirror** of the same math for
continuous project-level features (``train_model`` is NOT reused — it hardcodes
the 15 binary columns, docs/API.md row contract):

* same ``Ridge(alpha=0.3)`` on the ``log(hours)`` target;
* same out-of-fold conformal residual quantiles
  (``_residual_quantiles`` copied verbatim: finite-sample correction with
  ``method="higher"``, then x1.10 tail widening about the median);
* same floor / rounding / ordering of the ``[P10, P50, P90]`` output
  (``_finish`` mirror, ``MIN_HOURS = 3.0`` — a no-op at project scale);
* ONE documented adaptation: continuous features are z-scored with
  **train-fold** statistics inside the pipeline (binary 0/1 features never
  needed scaling; here scales differ by orders of magnitude, which would make
  alpha=0.3 meaningless without scaling). The scaler is fit on train folds
  only — no leakage.

Data: **Itemlet** (Zenodo 10.5281/zenodo.19411554, CC-BY-4.0) — 727,282 Jira
issues from 204 open-source projects; target = ``sum("Total Time Logged
(hours)")`` per project (absolute effort). The committed subset
``data/itemlet_projects.csv`` is derived by ``--build`` from the cached Zenodo
files (see ``data/itemlet_README.txt``).

Usage (from ``backend/`` with ``PYTHONPATH=.``):

    /root/venvs/estimator/bin/python scripts/itemlet_validation.py            # validate committed CSV
    /root/venvs/estimator/bin/python scripts/itemlet_validation.py --build    # rebuild subset from /root/itemlet_cache
    /root/venvs/estimator/bin/python scripts/itemlet_validation.py --self-test

Determinism: fixed seeds, no shuffling inside the conformal step; same CSV in
-> byte-identical tables out.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import GroupKFold, KFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# --------------------------------------------------------------------------- #
# Constants mirrored from app/services/estimation.py
# --------------------------------------------------------------------------- #

RIDGE_ALPHA = 0.3  # estimation.RIDGE_ALPHA
RESIDUAL_TAIL_WIDENING = 1.10  # estimation.RESIDUAL_TAIL_WIDENING
MIN_HOURS = 3.0  # estimation.MIN_DAYS, kept for faithfulness (no-op at project scale)
QUANTILE_LEVELS = (0.1, 0.5, 0.9)  # estimation.QUANTILE_LEVELS
FALLBACK_RESIDUAL_QUANTILES = {"q10": -0.55, "q50": 0.0, "q90": 0.55}
MIN_ROWS_CONFORMAL = 10

SEED = 42
N_FOLDS = 5
HOURS_PER_DAY = 8  # conversion only, clearly labeled in the report (not a claim)

DEFAULT_CACHE = Path("/root/itemlet_cache")
REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSET_PATH = REPO_ROOT / "data" / "itemlet_projects.csv"

#: Honest project-level feature set (deterministic aggregates; documented in
#: docs/ITEMLET_VALIDATION.md). Deliberately EXCLUDES any aggregate of
#: ``Total Time Logged`` (mean/median per-issue logged time would mechanically
#: reconstruct the target: sum = n_logged x mean_logged -> leakage, shown as a
#: separate labeled diagnostic instead).
FEATURE_NAMES: list[str] = [
    "log_issue_count",  # log1p(issue_count) — scope-size proxy
    "story_point_coverage_pct",  # share of issues with story points
    "median_story_points",  # median SP over estimated issues
    "resolved_share",  # resolved_count / issue_count
    "log_sprint_count",  # log1p(sprint_count)
    "has_sprint_data",  # 0/1 from project_summary
    "log_median_cycle_time_h",  # log1p(median cycle time hours) — heavy tail
    "log_span_months",  # log1p(active months from first to last issue)
    "bug_share",  # share of issues with issuetype Bug
    "story_share",  # share of issues with issuetype Story
    "log_mean_total_days",  # log1p(mean Total Days) — heavy tail
    "assignees_per_100_issues",  # distinct assignee accounts / issues * 100
    "log_mean_comment_count",  # log1p(mean comments per issue) — heavy tail
    "has_technical_terms_share",  # share of issues w/ technical lexicon terms
    "high_priority_share",  # share of High/Highest priority issues
]

#: Leakage diagnostic only (NOT a fair test): the target's own components.
#: log(sum) == log(n_logged) + log(mean_hours_per_issue_logged) exactly, so a
#: model given these two can reconstruct the target — that is the point of the
#: diagnostic: it proves the pipeline learns when a real signal exists.
LEAKY_FEATURE_NAMES: list[str] = ["log_n_issues_logged", "log_mean_hours_per_issue_logged"]


# --------------------------------------------------------------------------- #
# Generic mirror of the estimation math
# --------------------------------------------------------------------------- #


def _residual_quantiles(residuals: np.ndarray) -> dict[str, float]:
    """Copied verbatim from app/services/estimation.py:_residual_quantiles."""
    n = len(residuals)
    out: dict[str, float] = {}
    for key, q in zip(("q10", "q50", "q90"), QUANTILE_LEVELS):
        q_adjusted = min(1.0, q * (n + 1) / n)
        out[key] = float(np.quantile(residuals, q_adjusted, method="higher"))
    ordered = sorted(out.values())
    q10, q50, q90 = ordered
    return {
        "q10": q50 - (q50 - q10) * RESIDUAL_TAIL_WIDENING,
        "q50": q50,
        "q90": q50 + (q90 - q50) * RESIDUAL_TAIL_WIDENING,
    }


def _new_pipeline() -> Pipeline:
    """StandardScaler -> Ridge(alpha=0.3); the documented adaptation."""
    return Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=RIDGE_ALPHA))])


def fit_math(
    train_rows: list[dict], feature_names: list[str]
) -> tuple[Pipeline, dict[str, float], int]:
    """Train log(hours) ~ Ridge(alpha=0.3) + OOF conformal residual quantiles."""
    x = np.array(
        [[row["features"][name] for name in feature_names] for row in train_rows],
        dtype=float,
    )
    y = np.log(np.array([row["target_hours"] for row in train_rows], dtype=float))
    model = _new_pipeline()
    model.fit(x, y)
    n = len(train_rows)
    if n >= MIN_ROWS_CONFORMAL:
        folds = KFold(n_splits=min(5, n), shuffle=False)  # deterministic split
        oof = cross_val_predict(_new_pipeline(), x, y, cv=folds)
        quantiles = _residual_quantiles(y - oof)
    else:
        quantiles = dict(FALLBACK_RESIDUAL_QUANTILES)
    return model, quantiles, n


def _finish(p10: float, p50: float, p90: float) -> tuple[float, float, float]:
    """Mirror of estimation._finish (floor, round, order)."""
    p10 = max(MIN_HOURS, round(p10, 1))
    p50 = max(MIN_HOURS, round(p50, 1))
    p90 = max(MIN_HOURS, round(p90, 1))
    return tuple(sorted((p10, p50, p90)))  # type: ignore[return-value]


def predict_interval(
    model: Pipeline, quantiles: dict[str, float], x_row: np.ndarray
) -> tuple[float, float, float]:
    """exp(log_pred + residual quantiles), floor/round/order as in the product."""
    log_pred = float(model.predict(x_row.reshape(1, -1))[0])
    p10 = math.exp(log_pred + quantiles["q10"])
    p50 = math.exp(log_pred + quantiles["q50"])
    p90 = math.exp(log_pred + quantiles["q90"])
    return _finish(p10, p50, p90)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


def evaluate(
    train_rows: list[dict], test_rows: list[dict], feature_names: list[str]
) -> dict:
    """Fit on train rows, score P50 / [P10, P90] on test rows (hours space)."""
    model, quantiles, n_train = fit_math(train_rows, feature_names)
    y_true = np.array([row["target_hours"] for row in test_rows], dtype=float)
    p10, p50, p90 = [], [], []
    for row in test_rows:
        x_row = np.array([row["features"][name] for name in feature_names], dtype=float)
        lo, mid, hi = predict_interval(model, quantiles, x_row)
        p10.append(lo)
        p50.append(mid)
        p90.append(hi)
    p10, p50, p90 = np.array(p10), np.array(p50), np.array(p90)

    train_y = np.array([row["target_hours"] for row in train_rows], dtype=float)
    base_mean = np.full_like(y_true, float(train_y.mean()))
    base_median = np.full_like(y_true, float(np.median(train_y)))

    # Per-domain train mean; unseen test domains fall back to the global mean.
    by_domain: dict[str, list[float]] = {}
    for row in train_rows:
        by_domain.setdefault(row["domain"], []).append(row["target_hours"])
    domain_mean = {d: float(np.mean(v)) for d, v in by_domain.items()}
    global_mean = float(train_y.mean())
    base_domain = np.array(
        [domain_mean.get(row["domain"], global_mean) for row in test_rows], dtype=float
    )
    unseen_domain_share = float(
        np.mean([row["domain"] not in domain_mean for row in test_rows])
    )

    log_true = np.log(y_true)
    log_pred = np.log(np.maximum(p50, 1e-9))
    return {
        "n_train": n_train,
        "n_test": len(test_rows),
        "mae": float(mean_absolute_error(y_true, p50)),
        "mae_days": float(mean_absolute_error(y_true, p50) / HOURS_PER_DAY),
        "rmse": float(root_mean_squared_error(y_true, p50)),
        "r2": float(r2_score(y_true, p50)) if len(y_true) > 1 else float("nan"),
        "r2_log": float(r2_score(log_true, log_pred)) if len(y_true) > 1 else float("nan"),
        "coverage": float(np.mean((y_true >= p10) & (y_true <= p90))),
        "median_ae": float(np.median(np.abs(y_true - p50))),
        "baseline_mean_mae": float(mean_absolute_error(y_true, base_mean)),
        "baseline_median_mae": float(mean_absolute_error(y_true, base_median)),
        "baseline_domain_mae": float(mean_absolute_error(y_true, base_domain)),
        "unseen_domain_share": unseen_domain_share,
        "y_true": y_true,
        "p50": p50,
        "p10": p10,
        "p90": p90,
        "base_mean": base_mean,
        "base_median": base_median,
        "base_domain": base_domain,
    }


def aggregate(results: list[dict]) -> dict:
    """Pool all test predictions of a split and compute the same metrics."""
    y_true = np.concatenate([r["y_true"] for r in results])
    p50 = np.concatenate([r["p50"] for r in results])
    p10 = np.concatenate([r["p10"] for r in results])
    p90 = np.concatenate([r["p90"] for r in results])
    base_mean = np.concatenate([r["base_mean"] for r in results])
    base_median = np.concatenate([r["base_median"] for r in results])
    base_domain = np.concatenate([r["base_domain"] for r in results])
    log_true = np.log(y_true)
    log_pred = np.log(np.maximum(p50, 1e-9))
    return {
        "n_train": sum(r["n_train"] for r in results),
        "n_test": len(y_true),
        "mae": float(mean_absolute_error(y_true, p50)),
        "mae_days": float(mean_absolute_error(y_true, p50) / HOURS_PER_DAY),
        "rmse": float(root_mean_squared_error(y_true, p50)),
        "r2": float(r2_score(y_true, p50)),
        "r2_log": float(r2_score(log_true, log_pred)),
        "coverage": float(np.mean((y_true >= p10) & (y_true <= p90))),
        "median_ae": float(np.median(np.abs(y_true - p50))),
        "baseline_mean_mae": float(mean_absolute_error(y_true, base_mean)),
        "baseline_median_mae": float(mean_absolute_error(y_true, base_median)),
        "baseline_domain_mae": float(mean_absolute_error(y_true, base_domain)),
        "unseen_domain_share": float(np.mean([r["unseen_domain_share"] for r in results])),
    }


def random_cv_folds(rows: list[dict], n_folds: int = N_FOLDS, seed: int = SEED) -> list:
    """Deterministic seeded shuffle -> contiguous folds (as in tawos_validation)."""
    rng = np.random.RandomState(seed)
    order = rng.permutation(len(rows))
    chunks = np.array_split(order, n_folds)
    return [
        (
            [rows[i] for i in sorted(set(range(len(rows))) - set(chunk.tolist()))],
            [rows[i] for i in chunk.tolist()],
        )
        for chunk in chunks
    ]


def domain_cv_folds(rows: list[dict], n_folds: int = N_FOLDS) -> list:
    """GroupKFold over domain: whole domains are held out (primary claim)."""
    groups = np.array([row["domain"] for row in rows])
    gkf = GroupKFold(n_splits=n_folds)
    folds = []
    dummy = np.zeros(len(rows))
    for train_idx, test_idx in gkf.split(dummy, groups=groups):
        folds.append(([rows[i] for i in train_idx], [rows[i] for i in test_idx]))
    return folds


def augment(rows: list[dict], extra: dict[str, dict[str, float]]) -> list[dict]:
    """Return rows whose ``features`` dict is extended with ``extra`` per key."""
    return [
        {**row, "features": {**row["features"], **extra.get(row["project_key"], {})}}
        for row in rows
    ]


def load_subset(path: Path) -> tuple[list[dict], int]:
    """Load committed project-level rows; skip zero-logged targets (no target)."""
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Rebuild with --build (see data/itemlet_README.txt)."
        )
    rows: list[dict] = []
    skipped = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        stub_names = [c for c in (reader.fieldnames or []) if c.startswith("stub_")]
        for record in reader:
            hours = float(record["target_hours"])
            if hours <= 0:
                skipped += 1
                continue
            rows.append(
                {
                    "project_key": record["project_key"],
                    "domain": record["domain"],
                    "target_hours": hours,
                    "logging_coverage": float(record["logging_coverage"]),
                    "features": {name: float(record[name]) for name in FEATURE_NAMES},
                    "leaky_features": {
                        name: float(record[name]) for name in LEAKY_FEATURE_NAMES
                    },
                    "stub_features": {name: float(record[name]) for name in stub_names},
                }
            )
    if not rows:
        raise SystemExit(f"No usable rows in {path}")
    return rows, skipped


# --------------------------------------------------------------------------- #
# Subset build (from cached Zenodo files)
# --------------------------------------------------------------------------- #


def _evenly_spaced(part, k: int = 40):
    if len(part) <= k:
        return part
    idx = np.unique(np.linspace(0, len(part) - 1, k).round().astype(int))
    return part.iloc[idx]


def build_subset(cache_dir: Path, out_path: Path) -> None:
    """Aggregate the Itemlet parquet to one honest row per project (n=204)."""
    import pandas as pd

    from app.features import FEATURES
    from app.services.providers import StubProvider

    summary = pd.read_csv(cache_dir / "project_summary.csv")
    domain = pd.read_csv(cache_dir / "project_domain.csv")
    if not summary["domain"].equals(domain["domain"]):
        raise SystemExit("project_summary.domain != project_domain.domain — aborting")
    first = pd.to_datetime(summary["date_first_created"], format="%m/%d/%Y", errors="coerce")
    last = pd.to_datetime(summary["date_last_created"], format="%m/%d/%Y", errors="coerce")
    summary["span_months"] = (last - first).dt.days / 30.44

    pq_cols = [
        "project_key",
        "issue_key",
        "issue_summary",
        "issuetype_name",
        "status_statusCategory_name",
        "Assignee Account ID",
        "Total Time Logged (hours)",
        "priority_name",
        "comment_count",
        "Total Days",
        "has_technical_terms",
    ]
    df = pd.read_parquet(cache_dir / "itemlet_dataset.parquet", columns=pq_cols)
    print(f"parquet rows={len(df)} cols={len(df.columns)}")

    df["logged"] = df["Total Time Logged (hours)"] > 0
    df["is_bug"] = df["issuetype_name"].eq("Bug")
    df["is_story"] = df["issuetype_name"].eq("Story")
    df["is_done"] = df["status_statusCategory_name"].eq("Done")
    df["high_pri"] = df["priority_name"].isin(["Highest", "High"])
    df["has_tech"] = df["has_technical_terms"].astype(float)

    agg = df.groupby("project_key").agg(
        pq_issue_count=("issue_key", "size"),
        total_hours=("Total Time Logged (hours)", "sum"),
        n_issues_logged=("logged", "sum"),
        median_hours_per_issue=("Total Time Logged (hours)", "median"),
        bug_share=("is_bug", "mean"),
        story_share=("is_story", "mean"),
        done_share=("is_done", "mean"),
        high_priority_share=("high_pri", "mean"),
        mean_comment_count=("comment_count", "mean"),
        mean_total_days=("Total Days", "mean"),
        has_technical_terms_share=("has_tech", "mean"),
        distinct_assignees=("Assignee Account ID", "nunique"),
    )

    # Optional text diagnostic: StubProvider prevalence on a deterministic
    # sample of up to 40 issue summaries per project (sorted by issue_key,
    # evenly spaced). Cheap, offline, no LLM calls.
    sample = df[["project_key", "issue_key", "issue_summary"]].dropna(
        subset=["issue_summary"]
    )
    sample = sample.sort_values(["project_key", "issue_key"], kind="stable")
    parts = [
        _evenly_spaced(part[["project_key", "issue_key", "issue_summary"]])
        for _, part in sample.groupby("project_key", sort=True)
    ]
    sampled = pd.concat(parts, ignore_index=True)
    provider = StubProvider()
    stub_rows = []
    for pk, text in zip(sampled["project_key"], sampled["issue_summary"]):
        findings = provider.extract_findings(str(text))
        stub_rows.append(
            {
                "project_key": pk,
                **{
                    f"stub_{n}": 1.0 if findings[n].get("value") == 1 else 0.0
                    for n in FEATURES
                },
            }
        )
    stub_share = pd.DataFrame(stub_rows).groupby("project_key").mean()
    print(f"stub text sample: {len(sampled)} issues ({len(stub_share)} projects)")

    out = summary.merge(agg, left_on="project_key", right_index=True, how="left")
    out = out.merge(stub_share, left_on="project_key", right_index=True, how="left")
    out = out.merge(domain[["project_key", "domain_notes"]], on="project_key", how="left")
    missing = out["pq_issue_count"].isna().sum()
    if missing:
        raise SystemExit(f"{missing} projects missing parquet aggregates — aborting")
    mismatched = int((out["issue_count"] != out["pq_issue_count"]).sum())
    print(f"issue_count cross-check (summary vs parquet): {mismatched} mismatches")

    # Deterministic, documented imputation: overall median for the 1 null
    # cycle time, the 18 null spans (projects without usable date pairs) and
    # the 1 null mean_total_days; stub shares fall back to 0 (no evidence).
    med_cycle = float(out["median_cycle_time_h"].median())
    med_span = float(out["span_months"].median())
    med_days = float(out["mean_total_days"].median())
    out["median_cycle_time_h"] = out["median_cycle_time_h"].fillna(med_cycle)
    out["span_months"] = out["span_months"].fillna(med_span)
    out["mean_total_days"] = out["mean_total_days"].fillna(med_days)
    for col in [c for c in out.columns if c.startswith("stub_")]:
        out[col] = out[col].fillna(0.0)

    out["log_issue_count"] = np.log1p(out["issue_count"])
    out["log_sprint_count"] = np.log1p(out["sprint_count"])
    out["log_span_months"] = np.log1p(out["span_months"])
    out["log_median_cycle_time_h"] = np.log1p(out["median_cycle_time_h"])
    out["log_mean_total_days"] = np.log1p(out["mean_total_days"])
    out["log_mean_comment_count"] = np.log1p(out["mean_comment_count"])
    out["assignees_per_100_issues"] = out["distinct_assignees"] / out["issue_count"] * 100.0
    out["resolved_share"] = out["resolved_count"] / out["issue_count"]
    # Leaky pair (diagnostic only): log(total) == log(n_logged) + log(mean_logged).
    out["log_n_issues_logged"] = np.log(out["n_issues_logged"].clip(lower=1))
    out["log_mean_hours_per_issue_logged"] = np.log(
        (out["total_hours"] / out["n_issues_logged"].clip(lower=1)).clip(lower=1e-9)
    )
    out["logging_coverage"] = out["n_issues_logged"] / out["issue_count"]
    out["target_hours"] = out["total_hours"]
    out["target_person_days"] = out["target_hours"] / HOURS_PER_DAY
    assert not out[FEATURE_NAMES + LEAKY_FEATURE_NAMES].isna().any().any()

    # All 204 projects are kept in the CSV (full transparency). The validation
    # loads only target_hours > 0 rows: a project with zero logged time has no
    # absolute-effort target (mirrors the product's actual_days > 0 rule).
    n_zero = int((out["target_hours"] <= 0).sum())
    print(f"projects with zero logged time: {n_zero} / {len(out)} (kept in CSV, "
          f"skipped by validation)")

    columns = (
        ["project_key", "project_name", "domain", "target_hours", "target_person_days"]
        + ["issue_count", "resolved_count", "n_issues_logged", "logging_coverage",
           "median_hours_per_issue", "sprint_count", "span_months",
           "median_cycle_time_h", "mean_total_days", "mean_comment_count"]
        + FEATURE_NAMES
        + LEAKY_FEATURE_NAMES
        + [c for c in out.columns if c.startswith("stub_")]
        + ["distinct_assignees", "done_share", "domain_notes"]
    )
    out = out.sort_values("project_key").reset_index(drop=True)
    out = out[columns]
    assert not out.columns.duplicated().any()
    for col in out.columns:
        if out[col].dtype.kind == "f":
            out[col] = out[col].round(4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} rows={len(out)} cols={len(out.columns)}")


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #


def self_test() -> int:
    """Embedded rows: math runs, quantiles ordered, widening x1.10, deterministic."""
    rows = [
        {
            "project_key": f"P{i:02d}",
            "domain": "A" if i < 8 else "B",
            "target_hours": float(10 + 5 * i + (i % 3) * 7),
            "features": {
                name: float((i + j) % 4 == 0) for j, name in enumerate(FEATURE_NAMES)
            },
        }
        for i in range(12)
    ]
    model1, q1, n1 = fit_math(rows, FEATURE_NAMES)
    model2, q2, n2 = fit_math(rows, FEATURE_NAMES)
    ok = n1 == n2 == 12 and q1 == q2
    ok = ok and q1["q10"] <= q1["q50"] <= q1["q90"]
    x = np.array([rows[0]["features"][name] for name in FEATURE_NAMES], dtype=float)
    p1 = predict_interval(model1, q1, x)
    p2 = predict_interval(model2, q2, x)
    ok = ok and p1 == p2 and p1[0] <= p1[1] <= p1[2]

    folds = random_cv_folds(rows)
    ok = ok and len(folds) == N_FOLDS and sum(len(te) for _, te in folds) == 12
    for train, test in domain_cv_folds(rows, n_folds=2):
        ok = ok and not ({r["domain"] for r in train} & {r["domain"] for r in test})

    # Exact widening check on raw residuals.
    raw = np.array([-0.5, -0.2, 0.0, 0.1, 0.4])
    q = _residual_quantiles(raw)
    n = len(raw)
    raw_q = [
        float(np.quantile(raw, min(1.0, lvl * (n + 1) / n), method="higher"))
        for lvl in QUANTILE_LEVELS
    ]
    r10, r50, r90 = sorted(raw_q)
    ok = ok and math.isclose(q["q10"], r50 - (r50 - r10) * RESIDUAL_TAIL_WIDENING)
    ok = ok and math.isclose(q["q50"], r50)
    ok = ok and math.isclose(q["q90"], r50 + (r90 - r50) * RESIDUAL_TAIL_WIDENING)

    # Fold determinism: two shuffles with the same seed are identical.
    a = [te[0]["project_key"] for _, te in random_cv_folds(rows)]
    b = [te[0]["project_key"] for _, te in random_cv_folds(rows)]
    ok = ok and a == b

    print(f"self-test: {'PASS' if ok else 'FAIL'} (n={n1}, q={q1})")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def print_table(title: str, results: list[dict]) -> None:
    print(f"\n{title}")
    header = (
        f"  {'fold':>4} {'n_train':>7} {'n_test':>6} {'MAE_h':>9} {'MAE_d':>7} "
        f"{'RMSE_h':>9} {'R2':>7} {'R2log':>7} {'cov':>6} "
        f"{'bMean':>9} {'bMed':>9} {'bDom':>9}"
    )
    print(header)
    for i, res in enumerate(results):
        print(
            f"  {i + 1:>4} {res['n_train']:>7} {res['n_test']:>6} {fmt(res['mae'], 1):>9} "
            f"{fmt(res['mae_days'], 2):>7} {fmt(res['rmse'], 1):>9} {fmt(res['r2']):>7} "
            f"{fmt(res['r2_log']):>7} {fmt(res['coverage']):>6} "
            f"{fmt(res['baseline_mean_mae'], 1):>9} {fmt(res['baseline_median_mae'], 1):>9} "
            f"{fmt(res['baseline_domain_mae'], 1):>9}"
        )


def print_aggregate(label: str, agg: dict) -> None:
    print(
        f"   {label}: MAE={fmt(agg['mae'], 1)}h ({fmt(agg['mae_days'], 2)} p-d @8h) "
        f"RMSE={fmt(agg['rmse'], 1)}h R2={fmt(agg['r2'])} R2log={fmt(agg['r2_log'])} "
        f"cov={fmt(agg['coverage'])} median|err|={fmt(agg['median_ae'], 1)}h"
    )
    print(
        f"   baselines: global mean MAE={fmt(agg['baseline_mean_mae'], 1)}h, "
        f"global median MAE={fmt(agg['baseline_median_mae'], 1)}h, "
        f"per-domain mean MAE={fmt(agg['baseline_domain_mae'], 1)}h "
        f"(unseen-domain share {fmt(agg['unseen_domain_share'] * 100, 1)}%)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="rebuild subset from cache")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        raise SystemExit(self_test())
    if args.build:
        build_subset(args.cache_dir, SUBSET_PATH)
        return

    import sklearn

    print("=== Itemlet project-level validation (The Estimator) ===")
    print(f"subset: {SUBSET_PATH.relative_to(REPO_ROOT)}")
    print(f"deps: numpy {np.__version__}, scikit-learn {sklearn.__version__}")
    print(
        "math mirror: Ridge(alpha=0.3) on log(hours) + OOF conformal quantiles "
        "(x1.10 tail widening), z-scored features (train folds only)"
    )

    rows, skipped = load_subset(SUBSET_PATH)
    y = np.array([row["target_hours"] for row in rows])
    domains = sorted({row["domain"] for row in rows})
    print(
        f"\nprojects={len(rows)} usable (skipped {skipped} with zero logged time) "
        f"domains={len(domains)}"
    )
    print(
        f"target hours: min={fmt(y.min(), 1)} p25={fmt(float(np.quantile(y, 0.25)), 1)} "
        f"median={fmt(float(np.median(y)), 1)} p75={fmt(float(np.quantile(y, 0.75)), 1)} "
        f"p90={fmt(float(np.quantile(y, 0.9)), 1)} max={fmt(y.max(), 1)} mean={fmt(y.mean(), 1)}"
    )
    print(
        f"target person-days (x/8, conversion only): median="
        f"{fmt(float(np.median(y)) / HOURS_PER_DAY, 1)} max={fmt(y.max() / HOURS_PER_DAY, 1)}"
    )
    sizes = [len({row["domain"] for row in te}) for _, te in domain_cv_folds(rows)]
    print(f"domain-holdout folds hold out {sizes} domains respectively")

    print("\n1. Random 5-fold CV (seeded shuffle, seed=42)")
    cv_results = [evaluate(tr, te, FEATURE_NAMES) for tr, te in random_cv_folds(rows)]
    print_table("   per fold:", cv_results)
    print_aggregate("AGGREGATE", aggregate(cv_results))

    print("\n2. Domain-holdout GroupKFold(5) — primary generalization test")
    dh_results = [evaluate(tr, te, FEATURE_NAMES) for tr, te in domain_cv_folds(rows)]
    print_table("   per fold:", dh_results)
    print_aggregate("AGGREGATE", aggregate(dh_results))

    print("\n3. Sensitivity: logging-coverage filter (target validity)")
    print("   (total logged hours is a weak proxy when few issues are logged;")
    print("    coverage = share of the project's issues with any logged time)")
    for threshold in (0.05, 0.10):
        sub = [r for r in rows if r["logging_coverage"] >= threshold]
        n_domains = len({r["domain"] for r in sub})
        cv = [evaluate(tr, te, FEATURE_NAMES) for tr, te in random_cv_folds(sub)]
        if n_domains >= N_FOLDS:
            dh = [evaluate(tr, te, FEATURE_NAMES) for tr, te in domain_cv_folds(sub)]
            agg_dh = aggregate(dh)
            dh_text = (
                f"MAE={fmt(agg_dh['mae'], 1)}h R2={fmt(agg_dh['r2'])} "
                f"R2log={fmt(agg_dh['r2_log'])} cov={fmt(agg_dh['coverage'])}"
            )
        else:
            dh_text = f"skipped ({n_domains} domains < 5)"
        agg_cv = aggregate(cv)
        print(
            f"   coverage>={threshold:.0%}: n={len(sub)} | random CV: "
            f"MAE={fmt(agg_cv['mae'], 1)}h R2={fmt(agg_cv['r2'])} R2log={fmt(agg_cv['r2_log'])} "
            f"cov={fmt(agg_cv['coverage'])} | domain-holdout: {dh_text}"
        )
        print(
            f"      baselines (random CV): global mean MAE={fmt(agg_cv['baseline_mean_mae'], 1)}h, "
            f"global median MAE={fmt(agg_cv['baseline_median_mae'], 1)}h, "
            f"per-domain mean MAE={fmt(agg_cv['baseline_domain_mae'], 1)}h"
        )

    print("\n4. Leakage diagnostic (NOT a fair test; target components as features)")
    leaky_rows = augment(rows, {r["project_key"]: r["leaky_features"] for r in rows})
    leaky_cv = [
        evaluate(tr, te, FEATURE_NAMES + LEAKY_FEATURE_NAMES)
        for tr, te in random_cv_folds(leaky_rows)
    ]
    print_aggregate("leaky random CV", aggregate(leaky_cv))

    print("\n5. Text diagnostic: StubProvider shares on sampled issue summaries")
    print("   Spearman rho vs log(target); |rho| >= 0.25 would be worth a model test")
    from scipy.stats import spearmanr

    log_y = np.log(y)
    stub_names = sorted(rows[0]["stub_features"])
    max_abs_rho, max_rho_name = 0.0, None
    for name in stub_names:
        vals = np.array([r["stub_features"][name] for r in rows])
        share = float(vals.mean())
        if float(vals.std()) == 0.0:
            print(f"   {name:<28} share={fmt(share, 4)}  constant — no signal")
            continue
        rho, p_value = spearmanr(vals, log_y)
        print(
            f"   {name:<28} share={fmt(share, 4)}  rho={rho:+.3f} p={p_value:.3f}"
        )
        if abs(rho) > max_abs_rho:
            max_abs_rho, max_rho_name = abs(rho), name
    print(
        f"   strongest |rho| = {fmt(max_abs_rho)} ({max_rho_name}) -> "
        f"{'below' if max_abs_rho < 0.25 else 'ABOVE'} the 0.25 bar; "
        f"{'not added to the model' if max_abs_rho < 0.25 else 'exploratory only'}"
    )

    print("\ndone.")


if __name__ == "__main__":
    main()
