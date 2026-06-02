from __future__ import annotations

import importlib

import pytest

from brain_researcher.services.br_kg.etl.loaders.session_snapshot_loader import (
    build_session_snapshot_graph_payload,
    load_session_digests,
    validate_session_graph_payload,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.br_kg.schemas.edge_schemas import (
    ALLOWED_EDGES,
    EDGE_TYPES,
    validate_edge,
)
from brain_researcher.services.br_kg.schemas.node_schemas import (
    NODE_TYPES,
    validate_node,
)
from brain_researcher.services.shared import session_lessons as shared_session_lessons
from brain_researcher.services.shared.session_lessons import (
    SESSION_KG_NODE_LABELS,
    SESSION_KG_RELATIONSHIP_TYPES,
    build_session_kg_rows,
)


def _prov() -> dict[str, object]:
    return {
        "source": "research_logging",
        "method": "rule",
        "confidence": 1.0,
        "loader_version": "test",
    }


def _digest() -> dict[str, object]:
    return {
        "run_id": "br_test",
        "session_id": "kg-schema-session",
        "source_client": "",
        "status": "succeeded",
        "has_snapshot": True,
        "last_event_at": "2026-05-26T00:00:00Z",
        "snapshot": {
            "goal": "Ship prod rollout",
            "next_command": "pytest -q tests/unit/br_kg/test_session_lessons_graph_schema.py",
        },
        "done_items": [
            "Verified pytest -q tests/unit/mcp/test_research_event_tools.py.",
        ],
        "open_items": [
            "partial-validation: browser smoke was not run.",
        ],
        "event_tags": ["prod", "session-lessons"],
    }


def test_mcp_session_lessons_path_reexports_shared_module() -> None:
    mcp_session_lessons = importlib.import_module(
        "brain_researcher.services.mcp.session_lessons"
    )
    assert mcp_session_lessons is shared_session_lessons
    assert mcp_session_lessons.build_session_kg_rows is build_session_kg_rows


def test_session_lesson_schema_registries_include_requested_types() -> None:
    assert set(SESSION_KG_NODE_LABELS) <= set(NODE_TYPES)
    assert set(SESSION_KG_RELATIONSHIP_TYPES) <= set(EDGE_TYPES)

    for rel_type in SESSION_KG_RELATIONSHIP_TYPES:
        assert rel_type in ALLOWED_EDGES


def test_session_lesson_node_and_edge_examples_validate() -> None:
    assert (
        validate_node(
            "AgentSession",
            {
                "session_id": "s1",
                "prov": _prov(),
                "raw_session_json": {"session_id": "s1"},
            },
        ).id
        == "agent_session:s1"
    )
    assert (
        validate_node(
            "OpenRisk",
            {
                "id": "open_risk:1",
                "label": "partial-validation",
                "text": "No browser smoke was run.",
                "prov": _prov(),
            },
        ).label
        == "partial-validation"
    )

    edge = validate_edge(
        "EXPOSED_FAILURE_MODE",
        {
            "source_id": "task_surface:prod-runtime",
            "target_id": "open_risk:1",
            "prov": _prov(),
            "session_id": "s1",
        },
    )
    assert edge.source_type == "TaskSurface"


def test_session_lesson_edge_rejects_wrong_direction() -> None:
    with pytest.raises(ValueError):
        validate_edge(
            "EXPOSED_FAILURE_MODE",
            {
                "source_id": "agent_session:s1",
                "target_id": "open_risk:1",
                "prov": _prov(),
            },
        )


def test_session_graph_payload_has_no_dangling_edges() -> None:
    graph = build_session_kg_rows(_digest())
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}

    assert validate_session_graph_payload(graph) == []
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids
        for edge in graph["edges"]
    )
    assert set(SESSION_KG_RELATIONSHIP_TYPES) <= edge_types
    session_node = next(
        node for node in graph["nodes"] if "AgentSession" in node["labels"]
    )
    assert session_node["properties"]["raw_session_json"]["session_id"] == (
        "kg-schema-session"
    )


def test_session_digest_loader_writes_to_fake_graph_db() -> None:
    db = FakeGraphDB()
    result = load_session_digests(db, [_digest()])

    assert result["ok"] is True
    assert result["stats"]["nodes_written"] == result["node_count"]
    assert result["stats"]["relationships_written"] == result["edge_count"]
    assert db.find_nodes("AgentSession", {"session_id": "kg-schema-session"})
    assert db.find_relationships(rel_type="EXPOSED_FAILURE_MODE")


def test_session_snapshot_graph_payload_dedupes_surface_nodes() -> None:
    graph = build_session_snapshot_graph_payload([_digest(), _digest()])
    task_surface_nodes = [
        node for node in graph["nodes"] if "TaskSurface" in node["labels"]
    ]

    assert len({node["id"] for node in task_surface_nodes}) == len(task_surface_nodes)
