"""Dataset catalog evidence source adapter.

Wraps the kg_resolution dataset resolution to provide dataset matches
as KnowledgeItem objects.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from .base import BaseEvidenceSource, SourceCapabilities
from ..models import KnowledgeItem

logger = logging.getLogger(__name__)


class DatasetEvidenceSource(BaseEvidenceSource):
    """Evidence source adapter for the dataset catalog."""

    def __init__(self):
        self._available: Optional[bool] = None

    @property
    def source_id(self) -> str:
        return "dataset_catalog"

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_text_search=True,
            supports_semantic_search=False,
            supports_coordinate_lookup=False,
            supports_entity_resolution=True,
            supports_streaming=False,
            max_results_per_query=50,
            default_timeout_seconds=3.0,
            is_local=True,  # JSONL catalog is local
            tags=["datasets", "openneuro", "bids"],
        )

    async def is_available(self) -> bool:
        """Check if the dataset catalog is available."""
        if self._available is not None:
            return self._available

        try:
            from brain_researcher.core.datasets.catalog import load_catalog

            catalog = load_catalog()
            self._available = len(catalog) > 0
        except Exception as e:
            logger.debug("Dataset catalog unavailable: %s", e)
            self._available = False

        return self._available

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> Sequence[KnowledgeItem]:
        """Search dataset catalog for matching datasets.

        Args:
            query: Search text (dataset name, ID, or keyword)
            limit: Maximum results
            filters: Optional filters like {"modalities": ["fMRI"], "min_subjects": 20}

        Returns:
            Sequence of KnowledgeItem objects
        """
        try:
            from brain_researcher.core.datasets.catalog import load_catalog

            catalog = load_catalog()
            query_lower = query.lower()

            # Score datasets by relevance
            scored_datasets = []
            for dataset in catalog:
                score = 0.0

                # Check dataset ID
                if query_lower in dataset.dataset_id.lower():
                    score += 1.0

                # Check name
                if query_lower in dataset.name.lower():
                    score += 0.8

                # Check aliases
                for alias in dataset.alias or []:
                    if query_lower in alias.lower():
                        score += 0.7
                        break

                # Check tasks
                for task in dataset.tasks or []:
                    if query_lower in task.lower():
                        score += 0.5
                        break

                # Check modalities
                for modality in dataset.modalities or []:
                    if query_lower in modality.lower():
                        score += 0.3
                        break

                # Apply filters
                if filters:
                    if "modalities" in filters:
                        required = set(m.lower() for m in filters["modalities"])
                        available = set(m.lower() for m in (dataset.modalities or []))
                        if not required.intersection(available):
                            continue

                    if "min_subjects" in filters:
                        if (dataset.subjects_count or 0) < filters["min_subjects"]:
                            continue

                if score > 0:
                    scored_datasets.append((dataset, score))

            # Sort by score and limit
            scored_datasets.sort(key=lambda x: x[1], reverse=True)
            top_datasets = scored_datasets[:limit]

            # Convert to KnowledgeItem
            items = []
            for dataset, score in top_datasets:
                items.append(
                    KnowledgeItem(
                        id=f"dataset:{dataset.dataset_id}",
                        source_id=self.source_id,
                        title=dataset.short_name or dataset.name,
                        description=f"Dataset: {dataset.name} ({dataset.source_repo})",
                        score=min(score, 1.0),
                        confidence=1.0,
                        url=str(dataset.primary_url) if dataset.primary_url else None,
                        metadata={
                            "dataset_id": dataset.dataset_id,
                            "source_repo": dataset.source_repo,
                            "modalities": dataset.modalities or [],
                            "tasks": dataset.tasks or [],
                            "subjects_count": dataset.subjects_count,
                            "license": dataset.license,
                        },
                    )
                )

            return items

        except Exception as e:
            logger.warning("Dataset catalog search failed: %s", e)
            return []

    async def get_by_id(self, item_id: str) -> Optional[KnowledgeItem]:
        """Get a dataset by its ID."""
        try:
            from brain_researcher.services.agent.kg_resolution import (
                resolve_dataset_reference,
            )

            # Strip prefix if present
            dataset_id = item_id
            if dataset_id.startswith("dataset:"):
                dataset_id = dataset_id[8:]

            # Resolve dataset
            resolution = resolve_dataset_reference(dataset_id)
            if not resolution:
                return None

            return KnowledgeItem(
                id=f"dataset:{resolution.dataset_id}",
                source_id=self.source_id,
                title=resolution.display_name or resolution.name,
                description=f"Dataset: {resolution.name} ({resolution.source_repo})",
                score=1.0,
                confidence=1.0,
                url=resolution.primary_url,
                metadata={
                    "dataset_id": resolution.dataset_id,
                    "source_repo": resolution.source_repo,
                    "local_path": str(resolution.local_path) if resolution.local_path else None,
                    "bids_path": str(resolution.bids_path) if resolution.bids_path else None,
                    **resolution.metadata,
                },
            )

        except Exception as e:
            logger.warning("Dataset get_by_id failed for %s: %s", item_id, e)
            return None


__all__ = ["DatasetEvidenceSource"]
