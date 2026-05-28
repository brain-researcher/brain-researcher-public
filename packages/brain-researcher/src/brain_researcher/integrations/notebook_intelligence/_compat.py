"""Compatibility helpers for optional Notebook Intelligence imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NOTEBOOK_INTELLIGENCE_AVAILABLE = False
NOTEBOOK_INTELLIGENCE_IMPORT_ERROR: Exception | None = None

try:
    from notebook_intelligence.api import (  # type: ignore[import-not-found]
        ChatCommand,
        ChatParticipant,
        ChatRequest,
        ChatResponse,
        Host,
        MarkdownData,
        MCPServer,
        NotebookIntelligenceExtension,
        Tool,
    )

    NOTEBOOK_INTELLIGENCE_AVAILABLE = True
except Exception as exc:  # pragma: no cover - exercised in environments w/o NBI
    NOTEBOOK_INTELLIGENCE_IMPORT_ERROR = exc

    @dataclass(frozen=True)
    class ChatCommand:
        name: str = ""
        description: str = ""

    @dataclass
    class MarkdownData:
        content: str = ""
        detail: dict[str, Any] | None = None

    @dataclass
    class ChatRequest:
        host: Any = None
        command: str = ""
        prompt: str = ""
        chat_history: list[dict[str, Any]] = field(default_factory=list)
        cancel_token: Any = None

    class ChatResponse:
        participant_id = ""

        @property
        def message_id(self) -> str:
            return "offline"

        def stream(self, data: Any, finish: bool = False) -> None:
            raise RuntimeError("Notebook Intelligence is not installed.")

        def finish(self) -> None:
            raise RuntimeError("Notebook Intelligence is not installed.")

    class Tool:
        pass

    class MCPServer:
        def get_tools(self) -> list[Tool]:
            raise RuntimeError("Notebook Intelligence is not installed.")

    class Host:
        def register_chat_participant(self, participant: Any) -> None:
            raise RuntimeError("Notebook Intelligence is not installed.")

        def get_mcp_server(self, server_name: str) -> MCPServer | None:
            raise RuntimeError("Notebook Intelligence is not installed.")

    class ChatParticipant:
        @property
        def id(self) -> str:
            raise NotImplementedError

        @property
        def name(self) -> str:
            raise NotImplementedError

        @property
        def description(self) -> str:
            raise NotImplementedError

        @property
        def commands(self) -> list[ChatCommand]:
            return []

        @property
        def tools(self) -> list[Tool]:
            return []

        async def handle_chat_request(
            self,
            request: ChatRequest,
            response: ChatResponse,
            options: dict[str, Any] | None = None,
        ) -> None:
            raise NotImplementedError

        async def handle_chat_request_with_tools(
            self,
            request: ChatRequest,
            response: ChatResponse,
            options: dict[str, Any] | None = None,
            tool_context: dict[str, Any] | None = None,
            tool_choice: str = "auto",
        ) -> None:
            raise RuntimeError("Notebook Intelligence is not installed.")

    class NotebookIntelligenceExtension:
        @property
        def id(self) -> str:
            raise NotImplementedError

        @property
        def name(self) -> str:
            raise NotImplementedError

        @property
        def provider(self) -> str:
            raise NotImplementedError

        @property
        def url(self) -> str:
            raise NotImplementedError

        def activate(self, host: Host) -> None:
            raise NotImplementedError
