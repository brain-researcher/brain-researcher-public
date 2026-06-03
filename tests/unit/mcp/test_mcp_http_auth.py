from __future__ import annotations

import hashlib
import hmac
import importlib
import sys
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def _make_inner_app():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def _ok(_):
        return PlainTextResponse("inner-ok")

    return Starlette(routes=[Route("/", endpoint=_ok, methods=["GET"])])


def _make_mcp_streamable_inner_app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    sessions: set[str] = set()

    async def _rpc(request):
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {"code": -32600, "message": "Invalid request"},
                },
                status_code=400,
            )

        req_id = payload.get("id")
        method = str(payload.get("method") or "")
        session_id = request.headers.get("mcp-session-id")

        if method == "initialize":
            if session_id and session_id not in sessions:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id or "server-error",
                        "error": {"code": -32600, "message": "Session not found"},
                    },
                    status_code=404,
                    headers={"mcp-session-id": session_id},
                )
            if not session_id:
                session_id = f"sid-{len(sessions) + 1}"
                sessions.add(session_id)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"ok": True, "phase": "initialized"},
                },
                headers={"mcp-session-id": session_id},
            )

        if not session_id:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id or "server-error",
                    "error": {
                        "code": -32600,
                        "message": "Bad Request: Missing session ID",
                    },
                },
                status_code=400,
                headers={"mcp-session-id": "sid-missing"},
            )
        if session_id not in sessions:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id or "server-error",
                    "error": {"code": -32600, "message": "Session not found"},
                },
                status_code=404,
                headers={"mcp-session-id": session_id},
            )

        if method == "tools/list":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}},
                headers={"mcp-session-id": session_id},
            )

        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
            headers={"mcp-session-id": session_id},
        )

    return Starlette(routes=[Route("/", endpoint=_rpc, methods=["POST"])])


def _make_mcp_get_seeded_inner_app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    seed_session = "seed-session-id"

    async def _rpc(request):
        if request.method == "GET":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {
                        "code": -32600,
                        "message": "Not Acceptable: Client must accept text/event-stream",
                    },
                },
                status_code=406,
                headers={"mcp-session-id": seed_session},
            )

        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {"code": -32600, "message": "Invalid request"},
                },
                status_code=400,
            )

        req_id = payload.get("id")
        method = str(payload.get("method") or "")
        session_id = request.headers.get("mcp-session-id")

        if method == "initialize":
            if session_id != seed_session:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id or "server-error",
                        "error": {"code": -32600, "message": "Session not found"},
                    },
                    status_code=404,
                    headers={"mcp-session-id": session_id or "missing"},
                )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"ok": True, "phase": "initialized"},
                },
                headers={"mcp-session-id": seed_session},
            )

        if method == "tools/list":
            if session_id != seed_session:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id or "server-error",
                        "error": {"code": -32600, "message": "Session not found"},
                    },
                    status_code=404,
                    headers={"mcp-session-id": session_id or "missing"},
                )
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}},
                headers={"mcp-session-id": seed_session},
            )

        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id or "server-error", "result": {"ok": True}},
            headers={"mcp-session-id": seed_session},
        )

    return Starlette(routes=[Route("/", endpoint=_rpc, methods=["GET", "POST"])])


