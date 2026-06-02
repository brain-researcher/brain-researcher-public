"""Synthetic smoke test for workflow_behavior_to_fmri_retrieval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.tools.runner import execute_tool


def _workflow_present() -> bool:
    resp = mcp_server.workflow_search("behavior fmri retrieval", limit=50)
    if not resp.get("ok"):
        return False
    return any(
        str(row.get("id") or "") == "workflow_behavior_to_fmri_retrieval"
        for row in (resp.get("workflows") or [])
    )


@pytest.mark.timeout(120)
def test_workflow_behavior_to_fmri_retrieval_smoke(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if not _workflow_present():
        pytest.skip("workflow_behavior_to_fmri_retrieval is not registered yet")

    class StubNeo4jDB:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.graph.neo4j_utils.require_neo4j_db",
        lambda **_: StubNeo4jDB(),
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.behavior_to_fmri_retrieval",
        lambda **_: {
            "seed": {"id": "psych101:task:go-no-go"},
            "seed_tasks": [{"id": "psych101:task:go-no-go"}],
            "items": [
                {
                    "item_id": "taskanalysis:openneuro_glmfitlins:ds000009:stopsignal",
                    "retrieval_methods": [
                        "family_bridge",
                        "behavior_similar_family_bridge",
                    ],
                }
            ],
            "summary": {
                "item_count": 1,
                "behavior_neighbor_count": 1,
                "retrieval_method_counts": {
                    "family_bridge": 1,
                    "behavior_similar_family_bridge": 1,
                },
            },
        },
    )

    out_dir = tmp_path / "behavior_to_fmri_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_behavior_to_fmri_retrieval",
        {
            "output_dir": str(out_dir),
            "seed_id": "psych101:task:go-no-go",
            "limit": 1,
        },
    )

    assert res.status == "success", res.error
    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_behavior_to_fmri_retrieval"

    retrieval_path = out_dir / "behavior_to_fmri_retrieval.json"
    assert retrieval_path.exists()
    payload = json.loads(retrieval_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "behavior-to-fmri-retrieval-v1"
    assert payload["seed_id"] == "psych101:task:go-no-go"
    assert payload["retrieval"]["summary"]["item_count"] == 1
