"""Tests for the SQLite schema and the CSV -> database seed script.

Uses a small generated corpus (n=24) in ``tmp_path``; no network, no side
effects on the repo-root database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from app.data_gen.generate_history import main as generate_main
from app.db.database import connect, init_db
from app.features import FEATURES
from scripts.seed_db import seed

N_PROJECTS = 24
SEED = 7
EXPECTED_TABLES = {"projects", "features", "corrections", "estimates"}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Generate a small CSV, seed a fresh database and return paths + data."""
    base = tmp_path_factory.mktemp("seed_db")
    csv_path = base / "synthetic_history.csv"
    truth_path = base / "ground_truth.json"
    assert generate_main(
        ["--n", str(N_PROJECTS), "--seed", str(SEED), "--out", str(csv_path), "--truth", str(truth_path)]
    ) == 0
    db_path = base / "estimator.db"
    counts = seed(csv_path, db_path, reset=True)
    return {
        "base": base,
        "csv": csv_path,
        "db": db_path,
        "counts": counts,
        "df": pd.read_csv(csv_path),
    }


def test_init_db_creates_all_tables(tmp_path: Path) -> None:
    db_path = init_db(tmp_path / "empty.db")
    with connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert EXPECTED_TABLES <= tables


def test_schema_creates_expected_columns(tmp_path: Path) -> None:
    db_path = init_db(tmp_path / "empty.db")
    with connect(db_path) as conn:
        columns = {
            table: {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for table in EXPECTED_TABLES
        }
    assert columns["projects"] == {
        "id", "project_id", "date", "email_text", "actual_days",
        "team_estimate", "status", "is_synthetic",
    }
    assert columns["features"] == {
        "id", "project_id", "name", "value_binary", "value_prob", "evidence_quote",
    }
    assert columns["corrections"] == {"id", "feature_name", "coefficient", "sample_count", "updated_at"}
    assert columns["estimates"] == {"id", "project_id", "p10", "p50", "p90", "model_version", "created_at"}


def test_project_count_matches_csv_rows(seeded: dict) -> None:
    assert seeded["counts"]["projects"] == len(seeded["df"]) == N_PROJECTS
    with connect(seeded["db"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == len(seeded["df"])


def test_features_rows_are_15_per_project(seeded: dict) -> None:
    assert seeded["counts"]["features"] == 15 * N_PROJECTS
    with connect(seeded["db"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 15 * N_PROJECTS
        rows_without_full_set = conn.execute(
            "SELECT project_id FROM features GROUP BY project_id HAVING COUNT(*) != 15"
        ).fetchall()
    assert rows_without_full_set == []


def test_feature_values_match_csv(seeded: dict) -> None:
    df = seeded["df"].set_index("project_id")
    with connect(seeded["db"]) as conn:
        for project_id in df.index:
            project_row = conn.execute(
                "SELECT id, date, status, actual_days FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            assert project_row["id"] is not None
            assert project_row["date"] == df.loc[project_id, "date"]
            stored = {
                row["name"]: row["value_binary"]
                for row in conn.execute(
                    "SELECT name, value_binary FROM features WHERE project_id = ?",
                    (project_row["id"],),
                )
            }
            assert stored == {name: int(df.loc[project_id, f"feat_{name}"]) for name in FEATURES}


def test_feature_rows_have_prob_one_and_no_quote(seeded: dict) -> None:
    with connect(seeded["db"]) as conn:
        stats = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(value_prob = 1.0) AS prob_one, "
            "SUM(evidence_quote IS NULL) AS null_quotes FROM features"
        ).fetchone()
    assert stats["total"] == stats["prob_one"] == stats["null_quotes"] == 15 * N_PROJECTS


def test_open_projects_have_null_actual_days(seeded: dict) -> None:
    with connect(seeded["db"]) as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE status != 'done' AND actual_days IS NULL"
        ).fetchone()[0]
        total_open = conn.execute("SELECT COUNT(*) FROM projects WHERE status != 'done'").fetchone()[0]
    assert total_open > 0
    assert open_count == total_open


def test_unique_project_id_is_enforced(seeded: dict) -> None:
    with connect(seeded["db"]) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO projects (project_id, date, email_text, status) VALUES (?, ?, ?, ?)",
                ("P001", "2026-01-01", "duplicate", "done"),
            )
        conn.rollback()


def test_reseed_with_reset_is_idempotent(seeded: dict) -> None:
    first = seed(seeded["csv"], seeded["db"], reset=True)
    second = seed(seeded["csv"], seeded["db"], reset=True)
    assert first == second == seeded["counts"]
    with connect(seeded["db"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == N_PROJECTS
        assert conn.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 15 * N_PROJECTS


def test_seed_without_reset_upserts_without_duplicates(seeded: dict) -> None:
    counts = seed(seeded["csv"], seeded["db"], reset=False)
    assert counts == seeded["counts"]
    with connect(seeded["db"]) as conn:
        assert conn.execute("SELECT COUNT(DISTINCT project_id) FROM projects").fetchone()[0] == N_PROJECTS
