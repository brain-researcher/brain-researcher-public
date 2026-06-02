"""Evidence-path templates + path-element coercion for the BR-KG lens API.

Carved out of ``br_kg/app.py``: the helpers that build the per-label evidence
graph-path templates, compute a path signature, and coerce raw path hops /
nodes / relationships into the normalised shapes the lens evidence endpoints
return. These own no module state; the few shared names they need
(``GENERIC_EVIDENCE_LABELS`` and the ``_canonical_relation_metadata`` /
``_coerce_float_optional`` / ``_normalize_confidence_metadata`` helpers) stay in
``app.py`` and are imported back lazily inside the consuming functions, so the
dependency flows one-way: ``app -> evidence_paths``.

``app.py`` re-exports every name below so existing ``app.<name>`` references and
route handlers keep resolving.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _evidence_path_templates(include_mediated: bool) -> list[dict[str, Any]]:
    from brain_researcher.services.br_kg.app import GENERIC_EVIDENCE_LABELS

    templates: list[dict[str, Any]] = [
        {
            "path_type": "direct_dataset",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["datasets"],
        },
        {
            "path_type": "direct_statmap",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
        },
        {
            "path_type": "direct_task",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["tasks"],
        },
        {
            "path_type": "direct_publication",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["papers"],
        },
        {
            "path_type": "direct_study",
            "match_method": "direct",
            "target_labels": GENERIC_EVIDENCE_LABELS["studies"],
        },
    ]
    if include_mediated:
        templates.extend(
            [
                {
                    "path_type": "via_publication_dataset",
                    "match_method": "publication_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["papers"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["datasets"],
                },
                {
                    "path_type": "via_publication_statmap",
                    "match_method": "publication_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["papers"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
                },
                {
                    "path_type": "via_publication_task",
                    "match_method": "publication_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["papers"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["tasks"],
                },
                {
                    "path_type": "via_study_dataset",
                    "match_method": "study_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["studies"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["datasets"],
                },
                {
                    "path_type": "via_study_statmap",
                    "match_method": "study_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["studies"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["statmaps"],
                },
                {
                    "path_type": "via_study_task",
                    "match_method": "study_mediated",
                    "middle_labels": GENERIC_EVIDENCE_LABELS["studies"],
                    "target_labels": GENERIC_EVIDENCE_LABELS["tasks"],
                },
            ]
        )
    return templates


def _coerce_path_hops(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_path_node(node: Mapping[str, Any]) -> dict[str, Any]:
    labels = node.get("labels")
    if isinstance(labels, list):
        safe_labels = [str(label) for label in labels if label not in (None, "")]
    else:
        safe_labels = []
    return {
        "id": node.get("id"),
        "label": node.get("label"),
        "labels": safe_labels,
    }


def _coerce_path_relationship(rel: Mapping[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.br_kg.app import (
        _canonical_relation_metadata,
        _coerce_float_optional,
        _normalize_confidence_metadata,
    )

    rel_type = rel.get("type")
    rel_conf = _coerce_float_optional(rel.get("confidence"))
    canonical_meta = _canonical_relation_metadata(rel_type)
    confidence_meta = _normalize_confidence_metadata(
        rel_conf,
        rel.get("confidence_tier"),
    )
    confidence_tier = rel.get("confidence_tier")
    if confidence_tier in (None, ""):
        confidence_tier = confidence_meta["confidence_tier"]
    return {
        "type": rel_type,
        "source_id": rel.get("source_id"),
        "target_id": rel.get("target_id"),
        "confidence": rel_conf,
        "confidence_tier": confidence_tier,
        "prov_source": rel.get("prov_source"),
        "matched_via_rel_type": canonical_meta["matched_via_rel_type"],
        "canonical_edge_type": canonical_meta["canonical_edge_type"],
        "confidence_normalized": confidence_meta["confidence_normalized"],
        "approximate_rule_applied": bool(
            canonical_meta["approximate_rule_applied"]
            or confidence_meta["approximate_rule_applied"]
        ),
        "normalization_basis": confidence_meta["normalization_basis"],
    }


def _evidence_path_signature(path_record: Mapping[str, Any]) -> str:
    nodes = path_record.get("nodes") or []
    rels = path_record.get("relationships") or []
    node_ids = [str(node.get("id")) for node in nodes if node.get("id") is not None]
    rel_sig = [
        (
            str(rel.get("type")),
            str(rel.get("source_id")),
            str(rel.get("target_id")),
        )
        for rel in rels
    ]
    return json.dumps(
        {
            "path_type": path_record.get("path_type"),
            "nodes": node_ids,
            "rels": rel_sig,
        },
        sort_keys=True,
    )
