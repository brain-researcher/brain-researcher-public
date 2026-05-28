"""Batch-register FitLins multiverse outputs as BR external runs.

Usage:
  python scripts/review/import_fitlins_multiverse_batch.py \
      --search-root /oak/.../fitlins_multiverse

  python scripts/review/import_fitlins_multiverse_batch.py \
      --source-dir /path/to/one/run \
      --source-dir /path/to/another/run \
      --run-root /data/br_mcp_runs

This script scans common FitLins multiverse output layouts, imports each
candidate as a BR external run via the ``fitlins_multiverse`` adapter, and
writes a JSON summary of imported / skipped / failed sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.config.run_artifacts import get_mcp_run_root
from brain_researcher.services.review.external_artifact_adapters import (
    detect_external_artifact_adapter,
)
from brain_researcher.services.review.external_run_import import (
    ExternalRunImportSpec,
    stage_external_run_in_mcp_store,
)

UTC = timezone.utc

_MARKER_FILENAMES = frozenset(
    {
        "run_manifest.json",
        "multiverse_manifest.json",
        "robustness_yeo17.json",
        "yeo17_summary.csv",
    }
)


@dataclass(slots=True)
class BatchImportRecord:
    source_dir: str
    run_id: str
    status: str
    adapter_name: str | None = None
    review_tier: str | None = None
    run_dir: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(text: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "-" for ch in text.strip()]
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:96]


def _default_search_root() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "outputs" / "fitlins_multiverse"


def _default_output_json() -> Path:
    return (
        Path("data/exports/review")
        / f"fitlins_multiverse_batch_import_{_utc_stamp()}.json"
    )


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _candidate_root_from_path(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    if candidate.is_dir():
        return candidate
    if candidate.name not in _MARKER_FILENAMES:
        raise ValueError(f"unsupported candidate marker file: {candidate}")
    if (
        candidate.name == "multiverse_manifest.json"
        and candidate.parent.name == "specs"
    ):
        return candidate.parent.parent.resolve()
    if (
        candidate.name in {"robustness_yeo17.json", "yeo17_summary.csv"}
        and candidate.parent.name == "fitlins"
    ):
        return candidate.parent.parent.resolve()
    return candidate.parent.resolve()


def _candidate_metadata(source_dir: Path) -> tuple[str | None, str | None, str | None]:
    run_manifest = _load_json(source_dir / "run_manifest.json") or {}
    spec_manifest = _load_json(source_dir / "specs" / "multiverse_manifest.json")
    if spec_manifest is None:
        spec_manifest = _load_json(source_dir / "multiverse_manifest.json") or {}
    dataset_id = (
        str(run_manifest.get("dataset_id")).strip()
        if run_manifest.get("dataset_id")
        else None
    ) or (
        str(spec_manifest.get("dataset_id")).strip()
        if spec_manifest.get("dataset_id")
        else None
    )
    task = (
        str(run_manifest.get("task")).strip() if run_manifest.get("task") else None
    ) or (str(spec_manifest.get("task")).strip() if spec_manifest.get("task") else None)
    source_run_id = (
        str(run_manifest.get("run_id")).strip() if run_manifest.get("run_id") else None
    )
    return dataset_id, task, source_run_id


def derive_import_run_id(
    source_dir: Path, *, prefix: str = "fitlins-multiverse"
) -> str:
    dataset_id, task, source_run_id = _candidate_metadata(source_dir)
    label = source_run_id or source_dir.name
    parts = [
        _slug(prefix),
        _slug(dataset_id) if dataset_id else "",
        _slug(task) if task else "",
        _slug(label),
    ]
    core = "-".join(part for part in parts if part)
    if not core:
        core = _slug(source_dir.name) or "fitlins-multiverse"
    digest = hashlib.sha1(str(source_dir.resolve()).encode("utf-8")).hexdigest()[:10]
    max_core = 120
    return f"{core[:max_core]}-{digest}"


def discover_fitlins_multiverse_sources(
    *,
    search_roots: Sequence[Path],
    explicit_sources: Sequence[Path] = (),
    max_depth: int = 6,
) -> list[Path]:
    candidates: dict[str, Path] = {}

    def _add_candidate(path: Path) -> None:
        root = _candidate_root_from_path(path)
        if not root.exists() or not root.is_dir():
            return
        if (
            detect_external_artifact_adapter(root, preferred="fitlins_multiverse")
            is None
        ):
            return
        candidates[str(root)] = root

    for source in explicit_sources:
        _add_candidate(source)

    for raw_root in search_roots:
        search_root = raw_root.expanduser().resolve()
        if not search_root.exists() or not search_root.is_dir():
            continue
        for current, dirs, files in os.walk(search_root):
            current_path = Path(current)
            try:
                rel_parts = current_path.relative_to(search_root).parts
            except ValueError:
                rel_parts = ()
            depth = len(rel_parts)
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if depth >= max_depth:
                dirs[:] = []
            marker_names = sorted(_MARKER_FILENAMES.intersection(files))
            for marker in marker_names:
                _add_candidate(current_path / marker)

    return sorted(candidates.values(), key=lambda path: str(path))


def run_batch_import(
    *,
    sources: Sequence[Path],
    run_root: Path,
    run_id_prefix: str,
    link_mode: str,
    overwrite: bool,
    dry_run: bool,
    fail_fast: bool,
) -> list[BatchImportRecord]:
    results: list[BatchImportRecord] = []
    for source_dir in sources:
        run_id = derive_import_run_id(source_dir, prefix=run_id_prefix)
        try:
            import_result = stage_external_run_in_mcp_store(
                source_dir,
                spec=ExternalRunImportSpec(run_id=run_id),
                run_root=run_root,
                link_mode=link_mode,
                adapter_preference="fitlins_multiverse",
                overwrite=overwrite,
                dry_run=dry_run,
            )
            results.append(
                BatchImportRecord(
                    source_dir=str(source_dir),
                    run_id=run_id,
                    status="ok",
                    adapter_name=import_result.adapter_name,
                    review_tier=import_result.review_tier,
                    run_dir=import_result.run_dir,
                )
            )
        except FileExistsError as exc:
            results.append(
                BatchImportRecord(
                    source_dir=str(source_dir),
                    run_id=run_id,
                    status="skipped_existing",
                    error=str(exc),
                )
            )
            if fail_fast:
                raise
        except Exception as exc:
            results.append(
                BatchImportRecord(
                    source_dir=str(source_dir),
                    run_id=run_id,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            if fail_fast:
                raise
    return results


def _aggregate(records: Sequence[BatchImportRecord]) -> dict[str, int]:
    counts = {"ok": 0, "skipped_existing": 0, "error": 0}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    counts["total"] = len(records)
    return counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Root directory to scan recursively for FitLins multiverse outputs. Repeatable.",
    )
    parser.add_argument(
        "--source-dir",
        action="append",
        default=[],
        help="Explicit FitLins multiverse root or marker file. Repeatable.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="Maximum directory depth to scan under each --search-root.",
    )
    parser.add_argument(
        "--run-root",
        default=None,
        help="Optional explicit BR_MCP_RUN_ROOT override.",
    )
    parser.add_argument(
        "--run-id-prefix",
        default="fitlins-multiverse",
        help="Prefix for imported synthetic run ids.",
    )
    parser.add_argument(
        "--link-mode",
        choices=("symlink", "copy"),
        default="symlink",
        help="How imported artifacts should be mounted into the BR run store.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing imported run directory instead of skipping it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and plan imports without writing files.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately on the first import error.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to persist the batch import summary as JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    explicit_sources = [Path(item).expanduser().resolve() for item in args.source_dir]
    search_roots = [Path(item).expanduser().resolve() for item in args.search_root]
    if not search_roots and not explicit_sources:
        default_root = _default_search_root()
        if default_root.exists():
            search_roots = [default_root.resolve()]

    if not search_roots and not explicit_sources:
        raise SystemExit(
            "No --search-root or --source-dir provided, and default outputs/fitlins_multiverse does not exist."
        )

    run_root = (
        Path(args.run_root).expanduser().resolve()
        if args.run_root
        else get_mcp_run_root()
    )
    sources = discover_fitlins_multiverse_sources(
        search_roots=search_roots,
        explicit_sources=explicit_sources,
        max_depth=args.max_depth,
    )
    records = run_batch_import(
        sources=sources,
        run_root=run_root,
        run_id_prefix=args.run_id_prefix,
        link_mode=args.link_mode,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        fail_fast=args.fail_fast,
    )
    payload = {
        "ok": True,
        "search_roots": [str(path) for path in search_roots],
        "explicit_sources": [str(path) for path in explicit_sources],
        "run_root": str(run_root),
        "dry_run": bool(args.dry_run),
        "counts": _aggregate(records),
        "sources": [record.to_dict() for record in records],
    }

    output_json = (
        Path(args.output_json).expanduser().resolve() if args.output_json else None
    )
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["counts"].get("error", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
