"""Integration test for branch fallback execution in JobWorker."""

from __future__ import annotations

import asyncio
import json

import pytest

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

    async def get(self, job_id: str):  # pragma: no cover
        return self.current_job


class StubToolExecutor:
    def __init__(self):
        self.calls = []

    def run_tool(self, tool_name: str, **_):
        self.calls.append(tool_name)
        if tool_name == "tool.fail":
            return {"status": "error", "error": "forced failure"}
        return {"status": "success", "data": {}}


@pytest.mark.asyncio
async def test_branch_fallback_first_succeeds(monkeypatch):
    monkeypatch.setenv("BR_BRANCH_EXECUTION", "1")

    job_id = "job_branch_fallback"
    main_enhanced.job_updates[job_id] = None

    plan_payload = {
        "plan_id": "plan-branch",
        "dag": {
            "steps": [
                {
                    "id": "step-branch-001",
                    "tool": "tool.fail",
                    "params": {},
                    "metadata": {
                        "runtime_kind": "python",
                        "branch_group_id": "bg:test",
                        "branch_rank": 0,
                    },
                },
                {
                    "id": "step-branch-002",
                    "tool": "tool.success",
                    "params": {},
                    "metadata": {
                        "runtime_kind": "python",
                        "branch_group_id": "bg:test",
                        "branch_rank": 1,
                    },
                },
            ],
            "artifacts": [],
        },
    }

    job_record = JobRecord(
        job_id=job_id,
        kind="plan_execution",
        payload_json=json.dumps(
            {
                "type": "plan_execution",
                "prompt": "branch fallback test",
                "metadata": {"pipeline": "test"},
                "plan": plan_payload,
            }
        ),
        state=JobState.QUEUED,
    )

    stub_store = StubJobStore()
    stub_store.current_job = job_record
    previous_store = getattr(main_enhanced.app.state, "job_store", None)
    main_enhanced.app.state.job_store = stub_store
    tool_executor = StubToolExecutor()
    worker = JobWorker(stub_store, worker_id="branch-worker", plan_tool_executor=tool_executor)

    try:
        await worker._execute_plan_job(job_record, json.loads(job_record.payload_json))
        await asyncio.sleep(0)

        states = [state for _, state, _ in stub_store.updates if state is not None]
        assert JobState.SUCCEEDED in states, f"Job states: {stub_store.updates}"
        assert tool_executor.calls == ["tool.fail", "tool.success"]

        payload = json.loads(job_record.payload_json)
        plan_payload = payload.get("plan") or {}
        planner_state = plan_payload.get("planner_state") or {}
        assert planner_state.get("selected_branch_id") == "br:tool.success"
        assert plan_payload.get("planner_events"), "Expected planner_events to be populated"

        metadata = payload.get("metadata") or {}
        assert metadata.get("branch_events"), "Expected branch_events to be persisted on payload metadata"

        run_card = await main_enhanced.EnhancedJobManager.generate_run_card(job_id)
        assert run_card is not None
        assert run_card.execution.get("branch_events"), "Expected branch_events on run card execution"
        assert run_card.execution.get("planner_state"), "Expected planner_state on run card execution"
    finally:
        main_enhanced.job_updates.pop(job_id, None)
        main_enhanced.app.state.job_store = previous_store


