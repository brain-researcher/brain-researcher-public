"""
Utilities for checking agent tool dependencies.

This module reads :mod:`dependencies.yaml` which lists the Python packages,
executables, container runtimes, and environment variables that unlock
optional tool capabilities.  It mirrors the approach used by Biomni by keeping
metadata declarative and emitting structured guidance during discovery.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    yaml = None
    _YAML_IMPORT_ERROR = exc
else:
    _YAML_IMPORT_ERROR = None


@dataclass(frozen=True)
class DependencySpec:
    """Represents an entry in the dependency manifest."""

    name: str
    category: str
    optional: bool
    summary: str | None = None
    install_hint: str | None = None
    module: str | None = None
    command: str | None = None
    key: str | None = None
    used_by: list[str] | None = None


@dataclass(frozen=True)
class DependencyStatus:
    """Result of checking a single dependency."""

    spec: DependencySpec
    present: bool
    detail: str | None = None


class ManifestLoadError(RuntimeError):
    """Raised when the dependency manifest cannot be parsed."""


def _default_manifest_path() -> Path:
    return Path(__file__).with_name("dependencies.yaml")


def load_dependency_manifest(path: Path | None = None) -> list[DependencySpec]:
    """Parse the dependency manifest into :class:`DependencySpec` objects."""

    manifest_path = path or _default_manifest_path()
    if not manifest_path.exists():
        raise ManifestLoadError(f"Dependency manifest not found: {manifest_path}")

    if yaml is None:
        raise ManifestLoadError(
            "PyYAML is required to parse the dependency manifest"
        ) from _YAML_IMPORT_ERROR

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive logging
        raise ManifestLoadError(f"Failed to parse {manifest_path}: {exc}") from exc

    entries = data.get("dependencies", [])
    specs: list[DependencySpec] = []
    for entry in entries:
        specs.append(
            DependencySpec(
                name=entry["name"],
                category=entry["category"],
                optional=bool(entry.get("optional", True)),
                summary=entry.get("summary"),
                install_hint=entry.get("install_hint"),
                module=entry.get("module"),
                command=entry.get("command"),
                key=entry.get("key"),
                used_by=entry.get("used_by"),
            )
        )
    return specs


def _check_python_package(spec: DependencySpec) -> tuple[bool, str | None]:
    module_name = spec.module or spec.name
    if not module_name:
        return False, "No module specified for python-package dependency"
    module_spec = importlib.util.find_spec(module_name)
    return (
        module_spec is not None,
        None if module_spec else f"Module '{module_name}' not importable",
    )


def _check_executable(spec: DependencySpec) -> tuple[bool, str | None]:
    command = spec.command or spec.name
    if not command:
        return False, "No command specified for executable dependency"
    path = shutil.which(command)
    return (
        path is not None,
        None if path else f"Executable '{command}' not found on PATH",
    )


def _check_envvar(spec: DependencySpec) -> tuple[bool, str | None]:
    key = spec.key or spec.name
    if not key:
        return False, "No key specified for envvar dependency"
    value = os.environ.get(key)
    return (bool(value), None if value else f"Environment variable '{key}' not set")


_CHECKERS = {
    "python-package": _check_python_package,
    "executable": _check_executable,
    "container": _check_executable,
    "container-runtime": _check_executable,
    "envvar": _check_envvar,
}


def check_dependency(spec: DependencySpec) -> DependencyStatus:
    """Determine whether a dependency is available."""

    checker = _CHECKERS.get(spec.category)
    if checker is None:
        return DependencyStatus(
            spec=spec,
            present=False,
            detail=f"Unknown dependency category: {spec.category}",
        )

    present, detail = checker(spec)
    return DependencyStatus(
        spec=spec, present=present, detail=detail if not present else None
    )


def collect_dependency_status(path: Path | None = None) -> list[DependencyStatus]:
    """Load the manifest and evaluate each dependency."""

    specs = load_dependency_manifest(path)
    return [check_dependency(spec) for spec in specs]


def summarise_missing_by_category(
    statuses: Iterable[DependencyStatus],
) -> dict[str, list[DependencyStatus]]:
    """Group missing dependencies so callers can display category-specific guidance."""

    grouped: dict[str, list[DependencyStatus]] = {}
    for status in statuses:
        if status.present:
            continue
        grouped.setdefault(status.spec.category, []).append(status)
    return grouped
