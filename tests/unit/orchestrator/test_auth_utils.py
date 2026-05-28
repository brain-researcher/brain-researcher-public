from datetime import timedelta

from brain_researcher.services.orchestrator import auth_utils


def test_access_token_round_trip(monkeypatch):
    monkeypatch.setattr(auth_utils, "SECRET_KEY", "test-secret")

    token = auth_utils.create_access_token(
        {"sub": "user_demo"}, expires_delta=timedelta(minutes=5)
    )

    payload = auth_utils.verify_token(token)

    assert payload is not None
    assert payload["sub"] == "user_demo"
    assert payload["type"] == "access"


def test_verify_token_rejects_wrong_token_type(monkeypatch):
    monkeypatch.setattr(auth_utils, "SECRET_KEY", "test-secret")

    token = auth_utils.create_refresh_token(
        {"sub": "user_demo"}, expires_delta=timedelta(minutes=5)
    )

    assert auth_utils.verify_token(token, token_type="access") is None
