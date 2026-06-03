"""Evidence source adapters for Track K+.

Each source wraps an existing service and converts results to KnowledgeItem format.
"""

from .base import BaseEvidenceSource, SourceCapabilities
from .dataset import DatasetEvidenceSource
from .kg import KGEvidenceSource
from .niclip import NiCLIPEvidenceSource
from .tool import ToolEvidenceSource
from .pubmed import PubMedEvidenceSource
from .neurostore import NeuroStoreEvidenceSource

__all__ = [
    "BaseEvidenceSource",
    "DatasetEvidenceSource",
    "KGEvidenceSource",
    "NiCLIPEvidenceSource",
    "SourceCapabilities",
    "ToolEvidenceSource",
    "PubMedEvidenceSource",
    "NeuroStoreEvidenceSource",
]
