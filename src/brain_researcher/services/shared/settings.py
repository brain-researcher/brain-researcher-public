"""Shared runtime settings for agent and orchestrator services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_CODE_AGENT_TOOL_ID = "code_agent"


def _parse_allowlist(raw: str) -> list[str] | None:
    cleaned = raw.strip()
    if not cleaned or cleaned == "*":
        return None
    entries = [item.strip() for item in cleaned.split(",") if item.strip()]
    return entries or None


@dataclass(frozen=True)
class Settings:
    """Container for environment-driven runtime settings."""

    planner_mode: str
    tool_allowlist: list[str] | None
    enable_code_agent_tool: bool
    sandbox_enabled: bool
    dag_max_concurrency: int

    @property
    def allow_all_tools(self) -> bool:
        return self.tool_allowlist is None

    def is_tool_allowed(self, tool_id: str) -> bool:
        if tool_id == _CODE_AGENT_TOOL_ID and not self.enable_code_agent_tool:
            return False
        return self.tool_allowlist is None or tool_id in self.tool_allowlist


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from environment once and cache the result."""

    planner_mode = os.getenv("BR_PLANNER_MODE", "advisor").strip().lower()
    if planner_mode not in {"advisor", "autorun", "disabled"}:
        planner_mode = "advisor"

    raw_allowlist = os.getenv("AGENT_TOOL_ALLOWLIST", "*")
    tool_allowlist = _parse_allowlist(raw_allowlist)

    enable_code_agent_tool = os.getenv(
        "BR_ENABLE_CODE_AGENT_TOOL", "0"
    ).strip().lower() in {"1", "true", "yes", "on"}

    sandbox_enabled = os.getenv("BR_SANDBOX_ENABLED", "true").strip().lower() == "true"

    try:
        dag_max_concurrency = int(os.getenv("BR_DAG_MAX_CONCURRENCY", "1"))
    except ValueError:
        dag_max_concurrency = 1

    return Settings(
        planner_mode=planner_mode,
        tool_allowlist=tool_allowlist,
        enable_code_agent_tool=enable_code_agent_tool,
        sandbox_enabled=sandbox_enabled,
        dag_max_concurrency=max(1, dag_max_concurrency),
    )
