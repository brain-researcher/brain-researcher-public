"""Source-path I/O and sidecar-staging helpers for external artifact adapters.

Pure filesystem helpers that locate, load, index, and stage source files and
sidecar context files.  These functions share no review-specific logic and
are extracted here to keep ``external_artifact_adapters`` focused on payload
assembly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Source JSON / artifact-rel helpers
# ---------------------------------------------------------------------------


def _source_primary_json(
    source: Path,
    preferred_name: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    from brain_researcher.services.review.external_artifact_adapters import (  # noqa: PLC0415
        _load_json,
    )

    if source.is_file():
        payload = _load_json(source)
        if payload is None:
            return None, None, None
        artifact_rel = f"artifacts/source/{source.name}"
        return payload, source.name, artifact_rel

    path = source / preferred_name
    payload = _load_json(path)
    if payload is None:
        return None, None, None
    artifact_rel = f"artifacts/source/{preferred_name}"
    return payload, preferred_name, artifact_rel


def _source_artifact_rel(source_dir: Path, path: Path) -> str:
    return f"artifacts/source/{path.relative_to(source_dir).as_posix()}"


def _collect_generic_indexed_files(source: Path, *preferred_names: str) -> list[str]:
    indexed: list[str] = []
    seen: set[str] = set()
    if source.is_file():
        rel = f"artifacts/source/{source.name}"
        indexed.append(rel)
        seen.add(rel)
        return indexed

    for name in preferred_names:
        path = source / name
        if path.exists():
            rel = f"artifacts/source/{name}"
            indexed.append(rel)
            seen.add(rel)
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {
            ".json",
            ".jsonl",
            ".md",
            ".csv",
            ".tsv",
            ".npy",
        }:
            continue
        rel = f"artifacts/source/{path.name}"
        if rel in seen:
            continue
        indexed.append(rel)
        seen.add(rel)
        if len(indexed) >= 8:
            break
    return indexed


# ---------------------------------------------------------------------------
# Ancestor / registry helpers
# ---------------------------------------------------------------------------


def _find_ancestor_file(
    source: Path, filename: str, *, max_depth: int = 6
) -> Path | None:
    current = source.parent if source.is_file() else source
    for _ in range(max_depth + 1):
        candidate = current / filename
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _load_experiment_registry_entry(
    source: Path,
    run_id: str | None,
) -> tuple[dict[str, Any] | None, Path | None]:
    from brain_researcher.services.review.external_artifact_adapters import (  # noqa: PLC0415
        _iter_jsonl,
    )

    if not isinstance(run_id, str) or not run_id.strip():
        return None, None
    registry_path = _find_ancestor_file(source, "experiments.jsonl")
    if registry_path is None:
        return None, None
    for payload in _iter_jsonl(registry_path) or ():
        payload_run_id = payload.get("run_id")
        if isinstance(payload_run_id, str) and payload_run_id.strip() == run_id.strip():
            return payload, registry_path
    return None, registry_path


# ---------------------------------------------------------------------------
# Sidecar-file staging helpers
# ---------------------------------------------------------------------------


def _should_stage_sidecar_file(source: Path, sidecar: Path) -> bool:
    if not sidecar.exists():
        return False
    if source.is_file():
        return True
    try:
        return not sidecar.resolve().is_relative_to(source.resolve())
    except ValueError:
        return True


def _resolve_sidecar_path(source: Path, raw_path: str | None) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path.strip()).expanduser()
    search_roots = [source.parent if source.is_file() else source]
    if candidate.is_absolute():
        return candidate.resolve() if candidate.exists() else None
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def _append_context_sidecar_file(
    *,
    source: Path,
    indexed_artifacts: list[str],
    extra_source_files: list[dict[str, str]],
    raw_path: str | None,
    role: str,
) -> None:
    sidecar_path = _resolve_sidecar_path(source, raw_path)
    if sidecar_path is None or not _should_stage_sidecar_file(source, sidecar_path):
        return
    artifact_rel = f"artifacts/source/context/{sidecar_path.name}"
    if any(item.get("artifact_rel") == artifact_rel for item in extra_source_files):
        return
    extra_source_files.append(
        {
            "source_path": str(sidecar_path),
            "artifact_rel": artifact_rel,
            "role": role,
        }
    )
    if artifact_rel not in indexed_artifacts:
        indexed_artifacts.append(artifact_rel)
