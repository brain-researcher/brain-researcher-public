from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

_SEMANTIC_MATCHING_ENABLED: ContextVar[bool | None] = ContextVar(
    "br_runtime_semantic_matching_enabled",
    default=None,
)


def _parse_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def semantic_matching_enabled(
    explicit: bool | None = None,
    *,
    default: bool = True,
    env_var: str = "BR_RUNTIME_SEMANTIC_MATCHING",
) -> bool:
    """Resolve whether heavyweight semantic matching is enabled.

    Priority:
    1. explicit call-site override
    2. current request/runtime scope
    3. environment override
    4. caller-provided default
    """

    if explicit is not None:
        return bool(explicit)

    scoped = _SEMANTIC_MATCHING_ENABLED.get()
    if scoped is not None:
        return bool(scoped)

    env_value = _parse_optional_bool(os.environ.get(env_var))
    if env_value is not None:
        return env_value

    return bool(default)


@contextmanager
def semantic_matching_scope(enabled: bool | None) -> Iterator[None]:
    """Temporarily override heavyweight semantic matching for the current scope."""

    token = _SEMANTIC_MATCHING_ENABLED.set(
        None if enabled is None else bool(enabled)
    )
    try:
        yield
    finally:
        _SEMANTIC_MATCHING_ENABLED.reset(token)


@lru_cache(maxsize=2)
def get_cached_sentence_transformer(model_name: str):
    """Return a process-wide cached SentenceTransformer instance."""

    runtime_user = os.environ.get("BR_EMBEDDING_RUNTIME_USER", "brain-researcher")
    for key in ("USER", "LOGNAME", "LNAME", "USERNAME"):
        os.environ.setdefault(key, runtime_user)
    os.environ.setdefault("HOME", tempfile.gettempdir())
    cache_dir = os.environ.setdefault(
        "TORCHINDUCTOR_CACHE_DIR",
        os.path.join(tempfile.gettempdir(), "torchinductor_brain_researcher"),
    )
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def prewarm_sentence_transformer(model_name: str = "all-MiniLM-L6-v2") -> None:
    """Best-effort prewarm for the shared SentenceTransformer cache."""

    get_cached_sentence_transformer(model_name)


__all__ = [
    "get_cached_sentence_transformer",
    "prewarm_sentence_transformer",
    "semantic_matching_enabled",
    "semantic_matching_scope",
]
