"""TaskBeacon handoff helpers for hosted /hub workspaces.

This module keeps the first TaskBeacon integration narrow:

- accept only repos under the public ``TaskBeacon`` GitHub org
- derive a stable workspace target path under ``projects/<project_id>/taskbeacon/``
- materialize the repo inside a workspace when the runtime starts

The runtime materializer is intentionally best-effort. If clone fails, it writes
an error marker into the requested target directory so the workspace can still
open and show a concrete failure artifact instead of failing to boot entirely.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

_TASKBEACON_OWNER = "TaskBeacon"
_GITHUB_PREFIX_RE = re.compile(r"^https?://github\.com/", re.IGNORECASE)
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_HOSTED_CJK_FONT = "Noto Sans CJK SC"
_BR_QA_CONFIG = "config/br_config_qa.yaml"
_BR_SIM_CONFIG = "config/br_config_sim.yaml"
_BR_RUNNER = "run_br_taskbeacon.sh"


def normalize_taskbeacon_repo(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None

    if _GITHUB_PREFIX_RE.match(text):
        path = _GITHUB_PREFIX_RE.sub("", text, count=1).strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        text = path

    if "/" not in text:
        owner = _TASKBEACON_OWNER
        repo = text
    else:
        owner, repo = text.split("/", 1)

    if owner.lower() != _TASKBEACON_OWNER.lower():
        raise ValueError("TaskBeacon handoff only supports github.com/TaskBeacon repos")
    if not _REPO_NAME_RE.fullmatch(repo):
        raise ValueError(f"Invalid TaskBeacon repo name: {repo!r}")
    return f"{_TASKBEACON_OWNER}/{repo}"


def normalize_taskbeacon_ref(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if not _REF_RE.fullmatch(text):
        raise ValueError(f"Invalid TaskBeacon ref: {text!r}")
    return text


def taskbeacon_repo_name(repo: str) -> str:
    normalized = normalize_taskbeacon_repo(repo)
    assert normalized is not None
    return normalized.split("/", 1)[1]


def default_taskbeacon_target_path(project_id: str, repo: str) -> str:
    repo_name = taskbeacon_repo_name(repo)
    return f"projects/{project_id}/taskbeacon/{repo_name}"


def taskbeacon_clone_url(repo: str) -> str:
    normalized = normalize_taskbeacon_repo(repo)
    assert normalized is not None
    return f"https://github.com/{normalized}.git"


def resolve_taskbeacon_target_path(workspace_root: str | Path, target_path: str) -> Path:
    workspace = Path(workspace_root).expanduser().resolve()
    relative = Path(target_path)
    if relative.is_absolute():
        raise ValueError("TaskBeacon target_path must be workspace-relative")
    resolved = (workspace / relative).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"TaskBeacon target_path escapes workspace root: {target_path!r}"
        ) from exc
    return resolved


def _error_report(repo: str, ref: str | None, stderr: str) -> str:
    lines = [
        f"TaskBeacon import failed for {repo}.",
        "",
        "This runtime kept starting, but the requested task repo was not cloned.",
    ]
    if ref:
        lines.append(f"Requested ref: {ref}")
    if stderr.strip():
        lines.extend(["", "git stderr:", stderr.strip()])
    return "\n".join(lines).rstrip() + "\n"


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_yaml_config(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    parsed = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    return parsed if isinstance(parsed, dict) else {}


def _write_yaml_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _patch_window_config(cfg: dict[str, Any]) -> None:
    window = _as_mapping(cfg.setdefault("window", {}))
    window["screen"] = 0
    window["fullscreen"] = False
    window.setdefault("size", [1920, 1080])
    cfg["window"] = window


def _patch_stimulus_fonts(cfg: dict[str, Any]) -> None:
    stimuli = _as_mapping(cfg.get("stimuli"))
    for stim in stimuli.values():
        if isinstance(stim, dict) and str(stim.get("font") or "") == "SimHei":
            stim["font"] = _HOSTED_CJK_FONT


def _sanitize_taskbeacon_session_id(value: str | None, fallback: str) -> str:
    text = (value or "").strip() or fallback
    # Use one separator style for BR-hosted artifacts. Upstream ANT currently
    # mixes ``task-attention...`` JSONL with ``task_attention...`` CSV/JSON.
    text = text.replace("task-", "task_")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or fallback


def _patch_qa_config(cfg: dict[str, Any]) -> None:
    qa = _as_mapping(cfg.setdefault("qa", {}))
    output_dir = str(qa.get("output_dir") or "outputs/qa").rstrip("/")
    qa["output_dir"] = output_dir
    qa["log_path"] = f"{output_dir}/qa_action_events.jsonl"
    try:
        timing_scale = float(qa.get("timing_scale", 0.25))
    except (TypeError, ValueError):
        timing_scale = 0.25
    # Psyflow's QA observer still validates a synthetic 0.2s action. Keeping
    # the minimum scaled response window above that avoids noisy rejected-action
    # records while preserving a short smoke run.
    qa["timing_scale"] = max(timing_scale, 0.25)
    cfg["qa"] = qa


def _patch_sim_config(cfg: dict[str, Any]) -> None:
    sim = _as_mapping(cfg.setdefault("sim", {}))
    output_dir = str(sim.get("output_dir") or "outputs/sim").rstrip("/")
    session_id = _sanitize_taskbeacon_session_id(
        str(sim.get("session_id") or ""),
        "sub-sim001_task_attention_network_test_seed0",
    )
    sim["output_dir"] = output_dir
    sim["session_id"] = session_id
    sim["log_path"] = f"{output_dir}/{session_id}_sim_events.jsonl"
    cfg["sim"] = sim


def _hosted_taskbeacon_config(
    source: Path,
    *,
    mode: str,
) -> dict[str, Any] | None:
    cfg = _read_yaml_config(source)
    if cfg is None:
        return None
    _patch_window_config(cfg)
    _patch_stimulus_fonts(cfg)
    if mode == "qa":
        _patch_qa_config(cfg)
    elif mode == "sim":
        _patch_sim_config(cfg)
    return cfg


def _write_taskbeacon_runner(target_dir: Path) -> str:
    runner = target_dir / _BR_RUNNER
    runner.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "task_dir=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
        "mode=\"qa\"\n"
        "if [[ $# -gt 0 && \"${1}\" != --* ]]; then\n"
        "  mode=\"${1}\"\n"
        "  shift\n"
        "fi\n"
        "runner=\"${BR_TASKBEACON_RUNNER:-/app/scripts/runtime/run_taskbeacon_task.sh}\"\n"
        "if [[ ! -f \"${runner}\" ]]; then\n"
        "  echo \"BR TaskBeacon runner not found: ${runner}\" >&2\n"
        "  exit 127\n"
        "fi\n"
        "exec bash \"${runner}\" \"${mode}\" --task-dir \"${task_dir}\" \"$@\"\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    return _BR_RUNNER


def apply_taskbeacon_runtime_patches(target_dir: str | Path) -> dict[str, Any]:
    """Write BR-hosted runner/config overlays into a materialized task repo.

    The original TaskBeacon repo contents are preserved. BR writes separate
    ``br_config_*`` files and a small shell entrypoint used by hosted UI shells.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    qa_source = target / "config" / "config_qa.yaml"
    qa_cfg = _hosted_taskbeacon_config(qa_source, mode="qa")
    if qa_cfg is not None:
        _write_yaml_config(target / _BR_QA_CONFIG, qa_cfg)
        written.append(_BR_QA_CONFIG)

    sim_source = target / "config" / "config_sampler_sim.yaml"
    if not sim_source.exists():
        sim_source = target / "config" / "config_scripted_sim.yaml"
    sim_cfg = _hosted_taskbeacon_config(sim_source, mode="sim")
    if sim_cfg is not None:
        _write_yaml_config(target / _BR_SIM_CONFIG, sim_cfg)
        written.append(_BR_SIM_CONFIG)

    runner = _write_taskbeacon_runner(target)
    written.append(runner)
    return {
        "status": "patched",
        "files": written,
        "qa_config": _BR_QA_CONFIG if _BR_QA_CONFIG in written else None,
        "sim_config": _BR_SIM_CONFIG if _BR_SIM_CONFIG in written else None,
        "runner": runner,
    }


