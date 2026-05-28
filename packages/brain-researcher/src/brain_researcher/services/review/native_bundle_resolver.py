"""Shared native bundle resolution helpers for review consumers."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any


def load_json_artifact(path: Path | None) -> Any | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_ref_path(run_dir: Path, ref: Any) -> Path | None:
    if not isinstance(ref, str) or not ref.strip():
        return None
    candidate = Path(ref.strip()).expanduser()
    return candidate if candidate.is_absolute() else run_dir / candidate


def native_analysis_bundle(run_dir: Path) -> dict[str, Any]:
    payload = load_json_artifact(run_dir / "analysis_bundle.json")
    if not isinstance(payload, dict):
        return {}
    if str(payload.get("schema_version") or "") != "analysis-bundle-v1":
        return {}
    return payload


def native_observation(
    run_dir: Path,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    native_bundle = (
        bundle if isinstance(bundle, dict) else native_analysis_bundle(run_dir)
    )
    if native_bundle:
        embedded = native_bundle.get("observation")
        if isinstance(embedded, dict):
            return embedded
        files = native_bundle.get("files")
        if isinstance(files, dict):
            payload = load_json_artifact(
                resolve_ref_path(run_dir, files.get("observation_json"))
            )
            if isinstance(payload, dict):
                return payload
    payload = load_json_artifact(run_dir / "observation.json")
    return payload if isinstance(payload, dict) else {}


def native_execution_manifest(
    run_dir: Path,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    native_bundle = (
        bundle if isinstance(bundle, dict) else native_analysis_bundle(run_dir)
    )
    if native_bundle:
        embedded = native_bundle.get("execution_manifest")
        if isinstance(embedded, dict):
            return embedded
        files = native_bundle.get("files")
        if isinstance(files, dict):
            payload = load_json_artifact(
                resolve_ref_path(run_dir, files.get("execution_manifest_json"))
            )
            if isinstance(payload, dict):
                return payload
    payload = load_json_artifact(run_dir / "execution_manifest.json")
    return payload if isinstance(payload, dict) else {}


def iter_native_candidate_paths(
    run_dir: Path,
    bundle: dict[str, Any] | None = None,
):
    native_bundle = (
        bundle if isinstance(bundle, dict) else native_analysis_bundle(run_dir)
    )
    if not native_bundle:
        return

    seen: set[str] = set()
    refs: list[Any] = []
    refs.append(native_bundle.get("qc_summary_ref"))
    refs.extend(native_bundle.get("source_manifests") or [])
    refs.extend(native_bundle.get("evidence_index") or [])
    files = native_bundle.get("files")
    if isinstance(files, dict):
        refs.extend(files.values())

    for ref in refs:
        path = resolve_ref_path(run_dir, ref)
        if path is None or not path.exists():
            continue
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        yield path


def path_matches_pattern(run_dir: Path, path: Path, pattern: str) -> bool:
    try:
        rel = path.resolve().relative_to(run_dir.resolve()).as_posix()
    except Exception:
        rel = path.name
    return PurePosixPath(rel).match(pattern) or PurePosixPath(path.name).match(
        pattern.split("/")[-1]
    )


def find_first_with_native_hints(
    run_dir: Path,
    patterns: list[str],
    bundle: dict[str, Any] | None = None,
) -> Path | None:
    native_bundle = (
        bundle if isinstance(bundle, dict) else native_analysis_bundle(run_dir)
    )
    for path in iter_native_candidate_paths(run_dir, native_bundle):
        if any(path_matches_pattern(run_dir, path, pattern) for pattern in patterns):
            return path
    for pattern in patterns:
        matches = sorted(run_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def native_analysis_manifest(
    run_dir: Path,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    native_bundle = (
        bundle if isinstance(bundle, dict) else native_analysis_bundle(run_dir)
    )
    manifest = native_bundle.get("analysis_manifest") if native_bundle else None
    if isinstance(manifest, dict):
        return manifest
    summary_path = find_first_with_native_hints(
        run_dir,
        ["source_summary.json", "**/source_summary.json"],
        bundle=native_bundle,
    )
    payload = load_json_artifact(summary_path)
    return payload if isinstance(payload, dict) else {}


def native_steps(
    run_dir: Path,
    bundle: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    observation = native_observation(run_dir, bundle)
    steps = (
        observation.get("steps") if isinstance(observation.get("steps"), list) else []
    )
    return [step for step in steps if isinstance(step, dict)]


__all__ = [
    "find_first_with_native_hints",
    "iter_native_candidate_paths",
    "load_json_artifact",
    "native_analysis_bundle",
    "native_analysis_manifest",
    "native_execution_manifest",
    "native_observation",
    "native_steps",
    "path_matches_pattern",
    "resolve_ref_path",
]
