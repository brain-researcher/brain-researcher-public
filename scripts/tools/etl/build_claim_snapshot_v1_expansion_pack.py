#!/usr/bin/env python3
"""Build the next claim_snapshot_v1 expansion pack from fresh claim seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CORE_FIELDS = (
    "source_claim_id",
    "paper_id",
    "target_id",
    "target_type",
    "claim_text",
    "claim_kind",
    "polarity",
    "quality_profile",
    "benchmark_eligibility",
    "candidate_lane_present",
    "canonical_claim_id",
    "cluster_confidence",
    "failure_tags",
)
IDENTITY_FIELDS = (
    "source_claim_id",
    "paper_id",
    "target_id",
    "target_type",
    "claim_text",
    "claim_kind",
    "polarity",
    "canonical_claim_id",
)
SNAPSHOT_WARNING_ROLES = {"singleton_warning", "conflict_cluster_warning"}
ACCEPTED_MANIFEST_REVIEW_STATUSES = {"accepted_high_precision", "accepted_bootstrap"}
MIN_CANONICAL_FAMILIES = 24
MIN_WARNING_OR_CONFLICT_FAMILIES = 6
MIN_TARGET_TYPE_BUCKETS = 3


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-v1", type=Path, required=True)
    parser.add_argument("--prior-adjudication-pack", type=Path, required=True)
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--heldout-manifest", type=Path, required=True)
    parser.add_argument(
        "--accepted-regeneration-jsonl",
        type=Path,
        action="append",
        required=True,
        help="Repeat for each accepted_records.jsonl input to mine fresh non-title seeds.",
    )
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


def _stable_hash(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


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
    return f"canonical_claim:{_stable_hash(signature)}"


def _source_pack_label(path: Path) -> str:
    if path.parent.name and path.parent.parent.name:
        return f"{path.parent.parent.name}/{path.parent.name}"
    if path.parent.name:
        return path.parent.name
    return path.stem


def _require_core_fields(row: dict[str, Any], *, source_path: Path) -> None:
    missing = [field for field in CORE_FIELDS if field not in row]
    if missing:
        raise SystemExit(
            f"Fail-closed expansion input mismatch in {source_path}: missing core fields {missing}"
        )


def _identity_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in CORE_FIELDS[:-1]) + (tuple(row.get("failure_tags") or []),)


def _reviewed_identity_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in IDENTITY_FIELDS)


def _load_snapshot_rows(snapshot_path: Path) -> tuple[dict[str, dict[str, Any]], set[str], set[str], set[str]]:
    snapshot_rows: dict[str, dict[str, Any]] = {}
    family_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _iter_jsonl(snapshot_path):
        _require_core_fields(row, source_path=snapshot_path)
        claim_id = str(row["source_claim_id"]).strip()
        if claim_id in snapshot_rows:
            raise SystemExit(
                f"Fail-closed snapshot mismatch: duplicate source_claim_id {claim_id} in {snapshot_path}"
            )
        snapshot_rows[claim_id] = row
        family_to_rows[str(row["canonical_claim_id"])].append(row)

    snapshot_warning_families: set[str] = set()
    snapshot_target_types: set[str] = set()
    for family_id, members in family_to_rows.items():
        snapshot_target_types.update(str(member["target_type"]) for member in members if member.get("target_type"))
        polarities = {str(member.get("polarity") or "").strip() for member in members if member.get("polarity")}
        if len(polarities) > 1:
            snapshot_warning_families.add(family_id)
            continue
        if any(str(member.get("snapshot_role") or "") in SNAPSHOT_WARNING_ROLES for member in members):
            snapshot_warning_families.add(family_id)
    return snapshot_rows, set(family_to_rows), snapshot_warning_families, snapshot_target_types


def _load_prior_adjudication(adjudication_path: Path) -> dict[str, dict[str, Any]]:
    prior: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(adjudication_path):
        _require_core_fields(row, source_path=adjudication_path)
        claim_id = str(row["source_claim_id"]).strip()
        if claim_id in prior:
            raise SystemExit(
                f"Fail-closed adjudication mismatch: duplicate source_claim_id {claim_id} in {adjudication_path}"
            )
        prior[claim_id] = row
    return prior


def _validate_snapshot_against_prior(
    *,
    snapshot_rows: dict[str, dict[str, Any]],
    prior_adjudication: dict[str, dict[str, Any]],
) -> None:
    for claim_id, snapshot_row in snapshot_rows.items():
        prior_row = prior_adjudication.get(claim_id)
        if prior_row is None:
            raise SystemExit(
                f"Fail-closed snapshot drift: {claim_id} exists in snapshot-v1 but not in prior adjudication pack"
            )
        if not bool(prior_row.get("snapshot_v1_included")):
            raise SystemExit(
                f"Fail-closed snapshot drift: {claim_id} is included in snapshot-v1 but marked excluded in prior adjudication pack"
            )
        if _reviewed_identity_tuple(snapshot_row) != _reviewed_identity_tuple(prior_row):
            raise SystemExit(
                f"Fail-closed snapshot drift: core fields changed for reviewed claim {claim_id}"
            )


def _build_manifest_seed_rows(manifest_path: Path, *, source_pack: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for top_row in _iter_jsonl(manifest_path):
        claim_text = str(top_row.get("text") or "").strip()
        top_notes = str(top_row.get("notes") or "").strip()
        top_review_status = str(top_row.get("review_status") or "").strip()
        hypothesis_id = str(top_row.get("hypothesis_id") or "").strip()
        source_records = top_row.get("source_records") or []
        if not isinstance(source_records, list):
            continue
        for record in source_records:
            if not isinstance(record, dict):
                continue
            review_status = str(record.get("review_status") or "").strip()
            if review_status not in ACCEPTED_MANIFEST_REVIEW_STATUSES:
                continue
            claim_id = str(record.get("claim_id") or "").strip()
            target_id = str(record.get("target_id") or "").strip()
            target_type = str(record.get("target_type") or "").strip()
            paper_id = str(record.get("paper_id") or "").strip()
            polarity = str(record.get("polarity") or "").strip()
            if not all((claim_id, target_id, target_type, paper_id, claim_text, polarity)):
                raise SystemExit(
                    f"Fail-closed manifest seed mismatch in {manifest_path}: missing required record fields"
                )
            quality_profile = str(record.get("gate_profile") or "").strip() or (
                "high_precision" if review_status == "accepted_high_precision" else "kg_bootstrap"
            )
            warnings = (
                ["bootstrap_only_pre_gate_b"]
                if review_status == "accepted_bootstrap"
                else []
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
                    "quality_profile": quality_profile,
                    "benchmark_eligibility": (
                        "benchmark_eligible_high_precision"
                        if review_status == "accepted_high_precision"
                        else "bootstrap_only_pre_gate_b"
                    ),
                    "candidate_lane_present": False,
                    "canonical_claim_id": _canonical_claim_id(
                        target_id=target_id,
                        target_type=target_type,
                        claim_text=claim_text,
                        polarity=polarity,
                    ),
                    "cluster_confidence": (
                        0.95 if review_status == "accepted_high_precision" else 0.75
                    ),
                    "failure_tags": [],
                    "evaluation_slice": "benchmark_seed_expansion",
                    "proposed_action": "review_for_snapshot",
                    "review_status": review_status or top_review_status,
                    "adjudication_status": "not_adjudicated",
                    "notes": top_notes,
                    "source_packs": [source_pack],
                    "source_paths": [f"{manifest_path}#{hypothesis_id}" if hypothesis_id else str(manifest_path)],
                    "evidence_depths": [],
                    "warnings": warnings,
                    "expansion_seed_bucket": (
                        "accepted_high_precision_seed"
                        if review_status == "accepted_high_precision"
                        else "accepted_bootstrap_seed"
                    ),
                }
            )
    return rows


def _build_regeneration_seed_rows(regeneration_path: Path, *, source_pack: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_row in _iter_jsonl(regeneration_path):
        claim = raw_row.get("claim") or {}
        target = raw_row.get("target") or {}
        paper = raw_row.get("paper") or {}
        mapping = raw_row.get("mapping") or {}
        evidence = raw_row.get("evidence") or {}
        signals = raw_row.get("signals") or {}
        regeneration_source = raw_row.get("regeneration_source") or {}
        claim_id = str(claim.get("id") or "").strip()
        target_id = str(target.get("id") or "").strip()
        target_type = str(target.get("type") or "").strip()
        paper_id = str(paper.get("id") or "").strip()
        claim_text = str(claim.get("text") or "").strip()
        polarity = str(claim.get("polarity") or "").strip()
        section = str(evidence.get("section") or "").strip().lower()
        if not all((claim_id, target_id, target_type, paper_id, claim_text, polarity, section)):
            raise SystemExit(
                f"Fail-closed regeneration seed mismatch in {regeneration_path}: missing required claim/evidence fields"
            )
        if bool(signals.get("title_only_evidence")):
            continue
        if section == "title":
            continue
        if not bool(evidence.get("locatable")):
            continue
        mapping_confidence = float(mapping.get("mapping_confidence") or 0.0)
        warnings: list[str] = []
        if not bool(signals.get("section_level_evidence")):
            warnings.append("section_level_evidence_missing")
        rows.append(
            {
                "source_claim_id": claim_id,
                "paper_id": paper_id,
                "target_id": target_id,
                "target_type": target_type,
                "claim_text": claim_text,
                "claim_kind": _normalize_claim_kind(text=claim_text, polarity=polarity),
                "polarity": polarity,
                "quality_profile": "balanced_marginal_regenerated",
                "benchmark_eligibility": "benchmark_regenerated_non_title",
                "candidate_lane_present": False,
                "canonical_claim_id": _canonical_claim_id(
                    target_id=target_id,
                    target_type=target_type,
                    claim_text=claim_text,
                    polarity=polarity,
                ),
                "cluster_confidence": 0.85 if mapping_confidence >= 0.9 else 0.75,
                "failure_tags": [],
                "evaluation_slice": "regen_non_title_candidate",
                "proposed_action": "review_for_snapshot",
                "review_status": "accepted_regeneration_seed",
                "adjudication_status": "not_adjudicated",
                "notes": " | ".join(
                    part
                    for part in (
                        str(paper.get("title") or "").strip(),
                        str(regeneration_source.get("source_review_bucket") or "").strip(),
                        str(regeneration_source.get("source_bucket_reason") or "").strip(),
                    )
                    if part
                ),
                "source_packs": [source_pack],
                "source_paths": [str(regeneration_path)],
                "evidence_depths": [f"section_level_non_title:{section}"],
                "warnings": warnings,
                "expansion_seed_bucket": "accepted_regeneration_seed",
            }
        )
    return rows


def _family_target_types(rows: Iterable[dict[str, Any]]) -> set[str]:
    return {str(row.get("target_type") or "").strip() for row in rows if row.get("target_type")}


def build_outputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot_path = args.snapshot_v1.expanduser().resolve()
    prior_path = args.prior_adjudication_pack.expanduser().resolve()
    calibration_path = args.calibration_manifest.expanduser().resolve()
    heldout_path = args.heldout_manifest.expanduser().resolve()
    regeneration_paths = [path.expanduser().resolve() for path in args.accepted_regeneration_jsonl]

    snapshot_rows, snapshot_families, snapshot_warning_families, snapshot_target_types = _load_snapshot_rows(
        snapshot_path
    )
    prior_adjudication = _load_prior_adjudication(prior_path)
    _validate_snapshot_against_prior(
        snapshot_rows=snapshot_rows,
        prior_adjudication=prior_adjudication,
    )

    candidate_rows: list[dict[str, Any]] = []
    candidate_rows.extend(
        _build_manifest_seed_rows(calibration_path, source_pack="calibration_v3_lite")
    )
    candidate_rows.extend(
        _build_manifest_seed_rows(heldout_path, source_pack="heldout_v3_lite")
    )
    for regeneration_path in regeneration_paths:
        candidate_rows.extend(
            _build_regeneration_seed_rows(
                regeneration_path,
                source_pack=_source_pack_label(regeneration_path),
            )
        )

    seen_candidate_ids: set[str] = set()
    fresh_rows: list[dict[str, Any]] = []
    skipped_reviewed_total = 0
    for row in candidate_rows:
        _require_core_fields(row, source_path=Path(str(row["source_paths"][0]).split("#", 1)[0]))
        claim_id = str(row["source_claim_id"]).strip()
        if claim_id in seen_candidate_ids:
            raise SystemExit(
                f"Fail-closed expansion mismatch: duplicate candidate source_claim_id {claim_id}"
            )
        seen_candidate_ids.add(claim_id)
        prior_row = prior_adjudication.get(claim_id)
        if prior_row is not None:
            if _reviewed_identity_tuple(row) != _reviewed_identity_tuple(prior_row):
                raise SystemExit(
                    f"Fail-closed reviewed drift: fresh candidate {claim_id} conflicts with prior adjudication identity"
                )
            skipped_reviewed_total += 1
            continue
        fresh_rows.append(row)

    family_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fresh_rows:
        family_to_rows[str(row["canonical_claim_id"])].append(row)

    candidate_warning_families: set[str] = set()
    candidate_target_types = _family_target_types(fresh_rows)
    for family_id, members in family_to_rows.items():
        family_polarities = {
            str(member.get("polarity") or "").strip() for member in members if member.get("polarity")
        }
        family_warning = len(family_polarities) > 1 or any(
            member.get("warnings") or member.get("failure_tags") for member in members
        )
        if family_warning:
            candidate_warning_families.add(family_id)
        for member in members:
            member["family_member_count_in_pack"] = len(members)
            member["family_has_conflict"] = len(family_polarities) > 1
            member["family_has_warning_or_conflict"] = family_warning
            member["family_is_new_to_snapshot_v1"] = family_id not in snapshot_families
            member["expands_existing_snapshot_family"] = family_id in snapshot_families

    projected_families = set(snapshot_families) | set(family_to_rows)
    projected_warning_families = set(snapshot_warning_families) | set(candidate_warning_families)
    projected_target_types = set(snapshot_target_types) | set(candidate_target_types)

    fresh_rows.sort(
        key=lambda row: (
            row["expands_existing_snapshot_family"],
            row["target_type"],
            row["canonical_claim_id"],
            row["source_claim_id"],
        )
    )

    source_bucket_counts: Counter[str] = Counter(
        str(row.get("expansion_seed_bucket") or "") for row in fresh_rows if row.get("expansion_seed_bucket")
    )
    target_type_counts: Counter[str] = Counter(
        str(row.get("target_type") or "") for row in fresh_rows if row.get("target_type")
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "inputs": {
            "snapshot_v1": str(snapshot_path),
            "prior_adjudication_pack": str(prior_path),
            "calibration_manifest": str(calibration_path),
            "heldout_manifest": str(heldout_path),
            "accepted_regeneration_jsonl": [str(path) for path in regeneration_paths],
        },
        "counts": {
            "current_reviewed_rows_total": len(snapshot_rows),
            "current_reviewed_families_total": len(snapshot_families),
            "current_warning_or_conflict_families_total": len(snapshot_warning_families),
            "current_target_type_buckets_total": len(snapshot_target_types),
            "candidate_rows_total": len(fresh_rows),
            "candidate_canonical_families_total": len(family_to_rows),
            "candidate_new_families_total": sum(
                1 for family_id in family_to_rows if family_id not in snapshot_families
            ),
            "candidate_expands_existing_families_total": sum(
                1 for family_id in family_to_rows if family_id in snapshot_families
            ),
            "candidate_warning_or_conflict_families_total": len(candidate_warning_families),
            "candidate_target_type_buckets_total": len(candidate_target_types),
            "skipped_prior_reviewed_rows_total": skipped_reviewed_total,
            "projected_canonical_families_total": len(projected_families),
            "projected_warning_or_conflict_families_total": len(projected_warning_families),
            "projected_target_type_buckets_total": len(projected_target_types),
            "threshold_min_canonical_families": MIN_CANONICAL_FAMILIES,
            "threshold_min_warning_or_conflict_families": MIN_WARNING_OR_CONFLICT_FAMILIES,
            "threshold_min_target_type_buckets": MIN_TARGET_TYPE_BUCKETS,
            "threshold_canonical_families_met": len(projected_families) >= MIN_CANONICAL_FAMILIES,
            "threshold_warning_or_conflict_families_met": (
                len(projected_warning_families) >= MIN_WARNING_OR_CONFLICT_FAMILIES
            ),
            "threshold_target_type_buckets_met": len(projected_target_types) >= MIN_TARGET_TYPE_BUCKETS,
            "threshold_all_met": (
                len(projected_families) >= MIN_CANONICAL_FAMILIES
                and len(projected_warning_families) >= MIN_WARNING_OR_CONFLICT_FAMILIES
                and len(projected_target_types) >= MIN_TARGET_TYPE_BUCKETS
            ),
            **{
                f"candidate_seed_bucket_{bucket}": source_bucket_counts[bucket]
                for bucket in sorted(source_bucket_counts)
            },
            **{
                f"candidate_target_type_{target_type}": target_type_counts[target_type]
                for target_type in sorted(target_type_counts)
            },
        },
    }
    return fresh_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pack_rows, summary = build_outputs(args)
    pack_jsonl = output_dir / "claim_snapshot_v1_expansion_pack.jsonl"
    pack_tsv = output_dir / "claim_snapshot_v1_expansion_pack.tsv"
    summary_json = output_dir / "claim_snapshot_v1_expansion_summary.json"

    _write_jsonl(pack_jsonl, pack_rows)
    _write_tsv(
        pack_tsv,
        pack_rows,
        [
            "family_is_new_to_snapshot_v1",
            "expands_existing_snapshot_family",
            "family_has_warning_or_conflict",
            "expansion_seed_bucket",
            "source_claim_id",
            "paper_id",
            "target_type",
            "target_id",
            "polarity",
            "canonical_claim_id",
            "review_status",
            "benchmark_eligibility",
            "warnings",
            "failure_tags",
            "source_packs",
            "notes",
        ],
    )
    summary["artifacts"] = {
        "claim_snapshot_v1_expansion_pack_jsonl": str(pack_jsonl),
        "claim_snapshot_v1_expansion_pack_tsv": str(pack_tsv),
        "summary_json": str(summary_json),
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
