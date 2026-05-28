from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.autoresearch.supervisor import BoundedSupervisor, SupervisorConfig
from brain_researcher.autoresearch.state_contract import (
    RuntimeStateArtifact,
    StageCommit,
    append_jsonl_artifact,
    write_json_artifact,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_supervisor_writes_runtime_artifacts_for_predictive_line(tmp_path: Path) -> None:
    project_root = tmp_path / "brain_researcher" / "research" / "predictive" / "project"
    artifacts_root = project_root / "artifacts"
    diagnostics_root = artifacts_root / "diagnostics"
    manifests_root = project_root / "manifests"
    inputs_root = tmp_path / "brain_researcher" / "research" / "predictive" / "inputs"
    cache_dir = tmp_path / "brain_researcher" / "fc_benchmarking" / "inputs" / "lane_b_cache"
    for path in (
        project_root,
        artifacts_root,
        diagnostics_root,
        manifests_root,
        inputs_root,
        cache_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    (cache_dir / "term_1_iu.h5").write_text("ok", encoding="utf-8")
    (manifests_root / "lane_b_data_manifest.json").write_text(
        json.dumps({"term_cache_dir": str(cache_dir)}, indent=2),
        encoding="utf-8",
    )
    ledger_path = project_root / "experiments.jsonl"
    _write_jsonl(
        ledger_path,
        [
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "PicSeq_Unadj",
                    "hyperparameters": {"term_index": 11, "replicate_id": "r1"},
                },
                "scores": {"gold_r2": 0.03},
                "tags": [],
            },
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "PicSeq_Unadj",
                    "hyperparameters": {"term_index": 12},
                },
                "scores": {"gold_r2": 0.02},
                "tags": [],
            },
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "PicSeq_Unadj",
                    "hyperparameters": {"term_index": 13},
                },
                "scores": {"gold_r2": 0.0},
                "tags": ["label-shuffle-control"],
            },
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "ListSort_Unadj",
                    "hyperparameters": {"term_index": 21},
                },
                "scores": {"gold_r2": 0.03},
                "tags": [],
            },
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "ListSort_Unadj",
                    "hyperparameters": {"term_index": 22},
                },
                "scores": {"gold_r2": 0.0},
                "tags": ["label-shuffle-control"],
            },
        ],
    )
    config = SupervisorConfig.from_dict(
        {
            "line_id": "predictive",
            "session_id": "sess-predictive",
            "project_root": str(project_root),
            "controller_command": ["python", "-c", "print('ok')"],
            "scorer_name": "predictive_weak_targets",
            "scorer_args": {
                "ledger_path": str(ledger_path),
                "min_nulls": 1,
                "min_replicates": 0,
            },
            "state_root": str(artifacts_root / "autonomy"),
            "max_cycles": 1,
            "max_stall_cycles": 1,
            "target_score": 0.5,
        }
    )

    stop = BoundedSupervisor(config).run()

    assert stop.stop_reason == "completed"
    for name in ("state.json", "verdict.json", "handoff.json", "stop.json"):
        assert (artifacts_root / "autonomy" / name).exists()
    assert (artifacts_root / "autonomy" / "stage_commits.jsonl").exists()


def test_supervisor_resumes_from_latest_stage_commit_without_rerunning_controller(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "brain_researcher" / "research" / "predictive" / "project"
    artifacts_root = project_root / "artifacts"
    diagnostics_root = artifacts_root / "diagnostics"
    manifests_root = project_root / "manifests"
    inputs_root = tmp_path / "brain_researcher" / "research" / "predictive" / "inputs"
    cache_dir = tmp_path / "brain_researcher" / "fc_benchmarking" / "inputs" / "lane_b_cache"
    for path in (
        project_root,
        artifacts_root,
        diagnostics_root,
        manifests_root,
        inputs_root,
        cache_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    (cache_dir / "term_1_iu.h5").write_text("ok", encoding="utf-8")
    (manifests_root / "lane_b_data_manifest.json").write_text(
        json.dumps({"term_cache_dir": str(cache_dir)}, indent=2),
        encoding="utf-8",
    )
    ledger_path = project_root / "experiments.jsonl"
    _write_jsonl(
        ledger_path,
        [
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "PicSeq_Unadj",
                    "hyperparameters": {"term_index": 11, "replicate_id": "r1"},
                },
                "scores": {"gold_r2": 0.03},
                "tags": [],
            },
            {
                "phase": "phase9_weak_target_term_discovery",
                "config": {
                    "target": "ListSort_Unadj",
                    "hyperparameters": {"term_index": 22, "replicate_id": "r1"},
                },
                "scores": {"gold_r2": 0.04},
                "tags": [],
            },
        ],
    )
    state_root = artifacts_root / "autonomy"
    state_root.mkdir(parents=True, exist_ok=True)
    controller_marker = project_root / "controller_ran.txt"
    controller_command = (
        "python",
        "-c",
        (
            "from pathlib import Path; "
            f"Path(r'{controller_marker}').write_text('ran', encoding='utf-8')"
        ),
    )
    scorer_command = (
        "python",
        "-c",
        "import json; print(json.dumps({'score': 0.8, 'resume': True}))",
    )
    write_json_artifact(
        state_root / "state.json",
        RuntimeStateArtifact(
            line_id="predictive",
            session_id="sess-resume",
            cycle_count=1,
            stall_count=0,
            current_stage="scoring",
            active_run_root=str(project_root),
            best_score=0.4,
            last_score=0.4,
            last_improving_cycle=1,
            controller_command=controller_command,
            scorer_name="external_json",
            runtime_paths={"project_root": str(project_root)},
        ),
    )
    append_jsonl_artifact(
        state_root / "stage_commits.jsonl",
        StageCommit(
            line_id="predictive",
            session_id="sess-resume",
            cycle_count=1,
            stage="controller",
            input_fingerprint="input-fp",
            output_fingerprint="output-fp",
            resume_token={"cycle": 1, "stage": "scoring"},
            artifact_paths={"state": str(state_root / "state.json")},
        ),
    )

    config = SupervisorConfig.from_dict(
        {
            "line_id": "predictive",
            "session_id": "sess-resume",
            "project_root": str(project_root),
            "controller_command": list(controller_command),
            "scorer_name": "external_json",
            "scorer_args": {},
            "scorer_command": list(scorer_command),
            "state_root": str(state_root),
            "max_cycles": 1,
            "max_stall_cycles": 1,
            "target_score": 0.5,
        }
    )

    stop = BoundedSupervisor(config).run()

    assert stop.stop_reason == "completed"
    assert not controller_marker.exists()
    commits = [
        json.loads(line)
        for line in (state_root / "stage_commits.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert commits[0]["stage"] == "controller"
    assert any(commit["stage"] == "scoring" for commit in commits)
