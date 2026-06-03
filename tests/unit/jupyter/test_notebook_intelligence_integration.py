from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from brain_researcher.integrations.notebook_intelligence import (
    BrainResearcherNotebookIntelligenceExtension,
    BrainResearcherNotebookIntelligenceSettings,
    BrainResearcherParticipant,
    build_managed_mcp_server_config,
    build_user_config,
    resolve_notebook_intelligence_paths,
    write_extension_metadata,
    write_user_config,
    write_user_mcp_config,
)
from brain_researcher.integrations.notebook_intelligence._compat import MarkdownData


def test_nbi_settings_from_env(monkeypatch):
    monkeypatch.setenv("BR_PRODUCT_NAME", "Brain Researcher")
    monkeypatch.setenv("BR_PRODUCT_URL", "https://${PUBLIC_HOSTNAME}")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "https://hub.${PUBLIC_HOSTNAME}/mcp")
    monkeypatch.setenv("BR_MCP_BEARER_TOKEN", "secret-token")
    monkeypatch.setenv("BR_NBI_MCP_SERVER_NAME", "brain-researcher")
    monkeypatch.setenv("BR_NBI_CHAT_MODEL_PROVIDER", "openai-compatible")
    monkeypatch.setenv("BR_NBI_CHAT_MODEL_ID", "gpt-4.1")
    monkeypatch.setenv("BR_NBI_CHAT_MODEL_API_KEY", "chat-secret")
    monkeypatch.setenv("BR_NBI_CHAT_MODEL_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("BR_NBI_CHAT_MODEL_CONTEXT_WINDOW", "128000")
    monkeypatch.setenv(
        "BR_NOTEBOOK_INTELLIGENCE_AUTO_APPROVE_TOOLS",
        "kg_search_nodes,kg_verify_hypothesis",
    )

    settings = BrainResearcherNotebookIntelligenceSettings.from_env()
    mcp_server = build_managed_mcp_server_config(settings)

    assert settings.participant_name == "Brain Researcher"
    assert settings.mcp_server_name == "brain-researcher"
    assert build_user_config(settings)["chat_model"] == {
        "provider": "openai-compatible",
        "model": "openai-compatible-chat-model",
        "properties": [
            {"id": "model_id", "value": "gpt-4.1"},
            {"id": "api_key", "value": "chat-secret"},
            {"id": "base_url", "value": "https://api.openai.test/v1"},
            {"id": "context_window", "value": "128000"},
        ],
    }
    assert mcp_server == {
        "url": "https://hub.${PUBLIC_HOSTNAME}/mcp",
        "headers": {"Authorization": "Bearer secret-token"},
        "autoApprove": ["kg_search_nodes", "kg_verify_hypothesis"],
    }


def test_nbi_settings_fallback_to_managed_marimo_ai_env(monkeypatch):
    monkeypatch.setenv("BR_PRODUCT_NAME", "Brain Researcher")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "https://${PUBLIC_HOSTNAME}/mcp")
    monkeypatch.setenv("BR_MARIMO_AI_BASE_URL", "https://llm.${PUBLIC_HOSTNAME}/v1")
    monkeypatch.setenv("BR_MARIMO_AI_API_KEY", "runtime-ai-token")
    monkeypatch.setenv(
        "BR_MARIMO_AI_CHAT_MODEL",
        "brain-researcher/gemini-3-flash-preview",
    )
    monkeypatch.setenv(
        "BR_MARIMO_AI_AUTOCOMPLETE_MODEL",
        "brain-researcher/gemini-3-flash-preview",
    )

    settings = BrainResearcherNotebookIntelligenceSettings.from_env()
    payload = build_user_config(settings)

    assert settings.chat_model_provider == "openai-compatible"
    assert settings.chat_model_id == "gemini-3-flash-preview"
    assert settings.inline_completion_model_id == "gemini-3-flash-preview"
    assert payload["chat_model"] == {
        "provider": "openai-compatible",
        "model": "openai-compatible-chat-model",
        "properties": [
            {"id": "model_id", "value": "gemini-3-flash-preview"},
            {"id": "api_key", "value": "runtime-ai-token"},
            {
                "id": "base_url",
                "value": "https://llm.${PUBLIC_HOSTNAME}/v1",
            },
        ],
    }


