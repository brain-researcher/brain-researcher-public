"""Modality/space compatibility check functions for plan-time review."""

from __future__ import annotations

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_EEG_MEG_MODALITIES = frozenset({"eeg", "meg", "ieeg"})
_VOLUMETRIC_MNI_SPACES = frozenset(
    {"MNI152", "MNI152NLin2009cAsym", "MNI152NLin6Asym", "MNI"}
)
_DWI_TOOLS = frozenset(
    {
        "mrtrix_tckgen",
        "mrtrix_tcksift",
        "mrtrix_tckgen2",
        "dsi_studio_tracking",
        "fsl_dtifit",
        "ants_dti",
        "dipy_tracking",
        "dmri_tractography",
        "dmri_parcellate_connectome",
        "mrtrix_dwi2fod",
        "mrtrix_ss3t_csd",
        "tckgen",
        "tcksift",
        "dtifit",
    }
)
_BOLD_MODALITIES = frozenset(
    {"bold", "fmri", "func", "functional", "resting_state", "task_fmri"}
)


def atlas_modality_compatible(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Return a finding if EEG/MEG modality is paired with a volumetric MNI space/atlas."""
    modalities = {m.lower() for m in bundle.declared_modalities}
    spaces = set(bundle.declared_spaces)

    has_eeg_meg = bool(modalities & {m.lower() for m in _EEG_MEG_MODALITIES})
    has_volumetric_mni = bool(spaces & _VOLUMETRIC_MNI_SPACES)

    if has_eeg_meg and has_volumetric_mni:
        return ReviewFinding(
            rule_id="REVIEW_MODALITY_MISMATCH",
            severity="error",
            message=(
                f"Modalities {sorted(modalities & {m.lower() for m in _EEG_MEG_MODALITIES})} "
                f"combined with volumetric MNI space/atlas {sorted(spaces & _VOLUMETRIC_MNI_SPACES)} "
                "— modality/space mismatch."
            ),
            suggested_fix=(
                "Use a surface-based or EEG-compatible atlas (e.g. fsaverage) "
                "or source imaging in MNI space."
            ),
        )
    return None


def dwi_tool_on_bold_data(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Return a finding if DWI-specific tools appear with BOLD/fMRI declared modality."""
    modalities = {m.lower() for m in bundle.declared_modalities}
    tools_lower = {str(s.get("tool") or "").lower() for s in bundle.plan_steps}

    has_bold = bool(modalities & _BOLD_MODALITIES)
    has_dwi_tool = bool(tools_lower & {t.lower() for t in _DWI_TOOLS})

    if has_bold and has_dwi_tool:
        offending = sorted(tools_lower & {t.lower() for t in _DWI_TOOLS})
        return ReviewFinding(
            rule_id="REVIEW_DWI_TOOL_ON_BOLD",
            severity="error",
            message=(f"DWI tool(s) {offending} declared alongside BOLD/fMRI modality."),
            suggested_fix="Separate DWI and fMRI pipelines; do not mix tractography steps with BOLD GLM.",
        )
    return None


def mixed_mni_versions(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Return a finding if both MNI2009c and MNI6 appear in the same plan."""
    spaces = set(bundle.declared_spaces)
    # Also scan step params for space declarations
    for step in bundle.plan_steps:
        for key in ("space", "target_space", "atlas_space", "output_space"):
            val = step.get("params", {}).get(key)
            if isinstance(val, str) and val:
                spaces.add(val)

    has_2009c = any("2009" in s or "NLin2009" in s for s in spaces)
    has_6thgen = any("NLin6" in s or "6Asym" in s for s in spaces)

    if has_2009c and has_6thgen:
        return ReviewFinding(
            rule_id="REVIEW_MIXED_MNI_VERSIONS",
            severity="error",
            message="Both MNI152NLin2009cAsym and MNI152NLin6Asym detected in the same plan.",
            suggested_fix=(
                "Use MNI152NLin2009cAsym throughout (fMRIPrep default). "
                "MNI152NLin6Asym is the FSL standard — choose one consistently."
            ),
        )
    return None
