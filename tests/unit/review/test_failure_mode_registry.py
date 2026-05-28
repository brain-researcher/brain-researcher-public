from pathlib import Path

from brain_researcher.services.review.failure_mode_registry import (
    DEFAULT_REGISTRY_PATH,
    load_failure_mode_registry,
    render_failure_mode_registry_markdown,
)

DOC_PATH = Path("docs/review/failure_mode_registry.md")
PREDICTIVE_POLICY_PATH = Path("docs/review/predictive_permutation_null_policy.md")


def test_failure_mode_registry_loads_with_expected_detector_spine():
    registry = load_failure_mode_registry()

    assert registry.schema_version == "br-failure-mode-registry-v1"
    assert set(registry.detectors) == {
        "measured",
        "reconcile",
        "provenance",
        "invariant",
        "prior",
        "coverage",
    }
    assert len(registry.rules) >= 80


def test_failure_mode_registry_rows_have_unique_ids_and_fixtures():
    registry = load_failure_mode_registry()

    ids = [rule.id for rule in registry.rules]
    fixtures = [rule.fixture for rule in registry.rules]
    assert len(ids) == len(set(ids))
    assert len(fixtures) == len(set(fixtures))


def test_failure_mode_registry_encodes_gate_semantics():
    registry = load_failure_mode_registry()

    for rule in registry.rules:
        if rule.detect == "provenance":
            assert rule.prevent, rule.id
        if rule.detect in {"coverage", "prior"}:
            assert rule.gate == "review", rule.id
        if rule.severity == "warn":
            assert rule.default_action == "caveat"
        elif rule.gate == "execution":
            assert rule.default_action == "raise"
        else:
            assert rule.default_action == "block_claim"


def test_failure_mode_registry_preserves_high_priority_seed_rules():
    registry = load_failure_mode_registry()
    by_id = {rule.id: rule for rule in registry.rules}

    for rule_id in {
        "REVIEW_VALUEDOMAIN_FISHER_Z_INPUT",
        "REVIEW_LEAKAGE_FAMILY_SPLIT",
        "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC",
        "REVIEW_GOVERNANCE_VERDICT_NOT_STAMPED",
        "REVIEW_GOVERNANCE_MISSING_PERMUTATION_NULL",
        "REVIEW_GOVERNANCE_VERDICT_STALE_HASH",
    }:
        assert rule_id in by_id
        assert by_id[rule_id].silent is True
        assert by_id[rule_id].inflates == "favorable"
        assert by_id[rule_id].severity in {"critical", "error"}


def test_failure_mode_registry_doc_is_generated_from_yaml():
    registry = load_failure_mode_registry(DEFAULT_REGISTRY_PATH)
    rendered = render_failure_mode_registry_markdown(registry)

    assert DOC_PATH.read_text(encoding="utf-8") == rendered


def test_predictive_permutation_null_policy_tracks_registry_terms():
    text = PREDICTIVE_POLICY_PATH.read_text(encoding="utf-8")

    for expected in {
        "REVIEW_GOVERNANCE_MISSING_PERMUTATION_NULL",
        "REVIEW_GOVERNANCE_PERMUTATION_EXCHANGEABILITY_INVALID",
        "label_permutation_null",
        "br_full_pipeline_permutation_harness",
        "workflow_invocation",
        "raw_inputs",
        "pipeline_invocation_sha256",
        "Smoke",
        "Dev",
        "Release",
    }:
        assert expected in text
