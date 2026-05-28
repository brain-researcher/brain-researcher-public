"""
Evidence module for the Neuro Knowledge Layer.

Provides unified evidence gathering from multiple knowledge sources:
- BR-KG: Knowledge graph concepts and brain regions
- Dataset Catalog: Neuroimaging datasets (OpenNeuro, HCP, etc.)
- Tool Catalog: Analysis tools and pipelines
- PubMed: Scientific publications
- NeuroStore: Meta-analysis studies and statistical maps

Usage:
    >>> from brain_researcher.services.neurokg.evidence import gather_evidence, EvidenceSource
    >>>
    >>> # Query all sources
    >>> bundle = await gather_evidence("working memory fMRI")
    >>> print(f"Found {bundle.total_count} items")
    >>>
    >>> # Query specific sources
    >>> bundle = await gather_evidence(
    ...     "motor task dataset",
    ...     sources=[EvidenceSource.DATASET_CATALOG, EvidenceSource.NEUROKG],
    ...     limit_per_source=5,
    ... )
    >>>
    >>> # Access results
    >>> for item in bundle.top_items(10):
    ...     print(f"[{item.source.value}] {item.title}")
"""

from .aggregator import gather_evidence, gather_evidence_for_qur, gather_evidence_sync
from .models import EvidenceBundle, EvidenceItem, EvidenceSource, EvidenceType
from .protocols import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    EvidenceConnector,
)

__all__ = [
    # Main API
    "gather_evidence",
    "gather_evidence_for_qur",
    "gather_evidence_sync",
    # Models
    "EvidenceBundle",
    "EvidenceItem",
    "EvidenceSource",
    "EvidenceType",
    # Protocol & Errors
    "EvidenceConnector",
    "ConnectorError",
    "ConnectorAuthError",
    "ConnectorRateLimitError",
    "ConnectorTimeoutError",
]
