"""DB <-> service wiring for the API layer (startup caches + estimate pipeline).

Everything HTTP-agnostic lives here so ``routes.py`` stays thin:

* ``bootstrap`` — seed an empty DB, load rows, train the model, run the
  walk-forward replay **once** and persist its estimates (``replay-v1``).
* System-estimate resolution for History: replay cache > stored estimate rows
  > live model fallback (documented pragmatism, see ``system_estimates``).
* The shared estimate pipeline (extract -> estimate -> similar -> questions)
  used by ``POST /api/estimate``, the SSE stream and scenario loading.
* The learning loop for ``POST /api/projects/{id}/actual``: retrain, sliding
  coefficient update, corrections persistence and accuracy metrics.

All functions are synchronous; FastAPI handlers call them in the event loop
(cheap pure math) or a threadpool (DB / CSV work).
"""

from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from app.db.database import connect, init_db
from app.features import FEATURES
from app.services.codebase import (
    apply_friction,
    collect_signals,
    compute_friction,
    estimate_invasiveness,
    find_similar_changes,
)
from app.services.estimation import (
    COLD_START_MULTIPLIERS,
    EstimatorModel,
    coefficients,
    cold_start_estimate,
    estimate,
    estimate_mc,
    train_model,
)
from app.services.extraction import (
    MAX_EMAIL_CHARS,
    WARN_CONFLICT,
    WARN_LONG_EMAIL,
    ExtractionResult,
    extract_features,
)
from app.services.learning import accuracy_metrics, update_coefficients
from app.services.packages import build_packages
from app.services.providers import get_provider
from app.services.replay import replay
from app.services.similarity import find_similar
from app.services.voi import rank_questions
from app.settings import REPO_ROOT, auto_seed_enabled

logger = logging.getLogger(__name__)

DEFAULT_MIN_TRAIN = 10
REPLAY_MODEL_VERSION = "replay-v1"
LIVE_MODEL_VERSION = "live-v1"
SEED_CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
#: How many recent finished projects feed the LLM-with-history baseline (v0.2).
HISTORY_ROWS_LIMIT = 15
#: 409 detail when ``/api/packages`` is called before any model can be trained.
PACKAGES_COLD_START_DETAIL = (
    "Chưa có model được train (cold start): cần nạp dữ liệu lịch sử trước khi gợi ý gói dự án"
)
#: Serializes demo-DB rebuilds (``/api/reset``) across concurrent requests.
_RESET_LOCK = threading.Lock()
VALID_STATUSES = {"done", "in_progress", "pending"}
FEATURE_COLUMNS = [f"feat_{name}" for name in FEATURES]
IMPORT_REQUIRED_COLUMNS = [
    "project_id",
    "date",
    "actual_days",
    "team_estimate",
    "status",
    "is_synthetic",
    "email_text",
    *FEATURE_COLUMNS,
]

WARN_BIG_ACTUAL = "Giá trị bất thường, vui lòng kiểm tra lại"

# --------------------------------------------------------------------------- #
# Codebase Lab (contract v0.2, docs/API.md "optional codebase context")
# --------------------------------------------------------------------------- #

#: ``repo`` values accepted on ``POST /api/estimate``; the two demo repos are
#: built on demand into ``data/demo_repos/`` (gitignored), "self" analyzes the
#: server's own checkout.
CODEBASE_REPO_CHOICES: tuple[str, ...] = ("demo_a", "demo_b", "self")
#: ``repo`` -> demo-repo directory name produced by scripts/build_demo_repos.py.
CODEBASE_DEMO_REPOS: dict[str, str] = {
    "demo_a": "payment_plugin",
    "demo_b": "payment_spaghetti",
}
#: Documented feature -> path-keyword mapping for ``find_similar_changes``
#: (docs/API.md v0.2: "Keywords ... are derived from the extracted features").
#: Only features extracted as PRESENT (value == 1) contribute keywords.
CODEBASE_FEATURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "third_party_api": ("api", "client", "integration"),
    "payment_gateway": ("payment", "billing", "checkout"),
    "identity_provider": ("auth", "sso", "login"),
    "external_data_sync": ("sync", "connector"),
    "data_migration": ("migration", "database"),
    "multi_currency": ("currency",),
    "multi_tenancy": ("tenant",),
    "realtime_ui": ("realtime", "websocket", "stream"),
    "mobile_app": ("mobile", "ios", "android"),
    "offline_mode": ("offline",),
    "pci_dss": ("pci", "card"),
    "privacy_compliance": ("privacy", "gdpr"),
    "audit_logging": ("audit", "log"),
    "legacy_tech_stack": ("legacy",),
    "cross_team_coordination": ("coord",),
}
#: Documented fallback when the extraction found NO present feature: generic
#: source paths keep the structural signals meaningful, while similar-changes
#: stays evidence-free (no match -> invasiveness ``None`` -> median unchanged).
CODEBASE_FALLBACK_KEYWORDS: tuple[str, ...] = ("src", "app", "core", "main", "utils")
#: Env override for the demo-repos directory (tests point it at a tmp dir).
CODEBASE_DEMO_REPOS_DIR_ENV = "ESTIMATOR_DEMO_REPOS_DIR"
#: Timeout for the on-demand demo-repo builder subprocess.
CODEBASE_BUILD_TIMEOUT_SECONDS = 300.0
#: Contract note surfaced verbatim in every ``codebase`` block (docs/API.md v0.2).
CODEBASE_NOTE = (
    "DEMO-ASSUMED coefficients; the similar-past-changes mechanism is validated "
    "on 29k real commits (docs/CODEBASE_HISTORY_VALIDATION.md); no "
    "text-prediction accuracy claim (docs/CODEBASE_VALIDATION.md). "
    "One-directional by design: surcharge only, never a discount."
)
#: Serializes on-demand demo-repo builds across concurrent requests.
_DEMO_REPOS_LOCK = threading.Lock()


