"""Unit tests covering the run-plan submission path."""

import json

import pytest

from brain_researcher.services.agent.web_service import app, _PLAN_CACHE
from tests.unit.agent.job_store_test_utils import patched_job_store


@pytest.fixture(autouse=True)
def _isolate_run_plan_submission_tests(monkeypatch):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.delenv("BR_USE_TOOL_RETRIEVER", raising=False)
    monkeypatch.setattr(ws, "_get_contract_tool_retriever", lambda: None)
    monkeypatch.setattr(ws, "_env_tool_allowlist", lambda: None)


def _create_plan(client, modality="fmri"):
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": [modality],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    }
    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_run_plan_returns_202_with_urls(monkeypatch):
    client = app.test_client()
    plan = _create_plan(client)

    run_request = {
        "plan_id": plan["plan_id"],
        "version": plan["version"],
        "por_token": plan["por_token"],
    }

    with patched_job_store(monkeypatch) as store:
        response = client.post("/agent/run_plan", json=run_request)

    assert response.status_code == 202
    body = response.get_json()
    assert body["plan_id"] == plan["plan_id"]
    stream_suffix = f"/jobs/{body['job_id']}/stream"
    assert body["stream_url"].endswith(stream_suffix)
    assert body["status_url"].endswith(body["job_id"])
    assert store.enqueued_jobs and store.enqueued_jobs[0].job_id == body["job_id"]

    payload = json.loads(store.enqueued_jobs[0].payload_json)
    assert "plan" in payload
    assert payload["plan"]["plan_id"] == plan["plan_id"]
    assert payload["plan"]["dag"]["steps"], "Plan DAG should include steps"
    assert payload["plan"]["handoff"]["plan_id"] == plan["plan_id"]
    assert payload["plan"]["handoff"]["pipeline"] == "connectivity"


def test_missing_tool_validation_returns_422(monkeypatch):
    client = app.test_client()

    monkeypatch.setenv("BR_STRICT_PLAN_TOOL_VALIDATION", "true")

    class EmptyRegistry:
        def get_tool(self, tool_id):
            return None

        def list_tools(self):
            return []

    class DummyAgent:
        def __init__(self):
            self.tool_registry = EmptyRegistry()

    monkeypatch.setattr(
        "brain_researcher.services.agent.web_service.get_agent",
        lambda: DummyAgent(),
    )

    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    }

    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 422
    data = response.get_json()
    assert data["error"] in {"tools_not_available", "tool_not_available"}
    assert data["missing_tools"]


def test_plan_cache_popped_after_submit(monkeypatch):
    client = app.test_client()
    plan = _create_plan(client)
    plan_id = plan["plan_id"]
    assert plan_id in _PLAN_CACHE

    run_request = {
        "plan_id": plan_id,
        "version": plan["version"],
        "por_token": plan["por_token"],
    }

    with patched_job_store(monkeypatch):
        response = client.post("/agent/run_plan", json=run_request)

    assert response.status_code == 202
    assert plan_id not in _PLAN_CACHE


def test_run_plan_accepts_inline_plan_payload(monkeypatch):
    client = app.test_client()
    plan = _create_plan(client)
    plan_id = plan["plan_id"]
    _PLAN_CACHE.pop(plan_id, None)

    run_request = {
        "plan_id": plan_id,
        "version": plan["version"],
        "por_token": plan["por_token"],
        "plan": plan,
    }

    with patched_job_store(monkeypatch) as store:
        response = client.post("/agent/run_plan", json=run_request)

    assert response.status_code == 202
    assert store.enqueued_jobs
    payload = json.loads(store.enqueued_jobs[0].payload_json)
    assert payload["plan"]["plan_id"] == plan_id
    assert payload["plan"]["dag"]["steps"]
    assert plan_id not in _PLAN_CACHE


def test_run_plan_soft_validation_warns(monkeypatch):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.setattr(ws, "_plan_surface_allowset", lambda allowlist_mode: None)
    client = app.test_client()
    plan = _create_plan(client)
    plan_id = plan['plan_id']

    cached_plan = _PLAN_CACHE[plan_id]
    cached_plan["dag"]["steps"][0]["tool"] = "ghost_tool"
    cached_plan["chosen_tool"] = "ghost_tool"

    run_request = {
        'plan_id': plan_id,
        'version': plan['version'],
        'por_token': plan['por_token'],
    }

    with patched_job_store(monkeypatch) as store:
        response = client.post('/agent/run_plan', json=run_request)

    assert response.status_code == 202
    assert store.enqueued_jobs
    payload = json.loads(store.enqueued_jobs[0].payload_json)
    assert payload["plan"]["chosen_tool"] == "ghost_tool"
    assert payload["snapshot"]["chosen_tool"] == "ghost_tool"


def test_run_plan_missing_plan_returns_404():
    client = app.test_client()
    response = client.post(
        '/agent/run_plan',
        json={'plan_id': 'does-not-exist', 'version': 1, 'por_token': 'tok'},
    )

    assert response.status_code == 404
    assert response.get_json()['error'] == 'plan_not_found'


def test_run_plan_enqueue_failure_returns_500(monkeypatch):
    client = app.test_client()
    plan = _create_plan(client)

    async def failing_enqueue(job):  # pragma: no cover
        raise RuntimeError('job-store-down')

    with patched_job_store(monkeypatch) as store:
        store.enqueue = failing_enqueue
        response = client.post(
            '/agent/run_plan',
            json={
                'plan_id': plan['plan_id'],
                'version': plan['version'],
                'por_token': plan['por_token'],
            },
        )

    assert response.status_code == 500
    assert response.get_json()['error'] == 'job_submission_failed'
