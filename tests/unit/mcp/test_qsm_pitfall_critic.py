from __future__ import annotations

import pytest


@pytest.mark.unit
def test_qsm_candidate_filter_abstains_from_generic_fmri_tools():
    from brain_researcher.services.review.qsm_pitfall_critic import (
        filter_qsm_tool_candidates,
    )

    candidates = [
        {
            "name": "workflow_fmriprep_preprocessing",
            "description": "Single-subject fMRIPrep preprocessing workflow.",
            "modalities": ["fmri"],
        },
        {
            "name": "fsl_prepare_fieldmap",
            "description": "Prepare fieldmap for FEAT distortion correction.",
            "modalities": ["fmri"],
        },
    ]

    filtered, gate = filter_qsm_tool_candidates(
        query=(
            "QSM reconstruction from multi-echo GRE phase data with background "
            "field removal and dipole inversion"
        ),
        modality=["QSM", "GRE"],
        candidates=candidates,
    )

    assert filtered == []
    assert gate is not None
    assert gate["task_type"] == "qsm_reconstruction"
    assert gate["usable_guidance"] is False
    assert gate["should_advise"] is False
    assert gate["advice_mode"] == "abstain"
    assert set(gate["blocked_candidate_names"]) == {
        "workflow_fmriprep_preprocessing",
        "fsl_prepare_fieldmap",
    }


@pytest.mark.unit
def test_qsm_candidate_filter_keeps_qsm_specific_candidate():
    from brain_researcher.services.review.qsm_pitfall_critic import (
        filter_qsm_tool_candidates,
    )

    candidates = [
        {
            "name": "qsm_local_field_review",
            "description": "QSM local field, RESHARP, V-SHARP, and dipole inversion guidance.",
            "modalities": ["QSM"],
        },
        {
            "name": "workflow_mriqc",
            "description": "MRIQC quality report for fMRI/sMRI preprocessing.",
            "modalities": ["fmri", "smri"],
        },
    ]

    filtered, gate = filter_qsm_tool_candidates(
        query="QSM dipole inversion from local field",
        modality='["QSM", "GRE"]',
        candidates=candidates,
    )

    assert [item["name"] for item in filtered] == ["qsm_local_field_review"]
    assert gate is not None
    assert gate["usable_guidance"] is True
    assert gate["advice_mode"] == "audit_only"
    assert gate["hard_constraints"]
    assert gate["non_displacement_notice"]
    assert gate["qc_protocol"]
