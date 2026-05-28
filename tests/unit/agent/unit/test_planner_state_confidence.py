import json
from pathlib import Path

import pytest

from brain_researcher.services.agent.planner_confidence import (
    compute_confidence_summary,
)
from brain_researcher.services.agent.planner_state import (
    PlannerEvent,
    PlannerEventLogger,
    PlannerEventType,
    replay_planner_events,
)
from brain_researcher.services.agent.planner_trace import build_planner_trace


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def test_planner_trace_replay_and_logging(tmp_path: Path):
    plan_payload = {
        "plan_id": "plan_test_001",
        "resolvable": True,
        "mode": "catalog",
        "dag": {"steps": [{"id": "001-main", "tool": "tool_a"}], "artifacts": []},
        "chosen_tool": "tool_a",
        "routing_diagnostics": {
            "candidate_count": 2,
            "selected_tool_rank": 1,
            "selected_tool_in_top_5": True,
        },
        "candidates": [
            {
                "tool_id": "tool_a",
                "tool_name": "Tool A",
                "final_score": 0.90,
                "preflight_passed": True,
                "historical_quality_score": 0.60,
                "latency_score": 0.70,
            },
            {
                "tool_id": "tool_b",
                "tool_name": "Tool B",
                "final_score": 0.80,
                "preflight_passed": True,
                "historical_quality_score": 0.50,
                "latency_score": 0.50,
            },
        ],
    }
    req_payload = {
        "pipeline": "dummy_pipeline",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {},
    }

    events, state = build_planner_trace(plan_payload, request_payload=req_payload)
    assert events[0].event_type == PlannerEventType.PLANNER_STATE_INIT
    assert state["selected_tool_ids"] == ["tool_a"]
    assert state["selected_branch_id"] == "br:tool_a"
    assert "hyp:tool_b" in state["rejected"]
    assert state["routing_diagnostics"]["selected_tool_rank"] == 1

    # Replay from event dicts should match
    state2 = replay_planner_events([e.to_dict() for e in events])
    assert state2 == state

    # Log to JSONL and validate event sequence is preserved
    logger = PlannerEventLogger(run_id="run_planner_test", base_path=str(tmp_path))
    logger.log_many(events)

    session_files = list((tmp_path / "sessions").glob("*.jsonl"))
    assert session_files, "expected JSONL session file to be created"
    rows = _load_jsonl(session_files[0])

    logged_event_types = [
        r.get("planner_event", {}).get("event_type")
        for r in rows
        if isinstance(r.get("planner_event"), dict)
    ]
    assert logged_event_types == [e.event_type.value for e in events]


def test_planner_event_logger_default_uses_shared_metadata_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    metadata_root = tmp_path / "artifacts" / "metadata"
    monkeypatch.setenv("BR_METADATA_DIR", str(metadata_root))

    event = PlannerEvent(
        event_type=PlannerEventType.PLANNER_STATE_INIT,
        payload={"reason": "test"},
        diff={"pending_add": ["hyp:test"]},
    )

    logger = PlannerEventLogger(run_id="run_planner_default_root_test")
    logger.log(event)

    session_files = list((metadata_root / "sessions").glob("*.jsonl"))
    assert session_files, (
        "expected default planner logger to write via shared metadata root"
    )


def test_confidence_summary_fields_present():
    plan_payload = {
        "plan_id": "plan_test_conf_001",
        "resolvable": True,
        "dag": {"steps": [{"id": "001-main", "tool": "tool_a"}], "artifacts": []},
        "chosen_tool": "tool_a",
        "candidates": [
            {
                "tool_id": "tool_a",
                "tool_name": "Tool A",
                "final_score": 0.90,
                "preflight_passed": True,
            },
            {
                "tool_id": "tool_b",
                "tool_name": "Tool B",
                "final_score": 0.80,
                "preflight_passed": True,
            },
        ],
    }
    events, state = build_planner_trace(plan_payload, request_payload={"pipeline": "x"})
    plan_payload["planner_events"] = [e.to_dict() for e in events]
    plan_payload["planner_state"] = state

    summary = compute_confidence_summary(
        plan_payload, planner_events=plan_payload["planner_events"]
    )
    assert "plan_conf" in summary
    assert "branch_conf" in summary
    assert "step_conf" in summary
    assert 0.0 <= summary["plan_conf"] <= 1.0
    assert len(summary["branch_conf"]) >= 1
    assert len(summary["step_conf"]) >= 1


def test_recovery_event_updates_state_and_confidence_penalty():
    plan_payload = {
        "plan_id": "plan_test_recovery_001",
        "resolvable": True,
        "dag": {"steps": [{"id": "001-main", "tool": "tool_a"}], "artifacts": []},
        "chosen_tool": "tool_a",
        "candidates": [
            {
                "tool_id": "tool_a",
                "tool_name": "Tool A",
                "final_score": 0.90,
                "preflight_passed": True,
            },
            {
                "tool_id": "tool_b",
                "tool_name": "Tool B",
                "final_score": 0.80,
                "preflight_passed": True,
            },
        ],
    }
    events, state = build_planner_trace(plan_payload, request_payload={"pipeline": "x"})

    # Append a recovery event that switches to tool_b
    recovery_event = PlannerEvent(
        event_type=PlannerEventType.RECOVERY_TRIGGERED,
        payload={
            "reason": "tool_substitute_after_timeout",
            "from_tool": "tool_a",
            "to_tool": "tool_b",
        },
        diff={
            "rejected_add": ["hyp:tool_a"],
            "selected_branch_id_set": "br:tool_b",
            "selected_tool_ids_set": ["tool_b"],
        },
    )
    all_events = [*events, recovery_event]

    updated_state = replay_planner_events([e.to_dict() for e in all_events])
    assert updated_state["selected_tool_ids"] == ["tool_b"]
    assert "hyp:tool_a" in updated_state["rejected"]

    plan_payload["planner_state"] = updated_state
    plan_payload["planner_events"] = [e.to_dict() for e in all_events]

    summary = compute_confidence_summary(
        plan_payload, planner_events=plan_payload["planner_events"]
    )
    branch_rows = {b["branch_id"]: b for b in summary["branch_conf"]}
    assert "br:tool_b" in branch_rows
    assert branch_rows["br:tool_b"]["n_recoveries"] >= 1
