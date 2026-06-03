"""Jupyter Server extension skeleton for the hosted notebook assistant bridge."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from .bridge import (
    BridgeSessionState,
    NotebookAssistantBridgeSettings,
    build_bootstrap_payload,
    get_bridge_session_store,
    issue_bridge_session,
    proxy_mcp_request,
)

logger = logging.getLogger(__name__)


def _jupyter_server_extension_points() -> list[dict[str, str]]:
    return [{"module": "brain_researcher.integrations.jupyter.server_extension"}]


def _resolve_jupyter_runtime() -> SimpleNamespace:
    from jupyter_server.base.handlers import APIHandler
    from jupyter_server.utils import url_path_join
    import tornado.web as web

    return SimpleNamespace(
        APIHandler=APIHandler,
        url_path_join=url_path_join,
        web=web,
    )


def _json_finish(
    handler: Any, payload: dict[str, Any], *, status_code: int = 200
) -> None:
    handler.set_status(status_code)
    handler.set_header("Content-Type", "application/json")
    handler.finish(json.dumps(payload))


def _resolve_bridge_session(
    handler: Any, settings: NotebookAssistantBridgeSettings
) -> BridgeSessionState:
    request = handler.request
    requested_session_id = (
        request.headers.get(settings.session_header_name)
        or request.query_arguments.get(settings.session_query_param, [b""])[0].decode(
            "utf-8", errors="ignore"
        )
        or request.cookies.get(settings.session_query_param)
    )
    store = get_bridge_session_store(settings)
    existing = store.get(requested_session_id)
    if existing is not None:
        return existing
    return issue_bridge_session(settings, requested_session_id=None)


def _build_handler_classes(
    runtime: SimpleNamespace, settings: NotebookAssistantBridgeSettings
):
    APIHandler = runtime.APIHandler
    web = runtime.web

    class HealthHandler(APIHandler):
        @web.authenticated
        def get(self) -> None:
            _json_finish(
                self,
                {
                    "ok": True,
                    "service": "brain-researcher-notebook-bridge",
                    "bridge": build_bootstrap_payload(settings),
                },
            )

    class BootstrapHandler(APIHandler):
        @web.authenticated
        def get(self) -> None:
            bridge_session = _resolve_bridge_session(self, settings)
            self.set_header(
                settings.session_header_name, bridge_session.bridge_session_id
            )
            _json_finish(
                self,
                {
                    "ok": True,
                    "bootstrap": build_bootstrap_payload(
                        settings,
                        bridge_session=bridge_session,
                    ),
                },
            )

    class McpProxyHandler(APIHandler):
        @web.authenticated
        async def get(self) -> None:
            await self._proxy_request()

        @web.authenticated
        async def post(self) -> None:
            await self._proxy_request()

        @web.authenticated
        async def delete(self) -> None:
            await self._proxy_request()

        @web.authenticated
        def options(self) -> None:
            self.set_status(204)
            self.set_header("Allow", "GET,POST,DELETE,OPTIONS")
            self.finish()

        async def _proxy_request(self) -> None:
            bridge_session = _resolve_bridge_session(self, settings)
            upstream = await proxy_mcp_request(
                method=self.request.method,
                request_headers=self.request.headers,
                body=self.request.body or b"",
                settings=settings,
                bridge_session=bridge_session,
            )
            self.set_status(upstream.status_code)
            for name, value in upstream.headers.items():
                self.set_header(name, value)
            self.set_header(
                settings.session_header_name, bridge_session.bridge_session_id
            )
            if upstream.body:
                self.finish(upstream.body)
            else:
                self.finish()

    return HealthHandler, BootstrapHandler, McpProxyHandler


def register_handlers(
    serverapp: Any,
    *,
    settings: NotebookAssistantBridgeSettings | None = None,
    runtime: SimpleNamespace | None = None,
) -> list[tuple[Any, ...]]:
    active_settings = settings or NotebookAssistantBridgeSettings.from_env()
    active_runtime = runtime or _resolve_jupyter_runtime()

    health_handler, bootstrap_handler, mcp_proxy_handler = _build_handler_classes(
        active_runtime, active_settings
    )
    base_url = serverapp.web_app.settings.get("base_url", "/")
    join = active_runtime.url_path_join
    handlers = [
        (
            join(base_url, active_settings.api_base_path, "health"),
            health_handler,
        ),
        (
            join(base_url, active_settings.api_base_path, "bootstrap"),
            bootstrap_handler,
        ),
        (
            join(base_url, active_settings.api_base_path, "mcp"),
            mcp_proxy_handler,
        ),
    ]
    serverapp.web_app.add_handlers(".*$", handlers)
    return handlers


def _load_jupyter_server_extension(serverapp: Any) -> None:
    server_logger = getattr(serverapp, "log", logger)
    try:
        handlers = register_handlers(serverapp)
    except ImportError as exc:
        server_logger.warning(
            "Brain Researcher notebook bridge was not loaded because Jupyter Server runtime imports failed: %s",
            exc,
        )
        return

    server_logger.info(
        "Brain Researcher notebook bridge registered %s handler(s).",
        len(handlers),
    )


load_jupyter_server_extension = _load_jupyter_server_extension
