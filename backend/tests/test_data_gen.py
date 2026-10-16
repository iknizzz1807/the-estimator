"""Tests for the synthetic history generator (checklist GIAI ĐOẠN 1).

Offline, deterministic and side-effect free: everything is generated into
``tmp_path`` with the CLI entry point (``main``), which also covers the frozen
CSV/JSON output contract.

Beyond the original checks (byte determinism, schema, team bias, omission
rate, negations, no NaNs) this suite validates the added realism layers:
interaction multipliers, mid-history drift and blow-up outliers. The
statistical checks pool several seeds so they stay deterministic while having
enough samples to be meaningful (a single corpus still has few samples for the
rarest co-occurring pairs).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import fmean

import pandas as pd
import pytest

from app.data_gen.generate_history import (
    DRIFT_FACTOR,
    DRIFT_SWITCH_DATE,
    FEATURE_PROBABILITIES,
    HIDDEN_COEFFICIENTS,
    INTERACTION_MULTIPLIERS,
    METADATA_COLUMNS,
    OUTLIER_SHOCK_MAX,
    OUTLIER_SHOCK_MIN,
    RECENT_PROJECT_COUNT,
    REPO_ROOT,
    effort_days,
    generate,
    main,
)
from app.features import FEATURES, csv_columns
from app.services.estimation import coefficients as learned_multipliers
from app.services.estimation import train_model

N_PROJECTS = 240
SEED = 42
#: Seeds pooled by the "interaction raises effort" statistical check.
STATISTICAL_SEEDS = (42, 43, 44, 45, 46, 47)
NEW_PROJECT_KEYS = {"interaction_multiplier", "drift_factor", "outlier_shock"}


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Generate the full corpus once per module and load CSV + ground truth."""
    out_dir = tmp_path_factory.mktemp("data_gen")
    csv_path = out_dir / "synthetic_history.csv"
    truth_path = out_dir / "ground_truth.json"
    exit_code = main(
        ["--n", str(N_PROJECTS), "--seed", str(SEED), "--out", str(csv_path), "--truth", str(truth_path)]
    )
    assert exit_code == 0
    return {
        "csv": csv_path,
        "truth": truth_path,
        "df": pd.read_csv(csv_path),
        "truth_data": json.loads(truth_path.read_text(encoding="utf-8")),
    }


def _mean_ratio(df: pd.DataFrame) -> float:
    done = df[df["status"] == "done"]
    return float((done["team_estimate"] / done["actual_days"]).mean())


def _done_rows(df: pd.DataFrame) -> list[dict]:
    """Canonical rows (docs/API.md) for the done projects, for model training."""
    done = df[df["status"] == "done"]
    return [
        {
            "project_id": row["project_id"],
            "date": row["date"],
            "actual_days": float(row["actual_days"]),
            "team_estimate": float(row["team_estimate"]),
            "features": {name: int(row[f"feat_{name}"]) for name in FEATURES},
        }
        for _, row in done.iterrows()
    ]


def test_same_seed_produces_identical_bytes(tmp_path: Path) -> None:
    first_csv, first_truth = tmp_path / "a.csv", tmp_path / "a.json"
    second_csv, second_truth = tmp_path / "b.csv", tmp_path / "b.json"
    args = ["--n", str(N_PROJECTS), "--seed", str(SEED)]
    assert main([*args, "--out", str(first_csv), "--truth", str(first_truth)]) == 0
    assert main([*args, "--out", str(second_csv), "--truth", str(second_truth)]) == 0
    assert first_csv.read_bytes() == second_csv.read_bytes()
    assert first_truth.read_bytes() == second_truth.read_bytes()


def test_csv_columns_match_api_contract(generated: dict) -> None:
    assert list(generated["df"].columns) == METADATA_COLUMNS + csv_columns()
    assert generated["df"]["is_synthetic"].eq(1).all()


def test_default_paths_resolve_to_repo_root_data_dir() -> None:
    from app.data_gen.generate_history import DEFAULT_CSV_PATH, DEFAULT_TRUTH_PATH

    assert DEFAULT_CSV_PATH == REPO_ROOT / "data" / "synthetic_history.csv"
    assert DEFAULT_TRUTH_PATH == REPO_ROOT / "data" / "ground_truth.json"


def test_actual_days_minimum_and_empty_when_not_done(generated: dict) -> None:
    df = generated["df"]
    done = df[df["status"] == "done"]
    open_projects = df[df["status"] != "done"]
    assert len(done) > 0 and len(open_projects) > 0
    assert done["actual_days"].notna().all()
    assert (done["actual_days"] >= 5).all()
    assert open_projects["actual_days"].isna().all()
    assert set(df["status"]) <= {"done", "in_progress", "pending"}


