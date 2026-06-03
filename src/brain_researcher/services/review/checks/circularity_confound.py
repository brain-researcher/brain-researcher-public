"""Deterministic circularity / confound review checks.

Two high-precision checks that mirror the ``check_fn(bundle) -> ReviewFinding |
None`` pattern used by ``predictive_integrity.py`` and ``leakage_extra.py``.
Like those siblings, both checks are intentionally conservative: they fire ONLY
on explicit, structured ``review_context`` provenance and never infer a problem
from prose, free text, heuristics, or weak suspicion.

Checks
------
1. ``double_dipping_check`` (rule ``REVIEW_CIRCULARITY_DOUBLE_DIPPING``)
   Non-independence / circular analysis ("double dipping"): ROI or feature
   *selection* and the subsequent effect *test* use the same data / contrast
   with no independent localizer.

2. ``demographic_confound_uncontrolled_check``
   (rule ``REVIEW_CONFOUND_DEMOGRAPHIC_UNCONTROLLED``)
   A group-level significant demographic difference (e.g. age / sex) is recorded
   in provenance, but the statistical model's declared covariates omit the
   confounding variable.

review_context fields read
==========================
Both checks read ``bundle.review_context`` merged with the same nested fallback
surfaces used by the sibling leakage checks (``observed_artifacts.review_context``,
``source_summary.review_context``, ``review_contract.review_context``,
``analysis_bundle.review_context``). Within that merged mapping:

double_dipping_check
--------------------
Reads a ``roi_provenance`` (aliases: ``feature_selection_provenance``,
``selection_provenance``) mapping, looked up at the top level and under the
``selection`` / ``provenance`` sub-sections. Recognized keys:

- ``source`` (aliases ``selection_source``, ``selection_data``,
  ``definition_source``): the data/contrast used to *define* the ROI/features.
  The token ``same_contrast`` / ``same_data`` / ``test_data`` / ``test_contrast``
  marks the selection as drawn from the same data as the test.
- ``test_source`` (aliases ``test_data``, ``test_contrast``,
  ``effect_test_data``): the data/contrast used to *test* the effect.
- ``independent_localizer`` (aliases ``independent``, ``localizer_independent``,
  ``orthogonal_contrast``): explicit boolean stating selection is independent of
  the test. ``True`` suppresses the finding.
- ``selection_test_independence``: explicit boolean; ``False`` is a direct
  double-dipping marker, ``True`` suppresses the finding.
- ``circular`` / ``double_dipping``: explicit boolean direct markers; ``True``
  fires the finding.

The check fires when EITHER:
- an explicit circularity marker is True
  (``circular`` / ``double_dipping`` / ``selection_test_independence`` False), OR
- ``source`` is a same-data token (``same_contrast`` etc.), OR
- ``source`` and ``test_source`` are present and equal,
AND no independent-localizer escape hatch is set
(``independent_localizer`` / ``selection_test_independence`` True).

demographic_confound_uncontrolled_check
----------------------------------------
Reads a ``demographic_balance`` (aliases ``demographic_deltas``,
``group_demographics``, ``demographics``) section, at the top level and under
``confounds`` / ``provenance`` / ``statistics``. Two provenance shapes are
accepted:

- Mapping-of-variables form::

      demographic_balance:
        age: {significant: true, p: 0.001}
        sex: {significant: false}

  A variable is "significantly different across groups" when its entry has an
  explicit ``significant: true`` (aliases ``group_difference``, ``imbalanced``,
  ``differs``) OR an explicit ``p`` / ``p_value`` below ``alpha``
  (default 0.05, overridable via ``demographic_balance.alpha``).

- List form::

      demographic_deltas:
        - {variable: age, significant: true}

The model's controlled variables are read from ``model_covariates`` (aliases
``covariates``, ``nuisance_regressors``, ``adjusted_for``, ``controlled_for``,
``stat_model.covariates``) as a string list. A flagged demographic variable is
"uncontrolled" when neither it nor a known alias appears in that covariate list.
The check fires only when at least one significantly-different demographic
variable is NOT present in the declared covariates. If covariates are entirely
absent from provenance, the check does not fire (insufficient provenance).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

# --------------------------------------------------------------------------- #
# Shared review_context discovery (mirrors leakage_extra / predictive_integrity)
# --------------------------------------------------------------------------- #


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    value = bundle.observed_artifacts.get(key)
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    """Merge every place review_context can live, last-writer-wins."""

    candidates: list[dict[str, Any]] = []

    if isinstance(getattr(bundle, "review_context", None), dict):
        candidates.append(dict(bundle.review_context))

    for key in ("review_context", "source_summary"):
        artifact = _artifact_dict(bundle, key)
        if key == "source_summary":
            nested = artifact.get("review_context")
            if isinstance(nested, dict):
                candidates.append(dict(nested))
        else:
            candidates.append(artifact)

    contract = _artifact_dict(bundle, "review_contract")
    contract_context = contract.get("review_context")
    if isinstance(contract_context, dict):
        candidates.append(dict(contract_context))

    analysis_bundle = _artifact_dict(bundle, "analysis_bundle")
    analysis_context = analysis_bundle.get("review_context")
    if isinstance(analysis_context, dict):
        candidates.append(dict(analysis_context))

    merged: dict[str, Any] = {}
    for candidate in candidates:
        merged.update(candidate)
    return merged


def _nested_mapping(context: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _mapping(context.get(key))


def _normalize(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _explicit_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw: Iterable[object] = [value]
    elif isinstance(value, Mapping):
        raw = list(value.keys())
    elif isinstance(value, Iterable):
        raw = list(value)
    else:
        return []
    cleaned: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _first_present(
    sections: list[Mapping[str, object]], keys: tuple[str, ...]
) -> tuple[str, object] | None:
    """Return (key, value) for the first non-empty key across sections."""

    for section in sections:
        for key in keys:
            value = section.get(key)
            if value not in (None, "", [], {}):
                return key, value
    return None


# --------------------------------------------------------------------------- #
# (a) Double dipping / circular analysis
# --------------------------------------------------------------------------- #

_ROI_PROVENANCE_KEYS = (
    "roi_provenance",
    "feature_selection_provenance",
    "selection_provenance",
)
_SELECTION_SOURCE_KEYS = (
    "source",
    "selection_source",
    "selection_data",
    "definition_source",
    "roi_definition_source",
)
_TEST_SOURCE_KEYS = (
    "test_source",
    "test_data",
    "test_contrast",
    "effect_test_data",
    "effect_test_source",
)
_INDEPENDENT_LOCALIZER_KEYS = (
    "independent_localizer",
    "independent",
    "localizer_independent",
    "orthogonal_contrast",
)
_DIRECT_CIRCULAR_KEYS = (
    "circular",
    "double_dipping",
    "non_independent",
)
# Tokens (after normalization) that mean "selection drawn from the test data".
_SAME_DATA_TOKENS = frozenset(
    {
        "same_contrast",
        "same_data",
        "same_dataset",
        "test_data",
        "test_contrast",
        "test_set",
        "effect_test_data",
        "identical_data",
        "identical_contrast",
        "whole_data",
        "all_data",
        "selection_and_test_same",
    }
)


def _double_dipping_sections(
    context: Mapping[str, object],
) -> list[Mapping[str, object]]:
    return [
        context,
        _nested_mapping(context, "selection"),
        _nested_mapping(context, "provenance"),
        _nested_mapping(context, "circularity"),
    ]


def _resolve_roi_provenance(
    context: Mapping[str, object],
) -> tuple[str, Mapping[str, object]] | None:
    for section in _double_dipping_sections(context):
        for key in _ROI_PROVENANCE_KEYS:
            value = section.get(key)
            if isinstance(value, Mapping) and value:
                return key, value
    return None


def double_dipping_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block circular ROI/feature selection-and-test on the same data.

    Fires only on explicit ``review_context.roi_provenance`` provenance that
    shows ROI / feature selection and the effect test drawn from the same
    data / contrast with no independent localizer. See module docstring for the
    exact fields and the firing logic.
    """

    context = _review_context(bundle)
    resolved = _resolve_roi_provenance(context)
    if resolved is None:
        return None
    prov_key, provenance = resolved

    # Escape hatch: an explicit independent localizer / independence flag.
    for key in _INDEPENDENT_LOCALIZER_KEYS:
        if _explicit_bool(provenance.get(key)) is True:
            return None
    if _explicit_bool(provenance.get("selection_test_independence")) is True:
        return None

    evidence: list[str] = []
    triggered = False

    # 1. Direct explicit circularity markers.
    for key in _DIRECT_CIRCULAR_KEYS:
        if _explicit_bool(provenance.get(key)) is True:
            triggered = True
            evidence.append(f"review_context.{prov_key}.{key}=True")
    if _explicit_bool(provenance.get("selection_test_independence")) is False:
        triggered = True
        evidence.append(f"review_context.{prov_key}.selection_test_independence=False")

    # 2. Selection source is a same-data token.
    source_hit = _first_present([provenance], _SELECTION_SOURCE_KEYS)
    source_token = _normalize(source_hit[1]) if source_hit is not None else ""
    if source_hit is not None and source_token in _SAME_DATA_TOKENS:
        triggered = True
        evidence.append(f"review_context.{prov_key}.{source_hit[0]}={source_token}")

    # 3. Selection source == test source (same data/contrast).
    test_hit = _first_present([provenance], _TEST_SOURCE_KEYS)
    if source_hit is not None and test_hit is not None:
        test_token = _normalize(test_hit[1])
        if source_token and source_token == test_token:
            triggered = True
            evidence.append(
                f"review_context.{prov_key}.{source_hit[0]}=="
                f"{test_hit[0]}={source_token}"
            )

    if not triggered:
        return None

    evidence.append("registry_rule_ids=['REVIEW_CIRCULARITY_DOUBLE_DIPPING']")

    return ReviewFinding(
        rule_id="REVIEW_CIRCULARITY_DOUBLE_DIPPING",
        severity="error",
        action="block",
        message=(
            "Explicit ROI / feature-selection provenance shows the selection and "
            "the effect test were performed on the same data / contrast with no "
            "independent localizer. This is non-independent (circular) analysis "
            "('double dipping'), which biases effect estimates and invalidates the "
            "test statistics."
        ),
        suggested_fix=(
            "Define the ROI / features from data that is independent of the effect "
            "test: use an independent localizer contrast, a separate run/session, "
            "or a leave-one-subject-out / cross-validated selection, then re-emit "
            "roi_provenance with independent_localizer=true."
        ),
        kg_evidence=evidence,
        reason_tags=["circularity", "double_dipping", "non_independence"],
    )


