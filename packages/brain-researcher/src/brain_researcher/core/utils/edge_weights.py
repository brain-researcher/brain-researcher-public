"""
Compatibility shim for legacy imports.

The edge weight utilities were moved to :mod:`brain_researcher.core.kg.edge_weights`.
This module simply re-exports the public helpers so existing imports from
``brain_researcher.core.utils.edge_weights`` continue to function.
"""

from __future__ import annotations

from brain_researcher.core.kg.edge_weights import (  # noqa: F401
    build_edge_properties,
    compute_fleiss_kappa_matrix,
    compute_llm_confidence,
    compute_pubmed_score,
    compute_utility,
    normalize_csv_weight,
)

__all__ = [
    "build_edge_properties",
    "compute_fleiss_kappa_matrix",
    "compute_llm_confidence",
    "compute_pubmed_score",
    "compute_utility",
    "normalize_csv_weight",
]
