"""Shared JWT secret resolution helpers for local/dev service compatibility."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


def _is_test_env() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST") or os.getenv("BR_TESTING"))


@lru_cache(maxsize=1)
def _find_repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return None


@lru_cache(maxsize=32)
def get_repo_dotenv_value(key: str) -> str | None:
    repo_root = _find_repo_root()
    if repo_root is None:
        return None

    for filename in (".env.local", ".env"):
        env_path = repo_root / filename
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            current_key, value = line.split("=", 1)
            if current_key.strip() != key:
                continue
            normalized = value.strip().strip('"').strip("'")
            return normalized or None
    return None


def resolve_shared_jwt_secret(
    *,
    env_names: Iterable[str] = ("JWT_SECRET_KEY", "NEXTAUTH_SECRET", "JWT_SECRET"),
    dev_default: str | None = None,
    prefer_repo_secret_in_dev: bool = True,
) -> str | None:
    """Resolve a JWT secret with repo-root dotenv fallback in local development.

    In production, environment variables remain authoritative.
    In local dev, a repo-root dotenv secret can override mismatched process envs
    so independently launched services still agree on a single HS256 secret.
    """

    normalized_env_names = tuple(
        dict.fromkeys(str(name).strip() for name in env_names if name)
    )
    if not normalized_env_names:
        return dev_default

    explicit_values = [
        (name, str(value).strip())
        for name in normalized_env_names
        if (value := os.getenv(name)) and str(value).strip()
    ]
    explicit_secret = explicit_values[0][1] if explicit_values else None

    is_production = os.getenv("NODE_ENV") == "production" or (
        (os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
        in {"prod", "production"}
    )
    if is_production:
        return explicit_secret or dev_default

    repo_secret = (
        None
        if _is_test_env()
        else next(
            (
                value
                for name in normalized_env_names
                if (value := get_repo_dotenv_value(name))
            ),
            None,
        )
    )

    if (
        prefer_repo_secret_in_dev
        and repo_secret
        and explicit_secret
        and explicit_secret != repo_secret
    ):
        logger.warning(
            "JWT secret differs from repo-root dotenv secret; using repo-root value in local dev."
        )
        return repo_secret

    if explicit_secret:
        return explicit_secret
    if repo_secret:
        return repo_secret
    return dev_default