def test_nbi_settings_fallback_to_builtin_google_marimo_ai_env(monkeypatch):
    monkeypatch.setenv("BR_PRODUCT_NAME", "Brain Researcher")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "https://${PUBLIC_HOSTNAME}/mcp")
    monkeypatch.setenv("BR_MARIMO_AI_PROVIDER_NAME", "google")
    monkeypatch.setenv("BR_MARIMO_AI_API_KEY", "runtime-ai-token")
    monkeypatch.setenv(
        "BR_MARIMO_AI_CHAT_MODEL",
        "google/gemini-3-flash-preview",
    )
    monkeypatch.setenv(
        "BR_MARIMO_AI_AUTOCOMPLETE_MODEL",
        "google/gemini-3-flash-preview",
    )

    settings = BrainResearcherNotebookIntelligenceSettings.from_env()
    payload = build_user_config(settings)

    assert settings.chat_model_provider == "google"
    assert settings.chat_model_id == "gemini-3-flash-preview"
    assert settings.inline_completion_provider == "google"
    assert payload["chat_model"] == {
        "provider": "google",
        "model": "gemini-3-flash-preview",
    }


def test_write_extension_metadata(tmp_path):
    settings = BrainResearcherNotebookIntelligenceSettings.from_env()

    metadata_path = write_extension_metadata(settings, prefix=tmp_path)
    paths = resolve_notebook_intelligence_paths(settings, prefix=tmp_path)

    assert metadata_path == paths.env_extension_metadata_file
    assert json.loads(metadata_path.read_text()) == {
        "class": settings.extension_class,
    }


def test_write_user_mcp_config_merges_existing_servers(tmp_path):
    settings = BrainResearcherNotebookIntelligenceSettings(
        product_name="Brain Researcher",
        workspace_mode="hosted",
        provider_name="Brain Researcher",
        provider_url="https://${PUBLIC_HOSTNAME}",
        extension_id="brain-researcher",
        extension_name="Brain Researcher",
        extension_slug="brain-researcher",
        extension_class=(
            "brain_researcher.integrations.notebook_intelligence.extension."
            "BrainResearcherNotebookIntelligenceExtension"
        ),
        participant_id="brain-researcher",
        participant_name="Brain Researcher",
        participant_description="Neuroimaging research assistant powered by BR MCP.",
        mcp_server_name="brain-researcher",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token="secret-token",
        default_chat_mode="ask",
        chat_model_provider="openai-compatible",
        chat_model_id="gpt-4.1",
        chat_model_api_key="chat-secret",
        chat_model_base_url="https://api.openai.test/v1",
        chat_model_context_window=128000,
        inline_completion_provider=None,
        inline_completion_model_id=None,
        inline_completion_api_key=None,
        inline_completion_base_url=None,
        inline_completion_context_window=None,
        auto_approve_tools=("kg_search_nodes",),
    )
    home = tmp_path / "home"
    existing_dir = home / ".jupyter" / "nbi"
    existing_dir.mkdir(parents=True)
    existing_file = existing_dir / "mcp.json"
    existing_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"url": "http://other/mcp"},
                    "brain-researcher": {"url": "http://stale/mcp"},
                }
            }
        )
    )

    written_path = write_user_mcp_config(settings, user_home=home)
    payload = json.loads(written_path.read_text())

    assert payload["mcpServers"]["other"] == {"url": "http://other/mcp"}
    assert payload["mcpServers"]["brain-researcher"] == {
        "url": "https://hub.${PUBLIC_HOSTNAME}/mcp",
        "headers": {"Authorization": "Bearer secret-token"},
        "autoApprove": ["kg_search_nodes"],
    }


