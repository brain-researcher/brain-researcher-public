#!/usr/bin/env python3
"""Operator-side prod connectivity certification runner.

This script verifies:
- production MCP HTTP health + smoke surface
- ds000114 + fMRIPrep path discovery on prod
- pipeline_plan_validate + pipeline_execute for five connectivity workflows

It writes a local report bundle under:
`artifacts/prod_connectivity_certification/<timestamp>/`
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_researcher.services.mcp.execution_recipes import (  # noqa: E402
    _recipe_run_pack_payload,
)
from scripts.mcp.call_http_tool import (  # noqa: E402
    HttpMCPClient,
    ResearchLoggingSession,
    resolve_mcp_token,
    run_subprocess_with_trace,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


LOCAL_REPORT_ROOT = REPO_ROOT / "artifacts" / "prod_connectivity_certification"

DEFAULT_MCP_URL = os.environ.get("BR_MCP_HTTP_URL", "https://brain-researcher.com/mcp")
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_POLL_TIMEOUT_SECONDS = 1800.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS = 180.0
DEFAULT_REMOTE_OUTPUT_ROOT = "/app/artifacts/prod_connectivity_certification"
DEFAULT_REMOTE_WORK_ROOT = "/app/jobstore/prod_connectivity_certification"

DEFAULT_GCLOUD_VM_NAME = os.environ.get("BR_PROD_K3S_VM_NAME", "brain-researcher-vm")
DEFAULT_GCLOUD_ZONE = os.environ.get("BR_PROD_K3S_ZONE", "us-west1-b")
DEFAULT_GCLOUD_PROJECT = os.environ.get("BR_PROD_GCLOUD_PROJECT", "hai-gcp-dialogue-brain")
DEFAULT_K8S_NAMESPACE = "brain-researcher-core"
DEFAULT_SECRET_NAME = "brain-researcher-mcp-auth"
DEFAULT_SECRET_KEY = "BR_MCP_AUTH_TOKEN"
NON_PLAINTEXT_MCP_SECRET_KEYS = {
    "BR_MCP_AUTH_TOKENS_JSON",
    "BR_MCP_TOKEN_PEPPER",
}
DEFAULT_MCP_POD_PREFIX = "brain-researcher-mcp-"
DEFAULT_AGENT_POD = "brain-researcher-agent-0"

DATASET_ID = "ds000114"
TASK = "linebisection"
SESSION = "ses-test"
SPACE = "MNI152NLin2009cAsym"
RESOLUTION = "res-2"
SINGLE_SUBJECT = "sub-01"
GROUP_SUBJECTS = ("sub-01", "sub-02", "sub-03", "sub-06")
GROUP_LABELS = [0, 0, 1, 1]
DEFAULT_SEED_COORDS = [0.0, -52.0, 18.0]

WORKFLOW_IDS = (
    "workflow_rest_connectome_e2e",
    "workflow_seed_based_connectivity",
    "workflow_network_based_statistics",
    "workflow_connectivity_gradients",
    "workflow_group_ica",
)

REQUIRED_MCP_TOOLS = {
    "server_info",
    "dataset_get_resources",
    "get_execution_recipe",
    "pipeline_plan_validate",
    "pipeline_execute",
    "run_get",
}

ARTIFACT_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "workflow_rest_connectome_e2e": {
        "required_outputs": [
            "timeseries/timeseries.npy",
            "timeseries/timeseries.csv",
            "connectivity_matrix.npy",
        ],
        "optional_outputs": [
            "atlas/*.nii.gz",
            "atlas/*_labels.tsv",
            "atlas/*_labels.json",
            "timeseries/timeseries_summary.json",
        ],
    },
    "workflow_seed_based_connectivity": {
        "required_outputs": ["seed_based_fc.nii.gz"],
        "optional_outputs": [],
    },
    "workflow_connectivity_gradients": {
        "required_outputs": [
            "connectivity.npy",
            "gradients/graph_metrics.json",
            "gradients/graph_summary.json",
        ],
        "optional_outputs": [
            "gradients/thresholded_connectivity.npy",
            "gradients/communities.json",
            "gradients/graph_theory_plot.png",
        ],
    },
    "workflow_group_ica": {
        "required_outputs": [
            "group_ica/canica_components.nii.gz",
            "group_ica/canica_timecourses.npy",
            "group_ica/connectivity.npy",
            "group_ica/nbs.npy",
        ],
        "optional_outputs": [
            "group_ica/canica_summary.json",
            "group_ica/nbs.mask.npy",
            "group_ica/nbs.components.json",
            "group_ica/nbs.json",
        ],
    },
    "workflow_network_based_statistics": {
        "required_outputs": [
            "group_connectivity.npy",
            "nbs.npy",
            "nbs.mask.npy",
            "nbs.components.json",
        ],
        "optional_outputs": ["nbs.json"],
    },
}

PRECONDITION_CODES = {
    "domain_not_allowed",
    "missing_required_secrets",
    "network_blocked",
    "params_invalid",
    "params_missing_required",
    "path_not_allowed",
    "tool_execute_disabled",
    "tool_not_allowlisted",
}

PRECONDITION_MARKERS = (
    "atlas",
    "bids directory not found",
    "confounds",
    "dataset not found",
    "fastsurfer requires a freesurfer license file",
    "file not found",
    "fmriprep",
    "freeSurfer license".lower(),
    "input file not found",
    "missing",
    "mount path does not exist",
    "no matching",
    "no such file or directory",
    "not found",
    "operation not permitted",
    "path_not_allowed",
    "permission denied",
    "plan_invalid",
    "requires secrets/env vars that are not set",
)

_ACTIVE_RESEARCH_LOGGER: ResearchLoggingSession | None = None


class SurfaceError(RuntimeError):
    """Raised when the MCP/HTTP surface is not callable."""


@dataclass(frozen=True)
class WorkflowPlan:
    workflow_id: str
    plan: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def emit_progress(report_dir: Path, message: str, **extra: Any) -> None:
    payload = {"ts": utc_now_iso(), "message": message}
    if extra:
        payload.update(extra)
    append_jsonl(report_dir / "progress.jsonl", payload)
    if _ACTIVE_RESEARCH_LOGGER is not None:
        _ACTIVE_RESEARCH_LOGGER.record_progress(message, **extra)
    print(message, file=sys.stderr)


def _run_subprocess(
    cmd: list[str],
    *,
    timeout_s: float,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return run_subprocess_with_trace(
        cmd,
        timeout_s=timeout_s,
        check=check,
        logger=_ACTIVE_RESEARCH_LOGGER,
    )


def _close_research_logger(
    *,
    logger: ResearchLoggingSession | None,
    report_dir: Path,
    report: dict[str, Any],
    exit_code: int,
) -> None:
    global _ACTIVE_RESEARCH_LOGGER
    if logger is None or logger.client is None:
        _ACTIVE_RESEARCH_LOGGER = None
        return

    summary = dict(report.get("summary") or {})
    total = int(summary.get("total") or 0)
    verified = int(summary.get("verified") or 0)
    done = [
        f"Saved report bundle to {report_dir}",
        f"Verified {verified}/{total} workflows",
        f"Exit code {exit_code}",
    ]
    open_items: list[str] = []
    if int(summary.get("failed_surface") or 0):
        open_items.append("Investigate MCP surface failures in report.json")
    if int(summary.get("failed_precondition") or 0):
        open_items.append("Resolve workflow precondition failures")
    if int(summary.get("failed_code") or 0):
        open_items.append("Investigate workflow execution failures")
    if not report.get("health", {}).get("ok", False):
        open_items.append("Restore MCP health probe")
    next_command = (
        f"cat {report_dir / 'summary.txt'}"
        if (report_dir / "summary.txt").exists()
        else f"cat {report_dir / 'report.json'}"
    )
    try:
        logger.close(
            goal="Run production connectivity workflow certification over MCP HTTP.",
            done=done,
            open_items=open_items,
            next_command=next_command,
            tags=["ops", "prod", "certification", "connectivity"],
        )
    finally:
        _ACTIVE_RESEARCH_LOGGER = None


def _gcloud_ssh_cmd(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    remote_command: str,
) -> list[str]:
    cmd = ["gcloud", "compute", "ssh", vm_name, "--zone", zone]
    if project and project.strip():
        cmd.extend(["--project", project.strip()])
    cmd.extend(["--command", remote_command])
    return cmd


def run_remote_command(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    remote_command: str,
    timeout_s: float,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _run_subprocess(
        _gcloud_ssh_cmd(
            vm_name=vm_name,
            zone=zone,
            project=project,
            remote_command=remote_command,
        ),
        timeout_s=timeout_s,
        check=check,
    )


def _kubectl_exec_python(*, pod: str, namespace: str, code: str, args: list[str]) -> str:
    argv = " ".join(shlex.quote(str(item)) for item in args)
    script = (
        "python - <<'PY' "
        + argv
        + "\n"
        + code.rstrip()
        + "\nPY"
    ).strip()
    return _kubectl_exec_bash(pod=pod, namespace=namespace, script=script)


def _kubectl_exec_bash(*, pod: str, namespace: str, script: str) -> str:
    return (
        "sudo k3s kubectl "
        f"-n {shlex.quote(namespace)} exec {shlex.quote(pod)} -- "
        "bash -lc "
        f"{shlex.quote(script)}"
    )


def resolve_prod_mcp_token(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    secret_name: str,
    secret_key: str,
    timeout_s: float,
) -> str:
    local_token = resolve_mcp_token()
    if local_token:
        return local_token

    if not vm_name.strip():
        raise ValueError("gcloud VM name is required")
    if not zone.strip():
        raise ValueError("gcloud zone is required")

    remote_cmd = (
        "sudo k3s kubectl "
        f"-n {namespace} get secret {secret_name} -o json"
    )
    cmd = ["gcloud", "compute", "ssh", vm_name, "--zone", zone]
    if project and project.strip():
        cmd.extend(["--project", project.strip()])
    cmd.extend(["--command", remote_cmd])

    proc = _run_subprocess(cmd, timeout_s=timeout_s, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or "gcloud token resolution failed").strip()
        )

    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("resolved secret manifest is empty")

    try:
        payload = json.loads(raw)
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"failed to parse secret manifest: {exc}") from exc

    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"secret {secret_name!r} did not include a data map")

    if secret_key in NON_PLAINTEXT_MCP_SECRET_KEYS:
        raise RuntimeError(
            "selected secret key stores keyed-token metadata, not a plaintext MCP bearer token; "
            "provide --mcp-token, set BR_MCP_TOKEN locally, or authenticate via JWT"
        )

    raw_secret = str(data.get(secret_key) or "").strip()
    if raw_secret:
        try:
            decoded = base64.b64decode(raw_secret, validate=True).decode("utf-8").strip()
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"failed to decode secret payload: {exc}") from exc
        if not decoded:
            raise RuntimeError("decoded secret payload is empty")
        return decoded

    if NON_PLAINTEXT_MCP_SECRET_KEYS.issubset(data):
        raise RuntimeError(
            "prod MCP auth secret is configured in keyed-token mode "
            "(BR_MCP_AUTH_TOKENS_JSON + BR_MCP_TOKEN_PEPPER); no plaintext bearer token "
            "can be recovered from the cluster secret. Provide --mcp-token, set "
            "BR_MCP_TOKEN locally, or authenticate via JWT."
        )

    available_keys = ", ".join(sorted(data)) or "<none>"
    raise RuntimeError(
        f"secret key {secret_key!r} was not found in {secret_name!r}; available keys: {available_keys}"
    )


def resolve_mcp_pod(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod_name: str | None,
    timeout_s: float,
) -> str:
    explicit = str(pod_name or "").strip()
    if explicit:
        return explicit

    remote_cmd = (
        "sudo k3s kubectl "
        f"-n {shlex.quote(namespace)} get pods -o name"
    )
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=remote_cmd,
        timeout_s=timeout_s,
        check=True,
    )
    for line in (proc.stdout or "").splitlines():
        item = line.strip()
        if item.startswith("pod/" + DEFAULT_MCP_POD_PREFIX):
            return item.split("/", 1)[1]
    raise RuntimeError("no prod MCP pod matched expected prefix")


def stage_recipe_files(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    remote_dir: str,
    files: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    payload_b64 = base64.b64encode(
        json.dumps(files, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    code = """
