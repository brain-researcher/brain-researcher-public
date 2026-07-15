"""
Unit tests for fMRI tool wrappers.
"""

import json
from unittest.mock import Mock, patch

import nibabel as nib
import numpy as np
import pytest

from brain_researcher.services.tools.fmri_tools import (
    BrainSimilarityArgs,
    BrainSimilarityTool,
    ContrastAnalysisArgs,
    ContrastAnalysisTool,
    EncodingModelArgs,
    EncodingModelTool,
    FMRITools,
    GLMAnalysisArgs,
    GLMAnalysisTool,
)
from brain_researcher.services.tools.tool_base import ToolResult


class TestGLMAnalysisTool:
    """Test GLM analysis tool wrapper."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = GLMAnalysisTool()
        assert tool.get_tool_name() == "glm_analysis"
        assert "GLM" in tool.get_tool_description()
        assert tool.get_args_schema() == GLMAnalysisArgs

    def test_successful_analysis(self):
        """Test successful GLM analysis execution."""
        tool = GLMAnalysisTool()

        # Mock the _run method to return expected result
        with patch.object(tool, "_run") as mock_run:
            mock_run.return_value = ToolResult(
                status="success",
                data={
                    "dataset_id": "ds000001",
                    "n_contrasts": 2,
                    "contrasts": {
                        "motor_vs_rest": {
                            "z_map": "/data/results/motor_zmap.nii.gz",
                            "threshold": 3.5,
                        },
                        "visual_vs_rest": {
                            "z_map": "/data/results/visual_zmap.nii.gz",
                            "threshold": 3.5,
                        },
                    },
                    "peak_coordinates": [[-42, -22, 54], [42, -22, 54]],
                },
                metadata={"threshold": 3.5},
            )

            # Run tool
            result = tool.run(
                dataset_id="ds000001",
                contrasts={"motor_vs_rest": [1, -1], "visual_vs_rest": [0, 1, -1]},
                threshold=3.5,
            )

            # Assertions
            assert result["status"] == "success"
            assert result["data"]["dataset_id"] == "ds000001"
            assert result["data"]["n_contrasts"] == 2
            assert "motor_vs_rest" in result["data"]["contrasts"]
            assert len(result["data"]["peak_coordinates"]) > 0
            assert result["metadata"]["threshold"] == 3.5

            # Verify _run was called correctly
            mock_run.assert_called_once_with(
                dataset_id="ds000001",
                contrasts={"motor_vs_rest": [1, -1], "visual_vs_rest": [0, 1, -1]},
                threshold=3.5,
            )

    def test_analysis_with_output_dir(self):
        """Test GLM analysis with custom output directory."""
        tool = GLMAnalysisTool()

        with patch.object(tool, "_run") as mock_run:
            mock_run.return_value = ToolResult(
                status="success",
                data={
                    "dataset_id": "ds000001",
                    "n_contrasts": 1,
                    "contrasts": {
                        "contrast1": {
                            "z_map": "/path/to/result.nii.gz",
                            "threshold": 3.1,
                        }
                    },
                    "peak_coordinates": [[-42, -22, 54]],
                },
            )

            result = tool.run(
                dataset_id="ds000001",
                contrasts={"contrast1": [1, -1]},
                output_dir="/custom/output",
            )

            assert result["status"] == "success"
            mock_run.assert_called_with(
                dataset_id="ds000001",
                contrasts={"contrast1": [1, -1]},
                output_dir="/custom/output",
            )

    def test_analysis_error_handling(self):
        """Test error handling in GLM analysis."""
        tool = GLMAnalysisTool()

        with patch.object(tool, "_run") as mock_run:
            mock_run.side_effect = Exception("API connection failed")

            result = tool.run(dataset_id="ds000001", contrasts={})

        assert result["status"] == "error"
        assert "API connection failed" in result["error"]

    def test_args_schema_validation(self):
        """Test argument schema validation."""
        # Valid args
        args = GLMAnalysisArgs(
            dataset_id="ds000001", contrasts={"motor": [1, -1]}, threshold=2.5
        )
        assert args.dataset_id == "ds000001"
        assert args.threshold == 2.5

        # Test with minimal args
        minimal_args = GLMAnalysisArgs(dataset_id="ds000002", contrasts={})
        assert minimal_args.threshold == 3.1  # Default value

    def test_task_suffix_none_does_not_leak_into_paths(self, tmp_path):
        data_root = tmp_path / "data"
        glm_repo = tmp_path / "glmrepo"
        tmp_root = tmp_path / "scratch"
        data_root.mkdir()
        glm_repo.mkdir()
        tmp_root.mkdir()

        path_config = tmp_path / "path_config.json"
        path_config.write_text(
            json.dumps(
                {
                    "datasets_folder": str(data_root),
                    "openneuro_glmrepo": str(glm_repo),
                    "tmp_folder": str(tmp_root),
                }
            ),
            encoding="utf-8",
        )

        tool = GLMAnalysisTool()
        result = tool._run(
            dataset_id="ds000001",
            contrasts={"test": [1]},
            task="motor",
            task_suffix=None,
            execute=False,
            parse_only=False,
            path_config=str(path_config),
        )

        plan = result.data.get("plan", {})
        assert "None" not in plan.get("scratch_dir", "")
        assert "None" not in plan.get("output_dir", "")
        assert plan.get("scratch_dir", "").endswith("task-motor")


class TestEncodingModelTool:
    """Test encoding model tool wrapper."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = EncodingModelTool()
        assert tool.get_tool_name() == "encoding_model"
        assert "encoding models" in tool.get_tool_description()
        assert tool.get_args_schema() == EncodingModelArgs

    @patch("brain_researcher.core.analysis.encoding_model.EncodingModel")
    def test_successful_encoding_model(self, mock_model_class):
        """Test successful encoding model execution."""
        # Setup mock
        mock_model = Mock()
        mock_model_class.return_value = mock_model

        tool = EncodingModelTool()
        result = tool.run(
            dataset_id="ds000001",
            parcellation="schaefer_400",
            features=["feature1", "feature2"],
        )

        assert result["status"] == "success"
        assert result["data"]["r2_scores"]["mean"] == 0.65
        assert result["data"]["n_parcels"] == 400
        assert result["data"]["n_features"] == 2
        assert result["metadata"]["parcellation"] == "schaefer_400"

    def test_encoding_model_caching(self):
        """Test that encoding model results are cached."""
        tool = EncodingModelTool()

        with patch("brain_researcher.core.analysis.encoding_model.EncodingModel"):
            # First call
            result1 = tool.run(dataset_id="ds000001", parcellation="glasser_360")
            assert result1["status"] == "success"
            assert not result1["metadata"].get("from_cache", False)

            # Second call with same args should hit cache
            result2 = tool.run(dataset_id="ds000001", parcellation="glasser_360")
            assert result2["status"] == "success"
            assert result2["metadata"]["from_cache"] is True

            # Different args should not hit cache
            result3 = tool.run(dataset_id="ds000002", parcellation="glasser_360")
            assert not result3["metadata"].get("from_cache", False)

    @patch("brain_researcher.core.analysis.encoding_model.EncodingModel")
    def test_encoding_model_error(self, mock_model_class):
        """Test error handling in encoding model."""
        mock_model_class.side_effect = Exception("Model fitting failed")

        tool = EncodingModelTool()
        result = tool.run(dataset_id="ds000001")

        assert result["status"] == "error"
        assert "Model fitting failed" in result["error"]

    def test_cache_ttl_setting(self):
        """Test cache TTL is set correctly for encoding model."""
        tool = EncodingModelTool()
        assert tool.cache_ttl == 3600  # 1 hour


