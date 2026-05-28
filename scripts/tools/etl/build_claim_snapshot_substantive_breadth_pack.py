#!/usr/bin/env python3
"""Build a substantive non-title breadth pack after claim_snapshot_v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v2", type=Path, required=True)
    parser.add_argument("--warning-conflict-gap-pack", type=Path, required=True)
    parser.add_argument(
        "--accepted-regeneration-jsonl",
        type=Path,
        action="append",
        required=True,
        help="Repeat for each accepted_records.jsonl input to mine breadth candidates.",
    )
    parser.add_argument(
        "--include-claim-id",
        action="append",
        default=[],
        help="Optional explicit allowlist. If provided, only these claim IDs are eligible.",
    )
    parser.add_argument("--min-new-families", type=int, default=0)
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


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
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


def _normalize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_claim_kind(*, text: str, polarity: str) -> str:
    lowered = _normalize_text(text)
    if any(token in lowered for token in ("failed replication", "failed to replicate")):
        return "failed_replication"
    if any(token in lowered for token in ("no effect", "no difference", "null result", "did not differ")):
        return "null_result"
    if any(token in lowered for token in ("replication", "replicate", "reproduced", "reproduce")):
        return "replication"
    if any(token in lowered for token in ("contradiction", "contradicts", "conflict")):
        return "contradiction"
    return "claim"


def _canonical_claim_id(*, target_id: str, target_type: str, claim_text: str, polarity: str) -> str:
    signature = "|".join(
        [
            str(target_id or "").strip(),
            str(target_type or "").strip().lower(),
            _normalize_claim_kind(text=claim_text, polarity=polarity),
            _normalize_text(claim_text),
        ]
    )
    return f"canonical_claim:{hashlib.md5(signature.encode('utf-8')).hexdigest()}"


def _source_pack_label(path: Path) -> str:
    if path.parent.name and path.parent.parent.name:
        return f"{path.parent.parent.name}/{path.parent.name}"
    if path.parent.name:
        return path.parent.name
    return path.stem


def _load_base_identity(
    snapshot_v2_path: Path,
    warning_gap_path: Path,
) -> tuple[dict[str, tuple[Any, ...]], set[str], set[str]]:
    base_by_claim_id: dict[str, tuple[Any, ...]] = {}
    base_families: set[str] = set()
    base_claim_ids: set[str] = set()
    for path in (snapshot_v2_path, warning_gap_path):
        for row in _iter_jsonl(path):
            claim_id = str(row.get("source_claim_id") or "").strip()
            canonical_claim_id = str(row.get("canonical_claim_id") or "").strip()
            identity = (
                claim_id,
                str(row.get("paper_id") or "").strip(),
                str(row.get("target_id") or "").strip(),
                str(row.get("target_type") or "").strip(),
                str(row.get("claim_text") or "").strip(),
                str(row.get("polarity") or "").strip(),
                canonical_claim_id,
            )
            if claim_id:
                base_by_claim_id[claim_id] = identity
                base_claim_ids.add(claim_id)
            if canonical_claim_id:
                base_families.add(canonical_claim_id)
    return base_by_claim_id, base_families, base_claim_ids


def _build_candidate_rows(
    accepted_regeneration_paths: Sequence[Path],
    *,
    include_claim_ids: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for accepted_path in accepted_regeneration_paths:
        source_pack = _source_pack_label(accepted_path)
        for raw_row in _iter_jsonl(accepted_path):
            claim = raw_row.get("claim") or {}
            target = raw_row.get("target") or {}
            paper = raw_row.get("paper") or {}
            mapping = raw_row.get("mapping") or {}
            evidence = raw_row.get("evidence") or {}
            signals = raw_row.get("signals") or {}
            claim_id = str(claim.get("id") or "").strip()
            if include_claim_ids and claim_id not in include_claim_ids:
                continue
            target_id = str(target.get("id") or "").strip()
            target_type = str(target.get("type") or "").strip()
            paper_id = str(paper.get("id") or "").strip()
            claim_text = str(claim.get("text") or "").strip()
            polarity = str(claim.get("polarity") or "").strip()
            if not all((claim_id, target_id, target_type, paper_id, claim_text, polarity)):
                raise SystemExit(
                    f"Fail-closed breadth input mismatch in {accepted_path}: missing required claim fields"
                )
            section = str(evidence.get("section") or "").strip().lower()
            if not bool(evidence.get("locatable")):
                raise SystemExit(
                    f"Fail-closed breadth input mismatch in {accepted_path}: non-locatable evidence for {claim_id}"
                )
            if not section or section == "title" or bool(signals.get("title_only_evidence")):
                raise SystemExit(
                    f"Fail-closed breadth input mismatch in {accepted_path}: title-only evidence for {claim_id}"
                )
            rows.append(
                {
                    "source_claim_id": claim_id,
                    "paper_id": paper_id,
                    "target_id": target_id,
                    "target_type": target_type,
                    "claim_text": claim_text,
                    "claim_kind": _normalize_claim_kind(text=claim_text, polarity=polarity),
                    "polarity": polarity,
                    "canonical_claim_id": _canonical_claim_id(
                        target_id=target_id,
                        target_type=target_type,
                        claim_text=claim_text,
                        polarity=polarity,
                    ),
                    "section": section,
                    "mapping_confidence": float(mapping.get("mapping_confidence") or 0.0),
                    "paper_title": str(paper.get("title") or "").strip(),
                    "method_quote": str(signals.get("method_quote") or "").strip(),
                    "benchmark_eligibility": "benchmark_regenerated_non_title",
                    "source_pack": source_pack,
                    "breadth_seed_bucket": "accepted_regeneration_breadth_seed",
                    "notes": " | ".join(
                        part
                        for part in (
                            str(paper.get("title") or "").strip(),
                            str((raw_row.get("regeneration_source") or {}).get("source_review_bucket") or "").strip(),
                            str((raw_row.get("regeneration_source") or {}).get("source_bucket_reason") or "").strip(),
                        )
                        if part
                    ),
                }
            )
    return rows


def build_outputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    snapshot_v2_path = args.snapshot_v2.expanduser().resolve()
    warning_gap_path = args.warning_conflict_gap_pack.expanduser().resolve()
    accepted_paths = [path.expanduser().resolve() for path in args.accepted_regeneration_jsonl]
    include_claim_ids = {str(claim_id).strip() for claim_id in args.include_claim_id if str(claim_id).strip()}

    base_by_claim_id, base_families, base_claim_ids = _load_base_identity(
        snapshot_v2_path,
        warning_gap_path,
    )
    candidate_rows = _build_candidate_rows(
        accepted_paths,
        include_claim_ids=include_claim_ids,
    )

    seen_claim_ids: set[str] = set()
    pack_rows: list[dict[str, Any]] = []
    reserve_rows: list[dict[str, Any]] = []
    target_type_counts: Counter[str] = Counter()

    for row in candidate_rows:
        claim_id = row["source_claim_id"]
        if claim_id in seen_claim_ids:
            raise SystemExit(
                f"Fail-closed breadth pack mismatch: duplicate candidate source_claim_id {claim_id}"
            )
        seen_claim_ids.add(claim_id)

        identity = (
            claim_id,
            row["paper_id"],
            row["target_id"],
            row["target_type"],
            row["claim_text"],
            row["polarity"],
            row["canonical_claim_id"],
        )
        if claim_id in base_claim_ids:
            if base_by_claim_id[claim_id] != identity:
                raise SystemExit(
                    f"Fail-closed breadth drift: candidate {claim_id} conflicts with existing reviewed identity"
                )
            reserve_rows.append(
                {
                    **row,
                    "reserve_reason": "already_present_by_claim_id",
                    "family_is_new_post_gap": False,
                }
            )
            continue

        family_is_new = row["canonical_claim_id"] not in base_families
        tagged = {
            **row,
            "family_is_new_post_gap": family_is_new,
            "selected_via_allowlist": bool(include_claim_ids),
        }
        if family_is_new:
            pack_rows.append(tagged)
            target_type_counts[row["target_type"]] += 1
        else:
            reserve_rows.append({**tagged, "reserve_reason": "canonical_family_already_present"})

    if args.min_new_families and len({row["canonical_claim_id"] for row in pack_rows}) < args.min_new_families:
        raise SystemExit(
            "Fail-closed breadth pack mismatch: "
            f"only {len({row['canonical_claim_id'] for row in pack_rows})} net-new families, "
            f"below requested minimum {args.min_new_families}"
        )

    pack_rows.sort(key=lambda row: (row["target_type"], row["target_id"], row["source_claim_id"]))
    reserve_rows.sort(key=lambda row: (row["target_type"], row["target_id"], row["source_claim_id"]))

    pack_family_count = len({row["canonical_claim_id"] for row in pack_rows})
    projected_post_gap = len(base_families | {row["canonical_claim_id"] for row in pack_rows})
    remaining_shortfall = max(0, 24 - projected_post_gap)

    summary = {
        "generated_at": _utc_now_iso(),
        "inputs": {
            "snapshot_v2": str(snapshot_v2_path),
            "warning_conflict_gap_pack": str(warning_gap_path),
            "accepted_regeneration_jsonl": [str(path) for path in accepted_paths],
            "include_claim_ids": sorted(include_claim_ids),
            "min_new_families": args.min_new_families,
        },
        "counts": {
            "base_families_total": len(base_families),
            "bridge_families_total": len(
                {str(row.get('canonical_claim_id') or '') for row in _iter_jsonl(warning_gap_path)}
            ),
            "candidate_rows_total": len(pack_rows),
            "candidate_new_families_total": pack_family_count,
            "reserve_rows_total": len(reserve_rows),
            "projected_post_gap_families_total": projected_post_gap,
            "remaining_shortfall_after_pack": remaining_shortfall,
            **{
                f"candidate_target_type_{target_type}": target_type_counts[target_type]
                for target_type in sorted(target_type_counts)
            },
        },
    }
    return pack_rows, reserve_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pack_rows, reserve_rows, summary = build_outputs(args)
    pack_jsonl = output_dir / "claim_snapshot_substantive_breadth_pack.jsonl"
    pack_tsv = output_dir / "claim_snapshot_substantive_breadth_pack.tsv"
    reserve_jsonl = output_dir / "claim_snapshot_substantive_breadth_pack_reserve.jsonl"
    summary_json = output_dir / "claim_snapshot_substantive_breadth_pack_summary.json"

    _write_jsonl(pack_jsonl, pack_rows)
    _write_tsv(
        pack_tsv,
        pack_rows,
        [
            "source_claim_id",
            "target_type",
            "target_id",
            "canonical_claim_id",
            "section",
            "mapping_confidence",
            "breadth_seed_bucket",
            "notes",
        ],
    )
    _write_jsonl(reserve_jsonl, reserve_rows)
    summary["artifacts"] = {
        "claim_snapshot_substantive_breadth_pack_jsonl": str(pack_jsonl),
        "claim_snapshot_substantive_breadth_pack_tsv": str(pack_tsv),
        "claim_snapshot_substantive_breadth_pack_reserve_jsonl": str(reserve_jsonl),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
