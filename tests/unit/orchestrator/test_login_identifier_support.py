import json

import pytest
from starlette.requests import Request

from brain_researcher.services.orchestrator.main_enhanced import login
from brain_researcher.services.orchestrator.models import LoginRequest, User, UserRole


def _build_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "headers": [],
    }
    return Request(scope, receive)


def _build_user() -> User:
    return User(
        id="user_demo",
        username="demo",
        email="demo@brain-researcher.ai",
        full_name="Demo User",
        role=UserRole.RESEARCHER,
        hashed_password="fake-hash",
        auth_provider="password",
    )


@pytest.mark.asyncio
async def test_login_accepts_email_identifier(monkeypatch):
    user = _build_user()

    async def fake_get_by_username(_):
        return None

    async def fake_get_by_email(email):
        return user if email == "demo@brain-researcher.ai" else None

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced._user_store.get_by_username",
        fake_get_by_username,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced._user_store.get_by_email",
        fake_get_by_email,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced.verify_password",
        lambda plain, _hashed: plain == "demo123",
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced.users_db",
        {},
    )

    response = await login(
        _build_request(),
        LoginRequest(email="demo@brain-researcher.ai", password="demo123"),
    )
    payload = json.loads(response.body.decode("utf-8"))
    assert response.status_code == 200
    assert payload["user"]["email"] == "demo@brain-researcher.ai"


@pytest.mark.asyncio
async def test_login_accepts_username_identifier(monkeypatch):
    user = _build_user()

    async def fake_get_by_username(username):
        return user if username == "demo" else None

    async def fake_get_by_email(_):
        return None

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced._user_store.get_by_username",
        fake_get_by_username,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced._user_store.get_by_email",
        fake_get_by_email,
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced.verify_password",
        lambda plain, _hashed: plain == "demo123",
    )
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.main_enhanced.users_db",
        {},
    )

    response = await login(
        _build_request(),
        LoginRequest(username="demo", password="demo123"),
    )
    payload = json.loads(response.body.decode("utf-8"))
    assert response.status_code == 200
    assert payload["user"]["username"] == "demo"


def test_login_request_requires_identifier():
    with pytest.raises(Exception):
        LoginRequest(password="demo123")
