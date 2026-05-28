from __future__ import annotations


def test_asgi_ws_route_precedes_wsgi_mount() -> None:
    """Ensure `/ws` is not swallowed by the root WSGI mount."""

    from starlette.routing import Mount

    from brain_researcher.services.agent.asgi import asgi_app

    routes = list(asgi_app.router.routes)
    ws_idx = next(i for i, r in enumerate(routes) if getattr(r, "path", None) == "/ws")
    mount_idx = next(i for i, r in enumerate(routes) if isinstance(r, Mount))

    assert ws_idx < mount_idx


def test_default_sse_base_uses_agent_port_and_normalizes_bind_host(monkeypatch) -> None:
    from brain_researcher.services.agent import asgi as asgi_mod

    monkeypatch.setenv("AGENT_PORT", "8011")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.delenv("AGENT_HTTP_SCHEME", raising=False)

    assert asgi_mod._default_sse_base() == "http://127.0.0.1:8011"

