"""FastAPI app factory for the orchestrator service.

This module centralizes common FastAPI wiring (middleware, router inclusion,
OpenAPI customization) so entrypoints remain thin and we avoid drift between
main modules.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable, Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from brain_researcher.services.shared.api_version import API_VERSION, set_api_version
from brain_researcher.services.shared.settings import get_settings
from brain_researcher.services.shared.trace_headers import get_trace_id, set_trace_headers

from . import env as env_module
from . import metrics as metrics_module

logger = logging.getLogger(__name__)


def _include_optional_routers(app: FastAPI, routers: Iterable[Optional[APIRouter]]) -> None:
    for router in routers:
        if router is not None:
            app.include_router(router)


def _configure_openapi(app: FastAPI) -> None:
    @app.get("/api/openapi.json", include_in_schema=False)
    async def openapi_alias():
        """Expose OpenAPI under `/api` for public route consistency."""

        return app.openapi()

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("info", {})["x-api-version"] = API_VERSION
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = _custom_openapi


def _configure_trace_middleware(app: FastAPI, log: logging.Logger) -> None:
    @app.middleware("http")
    async def add_trace_id(request: Request, call_next):
        trace_id = get_trace_id(request.headers) or f"br-trace-{uuid.uuid4().hex[:12]}"
        request.state.trace_id = trace_id
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        set_trace_headers(response.headers, trace_id)
        set_api_version(response.headers)
        log.info(
            "trace_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            trace_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


def create_app(
    *,
    title: str,
    description: str,
    version: str,
    allowed_origins: list[str],
    lifespan=None,
    optional_routers: Iterable[Optional[APIRouter]] = (),
    trace_logger: Optional[logging.Logger] = None,
) -> FastAPI:
    """Create and configure the orchestrator FastAPI app."""

    app = FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=lifespan,
    )
    app.state.settings = get_settings()

    _configure_openapi(app)
    _configure_trace_middleware(app, trace_logger or logger)

    # Import modules (not symbols) so importlib.reload() in tests affects behavior.
    try:
        env_module.get_metrics_enabled.cache_clear()
    except AttributeError:
        pass
    metrics_enabled = env_module.get_metrics_enabled()
    metrics_collector = metrics_module.init_metrics(enabled=metrics_enabled)
    app.state.metrics = metrics_collector

    _include_optional_routers(app, optional_routers)

    # Cache management endpoints (P2.5)
    try:
        from .cache_api import router as cache_router
    except Exception as exc:
        logger.debug("Cache API router not available: %s", exc)
    else:
        app.include_router(cache_router)

    # Metrics endpoint (P5.11)
    if metrics_enabled:
        app.include_router(metrics_collector.get_router(), tags=["metrics"])

    # Configure CORS last (keeps middleware stack consistent with legacy entrypoints).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app
