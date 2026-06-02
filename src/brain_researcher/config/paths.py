"""Shared repository/config path resolution helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _normalize_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    if resolved.exists() and resolved.is_file():
        return resolved.parent
    return resolved


def _validate_config_root(path: Path, *, source: str) -> Path:
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(
            f"Invalid config root from {source}: {path} "
            "(set BR_CONFIG_ROOT to a valid directory)"
        )
    return path


@lru_cache(maxsize=1)
def _discover_config_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        cfg = parent / "configs"
        if not cfg.exists():
            continue
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return cfg

    for parent in current.parents:
        cfg = parent / "configs"
        if cfg.exists():
            return cfg

    raise FileNotFoundError(
        "Unable to locate configs directory from package path. "
        "Set BR_CONFIG_ROOT to repository root or configs directory."
    )


def clear_path_caches() -> None:
    """Clear internal resolver caches (mainly for tests)."""

    _discover_config_root.cache_clear()


def get_config_root() -> Path:
    """Return the canonical ``configs/`` directory.

    Resolution order:
    1. ``BR_CONFIG_ROOT`` env var (can point to repo root or configs dir)
    2. Upward sentinel walk from this package location.
    """

    configured = os.getenv("BR_CONFIG_ROOT")
    if configured:
        configured_dir = _normalize_dir(Path(configured))
        if (configured_dir / "configs").exists():
            return _validate_config_root(
                configured_dir / "configs", source="BR_CONFIG_ROOT(repo)"
            )
        return _validate_config_root(configured_dir, source="BR_CONFIG_ROOT(configs)")

    return _discover_config_root()


def get_repo_root() -> Path:
    """Return repository root derived from ``get_config_root()``."""

    return get_config_root().parent


def get_src_root() -> Path:
    """Return the canonical ``src/`` directory."""

    return get_repo_root() / "src"


def get_package_root() -> Path:
    """Return the canonical Python package root."""

    return get_src_root() / "brain_researcher"


def get_apps_root() -> Path:
    """Return the canonical ``apps/`` directory."""

    return get_repo_root() / "apps"


def get_data_root() -> Path:
    """Return the canonical ``data/`` directory."""

    return get_repo_root() / "data"


def get_default_atlas_output_root() -> Path:
    """Return the shared atlas artifact root.

    ``BR_ATLAS_OUTPUT_ROOT`` is the explicit runtime override. In containers
    where the shared atlas mount already exists, prefer ``/app/data/atlases``;
    otherwise fall back to the repository-level ``data/atlases`` directory.
    """

    explicit = os.getenv("BR_ATLAS_OUTPUT_ROOT", "").strip()
    if explicit:
        return Path(explicit)
    app_atlas_root = Path("/app/data/atlases")
    if app_atlas_root.exists():
        return app_atlas_root
    return get_data_root() / "atlases"


def get_outputs_root() -> Path:
    """Return the canonical ``outputs/`` directory."""

    return get_repo_root() / "outputs"


def resolve_from_config(*parts: str) -> Path:
    """Resolve a path under ``configs/``."""

    return get_config_root().joinpath(*parts)


def resolve_from_repo(*parts: str) -> Path:
    """Resolve a path under the repository root."""

    return get_repo_root().joinpath(*parts)
