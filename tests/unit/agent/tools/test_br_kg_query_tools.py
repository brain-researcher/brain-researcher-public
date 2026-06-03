from brain_researcher.services.br_kg import query_service
from brain_researcher.services.tools.br_kg_query_tool import (
    DatasetResourcesTool,
    NodeDetailsTool,
    RelatedDatasetsTool,
    SearchDatasetsTool,
    SearchNodesTool,
)


def test_search_nodes_tool_uses_service(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "search_nodes",
        lambda *a, **k: [query_service.KGNodeSummary(kg_id="n1", label="Motor", node_type="BrainRegion", score=0.9)],
    )
    tool = SearchNodesTool()
    result = tool._run("motor")
    assert result.status == "success"
    assert result.data["items"][0]["kg_id"] == "n1"


def test_search_datasets_tool_maps_results(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "search_datasets",
        lambda **kwargs: [
            query_service.DatasetSummary(
                dataset_id="ds000001",
                title="Motor fMRI",
                tasks=["motor"],
                modalities=["fMRI"],
                n_subjects=100,
                kg_id="nk:ds1",
                species="human",
            )
        ],
    )
    tool = SearchDatasetsTool()
    result = tool._run(text="motor")
    assert result.status == "success"
    assert result.data["items"][0]["dataset_id"] == "ds000001"
    assert result.data["items"][0]["kg_id"] == "nk:ds1"


def test_dataset_resources_tool_returns_data(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "dataset_resources",
        lambda dataset_ref: query_service.DatasetResourceSummary(
            dataset_id=dataset_ref,
            resolved_dataset_id=dataset_ref,
            resolution_mode="catalog",
            resolver_warnings=[],
            bids_path="/data/bids",
            is_bids_available=True,
            derivatives={"fmriprep": "/derivs/fmriprep"},
            available_derivatives=["fmriprep"],
            remote_urls={},
            size_bytes=10,
            kg_id="nk:ds1",
        ),
    )
    tool = DatasetResourcesTool()
    result = tool._run("ds000001")
    assert result.status == "success"
    assert result.data["kg_id"] == "nk:ds1"


def test_node_details_tool_handles_missing(monkeypatch):
    monkeypatch.setattr(query_service, "node_details", lambda kg_id: None)
    tool = NodeDetailsTool()
    result = tool._run("missing")
    assert result.status == "error"


def test_related_datasets_tool(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "related_datasets",
        lambda kg_id, limit=10: [
            query_service.DatasetSummary(
                dataset_id="ds000002",
                title="Visual",
                tasks=["visual"],
                modalities=["fMRI"],
                n_subjects=50,
                kg_id="nk:ds2",
                species=None,
            )
        ],
    )
    tool = RelatedDatasetsTool()
    result = tool._run("nk:concept:1")
    assert result.status == "success"
    assert result.data["items"][0]["dataset_id"] == "ds000002"
