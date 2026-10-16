"""SQLite helpers for The Estimator — stdlib ``sqlite3`` only.

Paths:
* ``get_db_path()`` resolves the repo-root ``data/estimator.db`` (overridable
  with the ``ESTIMATOR_DB_PATH`` env var, useful for tests and deployment).
* ``connect()`` opens a connection with ``sqlite3.Row`` rows and foreign keys
  enforced.
* ``init_db()`` executes ``schema.sql`` (idempotent).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Union

PathLike = Union[str, Path]

DB_ENV_VAR = "ESTIMATOR_DB_PATH"

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_db_path() -> Path:
    """Default database location: ``<repo-root>/data/estimator.db``.

    ``ESTIMATOR_DB_PATH`` overrides the location when set.
    """
    env_path = os.environ.get(DB_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()
    return _REPO_ROOT / "data" / "estimator.db"


def connect(db_path: PathLike | None = None) -> sqlite3.Connection:
    """Open a connection (Row factory, foreign keys on); creates parent dirs."""
    path = Path(db_path) if db_path is not None else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: PathLike | None = None) -> Path:
    """Create all tables/indexes from ``schema.sql`` and return the db path."""
    path = Path(db_path) if db_path is not None else get_db_path()
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return path
