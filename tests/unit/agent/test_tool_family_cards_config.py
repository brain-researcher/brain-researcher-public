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