# ``scripts/seed_db.py`` lives outside the ``app`` package — make it importable
# regardless of the process working directory.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
from scripts.seed_db import seed as seed_from_csv  # noqa: E402


# --------------------------------------------------------------------------- #
# Runtime state
# --------------------------------------------------------------------------- #


@dataclass
class AppState:
    """Runtime state shared by all handlers (one instance per app)."""

    db_path: Path
    provider: Any = None  # LLMProvider resolved once at startup
    llm_provider_name: str = "stub"
    model: EstimatorModel | None = None
    replay_cache: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: ``{project_id: {p10, p50, p90, in_interval}}`` walk-forward replay view
    #: used by the History screen (mirrors ``replay_cache[DEFAULT_MIN_TRAIN]``).
    history_cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def model_loaded(self) -> bool:
        """True when a trained (calibrated or warm-up) model is available."""
        return self.model is not None

    def project_count(self) -> int:
        """Live project count straight from SQLite (never cached)."""
        conn = connect(self.db_path)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
        finally:
            conn.close()


def now_iso() -> str:
    """Timestamp for ``created_at`` / ``updated_at`` columns."""
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #


def ensure_seeded(db_path: Path) -> int:
    """Create the schema and seed the synthetic CSV when the DB has no rows."""
    init_db(db_path)
    conn = connect(db_path)
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
    finally:
        conn.close()

    if count == 0 and auto_seed_enabled() and SEED_CSV_PATH.exists():
        try:
            counts = seed_from_csv(SEED_CSV_PATH, db_path, reset=False)
            logger.info("Seeded %d projects from %s", counts["projects"], SEED_CSV_PATH)
            count = int(counts["projects"])
        except Exception:  # pragma: no cover - defensive: cold start is fine too
            logger.exception("Seeding from %s failed - starting empty", SEED_CSV_PATH)
    return count


def reset_demo_db(state: AppState) -> dict[str, Any]:
    """Delete + reseed the demo DB from the synthetic CSV; retrain + refresh caches.

    Contract v0.2 ``POST /api/reset``. The whole rebuild runs behind a
    process-wide lock so concurrent reset requests cannot interleave. The new
    database is built in a sibling temp file and swapped in with
    ``os.replace`` (same-directory rename), so a reader opening the DB during
    the reset never observes a half-created schema.
    """
    with _RESET_LOCK:
        tmp_path = state.db_path.with_name(state.db_path.name + ".reset-tmp")
        tmp_path.unlink(missing_ok=True)
        try:
            seed_from_csv(SEED_CSV_PATH, tmp_path, reset=False)
            os.replace(tmp_path, state.db_path)
        finally:
            tmp_path.unlink(missing_ok=True)  # no-op after a successful replace
        rows = load_rows(state.db_path)
        fit_model(state, rows, keep_old=False)
        state.replay_cache.clear()
        refresh_replay(state, min_train=DEFAULT_MIN_TRAIN, persist=True)
        count = state.project_count()
    logger.info("Demo DB reset: %d projects, model_loaded=%s", count, state.model_loaded)
    return {"status": "ok", "projects_count": count}


def bootstrap(state: AppState) -> None:
    """Prepare caches for serving: seed, train, replay (once), persist."""
    projects = ensure_seeded(state.db_path)
    provider, provider_name = get_provider()
    state.provider = provider
    state.llm_provider_name = provider_name

    rows = load_rows(state.db_path)
    fit_model(state, rows, keep_old=False)
    refresh_replay(state, min_train=DEFAULT_MIN_TRAIN, persist=True)
    logger.info(
        "Ready: %d projects, model_loaded=%s, provider=%s",
        projects,
        state.model_loaded,
        state.llm_provider_name,
    )


# --------------------------------------------------------------------------- #
# Row loading
# --------------------------------------------------------------------------- #


def load_rows(db_path: Path) -> list[dict[str, Any]]:
    """All projects as canonical rows plus DB extras (db_id, status, email...).

    Canonical keys (docs/API.md): project_id, date, actual_days, team_estimate,
    features. Extras used by the API layer: db_id, email_text, status,
    is_synthetic.
    """
    conn = connect(db_path)
    try:
        projects = conn.execute(
            "SELECT id, project_id, date, email_text, actual_days, team_estimate, "
            "status, is_synthetic FROM projects ORDER BY id"
        ).fetchall()
        feature_map: dict[int, dict[str, int | None]] = {}
        for feature_row in conn.execute("SELECT project_id, name, value_binary FROM features"):
            feature_map.setdefault(int(feature_row["project_id"]), {})[
                feature_row["name"]
            ] = feature_row["value_binary"]
    finally:
        conn.close()

    rows: list[dict[str, Any]] = []
    for project in projects:
        stored = feature_map.get(int(project["id"]), {})
        rows.append(
            {
                "db_id": int(project["id"]),
                "project_id": project["project_id"],
                "date": project["date"],
                "email_text": project["email_text"],
                "actual_days": project["actual_days"],
                "team_estimate": project["team_estimate"],
                "status": project["status"],
                "is_synthetic": int(project["is_synthetic"] or 0),
                "features": {name: stored.get(name) for name in FEATURES},
            }
        )
    return rows


