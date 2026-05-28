"""
Tool catalog evidence connector.

Wraps the ToolRegistry to search for analysis tools and pipelines.
"""

from __future__ import annotations

from typing import Any

from ..models import EvidenceItem, EvidenceSource, EvidenceType
from ..protocols import ConnectorError
from .base import SyncWrapperConnector


class ToolConnector(SyncWrapperConnector):
    """
    Connector for searching the tool catalog.

    Searches for neuroimaging analysis tools (FSL, fMRIPrep, etc.)
    using the ToolRegistry's semantic search.
    """

    _registry = None
    _registry_init_attempted = False

    @property
    def source(self) -> EvidenceSource:
        return EvidenceSource.TOOL_CATALOG

    @property
    def is_available(self) -> bool:
        """Check if ToolRegistry can be loaded."""
        if self._registry is not None:
            return True
        if self._registry_init_attempted:
            return False
        try:
            self._get_registry()
            return True
        except Exception:
            return False

    def _get_registry(self):
        """Lazy-load the ToolRegistry."""
        if self._registry is None:
            self.__class__._registry_init_attempted = True
            try:
                from brain_researcher.services.tools.tool_registry import ToolRegistry

                # Use light mode for faster loading
                self.__class__._registry = ToolRegistry(auto_discover=True, light_mode=True)
            except Exception as e:
                raise ConnectorError(self.source, f"Failed to load ToolRegistry: {e}", e)
        return self._registry

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """
        Search for tools matching the query.

        Args:
            query: Search query (e.g., "GLM analysis", "connectivity")
            limit: Maximum results
            filters: Optional filters (currently unused)

        Returns:
            List of evidence items
        """
        try:
            registry = self._get_registry()
        except ConnectorError:
            raise
        except Exception as e:
            raise ConnectorError(self.source, f"Failed to get registry: {e}", e)

        try:
            tools = await self._run_sync(registry.get_tools_for_task, query, k=limit)
        except Exception as e:
            raise ConnectorError(self.source, f"Search failed: {e}", e)

        return [self._to_evidence_item(tool) for tool in tools]

    async def get_by_id(self, item_id: str) -> EvidenceItem | None:
        """Get a specific tool by name."""
        try:
            registry = self._get_registry()
            tool = registry.get_tool(item_id)
            if tool:
                return self._to_evidence_item(tool)
        except Exception:
            pass
        return None

    def _to_evidence_item(self, tool) -> EvidenceItem:
        """Convert tool wrapper to EvidenceItem."""
        name = tool.get_tool_name()
        description = tool.get_tool_description()

        return EvidenceItem(
            id=name,
            source=self.source,
            item_type=EvidenceType.TOOL,
            title=name,
            description=description[:300] if description else None,
            score=0.8,  # Default score since registry doesn't return scores
            metadata={
                "full_description": description,
                "tool_class": tool.__class__.__name__,
            },
        )
