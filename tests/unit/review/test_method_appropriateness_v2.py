"""Tests for the generalized method_appropriateness_check (B2.5)."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.checks.method_appropriateness import (
    _load_design_aliases,
    _load_method_aliases,
    _load_seed,
    _query_seed_compatibility,
    _resolve_canonical,
    method_appropriateness_check,
)


def _clear_caches():
    _load_seed.cache_clear()
    _load_design_aliases.cache_clear()
    _load_method_aliases.cache_clear()


def _bundle(
    steps: list[dict] | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=steps or [],
        declared_modalities=[],
        declared_spaces=[],
        kg_context=kg_context or {},
    )


# ---------------------------------------------------------------------------
# Seed loading
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSeedLoading:
    def test_seed_loads_successfully(self):
        _clear_caches()
        seed = _load_seed()
        assert "design_aliases" in seed
        assert "method_aliases" in seed
        assert "rules" in seed
        assert len(seed["rules"]) >= 20

    def test_design_aliases_populated(self):
        _clear_caches()
        aliases = _load_design_aliases()
        assert "repeated_measures" in aliases
        assert "independent_groups" in aliases
        assert "one_sample" in aliases
        assert "factorial" in aliases
        assert "mixed_design" in aliases
        assert "longitudinal" in aliases
        assert "correlation" in aliases

    def test_method_aliases_populated(self):
        _clear_caches()
        aliases = _load_method_aliases()
        assert "paired_t_test" in aliases
        assert "independent_t_test" in aliases
        assert "one_sample_t_test" in aliases
        assert "anova_oneway" in aliases
        assert "anova_repeated" in aliases
        assert "anova_mixed" in aliases
        assert "mixed_effects_model" in aliases
        assert "mann_whitney" in aliases
        assert "wilcoxon_signed_rank" in aliases

    def test_onvoc_design_map_present(self):
        _clear_caches()
        seed = _load_seed()
        odm = seed.get("onvoc_design_map", {})
        assert "ONVOC_0000616" in odm
        assert odm["ONVOC_0000616"] == "repeated_measures"


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAliasResolution:
    def test_canonical_key_resolves_to_itself(self):
        _clear_caches()
        aliases = _load_design_aliases()
        assert _resolve_canonical("repeated_measures", aliases) == "repeated_measures"

    def test_alias_resolves_to_canonical(self):
        _clear_caches()
        aliases = _load_design_aliases()
        assert _resolve_canonical("within-subject", aliases) == "repeated_measures"
        assert _resolve_canonical("between-subject", aliases) == "independent_groups"
        assert _resolve_canonical("one-sample", aliases) == "one_sample"
        assert _resolve_canonical("split-plot", aliases) == "mixed_design"

    def test_method_alias_resolves(self):
        _clear_caches()
        aliases = _load_method_aliases()
        assert _resolve_canonical("ttest_rel", aliases) == "paired_t_test"
        assert _resolve_canonical("ttest_ind", aliases) == "independent_t_test"
        assert _resolve_canonical("ttest_1samp", aliases) == "one_sample_t_test"
        assert _resolve_canonical("rmanova", aliases) == "anova_repeated"
        assert _resolve_canonical("LME", aliases) == "mixed_effects_model"

    def test_unknown_returns_none(self):
        _clear_caches()
        aliases = _load_design_aliases()
        assert _resolve_canonical("completely_unknown_design", aliases) is None


# ---------------------------------------------------------------------------
# Seed compatibility lookup
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSeedCompatibility:
    def test_incompatible_pair(self):
        _clear_caches()
        result = _query_seed_compatibility("repeated_measures", "independent_t_test")
        assert result is not None
        assert result["compatible"] is False
        assert result["source"] == "seed"

    def test_compatible_pair(self):
        _clear_caches()
        result = _query_seed_compatibility("repeated_measures", "paired_t_test")
        assert result is not None
        assert result["compatible"] is True

    def test_unknown_pair_returns_none(self):
        _clear_caches()
        result = _query_seed_compatibility("unknown_design", "unknown_method")
        assert result is None


# ---------------------------------------------------------------------------
# Incompatible rules fire correctly
# ---------------------------------------------------------------------------

_INCOMPATIBLE_CASES = [
    ("repeated_measures", "independent_t_test"),
    ("repeated_measures", "anova_oneway"),
    ("repeated_measures", "mann_whitney"),
    ("independent_groups", "paired_t_test"),
    ("independent_groups", "anova_repeated"),
    ("independent_groups", "wilcoxon_signed_rank"),
    ("one_sample", "independent_t_test"),
    ("one_sample", "paired_t_test"),
    ("mixed_design", "independent_t_test"),
    ("mixed_design", "anova_oneway"),
    ("longitudinal", "independent_t_test"),
    ("correlation", "independent_t_test"),
]


@pytest.mark.unit
@pytest.mark.parametrize("design,method", _INCOMPATIBLE_CASES)
def test_incompatible_rule_fires(design, method):
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "some_tool",
            "params": {
                "design_type": design,
                "statistical_method": method,
            },
            "step_id": "s1",
        }],
    )
    finding = method_appropriateness_check(bundle)
    assert finding is not None, f"Expected finding for ({design}, {method})"
    assert finding.severity in ("error", "warn")
    assert finding.kg_evidence


# ---------------------------------------------------------------------------
# Compatible rules do NOT fire
# ---------------------------------------------------------------------------

_COMPATIBLE_CASES = [
    ("repeated_measures", "paired_t_test"),
    ("repeated_measures", "anova_repeated"),
    ("repeated_measures", "mixed_effects_model"),
    ("repeated_measures", "wilcoxon_signed_rank"),
    ("independent_groups", "independent_t_test"),
    ("independent_groups", "anova_oneway"),
    ("independent_groups", "mann_whitney"),
    ("one_sample", "one_sample_t_test"),
    ("mixed_design", "anova_mixed"),
    ("mixed_design", "mixed_effects_model"),
    ("longitudinal", "mixed_effects_model"),
    ("longitudinal", "anova_repeated"),
    ("correlation", "correlation_pearson"),
    ("correlation", "linear_regression"),
]


@pytest.mark.unit
@pytest.mark.parametrize("design,method", _COMPATIBLE_CASES)
def test_compatible_rule_does_not_fire(design, method):
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "some_tool",
            "params": {
                "design_type": design,
                "statistical_method": method,
            },
            "step_id": "s1",
        }],
    )
    finding = method_appropriateness_check(bundle)
    assert finding is None, f"Did not expect finding for ({design}, {method})"


# ---------------------------------------------------------------------------
# Factorial rules fire as warnings (not errors)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("method", ["independent_t_test", "paired_t_test"])
def test_factorial_mismatch_is_warning(method):
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "some_tool",
            "params": {
                "design_type": "factorial",
                "statistical_method": method,
            },
            "step_id": "s1",
        }],
    )
    finding = method_appropriateness_check(bundle)
    assert finding is not None
    assert finding.severity == "warn"


# ---------------------------------------------------------------------------
# Unknown design/method returns None
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_unknown_design_returns_none():
    """No design hint at all → no finding."""
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "compute_metric",
            "params": {"output_dir": "/tmp/out"},
            "step_id": "s1",
        }],
    )
    finding = method_appropriateness_check(bundle)
    assert finding is None


@pytest.mark.unit
def test_unknown_method_returns_none():
    """Design known but no method hint → no finding."""
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "compute_metric",
            "params": {"design_type": "repeated_measures"},
            "step_id": "s1",
        }],
    )
    finding = method_appropriateness_check(bundle)
    assert finding is None


# ---------------------------------------------------------------------------
# Inference from tool names and text hints
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_infer_design_from_text_hints():
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "analyze",
            "params": {"description": "This is a within-subject paired design"},
            "step_id": "s1",
        }],
        kg_context={"statistical_method": "independent_t_test"},
    )
    # Design inferred from text, method from kg_context text hint
    finding = method_appropriateness_check(bundle)
    assert finding is not None


@pytest.mark.unit
def test_infer_method_from_tool_name():
    _clear_caches()
    bundle = _bundle(
        steps=[{
            "tool": "ttest_ind",
            "params": {"within_subject": True},
            "step_id": "s1",
        }],
    )
    finding = method_appropriateness_check(bundle)
    assert finding is not None
    assert finding.severity == "error"
