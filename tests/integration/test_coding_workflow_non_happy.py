from __future__ import annotations

from fastapi.testclient import TestClient


def _force_coding_mode(monkeypatch):
    monkeypatch.setenv("BR_PLANNER_MODE", "disabled")


def _create_job(client: TestClient) -> str:
    response = client.post(
        "/run",
        json={
            "prompt": "open the main orchestrator file and show first lines",
            "pipeline": "chat",
        },
    )
    assert response.status_code == 200
    return response.json()["job_id"]


def test_apply_patch_rejects_invalid_patch(monkeypatch, coding_workflow_test_routes):
    _force_coding_mode(monkeypatch)
    client = TestClient(coding_workflow_test_routes)
    job_id = _create_job(client)

    apply_resp = client.post(
        f"/jobs/{job_id}/apply_patch",
        json={"patch": "not a patch", "description": "invalid"},
    )

    assert apply_resp.status_code == 400
    detail = apply_resp.json().get("detail", "")
    assert "Patch" in detail or "patch" in detail


def test_run_tests_failure_marks_job_failed(monkeypatch, coding_workflow_test_routes):
    _force_coding_mode(monkeypatch)
    client = TestClient(coding_workflow_test_routes)
    job_id = _create_job(client)

    test_resp = client.post(
        f"/jobs/{job_id}/run_tests",
        json={"targets": ["tests/does_not_exist_test.py"]},
    )

    assert test_resp.status_code == 200
    assert test_resp.json().get("returncode") != 0

    final_job = client.get(f"/jobs/{job_id}").json()
    assert final_job["status"] == "failed"
