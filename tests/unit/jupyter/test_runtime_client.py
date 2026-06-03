from __future__ import annotations

import httpx
import pytest

from brain_researcher.integrations.jupyter.runtime_client import (
    JupyterRuntimeTarget,
    ensure_session,
)


@pytest.mark.asyncio
async def test_ensure_session_reuses_existing_session_by_path(monkeypatch):
    target = JupyterRuntimeTarget(
        base_url="https://hub.${PUBLIC_HOSTNAME}/user/demo",
        token="secret-token",
        kernel_name="python3",
        session_name="Brain Researcher Studio proj_demo",
        session_path="projects/proj_demo/.studio/rt_demo",
    )
    seen_requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path.endswith("/api/sessions"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "sess_existing",
                        "name": "Brain Researcher Studio proj_demo",
                        "path": "projects/proj_demo/.studio/rt_demo",
                        "kernel": {
                            "id": "kernel_existing",
                            "name": "python3",
                        },
                    }
                ],
            )
        if request.method == "POST" and request.url.path.endswith("/api/sessions"):
            raise AssertionError("ensure_session should not create a new session")
        return httpx.Response(404)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)

    handle = await ensure_session(target, existing_session_id=None, timeout_seconds=15)

    assert handle.session_id == "sess_existing"
    assert handle.kernel_id == "kernel_existing"
    assert handle.kernel_name == "python3"
    assert seen_requests == [("GET", "/user/demo/api/sessions")]
