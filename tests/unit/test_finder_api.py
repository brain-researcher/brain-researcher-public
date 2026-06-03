"""
Unit tests for the Finder API functionality.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from brain_researcher.services.br_kg import finder_api as finder_module
from brain_researcher.services.br_kg.finder_api import (
    DatasetSearcher,
    FacetCounter,
    Filter,
    NLPFilterParser,
)


def test_dedupe_citations_prefers_publication_for_explicit_alignment():
    items = [
        {
            "id": "study:canonical-1",
            "title": "Working memory in fMRI",
            "source_type": "study",
            "aligned_study_id": "study:canonical-1",
            "aligned_publication_id": "pub:alpha",
        },
        {
            "id": "pub:alpha",
            "pmid": "123",
            "title": "Working memory in fMRI",
            "source_type": "publication",
            "aligned_study_id": "study:canonical-1",
            "aligned_publication_id": "pub:alpha",
        },
    ]

    deduped = finder_module._dedupe_citations(items)

    assert len(deduped) == 1
    assert deduped[0]["id"] == "pub:alpha"
    assert deduped[0]["source_type"] == "publication"


class TestNLPFilterParser:
    """Test natural language to filter parsing."""

    def test_load_spacy_pipeline_falls_back_to_blank_model(self, monkeypatch):
        blank_pipeline = object()
        monkeypatch.setattr(
            finder_module.spacy,
            "load",
            Mock(side_effect=OSError("model missing")),
        )
        monkeypatch.setattr(
            finder_module.spacy,
            "blank",
            Mock(return_value=blank_pipeline),
        )

        pipeline = finder_module.load_spacy_pipeline()

        assert pipeline is blank_pipeline
        finder_module.spacy.blank.assert_called_once_with("en")

    @pytest.fixture
    def parser(self):
        return NLPFilterParser()

    def test_parse_modality_fmri(self, parser):
        """Test parsing fMRI modality."""
        filters = parser.parse("fMRI studies")
        assert any(f.facet == "modality" and f.value == "fmri" for f in filters)

    def test_parse_modality_structural(self, parser):
        """Test parsing structural MRI."""
        filters = parser.parse("structural MRI T1 weighted")
        assert any(f.facet == "modality" and f.value == "structural" for f in filters)

    def test_parse_task_motor(self, parser):
        """Test parsing motor task."""
        filters = parser.parse("motor task finger tapping")
        assert any(f.facet == "task" and f.value == "motor" for f in filters)

    def test_parse_task_memory(self, parser):
        """Test parsing memory task."""
        filters = parser.parse("working memory n-back task")
        assert any(f.facet == "task" and f.value == "memory" for f in filters)

    def test_parse_population_healthy(self, parser):
        """Test parsing healthy population."""
        filters = parser.parse("healthy controls")
        assert any(f.facet == "population" and f.value == "healthy" for f in filters)

    def test_parse_population_clinical(self, parser):
        """Test parsing clinical population."""
        filters = parser.parse("schizophrenia patients")
        assert any(f.facet == "population" and f.value == "clinical" for f in filters)

    def test_parse_year_range(self, parser):
        """Test parsing year range."""
        filters = parser.parse("studies from 2020 to 2023")
        year_filters = [f for f in filters if f.facet == "year"]
        assert len(year_filters) == 2
        assert any(f.op == ">=" and f.value == 2020 for f in year_filters)
        assert any(f.op == "<=" and f.value == 2023 for f in year_filters)

    def test_parse_year_after(self, parser):
        """Test parsing year after."""
        filters = parser.parse("studies after 2020")
        assert any(f.facet == "year" and f.op == ">=" and f.value == 2020 for f in filters)

    def test_parse_sample_size(self, parser):
        """Test parsing sample size."""
        filters = parser.parse("large sample over 100 subjects")
        assert any(f.facet == "sample_size" and f.op == ">=" and f.value == 100 for f in filters)

    def test_parse_multiple_filters(self, parser):
        """Test parsing multiple filters from complex query."""
        filters = parser.parse("fMRI motor task studies after 2020 with over 50 subjects")

        facets = {f.facet for f in filters}
        assert "modality" in facets
        assert "task" in facets
        assert "year" in facets
        assert "sample_size" in facets

    def test_parse_empty_query(self, parser):
        """Test parsing empty query."""
        filters = parser.parse("")
        assert filters == []

    def test_parse_no_filters(self, parser):
        """Test parsing query with no recognizable filters."""
        filters = parser.parse("random text without any filters")
        assert filters == []


class TestFacetCounter:
    """Test facet counting functionality."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = Mock()
        return mock

    @pytest.fixture
    def counter(self, mock_neo4j):
        return FacetCounter(mock_neo4j)

    def test_count_facets_with_results(self, counter, mock_neo4j):
        """Test counting facets with results."""
        # Mock Neo4j response
        mock_neo4j.run.return_value = [
            {"facet": "modality", "value": "fmri", "count": 150},
            {"facet": "modality", "value": "structural", "count": 75},
            {"facet": "task", "value": "motor", "count": 30},
            {"facet": "task", "value": "memory", "count": 45}
        ]

        filters = [Filter(facet="modality", value="fmri")]
        result = counter.count_facets(filters)

        assert "modality" in result
        assert "task" in result
        assert result["modality"]["fmri"] == 150
        assert result["task"]["motor"] == 30

    def test_count_facets_empty_filters(self, counter, mock_neo4j):
        """Test counting facets with no filters."""
        mock_neo4j.run.return_value = [
            {"facet": "modality", "value": "fmri", "count": 200}
        ]

        result = counter.count_facets([])

        assert "modality" in result
        assert result["modality"]["fmri"] == 200

    def test_count_facets_no_results(self, counter, mock_neo4j):
        """Test counting facets with no results."""
        mock_neo4j.run.return_value = []

        result = counter.count_facets([])

        assert result == {}


