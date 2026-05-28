from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

import brain_researcher.services.agent.autoresearch as autoresearch_module
from brain_researcher.services.agent.autoresearch import (
    FailureMotifCard,
    FixCandidate,
    ObservedRun,
    _assess_patch_legibility,
    _run_benchmark_slice,
    _run_validation_slice,
    detect_failure_observations,
    load_motif_canary_task_ids,
    mine_failure_motifs,
    propose_fix_candidates,
    validate_fix_candidate,
)
from brain_researcher.services.agent.repo_repair_context import (
    generate_repo_repair_context,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _make_run(
    root: Path,
    run_id: str,
    *,
    status: str,
    dry_run: bool,
    observation: dict | None = None,
    steps: list[dict] | None = None,
    error: str | None = None,
) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "run.json",
        {
            "run_id": run_id,
            "created_at": "2026-03-10T10:00:00Z",
            "status": status,
            "dry_run": dry_run,
            "started_at": "2026-03-10T10:00:01Z",
            "finished_at": "2026-03-10T10:00:02Z" if status != "running" else None,
            "steps": steps or [],
            "error": error,
        },
    )
    if observation is not None:
        _write_json(run_dir / "observation.json", observation)
    (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
    _write_json(run_dir / "provenance.json", {"run_id": run_id})
    _write_json(run_dir / "trajectory.json", {"steps": []})
    _write_json(
        run_dir / "analysis_bundle.json",
        {
            "run_id": run_id,
            "state": status,
            "files": {"observation_json": "observation.json"},
        },
    )


def _benchmark_payload(task_rows: list[dict]) -> dict:
    return {"results": task_rows}


def _task_row(task_id: str, *, success: bool, motif: str | None = None) -> dict:
    warnings = []
    violations = []
    errors = []
    if motif == "preflight_contract_failure":
        violations.append(
            {
                "code": "params_missing_required",
                "message": "Missing required params for workflow_x",
            }
        )
        errors.append("plan_invalid")
    if motif == "runtime_stall_or_incomplete_bundle":
        warnings.extend(
            [
                "trajectory_json is missing",
                "analysis_bundle_json is missing",
            ]
        )
    if motif == "trace_or_bundle_corruption":
        warnings.append("trace_jsonl is unreadable: JSONDecodeError")

    return {
        "task_id": task_id,
        "final_status": "success" if success else "max_attempts_reached",
        "final_evaluation": {"score": 1.0 if success else 0.2},
        "attempts": [
            {
                "status": "success" if success else "failed",
                "run_scorecard": {
                    "status": "succeeded" if success else "failed",
                    "completion_state": "succeeded" if success else "failed",
                    "policy": {"issue_count": 0},
                    "warnings": warnings,
                    "errors": errors,
                    "summary_metrics": {
                        "artifact_completeness_ratio": 1.0,
                        "error_count": 0 if success else (1 if errors else 0),
                    },
                    "steps": [
                        {
                            "step_id": "s1",
                            "tool_id": "workflow_example",
                            "status": "succeeded" if success else "failed",
                        }
                    ],
                },
                "run_bundle": {
                    "observation": {"violations": violations},
                },
                "run_warnings": [],
                "brainr_run_id": f"run_{task_id}",
            }
        ],
    }


def _native_task_row(
    task_id: str,
    *,
    success: bool,
    motif_present: bool | None = None,
    blocker: bool | None = None,
) -> dict:
    if motif_present is None:
        motif_present = not success
    if blocker is None:
        blocker = not success

    score = 1.0 if success else 0.3
    return {
        "task_id": task_id,
        "final_status": "success" if success else "max_attempts_reached",
        "motif_present": motif_present,
        "blocker": blocker,
        "final_evaluation": {
            "score": score,
            "evidence_missing": [] if success else ["analysis_bundle.json"],
            "metrics_met": ["run_terminal"] if success else [],
        },
        "attempts": [
            {
                "attempt_number": 1,
                "status": "success" if success else "failed",
                "score": score,
                "workdir": f"/tmp/{task_id.lower()}",
                "run_dir": f"/tmp/{task_id.lower()}/run",
                "brainr_run_id": f"native_{task_id}",
                "run_bundle": {"observation": {"violations": []}},
                "run_scorecard": {
                    "status": "succeeded" if success else "failed",
                    "completion_state": "succeeded" if success else "failed",
                    "policy": {"issue_count": 0},
                    "warnings": [],
                    "errors": [],
                    "summary_metrics": {
                        "artifact_completeness_ratio": 1.0 if success else 0.5,
                        "error_count": 0 if success else 1,
                    },
                    "steps": [
                        {
                            "step_id": task_id.lower(),
                            "tool_id": task_id,
                            "status": "succeeded" if success else "failed",
                        }
                    ],
                },
                "run_warnings": [],
                "error_message": None if success else "native harness verifier failed",
                "evidence_found": ["analysis_bundle.json"] if success else [],
                "evidence_missing": [] if success else ["analysis_bundle.json"],
                "metrics_met": ["run_terminal"] if success else [],
                "metrics_failed": [] if success else ["bundle_persisted"],
            }
        ],
    }


def test_detect_failure_observations_classifies_preflight_and_param_fill():
    observed = ObservedRun(
        run_id="run_1",
        run_dir="/tmp/run_1",
        status="failed",
        dry_run=True,
        tool_ids=["workflow_seed_based_connectivity"],
        step_statuses=["skipped"],
        errors=["plan_invalid"],
        warnings=["trace_jsonl is unreadable: JSONDecodeError"],
        violation_codes=["params_missing_required"],
        violation_messages=[
            "Missing required params for workflow_seed_based_connectivity"
        ],
        artifact_completeness_ratio=1.0,
    )

    motifs = {item.motif_family for item in detect_failure_observations(observed)}

    assert "preflight_contract_failure" in motifs
    assert "tool_param_fill_failure" in motifs
    assert "trace_or_bundle_corruption" not in motifs


def test_mine_failure_motifs_from_run_dirs(tmp_path):
    run_root = tmp_path / "mcp_runs"
    _make_run(
        run_root,
        "run_preflight",
        status="failed",
        dry_run=True,
        error="plan_invalid",
        steps=[
            {
                "step_id": "s1",
                "tool_id": "workflow_seed_based_connectivity",
                "status": "skipped",
                "error": "plan_invalid",
                "result_path": None,
            }
        ],
        observation={
            "run_id": "run_preflight",
            "state": "failed",
            "started_at": "2026-03-10T10:00:01Z",
            "finished_at": "2026-03-10T10:00:02Z",
            "steps": [
                {
                    "tool_call_id": "s1",
                    "name": "workflow_seed_based_connectivity",
                    "status": "skipped",
                    "error": "plan_invalid",
                }
            ],
            "violations": [
                {
                    "code": "params_missing_required",
                    "message": "Missing required params for workflow_seed_based_connectivity",
                }
            ],
        },
    )
    _make_run(
        run_root,
        "run_stalled",
        status="running",
        dry_run=False,
        steps=[
            {
                "step_id": "s1",
                "tool_id": "coordinate_to_concept",
                "status": "running",
                "error": None,
                "result_path": None,
            }
        ],
    )
    stalled_dir = run_root / "runs" / "run_stalled"
    old_mtime = stalled_dir.stat().st_mtime - 7200
    os.utime(stalled_dir, (old_mtime, old_mtime))
    os.utime(stalled_dir / "run.json", (old_mtime, old_mtime))

    cards = mine_failure_motifs(
        limit=50,
        days=30,
        autoresearch_root=tmp_path / "state",
        run_root=run_root,
    )
    motif_ids = {card.motif_id for card in cards}

    assert "preflight_contract_failure" in motif_ids
    assert "runtime_stall_or_incomplete_bundle" in motif_ids
    assert (
        tmp_path / "state" / "failure_motifs" / "failure_motifs_latest.jsonl"
    ).exists()


def test_propose_fix_candidates_materializes_candidate_manifest(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    motif_dir = state_root / "failure_motifs"
    motif_dir.mkdir(parents=True, exist_ok=True)
    card = FailureMotifCard(
        motif_id="tool_param_fill_failure",
        motif_family="tool_param_fill_failure",
        severity="high",
        frequency=3,
        affected_tools_workflows=["workflow_seed_based_connectivity"],
        representative_runs=["run_a"],
        evidence_snippets=["Missing required params"],
        suspected_surface="tool_schema_and_param_fill",
        suggested_fix_surfaces=["tool_schema_and_param_fill"],
        recommended_benchmark_slice_id="tool_param_fill_failure",
        source_corpus_summary={"total_runs": 1},
    )
    (motif_dir / "failure_motifs_latest.jsonl").write_text(
        json.dumps(asdict(card)) + "\n",
        encoding="utf-8",
    )

    def _fake_materialize(
        candidate_id: str, *, repo_root: Path, autoresearch_root: Path
    ) -> Path:
        path = tmp_path / "worktrees" / candidate_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._materialize_worktree",
        _fake_materialize,
    )

    candidates = propose_fix_candidates(
        "tool_param_fill_failure",
        autoresearch_root=state_root,
        max_candidates=1,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.allowed_paths
    assert (
        state_root / "candidates" / candidate.candidate_id / "candidate_fix.json"
    ).exists()
    assert (Path(candidate.worktree_path) / "fix_brief.md").exists()


def test_validate_fix_candidate_passes_fail_fast_gate(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    worktree = tmp_path / "candidate_worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    candidate = FixCandidate(
        candidate_id="cand_001",
        motif_id="preflight_contract_failure",
        motif_family="preflight_contract_failure",
        target_surface="mcp_preflight_contracts",
        allowed_paths=["src/brain_researcher/services/mcp/server.py"],
        worktree_path=str(worktree),
        patch_rationale="Tighten preflight validation",
        validation_slice_id="preflight_contract_failure",
        local_check_commands=["pytest -q tests/unit/mcp/test_local_mcp_server.py"],
        created_at="2026-03-10T10:00:00+00:00",
    )
    candidate_root = state_root / "candidates" / candidate.candidate_id
    candidate_root.mkdir(parents=True, exist_ok=True)
    (candidate_root / "candidate_fix.json").write_text(
        json.dumps(asdict(candidate)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._list_touched_paths",
        lambda _: ["src/brain_researcher/services/mcp/server.py"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_local_checks",
        lambda _: {"ok": True, "results": []},
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.load_motif_slice_task_ids",
        lambda *args, **kwargs: ["TASK-001", "TASK-002"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.load_canary_task_ids",
        lambda *args, **kwargs: ["CANARY-001", "CANARY-002"],
    )

    calls = []

    def _fake_run_benchmark_slice(*, candidate_label: str, slice_name: str, **kwargs):
        calls.append((candidate_label, slice_name))
        if slice_name == "motif_slice" and candidate_label == "baseline":
            payload = _benchmark_payload(
                [
                    _task_row(
                        "TASK-001", success=False, motif="preflight_contract_failure"
                    ),
                    _task_row("TASK-002", success=True),
                ]
            )
        elif slice_name == "motif_slice":
            payload = _benchmark_payload(
                [
                    _task_row("TASK-001", success=True),
                    _task_row("TASK-002", success=True),
                ]
            )
        elif candidate_label == "baseline":
            payload = _benchmark_payload(
                [
                    _task_row("CANARY-001", success=True),
                    _task_row("CANARY-002", success=True),
                ]
            )
        else:
            payload = _benchmark_payload(
                [
                    _task_row("CANARY-001", success=True),
                    _task_row("CANARY-002", success=True),
                ]
            )
        return {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "results_path": f"/tmp/{candidate_label}_{slice_name}.json",
            "payload": payload,
        }

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_benchmark_slice",
        _fake_run_benchmark_slice,
    )

    report = validate_fix_candidate(
        candidate.candidate_id,
        autoresearch_root=state_root,
        timeout_s=60,
    )

    assert report.gate_verdict == "passed"
    assert report.larger_benchmark_eligible is True
    assert report.fixed_failures == ["TASK-001"]
    assert len(calls) == 4
    assert (
        state_root / "validations" / candidate.candidate_id / "validation_report.json"
    ).exists()


def test_load_motif_canary_task_ids_returns_override_or_empty_list(tmp_path):
    motif_config = tmp_path / "motif_slices.yaml"
    motif_config.write_text(
        "\n".join(
            [
                "motifs:",
                "  preflight_contract_failure:",
                "    task_ids:",
                "      - TASK-001",
                "    canary_task_ids:",
                "      - ' CANARY-OVERRIDE-001 '",
                "      - ''",
                "      - CANARY-OVERRIDE-002",
                "  trace_or_bundle_corruption:",
                "    task_ids:",
                "      - TASK-002",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert load_motif_canary_task_ids(
        "preflight_contract_failure",
        path=motif_config,
    ) == ["CANARY-OVERRIDE-001", "CANARY-OVERRIDE-002"]
    assert (
        load_motif_canary_task_ids(
            "trace_or_bundle_corruption",
            path=motif_config,
        )
        == []
    )


def test_validate_fix_candidate_uses_motif_canary_override_then_falls_back(
    tmp_path,
    monkeypatch,
):
    state_root = tmp_path / "state"
    worktree = tmp_path / "candidate_worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    candidate = FixCandidate(
        candidate_id="cand_canary_override_001",
        motif_id="preflight_contract_failure",
        motif_family="preflight_contract_failure",
        target_surface="mcp_preflight_contracts",
        allowed_paths=["src/brain_researcher/services/mcp/server.py"],
        worktree_path=str(worktree),
        patch_rationale="Tighten preflight validation",
        validation_slice_id="preflight_contract_failure",
        local_check_commands=["pytest -q tests/unit/mcp/test_local_mcp_server.py"],
        created_at="2026-03-10T10:00:00+00:00",
    )
    candidate_root = state_root / "candidates" / candidate.candidate_id
    candidate_root.mkdir(parents=True, exist_ok=True)
    (candidate_root / "candidate_fix.json").write_text(
        json.dumps(asdict(candidate)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._list_touched_paths",
        lambda _: ["src/brain_researcher/services/mcp/server.py"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_local_checks",
        lambda _: {"ok": True, "results": []},
    )

    calls: list[tuple[str, str, list[str]]] = []

    def _fake_run_validation_slice(
        *, task_ids: list[str], candidate_label: str, slice_name: str, **kwargs
    ):
        calls.append((candidate_label, slice_name, list(task_ids)))
        if slice_name == "motif_slice":
            if candidate_label == "baseline":
                rows = [
                    _task_row(
                        task_ids[0],
                        success=False,
                        motif="preflight_contract_failure",
                    )
                ]
                rows.extend(
                    _task_row(task_id, success=True) for task_id in task_ids[1:]
                )
            else:
                rows = [_task_row(task_id, success=True) for task_id in task_ids]
        else:
            rows = [_task_row(task_id, success=True) for task_id in task_ids]
        return {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "results_path": f"/tmp/{candidate_label}_{slice_name}.json",
            "payload": _benchmark_payload(rows),
        }

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_validation_slice",
        _fake_run_validation_slice,
    )

    default_canary_path = tmp_path / "canary_slice.yaml"
    default_canary_path.write_text(
        "\n".join(
            [
                "task_ids:",
                "  - CANARY-DEFAULT-001",
                "  - CANARY-DEFAULT-002",
                "",
            ]
        ),
        encoding="utf-8",
    )

    override_motif_path = tmp_path / "motif_slices_with_override.yaml"
    override_motif_path.write_text(
        "\n".join(
            [
                "motifs:",
                "  preflight_contract_failure:",
                "    task_ids:",
                "      - TASK-001",
                "      - TASK-002",
                "    canary_task_ids:",
                "      - CANARY-OVERRIDE-001",
                "  trace_or_bundle_corruption:",
                "    task_ids:",
                "      - TASK-003",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = validate_fix_candidate(
        candidate.candidate_id,
        autoresearch_root=state_root,
        motif_slice_path=override_motif_path,
        canary_slice_path=default_canary_path,
        timeout_s=60,
    )

    assert report.gate_verdict == "passed"
    assert report.fixed_failures == ["TASK-001"]
    assert [
        task_ids for _, slice_name, task_ids in calls if slice_name == "canary_slice"
    ] == [
        ["CANARY-OVERRIDE-001"],
        ["CANARY-OVERRIDE-001"],
    ]

    calls.clear()

    fallback_motif_path = tmp_path / "motif_slices_without_override.yaml"
    fallback_motif_path.write_text(
        "\n".join(
            [
                "motifs:",
                "  preflight_contract_failure:",
                "    task_ids:",
                "      - TASK-001",
                "      - TASK-002",
                "  trace_or_bundle_corruption:",
                "    task_ids:",
                "      - TASK-003",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = validate_fix_candidate(
        candidate.candidate_id,
        autoresearch_root=state_root,
        motif_slice_path=fallback_motif_path,
        canary_slice_path=default_canary_path,
        timeout_s=60,
    )

    assert report.gate_verdict == "passed"
    assert report.fixed_failures == ["TASK-001"]
    assert [
        task_ids for _, slice_name, task_ids in calls if slice_name == "canary_slice"
    ] == [
        ["CANARY-DEFAULT-001", "CANARY-DEFAULT-002"],
        ["CANARY-DEFAULT-001", "CANARY-DEFAULT-002"],
    ]


def test_run_validation_slice_splits_harness_tasks_and_merges_payloads(
    tmp_path, monkeypatch
):
    state_root = tmp_path / "state"
    benchmark_root = tmp_path / "benchmark"
    python_repo = tmp_path / "candidate_repo"
    calls: list[tuple[str, str, list[str]]] = []

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.get_autoresearch_root",
        lambda *args, **kwargs: state_root,
    )

    def _fake_run_native_harness_slice(
        *, task_ids: list[str], candidate_label: str, slice_name: str, **kwargs
    ):
        calls.append(("native", candidate_label, task_ids))
        assert slice_name == "motif_slice"
        return {
            "returncode": 2,
            "stdout": "native stdout",
            "stderr": "native stderr",
            "results_path": "/tmp/native_results.json",
            "payload": {
                "results": [
                    _native_task_row("HARNESS-001", success=False),
                    _native_task_row(
                        "HARNESS-002", success=True, motif_present=False, blocker=False
                    ),
                ]
            },
        }

    def _fake_run_benchmark_slice(
        *, task_ids: list[str], candidate_label: str, slice_name: str, **kwargs
    ):
        calls.append(("benchmark", candidate_label, task_ids))
        assert slice_name == "motif_slice"
        return {
            "returncode": 0,
            "stdout": "benchmark stdout",
            "stderr": "benchmark stderr",
            "results_path": "/tmp/benchmark_results.json",
            "payload": {
                "results": [
                    _task_row("TASK-001", success=True),
                    _task_row(
                        "TASK-002", success=False, motif="preflight_contract_failure"
                    ),
                ]
            },
        }

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_native_harness_slice",
        _fake_run_native_harness_slice,
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_benchmark_slice",
        _fake_run_benchmark_slice,
    )

    result = _run_validation_slice(
        benchmark_root=benchmark_root,
        task_ids=["TASK-001", "HARNESS-001", "TASK-002", "HARNESS-002"],
        python_repo=python_repo,
        candidate_label="candidate",
        loop_profile_id="external_coding_v1",
        timeout_s=60,
        candidate_id="cand_001",
        slice_name="motif_slice",
    )

    assert calls == [
        ("native", "candidate", ["HARNESS-001", "HARNESS-002"]),
        ("benchmark", "candidate", ["TASK-001", "TASK-002"]),
    ]
    assert result["returncode"] == 2
    assert result["stdout"] == "benchmark stdout\nnative stdout"
    assert result["stderr"] == "benchmark stderr\nnative stderr"
    assert [row["task_id"] for row in result["payload"]["results"]] == [
        "TASK-001",
        "TASK-002",
        "HARNESS-001",
        "HARNESS-002",
    ]

    merged_path = (
        state_root
        / "benchmark_workdirs"
        / "cand_001"
        / "candidate"
        / "motif_slice"
        / "merged_results.json"
    )
    assert Path(result["results_path"]) == merged_path
    assert json.loads(merged_path.read_text(encoding="utf-8")) == result["payload"]


def test_validate_fix_candidate_passes_gate_for_native_harness_motif_slice(
    tmp_path,
    monkeypatch,
):
    state_root = tmp_path / "state"
    worktree = tmp_path / "candidate_worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    candidate = FixCandidate(
        candidate_id="cand_native_001",
        motif_id="preflight_contract_failure",
        motif_family="preflight_contract_failure",
        target_surface="mcp_preflight_contracts",
        allowed_paths=["src/brain_researcher/services/mcp/server.py"],
        worktree_path=str(worktree),
        patch_rationale="Tighten preflight validation",
        validation_slice_id="preflight_contract_failure",
        local_check_commands=["pytest -q tests/unit/mcp/test_local_mcp_server.py"],
        created_at="2026-03-10T10:00:00+00:00",
    )
    candidate_root = state_root / "candidates" / candidate.candidate_id
    candidate_root.mkdir(parents=True, exist_ok=True)
    (candidate_root / "candidate_fix.json").write_text(
        json.dumps(asdict(candidate)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._list_touched_paths",
        lambda _: ["src/brain_researcher/services/mcp/server.py"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_local_checks",
        lambda _: {"ok": True, "results": []},
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.load_motif_slice_task_ids",
        lambda *args, **kwargs: ["HARNESS-FAIL-001"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.load_canary_task_ids",
        lambda *args, **kwargs: ["CANARY-001", "CANARY-002"],
    )

    native_calls: list[tuple[str, str, list[str]]] = []
    benchmark_calls: list[tuple[str, str, list[str]]] = []

    def _fake_run_native_harness_slice(
        *, task_ids: list[str], candidate_label: str, slice_name: str, **kwargs
    ):
        native_calls.append((candidate_label, slice_name, task_ids))
        return {
            "returncode": 0 if candidate_label == "candidate" else 2,
            "stdout": "",
            "stderr": "",
            "results_path": f"/tmp/{candidate_label}_{slice_name}_native.json",
            "payload": {
                "results": [
                    _native_task_row(
                        "HARNESS-FAIL-001",
                        success=candidate_label == "candidate",
                        motif_present=candidate_label != "candidate",
                        blocker=candidate_label != "candidate",
                    )
                ]
            },
        }

    def _fake_run_benchmark_slice(
        *, task_ids: list[str], candidate_label: str, slice_name: str, **kwargs
    ):
        benchmark_calls.append((candidate_label, slice_name, task_ids))
        return {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "results_path": f"/tmp/{candidate_label}_{slice_name}_benchmark.json",
            "payload": _benchmark_payload(
                [
                    _task_row("CANARY-001", success=True),
                    _task_row("CANARY-002", success=True),
                ]
            ),
        }

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_native_harness_slice",
        _fake_run_native_harness_slice,
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_benchmark_slice",
        _fake_run_benchmark_slice,
    )

    report = validate_fix_candidate(
        candidate.candidate_id,
        autoresearch_root=state_root,
        timeout_s=60,
    )

    assert report.gate_verdict == "passed"
    assert report.larger_benchmark_eligible is True
    assert report.fixed_failures == ["HARNESS-FAIL-001"]
    assert report.regressions == []
    assert report.baseline_summary["motif_slice"]["motif_hit_count"] == 1
    assert report.baseline_summary["motif_slice"]["motif_blocker_count"] == 1
    assert report.candidate_summary["motif_slice"]["motif_hit_count"] == 0
    assert report.candidate_summary["motif_slice"]["motif_blocker_count"] == 0
    assert report.baseline_summary["canary_slice"]["success_rate"] == 1.0
    assert report.candidate_summary["canary_slice"]["success_rate"] == 1.0
    assert native_calls == [
        ("baseline", "motif_slice", ["HARNESS-FAIL-001"]),
        ("candidate", "motif_slice", ["HARNESS-FAIL-001"]),
    ]
    assert benchmark_calls == [
        ("baseline", "canary_slice", ["CANARY-001", "CANARY-002"]),
        ("candidate", "canary_slice", ["CANARY-001", "CANARY-002"]),
    ]
    assert (
        state_root / "validations" / candidate.candidate_id / "validation_report.json"
    ).exists()


def test_validate_fix_candidate_marks_absorbed_upstream_when_baseline_no_longer_reproduces(
    tmp_path,
    monkeypatch,
):
    state_root = tmp_path / "state"
    worktree = tmp_path / "candidate_worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    candidate = FixCandidate(
        candidate_id="cand_absorbed_001",
        motif_id="trace_or_bundle_corruption",
        motif_family="trace_or_bundle_corruption",
        target_surface="trace_bundle_integrity",
        allowed_paths=["src/brain_researcher/services/mcp/server.py"],
        worktree_path=str(worktree),
        patch_rationale="Keep MCP run finalization intact",
        validation_slice_id="trace_or_bundle_corruption",
        local_check_commands=["pytest -q tests/unit/mcp/test_local_mcp_server.py"],
        created_at="2026-03-12T10:00:00+00:00",
    )
    candidate_root = state_root / "candidates" / candidate.candidate_id
    candidate_root.mkdir(parents=True, exist_ok=True)
    (candidate_root / "candidate_fix.json").write_text(
        json.dumps(asdict(candidate)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._list_touched_paths",
        lambda _: ["src/brain_researcher/services/mcp/server.py"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_local_checks",
        lambda _: {"ok": True, "results": []},
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.load_motif_slice_task_ids",
        lambda *args, **kwargs: ["HARNESS-001"],
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.load_canary_task_ids",
        lambda *args, **kwargs: ["HARNESS-001"],
    )

    def _fake_run_validation_slice(*, candidate_label: str, **kwargs):
        return {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "results_path": f"/tmp/{candidate_label}.json",
            "payload": {
                "results": [
                    _native_task_row(
                        "HARNESS-001",
                        success=True,
                        motif_present=False,
                        blocker=False,
                    )
                ]
            },
        }

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch._run_validation_slice",
        _fake_run_validation_slice,
    )

    report = validate_fix_candidate(
        candidate.candidate_id,
        autoresearch_root=state_root,
        timeout_s=60,
    )

    assert report.gate_verdict == "absorbed_upstream"
    assert report.larger_benchmark_eligible is False
    assert report.fixed_failures == []
    assert report.status_explanation is not None
    assert "already include this repair" in report.status_explanation
    assert report.recommended_action is not None
    assert "Archive or close this candidate" in report.recommended_action

    persisted = json.loads(
        (
            state_root
            / "candidates"
            / candidate.candidate_id
            / "candidate_fix.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["status"] == "absorbed_upstream"


def test_assess_patch_legibility_scores_localized_clean_patch(monkeypatch, tmp_path):
    candidate = FixCandidate(
        candidate_id="cand_legibility_001",
        motif_id="tool_param_fill_failure",
        motif_family="tool_param_fill_failure",
        target_surface="tool_schema_and_param_fill",
        allowed_paths=["src/brain_researcher/services/mcp/server.py"],
        worktree_path=str(tmp_path),
        patch_rationale="Improve required-param validation",
        validation_slice_id="tool_param_fill_failure",
        local_check_commands=[],
        created_at="2026-03-12T10:00:00+00:00",
    )

    def _fake_git(*args, cwd):
        command = tuple(args)
        if command[:2] == ("diff", "--numstat"):
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="12\t3\tsrc/brain_researcher/services/mcp/server.py\n",
                stderr="",
            )
        if command[:2] == ("diff", "--unified=0"):
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                stdout="@@ -1 +1 @@\n+return validate_required_params(params)\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected git call: {command}")

    monkeypatch.setattr(autoresearch_module, "_git", _fake_git)

    assessment = _assess_patch_legibility(
        tmp_path,
        candidate,
        touched_paths=["src/brain_researcher/services/mcp/server.py"],
    )

    assert assessment["band"] == "high"
    assert assessment["score"] >= 85.0
    assert assessment["files_touched"] == 1
    assert assessment["outside_allowlist_count"] == 0
    assert assessment["lines_added"] == 12
    assert assessment["lines_deleted"] == 3
    assert assessment["temp_marker_hits"] == []
    assert assessment["debug_marker_hits"] == []


def test_validate_fix_candidate_persists_patch_legibility(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    worktree = tmp_path / "candidate_worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    candidate = FixCandidate(
        candidate_id="cand_legibility_report_001",
        motif_id="preflight_contract_failure",
        motif_family="preflight_contract_failure",
        target_surface="mcp_preflight_contracts",
        allowed_paths=["src/brain_researcher/services/mcp/server.py"],
        worktree_path=str(worktree),
        patch_rationale="Tighten preflight validation",
        validation_slice_id="preflight_contract_failure",
        local_check_commands=[],
        created_at="2026-03-12T10:00:00+00:00",
    )
    candidate_root = state_root / "candidates" / candidate.candidate_id
    candidate_root.mkdir(parents=True, exist_ok=True)
    (candidate_root / "candidate_fix.json").write_text(
        json.dumps(asdict(candidate)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        autoresearch_module,
        "_list_touched_paths",
        lambda _: ["src/brain_researcher/services/mcp/server.py"],
    )
    monkeypatch.setattr(
        autoresearch_module,
        "_assess_patch_legibility",
        lambda *args, **kwargs: {
            "score": 91.0,
            "band": "high",
            "files_touched": 1,
            "lines_added": 14,
            "lines_deleted": 2,
            "outside_allowlist_count": 0,
            "outside_allowlist_paths": [],
            "findings": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        autoresearch_module,
        "_run_local_checks",
        lambda _: {"ok": True, "results": []},
    )
    monkeypatch.setattr(
        autoresearch_module,
        "load_motif_slice_task_ids",
        lambda *args, **kwargs: ["HARNESS-001"],
    )
    monkeypatch.setattr(
        autoresearch_module,
        "load_canary_task_ids",
        lambda *args, **kwargs: ["HARNESS-001"],
    )
    monkeypatch.setattr(
        autoresearch_module,
        "_run_validation_slice",
        lambda *, candidate_label, **kwargs: {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "results_path": f"/tmp/{candidate_label}.json",
            "payload": {
                "results": [
                    _native_task_row(
                        "HARNESS-001",
                        success=True,
                        motif_present=False,
                        blocker=False,
                    )
                ]
            },
        },
    )

    report = validate_fix_candidate(
        candidate.candidate_id,
        autoresearch_root=state_root,
        timeout_s=60,
    )

    assert report.patch_legibility["score"] == 91.0
    assert report.patch_legibility["band"] == "high"

    persisted = json.loads(
        (
            state_root
            / "validations"
            / candidate.candidate_id
            / "validation_report.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["patch_legibility"]["score"] == 91.0
    assert persisted["patch_legibility"]["band"] == "high"


def test_run_benchmark_slice_exports_src_layout_pythonpath(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    results_dir = benchmark_root / "benchmark_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    python_repo = tmp_path / "candidate_repo"
    (python_repo / "src").mkdir(parents=True, exist_ok=True)

    captured = {}

    def _fake_run(cmd, cwd, env, capture_output, text, check):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        (results_dir / "results_fake.json").write_text(
            json.dumps({"results": []}),
            encoding="utf-8",
        )

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(
        "brain_researcher.services.agent.autoresearch.subprocess.run",
        _fake_run,
    )

    payload = _run_benchmark_slice(
        benchmark_root=benchmark_root,
        task_ids=["TASK-001"],
        python_repo=python_repo,
        candidate_label="candidate",
        loop_profile_id="external_coding_v1",
        timeout_s=60,
        candidate_id="cand_001",
        slice_name="motif_slice",
    )

    assert payload["returncode"] == 0
    pythonpath = captured["env"]["PYTHONPATH"].split(":")
    assert pythonpath[0] == str(python_repo / "src")
    assert pythonpath[1] == str(python_repo)


def test_generate_repo_repair_context_builds_persisted_artifact(tmp_path):
    autoresearch_root = tmp_path / "autoresearch"
    benchmark_root = tmp_path / "benchmark"
    golden_path = (
        tmp_path / "configs" / "codegen" / "autoresearch_golden_principles.yaml"
    )

    _write_jsonl(
        autoresearch_root / "failure_motifs" / "failure_motifs_latest.jsonl",
        [
            {
                "motif_id": "trace_or_bundle_corruption",
                "motif_family": "trace_or_bundle_corruption",
                "severity": "critical",
                "frequency": 7,
                "affected_tools_workflows": ["pipeline_execute"],
                "representative_runs": ["run_a", "run_b"],
                "evidence_snippets": ["trace-only run"],
                "suspected_surface": "trace_bundle_integrity",
                "suggested_fix_surfaces": ["trace_bundle_integrity"],
                "recommended_benchmark_slice_id": "trace_or_bundle_corruption",
                "source_corpus_summary": {"total_runs": 12},
            }
        ],
    )
    _write_json(
        autoresearch_root
        / "candidates"
        / "trace_or_bundle_corruption_001"
        / "candidate_fix.json",
        {
            "candidate_id": "trace_or_bundle_corruption_001",
            "motif_id": "trace_or_bundle_corruption",
            "motif_family": "trace_or_bundle_corruption",
            "target_surface": "trace_bundle_integrity",
            "allowed_paths": ["src/brain_researcher/services/mcp/server.py"],
            "worktree_path": "/tmp/trace_or_bundle_corruption_001",
            "patch_rationale": "Keep pipeline runs finalizing",
            "validation_slice_id": "trace_or_bundle_corruption",
            "local_check_commands": [],
            "created_at": "2026-03-12T10:00:00Z",
            "status": "absorbed_upstream",
        },
    )
    _write_json(
        autoresearch_root
        / "validations"
        / "trace_or_bundle_corruption_001"
        / "validation_report.json",
        {
            "candidate_id": "trace_or_bundle_corruption_001",
            "gate_verdict": "absorbed_upstream",
            "status_explanation": "Mainline already includes this repair.",
            "recommended_action": "Archive the candidate.",
            "touched_paths": ["src/brain_researcher/services/mcp/server.py"],
            "patch_legibility": {
                "score": 91.0,
                "band": "high",
            },
        },
    )
    (benchmark_root / "configs" / "autoresearch").mkdir(parents=True, exist_ok=True)
    (
        benchmark_root / "configs" / "autoresearch" / "motif_slices.yaml"
    ).write_text(
        """
motifs:
  trace_or_bundle_corruption:
    task_ids: [HARNESS-001]
    canary_task_ids: [HARNESS-001]
  runtime_stall_or_incomplete_bundle:
    task_ids: [HARNESS-002]
    canary_task_ids: [HARNESS-002]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (
        benchmark_root / "configs" / "autoresearch" / "canary_slice.yaml"
    ).write_text("task_ids: [HARNESS-001, HARNESS-002]\n", encoding="utf-8")
    golden_path.parent.mkdir(parents=True, exist_ok=True)
    golden_path.write_text(
        """
principles:
  - id: terminal_run_invariant
    title: Terminal Run Invariant
    rule: Every run must become terminal.
    why_it_exists: Stalled runs hide failures.
    failure_modes: [runtime_stall_or_incomplete_bundle]
    applies_to: [runtime, harness]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    payload = generate_repo_repair_context(
        top_n=4,
        persist=True,
        autoresearch_root=autoresearch_root,
        benchmark_root=benchmark_root,
        golden_principles_path=golden_path,
    )

    assert payload["ok"] is True
    context = payload["repo_repair_context"]
    assert context["summary"]["failure_motif_count"] == 1
    assert context["summary"]["absorbed_upstream_candidate_count"] == 1
    assert context["summary"]["harness_task_count"] == 2
    assert context["summary"]["golden_principle_count"] == 1
    assert context["hot_surfaces"][0]["surface"] == "trace_bundle_integrity"
    assert context["harness_coverage"]["all_harness_tasks"] == [
        "HARNESS-001",
        "HARNESS-002",
    ]
    assert "runtime_stall_or_incomplete_bundle" in context["harness_coverage"][
        "motifs_with_native_harness"
    ]
    assert context["absorbed_upstream_candidates"][0]["candidate_id"] == (
        "trace_or_bundle_corruption_001"
    )
    assert "Repo Repair Context" in payload["markdown"]
    for path in payload["persisted_files"]:
        assert Path(path).exists()
