#!/usr/bin/env python3
"""Build a task-panel subset package for rows missing live claim/publication state."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.tools.etl.migrate_task_panel_exact_ids import (
    DEFAULT_EXACT_PREFIXES,
    _env,
    _fetch_state,
    _load_rows,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where the subset task-panel package should be written.",
    )
    parser.add_argument(
        "--records-path",
        type=Path,
        default=None,
        help="Optional explicit task_panel_records.jsonl path. Defaults to sibling of manifest.",
    )
    parser.add_argument(
        "--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687")
    )
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--exact-prefix",
        action="append",
        dest="exact_prefixes",
        default=[],
        help="Exact task-id prefixes to include. Can be repeated.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _records_path(manifest_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    return manifest_path.resolve().parent / "task_panel_records.jsonl"


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _select_missing_state_rows(
    *,
    rows: list[dict[str, Any]],
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str | None,
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    with GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password)) as driver:
        with driver.session(database=neo4j_database or None) as session:
            for row in rows:
                state = session.execute_read(
                    _fetch_state,
                    paper_id=row["paper_id"],
                    run_id=row["run_id"],
                    claim_id=row["claim_id"],
                    new_task_id=row["new_task_id"],
                )
                if state is None:
                    missing.append(row)
    return missing


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_subset_manifest(
    *,
    source_manifest: dict[str, Any],
    source_manifest_path: Path,
    output_dir: Path,
    records_count: int,
    publication_count: int,
) -> dict[str, Any]:
    shard_dir = output_dir / "shards"
    raw_dir = output_dir / "raw"
    manifest_path = output_dir / "manifest_task_panel.json"
    shard_path = shard_dir / "shard_0000.jsonl"
    source_run_id = str(source_manifest.get("run_id") or "task-panel")
    run_id = f"{source_run_id}-missing-state-{_run_stamp()}"

    options = dict(source_manifest.get("options") or {})
    source_details = dict(source_manifest.get("source_details") or {})
    counts = {
        "publications_selected": publication_count,
        "shards": 1,
        "records_generated": records_count,
        "records_llm": records_count,
        "records_heuristic": 0,
        "llm_errors": 0,
        "llm_failure_reasons": {},
    }

    return {
        "run_id": run_id,
        "created_at": _utc_now_iso(),
        "source": source_manifest.get("source") or "kggen_onvoc_postprocess",
        "query": source_manifest.get("query") or "kggen-onvoc-task-panel-package",
        "prompt_template_version": source_manifest.get("prompt_template_version")
        or "n/a",
        "generator_version": "kggen-task-panel-missing-state-subset/v1",
        "options": options,
        "source_details": {
            **source_details,
            "source_manifest_path": str(source_manifest_path.resolve()),
            "subset_kind": "missing_state_exact_ids",
        },
        "paths": {
            "run_dir": str(output_dir.resolve()),
            "shard_dir": str(shard_dir.resolve()),
            "raw_dir": str(raw_dir.resolve()),
            "manifest_path": str(manifest_path.resolve()),
        },
        "counts": counts,
        "shards": [
            {
                "shard_id": 0,
                "path": str(shard_path.resolve()),
                "records_expected": records_count,
                "records_written": records_count,
                "mode": "task_panel_onvoc",
            }
        ],
        "ingest": {
            "status": "not_started",
            "started_at": None,
            "completed_at": None,
            "records_ingested": 0,
            "shards_completed": 0,
            "shards_failed": 0,
            "shards_skipped": 0,
            "mode": "spine",
            "review_queue_path": str((output_dir / "review_queue.jsonl").resolve()),
            "quality_profile": "kg_task_panel",
            "create_missing_targets": True,
            "ingest_checkpoint_path": str(
                (output_dir / "ingest_checkpoint.json").resolve()
            ),
        },
    }


def main() -> int:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    source_manifest_path = args.manifest.resolve()
    source_manifest = _load_manifest(source_manifest_path)
    records_path = _records_path(source_manifest_path, args.records_path)
    exact_prefixes = tuple(args.exact_prefixes or DEFAULT_EXACT_PREFIXES)
    rows = _load_rows(records_path, exact_prefixes)
    missing_rows = _select_missing_state_rows(
        rows=rows,
        neo4j_uri=str(args.neo4j_uri),
        neo4j_user=str(args.neo4j_user),
        neo4j_password=str(args.neo4j_password),
        neo4j_database=str(args.neo4j_database) if args.neo4j_database else None,
    )

    report = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "source_manifest_path": str(source_manifest_path),
        "records_path": str(records_path.resolve()),
        "candidate_rows": len(rows),
        "missing_state_rows": len(missing_rows),
        "publication_count": len({row["paper_id"] for row in missing_rows}),
        "output_dir": str(args.output_dir.resolve()),
    }

    if args.dry_run:
        print(json.dumps(report, ensure_ascii=True))
        return 0

    output_dir = args.output_dir.resolve()
    shard_dir = output_dir / "shards"
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    subset_records_path = output_dir / "task_panel_records.jsonl"
    subset_shard_path = shard_dir / "shard_0000.jsonl"
    selection_report_path = output_dir / "selection_report.json"
    manifest_path = output_dir / "manifest_task_panel.json"

    subset_payloads = [dict(row["record"]) for row in missing_rows]
    _write_jsonl(subset_records_path, subset_payloads)
    shutil.copy2(subset_records_path, subset_shard_path)

    manifest = _build_subset_manifest(
        source_manifest=source_manifest,
        source_manifest_path=source_manifest_path,
        output_dir=output_dir,
        records_count=len(subset_payloads),
        publication_count=len({row["paper_id"] for row in missing_rows}),
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    selection_report = {
        **report,
        "manifest_path": str(manifest_path),
        "subset_records_path": str(subset_records_path),
        "subset_shard_path": str(subset_shard_path),
        "sample_rows": [
            {
                "paper_id": row["paper_id"],
                "claim_id": row["claim_id"],
                "run_id": row["run_id"],
                "new_task_id": row["new_task_id"],
            }
            for row in missing_rows[:25]
        ],
    }
    selection_report_path.write_text(
        json.dumps(selection_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(selection_report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
