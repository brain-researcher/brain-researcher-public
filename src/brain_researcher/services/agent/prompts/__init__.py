"""Prompt templates for agent components."""

from brain_researcher.services.agent.prompts.tool_routing import (
    ROUTER_PROMPT,
    build_router_prompt,
    format_tool_summary,
)

__all__ = [
    "ROUTER_PROMPT",
    "build_router_prompt",
    "format_tool_summary",
]
