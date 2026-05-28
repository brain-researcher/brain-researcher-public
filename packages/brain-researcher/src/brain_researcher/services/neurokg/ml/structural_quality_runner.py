"""Runner utilities for the BR-KG structural quality benchmark."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from brain_researcher.services.neurokg import query_service
from brain_researcher.services.neurokg.text_v1 import (
    DEFAULT_TEXT_V1_MODEL,
    TEXT_V1_TEMPLATE_VERSION,
    create_text_v1_representation,
)

from .structural_quality_benchmark import (
    StructuralQualityBenchmarkConfig,
    run_structural_quality_benchmark,
)

logger = logging.getLogger(__name__)

DEFAULT_EDGE_TYPES = [
    "MEASURES",
    "BELONGS_TO_FAMILY",
    "REPORTS_CLAIM",
    "SUPPORTS",
]
DEFAULT_RELATION_SIGNATURES = {
    "MEASURES": {"source_types": ["Task"], "target_types": ["Concept"]},
    "BELONGS_TO_FAMILY": {"source_types": ["Task"], "target_types": ["TaskFamily"]},
    "REPORTS_CLAIM": {"source_types": ["Publication"], "target_types": ["Claim"]},
    "SUPPORTS": {"source_types": ["EvidenceSpan"], "target_types": ["Claim"]},
}
STRUCTURAL_QUALITY_PROFILES: dict[str, dict[str, Any]] = {
    "task_structure_neurostore_main": {
        "description": "Neurostore task-family structural benchmark on curated BELONGS_TO_FAMILY links.",
        "edge_types": ["BELONGS_TO_FAMILY"],
        "feature_source": "encoder_text_v1",
        "source_node_property_filters": {
            "BELONGS_TO_FAMILY": {"source": ["neurostore"]},
        },
        "edge_property_filters": {
            "BELONGS_TO_FAMILY": {
                "source": ["task_family_matcher_backfill"],
                "match_method": [
                    "exact_alias",
                    "aggressive_fuzzy_guarded",
                    "forced_best_candidate",
                ],
            }
        },
        "exclude_target_node_ids": {
            "BELONGS_TO_FAMILY": ["tf_uncategorized"],
        },
        "edge_sampling": {
            "BELONGS_TO_FAMILY": "balance_by_target",
        },
    },
    "task_structure_neurostore_strict": {
        "description": "Neurostore task benchmark with stricter BELONGS_TO_FAMILY match methods only.",
        "edge_types": ["BELONGS_TO_FAMILY"],
        "feature_source": "encoder_text_v1",
        "source_node_property_filters": {
            "BELONGS_TO_FAMILY": {"source": ["neurostore"]},
        },
        "edge_property_filters": {
            "BELONGS_TO_FAMILY": {
                "source": ["task_family_matcher_backfill"],
                "match_method": ["exact_alias", "aggressive_fuzzy_guarded"],
            }
        },
        "exclude_target_node_ids": {
            "BELONGS_TO_FAMILY": ["tf_uncategorized"],
        },
        "edge_sampling": {
            "BELONGS_TO_FAMILY": "balance_by_target",
        },
    },
    "task_structure_cogat_external": {
        "description": "External/generalization task benchmark on cognitive_atlas_niclip tasks.",
        "edge_types": ["MEASURES", "BELONGS_TO_FAMILY"],
        "feature_source": "encoder_text_v1",
        "source_node_property_filters": {
            "MEASURES": {"source": ["cognitive_atlas_niclip"]},
            "BELONGS_TO_FAMILY": {"source": ["cognitive_atlas_niclip"]},
        },
        "edge_property_filters": {
            "BELONGS_TO_FAMILY": {
                "source": ["task_family_matcher_backfill"],
                "match_method": [
                    "exact_alias",
                    "aggressive_fuzzy_guarded",
                    "forced_best_candidate",
                ],
            }
        },
        "exclude_target_node_ids": {
            "BELONGS_TO_FAMILY": ["tf_uncategorized"],
        },
        "edge_sampling": {
            "BELONGS_TO_FAMILY": "balance_by_target",
        },
    },
    "task_structure_taxonomy_sanity": {
        "description": "Sanity slice for taxonomy-authored task-family assignments.",
        "edge_types": ["BELONGS_TO_FAMILY"],
        "feature_source": "encoder_text_v1",
        "source_node_property_filters": {
            "BELONGS_TO_FAMILY": {"source": ["task_families", "taxonomy_surface_rules"]},
        },
        "target_node_property_filters": {},
        "edge_sampling": {
            "BELONGS_TO_FAMILY": "balance_by_target",
        },
    },
    "claim_spine_main": {
        "description": "Claim-spine structural benchmark on publication/claim/evidence relations.",
        "edge_types": ["REPORTS_CLAIM", "SUPPORTS"],
        "feature_source": "encoder_text_v1",
    },
}

_SAFE_REL_TYPE = re.compile(r"^[A-Z0-9_]+$")
_VALID_FEATURE_SOURCES = {
    "auto",
    "hashed",
    "cache_text_v1",
    "neo4j_text_v1",
    "encoder_text_v1",
}
_NODE_TYPE_PRIORITY = [
    "Task",
    "TaskDef",
    "TaskSpec",
    "Concept",
    "Construct",
    "Tool",
    "ToolFamily",
    "Claim",
    "EvidenceSpan",
    "Publication",
]

@dataclass
class StructuralQualitySliceExportConfig:
    """Configuration for exporting a fixed graph slice."""

    edge_types: list[str]
    limit_per_edge_type: int = 250
    include_closure: bool = True
    feature_dim: int = 64
    feature_source: str = "auto"
    profile_name: Optional[str] = None
    relation_signatures: Optional[dict[str, dict[str, list[str]]]] = None
    source_node_property_filters: Optional[dict[str, dict[str, list[str]]]] = None
    target_node_property_filters: Optional[dict[str, dict[str, list[str]]]] = None
    edge_property_filters: Optional[dict[str, dict[str, list[str]]]] = None
    exclude_target_node_ids: Optional[dict[str, list[str]]] = None
    edge_sampling: Optional[dict[str, str]] = None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "iso_format"):
        try:
            return value.iso_format()
        except Exception:
            pass
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        return str(value)
    return value


def _validate_edge_types(edge_types: list[str]) -> list[str]:
    validated = []
    for edge_type in edge_types:
        if not _SAFE_REL_TYPE.fullmatch(edge_type):
            raise ValueError(f"Unsafe relationship type: {edge_type}")
        validated.append(edge_type)
    return validated


def _validate_feature_source(feature_source: str) -> str:
    if feature_source not in _VALID_FEATURE_SOURCES:
        allowed = ", ".join(sorted(_VALID_FEATURE_SOURCES))
        raise ValueError(f"Unsupported feature_source={feature_source!r}; expected one of {allowed}")
    return feature_source


def get_structural_quality_profile(profile_name: str) -> dict[str, Any]:
    try:
        return STRUCTURAL_QUALITY_PROFILES[profile_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(STRUCTURAL_QUALITY_PROFILES))
        raise ValueError(f"Unknown structural quality profile {profile_name!r}; expected one of {allowed}") from exc


def _node_external_id(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("id") or node.get("node_id") or node.get("name"))
    props = dict(node)
    return str(props.get("id") or getattr(node, "element_id"))


def _node_element_id(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("element_id") or node.get("id") or node.get("node_id"))
    return str(getattr(node, "element_id"))


def _node_labels(node: Any) -> list[str]:
    if isinstance(node, dict):
        labels = node.get("labels") or []
        return [str(label) for label in labels]
    return sorted(getattr(node, "labels", []))


def _node_properties(node: Any) -> dict[str, Any]:
    if isinstance(node, dict):
        return dict(node.get("properties") or {})
    return dict(node)


def _primary_node_type(labels: list[str], properties: dict[str, Any]) -> str:
    explicit = properties.get("node_type") or properties.get("type")
    if explicit:
        return str(explicit)
    for candidate in _NODE_TYPE_PRIORITY:
        if candidate in labels:
            return candidate
    return labels[0] if labels else "Unknown"


def _node_text(node_payload: dict[str, Any]) -> str:
    text = create_text_v1_representation(
        node_payload.get("node_type", "Unknown"),
        node_payload.get("properties", {}),
    )
    return re.sub(r"\s+", " ", text).strip()


def _matches_signature(
    source_payload: dict[str, Any],
    target_payload: dict[str, Any],
    signature: Optional[dict[str, list[str]]],
) -> bool:
    if not signature:
        return True

    source_type = _primary_node_type(source_payload.get("labels", []), source_payload.get("properties", {}))
    target_type = _primary_node_type(target_payload.get("labels", []), target_payload.get("properties", {}))
    allowed_sources = set(signature.get("source_types") or [])
    allowed_targets = set(signature.get("target_types") or [])

    if allowed_sources and source_type not in allowed_sources:
        return False
    if allowed_targets and target_type not in allowed_targets:
        return False
    return True


def _matches_property_filters(
    properties: dict[str, Any],
    property_filters: Optional[dict[str, list[str]]],
) -> bool:
    if not property_filters:
        return True
    for key, allowed_values in property_filters.items():
        raw_value = properties.get(key)
        if isinstance(raw_value, list):
            candidate_values = {str(item) for item in raw_value if item is not None}
        elif raw_value is None:
            candidate_values = set()
        else:
            candidate_values = {str(raw_value)}
        if not candidate_values.intersection(str(value) for value in allowed_values):
            return False
    return True


def _sample_relation_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    strategy: str,
) -> list[dict[str, Any]]:
    if limit <= 0 or len(rows) <= limit:
        return rows
    if strategy != "balance_by_target":
        return rows[:limit]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["edge_payload"]["target"]), []).append(row)

    per_target_limit = max(1, int(np.ceil(limit / max(1, len(grouped)))))
    selected: list[dict[str, Any]] = []
    leftovers: list[dict[str, Any]] = []
    for target in sorted(grouped):
        group = grouped[target]
        selected.extend(group[:per_target_limit])
        leftovers.extend(group[per_target_limit:])
    if len(selected) < limit:
        selected.extend(leftovers[: limit - len(selected)])
    return selected[:limit]


def _hash_text_to_vector(text: str, dim: int) -> list[float]:
    if dim <= 0:
        raise ValueError("feature dimension must be positive")
    vector = np.zeros(dim, dtype=float)
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    if not tokens:
        return vector.tolist()
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector.tolist()


def _coerce_numeric_vector(value: Any) -> Optional[np.ndarray]:
    if value is None or isinstance(value, (str, bytes, dict)):
        return None
    try:
        array = np.asarray(value, dtype=float)
    except Exception:
        return None
    if array.ndim != 1 or array.size == 0:
        return None
    if np.isnan(array).any():
        return None
    return array.astype(float)


def _collect_neo4j_text_v1_features(
    nodes: list[dict[str, Any]],
) -> tuple[dict[str, np.ndarray], Optional[int]]:
    features: dict[str, np.ndarray] = {}
    dims: set[int] = set()
    for node in nodes:
        vector = _coerce_numeric_vector(node.get("properties", {}).get("embedding_text_v1"))
        if vector is None:
            continue
        features[node["id"]] = vector
        dims.add(int(vector.shape[0]))
    if len(dims) == 1:
        return features, next(iter(dims))
    return {}, None


def _encode_text_v1_features(
    nodes: list[dict[str, Any]],
    *,
    model_name: str = DEFAULT_TEXT_V1_MODEL,
    batch_size: int = 32,
) -> tuple[dict[str, np.ndarray], int]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device="cpu")
    texts = [node["text"] for node in nodes]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    feature_map = {
        node["id"]: np.asarray(vector, dtype=float) for node, vector in zip(nodes, embeddings, strict=True)
    }
    return feature_map, int(embeddings.shape[1])


def _load_cached_text_v1_features(
    nodes: list[dict[str, Any]],
) -> tuple[dict[str, np.ndarray], Optional[int], dict[str, int]]:
    from brain_researcher.services.neurokg.vector_search import (
        VectorIndexManager,
        VectorSearchConfig,
    )

    cache_dir = Path("data/neurokg/vector_cache/sbert")
    config = VectorSearchConfig(cache_dir=str(cache_dir), enable_gpu=False, enable_cache=False)
    manager = VectorIndexManager(config, skip_load=False)

    row_index_by_key: dict[tuple[str, str], int] = {}
    coverage_by_type: dict[str, int] = {}
    dims: set[int] = set()

    for node_type, rows in manager.metadata.items():
        index = manager.indices.get(node_type)
        if index is None:
            continue
        for row_index, row in enumerate(rows):
            key = (str(node_type), str(row.get("node_id")))
            row_index_by_key.setdefault(key, row_index)

    feature_map: dict[str, np.ndarray] = {}
    for node in nodes:
        key = (node["node_type"], node["id"])
        row_index = row_index_by_key.get(key)
        index = manager.indices.get(node["node_type"])
        if row_index is None or index is None:
            continue
        try:
            vector = np.asarray(index.reconstruct(row_index), dtype=float)
        except Exception:
            continue
        feature_map[node["id"]] = vector
        dims.add(int(vector.shape[0]))
        coverage_by_type[node["node_type"]] = coverage_by_type.get(node["node_type"], 0) + 1

    if len(dims) != 1:
        return {}, None, coverage_by_type
    return feature_map, next(iter(dims)), coverage_by_type


def build_benchmark_graph_slice(
    raw_slice: dict[str, Any], *, feature_dim: int = 64, feature_source: str = "auto"
) -> dict[str, Any]:
    """Normalize a raw slice into the benchmark graph contract."""
    feature_source = _validate_feature_source(feature_source)

    nodes = []
    for raw_node in raw_slice.get("nodes", []):
        labels = _node_labels(raw_node)
        properties = _node_properties(raw_node)
        node_id = str(raw_node.get("id") if isinstance(raw_node, dict) else _node_external_id(raw_node))
        node_type = _primary_node_type(labels, properties)
        text = _node_text({"node_type": node_type, "properties": properties})
        nodes.append(
            {
                "id": node_id,
                "element_id": str(raw_node.get("element_id") or node_id),
                "labels": labels,
                "properties": properties,
                "node_type": node_type,
                "text": text,
            }
        )

    resolved_feature_mode = f"hashed_text_v1_dim_{feature_dim}"
    feature_fallback_count = 0
    neo4j_feature_map, neo4j_dim = _collect_neo4j_text_v1_features(nodes)
    cached_feature_map: dict[str, np.ndarray] = {}
    cached_dim: Optional[int] = None
    cached_coverage_by_type: dict[str, int] = {}

    if feature_source in {"auto", "cache_text_v1"}:
        try:
            cached_feature_map, cached_dim, cached_coverage_by_type = _load_cached_text_v1_features(nodes)
        except Exception as exc:
            logger.warning("Cached text_v1 feature lookup failed: %s", exc)

    def _assign_from_map(feature_map: dict[str, np.ndarray]) -> int:
        assigned = 0
        for node in nodes:
            vector = feature_map.get(node["id"])
            if vector is not None:
                node["features"] = vector.tolist()
                assigned += 1
        return assigned

    assigned_count = 0
    if feature_source == "cache_text_v1" and cached_feature_map:
        assigned_count = _assign_from_map(cached_feature_map)
        for node in nodes:
            if "features" not in node:
                node["features"] = _hash_text_to_vector(node["text"], feature_dim)
                feature_fallback_count += 1
        if cached_dim is not None:
            resolved_feature_mode = f"cache_text_v1_partial_hashed_fallback_dim_{cached_dim}"
    elif feature_source == "neo4j_text_v1" and neo4j_feature_map:
        assigned_count = _assign_from_map(neo4j_feature_map)
        for node in nodes:
            if "features" not in node:
                node["features"] = _hash_text_to_vector(node["text"], feature_dim)
                feature_fallback_count += 1
        if neo4j_dim is not None and assigned_count == len(nodes):
            resolved_feature_mode = f"neo4j_text_v1_dim_{neo4j_dim}"
        elif neo4j_dim is not None:
            resolved_feature_mode = f"neo4j_text_v1_partial_hashed_fallback_dim_{neo4j_dim}"
    elif feature_source == "encoder_text_v1":
        encoded_feature_map, encoded_dim = _encode_text_v1_features(nodes)
        assigned_count = _assign_from_map(encoded_feature_map)
        resolved_feature_mode = f"encoder_text_v1_dim_{encoded_dim}"
    elif feature_source == "auto":
        assigned_count += _assign_from_map(cached_feature_map)
        assigned_count += _assign_from_map(
            {node_id: vector for node_id, vector in neo4j_feature_map.items() if node_id not in cached_feature_map}
        )
        missing_nodes = [node for node in nodes if "features" not in node]
        encoded_dim: Optional[int] = None
        if missing_nodes:
            try:
                encoded_feature_map, encoded_dim = _encode_text_v1_features(missing_nodes)
                assigned_count += _assign_from_map(encoded_feature_map)
            except Exception as exc:
                logger.warning("text_v1 encoder fallback failed, using hashed features: %s", exc)
        for node in nodes:
            if "features" not in node:
                node["features"] = _hash_text_to_vector(node["text"], feature_dim)
                feature_fallback_count += 1
        mode_parts = []
        if cached_feature_map and cached_dim is not None:
            mode_parts.append(f"cache_text_v1_dim_{cached_dim}")
        if neo4j_feature_map and neo4j_dim is not None:
            mode_parts.append(f"neo4j_text_v1_dim_{neo4j_dim}")
        if encoded_dim is not None:
            mode_parts.append(f"encoder_text_v1_dim_{encoded_dim}")
        if feature_fallback_count:
            mode_parts.append(f"hashed_text_v1_dim_{feature_dim}")
        if mode_parts:
            resolved_feature_mode = "_plus_".join(mode_parts)
    elif feature_source in {"auto", "neo4j_text_v1"} and neo4j_feature_map:
        if len(neo4j_feature_map) == len(nodes) and neo4j_dim is not None:
            assigned_count = _assign_from_map(neo4j_feature_map)
            resolved_feature_mode = f"neo4j_text_v1_dim_{neo4j_dim}"
        else:
            for node in nodes:
                node["features"] = _hash_text_to_vector(node["text"], feature_dim)
    else:
        for node in nodes:
            node["features"] = _hash_text_to_vector(node["text"], feature_dim)

    for node in nodes:
        node.setdefault("features", _hash_text_to_vector(node["text"], feature_dim))

    edges = []
    for raw_edge in raw_slice.get("edges", []):
        edge_type = (
            raw_edge.get("edge_type")
            or raw_edge.get("type")
            or raw_edge.get("relationship_type")
            or "RELATED_TO"
        )
        edges.append(
            {
                "source": str(raw_edge.get("source") or raw_edge.get("start")),
                "target": str(raw_edge.get("target") or raw_edge.get("end")),
                "edge_type": str(edge_type),
                "relation_signature": raw_edge.get("relation_signature"),
                "properties": dict(raw_edge.get("properties") or {}),
            }
        )

    metadata = dict(raw_slice.get("metadata") or {})
    metadata["feature_mode"] = resolved_feature_mode
    metadata["feature_source_requested"] = feature_source
    metadata["feature_source_resolved"] = resolved_feature_mode
    metadata["text_template_version"] = TEXT_V1_TEMPLATE_VERSION
    metadata["text_v1_model"] = (
        DEFAULT_TEXT_V1_MODEL if resolved_feature_mode.startswith("encoder_text_v1") else None
    )
    metadata["feature_stats"] = {
        "total_nodes": len(nodes),
        "assigned_feature_nodes": assigned_count,
        "cache_text_v1_nodes": len(cached_feature_map),
        "cache_text_v1_coverage_by_node_type": cached_coverage_by_type,
        "neo4j_text_v1_nodes": len(neo4j_feature_map),
        "hashed_fallback_nodes": feature_fallback_count,
    }

    return {"metadata": metadata, "nodes": nodes, "edges": edges}


def _serialise_node(node: Any) -> dict[str, Any]:
    properties = _node_properties(node)
    external_id = str(properties.get("id") or _node_element_id(node))
    properties.setdefault("id", external_id)
    return {
        "id": external_id,
        "element_id": _node_element_id(node),
        "labels": _node_labels(node),
        "properties": properties,
    }


def export_fixed_graph_slice(
    *,
    config: Optional[StructuralQualitySliceExportConfig] = None,
    db: Any = None,
) -> dict[str, Any]:
    """Export a fixed relation-aware graph slice from Neo4j."""

    cfg = config or StructuralQualitySliceExportConfig(edge_types=DEFAULT_EDGE_TYPES)
    if cfg.profile_name:
        profile = get_structural_quality_profile(cfg.profile_name)
        if not cfg.edge_types:
            cfg.edge_types = list(profile.get("edge_types") or [])
        if cfg.feature_source == "auto" and profile.get("feature_source"):
            cfg.feature_source = str(profile["feature_source"])
        if cfg.relation_signatures is None:
            cfg.relation_signatures = profile.get("relation_signatures")
        if cfg.source_node_property_filters is None:
            cfg.source_node_property_filters = profile.get("source_node_property_filters")
        if cfg.target_node_property_filters is None:
            cfg.target_node_property_filters = profile.get("target_node_property_filters")
        if cfg.edge_property_filters is None:
            cfg.edge_property_filters = profile.get("edge_property_filters")
        if cfg.exclude_target_node_ids is None:
            cfg.exclude_target_node_ids = profile.get("exclude_target_node_ids")
        if cfg.edge_sampling is None:
            cfg.edge_sampling = profile.get("edge_sampling")
    edge_types = _validate_edge_types(cfg.edge_types)
    relation_signatures = dict(DEFAULT_RELATION_SIGNATURES)
    relation_signatures.update(cfg.relation_signatures or {})
    source_node_property_filters = cfg.source_node_property_filters or {}
    target_node_property_filters = cfg.target_node_property_filters or {}
    edge_property_filters = cfg.edge_property_filters or {}
    exclude_target_node_ids = {
        edge_type: set(node_ids)
        for edge_type, node_ids in (cfg.exclude_target_node_ids or {}).items()
    }
    edge_sampling = cfg.edge_sampling or {}
    client = db or query_service.get_default_db()

    node_store: dict[str, dict[str, Any]] = {}
    selected_element_ids: set[str] = set()
    edge_store: dict[tuple[str, str, str], dict[str, Any]] = {}

    for edge_type in edge_types:
        signature = relation_signatures.get(edge_type)
        params: dict[str, Any] = {}
        signature_clause = ""
        if signature:
            if signature.get("source_types"):
                params["source_types"] = signature["source_types"]
                signature_clause += " AND any(label IN labels(a) WHERE label IN $source_types)"
            if signature.get("target_types"):
                params["target_types"] = signature["target_types"]
                signature_clause += " AND any(label IN labels(b) WHERE label IN $target_types)"
        sampling_strategy = edge_sampling.get(edge_type, "global_limit")
        needs_post_filtering = bool(
            source_node_property_filters.get(edge_type)
            or target_node_property_filters.get(edge_type)
            or edge_property_filters.get(edge_type)
            or exclude_target_node_ids.get(edge_type)
            or sampling_strategy != "global_limit"
        )
        limit_clause = ""
        if not needs_post_filtering:
            params["limit"] = int(cfg.limit_per_edge_type)
            limit_clause = "\n        LIMIT $limit"
        cypher = f"""
        MATCH (a)-[r:`{edge_type}`]->(b)
        WHERE 1 = 1 {signature_clause}
        RETURN a, b, properties(r) AS rel_props
        ORDER BY coalesce(a.name, a.title, a.id, elementId(a)),
                 coalesce(b.name, b.title, b.id, elementId(b))
        {limit_clause}
        """
        relation_rows: list[dict[str, Any]] = []
        for record in client._run(cypher, params):
            node_a = record["a"]
            node_b = record["b"]
            payload_a = _serialise_node(node_a)
            payload_b = _serialise_node(node_b)
            rel_props = dict(record.get("rel_props") or {})
            if not _matches_signature(payload_a, payload_b, signature):
                continue
            if not _matches_property_filters(
                payload_a.get("properties", {}),
                source_node_property_filters.get(edge_type),
            ):
                continue
            if not _matches_property_filters(
                payload_b.get("properties", {}),
                target_node_property_filters.get(edge_type),
            ):
                continue
            if not _matches_property_filters(rel_props, edge_property_filters.get(edge_type)):
                continue
            if payload_b["id"] in exclude_target_node_ids.get(edge_type, set()):
                continue
            relation_rows.append(
                {
                    "source_payload": payload_a,
                    "target_payload": payload_b,
                    "edge_payload": {
                "source": payload_a["id"],
                "target": payload_b["id"],
                "edge_type": edge_type,
                "relation_signature": signature,
                        "properties": rel_props,
                    },
                }
            )

        for row in _sample_relation_rows(
            relation_rows,
            limit=int(cfg.limit_per_edge_type),
            strategy=str(sampling_strategy),
        ):
            payload_a = row["source_payload"]
            payload_b = row["target_payload"]
            edge_payload = row["edge_payload"]
            node_store[payload_a["element_id"]] = payload_a
            node_store[payload_b["element_id"]] = payload_b
            selected_element_ids.add(payload_a["element_id"])
            selected_element_ids.add(payload_b["element_id"])
            edge_store[(payload_a["id"], payload_b["id"], edge_type)] = edge_payload

    if cfg.include_closure and selected_element_ids:
        for edge_type in edge_types:
            signature = relation_signatures.get(edge_type)
            params = {"element_ids": sorted(selected_element_ids)}
            signature_clause = ""
            if signature:
                if signature.get("source_types"):
                    params["source_types"] = signature["source_types"]
                    signature_clause += " AND any(label IN labels(a) WHERE label IN $source_types)"
                if signature.get("target_types"):
                    params["target_types"] = signature["target_types"]
                    signature_clause += " AND any(label IN labels(b) WHERE label IN $target_types)"
            closure_query = f"""
            MATCH (a)-[r:`{edge_type}`]->(b)
            WHERE elementId(a) IN $element_ids
              AND elementId(b) IN $element_ids
              {signature_clause}
            RETURN a, b, properties(r) AS rel_props
            """
            for record in client._run(closure_query, params):
                payload_a = _serialise_node(record["a"])
                payload_b = _serialise_node(record["b"])
                if not _matches_signature(payload_a, payload_b, signature):
                    continue
                node_store[payload_a["element_id"]] = payload_a
                node_store[payload_b["element_id"]] = payload_b
                edge_store[(payload_a["id"], payload_b["id"], edge_type)] = {
                    "source": payload_a["id"],
                    "target": payload_b["id"],
                    "edge_type": edge_type,
                    "relation_signature": signature,
                    "properties": dict(record.get("rel_props") or {}),
                }

    metadata = {
        "slice_kind": "fixed_relation_slice_v1",
        "profile_name": cfg.profile_name,
        "edge_types": edge_types,
        "relation_signatures": {
            edge_type: relation_signatures.get(edge_type) for edge_type in edge_types
        },
        "source_node_property_filters": source_node_property_filters,
        "target_node_property_filters": target_node_property_filters,
        "edge_property_filters": edge_property_filters,
        "exclude_target_node_ids": {
            edge_type: sorted(node_ids) for edge_type, node_ids in exclude_target_node_ids.items()
        },
        "edge_sampling": edge_sampling,
        "limit_per_edge_type": cfg.limit_per_edge_type,
        "include_closure": cfg.include_closure,
        "node_count": len(node_store),
        "edge_count": len(edge_store),
    }
    return {
        "metadata": metadata,
        "nodes": sorted(node_store.values(), key=lambda item: item["id"]),
        "edges": sorted(
            edge_store.values(),
            key=lambda item: (item["edge_type"], item["source"], item["target"]),
        ),
    }


def run_structural_quality_benchmark_from_graph_slice(
    graph_slice: dict[str, Any],
    *,
    output_dir: str,
    benchmark_config: Optional[StructuralQualityBenchmarkConfig] = None,
    feature_dim: int = 64,
    feature_source: str = "auto",
) -> dict[str, Any]:
    """Write a prepared graph slice and its benchmark artifacts to disk."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    prepared_slice = build_benchmark_graph_slice(
        graph_slice,
        feature_dim=feature_dim,
        feature_source=feature_source,
    )
    (output_path / "graph_slice.json").write_text(
        json.dumps(_json_ready(prepared_slice), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    result = run_structural_quality_benchmark(
        prepared_slice,
        config=benchmark_config,
        output_dir=str(output_path),
        graph_metadata=prepared_slice.get("metadata"),
    )
    return {"graph_slice": prepared_slice, "benchmark_result": result}


def export_and_run_structural_quality_benchmark(
    *,
    output_dir: str,
    slice_config: Optional[StructuralQualitySliceExportConfig] = None,
    benchmark_config: Optional[StructuralQualityBenchmarkConfig] = None,
    db: Any = None,
) -> dict[str, Any]:
    """Export a fixed live slice and run the structural quality benchmark."""

    cfg = slice_config or StructuralQualitySliceExportConfig(edge_types=DEFAULT_EDGE_TYPES)
    raw_slice = export_fixed_graph_slice(config=cfg, db=db)
    return run_structural_quality_benchmark_from_graph_slice(
        raw_slice,
        output_dir=output_dir,
        benchmark_config=benchmark_config,
        feature_dim=cfg.feature_dim,
        feature_source=cfg.feature_source,
    )