def done_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows usable for training: status done with a positive actual duration."""
    usable: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "done":
            continue
        try:
            actual = float(row.get("actual_days"))
        except (TypeError, ValueError):
            continue
        if actual > 0:
            usable.append(dict(row))
    return usable


def recent_done_rows(
    state: AppState, limit: int = HISTORY_ROWS_LIMIT
) -> list[dict[str, Any]]:
    """The most recent finished projects, newest first (AB history baseline v0.2).

    Same ordering the LLM history table uses (date desc, project_id desc), so
    capping here keeps the rendered prompt identical to passing every row.
    """
    rows = done_rows(load_rows(state.db_path))
    rows.sort(
        key=lambda row: (str(row.get("date") or ""), str(row.get("project_id") or "")),
        reverse=True,
    )
    return rows[: max(0, int(limit))]


def fit_model(
    state: AppState, rows: Sequence[Mapping[str, Any]], keep_old: bool = False
) -> bool:
    """Train on the done rows and store the model; True on success.

    ``keep_old=True`` keeps the previous model when training fails (spec §9:
    "Retrain model thất bại -> giữ model cũ"), otherwise it drops to cold start.
    """
    try:
        state.model = train_model(done_rows(rows))
        return True
    except ValueError as exc:
        logger.warning("Model training skipped (%s)", exc)
        if not keep_old:
            state.model = None
        return False


# --------------------------------------------------------------------------- #
# Replay + system estimates
# --------------------------------------------------------------------------- #


def refresh_replay(state: AppState, min_train: int = DEFAULT_MIN_TRAIN, persist: bool = True) -> dict[str, Any]:
    """(Re)compute the walk-forward replay and refresh caches.

    When ``min_train == DEFAULT_MIN_TRAIN`` the History cache is refreshed and
    (with ``persist``) the ``estimates`` table mirror is rewritten with
    ``model_version="replay-v1"`` rows.
    """
    rows = load_rows(state.db_path)
    result = replay(done_rows(rows), min_train=min_train)
    state.replay_cache[min_train] = result
    if min_train == DEFAULT_MIN_TRAIN:
        state.history_cache = {
            str(step["project_id"]): {
                "p10": step["p10"],
                "p50": step["p50"],
                "p90": step["p90"],
                "in_interval": step["in_interval"],
            }
            for step in result["steps"]
        }
        if persist:
            persist_replay_estimates(state, rows, result)
    return result


def persist_replay_estimates(
    state: AppState, rows: Sequence[Mapping[str, Any]], result: Mapping[str, Any]
) -> int:
    """Mirror the walk-forward steps into ``estimates`` (idempotent rewrite)."""
    internal_ids = {
        str(row["project_id"]): int(row["db_id"])
        for row in rows
        if row.get("db_id") is not None
    }
    steps = [step for step in result.get("steps", []) if step.get("project_id") in internal_ids]
    conn = connect(state.db_path)
    try:
        conn.execute("DELETE FROM estimates WHERE model_version = ?", (REPLAY_MODEL_VERSION,))
        conn.executemany(
            "INSERT INTO estimates (project_id, p10, p50, p90, model_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    internal_ids[str(step["project_id"])],
                    step["p10"],
                    step["p50"],
                    step["p90"],
                    REPLAY_MODEL_VERSION,
                    now_iso(),
                )
                for step in steps
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return len(steps)


def latest_estimates(db_path: Path) -> dict[str, dict[str, Any]]:
    """Latest persisted estimate per project (any model_version)."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT e.id, p.project_id, e.p10, e.p50, e.p90, e.model_version "
            "FROM estimates e JOIN projects p ON p.id = e.project_id ORDER BY e.id"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[str(row["project_id"])] = {
            "p10": row["p10"],
            "p50": row["p50"],
            "p90": row["p90"],
            "model_version": row["model_version"],
        }
    return out