def _make_mcp_get_seeded_requires_initialize_inner_app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    seed_session = "seed-session-id"
    initialized_sessions: set[str] = set()

    async def _rpc(request):
        if request.method == "GET":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {
                        "code": -32600,
                        "message": "Not Acceptable: Client must accept text/event-stream",
                    },
                },
                status_code=406,
                headers={"mcp-session-id": seed_session},
            )

        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {"code": -32600, "message": "Invalid request"},
                },
                status_code=400,
            )

        req_id = payload.get("id")
        method = str(payload.get("method") or "")
        session_id = request.headers.get("mcp-session-id")
        if session_id != seed_session:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id or "server-error",
                    "error": {"code": -32600, "message": "Session not found"},
                },
                status_code=404,
                headers={"mcp-session-id": session_id or "missing"},
            )

        if method == "initialize":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"ok": True, "phase": "initialized"},
                },
                headers={"mcp-session-id": seed_session},
            )
        if method == "notifications/initialized":
            initialized_sessions.add(seed_session)
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
                headers={"mcp-session-id": seed_session},
            )
        if method == "tools/call":
            if seed_session not in initialized_sessions:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id or "server-error",
                        "error": {
                            "code": -32600,
                            "message": "Received request before initialization was complete",
                        },
                    },
                    status_code=400,
                    headers={"mcp-session-id": seed_session},
                )
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
                headers={"mcp-session-id": seed_session},
            )

        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id or "server-error", "result": {"ok": True}},
            headers={"mcp-session-id": seed_session},
        )

    return Starlette(routes=[Route("/", endpoint=_rpc, methods=["GET", "POST"])])


def _make_mcp_plaintext_post_inner_app():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def _rpc(_request):
        return PlainTextResponse("plain-text-body")

    return Starlette(routes=[Route("/", endpoint=_rpc, methods=["POST"])])


def _make_mcp_tools_call_probe_inner_app():
    import asyncio
    import threading

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    state = {"active_calls": 0, "max_active_calls": 0}
    counter_lock = threading.Lock()
    seed_session = "seed-session-id"

    async def _rpc(request):
        if request.method == "GET":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {"code": -32600, "message": "not acceptable"},
                },
                status_code=406,
                headers={"mcp-session-id": seed_session},
            )

        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {"code": -32600, "message": "Invalid request"},
                },
                status_code=400,
            )
        req_id = payload.get("id")
        method = str(payload.get("method") or "")
        session_id = request.headers.get("mcp-session-id") or seed_session

        if method == "initialize":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
                headers={"mcp-session-id": session_id},
            )
        if method == "notifications/initialized":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
                headers={"mcp-session-id": session_id},
            )
        if method == "tools/call":
            with counter_lock:
                state["active_calls"] += 1
                state["max_active_calls"] = max(
                    state["max_active_calls"], state["active_calls"]
                )
            try:
                await asyncio.sleep(0.05)
            finally:
                with counter_lock:
                    state["active_calls"] -= 1
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
                headers={"mcp-session-id": session_id},
            )

        return JSONResponse(
            {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}},
            headers={"mcp-session-id": session_id},
        )

    return Starlette(routes=[Route("/", endpoint=_rpc, methods=["GET", "POST"])]), state


def _make_api_key(secret: str, key_id: str, pepper: bytes) -> tuple[str, str]:
    digest = hmac.new(pepper, secret.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"brk_{key_id}.{secret}"
    return token, digest


def test_http_auth_token_mode_allows_pat(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "token")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "pat-123")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_bearer_token"

    resp = client.get("/", headers={"Authorization": "Bearer pat-123"})
    assert resp.status_code == 200
    assert resp.text == "inner-ok"


def test_http_auth_browser_mcp_entry_redirects_to_setup(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "token")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "pat-123")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "MOUNT_PATH", "/mcp")
    monkeypatch.setattr(srv, "MCP_SETUP_PATH", "/mcp/setup")

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    browser_resp = client.get(
        "/mcp",
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )
    assert browser_resp.status_code == 302
    assert browser_resp.headers["location"] == "/mcp/setup"

    generic_get_resp = client.get(
        "/mcp",
        headers={"Accept": "*/*"},
        follow_redirects=False,
    )
    assert generic_get_resp.status_code == 302
    assert generic_get_resp.headers["location"] == "/mcp/setup"

    head_resp = client.head("/mcp", follow_redirects=False)
    assert head_resp.status_code == 302
    assert head_resp.headers["location"] == "/mcp/setup"

    protocol_resp = client.get(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        follow_redirects=False,
    )
    assert protocol_resp.status_code == 401
    assert protocol_resp.json()["error"] == "missing_bearer_token"


