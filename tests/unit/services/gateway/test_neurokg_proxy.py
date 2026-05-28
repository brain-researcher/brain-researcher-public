"""Legacy gateway compatibility tests for the retired BR-KG proxy routes."""

import os
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

if os.getenv("BR_ENABLE_LEGACY_GATEWAY_TESTS", "0").lower() not in {"1", "true", "yes", "on"}:
    pytest.skip(
        "Legacy gateway compatibility coverage is disabled by default. Set BR_ENABLE_LEGACY_GATEWAY_TESTS=1 to run it.",
        allow_module_level=True,
    )

from brain_researcher.legacy.gateway import neurokg_proxy


class _DummyUpstreamResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b'{"ok":true}',
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "application/json"}


class _RecordingAsyncClient:
    last_request: dict | None = None

    def __init__(self, *args, **kwargs):
        self._timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, *, method, url, params, content, headers):
        _RecordingAsyncClient.last_request = {
            "method": method,
            "url": url,
            "params": params,
            "content": content,
            "headers": headers,
            "timeout": self._timeout,
        }
        return _DummyUpstreamResponse()


def test_neurokg_health_is_proxied_to_neurokg_service(monkeypatch):
    monkeypatch.setenv("NEUROKG_API_URL", "http://neurokg:5000")
    monkeypatch.setattr(neurokg_proxy.httpx, "AsyncClient", _RecordingAsyncClient)

    app = FastAPI()
    app.include_router(neurokg_proxy.create_neurokg_proxy_router())
    client = TestClient(app)

    resp = client.get("/api/neurokg/health")

    assert resp.status_code == 200
    assert _RecordingAsyncClient.last_request["url"] == "http://neurokg:5000/health"


def test_neurokg_graph_preserves_repeated_query_params(monkeypatch):
    monkeypatch.setenv("NEUROKG_API_URL", "http://neurokg:5000")
    monkeypatch.setattr(neurokg_proxy.httpx, "AsyncClient", _RecordingAsyncClient)

    app = FastAPI()
    app.include_router(neurokg_proxy.create_neurokg_proxy_router())
    client = TestClient(app)

    resp = client.get("/api/neurokg/graph?limit=10&node_types=Concept&node_types=Task")

    assert resp.status_code == 200
    assert _RecordingAsyncClient.last_request["url"] == "http://neurokg:5000/api/graph"
    assert _RecordingAsyncClient.last_request["params"] == [
        ("limit", "10"),
        ("node_types", "Concept"),
        ("node_types", "Task"),
    ]


def test_kg_concepts_is_proxied_to_api_kg(monkeypatch):
    monkeypatch.setenv("NEUROKG_API_URL", "http://neurokg:5000")
    monkeypatch.setattr(neurokg_proxy.httpx, "AsyncClient", _RecordingAsyncClient)

    app = FastAPI()
    app.include_router(neurokg_proxy.create_neurokg_proxy_router())
    client = TestClient(app)

    resp = client.get("/api/kg/concepts?limit=1")

    assert resp.status_code == 200
    assert _RecordingAsyncClient.last_request["url"] == "http://neurokg:5000/api/kg/concepts"
    assert _RecordingAsyncClient.last_request["params"] == [("limit", "1")]


def test_neurokg_proxy_returns_503_on_upstream_failure(monkeypatch):
    monkeypatch.setenv("NEUROKG_API_URL", "http://neurokg:5000")

    class _FailingAsyncClient(_RecordingAsyncClient):
        async def request(self, *, method, url, params, content, headers):
            raise httpx.ConnectError(
                "boom",
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(neurokg_proxy.httpx, "AsyncClient", _FailingAsyncClient)

    app = FastAPI()
    app.include_router(neurokg_proxy.create_neurokg_proxy_router())
    client = TestClient(app)

    resp = client.get("/api/neurokg/health")

    assert resp.status_code == 503
    assert resp.json()["error"] == "neurokg_unreachable"
