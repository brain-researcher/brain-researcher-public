"""Helpers for building slice-aware FSL PNM EV regressors."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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
class PnmEvsRegressorParameters:
    """Normalized configuration for an FSL `pnm_evs` run."""

    func_file: str
    output_dir: str
    tr: float
    dry_run: bool = False
    output_prefix: str = "pnm"
    cardiac_file: str | None = None
    respiratory_file: str | None = None
    rvt_file: str | None = None
    heartrate_file: str | None = None
    csf_mask_file: str | None = None
    cardiac_order: int = 2
    respiratory_order: int = 1
    cardiac_multiplicative_order: int = 0
    respiratory_multiplicative_order: int = 0
    rvt_smooth: float | None = None
    heartrate_smooth: float | None = None
    slice_direction: str | None = None
    slice_order: str | None = None
    slice_timing_file: str | None = None
    pnm_evs_bin: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    env: Mapping[str, str] = field(default_factory=dict)


def pnm_evs_regressors_from_payload(
    payload: Mapping[str, Any],
) -> PnmEvsRegressorParameters:
    output_dir = payload.get("output_dir") or Path.cwd() / "pnm_evs_regressors"
    return PnmEvsRegressorParameters(
        func_file=str(payload["func_file"]),
        output_dir=str(output_dir),
        tr=float(payload["tr"]),
        dry_run=bool(payload.get("dry_run", False)),
        output_prefix=str(payload.get("output_prefix", "pnm")),
        cardiac_file=(
            str(payload["cardiac_file"]) if payload.get("cardiac_file") else None
        ),
        respiratory_file=(
            str(payload["respiratory_file"])
            if payload.get("respiratory_file")
            else None
        ),
        rvt_file=str(payload["rvt_file"]) if payload.get("rvt_file") else None,
        heartrate_file=(
            str(payload["heartrate_file"]) if payload.get("heartrate_file") else None
        ),
        csf_mask_file=(
            str(payload["csf_mask_file"]) if payload.get("csf_mask_file") else None
        ),
        cardiac_order=max(0, int(payload.get("cardiac_order", 2))),
        respiratory_order=max(0, int(payload.get("respiratory_order", 1))),
        cardiac_multiplicative_order=max(
            0, int(payload.get("cardiac_multiplicative_order", 0))
        ),
        respiratory_multiplicative_order=max(
            0, int(payload.get("respiratory_multiplicative_order", 0))
        ),
        rvt_smooth=(
            float(payload["rvt_smooth"])
            if payload.get("rvt_smooth") is not None
            else None
        ),
        heartrate_smooth=(
            float(payload["heartrate_smooth"])
            if payload.get("heartrate_smooth") is not None
            else None
        ),
        slice_direction=(
            str(payload["slice_direction"]) if payload.get("slice_direction") else None
        ),
        slice_order=str(payload["slice_order"]) if payload.get("slice_order") else None,
        slice_timing_file=(
            str(payload["slice_timing_file"])
            if payload.get("slice_timing_file")
            else None
        ),
        pnm_evs_bin=str(payload["pnm_evs_bin"]) if payload.get("pnm_evs_bin") else None,
        extra_args=_coerce_string_sequence(payload.get("extra_args")),
        env=dict(payload.get("env") or {}),
    )


def resolve_pnm_evs_executable(params: PnmEvsRegressorParameters) -> str:
    if params.pnm_evs_bin:
        return params.pnm_evs_bin
    env_override = os.environ.get("FSL_PNM_EVS_BIN")
    if env_override:
        return env_override
    detected = shutil.which("pnm_evs")
    return detected or "pnm_evs"


def build_pnm_evs_command(
    params: PnmEvsRegressorParameters,
    *,
    raw_output_file: str,
    executable: str | None = None,
) -> list[str]:
    binary = executable or resolve_pnm_evs_executable(params)
    cmd = [
        binary,
        "--tr",
        str(params.tr),
        "-i",
        params.func_file,
        "-o",
        raw_output_file,
    ]

    if params.cardiac_file:
        cmd.extend(["-c", params.cardiac_file, "--oc", str(params.cardiac_order)])
    if params.respiratory_file:
        cmd.extend(
            ["-r", params.respiratory_file, "--or", str(params.respiratory_order)]
        )
    if params.cardiac_multiplicative_order > 0:
        cmd.extend(["--multc", str(params.cardiac_multiplicative_order)])
    if params.respiratory_multiplicative_order > 0:
        cmd.extend(["--multr", str(params.respiratory_multiplicative_order)])
    if params.csf_mask_file:
        cmd.extend(["--csfmask", params.csf_mask_file])
    if params.rvt_file:
        cmd.extend(["--rvt", params.rvt_file])
    if params.heartrate_file:
        cmd.extend(["--heartrate", params.heartrate_file])
    if params.rvt_smooth is not None:
        cmd.extend(["--rvtsmooth", str(params.rvt_smooth)])
    if params.heartrate_smooth is not None:
        cmd.extend(["--heartratesmooth", str(params.heartrate_smooth)])
    if params.slice_direction:
        cmd.extend(["--slicedir", params.slice_direction])
    if params.slice_order:
        cmd.extend(["--sliceorder", params.slice_order])
    if params.slice_timing_file:
        cmd.extend(["--slicetiming", params.slice_timing_file])
    if params.extra_args:
        cmd.extend(params.extra_args)
    return cmd


def pnm_evs_environment_status(
    params: PnmEvsRegressorParameters,
    *,
    executable: str | None = None,
) -> dict[str, Any]:
    binary = executable or resolve_pnm_evs_executable(params)
    return {
        "binary": binary,
        "binary_available": Path(binary).exists() or shutil.which(binary) is not None,
        "fsl_dir": os.environ.get("FSLDIR"),
        "slice_aware": bool(params.slice_timing_file or params.slice_order),
        "env_override_count": len(params.env),
    }


def _default_pnm_column_names(
    params: PnmEvsRegressorParameters,
    n_columns: int,
) -> list[str]:
    names: list[str] = []
    if params.cardiac_file:
        for idx in range(1, params.cardiac_order + 1):
            names.extend(
                [
                    f"cardiac_retroicor_sin{idx}",
                    f"cardiac_retroicor_cos{idx}",
                ]
            )
    if params.respiratory_file:
        for idx in range(1, params.respiratory_order + 1):
            names.extend(
                [
                    f"respiratory_retroicor_sin{idx}",
                    f"respiratory_retroicor_cos{idx}",
                ]
            )
    if params.csf_mask_file:
        names.append("pnm_csf")
    if params.rvt_file:
        names.append("pnm_rvt")
    if params.heartrate_file:
        names.append("pnm_heartrate")
    if len(names) < n_columns:
        names.extend(
            f"{params.output_prefix}_ev_{idx:03d}"
            for idx in range(len(names) + 1, n_columns + 1)
        )
    return names[:n_columns]


def _execute_pnm_evs_command(
    planned_command: list[str],
    *,
    params: PnmEvsRegressorParameters,
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


def run_pnm_evs_regressors(params: PnmEvsRegressorParameters) -> dict[str, object]:
    func_path = Path(params.func_file)
    if not func_path.exists():
        raise FileNotFoundError(params.func_file)
    optional_inputs = [
        params.cardiac_file,
        params.respiratory_file,
        params.rvt_file,
        params.heartrate_file,
        params.csf_mask_file,
    ]
    if not any(optional_inputs):
        raise ValueError(
            "Provide at least one cardiac, respiratory, RVT, heartrate, or CSF mask input"
        )
    for optional_path in optional_inputs + [params.slice_timing_file]:
        if optional_path and not Path(optional_path).exists():
            raise FileNotFoundError(optional_path)
    if params.tr <= 0:
        raise ValueError("tr must be positive")

    out_dir = Path(params.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_output_path = out_dir / f"{params.output_prefix}_pnm_matrix.txt"
    confounds_tsv_path = out_dir / f"{params.output_prefix}_confounds.tsv"
    metadata_path = out_dir / f"{params.output_prefix}_metadata.json"
    command_path = out_dir / f"{params.output_prefix}_command.txt"
    stdout_path = out_dir / f"{params.output_prefix}_stdout.txt"
    stderr_path = out_dir / f"{params.output_prefix}_stderr.txt"

    executable = resolve_pnm_evs_executable(params)
    planned_command = build_pnm_evs_command(
        params,
        raw_output_file=str(raw_output_path),
        executable=executable,
    )
    env_status = pnm_evs_environment_status(params, executable=executable)
    plan = {
        "tool": "pnm_evs_regressors",
        "func_file": params.func_file,
        "cardiac_file": params.cardiac_file,
        "respiratory_file": params.respiratory_file,
        "rvt_file": params.rvt_file,
        "heartrate_file": params.heartrate_file,
        "csf_mask_file": params.csf_mask_file,
        "slice_direction": params.slice_direction,
        "slice_order": params.slice_order,
        "slice_timing_file": params.slice_timing_file,
        "planned_command": planned_command,
        "environment": env_status,
        "raw_output_file": str(raw_output_path),
        "confounds_file": str(confounds_tsv_path),
        "dry_run": params.dry_run,
    }
    command_path.write_text(" ".join(planned_command), encoding="utf-8")

    executed = False
    returncode: int | None = None
    stdout_text = ""
    stderr_text = ""
    column_names: list[str] = []

    if not params.dry_run:
        completed = _execute_pnm_evs_command(planned_command, params=params)
        executed = True
        returncode = completed.returncode
        stdout_text = completed.stdout or ""
        stderr_text = completed.stderr or ""
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")
        if completed.returncode != 0:
            metadata_path.write_text(
                json.dumps(
                    {**plan, "executed": True, "returncode": returncode}, indent=2
                ),
                encoding="utf-8",
            )
            raise RuntimeError(stderr_text or stdout_text or "pnm_evs execution failed")
        if not raw_output_path.exists():
            raise RuntimeError("pnm_evs completed without producing an EV matrix")

        matrix = np.loadtxt(raw_output_path, ndmin=2)
        if matrix.size == 0:
            raise RuntimeError("pnm_evs produced an empty EV matrix")
        if matrix.ndim == 1:
            matrix = matrix.reshape(-1, 1)
        column_names = _default_pnm_column_names(params, int(matrix.shape[1]))
        pd.DataFrame(matrix, columns=column_names).to_csv(
            confounds_tsv_path,
            sep="\t",
            index=False,
        )

    metadata = {
        **plan,
        "executed": executed,
        "returncode": returncode,
        "stdout_file": str(stdout_path) if stdout_path.exists() else None,
        "stderr_file": str(stderr_path) if stderr_path.exists() else None,
        "column_names": column_names,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


__all__ = [
    "PnmEvsRegressorParameters",
    "build_pnm_evs_command",
    "pnm_evs_environment_status",
    "pnm_evs_regressors_from_payload",
    "resolve_pnm_evs_executable",
    "run_pnm_evs_regressors",
]
