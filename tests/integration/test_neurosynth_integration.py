"""Integration tests for Neurosynth tools with real data."""

import os
from pathlib import Path

import pandas as pd
import pytest

# Check if nimare is available
try:
    import nimare
    from nimare import dataset as nimare_dataset

    HAS_NIMARE = True
except ImportError:
    HAS_NIMARE = False

from brain_researcher.services.tools.neurosynth_tools import (
    NeuroSynthMetaAnalysisTool,
    NeuroSynthTermSearchTool,
    NeuroSynthVisualizationTool,
)


def create_mini_dataset(output_path: Path):
    """Create a minimal Neurosynth-like dataset for testing."""
    if not HAS_NIMARE:
        pytest.skip("nimare not installed")

    # Create minimal coordinates DataFrame
    coords_data = {
        "id": ["study1", "study1", "study2", "study2", "study3"],
        "x": [-50.0, -48.0, 52.0, 50.0, -20.0],
        "y": [20.0, 22.0, -30.0, -28.0, 10.0],
        "z": [10.0, 12.0, 40.0, 42.0, 60.0],
        "space": ["MNI"] * 5,
    }
    coordinates = pd.DataFrame(coords_data)

    # Create minimal annotations DataFrame
    annotations_data = {
        "id": ["study1", "study2", "study3"],
        "terms_abstract__fear": [1.5, 0.2, 0.8],
        "terms_abstract__memory": [0.3, 2.1, 1.2],
        "terms_abstract__attention": [0.5, 0.7, 1.8],
    }
    annotations = pd.DataFrame(annotations_data)

    # Create metadata
    metadata = pd.DataFrame(
        {
            "id": ["study1", "study2", "study3"],
            "title": ["Fear Study", "Memory Study", "Attention Study"],
            "authors": ["Smith et al.", "Jones et al.", "Brown et al."],
            "year": [2020, 2021, 2022],
        }
    )

    # Create a minimal NiMARE dataset
    dataset = nimare_dataset.Dataset(
        coordinates=coordinates, annotations=annotations, metadata=metadata
    )

    # Save the dataset
    dataset.save(str(output_path))
    return dataset


@pytest.fixture(scope="session")
def mini_dataset_path(tmp_path_factory):
    """Create a mini dataset for testing."""
    if not HAS_NIMARE:
        pytest.skip("nimare not installed")

    tmp_dir = tmp_path_factory.mktemp("neurosynth_test")
    dataset_path = tmp_dir / "mini_neurosynth.pkl"

    create_mini_dataset(dataset_path)
    return str(dataset_path)


@pytest.mark.slow
@pytest.mark.skipif(not HAS_NIMARE, reason="nimare not installed")
class TestNeuroSynthIntegration:
    """Integration tests using a mini dataset."""

    def test_meta_analysis_to_visualization_pipeline(
        self, mini_dataset_path, monkeypatch, tmp_path
    ):
        """Test the full pipeline from meta-analysis to visualization."""
        # Set the dataset path
        monkeypatch.setenv("NEUROSYNTH_DATASET_PATH", mini_dataset_path)

        # Create output directory
        output_dir = tmp_path / "neurosynth_output"
        output_dir.mkdir()

        # Step 1: Search for terms
        search_tool = NeuroSynthTermSearchTool()
        search_result = search_tool.run(search_query="fear")

        assert search_result["status"] == "success"
        assert search_result["data"]["n_matches"] > 0

        # Step 2: Run meta-analysis
        meta_tool = NeuroSynthMetaAnalysisTool()
        meta_tool.output_dir = str(output_dir)

        meta_result = meta_tool.run(keyword="terms_abstract__fear")

        assert meta_result["status"] == "success"
        assert "activation_map_paths" in meta_result["data"]
        assert len(meta_result["data"]["activation_map_paths"]) > 0

        # Verify activation map was saved
        map_path = meta_result["data"]["activation_map_paths"][0]
        assert os.path.exists(map_path)
        assert map_path.endswith(".nii.gz")

        # Step 3: Visualize the activation map
        viz_tool = NeuroSynthVisualizationTool()
        viz_tool.output_dir = str(output_dir)

        viz_result = viz_tool.run(
            activation_map_paths=meta_result["data"]["activation_map_paths"],
            threshold=0.5,  # Lower threshold for mini dataset
        )

        assert viz_result["status"] == "success"
        assert "visualizations" in viz_result["data"]
        assert "saved_files" in viz_result["data"]

        # Check that visualization files were created
        for key, filepath in viz_result["data"]["saved_files"].items():
            assert os.path.exists(filepath)
            assert filepath.endswith(".png")

    def test_all_terms_searchable(self, mini_dataset_path, monkeypatch):
        """Test that all terms in the dataset are searchable."""
        monkeypatch.setenv("NEUROSYNTH_DATASET_PATH", mini_dataset_path)

        search_tool = NeuroSynthTermSearchTool()

        # Search for each term
        for term in ["fear", "memory", "attention"]:
            result = search_tool.run(search_query=term, fuzzy_match=False)
            assert result["status"] == "success"
            assert result["data"]["n_matches"] >= 1

            # Check exact match exists
            matches = result["data"]["matches"]
            terms_found = [m["term"] for m in matches]
            assert term in terms_found

    def test_coordinates_and_studies_returned(
        self, mini_dataset_path, monkeypatch, tmp_path
    ):
        """Test that coordinates and studies are properly returned."""
        monkeypatch.setenv("NEUROSYNTH_DATASET_PATH", mini_dataset_path)

        meta_tool = NeuroSynthMetaAnalysisTool()
        meta_tool.output_dir = str(tmp_path)

        result = meta_tool.run(keyword="terms_abstract__memory")

        assert result["status"] == "success"
        assert "studies" in result["data"]
        assert "coordinates" in result["data"]

        # Should have studies with memory keyword
        assert len(result["data"]["studies"]) > 0
        assert len(result["data"]["coordinates"]) > 0

    def test_invalid_keyword_handling(self, mini_dataset_path, monkeypatch, tmp_path):
        """Test handling of invalid keywords."""
        monkeypatch.setenv("NEUROSYNTH_DATASET_PATH", mini_dataset_path)

        meta_tool = NeuroSynthMetaAnalysisTool()
        meta_tool.output_dir = str(tmp_path)

        result = meta_tool.run(keyword="nonexistent_term")

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()


@pytest.mark.slow
@pytest.mark.skipif(not HAS_NIMARE, reason="nimare not installed")
def test_real_dataset_if_available():
    """Test with real dataset if available (optional)."""
    real_dataset_path = "/data/ECoG-foundation-model/mnndl_temp/brain_researcher/data/neurosynth_nimare/neurosynth_dataset_v7.pkl"

    if not os.path.exists(real_dataset_path):
        pytest.skip("Real Neurosynth dataset not available")

    # Quick smoke test with real data
    search_tool = NeuroSynthTermSearchTool()
    result = search_tool.run(search_query="emotion", limit=5)

    assert result["status"] == "success"
    assert result["data"]["n_matches"] > 0
    assert result["data"]["total_terms"] > 1000  # Real dataset has many terms
