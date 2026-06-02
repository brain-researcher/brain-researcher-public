"""Path defaults for Neuromaps ingestion assets."""

from __future__ import annotations

from pathlib import Path

from brain_researcher.config.paths import get_default_atlas_output_root

LEGACY_NEUROMAPS_DIR = Path("data/br-kg/raw/neuromaps")
LEGACY_NILEARN_DIR = Path("data/br-kg/raw/nilearn_atlases")


def preferred_neuromaps_root() -> Path:
    shared_root = get_default_atlas_output_root() / "neuromaps"
    if shared_root.exists():
        return shared_root
    return LEGACY_NEUROMAPS_DIR.expanduser().resolve()


def preferred_yeo_fallback_root() -> Path:
    shared_root = get_default_atlas_output_root() / "yeo_2011"
    if shared_root.exists():
        return shared_root
    return LEGACY_NILEARN_DIR.expanduser().resolve()


__all__ = [
    "LEGACY_NEUROMAPS_DIR",
    "LEGACY_NILEARN_DIR",
    "preferred_neuromaps_root",
    "preferred_yeo_fallback_root",
]
