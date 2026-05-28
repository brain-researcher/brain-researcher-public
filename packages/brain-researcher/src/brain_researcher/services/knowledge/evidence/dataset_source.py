"""Dataset catalog evidence source adapter.

Wraps the dataset catalog and KG dataset search to provide evidence via
the EvidenceSource protocol.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
    SyncEvidenceSourceAdapter,
)

logger = logging.getLogger(__name__)


class DatasetEvidenceSource(SyncEvidenceSourceAdapter):
    """Evidence source adapter for the dataset catalog.

    Combines two search strategies:
    1. Local catalog search via text matching on DatasetRecord.search_blob
    2. KG-based search via query_service.search_datasets()

    The results are deduplicated and merged.
    """

    def __init__(
        self,
        catalog_path: Optional[Path] = None,
        use_kg: bool = True,
        db=None,
    ):
        """Initialize the dataset evidence source.

        Args:
            catalog_path: Path to the dataset catalog JSONL file.
            use_kg: Whether to also search the KG for datasets.
            db: Optional Neo4jGraphDB instance for testing.
        """
        self._catalog_path = catalog_path
        self._use_kg = use_kg
        self._db = db

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.DATASET_CATALOG

    @property
    def source_id(self) -> str:
        return "dataset_catalog"

    def query_sync(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Query the dataset catalog for matching datasets.

        Args:
            query: EvidenceQuery with text and optional filters (modality,
                   min_subjects).

        Returns:
            List of EvidenceResult objects for matching datasets.
        """
        results: List[EvidenceResult] = []
        seen_ids: set[str] = set()

        # Strategy 1: Local catalog search
        try:
            catalog_results = self._search_catalog(query)
            for r in catalog_results:
                if r.id not in seen_ids:
                    results.append(r)
                    seen_ids.add(r.id)
        except Exception as exc:
            logger.warning("Catalog search failed: %s", exc)

        # Strategy 2: KG-based search (if enabled)
        if self._use_kg:
            try:
                kg_results = self._search_kg(query)
                for r in kg_results:
                    if r.id not in seen_ids:
                        results.append(r)
                        seen_ids.add(r.id)
            except Exception as exc:
                logger.warning("KG dataset search failed: %s", exc)

        # Sort by relevance
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        return results[: query.limit]

    def _search_catalog(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Search the local dataset catalog."""
        from brain_researcher.core.datasets.catalog import (
            DEFAULT_CATALOG_PATH,
            load_catalog,
        )

        catalog_path = self._catalog_path or DEFAULT_CATALOG_PATH
        catalog = load_catalog(catalog_path)

        query_lower = query.text.lower()
        results: List[EvidenceResult] = []

        for record in catalog:
            # Text matching on search_blob
            search_text = record.search_blob.lower()
            if query_lower not in search_text:
                continue

            # Apply filters
            if query.modality:
                modality_match = any(
                    query.modality.lower() in str(m).lower()
                    for m in record.modalities
                )
                if not modality_match:
                    continue

            if query.min_subjects and record.subjects_count:
                if record.subjects_count < query.min_subjects:
                    continue

            # Calculate simple relevance score
            score = self._calculate_relevance(query_lower, record)

            results.append(
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id=record.dataset_id,
                    title=record.name,
                    relevance_score=score,
                    confidence=0.9,  # Catalog matches are reliable
                    payload={
                        "modalities": [str(m) for m in record.modalities],
                        "tasks": record.tasks,
                        "subjects_count": record.subjects_count,
                        "source_repo": record.source_repo,
                        "source_repo_id": record.source_repo_id,
                        "access_type": str(record.access_type),
                        "has_derivatives": record.has_derivatives,
                    },
                    url=str(record.primary_url) if record.primary_url else None,
                    summary=record.description[:200] if record.description else None,
                )
            )

        return results

    def _search_kg(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Search the KG for datasets."""
        from brain_researcher.services.neurokg import query_service

        datasets = query_service.search_datasets(
            text=query.text,
            modality=query.modality,
            min_subjects=query.min_subjects,
            limit=query.limit,
            db=self._db,
        )

        results: List[EvidenceResult] = []
        for ds in datasets:
            results.append(
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id=ds.dataset_id,
                    title=ds.title,
                    relevance_score=0.7,  # KG matches get slightly lower default
                    confidence=0.8,
                    payload={
                        "modalities": ds.modalities,
                        "tasks": ds.tasks,
                        "n_subjects": ds.n_subjects,
                        "species": ds.species,
                        "kg_id": ds.kg_id,
                    },
                    summary=f"Dataset: {ds.title or ds.dataset_id}",
                )
            )

        return results

    def _calculate_relevance(self, query_lower: str, record) -> float:
        """Calculate relevance score for a dataset record."""
        score = 0.5  # Base score for any match

        # Exact name match bonus
        if query_lower in record.name.lower():
            score += 0.3

        # Task match bonus
        for task in record.tasks:
            if query_lower in task.lower():
                score += 0.1
                break

        # Tag match bonus
        for tag in record.tags:
            if query_lower in tag.lower():
                score += 0.05

        return min(1.0, score)

    def health_check_sync(self) -> bool:
        """Check if the catalog is accessible."""
        try:
            from brain_researcher.core.datasets.catalog import (
                DEFAULT_CATALOG_PATH,
                load_catalog,
            )

            catalog_path = self._catalog_path or DEFAULT_CATALOG_PATH
            catalog = load_catalog(catalog_path)
            return len(catalog) > 0
        except Exception:
            return False


def search_datasets(
    query_text: str,
    modality: Optional[str] = None,
    min_subjects: Optional[int] = None,
    limit: int = 10,
) -> List[EvidenceResult]:
    """Convenience function to search for dataset evidence.

    Args:
        query_text: Free-text search query.
        modality: Optional modality filter (fmri, eeg, etc.).
        min_subjects: Optional minimum subject count filter.
        limit: Maximum results to return.

    Returns:
        List of EvidenceResult for matching datasets.
    """
    source = DatasetEvidenceSource()
    query = EvidenceQuery(
        text=query_text,
        modality=modality,
        min_subjects=min_subjects,
        limit=limit,
    )
    return source.query_sync(query)


__all__ = [
    "DatasetEvidenceSource",
    "search_datasets",
]
