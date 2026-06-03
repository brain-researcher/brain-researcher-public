"""Runtime preflight checks exposed for Web UI plan validation."""

from __future__ import annotations

import os
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.tools.runtime_profiles import get_tool_recipe_override
from ..env import AGENT_URL

router = APIRouter(prefix="/api/preflight", tags=["preflight"])

_WORKFLOW_CATALOG_PATH = (
    resolve_from_config("workflows", "workflow_catalog.yaml")
)
_STUDIO_TOOL_MAPPINGS_PATH = (
    resolve_from_config("catalog", "studio_tool_mappings.yaml")
)
_CHAT_TOOLS_PATH = (
    resolve_from_config("catalog", "chat_tools.yaml")
)
_NEURODESK_PLAY_URL = "https://play.neurodesk.org/"
_NEURODESK_APP_URL = "https://neurodesk.org/getting-started/local/neurodeskapp/"
_NEURODESK_HPC_URL = "https://neurodesk.org/getting-started/installations/ubuntu2404/"


def _timeout_seconds() -> float:
    raw = os.getenv("BR_PREFLIGHT_AGENT_TIMEOUT_S", "6")
    try:
        value = float(raw)
    except ValueError:
        value = 6.0
    return max(value, 1.0)


def _normalize_tool_ids(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        tool_id = str(value or "").strip()
        if not tool_id or tool_id in seen:
            continue
        seen.add(tool_id)
        out.append(tool_id)
    return out


def _parse_env_tool_allowlist(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return _normalize_tool_ids(value.split(","))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_text_mapping(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in values.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            out[key_text] = value_text
    return out


@lru_cache(maxsize=1)
def _load_studio_tool_alias_map() -> dict[str, str]:
    if not _STUDIO_TOOL_MAPPINGS_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(_STUDIO_TOOL_MAPPINGS_PATH.read_text()) or {}
    except Exception:
        return {}

    raw_map = data.get("alias_to_runtime")
    if not isinstance(raw_map, dict):
        raw_map = data.get("aliases_to_runtime")
    if not isinstance(raw_map, dict):
        return {}

    mapping: dict[str, str] = {}
    for alias, canonical in raw_map.items():
        alias_key = str(alias or "").strip()
        canonical_value = str(canonical or "").strip()
        if not alias_key or not canonical_value:
            continue
        mapping[alias_key] = canonical_value
    return mapping


@lru_cache(maxsize=1)
def _load_runtime_allowlist() -> set[str]:
    env_tool_allowlist = _parse_env_tool_allowlist(os.getenv("AGENT_TOOL_ALLOWLIST"))
    if env_tool_allowlist is not None:
        try:
            from brain_researcher.services.agent.tool_allowlist_loader import (
                resolve_runtime_tool_allowlist,
            )

            resolved = resolve_runtime_tool_allowlist(
                env_tool_allowlist,
                strict=_env_flag("AGENT_TOOL_ALLOWLIST_STRICT"),
            )
        except Exception:
            resolved = env_tool_allowlist
        return set(resolved or [])

    if not _CHAT_TOOLS_PATH.exists():
        return set()
    try:
        data = yaml.safe_load(_CHAT_TOOLS_PATH.read_text()) or {}
    except Exception:
        return set()
    raw_tools = data.get("chat_tools")
    if not isinstance(raw_tools, list):
        return set()
    canonical: set[str] = set()
    for raw in _normalize_tool_ids(str(item or "") for item in raw_tools):
        canonical.add(_canonicalize_tool_id(raw))
    return canonical


def _canonicalize_tool_id(tool_id: str) -> str:
    mapping = _load_studio_tool_alias_map()
    if not mapping:
        return tool_id

    current = tool_id
    visited: set[str] = set()
    while current in mapping and current not in visited:
        visited.add(current)
        current = mapping[current]
    return current


def _canonicalize_tool_ids(
    tool_ids: list[str],
) -> tuple[list[str], dict[str, str], dict[str, list[str]], set[str]]:
    canonical: list[str] = []
    canonical_seen: set[str] = set()
    raw_to_canonical: dict[str, str] = {}
    canonical_to_raw_aliases: dict[str, list[str]] = {}
    unknown_tool_aliases: set[str] = set()

    alias_map = _load_studio_tool_alias_map()
    canonical_ids = {value for value in alias_map.values() if value}
    canonical_ids.update(key for key, value in alias_map.items() if key == value)

    for raw in tool_ids:
        resolved = _canonicalize_tool_id(raw)
        raw_to_canonical[raw] = resolved
        if raw != resolved:
            aliases = canonical_to_raw_aliases.setdefault(resolved, [])
            aliases.append(raw)
        elif alias_map and canonical_ids and raw not in canonical_ids and raw not in alias_map:
            unknown_tool_aliases.add(raw)
        if resolved in canonical_seen:
            continue
        canonical_seen.add(resolved)
        canonical.append(resolved)

    return canonical, raw_to_canonical, canonical_to_raw_aliases, unknown_tool_aliases


@lru_cache(maxsize=1)
def _load_workflow_catalog() -> dict[str, Any]:
    if not _WORKFLOW_CATALOG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(_WORKFLOW_CATALOG_PATH.read_text()) or {}
    except Exception:
        return {}


def _workflow_entry(workflow_id: str) -> dict[str, Any] | None:
    catalog = _load_workflow_catalog()
    workflows = catalog.get("workflows")
    if not isinstance(workflows, list):
        return None

    normalized = str(workflow_id or "").strip()
    if not normalized:
        return None

    for workflow in workflows:
        if not isinstance(workflow, dict):
            continue
        if str(workflow.get("id") or "").strip() == normalized:
            return workflow
    return None


def _workflow_tool_ids(workflow_id: str) -> list[str]:
    workflow = _workflow_entry(workflow_id)
    if not isinstance(workflow, dict):
        return []
    runtime = workflow.get("runtime")
    if not isinstance(runtime, dict):
        return []
    steps = runtime.get("steps")
    if not isinstance(steps, list):
        return []
    return _normalize_tool_ids(
        str(step.get("tool") or "").strip()
        for step in steps
        if isinstance(step, dict)
    )


async def _fetch_runtime_tool_status() -> tuple[dict[str, str], list[str]]:
    warnings: list[str] = []
    url = f"{AGENT_URL}/tools"
    try:
        async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {}, [f"Runtime tool inventory unavailable: {exc}"]

    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(tools, list):
        return {}, [f"Unexpected runtime tool inventory payload from {url}"]

    statuses: dict[str, str] = {}
    for row in tools:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("id") or "").strip()
        if not name:
            continue
        status = str(row.get("status") or "available").strip().lower()
        statuses[name] = status

    if not statuses:
        warnings.append("Runtime tool inventory is empty.")
    return statuses, warnings


class PreflightCheckRequest(BaseModel):
    workflow_id: str | None = None
    tool_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_source(self) -> PreflightCheckRequest:
        if not self.workflow_id and not self.tool_ids:
            raise ValueError("workflow_id or tool_ids must be provided")
        return self


class RuntimeToolCheck(BaseModel):
    tool_id: str
    requested_tool_id: str | None = None
    exists: bool
    available: bool
    status: str
    code: str | None = None
    detail: str | None = None


class EnvironmentSetupAction(BaseModel):
    id: str
    label: str
    href: str
    external: bool = True


class EnvironmentSetupGuidance(BaseModel):
    kind: str
    access_mode: str
    runtime_target: str
    install_path: str
    summary: str
    detail: str | None = None
    next_action_url: str | None = None
    docs_urls: list[str] = Field(default_factory=list)
    actions: list[EnvironmentSetupAction] = Field(default_factory=list)
    required_modules: list[str] = Field(default_factory=list)
    required_env_vars: list[str] = Field(default_factory=list)
    container_images: dict[str, str] = Field(default_factory=dict)
    supported_recipe_targets: list[str] = Field(default_factory=list)
    workflow_id: str | None = None


class PreflightCheckResponse(BaseModel):
    executable: bool
    checks: list[RuntimeToolCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resolved_from_workflow: bool = False
    guidance: EnvironmentSetupGuidance | None = None


def _build_environment_guidance(
    *,
    workflow_id: str | None,
    checks: list[RuntimeToolCheck],
) -> EnvironmentSetupGuidance | None:
    normalized_workflow_id = str(workflow_id or "").strip()
    if not normalized_workflow_id:
        return None

    workflow = _workflow_entry(normalized_workflow_id) or {}
    override = get_tool_recipe_override(normalized_workflow_id)

    supported_recipe_targets = _normalize_text_list(
        workflow.get("supported_recipe_targets")
    )
    primary_target = str(workflow.get("primary_target") or "").strip().lower()
    required_modules = _normalize_text_list(override.get("neurodesk_modules"))
    required_env_vars = _normalize_text_list(override.get("required_env_vars"))
    container_images = _normalize_text_mapping(override.get("container_images"))

    needs_neurodesk = (
        primary_target == "neurodesk"
        or "neurodesk" in {target.lower() for target in supported_recipe_targets}
        or bool(required_modules)
    )
    if not needs_neurodesk:
        if not (supported_recipe_targets or required_env_vars or container_images):
            return None
        unavailable_steps = [
            check.requested_tool_id or check.tool_id
            for check in checks
            if not check.available and (check.requested_tool_id or check.tool_id)
        ]
        detail_parts: list[str] = []
        if unavailable_steps:
            detail_parts.append(
                "Unavailable runtime steps: " + ", ".join(unavailable_steps)
            )
        if supported_recipe_targets:
            detail_parts.append(
                "Supported recipe targets: " + ", ".join(supported_recipe_targets)
            )
        if required_env_vars:
            detail_parts.append(
                "Required environment variables: " + ", ".join(required_env_vars)
            )
        if container_images:
            detail_parts.append(
                "Container images: "
                + ", ".join(f"{name}={image}" for name, image in container_images.items())
            )

        runtime_target = (
            primary_target
            or (supported_recipe_targets[0].lower() if supported_recipe_targets else "")
            or "recipe"
        )
        return EnvironmentSetupGuidance(
            kind="recipe_handoff_required",
            access_mode="self_setup_required",
            runtime_target=runtime_target,
            install_path="external",
            summary=(
                "This workflow has an execution recipe, but the hosted Studio "
                "runtime cannot execute it directly."
            ),
            detail=". ".join(detail_parts) if detail_parts else None,
            required_env_vars=required_env_vars,
            container_images=container_images,
            supported_recipe_targets=supported_recipe_targets,
            workflow_id=normalized_workflow_id,
        )

    unavailable_steps = [
        check.requested_tool_id or check.tool_id
        for check in checks
        if not check.available and (check.requested_tool_id or check.tool_id)
    ]

    detail_parts: list[str] = []
    if unavailable_steps:
        detail_parts.append(
            "Unavailable runtime steps: " + ", ".join(unavailable_steps)
        )
    if required_modules:
        detail_parts.append(
            "Expected Neurodesk modules: " + ", ".join(required_modules)
        )
    if required_env_vars:
        detail_parts.append(
            "Required environment variables: " + ", ".join(required_env_vars)
        )

    return EnvironmentSetupGuidance(
        kind="neurodesk_setup_required",
        access_mode="self_setup_required",
        runtime_target="neurodesk",
        install_path="app",
        summary=(
            "This workflow depends on a Neurodesk-backed runtime. "
            "Set up Neurodesk first, then re-check the environment."
        ),
        detail=". ".join(detail_parts) if detail_parts else None,
        next_action_url=_NEURODESK_APP_URL,
        docs_urls=[_NEURODESK_PLAY_URL, _NEURODESK_APP_URL, _NEURODESK_HPC_URL],
        actions=[
            EnvironmentSetupAction(
                id="neurodesk-play",
                label="Try Neurodesk Play",
                href=_NEURODESK_PLAY_URL,
            ),
            EnvironmentSetupAction(
                id="neurodesk-app",
                label="Install Neurodesk App",
                href=_NEURODESK_APP_URL,
            ),
            EnvironmentSetupAction(
                id="neurodesk-hpc",
                label="Use Neurocommand / HPC",
                href=_NEURODESK_HPC_URL,
            ),
        ],
        required_modules=required_modules,
        required_env_vars=required_env_vars,
        container_images=container_images,
        supported_recipe_targets=supported_recipe_targets,
        workflow_id=normalized_workflow_id,
    )


@router.post("/check", response_model=PreflightCheckResponse)
async def preflight_check(request: PreflightCheckRequest) -> PreflightCheckResponse:
    warnings: list[str] = []
    resolved_from_workflow = False
    normalized_workflow_id = str(request.workflow_id or "").strip() or None

    raw_tool_ids = _normalize_tool_ids(request.tool_ids)
    alias_map: dict[str, str] = {}
    alias_reverse: dict[str, list[str]] = {}
    if not raw_tool_ids and request.workflow_id:
        resolved_from_workflow = True
        raw_tool_ids = _workflow_tool_ids(str(request.workflow_id).strip())
        if not raw_tool_ids:
            warnings.append(
                f"Workflow '{request.workflow_id}' has no runtime steps or was not found."
            )
            return PreflightCheckResponse(
                executable=False,
                checks=[],
                warnings=warnings,
                resolved_from_workflow=resolved_from_workflow,
                guidance=_build_environment_guidance(
                    workflow_id=normalized_workflow_id,
                    checks=[],
                ),
            )

    tool_ids, alias_map, alias_reverse, unknown_aliases = _canonicalize_tool_ids(
        raw_tool_ids
    )
    alias_notes = [
        f"{raw} -> {canonical}"
        for raw, canonical in alias_map.items()
        if raw != canonical
    ]
    if alias_notes:
        warnings.append("Canonicalized tool IDs: " + ", ".join(alias_notes))

    runtime_statuses, runtime_warnings = await _fetch_runtime_tool_status()
    runtime_allowlist = _load_runtime_allowlist()
    warnings.extend(runtime_warnings)
    if not runtime_statuses:
        return PreflightCheckResponse(
            executable=False,
            checks=[],
            warnings=warnings,
            resolved_from_workflow=resolved_from_workflow,
            guidance=_build_environment_guidance(
                workflow_id=normalized_workflow_id,
                checks=[],
            ),
        )

    checks: list[RuntimeToolCheck] = []
    for tool_id in tool_ids:
        resolved_aliases = alias_reverse.get(tool_id) or []
        requested_tool_id = resolved_aliases[0] if resolved_aliases else tool_id
        resolved_hint = (
            f"Resolved from alias(es): {', '.join(resolved_aliases)}. "
            if resolved_aliases
            else ""
        )
        if runtime_allowlist and tool_id not in runtime_allowlist:
            checks.append(
                RuntimeToolCheck(
                    tool_id=tool_id,
                    requested_tool_id=requested_tool_id,
                    exists=False,
                    available=False,
                    status="blocked",
                    code="RUNTIME_TOOL_NOT_ALLOWED",
                    detail=(
                        f"{resolved_hint}Tool is excluded by the Studio runtime allowlist."
                    ),
                )
            )
            continue

        status = runtime_statuses.get(tool_id)
        if status is None:
            missing_code = (
                "UNKNOWN_TOOL_ALIAS"
                if requested_tool_id in unknown_aliases
                else "RUNTIME_TOOL_NOT_REGISTERED"
            )
            detail = (
                f"{resolved_hint}Tool alias is not defined in studio_tool_mappings.yaml."
                if missing_code == "UNKNOWN_TOOL_ALIAS"
                else f"{resolved_hint}Tool is not registered in the running agent."
            )
            checks.append(
                RuntimeToolCheck(
                    tool_id=tool_id,
                    requested_tool_id=requested_tool_id,
                    exists=False,
                    available=False,
                    status="missing",
                    code=missing_code,
                    detail=detail,
                )
            )
            continue

        is_available = status == "available"
        checks.append(
            RuntimeToolCheck(
                tool_id=tool_id,
                requested_tool_id=requested_tool_id,
                exists=True,
                available=is_available,
                status=status,
                code=None if is_available else "RUNTIME_TOOL_UNAVAILABLE",
                detail=(
                    None
                    if is_available
                    else f"{resolved_hint}Tool reported status '{status}'."
                ),
            )
        )

    executable = bool(checks) and all(check.available for check in checks)
    return PreflightCheckResponse(
        executable=executable,
        checks=checks,
        warnings=warnings,
        resolved_from_workflow=resolved_from_workflow,
        guidance=(
            None
            if executable
            else _build_environment_guidance(
                workflow_id=normalized_workflow_id,
                checks=checks,
            )
        ),
    )