def test_write_user_config_merges_existing_settings(tmp_path):
    settings = BrainResearcherNotebookIntelligenceSettings(
        product_name="Brain Researcher",
        workspace_mode="hosted",
        provider_name="Brain Researcher",
        provider_url="https://${PUBLIC_HOSTNAME}",
        extension_id="brain-researcher",
        extension_name="Brain Researcher",
        extension_slug="brain-researcher",
        extension_class=(
            "brain_researcher.integrations.notebook_intelligence.extension."
            "BrainResearcherNotebookIntelligenceExtension"
        ),
        participant_id="brain-researcher",
        participant_name="Brain Researcher",
        participant_description="Neuroimaging research assistant powered by BR MCP.",
        mcp_server_name="brain-researcher",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token="secret-token",
        default_chat_mode="ask",
        chat_model_provider="openai-compatible",
        chat_model_id="gpt-4.1",
        chat_model_api_key="chat-secret",
        chat_model_base_url="https://api.openai.test/v1",
        chat_model_context_window=128000,
        inline_completion_provider="openai-compatible",
        inline_completion_model_id="gpt-4.1-mini",
        inline_completion_api_key="inline-secret",
        inline_completion_base_url="https://api.openai.test/v1",
        inline_completion_context_window=8192,
        auto_approve_tools=("kg_search_nodes",),
    )
    home = tmp_path / "home"
    existing_dir = home / ".jupyter" / "nbi"
    existing_dir.mkdir(parents=True)
    existing_file = existing_dir / "config.json"
    existing_file.write_text(
        json.dumps({"store_github_access_token": False, "default_chat_mode": "agent"})
    )

    written_path = write_user_config(settings, user_home=home)
    payload = json.loads(written_path.read_text())

    assert payload["store_github_access_token"] is False
    assert payload["default_chat_mode"] == "ask"
    assert payload["chat_model"] == {
        "provider": "openai-compatible",
        "model": "openai-compatible-chat-model",
        "properties": [
            {"id": "model_id", "value": "gpt-4.1"},
            {"id": "api_key", "value": "chat-secret"},
            {"id": "base_url", "value": "https://api.openai.test/v1"},
            {"id": "context_window", "value": "128000"},
        ],
    }
    assert payload["inline_completion_model"] == {
        "provider": "openai-compatible",
        "model": "openai-compatible-inline-completion-model",
        "properties": [
            {"id": "model_id", "value": "gpt-4.1-mini"},
            {"id": "api_key", "value": "inline-secret"},
            {"id": "base_url", "value": "https://api.openai.test/v1"},
            {"id": "context_window", "value": "8192"},
        ],
    }


@dataclass(frozen=True)
class FakeTool:
    name: str
    description: str = ""


class FakeMCPServer:
    def __init__(self, tools: list[FakeTool]):
        self._tools = tools

    def get_tools(self):
        return list(self._tools)


class FakeHost:
    def __init__(self, server: FakeMCPServer | None, *, chat_model=None):
        self._server = server
        self.chat_model = chat_model
        self.participants = []
        self.chat_participants = {}
        self._default_chat_participant = None
        self.update_models_from_config_calls = 0

    def register_chat_participant(self, participant):
        self.participants.append(participant)
        self.chat_participants[participant.id] = participant

    def update_models_from_config(self):
        self.update_models_from_config_calls += 1

    def get_mcp_server(self, server_name: str):
        if server_name != "brain-researcher":
            return None
        return self._server


class FakeResponse:
    def __init__(self):
        self.streamed: list[MarkdownData] = []
        self.finished = False
        self.participant_id = "brain-researcher"

    @property
    def message_id(self) -> str:
        return "msg-1"

    def stream(self, data, finish: bool = False):
        self.streamed.append(data)
        if finish:
            self.finished = True

    def finish(self):
        self.finished = True


