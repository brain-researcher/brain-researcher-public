import pytest

from brain_researcher.services.shared.planner.por_tokens import (
    issue_por_token,
    issue_por_token_from_env,
    verify_por_token,
    verify_por_token_from_env,
)


def test_por_token_roundtrip() -> None:
    token = issue_por_token(plan_id="plan-123", version=2, secret="secret", ttl_seconds=3600, now=100)
    claims = verify_por_token(token=token, plan_id="plan-123", version=2, secret="secret", now=200)
    assert claims.plan_id == "plan-123"
    assert claims.version == 2
    assert claims.iat == 100
    assert claims.exp == 100 + 3600


def test_por_token_rejects_mismatched_plan() -> None:
    token = issue_por_token(plan_id="plan-123", version=1, secret="secret", ttl_seconds=3600, now=10)
    with pytest.raises(ValueError, match="does not match"):
        verify_por_token(token=token, plan_id="plan-999", version=1, secret="secret", now=20)


def test_por_token_rejects_expired() -> None:
    token = issue_por_token(plan_id="plan-123", version=1, secret="secret", ttl_seconds=60, now=10)
    with pytest.raises(ValueError, match="expired"):
        verify_por_token(token=token, plan_id="plan-123", version=1, secret="secret", now=1000)


def test_por_token_env_enforced_requires_secret(monkeypatch) -> None:
    monkeypatch.delenv("BR_POR_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("POR_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("BRAIN_RESEARCHER_POR_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError, match="BR_POR_TOKEN_SECRET"):
        issue_por_token_from_env(plan_id="plan-1", version=1)

    with pytest.raises(RuntimeError, match="BR_POR_TOKEN_SECRET"):
        verify_por_token_from_env(token="tok", plan_id="plan-1", version=1)

