"""Tests for the OnvocLinker integration with ONVOC tree constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import pytest
import yaml

from brain_researcher.services.br_kg.utils.onvoc_linker import OnvocLinker


@dataclass
class FakeRecord:
    data: Dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class FakeResult:
    def __init__(self, records: Iterable[Dict[str, Any]]) -> None:
        self._records = [FakeRecord(rec) for rec in records]

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None

    def close(self):
        pass


class FakeDB:
    def __init__(self, class_records: List[Dict[str, Any]]) -> None:
        self.class_records = class_records
        self.relationships: List[Dict[str, Any]] = []

    def _run(self, query: str, params: Optional[Dict[str, Any]] = None) -> FakeResult:
        params = params or {}
        if "coalesce(o.name, o.label, o.id) AS name" in query:
            return FakeResult(self.class_records)
        if "RETURN r.confidence AS confidence" in query:
            entity = params.get("entity_id")
            class_id = params.get("class_id")
            for rel in self.relationships:
                if rel["entity_id"] == entity and rel["class_id"] == class_id:
                    return FakeResult([{"confidence": rel["props"].get("confidence")}])
            return FakeResult([])
        if "RETURN o.id AS id, r.confidence AS confidence" in query:
            entity = params.get("entity_id")
            records = []
            for rel in self.relationships:
                if rel["entity_id"] == entity:
                    records.append(
                        {
                            "id": rel["class_id"],
                            "confidence": rel["props"].get("confidence"),
                        }
                    )
            return FakeResult(records)
        if "RETURN o.id AS id" in query:
            entity = params.get("entity_id")
            records = []
            for rel in self.relationships:
                if rel["entity_id"] == entity:
                    records.append({"id": rel["class_id"]})
            return FakeResult(records)
        return FakeResult([])

    def create_relationship(
        self, entity_id: str, class_id: str, rel_type: str, props: Dict[str, Any]
    ) -> None:
        self.relationships.append(
            {
                "entity_id": entity_id,
                "class_id": class_id,
                "rel_type": rel_type,
                "props": props,
            }
        )


@pytest.fixture()
def crosswalk_yaml(tmp_path):
    path = tmp_path / "crosswalk.yaml"
    payload = {
        "tasks": {
            "task:foo": {
                "primary": "ONVOC_CHILD_A",
                "labels": ["Child A"],
            }
        }
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


@pytest.fixture()
def tree_yaml(tmp_path):
    payload = {
        "version": "0.1",
        "tree": [
            {
                "id": "ONVOC_ROOT",
                "label": "Root",
                "level": 1,
                "children": [
                    {"id": "ONVOC_CHILD_A", "label": "Child A", "level": 2},
                    {"id": "ONVOC_CHILD_B", "label": "Child B", "level": 2},
                ],
            }
        ],
        "constraints": {
            "cannot_link": [
                {"ids": ["ONVOC_CHILD_A", "ONVOC_CHILD_B"], "reason": "siblings"}
            ]
        },
    }
    path = tmp_path / "tree.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_linker_respects_cannot_link_constraints(crosswalk_yaml, tree_yaml):
    db = FakeDB(
        [
            {"id": "ONVOC_CHILD_A", "name": "Child A", "alt_labels": []},
            {"id": "ONVOC_CHILD_B", "name": "Child B", "alt_labels": []},
        ]
    )
    linker = OnvocLinker(
        db,
        crosswalk_path=crosswalk_yaml,
        tree_path=tree_yaml,
    )
    assert linker.available

    created = linker.link_task_analysis(
        "task-node-1",
        names=["Child B"],
        canonical_ids=["task:foo"],
        concept_ids=[],
    )

    assert created == 1
    assert len(db.relationships) == 1
    assert db.relationships[0]["class_id"] == "ONVOC_CHILD_A"
    assert db.relationships[0]["props"]["method"] == "crosswalk"
