"""Compatibility shim for agent tool allowlist helpers.

The implementation lives in ``brain_researcher.services.tools`` so lower-layer
tool catalog code does not import the agent service.
"""

from __future__ import annotations

from brain_researcher.services.tools.tool_allowlist_loader import (
    allow_remote_execution_tools_enabled,
    expand_plan_tool_ids,
    filter_local_first_tool_ids,
    is_local_first_blocked_tool,
    load_chat_tools_allowlist,
    load_full_tool_allowlist,
    resolve_runtime_tool_allowlist,
)


def resolve_plan_tool_allowlist(
    env_tool_allowlist: list[str] | None,
    *,
    allowlist_mode: str | None = None,
    strict: bool | None = None,
) -> list[str] | None:
    """Resolve a plan allowlist through shim globals for monkeypatch compatibility."""

    mode = str(allowlist_mode or "").strip().lower()
    if mode == "diagnostic":
        return expand_plan_tool_ids(load_full_tool_allowlist())
    return expand_plan_tool_ids(
        resolve_runtime_tool_allowlist(env_tool_allowlist, strict=strict)
    )


__all__ = [
    "allow_remote_execution_tools_enabled",
    "expand_plan_tool_ids",
    "filter_local_first_tool_ids",
    "is_local_first_blocked_tool",
    "load_chat_tools_allowlist",
    "load_full_tool_allowlist",
    "resolve_plan_tool_allowlist",
    "resolve_runtime_tool_allowlist",
]