@pytest.mark.asyncio
async def test_participant_help_and_tools_commands():
    host = FakeHost(
        FakeMCPServer(
            [
                FakeTool("kg_search_nodes", "Search KG nodes."),
                FakeTool("tool_search", "Search available tools."),
            ]
        )
    )
    participant = BrainResearcherParticipant(host=host)

    help_response = FakeResponse()
    await participant.handle_chat_request(
        type("Request", (), {"command": "help", "prompt": "", "chat_history": []})(),
        help_response,
    )
    assert help_response.finished is True
    assert "Use me for neuroimaging-aware help" in help_response.streamed[0].content

    tools_response = FakeResponse()
    await participant.handle_chat_request(
        type("Request", (), {"command": "tools", "prompt": "", "chat_history": []})(),
        tools_response,
    )
    assert tools_response.finished is True
    assert "`kg_search_nodes`" in tools_response.streamed[0].content
    assert "`tool_search`" in tools_response.streamed[0].content
    assert "Search available tools." in tools_response.streamed[0].content


@pytest.mark.asyncio
async def test_participant_reports_missing_chat_model():
    host = FakeHost(FakeMCPServer([FakeTool("kg_search_nodes", "Search KG nodes.")]))
    participant = BrainResearcherParticipant(host=host)
    response = FakeResponse()

    await participant.handle_chat_request(
        type(
            "Request",
            (),
            {"command": "", "prompt": "Find me an SST dataset", "chat_history": []},
        )(),
        response,
    )

    assert response.finished is True
    assert (
        "does not currently have a chat model configured"
        in response.streamed[0].content
    )


@pytest.mark.asyncio
async def test_participant_delegates_prompt_to_tool_loop(monkeypatch):
    participant = BrainResearcherParticipant(
        host=FakeHost(FakeMCPServer([]), chat_model=object())
    )
    response = FakeResponse()
    captured = {}

    async def fake_loop(
        request, response, options=None, tool_context=None, tool_choice="auto"
    ):
        captured["request"] = request
        captured["response"] = response
        captured["options"] = options or {}
        captured["tool_context"] = tool_context or {}
        captured["tool_choice"] = tool_choice

    monkeypatch.setattr(participant, "handle_chat_request_with_tools", fake_loop)

    await participant.handle_chat_request(
        type(
            "Request",
            (),
            {"command": "", "prompt": "Find a motor task dataset", "chat_history": []},
        )(),
        response,
    )

    assert "Brain Researcher" in captured["options"]["system_prompt"]
    assert captured["tool_context"]["mcp_server_name"] == "brain-researcher"


def test_extension_registers_br_participant():
    host = FakeHost(FakeMCPServer([]))
    extension = BrainResearcherNotebookIntelligenceExtension()

    extension.activate(host)

    assert len(host.participants) == 1
    assert isinstance(host.participants[0], BrainResearcherParticipant)
    assert host.chat_participants["default"] is host.participants[0]
    assert host.chat_participants["brain-researcher"] is host.participants[0]
    assert host._default_chat_participant is host.participants[0]

    host.update_models_from_config()
    assert host.update_models_from_config_calls == 1
    assert host.chat_participants["default"] is host.participants[0]


def test_build_user_config_defaults_models_to_none():
    settings = BrainResearcherNotebookIntelligenceSettings(
        product_name="Brain Researcher",
        workspace_mode="hosted",
        provider_name="Brain Researcher",
        provider_url="https://${PUBLIC_HOSTNAME}",
        extension_id="brain-researcher",
        extension_name="Brain Researcher",
        extension_slug="brain-researcher",
        extension_class=(
            "brain_researcher.integrations.notebook_intelligence.extension."
            "BrainResearcherNotebookIntelligenceExtension"
        ),
        participant_id="brain-researcher",
        participant_name="Brain Researcher",
        participant_description="Neuroimaging research assistant powered by BR MCP.",
        mcp_server_name="brain-researcher",
        mcp_http_url="https://hub.${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token=None,
        default_chat_mode="ask",
        chat_model_provider=None,
        chat_model_id=None,
        chat_model_api_key=None,
        chat_model_base_url=None,
        chat_model_context_window=None,
        inline_completion_provider=None,
        inline_completion_model_id=None,
        inline_completion_api_key=None,
        inline_completion_base_url=None,
        inline_completion_context_window=None,
        auto_approve_tools=(),
    )

    payload = build_user_config(settings)

    assert payload["chat_model"] == {"provider": "none", "model": "none"}
    assert payload["inline_completion_model"] == {
        "provider": "none",
        "model": "none",
    }
