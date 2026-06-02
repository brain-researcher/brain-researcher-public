"""Shared helpers for LLM router access within the knowledge layer."""

from functools import lru_cache


@lru_cache(maxsize=1)
def get_llm_router():
    """Lazily instantiate and cache a single LLMRouter instance.

    Caches at module level to avoid repeated startup costs while keeping a
    simple import surface for callers.
    """

    from brain_researcher.services.agent.router import LLMRouter

    return LLMRouter()
