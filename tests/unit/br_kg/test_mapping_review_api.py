from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from brain_researcher.services.br_kg.api.mapping_review_api import (
    init_mapping_review_api,
    mapping_review_bp,
)


class InMemoryMappingDB:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.relationships: list[dict[str, Any]] = []

    def add_node(self, node_id: str, *, labels: list[str], name: str) -> None:
        self.nodes[node_id] = {
            "id": node_id,
            "labels": labels,
            "name": name,
            "source": "test",
        }

    def add_mapping(
        self,
        source_id: str,
        target_id: str,
        *,
        confidence: float = 0.9,
        method: str = "exact",
        created_by: str = "seed",
    ) -> None:
        self.relationships.append(
            {
                "start": source_id,
                "end": target_id,
                "data": {
                    "type": "MAPS_TO",
                    "confidence": confidence,
                    "method": method,
                    "created_by": created_by,
                },
            }
        )

    def find_relationships(
        self,
        start_node: str | None = None,
        end_node: str | None = None,
        rel_type: str | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        out: list[tuple[str, str, dict[str, Any]]] = []
        for rel in self.relationships:
            if start_node and rel["start"] != start_node:
                continue
            if end_node and rel["end"] != end_node:
                continue
            if rel_type and rel["data"].get("type") != rel_type:
                continue
            out.append((rel["start"], rel["end"], dict(rel["data"])))
        return out

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        node = self.nodes.get(node_id)
        return dict(node) if node else None

    def update_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any],
    ) -> bool:
        updated = False
        for rel in self.relationships:
            if (
                rel["start"] == start_node
                and rel["end"] == end_node
                and rel["data"].get("type") == rel_type
            ):
                rel["data"].update(properties)
                updated = True
        return updated

    def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        del query
        source_id = str((params or {}).get("source_id") or "")
        target_id = str((params or {}).get("target_id") or "")

        before = len(self.relationships)
        self.relationships = [
            rel
            for rel in self.relationships
            if not (
                rel["start"] == source_id
                and rel["end"] == target_id
                and rel["data"].get("type") == "MAPS_TO"
            )
        ]
        deleted_count = before - len(self.relationships)
        return [{"deleted_count": deleted_count}]

    def relationship_data(
        self, source_id: str, target_id: str
    ) -> dict[str, Any] | None:
        for rel in self.relationships:
            if (
                rel["start"] == source_id
                and rel["end"] == target_id
                and rel["data"].get("type") == "MAPS_TO"
            ):
                return rel["data"]
        return None


@pytest.fixture
def db() -> InMemoryMappingDB:
    db = InMemoryMappingDB()

    db.add_node("s1", labels=["Concept"], name="source 1")
    db.add_node("t1", labels=["Task"], name="target 1")
    db.add_node("s2", labels=["Concept"], name="source 2")
    db.add_node("t2", labels=["Task"], name="target 2")
    db.add_node("s3", labels=["Concept"], name="source 3")
    db.add_node("t3", labels=["Task"], name="target 3")

    db.add_mapping("s1", "t1", confidence=0.95, method="exact", created_by="seed")
    db.add_mapping("s2", "t2", confidence=0.60, method="fuzzy", created_by="seed")
    db.add_mapping("s3", "t3", confidence=0.91, method="exact", created_by="scheduler")
    return db


@pytest.fixture
def client(db: InMemoryMappingDB):
    app = Flask(__name__)
    init_mapping_review_api(lambda: db)
    app.register_blueprint(mapping_review_bp)
    return app.test_client()


def test_bulk_action_selected_subset_takes_precedence_over_filters(
    client, db: InMemoryMappingDB
):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={
            "action": "approve",
            "mapping_ids": ["s2->t2"],
            "filters": {"method": "exact"},
            "reviewer": "alice",
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["processed"] == 1
    assert payload["succeeded"] == 1
    assert payload["failed"] == 0

    assert db.relationship_data("s2", "t2")["reviewed"] is True
    assert db.relationship_data("s2", "t2")["reviewed_by"] == "alice"
    assert db.relationship_data("s1", "t1").get("reviewed") is None


def test_bulk_action_filtered_subset_applies_when_no_selection(
    client, db: InMemoryMappingDB
):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "delete", "filters": {"method": "exact"}},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["processed"] == 2
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert payload["errors"] == []

    remaining = db.find_relationships(rel_type="MAPS_TO")
    assert len(remaining) == 1
    assert remaining[0][0] == "s2"
    assert remaining[0][1] == "t2"


def test_bulk_action_reports_mixed_success_and_failure(client):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={
            "action": "approve",
            "mapping_ids": ["s1->t1", "missing->t9", "bad-format"],
            "reviewer": "bob",
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["processed"] == 3
    assert payload["succeeded"] == 1
    assert payload["failed"] == 2
    assert len(payload["errors"]) == 2
    assert {e["mapping_id"] for e in payload["errors"]} == {"missing->t9", "bad-format"}


def test_bulk_delete_reports_mixed_success_and_failure(client, db: InMemoryMappingDB):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "delete", "mapping_ids": ["s1->t1", "missing->t9"]},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["processed"] == 2
    assert payload["succeeded"] == 1
    assert payload["failed"] == 1
    assert payload["errors"] == [
        {"mapping_id": "missing->t9", "error": "Mapping not found"}
    ]
    assert db.relationship_data("s1", "t1") is None


def test_bulk_action_rejects_empty_scope(client):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "approve"},
    )

    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["error"] == "Provide mapping_ids or filters"


def test_bulk_action_rejects_invalid_action(client):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "noop", "mapping_ids": ["s1->t1"]},
    )
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["error"] == "Invalid action"


def test_bulk_action_rejects_invalid_payload_shapes(client):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "approve", "mapping_ids": "s1->t1"},
    )
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["error"] == "mapping_ids must be a list"

    resp_filters = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "approve", "filters": "not-an-object"},
    )
    assert resp_filters.status_code == 400
    payload_filters = resp_filters.get_json()
    assert payload_filters["error"] == "filters must be an object"


def test_bulk_action_rejects_invalid_numeric_filter(client):
    resp = client.post(
        "/api/mapping-review/mappings/bulk-action",
        json={"action": "delete", "filters": {"confidence_min": "not-a-number"}},
    )
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["error"] == "Invalid numeric value: not-a-number"


def test_approve_mapping_handles_empty_body_and_persists(client, db: InMemoryMappingDB):
    resp = client.post(
        "/api/mapping-review/mappings/s1->t1/approve",
        data="",
        content_type="application/json",
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["message"] == "Mapping approved successfully"

    rel = db.relationship_data("s1", "t1")
    assert rel is not None
    assert rel["reviewed"] is True
    assert rel["reviewed_by"] == "user"


def test_delete_mapping_removes_relationship(client, db: InMemoryMappingDB):
    resp = client.delete("/api/mapping-review/mappings/s1->t1")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["message"] == "Mapping deleted successfully"
    assert db.relationship_data("s1", "t1") is None

    second = client.delete("/api/mapping-review/mappings/s1->t1")
    assert second.status_code == 404