def test_recent_projects_are_open(generated: dict) -> None:
    df = generated["df"].sort_values(["date", "project_id"], kind="stable").reset_index(drop=True)
    newest = df.tail(RECENT_PROJECT_COUNT)
    assert df[df["status"] != "done"]["project_id"].tolist() == newest["project_id"].tolist()


def test_team_estimate_is_systematically_biased(generated: dict) -> None:
    df = generated["df"]
    # Drift and blow-ups make post-switch actuals larger: the team (which keeps
    # its pre-drift perceptions) must stay clearly optimistic overall.
    assert _mean_ratio(df) < 0.95
    with_tp = _mean_ratio(df[df["feat_third_party_api"] == 1])
    without_tp = _mean_ratio(df[df["feat_third_party_api"] == 0])
    assert with_tp < without_tp


def test_omission_rate_matches_target(generated: dict) -> None:
    projects = generated["truth_data"]["projects"]
    rate = sum(1 for p in projects.values() if p["omitted"]) / len(projects)
    assert 0.20 <= rate <= 0.40, f"omission rate {rate:.2%} outside 30% ± 10pp"


def test_negations_present(generated: dict) -> None:
    projects = generated["truth_data"]["projects"]
    assert sum(1 for p in projects.values() if p["negated"]) > 0


def test_no_nan_or_invalid_feature_values(generated: dict) -> None:
    df = generated["df"]
    feature_frame = df[csv_columns()]
    assert not feature_frame.isna().any().any()
    assert set(feature_frame.to_numpy().ravel().tolist()) <= {0, 1}


def test_emails_have_expected_word_count(generated: dict) -> None:
    word_counts = generated["df"]["email_text"].str.split().str.len()
    assert word_counts.min() >= 120
    assert word_counts.max() <= 350


def test_ground_truth_contains_interaction_drift_outlier_blocks(generated: dict) -> None:
    truth = generated["truth_data"]
    pairs = {
        tuple(item["features"]): item["multiplier"] for item in truth["interaction_multipliers"]
    }
    assert pairs == INTERACTION_MULTIPLIERS
    assert truth["drift"] == {
        "switch_date": DRIFT_SWITCH_DATE.isoformat(),
        "factor": DRIFT_FACTOR,
    }
    assert isinstance(truth["outliers"], dict) and truth["outliers"]
    assert set(truth["outliers"]) <= set(truth["projects"])


def test_ground_truth_structure_and_consistency(generated: dict) -> None:
    truth = generated["truth_data"]
    assert truth["seed"] == SEED
    assert truth["hidden_coefficients"] == HIDDEN_COEFFICIENTS
    assert truth["feature_probabilities"] == FEATURE_PROBABILITIES
    assert len(truth["projects"]) == N_PROJECTS

    switch_date = truth["drift"]["switch_date"]
    df = generated["df"].set_index("project_id")
    for project_id, project in truth["projects"].items():
        assert set(project) == {
            "features",
            "mentioned",
            "omitted",
            "negated",
            "actual_days",
            "team_estimate",
        } | NEW_PROJECT_KEYS
        assert list(project["features"]) == FEATURES
        present = {f for f, value in project["features"].items() if value == 1}
        assert set(project["mentioned"]) <= present
        assert set(project["omitted"]) <= present
        assert present == set(project["mentioned"]) | set(project["omitted"])
        assert not set(project["negated"]) & present

        # Per-project hidden factors must agree with features/date and blocks.
        expected_interactions = math.prod(
            multiplier
            for (first, second), multiplier in INTERACTION_MULTIPLIERS.items()
            if project["features"][first] and project["features"][second]
        )
        assert project["interaction_multiplier"] == pytest.approx(expected_interactions)
        expected_drift = DRIFT_FACTOR if df.loc[project_id, "date"] >= switch_date else 1.0
        assert project["drift_factor"] == pytest.approx(expected_drift)

    # Ground truth features must agree with the CSV feature columns.
    for project_id, project in truth["projects"].items():
        csv_values = {name: int(df.loc[project_id, f"feat_{name}"]) for name in FEATURES}
        assert csv_values == project["features"]


def test_project_ids_and_feature_probability_bounds(generated: dict) -> None:
    df = generated["df"]
    assert df["project_id"].tolist() == [f"P{i:03d}" for i in range(1, N_PROJECTS + 1)]
    assert all(0.15 <= p <= 0.45 for p in FEATURE_PROBABILITIES.values())
    assert len(HIDDEN_COEFFICIENTS) == len(FEATURES)
    assert all(coefficient > 1.0 for coefficient in HIDDEN_COEFFICIENTS.values())


# --------------------------------------------------------------------------- #
# Added realism: drift, outliers, interactions, main-effect recoverability
# --------------------------------------------------------------------------- #


