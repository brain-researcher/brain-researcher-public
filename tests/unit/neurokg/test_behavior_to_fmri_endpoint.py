import importlib
import sys

import pytest


@pytest.fixture()
def app_module(monkeypatch):
    from brain_researcher.services.neurokg.graph import neo4j_utils

    monkeypatch.setattr(neo4j_utils, "require_neo4j_db", lambda **_kwargs: object())
    sys.modules.pop("brain_researcher.services.neurokg.app", None)
    return importlib.import_module("brain_researcher.services.neurokg.app")


def test_behavior_to_fmri_endpoint_returns_payload(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "behavior_to_fmri_retrieval",
        lambda **_kwargs: {
            "seed": {"id": "psych101:task:go-no-go"},
            "seed_tasks": [{"task_id": "psych101:task:go-no-go"}],
            "items": [{"item_id": "ta:go-no-go", "dataset_ids": ["ds:go-no-go"]}],
            "summary": {"item_count": 1},
        },
    )

    client = app_module.app.test_client()
    response = client.post(
        "/api/behavior_to_fmri_retrieval",
        json={"seed_id": "psych101:task:go-no-go"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["seed"]["id"] == "psych101:task:go-no-go"
    assert payload["summary"]["item_count"] == 1


def test_behavior_to_fmri_endpoint_rejects_unsupported_seed(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module,
        "behavior_to_fmri_retrieval",
        lambda **_kwargs: {"error": "unsupported_seed_type"},
    )

    client = app_module.app.test_client()
    response = client.post(
        "/api/behavior_to_fmri_retrieval",
        json={"seed_id": "dataset:demo"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "unsupported_seed_type"
