"""Managed configuration helpers for hosted marimo runtimes."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 compatibility.
    import tomli as tomllib

from brain_researcher.core.utils.env_loader import ensure_env_loaded

logger = logging.getLogger(__name__)

DEFAULT_MCP_SERVER_NAME = "brain-researcher"
DEFAULT_AI_PROVIDER_NAME = "brain-researcher"
DEFAULT_AI_MODE = "agent"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_MAX_TOKENS = 4096
_DEFAULT_AI_RULES = """You are the Brain Researcher marimo assistant.
If the user asks a plain conceptual or natural-language neuroscience question, answer directly without tools by default.
If the user asks to edit notebook code, ground a claim in BR data, verify a result, or look up a live dataset/workflow/tool, use Brain Researcher first.
Treat Brain Researcher as the system of record for neuroimaging, datasets, workflows, connectomics, and knowledge-graph lookups.
Before writing a new neuroimaging, dataset, workflow, atlas, or connectomics cell, start with the smallest useful Brain Researcher tool step.
Prefer notebook code that uses `import brain_researcher.sdk as br` and `br.search()`, `br.recipe()`, `br.execute()`, or `br.call()` before raw `nilearn`, `neuprint`, or external HTTP APIs when Brain Researcher can express the task.
Do not emit placeholder, commented-out, or synthetic code when a Brain Researcher tool can answer the task; call the tool and surface the real result.
Never invent or speculate about a Brain Researcher tool name. Use `br.call("...")` only with a tool name verified from current BR search results or tool output in this session.
If no exact BR tool name has been verified, say that no exact tool was found and either ask one concise clarifying question or stop without emitting speculative `br.call(...)` code.
If BR hub `@tool://`, `@dataset://`, `@workflow://`, or `@kg://` context is present, treat it as grounding and use it in the next step.
Keep claims calibrated, distinguish evidence from inference, and ask one concise clarifying question when critical context is missing."""
_BUILTIN_PROVIDER_SPECS: dict[str, tuple[str, str]] = {
    "openai": ("open_ai", "openai"),
    "open_ai": ("open_ai", "openai"),
    "anthropic": ("anthropic", "anthropic"),
    "google": ("google", "google"),
    "bedrock": ("bedrock", "bedrock"),
    "azure": ("azure", "azure"),
    "ollama": ("ollama", "ollama"),
    "github": ("github", "github"),
    "openrouter": ("openrouter", "openrouter"),
    "wandb": ("wandb", "wandb"),
    "openai_compatible": ("open_ai_compatible", "openai_compatible"),
}


@dataclass(frozen=True)
class _ResolvedProvider:
    env_name: str
    model_provider: str
    config_key: str | None


def _normalize_optional_text(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value or None


def _normalize_optional_int(raw: str | None) -> int | None:
    value = _normalize_optional_text(raw)
    if value is None:
        return None
    return int(value)


def _normalize_optional_float(raw: str | None) -> float | None:
    value = _normalize_optional_text(raw)
    if value is None:
        return None
    return float(value)


def _normalize_optional_bool(raw: str | None) -> bool | None:
    value = _normalize_optional_text(raw)
    if value is None:
        return None
    return value.lower() not in {"0", "false", "no", "off"}


def _normalize_provider_lookup(raw: str | None) -> str | None:
    value = _normalize_optional_text(raw)
    if value is None:
        return None
    return value.lower().replace("-", "_")


def _resolve_provider(raw: str | None) -> _ResolvedProvider | None:
    env_name = _normalize_optional_text(raw)
    if env_name is None:
        return None
    builtin = _BUILTIN_PROVIDER_SPECS.get(_normalize_provider_lookup(env_name) or "")
    if builtin is None:
        return _ResolvedProvider(
            env_name=env_name,
            model_provider=env_name,
            config_key=None,
        )
    config_key, model_provider = builtin
    return _ResolvedProvider(
        env_name=env_name,
        model_provider=model_provider,
        config_key=config_key,
    )


def _provider_is_configured(
    provider: _ResolvedProvider | None,
    *,
    api_key: str | None,
    base_url: str | None,
) -> bool:
    if provider is None:
        return False
    if provider.config_key is None or provider.config_key == "open_ai_compatible":
        return bool(api_key and base_url)
    if provider.model_provider == "ollama":
        return bool(api_key or base_url)
    return bool(api_key)


def _qualify_model(model: str | None, provider_name: str | None) -> str | None:
    normalized = _normalize_optional_text(model)
    if normalized is None:
        return None
    if "/" in normalized or not provider_name:
        return normalized
    return f"{provider_name}/{normalized}"


def _default_chat_model() -> str:
    return (
        _normalize_optional_text(os.getenv("DEFAULT_LLM_MODEL")) or DEFAULT_GEMINI_MODEL
    )


def _default_autocomplete_model() -> str:
    return (
        _normalize_optional_text(os.getenv("DEFAULT_CODING_MODEL"))
        or _normalize_optional_text(os.getenv("DEFAULT_LLM_MODEL"))
        or DEFAULT_GEMINI_MODEL
    )


def _default_ai_rules() -> str:
    return _DEFAULT_AI_RULES


@dataclass(frozen=True)
class BrainResearcherMarimoSettings:
    user_home: str
    mcp_server_name: str
    mcp_http_url: str | None
    mcp_bearer_token: str | None
    mcp_timeout_seconds: float | None
    ai_provider_name: str | None
    ai_provider_config_key: str | None
    ai_model_provider: str | None
    ai_base_url: str | None
    ai_api_key: str | None
    ai_mode: str | None
    ai_rules: str | None
    ai_max_tokens: int | None
    ai_inline_tooltip: bool | None
    chat_model: str | None
    edit_model: str | None
    autocomplete_model: str | None

    @classmethod
    def from_env(cls) -> BrainResearcherMarimoSettings:
        ensure_env_loaded()
        user_home = os.path.expanduser("~")
        provider_name = (
            _normalize_optional_text(os.getenv("BR_MARIMO_AI_PROVIDER_NAME"))
            or DEFAULT_AI_PROVIDER_NAME
        )
        resolved_provider = _resolve_provider(provider_name)
        raw_chat_model = _normalize_optional_text(os.getenv("BR_MARIMO_AI_CHAT_MODEL"))
        raw_edit_model = _normalize_optional_text(os.getenv("BR_MARIMO_AI_EDIT_MODEL"))
        raw_autocomplete_model = _normalize_optional_text(
            os.getenv("BR_MARIMO_AI_AUTOCOMPLETE_MODEL")
        )
        base_url = _normalize_optional_text(os.getenv("BR_MARIMO_AI_BASE_URL"))
        api_key = _normalize_optional_text(os.getenv("BR_MARIMO_AI_API_KEY"))
        has_managed_ai = _provider_is_configured(
            resolved_provider,
            api_key=api_key,
            base_url=base_url,
        )
        model_provider = (
            resolved_provider.model_provider
            if resolved_provider is not None and has_managed_ai
            else None
        )
        default_chat_model = _default_chat_model() if has_managed_ai else None
        default_autocomplete_model = (
            _default_autocomplete_model() if has_managed_ai else None
        )
        chat_model = _qualify_model(
            raw_chat_model or default_chat_model, model_provider
        )
        edit_model = _qualify_model(
            raw_edit_model or raw_chat_model or default_chat_model, model_provider
        )
        autocomplete_model = _qualify_model(
            raw_autocomplete_model
            or raw_edit_model
            or (
                default_autocomplete_model
                if has_managed_ai
                else raw_chat_model or default_chat_model
            ),
            model_provider,
        )
        mode = _normalize_optional_text(os.getenv("BR_MARIMO_AI_MODE"))
        if mode is None and chat_model is not None:
            mode = DEFAULT_AI_MODE
        return cls(
            user_home=user_home,
            mcp_server_name=(
                _normalize_optional_text(os.getenv("BR_MARIMO_MCP_SERVER_NAME"))
                or _normalize_optional_text(os.getenv("BR_NBI_MCP_SERVER_NAME"))
                or DEFAULT_MCP_SERVER_NAME
            ),
            mcp_http_url=_normalize_optional_text(os.getenv("BR_MCP_HTTP_URL")),
            mcp_bearer_token=_normalize_optional_text(os.getenv("BR_MCP_BEARER_TOKEN")),
            mcp_timeout_seconds=_normalize_optional_float(
                os.getenv("BR_MARIMO_MCP_TIMEOUT_SECONDS")
            )
            or 30.0,
            ai_provider_name=(
                resolved_provider.env_name
                if resolved_provider is not None and has_managed_ai
                else None
            ),
            ai_provider_config_key=(
                resolved_provider.config_key
                if resolved_provider is not None and has_managed_ai
                else None
            ),
            ai_model_provider=model_provider,
            ai_base_url=base_url,
            ai_api_key=api_key,
            ai_mode=mode,
            ai_rules=(
                _normalize_optional_text(os.getenv("BR_MARIMO_AI_RULES"))
                or (_default_ai_rules() if has_managed_ai else None)
            ),
            ai_max_tokens=_normalize_optional_int(os.getenv("BR_MARIMO_AI_MAX_TOKENS"))
            or (DEFAULT_MAX_TOKENS if chat_model is not None else None),
            ai_inline_tooltip=_normalize_optional_bool(
                os.getenv("BR_MARIMO_AI_INLINE_TOOLTIP")
            ),
            chat_model=chat_model,
            edit_model=edit_model,
            autocomplete_model=autocomplete_model,
        )


def resolve_marimo_config_path(
    *,
    user_home: str | os.PathLike[str] | None = None,
) -> Path:
    home = Path(user_home or os.path.expanduser("~"))
    return home / ".marimo.toml"


def build_managed_mcp_server_config(
    settings: BrainResearcherMarimoSettings,
) -> dict[str, object] | None:
    if not settings.mcp_http_url:
        return None
    server_config: dict[str, object] = {"url": settings.mcp_http_url}
    if settings.mcp_bearer_token:
        server_config["headers"] = {
            "Authorization": f"Bearer {settings.mcp_bearer_token}"
        }
    if settings.mcp_timeout_seconds is not None:
        server_config["timeout"] = settings.mcp_timeout_seconds
    return server_config


def build_marimo_user_config(
    settings: BrainResearcherMarimoSettings,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(existing or {})

    mcp_config = dict(merged.get("mcp") or {})
    mcp_servers = dict(mcp_config.get("mcpServers") or {})
    managed_mcp_server = build_managed_mcp_server_config(settings)
    if managed_mcp_server is not None:
        mcp_servers[settings.mcp_server_name] = managed_mcp_server
    if mcp_servers:
        mcp_config["mcpServers"] = mcp_servers
        mcp_config.setdefault("presets", [])
        merged["mcp"] = mcp_config

    if not (settings.ai_provider_name and settings.ai_api_key and settings.chat_model):
        return merged

    ai_config = dict(merged.get("ai") or {})
    models = dict(ai_config.get("models") or {})
    configured_models = [
        model
        for model in (
            settings.chat_model,
            settings.edit_model or settings.chat_model,
            settings.autocomplete_model,
        )
        if model
    ]
    displayed_models = list(models.get("displayed_models") or [])
    custom_models = list(models.get("custom_models") or [])
    for model in configured_models:
        if model not in displayed_models:
            displayed_models.append(model)
        if model not in custom_models:
            custom_models.append(model)
    models["displayed_models"] = displayed_models
    models["custom_models"] = custom_models
    models["chat_model"] = settings.chat_model
    models["edit_model"] = settings.edit_model or settings.chat_model
    if settings.autocomplete_model:
        models["autocomplete_model"] = settings.autocomplete_model
    ai_config["models"] = models
    if settings.ai_provider_config_key is None:
        existing_custom_providers = dict(ai_config.get("custom_providers") or {})
        existing_provider_config = dict(
            existing_custom_providers.get(settings.ai_provider_name) or {}
        )
        provider_payload = {
            **existing_provider_config,
            "api_key": settings.ai_api_key,
        }
        if settings.ai_base_url:
            provider_payload["base_url"] = settings.ai_base_url
        ai_config["custom_providers"] = {
            **existing_custom_providers,
            settings.ai_provider_name: provider_payload,
        }
    else:
        existing_provider_config = dict(
            ai_config.get(settings.ai_provider_config_key) or {}
        )
        provider_payload = {
            **existing_provider_config,
            "api_key": settings.ai_api_key,
        }
        if settings.ai_base_url:
            provider_payload["base_url"] = settings.ai_base_url
        ai_config[settings.ai_provider_config_key] = provider_payload
    if settings.ai_mode:
        ai_config["mode"] = settings.ai_mode
    ai_rules = settings.ai_rules or _default_ai_rules()
    if ai_rules:
        ai_config["rules"] = ai_rules
    if settings.ai_max_tokens is not None:
        ai_config["max_tokens"] = settings.ai_max_tokens
    if settings.ai_inline_tooltip is not None:
        ai_config["inline_tooltip"] = settings.ai_inline_tooltip
    merged["ai"] = ai_config
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        logger.warning("Invalid marimo config at %s: %s", path, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_toml(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = tomlkit.document()
    for key, value in payload.items():
        document[key] = tomlkit.item(value)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(tomlkit.dumps(document))
    return path


def write_marimo_user_config(
    settings: BrainResearcherMarimoSettings,
    *,
    user_home: str | os.PathLike[str] | None = None,
) -> Path:
    config_path = resolve_marimo_config_path(user_home=user_home or settings.user_home)
    existing = _read_toml(config_path)
    payload = build_marimo_user_config(settings, existing=existing)
    return _write_toml(config_path, payload)
