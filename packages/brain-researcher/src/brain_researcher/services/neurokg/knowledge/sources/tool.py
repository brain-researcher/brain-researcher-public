"""Tool registry evidence source adapter.

Wraps the ToolRegistry to provide tool matches as KnowledgeItem objects.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from .base import BaseEvidenceSource, SourceCapabilities
from ..models import KnowledgeItem

logger = logging.getLogger(__name__)


class ToolEvidenceSource(BaseEvidenceSource):
    """Evidence source adapter for the tool registry."""

    def __init__(self, light_mode: bool = True):
        """Initialize the tool source.

        Args:
            light_mode: If True, use lightweight tool discovery (faster).
        """
        self._light_mode = light_mode
        self._registry = None
        self._available: Optional[bool] = None

    @property
    def source_id(self) -> str:
        return "tool_registry"

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_text_search=True,
            supports_semantic_search=True,  # Has FAISS indexing
            supports_coordinate_lookup=False,
            supports_entity_resolution=False,
            supports_streaming=False,
            max_results_per_query=30,
            default_timeout_seconds=3.0,
            is_local=True,
            tags=["tools", "analysis", "pipelines"],
        )

    def _get_registry(self):
        """Lazy-load the tool registry."""
        if self._registry is None:
            try:
                from brain_researcher.services.tools.tool_registry import ToolRegistry

                self._registry = ToolRegistry(
                    auto_discover=True,
                    light_mode=self._light_mode,
                )
            except Exception as e:
                logger.warning("Failed to load tool registry: %s", e)
                self._registry = None
        return self._registry

    async def is_available(self) -> bool:
        """Check if the tool registry is available."""
        if self._available is not None:
            return self._available

        try:
            registry = self._get_registry()
            self._available = registry is not None and len(registry.tools) > 0
        except Exception as e:
            logger.debug("Tool registry unavailable: %s", e)
            self._available = False

        return self._available

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: Optional[dict] = None,
    ) -> Sequence[KnowledgeItem]:
        """Search tool registry for matching tools.

        Args:
            query: Search text (tool description or keyword)
            limit: Maximum results
            filters: Optional filters like {"tags": ["glm", "fmri"]}

        Returns:
            Sequence of KnowledgeItem objects
        """
        try:
            registry = self._get_registry()
            if not registry:
                return []

            # Get matching tools
            tools = registry.get_tools_for_task(query, k=limit)

            # Convert to KnowledgeItem
            items = []
            for i, tool in enumerate(tools):
                # Calculate score based on position (first match = highest)
                score = 1.0 - (i * 0.05)  # Decreases by 0.05 per position
                score = max(score, 0.1)

                tool_name = tool.get_tool_name()
                tool_desc = tool.get_tool_description()
                tags = getattr(tool, "TAGS", [])

                # Apply tag filters if provided
                if filters and "tags" in filters:
                    required_tags = set(t.lower() for t in filters["tags"])
                    available_tags = set(t.lower() for t in tags)
                    if not required_tags.intersection(available_tags):
                        continue

                items.append(
                    KnowledgeItem(
                        id=f"tool:{tool_name}",
                        source_id=self.source_id,
                        title=tool_name,
                        description=tool_desc[:200] if tool_desc else None,
                        score=score,
                        confidence=0.9,  # Tool matching is heuristic
                        metadata={
                            "tool_name": tool_name,
                            "tags": tags,
                            "full_description": tool_desc,
                        },
                    )
                )

            return items

        except Exception as e:
            logger.warning("Tool registry search failed: %s", e)
            return []

    async def get_by_id(self, item_id: str) -> Optional[KnowledgeItem]:
        """Get a tool by its name."""
        try:
            registry = self._get_registry()
            if not registry:
                return None

            # Strip prefix if present
            tool_name = item_id
            if tool_name.startswith("tool:"):
                tool_name = tool_name[5:]

            # Look up tool
            tool = registry.tools.get(tool_name)
            if not tool:
                return None

            return KnowledgeItem(
                id=f"tool:{tool_name}",
                source_id=self.source_id,
                title=tool_name,
                description=tool.get_tool_description(),
                score=1.0,
                confidence=1.0,
                metadata={
                    "tool_name": tool_name,
                    "tags": getattr(tool, "TAGS", []),
                },
            )

        except Exception as e:
            logger.warning("Tool get_by_id failed for %s: %s", item_id, e)
            return None


__all__ = ["ToolEvidenceSource"]
