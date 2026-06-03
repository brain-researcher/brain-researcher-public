"""Integration-style tests for the flag-gated ``check_routing`` wiring that
``distill_scientific_review_records`` will use to subset its correctness-check
tuple.

The actual edit to ``distill_review.py`` is delivered as a unified diff and is
NOT applied in this worktree, so these tests verify the *behaviour the wiring
relies on* directly against ``check_routing.select_checks`` and a faithful
re-implementation of the gating decision the diff introduces:

    flag = os.getenv("BR_REVIEW_CHECK_ROUTING", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if flag:
        decision = select_checks(bundle, [fn.__name__ for fn in CHECKS])
        active = decision.select_callables(CHECKS)
    else:
        active = CHECKS

Assertions:
  * flag OFF  -> every check runs (no subsetting),
  * flag ON   -> conditional checks may be dropped, BUT every safety-floor
    (always-on) check is preserved.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from brain_researcher.services.review.check_routing import (
    ALWAYS_ON_GROUPS,
    _CHECK_TO_GROUP,
    classify_check,
    select_checks,
)

_FLAG = "BR_REVIEW_CHECK_ROUTING"
_TRUTHY = {"1", "true", "yes", "on"}


def _flag_enabled() -> bool:
    """Mirror the env-flag predicate the distill diff installs."""
    return os.getenv(_FLAG, "").strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Fake check callables: named functions so ``fn.__name__`` maps into the
# routing group table exactly as the real distill tuple does.
# ---------------------------------------------------------------------------
def _make_check(name):
    def _check(_bundle):  # pragma: no cover - never invoked in these tests
        return None

    _check.__name__ = name
    return _check


# Safety-floor representatives (one per always-on group) + a couple of
# conditional checks that should be skippable when their family is absent.
_SAFETY_FLOOR_NAMES = [
    "design_matrix_rank_check",  # structural_integrity
    "value_domain_contract_violation_check",  # value_domain
    "predictive_cv_leakage_check",  # leakage
    "permutation_exchangeability_check",  # null_model
    "predictive_review_context_metadata_check",  # review_context_integrity
]
_CONDITIONAL_NAMES = [
    "corr_symmetric_check",  # correlation_matrix
    "neuroai_subject_manifest_coverage_check",  # predictive_neuroai
    "effect_size_plausibility_check",  # glm_design
]
_UNCLASSIFIED_NAMES = [
    "claim_inflation_check",  # intentionally unclassified -> always run
]

_ALL_CHECK_FNS = tuple(
    _make_check(n)
    for n in (_SAFETY_FLOOR_NAMES + _CONDITIONAL_NAMES + _UNCLASSIFIED_NAMES)
)


def _glm_only_bundle():
    """Bundle with a coarse family signal (glm) that does NOT match the
    correlation_matrix / predictive_neuroai conditional groups, so those should
    be skippable when routing is enabled."""
    return SimpleNamespace(
        run_id="run-test",
        kg_context={"analysis_family": "glm", "statistical_method": "paired_t_test"},
        review_context={},
        declared_modalities=["anat"],
    )


# ---------------------------------------------------------------------------
# Sanity: the names we test are actually wired into the routing table.
# ---------------------------------------------------------------------------
def test_safety_floor_names_map_to_always_on_groups():
    for name in _SAFETY_FLOOR_NAMES:
        group = classify_check(name)
        assert group in ALWAYS_ON_GROUPS, (name, group)


def test_conditional_names_map_to_gated_groups():
    for name in _CONDITIONAL_NAMES:
        group = classify_check(name)
        assert group is not None and group not in ALWAYS_ON_GROUPS, (name, group)


def test_unclassified_names_are_unmapped():
    for name in _UNCLASSIFIED_NAMES:
        assert classify_check(name) is None
        assert name not in _CHECK_TO_GROUP


# ---------------------------------------------------------------------------
# Flag OFF -> run all checks (no subsetting).
# ---------------------------------------------------------------------------
def test_flag_off_runs_all_checks(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    assert _flag_enabled() is False

    bundle = _glm_only_bundle()
    # Emulate the diff's branch when the flag is off.
    active = _ALL_CHECK_FNS if not _flag_enabled() else None
    assert active is _ALL_CHECK_FNS
    assert [fn.__name__ for fn in active] == [
        fn.__name__ for fn in _ALL_CHECK_FNS
    ]


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "FALSE", "  "])
def test_falsey_flag_values_run_all_checks(monkeypatch, value):
    monkeypatch.setenv(_FLAG, value)
    assert _flag_enabled() is False
    active = _ALL_CHECK_FNS if not _flag_enabled() else []
    assert active is _ALL_CHECK_FNS


# ---------------------------------------------------------------------------
# Flag ON -> subset, but preserve the safety floor.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "On", " yes "])
def test_flag_on_subsets_but_preserves_safety_floor(monkeypatch, value):
    monkeypatch.setenv(_FLAG, value)
    assert _flag_enabled() is True

    bundle = _glm_only_bundle()
    names = [fn.__name__ for fn in _ALL_CHECK_FNS]
    decision = select_checks(bundle, names)
    active = decision.select_callables(_ALL_CHECK_FNS)
    active_names = {fn.__name__ for fn in active}

    # Safety floor: every always-on check survives.
    for name in _SAFETY_FLOOR_NAMES:
        assert name in active_names, f"safety-floor check dropped: {name}"

    # Unclassified checks survive (false-negative-averse).
    for name in _UNCLASSIFIED_NAMES:
        assert name in active_names, f"unclassified check dropped: {name}"

    # At least one non-matching conditional check is skipped for a glm bundle
    # (correlation_matrix / predictive_neuroai do not match glm signals).
    assert decision.skipped, "expected some conditional checks to be skipped"
    assert "corr_symmetric_check" in decision.skipped
    assert "neuroai_subject_manifest_coverage_check" in decision.skipped
    # The glm-matching conditional check is kept.
    assert "effect_size_plausibility_check" in active_names

    # Subsetting actually reduced the set.
    assert len(active) < len(_ALL_CHECK_FNS)
    # And every selected callable is order-preserved from the original tuple.
    assert [fn.__name__ for fn in active] == [
        fn.__name__ for fn in _ALL_CHECK_FNS if fn.__name__ in active_names
    ]


def test_flag_on_with_no_family_signal_keeps_everything(monkeypatch):
    """Conservative contract: no coarse family signal -> keep all checks even
    when the flag is on."""
    monkeypatch.setenv(_FLAG, "1")
    bundle = SimpleNamespace(
        run_id="run-empty",
        kg_context={},
        review_context={},
        declared_modalities=[],
    )
    names = [fn.__name__ for fn in _ALL_CHECK_FNS]
    decision = select_checks(bundle, names)
    active = decision.select_callables(_ALL_CHECK_FNS)
    assert not decision.skipped
    assert len(active) == len(_ALL_CHECK_FNS)


def test_flag_on_review_context_key_overrides_family_skip(monkeypatch):
    """A correlation_matrix review_context key forces its conditional checks to
    run even when the family signal is glm."""
    monkeypatch.setenv(_FLAG, "1")
    bundle = SimpleNamespace(
        run_id="run-rc",
        kg_context={"analysis_family": "glm"},
        review_context={"correlation_matrix": {"path": "x.json"}},
        declared_modalities=["func"],
    )
    names = [fn.__name__ for fn in _ALL_CHECK_FNS]
    decision = select_checks(bundle, names)
    active_names = {fn.__name__ for fn in decision.select_callables(_ALL_CHECK_FNS)}
    assert "corr_symmetric_check" in active_names
