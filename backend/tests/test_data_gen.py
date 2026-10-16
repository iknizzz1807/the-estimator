"""Tests for the synthetic history generator (checklist GIAI ĐOẠN 1).

Offline, deterministic and side-effect free: everything is generated into
``tmp_path`` with the CLI entry point (``main``), which also covers the frozen
CSV/JSON output contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.data_gen.generate_history import (
    FEATURE_PROBABILITIES,
    HIDDEN_COEFFICIENTS,
    METADATA_COLUMNS,
    REPO_ROOT,
    main,
)
from app.features import FEATURES, csv_columns

N_PROJECTS = 60
SEED = 42


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
    newest = df.tail(8)
    assert df[df["status"] != "done"]["project_id"].tolist() == newest["project_id"].tolist()


def test_team_estimate_is_systematically_biased(generated: dict) -> None:
    df = generated["df"]
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


def test_ground_truth_structure_and_consistency(generated: dict) -> None:
    truth = generated["truth_data"]
    assert truth["seed"] == SEED
    assert truth["hidden_coefficients"] == HIDDEN_COEFFICIENTS
    assert truth["feature_probabilities"] == FEATURE_PROBABILITIES
    assert len(truth["projects"]) == N_PROJECTS

    for project_id, project in truth["projects"].items():
        assert set(project) == {
            "features",
            "mentioned",
            "omitted",
            "negated",
            "actual_days",
            "team_estimate",
        }
        assert list(project["features"]) == FEATURES
        present = {f for f, value in project["features"].items() if value == 1}
        assert set(project["mentioned"]) <= present
        assert set(project["omitted"]) <= present
        assert present == set(project["mentioned"]) | set(project["omitted"])
        assert not set(project["negated"]) & present

    # Ground truth features must agree with the CSV feature columns.
    df = generated["df"].set_index("project_id")
    for project_id, project in truth["projects"].items():
        csv_values = {name: int(df.loc[project_id, f"feat_{name}"]) for name in FEATURES}
        assert csv_values == project["features"]


def test_project_ids_and_feature_probability_bounds(generated: dict) -> None:
    df = generated["df"]
    assert df["project_id"].tolist() == [f"P{i:03d}" for i in range(1, N_PROJECTS + 1)]
    assert all(0.15 <= p <= 0.45 for p in FEATURE_PROBABILITIES.values())
    assert len(HIDDEN_COEFFICIENTS) == len(FEATURES)
    assert all(coefficient > 1.0 for coefficient in HIDDEN_COEFFICIENTS.values())
