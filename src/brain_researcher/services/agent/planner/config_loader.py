"""Helpers for loading planner configuration files."""

from __future__ import annotations

import logging
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import get_repo_root as get_shared_repo_root

logger = logging.getLogger(__name__)


@lru_cache()
def get_repo_root() -> Path:
    """Return repository root (directory containing configs/)."""
    return get_shared_repo_root()


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            return data
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to load YAML config %s: %s", path, exc)
        return {}


def load_planner_config(filename: str) -> Dict[str, Any]:
    """Load a YAML config from configs/planner/."""
    path = get_repo_root() / "configs" / "planner" / filename
    return _load_yaml_file(path)


@lru_cache(maxsize=1)
def load_capability_crosswalk() -> Dict[str, Any]:
    """Load configs/planner/capability_crosswalk.yaml.

    This crosswalk maps external labels and common phrases into internal planner
    tokens (capability tags + intent ids) to improve recall without rewriting the
    core retrieval pipeline.
    """
    path = resolve_mapping_path(
        "capability_crosswalk",
        fallback=get_repo_root() / "configs" / "planner" / "capability_crosswalk.yaml",
        must_exist=False,
    )
    return _load_yaml_file(path)


def load_scoring_weights() -> Dict[str, Any]:
    """Load scoring weights config with backward compatibility for v0.1.

    Handles both v0.1 and v0.2 formats:
    - v0.1: Flat structure with top-level 'weights' dict
    - v0.2: Hierarchical structure with 'policy.scoring.weights'

    Returns:
        Dict with v0.2 structure (auto-converted if v0.1 detected)

    Raises deprecation warning for v0.1 format.
    """
    config = load_planner_config("scoring_weights.yaml")

    if not config:
        logger.warning("No scoring_weights.yaml found, using defaults")
        return _get_default_v2_config()

    version = config.get("version", "0.1.0")

    # v0.2 format - return as-is
    if version.startswith("0.2"):
        return config

    # v0.1 format - convert to v0.2 structure
    if version.startswith("0.1"):
        warnings.warn(
            "scoring_weights.yaml v0.1 format is deprecated. "
            "Please upgrade to v0.2 format. "
            "See configs/planner/scoring_weights.yaml for the new structure.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "Deprecated scoring_weights.yaml v0.1 format detected. "
            "Auto-converting to v0.2 structure."
        )
        return _convert_v1_to_v2(config)

    # Unknown version - assume v0.1 for backward compatibility
    logger.warning(
        "Unknown scoring_weights.yaml version: %s. Assuming v0.1 format.", version
    )
    return _convert_v1_to_v2(config)


def _convert_v1_to_v2(v1_config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert v0.1 config format to v0.2 structure.

    Args:
        v1_config: v0.1 format config

    Returns:
        v0.2 format config
    """
    # Extract v0.1 weights
    v1_weights = v1_config.get("weights", {})
    v1_scoring = v1_config.get("scoring", {})
    v1_resource_fit = v1_config.get("resource_fit", {})
    v1_metadata = v1_config.get("metadata", {})
    v1_explanations = v1_config.get("explanations", {})

    # Build v0.2 structure
    v2_config = {
        "version": "0.2.0-compat",  # Mark as auto-converted
        "policy": {
            "constraints": {
                "require_preflight": True,  # Default based on v0.1 behavior
                "require_capability_match": "strict",
                "require_container_availability": False,
                "gpu_required_if": [],
                "use_kg_constraints": False,
                "kg_constraint_mode": "relaxed",
                "kg_modalities": [],
                "kg_required_consumes": [],
                "kg_required_produces": [],
            },
            "scoring": {
                "weights": {
                    "intent_match": v1_weights.get("intent_match", 0.35),
                    "preflight": v1_weights.get("preflight", 0.25),
                    "description": v1_weights.get("description", 0.20),
                    "metadata": v1_weights.get("metadata", 0.10),
                    "resource_fit": v1_weights.get("resource_fit", 0.10),
                    "historical_quality": 0.0,  # Not in v0.1
                    "latency_pred": 0.0,  # Not in v0.1
                },
                "min_candidate_score": v1_scoring.get("min_candidate_score", 0.1),
                "exact_match_boost": v1_scoring.get("exact_match_boost", 0.1),
                "features": {
                    "embedding_similarity": False,
                    "tfidf_similarity": True,
                    "historical_quality": False,  # Disable for v0.1
                    "latency_pred": False,  # Disable for v0.1
                },
                "generate_explanations": v1_scoring.get("generate_explanations", True),
                "explanation_verbosity": v1_scoring.get(
                    "explanation_verbosity", "brief"
                ),
            },
        },
        "overrides": {"modality": {}, "operator": {}, "environment": {}},
        "strategy": {
            "default": "top1",
            "diverse_topk": {"k": 3, "diversity_penalty": 0.1},
        },
        "experiments": {"selection_policy": {"type": "weighted", "arms": []}},
        "telemetry": {
            "log_features": False,  # Disabled for v0.1 compat
            "log_selected_candidates": "top-3",
            "tag": "planner-v0.1-compat",
            "log_dir": "data/planner_logs",
        },
        "resource_fit": v1_resource_fit,
        "metadata": v1_metadata,
        "explanations": v1_explanations,
    }

    return v2_config


def _get_default_v2_config() -> Dict[str, Any]:
    """Return default v0.2 config when no file exists."""
    return {
        "version": "0.2.0-default",
        "policy": {
            "constraints": {
                "require_preflight": True,
                "require_capability_match": "strict",
                "require_container_availability": False,
                "gpu_required_if": [],
                "use_kg_constraints": False,
                "kg_constraint_mode": "relaxed",
                "kg_modalities": [],
                "kg_required_consumes": [],
                "kg_required_produces": [],
            },
            "scoring": {
                "weights": {
                    "intent_match": 0.30,
                    "preflight": 0.00,
                    "description": 0.20,
                    "metadata": 0.10,
                    "resource_fit": 0.15,
                    "historical_quality": 0.15,
                    "latency_pred": 0.10,
                },
                "min_candidate_score": 0.10,
                "exact_match_boost": 0.05,
                "features": {
                    "embedding_similarity": False,
                    "tfidf_similarity": True,
                    "historical_quality": True,
                    "latency_pred": True,
                },
                "generate_explanations": True,
                "explanation_verbosity": "brief",
            },
        },
        "overrides": {"modality": {}, "operator": {}, "environment": {}},
        "strategy": {"default": "top1"},
        "experiments": {"selection_policy": {"type": "weighted", "arms": []}},
        "telemetry": {
            "log_features": True,
            "log_selected_candidates": "top-3",
            "tag": "planner-v0.2",
            "log_dir": "data/planner_logs",
        },
    }
