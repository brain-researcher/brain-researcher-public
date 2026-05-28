from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from brain_researcher.services.orchestrator.taskbeacon_handoff import (
    apply_taskbeacon_runtime_patches,
    default_taskbeacon_target_path,
    materialize_taskbeacon_repo,
    normalize_taskbeacon_ref,
    normalize_taskbeacon_repo,
    resolve_taskbeacon_target_path,
)


def test_normalize_taskbeacon_repo_accepts_org_repo_and_github_url() -> None:
    assert normalize_taskbeacon_repo("TaskBeacon/T000015-ant") == "TaskBeacon/T000015-ant"
    assert (
        normalize_taskbeacon_repo("https://github.com/TaskBeacon/T000015-ant")
        == "TaskBeacon/T000015-ant"
    )
    assert normalize_taskbeacon_repo("T000015-ant") == "TaskBeacon/T000015-ant"


def test_default_taskbeacon_target_path_uses_project_scoped_import_dir() -> None:
    assert default_taskbeacon_target_path("proj_demo", "TaskBeacon/T000015-ant") == (
        "projects/proj_demo/taskbeacon/T000015-ant"
    )


def test_resolve_taskbeacon_target_path_rejects_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes workspace root"):
        resolve_taskbeacon_target_path(tmp_path, "../outside")


def test_materialize_taskbeacon_repo_skips_existing_import(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    target_dir = workspace_root / "projects" / "proj_demo" / "taskbeacon" / "T000015-ant"
    target_dir.mkdir(parents=True)
    (target_dir / "README.md").write_text("already here\n", encoding="utf-8")

    result = materialize_taskbeacon_repo(
        workspace_root=workspace_root,
        repo="TaskBeacon/T000015-ant",
        target_path="projects/proj_demo/taskbeacon/T000015-ant",
    )

    assert result["status"] == "skipped_existing"
    assert result["target_dir"] == str(target_dir.resolve())
    assert result["runtime_patch"]["runner"] == "run_br_taskbeacon.sh"


def test_apply_taskbeacon_runtime_patches_write_hosted_configs(tmp_path: Path) -> None:
    target_dir = tmp_path / "T000015-ant"
    config_dir = target_dir / "config"
    responder_dir = target_dir / "responders"
    config_dir.mkdir(parents=True)
    responder_dir.mkdir()
    (responder_dir / "task_sampler.py").write_text("# sampler\n", encoding="utf-8")
    (config_dir / "config_qa.yaml").write_text(
        """
window:
  screen: 1
  fullscreen: true
  size: [1920, 1080]
stimuli:
  feedback:
    type: text
    font: SimHei
qa:
  output_dir: outputs/qa
  timing_scale: 0.05
""".lstrip(),
        encoding="utf-8",
    )
    (config_dir / "config_sampler_sim.yaml").write_text(
        """
window:
  screen: 1
  fullscreen: true
stimuli:
  instruction_text:
    type: textbox
    font: SimHei
sim:
  output_dir: outputs/sim_sampler
  session_id: sub-sim001_task-attention_network_test_sampler_seed0
  log_path: outputs/sim_sampler/old_sim_events.jsonl
""".lstrip(),
        encoding="utf-8",
    )

    result = apply_taskbeacon_runtime_patches(target_dir)

    assert result["files"] == [
        "config/br_config_qa.yaml",
        "config/br_config_sim.yaml",
        "run_br_taskbeacon.sh",
    ]
    qa_cfg = yaml.safe_load((target_dir / "config" / "br_config_qa.yaml").read_text())
    assert qa_cfg["window"]["screen"] == 0
    assert qa_cfg["window"]["fullscreen"] is False
    assert qa_cfg["stimuli"]["feedback"]["font"] == "Noto Sans CJK SC"
    assert qa_cfg["qa"]["timing_scale"] == 0.25
    assert qa_cfg["qa"]["log_path"] == "outputs/qa/qa_action_events.jsonl"

    sim_cfg = yaml.safe_load((target_dir / "config" / "br_config_sim.yaml").read_text())
    assert sim_cfg["window"]["screen"] == 0
    assert sim_cfg["window"]["fullscreen"] is False
    assert sim_cfg["stimuli"]["instruction_text"]["font"] == "Noto Sans CJK SC"
    assert sim_cfg["sim"]["session_id"] == (
        "sub-sim001_task_attention_network_test_sampler_seed0"
    )
    assert sim_cfg["sim"]["log_path"] == (
        "outputs/sim_sampler/"
        "sub-sim001_task_attention_network_test_sampler_seed0_sim_events.jsonl"
    )
    runner = target_dir / "run_br_taskbeacon.sh"
    assert runner.exists()
    assert "/app/scripts/runtime/run_taskbeacon_task.sh" in runner.read_text(
        encoding="utf-8"
    )


def test_materialize_taskbeacon_repo_writes_error_marker_on_clone_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="fatal: network blocked",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    workspace_root = tmp_path / "workspace"
    result = materialize_taskbeacon_repo(
        workspace_root=workspace_root,
        repo="TaskBeacon/T000015-ant",
        target_path="projects/proj_demo/taskbeacon/T000015-ant",
        ref=normalize_taskbeacon_ref("main"),
    )

    assert result["status"] == "error"
    error_file = (
        workspace_root
        / "projects"
        / "proj_demo"
        / "taskbeacon"
        / "T000015-ant"
        / "BR_TASKBEACON_IMPORT_ERROR.txt"
    )
    assert error_file.exists()
    assert "fatal: network blocked" in error_file.read_text(encoding="utf-8")
