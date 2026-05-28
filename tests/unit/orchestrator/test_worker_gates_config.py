"""Tests for JobWorker gate engine config loading."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
from brain_researcher.services.orchestrator.worker import JobWorker


@pytest.mark.unit
def test_worker_loads_gate_engine_from_env_path(monkeypatch, tmp_path: Path) -> None:
    gate_path = tmp_path / "gates.yaml"
    gate_path.write_text(
        "\n".join(
            [
                "rules:",
                "  - rule_id: TEST_RULE",
                '    description: "test rule"',
                "    applies_to: step",
                "    stage: postcheck",
                "    metric: qc.test.value",
                "    comparator: gt",
                "    threshold: 0",
                '    message: "test message"',
                "    severity: warn",
                "    action: warn",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BR_GATES_CONFIG_PATH", str(gate_path))

    job_store = MemoryJobStore(total_gpu_slots=1)
    worker = JobWorker(
        job_store=job_store,
        worker_id="worker-test",
        tool_executor=MagicMock(),
        plan_tool_executor=MagicMock(),
    )

    assert worker.gate_engine is not None
    assert len(worker.gate_engine.rules) == 1
    assert worker.gate_engine.rules[0].rule_id == "TEST_RULE"
