"""Core graph database protocols used by ingestion."""

from __future__ import annotations

from typing import Callable, Protocol


class GraphDatabaseProtocol(Protocol):
    """Structural protocol for the graph clients used in ingestion."""

    def close(self) -> None: ...

    def get_stats(self) -> dict: ...


GraphFactory = Callable[[], GraphDatabaseProtocol]

__all__ = ["GraphDatabaseProtocol", "GraphFactory"]
