"""Lightweight auth shims for survey endpoints (test/integration use).

These functions provide minimal stand-ins so that survey modules can be
imported and exercised in tests without wiring the full auth stack from
`main_enhanced.py`. Real deployments should use the richer implementations
there; this module is intentionally simple and side-effect free.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    roles: list[str] = []


async def get_current_user() -> User:
    """Return a minimal test user."""
    return User(id="test-user", username="test", email="test@example.com", roles=["tester"])


async def get_current_active_user() -> User:
    """Alias for get_current_user for compatibility."""
    return await get_current_user()

