from __future__ import annotations

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.services.review.kg_rule_registry import (
    build_external_review_kg_criteria,
    evaluate_kg_review_registry,
    get_implemented_kg_review_rule_mappings,
    get_kg_review_implementation_rule_ids,
    merge_kg_registry_findings,
    record_external_review_rule_feedback,
    summarize_external_review_rule_feedback,
)
from brain_researcher.services.review.rule_engine import get_engine


class _FakeRegistryDb:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.params: dict[str, object] | None = None

    def _run(self, _cypher: str, params: dict[str, object]):
        self.params = params
        return list(self.rows)


class _CaptureDb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _run(self, cypher: str, params: dict[str, object]):
        self.calls.append((cypher, params))
        return []


def _bundle() -> CodeReviewBundle:
    return CodeReviewBundle(
        review_context={
            "selection": {
                "selection_on_test": True,
                "selection_scope": "heldout",
                "best_model": "layer-12",
            }
        },
        kg_context={"analysis_family": "embedding_analysis"},
    )


def test_get_implemented_registry_mappings_from_db() -> None:
    db = _FakeRegistryDb(
        [
            {
                "kg_rule_id": "TEST_SET_MODEL_SELECTION",
                "implementation_rule_id": "REVIEW_NEUROAI_SELECTION_ON_TEST",
            }
        ]
    )

    mappings = get_implemented_kg_review_rule_mappings(db=db)

    assert len(mappings) == 1
    assert mappings[0].kg_rule_id == "TEST_SET_MODEL_SELECTION"
    assert mappings[0].implementation_rule_id == "REVIEW_NEUROAI_SELECTION_ON_TEST"
    assert db.params == {"registry_id": "scientific_review_rule_registry_v1"}


def test_evaluate_kg_registry_dispatches_only_mapped_implemented_rules() -> None:
    db = _FakeRegistryDb(
        [
            {
                "kg_rule_id": "TEST_SET_MODEL_SELECTION",
                "implementation_rule_id": "REVIEW_NEUROAI_SELECTION_ON_TEST",
            },
            {
                "kg_rule_id": "UNCONFIGURED_SPEC_RULE",
                "implementation_rule_id": "REVIEW_NOT_IN_CONFIG",
            },
        ]
    )

    findings, consulted = evaluate_kg_review_registry(
        _bundle(),
        engine=get_engine(),
        db=db,
    )

    assert [finding.rule_id for finding in findings] == [
        "REVIEW_NEUROAI_SELECTION_ON_TEST"
    ]
    assert "TEST_SET_MODEL_SELECTION->REVIEW_NEUROAI_SELECTION_ON_TEST" in consulted
    assert all("REVIEW_NOT_IN_CONFIG" not in item for item in consulted)
    assert any("BRKG scientific-review registry" in item for item in findings[0].kg_evidence)


def test_kg_implementation_catalog_selects_unmapped_review_gate_rules() -> None:
    db = _FakeRegistryDb(
        [
            {
                "implementation_rule_id": "REVIEW_R2_TOO_LOW",
            },
        ]
    )
    bundle = CodeReviewBundle(stats_metrics={"r_squared": 0.01})

    findings, consulted = evaluate_kg_review_registry(
        bundle,
        engine=get_engine(),
        db=db,
    )

    assert [finding.rule_id for finding in findings] == ["REVIEW_R2_TOO_LOW"]
    assert "implementation_catalog->REVIEW_R2_TOO_LOW" in consulted
    assert any(
        "BRKG review implementation catalog selected configured rule" in item
        for item in findings[0].kg_evidence
    )


def test_kg_implementation_catalog_filter_prevents_new_unmapped_findings() -> None:
    db = _FakeRegistryDb(
        [
            {
                "implementation_rule_id": "REVIEW_R2_TOO_LOW",
            },
        ]
    )
    bundle = CodeReviewBundle(stats_metrics={"r_squared": 0.01})

    findings, consulted = evaluate_kg_review_registry(
        bundle,
        engine=get_engine(),
        db=db,
        catalog_rule_ids_filter={"REVIEW_MEAN_FD_HIGH"},
    )

    assert findings == []
    assert "implementation_catalog->REVIEW_R2_TOO_LOW" not in consulted


def test_get_kg_review_implementation_rule_ids_from_db() -> None:
    db = _FakeRegistryDb(
        [
            {"implementation_rule_id": "REVIEW_R2_TOO_LOW"},
            {"implementation_rule_id": "REVIEW_R2_TOO_LOW"},
            {"implementation_rule_id": "REVIEW_MEAN_FD_HIGH"},
        ]
    )

    assert get_kg_review_implementation_rule_ids(db=db) == (
        "REVIEW_R2_TOO_LOW",
        "REVIEW_MEAN_FD_HIGH",
    )


def test_merge_kg_registry_findings_preserves_single_finding_with_kg_evidence() -> None:
    existing = ReviewFinding(
        rule_id="REVIEW_NEUROAI_SELECTION_ON_TEST",
        severity="error",
        action="block",
        message="NeuroAI candidate selection explicitly used held-out or test data.",
        reason_tags=["leakage"],
    )
    kg = existing.model_copy(
        update={
            "kg_evidence": [
                "BRKG scientific-review registry selected implemented rule."
            ],
            "reason_tags": ["leakage", "generalization"],
        }
    )

    merged = merge_kg_registry_findings([existing], [kg])

    assert len(merged) == 1
    assert merged[0].kg_evidence == [
        "BRKG scientific-review registry selected implemented rule."
    ]
    assert merged[0].reason_tags == ["leakage", "generalization"]


