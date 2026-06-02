from types import SimpleNamespace

from brain_researcher.services.agent.tool_router import ToolRouter


def test_router_boosts_br_kg_for_brain_region():
    specs = [
        SimpleNamespace(
            runtime_id="br_kg.search_nodes",
            name="br_kg.search_nodes",
            description="",
            tags=["br_kg"],
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
    assert ranked[0].runtime_id == "br_kg.search_nodes"


def test_router_boosts_dataset_tools_when_dataset_present():
    specs = [
        SimpleNamespace(
            runtime_id="br_kg.search_datasets",
            name="br_kg.search_datasets",
            description="",
            tags=["dataset_catalog", "br_kg"],
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
    assert ranked[0].runtime_id == "br_kg.search_datasets"