class TestContrastAnalysisTool:
    """Test contrast analysis tool wrapper."""

    @staticmethod
    def _write_z_map(tmp_path):
        data = np.zeros((8, 8, 8), dtype=float)
        data[2:4, 2:4, 2:4] = 5.0
        data[2, 2, 2] = 7.0
        z_map = tmp_path / "motor_zmap.nii.gz"
        nib.save(nib.Nifti1Image(data, np.eye(4)), z_map)
        return z_map

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = ContrastAnalysisTool()
        assert tool.get_tool_name() == "contrast_analysis"
        assert "descriptive suprathreshold" in tool.get_tool_description()
        assert (
            "does not perform inferential significance" in tool.get_tool_description()
        )
        assert tool.get_args_schema() == ContrastAnalysisArgs

    def test_successful_contrast_analysis_uses_explicit_map(self, tmp_path):
        """An existing z-map is analyzed instead of replaced with demo data."""
        z_map = self._write_z_map(tmp_path)
        tool = ContrastAnalysisTool()
        result = tool.run(
            z_map_path=str(z_map),
            contrast_name="motor_vs_rest",
            task_description="Finger tapping task",
        )

        assert result["status"] == "success"
        assert result["data"]["contrast_name"] == "motor_vs_rest"
        assert result["data"]["task_description"] == "Finger tapping task"
        assert result["data"]["n_clusters"] == 1
        assert result["data"]["z_map_used"] == str(z_map.resolve())
        assert result["metadata"]["mock_mode"] is False
        assert result["metadata"]["real_data_available"] is True
        assert (
            result["metadata"]["cluster_semantics"]
            == "descriptive_suprathreshold_components"
        )
        assert result["metadata"]["inferential_significance"] is False
        assert result["metadata"]["multiple_comparisons_correction"] is None
        assert result["metadata"]["anatomical_labeling"] is False
        assert result["metadata"]["cognitive_interpretation"] is False
        assert (
            result["data"]["suprathreshold_clusters"]
            == result["data"]["significant_clusters"]
        )
        assert "cognitive_interpretation" not in result["data"]

        cluster = result["data"]["significant_clusters"][0]
        assert cluster["peak_coordinate"] == [2, 2, 2]
        assert cluster["coordinate_space"] == "voxel"
        assert cluster["cluster_size"] == 8
        assert cluster["peak_z"] == 7.0
        assert "region" not in cluster

    def test_contrast_analysis_samples_real_coordinate_value(self, tmp_path):
        """Coordinate analysis reads the supplied map rather than fixed values."""
        z_map = self._write_z_map(tmp_path)
        tool = ContrastAnalysisTool()
        result = tool.run(
            z_map_path=str(z_map),
            contrast_name="visual_vs_baseline",
            coordinates=[[2.0, 2.0, 2.0], [20.0, 20.0, 20.0]],
        )

        assert result["status"] == "success"
        coordinate_results = result["data"]["coordinate_analysis"]
        assert coordinate_results[0] == {
            "coordinate": [2.0, 2.0, 2.0],
            "coordinate_space": "world",
            "voxel_index": [2, 2, 2],
            "in_bounds": True,
            "z_value": 7.0,
        }
        assert coordinate_results[1]["in_bounds"] is False
        assert coordinate_results[1]["z_value"] is None

    def test_missing_z_map_fails_closed_without_dataset_fallback(self, tmp_path):
        """A missing input cannot resolve to a private dataset or demo result."""
        missing = tmp_path / "ds000001" / "contrast-pumps_stat-z_statmap.nii.gz"
        tool = ContrastAnalysisTool()
        result = tool.run(z_map_path=str(missing), contrast_name="pumps")

        assert result["status"] == "error"
        assert result["data"] is None
        assert result["error"] == f"Z-map file not found: {missing}"
        assert result["metadata"]["error_category"] == "data"
        assert "significant_clusters" not in result

    def test_empty_z_map_path_fails_closed(self):
        tool = ContrastAnalysisTool()
        result = tool.run(z_map_path="", contrast_name="motor_vs_rest")

        assert result["status"] == "error"
        assert result["data"] is None
        assert "requires an explicit z-map path" in result["error"]

    def test_missing_analysis_dependency_fails_closed(self, tmp_path):
        z_map = self._write_z_map(tmp_path)
        tool = ContrastAnalysisTool()
        with patch(
            "brain_researcher.core.analysis.contrast_analysis.ContrastAnalyzer._get_significant_clusters",
            side_effect=ImportError("scipy unavailable"),
        ):
            result = tool.run(z_map_path=str(z_map), contrast_name="motor_vs_rest")

        assert result["status"] == "error"
        assert result["data"] is None
        assert result["metadata"]["error_category"] == "configuration"
        assert "scipy unavailable" in result["error"]