@pytest.mark.asyncio
async def test_run_card_hydration_without_jobs_db(monkeypatch):
    job_id = "job_branch_hydrate"
    main_enhanced.jobs_db.pop(job_id, None)

    branch_events = [
        {
            "event_type": "branch_started",
            "branch_step_id": "step-branch-001",
            "branch_rank": 0,
            "branch_group_id": "bg:test",
            "ts": "2024-01-01T00:00:00Z",
        }
    ]
    planner_state = {"selected_branch_id": "br:tool.success"}
    planner_events = [
        {"event_type": "branch_started", "ts": 1704067200.0, "payload": {"branch_id": "br:tool.fail"}}
    ]

    plan_steps = [
        {
            "id": "step-branch-001",
            "tool": "tool.fail",
            "params": {},
            "produces": {"output": "fail"},
            "metadata": {
                "runtime_kind": "python",
                "branch_group_id": "bg:test",
                "branch_rank": 0,
            },
        },
        {
            "id": "step-branch-002",
            "tool": "tool.success",
            "params": {},
            "produces": {"output": "success"},
            "metadata": {
                "runtime_kind": "python",
                "branch_group_id": "bg:test",
                "branch_rank": 1,
            },
        },
        {
            "id": "step-branch-003",
            "tool": "tool.skip",
            "params": {},
            "produces": {"output": "skip"},
            "metadata": {
                "runtime_kind": "python",
                "branch_group_id": "bg:test",
                "branch_rank": 2,
            },
        },
    ]

    result_steps = [
        {"step_id": "step-branch-001", "tool": "tool.fail", "status": "error", "error": "forced"},
        {"step_id": "step-branch-002", "tool": "tool.success", "status": "success"},
        {"step_id": "step-branch-003", "tool": "tool.skip", "status": "skipped"},
    ]

    job_record = JobRecord(
        job_id=job_id,
        kind="plan_execution",
        payload_json=json.dumps(
            {
                "type": "plan_execution",
                "prompt": "branch hydrate test",
                "metadata": {
                    "pipeline": "test",
                    "branch_events": branch_events,
                    "planner_state": planner_state,
                    "planner_events": planner_events,
                },
                "plan": {"plan_id": "plan-hydrate", "dag": {"steps": plan_steps, "artifacts": []}},
                "result": {"state": "succeeded", "steps": result_steps},
            }
        ),
        state=JobState.SUCCEEDED,
    )

    stub_store = StubJobStore()
    stub_store.current_job = job_record
    previous_store = getattr(main_enhanced.app.state, "job_store", None)
    main_enhanced.app.state.job_store = stub_store

    try:
        run_card = await main_enhanced.EnhancedJobManager.generate_run_card(job_id)
        assert run_card is not None
        execution = run_card.execution
        assert execution.get("branch_events") == branch_events
        assert execution.get("planner_state", {}).get("selected_branch_id") == "br:tool.success"
        assert execution.get("planner_events")
        steps = execution.get("steps") or []
        tools = {step.get("tool") for step in steps if isinstance(step, dict)}
        statuses = {step.get("status") for step in steps if isinstance(step, dict)}
        assert {"tool.fail", "tool.success", "tool.skip"} <= tools
        assert {"error", "success", "skipped"} <= statuses
    finally:
        main_enhanced.app.state.job_store = previous_store


@pytest.mark.asyncio
async def test_branch_event_cap_dedupe(monkeypatch):
    monkeypatch.setenv("BR_BRANCH_EXECUTION", "1")

    job_id = "job_branch_dedupe"
    main_enhanced.job_updates[job_id] = None

    unique_events = [
        {
            "event_type": "branch_started",
            "branch_step_id": f"step-{i:03d}",
            "branch_rank": i,
            "ts": f"2024-01-01T00:00:{i:02d}Z",
        }
        for i in range(205)
    ]
    duplicate_events = [unique_events[0] for _ in range(5)]

    plan_payload = {
        "plan_id": "plan-dedupe",
        "dag": {
            "steps": [
                {
                    "id": "step-branch-001",
                    "tool": "tool.fail",
                    "params": {},
                    "metadata": {
                        "runtime_kind": "python",
                        "branch_group_id": "bg:test",
                        "branch_rank": 0,
                    },
                },
                {
                    "id": "step-branch-002",
                    "tool": "tool.success",
                    "params": {},
                    "metadata": {
                        "runtime_kind": "python",
                        "branch_group_id": "bg:test",
                        "branch_rank": 1,
                    },
                },
            ],
            "artifacts": [],
        },
    }

    job_record = JobRecord(
        job_id=job_id,
        kind="plan_execution",
        payload_json=json.dumps(
            {
                "type": "plan_execution",
                "prompt": "branch dedupe test",
                "metadata": {"branch_events": unique_events + duplicate_events},
                "plan": plan_payload,
            }
        ),
        state=JobState.QUEUED,
    )

    stub_store = StubJobStore()
    stub_store.current_job = job_record
    previous_store = getattr(main_enhanced.app.state, "job_store", None)
    main_enhanced.app.state.job_store = stub_store

    tool_executor = StubToolExecutor()
    worker = JobWorker(stub_store, worker_id="branch-worker", plan_tool_executor=tool_executor)

    try:
        await worker._execute_plan_job(job_record, json.loads(job_record.payload_json))
        await asyncio.sleep(0)

        payload = json.loads(job_record.payload_json)
        metadata = payload.get("metadata") or {}
        branch_events = metadata.get("branch_events") or []
        assert len(branch_events) <= 200

        keys = set()
        for event in branch_events:
            key = (
                event.get("event_type"),
                event.get("branch_step_id"),
                event.get("branch_rank"),
                event.get("ts"),
            )
            keys.add(key)
        assert len(keys) == len(branch_events)
    finally:
        main_enhanced.job_updates.pop(job_id, None)
        main_enhanced.app.state.job_store = previous_store