def test_build_external_review_kg_criteria_groups_rules_by_existing_axes() -> None:
    db = _FakeRegistryDb(
        [
            {
                "rule_id": "UNCORRECTED_WHOLEBRAIN",
                "description": "Whole-brain uncorrected p-value.",
                "detection": "Missing correction method.",
                "severity": "BLOCK",
                "lifecycle_status": "implemented",
                "validity_layers": ["statistical_validity"],
                "reason_tags": ["null_mismatch"],
                "metadata_fields": ["correction.method"],
                "implementation_rule_ids": ["REVIEW_MASS_UNIVARIATE_UNCORRECTED"],
                "sensitivity_templates": [],
            },
            {
                "rule_id": "REVERSE_INFERENCE",
                "description": "Region-to-process claim without forward evidence.",
                "detection": "Claim extraction.",
                "severity": "WARN",
                "lifecycle_status": "nlp_llm_candidate",
                "validity_layers": ["claim_validity"],
                "reason_tags": ["claim_inflation"],
                "metadata_fields": [],
                "implementation_rule_ids": [],
                "sensitivity_templates": [],
            },
        ]
    )

    criteria = build_external_review_kg_criteria(db=db)

    correctness = criteria["correctness"][0]
    assert correctness["rule_id"] == "UNCORRECTED_WHOLEBRAIN"
    assert correctness["br_executable"] is True
    assert "kg_node_id" in correctness
    assert criteria["judgment"][0]["rule_id"] == "REVERSE_INFERENCE"
    assert criteria["judgment"][0]["br_executable"] is False


def test_summarize_external_review_rule_feedback_resolves_kg_rule_hits() -> None:
    db = _FakeRegistryDb(
        [
            {
                "kg_rule_id": "UNCORRECTED_WHOLEBRAIN",
                "severity": "BLOCK",
                "lifecycle_status": "implemented",
                "implementation_rule_ids": ["REVIEW_MASS_UNIVARIATE_UNCORRECTED"],
            }
        ]
    )
    verdict = {
        "correctness": {
            "findings": [
                {
                    "rule_id": "REVIEW_MASS_UNIVARIATE_UNCORRECTED",
                    "severity": "error",
                    "message": "uncorrected whole-brain result",
                }
            ]
        }
    }

    feedback = summarize_external_review_rule_feedback(verdict, db=db)

    assert feedback["status"] == "ok"
    assert feedback["unknown_rule_ids"] == []
    hit = feedback["kg_rule_hits"][0]
    assert hit["kg_rule_id"] == "UNCORRECTED_WHOLEBRAIN"
    assert hit["kg_node_id"] == "review_rule:uncorrected_wholebrain"


def test_summarize_external_review_rule_feedback_resolves_implementation_hits() -> None:
    db = _FakeRegistryDb(
        [
            {
                "implementation_rule_id": "REVIEW_R2_TOO_LOW",
                "severity": "warn",
                "action": "warn",
                "review_mode": "artifact",
            }
        ]
    )
    verdict = {
        "correctness": {
            "findings": [
                {
                    "rule_id": "REVIEW_R2_TOO_LOW",
                    "severity": "warn",
                    "message": "low R2",
                }
            ]
        }
    }

    feedback = summarize_external_review_rule_feedback(verdict, db=db)

    assert feedback["status"] == "ok"
    assert feedback["unknown_rule_ids"] == []
    hit = feedback["kg_implementation_hits"][0]
    assert hit["implementation_rule_id"] == "REVIEW_R2_TOO_LOW"
    assert hit["kg_node_id"] == "implemented_review_rule:review_r2_too_low"


def test_record_external_review_rule_feedback_links_implementation_hits() -> None:
    db = _CaptureDb()
    feedback = {
        "implementation_catalog_id": "review_rules_yaml",
        "kg_rule_hits": [],
        "kg_implementation_hits": [
            {
                "implementation_rule_id": "REVIEW_R2_TOO_LOW",
                "kg_node_id": "implemented_review_rule:review_r2_too_low",
                "cited_rule_ids": ["REVIEW_R2_TOO_LOW"],
                "severity": "warn",
                "action": "warn",
                "review_mode": "artifact",
            }
        ],
    }

    result = record_external_review_rule_feedback(
        feedback=feedback,
        directive_id="dir1",
        verdict_id="verdict1",
        session_id="session1",
        reviewer="external_agent",
        overall_decision="diagnose",
        db=db,
    )

    assert result["status"] == "recorded"
    assert result["created"] == 1
    assert len(db.calls) == 1
    cypher, params = db.calls[0]
    assert "CITES_IMPLEMENTATION_RULE" in cypher
    assert params["catalog_id"] == "review_rules_yaml"
    rows = params["rows"]
    assert isinstance(rows, list)
    assert rows[0]["implementation_rule_id"] == "REVIEW_R2_TOO_LOW"
