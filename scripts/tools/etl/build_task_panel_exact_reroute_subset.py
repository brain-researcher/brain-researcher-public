#!/usr/bin/env python3
"""Build a manifest-backed exact-id reroute subset from lane-specific records.

Operational rule:

- task reroutes are built for `kg_task_panel` ingest followed by exact-id migration
- concept reroutes are built for exact-id migration only
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _promotion_strategy(target_type: str) -> str:
    return (
        "kg_task_panel_ingest_then_exact_id_migration"
        if target_type == "Task"
        else "exact_id_migration_only"
    )


def _subset_kind(*, target_type: str, target_id: str, subfamily_id: str | None) -> str:
    if target_type == "Task":
        suffix = (subfamily_id or target_id).strip().replace(":", "_")
    else:
        suffix = target_id.strip().replace(":", "_")
    return f"reroute-{target_type.lower()}-{suffix}"


def _validate_args(args: argparse.Namespace) -> None:
    if args.new_target_type == "Task":
        if not args.new_family_id or not args.new_subfamily_id:
            raise SystemExit(
                "Task reroutes require --new-family-id and --new-subfamily-id"
            )


def _emit_warning(*, target_type: str, target_id: str) -> None:
    if target_type != "Concept":
        return
    print(
        (
            "WARNING: Concept reroute subset built for "
            f"{target_id}. Skip ordinary kg_task_panel ingest; "
            "promote with exact-id migration only "
            "(migrate_task_panel_exact_ids.py --exact-prefix concept:)."
        ),
        file=sys.stderr,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--records-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--new-target-type",
        choices=["Task", "Concept"],
        default="Task",
        help="Target node label for rewritten records.",
    )
    parser.add_argument(
        "--new-target-id",
        "--new-task-id",
        dest="new_target_id",
        required=True,
    )
    parser.add_argument(
        "--new-target-label",
        "--new-task-label",
        dest="new_target_label",
        required=True,
    )
    parser.add_argument(
        "--new-family-id",
        default="",
        help="Required for Task reroutes; ignored for Concept reroutes.",
    )
    parser.add_argument(
        "--new-subfamily-id",
        default="",
        help="Required for Task reroutes; ignored for Concept reroutes.",
    )
    parser.add_argument("--new-onvoc-id", default="")
    parser.add_argument("--new-onvoc-uri", default="")
    parser.add_argument("--new-original-id", default="")
    parser.add_argument("--new-mapping-type", default="")
    parser.add_argument("--new-mapping-confidence", type=float, default=None)
    parser.add_argument(
        "--family-match-method",
        default="reroute_pack",
        help="Marker written into normalization.task_panel.family_match_method",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def _rewrite_record(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    payload = json.loads(json.dumps(record))
    target = dict(payload.get("target") or {})
    mapping = dict(payload.get("mapping") or {})
    normalization = dict(payload.get("normalization") or {})
    task_panel = dict(normalization.get("task_panel") or {})
    onvoc = dict(normalization.get("onvoc") or {})

    target["type"] = args.new_target_type
    target["id"] = args.new_target_id
    target["label"] = args.new_target_label
    if args.new_onvoc_id:
        target["onvoc_id"] = args.new_onvoc_id
    else:
        target.pop("onvoc_id", None)
    if args.new_onvoc_uri:
        target["onvoc_uri"] = args.new_onvoc_uri
    else:
        target.pop("onvoc_uri", None)
    if args.new_original_id:
        target["original_id"] = args.new_original_id
    payload["target"] = target

    mapping["canonical_id"] = args.new_target_id
    if args.new_mapping_type:
        mapping["mapping_type"] = args.new_mapping_type
    if args.new_mapping_confidence is not None:
        mapping["mapping_confidence"] = args.new_mapping_confidence
    if args.new_onvoc_id:
        mapping["onvoc_id"] = args.new_onvoc_id
    else:
        mapping.pop("onvoc_id", None)
    if args.new_onvoc_uri:
        mapping["onvoc_uri"] = args.new_onvoc_uri
    else:
        mapping.pop("onvoc_uri", None)
    payload["mapping"] = mapping

    if args.new_target_type == "Task":
        task_panel["task_id"] = args.new_target_id
        task_panel["family_id"] = args.new_family_id
        task_panel["subfamily_id"] = args.new_subfamily_id
        task_panel["family_match_method"] = args.family_match_method
        task_panel["family_match_input_label"] = args.new_target_label
        task_panel["task_fold_mode"] = "subfamily"
        if args.new_onvoc_id:
            task_panel["onvoc_id"] = args.new_onvoc_id
            task_panel["base_task_id"] = f"task:onvoc:{args.new_onvoc_id.lower()}"
        else:
            task_panel.pop("onvoc_id", None)
            task_panel.pop("base_task_id", None)
        normalization["task_panel"] = task_panel
    else:
        normalization.pop("task_panel", None)

    if args.new_onvoc_id or args.new_onvoc_uri:
        if args.new_onvoc_id:
            onvoc["onvoc_id"] = args.new_onvoc_id
        else:
            onvoc.pop("onvoc_id", None)
        if args.new_onvoc_uri:
            onvoc["onvoc_uri"] = args.new_onvoc_uri
        else:
            onvoc.pop("onvoc_uri", None)
        if args.new_target_label:
            onvoc["onvoc_label"] = args.new_target_label
        normalization["onvoc"] = onvoc
    else:
        normalization.pop("onvoc", None)
    payload["normalization"] = normalization
    return payload


def _build_subset_manifest(
    *,
    source_manifest: dict[str, Any],
    source_manifest_path: Path,
    output_dir: Path,
    records_count: int,
    publication_count: int,
    subset_kind: str,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    shard_dir = output_dir / "shards"
    raw_dir = output_dir / "raw"
    manifest_path = output_dir / "manifest_task_panel.json"
    shard_path = shard_dir / "shard_0000.jsonl"
    source_run_id = str(source_manifest.get("run_id") or "task-panel")
    run_id = f"{source_run_id}-{subset_kind}-{_run_stamp()}"
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
        "query": source_manifest.get("query") or subset_kind,
        "prompt_template_version": source_manifest.get("prompt_template_version")
        or "n/a",
        "generator_version": f"{subset_kind}/v1",
        "options": options,
        "source_details": {
            **source_details,
            "source_manifest_path": str(source_manifest_path.resolve()),
            "subset_kind": subset_kind,
            "reroute_target_type": target_type,
            "reroute_target_id": target_id,
            "promotion_strategy": _promotion_strategy(target_type),
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_args(args)
    _emit_warning(target_type=args.new_target_type, target_id=args.new_target_id)
    source_manifest_path = args.source_manifest.expanduser().resolve()
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    rows = _iter_jsonl(args.records_jsonl.expanduser().resolve())
    rewritten = [_rewrite_record(row, args) for row in rows]

    report = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "source_manifest_path": str(source_manifest_path),
        "records_jsonl_path": str(args.records_jsonl.expanduser().resolve()),
        "new_target_id": args.new_target_id,
        "new_target_label": args.new_target_label,
        "new_task_id": args.new_target_id,
        "new_task_label": args.new_target_label,
        "new_target_type": args.new_target_type,
        "new_mapping_type": args.new_mapping_type,
        "new_mapping_confidence": args.new_mapping_confidence,
        "promotion_strategy": _promotion_strategy(args.new_target_type),
        "task_panel_ingest_recommended": args.new_target_type == "Task",
        "rows": len(rewritten),
        "publications": len({row["paper"]["id"] for row in rewritten}),
        "output_dir": str(args.output_dir.expanduser().resolve()),
    }
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    output_dir = args.output_dir.expanduser().resolve()
    shard_dir = output_dir / "shards"
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    records_path = output_dir / "task_panel_records.jsonl"
    shard_path = shard_dir / "shard_0000.jsonl"
    manifest_path = output_dir / "manifest_task_panel.json"
    records_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rewritten),
        encoding="utf-8",
    )
    shutil.copy2(records_path, shard_path)

    subset_kind = _subset_kind(
        target_type=args.new_target_type,
        target_id=args.new_target_id,
        subfamily_id=args.new_subfamily_id,
    )
    manifest = _build_subset_manifest(
        source_manifest=source_manifest,
        source_manifest_path=source_manifest_path,
        output_dir=output_dir,
        records_count=len(rewritten),
        publication_count=len({row["paper"]["id"] for row in rewritten}),
        subset_kind=subset_kind,
        target_type=args.new_target_type,
        target_id=args.new_target_id,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["manifest_path"] = str(manifest_path)
    report["records_path"] = str(records_path)
    report["sample_claim_ids"] = [row["claim"]["id"] for row in rewritten[:10]]
    (output_dir / "reroute_subset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
