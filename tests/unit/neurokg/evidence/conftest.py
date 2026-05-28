"""Shared fixtures for evidence module tests."""

import pytest

from brain_researcher.services.neurokg.evidence.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceType,
)
from brain_researcher.services.neurokg.evidence.protocols import ConnectorError


@pytest.fixture
def sample_evidence_item():
    """Create a sample evidence item for testing."""
    return EvidenceItem(
        id="test-123",
        source=EvidenceSource.NEUROKG,
        item_type=EvidenceType.CONCEPT,
        title="Working Memory",
        description="A cognitive system for temporary information storage",
        score=0.95,
        metadata={"node_type": "CognitiveConcept"},
    )


@pytest.fixture
def sample_evidence_items():
    """Create multiple sample evidence items for testing."""
    return [
        EvidenceItem(
            id="concept-1",
            source=EvidenceSource.NEUROKG,
            item_type=EvidenceType.CONCEPT,
            title="Working Memory",
            score=0.9,
        ),
        EvidenceItem(
            id="ds000001",
            source=EvidenceSource.DATASET_CATALOG,
            item_type=EvidenceType.DATASET,
            title="Balloon Analog Risk Task",
            score=0.85,
        ),
        EvidenceItem(
            id="pmid:12345",
            source=EvidenceSource.PUBMED,
            item_type=EvidenceType.PUBLICATION,
            title="Neural correlates of working memory",
            score=0.8,
        ),
    ]


class MockConnector:
    """Mock connector for testing."""

    def __init__(
        self,
        source: EvidenceSource,
        items: list[EvidenceItem] | None = None,
        error: str | None = None,
        available: bool = True,
    ):
        self._source = source
        self._items = items or []
        self._error = error
        self._available = available

    @property
    def source(self) -> EvidenceSource:
        return self._source

    @property
    def is_available(self) -> bool:
        return self._available

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict | None = None,
    ) -> list[EvidenceItem]:
        if self._error:
            raise ConnectorError(self._source, self._error)
        return self._items[:limit]

    async def get_by_id(self, item_id: str) -> EvidenceItem | None:
        for item in self._items:
            if item.id == item_id:
                return item
        return None


@pytest.fixture
def mock_neurokg_connector(sample_evidence_items):
    """Create a mock BR-KG connector."""
    items = [i for i in sample_evidence_items if i.source == EvidenceSource.NEUROKG]
    return MockConnector(EvidenceSource.NEUROKG, items)


@pytest.fixture
def mock_dataset_connector(sample_evidence_items):
    """Create a mock dataset connector."""
    items = [i for i in sample_evidence_items if i.source == EvidenceSource.DATASET_CATALOG]
    return MockConnector(EvidenceSource.DATASET_CATALOG, items)


@pytest.fixture
def mock_failing_connector():
    """Create a mock connector that always fails."""
    return MockConnector(EvidenceSource.PUBMED, error="API unavailable")


@pytest.fixture
def mock_unavailable_connector():
    """Create a mock connector that is unavailable."""
    return MockConnector(EvidenceSource.NEUROSTORE, available=False)
