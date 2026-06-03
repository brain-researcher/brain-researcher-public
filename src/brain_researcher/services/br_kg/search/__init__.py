"""BR-KG search package public interface.

Keep API-service imports lightweight. The BR-KG Flask app only needs the
basic search engine and orchestrator during bootstrap; eager-importing vector
search modules pulls in sentence-transformers/torch and can stall service
startup before the HTTP server binds its port.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .basic_search import SearchEngine, SearchMode, SearchResult
from .orchestrator import SearchOrchestrator

__all__ = [
    "SearchEngine",
    "SearchMode",
    "SearchResult",
    "VectorSearchEngine",
    "AdvancedVectorSearchEngine",
    "VectorSearchConfig",
    "IndexType",
    "VectorSearchResult",
    "HybridSearchEngine",
    "SearchOrchestrator",
]


def __getattr__(name: str) -> Any:
    if name == "VectorSearchEngine":
        return getattr(import_module(".vector_search", __name__), name)
    if name == "VectorSearchConfig":
        return getattr(
            import_module("brain_researcher.services.br_kg.vector_search"), name
        )
    if name in {"AdvancedVectorSearchEngine", "IndexType"}:
        return getattr(import_module(".advanced_vector_search", __name__), name)
    if name == "VectorSearchResult":
        return import_module(".advanced_vector_search", __name__).SearchResult
    if name == "HybridSearchEngine":
        return getattr(import_module(".hybrid_search_engine", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
