"""Tests for literature evidence source adapter."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.evidence.literature_source import (
    LiteratureEvidenceSource,
    search_literature,
    search_literature_sync,
)


class TestLiteratureEvidenceSource:
    """Test suite for LiteratureEvidenceSource."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = LiteratureEvidenceSource(api_key="test-api-key")

    def test_source_properties(self):
        """Test source type and id properties."""
        assert self.source.source_type == EvidenceSourceType.LITERATURE
        assert self.source.source_id == "pubmed"

    def test_source_without_api_key(self):
        """Test source can be created without explicit api key."""
        source = LiteratureEvidenceSource()
        # Should try to get from env var
        assert source._api_key is None or isinstance(source._api_key, str)

    @patch.dict("os.environ", {"NCBI_API_KEY": "env-api-key"})
    def test_source_uses_env_api_key(self):
        """Test source reads API key from environment."""
        source = LiteratureEvidenceSource()
        assert source._api_key == "env-api-key"

    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    def test_lazy_connector_creation(self, mock_connector_class):
        """Test connector is lazily created on first use."""
        mock_connector = MagicMock()
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        connector = source._get_connector()

        mock_connector_class.assert_called_once_with(api_key="test-key")
        assert connector is mock_connector

    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    def test_connector_reused(self, mock_connector_class):
        """Test connector is reused on subsequent calls."""
        mock_connector = MagicMock()
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        connector1 = source._get_connector()
        connector2 = source._get_connector()

        # Should only create once
        mock_connector_class.assert_called_once()
        assert connector1 is connector2

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_query_basic(self, mock_connector_class):
        """Test basic async query returns results."""
        # Setup mock
        mock_item = MagicMock()
        mock_item.id = "pmid:12345"
        mock_item.title = "Brain Connectivity in Motor Learning"
        mock_item.score = 0.95
        mock_item.metadata = {
            "authors": ["Smith J", "Doe A"],
            "journal": "Nature Neuroscience",
            "year": 2023,
        }
        mock_item.doi = "10.1038/s41593-023-12345"
        mock_item.item_type = MagicMock(value="publication")
        mock_item.url = "https://pubmed.ncbi.nlm.nih.gov/12345/"
        mock_item.description = "This study examines brain connectivity..."

        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(return_value=[mock_item])
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        query = EvidenceQuery(text="brain connectivity motor learning", limit=10)
        results = await source.query(query)

        assert len(results) == 1
        assert results[0].source == EvidenceSourceType.LITERATURE
        assert results[0].id == "pmid:12345"
        assert results[0].title == "Brain Connectivity in Motor Learning"
        assert results[0].relevance_score == 0.95
        assert results[0].confidence == 0.9  # PubMed is authoritative
        assert results[0].payload["authors"] == ["Smith J", "Doe A"]
        assert results[0].payload["doi"] == "10.1038/s41593-023-12345"
        assert results[0].url == "https://pubmed.ncbi.nlm.nih.gov/12345/"

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_query_with_year_filters(self, mock_connector_class):
        """Test query with year filters."""
        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(return_value=[])
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        query = EvidenceQuery(
            text="fmri analysis",
            year_min=2020,
            year_max=2023,
            limit=20,
        )
        await source.query(query)

        # Check filters were passed
        call_kwargs = mock_connector.search.call_args[1]
        assert call_kwargs["filters"]["year_from"] == 2020
        assert call_kwargs["filters"]["year_to"] == 2023
        assert call_kwargs["limit"] == 20

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_query_no_results(self, mock_connector_class):
        """Test query with no matching publications."""
        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(return_value=[])
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        query = EvidenceQuery(text="nonexistent topic xyz123")
        results = await source.query(query)

        assert results == []

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_query_handles_connector_error(self, mock_connector_class):
        """Test query handles connector errors gracefully."""
        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(side_effect=Exception("API rate limit exceeded"))
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        query = EvidenceQuery(text="test query")
        results = await source.query(query)

        assert results == []

    @pytest.mark.asyncio
    async def test_query_connector_unavailable(self):
        """Test query when connector import fails."""
        source = LiteratureEvidenceSource(api_key="test-key")

        with patch.object(source, "_get_connector", return_value=None):
            query = EvidenceQuery(text="test query")
            results = await source.query(query)

            assert results == []

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_query_multiple_results(self, mock_connector_class):
        """Test query returning multiple publications."""
        mock_items = []
        for i in range(5):
            item = MagicMock()
            item.id = f"pmid:1000{i}"
            item.title = f"Paper {i}: Brain Research"
            item.score = 0.9 - i * 0.1
            item.metadata = {"authors": [f"Author {i}"], "journal": "Brain", "year": 2023}
            item.doi = f"10.1000/brain.{i}"
            item.item_type = MagicMock(value="publication")
            item.url = f"https://pubmed.ncbi.nlm.nih.gov/1000{i}/"
            item.description = f"Abstract for paper {i}"
            mock_items.append(item)

        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(return_value=mock_items)
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        query = EvidenceQuery(text="brain research", limit=10)
        results = await source.query(query)

        assert len(results) == 5
        # Check scores are preserved
        assert results[0].relevance_score == 0.9
        assert results[4].relevance_score == 0.5

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_query_handles_missing_score(self, mock_connector_class):
        """Test query handles items without score."""
        mock_item = MagicMock()
        mock_item.id = "pmid:99999"
        mock_item.title = "A Paper"
        mock_item.score = None  # No score
        mock_item.metadata = {}
        mock_item.doi = None
        mock_item.item_type = None
        mock_item.url = None
        mock_item.description = None

        mock_connector = MagicMock()
        mock_connector.search = AsyncMock(return_value=[mock_item])
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        query = EvidenceQuery(text="test")
        results = await source.query(query)

        assert len(results) == 1
        assert results[0].relevance_score == 0.8  # Default score

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_health_check_available(self, mock_connector_class):
        """Test health check when connector is available."""
        mock_connector = MagicMock()
        mock_connector.is_available = True
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        result = await source.health_check()

        assert result is True

    @pytest.mark.asyncio
    @patch("brain_researcher.services.neurokg.evidence.connectors.pubmed.PubMedConnector")
    async def test_health_check_unavailable(self, mock_connector_class):
        """Test health check when connector is unavailable."""
        mock_connector = MagicMock()
        mock_connector.is_available = False
        mock_connector_class.return_value = mock_connector

        source = LiteratureEvidenceSource(api_key="test-key")
        result = await source.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_connector_fails(self):
        """Test health check when connector creation fails."""
        source = LiteratureEvidenceSource(api_key="test-key")

        with patch.object(source, "_get_connector", side_effect=Exception("Import failed")):
            result = await source.health_check()
            assert result is False


