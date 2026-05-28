#!/usr/bin/env python3
"""Review replayed sf_social_perception_attention rows from the missing-claim subset."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FACE_GAZE_CORE_MAPPING_ORIGINALS = {
    "concept:gaze_processing",
    "concept:face_and_gaze_processing",
    "concept:face_identity_processing",
    "concept:faces_processing",
    "concept:facial_processing",
}
SOCIAL_AFFECT_BOUNDARY_MAPPING_ORIGINALS = {
    "concept:valence_processing",
    "concept:em_processing",
    "concept:social_perceptions",
}
CUE_REACTIVITY_MAPPING_ORIGINALS = {"concept:cue_processing"}
LANGUAGE_PRAGMATICS_MAPPING_ORIGINALS = {
    "concept:case_processing",
    "concept:accent_processing",
    "concept:ci_processing",
}
GENERIC_COGNITIVE_MAPPING_ORIGINALS = {
    "concept:feature_processing",
    "concept:space_processing",
    "concept:es_processing",
}
META_REVIEW_MAPPING_ORIGINALS = {"concept:core_processing"}
TARGET_OLD_TASK_ID = "task:subfamily:sf_social_perception_attention"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _classify(row: dict[str, Any]) -> tuple[str, str, str]:
    mapping_original = str(row.get("mapping_original") or "").strip()
    if mapping_original in FACE_GAZE_CORE_MAPPING_ORIGINALS:
        return (
            "face_gaze_social_core",
            "face_gaze_social_stimulus",
            "Strong face/gaze social-stimulus signal; review as the highest-confidence social-perception bucket.",
        )
    if mapping_original in SOCIAL_AFFECT_BOUNDARY_MAPPING_ORIGINALS:
        return (
            "affect_valence_social_boundary",
            "social_emotion_construct_boundary",
            "Boundary bucket between social perception and broader affect/valuation constructs; do not auto-collapse into either lane.",
        )
    if mapping_original in CUE_REACTIVITY_MAPPING_ORIGINALS:
        return (
            "cue_reactivity_non_social",
            "cue_salience_non_social",
            "Cue-reactivity/addiction salience row; reroute away from social-perception task semantics.",
        )
    if mapping_original in LANGUAGE_PRAGMATICS_MAPPING_ORIGINALS:
        return (
            "language_pragmatics_non_social",
            "language_pragmatics_processing",
            "Language or pragmatics processing row; should not stay under social-perception task semantics.",
        )
    if mapping_original in GENERIC_COGNITIVE_MAPPING_ORIGINALS:
        return (
            "generic_cognitive_sensory_non_social",
            "generic_cognitive_or_sensory_processing",
            "Generic cognitive or sensory processing row; reroute out of the social-perception task lane.",
        )
    if mapping_original in META_REVIEW_MAPPING_ORIGINALS:
        return (
            "meta_review_noise",
            "meta_review_or_method_summary",
            "Meta/review-style row, not a task target; exclude from task-lane semantics.",
        )
    return (
        "unexpected_social_replay_row",
        "unexpected_unbucketed_mapping",
        "Unbucketed social-perception replay row; inspect manually before changing semantics.",
    )


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "review_decision",
        "decision_reason",
        "paper_id",
        "claim_id",
        "run_id",
        "mapping_original",
        "old_task_id",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    replay_candidates_path = args.replay_candidates.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(replay_candidates_path):
        if str(row.get("old_task_id") or "").strip() != TARGET_OLD_TASK_ID:
            continue
        review_decision, decision_reason, decision_note = _classify(row)
        enriched = dict(row)
        enriched["review_decision"] = review_decision
        enriched["decision_reason"] = decision_reason
        enriched["decision_note"] = decision_note
        rows.append(enriched)

    decision_counts = Counter(row["review_decision"] for row in rows)
    mapping_counts = Counter(row["mapping_original"] for row in rows)
    _write_jsonl(output_dir / "social_perception_replay_review_pack.jsonl", rows)
    _write_tsv(output_dir / "social_perception_replay_review_pack.tsv", rows)
    for decision in (
        "face_gaze_social_core",
        "affect_valence_social_boundary",
        "cue_reactivity_non_social",
        "language_pragmatics_non_social",
        "generic_cognitive_sensory_non_social",
        "meta_review_noise",
        "unexpected_social_replay_row",
    ):
        decision_rows = [row for row in rows if row["review_decision"] == decision]
        _write_jsonl(output_dir / f"{decision}.jsonl", decision_rows)
        _write_tsv(output_dir / f"{decision}.tsv", decision_rows)

    summary = {
        "generated_at": _utc_now_iso(),
        "replay_candidates_path": str(replay_candidates_path),
        "counts": {
            "review_rows": len(rows),
            "face_gaze_social_core": decision_counts["face_gaze_social_core"],
            "affect_valence_social_boundary": decision_counts[
                "affect_valence_social_boundary"
            ],
            "cue_reactivity_non_social": decision_counts[
                "cue_reactivity_non_social"
            ],
            "language_pragmatics_non_social": decision_counts[
                "language_pragmatics_non_social"
            ],
            "generic_cognitive_sensory_non_social": decision_counts[
                "generic_cognitive_sensory_non_social"
            ],
            "meta_review_noise": decision_counts["meta_review_noise"],
            "unexpected_social_replay_row": decision_counts[
                "unexpected_social_replay_row"
            ],
        },
        "counts_by_mapping_original": mapping_counts.most_common(),
        "artifacts": {
            "review_pack_jsonl": str(
                output_dir / "social_perception_replay_review_pack.jsonl"
            ),
            "summary_json": str(output_dir / "social_perception_replay_review_summary.json"),
        },
    }
    (output_dir / "social_perception_replay_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
