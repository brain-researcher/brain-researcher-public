"""Tool registry evidence source adapter.

Wraps the ToolRegistry to provide evidence about available analysis tools
via the EvidenceSource protocol.
"""

from __future__ import annotations

import logging
import os

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
    SyncEvidenceSourceAdapter,
)

logger = logging.getLogger(__name__)


class ToolEvidenceSource(SyncEvidenceSourceAdapter):
    """Evidence source adapter for the tool registry.

    Wraps ToolRegistry.get_tools_for_task() to provide evidence about
    available analysis tools matching a query.
    """

    def __init__(self, registry=None, use_kg: bool | None = None):
        """Initialize the tool evidence source.

        Args:
            registry: Optional ToolRegistry instance. If None, will
                     create/get the default registry on first use.
            use_kg: Whether to also query BR-KG structured tool search.
                    If None, defaults to enabled only when no registry is supplied.
        """
        self._registry = registry
        if use_kg is None:
            # When a registry is injected (usually tests), avoid KG side-effects.
            enable = registry is None
        else:
            enable = bool(use_kg)

        if enable:
            self._use_kg = os.getenv("BR_KG_TOOL_DISCOVERY", "").lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        else:
            self._use_kg = False

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.TOOL_REGISTRY

    @property
    def source_id(self) -> str:
        return "tool_registry"

    def _get_registry(self):
        """Get or create the tool registry."""
        if self._registry is not None:
            return self._registry

        try:
            from brain_researcher.services.tools.tool_registry import ToolRegistry

            self._registry = ToolRegistry()
            return self._registry
        except Exception as exc:
            logger.warning("Failed to create ToolRegistry: %s", exc)
            return None

    def query_sync(self, query: EvidenceQuery) -> list[EvidenceResult]:
        """Query the tool registry for matching tools.

        Args:
            query: EvidenceQuery with text describing the desired analysis.

        Returns:
            List of EvidenceResult objects for matching tools.
        """
        results: list[EvidenceResult] = []

        registry = self._get_registry()
        if registry is None and not self._use_kg:
            return results

        seen_ids: set[str] = set()

        # ------------------------------------------------------------------
        # KG-backed discovery (optional, best-effort)
        # ------------------------------------------------------------------
        if self._use_kg:
            try:
                from brain_researcher.services.br_kg import query_service

                kg_data = query_service.search_tools_structured(
                    query=query.text,
                    exposed_only=True,
                    k_candidates=max(20, query.limit),
                )
                candidates = (
                    (kg_data or {}).get("candidates", [])
                    if isinstance(kg_data, dict)
                    else []
                )

                for idx, cand in enumerate(candidates[: query.limit]):
                    tool_id = str(cand.get("tool_id") or "")
                    if not tool_id or tool_id in seen_ids:
                        continue

                    resolved_id = tool_id
                    try:
                        resolution = query_service.resolve_tool_structured(
                            method=cand.get("method"),
                            software=cand.get("software"),
                            op_key=cand.get("op_key"),
                            prefer_version=cand.get("version"),
                            exposed_only=True,
                            default_only=True,
                        )
                        if isinstance(resolution, dict):
                            rec = resolution.get("recommendation") or {}
                            resolved_id = str(rec.get("tool_id") or resolved_id)
                    except Exception:
                        pass

                    score = max(0.1, 1.0 - (idx * 0.05))
                    results.append(
                        EvidenceResult(
                            source=EvidenceSourceType.TOOL_REGISTRY,
                            id=resolved_id,
                            title=resolved_id,
                            relevance_score=score,
                            confidence=0.85,
                            payload={
                                "source": "br_kg",
                                "kg_tool_id": tool_id,
                                "method": cand.get("method"),
                                "software": cand.get("software"),
                                "op_key": cand.get("op_key"),
                                "version": cand.get("version"),
                            },
                            summary=f"KG tool match: {resolved_id}",
                        )
                    )
                    seen_ids.add(resolved_id)
            except Exception as exc:
                logger.warning("KG tool search failed: %s", exc)

        try:
            # Use the registry's built-in search
            tools = (
                registry.get_tools_for_task(query.text, k=query.limit)
                if registry
                else []
            )

            for i, tool in enumerate(tools):
                # Get tool metadata
                name = tool.get_tool_name()
                description = tool.get_tool_description()
                tags = getattr(tool, "TAGS", [])

                # Calculate relevance based on position in results
                relevance = max(0.5, 1.0 - (i * 0.1))

                if name in seen_ids:
                    continue
                results.append(
                    EvidenceResult(
                        source=EvidenceSourceType.TOOL_REGISTRY,
                        id=name,
                        title=name,
                        relevance_score=relevance,
                        confidence=0.85,
                        payload={
                            "description": description,
                            "tags": tags,
                            "tool_class": tool.__class__.__name__,
                        },
                        summary=description[:200] if description else name,
                    )
                )
                seen_ids.add(name)

        except Exception as exc:
            logger.warning("Tool registry query failed: %s", exc)

        return results

    def health_check_sync(self) -> bool:
        """Check if the tool registry is available."""
        try:
            registry = self._get_registry()
            return registry is not None
        except Exception:
            return False


def search_tools(
    query_text: str,
    limit: int = 10,
) -> list[EvidenceResult]:
    """Convenience function to search for tool evidence.

    Args:
        query_text: Description of the desired analysis/task.
        limit: Maximum results to return.

    Returns:
        List of EvidenceResult for matching tools.
    """
    source = ToolEvidenceSource()
    query = EvidenceQuery(text=query_text, limit=limit)
    return source.query_sync(query)


__all__ = [
    "ToolEvidenceSource",
    "search_tools",
]
