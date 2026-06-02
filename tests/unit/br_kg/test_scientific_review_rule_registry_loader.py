from __future__ import annotations

import yaml

from brain_researcher.services.br_kg.bulk_loader import EntityValidator
from brain_researcher.services.br_kg.etl.loaders.scientific_review_rule_registry_loader import (
    DEFAULT_REVIEW_RULES_PATH,
    build_graph_payload,
    load_registry,
    load_review_rules_config,
    summarize_payload,
)


def test_registry_loads_and_materializes_queryable_rule_edges() -> None:
    registry = load_registry()
    payload = build_graph_payload(registry)
    summary = summarize_payload(payload)

    assert summary["node_types"]["ReviewRuleRegistry"] == 1
    assert summary["node_types"]["ReviewRule"] >= 70
    assert summary["node_types"]["ReviewImplementationRule"] >= 80
    assert summary["node_types"]["ReviewImplementationRuleCatalog"] == 1
    assert summary["node_types"]["ReviewCalibrationCase"] == 60
    assert summary["node_types"]["ReviewPolicyDecision"] >= 6
    assert summary["node_types"]["ReviewPositiveModifier"] >= 1
    assert summary["node_types"]["ReviewSchemaField"] >= 20

    rule_node = next(
        node
        for node in payload["nodes"]
        if node["id"] == "review_rule:motion_uncontrolled_group_diff"
    )
    assert rule_node["properties"]["severity"] == "BLOCK"
    assert rule_node["properties"]["lifecycle_status"] == "schema_dependent_candidate"

    rule_edges = [
        edge
        for edge in payload["edges"]
        if edge["source"] == "review_rule:motion_uncontrolled_group_diff"
    ]
    assert any(
        edge["type"] == "REQUIRES_FIELD"
        and edge["target"] == "review_schema_field:qc.group_fd_comparison"
        for edge in rule_edges
    )
    assert any(
        edge["type"] == "HAS_REASON_TAG"
        and edge["target"] == "review_reason_tag:confound"
        for edge in rule_edges
    )
    assert any(
        edge["type"] == "HAS_POLICY_DECISION"
        and edge["target"] == "review_policy_decision:prior_conflict_is_not_veto"
        for edge in payload["edges"]
    )
    assert any(
        edge["type"] == "CALIBRATES_MODIFIER"
        and edge["source"] == "review_case:c60"
        and edge["target"] == "review_positive_modifier:bids_stats_models_present"
        for edge in payload["edges"]
    )


def test_registry_maps_implemented_rules_to_existing_review_gate_ids() -> None:
    payload = build_graph_payload(load_registry())

    assert any(
        edge["type"] == "MAPPED_TO_IMPLEMENTATION"
        and edge["source"] == "review_rule:gsr_no_sensitivity"
        and edge["target"] == "implemented_review_rule:review_gsr_sensitivity_package"
        for edge in payload["edges"]
    )
    assert any(
        edge["type"] == "TRIGGERS_SENSITIVITY"
        and edge["source"] == "review_rule:gsr_no_sensitivity"
        and edge["target"] == "review_sensitivity_template:gsr"
        for edge in payload["edges"]
    )


def test_all_review_gate_rules_are_queryable_as_implementation_nodes() -> None:
    registry = load_registry()
    review_rules = load_review_rules_config()
    payload = build_graph_payload(registry, review_rules)
    configured_rule_ids = {
        rule["rule_id"] for rule in review_rules.get("rules", []) if "rule_id" in rule
    }

    implementation_nodes = {
        node["properties"]["rule_id"]: node
        for node in payload["nodes"]
        if node["type"] == "ReviewImplementationRule"
    }
    catalog_edges = [
        edge
        for edge in payload["edges"]
        if edge["type"] == "CONTAINS_IMPLEMENTATION_RULE"
    ]

    assert configured_rule_ids <= set(implementation_nodes)
    assert len(implementation_nodes) == len(configured_rule_ids)
    assert len(catalog_edges) == len(configured_rule_ids)

    tr_low = implementation_nodes["REVIEW_TR_LOW"]["properties"]
    assert tr_low["review_mode"] == "plan"
    assert tr_low["severity"] == "warn"
    assert tr_low["source_path"] == "configs/review_rules.yaml"


def test_implemented_registry_mappings_exist_in_review_rules_config() -> None:
    registry = load_registry()
    review_rules_path = DEFAULT_REVIEW_RULES_PATH
    review_rules = yaml.safe_load(review_rules_path.read_text(encoding="utf-8"))
    configured_rule_ids = {
        rule["rule_id"] for rule in review_rules.get("rules", []) if "rule_id" in rule
    }

    mapped_rule_ids = {
        implementation_rule_id
        for rule in registry["rules"]
        for implementation_rule_id in rule.get("implementation_rule_ids", [])
    }

    assert mapped_rule_ids <= configured_rule_ids


def test_entity_validator_accepts_review_rule_registry_entities() -> None:
    valid_node, node_error = EntityValidator.validate_node(
        {
            "type": "ReviewRule",
            "id": "review_rule:test",
            "rule_id": "TEST_RULE",
        }
    )
    assert valid_node
    assert node_error is None

    valid_catalog_node, catalog_node_error = EntityValidator.validate_node(
        {
            "type": "ReviewImplementationRuleCatalog",
            "id": "review_implementation_catalog:review_rules_yaml",
            "catalog_id": "review_rules_yaml",
        }
    )
    assert valid_catalog_node
    assert catalog_node_error is None

    valid_catalog_rel, catalog_rel_error = EntityValidator.validate_relationship(
        {
            "type": "CONTAINS_IMPLEMENTATION_RULE",
            "source_id": "review_implementation_catalog:review_rules_yaml",
            "target_id": "implemented_review_rule:review_tr_low",
            "confidence": 1.0,
        }
    )
    assert valid_catalog_rel
    assert catalog_rel_error is None

    valid_rel, rel_error = EntityValidator.validate_relationship(
        {
            "type": "REQUIRES_FIELD",
            "source_id": "review_rule:test",
            "target_id": "review_schema_field:model.type",
            "confidence": 1.0,
        }
    )
    assert valid_rel
    assert rel_error is None

    valid_modifier_rel, modifier_rel_error = EntityValidator.validate_relationship(
        {
            "type": "CALIBRATES_MODIFIER",
            "source_id": "review_case:c60",
            "target_id": "review_positive_modifier:bids_stats_models_present",
            "confidence": 1.0,
        }
    )
    assert valid_modifier_rel
    assert modifier_rel_error is None
