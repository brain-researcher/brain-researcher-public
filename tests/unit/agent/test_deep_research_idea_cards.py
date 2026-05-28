from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.agent.deep_research_idea_cards import (
    ObjectCluster,
    _build_mechanism_title,
    _curated_supporting_paper_titles,
    build_deep_research_idea_cards,
    load_kggen_relation_rows,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_load_kggen_relation_rows_filters_generic_objects(tmp_path: Path):
    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper": {"id": "paper:1", "title": "Paper 1", "journal": "example.org"},
                "relations": [
                    {
                        "subject": "gaze position artifacts",
                        "predicate": "are corrected by",
                        "object": "local luminance",
                        "confidence": 0.81,
                        "claim_text": "gaze position artifacts are corrected by local luminance",
                        "evidence_quote": "gaze position artifacts are corrected by local luminance",
                    },
                    {
                        "subject": "unexpected switch",
                        "predicate": "triggers",
                        "object": "event",
                        "confidence": 0.81,
                        "claim_text": "unexpected switch triggers event",
                        "evidence_quote": "unexpected switch triggers event",
                    },
                ],
            }
        ],
    )

    rows = load_kggen_relation_rows(kggen_path)

    assert len(rows) == 1
    assert rows[0].object_label == "local luminance"


def test_load_kggen_relation_rows_preserves_balanced_parentheses(tmp_path: Path):
    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper": {"id": "paper:1", "title": "Paper 1", "journal": "example.org"},
                "relations": [
                    {
                        "subject": "emotion regulation",
                        "predicate": "occurs in",
                        "object": "Major Depressive Disorder (MDD)",
                        "confidence": 0.81,
                        "claim_text": "emotion regulation occurs in Major Depressive Disorder (MDD)",
                        "evidence_quote": "emotion regulation occurs in Major Depressive Disorder (MDD)",
                    }
                ],
            }
        ],
    )

    rows = load_kggen_relation_rows(kggen_path)

    assert len(rows) == 1
    assert rows[0].object_label == "Major Depressive Disorder (MDD)"


def test_build_deep_research_idea_cards_generates_ranked_cards(tmp_path: Path):
    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper": {"id": "paper:1", "title": "Paper 1", "journal": "example.org"},
                "relations": [
                    {
                        "subject": "gaze position artifacts",
                        "predicate": "are corrected by",
                        "object": "local luminance",
                        "confidence": 0.84,
                        "claim_text": "gaze position artifacts are corrected by local luminance",
                        "evidence_quote": "gaze position artifacts are corrected by local luminance",
                    },
                    {
                        "subject": "phasic dilations",
                        "predicate": "reflect",
                        "object": "surprise",
                        "confidence": 0.83,
                        "claim_text": "phasic dilations reflect surprise",
                        "evidence_quote": "phasic dilations reflect surprise",
                    },
                ],
            },
            {
                "paper": {"id": "paper:2", "title": "Paper 2", "journal": "example.org"},
                "relations": [
                    {
                        "subject": "foreshortening artifacts",
                        "predicate": "are reduced by",
                        "object": "local luminance",
                        "confidence": 0.82,
                        "claim_text": "foreshortening artifacts are reduced by local luminance",
                        "evidence_quote": "foreshortening artifacts are reduced by local luminance",
                    },
                    {
                        "subject": "pupil dilation",
                        "predicate": "signals",
                        "object": "surprise",
                        "confidence": 0.80,
                        "claim_text": "pupil dilation signals surprise",
                        "evidence_quote": "pupil dilation signals surprise",
                    },
                ],
            },
            {
                "paper": {"id": "paper:3", "title": "Paper 3", "journal": "pmc.ncbi.nlm.nih.gov"},
                "relations": [
                    {
                        "subject": "long run-lengths",
                        "predicate": "reduce",
                        "object": "baseline pupil size",
                        "confidence": 0.79,
                        "claim_text": "long run-lengths reduce baseline pupil size",
                        "evidence_quote": "long run-lengths reduce baseline pupil size",
                    },
                    {
                        "subject": "individual differences",
                        "predicate": "appear in",
                        "object": "baseline pupil size",
                        "confidence": 0.79,
                        "claim_text": "individual differences appear in baseline pupil size",
                        "evidence_quote": "individual differences appear in baseline pupil size",
                    },
                ],
            },
        ],
    )

    deep_research_result = {
        "status": "ok",
        "summary": "# Response streak confounds in pupillometry\n\nKey points omitted.",
        "documents": [
            {"title": "Paper 1", "url": "https://example.org/p1"},
            {"title": "Paper 2", "url": "https://example.org/p2"},
            {"title": "Paper 3", "url": "https://example.org/p3"},
        ],
        "raw": {},
        "metadata": {"interaction_id": "int-123"},
    }

    payload = build_deep_research_idea_cards(
        deep_research_result=deep_research_result,
        kggen_input=kggen_path,
        top_n=3,
        min_supporting_papers=2,
    )

    assert payload["ok"] is True
    assert payload["mode"] == "deep_research_idea_cards"
    assert payload["deep_research"]["interaction_id"] == "int-123"
    assert payload["summary"]["n_candidate_cards"] == 2

    titles = [card["title"] for card in payload["candidate_cards"]]
    assert "Model local luminance explicitly" in titles
    assert "Test surprise as a mechanistic mediator" in titles

    first_card = payload["candidate_cards"][0]
    assert first_card["deep_research_status"] == "ok"
    assert first_card["grounding_status"] == "grounded"
    assert first_card["wow_score"] > 0.0
    assert first_card["novelty_signals"]["controlled_ood_score"] > 0.0
    assert first_card["topology_subgraph"]["focus_node_id"].startswith("drn_")
    assert first_card["provenance"]["interaction_id"] == "int-123"
    assert len(first_card["provenance"]["supporting_paper_ids"]) >= 2
    subgraph = payload["ephemeral_weighted_subgraph"]
    assert subgraph["version"] == "deep-research-subgraph/v1"
    assert subgraph["novelty_objective"]["mode"] == "controlled_ood_search"
    assert subgraph["summary"]["node_count"] >= 4
    assert subgraph["summary"]["edge_count"] >= 3
    assert subgraph["summary"]["card_subgraph_count"] == payload["summary"]["n_candidate_cards"]


