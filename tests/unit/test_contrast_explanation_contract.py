"""Cross-consumer contract for descriptive fMRI contrast summaries."""

import nibabel as nib
import numpy as np
import pytest

from brain_researcher.services.agent.explanation_generator import (
    ExpertiseLevel,
    ExplanationContext,
    ExplanationGenerator,
)
from brain_researcher.services.agent.language_templates import ExplanationLevel
from brain_researcher.services.tools.fmri_tools import ContrastAnalysisTool


def test_opposite_sign_components_stay_separate_and_stably_ordered(tmp_path):
    data = np.zeros((6, 6, 6), dtype=float)
    data[1:3, 1:3, 1:3] = 5.0
    data[3:5, 1:3, 1:3] = -6.0
    z_map = tmp_path / "opposite_signs_zmap.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), z_map)

    result = ContrastAnalysisTool().run(
        z_map_path=str(z_map), contrast_name="opposite_signs"
    )

    assert result["status"] == "success"
    clusters = result["data"]["suprathreshold_clusters"]
    assert [cluster["index"] for cluster in clusters] == [1, 2]
    assert [cluster["sign"] for cluster in clusters] == ["negative", "positive"]
    assert [cluster["cluster_size"] for cluster in clusters] == [8, 8]
    assert [cluster["peak_z"] for cluster in clusters] == [-6.0, 5.0]
    assert result["metadata"]["cluster_connectivity"] == 26
    assert result["metadata"]["opposite_signs_connected"] is False


@pytest.mark.parametrize(
    "explanation_level",
    [
        ExplanationLevel.TECHNICAL,
        ExplanationLevel.LAYMAN,
        ExplanationLevel.STRUCTURED,
        ExplanationLevel.SUMMARY,
    ],
)
def test_public_explanation_modes_keep_contrast_components_descriptive(
    tmp_path, explanation_level
):
    data = np.zeros((8, 8, 8), dtype=float)
    data[2:4, 2:4, 2:4] = 5.0
    data[2, 2, 2] = 7.0
    z_map = tmp_path / "contrast_zmap.nii.gz"
    nib.save(nib.Nifti1Image(data, np.eye(4)), z_map)

    tool_result = ContrastAnalysisTool().run(
        z_map_path=str(z_map), contrast_name="task_vs_baseline"
    )
    assert tool_result["status"] == "success"
    analysis_result = {
        **tool_result["data"],
        "metadata": tool_result["metadata"],
        # Deliberately include inferential-looking fields. The descriptive
        # component contract must take precedence whenever the key is present.
        "analysis_type": "clinical task GLM",
        "method": "GLM",
        "n_subjects": 120,
        "significant_regions": [
            {"name": "motor cortex", "coordinates": [1, 2, 3], "peak_value": 9.0}
        ],
        "significant_clusters": [
            {
                "region": "motor cortex",
                "p_value": 0.0001,
                "correction_method": "FWE",
            }
        ],
        "statistics": {
            "p_value": 0.0001,
            "effect_size": 1.2,
            "correction_method": "FWE",
        },
        "preprocessing": {"software": "fMRIPrep", "steps": ["smoothing"]},
        "statistical_model": {"type": "GLM", "contrasts": ["task vs baseline"]},
    }

    generator = ExplanationGenerator()
    result = generator.generate_explanation(
        analysis_result,
        ExplanationContext(
            expertise_level=ExpertiseLevel.EXPERT,
            preferred_level=explanation_level,
            include_statistics=True,
            include_implications=True,
            include_methodology=True,
            include_visual_descriptions=True,
            visual_context={"brain_maps": ["contrast_zmap.nii.gz"]},
            include_limitations=True,
            include_recommendations=True,
            use_analogies=True,
            include_advanced_statistics=True,
            domain_focus=["clinical", "cognitive", "behavioral"],
        ),
    )

    assert result.explanation_level is explanation_level
    assert result.confidence_score == 0.0
    assert result.metadata["descriptive_only"] is True
    assert result.metadata["confidence_applicable"] is False
    assert result.metadata["key_findings_count"] == 0
    assert result.citations == []

    lowered = result.text.lower()
    assert "descriptive" in lowered
    assert "component" in lowered
    assert "|z| >= 3.0" in result.text
    assert "5 voxels" in lowered
    assert "no inferential test was performed" in lowered

    for unsupported_phrase in (
        "significant",
        "activation",
        "p <",
        "fwe",
        "high confidence",
        "moderate confidence",
        "low confidence",
        "strong, robust, and reliable",
        "behavior",
        "clinical",
        "diagnosis",
        "treatment",
        "application",
        "working memory",
        "replication",
        "follow-up",
    ):
        assert unsupported_phrase not in lowered

    if explanation_level is ExplanationLevel.STRUCTURED:
        assert isinstance(result.structured, dict)
        structured_values = " ".join(result.structured.values()).lower()
        assert "not applicable to this descriptive inventory" in structured_values
        for unsupported_phrase in ("significant", "activation", "behavior", "clinical"):
            assert unsupported_phrase not in structured_values
