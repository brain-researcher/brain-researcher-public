"""KG payload adapter for the scientific-review failure-mode registry."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from brain_researcher.services.review.failure_mode_registry import (
    DEFAULT_REGISTRY_PATH,
    FailureModeRegistry,
    load_failure_mode_registry,
)


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


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> FailureModeRegistry:
    """Load the validated failure-mode registry."""

    return load_failure_mode_registry(Path(path))


def build_graph_payload(
    registry: FailureModeRegistry | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build a lightweight KG payload from the failure-mode registry."""

    registry = registry or load_registry()
    registry_node_id = f"review_rule_registry:{_slug(registry.registry_id)}"
    source_path = _display_path(registry.path)
    nodes: list[dict[str, Any]] = [
        _node(
            registry_node_id,
            "ReviewRuleRegistry",
            registry_id=registry.registry_id,
            title=registry.title,
            schema_version=registry.schema_version,
            source_path=source_path,
            registry_kind="failure_mode",
        )
    ]
    edges: list[dict[str, Any]] = []

    family_nodes = {
        family: f"review_rule_group:failure_family_{_slug(family)}"
        for family in registry.families
    }
    for family, node_id in family_nodes.items():
        nodes.append(
            _node(
                node_id,
                "ReviewRuleGroup",
                group_id=f"failure_family:{family}",
                label=family,
                group_kind="failure_family",
            )
        )

    detector_nodes = {
        detector: f"review_rule_group:failure_detector_{_slug(detector)}"
        for detector in registry.detectors
    }
    for detector, node_id in detector_nodes.items():
        spec = registry.detectors.get(detector) or {}
        nodes.append(
            _node(
                node_id,
                "ReviewRuleGroup",
                group_id=f"failure_detector:{detector}",
                label=detector,
                group_kind="failure_detector",
                runs_at=spec.get("runs_at") if isinstance(spec, dict) else None,
                description=spec.get("desc") if isinstance(spec, dict) else None,
            )
        )

    for rule in registry.rules:
        rule_node_id = f"review_rule:failure_mode_{_slug(rule.id)}"
        nodes.append(
            _node(
                rule_node_id,
                "ReviewRule",
                rule_id=rule.id,
                description=rule.what,
                family=rule.family,
                detector=rule.detect,
                gate=rule.gate,
                severity=rule.severity,
                default_action=rule.default_action,
                silent=rule.silent,
                inflates=rule.inflates,
                evidence=rule.evidence,
                prevent=rule.prevent,
                fixture=rule.fixture,
                source_registry_id=registry.registry_id,
                lifecycle_status="candidate",
            )
        )
        edges.append(
            _edge(
                registry_node_id,
                rule_node_id,
                "CONTAINS_RULE",
                registry_kind="failure_mode",
            )
        )
        edges.append(_edge(rule_node_id, family_nodes[rule.family], "IN_RULE_GROUP"))
        edges.append(_edge(rule_node_id, detector_nodes[rule.detect], "IN_RULE_GROUP"))

    return {"nodes": nodes, "edges": edges}


def summarize_payload(
    payload: dict[str, list[dict[str, Any]]],
) -> dict[str, Counter[str]]:
    """Return node and edge type counts for tests and ingestion previews."""

    return {
        "node_types": Counter(node["type"] for node in payload.get("nodes", [])),
        "edge_types": Counter(edge["type"] for edge in payload.get("edges", [])),
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(path.parents[2]))
    except Exception:
        return str(path)


__all__ = ["build_graph_payload", "load_registry", "summarize_payload"]
