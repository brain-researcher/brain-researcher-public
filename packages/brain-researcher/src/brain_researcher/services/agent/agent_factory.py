"""Shared factory for LLM-native NeuroAgentLLM with per-mode caching.

All frontends (CLI, /act_llm, UI) should resolve agents through this factory so
behaviour differences (tool_mode, coding bias, model choice) are explicit and
cache keys remain isolated.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import os
import threading
from typing import Optional

from brain_researcher.services.agent.tool_retriever import ToolRetriever
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

CODING_KEYWORDS = ("code", "fs", "git", "repo", "job", "terminal")
DEFAULT_CODING_MODEL = "gemini-3-flash-preview"
_FILTERED_REGISTRY_LOCK = threading.Lock()
_FILTERED_REGISTRY_CACHE: dict[str, ToolRegistry] = {}


def _default_registry_cache_key(tool_registry: ToolRegistry) -> str | None:
    """Best-effort cache key derived from a registry's exposed tool surface."""

    tools = getattr(tool_registry, "tools", None)
    if not isinstance(tools, dict):
        return None

    tool_ids = sorted(str(tool_id) for tool_id in tools.keys() if str(tool_id))
    digest = hashlib.sha256("\n".join(tool_ids).encode("utf-8")).hexdigest()[:16]
    return f"surface:{len(tool_ids)}:{digest}"


def _sort_tools_for_coding(tools):
    """Stable-sort tools so coding-related tools are bound first."""

    def _priority(tool):
        name = getattr(tool, "name", "") or getattr(tool, "tool_name", "")
        n = name.lower()
        return 0 if any(k in n for k in CODING_KEYWORDS) else 1

    return sorted(tools, key=_priority)


def _build_llm_agent(
    *,
    model: str,
    tool_mode: str,
    coding_bias: bool,
    tool_registry: Optional[ToolRegistry] = None,
):
    """Construct a NeuroAgentLLM instance with optional injected registry."""

    from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM

    use_retriever = os.getenv("BR_USE_TOOL_RETRIEVER", "true").lower() == "true"
    tool_retriever = None
    if use_retriever:
        try:
            tool_retriever = ToolRetriever()
            logger.info("Initialized ToolRetriever for two-stage selection")
        except Exception as exc:  # pragma: no cover - best effort init
            logger.warning("Failed to initialize ToolRetriever: %s", exc)

    agent = NeuroAgentLLM(
        llm_model=model,
        tool_choice=tool_mode,
        tool_retriever=tool_retriever,
        tool_registry=tool_registry,
    )

    # Re-order tools for coding bias while keeping full registry
    if coding_bias and getattr(agent, "tools", None):
        sorted_tools = _sort_tools_for_coding(agent.tools)
        agent.tools = sorted_tools
        try:
            bind_kwargs = {"tool_choice": tool_mode} if tool_mode else {}
            agent.llm_with_tools = agent.llm.bind_tools(sorted_tools, **bind_kwargs)
        except TypeError:
            agent.llm_with_tools = agent.llm.bind_tools(sorted_tools)

    logger.info(
        "Initialized NeuroAgentLLM (model=%s, tool_choice=%s, coding_bias=%s, retriever=%s, custom_registry=%s)",
        model,
        tool_mode,
        coding_bias,
        bool(tool_retriever),
        bool(tool_registry),
    )
    return agent


@functools.lru_cache(maxsize=16)
def _get_cached_agent(model: str, tool_mode: str, coding_bias: bool):
    """Internal cached factory keyed by model/tool_mode/coding flag."""
    return _build_llm_agent(
        model=model,
        tool_mode=tool_mode,
        coding_bias=coding_bias,
    )


@functools.lru_cache(maxsize=32)
def _get_cached_agent_for_registry(
    model: str,
    tool_mode: str,
    coding_bias: bool,
    tool_registry_cache_key: str,
):
    """Cached factory for injected registries keyed by filtered tool surface."""

    with _FILTERED_REGISTRY_LOCK:
        tool_registry = _FILTERED_REGISTRY_CACHE.get(tool_registry_cache_key)
    if tool_registry is None:  # pragma: no cover - defensive
        raise KeyError(
            f"Missing cached ToolRegistry for cache key {tool_registry_cache_key!r}"
        )
    return _build_llm_agent(
        model=model,
        tool_mode=tool_mode,
        coding_bias=coding_bias,
        tool_registry=tool_registry,
    )


def get_llm_agent(
    *,
    tool_mode: Optional[str] = None,
    coding_bias: bool = False,
    model_override: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None,
    tool_registry_cache_key: Optional[str] = None,
):
    """Resolve (or create) an agent keyed by model/tool_mode/coding_bias."""

    model = model_override
    if not model:
        model = (
            os.getenv("DEFAULT_CODING_MODEL", DEFAULT_CODING_MODEL)
            if coding_bias
            else os.getenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
        )

    mode = tool_mode or (
        "required" if coding_bias else os.getenv("BR_TOOL_CHOICE_MODE", "required")
    )
    if mode not in {"auto", "required", "none"}:
        mode = "required"

    if tool_registry is not None:
        cache_key = tool_registry_cache_key or _default_registry_cache_key(
            tool_registry
        )
        if cache_key:
            with _FILTERED_REGISTRY_LOCK:
                _FILTERED_REGISTRY_CACHE[cache_key] = tool_registry
            return _get_cached_agent_for_registry(
                model,
                mode,
                coding_bias,
                cache_key,
            )
        return _build_llm_agent(
            model=model,
            tool_mode=mode,
            coding_bias=coding_bias,
            tool_registry=tool_registry,
        )

    return _get_cached_agent(model, mode, coding_bias)


def get_coding_agent(tool_mode: Optional[str] = None):
    """Shortcut for a coding-biased agent (Gemini + tool prioritization)."""

    return get_llm_agent(tool_mode=tool_mode or "required", coding_bias=True)


def reset_llm_agent_cache() -> None:
    """Clear cached agents (useful for tests)."""

    _get_cached_agent.cache_clear()
    _get_cached_agent_for_registry.cache_clear()
    with _FILTERED_REGISTRY_LOCK:
        _FILTERED_REGISTRY_CACHE.clear()
