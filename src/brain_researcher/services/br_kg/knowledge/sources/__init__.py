"""Evidence source adapters for Track K+.

Each source wraps an existing service and converts results to KnowledgeItem format.
"""

from .base import BaseEvidenceSource, SourceCapabilities
from .dataset import DatasetEvidenceSource
from .kg import KGEvidenceSource
from .neurostore import NeuroStoreEvidenceSource
from .niclip import NiCLIPEvidenceSource
from .pubmed import PubMedEvidenceSource
from .tool import ToolEvidenceSource

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
