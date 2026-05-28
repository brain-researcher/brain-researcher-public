import pytest

from brain_researcher.services.agent.kg_resolution import (
    DatasetResolution,
    DatasetResources,
    DerivativeHit,
    KGNodeRef,
    QueryUnderstandingResult,
)
from brain_researcher.services.agent.planning import PlanningEngine


@pytest.mark.asyncio
async def test_planner_structured_context_includes_qur(monkeypatch):
    engine = PlanningEngine(use_cot_reasoning=False, use_advanced_parsing=False)

    # Minimal intent stub
    from brain_researcher.services.agent.planning import QueryIntent

    intent = QueryIntent(primary_intent="analysis", domain="fmri", entities={})

    qur = QueryUnderstandingResult(
        original_query="Analyze motor task",
        entities=[{"text": "ds000001", "type": "dataset"}],
        resolved_datasets=[
            DatasetResolution(
                dataset_id="ds:openneuro:ds000001",
                name="Motor",
                source_repo="OpenNeuro",
                primary_url="https://openneuro.org/datasets/ds000001",
                local_path=None,
                kg_node_id="dataset:ds000001",
                display_name="Motor",
                bids_path="/data/ds000001",
                remote_url="https://openneuro.org/datasets/ds000001",
                aliases=[],
                resources=DatasetResources(
                    bids_path="/data/ds000001",
                    derivatives={"fmriprep": "/deriv/fmriprep/ds000001"},
                    remote_urls={
                        "openneuro": "https://openneuro.org/datasets/ds000001"
                    },
                    size_bytes=None,
                    is_bids_available=True,
                    available_derivatives=["fmriprep"],
                ),
            )
        ],
        kg_nodes=[
            KGNodeRef(id="nkglite:brain_region:v1", label="V1", type="brain_region")
        ],
        ambiguities=["contrast not specified"],
        existing_derivatives=[
            DerivativeHit(
                dataset_id="ds:openneuro:ds000001",
                kind="fmriprep",
                path="/deriv/fmriprep/ds000001",
                description=None,
                pipeline_signature=None,
                metadata={},
            )
        ],
    )

    ctx = {"query_understanding": qur}

    # monkeypatch _run_prompt to capture prompt content
    captured = {}

    async def fake_run_prompt(prompt, _):
        # messages[1] is a HumanMessagePromptTemplate; render to string
        rendered = prompt.format()
        captured["content"] = rendered

        class Resp:
            content = "[]"

        return Resp()

    monkeypatch.setattr(engine, "_run_prompt", fake_run_prompt)

    await engine._generate_steps("Analyze motor task", intent, ctx, None)

    content = captured.get("content", "")
    assert "Structured Context" in content
    assert "ds000001" in content
    assert "/deriv/fmriprep/ds000001" in content
    assert "brain_region" in content
    assert "contrast not specified" in content
    assert "prefer list_dataset_assets" in content.lower()
    assert "reuse" in engine._format_query_understanding(qur).lower()


def test_planner_prefers_list_dataset_assets_in_candidate_order():
    engine = PlanningEngine(use_cot_reasoning=False, use_advanced_parsing=False)
    engine._tool_capabilities = {
        "resolve_dataset_asset": {
            "description": "Resolve a dataset asset",
            "domains": ["dataset"],
        },
        "list_dataset_assets": {
            "description": "Browse dataset assets",
            "domains": ["dataset"],
        },
    }

    relevant = engine._select_relevant_tools(
        "dataset",
        context={
            "query_understanding": {"resolved_datasets": ["ds000114"]},
            "tool_candidates": [
                {"tool_id": "resolve_dataset_asset"},
                {"tool_id": "list_dataset_assets"},
            ],
        },
        query="list available dataset assets for ds000114",
    )

    assert list(relevant) == ["list_dataset_assets", "resolve_dataset_asset"]
