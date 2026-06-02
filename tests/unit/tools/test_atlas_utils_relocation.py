"""Compatibility checks for atlas helper relocation."""

from __future__ import annotations

import importlib


def test_tools_atlas_utils_aliases_shared_module() -> None:
    legacy = importlib.import_module("brain_researcher.services.tools.atlas_utils")
    moved = importlib.import_module("brain_researcher.services.shared.atlas_utils")

    assert legacy is moved
    assert legacy.existing_search_roots is moved.existing_search_roots
    assert legacy.resolve_local_volume_atlas is moved.resolve_local_volume_atlas
