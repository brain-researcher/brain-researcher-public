from __future__ import annotations

from pathlib import Path

from brain_researcher.autoresearch.state_contract import (
    GateCheck,
    HandoffArtifact,
    StageCommit,
    RuntimeStateArtifact,
    StopArtifact,
    VerdictArtifact,
    append_jsonl_artifact,
    read_json_artifact,
    read_jsonl_artifacts,
    write_json_artifact,
)


def test_verdict_artifact_round_trip(tmp_path: Path) -> None:
    verdict = VerdictArtifact(
        line_id="predictive",
        decision="needs_exploration",
        correctness=GateCheck(passed=True, reasons=("paths valid",)),
        judgment=GateCheck(passed=False, reasons=("weak effect",)),
        completeness=GateCheck(
            passed=False,
            required_actions=("run exploratory follow-up",),
        ),
        critic_summary="Need one more arm.",
        critic_payload={"decision": "needs_exploration"},
    )

    path = write_json_artifact(tmp_path / "verdict.json", verdict)
    loaded = VerdictArtifact.from_dict(read_json_artifact(path))

    assert loaded.line_id == "predictive"
    assert loaded.decision == "needs_exploration"
    assert loaded.overall_passed is False
    assert loaded.completeness.required_actions == ("run exploratory follow-up",)


def test_runtime_handoff_and_stop_artifacts_write_json(tmp_path: Path) -> None:
    state = RuntimeStateArtifact(
        line_id="discovery",
        session_id="sess-1",
        cycle_count=2,
        stall_count=1,
        current_stage="scoring",
        active_run_root="/tmp/run",
        best_score=0.8,
        last_score=0.7,
        last_improving_cycle=1,
        controller_command=("python", "controller.py"),
        scorer_name="discovery_closed_loop",
        runtime_paths={"project_root": "/tmp/project"},
    )
    handoff = HandoffArtifact(
        line_id="discovery",
        session_id="sess-1",
        best_results={"score": 0.8},
        failed_approaches=("legacy_harness",),
        pending_actions=("repair branch",),
        recommended_next_action="Repair the branch before promotion.",
    )
    stop = StopArtifact(
        line_id="discovery",
        session_id="sess-1",
        final_status="blocked",
        stop_reason="stalled",
        total_cycles=2,
        stall_count=1,
        elapsed_seconds=12.5,
        last_score=0.7,
        scorer_name="discovery_closed_loop",
    )

    for name, payload in {
        "state.json": state,
        "handoff.json": handoff,
        "stop.json": stop,
    }.items():
        path = write_json_artifact(tmp_path / name, payload)
        loaded = read_json_artifact(path)
        assert loaded["line_id"] == payload.line_id


def test_stage_commit_jsonl_round_trip(tmp_path: Path) -> None:
    commit = StageCommit(
        line_id="predictive",
        session_id="sess-2",
        cycle_count=3,
        stage="scoring",
        input_fingerprint="input-fp",
        output_fingerprint="output-fp",
        resume_token={"cycle": 3, "stage": "verdict"},
        artifact_paths={"state": "/tmp/state.json"},
    )

    path = append_jsonl_artifact(tmp_path / "stage_commits.jsonl", commit)
    rows = read_jsonl_artifacts(path)
    loaded = StageCommit.from_dict(rows[0])

    assert loaded.line_id == "predictive"
    assert loaded.stage == "scoring"
    assert loaded.resume_token == {"cycle": 3, "stage": "verdict"}
    assert loaded.artifact_paths == {"state": "/tmp/state.json"}
