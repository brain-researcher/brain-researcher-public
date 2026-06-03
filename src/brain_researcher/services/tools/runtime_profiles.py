"""Shared runtime profile metadata for execution recipes and Neurodesk helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import resolve_from_config


_DEFAULT_RUNTIME_PACKAGE_ALIASES: dict[str, str] = {
    # Runtime-aligned canonical tool IDs that should resolve to Neurodesk
    # package families rather than remain as opaque identifiers.
    "ants_registration": "ants",
    "fsl_bedpostx": "fsl",
    "fsl_bed": "fsl",
    "fsl_bet": "fsl",
    "fsl_command": "fsl",
    "fsl_feat": "fsl",
    "fsl_fix": "fsl",
    "fsl_flirt": "fsl",
    "fsl_fnirt": "fsl",
    "fsl_melodic": "fsl",
    "fsl_palm": "fsl",
    "mrtrix3_command": "mrtrix3",
    "spm12": "cat12",
    "spm12_vbm": "cat12",
}


@lru_cache(maxsize=1)
def load_execution_recipe_config() -> dict[str, Any]:
    path = resolve_from_config("runtime", "execution_recipes.yaml")
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def execution_recipe_config_path() -> Path:
    """Return the canonical checked-in execution recipe metadata path."""

    return resolve_from_config("runtime", "execution_recipes.yaml")


def _normalize_key(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_runtime_package_name(name: str | None) -> str:
    """Resolve package aliases and canonical runtime IDs to Neurodesk packages."""

    normalized = _normalize_key(name)
    if not normalized:
        return normalized

    config = load_execution_recipe_config()
    for alias_source in (
        config.get("runtime_package_aliases"),
        config.get("aliases"),
        _DEFAULT_RUNTIME_PACKAGE_ALIASES,
    ):
        if not isinstance(alias_source, dict):
            continue
        alias = alias_source.get(normalized)
        if isinstance(alias, str) and alias.strip():
            normalized = alias.strip().lower()
            break

    packages = load_execution_recipe_config().get("neurodesk_packages")
    if isinstance(packages, dict) and normalized in packages:
        return normalized

    if "_" in normalized:
        prefix = normalized.split("_", 1)[0]
        if prefix and prefix != normalized:
            resolved_prefix = normalize_runtime_package_name(prefix)
            if resolved_prefix:
                return resolved_prefix

    return normalized


def get_neurodesk_package_profile(name: str | None) -> dict[str, Any] | None:
    """Return pinned Neurodesk metadata for a package/tool family."""

    normalized = normalize_runtime_package_name(name)
    if not normalized:
        return None

    packages = load_execution_recipe_config().get("neurodesk_packages")
    if not isinstance(packages, dict):
        return None

    raw = packages.get(normalized)
    if not isinstance(raw, dict):
        return None

    profile = dict(raw)
    profile.setdefault("module_name", normalized)
    profile["name"] = normalized
    return profile


def get_container_image(name: str | None) -> str | None:
    """Return a pinned container image tag when configured."""

    normalized = normalize_runtime_package_name(name)
    if not normalized:
        return None

    images = load_execution_recipe_config().get("container_images")
    if not isinstance(images, dict):
        return None
    raw = images.get(normalized)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def get_neurodesk_command_template(package: str, command: str) -> str | None:
    """Return the CLI command template for a Neurodesk package + command name.

    Templates use ``{param}`` for required positional substitutions and
    ``{-flag param}`` for optional flag+value pairs.  Returns *None* when no
    template is configured for the (package, command) combination.
    """
    profile = get_neurodesk_package_profile(package)
    if not isinstance(profile, dict):
        return None
    commands = profile.get("commands")
    if not isinstance(commands, dict):
        return None
    template = commands.get(command)
    return str(template) if isinstance(template, str) else None


def get_tool_recipe_override(tool_id: str | None) -> dict[str, Any]:
    """Return per-tool/workflow execution recipe overrides."""

    normalized = str(tool_id or "").strip()
    if not normalized:
        return {}

    overrides = load_execution_recipe_config().get("tool_overrides")
    if not isinstance(overrides, dict):
        return {}
    raw = overrides.get(normalized)
    return dict(raw) if isinstance(raw, dict) else {}


def get_tool_recipe_declaration(tool_id: str | None) -> dict[str, Any]:
    """Return declared canonical recipe metadata for a public tool."""

    normalized = str(tool_id or "").strip()
    if not normalized:
        return {}

    declarations = load_execution_recipe_config().get("tool_declarations")
    if not isinstance(declarations, dict):
        return {}
    raw = declarations.get(normalized)
    return dict(raw) if isinstance(raw, dict) else {}


__all__ = [
    "execution_recipe_config_path",
    "get_container_image",
    "get_neurodesk_command_template",
    "get_neurodesk_package_profile",
    "get_tool_recipe_declaration",
    "get_tool_recipe_override",
    "load_execution_recipe_config",
    "normalize_runtime_package_name",
]