def test_build_deep_research_idea_cards_filters_query_echo_objects_and_streak_language(
    tmp_path: Path,
):
    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper": {"id": "paper:1", "title": "Paper 1", "journal": "example.org"},
                "relations": [
                    {
                        "subject": "Patients with MDD",
                        "predicate": "exhibit",
                        "object": "ATP levels",
                        "confidence": 0.84,
                        "claim_text": "Patients with MDD exhibit ATP levels",
                        "evidence_quote": "Patients with MDD exhibit ATP levels",
                    },
                    {
                        "subject": "emotion regulation",
                        "predicate": "occurs in",
                        "object": "Major Depressive Disorder (MDD)",
                        "confidence": 0.83,
                        "claim_text": "emotion regulation occurs in Major Depressive Disorder (MDD)",
                        "evidence_quote": "emotion regulation occurs in Major Depressive Disorder (MDD)",
                    },
                    {
                        "subject": "brain networks",
                        "predicate": "support",
                        "object": "emotion regulation",
                        "confidence": 0.82,
                        "claim_text": "brain networks support emotion regulation",
                        "evidence_quote": "brain networks support emotion regulation",
                    },
                    {
                        "subject": "brain cells",
                        "predicate": "depend on",
                        "object": "energy production",
                        "confidence": 0.81,
                        "claim_text": "brain cells depend on energy production",
                        "evidence_quote": "brain cells depend on energy production",
                    },
                ],
            },
            {
                "paper": {"id": "paper:2", "title": "Paper 2", "journal": "example.org"},
                "relations": [
                    {
                        "subject": "MDD cohorts",
                        "predicate": "show reduced",
                        "object": "ATP levels",
                        "confidence": 0.84,
                        "claim_text": "MDD cohorts show reduced ATP levels",
                        "evidence_quote": "MDD cohorts show reduced ATP levels",
                    },
                    {
                        "subject": "emotion regulation",
                        "predicate": "is relevant to",
                        "object": "Major Depressive Disorder (MDD)",
                        "confidence": 0.83,
                        "claim_text": "emotion regulation is relevant to Major Depressive Disorder (MDD)",
                        "evidence_quote": "emotion regulation is relevant to Major Depressive Disorder (MDD)",
                    },
                    {
                        "subject": "fronto-parietal networks",
                        "predicate": "enable",
                        "object": "emotion regulation",
                        "confidence": 0.82,
                        "claim_text": "fronto-parietal networks enable emotion regulation",
                        "evidence_quote": "fronto-parietal networks enable emotion regulation",
                    },
                    {
                        "subject": "mitochondria",
                        "predicate": "support",
                        "object": "energy production",
                        "confidence": 0.81,
                        "claim_text": "mitochondria support energy production",
                        "evidence_quote": "mitochondria support energy production",
                    },
                ],
            },
        ],
    )

    deep_research_result = {
        "status": "ok",
        "summary": "MDD bioenergetics and emotion-regulation networks.",
        "documents": [
            {"title": "Paper 1", "url": "https://example.org/p1"},
            {"title": "Paper 2", "url": "https://example.org/p2"},
        ],
        "raw": {},
    }

    query = (
        "Major depressive disorder study testing whether mitochondrial health "
        "influences emotion-regulation brain networks"
    )
    payload = build_deep_research_idea_cards(
        deep_research_result=deep_research_result,
        kggen_input=kggen_path,
        query=query,
        top_n=3,
        min_supporting_papers=2,
    )

    object_labels = [card["provenance"]["object_label"] for card in payload["candidate_cards"]]
    assert object_labels == ["ATP levels", "energy production"]
    assert [card["rank"] for card in payload["candidate_cards"]] == [1, 2]
    assert "ATP levels" in object_labels
    assert "energy production" in object_labels
    assert "Major Depressive Disorder (MDD)" not in object_labels
    assert "emotion regulation" not in object_labels
    assert (
        payload["candidate_cards"][0]["query_relevance_score"]
        > payload["candidate_cards"][1]["query_relevance_score"]
    )
    assert all("streak" not in card["title"].lower() for card in payload["candidate_cards"])
    assert all(
        "streak" not in card["hypothesis"].lower() for card in payload["candidate_cards"]
    )
    assert all(
        "streak" not in card["minimal_discriminating_test"].lower()
        for card in payload["candidate_cards"]
    )


