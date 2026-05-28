"""
Validation tests for configs/tools_catalog.json.

These guard against introducing resource or modality literals that are
unsupported by the shared planner contract models.
"""

from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.shared.planner.models import Domain, Modality, ResourceType


def _load_catalog() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    catalog_path = repo_root / "configs" / "tools_catalog.json"
    with catalog_path.open() as fh:
        return json.load(fh)


def test_tool_catalog_resource_types_are_valid():
    catalog = _load_catalog()
    allowed = ResourceType.get_allowed()
    invalid_entries = []

    for tool in catalog.get("tools", []):
        for section in ("consumes", "produces"):
            for key, resource in (tool.get(section) or {}).items():
                if resource not in allowed:
                    invalid_entries.append(
                        (tool.get("name", "<unknown>"), section, key, resource)
                    )

    assert (
        not invalid_entries
    ), f"tools_catalog.json has invalid resources: {invalid_entries}"


def test_tool_catalog_domains_and_modalities_are_valid():
    catalog = _load_catalog()
    allowed_domains = set(Domain.__args__)
    allowed_modalities = set(Modality.__args__)

    bad_domains = []
    bad_modalities = []

    for tool in catalog.get("tools", []):
        domain = tool.get("domain")
        if domain not in allowed_domains:
            bad_domains.append((tool.get("name", "<unknown>"), domain))

        for modality in tool.get("modality", []):
            if modality not in allowed_modalities:
                bad_modalities.append((tool.get("name", "<unknown>"), modality))

    assert not bad_domains, f"Invalid domains: {bad_domains}"
    assert not bad_modalities, f"Invalid modalities: {bad_modalities}"
