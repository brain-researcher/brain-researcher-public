#!/usr/bin/env python3
"""Resolve missing-claim rows into expected-absent vs replay-candidate buckets."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_ABSENT_OLD_TASK_IDS = {
    "task:onvoc:onvoc_0000463",
    "task:onvoc:onvoc_0000438",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--dropped-records", type=Path, required=True)
    parser.add_argument("--missing-claim-rows", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "resolution",
        "resolution_reason",
        "paper_id",
        "claim_id",
        "run_id",
        "old_task_id",
        "old_task_label",
        "mapping_original",
        "paper_title",
    ]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write(
                "\t".join(
                    str(row.get(column, "")).replace("\t", " ").replace("\n", " ")
                    for column in columns
                )
                + "\n"
            )


def _build_lookup(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _iter_jsonl(path):
        claim_id = str((row.get("claim") or {}).get("id") or "").strip()
        paper_id = str((row.get("paper") or {}).get("id") or "").strip()
        run_id = str((row.get("run") or {}).get("run_id") or "").strip()
        if not claim_id or not paper_id or not run_id:
            continue
        lookup[(claim_id, paper_id, run_id)] = row
    return lookup


def _classify(record: dict[str, Any]) -> tuple[str, str, str]:
    target = dict(record.get("target") or {})
    old_task_id = str(target.get("id") or "").strip()
    if old_task_id in EXPECTED_ABSENT_OLD_TASK_IDS:
        return (
            "expected_absent_no_replay",
            "generic_construct_removed_by_v8",
            "The row was intentionally removed by the v8 router and its absence is expected.",
        )
    if old_task_id.startswith(("task:subfamily:", "task:family:")):
        return (
            "replay_candidate",
            "task_like_missing_state",
            "Task-like subfamily/family row missing from live graph; stage a bounded replay subset for review.",
        )
    return (
        "manual_review",
        "unexpected_missing_state",
        "Missing-claim row does not fit the expected-generic or task-like replay buckets.",
    )


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
    run_id = f"{source_run_id}-missing-claim-replay-{_run_stamp()}"
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
        "query": source_manifest.get("query") or "task-panel-missing-claim-replay",
        "prompt_template_version": source_manifest.get("prompt_template_version")
        or "n/a",
        "generator_version": "task-panel-missing-claim-replay/v1",
        "options": options,
        "source_details": {
            **source_details,
            "source_manifest_path": str(source_manifest_path.resolve()),
            "subset_kind": "missing_claim_replay_candidates",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source_manifest_path = args.source_manifest.expanduser().resolve()
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    dropped_lookup = _build_lookup(args.dropped_records.expanduser().resolve())
    missing_claim_input_rows = list(
        _iter_jsonl(args.missing_claim_rows.expanduser().resolve())
    )
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    replay_payloads: list[dict[str, Any]] = []
    for row in missing_claim_input_rows:
        claim_id = str(row.get("claim_id") or "").strip()
        paper_id = str(row.get("paper_id") or "").strip()
        run_id = str(row.get("run_id") or "").strip()
        record = dropped_lookup.get((claim_id, paper_id, run_id))
        if record is None:
            unresolved_rows.append(
                {
                    "claim_id": claim_id,
                    "paper_id": paper_id,
                    "run_id": run_id,
                    "old_task_id": str(row.get("old_task_id") or "").strip(),
                    "old_task_label": "",
                    "mapping_original": "",
                    "paper_title": "",
                    "resolution": "unresolved_missing_claim_row",
                    "resolution_reason": "missing_dropped_record_join",
                    "resolution_note": (
                        "Missing-claim row did not join back to dropped_records; "
                        "manual inspection is required before replay or closure."
                    ),
                }
            )
            continue
        target = dict(record.get("target") or {})
        paper = dict(record.get("paper") or {})
        mapping = dict(record.get("mapping") or {})
        resolution, resolution_reason, resolution_note = _classify(record)
        enriched = {
            "claim_id": claim_id,
            "paper_id": paper_id,
            "run_id": run_id,
            "old_task_id": str(target.get("id") or "").strip(),
            "old_task_label": str(target.get("label") or "").strip(),
            "mapping_original": str(mapping.get("original_canonical_id") or "").strip(),
            "paper_title": str(paper.get("title") or "").strip(),
            "resolution": resolution,
            "resolution_reason": resolution_reason,
            "resolution_note": resolution_note,
            "record": record,
        }
        resolved_rows.append(enriched)
        if resolution == "replay_candidate":
            replay_payloads.append(record)

    all_rows = [*resolved_rows, *unresolved_rows]
    decision_counts = Counter(row["resolution"] for row in all_rows)
    old_task_counts = Counter((row["old_task_id"], row["old_task_label"]) for row in all_rows)

    _write_jsonl(output_dir / "missing_claim_resolution_pack.jsonl", all_rows)
    _write_tsv(output_dir / "missing_claim_resolution_pack.tsv", all_rows)
    for decision in (
        "expected_absent_no_replay",
        "replay_candidate",
        "manual_review",
        "unresolved_missing_claim_row",
    ):
        decision_rows = [row for row in all_rows if row["resolution"] == decision]
        _write_jsonl(output_dir / f"{decision}.jsonl", decision_rows)
        _write_tsv(output_dir / f"{decision}.tsv", decision_rows)

    replay_dir = output_dir / "replay_subset"
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "raw").mkdir(parents=True, exist_ok=True)
    (replay_dir / "shards").mkdir(parents=True, exist_ok=True)
    subset_records_path = replay_dir / "task_panel_records.jsonl"
    subset_shard_path = replay_dir / "shards" / "shard_0000.jsonl"
    _write_jsonl(subset_records_path, replay_payloads)
    shutil.copy2(subset_records_path, subset_shard_path)
    replay_manifest = _build_subset_manifest(
        source_manifest=source_manifest,
        source_manifest_path=source_manifest_path,
        output_dir=replay_dir,
        records_count=len(replay_payloads),
        publication_count=len({row["paper"]["id"] for row in replay_payloads}),
    )
    (replay_dir / "manifest_task_panel.json").write_text(
        json.dumps(replay_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "source_manifest_path": str(source_manifest_path),
        "dropped_records_path": str(args.dropped_records.expanduser().resolve()),
        "missing_claim_rows_path": str(args.missing_claim_rows.expanduser().resolve()),
        "counts": {
            "missing_claim_rows": len(missing_claim_input_rows),
            "resolved_missing_claim_rows": len(resolved_rows),
            "unresolved_missing_claim_rows": len(unresolved_rows),
            "expected_absent_no_replay": decision_counts["expected_absent_no_replay"],
            "replay_candidate": decision_counts["replay_candidate"],
            "manual_review": decision_counts["manual_review"],
            "replay_candidate_publications": len(
                {row["paper"]["id"] for row in replay_payloads}
            ),
        },
        "counts_by_old_task": [
            [old_task_id, old_task_label, count]
            for (old_task_id, old_task_label), count in old_task_counts.most_common()
        ],
        "artifacts": {
            "resolution_pack_jsonl": str(output_dir / "missing_claim_resolution_pack.jsonl"),
            "unresolved_missing_claim_row_jsonl": str(
                output_dir / "unresolved_missing_claim_row.jsonl"
            ),
            "replay_subset_manifest": str(replay_dir / "manifest_task_panel.json"),
            "replay_subset_records": str(subset_records_path),
        },
    }
    (output_dir / "missing_claim_resolution_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
