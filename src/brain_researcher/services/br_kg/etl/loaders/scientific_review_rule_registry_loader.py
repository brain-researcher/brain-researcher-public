"""Loader for the scientific-review rule registry KG seed.

The registry is intentionally metadata-first. It makes rule policy, schema
dependencies, lifecycle status, and calibration cases queryable in BR-KG while
keeping execution authority in the existing review gate.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[6]
DEFAULT_REGISTRY_PATH = (
    ROOT / "configs" / "br-kg" / "scientific_review_rule_registry.yaml"
)
DEFAULT_REVIEW_RULES_PATH = ROOT / "configs" / "review_rules.yaml"


def _clean_text(value: object) -> str:
    return str(value).strip()


def _slug(value: object) -> str:
    text = _clean_text(value).lower()
    for old, new in (
        (" ", "_"),
        ("/", "_"),
        (":", "_"),
        ("-", "_"),
        (".", "_"),
        ("+", "_"),
    ):
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    item_key = (
        item.get("id"),
        item.get("type"),
        item.get("source"),
        item.get("target"),
        item.get("properties", {}).get("implementation_rule_id"),
    )
    for existing in items:
        existing_key = (
            existing.get("id"),
            existing.get("type"),
            existing.get("source"),
            existing.get("target"),
            existing.get("properties", {}).get("implementation_rule_id"),
        )
        if existing_key == item_key:
            return
    items.append(item)


def _node(node_id: str, node_type: str, **properties: Any) -> dict[str, Any]:
    props = {"id": node_id, **properties}
    return {"id": node_id, "type": node_type, "properties": props}


def _edge(
    source: str,
    target: str,
    edge_type: str,
    **properties: Any,
) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "type": edge_type,
        "properties": properties,
    }


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    """Load and validate the rule registry YAML."""

    registry_path = Path(path)
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Registry must be a mapping: {registry_path}")
    _validate_registry(data)
    return data


def load_review_rules_config(path: Path | str = DEFAULT_REVIEW_RULES_PATH) -> dict[str, Any]:
    """Load and validate the implemented review-gate rule config."""

    rules_path = Path(path)
    data = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Review rules config must be a mapping: {rules_path}")
    _validate_review_rules_config(data)
    return data


def _validate_registry(registry: dict[str, Any]) -> None:
    if not registry.get("registry_id"):
        raise ValueError("Registry is missing registry_id")

    rules = registry.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Registry must define a non-empty rules list")

    severities = {
        _clean_text(item.get("id")) for item in registry.get("severities", [])
    }
    statuses = {
        _clean_text(item.get("id")) for item in registry.get("lifecycle_statuses", [])
    }
    layers = {
        _clean_text(item.get("id")) for item in registry.get("validity_layers", [])
    }
    tags = {_clean_text(item.get("id")) for item in registry.get("reason_tags", [])}
    groups = {_clean_text(item.get("id")) for item in registry.get("rule_groups", [])}
    sensitivity_templates = {
        _clean_text(item.get("id"))
        for item in registry.get("sensitivity_templates", [])
    }
    modifiers = {
        _clean_text(item.get("id")) for item in registry.get("positive_modifiers", [])
    }

    seen_rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("Each rule must be a mapping")
        rule_id = _clean_text(rule.get("id"))
        if not rule_id:
            raise ValueError("Rule is missing id")
        if rule_id in seen_rule_ids:
            raise ValueError(f"Duplicate rule id: {rule_id}")
        seen_rule_ids.add(rule_id)

        severity = _clean_text(rule.get("severity"))
        if severity not in severities:
            raise ValueError(f"Rule {rule_id} references unknown severity {severity!r}")

        status = _clean_text(rule.get("lifecycle_status"))
        if status not in statuses:
            raise ValueError(
                f"Rule {rule_id} references unknown lifecycle_status {status!r}"
            )

        group = _clean_text(rule.get("group"))
        if group not in groups:
            raise ValueError(f"Rule {rule_id} references unknown group {group!r}")

        for layer in _as_list(rule.get("validity_layers")):
            layer_id = _clean_text(layer)
            if layer_id not in layers:
                raise ValueError(
                    f"Rule {rule_id} references unknown validity layer {layer_id!r}"
                )

        for tag in _as_list(rule.get("reason_tags")):
            tag_id = _clean_text(tag)
            if tag_id not in tags:
                raise ValueError(
                    f"Rule {rule_id} references unknown reason tag {tag_id!r}"
                )

        sensitivity_template = rule.get("sensitivity_template")
        if (
            sensitivity_template
            and _clean_text(sensitivity_template) not in sensitivity_templates
        ):
            raise ValueError(
                f"Rule {rule_id} references unknown sensitivity_template "
                f"{sensitivity_template!r}"
            )

    for case in registry.get("calibration_cases", []) or []:
        case_id = _clean_text(case.get("id"))
        if not case_id:
            raise ValueError("Calibration case is missing id")
        for rule_id in _as_list(case.get("calibrates_rules")):
            if _clean_text(rule_id) not in seen_rule_ids:
                raise ValueError(
                    f"Calibration case {case_id} references unknown rule {rule_id!r}"
                )
        for modifier_id in _as_list(case.get("calibrates_modifiers")):
            if _clean_text(modifier_id) not in modifiers:
                raise ValueError(
                    f"Calibration case {case_id} references unknown modifier {modifier_id!r}"
                )


def _validate_review_rules_config(review_rules: dict[str, Any]) -> None:
    rules = review_rules.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Review rules config must define a non-empty rules list")

    seen_rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("Each review rule must be a mapping")
        rule_id = _clean_text(rule.get("rule_id"))
        if not rule_id:
            raise ValueError("Review rule is missing rule_id")
        if rule_id in seen_rule_ids:
            raise ValueError(f"Duplicate review rule id: {rule_id}")
        seen_rule_ids.add(rule_id)


def build_graph_payload(
    registry: dict[str, Any],
    review_rules_config: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Convert a registry mapping into the generic BR-KG graph payload shape."""

    _validate_registry(registry)
    if review_rules_config is None:
        review_rules_config = load_review_rules_config()
    else:
        _validate_review_rules_config(review_rules_config)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    registry_id = f"review_registry:{registry['registry_id']}"
    _append_unique(
        nodes,
        _node(
            registry_id,
            "ReviewRuleRegistry",
            registry_id=registry["registry_id"],
            title=registry.get("title"),
            version=registry.get("version"),
            document_version=registry.get("document_version"),
            source_document_type=registry.get("source_document_type"),
            scope=registry.get("scope"),
            execution_boundary=registry.get("execution_boundary"),
        ),
    )

    severity_nodes = _add_reference_nodes(
        nodes,
        registry.get("severities", []),
        node_type="ReviewSeverity",
        id_prefix="review_severity",
    )
    status_nodes = _add_reference_nodes(
        nodes,
        registry.get("lifecycle_statuses", []),
        node_type="ReviewLifecycleStatus",
        id_prefix="review_lifecycle_status",
    )
    layer_nodes = _add_reference_nodes(
        nodes,
        registry.get("validity_layers", []),
        node_type="ReviewValidityLayer",
        id_prefix="review_validity_layer",
    )
    tag_nodes = _add_reference_nodes(
        nodes,
        registry.get("reason_tags", []),
        node_type="ReviewReasonTag",
        id_prefix="review_reason_tag",
    )
    group_nodes = _add_reference_nodes(
        nodes,
        registry.get("rule_groups", []),
        node_type="ReviewRuleGroup",
        id_prefix="review_rule_group",
    )
    sensitivity_nodes = _add_reference_nodes(
        nodes,
        registry.get("sensitivity_templates", []),
        node_type="ReviewSensitivityTemplate",
        id_prefix="review_sensitivity_template",
    )
    policy_nodes = _add_reference_nodes(
        nodes,
        registry.get("policy_decisions", []),
        node_type="ReviewPolicyDecision",
        id_prefix="review_policy_decision",
    )
    positive_modifier_nodes = _add_reference_nodes(
        nodes,
        registry.get("positive_modifiers", []),
        node_type="ReviewPositiveModifier",
        id_prefix="review_positive_modifier",
    )

    _add_review_implementation_rules(nodes, edges, review_rules_config)

    for policy_node in policy_nodes.values():
        _append_unique(edges, _edge(registry_id, policy_node, "HAS_POLICY_DECISION"))

    for modifier in registry.get("positive_modifiers", []) or []:
        modifier_key = _clean_text(modifier.get("id"))
        modifier_node = positive_modifier_nodes.get(modifier_key)
        if not modifier_node:
            continue
        _append_unique(edges, _edge(registry_id, modifier_node, "CONTAINS_MODIFIER"))
        for field in _as_list(modifier.get("metadata_fields")):
            field_key = _clean_text(field)
            field_node_id = f"review_schema_field:{field_key}"
            _append_unique(
                nodes,
                _node(field_node_id, "ReviewSchemaField", field_path=field_key),
            )
            _append_unique(edges, _edge(modifier_node, field_node_id, "REQUIRES_FIELD"))

    for rule in registry["rules"]:
        rule_key = _clean_text(rule["id"])
        rule_node_id = f"review_rule:{_slug(rule_key)}"
        _append_unique(
            nodes,
            _node(
                rule_node_id,
                "ReviewRule",
                rule_id=rule_key,
                description=rule.get("description"),
                detection=rule.get("detection"),
                severity=rule.get("severity"),
                lifecycle_status=rule.get("lifecycle_status"),
                novelty=rule.get("novelty"),
                exemptions=rule.get("exemptions", []),
                implementation_rule_ids=rule.get("implementation_rule_ids", []),
            ),
        )
        _append_unique(edges, _edge(registry_id, rule_node_id, "CONTAINS_RULE"))

        severity_node = severity_nodes.get(_clean_text(rule.get("severity")))
        if severity_node:
            _append_unique(edges, _edge(rule_node_id, severity_node, "HAS_SEVERITY"))

        status_node = status_nodes.get(_clean_text(rule.get("lifecycle_status")))
        if status_node:
            _append_unique(
                edges, _edge(rule_node_id, status_node, "HAS_LIFECYCLE_STATUS")
            )

        group_node = group_nodes.get(_clean_text(rule.get("group")))
        if group_node:
            _append_unique(edges, _edge(rule_node_id, group_node, "IN_RULE_GROUP"))

        for layer in _as_list(rule.get("validity_layers")):
            layer_node = layer_nodes.get(_clean_text(layer))
            if layer_node:
                _append_unique(
                    edges, _edge(rule_node_id, layer_node, "HAS_VALIDITY_LAYER")
                )

        for tag in _as_list(rule.get("reason_tags")):
            tag_node = tag_nodes.get(_clean_text(tag))
            if tag_node:
                _append_unique(edges, _edge(rule_node_id, tag_node, "HAS_REASON_TAG"))

        for field in _as_list(rule.get("metadata_fields")):
            field_key = _clean_text(field)
            field_node_id = f"review_schema_field:{field_key}"
            _append_unique(
                nodes,
                _node(field_node_id, "ReviewSchemaField", field_path=field_key),
            )
            _append_unique(edges, _edge(rule_node_id, field_node_id, "REQUIRES_FIELD"))

        for implementation_rule_id in _as_list(rule.get("implementation_rule_ids")):
            impl_key = _clean_text(implementation_rule_id)
            impl_node_id = f"implemented_review_rule:{_slug(impl_key)}"
            _append_unique(
                nodes,
                _node(
                    impl_node_id,
                    "ReviewImplementationRule",
                    rule_id=impl_key,
                    source_path="configs/review_rules.yaml",
                ),
            )
            _append_unique(
                edges,
                _edge(
                    rule_node_id,
                    impl_node_id,
                    "MAPPED_TO_IMPLEMENTATION",
                    implementation_rule_id=impl_key,
                ),
            )

        sensitivity_template = rule.get("sensitivity_template")
        if sensitivity_template:
            template_node = sensitivity_nodes.get(_clean_text(sensitivity_template))
            if template_node:
                _append_unique(
                    edges,
                    _edge(rule_node_id, template_node, "TRIGGERS_SENSITIVITY"),
                )

    for case in registry.get("calibration_cases", []) or []:
        case_key = _clean_text(case["id"])
        case_node_id = f"review_case:{_slug(case_key)}"
        _append_unique(
            nodes,
            _node(
                case_node_id,
                "ReviewCalibrationCase",
                case_id=case_key,
                scenario=case.get("scenario"),
                severity=case.get("severity"),
                novelty=case.get("novelty"),
            ),
        )
        _append_unique(
            edges, _edge(registry_id, case_node_id, "CONTAINS_CALIBRATION_CASE")
        )
        for rule_id in _as_list(case.get("calibrates_rules")):
            rule_node_id = f"review_rule:{_slug(rule_id)}"
            _append_unique(edges, _edge(case_node_id, rule_node_id, "CALIBRATES_RULE"))
        for modifier_id in _as_list(case.get("calibrates_modifiers")):
            modifier_node_id = f"review_positive_modifier:{_slug(modifier_id)}"
            _append_unique(
                edges, _edge(case_node_id, modifier_node_id, "CALIBRATES_MODIFIER")
            )

    return {"nodes": nodes, "edges": edges}


