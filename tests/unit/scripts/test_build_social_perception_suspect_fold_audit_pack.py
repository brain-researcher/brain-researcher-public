from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_social_perception_suspect_fold_audit_pack import (
    build_social_perception_suspect_fold_audit_pack,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_social_perception_suspect_fold_audit_pack(tmp_path: Path) -> None:
    package_dir = tmp_path / "task_panel_package"
    package_dir.mkdir(parents=True, exist_ok=True)

    _write_jsonl(
        package_dir / "task_panel_mapping_rows.jsonl",
        [
            {
                "status": "mapped",
                "source_id": "concept:personally_familiar_faces",
                "source_label": "personally familiar faces",
                "onvoc_id": "ONVOC_0000503",
                "onvoc_label": "Social Perception",
            },
            {
                "status": "mapped",
                "source_id": "concept:lexical_decision",
                "source_label": "lexical decision",
                "onvoc_id": "ONVOC_1234567",
                "onvoc_label": "Reading Comprehension",
            },
        ],
    )

    _write_jsonl(
        package_dir / "task_panel_records.jsonl",
        [
            {
                "paper": {
                    "id": "pmid:1234",
                    "title": "Neural substrates for functionally discriminating self-face from personally familiar faces.",
                    "pmid": "1234",
                    "doi": "10.1002/hbm.20168",
                },
                "claim": {
                    "id": "claim:1",
                    "text": "self-face is functionally discriminated from personally familiar faces",
                },
                "evidence": {
                    "quote": "ERP source analysis during familiar face processing.",
                },
                "target": {
                    "id": "task:subfamily:sf_speech_perception_comprehension",
                    "label": "Social Perception",
                    "onvoc_id": "ONVOC_0000503",
                    "original_id": "concept:ONVOC_0000503",
                },
                "mapping": {
                    "onvoc_id": "ONVOC_0000503",
                    "original_canonical_id": "concept:personally_familiar_faces",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_0000503",
                        "onvoc_label": "Social Perception",
                    },
                    "task_panel": {
                        "family_id": "tf_language_semantic",
                        "subfamily_id": "sf_speech_perception_comprehension",
                        "family_match_method": "aggressive_fuzzy_guarded",
                    },
                },
            },
            {
                "paper": {"id": "pmid:9999", "title": "Reading comprehension task"},
                "claim": {"id": "claim:2", "text": "reading comprehension task"},
                "target": {
                    "id": "task:subfamily:sf_lexical_access_orthography",
                    "label": "Reading Comprehension",
                    "onvoc_id": "ONVOC_1234567",
                },
                "mapping": {"onvoc_id": "ONVOC_1234567"},
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_1234567",
                        "onvoc_label": "Reading Comprehension",
                    },
                    "task_panel": {
                        "family_id": "tf_language_semantic",
                        "subfamily_id": "sf_lexical_access_orthography",
                        "family_match_method": "exact_alias",
                        "family_match_input_label": "lexical decision",
                    },
                },
            },
        ],
    )

    summary = build_social_perception_suspect_fold_audit_pack(
        package_dir=package_dir,
        output_dir=tmp_path / "audit_pack",
    )

    assert summary["suspect_rows_total"] == 1
    assert summary["heuristic_bucket_counts"]["high_conflict_social_not_speech"] == 1
    assert summary["family_match_method_counts"]["aggressive_fuzzy_guarded"] == 1

    rows = [
        json.loads(line)
        for line in (tmp_path / "audit_pack" / "suspect_fold_audit_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert (
        rows[0]["mapping_original_canonical_id"] == "concept:personally_familiar_faces"
    )
    assert rows[0]["source_label_candidates"][0] == "personally familiar faces"
    assert "face" in rows[0]["social_signal_terms"]
