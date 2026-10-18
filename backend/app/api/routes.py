"""HTTP routes for The Estimator API — contract frozen in docs/API.md.

Errors use FastAPI's standard ``{"detail": "..."}`` shape; validation
messages for business rules are Vietnamese (spec §9: "Vui lòng paste email",
"Giá trị bất thường, vui lòng kiểm tra lại").
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, AsyncIterator

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api import state as state_mod
from app.features import FEATURES
from app.scenarios import get_scenario, list_scenarios
from app.services.ab import ab_compare
from app.services.extraction import extract_features
from app.services.voi import rank_questions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

#: Spec §9 empty-email guard (same message the extraction service raises).
EMPTY_EMAIL_DETAIL = "Vui lòng paste email"

#: SSE step messages, in the order emitted (docs/API.md §/estimate/stream).
STEP_MESSAGES: dict[str, str] = {
    "extracting": "Đang trích xuất 15 features từ email...",
    "validating": "Đang kiểm tra evidence và mâu thuẫn...",
    "similar": "Đang tìm dự án tương tự...",
    "estimating": "Đang tính khoảng P10/P50/P90...",
    "questions": "Đang xếp hạng thông tin còn thiếu...",
    "done": "Hoàn tất",
}
STEP_ORDER = ["extracting", "validating", "similar", "estimating", "questions", "done"]

#: Tiny pause between SSE events so the UI can paint each step; the whole
#: stream still finishes in ~0.3s and stays deterministic.
STREAM_STEP_PAUSE_SECONDS = 0.05

MAX_AB_CALLS = 50


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class EstimateRequest(BaseModel):
    """Body of ``POST /api/estimate`` and ``POST /api/estimate/stream``.

    Contract v0.2: optional ``answers`` ({feature: 0|1}) overlay the extracted
    findings; answer-refinement calls are side-effect free (no new project row).
    Optional ``repo`` ("demo_a" | "demo_b" | "self") attaches the Codebase Lab
    block and makes the top-level ``estimate`` the ADJUSTED estimate.
    """

    email_text: str = ""
    answers: dict[str, int] | None = None
    repo: str | None = None


class PackagesRequest(BaseModel):
    """Body of ``POST /api/packages`` (contract v0.2)."""

    email_text: str = ""
    budget_days: float | None = None


class ActualRequest(BaseModel):
    """Body of ``POST /api/projects/{project_id}/actual``."""

    actual_days: float


class AbRequest(BaseModel):
    """Body of ``POST /api/ab`` (spec §4.5, default n=10).

    ``history_n`` sizes the v0.2 LLM-with-history baseline (default 3).
    """

    email_text: str = ""
    n: int = 10
    history_n: int = 3


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def get_state(request: Request) -> state_mod.AppState:
    """Runtime state attached to the app by the lifespan handler."""
    state = getattr(request.app.state, "estimator", None)
    if state is None:  # pragma: no cover - lifespan always sets it
        raise HTTPException(status_code=503, detail="Hệ thống đang khởi động, vui lòng thử lại")
    return state


def _require_email(email_text: str) -> str:
    """422 with the spec §9 message when the input is empty/whitespace."""
    if not email_text or not email_text.strip():
        raise HTTPException(status_code=422, detail=EMPTY_EMAIL_DETAIL)
    return email_text


def _sse(event: str, data: dict[str, Any]) -> str:
    """Serialize one Server-Sent Event (single-line JSON payload)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_feature_filters(raw_filters: list[str] | None) -> list[tuple[str, int]]:
    """Parse ``?feature=name`` / ``?feature=name=1`` / ``?feature=name=0``."""
    parsed: list[tuple[str, int]] = []
    for raw in raw_filters or []:
        name, _, value = raw.partition("=")
        name = name.strip()
        if name not in FEATURES:
            raise HTTPException(status_code=422, detail=f"Feature không hợp lệ: {name}")
        value = value.strip()
        if value in ("", "1"):
            parsed.append((name, 1))
        elif value == "0":
            parsed.append((name, 0))
        else:
            raise HTTPException(status_code=422, detail=f"Giá trị filter feature không hợp lệ: {raw}")
    return parsed


