"""Tests for provenance.json phase/mask_reason enrichment."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import JobWorker


@pytest.mark.unit
def test_update_provenance_phases_coerces_mask_reasons(tmp_path: Path) -> None:
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps({"steps": []}), encoding="utf-8")

    worker = JobWorker(
        job_store=MemoryJobStore(total_gpu_slots=1),
        worker_id="worker-test",
        tool_executor=MagicMock(),
        plan_tool_executor=MagicMock(),
    )

    worker._update_provenance_phases(
        str(provenance_path),
        workflow_result={},
        mask_reasons=[{"code": "BUDGET_EXCEEDED"}],
    )

    data = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert data["mask_reasons"][0]["schema_version"] == "violation-v1"
    assert data["mask_reasons"][0]["code"] == "BUDGET_EXCEEDED"
    assert data["mask_reasons"][0]["message"] == "BUDGET_EXCEEDED"
