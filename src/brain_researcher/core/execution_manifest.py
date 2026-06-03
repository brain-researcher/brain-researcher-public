"""Execution manifest writer.

Best-effort emission of reproducibility-oriented entrypoints for analysis bundles.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.execution_manifest import (
    ExecutionEntrypointsV1,
    ExecutionIORefV1,
    ExecutionManifestV1,
    ExecutionModeV1,
    ExecutionReproV1,
    ExecutionRuntimeV1,
    NeurodeskExecutionV1,
)

_PYTHON_SCRIPT_CANDIDATES = ("analysis.py", "run_analysis.py", "main.py")
_ENV_FILE_CANDIDATES = ("requirements.txt", "environment.yml", "environment.yaml")
_DOCKER_COMPOSE_CANDIDATES = ("docker-compose.repro.yml", "docker-compose.yml")
_INTERNAL_OUTPUT_FILENAMES = {
    "analysis_bundle.json",
    "analysis.json",
    "artifact_manifest.json",
    "execution_manifest.json",
    "inputs_manifest.json",
    "observation.json",
    "provenance.json",
    "reward_breakdown.json",
    "run.sh",
    "stderr.txt",
    "stdout.txt",
    "trace.jsonl",
    "trajectory.json",
}
_URI_PREFIXES = ("http://", "https://", "s3://", "gs://", "hf://")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _is_uri(value: str) -> bool:
    lowered = value.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _URI_PREFIXES)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _extract_payload(job: Any) -> dict[str, Any]:
    payload_json = getattr(job, "payload_json", None)
    if not payload_json:
        return {}
    try:
        parsed = json.loads(payload_json)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _coerce_command(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            return shlex.split(value)
        except ValueError:
            return [value.strip()]
    return []


def _command_from_sources(
    *,
    provenance: dict[str, Any],
    run_card: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    candidates = [
        provenance.get("command"),
        _safe_dict(run_card.get("execution")).get("command"),
        payload.get("command"),
    ]
    for candidate in candidates:
        command = _coerce_command(candidate)
        if command:
            return command
    return []


def _extract_parameters(
    *,
    provenance: dict[str, Any],
    run_card: dict[str, Any],
    analysis_manifest: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    for candidate in (
        provenance.get("parameters"),
        run_card.get("parameters"),
        analysis_manifest.get("parameters"),
        payload.get("parameters"),
        payload.get("params"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _extract_packages(
    *,
    provenance: dict[str, Any],
    run_card: dict[str, Any],
) -> dict[str, str]:
    candidates = [
        provenance.get("packages"),
        _safe_dict(run_card.get("environment")).get("packages"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return {
                str(name): str(version)
                for name, version in candidate.items()
                if str(name).strip() and str(version).strip()
            }
    return {}


def _resolve_existing_file(run_dir: Path, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        path = run_dir / candidate
        if path.exists() and path.is_file():
            return candidate
    return None


def _resolve_python_script(run_dir: Path, command: list[str]) -> str | None:
    existing = _resolve_existing_file(run_dir, _PYTHON_SCRIPT_CANDIDATES)
    if existing:
        return existing
    if (
        len(command) >= 2
        and command[0].startswith("python")
        and command[1].endswith(".py")
    ):
        candidate = Path(command[1])
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(run_dir.resolve()).as_posix()
            except Exception:
                return None
        rel = candidate.as_posix()
        if (run_dir / rel).exists():
            return rel
    return None


def _write_requirements_if_missing(
    run_dir: Path, packages: dict[str, str]
) -> str | None:
    existing = _resolve_existing_file(run_dir, _ENV_FILE_CANDIDATES)
    if existing:
        return existing
    if not packages:
        return None
    path = run_dir / "requirements.txt"
    lines = [f"{name}=={version}" for name, version in sorted(packages.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.name


def _write_run_script_if_missing(run_dir: Path, command: list[str]) -> str | None:
    path = run_dir / "run.sh"
    if path.exists() and path.is_file():
        return path.name
    if not command:
        return None
    content = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + shlex.join(command) + "\n"
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o755)
    except OSError:
        pass
    return path.name


def _extract_inputs(inputs_manifest: dict[str, Any]) -> list[ExecutionIORefV1]:
    rows = _safe_list(inputs_manifest.get("inputs"))
    outputs: list[ExecutionIORefV1] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = _first_text(row.get("path"), row.get("resolved_path"))
        if not path:
            continue
        if _is_uri(path):
            kind = "uri"
        elif row.get("checksum_reason") == "is_directory":
            kind = "directory"
        else:
            kind = "file"
        outputs.append(
            ExecutionIORefV1(
                name=_first_text(row.get("key"), Path(path).name, "input") or "input",
                kind=kind,
                required=True,
                description=_first_text(row.get("key")),
                path=path,
            )
        )
    return outputs


def _extract_outputs(artifacts: list[dict[str, Any]]) -> list[ExecutionIORefV1]:
    outputs: list[ExecutionIORefV1] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = _first_text(
            artifact.get("path"),
            artifact.get("uri"),
            artifact.get("download_url"),
            artifact.get("url"),
        )
        if not path:
            continue
        if Path(path).name in _INTERNAL_OUTPUT_FILENAMES:
            continue
        kind = "uri" if _is_uri(path) else "file"
        outputs.append(
            ExecutionIORefV1(
                name=_first_text(
                    artifact.get("name"),
                    artifact.get("file_name"),
                    artifact.get("artifact_id"),
                    artifact.get("id"),
                )
                or Path(path).name
                or "output",
                kind=kind,
                description=_first_text(
                    artifact.get("type"), artifact.get("media_type")
                ),
                path=path,
            )
        )
    return outputs


def _extract_python_version(
    *, provenance: dict[str, Any], run_card: dict[str, Any]
) -> str | None:
    candidates = [
        _safe_dict(provenance.get("environment")).get("python_version"),
        _safe_dict(_safe_dict(provenance.get("runtime")).get("host")).get(
            "python_version"
        ),
        _safe_dict(run_card.get("environment")).get("python_version"),
    ]
    for candidate in candidates:
        text = _first_text(candidate)
        if text:
            return text.split()[0]
    return sys.version.split()[0]


def _extract_neurodesk(command: list[str]) -> NeurodeskExecutionV1 | None:
    if not command:
        return None
    command_text = shlex.join(command)
    if not any(
        token in command_text
        for token in (
            "neurodesk",
            "/cvmfs/neurodesk",
            "apptainer",
            "singularity",
            ".simg",
        )
    ):
        return None
    modules = sorted(
        set(re.findall(r"module\s+load\s+([A-Za-z0-9._/-]+)", command_text))
    )
    container_paths = sorted(
        {
            token
            for token in command
            if "/cvmfs/neurodesk" in token or token.endswith(".simg")
        }
    )
    return NeurodeskExecutionV1(
        modules=modules,
        container_paths=container_paths,
        command_template=command_text,
    )


def _resolve_execution_mode(
    *,
    entrypoints: ExecutionEntrypointsV1,
    neurodesk: NeurodeskExecutionV1 | None,
) -> ExecutionModeV1:
    modes: list[ExecutionModeV1] = []
    if entrypoints.python_script:
        modes.append(ExecutionModeV1.python_script)
    if entrypoints.shell_script:
        modes.append(ExecutionModeV1.shell_script)
    if entrypoints.docker_compose:
        modes.append(ExecutionModeV1.docker_compose)
    if neurodesk:
        modes.append(ExecutionModeV1.neurodesk)
    unique = list(dict.fromkeys(modes))
    if not unique:
        return ExecutionModeV1.unknown
    if len(unique) == 1:
        return unique[0]
    return ExecutionModeV1.mixed


def build_execution_manifest(
    job: Any | None,
    output_dir: Path,
    *,
    observation: dict[str, Any] | None = None,
    analysis_manifest: dict[str, Any] | None = None,
    artifact_manifest: dict[str, Any] | None = None,
    inputs_manifest: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    run_card: dict[str, Any] | None = None,
) -> ExecutionManifestV1:
    run_dir = (
        Path(getattr(job, "run_dir", output_dir))
        if job is not None
        else Path(output_dir)
    )
    payload = _extract_payload(job) if job is not None else {}
    observation = (
        observation or _read_json_if_exists(run_dir / "observation.json") or {}
    )
    analysis_manifest = (
        analysis_manifest or _read_json_if_exists(run_dir / "analysis.json") or {}
    )
    artifact_manifest = (
        artifact_manifest
        or _read_json_if_exists(run_dir / "artifact_manifest.json")
        or {}
    )
    inputs_manifest = (
        inputs_manifest or _read_json_if_exists(run_dir / "inputs_manifest.json") or {}
    )
    provenance = (
        provenance
        or _safe_dict(observation.get("provenance"))
        or _read_json_if_exists(run_dir / "provenance.json")
        or {}
    )
    run_card = run_card or _safe_dict(observation.get("run_card"))

    command = _command_from_sources(
        provenance=provenance,
        run_card=run_card,
        payload=payload,
    )
    python_script = _resolve_python_script(run_dir, command)
    shell_script = _write_run_script_if_missing(run_dir, command)
    environment_file = _write_requirements_if_missing(
        run_dir,
        _extract_packages(provenance=provenance, run_card=run_card),
    )
    docker_compose = _resolve_existing_file(run_dir, _DOCKER_COMPOSE_CANDIDATES)
    neurodesk = _extract_neurodesk(command)

    entrypoints = ExecutionEntrypointsV1(
        python_script=python_script,
        shell_script=shell_script,
        environment_file=environment_file,
        docker_compose=docker_compose,
    )
    execution_mode = _resolve_execution_mode(
        entrypoints=entrypoints, neurodesk=neurodesk
    )
    repro_command = shlex.join(command) if command else None

    summary = _first_text(
        run_card.get("description"),
        run_card.get("title"),
        analysis_manifest.get("summary"),
        analysis_manifest.get("title"),
        payload.get("prompt"),
        payload.get("query"),
    )
    notes = "Generated from run provenance and bundle artifacts."
    if neurodesk is not None:
        notes = "Requires Neurodesk/Apptainer-compatible runtime."
    elif execution_mode == ExecutionModeV1.unknown:
        notes = "Best-effort manifest; no runnable entrypoint was recovered."

    artifacts = _safe_list(observation.get("artifacts")) or _safe_list(
        artifact_manifest.get("artifacts")
    )
    manifest = ExecutionManifestV1(
        execution_mode=execution_mode,
        summary=summary,
        entrypoints=entrypoints,
        runtime=ExecutionRuntimeV1(
            python_version=_extract_python_version(
                provenance=provenance, run_card=run_card
            ),
            docker_supported=bool(docker_compose),
            neurodesk_supported=neurodesk is not None,
        ),
        inputs=_extract_inputs(inputs_manifest),
        outputs=_extract_outputs(
            [item for item in artifacts if isinstance(item, dict)]
        ),
        parameters=_extract_parameters(
            provenance=provenance,
            run_card=run_card,
            analysis_manifest=analysis_manifest,
            payload=payload,
        ),
        repro=ExecutionReproV1(
            working_directory=".",
            command=repro_command,
            notes=notes,
        ),
        neurodesk=neurodesk,
    )
    return manifest


def save_execution_manifest(
    job: Any | None,
    output_dir: Path,
    *,
    observation: dict[str, Any] | None = None,
    analysis_manifest: dict[str, Any] | None = None,
    artifact_manifest: dict[str, Any] | None = None,
    inputs_manifest: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    run_card: dict[str, Any] | None = None,
) -> Path:
    run_dir = (
        Path(getattr(job, "run_dir", output_dir))
        if job is not None
        else Path(output_dir)
    )
    manifest = build_execution_manifest(
        job,
        run_dir,
        observation=observation,
        analysis_manifest=analysis_manifest,
        artifact_manifest=artifact_manifest,
        inputs_manifest=inputs_manifest,
        provenance=provenance,
        run_card=run_card,
    )
    path = run_dir / "execution_manifest.json"
    _atomic_write_json(path, manifest.model_dump(exclude_none=True))
    return path


def _isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["build_execution_manifest", "save_execution_manifest"]
