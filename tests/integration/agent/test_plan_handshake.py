"""Integration test covering the /agent/plan -> /agent/run_plan handshake."""

from brain_researcher.services.agent.web_service import app


def _collect_sse_response(response):
    return b"".join(response.response).decode()


def test_plan_then_run_handshake():
    client = app.test_client()

    plan_payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    }

    plan_response = client.post("/agent/plan", json=plan_payload)
    assert plan_response.status_code == 200
    plan_data = plan_response.get_json()

    run_payload = {
        "plan_id": plan_data["plan_id"],
        "version": plan_data["version"],
        "por_token": plan_data["por_token"],
    }

    run_response = client.post(
        "/agent/run_plan",
        json=run_payload,
        headers={"Accept": "text/event-stream"},
        buffered=True,
    )
    assert run_response.status_code == 200
    stream_text = _collect_sse_response(run_response)

    assert plan_data["plan_id"] in stream_text
    assert "event: plan_completed" in stream_text


def test_plan_then_run_handshake_eeg():
    client = app.test_client()

    plan_payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["eeg"],
        "inputs": {"raw_eeg": "sub-01_task-rest_eeg.fif", "montage_name": "standard_1020"},
    }

    plan_response = client.post("/agent/plan", json=plan_payload)
    assert plan_response.status_code == 200
    plan_data = plan_response.get_json()

    run_payload = {
        "plan_id": plan_data["plan_id"],
        "version": plan_data["version"],
        "por_token": plan_data["por_token"],
    }

    run_response = client.post(
        "/agent/run_plan",
        json=run_payload,
        headers={"Accept": "text/event-stream"},
        buffered=True,
    )
    assert run_response.status_code == 200
    stream_text = _collect_sse_response(run_response)

    assert "resolve_montage" in stream_text
    assert "event: plan_completed" in stream_text
