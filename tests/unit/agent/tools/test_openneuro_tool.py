"""Unit tests for OpenNeuro dataset query tools."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from brain_researcher.services.tools.openneuro_tool import (
    OpenNeuroSearchTool,
    OpenNeuroGetDatasetTool,
    OpenNeuroGetSummaryTool,
    OpenNeuroTools,
    _load_openneuro_catalog,
    _normalize_dataset_id,
    _path_available,
)


# Sample catalog data for testing
SAMPLE_CATALOG = [
    {
        "dataset_id": "ds:openneuro:ds000001",
        "name": "Balloon Analog Risk-taking Task",
        "modalities": ["MRI", "fMRI"],
        "acquisitions": ["BOLD", "T1w"],
        "subjects_count": 16,
        "tasks": ["balloon analog risk task"],
        "path_dataset": "/data/openneuro/ds000001",
        "path_fmriprep": "/data/derivatives/fmriprep/ds000001",
        "path_mriqc": "/data/derivatives/mriqc/ds000001",
        "path_glmfitlins": None,
        "authors": ["Tom Schonberg"],
        "license": "CC0",
        "primary_url": "https://openneuro.org/datasets/ds000001",
        "source_repo_id": "ds000001",
    },
    {
        "dataset_id": "ds:openneuro:ds000002",
        "name": "Classification learning",
        "modalities": ["MRI", "fMRI"],
        "acquisitions": ["BOLD", "T1w"],
        "subjects_count": 17,
        "tasks": ["deterministic classification", "probabilistic classification"],
        "path_dataset": "/data/openneuro/ds000002",
        "path_fmriprep": "/data/derivatives/fmriprep/ds000002",
        "path_mriqc": None,
        "path_glmfitlins": "/data/derivatives/glm/ds000002",
        "authors": ["Poldrack"],
        "license": "PDDL",
        "primary_url": "https://openneuro.org/datasets/ds000002",
        "source_repo_id": "ds000002",
    },
    {
        "dataset_id": "ds:openneuro:ds000030",
        "name": "UCLA Consortium for Neuropsychiatric Phenomics",
        "modalities": ["MRI", "fMRI", "DWI"],
        "acquisitions": ["BOLD", "T1w", "DWI"],
        "subjects_count": 272,
        "tasks": ["bart", "rest", "stopsignal"],
        "path_dataset": "/data/openneuro/ds000030",
        "path_fmriprep": None,
        "path_mriqc": "/data/derivatives/mriqc/ds000030",
        "path_glmfitlins": None,
        "authors": ["Bilder", "Poldrack"],
        "license": "CC0",
        "primary_url": "https://openneuro.org/datasets/ds000030",
        "source_repo_id": "ds000030",
    },
]


class TestNormalizeDatasetId:
    """Test dataset ID normalization."""

    def test_full_id(self):
        assert _normalize_dataset_id("ds:openneuro:ds000001") == "ds000001"

    def test_short_id(self):
        assert _normalize_dataset_id("ds000001") == "ds000001"

    def test_uppercase(self):
        assert _normalize_dataset_id("DS000001") == "ds000001"


class TestOpenNeuroSearchTool:
    """Test OpenNeuro search functionality."""

    @pytest.fixture
    def tool(self):
        return OpenNeuroSearchTool()

    @pytest.fixture
    def mock_catalog(self):
        with patch(
            "brain_researcher.services.tools.openneuro_tool._load_openneuro_catalog"
        ) as mock:
            mock.return_value = SAMPLE_CATALOG
            yield mock

    @pytest.fixture(autouse=True)
    def patch_path_available(self):
        # Treat any non-empty path string as available to avoid filesystem coupling in unit tests
        with patch("brain_researcher.services.tools.openneuro_tool._path_available", side_effect=lambda p: bool(p)):
            yield

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "openneuro.search"
        assert "openneuro" in tool.TAGS
        assert "1594" in tool.get_tool_description().lower() or "search" in tool.get_tool_description().lower()

    def test_search_no_filters(self, tool, mock_catalog):
        result = tool._run()
        assert result.status == "success"
        assert result.data["total"] == 3
        assert len(result.data["items"]) == 3

    def test_search_by_query(self, tool, mock_catalog):
        result = tool._run(query="balloon")
        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.data["items"][0]["dataset_id"] == "ds:openneuro:ds000001"

    def test_search_by_modality(self, tool, mock_catalog):
        result = tool._run(modality="DWI")
        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.data["items"][0]["dataset_id"] == "ds:openneuro:ds000030"

    def test_search_by_task(self, tool, mock_catalog):
        result = tool._run(task="classification")
        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.data["items"][0]["dataset_id"] == "ds:openneuro:ds000002"

    def test_search_min_subjects(self, tool, mock_catalog):
        result = tool._run(min_subjects=100)
        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.data["items"][0]["subjects_count"] == 272

    def test_search_has_fmriprep(self, tool, mock_catalog):
        result = tool._run(has_fmriprep=True)
        assert result.status == "success"
        assert result.data["total"] == 2
        for item in result.data["items"]:
            assert item["has_fmriprep"] is True

    def test_search_has_glmfitlins(self, tool, mock_catalog):
        result = tool._run(has_glmfitlins=True)
        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.data["items"][0]["dataset_id"] == "ds:openneuro:ds000002"

    def test_search_limit(self, tool, mock_catalog):
        result = tool._run(limit=1)
        assert result.status == "success"
        assert len(result.data["items"]) == 1
        assert result.data["total"] == 3
        assert result.data["returned"] == 1

    def test_search_empty_catalog(self, tool):
        with patch(
            "brain_researcher.services.tools.openneuro_tool._load_openneuro_catalog"
        ) as mock:
            mock.return_value = []
            result = tool._run()
            assert result.status == "error"
            assert "not available" in result.error.lower()


class TestOpenNeuroGetDatasetTool:
    """Test OpenNeuro get dataset functionality."""

    @pytest.fixture
    def tool(self):
        return OpenNeuroGetDatasetTool()

    @pytest.fixture
    def mock_catalog(self):
        with patch(
            "brain_researcher.services.tools.openneuro_tool._load_openneuro_catalog"
        ) as mock:
            mock.return_value = SAMPLE_CATALOG
            yield mock

    @pytest.fixture(autouse=True)
    def patch_path_available(self):
        with patch("brain_researcher.services.tools.openneuro_tool._path_available", side_effect=lambda p: bool(p)):
            yield

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "openneuro.get_dataset"
        assert "openneuro" in tool.TAGS

    def test_get_dataset_by_full_id(self, tool, mock_catalog):
        result = tool._run(dataset_id="ds:openneuro:ds000001")
        assert result.status == "success"
        assert result.data["name"] == "Balloon Analog Risk-taking Task"

    def test_get_dataset_by_short_id(self, tool, mock_catalog):
        result = tool._run(dataset_id="ds000001")
        assert result.status == "success"
        assert result.data["name"] == "Balloon Analog Risk-taking Task"

    def test_get_dataset_not_found(self, tool, mock_catalog):
        result = tool._run(dataset_id="ds999999")
        assert result.status == "error"
        assert "not found" in result.error.lower()


class TestOpenNeuroGetSummaryTool:
    """Test OpenNeuro get summary functionality."""

    @pytest.fixture
    def tool(self):
        return OpenNeuroGetSummaryTool()

    @pytest.fixture
    def mock_catalog(self):
        with patch(
            "brain_researcher.services.tools.openneuro_tool._load_openneuro_catalog"
        ) as mock:
            mock.return_value = SAMPLE_CATALOG
            yield mock

    @pytest.fixture(autouse=True)
    def patch_path_available(self):
        with patch("brain_researcher.services.tools.openneuro_tool._path_available", side_effect=lambda p: bool(p)):
            yield

    def test_tool_metadata(self, tool):
        assert tool.get_tool_name() == "openneuro.get_dataset_summary"

    def test_get_summary(self, tool, mock_catalog):
        result = tool._run(dataset_id="ds000001")
        assert result.status == "success"
        # Should have compact fields
        assert "dataset_id" in result.data
        assert "name" in result.data
        assert "modalities" in result.data
        assert "subjects" in result.data
        assert "available_locally" in result.data
        assert "derivatives_available" in result.data

    def test_summary_derivatives_info(self, tool, mock_catalog):
        result = tool._run(dataset_id="ds000001")
        assert result.status == "success"
        derivs = result.data["derivatives_available"]
        assert derivs["fmriprep"] is True
        assert derivs["mriqc"] is True
        assert derivs["glmfitlins"] is False


class TestOpenNeuroToolsFactory:
    """Test the tools factory."""

    def test_get_all_tools(self):
        factory = OpenNeuroTools()
        tools = factory.get_all_tools()
        assert len(tools) == 3

        tool_names = [t.get_tool_name() for t in tools]
        assert "openneuro.search" in tool_names
        assert "openneuro.get_dataset" in tool_names
        assert "openneuro.get_dataset_summary" in tool_names
