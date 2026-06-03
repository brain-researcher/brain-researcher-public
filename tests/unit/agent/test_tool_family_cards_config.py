from __future__ import annotations

from pathlib import Path

import yaml


def _family_cards() -> list[dict]:
    root = Path(__file__).resolve().parents[3]
    path = root / "configs" / "catalog" / "tool_family_cards.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    return list(data.get("family_cards") or [])


def test_family_card_leaf_families_present_for_harbor_ab():
    cards = {card["id"]: card for card in _family_cards()}

    assert "motion_correction" in cards
    assert cards["motion_correction"]["canonical_entrypoints"] == [
        "fmriprep_preprocessing",
        "motion_quantification",
    ]

    assert "preprocessing_denoising" in cards
    assert cards["preprocessing_denoising"]["canonical_entrypoints"] == [
        "fsl_fix",
        "fsl_melodic",
        "workflow_fmriprep_preprocessing",
    ]

    assert "searchlight_decoding" in cards
    assert cards["searchlight_decoding"]["canonical_entrypoints"][0] == (
        "searchlight_analysis"
    )

    assert "model_selection" in cards
    assert cards["model_selection"]["canonical_entrypoints"] == [
        "ml_cross_validation",
        "cross_validation",
        "validation_metrics",
        "decoding_classifier",
        "mvpa",
        "temporal_decoding",
    ]

    assert "statistical_correction" in cards
    assert cards["statistical_correction"]["canonical_entrypoints"] == [
        "multiple_comparison_correction"
    ]

    assert "kg_lookup" in cards
    assert cards["kg_lookup"]["canonical_entrypoints"][0] == "br_kg.search_nodes"

    assert "kg_construction" in cards
    assert cards["kg_construction"]["canonical_entrypoints"][0] == "graph_query"

    assert "electrophysiology_connectivity" in cards
    assert cards["electrophysiology_connectivity"]["canonical_entrypoints"] == [
        "mne_connectivity",
        "connectivity_measures",
    ]

    assert "brain_simulation" in cards
    assert cards["brain_simulation"]["canonical_entrypoints"][0] == "brain_simulation"

    assert "cortical_reconstruction" in cards
    assert cards["cortical_reconstruction"]["canonical_entrypoints"][0] == (
        "freesurfer_recon_all"
    )

    assert "surface_processing" in cards
    assert cards["surface_processing"]["canonical_entrypoints"][0] == (
        "surface_projection"
    )

    assert "graph_theory" in cards
    assert cards["graph_theory"]["canonical_entrypoints"][0] == (
        "workflow_dwi_connectome"
    )


def test_family_cards_narrow_overbroad_cards_for_specific_queries():
    cards = {card["id"]: card for card in _family_cards()}

    decoding_tags = " ".join(cards["decoding"]["tags"]).lower()
    assert "searchlight" not in decoding_tags

    morphometry_text = " ".join(
        [
            cards["morphometry"]["summary"],
            *cards["morphometry"]["tags"],
            *cards["morphometry"]["when_to_use"],
        ]
    ).lower()
    assert "brain age" not in morphometry_text

    realtime_text = " ".join(
        [
            cards["realtime"]["summary"],
            *cards["realtime"]["tags"],
            *cards["realtime"]["when_to_use"],
        ]
    ).lower()
    assert "motion correction" not in realtime_text

    visualization_text = " ".join(
        [
            cards["visualization"]["summary"],
            *cards["visualization"]["tags"],
            *cards["visualization"]["when_to_use"],
        ]
    ).lower()
    assert "glass brain" in visualization_text

    kg_lookup_text = " ".join(cards["kg_lookup"]["tags"]).lower()
    assert "graph metrics" not in kg_lookup_text

    graph_theory_text = " ".join(cards["graph_theory"]["tags"]).lower()
    assert "knowledge graph" not in graph_theory_text

    structural_segmentation_text = " ".join(
        [
            cards["structural_segmentation"]["summary"],
            *cards["structural_segmentation"]["tags"],
            *cards["structural_segmentation"]["when_to_use"],
        ]
    ).lower()
    assert "recon-all" not in structural_segmentation_text
