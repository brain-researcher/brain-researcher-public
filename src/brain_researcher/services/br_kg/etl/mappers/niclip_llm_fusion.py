#!/usr/bin/env python3
"""
NiCLIP-LLM Fusion Module

Integrates NiCLIP brain-data mapping with LLM semantic understanding
for enhanced cognitive annotation of fMRI contrasts.

This module provides:
1. Bidirectional validation between NiCLIP and LLM outputs
2. Confidence score fusion with task-adaptive weighting
3. Direction alignment validation
4. Active learning support for model improvement
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.metrics import cohen_kappa_score

from .glm_direction_validator import get_glm_validator

logger = logging.getLogger(__name__)


class CognitiveAnnotationFusion:
    """Fuses NiCLIP and LLM annotations for robust cognitive mapping."""

    # Task categories for adaptive weighting
    PERCEPTUAL_TASKS = ["visual", "auditory", "motor", "sensory", "perception"]
    COGNITIVE_TASKS = [
        "working_memory",
        "memory",
        "executive",
        "attention",
        "reasoning",
        "cognitive",
    ]
    SOCIAL_TASKS = ["social", "emotion", "language", "semantic"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the fusion module.

        Args:
            config: Configuration dictionary with fusion parameters
        """
        default_config = self._default_config()
        if config:
            # Merge with defaults
            self.config = self._merge_configs(default_config, config)
        else:
            self.config = default_config
        self._loaded = False

        # Load NiCLIP and LLM mappers if available
        self._load_mappers()

    def _merge_configs(
        self, default: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Recursively merge configurations."""
        merged = default.copy()
        for key, value in override.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)
            ):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _default_config(self) -> Dict[str, Any]:
        """Default configuration for fusion."""
        return {
            "weights": {
                "perceptual": {"niclip": 0.7, "llm": 0.3},
                "cognitive": {"niclip": 0.5, "llm": 0.5},
                "social": {"niclip": 0.3, "llm": 0.7},
                "default": {"niclip": 0.5, "llm": 0.5},
            },
            "direction_agreement_bonus": 0.1,
            "conflict_threshold": 0.3,
            "min_confidence": 0.1,
            "use_literature": True,
        }

    def _load_mappers(self):
        """Load NiCLIP and initialize connections."""
        try:
            from brain_researcher.services.br_kg.etl.mappers.niclip_spatial_mapper import (
                get_spatial_mapper,
            )
            from brain_researcher.services.br_kg.etl.mappers.niclip_task_mapper import (
                get_mapper,
            )

            self.niclip_task_mapper = get_mapper()
            self.niclip_spatial_mapper = get_spatial_mapper()

            self._loaded = (
                self.niclip_task_mapper
                and self.niclip_task_mapper._loaded
                and self.niclip_spatial_mapper
                and self.niclip_spatial_mapper._loaded
            )

            if self._loaded:
                logger.info("NiCLIP mappers loaded successfully")
            else:
                logger.warning("NiCLIP mappers not fully loaded")

            # Try to load GLM validator
            self.glm_validator = get_glm_validator()
            if self.glm_validator:
                logger.info("GLM validator loaded successfully")
            else:
                logger.warning("GLM validator not available")

        except Exception as e:
            logger.error(f"Failed to load NiCLIP mappers: {e}")
            self._loaded = False

    def fuse_annotations(
        self,
        contrast_name: str,
        task_name: str,
        llm_result: Dict[str, Any],
        niclip_result: Optional[Dict[str, Any]] = None,
        mni_coordinates: Optional[List[Tuple[float, float, float]]] = None,
        validate_with_glm: bool = True,
    ) -> Dict[str, Any]:
        """
        Fuse LLM and NiCLIP annotations for a contrast.

        Args:
            contrast_name: Name of the fMRI contrast
            task_name: Task identifier
            llm_result: LLM annotation output with constructs
            niclip_result: Optional pre-computed NiCLIP results
            mni_coordinates: Optional MNI coordinates for spatial validation

        Returns:
            Fused annotation with enhanced confidence scores
        """
        # Extract LLM constructs
        llm_constructs = llm_result.get("constructs", [])

        # Get or compute NiCLIP results
        if niclip_result is None and self._loaded and mni_coordinates:
            niclip_result = self._compute_niclip_annotations(task_name, mni_coordinates)

        # Determine task category for weighting
        task_category = self._classify_task(task_name, contrast_name)
        weights = self.config["weights"].get(
            task_category, self.config["weights"]["default"]
        )

        # Perform fusion
        fused_constructs = []
        construct_map = {}

        # First pass: Index all constructs
        for construct in llm_constructs:
            construct_id = construct["id"]
            construct_map[construct_id] = {
                "llm": construct,
                "niclip": None,
                "sources": ["llm"],
            }

        if niclip_result:
            for construct in niclip_result.get("constructs", []):
                construct_id = construct["id"]
                if construct_id in construct_map:
                    construct_map[construct_id]["niclip"] = construct
                    construct_map[construct_id]["sources"].append("niclip")
                else:
                    construct_map[construct_id] = {
                        "llm": None,
                        "niclip": construct,
                        "sources": ["niclip"],
                    }

        # Second pass: Fuse and validate
        for construct_id, data in construct_map.items():
            fused = self._fuse_single_construct(construct_id, data, weights)

            if fused["confidence"] >= self.config["min_confidence"]:
                fused_constructs.append(fused)

        # Sort by confidence
        fused_constructs.sort(key=lambda x: x["confidence"], reverse=True)

        # Calculate fusion metrics
        metrics = self._calculate_fusion_metrics(
            llm_constructs,
            niclip_result.get("constructs", []) if niclip_result else [],
            fused_constructs,
        )

        # Validate with GLM if requested and available
        glm_validation = None
        if validate_with_glm and self.glm_validator and mni_coordinates:
            try:
                # Extract predictions for validation
                predictions = []
                for construct in fused_constructs[:5]:  # Top 5 constructs
                    pred = {
                        "name": construct["name"],
                        "direction": construct.get("evidence", {})
                        .get("llm", {})
                        .get("direction", "+1"),
                    }
                    predictions.append(pred)

                # Validate against GLM
                glm_validation = self.glm_validator.validate_predictions(
                    predictions,
                    contrast_name,
                    mni_coordinates[:3],  # Use first 3 coordinates
                )

                # Add validation scores to constructs
                if glm_validation.get("validation_available"):
                    for construct, alignment in zip(
                        fused_constructs[:5], glm_validation["alignments"]
                    ):
                        construct["glm_alignment"] = {
                            "score": alignment["alignment_score"],
                            "beta_value": alignment["beta_value"],
                            "direction_match": alignment["predicted_direction"]
                            == alignment["actual_direction"],
                        }

            except Exception as e:
                logger.warning(f"GLM validation failed: {e}")
                glm_validation = {"validation_available": False, "error": str(e)}

        result = {
            "contrast_name": contrast_name,
            "task_name": task_name,
            "constructs": fused_constructs,
            "fusion_metrics": metrics,
            "method": "niclip_llm_fusion",
            "timestamp": datetime.utcnow().isoformat(),
        }

        if glm_validation:
            result["glm_validation"] = glm_validation

        return result

    def _compute_niclip_annotations(
        self, task_name: str, mni_coordinates: List[Tuple[float, float, float]]
    ) -> Dict[str, Any]:
        """Compute NiCLIP annotations from coordinates."""
        if not self._loaded:
            return {"constructs": []}

        # Use spatial mapper to get concepts from coordinates
        concepts = self.niclip_spatial_mapper.coordinate_to_concepts(
            mni_coordinates, radius=10.0, top_k=10
        )

        # Convert to construct format
        constructs = []
        for concept_data in concepts:
            construct = {
                "id": concept_data.get("concept_id", ""),
                "name": concept_data.get("concept", ""),
                "niclip_confidence": concept_data.get("alignment_score", 0.0),
                "spatial_confidence": concept_data.get("spatial_score", 0.0),
                "source": "niclip",
            }
            constructs.append(construct)

        return {"constructs": constructs}

    def _classify_task(self, task_name: str, contrast_name: str) -> str:
        """Classify task into perceptual/cognitive/social category."""
        combined = f"{task_name} {contrast_name}".lower()

        # Check each category
        for keyword in self.PERCEPTUAL_TASKS:
            if keyword in combined:
                return "perceptual"

        for keyword in self.COGNITIVE_TASKS:
            if keyword in combined:
                return "cognitive"

        for keyword in self.SOCIAL_TASKS:
            if keyword in combined:
                return "social"

        return "default"

    def _fuse_single_construct(
        self, construct_id: str, data: Dict[str, Any], weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Fuse a single construct from multiple sources."""
        llm_data = data["llm"]
        niclip_data = data["niclip"]

        # Base structure
        fused = {
            "id": construct_id,
            "name": "",
            "confidence": 0.0,
            "direction": "0",
            "evidence": {"sources": data["sources"], "llm": {}, "niclip": {}},
        }

        # Handle LLM data
        if llm_data:
            fused["name"] = llm_data.get("name", "")
            fused["direction"] = str(llm_data.get("direction", "0"))
            llm_conf = float(llm_data.get("llm_confidence", 0.0))
            fused["evidence"]["llm"] = {
                "confidence": llm_conf,
                "direction": fused["direction"],
            }

        # Handle NiCLIP data
        if niclip_data:
            if not fused["name"]:
                fused["name"] = niclip_data.get("name", "")

            niclip_conf = float(niclip_data.get("niclip_confidence", 0.0))
            spatial_conf = float(niclip_data.get("spatial_confidence", 0.0))

            # Average NiCLIP confidences
            niclip_final = (niclip_conf + spatial_conf) / 2

            fused["evidence"]["niclip"] = {
                "confidence": niclip_final,
                "spatial_confidence": spatial_conf,
                "alignment_score": niclip_conf,
            }

        # Calculate fused confidence
        if llm_data and niclip_data:
            # Both sources available
            llm_conf = fused["evidence"]["llm"]["confidence"]
            niclip_conf = fused["evidence"]["niclip"]["confidence"]

            # Weighted average
            base_conf = weights["llm"] * llm_conf + weights["niclip"] * niclip_conf

            # Direction agreement bonus (only for LLM since NiCLIP doesn't have direction yet)
            fused["confidence"] = base_conf

            # Check for conflicts
            conf_diff = abs(llm_conf - niclip_conf)
            if conf_diff > self.config["conflict_threshold"]:
                fused["evidence"]["conflict"] = True
                fused["evidence"]["conflict_score"] = conf_diff

        elif llm_data:
            # Only LLM available
            fused["confidence"] = fused["evidence"]["llm"]["confidence"]

        elif niclip_data:
            # Only NiCLIP available
            fused["confidence"] = fused["evidence"]["niclip"]["confidence"]

        # Round confidence
        fused["confidence"] = round(fused["confidence"], 3)

        return fused

    def _calculate_fusion_metrics(
        self,
        llm_constructs: List[Dict],
        niclip_constructs: List[Dict],
        fused_constructs: List[Dict],
    ) -> Dict[str, Any]:
        """Calculate metrics about the fusion process."""
        llm_ids = {c["id"] for c in llm_constructs}
        niclip_ids = {c["id"] for c in niclip_constructs}
        fused_ids = {c["id"] for c in fused_constructs}

        metrics = {
            "n_llm": len(llm_ids),
            "n_niclip": len(niclip_ids),
            "n_fused": len(fused_ids),
            "n_overlap": len(llm_ids & niclip_ids),
            "n_llm_only": len(llm_ids - niclip_ids),
            "n_niclip_only": len(niclip_ids - llm_ids),
            "overlap_ratio": len(llm_ids & niclip_ids)
            / max(len(llm_ids | niclip_ids), 1),
        }

        # Calculate average confidences
        if fused_constructs:
            metrics["avg_confidence"] = np.mean(
                [c["confidence"] for c in fused_constructs]
            )
            metrics["n_conflicts"] = sum(
                1
                for c in fused_constructs
                if c.get("evidence", {}).get("conflict", False)
            )
        else:
            metrics["avg_confidence"] = 0.0
            metrics["n_conflicts"] = 0

        return metrics

    def validate_with_expert(
        self, fused_result: Dict[str, Any], expert_annotations: List[str]
    ) -> Dict[str, float]:
        """
        Validate fused results against expert annotations.

        Args:
            fused_result: Output from fuse_annotations
            expert_annotations: List of construct IDs from expert

        Returns:
            Validation metrics
        """
        fused_ids = [c["id"] for c in fused_result["constructs"][:5]]  # Top 5

        # Calculate metrics
        if not fused_ids or not expert_annotations:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

        fused_set = set(fused_ids)
        expert_set = set(expert_annotations[:5])

        tp = len(fused_set & expert_set)
        precision = tp / len(fused_set) if fused_set else 0.0
        recall = tp / len(expert_set) if expert_set else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        return {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "true_positives": tp,
            "n_predicted": len(fused_set),
            "n_expert": len(expert_set),
        }

    def identify_conflicts(
        self, results: List[Dict[str, Any]], threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Identify high-conflict cases for active learning.

        Args:
            results: List of fusion results
            threshold: Conflict threshold (uses config default if None)

        Returns:
            List of high-conflict cases sorted by conflict score
        """
        threshold = threshold or self.config["conflict_threshold"]
        conflicts = []

        for result in results:
            for construct in result["constructs"]:
                if construct.get("evidence", {}).get("conflict", False):
                    conflict_score = construct["evidence"].get("conflict_score", 0)
                    if conflict_score >= threshold:
                        conflicts.append(
                            {
                                "contrast": result["contrast_name"],
                                "task": result["task_name"],
                                "construct_id": construct["id"],
                                "construct_name": construct["name"],
                                "conflict_score": conflict_score,
                                "llm_conf": construct["evidence"]["llm"]["confidence"],
                                "niclip_conf": construct["evidence"]["niclip"][
                                    "confidence"
                                ],
                            }
                        )

        # Sort by conflict score (descending)
        if conflicts:
            conflicts.sort(key=lambda x: x["conflict_score"], reverse=True)

        return conflicts


def get_fusion_module(config: Optional[Dict[str, Any]] = None):
    """Get or create the singleton fusion module."""
    global _fusion_module
    if "_fusion_module" not in globals():
        _fusion_module = CognitiveAnnotationFusion(config)
    return _fusion_module


def test_fusion():
    """Test the fusion module with example data."""
    # Create test LLM result
    llm_result = {
        "constructs": [
            {
                "id": "trm_4aae62e4ad209",
                "name": "cognitive control",
                "llm_confidence": 0.8,
                "direction": "+1",
            },
            {
                "id": "trm_4a3fd79d0a0be",
                "name": "working memory",
                "llm_confidence": 0.6,
                "direction": "+1",
            },
        ]
    }

    # Create test NiCLIP result
    niclip_result = {
        "constructs": [
            {
                "id": "trm_4aae62e4ad209",
                "name": "cognitive control",
                "niclip_confidence": 0.7,
                "spatial_confidence": 0.75,
            },
            {
                "id": "trm_50df0dd3d74f4",
                "name": "attention",
                "niclip_confidence": 0.65,
                "spatial_confidence": 0.7,
            },
        ]
    }

    # Test fusion
    fusion = get_fusion_module()
    result = fusion.fuse_annotations(
        "nback_vs_rest", "working_memory_task", llm_result, niclip_result
    )

    print("\n🔀 Fusion Test Results")
    print("=" * 50)
    print(f"Contrast: {result['contrast_name']}")
    print(f"Task: {result['task_name']}")
    print(f"\nFused Constructs:")
    for c in result["constructs"]:
        print(f"  - {c['name']} (ID: {c['id']})")
        print(f"    Confidence: {c['confidence']}")
        print(f"    Sources: {c['evidence']['sources']}")
        if "conflict" in c["evidence"]:
            print(f"    ⚠️  Conflict detected: {c['evidence']['conflict_score']}")

    print(f"\nFusion Metrics:")
    for key, value in result["fusion_metrics"].items():
        print(f"  {key}: {value}")

    # Test validation
    expert = ["trm_4aae62e4ad209", "trm_50df0dd3d74f4"]
    validation = fusion.validate_with_expert(result, expert)
    print(f"\nValidation against expert:")
    print(f"  Precision: {validation['precision']}")
    print(f"  Recall: {validation['recall']}")
    print(f"  F1: {validation['f1']}")


if __name__ == "__main__":
    test_fusion()