# --------------------------------------------------------------------------- #
# (b) Uncontrolled demographic confound
# --------------------------------------------------------------------------- #

_DEMOGRAPHIC_BALANCE_KEYS = (
    "demographic_balance",
    "demographic_deltas",
    "group_demographics",
    "demographics",
)
_COVARIATE_KEYS = (
    "model_covariates",
    "covariates",
    "nuisance_regressors",
    "adjusted_for",
    "controlled_for",
    "stat_model_covariates",
)
_SIGNIFICANT_FLAG_KEYS = (
    "significant",
    "group_difference",
    "imbalanced",
    "differs",
    "significant_difference",
)
_P_VALUE_KEYS = ("p", "p_value", "pval")
_DEFAULT_ALPHA = 0.05

# Known demographic variable aliases so "age" in covariates matches an "age"
# delta even if spelled differently.
_VARIABLE_ALIASES: dict[str, frozenset[str]] = {
    "age": frozenset({"age", "age_years", "mean_age", "age_at_scan"}),
    "sex": frozenset({"sex", "gender", "biological_sex"}),
    "education": frozenset({"education", "edu", "years_education", "education_years"}),
    "handedness": frozenset({"handedness", "hand"}),
    "iq": frozenset({"iq", "fsiq", "full_scale_iq"}),
}


