"""
NeuroStore evidence connector.

Provides search for neuroimaging meta-analysis studies and statistical maps
via the NeuroStore API.
"""

from __future__ import annotations

from typing import Any

from ..models import EvidenceItem, EvidenceSource, EvidenceType
from ..protocols import ConnectorError
from .base import BaseConnector


class NeuroStoreConnector(BaseConnector):
    """
    Connector for searching NeuroStore meta-analysis studies.

    NeuroStore provides access to neuroimaging studies with coordinates
    and statistical maps.
    """

    BASE_URL = "https://neurostore.org/api"

    @property
    def source(self) -> EvidenceSource:
        return EvidenceSource.NEUROSTORE

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """
        Search NeuroStore for studies.

        Args:
            query: Search query
            limit: Maximum results
            filters: Optional filters (currently unused)

        Returns:
            List of evidence items
        """
        params = {
            "search": query,
            "page_size": limit,
        }

        try:
            data = await self._fetch_json(f"{self.BASE_URL}/studies/", params)
        except ConnectorError:
            raise
        except Exception as e:
            raise ConnectorError(self.source, f"Search failed: {e}", e)

        results = data.get("results", [])
        return [self._to_evidence_item(study) for study in results]

    async def get_by_id(self, item_id: str) -> EvidenceItem | None:
        """Get a specific study by ID."""
        try:
            data = await self._fetch_json(f"{self.BASE_URL}/studies/{item_id}")
            return self._to_evidence_item(data)
        except Exception:
            return None

    def _to_evidence_item(self, study: dict[str, Any]) -> EvidenceItem:
        """Convert NeuroStore study to EvidenceItem."""
        study_id = study.get("id", "")
        name = study.get("name", "")
        description = study.get("description", "")

        # Truncate description
        if description and len(description) > 300:
            description = description[:300] + "..."

        # Count analyses if available
        n_analyses = study.get("n_analyses") or len(study.get("analyses", []))

        return EvidenceItem(
            id=str(study_id),
            source=self.source,
            item_type=EvidenceType.STATISTICAL_MAP,
            title=name,
            description=description if description else None,
            url=f"https://neurostore.org/studies/{study_id}",
            doi=study.get("doi"),
            score=0.8,  # Default score
            metadata={
                "n_analyses": n_analyses,
                "publication": study.get("publication"),
                "authors": study.get("authors", []),
                "year": study.get("year"),
            },
        )
