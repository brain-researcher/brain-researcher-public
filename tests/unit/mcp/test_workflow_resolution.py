from __future__ import annotations

import pytest


def _pick_non_catalog_workflow_id() -> str | None:
    from brain_researcher.services.tools.catalog_loader import (
        load_orchestration_workflows,
        load_tools_catalog,
    )

    workflows = load_orchestration_workflows()
    catalog_ids = set(load_tools_catalog().keys())
    return next((wid for wid in workflows if wid not in catalog_ids), None)


def _clear_mcp_registry_state(srv) -> None:
    # Ensure we don't read stale tool-spec resolution state.
    srv._TOOLSPEC_SCHEMA_CACHE.clear()
    try:
        srv._get_registry.cache_clear()
    except Exception:
        pass


def _assert_workflow_toolspec_is_executable(srv, workflow_id: str) -> None:
    from brain_researcher.services.tools.executor import _resolve_python_tool_instance

    spec = srv._get_toolspec_with_schema(workflow_id)
    assert spec is not None
    assert spec.backend == "python"
    assert bool(spec.python_class), f"{workflow_id} must resolve python_class"

    tool = _resolve_python_tool_instance(spec)
    assert tool is not None, f"{workflow_id} python_class must resolve an executable tool"
    assert callable(getattr(tool, "run", None))


def test_tool_search_and_plan_validate_agree_for_non_catalog_workflow():
    from brain_researcher.services.mcp import server as srv

    workflow_id = _pick_non_catalog_workflow_id()
    if workflow_id is None:
        pytest.skip("No non-catalog orchestration workflow IDs configured.")

    _clear_mcp_registry_state(srv)

    search = srv.tool_search(
        query=workflow_id,
        limit=500,
        exposed_only=True,
        include_workflows=True,
    )
    assert search["ok"] is True
    names = {tool.get("name") for tool in search.get("tools", [])}
    assert workflow_id in names

    validated = srv.pipeline_plan_validate(
        {"steps": [{"tool": workflow_id, "params": {}}]}
    )
    codes = {issue.get("code") for issue in validated.get("issues", [])}
    assert "unknown_tool" not in codes
    _assert_workflow_toolspec_is_executable(srv, workflow_id)


def test_visual_decoding_and_candidate_cards_workflows_are_executable():
    from brain_researcher.services.mcp import server as srv

    _clear_mcp_registry_state(srv)

    for workflow_id in (
        "workflow_visual_decoding",
        "workflow_hypothesis_candidate_cards",
    ):
        _assert_workflow_toolspec_is_executable(srv, workflow_id)
