#!/usr/bin/env python3
"""
Dual Evidence Knowledge Graph Integrator

Integrates the dual evidence graph with the NiCLIP-LLM fusion system
to provide persistent storage and querying of evidence from multiple sources.

This module provides:
1. Integration between fusion results and knowledge graph
2. Evidence persistence and retrieval
3. Conflict tracking and resolution
4. Multi-source evidence queries
5. Evidence validation and updates

Key Features:
- Automatic storage of fusion results in knowledge graph
- Evidence-based query enhancement
- Conflict detection and tracking
- Evidence provenance and lineage
- Cross-validation between sources
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..mappers.niclip_llm_fusion import CognitiveAnnotationFusion
from ...graph.dual_evidence_graph import DualEvidenceGraph

logger = logging.getLogger(__name__)


class DualEvidenceIntegrator:
    """Integrates fusion system with dual evidence knowledge graph."""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize dual evidence integrator.

        Args:
            db_path: Path to dual evidence database
        """
        if db_path is None:
            # Default to data directory
            db_path = str(Path(__file__).parent.parent.parent.parent.parent.parent /
                         "data" / "br_kg" / "dual_evidence.db")

        self.db_path = db_path
        self.graph = DualEvidenceGraph(db_path)
        self.fusion = CognitiveAnnotationFusion()

        logger.info(f"Dual Evidence Integrator initialized with database: {db_path}")

    def store_fusion_result(
        self,
        contrast_name: str,
        task_name: str,
        coordinates: List[Tuple[float, float, float]],
        fusion_result: Dict[str, Any],
        niclip_data: Optional[Dict[str, Any]] = None,
        llm_data: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Store fusion results in the dual evidence graph.

        Args:
            contrast_name: Name of the contrast/query
            task_name: Name of the task context
            coordinates: Brain coordinates involved
            fusion_result: Result from fusion analysis
            niclip_data: Raw NiCLIP data
            llm_data: Raw LLM data

        Returns:
            List of created fused concept node IDs
        """
        created_nodes = []

        try:
            # Extract constructs from fusion result
            constructs = fusion_result.get("constructs", [])

            for construct in constructs:
                concept_name = construct.get("name", "unknown_concept")

                # Prepare evidence data
                niclip_evidence = None
                if niclip_data and construct.get("niclip_confidence"):
                    niclip_evidence = {
                        "confidence": construct.get("niclip_confidence", 0.0),
                        "spatial_confidence": construct.get("spatial_confidence", 0.0),
                        "source_type": "brain_language_alignment",
                        "raw_data": niclip_data,
                        "contrast": contrast_name,
                        "task": task_name
                    }

                llm_evidence = None
                if llm_data and construct.get("llm_confidence"):
                    llm_evidence = {
                        "confidence": construct.get("llm_confidence", 0.0),
                        "semantic_confidence": construct.get("llm_confidence", 0.0),
                        "source_type": "semantic_reasoning",
                        "raw_data": llm_data,
                        "contrast": contrast_name,
                        "task": task_name
                    }

                # Prepare fusion metadata
                fusion_metadata = {
                    "consensus_confidence": construct.get("confidence", 0.0),
                    "evidence_sources": construct.get("evidence", {}).get("sources", []),
                    "fusion_method": "niclip_llm_weighted",
                    "validation_scores": construct.get("evidence", {}).get("validation", {}),
                    "timestamp": datetime.now().isoformat()
                }

                # Create fused concept node
                fused_id = self.graph.create_fused_concept(
                    concept_name=concept_name,
                    niclip_evidence=niclip_evidence,
                    llm_evidence=llm_evidence,
                    fusion_result=fusion_metadata,
                    coordinates=coordinates
                )

                created_nodes.append(fused_id)

                # Check for conflicts
                self._detect_and_record_conflicts(
                    concept_name,
                    niclip_evidence,
                    llm_evidence,
                    coordinates
                )

            # Store fusion metrics
            if "fusion_metrics" in fusion_result:
                self._store_fusion_metrics(
                    fusion_result["fusion_metrics"],
                    contrast_name,
                    task_name,
                    coordinates
                )

            logger.info(f"Stored {len(created_nodes)} fused concepts in knowledge graph")

        except Exception as e:
            logger.error(f"Error storing fusion result: {e}")

        return created_nodes

    def _detect_and_record_conflicts(
        self,
        concept_name: str,
        niclip_evidence: Optional[Dict[str, Any]],
        llm_evidence: Optional[Dict[str, Any]],
        coordinates: List[Tuple[float, float, float]]
    ):
        """Detect and record conflicts between evidence sources."""

        if not niclip_evidence or not llm_evidence:
            return

        niclip_conf = niclip_evidence.get("confidence", 0.0)
        llm_conf = llm_evidence.get("confidence", 0.0)

        # Confidence conflict detection
        conf_diff = abs(niclip_conf - llm_conf)
        if conf_diff > 0.3:  # Significant confidence difference
            conflict_details = {
                "severity": "high" if conf_diff > 0.5 else "medium",
                "difference": conf_diff,
                "niclip_confidence": niclip_conf,
                "llm_confidence": llm_conf,
                "coordinates": coordinates,
                "detection_method": "confidence_threshold"
            }

            self.graph.record_evidence_conflict(
                concept_name=concept_name,
                source1_evidence=niclip_evidence,
                source2_evidence=llm_evidence,
                conflict_type="confidence",
                conflict_details=conflict_details
            )

            logger.warning(f"Recorded confidence conflict for {concept_name}: "
                          f"NiCLIP={niclip_conf:.2f}, LLM={llm_conf:.2f}")

    def _store_fusion_metrics(
        self,
        fusion_metrics: Dict[str, Any],
        contrast_name: str,
        task_name: str,
        coordinates: List[Tuple[float, float, float]]
    ):
        """Store fusion-level metrics as a separate node."""

        properties = {
            "contrast_name": contrast_name,
            "task_name": task_name,
            "coordinates": json.dumps(coordinates),
            "avg_confidence": fusion_metrics.get("avg_confidence", 0.0),
            "n_conflicts": fusion_metrics.get("n_conflicts", 0),
            "overlap_ratio": fusion_metrics.get("overlap_ratio", 0.0),
            "coverage_ratio": fusion_metrics.get("coverage_ratio", 0.0),
            "consistency_score": fusion_metrics.get("consistency_score", 0.0),
            "timestamp": datetime.now().isoformat()
        }

        # Calculate spatial centroid
        if coordinates:
            centroid = [
                sum(coord[i] for coord in coordinates) / len(coordinates)
                for i in range(3)
            ]
            properties.update({
                "centroid_x": centroid[0],
                "centroid_y": centroid[1],
                "centroid_z": centroid[2]
            })

        metrics_id = self.graph.create_node("FusionMetrics", properties)

        logger.debug(f"Stored fusion metrics node: {metrics_id}")

    def query_dual_evidence_concepts(
        self,
        coordinates: List[Tuple[float, float, float]],
        radius: float = 10.0,
        min_consensus_confidence: float = 0.5,
        require_multiple_sources: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Query for concepts with dual evidence near given coordinates.

        Args:
            coordinates: Query coordinates
            radius: Search radius in mm
            min_consensus_confidence: Minimum consensus confidence
            require_multiple_sources: Require evidence from multiple sources

        Returns:
            List of dual evidence concepts
        """

        # Use graph's dual evidence search
        concepts = self.graph.find_dual_evidence_concepts(
            min_consensus_confidence=min_consensus_confidence,
            coordinates=coordinates,
            radius=radius
        )

        # Filter by source requirement
        if require_multiple_sources:
            concepts = [c for c in concepts if len(c["evidence_sources"]) >= 2]

        # Enhance with additional context
        enhanced_concepts = []
        for concept in concepts:
            # Add spatial distance
            concept_coords = concept.get("coordinates", [])
            if concept_coords:
                min_distance = float('inf')
                for query_coord in coordinates:
                    for concept_coord in concept_coords:
                        distance = sum(
                            (a - b) ** 2 for a, b in zip(query_coord, concept_coord)
                        ) ** 0.5
                        if distance < min_distance:
                            min_distance = distance
                concept["spatial_distance"] = min_distance

            # Add evidence quality metrics
            evidence_sources = concept.get("evidence_sources", [])
            if evidence_sources:
                confidences = [src.get("confidence", 0.0) for src in evidence_sources]
                concept["evidence_quality"] = {
                    "mean_confidence": sum(confidences) / len(confidences),
                    "min_confidence": min(confidences),
                    "max_confidence": max(confidences),
                    "confidence_variance": sum((c - sum(confidences)/len(confidences))**2
                                              for c in confidences) / len(confidences)
                }

            enhanced_concepts.append(concept)

        # Sort by consensus confidence and spatial distance
        enhanced_concepts.sort(
            key=lambda x: (x["consensus_confidence"], -x.get("spatial_distance", 0)),
            reverse=True
        )

        return enhanced_concepts

    def get_evidence_conflicts_for_region(
        self,
        coordinates: List[Tuple[float, float, float]],
        radius: float = 15.0
    ) -> List[Dict[str, Any]]:
        """
        Get evidence conflicts in a spatial region.

        Args:
            coordinates: Region coordinates
            radius: Search radius in mm

        Returns:
            List of conflicts in the region
        """

        # Get all conflicts
        all_conflicts = self.graph.get_evidence_conflicts(unresolved_only=True)

        # Filter by spatial proximity
        region_conflicts = []
        for conflict in all_conflicts:
            # Check if any evidence in conflict is near query coordinates
            evidence_in_region = False
            for evidence in conflict.get("evidence", []):
                evidence_node = self.graph.get_node(evidence["id"])
                if evidence_node and "coordinates" in evidence_node:
                    evidence_coords = json.loads(evidence_node["coordinates"])
                    for query_coord in coordinates:
                        for evidence_coord in evidence_coords:
                            distance = sum(
                                (a - b) ** 2 for a, b in zip(query_coord, evidence_coord)
                            ) ** 0.5
                            if distance <= radius:
                                evidence_in_region = True
                                break
                        if evidence_in_region:
                            break
                if evidence_in_region:
                    break

            if evidence_in_region:
                region_conflicts.append(conflict)

        return region_conflicts

    def validate_evidence_with_glm(
        self,
        concept_name: str,
        coordinates: List[Tuple[float, float, float]],
        contrast_name: str
    ) -> Dict[str, Any]:
        """
        Validate evidence using GLM data where available.

        Args:
            concept_name: Name of concept to validate
            coordinates: Brain coordinates
            contrast_name: Contrast name for GLM lookup

        Returns:
            Validation results
        """

        validation_result = {
            "concept_name": concept_name,
            "coordinates": coordinates,
            "contrast_name": contrast_name,
            "glm_validation": None,
            "validation_confidence": 0.0
        }

        try:
            # Use fusion system's GLM validation
            from ..mappers.glm_direction_validator import GLMDirectionValidator

            validator = GLMDirectionValidator()

            # Create mock predictions for validation
            predictions = [{
                "concept": concept_name,
                "confidence": 0.8,  # Will be updated based on evidence
                "coordinates": coordinates
            }]

            glm_result = validator.validate_predictions(
                predictions, contrast_name, coordinates
            )

            validation_result["glm_validation"] = glm_result
            validation_result["validation_confidence"] = glm_result.get("alignment_score", 0.0)

            # Store GLM evidence in graph
            if glm_result.get("alignment_score", 0.0) > 0.5:
                glm_evidence = {
                    "confidence": glm_result.get("alignment_score", 0.0),
                    "source_type": "brain_activation",
                    "validation_data": glm_result,
                    "contrast": contrast_name
                }

                glm_evidence_id = self.graph.create_evidence_node(
                    concept_name=concept_name,
                    source_type="brain_activation",
                    evidence_data=glm_result,
                    confidence_score=glm_result.get("alignment_score", 0.0),
                    coordinates=coordinates,
                    task_context=contrast_name
                )

                validation_result["glm_evidence_id"] = glm_evidence_id

        except Exception as e:
            logger.warning(f"GLM validation failed for {concept_name}: {e}")
            validation_result["error"] = str(e)

        return validation_result

    def enhance_query_with_evidence_history(
        self,
        coordinates: List[Tuple[float, float, float]],
        radius: float = 10.0
    ) -> Dict[str, Any]:
        """
        Enhance spatial query with historical evidence from the graph.

        Args:
            coordinates: Query coordinates
            radius: Search radius

        Returns:
            Enhanced query results with evidence history
        """

        # Get dual evidence concepts
        dual_concepts = self.query_dual_evidence_concepts(
            coordinates, radius, min_consensus_confidence=0.3
        )

        # Get evidence conflicts
        conflicts = self.get_evidence_conflicts_for_region(coordinates, radius)

        # Get fusion metrics in region
        fusion_metrics = []
        for node_id, node_data in self.graph.find_nodes("FusionMetrics"):
            if "coordinates" in node_data:
                metrics_coords = json.loads(node_data["coordinates"])
                # Check if within radius
                within_radius = False
                for query_coord in coordinates:
                    for metrics_coord in metrics_coords:
                        distance = sum(
                            (a - b) ** 2 for a, b in zip(query_coord, metrics_coord)
                        ) ** 0.5
                        if distance <= radius:
                            within_radius = True
                            break
                    if within_radius:
                        break

                if within_radius:
                    fusion_metrics.append({
                        "id": node_id,
                        "avg_confidence": node_data.get("avg_confidence"),
                        "n_conflicts": node_data.get("n_conflicts"),
                        "overlap_ratio": node_data.get("overlap_ratio"),
                        "timestamp": node_data.get("timestamp")
                    })

        # Calculate regional evidence statistics
        evidence_stats = {
            "total_concepts": len(dual_concepts),
            "high_confidence_concepts": len([c for c in dual_concepts
                                           if c["consensus_confidence"] > 0.7]),
            "conflict_count": len(conflicts),
            "avg_consensus_confidence": (
                sum(c["consensus_confidence"] for c in dual_concepts) / len(dual_concepts)
                if dual_concepts else 0.0
            ),
            "evidence_source_distribution": {}
        }

        # Count evidence sources
        for concept in dual_concepts:
            for source in concept.get("evidence_sources", []):
                source_type = source.get("source_type", "unknown")
                evidence_stats["evidence_source_distribution"][source_type] = (
                    evidence_stats["evidence_source_distribution"].get(source_type, 0) + 1
                )

        enhanced_result = {
            "query_coordinates": coordinates,
            "search_radius": radius,
            "dual_evidence_concepts": dual_concepts,
            "evidence_conflicts": conflicts,
            "fusion_metrics_history": fusion_metrics,
            "regional_evidence_stats": evidence_stats,
            "timestamp": datetime.now().isoformat()
        }

        return enhanced_result

    def export_evidence_summary(
        self,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export a summary of all evidence in the graph.

        Args:
            output_path: Optional path to save JSON summary

        Returns:
            Evidence summary dictionary
        """

        # Get comprehensive stats
        stats = self.graph.get_dual_evidence_stats()

        # Get all dual evidence concepts
        all_concepts = self.graph.find_dual_evidence_concepts(min_consensus_confidence=0.0)

        # Get all conflicts
        all_conflicts = self.graph.get_evidence_conflicts(unresolved_only=False)

        # Create summary
        summary = {
            "generation_timestamp": datetime.now().isoformat(),
            "database_path": self.db_path,
            "graph_statistics": stats,
            "dual_evidence_concepts": {
                "total_count": len(all_concepts),
                "high_confidence_count": len([c for c in all_concepts if c["consensus_confidence"] > 0.7]),
                "concepts": all_concepts
            },
            "evidence_conflicts": {
                "total_count": len(all_conflicts),
                "unresolved_count": len([c for c in all_conflicts if not c.get("resolved", False)]),
                "conflicts": all_conflicts
            }
        }

        # Save to file if requested
        if output_path:
            with open(output_path, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            logger.info(f"Evidence summary exported to: {output_path}")

        return summary

    def close(self):
        """Close database connections."""
        if hasattr(self, 'graph'):
            self.graph.close()


# Example usage
if __name__ == "__main__":
    # Initialize integrator
    integrator = DualEvidenceIntegrator()

    # Example coordinates (DLPFC)
    coordinates = [(-44, 36, 20), (44, 36, 20)]

    # Simulate fusion result
    mock_fusion_result = {
        "constructs": [
            {
                "name": "working memory",
                "confidence": 0.85,
                "niclip_confidence": 0.9,
                "llm_confidence": 0.8,
                "evidence": {
                    "sources": ["niclip", "llm"],
                    "validation": {"glm_alignment": 0.75}
                }
            }
        ],
        "fusion_metrics": {
            "avg_confidence": 0.85,
            "n_conflicts": 0,
            "overlap_ratio": 0.8
        }
    }

    # Store fusion result
    created_nodes = integrator.store_fusion_result(
        contrast_name="working_memory_task",
        task_name="n_back",
        coordinates=coordinates,
        fusion_result=mock_fusion_result
    )

    print(f"Created {len(created_nodes)} fused concept nodes")

    # Query dual evidence concepts
    dual_concepts = integrator.query_dual_evidence_concepts(
        coordinates=coordinates,
        radius=15.0
    )

    print(f"Found {len(dual_concepts)} dual evidence concepts in region")

    # Get enhanced query results
    enhanced_results = integrator.enhance_query_with_evidence_history(
        coordinates=coordinates,
        radius=15.0
    )

    print(f"Regional evidence stats: {enhanced_results['regional_evidence_stats']}")

    # Export summary
    summary = integrator.export_evidence_summary("evidence_summary.json")
    print(f"Exported evidence summary with {summary['dual_evidence_concepts']['total_count']} concepts")

    integrator.close()
    print("Dual evidence integration test completed!")