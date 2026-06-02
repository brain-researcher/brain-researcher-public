#!/usr/bin/env python3
"""Build a deduped Gabriel-only accepted-record ingest manifest.

Historical Gabriel checkpoints store per-file accepted counts, not accepted line
numbers. This script replays the recorded quality profile for each completed
checkpoint shard, keeps records accepted by the current Gabriel gate, dedupes
them, and emits a fresh ingest-compatible manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)

DEFAULT_EXCLUDE_TOKENS = (
    "kggen",
    "task_panel",
    "task-panel",
    "prod-curated",
    "prod-deduped",
)

PROFILE_RANK = {
    "high_precision": 5,
    "balanced": 4,
    "balanced_marginal": 3,
    "kg_bootstrap": 2,
    "kg_task_panel": 1,
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")


def _sha1_text(value: Any) -> str:
    return hashlib.sha1(str(value or "").strip().lower().encode("utf-8")).hexdigest()


def _path_has_excluded_token(path: Path, tokens: tuple[str, ...]) -> str | None:
    lowered = str(path).lower()
    for token in tokens:
        if token and token.lower() in lowered:
            return token
    return None


def _resolve_input_path(raw_path: Any, repo_root: Path) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None

    candidates: list[Path] = []
    path = Path(raw).expanduser()
    candidates.append(path)
    if not path.is_absolute():
        candidates.append(repo_root / path)

    marker = "data/br-kg/raw/gabriel/"
    if marker in raw:
        candidates.append(repo_root / marker / raw.split(marker, 1)[1])

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _loader_for_profile(profile: str) -> GabrielMeasurementLoader:
    return GabrielMeasurementLoader(None, config={"quality_profile": profile})


def _accepted_by_profile(
    record: dict[str, Any],
    loader: GabrielMeasurementLoader,
) -> tuple[bool, Any, list[str]]:
    variables = compute_gabriel_variables(
        record,
        required_provenance_fields=loader.required_provenance_fields,
    )
    _accepted, reasons = evaluate_high_precision_gate(variables, loader.gate_thresholds)
    reasons = loader._apply_review_only_overrides(
        record,
        variables,
        reasons,
        quality_profile=loader.quality_profile,
    )
    return len(reasons) == 0, variables, list(reasons)


def _record_ids(
    record: dict[str, Any],
    loader: GabrielMeasurementLoader,
) -> dict[str, str]:
    paper = loader._extract_paper(record)
    target = loader._extract_target(record)
    claim = loader._extract_claim(record, paper["paper_id"], target["target_id"])
    evidence = loader._extract_evidence(record, paper["paper_id"], claim["claim_id"])
    run = dict(record.get("run") or {})
    run_id = str(
        run.get("run_id") or record.get("run_id") or loader._hash_record(record)
    )
    return {
        "paper_id": str(paper.get("paper_id") or ""),
        "pmid": str(paper.get("pmid") or ""),
        "doi": str(paper.get("doi") or ""),
        "pmcid": str(paper.get("pmcid") or ""),
        "target_id": str(target.get("target_id") or ""),
        "target_type": str(target.get("target_type") or ""),
        "target_label": str(target.get("target_label") or ""),
        "claim_id": str(claim.get("claim_id") or ""),
        "claim_text": str(claim.get("text") or ""),
        "claim_kind": str(claim.get("claim_kind") or ""),
        "evidence_id": str(evidence.get("span_id") or ""),
        "evidence_quote": str(evidence.get("quote") or ""),
        "run_id": run_id,
    }


def _dedupe_key(ids: dict[str, str]) -> str:
    paper_key = ids["doi"] or ids["pmid"] or ids["pmcid"] or ids["paper_id"]
    evidence_hash = _sha1_text(ids["evidence_quote"])
    return "|".join(
        [
            ids["claim_id"],
            paper_key,
            ids["target_type"],
            ids["target_id"],
            evidence_hash,
        ]
    )


def _selection_score(
    profile: str, variables: Any, record: dict[str, Any]
) -> tuple[Any, ...]:
    model = str(
        (record.get("run") or {}).get("model") or record.get("model") or ""
    ).lower()
    model_rank = 0 if "heuristic" in model else 1
    return (
        PROFILE_RANK.get(profile, 0),
        model_rank,
        float(variables.provenance_completeness),
        float(variables.method_rigor),
        float(variables.evidence_quality_score),
        float(variables.claim_strength),
        float(variables.mapping_confidence),
        float(variables.mention_strength),
    )


def _iter_checkpoint_file_entries(
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    repo_root: Path,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    profile = str(checkpoint.get("quality_profile") or "high_precision").strip()
    mode = str(checkpoint.get("mode") or "spine").strip()
    for file_key, file_state in sorted((checkpoint.get("files") or {}).items()):
        if not isinstance(file_state, dict):
            continue
        stats = file_state.get("stats") or {}
        if str(file_state.get("status") or "").lower() != "completed":
            continue
        accepted_count = int(stats.get("records_accepted") or 0)
        if accepted_count <= 0:
            continue
        input_path = _resolve_input_path(
            file_state.get("input_path") or file_key, repo_root
        )
        entries.append(
            {
                "checkpoint_path": checkpoint_path,
                "quality_profile": profile,
                "mode": mode,
                "input_path": input_path,
                "raw_input_path": str(file_state.get("input_path") or file_key),
                "checkpoint_accepted": accepted_count,
            }
        )
    return entries


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    source_root = args.source_root.resolve()
    output_dir = args.output_dir.resolve()
    exclude_tokens = tuple(args.exclude_token or ())

    loaders: dict[str, GabrielMeasurementLoader] = {}
    selected: dict[str, dict[str, Any]] = {}
    checkpoint_summaries: list[dict[str, Any]] = []
    excluded_checkpoints: list[dict[str, str]] = []
    missing_inputs: list[dict[str, str]] = []
    mismatches: list[dict[str, Any]] = []
    parse_errors = 0
    raw_replay_total = 0
    replay_total = 0
    checkpoint_accepted_total = 0

    checkpoint_paths = sorted(source_root.glob(args.checkpoint_glob))
    for checkpoint_path in checkpoint_paths:
        excluded_token = _path_has_excluded_token(checkpoint_path, exclude_tokens)
        if excluded_token:
            excluded_checkpoints.append(
                {
                    "path": str(checkpoint_path),
                    "reason": f"excluded_token:{excluded_token}",
                }
            )
            continue
        try:
            checkpoint = _read_json(checkpoint_path)
        except Exception as exc:
            excluded_checkpoints.append(
                {"path": str(checkpoint_path), "reason": f"unreadable:{exc}"}
            )
            continue
        if str(checkpoint.get("source") or "").strip().lower() != "gabriel":
            excluded_checkpoints.append(
                {"path": str(checkpoint_path), "reason": "source_not_gabriel"}
            )
            continue

        entries = _iter_checkpoint_file_entries(checkpoint_path, checkpoint, repo_root)
        checkpoint_expected = sum(entry["checkpoint_accepted"] for entry in entries)
        checkpoint_replayed = 0
        for entry in entries:
            input_path = entry["input_path"]
            if input_path is None:
                missing_inputs.append(
                    {
                        "checkpoint_path": str(checkpoint_path),
                        "input_path": entry["raw_input_path"],
                    }
                )
                continue
            profile = str(entry["quality_profile"])
            loader = loaders.setdefault(profile, _loader_for_profile(profile))
            file_candidates: list[dict[str, Any]] = []
            with input_path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        parse_errors += 1
                        continue
                    if not isinstance(record, dict):
                        parse_errors += 1
                        continue
                    accepted, variables, _reasons = _accepted_by_profile(record, loader)
                    if not accepted:
                        continue
                    ids = _record_ids(record, loader)
                    key = _dedupe_key(ids)
                    score = _selection_score(profile, variables, record)
                    candidate = {
                        "dedupe_key": key,
                        "score": score,
                        "record": record,
                        "ids": ids,
                        "variables": {
                            "mention_strength": variables.mention_strength,
                            "mapping_confidence": variables.mapping_confidence,
                            "claim_polarity": variables.claim_polarity,
                            "claim_strength": variables.claim_strength,
                            "evidence_quality": variables.evidence_quality,
                            "evidence_quality_score": variables.evidence_quality_score,
                            "method_rigor": variables.method_rigor,
                            "provenance_completeness": variables.provenance_completeness,
                        },
                        "source": {
                            "checkpoint_path": str(checkpoint_path),
                            "input_path": str(input_path),
                            "line_number": line_number,
                            "quality_profile": profile,
                            "mode": entry["mode"],
                        },
                    }
                    file_candidates.append(candidate)
            raw_file_replayed = len(file_candidates)
            raw_replay_total += raw_file_replayed
            if (
                args.cap_to_checkpoint_count
                and raw_file_replayed > entry["checkpoint_accepted"]
            ):
                file_candidates = file_candidates[: entry["checkpoint_accepted"]]
            file_replayed = len(file_candidates)
            replay_total += file_replayed
            for candidate in file_candidates:
                existing = selected.get(candidate["dedupe_key"])
                if existing is None or tuple(candidate["score"]) > tuple(
                    existing["score"]
                ):
                    selected[candidate["dedupe_key"]] = candidate
            if raw_file_replayed != entry["checkpoint_accepted"]:
                mismatches.append(
                    {
                        "checkpoint_path": str(checkpoint_path),
                        "input_path": str(input_path),
                        "checkpoint_accepted": entry["checkpoint_accepted"],
                        "raw_replayed_accepted": raw_file_replayed,
                        "selected_after_cap": file_replayed,
                    }
                )
            checkpoint_replayed += file_replayed
        checkpoint_accepted_total += checkpoint_expected
        checkpoint_summaries.append(
            {
                "path": str(checkpoint_path),
                "quality_profile": str(checkpoint.get("quality_profile") or ""),
                "mode": str(checkpoint.get("mode") or ""),
                "files_with_accepted": len(entries),
                "checkpoint_accepted": checkpoint_expected,
                "replayed_accepted": checkpoint_replayed,
            }
        )

    selected_records = sorted(
        selected.values(),
        key=lambda item: (
            item["ids"]["target_type"],
            item["ids"]["target_id"],
            item["ids"]["paper_id"],
            item["ids"]["claim_id"],
            item["ids"]["evidence_id"],
        ),
    )

    profile_counts = Counter(
        item["source"]["quality_profile"] for item in selected_records
    )
    polarity_counts = Counter(
        item["variables"]["claim_polarity"] for item in selected_records
    )
    target_type_counts = Counter(
        item["ids"]["target_type"] for item in selected_records
    )
    model_counts = Counter(
        str(
            (item["record"].get("run") or {}).get("model")
            or item["record"].get("model")
            or "unknown"
        )
        for item in selected_records
    )
    target_counts = Counter(item["ids"]["target_id"] for item in selected_records)

    now = datetime.now(timezone.utc).isoformat()
    run_id = output_dir.name
    shard_dir = output_dir / "shards"
    manifest_path = output_dir / "manifest.json"
    inventory_path = output_dir / "dry_inventory.json"
    selected_index_path = output_dir / "selected_records_index.jsonl"

    summary = {
        "run_id": run_id,
        "created_at": now,
        "source_root": str(source_root),
        "checkpoint_glob": args.checkpoint_glob,
        "exclude_tokens": list(exclude_tokens),
        "checkpoints_discovered": len(checkpoint_paths),
        "checkpoints_included": len(checkpoint_summaries),
        "checkpoints_excluded": len(excluded_checkpoints),
        "files_missing": len(missing_inputs),
        "parse_errors": parse_errors,
        "checkpoint_accepted_total": checkpoint_accepted_total,
        "raw_replayed_accepted_total": raw_replay_total,
        "replayed_accepted_total": replay_total,
        "deduped_records": len(selected_records),
        "duplicates_dropped": max(0, replay_total - len(selected_records)),
        "mismatch_count": len(mismatches),
        "profile_counts": dict(sorted(profile_counts.items())),
        "polarity_counts": dict(sorted(polarity_counts.items())),
        "target_type_counts": dict(sorted(target_type_counts.items())),
        "model_counts": dict(sorted(model_counts.items())),
        "top_targets": target_counts.most_common(25),
        "checkpoint_summaries": checkpoint_summaries,
        "excluded_checkpoints": excluded_checkpoints,
        "missing_inputs": missing_inputs,
        "mismatches": mismatches,
        "artifacts": {
            "output_dir": str(output_dir),
            "manifest_path": str(manifest_path),
            "inventory_path": str(inventory_path),
            "selected_records_index_path": str(selected_index_path),
        },
    }

    if args.write:
        if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
            raise FileExistsError(
                f"Output directory is not empty: {output_dir}. Pass --overwrite."
            )
        shard_dir.mkdir(parents=True, exist_ok=True)
        for old in shard_dir.glob("shard_*.jsonl"):
            old.unlink()

        shard_payloads: list[list[dict[str, Any]]] = []
        current_shard: list[dict[str, Any]] = []
        for item in selected_records:
            record = dict(item["record"])
            record["_promotion"] = {
                "promotion_batch": run_id,
                "promotion_status": args.promotion_status,
                "release_status": args.release_status,
                "source": "gabriel",
                "dedupe_key": item["dedupe_key"],
                "historical_source": item["source"],
            }
            current_shard.append(record)
            if len(current_shard) >= args.shard_size:
                shard_payloads.append(current_shard)
                current_shard = []
        if current_shard:
            shard_payloads.append(current_shard)

        shards: list[dict[str, Any]] = []
        for shard_id, records in enumerate(shard_payloads):
            shard_path = shard_dir / f"shard_{shard_id:04d}.jsonl"
            with shard_path.open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(
                        json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
                    )
            shards.append(
                {
                    "shard_id": shard_id,
                    "path": str(shard_path),
                    "publications": len(
                        {
                            _record_ids(record, _loader_for_profile("kg_bootstrap"))[
                                "paper_id"
                            ]
                            for record in records
                        }
                    ),
                    "records": len(records),
                    "records_llm": sum(
                        1
                        for record in records
                        if "heuristic"
                        not in str(
                            (record.get("run") or {}).get("model")
                            or record.get("model")
                            or ""
                        ).lower()
                    ),
                    "records_heuristic": sum(
                        1
                        for record in records
                        if "heuristic"
                        in str(
                            (record.get("run") or {}).get("model")
                            or record.get("model")
                            or ""
                        ).lower()
                    ),
                    "errors": 0,
                }
            )

        manifest = {
            "run_id": run_id,
            "created_at": now,
            "generator_version": "gabriel-deduped-accepted-manifest/v1",
            "prompt_template_version": "historical-gabriel-replay",
            "source": "historical_gabriel_checkpoints",
            "source_details": {
                "source_root": str(source_root),
                "checkpoint_glob": args.checkpoint_glob,
                "exclude_tokens": list(exclude_tokens),
                "checkpoint_accepted_total": checkpoint_accepted_total,
                "raw_replayed_accepted_total": raw_replay_total,
                "replayed_accepted_total": replay_total,
                "deduped_records": len(selected_records),
            },
            "promotion": {
                "source": "gabriel",
                "promotion_status": args.promotion_status,
                "release_status": args.release_status,
                "kggen_excluded": True,
            },
            "query": {
                "source": "historical_checkpoints",
                "shard_size": args.shard_size,
            },
            "options": {
                "dedupe_key": "claim_id|paper_id_or_doi_or_pmid|target_type|target_id|evidence_quote_sha1",
                "accepted_replay": "current_gabriel_gate_with_checkpoint_quality_profile",
                "target_materialization": "deferred_by_default",
                "batch_ingest_write_targets_default": False,
            },
            "paths": {
                "run_dir": str(output_dir),
                "shard_dir": str(shard_dir),
                "manifest_path": str(manifest_path),
                "inventory_path": str(inventory_path),
                "selected_records_index_path": str(selected_index_path),
            },
            "counts": {
                "publications_selected": len(
                    {item["ids"]["paper_id"] for item in selected_records}
                ),
                "shards": len(shards),
                "records_generated": len(selected_records),
                "records_llm": sum(
                    count
                    for model, count in model_counts.items()
                    if "heuristic" not in model.lower()
                ),
                "records_heuristic": sum(
                    count
                    for model, count in model_counts.items()
                    if "heuristic" in model.lower()
                ),
                "historical_checkpoint_accepted": checkpoint_accepted_total,
                "historical_raw_replayed_accepted": raw_replay_total,
                "historical_replayed_accepted": replay_total,
                "duplicates_dropped": max(0, replay_total - len(selected_records)),
            },
            "shards": shards,
        }
        _write_json(manifest_path, manifest)
        _write_json(inventory_path, summary)
        with selected_index_path.open("w", encoding="utf-8") as handle:
            for item in selected_records:
                handle.write(
                    json.dumps(
                        {
                            "dedupe_key": item["dedupe_key"],
                            "ids": item["ids"],
                            "variables": item["variables"],
                            "source": item["source"],
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                    + "\n"
                )

    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/br-kg/raw/gabriel"),
    )
    parser.add_argument(
        "--checkpoint-glob",
        default="**/ingest_checkpoint*.json",
        help="Glob below --source-root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for manifest.json, shards, and dry_inventory.json.",
    )
    parser.add_argument(
        "--exclude-token", action="append", default=list(DEFAULT_EXCLUDE_TOKENS)
    )
    parser.add_argument("--shard-size", type=int, default=1000)
    parser.add_argument("--promotion-status", default="candidate_bootstrap")
    parser.add_argument("--release-status", default="not_release_grade")
    parser.add_argument(
        "--cap-to-checkpoint-count",
        dest="cap_to_checkpoint_count",
        action="store_true",
        default=True,
        help="When current gate replay exceeds a shard's historical accepted count, keep only the first historical-count accepted records.",
    )
    parser.add_argument(
        "--no-cap-to-checkpoint-count",
        dest="cap_to_checkpoint_count",
        action="store_false",
    )
    parser.add_argument("--write", action="store_true", help="Write output artifacts.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    summary = build_manifest(args)
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    if summary["mismatch_count"]:
        print(
            f"WARNING: {summary['mismatch_count']} checkpoint file(s) did not replay "
            "to the recorded accepted count.",
            file=sys.stderr,
        )
    if summary["files_missing"]:
        print(
            f"WARNING: {summary['files_missing']} checkpoint input file(s) were missing.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
