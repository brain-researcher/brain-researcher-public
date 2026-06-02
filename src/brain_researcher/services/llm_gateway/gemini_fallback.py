"""Compatibility wrapper for the Gemini CLI fallback cascade."""

from __future__ import annotations

from brain_researcher.services.llm_gateway.llm_budget_manager import (
    get_shared_llm_budget_manager,
)
from brain_researcher.services.llm_gateway.managed_credential_pool import (
    get_shared_managed_pool,
)
from brain_researcher.services.llm_gateway.router import LLMRouter

# Module-wide router instance so tests can monkeypatch attributes if required.
_ROUTER = LLMRouter(
    budget_manager=get_shared_llm_budget_manager(),
    managed_pool=get_shared_managed_pool(),
)


def chat_with_fallback(
    prompt: str,
    initial_model: str = "gemini-3-flash-preview",
    credential_name: str | None = None,
) -> tuple[str, str, str, dict, str | None]:
    """
    Execute a single chat request using the shared LLM router.

    Returns a tuple to preserve the historical contract:
        (text, provider, model_name, usage, fallback_reason)
    """
    result = _ROUTER.route_chat(
        prompt,
        model_hint=initial_model,
        credential_name=credential_name,
    )
    metadata = result.metadata
    return (
        result.text,
        metadata.provider,
        metadata.model,
        metadata.usage or {},
        metadata.fallback_reason,
    )


def _set_router_for_testing(router: LLMRouter) -> None:
    """Internal helper for tests to replace the shared router."""
    global _ROUTER  # noqa: PLW0603
    _ROUTER = router
