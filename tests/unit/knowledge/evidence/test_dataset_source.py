"""Tests for dataset evidence source adapter."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.evidence.dataset_source import (
    DatasetEvidenceSource,
    search_datasets,
)


class TestDatasetEvidenceSource:
    """Test suite for DatasetEvidenceSource."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = MagicMock()
        self.source = DatasetEvidenceSource(use_kg=False, db=self.mock_db)

    def test_source_properties(self):
        """Test source type and id properties."""
        assert self.source.source_type == EvidenceSourceType.DATASET_CATALOG
        assert self.source.source_id == "dataset_catalog"

    def test_source_initialization_options(self):
        """Test source can be initialized with various options."""
        # Default options
        source1 = DatasetEvidenceSource()
        assert source1._use_kg is True

        # With custom catalog path
        source2 = DatasetEvidenceSource(catalog_path=Path("/custom/path.jsonl"))
        assert source2._catalog_path == Path("/custom/path.jsonl")

        # Disable KG search
        source3 = DatasetEvidenceSource(use_kg=False)
        assert source3._use_kg is False

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_catalog_search(self, mock_load_catalog):
        """Test query searches local catalog."""
        # Setup mock catalog
        mock_record = MagicMock()
        mock_record.dataset_id = "ds000001"
        mock_record.name = "Motor Task fMRI"
        mock_record.description = "A dataset with motor task fMRI data."
        mock_record.search_blob = "motor task fmri bold ds000001"
        mock_record.modalities = ["fmri"]
        mock_record.tasks = ["motor"]
        mock_record.tags = ["task-fmri"]
        mock_record.subjects_count = 30
        mock_record.source_repo = "OpenNeuro"
        mock_record.source_repo_id = "ds000001"
        mock_record.access_type = "open"
        mock_record.has_derivatives = True
        mock_record.primary_url = "https://openneuro.org/datasets/ds000001"

        mock_load_catalog.return_value = [mock_record]

        query = EvidenceQuery(text="motor", limit=5)
        results = self.source.query_sync(query)

        assert len(results) == 1
        assert results[0].source == EvidenceSourceType.DATASET_CATALOG
        assert results[0].id == "ds000001"
        assert results[0].title == "Motor Task fMRI"
        assert isinstance(results[0].payload["modalities"], list)
        assert "fmri" in results[0].payload["modalities"]
        assert results[0].payload["source_repo"] == "OpenNeuro"

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_no_matches(self, mock_load_catalog):
        """Test query with no matching datasets."""
        mock_record = MagicMock()
        mock_record.search_blob = "visual perception eeg"
        mock_load_catalog.return_value = [mock_record]

        query = EvidenceQuery(text="motor cortex fmri")
        results = self.source.query_sync(query)

        assert results == []

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_modality_filter(self, mock_load_catalog):
        """Test query with modality filter."""
        # Create two datasets with different modalities
        fmri_record = MagicMock()
        fmri_record.dataset_id = "ds001"
        fmri_record.name = "fMRI Dataset"
        fmri_record.description = "An fMRI dataset"
        fmri_record.search_blob = "brain imaging study"
        fmri_record.modalities = ["fmri"]
        fmri_record.tasks = []
        fmri_record.tags = []
        fmri_record.subjects_count = 20
        fmri_record.source_repo = "OpenNeuro"
        fmri_record.source_repo_id = "ds001"
        fmri_record.access_type = "open"
        fmri_record.has_derivatives = False
        fmri_record.primary_url = None

        eeg_record = MagicMock()
        eeg_record.search_blob = "brain imaging study"
        eeg_record.modalities = ["eeg"]

        mock_load_catalog.return_value = [fmri_record, eeg_record]

        query = EvidenceQuery(text="brain imaging", modality="fmri", limit=10)
        results = self.source.query_sync(query)

        # Should only return fMRI dataset
        assert len(results) == 1
        assert results[0].id == "ds001"

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_min_subjects_filter(self, mock_load_catalog):
        """Test query with minimum subjects filter."""
        small_study = MagicMock()
        small_study.dataset_id = "ds_small"
        small_study.search_blob = "brain study"
        small_study.modalities = []
        small_study.subjects_count = 10

        large_study = MagicMock()
        large_study.dataset_id = "ds_large"
        large_study.name = "Large Study"
        large_study.description = "A large brain study"
        large_study.search_blob = "brain study"
        large_study.modalities = []
        large_study.tasks = []
        large_study.tags = []
        large_study.subjects_count = 100
        large_study.source_repo = "OpenNeuro"
        large_study.source_repo_id = "ds_large"
        large_study.access_type = "open"
        large_study.has_derivatives = False
        large_study.primary_url = None

        mock_load_catalog.return_value = [small_study, large_study]

        query = EvidenceQuery(text="brain", min_subjects=50, limit=10)
        results = self.source.query_sync(query)

        assert len(results) == 1
        assert results[0].id == "ds_large"

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_relevance_scoring(self, mock_load_catalog):
        """Test relevance scoring for matched datasets."""
        # Dataset with exact name match
        exact_match = MagicMock()
        exact_match.dataset_id = "ds_exact"
        exact_match.name = "Motor Task"
        exact_match.description = "Motor task dataset"
        exact_match.search_blob = "motor task fmri"
        exact_match.modalities = []
        exact_match.tasks = ["motor"]
        exact_match.tags = ["task-motor"]
        exact_match.subjects_count = 20
        exact_match.source_repo = "OpenNeuro"
        exact_match.source_repo_id = "ds_exact"
        exact_match.access_type = "open"
        exact_match.has_derivatives = False
        exact_match.primary_url = None

        # Dataset with only blob match
        blob_match = MagicMock()
        blob_match.dataset_id = "ds_blob"
        blob_match.name = "Some Other Study"
        blob_match.description = "A study involving motor tasks"
        blob_match.search_blob = "motor imagery experiment"
        blob_match.modalities = []
        blob_match.tasks = []
        blob_match.tags = []
        blob_match.subjects_count = 15
        blob_match.source_repo = "OpenNeuro"
        blob_match.source_repo_id = "ds_blob"
        blob_match.access_type = "open"
        blob_match.has_derivatives = False
        blob_match.primary_url = None

        mock_load_catalog.return_value = [exact_match, blob_match]

        query = EvidenceQuery(text="motor", limit=10)
        results = self.source.query_sync(query)

        assert len(results) == 2
        # Exact name match should have higher relevance
        exact_result = next(r for r in results if r.id == "ds_exact")
        blob_result = next(r for r in results if r.id == "ds_blob")
        assert exact_result.relevance_score > blob_result.relevance_score

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_handles_catalog_error(self, mock_load_catalog):
        """Test query handles catalog loading errors."""
        mock_load_catalog.side_effect = FileNotFoundError("Catalog not found")

        query = EvidenceQuery(text="test")
        results = self.source.query_sync(query)

        assert results == []

    @patch("brain_researcher.services.neurokg.query_service.search_datasets")
    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_with_kg_search(self, mock_load_catalog, mock_kg_search):
        """Test query combines catalog and KG results."""
        # Enable KG search
        source = DatasetEvidenceSource(use_kg=True, db=self.mock_db)

        # Empty catalog
        mock_load_catalog.return_value = []

        # KG returns a dataset
        mock_ds = MagicMock()
        mock_ds.dataset_id = "kg_dataset"
        mock_ds.title = "KG Found Dataset"
        mock_ds.modalities = ["fmri"]
        mock_ds.tasks = []
        mock_ds.n_subjects = 50
        mock_ds.species = "human"
        mock_ds.kg_id = "dataset:kg_dataset"

        mock_kg_search.return_value = [mock_ds]

        query = EvidenceQuery(text="connectivity", limit=5)
        results = source.query_sync(query)

        assert len(results) == 1
        assert results[0].id == "kg_dataset"
        assert results[0].payload["kg_id"] == "dataset:kg_dataset"
        # KG results default to a slightly higher relevance score
        assert results[0].relevance_score == 0.7

    @patch("brain_researcher.services.neurokg.query_service.search_datasets")
    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_query_sync_deduplicates_results(self, mock_load_catalog, mock_kg_search):
        """Test that duplicate results are deduplicated."""
        source = DatasetEvidenceSource(use_kg=True, db=self.mock_db)

        # Same dataset in both catalog and KG
        catalog_record = MagicMock()
        catalog_record.dataset_id = "ds000001"
        catalog_record.name = "Dataset 1"
        catalog_record.description = "Test dataset"
        catalog_record.search_blob = "fmri connectivity"
        catalog_record.modalities = ["fmri"]
        catalog_record.tasks = []
        catalog_record.tags = []
        catalog_record.subjects_count = 20
        catalog_record.source_repo = "OpenNeuro"
        catalog_record.source_repo_id = "ds000001"
        catalog_record.access_type = "open"
        catalog_record.has_derivatives = False
        catalog_record.primary_url = None

        mock_load_catalog.return_value = [catalog_record]

        kg_record = MagicMock()
        kg_record.dataset_id = "ds000001"
        kg_record.title = "Dataset 1"
        kg_record.modalities = ["fmri"]
        kg_record.tasks = []
        kg_record.n_subjects = 20
        kg_record.species = "human"
        kg_record.kg_id = "dataset:ds000001"

        mock_kg_search.return_value = [kg_record]

        query = EvidenceQuery(text="fmri", limit=10)
        results = source.query_sync(query)

        # Should only have one result (deduplicated)
        assert len(results) == 1
        assert results[0].id == "ds000001"

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_health_check_sync(self, mock_load_catalog):
        """Test health check verifies catalog is accessible."""
        mock_load_catalog.return_value = [MagicMock()]

        result = self.source.health_check_sync()
        assert result is True

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_health_check_sync_empty_catalog(self, mock_load_catalog):
        """Test health check fails with empty catalog."""
        mock_load_catalog.return_value = []

        result = self.source.health_check_sync()
        assert result is False

    @patch("brain_researcher.core.datasets.catalog.load_catalog")
    def test_health_check_sync_error(self, mock_load_catalog):
        """Test health check handles errors."""
        mock_load_catalog.side_effect = Exception("Load failed")

        result = self.source.health_check_sync()
        assert result is False


class TestSearchDatasetsFunction:
    """Test search_datasets convenience function."""

    @patch("brain_researcher.services.knowledge.evidence.dataset_source.DatasetEvidenceSource")
    def test_search_datasets_basic(self, mock_source_class):
        """Test basic search_datasets call."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = []
        mock_source_class.return_value = mock_source

        results = search_datasets("motor fmri", limit=5)

        mock_source.query_sync.assert_called_once()
        query = mock_source.query_sync.call_args[0][0]
        assert query.text == "motor fmri"
        assert query.limit == 5

    @patch("brain_researcher.services.knowledge.evidence.dataset_source.DatasetEvidenceSource")
    def test_search_datasets_with_filters(self, mock_source_class):
        """Test search_datasets with filters."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = []
        mock_source_class.return_value = mock_source

        results = search_datasets(
            "resting state",
            modality="fmri",
            min_subjects=50,
            limit=20,
        )

        query = mock_source.query_sync.call_args[0][0]
        assert query.modality == "fmri"
        assert query.min_subjects == 50
        assert query.limit == 20
