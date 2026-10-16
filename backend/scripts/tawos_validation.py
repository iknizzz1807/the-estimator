"""TAWOS cross-dataset validation experiment (bonus, see docs/TAWOS_VALIDATION.md).

Loads the committed subset ``data/tawos_subset.csv`` (real Jira user stories with
story-point labels from the TAWOS dataset), extracts the 15 canonical features
with the offline :class:`~app.services.providers.StubProvider`, and runs the
product's estimation math unchanged (:mod:`app.services.estimation`:
Ridge on log(actual_days) + split-conformal residual quantiles) with the story
points passed in as ``actual_days``. Story points are unit-agnostic here: the
model works on log(target), so only the *unit label* on the numbers changes.

What it prints (all deterministic, no network, no server):

1. per-feature prevalence of the 15 features on the subset;
2. random 5-fold CV metrics: MAE / RMSE (story points), R^2 (story-point space),
   empirical coverage of the [P10, P90] interval;
3. cross-project GroupKFold metrics (primary cross-dataset claim: train on 80%
   of projects, test on unseen projects) plus global mean / median baselines;
4. the same two evaluations for a "TAWOS-adapted" variant that only uses the
   features that fire in >= 3% of rows (docs/SPEC.md 5.5 allows 10 features
   when TAWOS has no compliance information).

Run from ``backend/`` with ``PYTHONPATH=.`` and the project venv:

    /root/venvs/estimator/bin/python scripts/tawos_validation.py

Determinism: fixed seed for the random split, ``KFold(shuffle=False)`` inside
``train_model``; same CSV in -> byte-identical tables out.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import GroupKFold

from app.features import FEATURES
from app.services.estimation import MIN_DAYS, estimate, train_model
from app.services.providers import StubProvider

SEED = 42
N_FOLDS = 5
PREVALENCE_THRESHOLD = 0.03  # "fires in >= 3% of rows" (spec 5.5 adaptation)
SUBSET_PATH = Path(__file__).resolve().parents[2] / "data" / "tawos_subset.csv"


def load_subset(path: Path) -> list[dict]:
    """Load the experiment rows (story_id, project_id, description, story_points)."""
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. See data/tawos_README.txt for provenance/extraction."
        )
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            sp = float(record["story_points"])
            if sp <= 0 or not record["description"].strip():
                continue
            rows.append(
                {
                    "story_id": record["story_id"],
                    "project_id": record["project_id"],
                    "description": record["description"],
                    "story_points": sp,
                }
            )
    if not rows:
        raise SystemExit(f"No usable rows in {path}")
    return rows


def extract_features(rows: list[dict]) -> None:
    """Attach StubProvider findings: binary features (value 1 -> 1.0, else 0.0)."""
    provider = StubProvider()
    for row in rows:
        findings = provider.extract_findings(row["description"])
        row["features"] = {
            name: 1.0 if findings[name].get("value") == 1 else 0.0 for name in FEATURES
        }


def prevalence(rows: list[dict]) -> dict[str, float]:
    n = len(rows)
    return {
        name: sum(1 for row in rows if row["features"][name] > 0) / n for name in FEATURES
    }


def evaluate(train_rows: list[dict], test_rows: list[dict], feature_names: list[str]) -> dict:
    """Train on log(story_points) and score P50/P10/P90 in story-point space.

    ``feature_names`` restricts the feature dicts handed to the estimator: a
    feature dropped here enters the vector as a constant 0 (no information),
    which is equivalent to excluding its column from the Ridge fit.
    """
    fit_rows = [
        {
            "features": {name: row["features"][name] for name in feature_names},
            "actual_days": row["story_points"],
        }
        for row in train_rows
    ]
    model = train_model(fit_rows)
    y_true = np.array([row["story_points"] for row in test_rows], dtype=float)
    p10, p50, p90 = [], [], []
    x_test = np.array(
        [
            [
                (row["features"][name] if name in feature_names else 0.0)
                for name in FEATURES
            ]
            for row in test_rows
        ],
        dtype=float,
    )
    for row in test_rows:
        feats = {name: row["features"][name] for name in feature_names}
        out = estimate(model, feats)
        p10.append(out["p10"])
        p50.append(out["p50"])
        p90.append(out["p90"])
    p10, p50, p90 = np.array(p10), np.array(p50), np.array(p90)
    # Diagnostic only: same conformal outputs before the MIN_DAYS=3.0 person-day
    # floor + 0.1 rounding (that floor is a product decision tuned for days).
    log_pred = model.model.predict(x_test)
    q = model.residual_quantiles
    p10u = np.exp(log_pred + q["q10"])
    p50u = np.exp(log_pred + q["q50"])
    p90u = np.exp(log_pred + q["q90"])
    # Baselines: global mean / median of the *train* story points, same test rows.
    train_y = np.array([row["story_points"] for row in train_rows], dtype=float)
    base_mean = np.full_like(y_true, float(train_y.mean()))
    base_median = np.full_like(y_true, float(np.median(train_y)))
    return {
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "mae": float(mean_absolute_error(y_true, p50)),
        "rmse": float(root_mean_squared_error(y_true, p50)),
        "r2": float(r2_score(y_true, p50)) if len(y_true) > 1 else float("nan"),
        "coverage": float(np.mean((y_true >= p10) & (y_true <= p90))),
        "median_ae": float(np.median(np.abs(y_true - p50))),
        "baseline_mean_mae": float(mean_absolute_error(y_true, base_mean)),
        "baseline_mean_rmse": float(root_mean_squared_error(y_true, base_mean)),
        "baseline_median_mae": float(mean_absolute_error(y_true, base_median)),
        "baseline_median_rmse": float(root_mean_squared_error(y_true, base_median)),
        "y_true": y_true,
        "p50": p50,
        "p10": p10,
        "p90": p90,
        "p50u": p50u,
        "p10u": p10u,
        "p90u": p90u,
        "base_mean": base_mean,
        "base_median": base_median,
    }


def aggregate(results: list[dict]) -> dict:
    """Pool all test predictions of a split and compute the same metrics."""
    y_true = np.concatenate([r["y_true"] for r in results])
    p50 = np.concatenate([r["p50"] for r in results])
    p10 = np.concatenate([r["p10"] for r in results])
    p90 = np.concatenate([r["p90"] for r in results])
    p50u = np.concatenate([r["p50u"] for r in results])
    p10u = np.concatenate([r["p10u"] for r in results])
    p90u = np.concatenate([r["p90u"] for r in results])
    base_mean = np.concatenate([r["base_mean"] for r in results])
    base_median = np.concatenate([r["base_median"] for r in results])
    return {
        "n_train": sum(r["n_train"] for r in results),
        "n_test": len(y_true),
        "mae": float(mean_absolute_error(y_true, p50)),
        "rmse": float(root_mean_squared_error(y_true, p50)),
        "r2": float(r2_score(y_true, p50)),
        "coverage": float(np.mean((y_true >= p10) & (y_true <= p90))),
        "median_ae": float(np.median(np.abs(y_true - p50))),
        "baseline_mean_mae": float(mean_absolute_error(y_true, base_mean)),
        "baseline_mean_rmse": float(root_mean_squared_error(y_true, base_mean)),
        "baseline_median_mae": float(mean_absolute_error(y_true, base_median)),
        "baseline_median_rmse": float(root_mean_squared_error(y_true, base_median)),
        "floor_binding": float(np.mean(p50u < MIN_DAYS)),
        "mae_unfloored": float(mean_absolute_error(y_true, p50u)),
        "r2_unfloored": float(r2_score(y_true, p50u)),
        "coverage_unfloored": float(np.mean((y_true >= p10u) & (y_true <= p90u))),
    }


def random_cv_folds(rows: list[dict], n_folds: int = N_FOLDS, seed: int = SEED) -> list[tuple[list, list]]:
    """Deterministic seeded shuffle -> contiguous folds (reproducible everywhere)."""
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


def project_cv_folds(rows: list[dict], n_folds: int = N_FOLDS) -> list[tuple[list, list]]:
    """GroupKFold over project_id: test projects are never seen in training."""
    groups = np.array([row["project_id"] for row in rows])
    gkf = GroupKFold(n_splits=n_folds)
    folds = []
    dummy_x = np.zeros(len(rows))
    for train_idx, test_idx in gkf.split(dummy_x, groups=groups):
        folds.append(([rows[i] for i in train_idx], [rows[i] for i in test_idx]))
    return folds


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def print_table(title: str, results: list[dict]) -> None:
    print(f"\n{title}")
    header = f"  {'fold':>4} {'n_train':>7} {'n_test':>6} {'MAE':>7} {'RMSE':>7} {'R2':>7} {'cov':>6} {'baseMeanMAE':>11} {'baseMedMAE':>10}"
    print(header)
    for i, res in enumerate(results):
        print(
            f"  {i + 1:>4} {res['n_train']:>7} {res['n_test']:>6} {fmt(res['mae']):>7} "
            f"{fmt(res['rmse']):>7} {fmt(res['r2']):>7} {fmt(res['coverage']):>6} "
            f"{fmt(res['baseline_mean_mae']):>11} {fmt(res['baseline_median_mae']):>10}"
        )


def main() -> None:
    import sklearn

    print("=== TAWOS cross-dataset validation (The Estimator) ===")
    try:
        shown_path = SUBSET_PATH.relative_to(SUBSET_PATH.parents[1])
    except ValueError:  # pragma: no cover - path layout differs
        shown_path = SUBSET_PATH
    print(f"subsets: {shown_path}")
    print(f"deps: numpy {np.__version__}, scikit-learn {sklearn.__version__}")
    rows = load_subset(SUBSET_PATH)
    extract_features(rows)

    n_projects = len({row["project_id"] for row in rows})
    sp = np.array([row["story_points"] for row in rows])
    print(
        f"rows={len(rows)} projects={n_projects} story_points: mean={fmt(sp.mean(), 2)} "
        f"median={fmt(float(np.median(sp)), 1)} max={fmt(sp.max(), 1)}"
    )

    prev = prevalence(rows)
    firing_rows = sum(1 for row in rows if any(v > 0 for v in row["features"].values()))
    print(f"\n1. StubProvider feature prevalence on TAWOS subset (n={len(rows)})")
    print(f"  {'feature':<26} {'count':>6} {'prevalence':>10}")
    for name in FEATURES:
        count = int(round(prev[name] * len(rows)))
        print(f"  {name:<26} {count:>6} {fmt(prev[name] * 100, 2):>9}%")
    print(f"  rows with >=1 feature: {firing_rows} ({fmt(firing_rows / len(rows) * 100, 2)}%)")

    adapted = [name for name in FEATURES if prev[name] >= PREVALENCE_THRESHOLD]
    print(f"\nadapted feature set (prevalence >= {PREVALENCE_THRESHOLD:.0%}): {adapted or '[] (none)'}")

    all_features = list(FEATURES)
    variants = [("all 15 features", all_features)]
    if adapted and adapted != all_features:
        variants.append((f"adapted ({len(adapted)} features)", adapted))

    for variant_name, feature_names in variants:
        print(f"\n=== Variant: {variant_name} ===")

        print("\n2. Random 5-fold CV (seeded shuffle, seed=42)")
        cv_results = [evaluate(tr, te, feature_names) for tr, te in random_cv_folds(rows)]
        print_table("   per fold:", cv_results)
        agg = aggregate(cv_results)
        print(
            f"   AGGREGATE: MAE={fmt(agg['mae'])} RMSE={fmt(agg['rmse'])} "
            f"R2={fmt(agg['r2'])} coverage={fmt(agg['coverage'])} "
            f"| baselines: mean MAE={fmt(agg['baseline_mean_mae'])} median MAE={fmt(agg['baseline_median_mae'])} "
            f"| median|err|={fmt(agg['median_ae'])}"
        )
        print(
            f"   diagnostic (3.0 SP floor removed): MAE={fmt(agg['mae_unfloored'])} "
            f"R2={fmt(agg['r2_unfloored'])} coverage={fmt(agg['coverage_unfloored'])} "
            f"| p50 hits the 3.0 floor on {fmt(agg['floor_binding'] * 100, 1)}% of test rows"
        )

        print("\n3. Cross-project GroupKFold (primary claim; unseen projects in test)")
        cp_results = []
        for tr, te in project_cv_folds(rows):
            res = evaluate(tr, te, feature_names)
            res["test_projects"] = sorted({row["project_id"] for row in te})
            res["n_test_projects"] = len(res["test_projects"])
            cp_results.append(res)
        print_table("   per fold:", cp_results)
        for i, res in enumerate(cp_results):
            examples = ", ".join(res["test_projects"][:4]) + (", ..." if res["n_test_projects"] > 4 else "")
            print(f"      fold {i + 1} test projects ({res['n_test_projects']}): {examples}")
        agg_cp = aggregate(cp_results)
        print(
            f"   AGGREGATE: MAE={fmt(agg_cp['mae'])} RMSE={fmt(agg_cp['rmse'])} "
            f"R2={fmt(agg_cp['r2'])} coverage={fmt(agg_cp['coverage'])} "
            f"| baselines: mean MAE={fmt(agg_cp['baseline_mean_mae'])} median MAE={fmt(agg_cp['baseline_median_mae'])} "
            f"| median|err|={fmt(agg_cp['median_ae'])}"
        )
        print(
            f"   diagnostic (3.0 SP floor removed): MAE={fmt(agg_cp['mae_unfloored'])} "
            f"R2={fmt(agg_cp['r2_unfloored'])} coverage={fmt(agg_cp['coverage_unfloored'])} "
            f"| p50 hits the 3.0 floor on {fmt(agg_cp['floor_binding'] * 100, 1)}% of test rows"
        )

    print("\ndone.")


if __name__ == "__main__":
    main()
