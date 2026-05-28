"""Unit tests for Neurosynth tools."""

import os
import tempfile
from unittest.mock import Mock, patch

import numpy as np
import pytest

from brain_researcher.services.tools.neurosynth_tools import (
    NeuroSynthMetaAnalysisArgs,
    NeuroSynthMetaAnalysisTool,
    NeuroSynthTermSearchArgs,
    NeuroSynthTermSearchTool,
    NeuroSynthTools,
    NeuroSynthVisualizationArgs,
    NeuroSynthVisualizationTool,
    _get_dataset_path,
)


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_activation_map():
    """Create a mock NIfTI activation map."""
    mock_img = Mock()
    mock_img.shape = (91, 109, 91)  # Standard MNI dimensions
    mock_img.get_fdata.return_value = np.random.randn(91, 109, 91)
    return mock_img


class TestDatasetPath:
    def test_get_dataset_path_from_env(self, monkeypatch):
        """Test getting dataset path from environment variable."""
        test_path = "/custom/path/dataset.pkl"
        monkeypatch.setenv("NEUROSYNTH_DATASET_PATH", test_path)

        # Mock os.path.exists to return True
        with patch("os.path.exists", return_value=True):
            assert _get_dataset_path() == test_path

    def test_get_dataset_path_default(self, monkeypatch):
        """Test default dataset path when env var not set."""
        monkeypatch.delenv("NEUROSYNTH_DATASET_PATH", raising=False)
        path = _get_dataset_path()
        assert "data/neurosynth_nimare/neurosynth_dataset_v7.pkl" in path


class TestNeuroSynthMetaAnalysisTool:
    def test_properties(self):
        tool = NeuroSynthMetaAnalysisTool()
        assert tool.get_tool_name() == "neurosynth_meta_analysis"
        assert "meta-analysis" in tool.get_tool_description().lower()
        assert "14,000" in tool.get_tool_description()  # ~14k studies
        assert tool.get_args_schema() == NeuroSynthMetaAnalysisArgs

    @patch("brain_researcher.core.analysis.neurosynth_integration.get_neurosynth_mapping")
    @patch("nibabel.save")
    def test_success_with_activation_maps(
        self, mock_save, mock_get, temp_output_dir, mock_activation_map
    ):
        """Test successful meta-analysis with activation map saving."""
        mock_get.return_value = {
            "keyword": "fear",
            "activation_maps": [mock_activation_map],
            "studies": ["study1", "study2"],
            "coordinates": [[10, 20, 30], [40, 50, 60]],
            "scores": [0.8, 0.7],
        }

        tool = NeuroSynthMetaAnalysisTool()
        tool.output_dir = temp_output_dir

        result = tool.run(keyword="fear")

        assert result["status"] == "success"
        assert result["data"]["keyword"] == "fear"
        assert "activation_map_paths" in result["data"]
        assert len(result["data"]["activation_map_paths"]) == 1
        assert result["metadata"]["n_studies"] == 2
        assert result["metadata"]["n_coordinates"] == 2

        # Verify nibabel.save was called
        mock_save.assert_called_once()
        save_path = mock_save.call_args[0][1]
        assert "neurosynth_fear" in save_path
        assert save_path.endswith(".nii.gz")

    @patch("brain_researcher.core.analysis.neurosynth_integration.get_neurosynth_mapping")
    def test_error_from_integration(self, mock_get):
        """Test handling errors from the integration module."""
        mock_get.return_value = {
            "keyword": "unknown",
            "error": "Label 'unknown' not found in dataset.",
            "activation_maps": [],
            "studies": [],
            "coordinates": [],
            "scores": [],
        }

        tool = NeuroSynthMetaAnalysisTool()
        result = tool.run(keyword="unknown")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @patch(
        "brain_researcher.core.analysis.neurosynth_integration.get_neurosynth_mapping",
        side_effect=RuntimeError("Dataset missing"),
    )
    def test_exception_handling(self, mock_get):
        """Test handling exceptions during meta-analysis."""
        tool = NeuroSynthMetaAnalysisTool()
        result = tool.run(keyword="fear")

        assert result["status"] == "error"
        assert "Dataset missing" in result["error"]


class TestNeuroSynthVisualizationTool:
    def test_properties(self):
        tool = NeuroSynthVisualizationTool()
        assert tool.get_tool_name() == "neurosynth_visualize"
        assert "publication-ready" in tool.get_tool_description()
        assert tool.get_args_schema() == NeuroSynthVisualizationArgs

    @patch("brain_researcher.core.analysis.neurosynth_integration.visualize_activation_maps")
    @patch("nibabel.load")
    def test_success_with_saving(
        self, mock_load, mock_vis, temp_output_dir, mock_activation_map
    ):
        """Test successful visualization with file saving."""
        # Create a temp activation map file
        map_path = os.path.join(temp_output_dir, "test_map.nii.gz")
        with open(map_path, "w") as f:
            f.write("dummy")

        mock_load.return_value = mock_activation_map
        mock_vis.return_value = {
            "slices_0": "base64_slice_data",
            "glass_0": "base64_glass_data",
            "3d_0": "base64_3d_data",
        }

        tool = NeuroSynthVisualizationTool()
        tool.output_dir = temp_output_dir

        result = tool.run(
            activation_map_paths=[map_path], threshold=2.5, output_dir=temp_output_dir
        )

        assert result["status"] == "success"
        assert "visualizations" in result["data"]
        assert "saved_files" in result["data"]
        assert result["data"]["threshold"] == 2.5
        assert result["metadata"]["n_maps"] == 1

        mock_vis.assert_called_once()
        call_args = mock_vis.call_args[0]
        assert len(call_args[0]) == 1  # One activation map
        assert mock_vis.call_args.kwargs["threshold"] == 2.5

    def test_missing_file_error(self):
        """Test error when activation map file doesn't exist."""
        tool = NeuroSynthVisualizationTool()
        result = tool.run(activation_map_paths=["/nonexistent/file.nii.gz"])

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @patch(
        "brain_researcher.core.analysis.neurosynth_integration.visualize_activation_maps",
        side_effect=Exception("Viz error"),
    )
    @patch("nibabel.load")
    @patch("os.path.exists", return_value=True)
    def test_visualization_error(self, mock_exists, mock_load, mock_vis):
        """Test handling visualization errors."""
        tool = NeuroSynthVisualizationTool()
        result = tool.run(activation_map_paths=["dummy.nii.gz"])

        assert result["status"] == "error"
        assert "Viz error" in result["error"]