def test_curated_supporting_paper_titles_filters_placeholders_and_fallbacks() -> None:
    cluster = ObjectCluster(
        object_label="energy production",
        paper_ids={"paper:1", "paper:2", "paper:3", "paper:4", "paper:5", "paper:6"},
        paper_titles={
            "paper:1": "node",
            "paper:2": "Deep research source 2 (sciencedaily.com)",
            "paper:3": "Mitochondrial Energy Transformation Capacity Influences Brain Activation",
            "paper:4": "Energy metabolism constrains prefrontal control",
            "paper:5": "url:2abac19504d492e1",
            "paper:6": "404: This page could not be found",
        },
    )

    titles = _curated_supporting_paper_titles(cluster)

    assert "node" not in titles
    assert "Deep research source 2 (sciencedaily.com)" not in titles
    assert "url:2abac19504d492e1" not in titles
    assert "404: This page could not be found" not in titles
    assert titles == [
        "Mitochondrial Energy Transformation Capacity Influences Brain Activation",
        "Energy metabolism constrains prefrontal control",
    ]


def test_build_mechanism_title_compresses_long_query_context() -> None:
    query = (
        "Major depressive disorder study testing whether mitochondrial health "
        "influences emotion-regulation brain networks"
    )

    title = _build_mechanism_title("energy production", query)

    assert title == "Test energy production: mitochondrial health -> emotion-regulation networks in MDD"
    assert len(title) <= 96


def test_build_deep_research_idea_cards_applies_query_relevance_floor_and_surfaces_titles(
    tmp_path: Path,
) -> None:
    kggen_path = tmp_path / "kggen.jsonl"
    _write_jsonl(
        kggen_path,
        [
            {
                "paper": {
                    "id": "paper:1",
                    "title": "Distinct Connectivity Signatures of Emotions Enhance Precision of Network Biomarkers in Mood Disorders",
                    "journal": "pnas.org",
                },
                "relations": [
                    {
                        "subject": "depressive symptoms",
                        "predicate": "are associated with",
                        "object": "lower mitochondrial protein content",
                        "confidence": 0.84,
                        "claim_text": "depressive symptoms are associated with lower mitochondrial protein content",
                        "evidence_quote": "depressive symptoms are associated with lower mitochondrial protein content",
                    },
                    {
                        "subject": "basic affective responses",
                        "predicate": "include",
                        "object": "pain",
                        "confidence": 0.81,
                        "claim_text": "basic affective responses include pain",
                        "evidence_quote": "basic affective responses include pain",
                    },
                ],
            },
            {
                "paper": {
                    "id": "paper:2",
                    "title": "Mitochondrial Energy Transformation Capacity Influences Brain Activation During Sensory, Affective, and Cognitive Tasks",
                    "journal": "nmn.com",
                },
                "relations": [
                    {
                        "subject": "chronic negative mood",
                        "predicate": "is associated with",
                        "object": "lower mitochondrial protein content",
                        "confidence": 0.83,
                        "claim_text": "chronic negative mood is associated with lower mitochondrial protein content",
                        "evidence_quote": "chronic negative mood is associated with lower mitochondrial protein content",
                    },
                    {
                        "subject": "basic affective responses",
                        "predicate": "includes",
                        "object": "pain",
                        "confidence": 0.8,
                        "claim_text": "basic affective responses includes pain",
                        "evidence_quote": "basic affective responses includes pain",
                    },
                ],
            },
        ],
    )

    payload = build_deep_research_idea_cards(
        deep_research_result={
            "status": "ok",
            "summary": "MDD bioenergetics and emotion-regulation networks.",
            "documents": [
                {"title": "Paper 1", "url": "https://example.org/p1"},
                {"title": "Paper 2", "url": "https://example.org/p2"},
            ],
            "raw": {},
        },
        kggen_input=kggen_path,
        query=(
            "Major depressive disorder study testing whether mitochondrial health "
            "influences emotion-regulation brain networks"
        ),
        top_n=5,
        min_supporting_papers=2,
    )

    object_labels = [card["provenance"]["object_label"] for card in payload["candidate_cards"]]
    assert object_labels == ["lower mitochondrial protein content"]
    assert payload["candidate_cards"][0]["supporting_paper_titles"] == [
        "Distinct Connectivity Signatures of Emotions Enhance Precision of Network Biomarkers in Mood Disorders",
        "Mitochondrial Energy Transformation Capacity Influences Brain Activation During Sensory, Affective, and Cognitive Tasks",
    ]