def _add_review_implementation_rules(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    review_rules_config: dict[str, Any],
) -> None:
    """Add every configured review-engine rule as a queryable KG node."""

    rules = review_rules_config.get("rules", []) or []
    catalog_node_id = "review_implementation_catalog:review_rules_yaml"
    _append_unique(
        nodes,
        _node(
            catalog_node_id,
            "ReviewImplementationRuleCatalog",
            catalog_id="review_rules_yaml",
            title="Brain Researcher review gate implementation rules",
            source_path="configs/review_rules.yaml",
            rule_count=len(rules),
        ),
    )

    for rule in rules:
        rule_id = _clean_text(rule["rule_id"])
        impl_node_id = f"implemented_review_rule:{_slug(rule_id)}"
        _append_unique(
            nodes,
            _node(
                impl_node_id,
                "ReviewImplementationRule",
                rule_id=rule_id,
                description=rule.get("description"),
                review_mode=rule.get("review_mode"),
                applies_to=rule.get("applies_to"),
                stage=rule.get("stage"),
                check_fn=rule.get("check_fn"),
                metric=rule.get("metric"),
                comparator=rule.get("comparator"),
                threshold=rule.get("threshold"),
                tool_filter=rule.get("tool_filter"),
                kg_lookup=rule.get("kg_lookup"),
                severity=rule.get("severity"),
                action=rule.get("action"),
                message=rule.get("message"),
                suggested_fix=rule.get("suggested_fix"),
                tags=_as_list(rule.get("tags")),
                reason_tags=_as_list(rule.get("reason_tags")),
                source_path="configs/review_rules.yaml",
            ),
        )
        _append_unique(
            edges,
            _edge(
                catalog_node_id,
                impl_node_id,
                "CONTAINS_IMPLEMENTATION_RULE",
                implementation_rule_id=rule_id,
            ),
        )


def _add_reference_nodes(
    nodes: list[dict[str, Any]],
    items: list[dict[str, Any]],
    *,
    node_type: str,
    id_prefix: str,
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in items or []:
        item_id = _clean_text(item.get("id"))
        node_id = f"{id_prefix}:{_slug(item_id)}"
        lookup[item_id] = node_id
        _append_unique(
            nodes,
            _node(
                node_id,
                node_type,
                **{k: v for k, v in item.items() if k != "id"},
                key=item_id,
            ),
        )
    return lookup


def summarize_payload(payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return compact counts for dry-runs and tests."""

    node_counts = Counter(
        node.get("type", "Entity") for node in payload.get("nodes", [])
    )
    edge_counts = Counter(edge.get("type", "REL") for edge in payload.get("edges", []))
    return {
        "nodes": len(payload.get("nodes", [])),
        "edges": len(payload.get("edges", [])),
        "node_types": dict(sorted(node_counts.items())),
        "edge_types": dict(sorted(edge_counts.items())),
    }


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_REVIEW_RULES_PATH",
    "build_graph_payload",
    "load_registry",
    "load_review_rules_config",
    "summarize_payload",
]
