#!/usr/bin/env python3
"""
Dual Evidence Knowledge Graph Extension

Extends the BR-KG graph database to support dual evidence from both
NiCLIP (brain-language alignment) and LLM (semantic understanding) sources.

This module provides:
1. Dual evidence node types and relationships
2. Evidence aggregation and confidence scoring
3. Conflict detection and resolution
4. Multi-source query capabilities
5. Evidence traceability and provenance

Key Features:
- Evidence nodes with source tracking
- Confidence-weighted relationships
- Cross-validation between sources
- Temporal evidence updates
- Conflict resolution strategies
"""

import json
import logging
from datetime import datetime
from typing import Any

from .graph_database import BRKGGraphDB

logger = logging.getLogger(__name__)


class DualEvidenceGraph(BRKGGraphDB):
    """Extended BR-KG graph with dual evidence support."""

    def __init__(self, db_path: str = "br_kg_dual_evidence.db"):
        """Initialize dual evidence graph database."""
        super().__init__(db_path)

        # Create dual evidence schema
        self._init_dual_evidence_schema()

        logger.info("Dual Evidence Graph initialized")

    def _init_dual_evidence_schema(self):
        """Initialize schema for dual evidence support."""

        # Create evidence-specific constraints
        self.create_constraint("Evidence", "source_id", "UNIQUE")
        self.create_constraint("EvidenceSource", "name", "UNIQUE")
        self.create_constraint("FusedConcept", "fusion_id", "UNIQUE")

        # Create evidence-specific indexes
        self.create_index("Evidence", "source_type")
        self.create_index("Evidence", "confidence_score")
        self.create_index("Evidence", "timestamp")
        self.create_index("FusedConcept", "consensus_confidence")
        self.create_index("ConflictRecord", "conflict_type")

        # Create evidence source nodes if they don't exist
        self._ensure_evidence_sources()

    def _ensure_evidence_sources(self):
        """Ensure evidence source nodes exist."""
        evidence_sources = [
            {
                "name": "NiCLIP",
                "type": "brain_language_alignment",
                "description": "Neuroimaging Contrastive Language-Image Pre-training",
                "version": "1.0",
                "reliability": 0.85,
            },
            {
                "name": "LLM_Semantic",
                "type": "semantic_reasoning",
                "description": "Large Language Model semantic understanding",
                "version": "1.0",
                "reliability": 0.80,
            },
            {
                "name": "GLM_Validation",
                "type": "brain_activation",
                "description": "General Linear Model activation validation",
                "version": "1.0",
                "reliability": 0.90,
            },
        ]

        for source in evidence_sources:
            try:
                self.create_node("EvidenceSource", source)
            except ValueError:
                # Source already exists
                pass

    def create_evidence_node(
        self,
        concept_name: str,
        source_type: str,
        evidence_data: dict[str, Any],
        confidence_score: float,
        coordinates: list[tuple[float, float, float]] | None = None,
        task_context: str | None = None,
    ) -> str:
        """
        Create an evidence node with source tracking.

        Args:
            concept_name: Name of the cognitive concept
            source_type: Type of evidence (niclip, llm, glm)
            evidence_data: Raw evidence data from source
            confidence_score: Confidence score (0-1)
            coordinates: Optional brain coordinates
            task_context: Optional task context

        Returns:
            Evidence node ID
        """

        # Create evidence properties
        properties = {
            "concept_name": concept_name,
            "source_type": source_type,
            "confidence_score": confidence_score,
            "timestamp": datetime.now().isoformat(),
            "evidence_data": json.dumps(evidence_data),
            "task_context": task_context,
        }

        if coordinates:
            properties["coordinates"] = json.dumps(coordinates)
            # Calculate centroid for spatial indexing
            centroid = [
                sum(coord[i] for coord in coordinates) / len(coordinates)
                for i in range(3)
            ]
            properties.update(
                {
                    "centroid_x": centroid[0],
                    "centroid_y": centroid[1],
                    "centroid_z": centroid[2],
                }
            )

        # Create evidence node
        evidence_id = self.create_node("Evidence", properties)

        # Link to evidence source
        source_nodes = self.find_nodes("EvidenceSource", {"type": source_type})
        if source_nodes:
            source_id = source_nodes[0][0]
            self.create_relationship(
                evidence_id,
                source_id,
                "GENERATED_BY",
                {"timestamp": datetime.now().isoformat()},
            )

        # Link to concept if it exists
        concept_nodes = self.find_nodes("Concept", {"name": concept_name})
        if concept_nodes:
            concept_id = concept_nodes[0][0]
            self.create_relationship(
                evidence_id,
                concept_id,
                "SUPPORTS_CONCEPT",
                {
                    "confidence": confidence_score,
                    "source": source_type,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        else:
            # Create concept node if it doesn't exist
            concept_id = self.create_node(
                "Concept", {"name": concept_name, "created_from": source_type}
            )
            self.create_relationship(
                evidence_id,
                concept_id,
                "SUPPORTS_CONCEPT",
                {
                    "confidence": confidence_score,
                    "source": source_type,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        return evidence_id

    def create_fused_concept(
        self,
        concept_name: str,
        niclip_evidence: dict[str, Any] | None = None,
        llm_evidence: dict[str, Any] | None = None,
        fusion_result: dict[str, Any] | None = None,
        coordinates: list[tuple[float, float, float]] | None = None,
    ) -> str:
        """
        Create a fused concept node that combines evidence from multiple sources.

        Args:
            concept_name: Name of the cognitive concept
            niclip_evidence: Evidence from NiCLIP system
            llm_evidence: Evidence from LLM system
            fusion_result: Result from fusion analysis
            coordinates: Brain coordinates for spatial context

        Returns:
            Fused concept node ID
        """

        # Calculate consensus confidence
        confidences = []
        if niclip_evidence and "confidence" in niclip_evidence:
            confidences.append(niclip_evidence["confidence"])
        if llm_evidence and "confidence" in llm_evidence:
            confidences.append(llm_evidence["confidence"])

        consensus_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        # Create fused concept properties
        properties = {
            "concept_name": concept_name,
            "consensus_confidence": consensus_confidence,
            "n_sources": len([e for e in [niclip_evidence, llm_evidence] if e]),
            "timestamp": datetime.now().isoformat(),
        }

        if niclip_evidence:
            properties["niclip_confidence"] = niclip_evidence.get("confidence", 0.0)
            properties["niclip_data"] = json.dumps(niclip_evidence)

        if llm_evidence:
            properties["llm_confidence"] = llm_evidence.get("confidence", 0.0)
            properties["llm_data"] = json.dumps(llm_evidence)

        if fusion_result:
            properties["fusion_data"] = json.dumps(fusion_result)
            properties["fusion_conflicts"] = fusion_result.get("n_conflicts", 0)
            properties["fusion_overlap"] = fusion_result.get("overlap_ratio", 0.0)

        if coordinates:
            properties["coordinates"] = json.dumps(coordinates)
            # Calculate spatial centroid
            centroid = [
                sum(coord[i] for coord in coordinates) / len(coordinates)
                for i in range(3)
            ]
            properties.update(
                {
                    "centroid_x": centroid[0],
                    "centroid_y": centroid[1],
                    "centroid_z": centroid[2],
                }
            )

        # Create fused concept node
        fused_id = self.create_node("FusedConcept", properties)

        # Create evidence nodes and link them
        if niclip_evidence:
            niclip_id = self.create_evidence_node(
                concept_name,
                "brain_language_alignment",
                niclip_evidence,
                niclip_evidence.get("confidence", 0.0),
                coordinates,
            )
            self.create_relationship(
                niclip_id,
                fused_id,
                "CONTRIBUTES_TO",
                {"weight": niclip_evidence.get("confidence", 0.0), "source": "niclip"},
            )

        if llm_evidence:
            llm_id = self.create_evidence_node(
                concept_name,
                "semantic_reasoning",
                llm_evidence,
                llm_evidence.get("confidence", 0.0),
                coordinates,
            )
            self.create_relationship(
                llm_id,
                fused_id,
                "CONTRIBUTES_TO",
                {"weight": llm_evidence.get("confidence", 0.0), "source": "llm"},
            )

        return fused_id

    def record_evidence_conflict(
        self,
        concept_name: str,
        source1_evidence: dict[str, Any],
        source2_evidence: dict[str, Any],
        conflict_type: str,
        conflict_details: dict[str, Any],
    ) -> str:
        """
        Record a conflict between evidence sources.

        Args:
            concept_name: Name of concept with conflicting evidence
            source1_evidence: Evidence from first source
            source2_evidence: Evidence from second source
            conflict_type: Type of conflict (confidence, direction, existence)
            conflict_details: Details about the conflict

        Returns:
            Conflict record node ID
        """

        properties = {
            "concept_name": concept_name,
            "conflict_type": conflict_type,
            "source1_type": source1_evidence.get("source_type", "unknown"),
            "source2_type": source2_evidence.get("source_type", "unknown"),
            "source1_confidence": source1_evidence.get("confidence", 0.0),
            "source2_confidence": source2_evidence.get("confidence", 0.0),
            "confidence_difference": abs(
                source1_evidence.get("confidence", 0.0)
                - source2_evidence.get("confidence", 0.0)
            ),
            "conflict_details": json.dumps(conflict_details),
            "timestamp": datetime.now().isoformat(),
            "resolved": False,
        }

        # Create conflict record
        conflict_id = self.create_node("ConflictRecord", properties)

        # Link to evidence sources if they exist
        evidence_nodes = self.find_nodes("Evidence", {"concept_name": concept_name})
        for evidence_id, evidence_data in evidence_nodes:
            if evidence_data.get("source_type") in [
                source1_evidence.get("source_type"),
                source2_evidence.get("source_type"),
            ]:
                self.create_relationship(
                    conflict_id,
                    evidence_id,
                    "CONFLICTS_WITH",
                    {"severity": conflict_details.get("severity", "medium")},
                )

        return conflict_id

    def find_dual_evidence_concepts(
        self,
        min_consensus_confidence: float = 0.5,
        coordinates: list[tuple[float, float, float]] | None = None,
        radius: float = 10.0,
    ) -> list[dict[str, Any]]:
        """
        Find concepts with evidence from multiple sources.

        Args:
            min_consensus_confidence: Minimum consensus confidence threshold
            coordinates: Optional spatial filter coordinates
            radius: Spatial search radius in mm

        Returns:
            List of fused concepts with dual evidence
        """

        # Find fused concepts meeting criteria
        fused_concepts = []

        for node_id, node_data in self.find_nodes("FusedConcept"):
            # Check consensus confidence threshold
            if node_data.get("consensus_confidence", 0.0) < min_consensus_confidence:
                continue

            # Check source count (must have multiple sources)
            if node_data.get("n_sources", 0) < 2:
                continue

            # Apply spatial filter if coordinates provided
            if coordinates and "coordinates" in node_data:
                concept_coords = json.loads(node_data["coordinates"])
                # Check if any concept coordinate is within radius of any query coordinate
                within_radius = False
                for query_coord in coordinates:
                    for concept_coord in concept_coords:
                        distance = (
                            sum(
                                (a - b) ** 2
                                for a, b in zip(
                                    query_coord, concept_coord, strict=False
                                )
                            )
                            ** 0.5
                        )
                        if distance <= radius:
                            within_radius = True
                            break
                    if within_radius:
                        break

                if not within_radius:
                    continue

            # Get evidence contributions
            contributions = self.find_relationships(
                end_node=node_id, rel_type="CONTRIBUTES_TO"
            )
            evidence_sources = []
            for start_node, _end_node, edge_data in contributions:
                evidence_node = self.get_node(start_node)
                if evidence_node:
                    evidence_sources.append(
                        {
                            "source_type": evidence_node.get("source_type"),
                            "confidence": evidence_node.get("confidence_score"),
                            "weight": edge_data.get("weight", 0.0),
                        }
                    )

            fused_concepts.append(
                {
                    "id": node_id,
                    "concept_name": node_data.get("concept_name"),
                    "consensus_confidence": node_data.get("consensus_confidence"),
                    "evidence_sources": evidence_sources,
                    "fusion_conflicts": node_data.get("fusion_conflicts", 0),
                    "fusion_overlap": node_data.get("fusion_overlap", 0.0),
                    "coordinates": (
                        json.loads(node_data["coordinates"])
                        if "coordinates" in node_data
                        else None
                    ),
                    "properties": node_data,
                }
            )

        # Sort by consensus confidence
        fused_concepts.sort(key=lambda x: x["consensus_confidence"], reverse=True)

        return fused_concepts

    def get_evidence_conflicts(
        self,
        concept_name: str | None = None,
        conflict_type: str | None = None,
        unresolved_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get evidence conflicts, optionally filtered.

        Args:
            concept_name: Filter by concept name
            conflict_type: Filter by conflict type
            unresolved_only: Only return unresolved conflicts

        Returns:
            List of conflict records
        """

        # Build filter criteria
        filters = {}
        if concept_name:
            filters["concept_name"] = concept_name
        if conflict_type:
            filters["conflict_type"] = conflict_type
        if unresolved_only:
            filters["resolved"] = False

        conflicts = []
        for node_id, node_data in self.find_nodes("ConflictRecord", filters):
            # Get linked evidence
            conflict_rels = self.find_relationships(
                start_node=node_id, rel_type="CONFLICTS_WITH"
            )
            evidence_nodes = []
            for _start_node, end_node, edge_data in conflict_rels:
                evidence_node = self.get_node(end_node)
                if evidence_node:
                    evidence_nodes.append(
                        {
                            "id": end_node,
                            "source_type": evidence_node.get("source_type"),
                            "confidence": evidence_node.get("confidence_score"),
                            "severity": edge_data.get("severity"),
                        }
                    )

            conflicts.append(
                {
                    "id": node_id,
                    "concept_name": node_data.get("concept_name"),
                    "conflict_type": node_data.get("conflict_type"),
                    "confidence_difference": node_data.get("confidence_difference"),
                    "details": json.loads(node_data.get("conflict_details", "{}")),
                    "evidence": evidence_nodes,
                    "timestamp": node_data.get("timestamp"),
                    "resolved": node_data.get("resolved", False),
                }
            )

        # Sort by confidence difference (most severe first)
        conflicts.sort(key=lambda x: x["confidence_difference"], reverse=True)

        return conflicts

    def resolve_conflict(
        self, conflict_id: str, resolution_method: str, resolution_data: dict[str, Any]
    ) -> bool:
        """
        Mark a conflict as resolved with resolution details.

        Args:
            conflict_id: ID of conflict record to resolve
            resolution_method: Method used to resolve (manual, automatic, etc.)
            resolution_data: Data about the resolution

        Returns:
            Success status
        """

        conflict_node = self.get_node(conflict_id)
        if not conflict_node:
            logger.error(f"Conflict node {conflict_id} not found")
            return False

        # Update conflict node
        self.graph.nodes[conflict_id].update(
            {
                "resolved": True,
                "resolution_method": resolution_method,
                "resolution_data": json.dumps(resolution_data),
                "resolution_timestamp": datetime.now().isoformat(),
            }
        )

        # Save to database
        labels = conflict_node.get("labels", ["ConflictRecord"])
        updated_props = dict(self.graph.nodes[conflict_id])
        self._save_node(conflict_id, labels, updated_props)

        logger.info(
            f"Resolved conflict {conflict_id} using method: {resolution_method}"
        )
        return True

    def get_dual_evidence_stats(self) -> dict[str, Any]:
        """Get statistics about dual evidence in the graph."""

        base_stats = self.get_stats()

        # Count evidence-specific nodes
        evidence_count = self.get_node_count("Evidence")
        fused_concept_count = self.get_node_count("FusedConcept")
        conflict_count = self.get_node_count("ConflictRecord")

        # Count by evidence source
        source_counts = {}
        for _node_id, node_data in self.find_nodes("Evidence"):
            source_type = node_data.get("source_type", "unknown")
            source_counts[source_type] = source_counts.get(source_type, 0) + 1

        # Count conflicts by type
        conflict_types = {}
        for _node_id, node_data in self.find_nodes("ConflictRecord"):
            conflict_type = node_data.get("conflict_type", "unknown")
            conflict_types[conflict_type] = conflict_types.get(conflict_type, 0) + 1

        # Calculate confidence distributions
        confidence_scores = []
        for _node_id, node_data in self.find_nodes("FusedConcept"):
            conf = node_data.get("consensus_confidence", 0.0)
            confidence_scores.append(conf)

        confidence_stats = {}
        if confidence_scores:
            confidence_stats = {
                "mean": sum(confidence_scores) / len(confidence_scores),
                "min": min(confidence_scores),
                "max": max(confidence_scores),
                "count": len(confidence_scores),
            }

        dual_evidence_stats = {
            "evidence_nodes": evidence_count,
            "fused_concepts": fused_concept_count,
            "conflict_records": conflict_count,
            "evidence_by_source": source_counts,
            "conflicts_by_type": conflict_types,
            "consensus_confidence_stats": confidence_stats,
        }

        # Merge with base stats
        base_stats["dual_evidence"] = dual_evidence_stats

        return base_stats


# Example usage
if __name__ == "__main__":
    # Initialize dual evidence graph
    graph = DualEvidenceGraph("test_dual_evidence.db")

    # Example: Create fused concept with dual evidence
    niclip_evidence = {
        "confidence": 0.85,
        "spatial_score": 0.9,
        "source_type": "brain_language_alignment",
        "task_priors": [0.002, 0.003, 0.001],
    }

    llm_evidence = {
        "confidence": 0.75,
        "semantic_score": 0.8,
        "source_type": "semantic_reasoning",
        "task_concepts": ["working memory", "cognitive control"],
    }

    fusion_result = {
        "consensus_confidence": 0.80,
        "n_conflicts": 1,
        "overlap_ratio": 0.6,
    }

    # Create fused concept
    fused_id = graph.create_fused_concept(
        "working memory",
        niclip_evidence=niclip_evidence,
        llm_evidence=llm_evidence,
        fusion_result=fusion_result,
        coordinates=[(-44, 36, 20), (44, 36, 20)],
    )

    print(f"Created fused concept: {fused_id}")

    # Record a conflict
    conflict_id = graph.record_evidence_conflict(
        "attention",
        {"source_type": "brain_language_alignment", "confidence": 0.9},
        {"source_type": "semantic_reasoning", "confidence": 0.4},
        "confidence",
        {"severity": "high", "difference": 0.5},
    )

    print(f"Recorded conflict: {conflict_id}")

    # Get dual evidence concepts
    dual_concepts = graph.find_dual_evidence_concepts(min_consensus_confidence=0.7)
    print(f"Found {len(dual_concepts)} dual evidence concepts")

    # Get stats
    stats = graph.get_dual_evidence_stats()
    print("Dual Evidence Graph Stats:")
    print(f"Evidence nodes: {stats['dual_evidence']['evidence_nodes']}")
    print(f"Fused concepts: {stats['dual_evidence']['fused_concepts']}")
    print(f"Conflicts: {stats['dual_evidence']['conflict_records']}")

    graph.close()
    print("Dual evidence graph test completed!")
