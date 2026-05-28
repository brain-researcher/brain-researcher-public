"""End-to-end tests for python tool pipelines executed via JobWorker."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
import nibabel as nib
import numpy as np

from brain_researcher.services.agent.tool_executor import ToolExecutor
from brain_researcher.services.tools.fetch_atlas_tool import FetchAtlasTool
from brain_researcher.services.tools.extract_timeseries_tool import (
    ExtractTimeseriesTool,
)
from brain_researcher.services.tools.nilearn_connectivity_matrix_tool import (
    NilearnConnectivityMatrixTool,
)
import brain_researcher.services.tools.fetch_atlas_tool as fetch_module
import brain_researcher.services.tools.extract_timeseries_tool as extract_module
import brain_researcher.services.tools.nilearn_connectivity_matrix_tool as connect_module
from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.orchestrator import main_enhanced
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.worker import JobWorker


class StubJobStore:
    def __init__(self):
        self.updates = []
        self.current_job = None

    async def update_state(self, job_id: str, new_state=None, **fields):
        self.updates.append((job_id, new_state, fields))
        return True

    async def cancel(self, job_id: str, reason: str | None = None):
        self.updates.append((job_id, JobState.CANCELLED, {"reason": reason}))
        return True

    async def get(self, job_id: str):  # pragma: no cover - minimal compatibility
        return self.current_job


@pytest.fixture
def real_tool_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_DEMO_ARTIFACT_DIR", str(tmp_path / "br_demo"))
    for module in (fetch_module, extract_module, connect_module):
        monkeypatch.setattr(module, "_OUTPUT_ROOT", tmp_path / "br_demo")
    registry = ToolRegistry(auto_discover=False, use_capabilities=False)
    registry.register_tool(FetchAtlasTool())
    registry.register_tool(ExtractTimeseriesTool())
    registry.register_tool(NilearnConnectivityMatrixTool())
    return ToolExecutor(tool_registry=registry, enable_caching=False, safe_mode=False)


@pytest.mark.asyncio
async def test_job_worker_executes_python_pipeline(real_tool_executor, tmp_path, monkeypatch):
    """Full pipeline: fetch_atlas -> extract_timeseries -> connectivity matrix."""
    job_id = "job-python-e2e"
    main_enhanced.job_updates[job_id] = None

    bold_img = tmp_path / "bold.nii.gz"
    data = np.random.rand(4, 4, 4, 20).astype("float32")
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(img, bold_img)

    plan_payload = {
        "plan_id": "plan-python",
        "dag": {
            "steps": [
                {
                    "id": "001-fetch-atlas",
                    "tool": "fetch_atlas",
                    "params": {"atlas_name": "synthetic"},
                    "metadata": {"runtime_kind": "python"},
                },
                {
                    "id": "002-extract-timeseries",
                    "tool": "extract_timeseries",
                    "params": {"img": str(bold_img)},
                    "metadata": {
                        "runtime_kind": "python",
                        "consumes": {"atlas": "atlas_path"},
                    },
                },
                {
                    "id": "003-connectivity",
                    "tool": "nilearn_connectivity_matrix",
                    "params": {},
                    "metadata": {
                        "runtime_kind": "python",
                        "consumes": {"timeseries": "timeseries"},
                    },
                },
            ],
            "artifacts": [],
        },
    }

    job_record = JobRecord(
        job_id=job_id,
        kind="plan_execution",
        payload_json=json.dumps({"type": "plan_execution", "plan": plan_payload}),
        state=JobState.QUEUED,
    )

    stub_store = StubJobStore()
    stub_store.current_job = job_record
    worker = JobWorker(stub_store, worker_id="python-worker", plan_tool_executor=real_tool_executor)

    await worker._execute_plan_job(job_record, json.loads(job_record.payload_json))
    await asyncio.sleep(0)

    states = [state for _, state, _ in stub_store.updates if state is not None]
    assert JobState.SUCCEEDED in states, f"Job states: {stub_store.updates}"

    assert job_record.run_dir
    run_dir = Path(job_record.run_dir)
    matrix_file = run_dir / "outputs" / "connectivity_matrix.json"
    assert matrix_file.exists()

    # Run-scoped outputs now land under the plan run directory, not the demo root.
    artifact_dir = Path(os.environ["BR_DEMO_ARTIFACT_DIR"])
    assert not (artifact_dir / "connectivity_matrix.json").exists()

    main_enhanced.job_updates.pop(job_id, None)
