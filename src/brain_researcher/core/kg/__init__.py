"""Knowledge graph package exports.

Keep heavyweight modules lazily loaded so importing light helpers
(e.g. ``brain_researcher.core.kg.edge_weights``) does not force model stack
imports during service startup.
"""

from __future__ import annotations

from typing import Any

from .embedding_config import EmbeddingConfig, get_config
from .embedding_metrics import EmbeddingMetricsCollector as EmbeddingMetrics
from .persistent_db import PersistentKnowledgeBase

__all__ = [
    "EmbeddingIndex",
    "EmbeddingConfig",
    "get_config",
    "PersistentKnowledgeBase",
    "EmbeddingMetrics",  # Alias for EmbeddingMetricsCollector
]


def __getattr__(name: str) -> Any:
    if name == "EmbeddingIndex":
        # Import lazily to avoid pulling sentence-transformers/torch at module
        # import time for code paths that do not need embeddings.
        from .embedding_index import EmbeddingIndex

        return EmbeddingIndex
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