import base64, json, os, stat, sys
from pathlib import Path

remote_dir = Path(sys.argv[1]).resolve()
files = json.loads(base64.b64decode(sys.argv[2].encode('ascii')).decode('utf-8'))
remote_dir.mkdir(parents=True, exist_ok=True)
for name, text in files.items():
    path = (remote_dir / name).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding='utf-8')
    if path.suffix == '.sh':
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
print(json.dumps({'ok': True, 'recipe_dir': str(remote_dir), 'file_count': len(files)}, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[remote_dir, payload_b64],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def execute_remote_recipe(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    recipe_dir: str,
    recipe_payload: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    recipe = recipe_payload.get("recipe")
    recipe = recipe if isinstance(recipe, dict) else {}
    setup_commands = [
        str(item).strip()
        for item in (recipe.get("setup_commands") or [])
        if str(item).strip()
    ]
    run_command = str(recipe.get("run_command") or "").strip()
    if not run_command:
        raise RuntimeError("recipe missing run_command")
    lines = [
        "set -euo pipefail",
        "export BRAIN_RESEARCHER_REPO=/app",
        f"cd {shlex.quote(recipe_dir)}",
        *setup_commands,
        run_command,
    ]
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_bash(
            pod=pod,
            namespace=namespace,
            script="\n".join(lines),
        ),
        timeout_s=timeout_s,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-4000:],
        "recipe_dir": recipe_dir,
    }


def _health_candidates(mcp_url: str) -> list[str]:
    parts = urlsplit(mcp_url)
    candidates: list[str] = []
    mount_health = parts.path.rstrip("/") + "/healthz"
    candidates.append(urlunsplit((parts.scheme, parts.netloc, mount_health, "", "")))
    candidates.append(urlunsplit((parts.scheme, parts.netloc, "/healthz", "", "")))

    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def probe_health(mcp_url: str, *, timeout_s: float) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for candidate in _health_candidates(mcp_url):
        proc = _run_subprocess(
            [
                "curl",
                "-sS",
                "-o",
                "-",
                "-w",
                "\\n%{http_code}",
                "--max-time",
                str(timeout_s),
                candidate,
            ],
            timeout_s=timeout_s + 1.0,
            check=False,
        )
        body, _, status_text = (proc.stdout or "").rpartition("\n")
        http_status = int(status_text) if status_text.isdigit() else None
        attempt = {
            "url": candidate,
            "return_code": proc.returncode,
            "http_status": http_status,
            "stdout": body[:500],
            "stderr": (proc.stderr or "")[:500],
        }
        attempts.append(attempt)
        if proc.returncode == 0 and http_status == 200:
            return {
                "ok": True,
                "url": candidate,
                "http_status": http_status,
                "body": body[:500],
                "attempts": attempts,
            }
        if (
            proc.returncode == 0
            and http_status == 401
            and candidate.endswith("/mcp/healthz")
            and "missing_bearer_token" in body
        ):
            return {
                "ok": True,
                "url": candidate,
                "http_status": http_status,
                "body": body[:500],
                "auth_challenge": True,
                "attempts": attempts,
            }
    return {"ok": False, "attempts": attempts}


def _workflow_output_dir(plan: dict[str, Any]) -> str:
    steps = plan.get("steps")
    if isinstance(steps, list) and steps:
        step = steps[-1]
        if isinstance(step, dict):
            return str(step.get("output_dir") or "").strip()
    return ""


def _direct_recipe_params(workflow: WorkflowPlan) -> dict[str, Any] | None:
    steps = workflow.plan.get("steps")
    if not isinstance(steps, list) or len(steps) != 1:
        return None
    step = steps[0]
    if not isinstance(step, dict) or str(step.get("tool") or "") != workflow.workflow_id:
        return None
    params = step.get("params")
    return dict(params) if isinstance(params, dict) else None


def verify_mcp_smoke(client: HttpMCPClient) -> dict[str, Any]:
    initialize_resp = client.initialize(prime=True)
    list_resp = client.rpc("tools/list", {})
    info_resp = client.call_tool("server_info", {}, prime=False, initialize=False)

    tool_names: list[str] = []
    if list_resp.get("ok"):
        envelope = list_resp.get("envelope") or {}
        result = envelope.get("result") if isinstance(envelope, dict) else None
        tools = result.get("tools") if isinstance(result, dict) else None
        if isinstance(tools, list):
            for item in tools:
                if isinstance(item, dict) and item.get("name"):
                    tool_names.append(str(item["name"]))

    missing_required = sorted(REQUIRED_MCP_TOOLS - set(tool_names))
    info_payload = info_resp.get("payload")
    smoke_ok = (
        bool(initialize_resp.get("ok"))
        and bool(list_resp.get("ok"))
        and bool(info_resp.get("ok"))
        and isinstance(info_payload, dict)
        and info_payload.get("ok") is True
        and not missing_required
    )

    return {
        "ok": smoke_ok,
        "initialize": initialize_resp,
        "tools_list": list_resp,
        "server_info": info_resp,
        "tool_names": tool_names,
        "missing_required_tools": missing_required,
    }


def get_local_recipe_payload(
    client: HttpMCPClient,
    workflow: WorkflowPlan,
) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
    params = _direct_recipe_params(workflow)
    if not params:
        return None, None
    response, payload = _require_tool_payload(
        client,
        "get_execution_recipe",
        {
            "tool_id": workflow.workflow_id,
            "params": params,
            "target_runtime": "python",
        },
    )
    if payload.get("ok") is not True:
        raise SurfaceError(
            str(payload.get("error") or "get_execution_recipe returned ok=false")
        )
    recipe = payload.get("recipe")
    recipe = dict(recipe) if isinstance(recipe, dict) else None
    dependencies = (
        dict(recipe.get("dependencies"))
        if isinstance(recipe, dict) and isinstance(recipe.get("dependencies"), dict)
        else {}
    )
    python_packages = [
        str(item).strip()
        for item in (dependencies.get("python_packages") or [])
        if str(item).strip()
    ]
    if recipe and "brain_researcher" in python_packages:
        extras = [pkg for pkg in python_packages if pkg != "brain_researcher"]
        extra_args = (
            " " + " ".join(shlex.quote(pkg) for pkg in extras) if extras else ""
        )
        recipe["required_env_vars"] = sorted(
            {
                *[
                    str(name).strip()
                    for name in (recipe.get("required_env_vars") or [])
                    if str(name).strip()
                ],
                "BRAIN_RESEARCHER_REPO",
            }
        )
        recipe["setup_commands"] = [
            "python -m venv .venv",
            ". .venv/bin/activate",
            "python -m pip install --upgrade pip",
            f'pip install -e "${{BRAIN_RESEARCHER_REPO}}"{extra_args}',
        ]
        payload["recipe"] = recipe
    if isinstance(payload.get("recipe"), dict):
        run_pack = _recipe_run_pack_payload(
            workflow.workflow_id,
            "python",
            dict(payload["recipe"]),
        )
        payload["run_pack"] = run_pack
        payload["local_run"] = run_pack
    return response, payload


def get_handoff_recipe_payload(
    client: HttpMCPClient,
    workflow: WorkflowPlan,
) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
    params = _direct_recipe_params(workflow)
    arguments: dict[str, Any] = {
        "tool_id": workflow.workflow_id,
        "target_runtime": "python",
    }
    if params:
        arguments["params"] = params
    response, payload = _require_tool_payload(
        client,
        "get_execution_recipe",
        arguments,
    )
    if payload.get("ok") is not True:
        raise SurfaceError(
            str(payload.get("error") or "get_execution_recipe returned ok=false")
        )
    if isinstance(payload.get("recipe"), dict):
        run_pack = _recipe_run_pack_payload(
            workflow.workflow_id,
            "python",
            dict(payload["recipe"]),
        )
        payload["run_pack"] = run_pack
        payload["local_run"] = run_pack
    return response, payload


def _attach_run_pack(
    result: dict[str, Any],
    run_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    if run_pack:
        result["run_pack"] = dict(run_pack)
        result["local_run"] = dict(run_pack)
    return result


def inspect_remote_output_dir(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    output_dir: str,
    timeout_s: float,
) -> dict[str, Any]:
    code = """
import json, sys
from pathlib import Path

output_dir = Path(sys.argv[1]).resolve()
payload = {"output_dir": str(output_dir), "exists": output_dir.exists(), "files": {}}
if output_dir.exists():
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(output_dir).as_posix()
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
        payload["files"][rel] = {
            "path": str(path),
            "size_bytes": size_bytes,
        }
payload["file_count"] = len(payload["files"])
print(json.dumps(payload, indent=2, sort_keys=True))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[output_dir],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def _match_output_patterns(
    files: dict[str, Any],
    patterns: list[str],
) -> dict[str, list[str]]:
    matched: dict[str, list[str]] = {}
    names = sorted(files.keys())
    for pattern in patterns:
        matched[pattern] = [
            name for name in names if fnmatch.fnmatch(name, pattern)
        ]
    return matched


def validate_remote_artifacts(
    *,
    workflow_id: str,
    inspected: dict[str, Any],
) -> dict[str, Any]:
    contract = ARTIFACT_CONTRACTS.get(workflow_id)
    if not contract:
        raise RuntimeError(f"missing artifact contract for {workflow_id}")
    files = inspected.get("files")
    files = files if isinstance(files, dict) else {}
    required = list(contract.get("required_outputs") or [])
    optional = list(contract.get("optional_outputs") or [])
    required_matches = _match_output_patterns(files, required)
    optional_matches = _match_output_patterns(files, optional)
    missing_required = [
        pattern for pattern, matches in required_matches.items() if not matches
    ]
    payload = {
        "workflow_id": workflow_id,
        "output_dir": inspected.get("output_dir"),
        "exists": bool(inspected.get("exists")),
        "file_count": inspected.get("file_count"),
        "files": files,
        "required_matches": required_matches,
        "optional_matches": optional_matches,
        "missing_required": missing_required,
        "ok": bool(inspected.get("exists")) and not missing_required,
    }
    return payload


def _stream_subprocess_to_file(
    cmd: list[str],
    *,
    destination: Path,
    timeout_s: float,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.PIPE)
        try:
            _, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.communicate()
            if destination.exists():
                destination.unlink()
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout_s) from exc
    stderr_text = (stderr or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        if destination.exists():
            destination.unlink()
        raise RuntimeError(stderr_text or f"command failed: {' '.join(cmd)}")
    return {
        "local_path": str(destination),
        "size_bytes": destination.stat().st_size if destination.exists() else 0,
        "stderr": stderr_text,
    }


def _safe_extract_tarball(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise RuntimeError(f"unsafe tar member path: {member.name}")
        handle.extractall(destination)


def download_remote_output_dir(
    *,
    report_dir: Path,
    workflow_id: str,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    output_dir: str,
    timeout_s: float,
) -> dict[str, Any]:
    workflow_dir = report_dir / workflow_id
    downloads_dir = workflow_dir / "downloaded_artifacts"
    archive_path = downloads_dir / "output_dir.tar.gz"
    extracted_dir = downloads_dir / "output_dir"
    remote = Path(output_dir)
    remote_command = _kubectl_exec_bash(
        pod=pod,
        namespace=namespace,
        script=(
            f"tar -C {shlex.quote(str(remote.parent))} -czf - "
            f"{shlex.quote(remote.name)}"
        ),
    )
    download_meta = _stream_subprocess_to_file(
        _gcloud_ssh_cmd(
            vm_name=vm_name,
            zone=zone,
            project=project,
            remote_command=remote_command,
        ),
        destination=archive_path,
        timeout_s=timeout_s,
    )
    _safe_extract_tarball(archive_path, extracted_dir)
    file_count = sum(1 for path in extracted_dir.rglob("*") if path.is_file())
    payload = {
        "ok": True,
        "download_dir": str(downloads_dir),
        "archive": download_meta,
        "extracted_dir": str(extracted_dir),
        "file_count": file_count,
    }
    write_json(workflow_dir / "downloaded_artifacts.json", payload)
    return payload


def download_remote_file(
    *,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    remote_path: str,
    destination: Path,
    timeout_s: float,
) -> dict[str, Any]:
    remote_command = _kubectl_exec_bash(
        pod=pod,
        namespace=namespace,
        script=f"cat {shlex.quote(remote_path)}",
    )
    download_meta = _stream_subprocess_to_file(
        _gcloud_ssh_cmd(
            vm_name=vm_name,
            zone=zone,
            project=project,
            remote_command=remote_command,
        ),
        destination=destination,
        timeout_s=timeout_s,
    )
    return {
        "ok": True,
        "remote_path": remote_path,
        "local_path": str(destination),
        **download_meta,
    }


def _write_recipe_files_to_workspace(
    workspace: Path,
    files: dict[str, Any],
) -> list[str]:
    workspace.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    workspace_root = workspace.resolve()
    for name, text in files.items():
        path = (workspace / name).resolve()
        if workspace_root not in path.parents and path != workspace_root:
            raise RuntimeError(f"unsafe recipe file path: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding="utf-8")
        if path.suffix == ".sh":
            path.chmod(path.stat().st_mode | 0o111)
        written.append(path.relative_to(workspace_root).as_posix())
    return sorted(written)


def _copy_path_into_bundle(
    *,
    source: Path,
    destination: Path,
) -> list[str]:
    written: list[str] = []
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return [destination.name]
    if not source.is_dir():
        return []
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        written.append(target.relative_to(destination).as_posix())
    return written


def _bundled_relative_path(path: Path, workspace: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


def _extract_run_steps(run_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(run_payload, dict):
        return []
    run = run_payload.get("run")
    if not isinstance(run, dict):
        return []
    steps = run.get("steps")
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _find_remote_reference_inputs(
    *,
    workflow_id: str,
    run_payload: dict[str, Any] | None,
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for step in _extract_run_steps(run_payload):
        params = step.get("params")
        if not isinstance(params, dict):
            continue
        for key in ("atlas", "atlas_path"):
            value = str(params.get(key) or "").strip()
            if not value or not value.startswith("/"):
                continue
            ref_key = ("atlas", value)
            if ref_key in seen:
                continue
            seen.add(ref_key)
            refs.append({"kind": "atlas", "remote_path": value, "param_key": key})
    return refs


def _patch_handoff_params(
    *,
    workflow_id: str,
    params: dict[str, Any],
    bundled_inputs: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    patched = dict(params)
    missing_inputs: list[str] = []
    output_dir = str(patched.get("output_dir") or "").strip()
    if not output_dir or output_dir.startswith("/"):
        patched["output_dir"] = f"./outputs/out/{workflow_id}"
    if workflow_id == "workflow_rest_connectome_e2e":
        atlas_path = bundled_inputs.get("atlas_path")
        if atlas_path:
            patched["atlas_path"] = atlas_path
        if not str(patched.get("img") or "").strip():
            patched["img"] = "<set-local-bold.nii.gz>"
            missing_inputs.append("img")
    elif workflow_id == "workflow_connectivity_gradients":
        timeseries = bundled_inputs.get("timeseries")
        if timeseries:
            patched["timeseries"] = timeseries
        elif not str(patched.get("timeseries") or "").strip():
            patched["timeseries"] = "<set-local-timeseries.npy>"
            missing_inputs.append("timeseries")
    return patched, missing_inputs


def build_handoff_bundle(
    *,
    report_dir: Path,
    workflow_id: str,
    recipe_payload: dict[str, Any] | None,
    run_pack: dict[str, Any] | None,
    downloaded_artifacts: dict[str, Any] | None,
    run_payload: dict[str, Any] | None,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    timeout_s: float,
) -> dict[str, Any]:
    if not isinstance(recipe_payload, dict):
        return {"ok": False, "reason": "missing_recipe_payload"}
    if not isinstance(run_pack, dict):
        return {"ok": False, "reason": "missing_run_pack"}
    recipe = recipe_payload.get("recipe")
    files = dict(recipe.get("files") or {}) if isinstance(recipe, dict) else {}
    if not files:
        return {"ok": False, "reason": "missing_recipe_files"}

    workflow_dir = report_dir / workflow_id
    bundle_dir = workflow_dir / "handoff_bundle"
    workspace_name = Path(str(run_pack.get("workspace") or f"./{workflow_id}_recipe")).name
    workspace = bundle_dir / workspace_name
    workspace.mkdir(parents=True, exist_ok=True)
    written_files = _write_recipe_files_to_workspace(workspace, files)

    original_params_path = workspace / "params.json"
    params = {}
    if original_params_path.exists():
        try:
            params = json.loads(original_params_path.read_text(encoding="utf-8"))
        except Exception:
            params = {}
        recipe_params_copy = workspace / "params.recipe.json"
        recipe_params_copy.write_text(
            original_params_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        if "params.recipe.json" not in written_files:
            written_files.append("params.recipe.json")

    bundled_inputs_root = workspace / "bundled_inputs"
    bundled_inputs_root.mkdir(parents=True, exist_ok=True)
    bundled_inputs: list[dict[str, Any]] = []
    param_overrides: dict[str, str] = {}

    extracted_dir = Path(
        str((downloaded_artifacts or {}).get("extracted_dir") or "")
    ).expanduser()
    if extracted_dir.exists():
        atlas_candidates = sorted(extracted_dir.rglob("atlas/*.nii.gz"))
        if atlas_candidates:
            atlas_src = atlas_candidates[0]
            atlas_dst = bundled_inputs_root / "atlas" / atlas_src.name
            _copy_path_into_bundle(source=atlas_src, destination=atlas_dst)
            atlas_rel = _bundled_relative_path(atlas_dst, workspace)
            param_overrides["atlas_path"] = atlas_rel
            bundled_inputs.append(
                {
                    "kind": "atlas",
                    "source": "downloaded_artifacts",
                    "path": str(atlas_dst),
                    "relative_path": atlas_rel,
                }
            )
        timeseries_candidates = sorted(extracted_dir.rglob("timeseries/timeseries.npy"))
        if timeseries_candidates:
            ts_src = timeseries_candidates[0]
            ts_dst = bundled_inputs_root / "timeseries" / ts_src.name
            _copy_path_into_bundle(source=ts_src, destination=ts_dst)
            ts_rel = _bundled_relative_path(ts_dst, workspace)
            param_overrides["timeseries"] = ts_rel
            bundled_inputs.append(
                {
                    "kind": "timeseries",
                    "source": "downloaded_artifacts",
                    "path": str(ts_dst),
                    "relative_path": ts_rel,
                }
            )
            csv_src = ts_src.with_suffix(".csv")
            if csv_src.exists():
                csv_dst = bundled_inputs_root / "timeseries" / csv_src.name
                _copy_path_into_bundle(source=csv_src, destination=csv_dst)
                bundled_inputs.append(
                    {
                        "kind": "timeseries_csv",
                        "source": "downloaded_artifacts",
                        "path": str(csv_dst),
                        "relative_path": _bundled_relative_path(csv_dst, workspace),
                    }
                )

    if "atlas_path" not in param_overrides:
        for ref in _find_remote_reference_inputs(
            workflow_id=workflow_id,
            run_payload=run_payload,
        ):
            if ref.get("kind") != "atlas":
                continue
            remote_path = str(ref.get("remote_path") or "").strip()
            if not remote_path:
                continue
            atlas_dst = bundled_inputs_root / "atlas" / Path(remote_path).name
            download_remote_file(
                vm_name=vm_name,
                zone=zone,
                project=project,
                namespace=namespace,
                pod=pod,
                remote_path=remote_path,
                destination=atlas_dst,
                timeout_s=timeout_s,
            )
            atlas_rel = _bundled_relative_path(atlas_dst, workspace)
            param_overrides["atlas_path"] = atlas_rel
            bundled_inputs.append(
                {
                    "kind": "atlas",
                    "source": "remote_input",
                    "remote_path": remote_path,
                    "path": str(atlas_dst),
                    "relative_path": atlas_rel,
                }
            )
            break

    patched_params, missing_inputs = _patch_handoff_params(
        workflow_id=workflow_id,
        params=params,
        bundled_inputs=param_overrides,
    )
    original_params_path.write_text(
        json.dumps(patched_params, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    params_local_path = workspace / "params.local.json"
    params_local_path.write_text(
        json.dumps(patched_params, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if "params.local.json" not in written_files:
        written_files.append("params.local.json")

    payload = {
        "ok": True,
        "bundle_dir": str(bundle_dir),
        "workspace": str(workspace),
        "workspace_name": workspace_name,
        "written_files": sorted(written_files),
        "bundled_inputs": bundled_inputs,
        "params_json": str(original_params_path),
        "params_local_json": str(params_local_path),
        "missing_inputs": missing_inputs,
    }
    write_json(workflow_dir / "handoff_bundle.json", payload)
    return payload


def _attach_handoff_bundle(
    result: dict[str, Any],
    *,
    report_dir: Path,
    workflow: WorkflowPlan,
    recipe_payload: dict[str, Any] | None,
    run_pack: dict[str, Any] | None,
    downloaded_artifacts: dict[str, Any] | None,
    run_payload: dict[str, Any] | None,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    pod: str,
    timeout_s: float,
) -> dict[str, Any]:
    try:
        handoff_bundle = build_handoff_bundle(
            report_dir=report_dir,
            workflow_id=workflow.workflow_id,
            recipe_payload=recipe_payload,
            run_pack=run_pack,
            downloaded_artifacts=downloaded_artifacts,
            run_payload=run_payload,
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=pod,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        handoff_bundle = {"ok": False, "reason": "handoff_bundle_failed", "error": str(exc)}
        write_json(report_dir / workflow.workflow_id / "handoff_bundle.json", handoff_bundle)
    result["handoff_bundle"] = handoff_bundle
    return result


def _require_tool_payload(
    client: HttpMCPClient,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.call_tool(tool_name, arguments, prime=False, initialize=True)
    if not response.get("ok"):
        raise SurfaceError(
            f"{tool_name} transport failed: {response.get('http_status')} "
            f"{response.get('envelope') or response.get('error')}"
        )
    payload = response.get("payload")
    if not isinstance(payload, dict):
        raise SurfaceError(f"{tool_name} returned non-object payload")
    return response, payload


def discover_prod_inputs(
    client: HttpMCPClient,
    *,
    atlas_path: str | None = None,
) -> dict[str, Any]:
    _resp, payload = _require_tool_payload(
        client,
        "dataset_get_resources",
        {"dataset_ref": DATASET_ID},
    )
    if payload.get("ok") is not True:
        raise RuntimeError(str(payload.get("error") or "dataset_get_resources failed"))

    resources = payload.get("resources")
    if not isinstance(resources, dict):
        raise RuntimeError("dataset_get_resources returned invalid resources payload")

    bids_root = str(resources.get("bids_path") or "").strip()
    derivatives = resources.get("derivatives")
    derivatives = derivatives if isinstance(derivatives, dict) else {}
    fmriprep_root = str(derivatives.get("fmriprep") or "").strip()
    if not bids_root:
        raise RuntimeError(f"{DATASET_ID} missing BIDS root in dataset resources")
    if not fmriprep_root:
        raise RuntimeError(f"{DATASET_ID} missing fMRIPrep root in dataset resources")

    atlas_candidates = [
        item
        for item in [
            atlas_path,
            os.environ.get("BR_SCHAEFER100_ATLAS"),
            "/app/data/atlases/schaefer_2018/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
            "/data/atlases/schaefer_2018/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
            "/app/data/br-kg/raw/nilearn_atlases/schaefer_2018/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
            "/data/br-kg/raw/nilearn_atlases/schaefer_2018/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
        ]
        if item
    ]

    def _func_dir(subject_label: str) -> str:
        return f"{fmriprep_root}/{subject_label}/{SESSION}/func"

    def _bold(subject_label: str) -> str:
        return (
            f"{_func_dir(subject_label)}/"
            f"{subject_label}_{SESSION}_task-{TASK}_space-{SPACE}_{RESOLUTION}_desc-preproc_bold.nii.gz"
        )

    def _mask(subject_label: str) -> str:
        return (
            f"{_func_dir(subject_label)}/"
            f"{subject_label}_{SESSION}_task-{TASK}_space-{SPACE}_{RESOLUTION}_desc-brain_mask.nii.gz"
        )

    def _confounds(subject_label: str) -> str:
        return (
            f"{_func_dir(subject_label)}/"
            f"{subject_label}_{SESSION}_task-{TASK}_desc-confounds_timeseries.tsv"
        )

    return {
        "dataset_id": DATASET_ID,
        "bids_root": bids_root,
        "participants_tsv": f"{bids_root}/participants.tsv",
        "fmriprep_root": fmriprep_root,
        "atlas_candidates": atlas_candidates,
        "atlas_path": atlas_candidates[0] if atlas_candidates else "",
        "single_subject": SINGLE_SUBJECT,
        "single_subject_bold": _bold(SINGLE_SUBJECT),
        "single_subject_confounds": _confounds(SINGLE_SUBJECT),
        "single_subject_mask": _mask(SINGLE_SUBJECT),
        "group_subjects": list(GROUP_SUBJECTS),
        "group_subject_bolds": [_bold(subject) for subject in GROUP_SUBJECTS],
        "group_labels": list(GROUP_LABELS),
    }


def _step(
    *,
    step_id: str,
    tool: str,
    params: dict[str, Any],
    output_dir: str,
    work_dir: str,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "tool": tool,
        "params": params,
        "output_dir": output_dir,
        "work_dir": work_dir,
    }


def build_workflow_plans(
    discovered: dict[str, Any],
    *,
    remote_output_root: str,
    remote_work_root: str,
) -> list[WorkflowPlan]:
    atlas_path = str(discovered.get("atlas_path") or "")
    if not atlas_path:
        raise RuntimeError("no atlas path candidate available for certification")

    single_img = str(discovered["single_subject_bold"])
    single_confounds = str(discovered["single_subject_confounds"])
    single_mask = str(discovered["single_subject_mask"])
    group_imgs = list(discovered["group_subject_bolds"])
    labels = list(discovered["group_labels"])

    def out(*parts: str) -> str:
        return "/".join([remote_output_root.rstrip("/"), *parts])

    def work(*parts: str) -> str:
        return "/".join([remote_work_root.rstrip("/"), *parts])

    plans = [
        WorkflowPlan(
            workflow_id="workflow_rest_connectome_e2e",
            plan={
                "steps": [
                    _step(
                        step_id="rest_connectome",
                        tool="workflow_rest_connectome_e2e",
                        params={
                            "img": single_img,
                            "atlas_name": "Schaefer2018_100",
                            "atlas_path": atlas_path,
                            "connectivity_kind": "correlation",
                            "output_dir": out("workflow_rest_connectome_e2e"),
                        },
                        output_dir=out("workflow_rest_connectome_e2e"),
                        work_dir=work("workflow_rest_connectome_e2e"),
                    )
                ]
            },
        ),
        WorkflowPlan(
            workflow_id="workflow_seed_based_connectivity",
            plan={
                "steps": [
                    _step(
                        step_id="seed_based",
                        tool="workflow_seed_based_connectivity",
                        params={
                            "img": single_img,
                            "seed_coords": list(DEFAULT_SEED_COORDS),
                            "confounds": single_confounds,
                            "mask_img": single_mask,
                            "output_dir": out("workflow_seed_based_connectivity"),
                        },
                        output_dir=out("workflow_seed_based_connectivity"),
                        work_dir=work("workflow_seed_based_connectivity"),
                    )
                ]
            },
        ),
        WorkflowPlan(
            workflow_id="workflow_connectivity_gradients",
            plan={
                "steps": [
                    _step(
                        step_id="extract_ts",
                        tool="extract_timeseries",
                        params={
                            "img": single_img,
                            "atlas": atlas_path,
                            "output_dir": out(
                                "workflow_connectivity_gradients", "timeseries"
                            ),
                        },
                        output_dir=out("workflow_connectivity_gradients", "timeseries"),
                        work_dir=work("workflow_connectivity_gradients", "timeseries"),
                    ),
                    _step(
                        step_id="gradients",
                        tool="workflow_connectivity_gradients",
                        params={
                            "timeseries": "${steps.extract_ts.data.outputs.timeseries}",
                            "connectivity_kind": "correlation",
                            "output_dir": out("workflow_connectivity_gradients"),
                        },
                        output_dir=out("workflow_connectivity_gradients"),
                        work_dir=work("workflow_connectivity_gradients"),
                    ),
                ]
            },
        ),
        WorkflowPlan(
            workflow_id="workflow_group_ica",
            plan={
                "steps": [
                    _step(
                        step_id="group_ica",
                        tool="workflow_group_ica",
                        params={
                            "img": group_imgs,
                            "labels": labels,
                            "n_components": 10,
                            "threshold": 1.0,
                            "n_permutations": 20,
                            "output_dir": out("workflow_group_ica"),
                        },
                        output_dir=out("workflow_group_ica"),
                        work_dir=work("workflow_group_ica"),
                    )
                ]
            },
        ),
        WorkflowPlan(
            workflow_id="workflow_network_based_statistics",
            plan={
                "steps": [
                    _step(
                        step_id="group_ica_seed",
                        tool="workflow_group_ica",
                        params={
                            "img": group_imgs,
                            "labels": labels,
                            "n_components": 10,
                            "threshold": 1.0,
                            "n_permutations": 20,
                            "output_dir": out(
                                "workflow_network_based_statistics", "group_ica_seed"
                            ),
                        },
                        output_dir=out(
                            "workflow_network_based_statistics", "group_ica_seed"
                        ),
                        work_dir=work(
                            "workflow_network_based_statistics", "group_ica_seed"
                        ),
                    ),
                    _step(
                        step_id="nbs",
                        tool="workflow_network_based_statistics",
                        params={
                            "timeseries": "${steps.group_ica_seed.data.outputs.timecourses_file}",
                            "labels": labels,
                            "connectivity_kind": "correlation",
                            "threshold": 1.0,
                            "n_permutations": 20,
                            "output_dir": out("workflow_network_based_statistics"),
                        },
                        output_dir=out("workflow_network_based_statistics"),
                        work_dir=work("workflow_network_based_statistics"),
                    ),
                ]
            },
        ),
    ]
    return plans


def _issue_list_has_errors(issues: Any) -> bool:
    if not isinstance(issues, list):
        return False
    return any(isinstance(item, dict) and item.get("level") == "error" for item in issues)


def _extract_issue_codes(items: Any) -> set[str]:
    codes: set[str] = set()
    if not isinstance(items, list):
        return codes
    for item in items:
        if isinstance(item, dict) and item.get("code"):
            codes.add(str(item["code"]))
    return codes


def _looks_like_precondition_text(text: str | None) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in PRECONDITION_MARKERS)


def normalize_plan_for_execute(payload: dict[str, Any], fallback_plan: dict[str, Any]) -> dict[str, Any]:
    normalized = payload.get("normalized_plan")
    if not isinstance(normalized, dict):
        return fallback_plan
    execute_plan: dict[str, Any] = {"steps": normalized.get("steps") or fallback_plan["steps"]}
    project_root = normalized.get("project_root")
    if project_root:
        execute_plan["project_root"] = project_root
    return execute_plan


def classify_workflow_result(
    *,
    validate_payload: dict[str, Any] | None,
    execute_payload: dict[str, Any] | None,
    run_payload: dict[str, Any] | None,
    poll_error: str | None = None,
    surface_error: str | None = None,
) -> tuple[str, str]:
    if surface_error:
        return "failed_surface", surface_error

    if poll_error:
        return "failed_surface", poll_error

    if isinstance(validate_payload, dict):
        validate_codes = _extract_issue_codes(validate_payload.get("issues"))
        validate_codes |= _extract_issue_codes(validate_payload.get("policy_issues"))
        if validate_payload.get("ok") is not True or _issue_list_has_errors(
            validate_payload.get("issues")
        ):
            if validate_codes & PRECONDITION_CODES or validate_codes:
                return "failed_precondition", str(
                    validate_payload.get("error")
                    or (validate_payload.get("issues") or [{}])[0].get("message")
                    or "validation_precondition_failed"
                )
            return "failed_code", str(validate_payload.get("error") or "validation_failed")

    if isinstance(execute_payload, dict) and execute_payload.get("ok") is not True:
        execute_codes = _extract_issue_codes(execute_payload.get("issues"))
        execute_codes |= _extract_issue_codes(execute_payload.get("policy_issues"))
        error_text = str(execute_payload.get("error") or "")
        if error_text == "plan_invalid" or execute_codes:
            return "failed_precondition", error_text or "plan_invalid"
        return "failed_code", error_text or "pipeline_execute_failed"

    if isinstance(run_payload, dict):
        run = run_payload.get("run")
        if isinstance(run, dict):
            status = str(run.get("status") or "")
            if status == "succeeded":
                return "verified", "run_succeeded"
            if status in {"failed", "cancelled"}:
                texts = [str(run.get("error") or "")]
                codes = set()
                for step in run.get("steps") or []:
                    if not isinstance(step, dict):
                        continue
                    texts.append(str(step.get("error") or ""))
                    codes |= _extract_issue_codes(step.get("policy_issues"))
                joined = " | ".join(part for part in texts if part).strip()
                if codes & PRECONDITION_CODES or _looks_like_precondition_text(joined):
                    return "failed_precondition", joined or status
                return "failed_code", joined or status
            return "failed_surface", f"unexpected_run_status:{status or 'unknown'}"

    return "failed_surface", "missing_terminal_run_payload"


def wait_for_run(
    client: HttpMCPClient,
    run_id: str,
    *,
    timeout_s: float,
    poll_interval_s: float,
    report_dir: Path,
    workflow_id: str,
) -> dict[str, Any]:
    started = time.time()
    deadline = started + timeout_s
    attempts = 0
    last_payload: dict[str, Any] | None = None
    last_response: dict[str, Any] | None = None

    while time.time() < deadline:
        attempts += 1
        response = client.call_tool(
            "run_get",
            {"run_id": run_id},
            prime=False,
            initialize=True,
        )
        last_response = response
        if not response.get("ok"):
            emit_progress(
                report_dir,
                f"[poll] {workflow_id} run_id={run_id} transport_error={response.get('http_status')}",
                workflow_id=workflow_id,
                run_id=run_id,
                attempts=attempts,
                http_status=response.get("http_status"),
            )
            time.sleep(poll_interval_s)
            continue
        payload = response.get("payload")
        if not isinstance(payload, dict):
            emit_progress(
                report_dir,
                f"[poll] {workflow_id} run_id={run_id} non_object_payload",
                workflow_id=workflow_id,
                run_id=run_id,
                attempts=attempts,
            )
            time.sleep(poll_interval_s)
            continue
        if payload.get("ok") is not True:
            return {
                "ok": False,
                "error": str(payload.get("error") or "run_get returned ok=false"),
                "payload": payload,
                "attempts": attempts,
            }
        last_payload = payload
        run = payload.get("run")
        status = str(run.get("status") or "") if isinstance(run, dict) else ""
        emit_progress(
            report_dir,
            f"[poll] {workflow_id} run_id={run_id} status={status or 'unknown'} attempt={attempts}",
            workflow_id=workflow_id,
            run_id=run_id,
            status=status,
            attempts=attempts,
        )
        if payload.get("ok") is True and status in {"succeeded", "failed", "cancelled"}:
            return {
                "ok": True,
                "payload": payload,
                "attempts": attempts,
                "elapsed_s": round(time.time() - started, 3),
            }
        time.sleep(poll_interval_s)

    return {
        "ok": False,
        "error": "run_poll_timeout",
        "payload": last_payload,
        "response": last_response,
        "attempts": attempts,
        "elapsed_s": round(time.time() - started, 3),
    }


def certify_workflow(
    client: HttpMCPClient,
    workflow: WorkflowPlan,
    *,
    dry_run: bool,
    poll_timeout_s: float,
    poll_interval_s: float,
    report_dir: Path,
    vm_name: str,
    zone: str,
    project: str | None,
    namespace: str,
    artifact_pod: str,
    agent_pod: str,
    artifact_download_timeout_s: float,
) -> dict[str, Any]:
    workflow_dir = report_dir / workflow.workflow_id
    workflow_dir.mkdir(parents=True, exist_ok=True)
    write_json(workflow_dir / "plan.request.json", workflow.plan)
    run_pack = None
    local_recipe_payload = None
    try:
        recipe_response, recipe_payload = get_local_recipe_payload(client, workflow)
    except SurfaceError as exc:
        recipe_response = None
        recipe_payload = None
        local_run_error = str(exc)
        write_json(
            workflow_dir / "recipe.error.json",
            {"workflow_id": workflow.workflow_id, "error": local_run_error},
        )
    else:
        local_recipe_payload = recipe_payload
        run_pack = (
            dict(recipe_payload.get("run_pack"))
            if isinstance(recipe_payload, dict)
            and isinstance(recipe_payload.get("run_pack"), dict)
            else None
        )
        if recipe_response is not None:
            write_json(workflow_dir / "recipe.response.json", recipe_response)
        if local_recipe_payload is not None:
            write_json(workflow_dir / "recipe.payload.json", local_recipe_payload)
        if run_pack:
            write_json(workflow_dir / "run_pack.json", run_pack)
            write_json(workflow_dir / "local_run.json", run_pack)

    recipe_output_dir = _workflow_output_dir(workflow.plan)
    if (
        isinstance(local_recipe_payload, dict)
        and local_recipe_payload.get("ok") is True
        and local_recipe_payload.get("hosted_via_br_mcp_service") is False
        and str(local_recipe_payload.get("target_runtime") or "") == "python"
    ):
        remote_recipe_dir = "/".join(
            [
                DEFAULT_REMOTE_WORK_ROOT.rstrip("/"),
                report_dir.name,
                workflow.workflow_id,
                "recipe",
            ]
        )
        recipe_files = (
            (local_recipe_payload.get("recipe") or {}).get("files")
            if isinstance(local_recipe_payload.get("recipe"), dict)
            else None
        )
        recipe_files = dict(recipe_files) if isinstance(recipe_files, dict) else {}
        try:
            staged = stage_recipe_files(
                vm_name=vm_name,
                zone=zone,
                project=project,
                namespace=namespace,
                pod=agent_pod,
                remote_dir=remote_recipe_dir,
                files=recipe_files,
                timeout_s=artifact_download_timeout_s,
            )
        except Exception as exc:
            result = {
                "workflow_id": workflow.workflow_id,
                "classification": "failed_surface",
                "reason": "recipe_stage_failed",
                "execution_mode": "local_recipe_on_agent",
                "output_dir": recipe_output_dir,
                "agent_pod": agent_pod,
                "error": str(exc),
            }
            result = _attach_run_pack(result, run_pack)
            write_json(workflow_dir / "result.json", result)
            return result
        write_json(workflow_dir / "recipe.stage.json", staged)
        emit_progress(
            report_dir,
            f"[workflow] execute {workflow.workflow_id} via local recipe on {agent_pod}",
            workflow_id=workflow.workflow_id,
            pod=agent_pod,
        )
        execution = execute_remote_recipe(
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=agent_pod,
            recipe_dir=remote_recipe_dir,
            recipe_payload=local_recipe_payload,
            timeout_s=poll_timeout_s,
        )
        write_json(workflow_dir / "recipe.execute.json", execution)
        if not execution.get("ok"):
            result = {
                "workflow_id": workflow.workflow_id,
                "classification": "failed_code",
                "reason": "recipe_execution_failed",
                "execution_mode": "local_recipe_on_agent",
                "output_dir": recipe_output_dir,
                "agent_pod": agent_pod,
                "execution": execution,
            }
            result = _attach_run_pack(result, run_pack)
            write_json(workflow_dir / "result.json", result)
            return result
        try:
            inspected = inspect_remote_output_dir(
                vm_name=vm_name,
                zone=zone,
                project=project,
                namespace=namespace,
                pod=agent_pod,
                output_dir=recipe_output_dir,
                timeout_s=artifact_download_timeout_s,
            )
        except Exception as exc:
            result = {
                "workflow_id": workflow.workflow_id,
                "classification": "failed_surface",
                "reason": "artifact_inspection_failed",
                "execution_mode": "local_recipe_on_agent",
                "output_dir": recipe_output_dir,
                "agent_pod": agent_pod,
                "execution": execution,
                "error": str(exc),
            }
            result = _attach_run_pack(result, run_pack)
            write_json(workflow_dir / "result.json", result)
            return result
        write_json(workflow_dir / "artifacts.inspect.json", inspected)
        artifacts = validate_remote_artifacts(
            workflow_id=workflow.workflow_id,
            inspected=inspected,
        )
        write_json(workflow_dir / "artifacts.json", artifacts)
        if not artifacts.get("ok"):
            result = {
                "workflow_id": workflow.workflow_id,
                "classification": "failed_code",
                "reason": "missing_artifacts",
                "execution_mode": "local_recipe_on_agent",
                "output_dir": recipe_output_dir,
                "agent_pod": agent_pod,
                "execution": execution,
                "artifacts": artifacts,
            }
            result = _attach_run_pack(result, run_pack)
            write_json(workflow_dir / "result.json", result)
            return result
        try:
            downloaded_artifacts = download_remote_output_dir(
                report_dir=report_dir,
                workflow_id=workflow.workflow_id,
                vm_name=vm_name,
                zone=zone,
                project=project,
                namespace=namespace,
                pod=agent_pod,
                output_dir=recipe_output_dir,
                timeout_s=artifact_download_timeout_s,
            )
        except Exception as exc:
            result = {
                "workflow_id": workflow.workflow_id,
                "classification": "failed_surface",
                "reason": "artifact_download_failed",
                "execution_mode": "local_recipe_on_agent",
                "output_dir": recipe_output_dir,
                "agent_pod": agent_pod,
                "execution": execution,
                "artifacts": artifacts,
                "error": str(exc),
            }
            result = _attach_run_pack(result, run_pack)
            write_json(workflow_dir / "result.json", result)
            return result
        result = {
            "workflow_id": workflow.workflow_id,
            "classification": "verified",
            "reason": "recipe_run_succeeded",
            "execution_mode": "local_recipe_on_agent",
            "output_dir": recipe_output_dir,
            "agent_pod": agent_pod,
            "execution": execution,
            "artifacts": artifacts,
            "downloaded_artifacts": downloaded_artifacts,
        }
        result = _attach_run_pack(result, run_pack)
        result = _attach_handoff_bundle(
            result,
            report_dir=report_dir,
            workflow=workflow,
            recipe_payload=local_recipe_payload,
            run_pack=run_pack,
            downloaded_artifacts=downloaded_artifacts,
            run_payload=None,
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=agent_pod,
            timeout_s=artifact_download_timeout_s,
        )
        write_json(workflow_dir / "result.json", result)
        return result

    emit_progress(report_dir, f"[workflow] validate {workflow.workflow_id}", workflow_id=workflow.workflow_id)

    try:
        validate_response, validate_payload = _require_tool_payload(
            client,
            "pipeline_plan_validate",
            {"plan": workflow.plan},
        )
    except SurfaceError as exc:
        classification, reason = classify_workflow_result(
            validate_payload=None,
            execute_payload=None,
            run_payload=None,
            surface_error=str(exc),
        )
        result = {
            "workflow_id": workflow.workflow_id,
            "classification": classification,
            "reason": reason,
        }
        result = _attach_run_pack(result, run_pack)
        write_json(workflow_dir / "result.json", result)
        return result

    write_json(workflow_dir / "validate.response.json", validate_response)

    execute_plan = normalize_plan_for_execute(validate_payload, workflow.plan)
    write_json(workflow_dir / "plan.execute.json", execute_plan)

    if validate_payload.get("ok") is not True or _issue_list_has_errors(
        validate_payload.get("issues")
    ):
        classification, reason = classify_workflow_result(
            validate_payload=validate_payload,
            execute_payload=None,
            run_payload=None,
        )
        result = {
            "workflow_id": workflow.workflow_id,
            "classification": classification,
            "reason": reason,
            "validate": validate_payload,
        }
        result = _attach_run_pack(result, run_pack)
        write_json(workflow_dir / "result.json", result)
        return result

    emit_progress(
        report_dir,
        f"[workflow] execute {workflow.workflow_id} dry_run={str(dry_run).lower()}",
        workflow_id=workflow.workflow_id,
        dry_run=dry_run,
    )

    try:
        execute_response, execute_payload = _require_tool_payload(
            client,
            "pipeline_execute",
            {"plan": execute_plan, "dry_run": bool(dry_run)},
        )
    except SurfaceError as exc:
        classification, reason = classify_workflow_result(
            validate_payload=validate_payload,
            execute_payload=None,
            run_payload=None,
            surface_error=str(exc),
        )
        result = {
            "workflow_id": workflow.workflow_id,
            "classification": classification,
            "reason": reason,
            "validate": validate_payload,
        }
        result = _attach_run_pack(result, run_pack)
        write_json(workflow_dir / "result.json", result)
        return result

    write_json(workflow_dir / "execute.response.json", execute_response)

    if execute_payload.get("ok") is not True:
        classification, reason = classify_workflow_result(
            validate_payload=validate_payload,
            execute_payload=execute_payload,
            run_payload=None,
        )
        result = {
            "workflow_id": workflow.workflow_id,
            "classification": classification,
            "reason": reason,
            "validate": validate_payload,
            "execute": execute_payload,
        }
        result = _attach_run_pack(result, run_pack)
        write_json(workflow_dir / "result.json", result)
        return result

    run_id = str(execute_payload.get("run_id") or "").strip()
    if not run_id:
        classification, reason = classify_workflow_result(
            validate_payload=validate_payload,
            execute_payload=execute_payload,
            run_payload=None,
            surface_error="pipeline_execute returned no run_id",
        )
        result = {
            "workflow_id": workflow.workflow_id,
            "classification": classification,
            "reason": reason,
            "validate": validate_payload,
            "execute": execute_payload,
        }
        result = _attach_run_pack(result, run_pack)
        write_json(workflow_dir / "result.json", result)
        return result

    poll = wait_for_run(
        client,
        run_id,
        timeout_s=poll_timeout_s,
        poll_interval_s=poll_interval_s,
        report_dir=report_dir,
        workflow_id=workflow.workflow_id,
    )
    write_json(workflow_dir / "run.poll.json", poll)

    run_payload = poll.get("payload") if poll.get("ok") else None
    classification, reason = classify_workflow_result(
        validate_payload=validate_payload,
        execute_payload=execute_payload,
        run_payload=run_payload if isinstance(run_payload, dict) else None,
        poll_error=None if poll.get("ok") else str(poll.get("error") or "run_poll_failed"),
    )
    output_dir = _workflow_output_dir(execute_plan) or _workflow_output_dir(workflow.plan)
    result = {
        "workflow_id": workflow.workflow_id,
        "classification": classification,
        "reason": reason,
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "output_dir": output_dir,
        "validate": validate_payload,
        "execute": execute_payload,
        "run": run_payload,
        "poll": poll,
    }
    result = _attach_run_pack(result, run_pack)
    if classification != "verified":
        write_json(workflow_dir / "result.json", result)
        return result

    try:
        inspected = inspect_remote_output_dir(
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=artifact_pod,
            output_dir=output_dir,
            timeout_s=artifact_download_timeout_s,
        )
    except Exception as exc:
        result.update(
            {
                "classification": "failed_surface",
                "reason": "artifact_inspection_failed",
                "artifact_pod": artifact_pod,
                "artifact_error": str(exc),
            }
        )
        write_json(workflow_dir / "result.json", result)
        return result
    write_json(workflow_dir / "artifacts.inspect.json", inspected)
    artifacts = validate_remote_artifacts(
        workflow_id=workflow.workflow_id,
        inspected=inspected,
    )
    write_json(workflow_dir / "artifacts.json", artifacts)
    if not artifacts.get("ok"):
        result.update(
            {
                "classification": "failed_code",
                "reason": "missing_artifacts",
                "artifact_pod": artifact_pod,
                "artifacts": artifacts,
            }
        )
        write_json(workflow_dir / "result.json", result)
        return result

    try:
        downloaded_artifacts = download_remote_output_dir(
            report_dir=report_dir,
            workflow_id=workflow.workflow_id,
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=artifact_pod,
            output_dir=output_dir,
            timeout_s=artifact_download_timeout_s,
        )
    except Exception as exc:
        result.update(
            {
                "classification": "failed_surface",
                "reason": "artifact_download_failed",
                "artifact_pod": artifact_pod,
                "artifacts": artifacts,
                "artifact_error": str(exc),
            }
        )
        write_json(workflow_dir / "result.json", result)
        return result

    handoff_recipe_payload = local_recipe_payload
    if handoff_recipe_payload is None:
        try:
            _handoff_response, handoff_recipe_payload = get_handoff_recipe_payload(
                client,
                workflow,
            )
        except Exception as exc:
            handoff_recipe_payload = None
            write_json(
                workflow_dir / "handoff_recipe.error.json",
                {"workflow_id": workflow.workflow_id, "error": str(exc)},
            )
        else:
            write_json(
                workflow_dir / "handoff_recipe.payload.json",
                handoff_recipe_payload,
            )
            if run_pack is None and isinstance(
                handoff_recipe_payload.get("run_pack"), dict
            ):
                run_pack = dict(handoff_recipe_payload["run_pack"])
                result = _attach_run_pack(result, run_pack)
                write_json(workflow_dir / "run_pack.json", run_pack)
                write_json(workflow_dir / "local_run.json", run_pack)
    result["artifact_pod"] = artifact_pod
    result["artifacts"] = artifacts
    result["downloaded_artifacts"] = downloaded_artifacts
    result = _attach_handoff_bundle(
        result,
        report_dir=report_dir,
        workflow=workflow,
        recipe_payload=handoff_recipe_payload,
        run_pack=run_pack,
        downloaded_artifacts=downloaded_artifacts,
        run_payload=run_payload if isinstance(run_payload, dict) else None,
        vm_name=vm_name,
        zone=zone,
        project=project,
        namespace=namespace,
        pod=artifact_pod,
        timeout_s=artifact_download_timeout_s,
    )
    write_json(workflow_dir / "result.json", result)
    return result


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_classification: dict[str, int] = {}
    for row in results:
        key = str(row.get("classification") or "unknown")
        by_classification[key] = by_classification.get(key, 0) + 1
    return {
        "total": len(results),
        "verified": by_classification.get("verified", 0),
        "failed_surface": by_classification.get("failed_surface", 0),
        "failed_precondition": by_classification.get("failed_precondition", 0),
        "failed_code": by_classification.get("failed_code", 0),
        "by_classification": by_classification,
    }


def _write_summary_text(report_dir: Path, payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    lines = [
        f"generated_at: {payload.get('generated_at')}",
        f"mcp_url: {payload.get('mcp_url')}",
        f"dry_run: {payload.get('dry_run')}",
        f"health_ok: {((payload.get('health') or {}).get('ok'))}",
        f"smoke_ok: {((payload.get('smoke') or {}).get('ok'))}",
        f"verified: {summary.get('verified')}",
        f"failed_surface: {summary.get('failed_surface')}",
        f"failed_precondition: {summary.get('failed_precondition')}",
        f"failed_code: {summary.get('failed_code')}",
        "",
    ]
    for row in payload.get("results") or []:
        lines.append(
            f"{row.get('workflow_id')}: {row.get('classification')} ({row.get('reason')})"
        )
    (report_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_certification(args: argparse.Namespace) -> tuple[int, Path, dict[str, Any]]:
    global _ACTIVE_RESEARCH_LOGGER
    report_dir = Path(args.output_root) / utc_stamp()
    report_dir.mkdir(parents=True, exist_ok=True)
    _ACTIVE_RESEARCH_LOGGER = ResearchLoggingSession(
        source_client="prod_connectivity_certification",
        client_session_id=report_dir.name,
    )
    emit_progress(report_dir, "[start] prod connectivity certification", dry_run=args.dry_run)

    token_source = "explicit"
    token = args.mcp_token
    if not token:
        local_token = resolve_mcp_token()
        if local_token:
            token_source = "local_resolver"
            token = local_token
            emit_progress(report_dir, "[auth] using local BR_MCP_TOKEN resolver")
        else:
            token_source = "gcloud_k3s_secret"
            emit_progress(report_dir, "[auth] resolving prod MCP token via gcloud + k3s secret")
            token = resolve_prod_mcp_token(
                vm_name=args.gcloud_vm_name,
                zone=args.gcloud_zone,
                project=args.gcloud_project,
                namespace=args.k8s_namespace,
                secret_name=args.secret_name,
                secret_key=args.secret_key,
                timeout_s=float(args.timeout_s),
            )

    health = probe_health(args.mcp_url, timeout_s=min(float(args.timeout_s), 10.0))
    write_json(report_dir / "health.json", health)
    if not health.get("ok"):
        report = {
            "generated_at": utc_now_iso(),
            "mcp_url": args.mcp_url,
            "dry_run": bool(args.dry_run),
            "token_source": token_source,
            "health": health,
            "smoke": {"ok": False, "error": "health_probe_failed"},
            "path_discovery": None,
            "results": [],
            "summary": {
                "total": 0,
                "verified": 0,
                "failed_surface": 0,
                "failed_precondition": 0,
                "failed_code": 0,
                "by_classification": {},
            },
        }
        write_json(report_dir / "report.json", report)
        _write_summary_text(report_dir, report)
        _close_research_logger(
            logger=_ACTIVE_RESEARCH_LOGGER,
            report_dir=report_dir,
            report=report,
            exit_code=1,
        )
        return 1, report_dir, report

    client = HttpMCPClient(
        url=args.mcp_url,
        token=token,
        timeout_s=float(args.timeout_s),
        client_name="prod_connectivity_certification",
        client_version="0.1.0",
    )
    _ACTIVE_RESEARCH_LOGGER.bind_client(client)
    _ACTIVE_RESEARCH_LOGGER.start(
        "Start prod connectivity certification.",
        tags=["ops", "prod", "certification", "connectivity"],
    )

    smoke = verify_mcp_smoke(client)
    write_json(report_dir / "smoke.json", smoke)
    if not smoke.get("ok"):
        report = {
            "generated_at": utc_now_iso(),
            "mcp_url": args.mcp_url,
            "dry_run": bool(args.dry_run),
            "token_source": token_source,
            "health": health,
            "smoke": smoke,
            "path_discovery": None,
            "results": [],
            "summary": {
                "total": 0,
                "verified": 0,
                "failed_surface": 0,
                "failed_precondition": 0,
                "failed_code": 0,
                "by_classification": {},
            },
        }
        write_json(report_dir / "report.json", report)
        _write_summary_text(report_dir, report)
        _close_research_logger(
            logger=_ACTIVE_RESEARCH_LOGGER,
            report_dir=report_dir,
            report=report,
            exit_code=1,
        )
        return 1, report_dir, report

    try:
        discovered = discover_prod_inputs(client, atlas_path=args.atlas_path)
    except SurfaceError as exc:
        report = {
            "generated_at": utc_now_iso(),
            "mcp_url": args.mcp_url,
            "dry_run": bool(args.dry_run),
            "token_source": token_source,
            "health": health,
            "smoke": smoke,
            "path_discovery": {"ok": False, "error": str(exc)},
            "results": [],
            "summary": {
                "total": 0,
                "verified": 0,
                "failed_surface": 1,
                "failed_precondition": 0,
                "failed_code": 0,
                "by_classification": {"failed_surface": 1},
            },
        }
        write_json(report_dir / "report.json", report)
        _write_summary_text(report_dir, report)
        _close_research_logger(
            logger=_ACTIVE_RESEARCH_LOGGER,
            report_dir=report_dir,
            report=report,
            exit_code=1,
        )
        return 1, report_dir, report
    except Exception as exc:
        report = {
            "generated_at": utc_now_iso(),
            "mcp_url": args.mcp_url,
            "dry_run": bool(args.dry_run),
            "token_source": token_source,
            "health": health,
            "smoke": smoke,
            "path_discovery": {"ok": False, "error": str(exc)},
            "results": [],
            "summary": {
                "total": 0,
                "verified": 0,
                "failed_surface": 0,
                "failed_precondition": 1,
                "failed_code": 0,
                "by_classification": {"failed_precondition": 1},
            },
        }
        write_json(report_dir / "report.json", report)
        _write_summary_text(report_dir, report)
        _close_research_logger(
            logger=_ACTIVE_RESEARCH_LOGGER,
            report_dir=report_dir,
            report=report,
            exit_code=1,
        )
        return 1, report_dir, report

    discovered["ok"] = True
    write_json(report_dir / "path_discovery.json", discovered)

    artifact_pod = None
    try:
        artifact_pod = resolve_mcp_pod(
            vm_name=args.gcloud_vm_name,
            zone=args.gcloud_zone,
            project=args.gcloud_project,
            namespace=args.k8s_namespace,
            pod_name=args.mcp_pod,
            timeout_s=float(args.timeout_s),
        )
    except Exception as exc:
        write_json(
            report_dir / "artifact_pod.error.json",
            {"ok": False, "error": str(exc)},
        )
        artifact_pod = None
    else:
        write_json(
            report_dir / "artifact_pod.json",
            {"ok": True, "pod": artifact_pod},
        )

    remote_output_root = "/".join(
        [args.remote_output_root.rstrip("/"), report_dir.name]
    )
    remote_work_root = "/".join([args.remote_work_root.rstrip("/"), report_dir.name])
    plans = build_workflow_plans(
        discovered,
        remote_output_root=remote_output_root,
        remote_work_root=remote_work_root,
    )

    selected = {item.strip() for item in args.workflow_id if item.strip()}
    if selected:
        plans = [plan for plan in plans if plan.workflow_id in selected]

    results: list[dict[str, Any]] = []
    for workflow in plans:
        result = certify_workflow(
            client,
            workflow,
            dry_run=bool(args.dry_run),
            poll_timeout_s=float(args.poll_timeout_s),
            poll_interval_s=float(args.poll_interval_s),
            report_dir=report_dir,
            vm_name=args.gcloud_vm_name,
            zone=args.gcloud_zone,
            project=args.gcloud_project,
            namespace=args.k8s_namespace,
            artifact_pod=artifact_pod or "",
            agent_pod=args.agent_pod,
            artifact_download_timeout_s=float(args.artifact_download_timeout_s),
        )
        results.append(result)

    summary = summarize_results(results)
    report = {
        "generated_at": utc_now_iso(),
        "mcp_url": args.mcp_url,
        "dry_run": bool(args.dry_run),
        "token_source": token_source,
        "remote_output_root": remote_output_root,
        "remote_work_root": remote_work_root,
        "artifact_pod": artifact_pod,
        "health": health,
        "smoke": smoke,
        "path_discovery": discovered,
        "results": results,
        "summary": summary,
    }
    write_json(report_dir / "report.json", report)
    _write_summary_text(report_dir, report)

    exit_code = 0 if summary.get("total") and summary.get("verified") == summary.get("total") else 1
    _close_research_logger(
        logger=_ACTIVE_RESEARCH_LOGGER,
        report_dir=report_dir,
        report=report,
        exit_code=exit_code,
    )
    return exit_code, report_dir, report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run production connectivity workflow certification over MCP HTTP.",
    )
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--mcp-token", default=None)
    parser.add_argument("--gcloud-vm-name", default=DEFAULT_GCLOUD_VM_NAME)
    parser.add_argument("--gcloud-zone", default=DEFAULT_GCLOUD_ZONE)
    parser.add_argument("--gcloud-project", default=DEFAULT_GCLOUD_PROJECT)
    parser.add_argument("--k8s-namespace", default=DEFAULT_K8S_NAMESPACE)
    parser.add_argument("--secret-name", default=DEFAULT_SECRET_NAME)
    parser.add_argument("--secret-key", default=DEFAULT_SECRET_KEY)
    parser.add_argument("--atlas-path", default=None)
    parser.add_argument(
        "--agent-pod",
        default=DEFAULT_AGENT_POD,
        help="Agent pod used for local-recipe execution when MCP reports hosted_via_br_mcp_service=false.",
    )
    parser.add_argument(
        "--output-root",
        default=str(LOCAL_REPORT_ROOT),
        help="Local report root. A UTC timestamp directory is appended automatically.",
    )
    parser.add_argument("--remote-output-root", default=DEFAULT_REMOTE_OUTPUT_ROOT)
    parser.add_argument("--remote-work-root", default=DEFAULT_REMOTE_WORK_ROOT)
    parser.add_argument(
        "--artifact-download-timeout-s",
        type=float,
        default=DEFAULT_ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--mcp-pod",
        default="",
        help="Optional explicit MCP pod to inspect for remote artifacts.",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Optional workflow subset to certify. Repeatable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Submit pipeline_execute with dry_run=true.",
    )
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-timeout-s", type=float, default=DEFAULT_POLL_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval-s", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    exit_code, report_dir, report = run_certification(args)
    print(
        json.dumps(
            {
                "ok": exit_code == 0,
                "report_dir": str(report_dir),
                "summary": report.get("summary"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
