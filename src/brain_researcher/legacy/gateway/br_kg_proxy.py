from __future__ import annotations

import logging
import os
from typing import Tuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

DEFAULT_BR_KG_BASE_URL = "http://localhost:5000"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _get_br_kg_base_url() -> str:
    # Prefer the Agent's internal service URL (K8s sets BR_KG_API_URL).
    base = (
        os.getenv("BR_KG_API_URL")
        or os.getenv("BR_KG_URL")
        or os.getenv("NEXT_PUBLIC_BR_KG_API")
        or DEFAULT_BR_KG_BASE_URL
    )
    return base.rstrip("/")


def _forward_headers(request: Request) -> dict[str, str]:
    # Forward request headers to BR-KG, stripping hop-by-hop headers.
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _forward_query_params(request: Request) -> list[Tuple[str, str]]:
    # Preserve repeated query params (e.g., ?node_types=A&node_types=B).
    return list(request.query_params.multi_items())


async def _proxy_to_br_kg(
    request: Request,
    upstream_path: str,
    *,
    timeout_seconds: float,
) -> Response:
    base_url = _get_br_kg_base_url()
    upstream_url = f"{base_url}{upstream_path}"

    headers = _forward_headers(request)
    params = _forward_query_params(request)
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            upstream = await client.request(
                method=request.method,
                url=upstream_url,
                params=params,
                content=body if body else None,
                headers=headers,
            )
    except httpx.RequestError as exc:
        logger.warning("BR-KG proxy request failed: %s", exc)
        return JSONResponse(
            {"error": "br-kg_unreachable", "detail": str(exc)},
            status_code=503,
        )

    content_type = upstream.headers.get("content-type")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type,
    )


def create_br_kg_proxy_router() -> APIRouter:
    timeout_seconds = float(os.getenv("BR_KG_PROXY_TIMEOUT_SECONDS", "10"))

    router = APIRouter()

    # ------------------------------------------------------------------ #
    # /api/br-kg/* (UI expects these under the Agent service in prod)
    # ------------------------------------------------------------------ #
    br_kg_router = APIRouter(prefix="/api/br-kg", tags=["kg-proxy"])

    @br_kg_router.get("/health")
    async def br_kg_health(request: Request):
        return await _proxy_to_br_kg(
            request, "/health", timeout_seconds=timeout_seconds
        )

    @br_kg_router.get("/graph")
    async def br_kg_graph(request: Request):
        return await _proxy_to_br_kg(
            request, "/api/graph", timeout_seconds=timeout_seconds
        )

    @br_kg_router.post("/graph/query")
    async def br_kg_graph_query(request: Request):
        return await _proxy_to_br_kg(
            request, "/api/graph/query", timeout_seconds=timeout_seconds
        )

    router.include_router(br_kg_router)

    # ------------------------------------------------------------------ #
    # /api/kg/* (ONVOC concept browsing + evidence)
    # ------------------------------------------------------------------ #
    kg_router = APIRouter(prefix="/api/kg", tags=["kg-proxy"])

    @kg_router.api_route(
        "/health",
        methods=["GET"],
    )
    async def kg_health(request: Request):
        return await _proxy_to_br_kg(
            request, "/health", timeout_seconds=timeout_seconds
        )

    @kg_router.api_route(
        "/{path:path}",
        methods=["GET"],
    )
    async def kg_get(request: Request, path: str):
        return await _proxy_to_br_kg(
            request, f"/api/kg/{path}", timeout_seconds=timeout_seconds
        )

    router.include_router(kg_router)

    return router


router = create_br_kg_proxy_router()
