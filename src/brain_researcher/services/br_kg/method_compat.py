"""Method-compatibility resolution for the KG query service.

Carved out of ``br_kg/query_service.py`` to start decomposing that ~15k-line
module. Holds the design/method compatibility seed loading, alias indexing,
graph/KG compatibility lookup, and ONVOC design resolution used by
``query_service.get_method_compatibility``.

``query_service`` re-exports these names (``from .method_compat import *``-style
explicit list) so existing ``query_service.<name>`` references keep resolving.
The three generic record helpers (``_as_list`` / ``_rec_get`` /
``_run_with_optional_timeout``) stay in ``query_service`` and are imported back
here; this is import-cycle-safe because ``query_service`` imports this submodule
only AFTER those helpers are defined.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import Any

# NOTE: the generic record helpers (_as_list / _rec_get / _run_with_optional_timeout)
# live in query_service and are imported lazily inside _method_compatibility_graph_lookup
# (the only consumer). A module-top import would create a circular import when
# method_compat is imported before query_service finishes initializing.

logger = logging.getLogger(__name__)


_METHOD_COMPATIBILITY_SEED_PATH = (
    Path(__file__).resolve().parents[4]
    / "configs"
    / "br_kg"
    / "method_compatibility_seed.yaml"
)
_METHOD_COMPATIBILITY_REL_TYPES = (
    "COMPATIBLE_WITH",
    "INCOMPATIBLE_WITH",
    "REQUIRES",
)
_METHOD_COMPATIBILITY_GENERIC_DESIGN_LABELS = {
    "experimental_design",
    "experimentaldesign",
    "design",
    "study_design",
}
_METHOD_COMPATIBILITY_GENERIC_METHOD_LABELS = {
    "statistical_method",
    "statisticalmethod",
    "method",
}


def _normalize_method_compatibility_text(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _build_method_compatibility_alias_index(
    seed: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    def _index_aliases(raw: Any) -> dict[str, str]:
        aliases: dict[str, str] = {}
        if not isinstance(raw, Mapping):
            return aliases
        for canonical, values in raw.items():
            canonical_text = _normalize_method_compatibility_text(str(canonical))
            if not canonical_text:
                continue
            aliases[canonical_text] = canonical_text
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, Iterable):
                continue
            for value in values:
                alias_text = _normalize_method_compatibility_text(str(value))
                if alias_text:
                    aliases[alias_text] = canonical_text
        return aliases

    design_aliases = _index_aliases(seed.get("design_aliases"))
    method_aliases = _index_aliases(seed.get("method_aliases"))
    return design_aliases, method_aliases


def _method_compatibility_aliases_for_canonical(
    aliases: Mapping[str, str],
    canonical: str,
) -> set[str]:
    return {
        alias
        for alias, mapped_canonical in aliases.items()
        if mapped_canonical == canonical and alias
    }


def _method_compatibility_expected_texts(
    *,
    canonical: str,
    aliases: Mapping[str, str],
    generic_texts: Collection[str],
) -> set[str]:
    expected = {canonical}
    expected.update(_method_compatibility_aliases_for_canonical(aliases, canonical))
    return {value for value in expected if value}


def _method_compatibility_node_texts(node: Any) -> set[str]:
    texts: set[str] = set()

    def _add(value: Any) -> None:
        normalized = _normalize_method_compatibility_text(value)
        if normalized:
            texts.add(normalized)

    try:
        if isinstance(node, Mapping):
            items = list(node.items())
        else:
            items = list(dict(node).items())  # type: ignore[arg-type]
    except Exception:
        items = []

    for key, value in items:
        key_norm = _normalize_method_compatibility_text(key)
        if isinstance(value, str):
            _add(value)
        elif isinstance(value, Collection) and not isinstance(value, (str, bytes)):
            for item in value:
                _add(item)
        elif value is not None:
            _add(value)
        if key_norm in {
            "label",
            "labels",
            "name",
            "id",
            "canonical_id",
            "type",
            "kind",
        }:
            _add(value)

    for attr in ("labels", "name", "label", "id", "canonical_id", "type", "kind"):
        try:
            value = getattr(node, attr)
        except Exception:
            continue
        if isinstance(value, str):
            _add(value)
        elif isinstance(value, Collection) and not isinstance(value, (str, bytes)):
            for item in value:
                _add(item)
        elif value is not None:
            _add(value)

    return texts


def _method_compatibility_node_matches(
    node: Any,
    expected_texts: Collection[str],
) -> bool:
    node_texts = _method_compatibility_node_texts(node)
    return any(text in node_texts for text in expected_texts)


def _method_compatibility_graph_node_attrs(graph: Any, node_id: Any) -> dict[str, Any]:
    try:
        node_attrs = graph.nodes[node_id]
    except Exception:
        return {}
    if isinstance(node_attrs, Mapping):
        return dict(node_attrs)
    try:
        return dict(node_attrs)
    except Exception:
        return {}


def _method_compatibility_rule_id(
    canonical_design: str,
    canonical_method: str,
    compatible: bool,
) -> str:
    rule_map = {
        (
            "repeated_measures",
            "paired_t_test",
            True,
        ): "repeated_measures_requires_paired_t_test",
        (
            "repeated_measures",
            "independent_t_test",
            False,
        ): "repeated_measures_blocks_independent_t_test",
        (
            "independent_groups",
            "independent_t_test",
            True,
        ): "independent_groups_supports_independent_t_test",
        (
            "independent_groups",
            "paired_t_test",
            False,
        ): "independent_groups_blocks_paired_t_test",
    }
    return rule_map.get(
        (canonical_design, canonical_method, compatible),
        f"graph_method_compatibility_{canonical_design}_{canonical_method}_{'compatible' if compatible else 'incompatible'}",
    )


def _method_compatibility_payload(
    *,
    design: str,
    method: str,
    canonical_design: str,
    canonical_method: str,
    compatible: bool,
    source: str,
    rationale: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    graph_labels: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "design": {
            "raw": design,
            "canonical": canonical_design,
        },
        "method": {
            "raw": method,
            "canonical": canonical_method,
        },
        "compatible": compatible,
        "verdict": "compatible" if compatible else "incompatible",
        "severity": "ok" if compatible else "error",
        "rule_id": _method_compatibility_rule_id(
            canonical_design, canonical_method, compatible
        ),
        "source": source,
    }
    if rationale:
        payload["rationale"] = rationale
    if evidence:
        payload["evidence"] = dict(evidence)
    if graph_labels:
        payload["graph"] = dict(graph_labels)
    return payload


def _method_compatibility_graph_lookup(
    *,
    db: Any,
    design: str,
    method: str,
    canonical_design: str,
    canonical_method: str,
    design_aliases: Mapping[str, str],
    method_aliases: Mapping[str, str],
) -> dict[str, Any] | None:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _as_list,
        _rec_get,
        _run_with_optional_timeout,
    )

    design_expected = _method_compatibility_expected_texts(
        canonical=canonical_design,
        aliases=design_aliases,
        generic_texts=_METHOD_COMPATIBILITY_GENERIC_DESIGN_LABELS,
    )
    method_expected = _method_compatibility_expected_texts(
        canonical=canonical_method,
        aliases=method_aliases,
        generic_texts=_METHOD_COMPATIBILITY_GENERIC_METHOD_LABELS,
    )

    graph = getattr(db, "graph", None)
    if graph is not None:
        try:
            edges_iter = graph.edges(data=True, keys=True)
        except Exception:
            try:
                edges_iter = (
                    (u, v, None, data) for u, v, data in graph.edges(data=True)
                )
            except Exception:
                edges_iter = ()
        for source_id, target_id, rel_key, rel_data in edges_iter:
            rel_type = _normalize_method_compatibility_text(
                _rec_get(rel_data, "type") or rel_key or _rec_get(rel_data, "label")
            ).upper()
            if rel_type not in _METHOD_COMPATIBILITY_REL_TYPES:
                continue
            source_node = _method_compatibility_graph_node_attrs(graph, source_id)
            target_node = _method_compatibility_graph_node_attrs(graph, target_id)
            forward_matches = _method_compatibility_node_matches(
                source_node, design_expected
            ) and _method_compatibility_node_matches(target_node, method_expected)
            reverse_matches = _method_compatibility_node_matches(
                source_node, method_expected
            ) and _method_compatibility_node_matches(target_node, design_expected)
            if not (forward_matches or reverse_matches):
                continue
            compatible = rel_type != "INCOMPATIBLE_WITH"
            rationale = (
                "Graph-backed compatibility edge indicates this design/method pair is appropriate."
                if compatible
                else "Graph-backed incompatibility edge indicates this design/method pair should be blocked."
            )
            evidence = {
                "relationship_type": rel_type,
                "relationship_direction": (
                    "design_to_method" if forward_matches else "method_to_design"
                ),
                "source_node_id": source_id,
                "target_node_id": target_id,
            }
            return _method_compatibility_payload(
                design=design,
                method=method,
                canonical_design=canonical_design,
                canonical_method=canonical_method,
                compatible=compatible,
                source="graph",
                rationale=rationale,
                evidence=evidence,
                graph_labels={
                    "design_labels": sorted(
                        _method_compatibility_node_texts(source_node)
                    ),
                    "method_labels": sorted(
                        _method_compatibility_node_texts(target_node)
                    ),
                },
            )

    cypher = """
        MATCH (source)-[rel]->(target)
        WHERE type(rel) IN $rel_types
        RETURN source, rel, target
        LIMIT $limit
    """
    try:
        records = _as_list(
            _run_with_optional_timeout(
                db,
                cypher,
                {"rel_types": list(_METHOD_COMPATIBILITY_REL_TYPES), "limit": 100},
                timeout_s=5.0,
            )
        )
    except Exception:
        return None

    for record in records:
        source_node = (
            _rec_get(record, "source")
            or _rec_get(record, "design")
            or _rec_get(record, "a")
        )
        target_node = (
            _rec_get(record, "target")
            or _rec_get(record, "method")
            or _rec_get(record, "b")
        )
        rel = _rec_get(record, "rel") or _rec_get(record, "r")
        rel_type = _normalize_method_compatibility_text(
            _rec_get(rel, "type")
            or _rec_get(record, "rel_type")
            or _rec_get(record, "type")
        ).upper()
        if rel_type not in _METHOD_COMPATIBILITY_REL_TYPES:
            continue

        forward_matches = _method_compatibility_node_matches(
            source_node, design_expected
        ) and _method_compatibility_node_matches(target_node, method_expected)
        reverse_matches = _method_compatibility_node_matches(
            source_node, method_expected
        ) and _method_compatibility_node_matches(target_node, design_expected)
        if not (forward_matches or reverse_matches):
            continue

        compatible = rel_type != "INCOMPATIBLE_WITH"
        rationale = (
            "KG-backed compatibility edge indicates this design/method pair is appropriate."
            if compatible
            else "KG-backed incompatibility edge indicates this design/method pair should be blocked."
        )
        evidence = {
            "relationship_type": rel_type,
            "relationship_direction": (
                "design_to_method" if forward_matches else "method_to_design"
            ),
        }
        source_labels = sorted(_method_compatibility_node_texts(source_node))
        target_labels = sorted(_method_compatibility_node_texts(target_node))
        return _method_compatibility_payload(
            design=design,
            method=method,
            canonical_design=canonical_design,
            canonical_method=canonical_method,
            compatible=compatible,
            source="graph",
            rationale=rationale,
            evidence=evidence,
            graph_labels={
                "design_labels": source_labels if forward_matches else target_labels,
                "method_labels": target_labels if forward_matches else source_labels,
            },
        )

    return None


@functools.lru_cache(maxsize=1)
def _load_method_compatibility_seed() -> dict[str, Any]:
    """Load the curated method-compatibility seed used by B2 v0."""

    try:
        import yaml  # type: ignore

        if not _METHOD_COMPATIBILITY_SEED_PATH.exists():
            return {}
        payload = (
            yaml.safe_load(_METHOD_COMPATIBILITY_SEED_PATH.read_text(encoding="utf-8"))
            or {}
        )
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug(
            "Failed to load method compatibility seed from %s: %s",
            _METHOD_COMPATIBILITY_SEED_PATH,
            exc,
        )
        return {}


def _resolve_design_via_onvoc(
    raw_design: str,
    seed: Mapping[str, Any],
) -> str | None:
    """Attempt to resolve a design label to a canonical key via ONVOC Study Design.

    Uses the ONVOC tree to find the closest matching Study Design node, then maps
    it to a canonical design key via the seed's ``onvoc_design_map``.
    """
    onvoc_design_map = seed.get("onvoc_design_map") or {}
    if not onvoc_design_map:
        return None
    try:
        from brain_researcher.services.br_kg.utils.onvoc_linker import DEFAULT_TREE_PATH
        from brain_researcher.services.br_kg.utils.onvoc_tree import OnvocTree

        tree = OnvocTree.load(DEFAULT_TREE_PATH)
    except Exception:
        return None

    # Get all descendants of ONVOC_0000007 (Study Design)
    study_design_root = "ONVOC_0000007"
    descendants = tree.descendants(study_design_root)
    descendants.add(study_design_root)

    # Build label→id index for study design subtree
    label_to_id: dict[str, str] = {}
    for node_id in descendants:
        node = tree.nodes.get(node_id)
        if node:
            label_to_id[node.label.lower()] = node_id

    if not label_to_id:
        return None

    raw_lower = raw_design.strip().lower()

    # Exact label match
    if raw_lower in label_to_id:
        matched_id = label_to_id[raw_lower]
        return onvoc_design_map.get(matched_id)

    # Fuzzy match via rapidfuzz if available
    try:
        from rapidfuzz import fuzz as _fuzz

        best_score, best_id = 0.0, None
        for label, node_id in label_to_id.items():
            score = _fuzz.QRatio(raw_lower, label)
            if score > best_score:
                best_score, best_id = score, node_id
        if best_score >= 80 and best_id is not None:
            return onvoc_design_map.get(best_id)
    except ImportError:
        # Substring match fallback
        for label, node_id in label_to_id.items():
            if raw_lower in label or label in raw_lower:
                return onvoc_design_map.get(node_id)

    return None
