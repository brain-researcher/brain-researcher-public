"""Cross-step assumption consistency checks for plan-time review.

These checks detect contradictions *between* pipeline steps — something
single-step or single-artifact checks cannot see.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

# ---------------------------------------------------------------------------
# Tool sets
# ---------------------------------------------------------------------------

_BANDPASS_TOOLS = frozenset(
    {
        "nilearn_clean_img",
        "nilearn_bandpass",
        "xcpd",
        "xcpd_denoise",
        "butterworth_filter",
        "bandpass_filter",
        "fsl_regfilt",
        "nilearn_preprocessing",
        "nilearn_signal_clean",
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
        "fitlins",
        "statsmodels_glm",
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

_PREPROCESSING_TOOLS = frozenset(
    {
        "fmriprep",
        "nilearn_preprocessing",
        "xcpd",
        "xcpd_denoise",
        "nilearn_clean_img",
        "nilearn_signal_clean",
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
        "atlas_parcellate",
        "parcellate",
        "nilearn_masker",
        "extract_roi",
    }
)

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

# MNI space normalization — treat these as equivalent for matching purposes
_MNI_ALIASES: dict[str, str] = {
    "mni152nlin2009casym": "MNI152NLin2009cAsym",
    "mni2009c": "MNI152NLin2009cAsym",
    "mni152nlin6asym": "MNI152NLin6Asym",
    "mni6": "MNI152NLin6Asym",
    "mni152": "MNI152",
    "mni": "MNI152",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_name(step: dict) -> str:
    return str(step.get("tool") or "").lower()


def _get_param(step: dict, *keys: str) -> Any:
    """Extract first non-None param value from step, trying multiple keys."""
    params = step.get("params") or {}
    if not isinstance(params, dict):
        return None
    for k in keys:
        v = params.get(k)
        if v is not None:
            return v
    return None


def _normalize_space(raw: Any) -> str | None:
    """Normalize a space name to canonical form."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    lowered = raw.strip().lower()
    return _MNI_ALIASES.get(lowered, raw.strip())


