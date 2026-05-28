from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
from brain_researcher.services.orchestrator import auth_endpoints as auth_mod


class _FakeUser:
    def __init__(
        self,
        *,
        user_id: str,
        username: str,
        email: str,
        role: str,
        is_active: bool = True,
        created_at: datetime | None = None,
    ) -> None:
        self.id = user_id
        self.username = username
        self.email = email
        self.full_name = username
        self.role = SimpleNamespace(value=role)
        self.is_active = is_active
        self.auth_provider = "password"
        self.created_at = created_at or datetime.utcnow()
        self.last_login = None
        self.preferences = {}
        self.hashed_password = None


def _make_token(sub: str) -> str:
    return jwt.encode({"sub": sub}, auth_mod.SECRET_KEY, algorithm=auth_mod.JWT_ALGORITHM)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_mod.router)
    return TestClient(app)


def test_admin_users_requires_admin_role(monkeypatch):
    admin = _FakeUser(user_id="user_admin", username="admin", email="a@example.com", role="researcher")

    class _Store:
        async def get_by_id(self, _user_id: str):
            return admin

        async def list_all(self):
            return [admin]

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    client = _make_client()
    token = _make_token("user_admin")
    response = client.get("/auth/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_admin_users_lists_and_filters(monkeypatch):
    now = datetime.utcnow()
    admin = _FakeUser(
        user_id="user_admin",
        username="admin",
        email="admin@example.com",
        role="admin",
        created_at=now - timedelta(days=2),
    )
    active_user = _FakeUser(
        user_id="user_a",
        username="alice",
        email="alice@example.com",
        role="researcher",
        created_at=now - timedelta(days=1),
    )
    inactive_user = _FakeUser(
        user_id="user_b",
        username="bob",
        email="bob@example.com",
        role="viewer",
        is_active=False,
        created_at=now,
    )

    class _Store:
        async def get_by_id(self, user_id: str):
            return admin if user_id == "user_admin" else None

        async def list_all(self):
            return [admin, active_user, inactive_user]

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    client = _make_client()
    token = _make_token("user_admin")

    response = client.get("/auth/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["count"] == 2
    usernames = {item["username"] for item in payload["users"]}
    assert usernames == {"admin", "alice"}

    response_all = client.get(
        "/auth/admin/users?include_inactive=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response_all.status_code == 200
    payload_all = response_all.json()
    assert payload_all["total"] == 3
    assert payload_all["count"] == 3
    assert any(item["username"] == "bob" for item in payload_all["users"])


def test_admin_can_mark_force_password_reset(monkeypatch):
    admin = _FakeUser(
        user_id="user_admin",
        username="admin",
        email="admin@example.com",
        role="admin",
    )
    target = _FakeUser(
        user_id="user_target",
        username="alice",
        email="alice@example.com",
        role="researcher",
    )

    class _Store:
        async def get_by_id(self, user_id: str):
            if user_id == "user_admin":
                return admin
            if user_id == "user_target":
                return target
            return None

        async def list_all(self):
            return [admin, target]

        async def mark_password_reset_required(self, user_id: str, reason: str):
            user = await self.get_by_id(user_id)
            if user is None:
                return None
            user.preferences["must_reset_password"] = True
            user.preferences["password_reset"] = {"required": True, "reason": reason}
            return user

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    client = _make_client()
    token = _make_token("user_admin")

    response = client.post(
        "/auth/admin/users/user_target/force-password-reset",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "missing_password_hash"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["user"]["id"] == "user_target"
    assert payload["user"]["password_reset_required"] is True


def test_admin_can_set_password_and_clear_reset(monkeypatch):
    admin = _FakeUser(
        user_id="user_admin",
        username="admin",
        email="admin@example.com",
        role="admin",
    )
    target = _FakeUser(
        user_id="user_target",
        username="alice",
        email="alice@example.com",
        role="researcher",
    )
    target.preferences = {"must_reset_password": True}

    class _Store:
        async def get_by_id(self, user_id: str):
            if user_id == "user_admin":
                return admin
            if user_id == "user_target":
                return target
            return None

        async def list_all(self):
            return [admin, target]

        async def set_password_hash(self, user_id: str, hashed_password: str, clear_reset_flag: bool = True):
            user = await self.get_by_id(user_id)
            if user is None:
                return None
            user.hashed_password = hashed_password
            if clear_reset_flag:
                user.preferences.pop("must_reset_password", None)
            return user

    monkeypatch.setattr(auth_mod, "_user_store", _Store())
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.auth_utils.hash_password",
        lambda plain: f"hash::{plain}",
    )
    client = _make_client()
    token = _make_token("user_admin")

    response = client.post(
        "/auth/admin/users/user_target/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_password": "NewDemoPass123!", "clear_reset_flag": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["user"]["id"] == "user_target"
    assert payload["user"]["password_reset_required"] is False
    assert target.hashed_password == "hash::NewDemoPass123!"
