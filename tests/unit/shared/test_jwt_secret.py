from __future__ import annotations

from brain_researcher.services.shared import jwt_secret


def test_resolve_shared_jwt_secret_prefers_repo_secret_on_dev_mismatch(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "process-secret")
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.setattr(jwt_secret, "_is_test_env", lambda: False)
    monkeypatch.setattr(
        jwt_secret,
        "get_repo_dotenv_value",
        lambda key: "repo-secret" if key == "JWT_SECRET_KEY" else None,
    )

    resolved = jwt_secret.resolve_shared_jwt_secret(
        env_names=("JWT_SECRET_KEY", "NEXTAUTH_SECRET")
    )

    assert resolved == "repo-secret"


def test_resolve_shared_jwt_secret_uses_explicit_secret_when_repo_missing(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("NEXTAUTH_SECRET", "nextauth-secret")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setattr(jwt_secret, "_is_test_env", lambda: False)
    monkeypatch.setattr(jwt_secret, "get_repo_dotenv_value", lambda key: None)

    resolved = jwt_secret.resolve_shared_jwt_secret(
        env_names=("JWT_SECRET_KEY", "NEXTAUTH_SECRET")
    )

    assert resolved == "nextauth-secret"
