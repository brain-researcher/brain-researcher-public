"""Utility modules for brain researcher.

This module contains utility functions migrated from the root utils/ directory.
"""

# Import commonly used functions for easier access
from .deepseek_client import call_deepseek_api, parse_llm_response
from .env_loader import ensure_env_loaded

# Try to import optional modules, but don't fail if they don't exist
try:
    from .edge_weights import (
        build_edge_properties,
        compute_fleiss_kappa_matrix,
        compute_llm_confidence,
        compute_pubmed_score,
        compute_utility,
        normalize_csv_weight,
    )
except ImportError:
    pass

try:
    from .port_utils import find_free_port, find_multiple_free_ports, is_port_free
except ImportError:
    pass

try:
    from .spatial import (
        euclidean_distance,
        find_nearby_rois,
        get_roi_coordinates,
        list_available_rois,
        mni_to_talairach,
        overlap_score,
        talairach_to_mni,
        validate_coordinates,
    )
except ImportError:
    pass

try:
    from .task_matcher import TaskMatcher
except ImportError:
    pass

try:
    from .mne_env import configure_mne_environment
except ImportError:
    pass

__all__ = [
    # Spatial functions
    "euclidean_distance",
    "find_nearby_rois",
    "get_roi_coordinates",
    "list_available_rois",
    "mni_to_talairach",
    "overlap_score",
    "talairach_to_mni",
    "validate_coordinates",
    # Task matcher
    "TaskMatcher",
    # Edge weights
    "compute_llm_confidence",
    "compute_fleiss_kappa_matrix",
    "compute_pubmed_score",
    "normalize_csv_weight",
    "compute_utility",
    "build_edge_properties",
    # Port utilities
    "find_free_port",
    "is_port_free",
    "find_multiple_free_ports",
    # API clients
    "call_deepseek_api",
    "parse_llm_response",
    "ensure_env_loaded",
    # MNE helpers
    "configure_mne_environment",
]
