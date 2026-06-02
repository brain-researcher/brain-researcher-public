"""Shared confounds-family definitions for GLM multiverse axes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

CONF_FAMILY_AXES = (
    "confounds_motion_6",
    "confounds_motion_24",
    "confounds_global_signal",
    "confounds_csf",
    "confounds_white_matter",
    "confounds_csf_wm",
    "confounds_framewise_displacement",
    "confounds_dvars",
    "confounds_cosine_dct",
    "confounds_acompcor",
    "confounds_tcompcor",
    "confounds_ccompcor",
    "confounds_wcompcor",
    "confounds_non_steady_state",
    "confounds_scrub_motion_outliers",
    "confounds_aroma",
    "confounds_physio",
    "confounds_pupil",
)

CONF_FAMILY_PATTERNS: dict[str, list[str]] = {
    "confounds_motion_6": [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
    ],
    "confounds_motion_24": [
        "trans_x",
        "trans_y",
        "trans_z",
        "rot_x",
        "rot_y",
        "rot_z",
        "trans_x_derivative1",
        "trans_y_derivative1",
        "trans_z_derivative1",
        "rot_x_derivative1",
        "rot_y_derivative1",
        "rot_z_derivative1",
        "trans_x_power2",
        "trans_y_power2",
        "trans_z_power2",
        "rot_x_power2",
        "rot_y_power2",
        "rot_z_power2",
    ],
    "confounds_global_signal": ["global_signal"],
    "confounds_csf": ["csf"],
    "confounds_white_matter": ["white_matter"],
    "confounds_csf_wm": ["csf_wm"],
    "confounds_framewise_displacement": ["framewise_displacement"],
    "confounds_dvars": ["dvars", "std_dvars"],
    "confounds_cosine_dct": ["cosine*"],
    "confounds_acompcor": ["a_comp_cor_*"],
    "confounds_tcompcor": ["t_comp_cor_*"],
    "confounds_ccompcor": ["c_comp_cor_*"],
    "confounds_wcompcor": ["w_comp_cor_*"],
    "confounds_non_steady_state": ["non_steady_state_outlier*"],
    "confounds_scrub_motion_outliers": ["motion_outlier*"],
    "confounds_aroma": ["aroma_motion_*"],
    "confounds_physio": [
        "cardiac_signal_*",
        "cardiac_retroicor_*",
        "respiratory_signal_*",
        "respiratory_retroicor_*",
        "cardiorespiratory_sum_*",
        "cardiorespiratory_diff_*",
    ],
    "confounds_pupil": [
        "pupil_filtered_z",
        "pupil_derivative1_z",
        "pupil_tonic_z",
        "pupil_phasic_z",
        "pupil_blink_fraction",
    ],
}


def extract_confounds_family_flags(x_terms: Iterable[str]) -> dict[str, bool]:
    terms = [t.lower() for t in x_terms if t]

    def _starts_with(prefixes: tuple[str, ...]) -> bool:
        return any(term.startswith(prefixes) for term in terms)

    def _contains_prefix(prefixes: tuple[str, ...], needle: str) -> bool:
        return any(term.startswith(prefixes) and needle in term for term in terms)

    flags = {
        "confounds_motion_6": _starts_with(("trans_", "rot_")),
        "confounds_motion_24": _contains_prefix(("trans_", "rot_"), "derivative1")
        or _contains_prefix(("trans_", "rot_"), "power2"),
        "confounds_global_signal": _starts_with(("global_signal",)),
        "confounds_csf": any(
            term.startswith("csf") and not term.startswith("csf_wm") for term in terms
        ),
        "confounds_white_matter": _starts_with(("white_matter",)),
        "confounds_csf_wm": _starts_with(("csf_wm",)),
        "confounds_framewise_displacement": "framewise_displacement" in terms,
        "confounds_dvars": any(
            term.startswith(("dvars", "std_dvars")) for term in terms
        ),
        "confounds_cosine_dct": _starts_with(("cosine",)),
        "confounds_acompcor": _starts_with(("a_comp_cor",)),
        "confounds_tcompcor": _starts_with(("t_comp_cor",)) or "tcompcor" in terms,
        "confounds_ccompcor": _starts_with(("c_comp_cor",)),
        "confounds_wcompcor": _starts_with(("w_comp_cor",)),
        "confounds_non_steady_state": _starts_with(("non_steady_state_outlier",)),
        "confounds_scrub_motion_outliers": _starts_with(("motion_outlier",)),
        "confounds_aroma": _starts_with(("aroma_motion",)),
        "confounds_physio": _starts_with(
            (
                "cardiac_signal_",
                "cardiac_retroicor_",
                "respiratory_signal_",
                "respiratory_retroicor_",
                "cardiorespiratory_sum_",
                "cardiorespiratory_diff_",
            )
        ),
        "confounds_pupil": _starts_with(
            (
                "pupil_filtered_z",
                "pupil_derivative1_z",
                "pupil_tonic_z",
                "pupil_phasic_z",
                "pupil_blink_fraction",
            )
        ),
    }
    return {axis: bool(flags.get(axis, False)) for axis in CONF_FAMILY_AXES}


def enforce_motion_consistency(families: dict[str, bool]) -> dict[str, bool]:
    if families.get("confounds_motion_24"):
        families["confounds_motion_6"] = True
    if "confounds_motion_6" in families and not families.get("confounds_motion_6"):
        families["confounds_motion_24"] = False
    return families


def confounds_families_to_patterns(families: Mapping[str, bool]) -> list[str]:
    merged = enforce_motion_consistency(dict(families))
    patterns: list[str] = []
    if merged.get("confounds_motion_24"):
        patterns.extend(CONF_FAMILY_PATTERNS["confounds_motion_24"])
    elif merged.get("confounds_motion_6"):
        patterns.extend(CONF_FAMILY_PATTERNS["confounds_motion_6"])

    for axis, pats in CONF_FAMILY_PATTERNS.items():
        if axis in {"confounds_motion_6", "confounds_motion_24"}:
            continue
        if merged.get(axis):
            patterns.extend(pats)

    seen: set[str] = set()
    out: list[str] = []
    for pat in patterns:
        if pat in seen:
            continue
        seen.add(pat)
        out.append(pat)
    return out
