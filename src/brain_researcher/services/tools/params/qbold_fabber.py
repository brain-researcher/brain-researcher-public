"""Deterministic qBOLD FABBER planning helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _coerce_float_sequence(values: object | None) -> tuple[float, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = [item for item in values.replace(";", ",").split(",") if item.strip()]
    if isinstance(values, Sequence):
        return tuple(float(v) for v in values)
    return (float(values),)


def _coerce_string_sequence(values: object | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        stripped = values.strip()
        return tuple(part for part in stripped.split() if part)
    if isinstance(values, Sequence):
        return tuple(str(v) for v in values if v is not None)
    return (str(values),)


@dataclass(frozen=True)
class QBoldFabberParameters:
    """Normalised configuration for a FABBER qBOLD plan."""

    input_file: str
    output_dir: str
    dry_run: bool = True
    mask_file: str | None = None
    model: str = "qbold"
    method: str = "vb"
    te: float | None = None
    echo_times: tuple[float, ...] = field(default_factory=tuple)
    tau_list: tuple[float, ...] = field(default_factory=tuple)
    infer_oef: bool = True
    infer_dbv: bool = True
    infer_r2p: bool = True
    priors: Mapping[str, Any] = field(default_factory=dict)
    fabber_bin: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    env: Mapping[str, str] = field(default_factory=dict)


def qbold_fabber_from_payload(payload: Mapping[str, Any]) -> QBoldFabberParameters:
    """Create a typed parameter object from a loose payload."""

    output_dir = payload.get("output_dir") or Path.cwd() / "qbold_fabber"
    return QBoldFabberParameters(
        input_file=str(payload["input_file"]),
        output_dir=str(output_dir),
        dry_run=bool(payload.get("dry_run", True)),
        mask_file=str(payload["mask_file"]) if payload.get("mask_file") else None,
        model=str(payload.get("model", "qbold")),
        method=str(payload.get("method", "vb")),
        te=float(payload["te"]) if payload.get("te") is not None else None,
        echo_times=_coerce_float_sequence(payload.get("echo_times")),
        tau_list=_coerce_float_sequence(payload.get("tau_list")),
        infer_oef=bool(payload.get("infer_oef", True)),
        infer_dbv=bool(payload.get("infer_dbv", True)),
        infer_r2p=bool(payload.get("infer_r2p", True)),
        priors=dict(payload.get("priors") or {}),
        fabber_bin=str(payload["fabber_bin"]) if payload.get("fabber_bin") else None,
        extra_args=_coerce_string_sequence(payload.get("extra_args")),
        env=dict(payload.get("env") or {}),
    )


def resolve_qbold_fabber_executable(params: QBoldFabberParameters) -> str:
    """Resolve the FABBER qBOLD executable, preferring explicit overrides."""

    if params.fabber_bin:
        return params.fabber_bin
    env_override = os.environ.get("FABBER_QBOLD_BIN")
    if env_override:
        return env_override
    detected = shutil.which("fabber_qbold")
    return detected or "fabber_qbold"


def build_qbold_fabber_command(
    params: QBoldFabberParameters, *, executable: str | None = None
) -> list[str]:
    """Construct a deterministic FABBER qBOLD command preview."""

    binary = executable or resolve_qbold_fabber_executable(params)
    cmd = [
        binary,
        "--data",
        params.input_file,
        "--output",
        params.output_dir,
        "--model",
        params.model,
        "--method",
        params.method,
    ]

    if params.mask_file:
        cmd.extend(["--mask", params.mask_file])
    if params.te is not None:
        cmd.extend(["--te", str(params.te)])
    if params.echo_times:
        cmd.extend(
            ["--echo-times", ",".join(str(value) for value in params.echo_times)]
        )
    if params.tau_list:
        cmd.extend(["--tau-list", ",".join(str(value) for value in params.tau_list)])

    if params.infer_oef:
        cmd.append("--infer-oef")
    else:
        cmd.append("--no-infer-oef")

    if params.infer_dbv:
        cmd.append("--infer-dbv")
    else:
        cmd.append("--no-infer-dbv")

    if params.infer_r2p:
        cmd.append("--infer-r2p")
    else:
        cmd.append("--no-infer-r2p")

    for key in sorted(params.priors):
        cmd.extend(["--prior", f"{key}={params.priors[key]}"])

    if params.extra_args:
        cmd.extend(params.extra_args)
    return cmd


def qbold_fabber_environment_status(
    params: QBoldFabberParameters,
    *,
    executable: str | None = None,
) -> dict[str, Any]:
    """Return a concise environment report for the qBOLD scaffold."""

    binary = executable or resolve_qbold_fabber_executable(params)
    env = dict(params.env)
    status = {
        "binary": binary,
        "binary_available": False,
        "fabber_qbold_env": os.environ.get("FABBER_QBOLD_BIN"),
        "fsl_dir": os.environ.get("FSLDIR"),
        "env_override_count": len(env),
    }
    if params.fabber_bin or status["fabber_qbold_env"]:
        status["binary_available"] = Path(binary).exists() or shutil.which(binary) is not None
    else:
        status["binary_available"] = shutil.which(binary) is not None
    return status


def _execute_qbold_fabber_command(
    planned_command: list[str],
    *,
    params: QBoldFabberParameters,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({key: str(value) for key, value in params.env.items()})
    return subprocess.run(
        planned_command,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(Path(params.output_dir)),
    )


def run_qbold_fabber(params: QBoldFabberParameters) -> dict[str, object]:
    """Create a deterministic FABBER qBOLD plan and optionally execute it."""

    input_path = Path(params.input_file)
    if not input_path.exists():
        raise FileNotFoundError(params.input_file)
    if params.mask_file and not Path(params.mask_file).exists():
        raise FileNotFoundError(params.mask_file)

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    executable = resolve_qbold_fabber_executable(params)
    planned_command = build_qbold_fabber_command(params, executable=executable)
    env_status = qbold_fabber_environment_status(params, executable=executable)

    expected_outputs = {
        "oef_map": str(out_dir / "qbold_oef_map.nii.gz"),
        "dbv_map": str(out_dir / "qbold_dbv_map.nii.gz"),
        "r2p_map": str(out_dir / "qbold_r2p_map.nii.gz"),
        "posterior_summary": str(out_dir / "qbold_posterior_summary.json"),
        "log": str(out_dir / "qbold_fabber.log"),
    }

    plan = {
        "tool": "qbold_fabber",
        "input_file": params.input_file,
        "mask_file": params.mask_file,
        "model": params.model,
        "method": params.method,
        "te": params.te,
        "echo_times": list(params.echo_times),
        "tau_list": list(params.tau_list),
        "infer_oef": params.infer_oef,
        "infer_dbv": params.infer_dbv,
        "infer_r2p": params.infer_r2p,
        "priors": dict(params.priors),
        "planned_command": planned_command,
        "environment": env_status,
        "expected_outputs": expected_outputs,
        "dry_run": params.dry_run,
    }

    plan_json_path = out_dir / "qbold_fabber_plan.json"
    command_path = out_dir / "qbold_fabber_command.txt"
    execution_report_path = out_dir / "qbold_fabber_execution.json"
    stdout_path = out_dir / "qbold_fabber_stdout.txt"
    stderr_path = out_dir / "qbold_fabber_stderr.txt"
    plan_json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    command_path.write_text(" ".join(planned_command), encoding="utf-8")

    executed = False
    returncode: int | None = None
    materialized_outputs = {
        key: value for key, value in expected_outputs.items() if Path(value).exists()
    }

    if not params.dry_run and env_status["binary_available"]:
        completed = _execute_qbold_fabber_command(planned_command, params=params)
        executed = True
        returncode = int(completed.returncode)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        execution_report = {
            "tool": "qbold_fabber",
            "command": planned_command,
            "returncode": returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "backend_available": True,
        }
        execution_report_path.write_text(
            json.dumps(execution_report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if returncode != 0:
            raise RuntimeError(
                f"qBOLD FABBER execution failed with return code {returncode}"
            )
        materialized_outputs = {
            key: value for key, value in expected_outputs.items() if Path(value).exists()
        }
        mode = "executed"
        message = "qBOLD FABBER executed successfully."
    else:
        mode = "dry_run" if params.dry_run else "planned_only_missing_backend"
        message = (
            "qBOLD FABBER dry run completed."
            if params.dry_run
            else "qBOLD FABBER backend unavailable; plan preserved without execution."
        )

    return {
        "outputs": {
            "plan_json": str(plan_json_path),
            "command_preview": str(command_path),
            "execution_report": str(execution_report_path) if executed else None,
            "stdout": str(stdout_path) if executed else None,
            "stderr": str(stderr_path) if executed else None,
            "expected_outputs": expected_outputs,
            "materialized_outputs": materialized_outputs,
        },
        "summary": {
            "tool_id": "qbold_fabber",
            "mode": mode,
            "dry_run": params.dry_run,
            "backend_available": env_status["binary_available"],
            "resolved_executable": executable,
            "model": params.model,
            "method": params.method,
            "has_mask": params.mask_file is not None,
            "echo_times_count": len(params.echo_times),
            "tau_list_count": len(params.tau_list),
            "planned_command": planned_command,
            "returncode": returncode,
            "materialized_output_keys": sorted(materialized_outputs.keys()),
        },
        "message": message,
    }


__all__ = [
    "QBoldFabberParameters",
    "build_qbold_fabber_command",
    "qbold_fabber_environment_status",
    "qbold_fabber_from_payload",
    "resolve_qbold_fabber_executable",
    "run_qbold_fabber",
]