def _confound_sections(context: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        context,
        _nested_mapping(context, "confounds"),
        _nested_mapping(context, "provenance"),
        _nested_mapping(context, "statistics"),
        _nested_mapping(context, "design"),
    ]


def _canonical_variable(name: str) -> str:
    normalized = _normalize(name)
    for canonical, aliases in _VARIABLE_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return normalized


def _covariate_canon_set(sections: list[Mapping[str, object]]) -> set[str] | None:
    """Return canonicalized covariate names, or None if none declared."""

    found = False
    canon: set[str] = set()
    for section in sections:
        for key in _COVARIATE_KEYS:
            value = section.get(key)
            if value in (None, ""):
                continue
            names = _string_list(value)
            if names or isinstance(value, list | tuple | Mapping):
                found = True
            for name in names:
                canon.add(_canonical_variable(name))
        # Nested stat_model.covariates
        stat_model = section.get("stat_model")
        if isinstance(stat_model, Mapping):
            covs = stat_model.get("covariates")
            if covs not in (None, ""):
                found = True
                for name in _string_list(covs):
                    canon.add(_canonical_variable(name))
    return canon if found else None


def _entry_is_significant(entry: Mapping[str, object], alpha: float) -> bool:
    for key in _SIGNIFICANT_FLAG_KEYS:
        if _explicit_bool(entry.get(key)) is True:
            return True
    for key in _P_VALUE_KEYS:
        p = _float_value(entry.get(key))
        if p is not None and p < alpha:
            return True
    return False


