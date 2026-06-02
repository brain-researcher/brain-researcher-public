"""Tool-ordering check functions for plan-time review."""

from __future__ import annotations

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

# Tool sets for ordering checks
_REGISTRATION_TOOLS = frozenset(
    {
        "coreg_register",
        "coreg_apply_xfm",
        "fsl_flirt",
        "fsl_fnirt",
        "ants_registration",
        "antsRegistration",
        "mri_robust_register",
        "spm_normalise",
        "spm_coreg",
    }
)

_ATLAS_TOOLS = frozenset(
    {
        "parcellation_fetch",
        "label_transfer",
        "dmri_parcellate_connectome",
        "nilearn_fetch_atlas",
        "extract_timeseries",
        "atlas_apply",
        "atlas_label",
    }
)

_SKULL_STRIP_TOOLS = frozenset(
    {
        "bet",
        "antsBrainExtraction",
        "hd_bet",
        "mri_synthstrip",
        "fsl_bet",
        "skull_strip",
    }
)

_GLM_TOOLS = frozenset(
    {
        "glm_fit",
        "glm_first_level",
        "spm_glm",
        "nilearn_first_level_model",
        "glm_contrasts",
        "first_level_model",
        "fsl_feat",
        "fsl_film_gls",
    }
)

_CONFOUND_TOOLS = frozenset(
    {
        "confound_regression",
        "regress_confounds",
        "nilearn_clean_img",
        "fsl_regfilt",
        "aroma_denoise",
        "fmriprep_confounds",
        "extract_confounds",
    }
)


def _tool_name(step: dict) -> str:
    return str(step.get("tool") or "").lower()


def registration_before_atlas_analysis(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Return a finding if any atlas step comes before any registration step."""
    steps = bundle.plan_steps
    first_reg_idx: int | None = None
    first_atlas_idx: int | None = None

    for idx, step in enumerate(steps):
        tool = _tool_name(step)
        if tool in _REGISTRATION_TOOLS and first_reg_idx is None:
            first_reg_idx = idx
        if tool in _ATLAS_TOOLS and first_atlas_idx is None:
            first_atlas_idx = idx

    if first_atlas_idx is None or first_reg_idx is None:
        return None

    if first_atlas_idx < first_reg_idx:
        atlas_step = steps[first_atlas_idx]
        return ReviewFinding(
            rule_id="REVIEW_REGISTRATION_ORDER",
            severity="error",
            message=(
                f"Atlas/parcellation step '{atlas_step.get('tool')}' (step {first_atlas_idx + 1}) "
                f"precedes registration step '{steps[first_reg_idx].get('tool')}' "
                f"(step {first_reg_idx + 1}); results will be in wrong space."
            ),
            suggested_fix="Move the registration step before any atlas/parcellation step.",
            step_id=atlas_step.get("step_id"),
        )
    return None


def skull_stripping_before_registration(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Return a finding if a registration step appears before skull-stripping."""
    steps = bundle.plan_steps
    first_reg_idx: int | None = None
    first_strip_idx: int | None = None

    for idx, step in enumerate(steps):
        tool = _tool_name(step)
        if tool in _REGISTRATION_TOOLS and first_reg_idx is None:
            first_reg_idx = idx
        if tool in _SKULL_STRIP_TOOLS and first_strip_idx is None:
            first_strip_idx = idx

    if first_reg_idx is None or first_strip_idx is None:
        return None

    if first_reg_idx < first_strip_idx:
        reg_step = steps[first_reg_idx]
        return ReviewFinding(
            rule_id="REVIEW_SKULL_STRIP_ORDER",
            severity="warn",
            message=(
                f"Registration step '{reg_step.get('tool')}' (step {first_reg_idx + 1}) "
                f"precedes skull-stripping step '{steps[first_strip_idx].get('tool')}' "
                f"(step {first_strip_idx + 1}); registering with skull may degrade accuracy."
            ),
            suggested_fix="Skull-strip (bet, antsBrainExtraction) before registration.",
            step_id=reg_step.get("step_id"),
        )
    return None


def confound_regression_before_glm(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Return a finding if a GLM step exists without a preceding confound regression step."""
    steps = bundle.plan_steps
    first_glm_idx: int | None = None
    first_confound_idx: int | None = None

    for idx, step in enumerate(steps):
        tool = _tool_name(step)
        if tool in _GLM_TOOLS and first_glm_idx is None:
            first_glm_idx = idx
        if tool in _CONFOUND_TOOLS and first_confound_idx is None:
            first_confound_idx = idx

    if first_glm_idx is None:
        return None

    # GLM exists, but no confound step at all — or confound comes after GLM
    if first_confound_idx is None or first_confound_idx > first_glm_idx:
        glm_step = steps[first_glm_idx]
        return ReviewFinding(
            rule_id="REVIEW_MISSING_CONFOUND_REGRESSION",
            severity="warn",
            message=(
                f"GLM step '{glm_step.get('tool')}' (step {first_glm_idx + 1}) "
                "found but no confound regression step precedes it."
            ),
            suggested_fix=(
                "Add a confound regression step (e.g. confound_regression, nilearn_clean_img) "
                "before GLM to remove motion and physiological noise."
            ),
            step_id=glm_step.get("step_id"),
        )
    return None