def test_http_auth_token_or_jwt_allows_hs256_jwt(monkeypatch):
    from jose import jwt
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "token_or_jwt")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "pat-123")
    monkeypatch.setattr(srv, "JWT_SECRET_KEY", "jwt-secret")
    monkeypatch.setattr(srv, "JWKS_URL", "")
    monkeypatch.setattr(srv, "JWT_ISSUER", "")
    monkeypatch.setattr(srv, "JWT_AUDIENCE", "")
    monkeypatch.setattr(srv, "JWT_AUDIENCES", [])
    monkeypatch.setattr(srv, "JWT_ALGORITHMS", set())
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    token = jwt.encode(
        {"sub": "user-1", "exp": int(time.time()) + 3600},
        "jwt-secret",
        algorithm="HS256",
    )

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.text == "inner-ok"

    resp = client.get("/", headers={"Authorization": "Bearer pat-123"})
    assert resp.status_code == 200
    assert resp.text == "inner-ok"


def test_http_origin_and_host_restrictions(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", {"https://${PUBLIC_HOSTNAME}"})
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", {"${PUBLIC_HOSTNAME}"})

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    # Bad origin rejected.
    resp = client.get(
        "/",
        headers={"Host": "${PUBLIC_HOSTNAME}", "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "origin_not_allowed"

    # Bad host rejected.
    resp = client.get(
        "/",
        headers={"Host": "evil.example", "Origin": "https://${PUBLIC_HOSTNAME}"},
    )
    assert resp.status_code == 421
    assert resp.json()["error"] == "host_not_allowed"

    # /healthz must not be blocked by host/origin checks.
    resp = client.get(
        "/healthz",
        headers={"Host": "evil.example", "Origin": "https://evil.example"},
    )
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_http_resolve_endpoint_returns_reference_resolution(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "MOUNT_PATH", "/mcp")

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/resolve", params={"ref": "doi:10.1016/j.tics.2005.12.004"})
    mounted_resp = client.get(
        "/mcp/resolve", params={"ref": "doi:10.1016/j.tics.2005.12.004"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["resolved"] is True
    assert body["result"]["reference_kind"] == "doi"
    assert mounted_resp.status_code == 200
    assert mounted_resp.json()["result"]["reference_kind"] == "doi"


def test_http_auth_token_mode_allows_user_api_key(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    pepper = bytes.fromhex("ab" * 32)
    token, digest = _make_api_key("alice-secret", "alice_k1", pepper)

    monkeypatch.setattr(srv, "AUTH_MODE", "token")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", pepper)
    monkeypatch.setattr(
        srv,
        "AUTH_TOKENS_BY_KID",
        {
            "alice_k1": srv.ApiKeyRecord(
                user_id="alice",
                digest=digest,
                enabled=True,
                expires_at=None,
            )
        },
    )
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.text == "inner-ok"


def test_http_auth_token_mode_rejects_disabled_or_expired_api_key(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    pepper = bytes.fromhex("cd" * 32)
    alice_token, alice_digest = _make_api_key("alice-secret", "alice_k1", pepper)
    bob_token, bob_digest = _make_api_key("bob-secret", "bob_k1", pepper)

    monkeypatch.setattr(srv, "AUTH_MODE", "token")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", pepper)
    monkeypatch.setattr(
        srv,
        "AUTH_TOKENS_BY_KID",
        {
            "alice_k1": srv.ApiKeyRecord(
                user_id="alice",
                digest=alice_digest,
                enabled=False,
                expires_at=None,
            ),
            "bob_k1": srv.ApiKeyRecord(
                user_id="bob",
                digest=bob_digest,
                enabled=True,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            ),
        },
    )
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/", headers={"Authorization": f"Bearer {alice_token}"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"

    resp = client.get("/", headers={"Authorization": f"Bearer {bob_token}"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_http_auth_auto_mode_uses_api_keys_when_configured(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    pepper = bytes.fromhex("ef" * 32)
    token, digest = _make_api_key("ci-secret", "ci_k1", pepper)

    monkeypatch.setattr(srv, "AUTH_MODE", "auto")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(srv, "JWKS_URL", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", pepper)
    monkeypatch.setattr(
        srv,
        "AUTH_TOKENS_BY_KID",
        {
            "ci_k1": srv.ApiKeyRecord(
                user_id="ci",
                digest=digest,
                enabled=True,
                expires_at=None,
            )
        },
    )
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    unauth = client.get("/")
    assert unauth.status_code == 401

    authed = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert authed.status_code == 200
    assert authed.text == "inner-ok"


def test_server_module_loads_auth_env_from_dotenv_for_direct_module_run(
    monkeypatch, tmp_path
):
    from brain_researcher.core.utils import env_loader
    from brain_researcher.services.mcp import server as srv

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "BR_MCP_AUTH_MODE=token_or_jwt\n" "JWT_SECRET_KEY=dotenv-jwt-secret\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BR_MCP_AUTH_MODE", raising=False)
    monkeypatch.delenv("BR_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.delenv("BRAIN_RESEARCHER_SKIP_DOTENV", raising=False)
    monkeypatch.setattr(env_loader, "_loaded", False)
    monkeypatch.setattr(env_loader, "_loaded_path", None)

    try:
        reloaded = importlib.reload(srv)

        assert reloaded.AUTH_MODE == "token_or_jwt"
        assert reloaded.JWT_SECRET_KEY == "dotenv-jwt-secret"
    finally:
        # importlib.reload(srv) rebuilds srv.mcp as a fresh FastMCP with only
        # server.py's own @mcp.tool()s; the router modules' tool registrations are
        # one-time import side-effects that do NOT re-run (cached in sys.modules),
        # so the ~20 router-hosted tools (artifacts/plan/slurm/grounding/memory/...)
        # vanish from the shared instance and pollute later surface-introspection
        # tests. Restore: undo env/cwd, reload srv with the real env, then re-import
        # the router modules so their @mcp.tool()s re-register on the new srv.mcp.
        monkeypatch.undo()
        importlib.reload(srv)
        for _router in sorted(set(srv._ROUTER_TOOL_EXPORTS.values())):
            importlib.reload(
                sys.modules[f"brain_researcher.services.mcp.routers.{_router}"]
            )


def test_http_auth_auto_mode_without_config_fails_closed(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "auto")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", None)
    monkeypatch.setattr(srv, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(srv, "JWKS_URL", "")
    monkeypatch.setattr(srv, "_AUTO_AUTH_FAIL_CLOSED_WARNED", False)
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    missing = client.get("/")
    assert missing.status_code == 401
    assert missing.json()["error"] == "missing_bearer_token"

    bad_token = client.get("/", headers={"Authorization": "Bearer anything"})
    assert bad_token.status_code == 401
    assert bad_token.json()["error"] == "unauthorized"


def test_resolve_auth_mode_auto_without_config_returns_token(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "auto")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", None)
    monkeypatch.setattr(srv, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(srv, "JWKS_URL", "")
    monkeypatch.setattr(srv, "_AUTO_AUTH_FAIL_CLOSED_WARNED", False)

    assert srv._resolve_auth_mode() == "token"


def test_http_auth_falls_back_to_static_tokens_when_redis_unavailable(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    pepper = bytes.fromhex("11" * 32)
    token, digest = _make_api_key("static-secret", "static_k1", pepper)

    monkeypatch.setattr(srv, "AUTH_MODE", "token")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", pepper)
    monkeypatch.setattr(srv, "TOKEN_PEPPER_VERSION", "v1")
    monkeypatch.setattr(
        srv,
        "AUTH_TOKENS_BY_KID",
        {
            "static_k1": srv.ApiKeyRecord(
                user_id="alice",
                digest=digest,
                enabled=True,
                expires_at=None,
            )
        },
    )
    monkeypatch.setattr(srv, "_get_token_redis", lambda: None)
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.text == "inner-ok"


def test_http_auth_prefers_redis_record_for_same_kid(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    class _RedisRecord:
        def hgetall(self, _key: str):
            return {
                "kid": "alice_k1",
                "user_id": "alice",
                "digest": "0" * 64,
                "enabled": "0",
                "created_at": "2026-02-13T00:00:00Z",
                "pepper_version": "v1",
            }

    pepper = bytes.fromhex("22" * 32)
    token, digest = _make_api_key("redis-secret", "alice_k1", pepper)

    monkeypatch.setattr(srv, "AUTH_MODE", "token")
    monkeypatch.setattr(srv, "AUTH_TOKEN", "")
    monkeypatch.setattr(srv, "TOKEN_PEPPER", pepper)
    monkeypatch.setattr(srv, "TOKEN_PEPPER_VERSION", "v1")
    monkeypatch.setattr(
        srv,
        "AUTH_TOKENS_BY_KID",
        {
            "alice_k1": srv.ApiKeyRecord(
                user_id="alice",
                digest=digest,
                enabled=True,
                expires_at=None,
            )
        },
    )
    monkeypatch.setattr(srv, "_get_token_redis", lambda: _RedisRecord())
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())

    app = srv.build_http_app(_make_inner_app())
    client = TestClient(app)

    resp = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_http_mcp_session_bootstrap_supports_initialize_then_tools_list(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(_make_mcp_streamable_inner_app())
    client = TestClient(app)

    init_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "init1", "method": "initialize", "params": {}},
    )
    assert init_resp.status_code == 200
    init_sid = init_resp.headers.get("mcp-session-id")
    assert init_sid
    assert init_resp.json()["result"]["phase"] == "initialized"

    list_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "list1", "method": "tools/list", "params": {}},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["result"]["tools"] == []
    assert list_resp.headers.get("mcp-session-id") == init_sid


def test_http_mcp_session_bootstrap_prefers_cached_session_over_bad_explicit(
    monkeypatch,
):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(_make_mcp_streamable_inner_app())
    client = TestClient(app)

    init_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "init1", "method": "initialize", "params": {}},
    )
    assert init_resp.status_code == 200
    explicit_sid = init_resp.headers.get("mcp-session-id")
    assert explicit_sid

    list_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "list1", "method": "tools/list", "params": {}},
        headers={"mcp-session-id": explicit_sid},
    )
    assert list_resp.status_code == 200
    assert list_resp.headers.get("mcp-session-id") == explicit_sid

    bad_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "list2", "method": "tools/list", "params": {}},
        headers={"mcp-session-id": "bogus-session-id"},
    )
    assert bad_resp.status_code == 200
    assert bad_resp.headers.get("mcp-session-id") == explicit_sid


def test_http_mcp_session_bootstrap_reuses_get_seeded_session(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(_make_mcp_get_seeded_inner_app())
    client = TestClient(app)

    preflight = client.get(
        "/",
        headers={"Accept": "application/json", "User-Agent": "preflight-client/1.0"},
    )
    assert preflight.status_code == 406
    assert preflight.headers.get("mcp-session-id") == "seed-session-id"

    init_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "init1", "method": "initialize", "params": {}},
        headers={"User-Agent": "rpc-client/2.0"},
    )
    assert init_resp.status_code == 200
    assert init_resp.headers.get("mcp-session-id") == "seed-session-id"

    list_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "list1", "method": "tools/list", "params": {}},
    )
    assert list_resp.status_code == 200
    assert list_resp.headers.get("mcp-session-id") == "seed-session-id"


def test_http_mcp_session_bootstrap_overrides_stale_explicit_session(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(_make_mcp_get_seeded_inner_app())
    client = TestClient(app)

    preflight = client.get(
        "/",
        headers={"Accept": "application/json", "User-Agent": "preflight-client/1.0"},
    )
    assert preflight.status_code == 406
    assert preflight.headers.get("mcp-session-id") == "seed-session-id"

    init_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "init1", "method": "initialize", "params": {}},
        headers={
            "User-Agent": "rpc-client/2.0",
            "mcp-session-id": "stale-session-id",
        },
    )
    assert init_resp.status_code == 200
    assert init_resp.headers.get("mcp-session-id") == "seed-session-id"


def test_http_mcp_session_bootstrap_strips_stale_initialize_session(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(_make_mcp_streamable_inner_app())
    client = TestClient(app)

    init_resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "init1", "method": "initialize", "params": {}},
        headers={"mcp-session-id": "stale-session-id"},
    )
    assert init_resp.status_code == 200
    assert init_resp.headers.get("mcp-session-id") == "sid-1"


def test_http_mcp_session_bootstrap_auto_initializes_before_tools_call(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_INIT_CACHE", {})

    app = srv.build_http_app(_make_mcp_get_seeded_requires_initialize_inner_app())
    client = TestClient(app)

    resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "call1", "method": "tools/call", "params": {}},
        headers={"mcp-session-id": "stale-session-id"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("mcp-session-id") == "seed-session-id"


def test_http_mcp_session_bootstrap_prime_get_timeout_returns_quickly(monkeypatch):
    import asyncio

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    state = {"get_cancelled": False}
    slow_get_seconds = 1.0

    async def _rpc(request):
        if request.method == "GET":
            try:
                await asyncio.sleep(slow_get_seconds)
            except asyncio.CancelledError:
                state["get_cancelled"] = True
                raise
            return JSONResponse(
                {"ok": True}, headers={"mcp-session-id": "late-session-id"}
            )

        payload = await request.json()
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "ok": True,
                    "session_id_seen_by_inner": request.headers.get("mcp-session-id"),
                },
            }
        )

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_PRIME_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(
        Starlette(routes=[Route("/", endpoint=_rpc, methods=["GET", "POST"])])
    )
    client = TestClient(app)

    started = time.perf_counter()
    resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "list1", "method": "tools/list", "params": {}},
    )
    elapsed = time.perf_counter() - started

    assert resp.status_code == 200
    assert resp.json()["result"]["session_id_seen_by_inner"] is None
    assert state["get_cancelled"] is True
    assert elapsed < 0.6


