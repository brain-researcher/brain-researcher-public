from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.neurokg.etl.evaluation.gabriel_onvoc_map import (
    map_kggen_to_onvoc,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _record(*, paper_id: str, target_id: str, target_label: str) -> dict:
    return {
        "run": {
            "run_id": f"run-{paper_id}",
            "tool": "kggen",
            "model": "gemini-2.5-flash",
            "prompt_hash": "h1",
            "template_hash": "h2",
            "raw_response_path": "/tmp/kggen.json",
            "loader_version": "kggen",
            "timestamp": "2026-02-25T00:00:00Z",
        },
        "paper": {
            "id": paper_id,
            "title": "Test paper",
        },
        "target": {
            "type": "Concept",
            "id": target_id,
            "label": target_label,
        },
        "mapping": {
            "canonical_id": target_id,
            "mapping_type": "related",
            "mapping_confidence": 0.6,
        },
        "claim": {
            "id": f"claim:{paper_id}",
            "text": "Test relation.",
            "polarity": "supports",
            "claim_strength": 0.6,
        },
        "evidence": {
            "quote": "Test relation.",
            "section": "abstract",
            "has_statistical_detail": False,
            "locatable": True,
            "direct_quote": True,
        },
        "signals": {
            "mention_frequency": 1,
            "max_frequency": 5,
            "semantic_similarity": 0.6,
            "ontology_match": False,
            "context_overlap": 0.4,
            "modal_density": 0.5,
            "statistical_density": 0.2,
            "assertive_verb_ratio": 0.5,
            "sample_size_adequacy": 0.4,
            "roi_definition_clear": False,
        },
    }


def _write_onvoc_assets(tmp_path: Path) -> tuple[Path, Path]:
    crosswalk_path = tmp_path / "onvoc_crosswalk.yaml"
    crosswalk_path.write_text(
        json.dumps(
            {
                "tasks": {
                    "task:go-no-go": {
                        "primary": "ONVOC_9990003",
                        "labels": ["Response Inhibition Task"],
                    }
                },
                "concepts": {
                    "concept:attention": {
                        "primary": "ONVOC_9990001",
                        "labels": ["Attention"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    tree_path = tmp_path / "onvoc_tree.yaml"
    tree_path.write_text(
        json.dumps(
            {
                "tree": [
                    {
                        "id": "ONVOC_9990001",
                        "uri": "https://w3id.org/onvoc/ONVOC_9990001",
                        "label": "Attention",
                        "level": 3,
                    },
                    {
                        "id": "ONVOC_9990002",
                        "uri": "https://w3id.org/onvoc/ONVOC_9990002",
                        "label": "Frontoparietal Network",
                        "level": 3,
                    },
                    {
                        "id": "ONVOC_9990003",
                        "uri": "https://w3id.org/onvoc/ONVOC_9990003",
                        "label": "Response Inhibition",
                        "level": 3,
                    },
                    {
                        "id": "ONVOC_0000207",
                        "uri": "https://w3id.org/onvoc/ONVOC_0000207",
                        "label": "Depressive Disorder",
                        "level": 3,
                    },
                    {
                        "id": "ONVOC_0000211",
                        "uri": "https://w3id.org/onvoc/ONVOC_0000211",
                        "label": "Post-Traumatic Stress Disorder",
                        "level": 3,
                    },
                    {
                        "id": "ONVOC_0000210",
                        "uri": "https://w3id.org/onvoc/ONVOC_0000210",
                        "label": "Attention-Deficit Hyperactivity Disorder",
                        "level": 3,
                    },
                    {
                        "id": "ONVOC_0000694",
                        "uri": "https://w3id.org/onvoc/ONVOC_0000694",
                        "label": "Anxiety",
                        "level": 3,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return crosswalk_path, tree_path


def test_map_kggen_to_onvoc_emits_edges_and_review_artifacts(tmp_path: Path) -> None:
    crosswalk_path, tree_path = _write_onvoc_assets(tmp_path)

    kggen_path = tmp_path / "kggen_adapted.jsonl"
    _write_jsonl(
        kggen_path,
        [
            _record(
                paper_id="pmid:810001",
                target_id="concept:attention",
                target_label="Attention",
            ),
            _record(
                paper_id="pmid:810002",
                target_id="concept:frontoparietal_network",
                target_label="Frontoparietal Network",
            ),
            _record(
                paper_id="pmid:810003",
                target_id="concept:unknown_construct",
                target_label="Unknown Construct",
            ),
        ],
    )

    output_dir = tmp_path / "onvoc_eval"
    report = map_kggen_to_onvoc(
        kggen_input=kggen_path,
        output_dir=output_dir,
        min_score=0.82,
        same_as_threshold=0.97,
        normalize_targets=True,
        crosswalk_path=crosswalk_path,
        tree_path=tree_path,
    )

    assert report["schema_version"] == "gabriel-onvoc-map-v1"
    assert report["summary"]["maps_to_edges"] == 2
    assert report["summary"]["same_as_edges"] == 1
    assert report["summary"]["review_items"] == 1
    assert report["summary"]["normalized_records"] == 3
    assert "candidate_stats" in report
    assert "embedding" in report

    assert Path(report["artifacts"]["report_path"]).exists()
    assert Path(report["artifacts"]["mapping_rows_path"]).exists()
    assert Path(report["artifacts"]["review_queue_path"]).exists()
    assert Path(report["artifacts"]["maps_to_edges_path"]).exists()
    assert Path(report["artifacts"]["same_as_edges_path"]).exists()
    assert Path(report["artifacts"]["normalized_records_path"]).exists()

    maps_to_rows = (
        Path(report["artifacts"]["maps_to_edges_path"]).read_text(encoding="utf-8").splitlines()
    )
    same_as_rows = (
        Path(report["artifacts"]["same_as_edges_path"]).read_text(encoding="utf-8").splitlines()
    )
    assert len(maps_to_rows) == 2
    assert len(same_as_rows) == 1

    normalized_rows = [
        json.loads(line)
        for line in Path(report["artifacts"]["normalized_records_path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(normalized_rows) == 3
    assert normalized_rows[0]["mapping"]["canonical_id"] == "concept:ONVOC_9990001"
    assert normalized_rows[1]["mapping"]["canonical_id"] == "concept:ONVOC_9990002"
    assert normalized_rows[2]["mapping"]["canonical_id"] == "concept:unknown_construct"


def test_map_kggen_to_onvoc_respects_min_score_threshold(tmp_path: Path) -> None:
    crosswalk_path, tree_path = _write_onvoc_assets(tmp_path)

    kggen_path = tmp_path / "kggen_low.jsonl"
    _write_jsonl(
        kggen_path,
        [
            _record(
                paper_id="pmid:820001",
                target_id="concept:frontoparietal_network",
                target_label="Frontoparietal Network",
            )
        ],
    )

    report = map_kggen_to_onvoc(
        kggen_input=kggen_path,
        output_dir=tmp_path / "onvoc_eval",
        min_score=0.95,
        same_as_threshold=0.97,
        normalize_targets=False,
        crosswalk_path=crosswalk_path,
        tree_path=tree_path,
    )

    assert report["summary"]["maps_to_edges"] == 0
    assert report["summary"]["same_as_edges"] == 0
    assert report["summary"]["review_items"] == 1


def test_map_kggen_to_onvoc_maps_task_family_from_concept_label(tmp_path: Path) -> None:
    crosswalk_path, tree_path = _write_onvoc_assets(tmp_path)

    kggen_path = tmp_path / "kggen_task_family.jsonl"
    _write_jsonl(
        kggen_path,
        [
            _record(
                paper_id="paper:10_1007_s00426_021_01479_5",
                target_id="concept:orthogonalized_go_nogo_task",
                target_label="orthogonalized go/nogo task",
            )
        ],
    )

    report = map_kggen_to_onvoc(
        kggen_input=kggen_path,
        output_dir=tmp_path / "onvoc_eval",
        min_score=0.82,
        same_as_threshold=0.97,
        normalize_targets=True,
        crosswalk_path=crosswalk_path,
        tree_path=tree_path,
    )

    assert report["summary"]["maps_to_edges"] == 1
    assert report["summary"]["same_as_edges"] == 0
    assert report["method_counts"].get("crosswalk_task_family", 0) == 1

    edges = [
        json.loads(line)
        for line in Path(report["artifacts"]["maps_to_edges_path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(edges) == 1
    assert edges[0]["target_id"] == "concept:ONVOC_9990003"


def test_map_kggen_to_onvoc_generates_candidate_for_fronto_parietal_variant(
    tmp_path: Path,
) -> None:
    crosswalk_path, tree_path = _write_onvoc_assets(tmp_path)

    kggen_path = tmp_path / "kggen_fronto_parietal.jsonl"
    _write_jsonl(
        kggen_path,
        [
            _record(
                paper_id="pmid:40000002",
                target_id="concept:fronto_parietal_control_regions",
                target_label="fronto-parietal control regions",
            )
        ],
    )

    report = map_kggen_to_onvoc(
        kggen_input=kggen_path,
        output_dir=tmp_path / "onvoc_eval",
        min_score=0.82,
        same_as_threshold=0.97,
        candidate_top_k=20,
        embedding_enabled=False,
        normalize_targets=True,
        crosswalk_path=crosswalk_path,
        tree_path=tree_path,
    )

    rows = [
        json.loads(line)
        for line in Path(report["artifacts"]["mapping_rows_path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["candidate_count_lexical"] >= 1
    assert rows[0]["reason"] != "no_candidate_after_lexical"


def test_map_kggen_to_onvoc_maps_disease_aliases(tmp_path: Path) -> None:
    crosswalk_path, tree_path = _write_onvoc_assets(tmp_path)

    kggen_path = tmp_path / "kggen_disease_aliases.jsonl"
    _write_jsonl(
        kggen_path,
        [
            _record(
                paper_id="paper:1",
                target_id="concept:difficult_to_treat_mdd",
                target_label="difficult-to-treat major depressive disorder (mdd)",
            ),
            _record(
                paper_id="paper:2",
                target_id="concept:ptsd_afflicted_youth",
                target_label="ptsd-afflicted youth",
            ),
            _record(
                paper_id="paper:3",
                target_id="concept:medication_naive_adhd_children",
                target_label="medication-naive adhd children",
            ),
            _record(
                paper_id="paper:4",
                target_id="concept:high_social_anxiety",
                target_label="high social anxiety",
            ),
        ],
    )

    report = map_kggen_to_onvoc(
        kggen_input=kggen_path,
        output_dir=tmp_path / "onvoc_eval",
        min_score=0.82,
        same_as_threshold=0.97,
        normalize_targets=True,
        crosswalk_path=crosswalk_path,
        tree_path=tree_path,
    )

    assert report["summary"]["maps_to_edges"] == 4
    assert report["method_counts"].get("crosswalk_disease_alias", 0) >= 4

    edges = [
        json.loads(line)
        for line in Path(report["artifacts"]["maps_to_edges_path"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    targets = {edge["source_id"]: edge["target_id"] for edge in edges}
    assert targets["concept:difficult_to_treat_mdd"] == "concept:ONVOC_0000207"
    assert targets["concept:ptsd_afflicted_youth"] == "concept:ONVOC_0000211"
    assert targets["concept:medication_naive_adhd_children"] == "concept:ONVOC_0000210"
    assert targets["concept:high_social_anxiety"] == "concept:ONVOC_0000694"
