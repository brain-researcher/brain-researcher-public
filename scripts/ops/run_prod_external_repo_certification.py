#!/usr/bin/env python3
"""Operator-side prod certification for external-repo workflow recipes.

This runner is for workflows whose MCP recipe metadata reports
`hosted_via_br_mcp_service=false`. For these workflows, the correct prod bar is:

1. MCP HTTP can generate a runnable execution recipe
2. Required prod-side inputs are staged into the agent runtime
3. The returned recipe is executed inside the live prod agent environment
4. Expected artifacts are materialized on prod
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mcp.call_http_tool import (  # noqa: E402
    HttpMCPClient,
    ResearchLoggingSession,
    resolve_mcp_token,
    run_subprocess_with_trace,
)

LOCAL_REPORT_ROOT = REPO_ROOT / "artifacts" / "prod_external_repo_certification"

DEFAULT_MCP_URL = os.environ.get("BR_MCP_HTTP_URL", "https://brain-researcher.com/mcp")
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_REMOTE_EXECUTE_TIMEOUT_SECONDS = 300.0
DEFAULT_REMOTE_LAUNCH_TIMEOUT_SECONDS = 60.0
DEFAULT_REMOTE_TIMEOUT_GRACE_SECONDS = 300.0
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0
DEFAULT_ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS = 180.0
DEFAULT_GCLOUD_VM_NAME = os.environ.get("BR_PROD_K3S_VM_NAME", "brain-researcher-vm")
DEFAULT_GCLOUD_ZONE = os.environ.get("BR_PROD_K3S_ZONE", "us-west1-b")
DEFAULT_GCLOUD_PROJECT = os.environ.get(
    "BR_PROD_GCLOUD_PROJECT", "hai-gcp-dialogue-brain"
)
DEFAULT_K8S_NAMESPACE = "brain-researcher-core"
DEFAULT_SECRET_NAME = "brain-researcher-mcp-auth"
DEFAULT_SECRET_KEY = "BR_MCP_AUTH_TOKEN"
NON_PLAINTEXT_MCP_SECRET_KEYS = {
    "BR_MCP_AUTH_TOKENS_JSON",
    "BR_MCP_TOKEN_PEPPER",
}
DEFAULT_AGENT_POD = "brain-researcher-agent-0"
DEFAULT_REMOTE_INPUT_ROOT = "/app/jobstore/prod_external_repo_certification"
DEFAULT_REMOTE_OUTPUT_ROOT = "/app/artifacts/prod_external_repo_certification"
DEFAULT_DATASET_ROOT = "/app/data/openneuro/ds000114"
DEFAULT_FMRIPREP_DERIV_ROOT = (
    "/app/data/OpenNeuroDerivatives/fmriprep/ds000114-fmriprep"
)
DEFAULT_ALT_FMRIPREP_DERIV_ROOT = "/app/data/OpenNeuroDerivatives/fmriprep/ds000114"

DEFAULT_WORKFLOWS = (
    "workflow_mriqc",
    "workflow_fmriprep_preprocessing",
    "workflow_preprocessing_qc",
)
DEFAULT_RECIPE_TARGET = "neurodesk"
DEFAULT_PARTICIPANT_LABEL = "01"
DEFAULT_SESSION_LABEL = "ses-test"
DEFAULT_TASK_NAME = "linebisection"

REQUIRED_ARTIFACTS = {
    "workflow_mriqc": [
        "dataset_description.json",
        "subject_report_html",
    ],
    "workflow_fmriprep_preprocessing": [
        "dataset_description.json",
        "derivatives_dir",
    ],
    "workflow_preprocessing_qc": [
        "qc/qc_table.csv",
        "qc/qc_outliers.csv",
        "qc/qc_summary.json",
        "qc/index.html",
        "fmriprep/dataset_description.json",
        "mriqc/subject_report_html",
    ],
}

_ACTIVE_RESEARCH_LOGGER: ResearchLoggingSession | None = None


@dataclass(frozen=True)
class WorkflowRuntime:
    workflow_id: str
    recipe_target: str
    recipe_dir: str
    output_dir: str
    work_dir: str
    params_json: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_") or "item"


def _run_subprocess(
    cmd: list[str], *, timeout_s: float, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return run_subprocess_with_trace(
        cmd,
        timeout_s=timeout_s,
        check=check,
        logger=_ACTIVE_RESEARCH_LOGGER,
    )


def emit_progress(report_dir: Path, message: str, **extra: Any) -> None:
    payload = {"ts": utc_now_iso(), "message": message}
    if extra:
        payload.update(extra)
    path = report_dir / "progress.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")
    if _ACTIVE_RESEARCH_LOGGER is not None:
        _ACTIVE_RESEARCH_LOGGER.record_progress(message, **extra)
    print(message, file=sys.stderr)


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
    total = len(report.get("results") or [])
    done = [
        f"Saved report bundle to {report_dir}",
        f"Evaluated {total} workflows",
        f"Exit code {exit_code}",
    ]
    open_items: list[str] = []
    for key, message in (
        ("failed_surface", "Investigate MCP surface failures"),
        ("failed_precondition", "Resolve workflow preconditions"),
        ("failed_code", "Investigate workflow execution failures"),
        ("failed_timeout_local", "Investigate local timeout failures"),
        ("failed_timeout_remote", "Investigate remote timeout failures"),
        ("failed_oom", "Investigate OOM failures"),
    ):
        if int(summary.get(key) or 0):
            open_items.append(message)
    next_command = (
        f"cat {report_dir / 'summary.txt'}"
        if (report_dir / "summary.txt").exists()
        else f"cat {report_dir / 'report.json'}"
    )
    try:
        logger.close(
            goal="Run prod certification for external-repo workflow recipes.",
            done=done,
            open_items=open_items,
            next_command=next_command,
            tags=["ops", "prod", "certification", "external_repo"],
        )
    finally:
        _ACTIVE_RESEARCH_LOGGER = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run prod certification for external-repo workflow recipes"
    )
    parser.add_argument(
        "--mcp-url", default=DEFAULT_MCP_URL, help="Prod MCP HTTP endpoint"
    )
    parser.add_argument(
        "--mcp-token",
        default="",
        help="Optional bearer token override. Defaults to BR_MCP_TOKEN or prod secret.",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Workflow IDs to certify (default: preproc/QC family first wave)",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-request timeout for MCP/SSH/kubectl control-plane calls.",
    )
    parser.add_argument(
        "--remote-execute-timeout-s",
        type=float,
        default=DEFAULT_REMOTE_EXECUTE_TIMEOUT_SECONDS,
        help="Pod-side deadline enforced inside the agent for the workflow command.",
    )
    parser.add_argument(
        "--remote-launch-timeout-s",
        type=float,
        default=DEFAULT_REMOTE_LAUNCH_TIMEOUT_SECONDS,
        help="Timeout for the short remote launch command that backgrounds the pod-side supervisor.",
    )
    parser.add_argument(
        "--remote-timeout-grace-s",
        type=float,
        default=DEFAULT_REMOTE_TIMEOUT_GRACE_SECONDS,
        help="Additional local wait budget after the pod-side deadline before classifying a local timeout.",
    )
    parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Polling interval for remote supervisor state.",
    )
    parser.add_argument(
        "--heartbeat-interval-s",
        type=float,
        default=DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        help="Heartbeat update interval written by the pod-side supervisor.",
    )
    parser.add_argument(
        "--artifact-download-timeout-s",
        type=float,
        default=DEFAULT_ARTIFACT_DOWNLOAD_TIMEOUT_SECONDS,
        help="Per-artifact download timeout for successful verified workflows.",
    )
    parser.add_argument(
        "--output-root",
        default=str(LOCAL_REPORT_ROOT),
        help="Local report root",
    )
    parser.add_argument(
        "--vm-name", default=DEFAULT_GCLOUD_VM_NAME, help="Prod VM name"
    )
    parser.add_argument("--zone", default=DEFAULT_GCLOUD_ZONE, help="Prod GCE zone")
    parser.add_argument(
        "--project", default=DEFAULT_GCLOUD_PROJECT, help="Prod GCP project"
    )
    parser.add_argument(
        "--namespace", default=DEFAULT_K8S_NAMESPACE, help="Prod k3s namespace"
    )
    parser.add_argument(
        "--agent-pod",
        default=DEFAULT_AGENT_POD,
        help="Agent pod name for recipe execution",
    )
    parser.add_argument(
        "--remote-input-root",
        default=DEFAULT_REMOTE_INPUT_ROOT,
        help="Prod agent input staging root",
    )
    parser.add_argument(
        "--remote-output-root",
        default=DEFAULT_REMOTE_OUTPUT_ROOT,
        help="Prod agent artifact output root",
    )
    parser.add_argument(
        "--dataset-root",
        default=DEFAULT_DATASET_ROOT,
        help="Prod dataset root available in the agent pod",
    )
    parser.add_argument(
        "--fmriprep-deriv-root",
        default=DEFAULT_FMRIPREP_DERIV_ROOT,
        help="Prod reference fMRIPrep derivatives root available in the agent pod",
    )
    parser.add_argument(
        "--participant-label",
        default=DEFAULT_PARTICIPANT_LABEL,
        help="Single participant label used for the minimal recipe",
    )
    parser.add_argument(
        "--fs-license-file",
        default="",
        help="Optional local FreeSurfer license path to stage into prod",
    )
    parser.add_argument(
        "--recipe-target",
        default=DEFAULT_RECIPE_TARGET,
        help="Execution recipe target runtime (default: neurodesk)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stage recipe files and print commands without executing heavy workflows",
    )
    return parser.parse_args(argv)


def _selected_workflows(items: list[str]) -> list[str]:
    selected = [item.strip() for item in items if item.strip()]
    return selected or list(DEFAULT_WORKFLOWS)


def _candidate_fmriprep_deriv_roots(primary_root: str) -> list[str]:
    roots: list[str] = []
    for raw in (primary_root, DEFAULT_ALT_FMRIPREP_DERIV_ROOT):
        value = str(raw or "").strip()
        if not value or value in roots:
            continue
        roots.append(value)
        if value.endswith("-fmriprep"):
            alt = value[: -len("-fmriprep")]
            if alt and alt not in roots:
                roots.append(alt)
        else:
            alt = value + "-fmriprep"
            if alt not in roots:
                roots.append(alt)
    return roots


def resolve_local_fs_license(explicit_path: str | None = None) -> Path | None:
    candidates = []
    if explicit_path and explicit_path.strip():
        candidates.append(Path(explicit_path).expanduser())
    env_value = os.environ.get("FS_LICENSE", "").strip()
    if env_value:
        candidates.append(Path(env_value).expanduser())
    candidates.extend(
        [
            Path.home() / ".freesurfer_license.txt",
            Path.home() / "freesurfer_license.txt",
            Path.home() / ".freesurfer" / "license.txt",
        ]
    )
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _gcloud_ssh_cmd(
    *,
    vm_name: str,
    zone: str,
    project: str,
    remote_command: str,
) -> list[str]:
    return [
        "gcloud",
        "compute",
        "ssh",
        vm_name,
        "--zone",
        zone,
        "--project",
        project,
        "--command",
        remote_command,
    ]


def run_remote_command(
    *,
    vm_name: str,
    zone: str,
    project: str,
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


def _kubectl_exec_python(
    *,
    pod: str,
    namespace: str,
    code: str,
    args: list[str] | None = None,
) -> str:
    arg_str = " ".join(shlex.quote(item) for item in (args or []))
    return (
        f"sudo k3s kubectl -n {shlex.quote(namespace)} exec {shlex.quote(pod)} -- "
        f"python -c {shlex.quote(code)}" + (f" {arg_str}" if arg_str else "")
    )


def _kubectl_exec_bash(*, pod: str, namespace: str, script: str) -> str:
    return (
        f"sudo k3s kubectl -n {shlex.quote(namespace)} exec {shlex.quote(pod)} -- "
        f"bash -lc {shlex.quote(script)}"
    )


def probe_agent_environment(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    dataset_root: str,
    fmriprep_deriv_root: str,
    timeout_s: float,
) -> dict[str, Any]:
    code = """
