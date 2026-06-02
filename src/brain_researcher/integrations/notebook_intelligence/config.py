"""Runtime configuration helpers for Notebook Intelligence integration."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from brain_researcher.core.utils.env_loader import ensure_env_loaded

DEFAULT_EXTENSION_CLASS = (
    "brain_researcher.integrations.notebook_intelligence.extension."
    "BrainResearcherNotebookIntelligenceExtension"
)
DEFAULT_EXTENSION_SLUG = "brain-researcher"
DEFAULT_PRODUCT_URL = "https://brain-researcher.com"
DEFAULT_PARTICIPANT_ID = "brain-researcher"
DEFAULT_MCP_SERVER_NAME = "brain-researcher"
DEFAULT_CHAT_MODE = "ask"
DISABLED_MODEL_CONFIG = {"provider": "none", "model": "none"}
COMPATIBLE_PROVIDER_MODEL_IDS = {
    "openai-compatible": {
        "chat": "openai-compatible-chat-model",
        "inline_completion": "openai-compatible-inline-completion-model",
    },
    "litellm-compatible": {
        "chat": "litellm-compatible-chat-model",
        "inline_completion": "litellm-compatible-inline-completion-model",
    },
}
_DIRECT_PROVIDER_ALIASES = {
    "openai": "openai",
    "open_ai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "bedrock": "bedrock",
    "azure": "azure",
    "ollama": "ollama",
    "github": "github",
    "openrouter": "openrouter",
    "wandb": "wandb",
}


def _normalize_optional_text(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _normalize_optional_int(raw: str | None) -> int | None:
    value = _normalize_optional_text(raw)
    if value is None:
        return None
    return int(value)


def _strip_provider_prefix(model_id: str | None) -> str | None:
    normalized = _normalize_optional_text(model_id)
    if normalized is None:
        return None
    if "/" not in normalized:
        return normalized
    return normalized.split("/", 1)[1].strip() or None


def _nbi_provider_from_marimo_env(
    provider_name: str | None,
    *,
    base_url: str | None,
    api_key: str | None,
) -> str | None:
    normalized_provider = _normalize_optional_text(provider_name)
    if normalized_provider is not None:
        alias = _DIRECT_PROVIDER_ALIASES.get(
            normalized_provider.lower().replace("-", "_")
        )
        if alias is not None and api_key:
            return alias
    if base_url and api_key:
        return "openai-compatible"
    return None


@dataclass(frozen=True)
class NotebookIntelligencePaths:
    prefix: Path
    user_home: Path
    env_dir: Path
    env_extensions_dir: Path
    env_extension_metadata_file: Path
    user_dir: Path
    user_config_file: Path
    user_mcp_file: Path


@dataclass(frozen=True)
class BrainResearcherNotebookIntelligenceSettings:
    product_name: str
    workspace_mode: str
    provider_name: str
    provider_url: str
    extension_id: str
    extension_name: str
    extension_slug: str
    extension_class: str
    participant_id: str
    participant_name: str
    participant_description: str
    mcp_server_name: str
    mcp_http_url: str | None
    mcp_bearer_token: str | None
    default_chat_mode: str
    chat_model_provider: str | None
    chat_model_id: str | None
    chat_model_api_key: str | None
    chat_model_base_url: str | None
    chat_model_context_window: int | None
    inline_completion_provider: str | None
    inline_completion_model_id: str | None
    inline_completion_api_key: str | None
    inline_completion_base_url: str | None
    inline_completion_context_window: int | None
    auto_approve_tools: tuple[str, ...]

    @classmethod
    def from_env(cls) -> BrainResearcherNotebookIntelligenceSettings:
        ensure_env_loaded()
        product_name = os.getenv("BR_PRODUCT_NAME", "Brain Researcher").strip()
        participant_name = (
            os.getenv("BR_NOTEBOOK_INTELLIGENCE_PARTICIPANT_NAME", "").strip()
            or product_name
        )
        marimo_ai_base_url = _normalize_optional_text(
            os.getenv("BR_MARIMO_AI_BASE_URL")
        )
        marimo_ai_api_key = _normalize_optional_text(os.getenv("BR_MARIMO_AI_API_KEY"))
        marimo_ai_provider_name = _normalize_optional_text(
            os.getenv("BR_MARIMO_AI_PROVIDER_NAME")
        )
        marimo_chat_model = _strip_provider_prefix(os.getenv("BR_MARIMO_AI_CHAT_MODEL"))
        marimo_autocomplete_model = _strip_provider_prefix(
            os.getenv("BR_MARIMO_AI_AUTOCOMPLETE_MODEL")
        )
        marimo_provider = _nbi_provider_from_marimo_env(
            marimo_ai_provider_name,
            base_url=marimo_ai_base_url,
            api_key=marimo_ai_api_key,
        )
        return cls(
            product_name=product_name or "Brain Researcher",
            workspace_mode=os.getenv("BR_WORKSPACE_MODE", "hosted").strip() or "hosted",
            provider_name=os.getenv(
                "BR_NOTEBOOK_INTELLIGENCE_PROVIDER_NAME",
                "Brain Researcher",
            ).strip()
            or "Brain Researcher",
            provider_url=(
                _normalize_optional_text(os.getenv("BR_PRODUCT_URL"))
                or _normalize_optional_text(os.getenv("BR_PUBLIC_BASE_URL"))
                or DEFAULT_PRODUCT_URL
            ),
            extension_id=(
                os.getenv("BR_NOTEBOOK_INTELLIGENCE_EXTENSION_ID")
                or DEFAULT_EXTENSION_SLUG
            ).strip()
            or DEFAULT_EXTENSION_SLUG,
            extension_name=(
                os.getenv("BR_NOTEBOOK_INTELLIGENCE_EXTENSION_NAME") or product_name
            ).strip()
            or "Brain Researcher",
            extension_slug=(
                os.getenv("BR_NOTEBOOK_INTELLIGENCE_EXTENSION_SLUG")
                or DEFAULT_EXTENSION_SLUG
            ).strip()
            or DEFAULT_EXTENSION_SLUG,
            extension_class=(
                os.getenv("BR_NOTEBOOK_INTELLIGENCE_EXTENSION_CLASS")
                or DEFAULT_EXTENSION_CLASS
            ).strip()
            or DEFAULT_EXTENSION_CLASS,
            participant_id=(
                os.getenv("BR_NOTEBOOK_INTELLIGENCE_PARTICIPANT_ID")
                or DEFAULT_PARTICIPANT_ID
            ).strip()
            or DEFAULT_PARTICIPANT_ID,
            participant_name=participant_name,
            participant_description=(
                os.getenv(
                    "BR_NOTEBOOK_INTELLIGENCE_PARTICIPANT_DESCRIPTION", ""
                ).strip()
                or "Neuroimaging research assistant powered by BR MCP."
            ),
            mcp_server_name=(
                os.getenv("BR_NOTEBOOK_INTELLIGENCE_MCP_SERVER_NAME")
                or os.getenv("BR_NBI_MCP_SERVER_NAME")
                or DEFAULT_MCP_SERVER_NAME
            ).strip()
            or DEFAULT_MCP_SERVER_NAME,
            mcp_http_url=_normalize_optional_text(os.getenv("BR_MCP_HTTP_URL")),
            mcp_bearer_token=_normalize_optional_text(os.getenv("BR_MCP_BEARER_TOKEN")),
            default_chat_mode=(
                os.getenv("BR_NBI_DEFAULT_CHAT_MODE", DEFAULT_CHAT_MODE).strip()
                or DEFAULT_CHAT_MODE
            ),
            chat_model_provider=_normalize_optional_text(
                os.getenv("BR_NBI_CHAT_MODEL_PROVIDER")
            )
            or marimo_provider,
            chat_model_id=_normalize_optional_text(os.getenv("BR_NBI_CHAT_MODEL_ID"))
            or marimo_chat_model,
            chat_model_api_key=_normalize_optional_text(
                os.getenv("BR_NBI_CHAT_MODEL_API_KEY")
            )
            or marimo_ai_api_key,
            chat_model_base_url=_normalize_optional_text(
                os.getenv("BR_NBI_CHAT_MODEL_BASE_URL")
            )
            or marimo_ai_base_url,
            chat_model_context_window=_normalize_optional_int(
                os.getenv("BR_NBI_CHAT_MODEL_CONTEXT_WINDOW")
            ),
            inline_completion_provider=_normalize_optional_text(
                os.getenv("BR_NBI_INLINE_COMPLETION_PROVIDER")
            )
            or marimo_provider,
            inline_completion_model_id=_normalize_optional_text(
                os.getenv("BR_NBI_INLINE_COMPLETION_MODEL_ID")
            )
            or marimo_autocomplete_model,
            inline_completion_api_key=_normalize_optional_text(
                os.getenv("BR_NBI_INLINE_COMPLETION_API_KEY")
            )
            or marimo_ai_api_key,
            inline_completion_base_url=_normalize_optional_text(
                os.getenv("BR_NBI_INLINE_COMPLETION_BASE_URL")
            )
            or marimo_ai_base_url,
            inline_completion_context_window=_normalize_optional_int(
                os.getenv("BR_NBI_INLINE_COMPLETION_CONTEXT_WINDOW")
            ),
            auto_approve_tools=_csv_env("BR_NOTEBOOK_INTELLIGENCE_AUTO_APPROVE_TOOLS"),
        )


def resolve_notebook_intelligence_paths(
    settings: BrainResearcherNotebookIntelligenceSettings,
    *,
    prefix: str | os.PathLike[str] | None = None,
    user_home: str | os.PathLike[str] | None = None,
) -> NotebookIntelligencePaths:
    prefix_path = Path(prefix or sys.prefix)
    user_home_path = Path(user_home or os.path.expanduser("~"))
    env_dir = prefix_path / "share" / "jupyter" / "nbi"
    env_extensions_dir = prefix_path / "share" / "jupyter" / "nbi_extensions"
    user_dir = user_home_path / ".jupyter" / "nbi"
    return NotebookIntelligencePaths(
        prefix=prefix_path,
        user_home=user_home_path,
        env_dir=env_dir,
        env_extensions_dir=env_extensions_dir,
        env_extension_metadata_file=env_extensions_dir
        / settings.extension_slug
        / "extension.json",
        user_dir=user_dir,
        user_config_file=user_dir / "config.json",
        user_mcp_file=user_dir / "mcp.json",
    )


def build_extension_metadata(
    settings: BrainResearcherNotebookIntelligenceSettings,
) -> dict[str, str]:
    return {"class": settings.extension_class}


def build_managed_mcp_server_config(
    settings: BrainResearcherNotebookIntelligenceSettings,
) -> dict[str, object] | None:
    if not settings.mcp_http_url:
        return None
    server_config: dict[str, object] = {"url": settings.mcp_http_url}
    if settings.mcp_bearer_token:
        server_config["headers"] = {
            "Authorization": f"Bearer {settings.mcp_bearer_token}"
        }
    if settings.auto_approve_tools:
        server_config["autoApprove"] = list(settings.auto_approve_tools)
    return server_config


def build_user_config(
    settings: BrainResearcherNotebookIntelligenceSettings,
    *,
    existing: dict[str, object] | None = None,
) -> dict[str, object]:
    merged = dict(existing or {})
    merged["default_chat_mode"] = settings.default_chat_mode
    chat_model = _build_model_selection(
        provider=settings.chat_model_provider,
        model_id=settings.chat_model_id,
        api_key=settings.chat_model_api_key,
        base_url=settings.chat_model_base_url,
        context_window=settings.chat_model_context_window,
        kind="chat",
    )
    if chat_model is not None:
        merged["chat_model"] = chat_model
    else:
        merged.setdefault("chat_model", dict(DISABLED_MODEL_CONFIG))
    inline_completion_model = _build_model_selection(
        provider=settings.inline_completion_provider,
        model_id=settings.inline_completion_model_id,
        api_key=settings.inline_completion_api_key,
        base_url=settings.inline_completion_base_url,
        context_window=settings.inline_completion_context_window,
        kind="inline_completion",
    )
    if inline_completion_model is not None:
        merged["inline_completion_model"] = inline_completion_model
    else:
        merged.setdefault("inline_completion_model", dict(DISABLED_MODEL_CONFIG))
    return merged


def _build_model_selection(
    *,
    provider: str | None,
    model_id: str | None,
    api_key: str | None,
    base_url: str | None,
    context_window: int | None,
    kind: str,
) -> dict[str, object] | None:
    if not provider or not model_id:
        return None

    wrapper_model_id = COMPATIBLE_PROVIDER_MODEL_IDS.get(provider, {}).get(kind)
    if wrapper_model_id is None:
        return {"provider": provider, "model": model_id}

    properties: list[dict[str, str]] = [{"id": "model_id", "value": model_id}]
    if api_key:
        properties.append({"id": "api_key", "value": api_key})
    if base_url:
        properties.append({"id": "base_url", "value": base_url})
    if context_window is not None:
        properties.append({"id": "context_window", "value": str(context_window)})
    return {
        "provider": provider,
        "model": wrapper_model_id,
        "properties": properties,
    }


def build_user_mcp_config(
    settings: BrainResearcherNotebookIntelligenceSettings,
    *,
    existing: dict[str, object] | None = None,
) -> dict[str, object]:
    merged = dict(existing or {})
    existing_servers = merged.get("mcpServers")
    if isinstance(existing_servers, dict):
        mcp_servers = dict(existing_servers)
    else:
        mcp_servers = {}

    managed_server = build_managed_mcp_server_config(settings)
    if managed_server is not None:
        mcp_servers[settings.mcp_server_name] = managed_server

    merged["mcpServers"] = mcp_servers
    return merged


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def write_extension_metadata(
    settings: BrainResearcherNotebookIntelligenceSettings,
    *,
    prefix: str | os.PathLike[str] | None = None,
) -> Path:
    paths = resolve_notebook_intelligence_paths(settings, prefix=prefix)
    metadata_path = paths.env_extension_metadata_file
    return _write_json(metadata_path, build_extension_metadata(settings))


def write_user_config(
    settings: BrainResearcherNotebookIntelligenceSettings,
    *,
    user_home: str | os.PathLike[str] | None = None,
) -> Path:
    paths = resolve_notebook_intelligence_paths(settings, user_home=user_home)
    existing = _read_json(paths.user_config_file)
    payload = build_user_config(settings, existing=existing)
    return _write_json(paths.user_config_file, payload)


def write_user_mcp_config(
    settings: BrainResearcherNotebookIntelligenceSettings,
    *,
    user_home: str | os.PathLike[str] | None = None,
) -> Path:
    paths = resolve_notebook_intelligence_paths(settings, user_home=user_home)
    existing = _read_json(paths.user_mcp_file)
    payload = build_user_mcp_config(settings, existing=existing)
    return _write_json(paths.user_mcp_file, payload)
