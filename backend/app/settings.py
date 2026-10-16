"""API settings for The Estimator (pydantic-settings, repo-root ``.env``).

Everything must work with **no ``.env`` at all** (offline demo mode):
``LLM_PROVIDER`` defaults to ``stub``, the database to ``data/estimator.db``
and CORS to ``http://localhost:3000``.

Database path resolution order (first match wins):
1. ``ESTIMATOR_DB_PATH`` environment variable (tests / deployment override,
   also honored by ``app.db.database.get_db_path``),
2. ``DATABASE_PATH`` from the ``.env`` file (relative paths resolve against
   the repository root),
3. the default ``<repo-root>/data/estimator.db``.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: ``backend/`` directory (parent of the ``app`` package).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
#: Repository root (parent of ``backend/``); holds ``.env`` and ``data/``.
REPO_ROOT = BACKEND_ROOT.parent

DEFAULT_DB_RELATIVE = "data/estimator.db"
DB_ENV_VAR = "ESTIMATOR_DB_PATH"
#: Set to 0/false/no/off to skip auto-seeding an empty database (tests use it
#: to exercise the cold-start path).
AUTO_SEED_ENV_VAR = "ESTIMATOR_AUTO_SEED"


class AppSettings(BaseSettings):
    """Env-driven settings for the API layer; every field has a safe default."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "stub"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    database_path: str = DEFAULT_DB_RELATIVE
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed CORS allow-list (comma-separated in the env var)."""
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return origins or ["http://localhost:3000"]


def get_settings() -> AppSettings:
    """Load settings from environment / ``.env`` (fresh read, test-friendly)."""
    return AppSettings()


def resolve_db_path(settings: AppSettings | None = None) -> Path:
    """Resolve the SQLite file per the module docstring's precedence rules."""
    env_override = os.environ.get(DB_ENV_VAR)
    if env_override:
        return Path(env_override).expanduser()
    resolved_settings = settings or get_settings()
    raw = (resolved_settings.database_path or DEFAULT_DB_RELATIVE).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def auto_seed_enabled() -> bool:
    """Whether an empty database should be seeded from the synthetic CSV."""
    raw = os.environ.get(AUTO_SEED_ENV_VAR)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}
