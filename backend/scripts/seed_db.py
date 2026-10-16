"""Seed ``estimator.db`` from the synthetic history CSV (checklist GIAI ĐOẠN 1).

Reads the frozen CSV format (docs/API.md), initializes the schema and upserts
one ``projects`` row plus 15 ``features`` rows per project
(``value_binary`` from the ``feat_*`` columns, ``value_prob`` = 1.0,
``evidence_quote`` = NULL — synthetic rows have no extracted evidence).

Idempotent: re-running without ``--reset`` updates projects in place (stable
internal ids); ``--reset`` deletes the db file first for a clean rebuild.

CLI:
    python scripts/seed_db.py --csv data/synthetic_history.csv --db data/estimator.db --reset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

# Allow `python scripts/seed_db.py` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import connect, get_db_path, init_db  # noqa: E402
from app.features import FEATURES, FEATURE_COLUMN_PREFIX  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"

_PROJECT_COLUMNS = [
    "project_id",
    "date",
    "actual_days",
    "team_estimate",
    "status",
    "is_synthetic",
]
_REQUIRED_COLUMNS = _PROJECT_COLUMNS + ["email_text", *(f"{FEATURE_COLUMN_PREFIX}{f}" for f in FEATURES)]


def _optional_float(value: Any) -> float | None:
    """NaN/None -> None, everything else -> float (keeps actual_days NULL-able)."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def seed(csv_path: str | Path, db_path: str | Path | None = None, reset: bool = False) -> dict[str, int]:
    """Seed the database from ``csv_path`` and return row counts.

    Args:
        csv_path: synthetic history CSV (frozen column order from docs/API.md).
        db_path: target SQLite file; defaults to ``get_db_path()``.
        reset: delete the database file first (clean rebuild).

    Returns:
        ``{"projects": <rows>, "features": <rows * 15>}``.
    """
    csv_path = Path(csv_path)
    resolved_db = Path(db_path) if db_path is not None else get_db_path()
    if reset and resolved_db.exists():
        resolved_db.unlink()

    df = pd.read_csv(csv_path)
    missing = [column for column in _REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"{csv_path} is missing required columns: {missing}")

    init_db(resolved_db)
    conn = connect(resolved_db)
    try:
        for row in df.to_dict("records"):
            project_id = str(row["project_id"])
            project_values = (
                str(row["date"]),
                _optional_float(row["actual_days"]),
                _optional_float(row["team_estimate"]),
                str(row["status"]),
                int(row["is_synthetic"]),
                str(row["email_text"]),
            )
            existing = conn.execute(
                "SELECT id FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    "INSERT INTO projects "
                    "(project_id, date, actual_days, team_estimate, status, is_synthetic, email_text) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (project_id, *project_values),
                )
                internal_id = int(cursor.lastrowid)
            else:
                internal_id = int(existing["id"])
                conn.execute(
                    "UPDATE projects SET date = ?, actual_days = ?, team_estimate = ?, "
                    "status = ?, is_synthetic = ?, email_text = ? WHERE id = ?",
                    (*project_values, internal_id),
                )
            conn.execute("DELETE FROM features WHERE project_id = ?", (internal_id,))
            conn.executemany(
                "INSERT INTO features (project_id, name, value_binary, value_prob, evidence_quote) "
                "VALUES (?, ?, ?, 1.0, NULL)",
                [
                    (internal_id, name, int(row[f"{FEATURE_COLUMN_PREFIX}{name}"]))
                    for name in FEATURES
                ],
            )
        conn.commit()
        project_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        feature_count = conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]
    finally:
        conn.close()
    return {"projects": int(project_count), "features": int(feature_count)}


def build_parser() -> argparse.ArgumentParser:
    """CLI parser with repo-root defaults regardless of CWD."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help=f"input CSV (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--db", type=Path, default=None, help="target SQLite file (default: data/estimator.db)")
    parser.add_argument("--reset", action="store_true", help="delete the database file before seeding")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Seed the database and print a summary; returns the exit code."""
    args = build_parser().parse_args(argv)
    db_path = args.db if args.db is not None else get_db_path()
    counts = seed(args.csv, db_path, reset=args.reset)
    action = "Reset and seeded" if args.reset else "Seeded"
    print(f"{action} {counts['projects']} projects / {counts['features']} feature rows into {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