class TestBrainSimilarityTool:
    """Test brain similarity tool wrapper."""

    def test_tool_properties(self):
        """Test tool name and description."""
        tool = BrainSimilarityTool()
        assert tool.get_tool_name() == "brain_similarity"
        assert "similarity between brain activation" in tool.get_tool_description()
        assert tool.get_args_schema() == BrainSimilarityArgs

    def test_correlation_similarity(self):
        """Test correlation similarity computation."""
        tool = BrainSimilarityTool()
        result = tool.run(
            dataset1="ds000001", dataset2="ds000002", metric="correlation"
        )

        assert result["status"] == "success"
        assert result["data"]["similarity_score"] == 0.72
        assert result["data"]["metric"] == "correlation"
        assert "regional_similarities" in result["data"]
        assert "interpretation" in result["data"]
        assert "high similarity" in result["data"]["interpretation"]

    def test_cosine_similarity(self):
        """Test cosine similarity computation."""
        tool = BrainSimilarityTool()
        result = tool.run(dataset1="ds000001", dataset2="ds000002", metric="cosine")

        assert result["status"] == "success"
        assert result["data"]["similarity_score"] == 0.68
        assert result["data"]["metric"] == "cosine"
        assert "moderate similarity" in result["data"]["interpretation"]

    def test_euclidean_distance(self):
        """Test euclidean distance computation."""
        tool = BrainSimilarityTool()
        result = tool.run(dataset1="ds000001", dataset2="ds000002", metric="euclidean")

        assert result["status"] == "success"
        assert result["data"]["similarity_score"] == 12.5  # Distance, not similarity
        assert result["data"]["metric"] == "euclidean"

    def test_similarity_with_mask(self):
        """Test similarity computation with brain mask."""
        tool = BrainSimilarityTool()
        result = tool.run(
            dataset1="ds000001",
            dataset2="ds000002",
            metric="correlation",
            mask="/data/masks/motor_cortex.nii.gz",
        )

        assert result["status"] == "success"
        assert result["data"]["mask_applied"] == "/data/masks/motor_cortex.nii.gz"

    def test_similarity_error(self):
        """Test error handling in similarity computation."""
        tool = BrainSimilarityTool()

        with patch.object(tool, "_run", side_effect=Exception("Dataset not found")):
            result = tool.run(dataset1="invalid_dataset", dataset2="ds000002")

            assert result["status"] == "error"
            assert "Dataset not found" in result["error"]


