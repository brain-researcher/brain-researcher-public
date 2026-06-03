"""Compose dataset configuration from overlay + local mounts.

This module produces a backward-compatible dictionary matching keys used by
`DataPathConfig` (local, oak_mount, api_sources, cache, dataset_priority,
loader_defaults, br_kg).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    return data


def compose_data_paths(
    project_root: Path | None = None, env: str = "dev"
) -> dict[str, Any]:
    """Compose the legacy data_paths-style config from new sources.

    Args:
        project_root: Repository root; auto-detected from this file when None
        env: Overlay name: one of dev|staging|prod|br_kg (for general keys)

    Returns:
        Backward-compatible configuration dictionary
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parents[3]

    cfg_dir = project_root / "configs" / "datasets"
    local_mounts = _read_yaml(cfg_dir / "local_mounts.yaml")

    # Choose overlay; fall back to dev
    overlay_path = cfg_dir / "overlays" / f"{env}.yaml"
    overlay = _read_yaml(overlay_path)
    if not overlay:
        overlay = _read_yaml(cfg_dir / "overlays" / "dev.yaml")

    # Map to legacy structure
    out: dict[str, Any] = {}

    # Local
    if "local" in local_mounts:
        out["local"] = local_mounts["local"]

    # OAK mount
    oak_cfg = local_mounts.get("oak_mount", {})
    if oak_cfg:
        out["oak_mount"] = {
            "enabled": bool(oak_cfg.get("enabled", False)),
            "base": oak_cfg.get("base"),
            "datasets": oak_cfg.get("datasets", {}),
        }
        # propagate resources and user under oak_mount for convenience
        if "resources" in oak_cfg:
            out["oak_mount"]["resources"] = oak_cfg["resources"]
        if "user" in oak_cfg:
            out["oak_mount"]["user"] = oak_cfg["user"]

    # API and cache
    for key in ("api_sources", "cache", "loader_defaults", "dataset_priority", "br_kg"):
        if key in overlay:
            out[key] = overlay[key]

    # Attach br_kg pipeline overlay under a namespaced key
    br_kg_overlay = _read_yaml(cfg_dir / "overlays" / "br-kg.yaml")
    if br_kg_overlay:
        out["_br_kg_overlay"] = br_kg_overlay

    return out
