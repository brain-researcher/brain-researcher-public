"""Tests for ResourceType YAML loading and error handling."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from brain_researcher.services.shared.planner.models import ResourceType


@pytest.fixture(autouse=True)
def restore_resource_types():
    """Snapshot and restore ResourceType state to avoid cross-test bleed."""
    allowed_before = ResourceType.get_allowed()
    yaml_loaded = ResourceType._YAML_LOADED  # type: ignore[attr-defined]
    yield
    ResourceType._ALLOWED = set(allowed_before)  # type: ignore[attr-defined]
    ResourceType._YAML_LOADED = yaml_loaded  # type: ignore[attr-defined]


def test_load_from_yaml_adds_new_types(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    yaml_path = tmp_path / "resources.yaml"
    yaml_path.write_text(
        """
resources:
  - name: extra_type
  - name: another_type
"""
    )

    hardcoded = set(ResourceType._HARDCODED)  # type: ignore[attr-defined]
    ResourceType.load_from_yaml(yaml_path)
    after = ResourceType.get_allowed()

    assert "extra_type" in after
    assert "another_type" in after
    assert set(after) == hardcoded | {"extra_type", "another_type"}


def test_load_from_yaml_missing_file_warns_and_keeps_defaults(caplog: pytest.LogCaptureFixture):
    missing_path = Path("/tmp/definitely_missing_resource_yaml.yaml")
    before = ResourceType.get_allowed()

    import logging

    caplog.set_level(logging.WARNING, logger="brain_researcher.services.shared.planner.models")
    ResourceType.load_from_yaml(missing_path)

    after = ResourceType.get_allowed()
    assert before == after
    assert "Resource YAML not found" in caplog.text


def test_load_from_yaml_malformed_resets_to_hardcoded(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    malformed = tmp_path / "bad.yaml"
    malformed.write_text("::not yaml::")

    import logging

    caplog.set_level(logging.ERROR, logger="brain_researcher.services.shared.planner.models")
    hardcoded = set(ResourceType._HARDCODED)  # type: ignore[attr-defined]
    ResourceType.load_from_yaml(malformed)
    after = ResourceType.get_allowed()

    # Should fall back exactly to hardcoded set
    assert set(after) == hardcoded
