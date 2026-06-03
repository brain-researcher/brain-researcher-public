from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 compatibility.
    import tomli as tomllib

from brain_researcher.integrations.marimo import (
    BrainResearcherMarimoSettings,
    build_marimo_user_config,
    resolve_marimo_config_path,
    write_marimo_user_config,
)
from brain_researcher.integrations.marimo.config import _default_ai_rules


def test_default_ai_rules_forbid_speculative_br_call_tool_names() -> None:
    rules = _default_ai_rules()

    assert "Never invent or speculate about a Brain Researcher tool name." in rules
    assert "stop without emitting speculative `br.call(...)` code." in rules


def test_default_ai_rules_route_conceptual_questions_without_tools() -> None:
    rules = _default_ai_rules()

    assert "plain conceptual or natural-language neuroscience question" in rules
    assert "answer directly without tools by default" in rules
    assert "edit notebook code, ground a claim in BR data" in rules
    assert "use Brain Researcher first" in rules


def test_marimo_settings_from_env_builds_managed_ai_and_mcp_config(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/br-home")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "https://${PUBLIC_HOSTNAME}/mcp")
    monkeypatch.setenv("BR_MCP_BEARER_TOKEN", "runtime-mcp-token")
    monkeypatch.setenv("BR_MARIMO_AI_BASE_URL", "https://llm.${PUBLIC_HOSTNAME}/v1")
    monkeypatch.setenv("BR_MARIMO_AI_API_KEY", "runtime-ai-token")
    monkeypatch.setenv("BR_MARIMO_AI_PROVIDER_NAME", "brain-researcher")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("DEFAULT_CODING_MODEL", "gemini-3-flash-preview")

    settings = BrainResearcherMarimoSettings.from_env()
    payload = build_marimo_user_config(settings)

    assert settings.chat_model == "brain-researcher/gemini-3-flash-preview"
    assert settings.ai_rules == _default_ai_rules()
    # Hosted quickstart auto-runs cells on open (marimo ships this False).
    assert payload["runtime"]["auto_instantiate"] is True
    assert payload["ai"]["mode"] == "agent"
    assert payload["ai"]["rules"] == _default_ai_rules()
    assert payload["ai"]["models"]["chat_model"] == (
        "brain-researcher/gemini-3-flash-preview"
    )
    assert payload["ai"]["models"]["autocomplete_model"] == (
        "brain-researcher/gemini-3-flash-preview"
    )
    assert payload["ai"]["custom_providers"]["brain-researcher"] == {
        "api_key": "runtime-ai-token",
        "base_url": "https://llm.${PUBLIC_HOSTNAME}/v1",
    }
    assert payload["mcp"]["mcpServers"]["brain-researcher"] == {
        "url": "https://${PUBLIC_HOSTNAME}/mcp",
        "headers": {"Authorization": "Bearer runtime-mcp-token"},
        "timeout": 30.0,
    }


def test_marimo_settings_from_env_supports_builtin_google_provider(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/br-home")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "https://${PUBLIC_HOSTNAME}/mcp")
    monkeypatch.setenv("BR_MCP_BEARER_TOKEN", "runtime-mcp-token")
    monkeypatch.setenv("BR_MARIMO_AI_PROVIDER_NAME", "google")
    monkeypatch.delenv("BR_MARIMO_AI_BASE_URL", raising=False)
    monkeypatch.setenv("BR_MARIMO_AI_API_KEY", "runtime-ai-token")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("DEFAULT_CODING_MODEL", "gemini-3-flash-preview")

    settings = BrainResearcherMarimoSettings.from_env()
    payload = build_marimo_user_config(settings)

    assert settings.ai_provider_name == "google"
    assert settings.ai_provider_config_key == "google"
    assert settings.ai_model_provider == "google"
    assert settings.chat_model == "google/gemini-3-flash-preview"
    assert payload["ai"]["models"]["chat_model"] == "google/gemini-3-flash-preview"
    assert payload["ai"]["google"] == {"api_key": "runtime-ai-token"}
    assert "custom_providers" not in payload["ai"]


def test_write_marimo_user_config_merges_existing_config(tmp_path) -> None:
    settings = BrainResearcherMarimoSettings(
        user_home=str(tmp_path / "home"),
        mcp_server_name="brain-researcher",
        mcp_http_url="https://${PUBLIC_HOSTNAME}/mcp",
        mcp_bearer_token="runtime-mcp-token",
        mcp_timeout_seconds=15.0,
        ai_provider_name="brain-researcher",
        ai_provider_config_key=None,
        ai_model_provider="brain-researcher",
        ai_base_url="https://llm.${PUBLIC_HOSTNAME}/v1",
        ai_api_key="runtime-ai-token",
        ai_mode="agent",
        ai_rules=None,
        ai_max_tokens=8192,
        ai_inline_tooltip=True,
        chat_model="brain-researcher/gemini-3-flash-preview",
        edit_model="brain-researcher/gemini-3-flash-preview",
        autocomplete_model="brain-researcher/gemini-3-flash-preview",
    )
    config_path = resolve_marimo_config_path(user_home=tmp_path / "home")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[display]
theme = "dark"

[ai]
mode = "ask"

[ai.custom_providers.existing]
api_key = "keep-me"
base_url = "https://existing.example/v1"

[mcp.mcpServers.other]
url = "https://other.example/mcp"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    written_path = write_marimo_user_config(settings, user_home=tmp_path / "home")

    with written_path.open("rb") as handle:
        payload = tomllib.load(handle)

    assert payload["display"]["theme"] == "dark"
    assert payload["ai"]["mode"] == "agent"
    assert payload["ai"]["custom_providers"]["existing"] == {
        "api_key": "keep-me",
        "base_url": "https://existing.example/v1",
    }
    assert payload["ai"]["custom_providers"]["brain-researcher"] == {
        "api_key": "runtime-ai-token",
        "base_url": "https://llm.${PUBLIC_HOSTNAME}/v1",
    }
    assert payload["ai"]["rules"] == _default_ai_rules()
    assert payload["ai"]["models"]["displayed_models"] == [
        "brain-researcher/gemini-3-flash-preview",
    ]
    assert payload["mcp"]["mcpServers"]["other"] == {"url": "https://other.example/mcp"}
    assert payload["mcp"]["mcpServers"]["brain-researcher"] == {
        "url": "https://${PUBLIC_HOSTNAME}/mcp",
        "headers": {"Authorization": "Bearer runtime-mcp-token"},
        "timeout": 15.0,
    }
