from __future__ import annotations

import pytest

from brain_researcher.services.br_kg.traversal import multi_hop_queries as mhq


class _FakeSession:
    def __init__(self, captured: dict[str, object]):
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        self._captured["query"] = query
        self._captured["params"] = params
        return []


class _FakeDB:
    def __init__(self, captured: dict[str, object]):
        self._captured = captured

    def session(self):
        return _FakeSession(self._captured)


class _FakeNeo4jQuery:
    def __init__(self, text: str, timeout: float | None = None):
        self.text = text
        self.timeout = timeout


def test_execute_traversal_query_applies_neo4j_timeout(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(mhq, "Neo4jQuery", _FakeNeo4jQuery)

    engine = mhq.MultiHopQueryEngine(_FakeDB(captured))
    constraints = mhq.TraversalConstraints(max_depth=2, max_results=5, query_timeout_ms=2500)

    result = engine._execute_traversal_query(
        "RETURN 1 AS x",
        start_node_id="concept:wm",
        target_node_id=None,
        constraints=constraints,
    )

    assert result == []
    assert isinstance(captured["query"], _FakeNeo4jQuery)
    assert captured["query"].timeout == pytest.approx(2.5)
    assert captured["params"]["start_id"] == "concept:wm"


def test_execute_traversal_query_without_timeout_uses_plain_query(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(mhq, "Neo4jQuery", None)

    engine = mhq.MultiHopQueryEngine(_FakeDB(captured))
    constraints = mhq.TraversalConstraints(max_depth=1, max_results=3, query_timeout_ms=None)

    result = engine._execute_traversal_query(
        "RETURN 1 AS x",
        start_node_id="concept:wm",
        target_node_id=None,
        constraints=constraints,
    )

    assert result == []
    assert captured["query"] == "RETURN 1 AS x"
