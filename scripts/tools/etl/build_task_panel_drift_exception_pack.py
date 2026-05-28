#!/usr/bin/env python3
"""Build residual drift exception lists after protected claims are excluded."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EMOTION_REGULATION_CURRENT_ID = "neurostore_task:55joBd4TMrva:fmri:0"
EPISODIC_MEMORY_CURRENT_ID = "neurostore_task:2oMh3nFe82q8:fmri:0"
KEEP_EMOTION_MAPPING_ORIGINALS = {
    "concept:emotional_regulation",
    "concept:emotional_control",
    "concept:emotion_attention_regulation",
    "concept:emotion_upregulation",
}
KEEP_EPISODIC_MAPPING_ORIGINALS = {
    "concept:episodic_memories",
}
MANUAL_EPISODIC_MAPPING_ORIGINALS = {
    "concept:movie",
}
TAIL_MANUAL_TRANSITIONS = {
    ("task:subfamily:sf_wm_updating_streaming", "neurostore_task:7CHG5JsyUddj:fmri:1"),
    (
        "task:subfamily:sf_lexical_access_orthography",
        "neurostore_task:3bPPYn5rYNLf:fmri:0",
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adjudication-pack", type=Path, required=True)
    parser.add_argument("--protected-claim-ids", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _load_protected_claim_ids(path: Path) -> set[str]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Missing protected-claim-ids file: {resolved}")
    return {
        line.strip()
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _classify(row: dict[str, Any]) -> tuple[str, str, str]:
    old_task_id = str(row.get("old_task_id") or "").strip()
    current_target_id = str(row.get("current_target_id") or "").strip()
    mapping_original = str(row.get("mapping_original") or "").strip()
    proposed_action = str(row.get("proposed_action") or "").strip()

    if (
        old_task_id == "task:subfamily:sf_affect_induction"
        and current_target_id == EMOTION_REGULATION_CURRENT_ID
    ):
        if mapping_original in KEEP_EMOTION_MAPPING_ORIGINALS:
            return (
                "keep_exception",
                "emotion_regulation_semantic_match",
                "Keep as semantic namespace replacement; mapping original aligns with Emotion Regulation.",
            )
        return (
            "reject_default",
            "emotion_regulation_semantic_mismatch",
            "Do not auto-keep under Emotion Regulation; mapping original suggests perception/viewing affect rather than regulation.",
        )

    if (
        old_task_id == "task:subfamily:sf_item_recognition"
        and current_target_id == EPISODIC_MEMORY_CURRENT_ID
    ):
        if mapping_original in KEEP_EPISODIC_MAPPING_ORIGINALS:
            return (
                "keep_exception",
                "episodic_memory_semantic_match",
                "Keep as semantic namespace replacement; mapping original aligns with episodic memory.",
            )
        if mapping_original in MANUAL_EPISODIC_MAPPING_ORIGINALS:
            return (
                "manual_review",
                "episodic_memory_ambiguous_movie",
                "Movie-related rows are ambiguous between memory, viewing, and stimulus metadata.",
            )
        return (
            "reject_default",
            "episodic_memory_semantic_mismatch",
            "Reject by default; mapping original looks like metadata/noise or does not support Episodic Memory.",
        )

    if (old_task_id, current_target_id) in TAIL_MANUAL_TRANSITIONS:
        return (
            "manual_review",
            "unreviewed_neurostore_tail",
            "Small neurostore tail not yet transition-reviewed; hold for manual adjudication.",
        )

    if proposed_action == "review_default_reject":
        return (
            "reject_default",
            "coarse_onvoc_collapse",
            "Reject by default; drift collapsed a subfamily task to a coarse ONVOC target.",
        )

    if proposed_action == "review_semantic_coarsening":
        return (
            "manual_review",
            "unclassified_semantic_coarsening",
            "Semantic coarsening without a reviewed transition rule; hold for manual review.",
        )

    return (
        "manual_review",
        "unexpected_residual_drift",
        "Residual drift row fell outside the current rule set; inspect manually.",
    )


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "final_decision",
        "decision_reason",
        "paper_id",
        "claim_id",
        "run_id",
        "old_task_id",
        "current_target_id",
        "mapping_original",
        "current_target_label",
        "onvoc_label",
        "paper_title",
        "decision_note",
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


def build_summary(
    rows: Sequence[dict[str, Any]],
    adjudication_pack_path: Path,
    protected_claim_ids_path: Path,
) -> dict[str, Any]:
    decision_counts = Counter(row["final_decision"] for row in rows)
    reason_counts = Counter(row["decision_reason"] for row in rows)
    transition_counts = Counter(
        (row["old_task_id"], row["current_target_id"], row["final_decision"])
        for row in rows
    )
    protection_claim_ids = sorted(
        {row["claim_id"] for row in rows if row["final_decision"] == "keep_exception"}
    )
    manual_claim_ids = sorted(
        {row["claim_id"] for row in rows if row["final_decision"] == "manual_review"}
    )
    reject_claim_ids = sorted(
        {row["claim_id"] for row in rows if row["final_decision"] == "reject_default"}
    )
    return {
        "generated_at": _utc_now_iso(),
        "adjudication_pack_path": str(adjudication_pack_path.resolve()),
        "protected_claim_ids_path": str(protected_claim_ids_path.resolve()),
        "counts": {
            "residual_rows": len(rows),
            "keep_exception_rows": decision_counts["keep_exception"],
            "manual_review_rows": decision_counts["manual_review"],
            "reject_default_rows": decision_counts["reject_default"],
            "keep_exception_claim_ids": len(protection_claim_ids),
            "manual_review_claim_ids": len(manual_claim_ids),
            "reject_default_claim_ids": len(reject_claim_ids),
        },
        "counts_by_reason": reason_counts.most_common(),
        "top_transitions": [
            [old_task_id, current_target_id, decision, count]
            for (old_task_id, current_target_id, decision), count in transition_counts.most_common(
                20
            )
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    adjudication_pack_path = args.adjudication_pack.expanduser().resolve()
    protected_claim_ids = _load_protected_claim_ids(args.protected_claim_ids)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    residual_rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(adjudication_pack_path):
        claim_id = str(row.get("claim_id") or "").strip()
        if claim_id in protected_claim_ids:
            continue
        final_decision, decision_reason, decision_note = _classify(row)
        enriched = dict(row)
        enriched["final_decision"] = final_decision
        enriched["decision_reason"] = decision_reason
        enriched["decision_note"] = decision_note
        residual_rows.append(enriched)

    summary = build_summary(
        residual_rows, adjudication_pack_path, args.protected_claim_ids
    )
    keep_claim_ids = sorted(
        {row["claim_id"] for row in residual_rows if row["final_decision"] == "keep_exception"}
    )
    manual_claim_ids = sorted(
        {row["claim_id"] for row in residual_rows if row["final_decision"] == "manual_review"}
    )
    reject_claim_ids = sorted(
        {row["claim_id"] for row in residual_rows if row["final_decision"] == "reject_default"}
    )

    _write_jsonl(output_dir / "drift_exception_pack.jsonl", residual_rows)
    _write_tsv(output_dir / "drift_exception_pack.tsv", residual_rows)
    for decision in ("keep_exception", "manual_review", "reject_default"):
        decision_rows = [row for row in residual_rows if row["final_decision"] == decision]
        _write_jsonl(output_dir / f"{decision}.jsonl", decision_rows)
        _write_tsv(output_dir / f"{decision}.tsv", decision_rows)
    (output_dir / "keep_exception_claim_ids.txt").write_text(
        "\n".join(keep_claim_ids) + ("\n" if keep_claim_ids else ""),
        encoding="utf-8",
    )
    (output_dir / "manual_review_claim_ids.txt").write_text(
        "\n".join(manual_claim_ids) + ("\n" if manual_claim_ids else ""),
        encoding="utf-8",
    )
    (output_dir / "reject_default_claim_ids.txt").write_text(
        "\n".join(reject_claim_ids) + ("\n" if reject_claim_ids else ""),
        encoding="utf-8",
    )
    (output_dir / "drift_exception_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
