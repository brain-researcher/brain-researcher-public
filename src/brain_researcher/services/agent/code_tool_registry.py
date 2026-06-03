"""Minimal tool registry for coding tasks.

This registry contains only the tools needed for code editing:
- code.fs.read_file: Read file content
- code.fs.read_dir: List directory with content preview
- code.fs.apply_patch: Apply unified diff patches
- code.search: Ripgrep-style code search
- code.shell.run_tests: Run test commands
- code.sandbox.run: Execute Python in sandbox

This isolation ensures the coding agent sees only these 6 tools,
not the 200+ tools in the general registry.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CodeToolRegistry:
    """Minimal tool registry for coding tasks.

    Unlike the general ToolRegistry which auto-discovers 200+ tools,
    this registry manually registers only the 6 code-specific tools
    needed for the CodeOrchestrator.
    """

    def __init__(self):
        self._tools: dict[str, CodeTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the minimal code tool set."""
        from brain_researcher.services.agent.code_tools import (
            ApplyPatchTool,
            CodeSearchTool,
            ReadDirTool,
            ReadFileTool,
            RunTestsTool,
            SandboxRunTool,
        )

        tools = [
            ReadFileTool(),
            ReadDirTool(),
            ApplyPatchTool(),
            CodeSearchTool(),
            RunTestsTool(),
            SandboxRunTool(),
        ]

        for tool in tools:
            self._tools[tool.name] = tool
            logger.debug("Registered code tool: %s", tool.name)

    def get_tool(self, name: str) -> CodeTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI-compatible tool schemas for all tools."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def execute(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name with given parameters."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}

        try:
            return tool.run(**params)
        except Exception as exc:
            logger.exception("Tool %s failed: %s", tool_name, exc)
            return {"status": "error", "error": str(exc)}


class CodeTool:
    """Base class for code tools."""

    name: str = "code.tool"
    description: str = "A code tool"

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for tool parameters."""
        raise NotImplementedError

    def run(self, **kwargs) -> dict[str, Any]:
        """Execute the tool and return result."""
        raise NotImplementedError

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }


# Singleton instance
_code_tool_registry: CodeToolRegistry | None = None


def get_code_tool_registry() -> CodeToolRegistry:
    """Get or create the shared CodeToolRegistry instance."""
    global _code_tool_registry
    if _code_tool_registry is None:
        _code_tool_registry = CodeToolRegistry()
    return _code_tool_registry


__all__ = ["CodeToolRegistry", "CodeTool", "get_code_tool_registry"]
