"""Canonical artifact and path contracts for predictive and discovery lines."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LineId = Literal["predictive", "discovery"]

DEFAULT_DATA_ROOT = Path("/data/brain_researcher")
RESEARCH_ROOT_NAME = "research"


def _normalize_path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


@dataclass(frozen=True)
class LineSpec:
    line_id: LineId
    canonical_name: str
    legacy_name: str
    ledger_name: str
    extra_ledgers: tuple[str, ...] = ()


LINE_SPECS: dict[LineId, LineSpec] = {
    "predictive": LineSpec(
        line_id="predictive",
        canonical_name="predictive",
        legacy_name="fc_benchmarking",
        ledger_name="experiments.jsonl",
    ),
    "discovery": LineSpec(
        line_id="discovery",
        canonical_name="discovery",
        legacy_name="tribe_encoding",
        ledger_name="tribe_hypothesis_ledger.jsonl",
        extra_ledgers=("tribe_kg_call_log.jsonl", "tribe_surprises.jsonl"),
    ),
}


@dataclass(frozen=True)
class ArtifactPaths:
    line_id: LineId
    data_root: Path
    line_root: Path
    legacy_line_root: Path
    project_root: Path
    artifact_root: Path
    ledger_path: Path
    status_root: Path
    diagnostics_root: Path | None
    checkpoint_root: Path | None
    manifests_root: Path
    inputs_root: Path
    sources_root: Path
    prompts_root: Path | None
    scored_ledgers: tuple[Path, ...]
    alias_line_roots: tuple[Path, ...]
    alias_project_roots: tuple[Path, ...]

    def to_dict(self) -> dict[str, str | list[str] | None]:
        return {
            "line_id": self.line_id,
            "data_root": str(self.data_root),
            "line_root": str(self.line_root),
            "legacy_line_root": str(self.legacy_line_root),
            "project_root": str(self.project_root),
            "artifact_root": str(self.artifact_root),
            "ledger_path": str(self.ledger_path),
            "status_root": str(self.status_root),
            "diagnostics_root": (
                None if self.diagnostics_root is None else str(self.diagnostics_root)
            ),
            "checkpoint_root": (
                None if self.checkpoint_root is None else str(self.checkpoint_root)
            ),
            "manifests_root": str(self.manifests_root),
            "inputs_root": str(self.inputs_root),
            "sources_root": str(self.sources_root),
            "prompts_root": (
                None if self.prompts_root is None else str(self.prompts_root)
            ),
            "scored_ledgers": [str(path) for path in self.scored_ledgers],
            "alias_line_roots": [str(path) for path in self.alias_line_roots],
            "alias_project_roots": [str(path) for path in self.alias_project_roots],
        }


def line_spec(line_id: LineId) -> LineSpec:
    try:
        return LINE_SPECS[line_id]
    except KeyError as exc:
        raise ValueError(f"Unknown autoresearch line_id: {line_id}") from exc


def resolve_data_root(data_root: Path | str | None = None) -> Path:
    return _normalize_path(data_root or DEFAULT_DATA_ROOT)


def canonical_line_root(
    line_id: LineId, *, data_root: Path | str | None = None
) -> Path:
    spec = line_spec(line_id)
    return resolve_data_root(data_root) / RESEARCH_ROOT_NAME / spec.canonical_name


def legacy_line_root(line_id: LineId, *, data_root: Path | str | None = None) -> Path:
    spec = line_spec(line_id)
    return resolve_data_root(data_root) / spec.legacy_name


def remote_alias_line_roots(line_id: LineId) -> tuple[Path, ...]:
    spec = line_spec(line_id)
    # Default: /home/ubuntu (generic cloud-VM dev convention).
    # Override with BR_REMOTE_ALIAS_ROOTS=path1:path2:... for additional roots.
    alias_bases_env = os.environ.get("BR_REMOTE_ALIAS_ROOTS", "").strip()
    if alias_bases_env:
        alias_bases = [b.strip() for b in alias_bases_env.split(":") if b.strip()]
    else:
        alias_bases = ["/home/ubuntu"]
    roots: list[Path] = []
    for base in alias_bases:
        base_path = Path(base)
        roots.append(base_path / spec.legacy_name)
        roots.append(base_path / "research" / spec.canonical_name)
    return tuple(root.resolve() for root in roots)


def _remap_under_roots(path: Path, mappings: tuple[tuple[Path, Path], ...]) -> Path:
    for source_root, destination_root in mappings:
        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue
        return (destination_root / relative).resolve()
    return path


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def canonicalize_line_path(
    value: Path | str,
    line_id: LineId,
    *,
    data_root: Path | str | None = None,
) -> Path:
    resolved = _normalize_path(value)
    canonical_root = canonical_line_root(line_id, data_root=data_root)
    legacy_root = legacy_line_root(line_id, data_root=data_root)
    mappings: list[tuple[Path, Path]] = [
        (canonical_root, canonical_root),
        (legacy_root, canonical_root),
    ]
    for alias_root in remote_alias_line_roots(line_id):
        mappings.append((alias_root, canonical_root))
    return _remap_under_roots(resolved, tuple(mappings))


def resolve_line_paths(
    line_id: LineId,
    *,
    data_root: Path | str | None = None,
    root: Path | str | None = None,
) -> ArtifactPaths:
    spec = line_spec(line_id)
    resolved_data_root = resolve_data_root(data_root)
    line_root = canonical_line_root(line_id, data_root=resolved_data_root)
    legacy_root = legacy_line_root(line_id, data_root=resolved_data_root)
    if root is not None:
        raw_root = _normalize_path(root)
        known_roots = (
            line_root,
            legacy_root,
            *remote_alias_line_roots(line_id),
        )
        if any(_is_under_root(raw_root, candidate) for candidate in known_roots):
            normalized_root = canonicalize_line_path(
                raw_root, line_id, data_root=resolved_data_root
            )
            if normalized_root == line_root / "project":
                line_root = normalized_root.parent
            elif normalized_root == line_root:
                line_root = normalized_root
            elif _is_under_root(normalized_root, line_root / "project"):
                line_root = (line_root / "project").parent
        elif raw_root.name == "project":
            line_root = raw_root.parent
        else:
            line_root = raw_root

    project_root = line_root / "project"
    artifact_root = project_root / "artifacts"
    manifests_root = project_root / "manifests"
    inputs_root = line_root / "inputs"
    sources_root = line_root / "sources"
    prompts_root: Path | None = None
    diagnostics_root: Path | None = None
    checkpoint_root: Path | None = None

    if line_id == "predictive":
        ledger_path = project_root / spec.ledger_name
        diagnostics_root = artifact_root / "diagnostics"
        status_root = diagnostics_root
        prompts_root = artifact_root / "prompts"
        scored_ledgers = (ledger_path,)
    else:
        checkpoint_root = artifact_root / "closed_loop"
        ledger_path = checkpoint_root / spec.ledger_name
        status_root = checkpoint_root
        scored_ledgers = (ledger_path,) + tuple(
            checkpoint_root / name for name in spec.extra_ledgers
        )

    alias_line_roots = tuple(
        dict.fromkeys(
            [
                legacy_root,
                *remote_alias_line_roots(line_id),
            ]
        )
    )
    alias_project_roots = tuple(root / "project" for root in alias_line_roots)

    return ArtifactPaths(
        line_id=line_id,
        data_root=resolved_data_root,
        line_root=line_root,
        legacy_line_root=legacy_root,
        project_root=project_root,
        artifact_root=artifact_root,
        ledger_path=ledger_path,
        status_root=status_root,
        diagnostics_root=diagnostics_root,
        checkpoint_root=checkpoint_root,
        manifests_root=manifests_root,
        inputs_root=inputs_root,
        sources_root=sources_root,
        prompts_root=prompts_root,
        scored_ledgers=scored_ledgers,
        alias_line_roots=alias_line_roots,
        alias_project_roots=alias_project_roots,
    )


__all__ = [
    "ArtifactPaths",
    "DEFAULT_DATA_ROOT",
    "LINE_SPECS",
    "LineId",
    "LineSpec",
    "canonical_line_root",
    "canonicalize_line_path",
    "legacy_line_root",
    "line_spec",
    "remote_alias_line_roots",
    "resolve_data_root",
    "resolve_line_paths",
]
