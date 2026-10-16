"""FastAPI application factory for The Estimator.

Run locally (offline stub provider):
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Startup (lifespan) resolves the SQLite path, seeds the synthetic history on an
empty database, trains the model and runs the walk-forward replay once; see
``app.api.state.bootstrap``. CORS origins come from ``CORS_ORIGINS`` (default
``http://localhost:3000``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.state import AppState, bootstrap
from app.settings import get_settings, resolve_db_path

logger = logging.getLogger(__name__)

GENERIC_ERROR_DETAIL = "Lỗi hệ thống, vui lòng thử lại"


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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Errors never leak stack traces; always the standard {"detail"} shape."""
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR_DETAIL})

    @app.get("/")
    def root() -> dict[str, str]:
        """Tiny landing payload for humans poking the server with curl."""
        return {"name": "The Estimator API", "health": "/api/health", "docs": "/docs"}

    return app


app = create_app()
