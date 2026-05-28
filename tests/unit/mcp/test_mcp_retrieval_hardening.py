from __future__ import annotations


def test_workflow_search_matches_broad_resting_state_connectivity_query() -> None:
    from brain_researcher.services.mcp import server as srv

    resp = srv.workflow_search(
        "resting-state fMRI connectivity default mode network",
        limit=10,
    )

    assert resp["ok"] is True
    workflow_ids = [str(row.get("id") or "") for row in resp["workflows"]]
    assert "workflow_rest_connectome_e2e" in workflow_ids


def test_execution_recipe_handoff_uses_supported_python_runtime_for_ds000114() -> None:
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_rest_connectome_e2e",
        target_runtime="python",
        params={"dataset_id": "ds000114"},
    )

    assert resp["ok"] is True
    assert resp["resolved_tool_id"] == "workflow_rest_connectome_e2e"
    assert resp["target_runtime"] == "python"
    assert resp["supported_recipe_targets"] == ["python"]
    assert resp["run_pack"]["handoff"]["workflow_id"] == "workflow_rest_connectome_e2e"
    assert resp["run_pack"]["handoff"]["execution"]["target_runtime"] == "python"
    assert resp["run_pack"]["handoff"]["inputs"]["dataset_id"] == "ds000114"
    assert resp["recipe"]["files"]["params.json"]


def test_kg_multihop_qa_no_seed_broad_query_returns_seed_suggestions(
    monkeypatch,
) -> None:
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools import kg_multihop_qa_tool as qa_tool_module

    class FakeKGMultihopQATool:
        def run(self, **kwargs):
            del kwargs
            return {
                "status": "error",
                "error": "No seed entities found for the provided question",
            }

    monkeypatch.setattr(qa_tool_module, "KGMultihopQATool", FakeKGMultihopQATool)

    resp = srv.kg_multihop_qa(
        question=(
            "How does default mode network fMRI connectivity relate to "
            "atlas-based connectome workflows?"
        ),
        semantic=True,
    )

    assert resp["ok"] is False
    suggestions = resp["seed_suggestions"]
    queries = {str(item.get("query") or "") for item in suggestions}
    assert "default mode network" in queries
    assert "connectome" in queries
    assert "atlas-based signal extraction" in queries
