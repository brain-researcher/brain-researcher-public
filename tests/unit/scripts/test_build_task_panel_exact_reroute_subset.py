from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_task_panel_exact_reroute_subset as reroute_subset


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_exact_reroute_subset_rewrites_target_and_manifest(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "source" / "manifest_task_panel.json"
    records = tmp_path / "lane_records.jsonl"
    output_dir = tmp_path / "reroute_subset"

    _write_json(
        source_manifest,
        {
            "run_id": "task-panel-v8",
            "source": "kggen_onvoc_postprocess",
            "query": "task-panel",
            "options": {"task_fold_mode": "subfamily"},
            "source_details": {"source_package": "v8"},
        },
    )
    _write_jsonl(
        records,
        [
            {
                "paper": {"id": "pmid:1"},
                "claim": {"id": "claim:1"},
                "run": {"run_id": "run:1"},
                "target": {
                    "id": "task:subfamily:sf_social_perception_attention",
                    "label": "Social Perception",
                    "onvoc_id": "ONVOC_0000503",
                },
                "mapping": {
                    "canonical_id": "task:subfamily:sf_social_perception_attention",
                    "onvoc_id": "ONVOC_0000503",
                },
                "normalization": {
                    "onvoc": {"onvoc_id": "ONVOC_0000503", "onvoc_label": "Social Perception"},
                    "task_panel": {
                        "task_id": "task:subfamily:sf_social_perception_attention",
                        "base_task_id": "task:onvoc:onvoc_0000503",
                        "family_id": "tf_social_cognition",
                        "subfamily_id": "sf_social_perception_attention",
                    },
                },
            }
        ],
    )

    assert (
        reroute_subset.main(
            [
            "--source-manifest",
            str(source_manifest),
                "--records-jsonl",
                str(records),
                "--output-dir",
                str(output_dir),
                "--new-target-id",
                "task:subfamily:sf_affect_induction",
                "--new-target-label",
                "Emotion Regulation",
                "--new-family-id",
                "tf_preference_affective",
            "--new-subfamily-id",
            "sf_affect_induction",
            "--new-onvoc-id",
            "ONVOC_0000462",
            "--new-onvoc-uri",
            "https://w3id.org/onvoc/ONVOC_0000462",
            "--new-original-id",
            "concept:ONVOC_0000462",
            ]
        )
        == 0
    )

    rewritten = [
        json.loads(line)
        for line in (output_dir / "task_panel_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert rewritten[0]["target"]["id"] == "task:subfamily:sf_affect_induction"
    assert rewritten[0]["target"]["label"] == "Emotion Regulation"
    assert rewritten[0]["normalization"]["task_panel"]["family_id"] == "tf_preference_affective"
    assert rewritten[0]["normalization"]["task_panel"]["subfamily_id"] == "sf_affect_induction"

    manifest = json.loads(
        (output_dir / "manifest_task_panel.json").read_text(encoding="utf-8")
    )
    assert manifest["counts"]["records_generated"] == 1
    assert manifest["source_details"]["promotion_strategy"] == (
        "kg_task_panel_ingest_then_exact_id_migration"
    )


def test_build_task_panel_exact_reroute_subset_can_clear_legacy_onvoc_fields(
    tmp_path: Path,
    capsys,
) -> None:
    source_manifest = tmp_path / "source" / "manifest_task_panel.json"
    records = tmp_path / "lane_records.jsonl"
    output_dir = tmp_path / "reroute_subset"

    _write_json(
        source_manifest,
        {
            "run_id": "task-panel-v8",
            "source": "kggen_onvoc_postprocess",
            "query": "task-panel",
            "options": {"task_fold_mode": "subfamily"},
            "source_details": {"source_package": "v8"},
        },
    )
    _write_jsonl(
        records,
        [
            {
                "paper": {"id": "pmid:2"},
                "claim": {"id": "claim:2"},
                "run": {"run_id": "run:2"},
                "target": {
                    "id": "task:subfamily:sf_social_perception_attention",
                    "label": "Social Perception",
                    "onvoc_id": "ONVOC_0000503",
                    "onvoc_uri": "https://w3id.org/onvoc/ONVOC_0000503",
                    "original_id": "concept:ONVOC_0000503",
                },
                "mapping": {
                    "canonical_id": "task:subfamily:sf_social_perception_attention",
                    "onvoc_id": "ONVOC_0000503",
                    "onvoc_uri": "https://w3id.org/onvoc/ONVOC_0000503",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_0000503",
                        "onvoc_uri": "https://w3id.org/onvoc/ONVOC_0000503",
                        "onvoc_label": "Social Perception",
                    },
                    "task_panel": {
                        "task_id": "task:subfamily:sf_social_perception_attention",
                        "base_task_id": "task:onvoc:onvoc_0000503",
                        "onvoc_id": "ONVOC_0000503",
                        "family_id": "tf_social_cognition",
                        "subfamily_id": "sf_social_perception_attention",
                    },
                },
            }
        ],
    )

    assert (
        reroute_subset.main(
            [
                "--source-manifest",
                str(source_manifest),
                "--records-jsonl",
                str(records),
                "--output-dir",
                str(output_dir),
                "--new-target-type",
                "Concept",
                "--new-target-id",
                "concept:ci_processing",
                "--new-target-label",
                "Discourse/Pragmatics",
                "--new-original-id",
                "concept:ci_processing",
            ]
        )
        == 0
    )

    rewritten = [
        json.loads(line)
        for line in (output_dir / "task_panel_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ][0]
    assert rewritten["target"]["type"] == "Concept"
    assert rewritten["target"]["id"] == "concept:ci_processing"
    assert rewritten["target"]["label"] == "Discourse/Pragmatics"
    assert rewritten["target"]["original_id"] == "concept:ci_processing"
    assert "onvoc_id" not in rewritten["target"]
    assert "onvoc_uri" not in rewritten["target"]
    assert "onvoc_id" not in rewritten["mapping"]
    assert "onvoc_uri" not in rewritten["mapping"]
    assert "onvoc" not in rewritten["normalization"]
    assert "task_panel" not in rewritten["normalization"]

    report = json.loads(
        (output_dir / "reroute_subset_report.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (output_dir / "manifest_task_panel.json").read_text(encoding="utf-8")
    )
    assert report["promotion_strategy"] == "exact_id_migration_only"
    assert report["task_panel_ingest_recommended"] is False
    assert manifest["source_details"]["promotion_strategy"] == (
        "exact_id_migration_only"
    )
    captured = capsys.readouterr()
    assert "Concept reroute subset built for concept:ci_processing" in captured.err
    assert "Skip ordinary kg_task_panel ingest" in captured.err
    assert "--exact-prefix concept:" in captured.err


def test_build_task_panel_exact_reroute_subset_rejects_task_without_family_fields(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "source" / "manifest_task_panel.json"
    records = tmp_path / "lane_records.jsonl"
    output_dir = tmp_path / "reroute_subset"

    _write_json(
        source_manifest,
        {"run_id": "task-panel-v8", "source": "kggen_onvoc_postprocess"},
    )
    _write_jsonl(
        records,
        [
            {
                "paper": {"id": "pmid:3"},
                "claim": {"id": "claim:3"},
                "run": {"run_id": "run:3"},
                "target": {"id": "task:onvoc:onvoc_0000001", "label": "Legacy"},
                "mapping": {"canonical_id": "task:onvoc:onvoc_0000001"},
            }
        ],
    )

    try:
        reroute_subset.main(
            [
                "--source-manifest",
                str(source_manifest),
                "--records-jsonl",
                str(records),
                "--output-dir",
                str(output_dir),
                "--new-target-id",
                "task:subfamily:sf_affect_induction",
                "--new-target-label",
                "Emotion Regulation",
            ]
        )
    except SystemExit as exc:
        assert "Task reroutes require --new-family-id and --new-subfamily-id" in str(
            exc
        )
    else:
        raise AssertionError("Expected Task reroute to require family/subfamily ids")