def _parse_answers(answers: dict[str, int] | None) -> dict[str, int]:
    """Validate/normalize the v0.2 ``answers`` map (canonical names, values 0/1)."""
    if not answers:
        return {}
    parsed: dict[str, int] = {}
    for name, value in answers.items():
        if name not in FEATURES:
            raise HTTPException(status_code=422, detail=f"Feature không hợp lệ: {name}")
        if int(value) not in (0, 1):
            raise HTTPException(
                status_code=422,
                detail=f"answers[{name}] phải là 0 hoặc 1 (nhận được {value!r})",
            )
        parsed[name] = int(value)
    return parsed


def _parse_repo(repo: str | None) -> str | None:
    """Validate the v0.2 ``repo`` selector (absent passes through unchanged).

    Accepts the built-in choices plus a pasted public GitHub repo
    (``https://github.com/<owner>/<repo>`` or the ``<owner>/<repo>`` shorthand),
    canonicalised to ``gh:<owner>/<repo>``. Anything else is a 422.
    """
    if repo is None:
        return None
    try:
        return state_mod.normalize_repo_selector(repo)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"repo không hợp lệ: {repo!r} — chấp nhận demo_a, demo_b, self, "
                "hoặc URL repo công khai dạng https://github.com/<owner>/<repo>"
            ),
        ) from None


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Service status: model, effective LLM provider and project count."""
    state = get_state(request)
    return {
        "status": "ok",
        "model_loaded": state.model_loaded,
        "llm_provider": state.llm_provider_name,
        "projects_count": state.project_count(),
        # Extras for the UI (never replace contract keys).
        "mode": "calibrated" if state.model_loaded else "cold_start",
        "n_train": state.model.n_train if state.model is not None else 0,
        # Codebase Lab capabilities so the UI never offers a broken option
        # (DECISIONS D17/D20: cloud builds have no .git, so "self" is absent).
        "codebase": {
            "choices": list(state_mod.CODEBASE_REPO_CHOICES),
            "self_available": state_mod.self_repo_available(),
            "url_clone": True,
            # Pre-cloned example repos present on this host (empty when the image
            # was built without them) — clickable, instant, no URL to paste.
            "examples": state_mod.available_examples(),
        },
    }


# --------------------------------------------------------------------------- #
# Estimate
# --------------------------------------------------------------------------- #


@router.post("/estimate")
def estimate_endpoint(payload: EstimateRequest, request: Request) -> dict[str, Any]:
    """Full pipeline: extract -> answers overlay -> estimate -> similar -> questions.

    Contract v0.2: a direct call without ``answers`` persists a new project
    row; answer-refinement calls (non-empty ``answers``) are side-effect free.
    Optional ``repo`` attaches the Codebase Lab block (adjusted estimate).
    """
    state = get_state(request)
    email_text = _require_email(payload.email_text)
    answers = _parse_answers(payload.answers)
    repo = _parse_repo(payload.repo)
    try:
        return state_mod.run_estimate_pipeline(
            state, email_text, persist=not answers, answers=answers, repo=repo
        )
    except RuntimeError as exc:  # demo-repo build / unreadable checkout
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _stream_estimate(
    state: state_mod.AppState,
    email_text: str,
    answers: dict[str, int] | None = None,
    persist: bool = True,
    repo: str | None = None,
) -> AsyncIterator[str]:
    """Yield ``step`` events in contract order, then the final ``result``."""
    try:
        yield _sse("step", {"step": "extracting", "message": STEP_MESSAGES["extracting"]})
        extraction, _provider = await run_in_threadpool(state_mod.extract_stage, state, email_text)
        extraction = state_mod.apply_answers(extraction, answers)
        await asyncio.sleep(STREAM_STEP_PAUSE_SECONDS)

        yield _sse("step", {"step": "validating", "message": STEP_MESSAGES["validating"]})
        features = state_mod.resolve_features(extraction)
        warnings = state_mod.collect_warnings(extraction, email_text)
        await asyncio.sleep(STREAM_STEP_PAUSE_SECONDS)

        yield _sse("step", {"step": "similar", "message": STEP_MESSAGES["similar"]})
        similar = await run_in_threadpool(
            state_mod.similar_projects, state, email_text, features, 3
        )
        await asyncio.sleep(STREAM_STEP_PAUSE_SECONDS)

        yield _sse("step", {"step": "estimating", "message": STEP_MESSAGES["estimating"]})
        prediction = state_mod.predict(state, features)
        codebase: dict[str, Any] | None = None
        codebase_error: str | None = None
        if repo:
            try:
                codebase = await run_in_threadpool(
                    state_mod.build_codebase_block, repo, features, prediction
                )
                prediction = dict(codebase["adjusted_estimate"])
            except RuntimeError as exc:
                # Never fail the whole stream for an optional context block.
                codebase_error = str(exc)
                logger.warning("Codebase Lab unavailable for %r: %s", repo, exc)
        await asyncio.sleep(STREAM_STEP_PAUSE_SECONDS)

        yield _sse("step", {"step": "questions", "message": STEP_MESSAGES["questions"]})
        questions = await run_in_threadpool(rank_questions, state.model, extraction.findings, 5)
        await asyncio.sleep(STREAM_STEP_PAUSE_SECONDS)

        yield _sse("step", {"step": "done", "message": STEP_MESSAGES["done"]})
        coefficient_rows = state_mod.coefficient_view(state)
        project_id: str | None = None
        if persist:
            project_id = await run_in_threadpool(
                state_mod.persist_estimate, state, email_text, extraction, prediction
            )
        payload = state_mod.build_estimate_payload(
            extraction, prediction, similar, questions, coefficient_rows, warnings, project_id
        )
        if codebase is not None:
            payload["codebase"] = codebase
        if codebase_error is not None:
            payload["codebase_error"] = codebase_error
        yield _sse("result", payload)
    except Exception as exc:  # keep the stream well-formed even on failure
        logger.exception("SSE estimate failed")
        yield _sse("error", {"detail": str(exc) or "Có lỗi xảy ra, vui lòng thử lại"})


@router.post("/estimate/stream")
async def estimate_stream_endpoint(payload: EstimateRequest, request: Request) -> StreamingResponse:
    """SSE variant of ``/api/estimate`` (same input, incl. v0.2 ``answers``/``repo``)."""
    state = get_state(request)
    email_text = _require_email(payload.email_text)
    answers = _parse_answers(payload.answers)
    repo = _parse_repo(payload.repo)
    return StreamingResponse(
        _stream_estimate(state, email_text, answers=answers, persist=not answers, repo=repo),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Demo data reset (contract v0.2)
# --------------------------------------------------------------------------- #


@router.post("/reset")
def reset_endpoint(request: Request) -> dict[str, Any]:
    """Reseed the demo DB to the pristine synthetic history (retrain + cache)."""
    state = get_state(request)
    return state_mod.reset_demo_db(state)


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


@router.get("/projects")
def list_projects(
    request: Request,
    status: str | None = Query(default=None),
    feature: list[str] | None = Query(default=None),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> list[dict[str, Any]]:
    """All projects with features + system interval + delta vs team estimate."""
    state = get_state(request)
    feature_filters = _parse_feature_filters(feature)

    rows = sorted(
        state_mod.load_rows(state.db_path),
        key=lambda row: (str(row.get("date") or ""), str(row.get("project_id") or "")),
    )
    estimates = state_mod.system_estimates(state, rows)

    result: list[dict[str, Any]] = []
    for row in rows:
        if status and row.get("status") != status:
            continue
        if date_from and str(row.get("date") or "") < date_from:
            continue
        if date_to and str(row.get("date") or "") > date_to:
            continue
        row_features = row.get("features") or {}
        if any(int(bool(row_features.get(name))) != want for name, want in feature_filters):
            continue
        result.append(
            state_mod.project_row_payload(row, estimates.get(str(row["project_id"])))
        )
    return result


@router.post("/projects/{project_id}/actual")
def submit_actual(project_id: str, payload: ActualRequest, request: Request) -> dict[str, Any]:
    """Record the real duration: retrain + coefficient update + accuracy."""
    state = get_state(request)
    if payload.actual_days <= 0 or not math.isfinite(payload.actual_days):
        raise HTTPException(
            status_code=422,
            detail="actual_days phải lớn hơn 0 (số ngày thực tế không hợp lệ)",
        )
    result = state_mod.apply_actual(state, project_id, float(payload.actual_days))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy dự án {project_id}")
    return result


# --------------------------------------------------------------------------- #
# Packages (budget-fit scope, contract v0.2)
# --------------------------------------------------------------------------- #


@router.post("/packages")
def packages_endpoint(payload: PackagesRequest, request: Request) -> dict[str, Any]:
    """Budget-fit scope packages from the extracted features (no persistence)."""
    state = get_state(request)
    email_text = _require_email(payload.email_text)
    budget_days = payload.budget_days
    if (
        budget_days is None
        or not math.isfinite(float(budget_days))
        or float(budget_days) <= 0
    ):
        raise HTTPException(status_code=422, detail="budget_days phải là số ngày lớn hơn 0")
    if state.model is None:
        raise HTTPException(status_code=409, detail=state_mod.PACKAGES_COLD_START_DETAIL)
    try:
        return state_mod.run_packages(state, email_text, float(budget_days))
    except ValueError as exc:  # defensive: cold start between the check and the call
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


@router.get("/replay")
def get_replay(
    request: Request,
    min_train: int = Query(default=state_mod.DEFAULT_MIN_TRAIN, ge=5, le=1000),
) -> dict[str, Any]:
    """Walk-forward replay: cached for min_train=10, recomputed otherwise."""
    state = get_state(request)
    cached = state.replay_cache.get(min_train)
    if cached is None:
        cached = state_mod.refresh_replay(
            state, min_train=min_train, persist=(min_train == state_mod.DEFAULT_MIN_TRAIN)
        )
    return {"steps": cached["steps"], "summary": cached["summary"], "min_train": min_train}


# --------------------------------------------------------------------------- #
# A/B comparison
# --------------------------------------------------------------------------- #


@router.post("/ab")
def ab_endpoint(payload: AbRequest, request: Request) -> dict[str, Any]:
    """LLM-only spread vs the system estimate + v0.2 LLM-with-history baseline."""
    state = get_state(request)
    email_text = _require_email(payload.email_text)
    calls = max(1, min(int(payload.n or 10), MAX_AB_CALLS))
    history_calls = max(1, min(int(payload.history_n or 3), MAX_AB_CALLS))

    extraction = extract_features(email_text, provider=(state.provider, state.llm_provider_name))
    features = state_mod.resolve_features(extraction)
    system = state_mod.predict(state, features)
    history_rows = state_mod.recent_done_rows(state)
    try:
        result = ab_compare(
            email_text,
            provider=state.provider,
            system_estimate=system["p50"],
            n=calls,
            history_rows=history_rows,
            history_n=history_calls,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["system_mode"] = system["mode"]
    return result


# --------------------------------------------------------------------------- #
# CSV import
# --------------------------------------------------------------------------- #


@router.post("/import")
async def import_endpoint(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    """Multipart canonical-CSV upload -> ``{imported, skipped, errors}``."""
    state = get_state(request)
    data = await file.read()
    try:
        return await run_in_threadpool(state_mod.import_csv, state, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Demo scenarios
# --------------------------------------------------------------------------- #


@router.get("/scenarios")
def scenarios_endpoint() -> list[dict[str, str]]:
    """The 3 built-in demo scenarios for the 1-click "Load Sample Data"."""
    return list_scenarios()


@router.post("/scenarios/{scenario_id}/load")
def load_scenario_endpoint(scenario_id: str, request: Request) -> dict[str, Any]:
    """Run the full estimate pipeline on a scenario (same shape as /estimate)."""
    state = get_state(request)
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy scenario {scenario_id}")
    return state_mod.run_estimate_pipeline(state, scenario["email_text"], persist=True)
