import json
from pathlib import Path

import pytest

from brain_researcher.services.agent.evidence_collection import (
    EvidenceCollector,
    EvidenceType,
)


def test_collect_tool_and_params_captured(tmp_path: Path):
    coll = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    coll.clear()  # start clean

    ev = coll.collect_tool_execution(
        tool_name="fsl-bet",
        version="6.0.7",
        command="bet input.nii.gz output.nii.gz",
        parameters={"f": 0.5, "g": 0.0},
        execution_time=1.23,
        success=True,
    )

    tools = coll.get_evidence_by_type(EvidenceType.TOOL)
    params = coll.get_evidence_by_type(EvidenceType.PARAMETER)

    assert len(tools) == 1
    assert len(params) == 1
    assert tools[0].content["name"] == "fsl-bet"
    assert tools[0].content["version"] == "6.0.7"
    assert params[0].source == "fsl-bet"
    assert params[0].content["f"] == 0.5


def test_jsonld_export_has_context_and_graph(tmp_path: Path):
    coll = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    coll.clear()
    coll.collect_dataset(dataset_id="ds000001", name="Example")
    path = coll.export_jsonld()

    assert path.exists()
    data = json.loads(path.read_text())
    assert "@context" in data
    assert "@graph" in data
    # at least the run node + one evidence
    assert len(data["@graph"]) >= 2


def test_run_card_contains_sections(tmp_path: Path):
    coll = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    coll.clear()
    coll.collect_dataset("ds000002", name="Demo DS")
    coll.collect_publication(
        doi="10.1000/demo", title="Demo Study", authors=["Doe, J"], year=2024
    )
    coll.collect_tool_execution(
        tool_name="neurodesk-fsl", version="1.2.3", parameters={"thr": 2.3}
    )
    card = coll.generate_run_card()

    assert card["run_id"].startswith("run_")
    assert any(card.get(k) is not None for k in ["datasets", "tools", "parameters"])
    assert isinstance(card.get("citations"), list)


def test_provenance_chain_edges(tmp_path: Path):
    coll = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    coll.clear()
    chain = coll.start_chain("demo chain")
    e1 = coll.collect_dataset("dsX", name="X")
    e2 = coll.collect_tool_execution("toolA", parameters={})
    coll.end_chain()

    report = coll.generate_report()
    chains = report["chains"]
    assert len(chains) == 1
    prov = chains[0]["provenance"]
    # one edge between two steps
    assert len(prov["edges"]) == 1
    assert prov["edges"][0]["label"] == "derives_from"


def test_publication_linking_adds_citation(tmp_path: Path):
    coll = EvidenceCollector(storage_path=tmp_path, auto_persist=False)
    coll.clear()
    pub = coll.collect_publication(
        doi="10.1234/abcd", title="A Study", authors=["Smith, A"], year=2023
    )
    tool = coll.collect_tool_execution("toolX", parameters={})
    ok = coll.link_publication_to_evidence(tool.evidence_id, "10.1234/abcd")
    assert ok is True
    # citation string should be present
    citations = coll.get_citations()
    assert any("A Study" in c or "Smith" in c for c in citations)

