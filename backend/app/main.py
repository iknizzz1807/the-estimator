"""FastAPI application factory for The Estimator.

Run locally (offline stub provider):
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Startup (lifespan) resolves the SQLite path, seeds the synthetic history on an
empty database, trains the model and runs the walk-forward replay once; see
``app.api.state.bootstrap``. CORS origins come from ``CORS_ORIGINS`` (default
``http://localhost:3000``).

Single-service deploy: when the statically-exported frontend exists
(``frontend/out``, produced by ``cd frontend && npm run build``), it is mounted
at ``/`` so one process serves both ``/api/*`` and the UI on a single port.
Without the export the app runs API-only (JSON landing payload at ``/``).
"""

from __future__ import annotations

import logging
import stat as stat_module
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from app.api.routes import router
from app.api.state import AppState, bootstrap
from app.settings import get_settings, resolve_db_path

logger = logging.getLogger(__name__)

GENERIC_ERROR_DETAIL = "Lỗi hệ thống, vui lòng thử lại"

#: Statically-exported frontend (``next build`` with ``output: "export"``).
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "out"


class StaticExportFiles(StaticFiles):
    """``StaticFiles(html=True)`` that also resolves extensionless page URLs.

    Next's static export writes pages as ``estimate.html`` (``trailingSlash:
    false``). Plain StaticFiles would 404 ``/estimate`` (or serve the 404 page),
    because it only maps ``/`` and directory/``index.html`` pairs. This class
    retries a miss as ``<path>.html`` before falling back to Next's ``404.html``.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response: Response | None = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = None
        if (
            (response is None or response.status_code == 404)
            and path
            and not path.endswith(".html")
        ):
            full_path, stat_result = await anyio.to_thread.run_sync(
                self.lookup_path, f"{path}.html"
            )
            if stat_result is not None and stat_module.S_ISREG(stat_result.st_mode):
                return self.file_response(full_path, stat_result, scope)
        if response is None:
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        return response


def create_app() -> FastAPI:
    """Build the FastAPI app (one call per process; tests build their own)."""
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db_path = resolve_db_path(settings)
        state = AppState(db_path=db_path)
        try:
            bootstrap(state)
        except Exception:  # pragma: no cover - defensive: serve degraded, not dead
            logger.exception("Startup bootstrap failed - serving in degraded mode")
        # Always expose a state object so handlers can answer even after a
        # partial bootstrap (cold-start behaviour instead of 500s).
        app.state.estimator = state
        logger.info(
            "The Estimator API ready (db=%s, provider=%s, model_loaded=%s)",
            db_path,
            state.llm_provider_name,
            state.model_loaded,
        )
        yield

    app = FastAPI(
        title="The Estimator API",
        version="0.1.0",
        description="Effort estimation from past projects, not vibes.",
        lifespan=lifespan,
    )

    origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    # Unknown /api/* paths must stay JSON and never fall through to the
    # frontend mount; real /api routes are matched earlier (route order).
    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Errors never leak stack traces; always the standard {"detail"} shape."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR_DETAIL})

    if FRONTEND_DIST.is_dir():
        # Single-service deploy: one port serves the API and the static export
        # (Next's own 404.html acts as the miss page). Checked at create time
        # so tests / API-only runs without a frontend build keep working.
        app.mount(
            "/",
            StaticExportFiles(directory=str(FRONTEND_DIST), html=True),
            name="frontend",
        )
        logger.info("Serving static frontend export from %s", FRONTEND_DIST)
    else:

        @app.get("/")
        def root() -> dict[str, str]:
            """Tiny landing payload for humans poking the server with curl."""
            return {"name": "The Estimator API", "health": "/api/health", "docs": "/docs"}

    return app


app = create_app()