class TestDatasetSearcher:
    """Test dataset searching functionality."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = Mock()
        return mock

    @pytest.fixture
    def searcher(self, mock_neo4j):
        return DatasetSearcher(mock_neo4j)

    def test_calculate_readiness_green(self, searcher):
        """Test readiness calculation for green status."""
        dataset = {
            "has_bids": True,
            "qc_status": "passed",
            "sample_size": 50,
            "tr": 2.0
        }

        readiness = searcher._calculate_readiness(dataset)

        assert readiness["color"] == "green"
        assert readiness["score"] >= 0.8
        assert "BIDS compliant" in readiness["reason"]

    def test_calculate_readiness_yellow(self, searcher):
        """Test readiness calculation for yellow status."""
        dataset = {
            "has_bids": True,
            "qc_status": None,
            "sample_size": 15,
            "tr": 2.0
        }

        readiness = searcher._calculate_readiness(dataset)

        assert readiness["color"] == "yellow"
        assert 0.5 <= readiness["score"] < 0.8
        assert "Small sample" in readiness["reason"]

    def test_calculate_readiness_red(self, searcher):
        """Test readiness calculation for red status."""
        dataset = {
            "has_bids": False,
            "qc_status": "failed",
            "sample_size": 5,
            "tr": None
        }

        readiness = searcher._calculate_readiness(dataset)

        assert readiness["color"] == "red"
        assert readiness["score"] < 0.5
        assert "Not BIDS" in readiness["reason"]
        assert "QC failed" in readiness["reason"]

    def test_search_datasets_with_filters(self, searcher, mock_neo4j):
        """Test searching datasets with filters."""
        mock_neo4j.run.return_value = [
            {
                "id": "ds001",
                "name": "Motor Task Study",
                "description": "fMRI motor task",
                "modality": "fmri",
                "task": "motor",
                "sample_size": 30,
                "has_bids": True,
                "qc_status": "passed",
                "tr": 2.0,
                "matched_fields": ["modality", "task"]
            }
        ]

        filters = [
            Filter(facet="modality", value="fmri"),
            Filter(facet="task", value="motor")
        ]

        result = searcher.search(filters, sort_by="relevance", limit=10, offset=0)

        assert len(result) == 1
        assert result[0]["id"] == "ds001"
        assert result[0]["readiness"]["color"] == "green"
        assert "modality" in result[0]["why_matched"]

    def test_search_datasets_sort_by_readiness(self, searcher, mock_neo4j):
        """Test searching datasets sorted by readiness."""
        mock_neo4j.run.return_value = [
            {
                "id": "ds001",
                "name": "Dataset 1",
                "has_bids": False,
                "qc_status": None,
                "sample_size": 10,
                "tr": None,
                "matched_fields": []
            },
            {
                "id": "ds002",
                "name": "Dataset 2",
                "has_bids": True,
                "qc_status": "passed",
                "sample_size": 50,
                "tr": 2.0,
                "matched_fields": []
            }
        ]

        result = searcher.search([], sort_by="readiness", limit=10, offset=0)

        # Should be sorted by readiness score (ds002 first)
        assert result[0]["id"] == "ds002"
        assert result[1]["id"] == "ds001"


class TestFinderAPIIntegration:
    """Integration tests for Finder API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from brain_researcher.services.br_kg.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @patch('brain_researcher.services.br_kg.finder_api.Neo4jConnection')
    def test_suggest_filters_endpoint(self, mock_neo4j_class, client):
        """Test /kg/suggestFilters endpoint."""
        response = client.post('/kg/suggestFilters',
                              json={"text": "fMRI motor task"})

        assert response.status_code == 200
        data = response.get_json()
        assert "filters" in data
        assert isinstance(data["filters"], list)

    @patch('brain_researcher.services.br_kg.finder_api.Neo4jConnection')
    def test_facets_endpoint(self, mock_neo4j_class, client):
        """Test /kg/facets endpoint."""
        mock_instance = Mock()
        mock_neo4j_class.return_value = mock_instance
        mock_instance.run.return_value = [
            {"facet": "modality", "value": "fmri", "count": 100}
        ]

        response = client.post('/kg/facets',
                              json={"filters": []})

        assert response.status_code == 200
        data = response.get_json()
        assert "facets" in data

    @patch('brain_researcher.services.br_kg.finder_api.Neo4jConnection')
    def test_search_datasets_endpoint(self, mock_neo4j_class, client):
        """Test /kg/searchDatasets endpoint."""
        mock_instance = Mock()
        mock_neo4j_class.return_value = mock_instance
        mock_instance.run.return_value = [{
            "id": "ds001",
            "name": "Test Dataset",
            "has_bids": True,
            "qc_status": "passed",
            "sample_size": 30,
            "tr": 2.0,
            "matched_fields": []
        }]

        response = client.post('/kg/searchDatasets',
                              json={
                                  "filters": [],
                                  "sort": "relevance",
                                  "limit": 10,
                                  "offset": 0
                              })

        assert response.status_code == 200
        data = response.get_json()
        assert "datasets" in data
        assert len(data["datasets"]) == 1

    @patch('brain_researcher.services.br_kg.finder_api.Neo4jConnection')
    def test_explain_dataset_endpoint(self, mock_neo4j_class, client):
        """Test /kg/explain/:id endpoint."""
        mock_instance = Mock()
        mock_neo4j_class.return_value = mock_instance
        mock_instance.run.return_value = [{
            "dataset": {
                "id": "ds001",
                "name": "Test Dataset",
                "has_bids": True,
                "qc_status": "passed",
                "sample_size": 30,
                "tr": 2.0,
                "created": datetime.now()
            },
            "papers": [],
            "methods": [],
            "derivatives": []
        }]

        response = client.get('/kg/explain/ds001')

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "ds001"
        assert "readiness" in data
        assert "evidence" in data
        assert "graph" in data

    @patch('brain_researcher.services.br_kg.finder_api.Neo4jConnection')
    def test_explain_dataset_not_found(self, mock_neo4j_class, client):
        """Test /kg/explain/:id endpoint with non-existent dataset."""
        mock_instance = Mock()
        mock_neo4j_class.return_value = mock_instance
        mock_instance.run.return_value = []

        response = client.get('/kg/explain/ds999')

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
