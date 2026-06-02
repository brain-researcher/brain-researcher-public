"""Evidence sources for the Knowledge Layer."""

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSource,
    EvidenceSourceType,
    SyncEvidenceSourceAdapter,
)
from brain_researcher.services.knowledge.evidence.dataset_source import (
    DatasetEvidenceSource,
    search_datasets,
)
from brain_researcher.services.knowledge.evidence.kg_source import (
    KGEvidenceSource,
    get_brain_regions,
    get_concepts,
)
from brain_researcher.services.knowledge.evidence.literature_source import (
    LiteratureEvidenceSource,
    search_literature,
    search_literature_sync,
)
from brain_researcher.services.knowledge.evidence.tool_source import (
    ToolEvidenceSource,
    search_tools,
)

__all__ = [
    # Base types
    "EvidenceBundle",
    "EvidenceQuery",
    "EvidenceResult",
    "EvidenceSource",
    "EvidenceSourceType",
    "SyncEvidenceSourceAdapter",
    # Source implementations
    "DatasetEvidenceSource",
    "KGEvidenceSource",
    "LiteratureEvidenceSource",
    "ToolEvidenceSource",
    # Convenience functions
    "get_brain_regions",
    "get_concepts",
    "search_datasets",
    "search_literature",
    "search_literature_sync",
    "search_tools",
]