def test_drift_effect_present(generated: dict) -> None:
    """Post-switch actuals carry the hidden x1.22 drift; pre-switch do not."""
    truth = generated["truth_data"]
    df = generated["df"]
    done = df[df["status"] == "done"]
    assert len(done) > 0
    switch_date = truth["drift"]["switch_date"]

    pre_actual, post_actual = [], []
    pre_corrected, post_corrected = [], []
    for _, row in done.iterrows():
        project = truth["projects"][row["project_id"]]
        features = {name: int(row[f"feat_{name}"]) for name in FEATURES}
        formula = math.log(effort_days(features))
        # Literal requirement: residual vs the main-effects formula.
        (post_actual if row["date"] >= switch_date else pre_actual).append(
            math.log(row["actual_days"]) - formula
        )
        # Interactions/outliers removed: residual = drift factor + noise only.
        correction = project["interaction_multiplier"] * (project["outlier_shock"] or 1.0)
        (post_corrected if row["date"] >= switch_date else pre_corrected).append(
            math.log(row["actual_days"]) - formula - math.log(correction)
        )

    assert len(pre_actual) >= 10 and len(post_actual) >= 10
    assert fmean(pre_actual) < fmean(post_actual), "expected direction: post-switch > pre-switch"
    drift_gap = fmean(post_corrected) - fmean(pre_corrected)
    # log(1.22) = 0.199; generous band around it (157 pre / 71 post-switch rows, o=0.18).
    assert 0.10 <= drift_gap <= 0.35, f"drift gap {drift_gap:.3f} not near log(1.22)"


def test_outlier_rate_and_shocks_within_contract(generated: dict) -> None:
    truth = generated["truth_data"]
    df = generated["df"]
    outliers = truth["outliers"]
    assert set(outliers) <= set(df["project_id"])

    rate = len(outliers) / N_PROJECTS
    assert 0.03 <= rate <= 0.07, f"outlier rate {rate:.2%} outside 5% ± 2pp"
    for project_id, shock in outliers.items():
        assert OUTLIER_SHOCK_MIN <= shock <= OUTLIER_SHOCK_MAX, f"{project_id} shock {shock}"
        project = truth["projects"][project_id]
        assert project["outlier_shock"] == pytest.approx(shock)
        assert project["actual_days"] is not None  # shocks only land on done rows

    for project_id, project in truth["projects"].items():
        assert (project["outlier_shock"] is None) == (project_id not in outliers)


def test_interaction_pairs_raise_effort_beyond_main_effects() -> None:
    """Pooled over seeds: joint pairs beat the individual-product prediction."""
    joint: list[float] = []
    other: list[float] = []
    per_pair: dict[tuple[str, str], list[float]] = {pair: [] for pair in INTERACTION_MULTIPLIERS}
    for seed in STATISTICAL_SEEDS:
        records, truth = generate(n=N_PROJECTS, seed=seed)
        for record in records:
            if record.status != "done":
                continue
            project = truth["projects"][record.project_id]
            features = dict(record.features)
            # Correction removes drift/outlier effects only: the residual keeps
            # the interaction uplift (and lognormal noise) when a pair is joint.
            correction = project["drift_factor"] * (project["outlier_shock"] or 1.0)
            residual = math.log(record.actual_days) - math.log(effort_days(features) * correction)
            active = [
                pair
                for pair in INTERACTION_MULTIPLIERS
                if features[pair[0]] and features[pair[1]]
            ]
            if active:
                joint.append(residual)
            else:
                other.append(residual)
            if len(active) == 1:
                per_pair[active[0]].append(residual)

    # 6 seeds x 228 done rows pool ~234 joint / ~1134 interaction-free rows.
    assert len(joint) >= 150 and len(other) >= 900
    # Joint projects systematically exceed the individual-product prediction...
    assert fmean(joint) > fmean(other) + 0.05, f"joint={fmean(joint):.3f} other={fmean(other):.3f}"
    # ...while interaction-free projects show no spurious uplift.
    assert abs(fmean(other)) < 0.05
    for pair, values in per_pair.items():
        assert len(values) >= 40, f"{pair} has too few clean samples: {len(values)}"
        assert fmean(values) > 0.03, f"{pair} uplift {fmean(values):.3f} not positive"


def test_main_effects_recoverable_on_training_rows(generated: dict) -> None:
    """Ridge (the learning loop) must recover every main effect within ~20%."""
    model = train_model(_done_rows(generated["df"]))
    learned = {item["feature"]: item["multiplier"] for item in learned_multipliers(model)}
    assert set(learned) == set(FEATURES)
    for name in FEATURES:
        ratio = learned[name] / HIDDEN_COEFFICIENTS[name]
        assert 0.80 <= ratio <= 1.20, (
            f"{name}: learned {learned[name]:.3f} vs hidden {HIDDEN_COEFFICIENTS[name]:.2f} "
            f"({ratio - 1:+.1%})"
        )
