"""Unified Node Matching Service for BR-KG

Implements entity matching, SAME_AS edge creation, and canonical node selection
following schema_catalog.md and invariants.md specifications.

Matching cascade: Exact → Embedding → Fuzzy → Spatial
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

from brain_researcher.services.shared.runtime_semantic import (
    semantic_matching_enabled,
)

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of node matching operation."""

    target_node_id: str
    confidence: float
    method: str  # exact, fuzzy, embedding, spatial
    matched_fields: List[str]
    metadata: Dict[str, Any]


class UnifiedNodeMatcher:
    """Centralized node matching following PRD specifications."""

    STRICT_EVIDENCE_NODE_TYPES = {"Task", "Concept", "Phenotype"}

    def __init__(
        self,
        config_dir: str = "configs/br-kg",
        *,
        enable_semantic: bool | None = None,
    ):
        """Initialize matcher with configuration.

        Args:
            config_dir: Path to config directory
        """
        self.config_dir = Path(config_dir)
        self.enable_semantic = semantic_matching_enabled(enable_semantic, default=True)
        self.edge_scoring = self._load_yaml("edge_scoring.yaml")
        self.thresholds = self._load_yaml("thresholds.yaml")

        # Initialize specialized matchers
        self._init_matchers()

        # Cache for canonical node lookups
        self.canonical_cache = {}

    def _load_yaml(self, filename: str) -> Dict:
        """Load YAML configuration file."""
        path = self.config_dir / filename
        if not path.exists():
            logger.warning(f"Config not found: {path}, using defaults")
            return {}

        with open(path) as f:
            return yaml.safe_load(f)

    def _init_matchers(self):
        """Initialize specialized matchers."""
        if not self.enable_semantic:
            self.task_matcher = None
            self.phenotype_matcher = None
            return
        try:
            from ..utils.task_matcher import TaskMatcher

            self.task_matcher = TaskMatcher()
        except Exception as e:
            logger.warning(f"TaskMatcher not available: {e}")
            self.task_matcher = None

        try:
            from ..utils.phenotype_matcher_fixed import PhenotypeMatcher

            self.phenotype_matcher = PhenotypeMatcher()
        except Exception as e:
            logger.warning(f"PhenotypeMatcher not available: {e}")
            self.phenotype_matcher = None

    def match_node(
        self,
        candidate: Dict[str, Any],
        node_type: str,
        existing_nodes: List[Dict[str, Any]],
    ) -> List[MatchResult]:
        """Match candidate node against existing nodes.

        Args:
            candidate: Node to match
            node_type: Type of node (Task, Concept, etc.)
            existing_nodes: List of existing nodes to match against

        Returns:
            List of MatchResult ordered by confidence (highest first)
        """
        if not existing_nodes:
            return []

        # Get node type config
        node_config = self.edge_scoring.get("node_type_configs", {}).get(node_type, {})
        methods = node_config.get("methods", ["exact", "fuzzy"])
        primary_fields = node_config.get("primary_fields", ["id", "label"])
        threshold = self.thresholds.get("same_as_thresholds", {}).get(node_type, 0.85)

        matches = []

        # Try each matching method in order
        for method in methods:
            if method == "exact":
                matches.extend(
                    self._exact_match(candidate, existing_nodes, primary_fields)
                )
            elif method == "fuzzy":
                matches.extend(
                    self._fuzzy_match(candidate, existing_nodes, primary_fields)
                )
            elif method == "embedding":
                matches.extend(
                    self._embedding_match(candidate, existing_nodes, node_type)
                )
            elif method == "spatial":
                matches.extend(self._spatial_match(candidate, existing_nodes))

        # Aggregate evidence per target and enforce strict mapping acceptance:
        # exact/id OR >=2 method families (reject fuzzy-only/embedding-only).
        grouped_matches: Dict[str, Dict[str, Any]] = {}
        for match in matches:
            if not match.target_node_id:
                continue
            group = grouped_matches.setdefault(
                match.target_node_id,
                {
                    "best_match": match,
                    "methods": set(),
                    "families": set(),
                    "matched_fields": set(),
                },
            )
            group["methods"].add(match.method)
            group["families"].add(self._method_family(match.method))
            group["matched_fields"].update(match.matched_fields)
            if match.confidence > group["best_match"].confidence:
                group["best_match"] = match

        filtered: List[MatchResult] = []
        for target_node_id, group in grouped_matches.items():
            best_match = group["best_match"]
            if best_match.confidence < threshold:
                continue

            evidence_methods = sorted(m for m in group["methods"] if m)
            if not self._is_mapping_acceptable(
                evidence_methods,
                edge_type="SAME_AS",
                node_type=node_type,
            ):
                continue

            metadata = dict(best_match.metadata or {})
            metadata["evidence_methods"] = evidence_methods
            metadata["evidence_families"] = sorted(group["families"])
            metadata["evidence_count"] = len(evidence_methods)
            metadata["node_type"] = node_type

            filtered.append(
                MatchResult(
                    target_node_id=target_node_id,
                    confidence=best_match.confidence,
                    method=self._select_primary_method(
                        evidence_methods, best_match.method
                    ),
                    matched_fields=sorted(group["matched_fields"]),
                    metadata=metadata,
                )
            )

        return sorted(filtered, key=lambda m: m.confidence, reverse=True)

    def _exact_match(
        self, candidate: Dict, existing: List[Dict], fields: List[str]
    ) -> List[MatchResult]:
        """Exact field matching."""
        matches = []

        for node in existing:
            matched_fields = []
            for field in fields:
                if field in candidate and field in node:
                    cand_val = self._normalize_string(str(candidate[field]))
                    node_val = self._normalize_string(str(node[field]))
                    if cand_val == node_val:
                        matched_fields.append(field)

            if matched_fields:
                has_id_signal = any(
                    self._is_id_field(field) for field in matched_fields
                )
                non_id_fields = [
                    field for field in fields if not self._is_id_field(field)
                ]
                matched_non_id_fields = [
                    field for field in matched_fields if field in non_id_fields
                ]
                if has_id_signal:
                    confidence = 1.0
                elif non_id_fields and len(matched_non_id_fields) == len(non_id_fields):
                    # Exact match across all semantic fields (label/definition/etc.) stays high-confidence.
                    confidence = 0.95
                elif len(matched_fields) == len(fields):
                    confidence = 0.95
                else:
                    confidence = 0.8
                matches.append(
                    MatchResult(
                        target_node_id=node.get("id", node.get("uid")),
                        confidence=confidence,
                        method="id" if has_id_signal else "exact",
                        matched_fields=matched_fields,
                        metadata={
                            "match_count": len(matched_fields),
                            "has_id_signal": has_id_signal,
                        },
                    )
                )

        return matches

    def _fuzzy_match(
        self, candidate: Dict, existing: List[Dict], fields: List[str]
    ) -> List[MatchResult]:
        """Fuzzy string matching using Dice coefficient."""
        from rapidfuzz import fuzz

        matches = []
        threshold = (
            self.edge_scoring.get("matching_methods", {})
            .get("fuzzy", {})
            .get("threshold", 0.9)
        )

        for node in existing:
            scores = []
            matched_fields = []

            for field in fields:
                if field in candidate and field in node:
                    cand_str = str(candidate[field])
                    node_str = str(node[field])

                    # Use token sort ratio for better matching
                    score = fuzz.token_sort_ratio(cand_str, node_str) / 100.0

                    if score >= threshold:
                        scores.append(score)
                        matched_fields.append(field)

            if scores:
                confidence = np.mean(scores)
                matches.append(
                    MatchResult(
                        target_node_id=node.get("id", node.get("uid")),
                        confidence=float(confidence),
                        method="fuzzy",
                        matched_fields=matched_fields,
                        metadata={"avg_score": float(confidence)},
                    )
                )

        return matches

    def _embedding_match(
        self, candidate: Dict, existing: List[Dict], node_type: str
    ) -> List[MatchResult]:
        """Semantic embedding matching."""
        if not self.enable_semantic:
            return []
        matches = []

        # Use specialized matchers if available
        if node_type == "Task" and self.task_matcher:
            label = candidate.get("label", candidate.get("name", ""))
            if label:
                results = self.task_matcher.match_candidates(label, top_k=5)
                for res in results:
                    # Find matching existing node
                    for node in existing:
                        if node.get("label") == res["label"]:
                            matches.append(
                                MatchResult(
                                    target_node_id=node.get("id", node.get("uid")),
                                    confidence=res["score"],
                                    method=f"embedding_{res['engine']}",
                                    matched_fields=["label"],
                                    metadata={"engine": res["engine"]},
                                )
                            )
                            break

        return matches

    def _spatial_match(
        self, candidate: Dict, existing: List[Dict]
    ) -> List[MatchResult]:
        """Spatial distance matching for coordinates."""
        matches = []

        if not all(k in candidate for k in ["x", "y", "z"]):
            return matches

        cand_coords = np.array([candidate["x"], candidate["y"], candidate["z"]])
        threshold_mm = self.thresholds.get("spatial_matching", {}).get(
            "coordinate_radius_mm", 8.0
        )

        for node in existing:
            if all(k in node for k in ["x", "y", "z"]):
                node_coords = np.array([node["x"], node["y"], node["z"]])
                distance = np.linalg.norm(cand_coords - node_coords)

                if distance <= threshold_mm:
                    # Linear decay: score = 1 - (d / threshold)
                    confidence = 1.0 - (distance / threshold_mm)
                    matches.append(
                        MatchResult(
                            target_node_id=node.get("id", node.get("uid")),
                            confidence=float(confidence),
                            method="spatial",
                            matched_fields=["x", "y", "z"],
                            metadata={"distance_mm": float(distance)},
                        )
                    )

        return matches

    def create_same_as_edges(
        self, source_id: str, matches: List[MatchResult], graph_db
    ) -> List[str]:
        """Create SAME_AS edges for matched nodes.

        Args:
            source_id: Source node ID
            matches: List of match results
            graph_db: Graph database instance

        Returns:
            List of created edge IDs
        """
        edge_ids = []
        min_confidence = (
            self.edge_scoring.get("edge_rules", {})
            .get("SAME_AS", {})
            .get("min_confidence", 0.90)
        )

        for match in matches:
            if match.confidence < min_confidence:
                continue

            evidence_methods = (
                match.metadata.get("evidence_methods", [])
                if isinstance(match.metadata, dict)
                else []
            )
            if not evidence_methods:
                evidence_methods = [match.method]
            node_type = (
                match.metadata.get("node_type")
                if isinstance(match.metadata, dict)
                else None
            )
            if not self._is_mapping_acceptable(
                evidence_methods,
                edge_type="SAME_AS",
                node_type=node_type,
            ):
                continue

            # Create bidirectional SAME_AS edge
            edge_props = {
                "confidence": match.confidence,
                "method": match.method,
                "matched_fields": match.matched_fields,
                "created_at": datetime.utcnow().isoformat(),
                "provenance": {
                    "source": "UnifiedNodeMatcher",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": match.metadata,
                },
            }

            try:
                # Create edge (bidirectional)
                edge_id = graph_db.create_relationship(
                    source_id, match.target_node_id, "SAME_AS", edge_props
                )
                edge_ids.append(edge_id)

                logger.info(
                    f"Created SAME_AS edge: {source_id} <-> {match.target_node_id} "
                    f"(confidence={match.confidence:.2f}, method={match.method})"
                )
            except Exception as e:
                logger.error(f"Failed to create SAME_AS edge: {e}")

        return edge_ids

    def _is_id_field(self, field: str) -> bool:
        normalized = (field or "").lower()
        return normalized == "id" or normalized.endswith("_id")

    def _method_family(self, method: str) -> str:
        normalized = (method or "").lower()
        if normalized in {"exact", "fuzzy", "id"}:
            return "string"
        if normalized.startswith("embedding"):
            return "semantic"
        if normalized in {"spatial", "overlap"}:
            return "spatial"
        if normalized in {"meta_analytic", "hed_signature"}:
            return "meta"
        return "other"

    def _is_mapping_acceptable(
        self,
        methods: List[str],
        edge_type: str = "SAME_AS",
        node_type: Optional[str] = None,
    ) -> bool:
        """Strict acceptance for SAME_AS/MAPS_TO mappings."""
        _ = edge_type  # Shared rule for SAME_AS/MAPS_TO.
        normalized_methods = {m.lower() for m in methods if m}
        if not normalized_methods:
            return False
        # Keep strict evidence requirements scoped to high-risk semantic mapping types.
        if node_type and node_type not in self.STRICT_EVIDENCE_NODE_TYPES:
            return True
        if "exact" in normalized_methods or "id" in normalized_methods:
            return True
        method_families = {self._method_family(m) for m in normalized_methods}
        return len(method_families) >= 2

    def _select_primary_method(self, methods: List[str], fallback: str) -> str:
        normalized = {(m or "").lower(): m for m in methods}
        if "id" in normalized:
            return normalized["id"]
        if "exact" in normalized:
            return normalized["exact"]
        return fallback

    def select_canonical(self, node_ids: List[str], node_type: str, graph_db) -> str:
        """Select canonical node from cluster following priority rules.

        Args:
            node_ids: List of equivalent node IDs
            node_type: Type of nodes
            graph_db: Graph database instance

        Returns:
            Canonical node ID
        """
        if len(node_ids) == 1:
            return node_ids[0]

        # Get source priority for this node type
        priorities = (
            self.thresholds.get("canonical_selection", {})
            .get("source_priority", {})
            .get(node_type, [])
        )

        # Fetch nodes
        nodes = []
        for nid in node_ids:
            try:
                node = graph_db.get_node(nid)
                if node:
                    nodes.append(node)
            except Exception as e:
                logger.warning(f"Failed to fetch node {nid}: {e}")

        if not nodes:
            return node_ids[0]

        # Apply priority rules
        for source_prefix in priorities:
            for node in nodes:
                node_id = node.get("id", "")
                if node_id.startswith(source_prefix):
                    return node_id

        # Tiebreaker: most connections
        node_degrees = {}
        for node in nodes:
            nid = node.get("id", node.get("uid"))
            try:
                degree = graph_db.graph.degree(nid)
                node_degrees[nid] = degree
            except:
                node_degrees[nid] = 0

        canonical = max(node_degrees.keys(), key=lambda k: node_degrees[k])
        return canonical

    def _normalize_string(self, s: str) -> str:
        """Normalize string for comparison."""
        import re

        # Case fold
        s = s.lower()
        # Remove punctuation
        s = re.sub(r"[^\w\s]", "", s)
        # Remove extra whitespace
        s = " ".join(s.split())
        return s


if __name__ == "__main__":
    # Quick test
    matcher = UnifiedNodeMatcher()

    test_candidate = {
        "id": "test_task_1",
        "label": "N-back task",
        "description": "Working memory task",
    }

    test_existing = [
        {"id": "cogat:nback", "label": "n-back"},
        {"id": "bids:nback_task", "label": "nback task"},
    ]

    matches = matcher.match_node(test_candidate, "Task", test_existing)
    print(f"Found {len(matches)} matches:")
    for m in matches:
        print(f"  {m.target_node_id}: {m.confidence:.2f} via {m.method}")
