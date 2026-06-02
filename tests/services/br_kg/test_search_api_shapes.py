import importlib
import sys
from dataclasses import dataclass

import pytest


@dataclass
class DummyResult:
    node_id: str = "n1"
    node_type: str = "Concept"
    score: float = 1.0
    matched_fields: list = None
    properties: dict = None
    highlight: dict = None

    def __post_init__(self):
        if self.matched_fields is None:
            self.matched_fields = ["name"]
        if self.properties is None:
            self.properties = {"name": "working memory"}
        if self.highlight is None:
            self.highlight = {"name": "<mark>working memory</mark>"}


class DummySearchEngine:
    def __init__(self, db):
        self.db = db

    def search(self, query, node_types=None, limit=100):
        return [DummyResult()]


@pytest.fixture
def search_client(monkeypatch):
    from brain_researcher.services.br_kg.graph import neo4j_utils

    monkeypatch.setattr(neo4j_utils, "require_neo4j_db", lambda **_kwargs: object())

    sys.modules.pop("brain_researcher.services.br_kg.app", None)
    app_module = importlib.import_module("brain_researcher.services.br_kg.app")

    monkeypatch.setattr(app_module, "SearchEngine", DummySearchEngine, raising=True)

    from brain_researcher.services.br_kg.db import bootstrap as seed_neo4j

    monkeypatch.setattr(seed_neo4j, "get_db", lambda: object())

    from brain_researcher.core.literature import gfs_store

    monkeypatch.setattr(
        gfs_store,
        "search_gfs",
        lambda *args, **kwargs: {
            "status": "ok",
            "store": "dummy-store",
            "model": "dummy-model",
            "hits": [{"title": "paper", "text": "working memory"}],
        },
    )

    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_search_envelope_shape(search_client):
    response = search_client.post(
        "/api/search",
        json={"query": "working memory", "rerank": "gfs"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)
    assert "results" in data
    assert isinstance(data["results"], list)
    assert "rerank_gfs" in data


def test_search_legacy_list_shape(search_client):
    response = search_client.post(
        "/api/search?format=list",
        json={"query": "working memory", "rerank": "gfs"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
