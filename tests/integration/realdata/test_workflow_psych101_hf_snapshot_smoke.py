"""Synthetic smoke test for workflow_psych101_hf_snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.br_kg.etl.loaders.psych101_hf_loader import (
    Psych101DatasetMetadata,
    Psych101ExperimentSummary,
    Psych101ParquetFile,
    Psych101SplitInfo,
)
from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.tools.runner import execute_tool


def _workflow_present() -> bool:
    resp = mcp_server.workflow_search("psych101", limit=50)
    if not resp.get("ok"):
        return False
    return any(
        str(row.get("id") or "") == "workflow_psych101_hf_snapshot"
        for row in (resp.get("workflows") or [])
    )


class StubNeo4jDB:
    def __init__(self) -> None:
        self.closed = False
        self.nodes: list[tuple[list[str], dict[str, object], str | None]] = []
        self.relationships: list[tuple[str, str, str, dict[str, object]]] = []

    def create_node(self, labels, properties=None, node_id=None, auto_commit=True):
        del auto_commit
        label_list = [labels] if isinstance(labels, str) else list(labels)
        self.nodes.append((label_list, dict(properties or {}), node_id))
        return node_id or f"node-{len(self.nodes)}"

    def create_relationship(
        self,
        start_node,
        end_node,
        rel_type,
        properties=None,
        auto_commit=True,
    ):
        del auto_commit
        self.relationships.append(
            (start_node, end_node, rel_type, dict(properties or {}))
        )
        return True

    def close(self) -> None:
        self.closed = True


@pytest.mark.timeout(120)
def test_workflow_psych101_hf_snapshot_smoke(tmp_path: Path, monkeypatch):
    if not _workflow_present():
        pytest.skip("workflow_psych101_hf_snapshot is not registered yet")

    metadata = Psych101DatasetMetadata(
        dataset_id="marcelbinz/Psych-101",
        title="Psych-101",
        license="apache-2.0",
        tags=("psychology",),
        splits=(Psych101SplitInfo(split="train", num_rows=5),),
        parquet_files=(
            Psych101ParquetFile(
                split="train",
                url="https://example.org/0000.parquet",
                filename="0000.parquet",
                num_rows=5,
            ),
        ),
        source_url="https://huggingface.co/datasets/marcelbinz/Psych-101",
        card_url="https://huggingface.co/datasets/marcelbinz/Psych-101",
    )
    experiments = [
        Psych101ExperimentSummary(
            experiment="peterson2021using/exp1.csv",
            row_count=3,
            participant_count=3,
        ),
        Psych101ExperimentSummary(
            experiment="hebart2023things/exp1.csv",
            row_count=2,
            participant_count=2,
        ),
    ]

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.etl.loaders.psych101_hf_loader.fetch_psych101_dataset_metadata",
        lambda dataset_id="marcelbinz/Psych-101", **_: metadata,
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.etl.loaders.psych101_hf_loader.summarize_psych101_from_metadata",
        lambda metadata, **_: experiments,
    )
    stub_db = StubNeo4jDB()
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.graph.neo4j_utils.require_neo4j_db",
        lambda **_: stub_db,
    )

    out_dir = tmp_path / "psych101_hf_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_psych101_hf_snapshot",
        {
            "output_dir": str(out_dir),
            "dataset_id": "psych101-demo",
        },
    )

    assert res.status == "success", res.error
    workflow_data = res.data or {}
    provenance = workflow_data.get("provenance") or {}
    assert provenance.get("workflow_id") == "workflow_psych101_hf_snapshot"

    metadata_path = out_dir / "psych101_hf_metadata.json"
    graph_path = out_dir / "psych101_hf_metadata_graph_plan.json"
    neo4j_path = out_dir / "psych101_hf_metadata_neo4j_ingest.json"
    assert metadata_path.exists()
    assert graph_path.exists()
    assert neo4j_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["graph_dataset_metadata"]["dataset_id"] == "psych101-demo"
    assert payload["neo4j_ingest"]["status"] == "success"
    assert stub_db.closed is True
