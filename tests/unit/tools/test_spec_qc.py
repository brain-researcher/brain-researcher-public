from __future__ import annotations

from brain_researcher.services.tools.ants_tool import ANTsRegistrationTool
from brain_researcher.services.tools.fsl_bet_tool import TOOL_SPEC as FSL_BET_SPEC
from brain_researcher.services.tools.fsl_flirt_tool import FSLFLIRTTool
from brain_researcher.services.tools.fsl_fnirt_tool import TOOL_SPEC as FSL_FNIRT_SPEC
from brain_researcher.services.tools.fsl_bet_tool import FSLBETTool
from brain_researcher.services.tools.mne_ica_tool import TOOL_SPEC as MNE_ICA_SPEC
from brain_researcher.services.tools.mne_preprocessing_tool import (
    TOOL_SPEC as MNE_PREPROCESSING_SPEC,
)
from brain_researcher.services.tools.segmentation_tool import SegmentationTool
from brain_researcher.services.tools.spec import spec_from_tool
from brain_researcher.services.tools.xcpd_tool import TOOL_SPEC as XCPD_SPEC


def test_spec_from_tool_preserves_qc_spec():
    spec = spec_from_tool(FSLBETTool())

    assert spec is not None
    assert spec.qc_spec is not None
    assert spec.qc_spec.artifact_output_keys == ["qc_png"]
    assert "over_strip" in spec.qc_spec.failure_modes
    assert spec.qc_spec.render_contract is not None
    assert spec.qc_spec.render_contract.kind == "mask_overlay"
    assert spec.qc_spec.prechecks is not None
    assert spec.qc_spec.prechecks.required_outputs["mask"] == "mask_missing"


def test_runtime_wrapper_toolspec_names_use_canonical_public_ids():
    assert FSL_BET_SPEC.name == "fsl_bet"
    assert FSL_BET_SPEC.niwrap_id == "fsl.bet.run"
    assert FSL_FNIRT_SPEC.name == "fsl_fnirt"
    assert MNE_ICA_SPEC.name == "mne_ica"
    assert MNE_PREPROCESSING_SPEC.name == "mne_preprocessing"
    assert XCPD_SPEC.name == "xcpd_postprocessing"

    for spec in (
        FSL_BET_SPEC,
        FSL_FNIRT_SPEC,
        MNE_ICA_SPEC,
        MNE_PREPROCESSING_SPEC,
        XCPD_SPEC,
    ):
        assert ".run" not in spec.name


def test_registration_and_segmentation_tools_expose_qc_spec():
    flirt_spec = spec_from_tool(FSLFLIRTTool())
    ants_spec = spec_from_tool(ANTsRegistrationTool())
    segmentation_spec = spec_from_tool(SegmentationTool())

    assert flirt_spec is not None
    assert flirt_spec.qc_spec is not None
    assert flirt_spec.qc_spec.render_contract is not None
    assert flirt_spec.qc_spec.render_contract.kind == "checkerboard"
    assert flirt_spec.qc_spec.prechecks is not None
    assert flirt_spec.qc_spec.prechecks.required_outputs["registered_image"] == "output_missing"

    assert ants_spec is not None
    assert ants_spec.qc_spec is not None
    assert ants_spec.qc_spec.render_contract is not None
    assert ants_spec.qc_spec.render_contract.kind == "checkerboard"
    assert ants_spec.qc_spec.prechecks is not None
    assert ants_spec.qc_spec.prechecks.required_outputs["warped_image"] == "output_missing"

    assert segmentation_spec is not None
    assert segmentation_spec.qc_spec is not None
    assert segmentation_spec.qc_spec.render_contract is not None
    assert segmentation_spec.qc_spec.render_contract.kind == "label_overlay"
    assert segmentation_spec.qc_spec.prechecks is not None
    assert segmentation_spec.qc_spec.prechecks.required_outputs["segmentation"] == "output_missing"
