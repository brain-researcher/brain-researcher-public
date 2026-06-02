from brain_researcher.services.br_kg.etl.loaders.scientific_review_failure_mode_registry_loader import (
    build_graph_payload,
    load_registry,
    summarize_payload,
)


def test_failure_mode_registry_materializes_queryable_kg_payload():
    registry = load_registry()
    payload = build_graph_payload(registry)
    summary = summarize_payload(payload)

    assert summary["node_types"]["ReviewRuleRegistry"] == 1
    assert summary["node_types"]["ReviewRule"] == len(registry.rules)
    assert summary["node_types"]["ReviewRuleGroup"] == (
        len(registry.families) + len(registry.detectors)
    )
    assert summary["edge_types"]["CONTAINS_RULE"] == len(registry.rules)
    assert summary["edge_types"]["IN_RULE_GROUP"] == len(registry.rules) * 2


def test_failure_mode_registry_payload_preserves_seed_failure_modes():
    payload = build_graph_payload(load_registry())
    rules = {
        node["properties"]["rule_id"]: node["properties"]
        for node in payload["nodes"]
        if node["type"] == "ReviewRule"
    }

    fisher_z = rules["REVIEW_VALUEDOMAIN_FISHER_Z_INPUT"]
    assert fisher_z["detector"] == "measured"
    assert fisher_z["gate"] == "execution"
    assert fisher_z["default_action"] == "raise"

    missing_diagnostic = rules["REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"]
    assert missing_diagnostic["detector"] == "coverage"
    assert missing_diagnostic["gate"] == "review"
    assert missing_diagnostic["default_action"] == "block_claim"
