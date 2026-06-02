"""LLM router protocol for application-tier consumers.

Defines the narrow surface that application modules (autoresearch,
research, behavior) need from an LLM router without depending on the
concrete implementation in ``services.agent.router``. Service-tier code
constructs the concrete router and injects it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMRouterResult(Protocol):
    """Minimal result shape returned by ``LLMRouterProtocol.route_chat``."""

    text: str


@runtime_checkable
class LLMRouterProtocol(Protocol):
    """Minimal router surface used by application-tier callers."""

    def route_chat(
        self,
        *,
        prompt: str,
        model_hint: str,
        task_type: str,
        strict_json: bool,
    ) -> LLMRouterResult: ...


__all__ = ["LLMRouterProtocol", "LLMRouterResult"]
