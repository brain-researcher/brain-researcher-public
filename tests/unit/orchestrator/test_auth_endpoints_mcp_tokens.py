from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
from brain_researcher.services.orchestrator import auth_endpoints as auth_mod


class _FakeUser:
    def __init__(self, *, user_id: str, username: str, email: str) -> None:
        self.id = user_id
        self.username = username
        self.email = email
        self.full_name = username
        self.role = SimpleNamespace(value="researcher")
        self.is_active = True
        self.auth_provider = "password"
        self.created_at = datetime.utcnow()
        self.last_login = None
        self.preferences = {}
        self.hashed_password = None


def _make_token(sub: str) -> str:
    return jwt.encode({"sub": sub}, auth_mod.SECRET_KEY, algorithm=auth_mod.JWT_ALGORITHM)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_mod.router)
    return TestClient(app)


def test_list_mcp_tokens_returns_user_tokens(monkeypatch):
    user = _FakeUser(user_id="user_alice", username="alice", email="alice@example.com")

    class _Store:
        async def get_by_id(self, user_id: str):
            return user if user_id == user.id else None

    class _TokenStore:
        async def list_user_tokens(self, user_id: str):
            assert user_id == user.id
            return [{"kid": "alice_1", "enabled": True}]

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    monkeypatch.setattr(auth_mod, "mcp_token_store", _TokenStore())
    client = _make_client()
    token = _make_token(user.id)

    response = client.get("/auth/mcp-tokens", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["tokens"][0]["kid"] == "alice_1"


def test_create_mcp_token_rotates_and_returns_plaintext(monkeypatch):
    user = _FakeUser(user_id="user_alice", username="alice", email="alice@example.com")

    class _Store:
        async def get_by_id(self, user_id: str):
            return user if user_id == user.id else None

    class _TokenStore:
        async def create_or_rotate_token(self, user_id: str, *, expires_at: str | None = None):
            assert user_id == user.id
            assert expires_at is None
            return (
                "brk_alice_1.secret",
                {"kid": "alice_1", "enabled": True, "created_at": "2026-02-13T00:00:00Z"},
            )

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    monkeypatch.setattr(auth_mod, "mcp_token_store", _TokenStore())
    client = _make_client()
    token = _make_token(user.id)

    response = client.post(
        "/auth/mcp-tokens",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token"] == "brk_alice_1.secret"
    assert payload["metadata"]["kid"] == "alice_1"


def test_verify_mcp_token_with_header(monkeypatch):
    user = _FakeUser(user_id="user_alice", username="alice", email="alice@example.com")

    class _Store:
        async def get_by_id(self, user_id: str):
            return user if user_id == user.id else None

    class _TokenStore:
        async def verify_token(self, token: str, *, update_last_used: bool = True):
            assert token == "brk_alice_1.secret"
            assert update_last_used is False
            return SimpleNamespace(
                user_id=user.id,
                kid="alice_1",
                last_used_at="2026-02-13T00:00:00Z",
            )

        async def status(self, _user_id: str):
            return {}

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    monkeypatch.setattr(auth_mod, "mcp_token_store", _TokenStore())
    client = _make_client()
    auth_token = _make_token(user.id)

    response = client.get(
        "/auth/mcp-tokens/verify",
        headers={
            "Authorization": f"Bearer {auth_token}",
            "x-mcp-token": "brk_alice_1.secret",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["kid"] == "alice_1"


def test_revoke_mcp_token_404_when_missing(monkeypatch):
    user = _FakeUser(user_id="user_alice", username="alice", email="alice@example.com")

    class _Store:
        async def get_by_id(self, user_id: str):
            return user if user_id == user.id else None

    class _TokenStore:
        async def revoke_user_token(self, user_id: str, kid: str):
            assert user_id == user.id
            assert kid == "alice_1"
            return False

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    monkeypatch.setattr(auth_mod, "mcp_token_store", _TokenStore())
    client = _make_client()
    token = _make_token(user.id)

    response = client.delete(
        "/auth/mcp-tokens/alice_1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Token not found"


def test_list_mcp_tokens_falls_back_to_email_when_sub_not_found(monkeypatch):
    user = _FakeUser(user_id="user_alice", username="alice", email="alice@example.com")

    class _Store:
        async def get_by_id(self, _user_id: str):
            return None

        async def get_by_email(self, email: str):
            return user if email == user.email else None

    class _TokenStore:
        async def list_user_tokens(self, user_id: str):
            assert user_id == user.id
            return [{"kid": "alice_1", "enabled": True}]

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    monkeypatch.setattr(auth_mod, "mcp_token_store", _TokenStore())
    client = _make_client()
    token = jwt.encode(
        {"sub": "google-oauth-subject", "email": "alice@example.com"},
        auth_mod.SECRET_KEY,
        algorithm=auth_mod.JWT_ALGORITHM,
    )

    response = client.get("/auth/mcp-tokens", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["tokens"][0]["kid"] == "alice_1"
