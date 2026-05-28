from __future__ import annotations

import pytest

from brain_researcher.services.mcp.execution_recipes import (
    build_execution_recipe,
    resolve_recipe_metadata,
)


@pytest.mark.parametrize(
    ("tool_id", "expected_kind"),
    [
        ("qbold_fabber", "binary_backed_atomic"),
        ("calibrated_perfusion_surrogate", "composite_workflow"),
    ],
)
def test_new_perfusion_tools_expose_python_recipe_metadata(tool_id, expected_kind):
    metadata = resolve_recipe_metadata(tool_id)

    assert metadata["execution_story_kind"] == expected_kind
    assert metadata["supported_recipe_targets"] == ["python"]
    assert metadata["primary_target"] == "python"
    assert metadata["hosted_via_br_mcp_service"] is False


@pytest.mark.parametrize(
    ("tool_id", "expected_kind"),
    [
        ("qbold_fabber", "binary_backed_atomic"),
        ("calibrated_perfusion_surrogate", "composite_workflow"),
    ],
)
def test_new_perfusion_tools_build_python_execution_recipes(tool_id, expected_kind):
    recipe = build_execution_recipe(tool_id, target_runtime="python")

    assert recipe["ok"] is True
    assert recipe["supported_recipe_targets"] == ["python"]
    assert recipe["execution_story_kind"] == expected_kind
    assert recipe["recipe"] is not None
