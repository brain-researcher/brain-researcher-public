"""Thin Brain Researcher participant for Notebook Intelligence."""

from __future__ import annotations

from typing import Any

from ._compat import (
    ChatCommand,
    ChatParticipant,
    ChatRequest,
    ChatResponse,
    Host,
    MarkdownData,
    Tool,
)
from .config import BrainResearcherNotebookIntelligenceSettings


def build_brain_researcher_system_prompt(
    settings: BrainResearcherNotebookIntelligenceSettings,
) -> str:
    return (
        f"You are {settings.product_name}, a neuroimaging research assistant "
        "embedded inside JupyterLab. Prefer Brain Researcher MCP tools for "
        "dataset discovery, task and contrast interpretation, workflow "
        "recommendations, and methodological guidance. Keep notebook work "
        "grounded in the user's files, cells, and current workspace. When "
        "code or execution is needed, help the user produce notebook-safe, "
        "runnable steps rather than abstract advice."
    )


class BrainResearcherParticipant(ChatParticipant):
    def __init__(
        self,
        *,
        host: Host | None = None,
        settings: BrainResearcherNotebookIntelligenceSettings | None = None,
    ) -> None:
        self._host = host
        self._settings = (
            settings or BrainResearcherNotebookIntelligenceSettings.from_env()
        )

    @property
    def id(self) -> str:
        return self._settings.participant_id

    @property
    def name(self) -> str:
        return self._settings.participant_name

    @property
    def description(self) -> str:
        return self._settings.participant_description

    @property
    def commands(self) -> list[ChatCommand]:
        return [
            ChatCommand(
                name="help",
                description="Show Brain Researcher notebook guidance.",
            ),
            ChatCommand(
                name="tools",
                description="List the connected Brain Researcher MCP tools.",
            ),
        ]

    @property
    def tools(self) -> list[Tool]:
        server = self._get_mcp_server()
        if server is None:
            return []
        try:
            tools = server.get_tools()
        except Exception:
            return []
        return list(tools or [])

    async def handle_chat_request(
        self,
        request: ChatRequest,
        response: ChatResponse,
        options: dict[str, Any] | None = None,
    ) -> None:
        command = (getattr(request, "command", "") or "").strip().lower()
        if command == "help":
            response.stream(MarkdownData(self._render_help_markdown()))
            response.finish()
            return
        if command == "tools":
            response.stream(MarkdownData(self._render_tools_markdown()))
            response.finish()
            return

        active_host = getattr(request, "host", None) or self._host
        if getattr(active_host, "chat_model", None) is None:
            response.stream(MarkdownData(self._render_missing_model_markdown()))
            response.finish()
            return

        merged_options = dict(options or {})
        merged_options.setdefault(
            "system_prompt",
            build_brain_researcher_system_prompt(self._settings),
        )
        await self.handle_chat_request_with_tools(
            request,
            response,
            options=merged_options,
            tool_context={"mcp_server_name": self._settings.mcp_server_name},
        )

    def _get_mcp_server(self):
        if self._host is None:
            return None
        try:
            return self._host.get_mcp_server(self._settings.mcp_server_name)
        except Exception:
            return None

    def _render_help_markdown(self) -> str:
        return (
            f"## {self._settings.product_name}\n\n"
            "Use me for neuroimaging-aware help inside this notebook workspace.\n\n"
            "- Ask for dataset discovery, task or contrast interpretation, atlas or ROI guidance, or workflow recommendations.\n"
            f"- I will prefer MCP tools from `{self._settings.mcp_server_name}` when they are connected.\n"
            "- Keep requests notebook-oriented: reference the current file, active cells, or the next runnable analysis step."
        )

    def _render_tools_markdown(self) -> str:
        tools = self.tools
        if not tools:
            return (
                "## Brain Researcher MCP tools\n\n"
                f"No tools are currently available from `{self._settings.mcp_server_name}`."
            )
        tool_lines = "\n".join(
            f"- `{tool.name}`: {getattr(tool, 'description', '')}".rstrip()
            for tool in tools
        )
        return (
            "## Brain Researcher MCP tools\n\n"
            f"Connected server: `{self._settings.mcp_server_name}`\n\n"
            f"{tool_lines}"
        )

    def _render_missing_model_markdown(self) -> str:
        return (
            "## Notebook model not configured\n\n"
            "Notebook Intelligence does not currently have a chat model configured "
            "for Brain Researcher. The BR MCP server is still wired in, so you can "
            "inspect the connected tools now and add an LLM provider later.\n\n"
            f"{self._render_tools_markdown()}"
        )
