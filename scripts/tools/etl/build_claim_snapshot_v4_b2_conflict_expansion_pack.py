#!/usr/bin/env python3
"""Build a reviewed B2 conflict-expansion pack from curated or hot-loaded live claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

CURATED_FAMILIES: list[dict[str, Any]] = [
    {
        "family_key": "attention_top_down_bottom_up_dissociation",
        "canonical_claim_id": "canonical_claim:"
        + hashlib.md5(
            "concept:attention|top_down_bottom_up_attention_dissociation".encode("utf-8")
        ).hexdigest(),
        "target_id": "concept:attention",
        "target_type": "Concept",
        "claim_ids": [
            "claim:ebb1be1002d3e248b15edcf1587285ea",
            "claim:b81e188008db904ec71df67f8623f067",
        ],
        "family_label": "top_down_bottom_up_attention_dissociation",
        "decision_reason": (
            "Curated live mixed-polarity attention family with explicit top-down/bottom-up "
            "attention language. Retain as conflict-cluster warning so B2 no longer has only "
            "one conflict family."
        ),
        "failure_tags": [
            "polarity_or_antonym_confusion",
            "semantic_composite_or_analysis_claim",
            "title_only_or_insufficient_text",
        ],
    }
]

DEFAULT_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "from",
    "into",
    "during",
    "after",
    "before",
    "over",
    "under",
    "across",
    "load",
    "study",
    "effects",
    "effect",
    "brain",
    "neural",
    "human",
    "humans",
    "functional",
    "magnetic",
    "resonance",
    "imaging",
}
COMPOSITE_TOKENS = ("network", "networks", "analysis", "connectivity", "pattern")
TITLEISH_TOKENS = ("study", "imaging", "fmri", "resting", "evidence")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--families-json",
        type=Path,
        help="Optional JSON file containing an explicit list of family specs.",
    )
    parser.add_argument(
        "--target-id",
        action="append",
        default=[],
        help="Hot-load one conflict family per target from live Neo4j.",
    )
    parser.add_argument(
        "--exclude-pack-jsonl",
        action="append",
        default=[],
        help=(
            "Optional reviewed pack/examples JSONL whose source_claim_id/example_id values "
            "should be excluded from hot-load mining."
        ),
    )
    parser.add_argument(
        "--min-token-overlap",
        type=int,
        default=2,
        help="Minimum shared token count when mining live opposing pairs.",
    )
    parser.add_argument(
        "--min-jaccard",
        type=float,
        default=0.2,
        help="Minimum token Jaccard overlap when mining live opposing pairs.",
    )
    parser.add_argument(
        "--top-k-per-target",
        type=int,
        default=1,
        help="Maximum mined opposing families per target.",
    )
    parser.add_argument(
        "--quality-profile",
        default="live_conflict_seed",
        help="Quality profile to stamp on hot-loaded rows.",
    )
    parser.add_argument(
        "--review-status",
        default="reviewed_live_conflict_seed",
        help="Review status to stamp on hot-loaded rows.",
    )
    return parser.parse_args(argv)


def _load_repo_dotenv() -> None:
    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key, value)


def _require_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(
            f"Fail-closed B2 conflict expansion mismatch: missing required env {name}"
        )
    return value


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _slugify(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def _target_type_for_id(target_id: str) -> str:
    lowered = target_id.lower()
    if lowered.startswith(("region:", "schaefer", "aal:", "brodmann:", "onvoc_")):
        return "Region"
    if lowered.startswith(("task:", "neurostore_task:", "nback")):
        return "Task"
    return "Concept"


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return [token for token in tokens if len(token) > 2 and token not in DEFAULT_STOPWORDS]


def _load_families_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("Fail-closed B2 conflict expansion mismatch: families-json must be a list")
    return [dict(item) for item in raw]


def _collect_excluded_claim_ids(paths: Sequence[Path]) -> set[str]:
    excluded: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        with resolved.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                row = json.loads(raw)
                claim_id = str(
                    row.get("source_claim_id") or row.get("example_id") or row.get("claim_id") or ""
                ).strip()
                if claim_id:
                    excluded.add(claim_id)
    return excluded


def _connect_driver() -> GraphDatabase.driver:
    _load_repo_dotenv()
    uri = _require_env("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER") or "neo4j"
    password = _require_env("NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


def _fetch_claim_rows_by_ids(claim_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    query = """
    MATCH (c:Claim)
    WHERE c.id IN $claim_ids
    OPTIONAL MATCH (:Publication)-[r:REPORTS_CLAIM]->(c)
    RETURN
      c.id AS claim_id,
      c.paper_id AS paper_id,
      c.target_id AS target_id,
      c.claim_polarity AS polarity,
      c.text AS claim_text,
      c.method_rigor AS method_rigor,
      c.claim_strength AS claim_strength,
      c.source AS source,
      r.run_id AS run_id,
      r.source AS rel_source,
      r.evidence_quality_score AS evidence_quality_score
    ORDER BY c.id
    """
    driver = _connect_driver()
    try:
        with driver.session() as session:
            rows = session.run(query, claim_ids=list(claim_ids)).data()
    finally:
        driver.close()
    by_claim_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        claim_id = str(row.get("claim_id") or "").strip()
        if claim_id:
            by_claim_id[claim_id] = row
    missing = sorted(set(claim_ids) - set(by_claim_id))
    if missing:
        raise SystemExit(
            "Fail-closed B2 conflict expansion mismatch: missing live claim ids "
            f"{missing}"
        )
    return by_claim_id


def _fetch_target_claims(target_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not target_ids:
        return []
    query = """
    MATCH (c:Claim)
    WHERE c.target_id IN $target_ids AND c.claim_polarity IN ["supports", "refutes"]
    OPTIONAL MATCH (:Publication)-[r:REPORTS_CLAIM]->(c)
    RETURN
      c.id AS claim_id,
      c.paper_id AS paper_id,
      c.target_id AS target_id,
      c.claim_polarity AS polarity,
      c.text AS claim_text,
      c.method_rigor AS method_rigor,
      c.claim_strength AS claim_strength,
      c.source AS source,
      r.run_id AS run_id,
      r.source AS rel_source,
      r.evidence_quality_score AS evidence_quality_score
    ORDER BY c.target_id, c.claim_strength DESC, c.id
    """
    driver = _connect_driver()
    try:
        with driver.session() as session:
            rows = session.run(query, target_ids=list(target_ids)).data()
    finally:
        driver.close()
    return rows


def _family_failure_tags(*texts: str) -> list[str]:
    joined = " ".join(texts).lower()
    tags = ["polarity_or_antonym_confusion"]
    if any(token in joined for token in COMPOSITE_TOKENS):
        tags.append("semantic_composite_or_analysis_claim")
    if any(token in joined for token in TITLEISH_TOKENS):
        tags.append("title_only_or_insufficient_text")
    return sorted(set(tags))


def _mine_families_from_targets(
    *,
    target_ids: Sequence[str],
    min_token_overlap: int,
    min_jaccard: float,
    top_k_per_target: int,
    excluded_claim_ids: set[str],
) -> list[dict[str, Any]]:
    live_rows = _fetch_target_claims(target_ids)
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in live_rows:
        claim_id = str(row.get("claim_id") or "").strip()
        if claim_id and claim_id in excluded_claim_ids:
            continue
        by_target[str(row.get("target_id") or "").strip()].append(row)

    families: list[dict[str, Any]] = []
    for target_id in target_ids:
        rows = by_target.get(target_id, [])
        supports = [row for row in rows if str(row.get("polarity")) == "supports"]
        refutes = [row for row in rows if str(row.get("polarity")) == "refutes"]
        scored_pairs: list[tuple[float, int, str, dict[str, Any], dict[str, Any]]] = []
        for support in supports:
            support_tokens = set(_tokenize(str(support.get("claim_text") or "")))
            if not support_tokens:
                continue
            for refute in refutes:
                if str(support.get("paper_id") or "") == str(refute.get("paper_id") or ""):
                    continue
                refute_tokens = set(_tokenize(str(refute.get("claim_text") or "")))
                if not refute_tokens:
                    continue
                overlap = support_tokens & refute_tokens
                if len(overlap) < min_token_overlap:
                    continue
                jaccard = len(overlap) / len(support_tokens | refute_tokens)
                if jaccard < min_jaccard:
                    continue
                overlap_slug = "_".join(sorted(list(overlap))[:4]) or _slugify(target_id)
                scored_pairs.append((jaccard, len(overlap), overlap_slug, support, refute))

        scored_pairs.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -(float(item[3].get("claim_strength") or 0.0) + float(item[4].get("claim_strength") or 0.0)),
                str(item[3].get("claim_id") or ""),
                str(item[4].get("claim_id") or ""),
            )
        )
        used_claim_ids: set[str] = set()
        selected = 0
        for jaccard, overlap_count, overlap_slug, support, refute in scored_pairs:
            support_id = str(support.get("claim_id") or "").strip()
            refute_id = str(refute.get("claim_id") or "").strip()
            if not support_id or not refute_id:
                continue
            if support_id in used_claim_ids or refute_id in used_claim_ids:
                continue
            selected += 1
            used_claim_ids.update({support_id, refute_id})
            families.append(
                {
                    "family_key": f"hotload_{_slugify(target_id)}_{selected}",
                    "canonical_claim_id": "canonical_claim:"
                    + hashlib.md5(
                        f"{target_id}|{support_id}|{refute_id}".encode("utf-8")
                    ).hexdigest(),
                    "target_id": target_id,
                    "target_type": _target_type_for_id(target_id),
                    "claim_ids": [support_id, refute_id],
                    "family_label": overlap_slug,
                    "decision_reason": (
                        f"Hot-loaded live mixed-polarity family for {target_id} using token "
                        f"overlap heuristic (jaccard={jaccard:.3f}, overlap={overlap_count})."
                    ),
                    "failure_tags": _family_failure_tags(
                        str(support.get("claim_text") or ""),
                        str(refute.get("claim_text") or ""),
                    ),
                    "mining_jaccard": jaccard,
                    "mining_overlap_count": overlap_count,
                    "mining_overlap_slug": overlap_slug,
                }
            )
            if selected >= top_k_per_target:
                break
        if selected == 0:
            raise SystemExit(
                "Fail-closed B2 conflict expansion mismatch: "
                f"no live opposing pair passed filters for target {target_id}"
            )
    return families


def _resolve_families(
    args: argparse.Namespace, excluded_claim_ids: set[str]
) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    if args.families_json:
        families.extend(_load_families_json(args.families_json.expanduser().resolve()))
    if args.target_id:
        families.extend(
            _mine_families_from_targets(
                target_ids=[str(target_id).strip() for target_id in args.target_id if str(target_id).strip()],
                min_token_overlap=args.min_token_overlap,
                min_jaccard=args.min_jaccard,
                top_k_per_target=args.top_k_per_target,
                excluded_claim_ids=excluded_claim_ids,
            )
        )
    if not families:
        families = list(CURATED_FAMILIES)
    return families


def build_outputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    excluded_claim_ids = _collect_excluded_claim_ids(
        [Path(raw_path) for raw_path in list(args.exclude_pack_jsonl or []) if str(raw_path).strip()]
    )
    family_specs = _resolve_families(args, excluded_claim_ids)
    claim_ids = [
        claim_id
        for family in family_specs
        for claim_id in list(family.get("claim_ids") or [])
        if str(claim_id).strip()
    ]
    live_rows = _fetch_claim_rows_by_ids(claim_ids)
    seen_source_claim_ids: set[str] = set()
    pack_rows: list[dict[str, Any]] = []
    target_type_counter: Counter[str] = Counter()

    for family in family_specs:
        target_id = str(family["target_id"])
        target_type = str(family.get("target_type") or _target_type_for_id(target_id))
        target_type_counter[target_type] += 1
        for claim_id in list(family["claim_ids"]):
            if claim_id in seen_source_claim_ids:
                raise SystemExit(
                    "Fail-closed B2 conflict expansion mismatch: "
                    f"duplicate source_claim_id across families {claim_id}"
                )
            seen_source_claim_ids.add(claim_id)
            live = live_rows[claim_id]
            live_target_id = str(live.get("target_id") or "").strip()
            if live_target_id != target_id:
                raise SystemExit(
                    "Fail-closed B2 conflict expansion mismatch: "
                    f"{claim_id} target_id {live_target_id!r} != expected {target_id!r}"
                )
            pack_rows.append(
                {
                    "source_claim_id": claim_id,
                    "paper_id": str(live.get("paper_id") or "").strip(),
                    "canonical_claim_id": str(family["canonical_claim_id"]),
                    "target_id": target_id,
                    "target_type": target_type,
                    "claim_text": str(live.get("claim_text") or "").strip(),
                    "claim_kind": "claim",
                    "polarity": str(live.get("polarity") or "").strip(),
                    "quality_profile": str(args.quality_profile),
                    "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                    "candidate_lane_present": False,
                    "failure_tags": list(family.get("failure_tags") or ["polarity_or_antonym_confusion"]),
                    "adjudicated_action": "retain_conflict_cluster_with_warning",
                    "adjudication_status": "reviewed_conflict_cluster_warning",
                    "adjudication_bucket": "include_conflict_cluster_with_warning",
                    "snapshot_role": "conflict_cluster_warning",
                    "decision_reason": str(family["decision_reason"]),
                    "review_status": str(args.review_status),
                    "evaluation_slice": "same_target_opposing_stance",
                    "review_material": {
                        "source": "live_neo4j_claim_export",
                        "family_key": str(family["family_key"]),
                        "family_label": str(family["family_label"]),
                        "run_id": str(live.get("run_id") or "").strip(),
                        "claim_source": str(live.get("source") or "").strip(),
                        "rel_source": str(live.get("rel_source") or "").strip(),
                        "method_rigor": live.get("method_rigor"),
                        "claim_strength": live.get("claim_strength"),
                        "evidence_quality_score": live.get("evidence_quality_score"),
                        "mining_jaccard": family.get("mining_jaccard"),
                        "mining_overlap_count": family.get("mining_overlap_count"),
                        "mining_overlap_slug": family.get("mining_overlap_slug"),
                    },
                }
            )

    summary = {
        "generated_at": _utc_now_iso(),
        "counts": {
            "conflict_families_total": len(family_specs),
            "rows_total": len(pack_rows),
            "target_type_Concept": sum(1 for row in pack_rows if row["target_type"] == "Concept"),
            "target_type_Region": sum(1 for row in pack_rows if row["target_type"] == "Region"),
            "target_type_Task": sum(1 for row in pack_rows if row["target_type"] == "Task"),
        },
        "notes": {
            "bounded_live_conflict_seed": True,
            "families_json_used": bool(args.families_json),
            "hotload_target_ids_total": len([target_id for target_id in args.target_id if str(target_id).strip()]),
            "excluded_claim_ids_total": len(excluded_claim_ids),
            "purpose": "Increase B2 conflict-family coverage so test can contain conflict rows.",
        },
        "resolved_families": family_specs,
    }
    return pack_rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    pack_rows, summary = build_outputs(args)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pack_path = args.output_dir / "claim_snapshot_v4_b2_conflict_expansion_pack.jsonl"
    summary_path = args.output_dir / "claim_snapshot_v4_b2_conflict_expansion_summary.json"
    _write_jsonl(pack_path, pack_rows)
    summary["artifacts"] = {
        "conflict_expansion_pack_jsonl": str(pack_path),
        "summary_json": str(summary_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
