from __future__ import annotations

import os
from pathlib import Path
import textwrap

from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.main_enhanced import app, jobs_db


def test_coding_workflow_plan_patch_and_tests(tmp_path):
    previous_mode = os.environ.get("CODING_AGENT_MODE")
    os.environ["CODING_AGENT_MODE"] = "1"
    client = TestClient(app)

    response = client.post(
        "/run",
        json={
            "prompt": "open the main orchestrator file and show first lines",
            "pipeline": "chat",
        },
    )
    assert response.status_code == 200
    data = response.json()
    job_id = data["job_id"]
    assert "plan" in data
    assert data["plan"]["intent"] in {"read", "edit", "mixed", "search"}

    job = jobs_db[job_id]
    coding_meta = job.metadata.get("coding")
    assert coding_meta is not None
    assert "plan" in coding_meta

    file_name = f"tmp_coding_agent_test_{job_id}.txt"
    patch = textwrap.dedent(
        f"""\
        diff --git a/{file_name} b/{file_name}
        new file mode 100644
        index 0000000..4aa4a4b
        --- /dev/null
        +++ b/{file_name}
        @@
        +coding agent smoke test
        """
    )

    propose = client.post(
        f"/jobs/{job_id}/propose_patch",
        json={"patch": patch, "description": "add temporary file"},
    )
    assert propose.status_code == 200

    apply_resp = client.post(f"/jobs/{job_id}/apply_patch")
    assert apply_resp.status_code == 200
    assert apply_resp.json().get("applied") is True
    assert Path(file_name).exists()

    test_resp = client.post(
        f"/jobs/{job_id}/run_tests",
        json={"targets": ["tests/unit/orchestrator/test_nl2tool_profile.py"]},
    )
    assert test_resp.status_code == 200
    assert test_resp.json()["returncode"] == 0

    final_job = client.get(f"/jobs/{job_id}").json()
    assert final_job["status"] == "completed"

    # Cleanup
    Path(file_name).unlink(missing_ok=True)
    if previous_mode is not None:
        os.environ["CODING_AGENT_MODE"] = previous_mode
    else:
        os.environ.pop("CODING_AGENT_MODE", None)