class TestSearchLiteratureFunction:
    """Test search_literature async convenience function."""

    @pytest.mark.asyncio
    @patch("brain_researcher.services.knowledge.evidence.literature_source.LiteratureEvidenceSource")
    async def test_search_literature_basic(self, mock_source_class):
        """Test basic search_literature call."""
        mock_source = MagicMock()
        mock_source.query = AsyncMock(return_value=[])
        mock_source_class.return_value = mock_source

        results = await search_literature("brain imaging", limit=5)

        mock_source.query.assert_called_once()
        query = mock_source.query.call_args[0][0]
        assert query.text == "brain imaging"
        assert query.limit == 5

    @pytest.mark.asyncio
    @patch("brain_researcher.services.knowledge.evidence.literature_source.LiteratureEvidenceSource")
    async def test_search_literature_with_years(self, mock_source_class):
        """Test search_literature with year filters."""
        mock_source = MagicMock()
        mock_source.query = AsyncMock(return_value=[])
        mock_source_class.return_value = mock_source

        results = await search_literature(
            "fmri connectivity",
            year_min=2018,
            year_max=2023,
            limit=20,
        )

        query = mock_source.query.call_args[0][0]
        assert query.year_min == 2018
        assert query.year_max == 2023


class TestSearchLiteratureSyncFunction:
    """Test search_literature_sync synchronous convenience function."""

    @patch("brain_researcher.services.knowledge.evidence.literature_source.LiteratureEvidenceSource")
    def test_search_literature_sync_basic(self, mock_source_class):
        """Test basic search_literature_sync call."""
        mock_result = MagicMock()
        mock_result.id = "pmid:12345"

        mock_source = MagicMock()
        mock_source.query = AsyncMock(return_value=[mock_result])
        mock_source_class.return_value = mock_source

        results = search_literature_sync("brain imaging", limit=5)

        assert len(results) == 1
        assert results[0].id == "pmid:12345"

    @patch("brain_researcher.services.knowledge.evidence.literature_source.LiteratureEvidenceSource")
    def test_search_literature_sync_with_filters(self, mock_source_class):
        """Test search_literature_sync with all filters."""
        mock_source = MagicMock()
        mock_source.query = AsyncMock(return_value=[])
        mock_source_class.return_value = mock_source

        results = search_literature_sync(
            "eeg analysis",
            year_min=2020,
            year_max=2024,
            limit=15,
        )

        # Verify the async function was called with correct parameters
        mock_source.query.assert_called_once()
        query = mock_source.query.call_args[0][0]
        assert query.text == "eeg analysis"
        assert query.year_min == 2020
        assert query.year_max == 2024
        assert query.limit == 15