def materialize_taskbeacon_repo(
    *,
    workspace_root: str | Path,
    repo: str,
    target_path: str,
    ref: str | None = None,
) -> dict[str, Any]:
    normalized_repo = normalize_taskbeacon_repo(repo)
    if normalized_repo is None:
        raise ValueError("TaskBeacon repo is required")
    normalized_ref = normalize_taskbeacon_ref(ref)
    target_dir = resolve_taskbeacon_target_path(workspace_root, target_path)

    if target_dir.exists():
        if target_dir.is_file():
            raise ValueError(f"TaskBeacon target_path points to a file: {target_path!r}")
        if any(target_dir.iterdir()):
            runtime_patch = apply_taskbeacon_runtime_patches(target_dir)
            return {
                "status": "skipped_existing",
                "repo": normalized_repo,
                "ref": normalized_ref,
                "target_path": target_path,
                "target_dir": str(target_dir),
                "runtime_patch": runtime_patch,
            }

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    clone_cmd = ["git", "clone", "--depth", "1"]
    if normalized_ref is not None:
        clone_cmd.extend(["--branch", normalized_ref, "--single-branch"])
    clone_cmd.extend([taskbeacon_clone_url(normalized_repo), str(target_dir)])

    proc = subprocess.run(clone_cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        target_dir.mkdir(parents=True, exist_ok=True)
        error_path = target_dir / "BR_TASKBEACON_IMPORT_ERROR.txt"
        error_path.write_text(
            _error_report(normalized_repo, normalized_ref, proc.stderr),
            encoding="utf-8",
        )
        return {
            "status": "error",
            "repo": normalized_repo,
            "ref": normalized_ref,
            "target_path": target_path,
            "target_dir": str(target_dir),
            "error_file": str(error_path),
            "return_code": proc.returncode,
            "stderr": proc.stderr,
        }

    runtime_patch = apply_taskbeacon_runtime_patches(target_dir)
    return {
        "status": "cloned",
        "repo": normalized_repo,
        "ref": normalized_ref,
        "target_path": target_path,
        "target_dir": str(target_dir),
        "clone_url": taskbeacon_clone_url(normalized_repo),
        "runtime_patch": runtime_patch,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize a TaskBeacon repo in a workspace")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--target-path", required=True)
    parser.add_argument("--ref", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = materialize_taskbeacon_repo(
        workspace_root=args.workspace_root,
        repo=args.repo,
        target_path=args.target_path,
        ref=args.ref,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
