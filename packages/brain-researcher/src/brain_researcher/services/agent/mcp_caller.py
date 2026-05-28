"""Lazy MCP caller helpers for external tracker integrations.

This module intentionally keeps a tiny per-call MCP bridge and compatibility
helpers for existing call sites that still import ``create_mcp_caller``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


def _resolve_env(new_key: str, legacy_key: str) -> Tuple[Optional[str], bool]:
    """Resolve env with one-release compatibility.

    Returns:
        (value, used_legacy)
    """
    new_val = os.getenv(new_key)
    if new_val:
        return new_val, False

    legacy_val = os.getenv(legacy_key)
    if legacy_val:
        logger.info(
            "Using deprecated env var %s; migrate to %s.",
            legacy_key,
            new_key,
        )
        return legacy_val, True

    return None, False


class LazyStdioMCPCaller:
    """Per-call MCP stdio client."""

    def __init__(self, server_command: Optional[list[str]] = None):
        if server_command is not None:
            self.server_command = server_command
        else:
            raise ValueError("server_command is required for LazyStdioMCPCaller")

    async def __call__(self, tool_name: str, params: dict) -> Optional[dict]:
        """Execute an MCP tool call with a per-call connection."""
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client
        except Exception as e:  # pragma: no cover
            logger.warning(f"MCP client dependencies missing: {e}")
            return None

        env = os.environ.copy()
        server_params = StdioServerParameters(
            command=self.server_command[0],
            args=self.server_command[1:],
            env=env,
        )

        try:
            async with stdio_client(server_params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, params)
                    # Most MCP servers return JSON in the first text content entry.
                    content = result.content[0].text if result.content else None
                    if content:
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse MCP response for {tool_name}: {content[:200]}")
                            return None
                    return {"success": True}
        except asyncio.TimeoutError:
            logger.warning(f"MCP call timed out for {tool_name}")
        except Exception as e:
            logger.warning(f"MCP call {tool_name} failed: {e}")
        return None


class LazyLinearMCPCaller(LazyStdioMCPCaller):
    """Backward-compatible Linear caller."""

    def __init__(self, server_command: Optional[list[str]] = None):
        super().__init__(server_command=server_command or _default_linear_server_command())


def _default_linear_server_command() -> list[str]:
    """Resolve the linear MCP server command."""
    if shutil.which("linear-mcp-server"):
        return ["linear-mcp-server"]
    return ["npx", "-y", "linear-mcp-server"]


def create_linear_mcp_caller() -> Optional[Callable]:
    """Return a Linear MCP caller if required env is configured."""
    team_id, _ = _resolve_env("BR_PLAN_TRACKER_LINEAR_TEAM_ID", "LINEAR_TEAM_ID")
    api_key, _ = _resolve_env("BR_PLAN_TRACKER_LINEAR_API_KEY", "LINEAR_API_KEY")

    if not team_id:
        logger.debug("Linear tracker team ID not set, skipping MCP caller")
        return None
    if not api_key or len(api_key) < 10:
        logger.warning("Linear tracker team ID set but API key missing/invalid")
        return None

    return LazyLinearMCPCaller()


def create_mcp_caller() -> Optional[Callable]:
    """Compatibility wrapper for legacy imports.

    Deprecated:
        Prefer ``create_linear_mcp_caller`` or issue-tracker factory methods.
    """
    logger.debug(
        "create_mcp_caller is deprecated; use create_linear_mcp_caller or "
        "create_issue_tracker_backend."
    )
    return create_linear_mcp_caller()