def _extract_spaces(step: dict, *keys: str) -> set[str]:
    """Extract and normalize space values from step params."""
    spaces: set[str] = set()
    for key in keys:
        val = _get_param(step, key)
        if isinstance(val, str) and val.strip():
            normed = _normalize_space(val)
            if normed:
                spaces.add(normed)
        elif isinstance(val, list):
            for v in val:
                normed = _normalize_space(v)
                if normed:
                    spaces.add(normed)
    return spaces


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def bandpass_glm_drift_overlap(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Warn if bandpass filter and GLM drift model cover the same frequency range.

    Double-filtering removes signal twice in the overlapping band.
    """
    bandpass_hp: float | None = None
    glm_hp: float | None = None

    for step in bundle.plan_steps:
        tool = _tool_name(step)
        if tool in _BANDPASS_TOOLS and bandpass_hp is None:
            raw = _get_param(step, "high_pass", "hp", "highpass", "hp_filter")
            # xcpd-style tuple: bandpass_filter=[low_cutoff, high_cutoff]
            if raw is None:
                bf = _get_param(step, "bandpass_filter", "bandpass")
                if isinstance(bf, list | tuple) and len(bf) >= 1:
                    try:
                        raw = float(bf[0])
                    except (TypeError, ValueError):
                        pass
            try:
                bandpass_hp = float(raw)
            except (TypeError, ValueError):
                pass

        if tool in _GLM_TOOLS and glm_hp is None:
            raw = _get_param(
                step,
                "high_pass",
                "hp",
                "highpass",
                "hp_filter",
                "drift_cutoff",
                "cosine_drift_cutoff",
            )
            try:
                glm_hp = float(raw)
            except (TypeError, ValueError):
                pass

    if bandpass_hp is None or glm_hp is None:
        return None

    # Overlap: both filters active in similar range (within 2x)
    ratio = (
        max(bandpass_hp, glm_hp) / min(bandpass_hp, glm_hp)
        if min(bandpass_hp, glm_hp) > 0
        else float("inf")
    )
    if ratio <= 2.0:
        return ReviewFinding(
            rule_id="REVIEW_BANDPASS_GLM_DRIFT_OVERLAP",
            severity="warn",
            message=(
                f"Bandpass high_pass={bandpass_hp} Hz and GLM high_pass={glm_hp} Hz "
                f"overlap (ratio {ratio:.1f}×) — double-filtering risk."
            ),
            suggested_fix=(
                "Either remove the bandpass filter step or set GLM drift_model to None "
                "to avoid attenuating signal twice in the same frequency band."
            ),
        )
    return None


def preprocessing_stats_space_mismatch(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Error if preprocessing output space differs from stats/atlas expected space."""
    preproc_spaces: set[str] = set()
    stats_spaces: set[str] = set()

    for step in bundle.plan_steps:
        tool = _tool_name(step)
        if tool in _PREPROCESSING_TOOLS:
            preproc_spaces |= _extract_spaces(
                step,
                "output_space",
                "output_spaces",
                "target_space",
            )
        if tool in (_ATLAS_TOOLS | _GLM_TOOLS):
            stats_spaces |= _extract_spaces(
                step,
                "space",
                "target_space",
                "atlas_space",
                "input_space",
            )

    if not preproc_spaces or not stats_spaces:
        return None

    if preproc_spaces.isdisjoint(stats_spaces):
        return ReviewFinding(
            rule_id="REVIEW_SPACE_MISMATCH_ACROSS_STEPS",
            severity="error",
            message=(
                f"Preprocessing outputs space {sorted(preproc_spaces)} but "
                f"stats/atlas steps expect {sorted(stats_spaces)} — space mismatch."
            ),
            suggested_fix=(
                "Ensure preprocessing output_space matches the space expected by "
                "downstream analysis steps, or add a registration step between them."
            ),
        )
    return None


def bandpass_before_confound_regression(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn if a bandpass filter step precedes confound regression.

    Standard practice: regress confounds first, then bandpass, to avoid
    reintroducing noise in the pass-band.
    """
    first_bandpass_idx: int | None = None
    first_confound_idx: int | None = None

    for idx, step in enumerate(bundle.plan_steps):
        tool = _tool_name(step)
        if tool in _BANDPASS_TOOLS and first_bandpass_idx is None:
            # nilearn_clean_img can do both — only count as bandpass if it has
            # explicit bandpass params
            if tool == "nilearn_clean_img":
                if _get_param(step, "high_pass", "low_pass", "bandpass_filter") is None:
                    continue
            first_bandpass_idx = idx
        if tool in _CONFOUND_TOOLS and first_confound_idx is None:
            first_confound_idx = idx

    if first_bandpass_idx is None or first_confound_idx is None:
        return None

    if first_bandpass_idx < first_confound_idx:
        return ReviewFinding(
            rule_id="REVIEW_BANDPASS_BEFORE_CONFOUND",
            severity="warn",
            message=(
                f"Bandpass filter step (step {first_bandpass_idx + 1}) precedes "
                f"confound regression (step {first_confound_idx + 1}) — "
                "may reintroduce aliased noise in the pass-band."
            ),
            suggested_fix=(
                "Run confound regression before bandpass filtering, "
                "or use a combined denoising step (e.g. nilearn_clean_img with confounds + bandpass)."
            ),
        )
    return None


def atlas_registration_space_mismatch(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Error if atlas space and registration target space are incompatible."""
    reg_target_spaces: set[str] = set()
    atlas_spaces: set[str] = set()

    for step in bundle.plan_steps:
        tool = _tool_name(step)
        if tool in _REGISTRATION_TOOLS:
            reg_target_spaces |= _extract_spaces(
                step,
                "target_space",
                "reference_space",
                "dest_space",
            )
        if tool in _ATLAS_TOOLS:
            atlas_spaces |= _extract_spaces(
                step,
                "space",
                "atlas_space",
                "target_space",
            )

    if not reg_target_spaces or not atlas_spaces:
        return None

    if reg_target_spaces.isdisjoint(atlas_spaces):
        return ReviewFinding(
            rule_id="REVIEW_ATLAS_REG_SPACE_MISMATCH",
            severity="error",
            message=(
                f"Registration targets {sorted(reg_target_spaces)} but "
                f"atlas/parcellation expects {sorted(atlas_spaces)} — space mismatch."
            ),
            suggested_fix=(
                "Use the same space for registration and atlas. "
                "MNI152NLin2009cAsym is the fMRIPrep default; "
                "MNI152NLin6Asym is FSL standard — pick one consistently."
            ),
        )
    return None