def _alpha(sections: list[Mapping[str, object]]) -> float:
    for section in sections:
        for key in _DEMOGRAPHIC_BALANCE_KEYS:
            block = section.get(key)
            if isinstance(block, Mapping):
                a = _float_value(block.get("alpha"))
                if a is not None and 0.0 < a < 1.0:
                    return a
    return _DEFAULT_ALPHA


def _significant_demographic_variables(
    sections: list[Mapping[str, object]], alpha: float
) -> list[str]:
    """Return canonical names of demographic variables flagged as different."""

    flagged: set[str] = set()
    for section in sections:
        hit = _first_present([section], _DEMOGRAPHIC_BALANCE_KEYS)
        if hit is None:
            continue
        block = hit[1]
        # Mapping-of-variables form.
        if isinstance(block, Mapping):
            for var_name, entry in block.items():
                if var_name == "alpha":
                    continue
                if isinstance(entry, Mapping):
                    if _entry_is_significant(entry, alpha):
                        flagged.add(_canonical_variable(str(var_name)))
                else:
                    # e.g. {"age": true}
                    if _explicit_bool(entry) is True:
                        flagged.add(_canonical_variable(str(var_name)))
        # List form.
        elif isinstance(block, Iterable) and not isinstance(block, str | bytes):
            for entry in block:
                if not isinstance(entry, Mapping):
                    continue
                var_name = (
                    entry.get("variable") or entry.get("name") or entry.get("var")
                )
                if var_name in (None, ""):
                    continue
                if _entry_is_significant(entry, alpha):
                    flagged.add(_canonical_variable(str(var_name)))
    return sorted(flagged)


def demographic_confound_uncontrolled_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block group-level demographic confounds omitted from the stat model.

    Fires only when explicit ``review_context`` provenance records a
    significant group-level demographic difference (age/sex/...) AND the declared
    model covariates (which must themselves be present) omit that variable.
    See module docstring for the exact fields and firing logic.
    """

    context = _review_context(bundle)
    sections = _confound_sections(context)

    alpha = _alpha(sections)
    flagged = _significant_demographic_variables(sections, alpha)
    if not flagged:
        return None

    covariates = _covariate_canon_set(sections)
    if covariates is None:
        # No declared covariates at all => insufficient provenance, do not fire.
        return None

    uncontrolled = [var for var in flagged if var not in covariates]
    if not uncontrolled:
        return None

    evidence = [
        f"review_context.demographic_significant={flagged}",
        f"review_context.model_covariates={sorted(covariates)}",
        f"review_context.uncontrolled_demographics={uncontrolled}",
        f"alpha={alpha:g}",
        "registry_rule_ids=['REVIEW_CONFOUND_DEMOGRAPHIC_UNCONTROLLED']",
    ]

    return ReviewFinding(
        rule_id="REVIEW_CONFOUND_DEMOGRAPHIC_UNCONTROLLED",
        severity="error",
        action="block",
        message=(
            "Explicit provenance records a significant group-level demographic "
            f"difference for {', '.join(uncontrolled)}, but the declared statistical "
            "model covariates omit it. Group differences in demographics that are "
            "not modeled confound the group effect of interest."
        ),
        suggested_fix=(
            "Add the flagged demographic variable(s) "
            f"({', '.join(uncontrolled)}) as covariates / nuisance regressors in "
            "the group-level model (or match groups on them), then re-emit "
            "model_covariates including these variables."
        ),
        kg_evidence=evidence,
        reason_tags=["confound", "demographic", "group_difference"],
    )


__all__ = [
    "double_dipping_check",
    "demographic_confound_uncontrolled_check",
]
