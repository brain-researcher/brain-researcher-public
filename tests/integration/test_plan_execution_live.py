"""Optional live integration test for end-to-end plan submission."""

from __future__ import annotations

import os
import time

import pytest
import requests


@pytest.mark.slow
def test_live_plan_submission_roundtrip():
    """Submit a real run via HTTP and verify the run is visible to status API.

    This test is opt-in because it depends on a live deployment.
    Enable with:
      BR_ENABLE_LIVE_PLAN_TESTS=1
      BR_LIVE_BASE_URL=https://brain-researcher.com
      BR_LIVE_BEARER_TOKEN=<token>
    """

    if os.getenv("BR_ENABLE_LIVE_PLAN_TESTS", "0") != "1":
        pytest.skip("Live plan tests disabled (set BR_ENABLE_LIVE_PLAN_TESTS=1)")

    base = os.getenv("BR_LIVE_BASE_URL", "").rstrip("/")
    token = os.getenv("BR_LIVE_BEARER_TOKEN", "")
    if not base or not token:
        pytest.skip("Missing BR_LIVE_BASE_URL or BR_LIVE_BEARER_TOKEN")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    plan = {
        "type": "dataset_analysis",
        "intent": "Live integration smoke test",
        "pipeline": "preprocessing",
        "dataset_id": "ds:manual:abide",
        "template_id": "dynamic_workflow/workflow_preprocessing_qc",
        "parameters": {
            "dataset_id": "ds:manual:abide",
            "analysis_id": "dynamic_workflow",
            "pipeline_id": "workflow_preprocessing_qc",
        },
        "steps": [
            {
                "tool": "workflow_preprocessing_qc",
                "args": {
                    "dataset_id": "ds:manual:abide",
                    "analysis_id": "dynamic_workflow",
                    "pipeline_id": "workflow_preprocessing_qc",
                },
            }
        ],
    }

    create = requests.post(
        f"{base}/api/runs",
        headers=headers,
        json={"plan": plan},
        timeout=30,
    )
    create.raise_for_status()
    payload = create.json()
    run_id = payload.get("run_id") or payload.get("job_id")
    assert isinstance(run_id, str) and run_id

    status_payload = None
    for _ in range(6):
        status_resp = requests.get(f"{base}/api/runs/{run_id}", headers=headers, timeout=20)
        if status_resp.status_code == 200:
            status_payload = status_resp.json()
            break
        time.sleep(2)

    assert isinstance(status_payload, dict)
    assert status_payload.get("run_id") == run_id
    assert status_payload.get("status") in {
        "queued",
        "pending",
        "running",
        "completed",
        "failed",
        "cancelling",
        "cancelled",
        "timeout",
    }