def system_estimates(state: AppState, rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Best available system interval per project for the History screen.

    Precedence (documented pragmatism):
    1. walk-forward replay cache (out-of-sample, ``source="replay"``),
    2. latest stored estimate row (``source="stored"``),
    3. live model / cold-start fallback for everything else --- in-sample for
       old rows, but keeps History complete (``source="model"|"cold_start"``).
    """
    estimates: dict[str, dict[str, Any]] = {
        project_id: {**entry, "source": "replay"}
        for project_id, entry in state.history_cache.items()
    }
    for project_id, entry in latest_estimates(state.db_path).items():
        if project_id in estimates or entry.get("p50") is None:
            continue
        estimates[project_id] = {**entry, "in_interval": None, "source": "stored"}

    for row in rows:
        project_id = str(row["project_id"])
        if project_id in estimates:
            continue
        prediction = predict(state, row.get("features") or {})
        estimates[project_id] = {
            "p10": prediction["p10"],
            "p50": prediction["p50"],
            "p90": prediction["p90"],
            "in_interval": None,
            "source": "model" if state.model_loaded else "cold_start",
        }
    return estimates


# --------------------------------------------------------------------------- #
# Estimate pipeline
# --------------------------------------------------------------------------- #


def resolve_features(extraction: ExtractionResult) -> dict[str, bool | None]:
    """Findings -> ``{feature: True|False|None}`` in canonical order."""
    return {finding.name: finding.value for finding in extraction.findings}


def apply_answers(
    extraction: ExtractionResult, answers: Mapping[str, Any] | None
) -> ExtractionResult:
    """Overlay user answers (0/1) on the extracted findings (contract v0.2).

    The answer wins and the feature becomes known; answered findings carry
    confidence 1.0 (user-provided) and keep the extraction's evidence quote.
    ``missing`` is recomputed. ``None``/empty ``answers`` return the extraction
    untouched.
    """
    if not answers:
        return extraction
    findings = [
        (
            finding.model_copy(
                update={
                    "value": bool(int(answers[finding.name])),
                    "confidence": 1.0,
                }
            )
            if finding.name in answers
            else finding
        )
        for finding in extraction.findings
    ]
    missing = [finding.name for finding in findings if finding.value is None]
    return extraction.model_copy(update={"findings": findings, "missing": missing})


def extract_stage(state: AppState, email_text: str) -> tuple[ExtractionResult, str]:
    """Run the extraction service with the provider resolved at startup."""
    if state.provider is None:  # defensive: lifespan normally sets this
        state.provider, state.llm_provider_name = get_provider()
    result = extract_features(email_text, provider=(state.provider, state.llm_provider_name))
    return result, result.provider


def predict(state: AppState, features: Mapping[str, Any] | None) -> dict[str, Any]:
    """Calibrated prediction when a model exists, cold start otherwise.

    Contract v0.2: while the calibrated model still sees unknown (``None``)
    features the interval comes from :func:`estimate_mc`
    (``method="mc"``, unknown features sampled at their training prevalence);
    fully-known vectors and warm-up/cold-start models use the deterministic
    point estimator (``method="point"``). ``unit``/``method`` are always
    present.
    """
    source = features or {}
    unknowns = [
        name
        for name in (state.model.feature_names if state.model is not None else ())
        if name in source and source[name] is None
    ]
    if state.model is not None and state.model.calibrated and unknowns:
        return estimate_mc(state.model, source)

    prediction = (
        estimate(state.model, source)
        if state.model is not None
        else cold_start_estimate(source)
    )
    prediction.setdefault("unit", "days")
    prediction["method"] = "point"
    return prediction


def similar_projects(
    state: AppState, email_text: str, features: Mapping[str, Any] | None, k: int = 3
) -> list[dict[str, Any]]:
    """Top-k most similar **done** projects, enriched with ``title_hint``."""
    rows = load_rows(state.db_path)
    corpus = [
        row for row in rows if row.get("status") == "done" and str(row.get("email_text") or "").strip()
    ]
    hits = find_similar(email_text, corpus, k=k, query_features=features)
    by_id = {str(row["project_id"]): row for row in corpus}
    return [
        {
            **hit,
            "title_hint": title_hint(
                (by_id.get(str(hit.get("project_id"))) or {}).get("email_text")
            ),
        }
        for hit in hits
    ]


def collect_warnings(extraction: ExtractionResult, email_text: str) -> list[str]:
    """Extraction warnings + long-email + realtime/offline contradiction (deduped)."""
    warnings: list[str] = []
    for warning in list(extraction.warnings):
        if warning and warning not in warnings:
            warnings.append(warning)

    if len(email_text or "") > MAX_EMAIL_CHARS and WARN_LONG_EMAIL not in warnings:
        warnings.append(WARN_LONG_EMAIL)

    values = {finding.name: finding.value for finding in extraction.findings}
    if values.get("realtime_ui") and values.get("offline_mode") and WARN_CONFLICT not in warnings:
        warnings.append(WARN_CONFLICT)
    return warnings


def coefficient_view(state: AppState) -> list[dict[str, Any]]:
    """Contract coefficients: ``{feature, multiplier, sample_count}`` (+ extras).

    ``sample_count`` comes from the corrections table; while it is empty it is
    the count of done projects that have the feature (=1).
    """
    if state.model is not None:
        base = [{**item, "source": "learned"} for item in coefficients(state.model)]
    else:
        base = [
            {
                "feature": name,
                "multiplier": round(COLD_START_MULTIPLIERS[name], 3),
                "raw": None,
                "source": "cold_start",
            }
            for name in FEATURES
        ]
    counts = sample_counts(state)
    return [{**item, "sample_count": counts.get(item["feature"], 0)} for item in base]


def sample_counts(state: AppState) -> dict[str, int]:
    """Per-feature sample counts: corrections table first, else done counts."""
    conn = connect(state.db_path)
    try:
        correction_rows = conn.execute(
            "SELECT feature_name, sample_count FROM corrections"
        ).fetchall()
        if correction_rows:
            counts = {
                str(row["feature_name"]): int(row["sample_count"] or 0)
                for row in correction_rows
            }
        else:
            done_feature_rows = conn.execute(
                "SELECT f.name AS name, COUNT(*) AS n FROM features f "
                "JOIN projects p ON p.id = f.project_id "
                "WHERE p.status = 'done' AND f.value_binary = 1 GROUP BY f.name"
            ).fetchall()
            counts = {str(row["name"]): int(row["n"]) for row in done_feature_rows}
    finally:
        conn.close()
    return {name: counts.get(name, 0) for name in FEATURES}


def serialize_findings(extraction: ExtractionResult) -> list[dict[str, Any]]:
    """Findings with ``value`` cast to ``1 | 0 | null`` (contract shape)."""
    return [
        {
            "name": finding.name,
            "value": None if finding.value is None else int(finding.value),
            "confidence": round(float(finding.confidence), 3),
            "evidence_quote": finding.evidence_quote,
        }
        for finding in extraction.findings
    ]


# --------------------------------------------------------------------------- #
# Codebase Lab helpers (contract v0.2 ``repo`` -> ``codebase`` block)
# --------------------------------------------------------------------------- #


def demo_repos_dir() -> Path:
    """Directory holding the built demo repos (``ESTIMATOR_DEMO_REPOS_DIR`` wins).

    Read at call time (never cached at import) so tests can redirect it.
    """
    override = os.environ.get(CODEBASE_DEMO_REPOS_DIR_ENV)
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return REPO_ROOT / "data" / "demo_repos"


def codebase_repo_path(repo: str) -> Path:
    """Filesystem path for a validated ``repo`` value; builds demo repos on demand.

    The deterministic builder (``scripts/build_demo_repos.py``) runs once, in a
    subprocess with this interpreter and ``cwd=backend``, guarded by a
    process-wide lock so concurrent first requests cannot interleave git
    commands. Raises ``RuntimeError`` (Vietnamese detail) when it fails.
    """
    if repo == "self":
        return REPO_ROOT
    name = CODEBASE_DEMO_REPOS[repo]
    target = demo_repos_dir()
    path = target / name
    if path.exists():
        return path
    with _DEMO_REPOS_LOCK:
        if path.exists():  # another request built it while we waited
            return path
        script = _BACKEND_ROOT / "scripts" / "build_demo_repos.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--target", str(target)],
            cwd=str(_BACKEND_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=CODEBASE_BUILD_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0 or not path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            message = f"Không thể dựng repo demo {repo!r}"
            raise RuntimeError(f"{message}: {detail}" if detail else message)
    return path


def codebase_keywords(features: Mapping[str, Any] | None) -> list[str]:
    """Path keywords for ``find_similar_changes`` from PRESENT features (== 1).

    Documented mapping :data:`CODEBASE_FEATURE_KEYWORDS`; canonical feature
    order, first-seen de-duplication. When no feature is present the documented
    fallback set :data:`CODEBASE_FALLBACK_KEYWORDS` is used.
    """
    source = features or {}
    keywords: list[str] = []
    for name in FEATURES:
        if int(source.get(name) or 0) != 1:
            continue
        for keyword in CODEBASE_FEATURE_KEYWORDS.get(name, ()):
            if keyword not in keywords:
                keywords.append(keyword)
    return keywords or list(CODEBASE_FALLBACK_KEYWORDS)


def build_codebase_block(
    repo: str,
    features: Mapping[str, Any] | None,
    base_estimate: Mapping[str, Any],
) -> dict[str, Any]:
    """Contract v0.2 ``codebase`` block (docs/API.md) for one estimate.

    Collects leakage-guarded structural signals as of today, matches similar
    past commits on the feature-derived keywords, and applies friction (tail
    widening) + invasiveness (median shift) to a COPY of ``base_estimate``.
    Similar-change items are capped at the 5 newest and projected to the exact
    contract keys; when no commit matches, invasiveness is ``None`` and the
    median is unchanged (no evidence -> no fabricated shift).
    """
    repo_path = codebase_repo_path(repo)
    keywords = codebase_keywords(features)
    at_date = datetime.now(timezone.utc).date().isoformat()

    signals = collect_signals(repo_path, at_date=at_date)
    friction = compute_friction(signals)
    commits = find_similar_changes(repo_path, keywords, at_date=at_date, limit=10)
    invasiveness = estimate_invasiveness(commits)
    applied = apply_friction(base_estimate, friction, invasiveness)

    return {
        "repo": repo,
        "friction": {
            "score": friction["score"],
            "level": friction["level"],
            "components": friction["components"],
        },
        "invasiveness": (
            {
                "modified_ratio": invasiveness["modified_ratio"],
                "mean_files_touched": invasiveness["mean_files_touched"],
                "based_on_commits": invasiveness["based_on_commits"],
            }
            if invasiveness is not None
            else None
        ),
        "similar_changes": [
            {
                "commit": str(commit.get("commit") or "")[:7],
                "date": commit.get("date"),
                "files_touched": int(commit.get("files_touched") or 0),
                "new_files": int(commit.get("new_files") or 0),
                "modified_files": int(commit.get("modified_files") or 0),
            }
            for commit in commits[:5]
        ],
        "base_estimate": {**base_estimate, "unit": "days"},
        "adjusted_estimate": {**applied["estimate"], "unit": "days"},
        "adjustments": [dict(item) for item in applied["adjustments"]],
        "note": CODEBASE_NOTE,
    }


def build_estimate_payload(
    extraction: ExtractionResult,
    prediction: Mapping[str, Any],
    similar: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    coefficient_rows: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    project_id: str | None,
) -> dict[str, Any]:
    """Assemble the frozen ``POST /api/estimate`` response (extras allowed)."""
    return {
        "project_id": project_id,
        "findings": serialize_findings(extraction),
        "estimate": {**prediction, "unit": "days"},
        "similar_projects": [dict(item) for item in similar],
        "questions": [dict(item) for item in questions],
        "coefficients": [dict(item) for item in coefficient_rows],
        "warnings": list(warnings),
        # Extras (never replace a contract key): useful for the UI.
        "missing": list(extraction.missing),
        "provider": extraction.provider,
    }


def run_estimate_pipeline(
    state: AppState,
    email_text: str,
    persist: bool = True,
    answers: Mapping[str, Any] | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Full estimate pipeline for ``/api/estimate`` and scenario loading.

    extract -> (answers overlay) -> estimate -> (codebase adjustment) ->
    similar -> questions -> (persist new project row). ``persist`` is False for
    answer-refinement calls: contract v0.2 only creates a new P0nn row for a
    direct estimate call without ``answers``.

    With ``repo`` set (contract v0.2, Codebase Lab) the response gains the
    ``codebase`` block and the top-level ``estimate`` becomes the ADJUSTED
    estimate; answer-refinement calls re-apply the same repo logic.
    """
    extraction, _provider_name = extract_stage(state, email_text)
    extraction = apply_answers(extraction, answers)
    features = resolve_features(extraction)
    prediction = predict(state, features)

    codebase: dict[str, Any] | None = None
    if repo:
        codebase = build_codebase_block(repo, features, prediction)
        prediction = dict(codebase["adjusted_estimate"])

    similar = similar_projects(state, email_text, features, k=3)
    questions = rank_questions(state.model, extraction.findings, top_k=5)
    coefficient_rows = coefficient_view(state)
    warnings = collect_warnings(extraction, email_text)

    project_id: str | None = None
    if persist:
        project_id = persist_estimate(state, email_text, extraction, prediction)
    payload = build_estimate_payload(
        extraction, prediction, similar, questions, coefficient_rows, warnings, project_id
    )
    if codebase is not None:
        payload["codebase"] = codebase
    return payload


def run_packages(state: AppState, email_text: str, budget_days: float) -> dict[str, Any]:
    """Extraction pipeline -> budget-fit scope packages (no persistence).

    Uses the same extraction/feature resolution as ``/api/estimate`` so the
    packages are built from exactly the features the UI shows; unknown
    features stay unknown in every tier (see ``app.services.packages``).
    """
    if state.model is None:
        raise ValueError(PACKAGES_COLD_START_DETAIL)
    extraction, _provider_name = extract_stage(state, email_text)
    features = resolve_features(extraction)
    result = build_packages(state.model, features, float(budget_days))
    result["provider"] = extraction.provider
    return result


# --------------------------------------------------------------------------- #
# Persistence helpers
# --------------------------------------------------------------------------- #


def next_project_id(conn: Any) -> str:
    """Next ``P0nn`` id: max numeric suffix over existing ids + 1."""
    highest = 0
    for row in conn.execute("SELECT project_id FROM projects").fetchall():
        match = re.fullmatch(r"P(\d+)", str(row["project_id"] or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"P{highest + 1:03d}"


def persist_estimate(
    state: AppState,
    email_text: str,
    extraction: ExtractionResult,
    prediction: Mapping[str, Any],
) -> str:
    """Insert the estimated project + 15 feature rows + one ``estimates`` row."""
    conn = connect(state.db_path)
    try:
        project_id = next_project_id(conn)
        cursor = conn.execute(
            "INSERT INTO projects "
            "(project_id, date, email_text, actual_days, team_estimate, status, is_synthetic) "
            "VALUES (?, ?, ?, NULL, NULL, 'pending', 0)",
            (project_id, date.today().isoformat(), email_text),
        )
        internal_id = int(cursor.lastrowid)
        conn.executemany(
            "INSERT INTO features (project_id, name, value_binary, value_prob, evidence_quote) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    internal_id,
                    finding.name,
                    None if finding.value is None else int(finding.value),
                    float(finding.confidence),
                    finding.evidence_quote,
                )
                for finding in extraction.findings
            ],
        )
        conn.execute(
            "INSERT INTO estimates (project_id, p10, p50, p90, model_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                internal_id,
                prediction["p10"],
                prediction["p50"],
                prediction["p90"],
                LIVE_MODEL_VERSION,
                now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return project_id


def title_hint(email_text: str | None, length: int = 60) -> str:
    """Short human hint for a project row: skip greeting, collapse, truncate."""
    raw = str(email_text or "").strip()
    if not raw:
        return ""
    first_line, _, rest = raw.partition("\n")
    # Drop a short greeting line ("Dear team,", "Greetings,", "Chào đội ngũ,").
    if rest and len(first_line.strip()) <= 30 and first_line.strip().endswith((",", ":")):
        raw = rest
    collapsed = " ".join(raw.split())
    if len(collapsed) <= length:
        return collapsed
    return collapsed[:length].rstrip() + "..."


def project_row_payload(row: Mapping[str, Any], system: Mapping[str, Any] | None) -> dict[str, Any]:
    """One ``GET /api/projects`` row: contract keys + extras."""
    team_estimate = row.get("team_estimate")
    system_p50 = system.get("p50") if system else None
    actual_days = row.get("actual_days")

    delta_pct = None
    if system_p50 is not None and team_estimate not in (None, 0):
        delta_pct = round((float(system_p50) - float(team_estimate)) / float(team_estimate) * 100.0, 1)

    actual_vs_system_pct = None
    if actual_days is not None and system_p50:
        actual_vs_system_pct = round(
            (float(actual_days) - float(system_p50)) / float(system_p50) * 100.0, 1
        )

    return {
        "project_id": row.get("project_id"),
        "date": row.get("date"),
        "status": row.get("status"),
        "team_estimate": team_estimate,
        "system_p10": system.get("p10") if system else None,
        "system_p50": system_p50,
        "system_p90": system.get("p90") if system else None,
        "system_source": system.get("source") if system else None,
        "actual_days": actual_days,
        "delta_pct": delta_pct,
        "features": {
            name: (None if row.get("features", {}).get(name) is None else int(row["features"][name]))
            for name in FEATURES
        },
        "summary": title_hint(row.get("email_text")),
        "is_synthetic": row.get("is_synthetic", 1),
        "in_interval": system.get("in_interval") if system else None,
        # Extra convenience for the History table (system P50 vs actual).
        "actual_vs_system_pct": actual_vs_system_pct,
    }


# --------------------------------------------------------------------------- #
# Learning loop (POST /api/projects/{id}/actual)
# --------------------------------------------------------------------------- #


def current_system_prediction(
    state: AppState, project_id: str, features: Mapping[str, Any]
) -> dict[str, Any]:
    """The system's best prior prediction for a project (for the learning loop)."""
    stored = latest_estimates(state.db_path).get(project_id)
    if stored and stored.get("p50") is not None:
        return {**stored, "mode": "stored"}
    cached = state.history_cache.get(project_id)
    if cached and cached.get("p50") is not None:
        return {**cached, "mode": "replay"}
    return predict(state, features)


def coefficient_snapshot(
    state: AppState,
    model_before: EstimatorModel | None,
    project_features: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, int]]:
    """(current multipliers, sample counts *before* this project) for the update.

    Current multipliers: corrections table when populated (source of truth
    after the first actual), else the pre-retrain model's learned multipliers,
    else the cold-start defaults. Sample-count basis: count of done projects
    with the feature = 1, excluding this project (it was just marked done).
    """
    conn = connect(state.db_path)
    try:
        correction_rows = conn.execute(
            "SELECT feature_name, coefficient, sample_count FROM corrections"
        ).fetchall()
        done_feature_rows = conn.execute(
            "SELECT f.name AS name, COUNT(*) AS n FROM features f "
            "JOIN projects p ON p.id = f.project_id "
            "WHERE p.status = 'done' AND f.value_binary = 1 GROUP BY f.name"
        ).fetchall()
    finally:
        conn.close()
    done_counts = {str(row["name"]): int(row["n"]) for row in done_feature_rows}

    if correction_rows:
        current = {
            str(row["feature_name"]): float(row["coefficient"]) for row in correction_rows
        }
        counts = {
            str(row["feature_name"]): int(row["sample_count"] or 0) for row in correction_rows
        }
    else:
        if model_before is not None:
            current = {item["feature"]: float(item["multiplier"]) for item in coefficients(model_before)}
        else:
            current = {name: float(COLD_START_MULTIPLIERS[name]) for name in FEATURES}
        counts = {}

    for name in FEATURES:
        if name not in counts:
            present = 1 if project_features.get(name) else 0
            counts[name] = max(0, done_counts.get(name, 0) - present)
        current.setdefault(name, 1.0)
    return current, counts


def persist_corrections(state: AppState, new_coefficients: Mapping[str, float], new_counts: Mapping[str, int]) -> None:
    """Upsert the corrections table (one row per canonical feature)."""
    stamp = now_iso()
    conn = connect(state.db_path)
    try:
        for name in FEATURES:
            coefficient = float(new_coefficients.get(name, 1.0))
            count = int(new_counts.get(name, 0))
            updated = conn.execute(
                "UPDATE corrections SET coefficient = ?, sample_count = ?, updated_at = ? "
                "WHERE feature_name = ?",
                (coefficient, count, stamp, name),
            )
            if updated.rowcount == 0:
                conn.execute(
                    "INSERT INTO corrections (feature_name, coefficient, sample_count, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (name, coefficient, count, stamp),
                )
        conn.commit()
    finally:
        conn.close()


def compute_accuracy(state: AppState, actual_days: float, predicted_p50: float) -> dict[str, Any]:
    """``{mae_before, mae_after, coverage_pct}`` for the learning loop.

    Documented choice: ``mae_before`` is the cached replay MAE; ``mae_after``
    is recomputed with ``accuracy_metrics`` over the cached replay steps **plus
    this project's point error** (coverage stays interval-based from the replay).
    """
    cached = state.replay_cache.get(DEFAULT_MIN_TRAIN) or {}
    steps = cached.get("steps") or []
    replay_rows = [
        {
            "actual_days": step["actual"],
            "p50": step["p50"],
            "p10": step["p10"],
            "p90": step["p90"],
        }
        for step in steps
    ]
    metrics = accuracy_metrics(
        replay_rows + [{"actual_days": float(actual_days), "p50": float(predicted_p50)}]
    )
    return {
        "mae_before": (cached.get("summary") or {}).get("mae_system"),
        "mae_after": metrics["mae"],
        "coverage_pct": metrics["coverage_pct"],
    }


def apply_actual(state: AppState, project_id: str, actual_days: float) -> dict[str, Any] | None:
    """Record an actual duration: retrain, update coefficients, measure accuracy.

    Returns ``None`` when the project does not exist (route -> 404).
    """
    rows = load_rows(state.db_path)
    row = next((item for item in rows if item["project_id"] == project_id), None)
    if row is None:
        return None

    features = row.get("features") or {}
    model_before = state.model
    prediction = current_system_prediction(state, project_id, features)
    warning = WARN_BIG_ACTUAL if actual_days > 1000 else None

    conn = connect(state.db_path)
    try:
        conn.execute(
            "UPDATE projects SET actual_days = ?, status = 'done' WHERE project_id = ?",
            (float(actual_days), project_id),
        )
        conn.commit()
    finally:
        conn.close()

    rows_after = load_rows(state.db_path)
    retrain_failed = not fit_model(state, rows_after, keep_old=True)
    retrain_warning = (
        "Không thể train lại model với dữ liệu hiện có; giữ model cũ" if retrain_failed else None
    )

    current, counts = coefficient_snapshot(state, model_before, features)
    updated_row = {**row, "actual_days": float(actual_days), "status": "done"}
    new_coefficients, new_counts, updates = update_coefficients(
        current, updated_row, float(prediction["p50"]), sample_counts=counts
    )
    persist_corrections(state, new_coefficients, new_counts)

    accuracy = compute_accuracy(state, actual_days, float(prediction["p50"]))

    # Refresh the walk-forward replay/caches so History and /api/replay reflect
    # the new sample (mirror estimates are rewritten, see refresh_replay).
    refresh_replay(state, min_train=DEFAULT_MIN_TRAIN, persist=True)

    refreshed = next(item for item in load_rows(state.db_path) if item["project_id"] == project_id)
    project_payload = project_row_payload(
        refreshed, system_estimates(state, [refreshed]).get(project_id)
    )
    warnings = [item for item in (warning, retrain_warning) if item]
    return {
        "project": project_payload,
        "coefficient_updates": [
            {
                "feature": update["feature"],
                "old": round(float(update["old"]), 4),
                "new": round(float(update["new"]), 4),
                "n": int(update["n"]),
                "sample_count": int(update["n"]),
            }
            for update in updates
        ],
        "accuracy": accuracy,
        "warning": warning,
        "warnings": warnings,
        "predicted_days": float(prediction["p50"]),
    }


# --------------------------------------------------------------------------- #
# CSV import (POST /api/import)
# --------------------------------------------------------------------------- #


def _optional_float(value: Any) -> float | None:
    """NaN/None -> None, otherwise float."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _feature_value(value: Any) -> int | None:
    """Coerce a CSV feature cell to 0/1; None for NaN (treated as absent)."""
    if value is None or pd.isna(value):
        return 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes"}:
            return 1
        if token in {"0", "false", "no", ""}:
            return 0
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def import_csv(state: AppState, data: bytes) -> dict[str, Any]:
    """Parse a canonical CSV, insert valid new rows, retrain on success.

    Returns ``{imported, skipped, errors}``. Raises ``ValueError`` when the
    payload is not a readable CSV or misses canonical columns (route -> 422).
    """
    if not data:
        raise ValueError("File CSV rỗng")
    try:
        frame = pd.read_csv(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Không đọc được file CSV: {exc}") from exc

    missing = [column for column in IMPORT_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"CSV thiếu cột bắt buộc: {', '.join(missing)}")

    imported = 0
    skipped = 0
    errors: list[str] = []
    seen: set[str] = set()
    conn = connect(state.db_path)
    try:
        existing = {
            str(row["project_id"]) for row in conn.execute("SELECT project_id FROM projects")
        }
        for index, row in enumerate(frame.to_dict("records"), start=1):
            project_id = str(row.get("project_id") or "").strip()
            if not project_id:
                skipped += 1
                errors.append(f"row {index}: thiếu project_id")
                continue
            if project_id in existing or project_id in seen:
                skipped += 1
                errors.append(f"row {index}: project_id {project_id} đã tồn tại")
                continue

            status = str(row.get("status") or "").strip()
            if status not in VALID_STATUSES:
                skipped += 1
                errors.append(f"row {index}: status không hợp lệ ({status!r})")
                continue

            actual_days = _optional_float(row.get("actual_days"))
            if status == "done" and (actual_days is None or actual_days <= 0):
                skipped += 1
                errors.append(f"row {index}: actual_days không hợp lệ cho dự án done")
                continue
            if status != "done":
                actual_days = None

            feature_values: dict[str, int] = {}
            invalid_feature: str | None = None
            for name in FEATURES:
                parsed = _feature_value(row.get(f"feat_{name}"))
                if parsed is None:
                    invalid_feature = name
                    break
                feature_values[name] = parsed
            if invalid_feature is not None:
                skipped += 1
                errors.append(f"row {index}: feat_{invalid_feature} phải là 0 hoặc 1")
                continue

            cursor = conn.execute(
                "INSERT INTO projects "
                "(project_id, date, email_text, actual_days, team_estimate, status, is_synthetic) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    str(row.get("date") or "") or None,
                    str(row.get("email_text") or ""),
                    actual_days,
                    _optional_float(row.get("team_estimate")),
                    status,
                    int(_optional_float(row.get("is_synthetic")) or 0),
                ),
            )
            internal_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO features (project_id, name, value_binary, value_prob, evidence_quote) "
                "VALUES (?, ?, ?, 1.0, NULL)",
                [(internal_id, name, feature_values[name]) for name in FEATURES],
            )
            seen.add(project_id)
            imported += 1
        conn.commit()
    finally:
        conn.close()

    if imported:
        rows = load_rows(state.db_path)
        fit_model(state, rows, keep_old=True)
        refresh_replay(state, min_train=DEFAULT_MIN_TRAIN, persist=True)

    return {"imported": imported, "skipped": skipped, "errors": errors}
