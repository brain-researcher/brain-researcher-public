"""Dependency-inversion seam for the review-layer LLM judgment critics.

The scientific judgment critics in ``services/review`` need to route a prompt
to an LLM provider, which is implemented by ``services/agent`` (the
``LLMRouter``). ``review`` sits *below* ``agent`` in the services layer order
(``... < review < ... < agent < ...``), so importing ``LLMRouter`` directly is a
back-edge.

This module defines the minimal structural contract the critics depend on
(``JudgmentRouter`` / ``JudgmentChatResult``) plus a tiny registry for the
default router factory. The concrete ``LLMRouter`` is registered by a higher
layer (the MCP server, which is the real entrypoint into the review path and
already imports ``agent``); ``review`` depends only on this ``shared`` seam.

If no factory has been registered (e.g. a unit test that does not exercise the
agent layer and does not pass an explicit router), ``get_default_judgment_router``
raises ``RuntimeError``. Every caller constructs the default router inside a
``try`` block that degrades to a conservative "provider_failed" verdict, so a
missing registration never silently looks like scientific approval.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class JudgmentChatResult(Protocol):
    """Structural result of a single chat invocation used by the critics.

    The critics only read ``.text``; the concrete ``LLMChatResult`` carries
    additional routing metadata that is irrelevant to verdict parsing.
    """

    @property
    def text(self) -> str: ...


@runtime_checkable
class JudgmentRouter(Protocol):
    """Structural contract for the LLM router used by the judgment critics."""

    def route_chat(self, **kwargs: Any) -> JudgmentChatResult: ...


JudgmentRouterFactory = Callable[[], JudgmentRouter]

_default_judgment_router_factory: JudgmentRouterFactory | None = None


def register_default_judgment_router(factory: JudgmentRouterFactory) -> None:
    """Register the factory used to build the default judgment router.

    Idempotent by design: the higher layer may register on every import.
    """

    global _default_judgment_router_factory
    _default_judgment_router_factory = factory


def has_default_judgment_router() -> bool:
    """Whether a default judgment-router factory has been registered."""

    return _default_judgment_router_factory is not None


def get_default_judgment_router() -> JudgmentRouter:
    """Build the registered default judgment router.

    Raises:
        RuntimeError: if no factory has been registered. Callers construct the
            default router inside a ``try`` block and degrade gracefully.
    """

    factory = _default_judgment_router_factory
    if factory is None:
        raise RuntimeError(
            "No default judgment router registered. The agent-layer LLMRouter "
            "factory must be registered via register_default_judgment_router() "
            "before the judgment critic runs without an explicit router."
        )
    return factory()


__all__ = [
    "JudgmentChatResult",
    "JudgmentRouter",
    "JudgmentRouterFactory",
    "register_default_judgment_router",
    "has_default_judgment_router",
    "get_default_judgment_router",
]
