from __future__ import annotations

import json
from pathlib import Path

from scripts.br_kg.build_kggen_task_mapping_salvage_pack import (
    build_task_mapping_salvage_pack,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def test_build_task_mapping_salvage_pack_groups_candidates(tmp_path: Path) -> None:
    mapping_rows = tmp_path / "mapping_rows.jsonl"
    adapted = tmp_path / "kggen_adapted.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        mapping_rows,
        [
            {
                "record_index": 1,
                "source_id": "concept:word_reading",
                "source_label": "word reading",
                "status": "below_threshold",
                "reason": "below_threshold",
                "onvoc_label": "Reading Comprehension",
                "top1_score": 0.31,
                "top2_score": 0.24,
                "method": "lexical_ngram",
            },
            {
                "record_index": 2,
                "source_id": "concept:phonological_localizers",
                "source_label": "phonological localizers",
                "status": "below_threshold",
                "reason": "below_threshold",
                "onvoc_label": "Phonological Processing",
                "top1_score": 0.35,
                "top2_score": 0.22,
                "method": "lexical_ngram",
            },
            {
                "record_index": 3,
                "source_id": "concept:resting_state_fmri",
                "source_label": "Resting-State fMRI",
                "status": "ambiguous",
                "reason": "margin_too_small",
                "top1_score": 0.19,
                "top2_score": 0.17,
                "method": None,
            },
            {
                "record_index": 4,
                "source_id": "concept:fmri_processing",
                "source_label": "fMRI Processing",
                "status": "below_threshold",
                "reason": "below_threshold",
                "onvoc_label": "Phonological Processing",
                "top1_score": 0.38,
                "top2_score": 0.16,
                "method": "lexical_ngram",
            },
            {
                "record_index": 5,
                "source_id": "concept:language",
                "source_label": "Language",
                "status": "mapped",
                "reason": "crosswalk_label_exact",
                "onvoc_id": "ONVOC_0000431",
                "onvoc_label": "Language",
                "method": "crosswalk_label",
            },
        ],
    )

    _write_jsonl(
        adapted,
        [
            {
                "paper": {"id": "pmid:1", "title": "word reading paper"},
                "claim": {"text": "word reading claim"},
                "evidence": {"quote": "word reading quote", "section": "title"},
                "signals": {"title_hit": True},
            },
            {
                "paper": {"id": "pmid:2", "title": "phonology paper"},
                "claim": {"text": "phonology claim"},
                "evidence": {"quote": "phonology quote", "section": "title"},
                "signals": {"title_hit": True},
            },
            {
                "paper": {"id": "pmid:3", "title": "rest paper"},
                "claim": {"text": "rest claim"},
                "evidence": {"quote": "rest quote", "section": "title"},
                "signals": {"title_hit": True},
            },
            {
                "paper": {"id": "pmid:4", "title": "processing paper"},
                "claim": {"text": "processing claim"},
                "evidence": {"quote": "processing quote", "section": "title"},
                "signals": {"title_hit": True},
            },
            {
                "paper": {"id": "pmid:5", "title": "language paper"},
                "claim": {"text": "language claim"},
                "evidence": {"quote": "language quote", "section": "title"},
                "signals": {"title_hit": True},
            },
        ],
    )

    summary = build_task_mapping_salvage_pack(
        mapping_rows_path=mapping_rows,
        kggen_adapted_path=adapted,
        output_dir=output_dir,
        include_mapped_controls=True,
    )

    assert summary["counts"]["task_like_unique_unresolved"] == 4
    assert summary["counts"]["mapped_controls"] == 1
    assert summary["bucket_counts"]["threshold_gap"] == 1
    assert summary["bucket_counts"]["crosswalk_gap"] == 1
    assert summary["bucket_counts"]["meta_baseline_gap"] == 1
    assert summary["bucket_counts"]["non_task_modality"] == 1

    pack_path = Path(summary["artifacts"]["salvage_pack_jsonl"])
    rows = [
        json.loads(line) for line in pack_path.read_text(encoding="utf-8").splitlines()
    ]

    by_label = {row["source_label"]: row for row in rows}
    assert (
        by_label["phonological localizers"]["suggested_onvoc_label"]
        == "Phonological Processing"
    )
    assert by_label["word reading"]["salvage_bucket"] == "crosswalk_gap"
    assert (
        by_label["Resting-State fMRI"]["suggested_action"]
        == "reroute_meta_baseline_lane"
    )
    assert (
        by_label["fMRI Processing"]["suggested_action"] == "blacklist_non_task_modality"
    )
