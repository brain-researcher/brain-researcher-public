import importlib
import sys

import pytest


class _StubOrchestrator:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def process_query(
        self,
        natural_language_query,
        user_context=None,
        return_intermediate=False,
    ):
        self.calls.append(
            {
                "natural_language_query": natural_language_query,
                "user_context": user_context,
                "return_intermediate": return_intermediate,
            }
        )
        return self._response


@pytest.fixture()
def app_module(monkeypatch):
    from brain_researcher.services.neurokg.graph import neo4j_utils

    monkeypatch.setattr(neo4j_utils, "require_neo4j_db", lambda **_kwargs: object())
    sys.modules.pop("brain_researcher.services.neurokg.app", None)
    return importlib.import_module("brain_researcher.services.neurokg.app")


def test_nl_query_route_success(monkeypatch, app_module):
    from brain_researcher.services.neurokg import nl_query as nl_query_module

    orchestrator = _StubOrchestrator(
        {
            "query_id": "nlq_1",
            "success": True,
            "result": {"summary": "ok", "data": []},
        }
    )
    factory_calls = []

    def _factory(**kwargs):
        factory_calls.append(kwargs)
        return orchestrator

    monkeypatch.setattr(nl_query_module, "create_nl_query_orchestrator", _factory)

    client = app_module.app.test_client()
    resp = client.post(
        "/api/nl-query",
        json={
            "query": "find datasets for n-back",
            "user_context": {"tenant_id": "default"},
            "return_intermediate": True,
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True

    assert len(factory_calls) == 1
    assert factory_calls[0]["neo4j_db"] is app_module.neo4j_db

    assert len(orchestrator.calls) == 1
    call = orchestrator.calls[0]
    assert call["natural_language_query"] == "find datasets for n-back"
    assert call["user_context"] == {"tenant_id": "default"}
    assert call["return_intermediate"] is True


def test_nl_query_route_not_supported_returns_501(monkeypatch, app_module):
    from brain_researcher.services.neurokg import nl_query as nl_query_module

    orchestrator = _StubOrchestrator(
        {
            "query_id": "nlq_2",
            "success": False,
            "error_code": "not_supported",
            "error": "query_type=sparql is not supported",
            "not_supported": {
                "query_type": "sparql",
                "supported_query_types": ["cypher"],
            },
        }
    )

    monkeypatch.setattr(
        nl_query_module,
        "create_nl_query_orchestrator",
        lambda **_kwargs: orchestrator,
    )

    client = app_module.app.test_client()
    resp = client.post("/api/nl-query", json={"query": "run sparql query_type=sparql"})

    assert resp.status_code == 501
    body = resp.get_json()
    assert body["success"] is False
    assert body["error_code"] == "not_supported"


def test_nl_query_route_missing_query_returns_400(app_module):
    client = app_module.app.test_client()
    resp = client.post("/api/nl-query", json={"user_context": {"k": "v"}})

    assert resp.status_code == 400
    body = resp.get_json()
    assert "query" in body["error"]


def test_nl_query_route_invalid_return_intermediate_returns_400(app_module):
    client = app_module.app.test_client()
    resp = client.post(
        "/api/nl-query",
        json={"query": "find x", "return_intermediate": "true"},
    )

    assert resp.status_code == 400
    body = resp.get_json()
    assert "return_intermediate" in body["error"]