import json, os
from brain_researcher.services.tools.pipeline_tools import _resolve_bids_app_executable

dataset_root, deriv_root = __import__('sys').argv[1:3]
payload = {
    'dataset_root': dataset_root,
    'dataset_exists': os.path.isdir(dataset_root),
    'fmriprep_deriv_root': deriv_root,
    'fmriprep_deriv_exists': os.path.isdir(deriv_root),
    'apptainer': os.path.exists('/usr/local/bin/apptainer'),
    'docker': os.path.exists('/usr/bin/docker'),
    'cvmfs': os.path.isdir('/cvmfs/neurodesk.ardc.edu.au'),
    'cvmfs_containers': os.path.isdir('/cvmfs/neurodesk.ardc.edu.au/containers'),
    'executables': {
        'fmriprep': _resolve_bids_app_executable('fmriprep', env_var='BR_FMRIPREP_BIN'),
        'mriqc': _resolve_bids_app_executable('mriqc', env_var='BR_MRIQC_BIN'),
        'qsiprep': _resolve_bids_app_executable('qsiprep', env_var='BR_QSIPREP_BIN'),
        'smriprep': _resolve_bids_app_executable('smriprep', env_var='BR_SMRIPREP_BIN'),
    },
    'fs_license_env': os.environ.get('FS_LICENSE'),
}
print(json.dumps(payload, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[dataset_root, fmriprep_deriv_root],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def stage_file_in_agent(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    local_path: Path,
    remote_path: str,
    timeout_s: float,
) -> dict[str, Any]:
    payload_b64 = base64.b64encode(local_path.read_bytes()).decode("ascii")
    code = """
import base64, os, sys
from pathlib import Path

remote_path = Path(sys.argv[1])
payload = base64.b64decode(sys.argv[2].encode('ascii'))
remote_path.parent.mkdir(parents=True, exist_ok=True)
remote_path.write_bytes(payload)
os.chmod(remote_path, 0o600)
print(remote_path)
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[remote_path, payload_b64],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return {"remote_path": proc.stdout.strip()}


def stage_minimal_bids_subset(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    dataset_root: str,
    participant_label: str,
    remote_subset_root: str,
    session_label: str,
    task_name: str,
    timeout_s: float,
) -> dict[str, Any]:
    subject_dir = f"sub-{participant_label}"
    code = """
import json, shutil, sys
from pathlib import Path

dataset_root = Path(sys.argv[1]).resolve()
subject_dir = sys.argv[2]
session_label = sys.argv[3]
task_name = sys.argv[4]
remote_root = Path(sys.argv[5]).resolve()
remote_root.mkdir(parents=True, exist_ok=True)

def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)

top_level_names = {
    'dataset_description.json',
    'participants.tsv',
    'participants.json',
    'README',
    'CHANGES',
    f'task-{task_name}_bold.json',
}
copied = []
for child in dataset_root.iterdir():
    if child.name in top_level_names and child.is_file():
        target = remote_root / child.name
        copy_file(child, target)
        copied.append(str(target))

src_subject = dataset_root / subject_dir
if not src_subject.is_dir():
    raise RuntimeError(f'missing subject directory: {src_subject}')

src_session = src_subject / session_label
if not src_session.is_dir():
    raise RuntimeError(f'missing session directory: {src_session}')

for src in sorted(src_session.rglob('*')):
    if src.is_dir():
        continue
    rel = src.relative_to(dataset_root)
    if 'anat' in rel.parts and '_T1w' in src.name:
        dst = remote_root / rel
        copy_file(src, dst)
        copied.append(str(dst))
        continue
    if 'func' in rel.parts and f'_task-{task_name}_' in src.name:
        dst = remote_root / rel
        copy_file(src, dst)
        copied.append(str(dst))

print(json.dumps({
    'dataset_root': str(dataset_root),
    'subset_root': str(remote_root),
    'subject_dir': str(remote_root / subject_dir),
    'session_label': session_label,
    'task_name': task_name,
    'copied_count': len(copied),
}, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[
                dataset_root,
                subject_dir,
                session_label,
                task_name,
                remote_subset_root,
            ],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def stage_precomputed_qc_table(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    fmriprep_deriv_roots: list[str],
    participant_label: str,
    session_label: str,
    task_name: str,
    remote_qc_tsv: str,
    timeout_s: float,
) -> dict[str, Any]:
    subject_dir = f"sub-{participant_label}"
    code = """
import csv, json, math, os, sys
from pathlib import Path

deriv_roots = [Path(item).resolve() for item in sys.argv[1].split(os.pathsep) if item]
subject_dir = sys.argv[2]
session_label = sys.argv[3]
task_name = sys.argv[4]
out_path = Path(sys.argv[5]).resolve()
out_path.parent.mkdir(parents=True, exist_ok=True)

deriv_root = None
confounds = []
patterns = [
    f'{subject_dir}/{session_label}/func/*_task-{task_name}_desc-confounds_timeseries.tsv',
    f'{subject_dir}/{session_label}/func/*_task-{task_name}_*_desc-confounds_timeseries.tsv',
]
for candidate in deriv_roots:
    matches = []
    for pattern in patterns:
        matches.extend(candidate.glob(pattern))
    matches = sorted({match.resolve() for match in matches})
    if matches:
        deriv_root = candidate
        confounds = matches
        break
if deriv_root is None or not confounds:
    tried = ', '.join(str(item) for item in deriv_roots)
    raise RuntimeError(f'no confounds TSV found under [{tried}] matching {patterns}')

def mean_fd(path: Path) -> float:
    values = []
    with path.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle, delimiter='\\t')
        for row in reader:
            raw = (row.get('framewise_displacement') or '').strip()
            if not raw or raw.lower() == 'n/a':
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
    return float(sum(values) / len(values)) if values else float('nan')

rows = []
for path in confounds:
    run_id = path.stem.removesuffix('_desc-confounds_timeseries')
    rows.append({'run_id': run_id, 'fd_mean': mean_fd(path)})

with out_path.open('w', encoding='utf-8', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=['run_id', 'fd_mean'], delimiter='\\t')
    writer.writeheader()
    writer.writerows(rows)

print(json.dumps({'qc_tsv': str(out_path), 'rows': len(rows)}, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[
                os.pathsep.join(fmriprep_deriv_roots),
                subject_dir,
                session_label,
                task_name,
                remote_qc_tsv,
            ],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def _record_precondition_failure(
    *,
    report_dir: Path,
    workflow_id: str,
    recipe_target: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_dir = report_dir / workflow_id
    workflow_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "workflow_id": workflow_id,
        "classification": "failed_precondition",
        "reason": reason,
        "recipe_target": recipe_target,
    }
    if details:
        result["details"] = details
    write_json(workflow_dir / "result.json", result)
    return result


def _record_workflow_failure(
    *,
    report_dir: Path,
    workflow_id: str,
    recipe_target: str,
    classification: str,
    reason: str,
    output_dir: str | None = None,
    work_dir: str | None = None,
    state_dir: str | None = None,
    details: dict[str, Any] | None = None,
    run_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_dir = report_dir / workflow_id
    workflow_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "workflow_id": workflow_id,
        "classification": classification,
        "reason": reason,
        "recipe_target": recipe_target,
    }
    if output_dir:
        result["output_dir"] = output_dir
    if work_dir:
        result["work_dir"] = work_dir
    if state_dir:
        result["state_dir"] = state_dir
    if details:
        result["details"] = details
    result = _attach_run_pack(result, run_pack)
    write_json(workflow_dir / "result.json", result)
    return result


def _run_pack_payload(recipe_payload: dict[str, Any]) -> dict[str, Any] | None:
    run_pack = recipe_payload.get("run_pack")
    if isinstance(run_pack, dict):
        return dict(run_pack)
    local_run = recipe_payload.get("local_run")
    recipe = recipe_payload.get("recipe")
    tool_id = str(
        recipe_payload.get("resolved_tool_id")
        or recipe_payload.get("requested_tool_id")
        or ""
    ).strip()
    target_runtime = str(recipe_payload.get("target_runtime") or "").strip()
    if not target_runtime and isinstance(local_run, dict):
        workspace = str(local_run.get("workspace") or "").strip()
        for candidate in ("python", "container", "neurodesk", "slurm"):
            if workspace.endswith(f"_{candidate}_recipe"):
                target_runtime = candidate
                break
    if isinstance(recipe, dict):
        try:
            from brain_researcher.services.mcp.execution_recipes import (
                _recipe_run_pack_payload as _derive_run_pack_payload,
            )
        except Exception:
            return dict(local_run) if isinstance(local_run, dict) else None
        derived = _derive_run_pack_payload(tool_id, target_runtime, recipe)
        if isinstance(derived, dict):
            if isinstance(local_run, dict):
                merged = dict(derived)
                merged.update(dict(local_run))
                return merged
            return dict(derived)
    if not isinstance(recipe, dict):
        return dict(local_run) if isinstance(local_run, dict) else None
    return dict(local_run) if isinstance(local_run, dict) else None


def _local_run_payload(recipe_payload: dict[str, Any]) -> dict[str, Any] | None:
    return _run_pack_payload(recipe_payload)


def _attach_run_pack(
    result: dict[str, Any],
    run_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    if run_pack:
        result["run_pack"] = dict(run_pack)
        result["local_run"] = dict(run_pack)
    return result


def _write_recipe_files_to_workspace(
    workspace: Path,
    files: dict[str, str],
) -> list[str]:
    workspace.mkdir(parents=True, exist_ok=True)
    workspace_root = workspace.resolve()
    written: list[str] = []
    for name, content in files.items():
        path = (workspace / name).resolve()
        if workspace_root not in path.parents and path != workspace_root:
            raise RuntimeError(f"unsafe recipe file path: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        if path.suffix == ".sh":
            path.chmod(path.stat().st_mode | 0o111)
        written.append(path.relative_to(workspace_root).as_posix())
    return sorted(written)


def _copy_local_path_into_bundle(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _patch_handoff_params(
    *,
    workflow_id: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    patched = dict(params)
    missing_inputs = ["bids_dir"]
    patched["bids_dir"] = "<set-local-bids-root>"
    patched["output_dir"] = f"./outputs/out/{workflow_id}"

    if workflow_id == "workflow_mriqc":
        patched["work_dir"] = f"./work/{workflow_id}"
        patched["mriqc_output_dir"] = patched["output_dir"]
        patched["mriqc_work_dir"] = patched["work_dir"]
    elif workflow_id == "workflow_fmriprep_preprocessing":
        patched["work_dir"] = f"./work/{workflow_id}"
        if "fs_license_file" in patched:
            patched["fs_license_file"] = "/path/to/freesurfer/license.txt"
    elif workflow_id == "workflow_preprocessing_qc":
        patched["fmriprep_output_dir"] = f"{patched['output_dir']}/fmriprep"
        patched["mriqc_output_dir"] = f"{patched['output_dir']}/mriqc"
        patched["fmriprep_work_dir"] = f"./work/{workflow_id}/fmriprep"
        patched["mriqc_work_dir"] = f"./work/{workflow_id}/mriqc"
        if "fs_license_file" in patched:
            patched["fs_license_file"] = "/path/to/freesurfer/license.txt"
        if "qc_tsv" in patched:
            patched["qc_tsv"] = ""
    return patched, missing_inputs


def build_handoff_bundle(
    *,
    report_dir: Path,
    workflow_id: str,
    recipe_payload: dict[str, Any] | None,
    run_pack: dict[str, Any] | None,
    downloaded_artifacts: dict[str, Any] | None,
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

    params_path = workspace / "params.json"
    params = {}
    if params_path.exists():
        try:
            params = json.loads(params_path.read_text(encoding="utf-8"))
        except Exception:
            params = {}
        recipe_copy = workspace / "params.recipe.json"
        recipe_copy.write_text(params_path.read_text(encoding="utf-8"), encoding="utf-8")
        if "params.recipe.json" not in written_files:
            written_files.append("params.recipe.json")

    patched_params, missing_inputs = _patch_handoff_params(
        workflow_id=workflow_id,
        params=params,
    )
    params_path.write_text(
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

    bundled_artifacts: list[dict[str, Any]] = []
    manifest_artifacts = (
        dict((downloaded_artifacts or {}).get("artifacts") or {})
        if isinstance(downloaded_artifacts, dict)
        else {}
    )
    if manifest_artifacts:
        artifacts_dir = workspace / "downloaded_artifacts"
        for name, item in sorted(manifest_artifacts.items()):
            if not isinstance(item, dict) or not bool(item.get("downloaded")):
                continue
            local_path = Path(str(item.get("local_path") or "")).expanduser()
            if not local_path.exists() or not local_path.is_file():
                continue
            safe_name = local_path.name or _artifact_output_filename(
                name,
                str(item.get("path") or ""),
                str(item.get("kind") or "file"),
            )
            destination = artifacts_dir / safe_name
            _copy_local_path_into_bundle(local_path, destination)
            bundled_artifacts.append(
                {
                    "name": name,
                    "kind": str(item.get("kind") or "file"),
                    "path": str(destination),
                    "relative_path": destination.relative_to(workspace).as_posix(),
                }
            )

    payload = {
        "ok": True,
        "bundle_dir": str(bundle_dir),
        "workspace": str(workspace),
        "workspace_name": workspace_name,
        "written_files": sorted(written_files),
        "bundled_artifacts": bundled_artifacts,
        "params_json": str(params_path),
        "params_local_json": str(params_local_path),
        "missing_inputs": missing_inputs,
    }
    write_json(workflow_dir / "handoff_bundle.json", payload)
    return payload


def _attach_handoff_bundle(
    result: dict[str, Any],
    *,
    report_dir: Path,
    workflow_id: str,
    recipe_payload: dict[str, Any] | None,
    run_pack: dict[str, Any] | None,
    downloaded_artifacts: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        handoff_bundle = build_handoff_bundle(
            report_dir=report_dir,
            workflow_id=workflow_id,
            recipe_payload=recipe_payload,
            run_pack=run_pack,
            downloaded_artifacts=downloaded_artifacts,
        )
    except Exception as exc:
        handoff_bundle = {
            "ok": False,
            "reason": "handoff_bundle_failed",
            "error": str(exc),
        }
        write_json(report_dir / workflow_id / "handoff_bundle.json", handoff_bundle)
    result["handoff_bundle"] = handoff_bundle
    return result


def _remote_smoke_started(status: dict[str, Any]) -> bool:
    return any(
        bool(str(status.get(key) or "").strip())
        for key in ("started_at", "heartbeat", "pid", "launcher_pid")
    )


def _artifact_output_filename(name: str, remote_path: str, kind: str) -> str:
    safe_name = _slugify(name)
    remote = Path(str(remote_path or "").strip())
    suffix = "".join(remote.suffixes)
    if kind == "dir":
        return f"{safe_name}.tar.gz"
    if suffix:
        return f"{safe_name}{suffix}"
    return safe_name


def get_recipe(
    client: HttpMCPClient,
    *,
    workflow_id: str,
    recipe_target: str,
) -> dict[str, Any]:
    response = client.call_tool(
        "get_execution_recipe",
        {"tool_id": workflow_id, "target_runtime": recipe_target},
        prime=False,
        initialize=True,
    )
    if not response.get("ok"):
        raise RuntimeError(
            f"get_execution_recipe transport failed: {response.get('http_status')}"
        )
    payload = response.get("payload")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(
            f"get_execution_recipe failed: {payload.get('error') if isinstance(payload, dict) else payload}"
        )
    return payload


def override_recipe_files(
    recipe_payload: dict[str, Any],
    *,
    workflow_id: str,
    participant_label: str,
    bids_dir: str,
    output_dir: str,
    work_dir: str,
    qc_tsv: str | None,
    fs_license_file: str | None,
) -> dict[str, str]:
    recipe = recipe_payload.get("recipe") or {}
    files = dict(recipe.get("files") or {})
    params = json.loads(files.get("params.json") or recipe.get("params_json") or "{}")
    params["bids_dir"] = bids_dir
    params["output_dir"] = output_dir
    params["participant_label"] = [participant_label]
    if workflow_id == "workflow_mriqc":
        params["work_dir"] = work_dir
        params["mriqc_output_dir"] = output_dir
        params["mriqc_work_dir"] = work_dir
    elif workflow_id == "workflow_fmriprep_preprocessing":
        params["work_dir"] = work_dir
        if fs_license_file:
            params["fs_license_file"] = fs_license_file
    elif workflow_id == "workflow_preprocessing_qc":
        if fs_license_file:
            params["fs_license_file"] = fs_license_file
        if qc_tsv:
            params["qc_tsv"] = qc_tsv
        params["fmriprep_output_dir"] = f"{output_dir}/fmriprep"
        params["mriqc_output_dir"] = f"{output_dir}/mriqc"
        params["fmriprep_work_dir"] = f"{work_dir}/fmriprep"
        params["mriqc_work_dir"] = f"{work_dir}/mriqc"
    files["params.json"] = json.dumps(params, indent=2, sort_keys=True)
    if workflow_id == "workflow_mriqc" and "run_workflow_mriqc.sh" in files:
        files["run_workflow_mriqc.sh"] = _append_shell_flag(
            files["run_workflow_mriqc.sh"],
            "--no-sub",
        )
    if (
        workflow_id == "workflow_fmriprep_preprocessing"
        and "run_workflow_fmriprep_preprocessing.sh" in files
    ):
        files["run_workflow_fmriprep_preprocessing.sh"] = _append_shell_flag(
            files["run_workflow_fmriprep_preprocessing.sh"],
            "--fs-no-reconall",
        )
    if workflow_id == "workflow_preprocessing_qc" and "run_fmriprep.sh" in files:
        files["run_fmriprep.sh"] = _append_shell_flag(
            files["run_fmriprep.sh"],
            "--fs-no-reconall",
        )
    if workflow_id == "workflow_preprocessing_qc" and "run_mriqc.sh" in files:
        files["run_mriqc.sh"] = _append_shell_flag(
            files["run_mriqc.sh"],
            "--no-sub",
        )
    return {str(k): str(v) for k, v in files.items()}


def _append_shell_flag(script_text: str, flag: str) -> str:
    if flag in script_text:
        return script_text
    lines = script_text.splitlines()
    last_idx = max((idx for idx, line in enumerate(lines) if line.strip()), default=-1)
    if last_idx < 0:
        return script_text
    if not lines[last_idx].rstrip().endswith("\\"):
        lines[last_idx] = lines[last_idx].rstrip() + " \\"
    lines.insert(last_idx + 1, f"  {flag}")
    rendered = "\n".join(lines)
    return rendered + ("\n" if script_text.endswith("\n") else "")


def stage_recipe_files(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    remote_dir: str,
    files: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    payload_b64 = base64.b64encode(json.dumps(files).encode("utf-8")).decode("ascii")
    code = """
import base64, json, os, sys
from pathlib import Path

remote_dir = Path(sys.argv[1]).resolve()
files = json.loads(base64.b64decode(sys.argv[2].encode('ascii')).decode('utf-8'))
remote_dir.mkdir(parents=True, exist_ok=True)
for name, content in files.items():
    path = remote_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    if path.suffix == '.sh':
        os.chmod(path, 0o755)
print(json.dumps({'recipe_dir': str(remote_dir), 'file_count': len(files)}, indent=2))
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


def _normalize_setup_command(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    if text.startswith("module load "):
        module_spec = text[len("module load ") :].strip()
        quoted = shlex.quote(module_spec)
        return (
            "if command -v module >/dev/null 2>&1; then "
            f"module load {quoted}; "
            "elif [[ -f /etc/profile.d/modules.sh ]]; then "
            ". /etc/profile.d/modules.sh >/dev/null 2>&1 || true; "
            "if command -v module >/dev/null 2>&1; then "
            f"module load {quoted}; "
            "else "
            f"echo 'skipping unavailable module command: {module_spec}' >&2; "
            "fi; "
            "else "
            f"echo 'skipping unavailable module command: {module_spec}' >&2; "
            "fi"
        )
    return text


def build_run_script(
    *,
    workflow_id: str,
    recipe_payload: dict[str, Any],
    recipe_dir: str,
    fs_license_file: str | None,
    executables: dict[str, str] | None = None,
) -> str:
    executables = executables or {}
    recipe = recipe_payload.get("recipe") or {}
    path_prefixes: list[str] = []
    ensure_dirs: list[str] = []
    params: dict[str, Any] = {}
    for key in ("mriqc", "fmriprep"):
        resolved = str(executables.get(key) or "").strip()
        if resolved.startswith("/"):
            parent = str(Path(resolved).parent)
            if parent not in path_prefixes:
                path_prefixes.append(parent)
    bind_paths: list[str] = []
    params_text = str((recipe.get("files") or {}).get("params.json") or "")
    if params_text:
        try:
            params = json.loads(params_text)
        except json.JSONDecodeError:
            params = {}
        for key in (
            "bids_dir",
            "output_dir",
            "work_dir",
            "fmriprep_output_dir",
            "mriqc_output_dir",
            "fmriprep_work_dir",
            "mriqc_work_dir",
        ):
            raw = str(params.get(key) or "").strip()
            if raw and raw not in bind_paths:
                bind_paths.append(raw)
            if key != "bids_dir" and raw and raw not in ensure_dirs:
                ensure_dirs.append(raw)
    if fs_license_file:
        bind_paths.append(fs_license_file)
    deduped_bind_paths: list[str] = []
    for item in bind_paths:
        raw = str(item or "").strip()
        if raw and raw not in deduped_bind_paths:
            deduped_bind_paths.append(raw)
    bind_paths = deduped_bind_paths

    shell_parts = ["set -euo pipefail", f"cd {shlex.quote(recipe_dir)}"]
    if path_prefixes:
        quoted_prefix = ":".join(shlex.quote(item) for item in path_prefixes)
        shell_parts.append(f"export PATH={quoted_prefix}:$PATH")
    if ensure_dirs:
        shell_parts.append(
            "mkdir -p " + " ".join(shlex.quote(item) for item in ensure_dirs)
        )
    if bind_paths:
        bind_csv = ",".join(bind_paths)
        shell_parts.append(
            f"export APPTAINER_BINDPATH={shlex.quote(bind_csv)}"
            "${APPTAINER_BINDPATH:+,$APPTAINER_BINDPATH}; "
            "export SINGULARITY_BINDPATH=$APPTAINER_BINDPATH"
        )
    if fs_license_file:
        shell_parts.append(f"export FS_LICENSE={shlex.quote(fs_license_file)}")
    for command in recipe.get("setup_commands") or []:
        normalized = _normalize_setup_command(str(command))
        if normalized:
            shell_parts.append(normalized)
    participant_label = params.get("participant_label") or []
    participant_value = (
        str(participant_label[0])
        if isinstance(participant_label, list) and participant_label
        else str(participant_label or "")
    )
    if workflow_id == "workflow_mriqc":
        run_command = (
            f"BIDS_DIR={shlex.quote(str(params.get('bids_dir') or ''))} "
            f"OUTPUT_DIR={shlex.quote(str(params.get('output_dir') or ''))} "
            f"WORK_DIR={shlex.quote(str(params.get('work_dir') or ''))} "
            f"PARTICIPANT_LABEL={shlex.quote(participant_value)} "
            "bash run_workflow_mriqc.sh"
        )
    elif workflow_id == "workflow_fmriprep_preprocessing":
        prefix = (
            f"FS_LICENSE={shlex.quote(fs_license_file)} " if fs_license_file else ""
        )
        run_command = (
            prefix
            + f"BIDS_DIR={shlex.quote(str(params.get('bids_dir') or ''))} "
            + f"OUTPUT_DIR={shlex.quote(str(params.get('output_dir') or ''))} "
            + f"WORK_DIR={shlex.quote(str(params.get('work_dir') or ''))} "
            + f"PARTICIPANT_LABEL={shlex.quote(participant_value)} "
            + "bash run_workflow_fmriprep_preprocessing.sh"
        )
    elif workflow_id == "workflow_preprocessing_qc":
        prefix = (
            f"FS_LICENSE={shlex.quote(fs_license_file)} " if fs_license_file else ""
        )
        root_output = str(params.get("output_dir") or "")
        root_work = str(params.get("fmriprep_work_dir") or params.get("work_dir") or "")
        fmriprep_output = str(
            params.get("fmriprep_output_dir") or f"{root_output}/fmriprep"
        )
        mriqc_output = str(params.get("mriqc_output_dir") or f"{root_output}/mriqc")
        fmriprep_work = str(params.get("fmriprep_work_dir") or f"{root_work}/fmriprep")
        mriqc_work = str(params.get("mriqc_work_dir") or f"{root_work}/mriqc")
        run_command = (
            prefix
            + f"BIDS_DIR={shlex.quote(str(params.get('bids_dir') or ''))} "
            + f"PARTICIPANT_LABEL={shlex.quote(participant_value)} "
            + f"OUTPUT_DIR={shlex.quote(fmriprep_output)} "
            + f"WORK_DIR={shlex.quote(fmriprep_work)} "
            + "bash run_fmriprep.sh; "
            + prefix
            + f"BIDS_DIR={shlex.quote(str(params.get('bids_dir') or ''))} "
            + f"PARTICIPANT_LABEL={shlex.quote(participant_value)} "
            + f"OUTPUT_DIR={shlex.quote(mriqc_output)} "
            + f"WORK_DIR={shlex.quote(mriqc_work)} "
            + "bash run_mriqc.sh; "
            + "python post_qc.py"
        )
    else:
        run_command = str(recipe.get("run_command") or "").strip()
        if not run_command:
            raise ValueError("recipe payload did not include run_command")
    shell_parts.append(run_command)
    return "; ".join(shell_parts)


def build_supervised_wrapper_script(
    *,
    run_script: str,
    state_dir: str,
    log_dir: str,
    remote_execute_timeout_s: float,
    heartbeat_interval_s: float,
) -> str:
    timeout_seconds = max(int(remote_execute_timeout_s), 1)
    heartbeat_seconds = max(int(heartbeat_interval_s), 1)
    payload_marker = "__BR_REMOTE_PAYLOAD__"
    return f"""#!/usr/bin/env bash
set -euo pipefail
STATE_DIR={shlex.quote(state_dir)}
LOG_DIR={shlex.quote(log_dir)}
PAYLOAD_SH="$STATE_DIR/payload.sh"
HEARTBEAT_FILE="$STATE_DIR/heartbeat"
STATE_FILE="$STATE_DIR/state"
EXIT_CODE_FILE="$STATE_DIR/exit_code"
PID_FILE="$STATE_DIR/pid"
STARTED_FILE="$STATE_DIR/started_at"
FINISHED_FILE="$STATE_DIR/finished_at"
LAUNCHER_PID_FILE="$STATE_DIR/launcher_pid"
STDOUT_LOG="$LOG_DIR/stdout.log"
STDERR_LOG="$LOG_DIR/stderr.log"

mkdir -p "$STATE_DIR" "$LOG_DIR"
printf '%s\\n' "$$" > "$LAUNCHER_PID_FILE"
cat > "$PAYLOAD_SH" <<'{payload_marker}'
{run_script.rstrip()}
{payload_marker}
chmod 755 "$PAYLOAD_SH"
date -u +%Y-%m-%dT%H:%M:%SZ > "$STARTED_FILE"
date -u +%Y-%m-%dT%H:%M:%SZ > "$HEARTBEAT_FILE"
printf 'running\\n' > "$STATE_FILE"

timeout --foreground --kill-after=30s {timeout_seconds}s bash "$PAYLOAD_SH" >"$STDOUT_LOG" 2>"$STDERR_LOG" &
child_pid=$!
printf '%s\\n' "$child_pid" > "$PID_FILE"

(
  while kill -0 "$child_pid" 2>/dev/null; do
    date -u +%Y-%m-%dT%H:%M:%SZ > "$HEARTBEAT_FILE"
    sleep {heartbeat_seconds}
  done
) &
heartbeat_pid=$!

set +e
wait "$child_pid"
rc=$?
set -e
kill "$heartbeat_pid" 2>/dev/null || true
wait "$heartbeat_pid" 2>/dev/null || true

date -u +%Y-%m-%dT%H:%M:%SZ > "$FINISHED_FILE"
printf '%s\\n' "$rc" > "$EXIT_CODE_FILE"
if [[ "$rc" -eq 0 ]]; then
  printf 'succeeded\\n' > "$STATE_FILE"
elif [[ "$rc" -eq 124 ]]; then
  printf 'timeout\\n' > "$STATE_FILE"
elif [[ "$rc" -eq 137 ]]; then
  printf 'oom\\n' > "$STATE_FILE"
else
  printf 'failed\\n' > "$STATE_FILE"
fi
"""


def launch_remote_supervised_job(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    remote_recipe_dir: str,
    remote_state_dir: str,
    wrapper_name: str,
    timeout_s: float,
) -> dict[str, Any]:
    wrapper_path = f"{remote_recipe_dir.rstrip('/')}/{wrapper_name}"
    launcher_stdout = f"{remote_state_dir.rstrip('/')}/launcher.stdout"
    launcher_stderr = f"{remote_state_dir.rstrip('/')}/launcher.stderr"
    launch_script = (
        f"mkdir -p {shlex.quote(remote_state_dir)}; "
        f"cd {shlex.quote(remote_recipe_dir)}; "
        f"nohup bash {shlex.quote(wrapper_path)} "
        f">{shlex.quote(launcher_stdout)} 2>{shlex.quote(launcher_stderr)} "
        "</dev/null & echo $!"
    )
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_bash(
            pod=pod,
            namespace=namespace,
            script=launch_script,
        ),
        timeout_s=timeout_s,
        check=True,
    )
    launcher_pid = str(proc.stdout or "").strip().splitlines()
    return {
        "wrapper_path": wrapper_path,
        "state_dir": remote_state_dir,
        "launcher_stdout": launcher_stdout,
        "launcher_stderr": launcher_stderr,
        "launcher_pid": launcher_pid[-1] if launcher_pid else "",
    }


def read_remote_supervised_job_status(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    state_dir: str,
    log_dir: str,
    timeout_s: float,
) -> dict[str, Any]:
    code = """
import json, os, sys, time
from pathlib import Path

state_dir = Path(sys.argv[1]).resolve()
log_dir = Path(sys.argv[2]).resolve()
payload = {
    'state_dir': str(state_dir),
    'log_dir': str(log_dir),
    'state_dir_exists': state_dir.exists(),
    'log_dir_exists': log_dir.exists(),
}

def read_text(path: Path) -> str:
    if not path.exists():
        return ''
    try:
        return path.read_text(encoding='utf-8').strip()
    except Exception:
        return ''

def tail_text(path: Path, max_bytes: int = 2000) -> str:
    if not path.exists():
        return ''
    with path.open('rb') as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(size - max_bytes, 0))
        return handle.read().decode('utf-8', errors='replace').strip()

for name in ('state', 'pid', 'launcher_pid', 'exit_code', 'started_at', 'finished_at', 'heartbeat'):
    payload[name] = read_text(state_dir / name)

payload['stdout_log'] = str(log_dir / 'stdout.log')
payload['stderr_log'] = str(log_dir / 'stderr.log')
payload['stdout_tail'] = tail_text(log_dir / 'stdout.log')
payload['stderr_tail'] = tail_text(log_dir / 'stderr.log')
payload['launcher_stdout_tail'] = tail_text(state_dir / 'launcher.stdout')
payload['launcher_stderr_tail'] = tail_text(state_dir / 'launcher.stderr')

pid_text = payload.get('pid') or ''
payload['pid_alive'] = pid_text.isdigit() and Path(f'/proc/{pid_text}').exists()
heartbeat_path = state_dir / 'heartbeat'
payload['heartbeat_age_s'] = None
if heartbeat_path.exists():
    payload['heartbeat_age_s'] = max(0.0, time.time() - heartbeat_path.stat().st_mtime)

combined = '\\n'.join(
    item for item in (
        payload.get('stderr_tail'),
        payload.get('stdout_tail'),
        payload.get('launcher_stderr_tail'),
    ) if item
).lower()
payload['oom_hint'] = (
    str(payload.get('exit_code') or '').strip() == '137'
    or 'out of memory' in combined
    or 'oom' in combined
    or '\\nkilled\\n' in combined
)
print(json.dumps(payload, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[state_dir, log_dir],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def _classify_remote_terminal_status(status: dict[str, Any]) -> tuple[str, str]:
    state = str(status.get("state") or "").strip().lower()
    exit_code = str(status.get("exit_code") or "").strip()
    if state == "timeout":
        return "failed_timeout_remote", "remote_deadline_exceeded"
    if state == "oom" or bool(status.get("oom_hint")):
        return "failed_oom", f"remote_exit_code:{exit_code or '137'}"
    if state == "failed":
        return "failed_code", f"remote_recipe_exit_code:{exit_code or 'unknown'}"
    return "failed_code", f"remote_state:{state or 'unknown'}"


def wait_for_remote_supervised_job(
    *,
    report_dir: Path,
    workflow_id: str,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    state_dir: str,
    log_dir: str,
    request_timeout_s: float,
    poll_interval_s: float,
    poll_timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(poll_timeout_s, poll_interval_s, 1.0)
    interval = max(poll_interval_s, 1.0)
    last_status: dict[str, Any] | None = None
    last_transport_error: dict[str, Any] | None = None
    last_state = ""
    while time.monotonic() < deadline:
        try:
            status = read_remote_supervised_job_status(
                vm_name=vm_name,
                zone=zone,
                project=project,
                namespace=namespace,
                pod=pod,
                state_dir=state_dir,
                log_dir=log_dir,
                timeout_s=request_timeout_s,
            )
            last_status = status
            state = str(status.get("state") or "").strip().lower()
            if state != last_state:
                emit_progress(
                    report_dir,
                    f"[poll] {workflow_id} state={state or 'unknown'}",
                    workflow_id=workflow_id,
                    state=state or "unknown",
                )
                last_state = state
            if state in {"succeeded", "timeout", "oom", "failed"}:
                return status
        except subprocess.TimeoutExpired as exc:
            last_transport_error = {
                "kind": "timeout",
                "timeout_seconds": request_timeout_s,
                "error": str(exc),
            }
        except Exception as exc:  # pragma: no cover - defensive path
            last_transport_error = {
                "kind": "error",
                "error": str(exc),
            }
        time.sleep(interval)
    if last_status:
        status = dict(last_status)
        status["classification"] = "failed_timeout_local"
        status["reason"] = "local_poll_deadline_exceeded"
        if last_transport_error:
            status["transport_error"] = last_transport_error
        return status
    return {
        "state": "unknown",
        "classification": "failed_timeout_local",
        "reason": "local_poll_deadline_exceeded",
        "transport_error": last_transport_error
        or {
            "kind": "timeout",
            "timeout_seconds": request_timeout_s,
        },
    }


def validate_remote_artifacts(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    workflow_id: str,
    output_dir: str,
    timeout_s: float,
) -> dict[str, Any]:
    code = """
import json, sys
from pathlib import Path

workflow_id = sys.argv[1]
output_dir = Path(sys.argv[2]).resolve()
payload = {'workflow_id': workflow_id, 'output_dir': str(output_dir), 'artifacts': {}}

def add(name: str, path: Path) -> None:
    payload['artifacts'][name] = {'path': str(path), 'exists': path.exists()}

if workflow_id == 'workflow_mriqc':
    add('dataset_description.json', output_dir / 'dataset_description.json')
    subject_report = next(output_dir.glob('sub-*.html'), None)
    add('subject_report_html', subject_report or (output_dir / 'missing.html'))
elif workflow_id == 'workflow_fmriprep_preprocessing':
    add('dataset_description.json', output_dir / 'dataset_description.json')
    add('derivatives_dir', output_dir)
elif workflow_id == 'workflow_preprocessing_qc':
    for rel in ('qc/qc_table.csv', 'qc/qc_outliers.csv', 'qc/qc_summary.json', 'qc/index.html'):
        add(rel, output_dir / rel)
    add('fmriprep/dataset_description.json', output_dir / 'fmriprep' / 'dataset_description.json')
    subject_report = next((output_dir / 'mriqc').glob('sub-*.html'), None)
    add('mriqc/subject_report_html', subject_report or (output_dir / 'mriqc' / 'missing.html'))
else:
    raise RuntimeError(f'unsupported workflow_id: {workflow_id}')

payload['ok'] = all(item['exists'] for item in payload['artifacts'].values())
print(json.dumps(payload, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[workflow_id, output_dir],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


def inspect_remote_artifacts(
    *,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    artifacts: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    payload_b64 = base64.b64encode(
        json.dumps(artifacts, sort_keys=True).encode("utf-8")
    ).decode("ascii")
    code = """
import base64, json, sys
from pathlib import Path

artifacts = json.loads(base64.b64decode(sys.argv[1].encode('ascii')).decode('utf-8'))
payload = {'artifacts': {}}
for name, item in artifacts.items():
    raw_path = str((item or {}).get('path') or '').strip()
    path = Path(raw_path).resolve() if raw_path else None
    entry = {'path': raw_path, 'exists': bool(path and path.exists())}
    if path and path.exists():
        if path.is_dir():
            size_bytes = 0
            for child in path.rglob('*'):
                if child.is_file():
                    try:
                        size_bytes += child.stat().st_size
                    except OSError:
                        pass
            entry['kind'] = 'dir'
            entry['size_bytes'] = size_bytes
        else:
            entry['kind'] = 'file'
            try:
                entry['size_bytes'] = path.stat().st_size
            except OSError:
                entry['size_bytes'] = None
    payload['artifacts'][name] = entry
print(json.dumps(payload, indent=2))
""".strip()
    proc = run_remote_command(
        vm_name=vm_name,
        zone=zone,
        project=project,
        remote_command=_kubectl_exec_python(
            pod=pod,
            namespace=namespace,
            code=code,
            args=[payload_b64],
        ),
        timeout_s=timeout_s,
        check=True,
    )
    return json.loads(proc.stdout)


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


def download_remote_artifacts(
    *,
    report_dir: Path,
    workflow_id: str,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    artifacts: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    workflow_dir = report_dir / workflow_id
    downloads_dir = workflow_dir / "downloaded_artifacts"
    inspected = inspect_remote_artifacts(
        vm_name=vm_name,
        zone=zone,
        project=project,
        namespace=namespace,
        pod=pod,
        artifacts=artifacts,
        timeout_s=timeout_s,
    )
    write_json(workflow_dir / "downloaded_artifacts.inspect.json", inspected)
    manifest: dict[str, Any] = {"download_dir": str(downloads_dir), "artifacts": {}}
    for name, item in (inspected.get("artifacts") or {}).items():
        if not bool(item.get("exists")):
            manifest["artifacts"][name] = {
                **item,
                "downloaded": False,
                "reason": "missing_remote_artifact",
            }
            continue
        remote_path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "file").strip()
        local_name = _artifact_output_filename(name, remote_path, kind)
        local_path = downloads_dir / local_name
        remote = Path(remote_path)
        if kind == "dir":
            remote_command = _kubectl_exec_bash(
                pod=pod,
                namespace=namespace,
                script=(
                    f"tar -C {shlex.quote(str(remote.parent))} -czf - "
                    f"{shlex.quote(remote.name)}"
                ),
            )
        else:
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
            destination=local_path,
            timeout_s=timeout_s,
        )
        manifest["artifacts"][name] = {
            **item,
            **download_meta,
            "downloaded": True,
        }
    manifest["ok"] = all(
        bool(item.get("downloaded")) for item in manifest["artifacts"].values()
    )
    write_json(workflow_dir / "downloaded_artifacts.json", manifest)
    return manifest


def certify_workflow(
    client: HttpMCPClient,
    *,
    workflow_id: str,
    recipe_target: str,
    report_dir: Path,
    vm_name: str,
    zone: str,
    project: str,
    namespace: str,
    pod: str,
    participant_label: str,
    staged_bids_root: str,
    staged_qc_tsv: str | None,
    staged_fs_license: str | None,
    remote_input_root: str,
    remote_output_root: str,
    executables: dict[str, str] | None,
    request_timeout_s: float,
    remote_execute_timeout_s: float,
    remote_launch_timeout_s: float,
    remote_timeout_grace_s: float,
    poll_interval_s: float,
    heartbeat_interval_s: float,
    artifact_download_timeout_s: float,
    dry_run: bool,
) -> dict[str, Any]:
    workflow_dir = report_dir / workflow_id
    workflow_dir.mkdir(parents=True, exist_ok=True)

    emit_progress(
        report_dir,
        f"[recipe] get_execution_recipe {workflow_id}",
        workflow_id=workflow_id,
    )
    recipe_payload = get_recipe(
        client, workflow_id=workflow_id, recipe_target=recipe_target
    )
    write_json(workflow_dir / "recipe.json", recipe_payload)
    run_pack = _run_pack_payload(recipe_payload)
    if run_pack:
        write_json(workflow_dir / "run_pack.json", run_pack)
        write_json(workflow_dir / "local_run.json", run_pack)

    remote_recipe_dir = f"{remote_input_root.rstrip('/')}/{workflow_id}/recipe"
    remote_output_dir = f"{remote_output_root.rstrip('/')}/{workflow_id}"
    remote_work_dir = f"{remote_input_root.rstrip('/')}/{workflow_id}/work"
    remote_state_dir = f"{remote_input_root.rstrip('/')}/{workflow_id}/state"
    remote_log_dir = f"{remote_output_dir.rstrip('/')}/logs"
    files = override_recipe_files(
        recipe_payload,
        workflow_id=workflow_id,
        participant_label=participant_label,
        bids_dir=staged_bids_root,
        output_dir=remote_output_dir,
        work_dir=remote_work_dir,
        qc_tsv=staged_qc_tsv,
        fs_license_file=staged_fs_license,
    )
    recipe_payload_for_run = {
        **recipe_payload,
        "recipe": {**(recipe_payload.get("recipe") or {}), "files": files},
    }
    run_script = build_run_script(
        workflow_id=workflow_id,
        recipe_payload=recipe_payload_for_run,
        recipe_dir=remote_recipe_dir,
        fs_license_file=staged_fs_license,
        executables=executables,
    )
    files["run_supervised.sh"] = build_supervised_wrapper_script(
        run_script=run_script,
        state_dir=remote_state_dir,
        log_dir=remote_log_dir,
        remote_execute_timeout_s=remote_execute_timeout_s,
        heartbeat_interval_s=heartbeat_interval_s,
    )
    staged_recipe = stage_recipe_files(
        vm_name=vm_name,
        zone=zone,
        project=project,
        namespace=namespace,
        pod=pod,
        remote_dir=remote_recipe_dir,
        files=files,
        timeout_s=request_timeout_s,
    )
    write_json(workflow_dir / "recipe.stage.json", staged_recipe)
    write_json(workflow_dir / "run.command.json", {"bash": run_script})

    if dry_run:
        result = {
            "workflow_id": workflow_id,
            "classification": "dry_run",
            "reason": "recipe_staged",
            "recipe_target": recipe_target,
            "recipe_dir": remote_recipe_dir,
            "output_dir": remote_output_dir,
            "work_dir": remote_work_dir,
            "state_dir": remote_state_dir,
        }
        result = _attach_run_pack(result, run_pack)
        result = _attach_handoff_bundle(
            result,
            report_dir=report_dir,
            workflow_id=workflow_id,
            recipe_payload=recipe_payload_for_run,
            run_pack=run_pack,
            downloaded_artifacts=None,
        )
        write_json(workflow_dir / "result.json", result)
        return result

    emit_progress(report_dir, f"[execute] {workflow_id}", workflow_id=workflow_id)
    try:
        launch = launch_remote_supervised_job(
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=pod,
            remote_recipe_dir=remote_recipe_dir,
            remote_state_dir=remote_state_dir,
            wrapper_name="run_supervised.sh",
            timeout_s=remote_launch_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return _record_workflow_failure(
            report_dir=report_dir,
            workflow_id=workflow_id,
            recipe_target=recipe_target,
            classification="failed_timeout_local",
            reason="remote_launch_deadline_exceeded",
            output_dir=remote_output_dir,
            work_dir=remote_work_dir,
            state_dir=remote_state_dir,
            details={"error": str(exc), "timeout_seconds": remote_launch_timeout_s},
            run_pack=run_pack,
        )
    except Exception as exc:
        return _record_workflow_failure(
            report_dir=report_dir,
            workflow_id=workflow_id,
            recipe_target=recipe_target,
            classification="failed_surface",
            reason="remote_launch_failed",
            output_dir=remote_output_dir,
            work_dir=remote_work_dir,
            state_dir=remote_state_dir,
            details={"error": str(exc)},
            run_pack=run_pack,
        )
    write_json(workflow_dir / "launch.json", launch)
    try:
        status = wait_for_remote_supervised_job(
            report_dir=report_dir,
            workflow_id=workflow_id,
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=pod,
            state_dir=remote_state_dir,
            log_dir=remote_log_dir,
            request_timeout_s=request_timeout_s,
            poll_interval_s=poll_interval_s,
            poll_timeout_s=max(
                remote_execute_timeout_s + remote_timeout_grace_s,
                poll_interval_s,
            ),
        )
    except Exception as exc:
        return _record_workflow_failure(
            report_dir=report_dir,
            workflow_id=workflow_id,
            recipe_target=recipe_target,
            classification="failed_surface",
            reason="remote_poll_failed",
            output_dir=remote_output_dir,
            work_dir=remote_work_dir,
            state_dir=remote_state_dir,
            details={"error": str(exc)},
            run_pack=run_pack,
        )
    write_json(workflow_dir / "remote_status.json", status)
    state = str(status.get("state") or "").strip().lower()
    if state != "succeeded":
        classification = str(status.get("classification") or "")
        reason = str(status.get("reason") or "")
        if not classification or not reason:
            if state == "timeout" and _remote_smoke_started(status):
                classification = "verified_deferred"
                reason = "smoke_budget_exhausted_deferred_to_local"
            else:
                classification, reason = _classify_remote_terminal_status(status)
        result = {
            "workflow_id": workflow_id,
            "classification": classification,
            "reason": reason,
            "recipe_target": recipe_target,
            "output_dir": remote_output_dir,
            "work_dir": remote_work_dir,
            "state_dir": remote_state_dir,
            "remote_status": status,
        }
        result = _attach_run_pack(result, run_pack)
        if classification == "verified_deferred":
            result["cert_budget_seconds"] = remote_execute_timeout_s
            result = _attach_handoff_bundle(
                result,
                report_dir=report_dir,
                workflow_id=workflow_id,
                recipe_payload=recipe_payload_for_run,
                run_pack=run_pack,
                downloaded_artifacts=None,
            )
        write_json(workflow_dir / "result.json", result)
        return result

    try:
        artifacts = validate_remote_artifacts(
            vm_name=vm_name,
            zone=zone,
            project=project,
            namespace=namespace,
            pod=pod,
            workflow_id=workflow_id,
            output_dir=remote_output_dir,
            timeout_s=request_timeout_s,
        )
    except Exception as exc:
        return _record_workflow_failure(
            report_dir=report_dir,
            workflow_id=workflow_id,
            recipe_target=recipe_target,
            classification="failed_surface",
            reason="artifact_validation_failed",
            output_dir=remote_output_dir,
            work_dir=remote_work_dir,
            state_dir=remote_state_dir,
            details={"error": str(exc), "remote_status": status},
            run_pack=run_pack,
        )
    write_json(workflow_dir / "artifacts.json", artifacts)
    classification = "verified" if artifacts.get("ok") else "failed_code"
    reason = "recipe_run_succeeded" if artifacts.get("ok") else "missing_artifacts"
    downloaded_artifacts = None
    if classification == "verified":
        try:
            downloaded_artifacts = download_remote_artifacts(
                report_dir=report_dir,
                workflow_id=workflow_id,
                vm_name=vm_name,
                zone=zone,
                project=project,
                namespace=namespace,
                pod=pod,
                artifacts=dict(artifacts.get("artifacts") or {}),
                timeout_s=artifact_download_timeout_s,
            )
        except Exception as exc:
            return _record_workflow_failure(
                report_dir=report_dir,
                workflow_id=workflow_id,
                recipe_target=recipe_target,
                classification="failed_surface",
                reason="artifact_download_failed",
                output_dir=remote_output_dir,
                work_dir=remote_work_dir,
                state_dir=remote_state_dir,
                details={"error": str(exc), "artifacts": artifacts},
                run_pack=run_pack,
            )
        if not bool((downloaded_artifacts or {}).get("ok")):
            return _record_workflow_failure(
                report_dir=report_dir,
                workflow_id=workflow_id,
                recipe_target=recipe_target,
                classification="failed_surface",
                reason="artifact_download_incomplete",
                output_dir=remote_output_dir,
                work_dir=remote_work_dir,
                state_dir=remote_state_dir,
                details={
                    "artifacts": artifacts,
                    "downloaded_artifacts": downloaded_artifacts,
                },
                run_pack=run_pack,
            )
    result = {
        "workflow_id": workflow_id,
        "classification": classification,
        "reason": reason,
        "recipe_target": recipe_target,
        "output_dir": remote_output_dir,
        "work_dir": remote_work_dir,
        "state_dir": remote_state_dir,
        "artifacts": artifacts,
        "remote_status": status,
    }
    if downloaded_artifacts:
        result["downloaded_artifacts"] = downloaded_artifacts
    result = _attach_run_pack(result, run_pack)
    result = _attach_handoff_bundle(
        result,
        report_dir=report_dir,
        workflow_id=workflow_id,
        recipe_payload=recipe_payload_for_run,
        run_pack=run_pack,
        downloaded_artifacts=downloaded_artifacts,
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
        "verified_deferred": by_classification.get("verified_deferred", 0),
        "failed_surface": by_classification.get("failed_surface", 0),
        "failed_precondition": by_classification.get("failed_precondition", 0),
        "failed_code": by_classification.get("failed_code", 0),
        "failed_timeout_local": by_classification.get("failed_timeout_local", 0),
        "failed_timeout_remote": by_classification.get("failed_timeout_remote", 0),
        "failed_oom": by_classification.get("failed_oom", 0),
        "dry_run": by_classification.get("dry_run", 0),
        "by_classification": by_classification,
    }


def _write_summary_text(report_dir: Path, payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    lines = [
        f"generated_at: {payload.get('generated_at')}",
        f"mcp_url: {payload.get('mcp_url')}",
        f"dry_run: {payload.get('dry_run')}",
        f"verified: {summary.get('verified')}",
        f"verified_deferred: {summary.get('verified_deferred')}",
        f"failed_surface: {summary.get('failed_surface')}",
        f"failed_precondition: {summary.get('failed_precondition')}",
        f"failed_code: {summary.get('failed_code')}",
        f"failed_timeout_local: {summary.get('failed_timeout_local')}",
        f"failed_timeout_remote: {summary.get('failed_timeout_remote')}",
        f"failed_oom: {summary.get('failed_oom')}",
        f"dry_run_count: {summary.get('dry_run')}",
        "",
    ]
    for row in payload.get("results") or []:
        lines.append(
            f"{row.get('workflow_id')}: {row.get('classification')} ({row.get('reason')})"
        )
    (report_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    global _ACTIVE_RESEARCH_LOGGER
    args = parse_args(argv)
    selected = _selected_workflows(list(args.workflow_id))

    report_dir = Path(args.output_root) / utc_stamp()
    report_dir.mkdir(parents=True, exist_ok=True)
    _ACTIVE_RESEARCH_LOGGER = ResearchLoggingSession(
        source_client="prod_external_repo_certification",
        client_session_id=report_dir.name,
    )
    emit_progress(
        report_dir, "[start] prod external-repo certification", dry_run=args.dry_run
    )

    token = args.mcp_token
    token_source = "explicit"
    if not token:
        local_token = resolve_mcp_token()
        if local_token:
            token = local_token
            token_source = "local_resolver"
            emit_progress(report_dir, "[auth] using local BR_MCP_TOKEN resolver")
        else:
            token = resolve_prod_mcp_token(
                vm_name=args.vm_name,
                zone=args.zone,
                project=args.project,
                namespace=args.namespace,
                secret_name=DEFAULT_SECRET_NAME,
                secret_key=DEFAULT_SECRET_KEY,
                timeout_s=args.timeout_s,
            )
            token_source = "prod_secret"
            emit_progress(report_dir, "[auth] using prod k3s secret")

    client = HttpMCPClient(
        url=args.mcp_url,
        token=token,
        timeout_s=args.timeout_s,
        client_name="prod_external_repo_certification",
    )
    _ACTIVE_RESEARCH_LOGGER.bind_client(client)
    _ACTIVE_RESEARCH_LOGGER.start(
        "Start prod external-repo certification.",
        tags=["ops", "prod", "certification", "external_repo"],
    )

    probe = probe_agent_environment(
        vm_name=args.vm_name,
        zone=args.zone,
        project=args.project,
        namespace=args.namespace,
        pod=args.agent_pod,
        dataset_root=args.dataset_root,
        fmriprep_deriv_root=args.fmriprep_deriv_root,
        timeout_s=args.timeout_s,
    )
    write_json(report_dir / "agent_probe.json", probe)

    local_fs_license = resolve_local_fs_license(args.fs_license_file)
    if not local_fs_license:
        emit_progress(report_dir, "[inputs] no local FreeSurfer license found")
    else:
        emit_progress(report_dir, f"[inputs] using local FS license {local_fs_license}")

    remote_input_root = f"{args.remote_input_root.rstrip('/')}/{report_dir.name}"
    remote_output_root = f"{args.remote_output_root.rstrip('/')}/{report_dir.name}"
    staged_license = None
    if local_fs_license:
        staged = stage_file_in_agent(
            vm_name=args.vm_name,
            zone=args.zone,
            project=args.project,
            namespace=args.namespace,
            pod=args.agent_pod,
            local_path=local_fs_license,
            remote_path=f"{remote_input_root}/freesurfer/license.txt",
            timeout_s=args.timeout_s,
        )
        staged_license = str(staged["remote_path"])
        write_json(report_dir / "fs_license.stage.json", staged)
    elif str(probe.get("fs_license_env") or "").strip():
        staged_license = str(probe.get("fs_license_env")).strip()
        write_json(
            report_dir / "fs_license.stage.json",
            {"remote_path": staged_license, "source": "agent_env"},
        )

    precondition_failures: list[dict[str, Any]] = []
    blocked_workflows: set[str] = set()
    if not staged_license:
        for workflow_id in selected:
            if workflow_id not in {
                "workflow_fmriprep_preprocessing",
                "workflow_preprocessing_qc",
            }:
                continue
            emit_progress(
                report_dir,
                f"[precondition] missing FreeSurfer license for {workflow_id}",
                workflow_id=workflow_id,
            )
            precondition_failures.append(
                _record_precondition_failure(
                    report_dir=report_dir,
                    workflow_id=workflow_id,
                    recipe_target=args.recipe_target,
                    reason="missing_fs_license",
                    details={
                        "local_fs_license": str(local_fs_license or ""),
                        "agent_fs_license_env": str(probe.get("fs_license_env") or ""),
                    },
                )
            )
            blocked_workflows.add(workflow_id)

    staged_subset = stage_minimal_bids_subset(
        vm_name=args.vm_name,
        zone=args.zone,
        project=args.project,
        namespace=args.namespace,
        pod=args.agent_pod,
        dataset_root=args.dataset_root,
        participant_label=args.participant_label,
        remote_subset_root=f"{remote_input_root}/ds000114_sub-{args.participant_label}_minimal",
        session_label=DEFAULT_SESSION_LABEL,
        task_name=DEFAULT_TASK_NAME,
        timeout_s=args.timeout_s,
    )
    write_json(report_dir / "bids_subset.stage.json", staged_subset)

    staged_qc = None
    if (
        "workflow_preprocessing_qc" in selected
        and "workflow_preprocessing_qc" not in blocked_workflows
    ):
        derivative_roots = _candidate_fmriprep_deriv_roots(args.fmriprep_deriv_root)
        try:
            staged_qc = stage_precomputed_qc_table(
                vm_name=args.vm_name,
                zone=args.zone,
                project=args.project,
                namespace=args.namespace,
                pod=args.agent_pod,
                fmriprep_deriv_roots=derivative_roots,
                participant_label=args.participant_label,
                session_label=DEFAULT_SESSION_LABEL,
                task_name=DEFAULT_TASK_NAME,
                remote_qc_tsv=f"{remote_input_root}/precomputed_qc.tsv",
                timeout_s=args.timeout_s,
            )
            write_json(report_dir / "qc_tsv.stage.json", staged_qc)
        except RuntimeError as exc:
            emit_progress(
                report_dir,
                "[precondition] missing precomputed QC table for workflow_preprocessing_qc",
                workflow_id="workflow_preprocessing_qc",
            )
            precondition_failures.append(
                _record_precondition_failure(
                    report_dir=report_dir,
                    workflow_id="workflow_preprocessing_qc",
                    recipe_target=args.recipe_target,
                    reason="missing_precomputed_qc",
                    details={
                        "error": str(exc),
                        "derivative_roots": derivative_roots,
                        "participant_label": args.participant_label,
                        "session_label": DEFAULT_SESSION_LABEL,
                        "task_name": DEFAULT_TASK_NAME,
                    },
                )
            )
            blocked_workflows.add("workflow_preprocessing_qc")

    results = list(precondition_failures)
    for workflow_id in selected:
        if workflow_id in blocked_workflows:
            continue
        result = certify_workflow(
            client,
            workflow_id=workflow_id,
            recipe_target=args.recipe_target,
            report_dir=report_dir,
            vm_name=args.vm_name,
            zone=args.zone,
            project=args.project,
            namespace=args.namespace,
            pod=args.agent_pod,
            participant_label=args.participant_label,
            staged_bids_root=str(staged_subset["subset_root"]),
            staged_qc_tsv=str((staged_qc or {}).get("qc_tsv") or ""),
            staged_fs_license=staged_license,
            remote_input_root=remote_input_root,
            remote_output_root=remote_output_root,
            executables=dict(probe.get("executables") or {}),
            request_timeout_s=args.timeout_s,
            remote_execute_timeout_s=args.remote_execute_timeout_s,
            remote_launch_timeout_s=args.remote_launch_timeout_s,
            remote_timeout_grace_s=args.remote_timeout_grace_s,
            poll_interval_s=args.poll_interval_s,
            heartbeat_interval_s=args.heartbeat_interval_s,
            artifact_download_timeout_s=args.artifact_download_timeout_s,
            dry_run=args.dry_run,
        )
        results.append(result)

    report = {
        "generated_at": utc_now_iso(),
        "mcp_url": args.mcp_url,
        "dry_run": bool(args.dry_run),
        "selected_workflows": selected,
        "token_source": token_source,
        "agent_pod": args.agent_pod,
        "agent_probe": probe,
        "staged_bids_subset": staged_subset,
        "staged_qc_tsv": staged_qc,
        "staged_fs_license": staged_license,
        "results": results,
        "summary": summarize_results(results),
    }
    write_json(report_dir / "report.json", report)
    _write_summary_text(report_dir, report)
    print(
        json.dumps(
            {"ok": True, "report_dir": str(report_dir), "summary": report["summary"]},
            indent=2,
        )
    )
    exit_code = (
        0
        if (
            report["summary"]["failed_code"] == 0
            and report["summary"]["failed_surface"] == 0
            and report["summary"]["failed_precondition"] == 0
            and report["summary"]["failed_timeout_local"] == 0
            and report["summary"]["failed_timeout_remote"] == 0
            and report["summary"]["failed_oom"] == 0
        )
        else 1
    )
    _close_research_logger(
        logger=_ACTIVE_RESEARCH_LOGGER,
        report_dir=report_dir,
        report=report,
        exit_code=exit_code,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