def test_http_mcp_session_bootstrap_rejects_oversized_json_body(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_MAX_BODY_BYTES", 256)

    app = srv.build_http_app(_make_mcp_streamable_inner_app())
    client = TestClient(app)

    resp = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "oversized-1",
            "method": "tools/list",
            "params": {"blob": "x" * 4096},
        },
    )

    body = resp.json()
    assert resp.status_code == 413
    assert body.get("error") == "payload_too_large"
    assert body.get("max_body_bytes") == 256


def test_http_mcp_json_guard_rewrites_plaintext_post(monkeypatch):
    from starlette.testclient import TestClient

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})

    app = srv.build_http_app(_make_mcp_plaintext_post_inner_app())
    client = TestClient(app)

    resp = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "list1", "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 502
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["error"] == "unexpected_response_content_type"
    assert body["content_type"].startswith("text/plain")


def test_http_mcp_session_bootstrap_serializes_tools_call(monkeypatch):
    import asyncio

    import httpx

    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "AUTH_MODE", "none")
    monkeypatch.setattr(srv, "ALLOWED_ORIGINS", set())
    monkeypatch.setattr(srv, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(srv, "SESSION_BOOTSTRAP_ENABLED", True)
    monkeypatch.setattr(srv, "SERIALIZE_TOOLS_CALL", True)
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_CACHE", {})
    monkeypatch.setattr(srv, "_SESSION_BOOTSTRAP_INIT_CACHE", {})

    inner, state = _make_mcp_tools_call_probe_inner_app()
    app = srv.build_http_app(inner)

    async def _run_parallel_calls():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            headers = {"mcp-session-id": "seed-session-id"}

            async def _call(call_id: str):
                return await client.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "id": call_id,
                        "method": "tools/call",
                        "params": {},
                    },
                    headers=headers,
                )

            return await asyncio.gather(_call("call-1"), _call("call-2"))

    responses = asyncio.run(_run_parallel_calls())
    assert [r.status_code for r in responses] == [200, 200]
    assert state["max_active_calls"] == 1
