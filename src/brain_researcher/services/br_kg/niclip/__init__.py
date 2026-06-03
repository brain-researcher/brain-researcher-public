"""
NICLIP Integration Module for BR-KG

This module provides integration between NICLIP (Neuroimaging-Cognitive Language-Image Pretraining)
and the BR-KG knowledge graph system.
"""

from .contrast_text_orchestrator import ContrastTextToPredictedMapOrchestrator
from .coordinate_mapper import NiCLIPCoordinateMapper
from .embedding_service import EmbeddingConfig, NICLIPEmbeddingService
from .engine import NiclipEngine, NiclipEngineConfig

__all__ = [
    "NICLIPEmbeddingService",
    "EmbeddingConfig",
    "NiclipEngine",
    "NiclipEngineConfig",
    "NiCLIPCoordinateMapper",
    "ContrastTextToPredictedMapOrchestrator",
]
