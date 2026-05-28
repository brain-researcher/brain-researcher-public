from types import SimpleNamespace

from brain_researcher.services.agent.tool_router import ToolRouter


def test_router_boosts_neurokg_for_brain_region():
    specs = [
        SimpleNamespace(
            runtime_id="neurokg.search_nodes",
            name="neurokg.search_nodes",
            description="",
            tags=["neurokg"],
            dangerous=False,
        ),
        SimpleNamespace(
            runtime_id="other.tool",
            name="other",
            description="",
            tags=[],
            dangerous=False,
        ),
    ]
    ctx = {
        "query_understanding": SimpleNamespace(
            resolved_datasets=[],
            kg_nodes=[SimpleNamespace(type="BrainRegion")],
        )
    }
    ranked = ToolRouter._rank("motor cortex", specs, ctx=ctx)
    assert ranked[0].runtime_id == "neurokg.search_nodes"


def test_router_boosts_dataset_tools_when_dataset_present():
    specs = [
        SimpleNamespace(
            runtime_id="neurokg.search_datasets",
            name="neurokg.search_datasets",
            description="",
            tags=["dataset_catalog", "neurokg"],
            dangerous=False,
        ),
        SimpleNamespace(
            runtime_id="generic",
            name="generic",
            description="",
            tags=[],
            dangerous=False,
        ),
    ]
    ctx = {
        "query_understanding": SimpleNamespace(
            resolved_datasets=[SimpleNamespace(dataset_id="ds1")],
            kg_nodes=[],
        )
    }
    ranked = ToolRouter._rank("dataset", specs, ctx=ctx)
    assert ranked[0].runtime_id == "neurokg.search_datasets"

