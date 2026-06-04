"""Validate canonical TRIBE closed-loop artifact roots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.artifact_schema import (
    canonicalize_line_path,
    resolve_line_paths,
)
from brain_researcher.services.tools.tribe_stimulus_library import resolve_project_paths

IGNORED_EMBEDDED_PATH_PREFIXES = (
    Path("/run"),
    Path("/tmp"),
    Path("/var/tmp"),
    Path("/usr"),
    Path("/bin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/opt"),
    Path("/home/ubuntu/miniconda3"),
    *(
        Path(p)
        for p in os.environ.get("BR_EXTRA_RESTRICTED_PATHS", "").split(":")
        if p.strip()
    ),
)


@dataclass(frozen=True)
class PathFinding:
    code: str
    path: str
    detail: str


@dataclass(frozen=True)
class PathValidationResult:
    ok: bool
    canonical_project_root: str
    canonical_closed_loop_root: str
    canonical_hypothesis_ledger_path: str
    allowed_roots: tuple[str, ...]
    scanned_files: int
    findings: tuple[PathFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [asdict(item) for item in self.findings]
        return payload


def _iter_jsonl(path: Path) -> Iterable[tuple[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                yield f"{path}:{line_number}", json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} invalid JSON: {exc}") from exc


def _iter_json_objects(path: Path) -> Iterable[tuple[str, Any]]:
    if path.suffix == ".jsonl":
        yield from _iter_jsonl(path)
        return
    with path.open("r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} invalid JSON: {exc}") from exc
    yield str(path), payload


def _iter_absolute_path_strings(value: Any, context: str) -> Iterable[tuple[str, Path]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            child_context = f"{context}.{key}"
            yield from _iter_absolute_path_strings(nested, child_context)
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            child_context = f"{context}[{index}]"
            yield from _iter_absolute_path_strings(nested, child_context)
        return
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.startswith(("/", "~")):
            yield context, Path(normalized).expanduser().resolve()


def _is_under_any_root(path: Path, allowed_roots: tuple[Path, ...]) -> bool:
    for root in allowed_roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _is_ignored_runtime_path(path: Path) -> bool:
    return _is_under_any_root(path, IGNORED_EMBEDDED_PATH_PREFIXES)


def _dedupe_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    for root in roots:
        if any(root == existing for existing in unique):
            continue
        unique.append(root)
    return tuple(unique)


def _scan_closed_loop_json(
    *,
    canonical_closed_loop_root: Path,
    allowed_roots: tuple[Path, ...],
) -> tuple[int, list[PathFinding]]:
    findings: list[PathFinding] = []
    scanned_files = 0
    if not canonical_closed_loop_root.exists():
        return scanned_files, findings

    for candidate in sorted(canonical_closed_loop_root.rglob("*")):
        if candidate.suffix not in {".json", ".jsonl"} or not candidate.is_file():
            continue
        scanned_files += 1
        for context, payload in _iter_json_objects(candidate):
            for string_context, path_value in _iter_absolute_path_strings(
                payload, context
            ):
                if _is_under_any_root(
                    path_value, allowed_roots
                ) or _is_ignored_runtime_path(path_value):
                    continue
                findings.append(
                    PathFinding(
                        code="embedded_path_outside_allowed_roots",
                        path=str(path_value),
                        detail=f"Referenced from {string_context}",
                    )
                )
    return scanned_files, findings


def _find_stray_ledgers(
    project_root: Path, canonical_ledger_path: Path
) -> list[PathFinding]:
    findings: list[PathFinding] = []
    for candidate in sorted(project_root.rglob("tribe_hypothesis_ledger.jsonl")):
        resolved = candidate.resolve()
        if resolved == canonical_ledger_path:
            continue
        findings.append(
            PathFinding(
                code="stray_hypothesis_ledger",
                path=str(resolved),
                detail="Ledger exists outside canonical artifacts/closed_loop root",
            )
        )
    return findings


def validate_artifact_root(
    *,
    stimulus_library: Path,
    project_root_override: Path | None = None,
    alias_project_roots: tuple[Path, ...] = (),
    require_ledger: bool = True,
) -> PathValidationResult:
    project_paths = resolve_project_paths(stimulus_library)
    shared_paths = resolve_line_paths(
        "discovery",
        root=(
            project_root_override.expanduser().resolve()
            if project_root_override is not None
            else project_paths.project_root
        ),
    )
    canonical_project_root = shared_paths.project_root
    canonical_closed_loop_root = shared_paths.checkpoint_root or (
        canonical_project_root / "artifacts" / "closed_loop"
    )
    canonical_hypothesis_ledger_path = shared_paths.ledger_path

    allowed_roots = _dedupe_roots(
        (
            canonical_project_root,
            project_paths.analysis_root,
            project_paths.prediction_root,
            project_paths.manifests_root,
            project_paths.materialized_library_root,
            project_paths.derived_media_root,
            project_paths.tribe_cache_root,
            canonicalize_line_path(project_paths.data_root, "discovery"),
            canonicalize_line_path(project_paths.source_checkout_root, "discovery"),
        )
    )

    findings: list[PathFinding] = []
    if not canonical_closed_loop_root.exists():
        findings.append(
            PathFinding(
                code="missing_closed_loop_root",
                path=str(canonical_closed_loop_root),
                detail="Canonical artifacts/closed_loop directory does not exist",
            )
        )
    if require_ledger and not canonical_hypothesis_ledger_path.exists():
        findings.append(
            PathFinding(
                code="missing_hypothesis_ledger",
                path=str(canonical_hypothesis_ledger_path),
                detail="Canonical hypothesis ledger is missing",
            )
        )

    findings.extend(
        _find_stray_ledgers(canonical_project_root, canonical_hypothesis_ledger_path)
    )

    for alias_root in alias_project_roots:
        resolved_alias = alias_root.expanduser().resolve()
        if not resolved_alias.exists():
            continue
        findings.extend(
            _find_stray_ledgers(resolved_alias, canonical_hypothesis_ledger_path)
        )
        alias_closed_loop_root = resolved_alias / "artifacts" / "closed_loop"
        if alias_closed_loop_root.exists():
            entry_count = sum(1 for _ in alias_closed_loop_root.iterdir())
            findings.append(
                PathFinding(
                    code="alias_closed_loop_root_present",
                    path=str(alias_closed_loop_root),
                    detail=f"Alias artifacts/closed_loop exists with {entry_count} top-level entries",
                )
            )

    scanned_files, scan_findings = _scan_closed_loop_json(
        canonical_closed_loop_root=canonical_closed_loop_root,
        allowed_roots=allowed_roots,
    )
    findings.extend(scan_findings)

    return PathValidationResult(
        ok=not findings,
        canonical_project_root=str(canonical_project_root),
        canonical_closed_loop_root=str(canonical_closed_loop_root),
        canonical_hypothesis_ledger_path=str(canonical_hypothesis_ledger_path),
        allowed_roots=tuple(str(root) for root in allowed_roots),
        scanned_files=scanned_files,
        findings=tuple(findings),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stimulus-library",
        type=Path,
        required=True,
        help="Path to an explicit TRIBE stimulus-library YAML.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Optional override for the canonical TRIBE project root.",
    )
    parser.add_argument(
        "--alias-project-root",
        type=Path,
        action="append",
        default=[],
        help="Known legacy/alias project root that should be treated as drift if it still contains artifacts.",
    )
    parser.add_argument(
        "--allow-missing-ledger",
        action="store_true",
        help="Do not fail if the canonical hypothesis ledger is absent.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the validation report as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_artifact_root(
            stimulus_library=args.stimulus_library.expanduser().resolve(),
            project_root_override=(
                args.project_root.expanduser().resolve()
                if args.project_root is not None
                else None
            ),
            alias_project_roots=tuple(
                path.expanduser().resolve() for path in args.alias_project_root
            ),
            require_ledger=not args.allow_missing_ledger,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"Canonical project root: {result.canonical_project_root}")
        print(f"Closed-loop root: {result.canonical_closed_loop_root}")
        print(f"Hypothesis ledger: {result.canonical_hypothesis_ledger_path}")
        if result.findings:
            print("Findings:", file=sys.stderr)
            for finding in result.findings:
                print(
                    f"- [{finding.code}] {finding.path}: {finding.detail}",
                    file=sys.stderr,
                )
        else:
            print("OK: no path drift detected")
    return 0 if result.ok else 1


__all__ = [
    "PathFinding",
    "PathValidationResult",
    "build_parser",
    "main",
    "validate_artifact_root",
]