class TestNeuroSynthTermSearchTool:
    def test_properties(self):
        tool = NeuroSynthTermSearchTool()
        assert tool.get_tool_name() == "neurosynth_search_terms"
        assert "fuzzy matching" in tool.get_tool_description()
        assert tool.get_args_schema() == NeuroSynthTermSearchArgs

    @patch("brain_researcher.services.tools.neurosynth_tools._load_dataset")
    def test_fuzzy_search_with_rapidfuzz(self, mock_load):
        """Test fuzzy search using rapidfuzz."""
        mock_ds = Mock()
        mock_ds.get_labels.return_value = [
            "terms_abstract__fear",
            "terms_abstract__memory",
            "terms_abstract__working memory",
            "terms_abstract__episodic memory",
        ]
        mock_load.return_value = mock_ds

        # Mock rapidfuzz
        with patch("rapidfuzz.process.extract") as mock_extract:
            mock_extract.return_value = [
                ("memory", 100.0, 1),
                ("working memory", 85.0, 2),
                ("episodic memory", 85.0, 3),
            ]

            tool = NeuroSynthTermSearchTool()
            result = tool.run(search_query="mem", fuzzy_match=True, limit=5)

            assert result["status"] == "success"
            assert result["data"]["n_matches"] == 3
            assert result["data"]["matches"][0]["term"] == "memory"
            assert result["data"]["matches"][0]["score"] == 100.0
            assert (
                "terms_abstract__memory" in result["data"]["matches"][0]["full_label"]
            )

    @patch("brain_researcher.services.tools.neurosynth_tools._load_dataset")
    def test_fuzzy_search_fallback(self, mock_load):
        """Test fallback to substring matching when rapidfuzz not available."""
        mock_ds = Mock()
        mock_ds.get_labels.return_value = [
            "terms_abstract__fear",
            "terms_abstract__memory",
            "terms_abstract__working memory",
        ]
        mock_load.return_value = mock_ds

        # Mock ImportError for rapidfuzz
        with patch("rapidfuzz.process.extract", side_effect=ImportError):
            tool = NeuroSynthTermSearchTool()
            result = tool.run(search_query="mem", fuzzy_match=True)

            assert result["status"] == "success"
            assert result["data"]["n_matches"] == 2
            terms = [m["term"] for m in result["data"]["matches"]]
            assert "memory" in terms
            assert "working memory" in terms

    @patch("brain_researcher.services.tools.neurosynth_tools._load_dataset")
    def test_exact_search(self, mock_load):
        """Test exact term matching."""
        mock_ds = Mock()
        mock_ds.get_labels.return_value = [
            "terms_abstract__fear",
            "terms_abstract__memory",
            "terms_abstract__Memory",  # Different case
        ]
        mock_load.return_value = mock_ds

        tool = NeuroSynthTermSearchTool()
        result = tool.run(search_query="memory", fuzzy_match=False)

        assert result["status"] == "success"
        assert result["data"]["n_matches"] == 2  # Case-insensitive
        assert all(m["score"] == 100.0 for m in result["data"]["matches"])

    @patch(
        "brain_researcher.services.tools.neurosynth_tools._load_dataset",
        side_effect=FileNotFoundError("Dataset missing"),
    )
    def test_dataset_loading_error(self, mock_load):
        """Test error when dataset can't be loaded."""
        tool = NeuroSynthTermSearchTool()
        result = tool.run(search_query="fear")

        assert result["status"] == "error"
        assert "Dataset missing" in result["error"]


class TestNeuroSynthTools:
    def test_collection(self):
        """Test the tools collection."""
        tools = NeuroSynthTools()
        all_tools = tools.get_all_tools()

        assert len(all_tools) == 3

        names = {t.get_tool_name() for t in all_tools}
        assert names == {
            "neurosynth_meta_analysis",
            "neurosynth_visualize",
            "neurosynth_search_terms",
        }

        # Test get_tool_by_name
        assert isinstance(
            tools.get_tool_by_name("neurosynth_meta_analysis"),
            NeuroSynthMetaAnalysisTool,
        )
        assert isinstance(
            tools.get_tool_by_name("neurosynth_visualize"), NeuroSynthVisualizationTool
        )
        assert isinstance(
            tools.get_tool_by_name("neurosynth_search_terms"), NeuroSynthTermSearchTool
        )
        assert tools.get_tool_by_name("nonexistent") is None

    def test_all_tools_have_output_dir(self):
        """Test that all tools have output_dir configuration."""
        tools = NeuroSynthTools()
        for tool in tools.get_all_tools():
            assert hasattr(tool, "output_dir")
            assert tool.output_dir is not None