class TestFMRITools:
    """Test FMRITools collection class."""

    def test_tools_initialization(self):
        """Test that all tools are initialized."""
        tools = FMRITools()

        assert isinstance(tools.glm, GLMAnalysisTool)
        assert isinstance(tools.encoding, EncodingModelTool)
        assert isinstance(tools.contrast, ContrastAnalysisTool)
        assert isinstance(tools.similarity, BrainSimilarityTool)

    def test_get_all_tools(self):
        """Test getting all tools as a list."""
        tools = FMRITools()
        all_tools = tools.get_all_tools()

        assert len(all_tools) == 4
        assert all(hasattr(tool, "run") for tool in all_tools)

        # Check tool names
        tool_names = [tool.get_tool_name() for tool in all_tools]
        assert "glm_analysis" in tool_names
        assert "encoding_model" in tool_names
        assert "contrast_analysis" in tool_names
        assert "brain_similarity" in tool_names

    def test_get_tool_by_name(self):
        """Test getting specific tool by name."""
        tools = FMRITools()

        # Valid tool names
        glm_tool = tools.get_tool_by_name("glm_analysis")
        assert isinstance(glm_tool, GLMAnalysisTool)

        encoding_tool = tools.get_tool_by_name("encoding_model")
        assert isinstance(encoding_tool, EncodingModelTool)

        # Invalid tool name
        invalid_tool = tools.get_tool_by_name("invalid_tool")
        assert invalid_tool is None

    def test_langchain_tool_conversion(self):
        """Test converting tools to LangChain format."""
        tools = FMRITools()

        # Convert GLM tool
        lc_tool = tools.glm.as_langchain_tool()
        assert lc_tool.name == "glm_analysis"
        assert lc_tool.args_schema == GLMAnalysisArgs

        # Test it can be called
        with patch("brain_researcher.services.br_kg.api.glmfitlins_api.GLMFitlinsAPI"):
            result = lc_tool.func(dataset_id="ds000001", contrasts={"test": [1, -1]})
            assert isinstance(result, dict)
            assert "status" in result


class TestIntegrationScenarios:
    """Test realistic integration scenarios with fMRI tools."""

    @patch.object(GLMAnalysisTool, "_run")
    def test_glm_to_contrast_pipeline(self, mock_api_class, tmp_path):
        """Test pipeline from GLM analysis to contrast interpretation."""
        z_map = TestContrastAnalysisTool._write_z_map(tmp_path)
        mock_api_class.return_value = ToolResult(
            status="success",
            data={
                "contrasts": {"motor_vs_rest": {"z_map": str(z_map)}},
            },
        )

        # Run GLM analysis
        glm_tool = GLMAnalysisTool()
        glm_result = glm_tool.run(
            dataset_id="ds000001", contrasts={"motor_vs_rest": [1, -1]}
        )

        assert glm_result["status"] == "success"
        z_map_path = glm_result["data"]["contrasts"]["motor_vs_rest"]["z_map"]

        # Use output for contrast analysis
        contrast_tool = ContrastAnalysisTool()
        contrast_result = contrast_tool.run(
            z_map_path=z_map_path,
            contrast_name="motor_vs_rest",
            task_description="Finger tapping task",
        )

        assert contrast_result["status"] == "success"
        assert contrast_result["data"]["contrast_name"] == "motor_vs_rest"

    def test_multiple_dataset_similarity(self):
        """Test computing similarity across multiple datasets."""
        similarity_tool = BrainSimilarityTool()

        datasets = ["ds000001", "ds000002", "ds000003"]
        similarities = []

        # Compute pairwise similarities
        for i in range(len(datasets)):
            for j in range(i + 1, len(datasets)):
                result = similarity_tool.run(
                    dataset1=datasets[i], dataset2=datasets[j], metric="correlation"
                )
                if result["status"] == "success":
                    similarities.append(
                        {
                            "pair": (datasets[i], datasets[j]),
                            "score": result["data"]["similarity_score"],
                        }
                    )

        assert len(similarities) == 3  # 3 choose 2
        assert all(s["score"] >= 0 for s in similarities)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
