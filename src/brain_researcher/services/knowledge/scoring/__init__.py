"""Scoring utilities for the Knowledge Layer (NiCLIP integration).

This module provides:
- NiCLIPEvidenceSource: Evidence source adapter for NiCLIP embeddings
- NiCLIPScorer: High-level scorer for relevance scoring
- ScoredConcept: Result type for scored concepts

The scorers leverage pre-computed brain-text aligned embeddings to provide
neuroimaging-aware relevance scoring against cognitive vocabularies.
"""

from brain_researcher.services.knowledge.scoring.niclip_scorer import (
    NiCLIPConfig,
    NiCLIPEvidenceSource,
    NiCLIPScorer,
    ScoredConcept,
    create_niclip_source,
    search_niclip,
)

__all__ = [
    "NiCLIPConfig",
    "NiCLIPEvidenceSource",
    "NiCLIPScorer",
    "ScoredConcept",
    "create_niclip_source",
    "search_niclip",
]
