"""Compatibility checks for sandbox path validation relocation."""

from __future__ import annotations

import pytest

from brain_researcher.services.orchestrator.runtime import sandbox
from brain_researcher.services.shared import path_validation


def test_sandbox_reexports_shared_path_validation() -> None:
    assert sandbox.validate_path is path_validation.validate_path
    assert sandbox.validate_paths is path_validation.validate_paths


def test_shared_path_validation_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="directory traversal"):
        path_validation.validate_path("../unsafe")
