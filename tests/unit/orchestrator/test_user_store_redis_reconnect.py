from __future__ import annotations

import sys
import types

import pytest

from brain_researcher.services.orchestrator import user_store as user_store_mod


@pytest.mark.asyncio
async def test_get_redis_retries_after_previous_failure(monkeypatch):
    class _FailingClient:
        async def ping(self):
            raise RuntimeError("connect failed")

    class _HealthyClient:
        async def ping(self):
            return True

    calls = {"count": 0}
    healthy_client = _HealthyClient()

    def _from_url(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _FailingClient()
        return healthy_client

    redis_asyncio_module = types.SimpleNamespace(from_url=_from_url)
    redis_module = types.SimpleNamespace(asyncio=redis_asyncio_module)
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio_module)

    monkeypatch.setattr(user_store_mod, "_get_redis_retry_interval_seconds", lambda: 0.0)
    monkeypatch.setenv("REDIS_URL", "redis://fake:6379/0")

    user_store_mod._redis_client = None
    user_store_mod._redis_last_connect_attempt = 0.0
    user_store_mod._redis_connect_error_logged = False

    first = await user_store_mod._get_redis()
    second = await user_store_mod._get_redis()

    assert first is None
    assert second is healthy_client
    assert calls["count"] == 2


def test_user_to_dict_preserves_hashed_password():
    class _FakeUser:
        hashed_password = "$2b$12$dummy"

        def model_dump(self, mode="json"):
            assert mode == "json"
            return {"id": "user_1", "username": "demo"}

    data = user_store_mod._user_to_dict(_FakeUser())
    assert data["id"] == "user_1"
    assert data["hashed_password"] == "$2b$12$dummy"


def test_user_to_dict_omits_empty_hash():
    class _FakeUser:
        hashed_password = None

        def model_dump(self, mode="json"):
            assert mode == "json"
            return {"id": "user_2", "username": "oauth_user"}

    data = user_store_mod._user_to_dict(_FakeUser())
    assert data["id"] == "user_2"
    assert "hashed_password" not in data
