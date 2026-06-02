"""
Legacy ASGI gateway that exposes the Flask agent HTTP API plus a narrow set of
legacy compatibility routes on the same port.

This module is no longer the canonical runtime path. The active topology is
split services (web, agent, orchestrator, br_kg). A separate legacy full reverse-proxy gateway lives under `brain_researcher.legacy.api_gateway`.
The retired orchestrator-compatibility flow is gone: this app no longer mounts the
Orchestrator HTTP API under `/orchestrator`.

Why it still exists: older demos and compatibility tests may still need a
single-process facade while the active product runtime no longer does. The
canonical legacy owner now lives under `brain_researcher.legacy.gateway`. Run with:

    uvicorn brain_researcher.legacy.gateway.asgi_app:app --host 0.0.0.0 --port 8000

Notes:
* WebSocket routes come from `orchestrator.websocket_endpoints` (FastAPI).
* All remaining HTTP is delegated to the existing Flask `web_service.app`.
* Order matters: include the WS router first so WSGI mount does not swallow it.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.wsgi import WSGIMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the unified ASGI application."""
    # ------------------------------------------------------------------ #
    # Orchestrator app (ASGI) — keep its lifespan alive for legacy WS/pipeline
    # compatibility even though the retired HTTP mount is gone.
    # ------------------------------------------------------------------ #
    orchestrator_app = None
    orchestrator_error: str | None = None
    try:
        from brain_researcher.services.orchestrator.main_enhanced import (
            app as _orch_app,
        )

        orchestrator_app = _orch_app
        logger.info("✓ Loaded orchestrator app for legacy WS/pipeline compatibility")
    except Exception as exc:  # pragma: no cover - best-effort import
        orchestrator_error = str(exc)
        logger.error("Failed to load orchestrator app: %s", exc)

    @asynccontextmanager
    async def lifespan(app):
        # Run orchestrator lifespan so its startup initializes job_store, etc.
        if orchestrator_app:
            try:
                lifespan_ctx = getattr(
                    orchestrator_app.router, "lifespan_context", None
                )
                if lifespan_ctx is not None:
                    async with lifespan_ctx(orchestrator_app):
                        logger.info("✓ Orchestrator lifespan completed")
                        yield
                    return
                await orchestrator_app.router.startup()
                logger.info("✓ Orchestrator startup completed")
            except Exception as exc:  # pragma: no cover
                logger.error("Orchestrator startup failed: %s", exc)
        yield
        if orchestrator_app:
            try:
                await orchestrator_app.router.shutdown()
                logger.info("✓ Orchestrator shutdown completed")
            except Exception as exc:  # pragma: no cover
                logger.error("Orchestrator shutdown failed: %s", exc)

    app = FastAPI(
        title="Brain Researcher Gateway (Legacy)", version="0.2.0", lifespan=lifespan
    )

    flask_mounted = False
    flask_error: str | None = None

    @app.get("/health")
    async def health() -> dict:
        # Liveness: keep it lightweight so kubelet doesn't restart the pod on
        # transient dependency failures.
        return {
            "status": "ok",
            "service": "brain-researcher-gateway",
            "components": {
                "agent": "mounted" if flask_mounted else "not_mounted",
                "orchestrator": (
                    "legacy_ws_pipeline_only"
                    if orchestrator_app is not None
                    else "unavailable"
                ),
            },
        }

    @app.get("/ready")
    async def ready():
        if not flask_mounted:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "service": "brain-researcher-gateway",
                    "detail": {
                        "agent_error": flask_error,
                        "orchestrator_error": orchestrator_error,
                    },
                },
                status_code=503,
            )
        return {"status": "ready", "service": "brain-researcher-gateway"}

    # ------------------------------------------------------------------ #
    # 1) WebSockets (FastAPI router from orchestrator)
    # ------------------------------------------------------------------ #
    try:
        from brain_researcher.services.orchestrator.websocket_endpoints import (
            router as ws_router,
        )

        # The router already has prefix="/ws"; include as-is.
        app.include_router(ws_router)
        logger.info("✓ Registered orchestrator WebSocket router (/ws/...)")
    except Exception as exc:  # pragma: no cover - best-effort import
        logger.error("Failed to register WS router: %s", exc)

    # ------------------------------------------------------------------ #
    # 1b) Orchestrator pipeline endpoints (legacy polling)
    # ------------------------------------------------------------------ #
    try:
        from brain_researcher.services.orchestrator.visualization_endpoints import (
            pipeline_router,
        )

        app.include_router(pipeline_router)
        logger.info("✓ Registered orchestrator pipeline router (/api/pipeline/...)")
    except Exception as exc:  # pragma: no cover - best-effort import
        logger.error("Failed to register pipeline router: %s", exc)

    # ------------------------------------------------------------------ #
    # 1c) BR-KG proxy endpoints (KG browsing and graph tools)
    # ------------------------------------------------------------------ #
    try:
        from brain_researcher.legacy.gateway.br_kg_proxy import (
            router as br_kg_proxy_router,
        )

        app.include_router(br_kg_proxy_router)
        logger.info("✓ Registered BR-KG proxy router (/api/br-kg/..., /api/kg/...)")
    except Exception as exc:  # pragma: no cover - best-effort import
        logger.error("Failed to register BR-KG proxy router: %s", exc)

    # ------------------------------------------------------------------ #
    # 1d) fMRI foundation inference router (NiCLIP-backed)
    # ------------------------------------------------------------------ #
    try:
        from brain_researcher.services.model.inference_api import (
            router as inference_router,
        )

        app.include_router(inference_router)
        logger.info("✓ Registered inference router (/api/v1/inference/...)")
    except Exception as exc:  # pragma: no cover - best-effort import
        logger.error("Failed to register inference router: %s", exc)

    # ------------------------------------------------------------------ #
    # 2) Flask HTTP API (delegate everything else)
    # ------------------------------------------------------------------ #
    try:
        from brain_researcher.services.agent.web_service import app as flask_app

        # Optionally extend CORS at the FastAPI layer; Flask already enables CORS
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Mount at root so any path not claimed above falls through to Flask.
        app.mount("/", WSGIMiddleware(flask_app))
        # Ensure the root WSGI mount does not shadow FastAPI routes like /health and /ready.
        # Starlette may prioritize a "/" Mount ahead of other HTTP routes.
        try:  # pragma: no cover - routing implementation detail
            from starlette.routing import Mount

            for idx, route in enumerate(list(app.router.routes)):
                if isinstance(route, Mount) and route.path == "/":
                    app.router.routes.pop(idx)
                    app.router.routes.append(route)
                    break
        except Exception:
            pass
        flask_mounted = True
        logger.info("✓ Mounted Flask agent app at '/'")
    except Exception as exc:  # pragma: no cover - best-effort import
        flask_error = str(exc)
        logger.error("Failed to mount Flask app: %s", exc)

    return app


app = create_app()
