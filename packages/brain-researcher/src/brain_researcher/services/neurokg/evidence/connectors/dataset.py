"""
Dataset catalog evidence connector.

Wraps the query_service.search_datasets() function to search for
neuroimaging datasets in the knowledge graph.
"""

from __future__ import annotations

from typing import Any

from ..models import EvidenceItem, EvidenceSource, EvidenceType
from ..protocols import ConnectorError
from .base import SyncWrapperConnector


class DatasetConnector(SyncWrapperConnector):
    """
    Connector for searching the dataset catalog.

    Searches for neuroimaging datasets (OpenNeuro, HCP, etc.) using
    the Neo4j-backed query service with NL-based filter inference.
    """

    @property
    def source(self) -> EvidenceSource:
        return EvidenceSource.DATASET_CATALOG

    @property
    def is_available(self) -> bool:
        """Check if Neo4j is available."""
        try:
            from brain_researcher.services.neurokg.query_service import get_default_db

            db = get_default_db()
            return db is not None
        except Exception:
            return False

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """
        Search for datasets matching the query.

        Args:
            query: Search query (supports NL hints like "fMRI motor task")
            limit: Maximum results
            filters: Optional filters:
                - task_ids: List of task names
                - modality: Modality filter (e.g., "fmri", "meg")
                - min_subjects: Minimum number of subjects
                - species: Species filter (e.g., "human", "mouse")

        Returns:
            List of evidence items
        """
        try:
            from brain_researcher.services.neurokg.query_service import search_datasets
        except ImportError as e:
            raise ConnectorError(self.source, "query_service not available", e)

        # Extract filters
        task_ids = filters.get("task_ids") if filters else None
        modality = filters.get("modality") if filters else None
        min_subjects = filters.get("min_subjects") if filters else None
        species = filters.get("species") if filters else None

        try:
            results = await self._run_sync(
                search_datasets,
                text=query,
                task_ids=task_ids,
                modality=modality,
                min_subjects=min_subjects,
                species=species,
                limit=limit,
                infer_from_text=True,  # Enable NL-based filter inference
            )
        except Exception as e:
            raise ConnectorError(self.source, f"Search failed: {e}", e)

        return [self._to_evidence_item(r) for r in results]

    def _to_evidence_item(self, dataset) -> EvidenceItem:
        """Convert DatasetSummary to EvidenceItem."""
        # Build description from tasks and modalities
        parts = []
        if dataset.tasks:
            parts.append(f"Tasks: {', '.join(dataset.tasks[:3])}")
        if dataset.modalities:
            parts.append(f"Modalities: {', '.join(dataset.modalities)}")
        if dataset.n_subjects:
            parts.append(f"N={dataset.n_subjects}")
        description = "; ".join(parts) if parts else None

        # Ensure dataset_id is a string
        dataset_id = str(dataset.dataset_id) if dataset.dataset_id else ""

        # Generate URL for OpenNeuro datasets
        url = None
        if dataset_id.startswith("ds"):
            url = f"https://openneuro.org/datasets/{dataset_id}"

        return EvidenceItem(
            id=dataset_id,
            source=self.source,
            item_type=EvidenceType.DATASET,
            title=dataset.title or dataset_id,
            description=description,
            url=url,
            score=1.0,  # search_datasets doesn't return scores
            metadata={
                "tasks": dataset.tasks,
                "modalities": dataset.modalities,
                "n_subjects": dataset.n_subjects,
                "species": dataset.species,
                "kg_id": dataset.kg_id,
            },
        )
