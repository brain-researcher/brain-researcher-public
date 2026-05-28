"""Unit tests for statistical analysis tools."""

import os
import tempfile
from unittest.mock import Mock, patch

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

from brain_researcher.services.tools.statistical_tools import (
    ClusterCorrectionArgs,
    ClusterCorrectionTool,
    ConnectivityStatisticsTool,
    ConnectivityStatsArgs,
    GLMStatisticalAnalysisTool,
    GLMStatisticalArgs,
    GroupComparisonArgs,
    GroupComparisonTool,
    MultipleComparisonsCorrectionTool,
    MultipleCorrectionArgs,
    StatisticalTools,
    SurfaceStatisticsArgs,
    SurfaceStatisticsTool,
    VoxelwisePermutationArgs,
    VoxelwisePermutationTool,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(name="mock_3d_image")
def _mock_3d_image_fixture():
    """Create a mock 3D NIfTI image."""
    data = np.random.randn(10, 10, 10)
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)
    return img


def mock_3d_image():
    """Helper to build a fresh 3D NIfTI image for local calls."""
    data = np.random.randn(10, 10, 10)
    affine = np.eye(4)
    return nib.Nifti1Image(data, affine)


@pytest.fixture
def mock_4d_image():
    """Create a mock 4D fMRI NIfTI image."""
    data = np.random.randn(10, 10, 10, 20)  # 20 time points
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)
    return img


@pytest.fixture
def design_matrix():
    """Create a mock design matrix."""
    n_scans = 20
    design = pd.DataFrame(
        {
            "intercept": np.ones(n_scans),
            "condition": np.repeat([0, 1], n_scans // 2),
            "linear_trend": np.linspace(0, 1, n_scans),
        }
    )
    return design


class TestGLMStatisticalAnalysisTool:
    def test_properties(self):
        tool = GLMStatisticalAnalysisTool()
        assert tool.get_tool_name() == "glm_statistical_analysis"
        assert "GLM" in tool.get_tool_description()
        assert tool.get_args_schema() == GLMStatisticalArgs

    def test_design_matrix_validation(self, temp_dir, mock_4d_image, design_matrix):
        """Test that design matrix validation works correctly."""
        tool = GLMStatisticalAnalysisTool()

        # Save test data
        img_path = os.path.join(temp_dir, "test_4d.nii.gz")
        nib.save(mock_4d_image, img_path)

        # Wrong number of rows in design matrix
        bad_design = design_matrix.iloc[:10]  # Only 10 rows instead of 20
        design_path = os.path.join(temp_dir, "bad_design.csv")
        bad_design.to_csv(design_path, index=False)

        result = tool.run(
            data_paths=[img_path],
            design_matrix=design_path,
            contrasts={"main": [0, 1, 0]},
            output_dir=temp_dir,
        )

        assert result["status"] == "error"
        assert "must match number of scans" in result["error"]

    def test_contrast_validation(self, temp_dir, mock_4d_image, design_matrix):
        """Test that contrast validation works correctly."""
        tool = GLMStatisticalAnalysisTool()

        # Save test data
        img_path = os.path.join(temp_dir, "test_4d.nii.gz")
        nib.save(mock_4d_image, img_path)

        design_path = os.path.join(temp_dir, "design.csv")
        design_matrix.to_csv(design_path, index=False)

        # Wrong contrast length
        result = tool.run(
            data_paths=[img_path],
            design_matrix=design_path,
            contrasts={"bad": [0, 1]},  # Only 2 weights for 3 columns
            output_dir=temp_dir,
        )

        assert result["status"] == "error"
        assert "length" in result["error"]

    @patch("nilearn.glm.first_level.FirstLevelModel")
    def test_successful_glm(
        self, mock_glm_class, temp_dir, mock_4d_image, design_matrix
    ):
        """Test successful GLM analysis."""
        tool = GLMStatisticalAnalysisTool()

        # Mock GLM
        mock_glm = Mock()
        mock_glm_class.return_value = mock_glm
        mock_glm.fit.return_value = mock_glm

        # Mock contrast results
        mock_z_map = mock_3d_image()
        mock_t_map = mock_3d_image()
        mock_p_map = mock_3d_image()
        mock_effect_map = mock_3d_image()

        def compute_contrast_side_effect(weights, output_type):
            if output_type == "z_score":
                return mock_z_map
            elif output_type == "stat":
                return mock_t_map
            elif output_type == "p_value":
                return mock_p_map
            elif output_type == "effect_size":
                return mock_effect_map

        mock_glm.compute_contrast.side_effect = compute_contrast_side_effect

        # Save test data
        img_path = os.path.join(temp_dir, "test_4d.nii.gz")
        nib.save(mock_4d_image, img_path)

        design_path = os.path.join(temp_dir, "design.csv")
        design_matrix.to_csv(design_path, index=False)

        result = tool.run(
            data_paths=[img_path],
            design_matrix=design_path,
            contrasts={"main": [0, 1, 0]},
            tr=2.0,
            output_dir=temp_dir,
        )

        assert result["status"] == "success"
        assert "results" in result["data"]
        assert "main" in result["data"]["results"]
        assert os.path.exists(result["data"]["results"]["main"]["z_map_path"])


class TestGroupComparisonTool:
    def test_properties(self):
        tool = GroupComparisonTool()
        assert tool.get_tool_name() == "group_comparison"
        assert "group comparison" in tool.get_tool_description()
        assert tool.get_args_schema() == GroupComparisonArgs

    def test_paired_test_validation(self, temp_dir, mock_3d_image):
        """Test that paired tests require equal group sizes."""
        tool = GroupComparisonTool()

        # Create unequal groups
        g1_paths = []
        g2_paths = []

        for i in range(3):
            path = os.path.join(temp_dir, f"g1_sub{i}.nii.gz")
            nib.save(mock_3d_image, path)
            g1_paths.append(path)

        for i in range(2):  # Different size
            path = os.path.join(temp_dir, f"g2_sub{i}.nii.gz")
            nib.save(mock_3d_image, path)
            g2_paths.append(path)

        result = tool.run(
            group1_data=g1_paths,
            group2_data=g2_paths,
            test_type="paired",
            output_dir=temp_dir,
        )

        assert result["status"] == "error"
        assert "equal group sizes" in result["error"]

    @patch("scipy.stats.ttest_ind")
    def test_successful_group_comparison(self, mock_ttest, temp_dir, mock_3d_image):
        """Test successful group comparison."""
        tool = GroupComparisonTool()

        # Mock t-test results
        n_voxels = 1000  # Approximate for 10x10x10 brain mask
        mock_ttest.return_value = (
            np.random.randn(n_voxels),  # t-values
            np.random.uniform(0, 1, n_voxels),  # p-values
        )

        # Create groups
        g1_paths = []
        g2_paths = []

        for i in range(3):
            path = os.path.join(temp_dir, f"g1_sub{i}.nii.gz")
            nib.save(mock_3d_image, path)
            g1_paths.append(path)

            path = os.path.join(temp_dir, f"g2_sub{i}.nii.gz")
            nib.save(mock_3d_image, path)
            g2_paths.append(path)

        result = tool.run(
            group1_data=g1_paths,
            group2_data=g2_paths,
            test_type="independent",
            output_dir=temp_dir,
        )

        assert result["status"] == "success"
        assert os.path.exists(result["data"]["t_map_path"])
        assert os.path.exists(result["data"]["p_map_path"])
        assert os.path.exists(result["data"]["cohen_d_map_path"])
        assert "n_significant_voxels" in result["data"]


class TestMultipleComparisonsCorrectionTool:
    def test_properties(self):
        tool = MultipleComparisonsCorrectionTool()
        assert tool.get_tool_name() == "multiple_comparisons_correction"
        assert "multiple comparisons" in tool.get_tool_description()
        assert tool.get_args_schema() == MultipleCorrectionArgs

    def test_fdr_correction_list(self):
        """Test FDR correction on a list of p-values."""
        tool = MultipleComparisonsCorrectionTool()

        p_values = [0.001, 0.01, 0.02, 0.05, 0.1, 0.5, 0.9]

        result = tool.run(p_values=p_values, method="fdr", alpha=0.05)

        assert result["status"] == "success"
        assert len(result["data"]["corrected_p"]) == len(p_values)
        assert len(result["data"]["significant"]) == len(p_values)
        assert result["data"]["n_tests"] == len(p_values)

    def test_bonferroni_correction_list(self):
        """Test Bonferroni correction on a list of p-values."""
        tool = MultipleComparisonsCorrectionTool()

        p_values = [0.001, 0.01, 0.05]

        result = tool.run(p_values=p_values, method="bonferroni", alpha=0.05)

        assert result["status"] == "success"
        # Bonferroni should multiply p-values by number of tests
        corrected = result["data"]["corrected_p"]
        assert corrected[0] >= p_values[0] * len(p_values)

    def test_image_correction(self, temp_dir, mock_3d_image):
        """Test correction on a p-value image."""
        tool = MultipleComparisonsCorrectionTool()

        # Create p-value map
        p_data = np.random.uniform(0, 1, mock_3d_image.shape)
        p_img = nib.Nifti1Image(p_data, mock_3d_image.affine)
        p_path = os.path.join(temp_dir, "p_values.nii.gz")
        nib.save(p_img, p_path)

        result = tool.run(p_values=p_path, method="fdr", alpha=0.05, is_image=True)

        assert result["status"] == "success"
        assert "corrected_p_map_path" in result["data"]
        assert os.path.exists(result["data"]["corrected_p_map_path"])


class TestClusterCorrectionTool:
    def test_properties(self):
        tool = ClusterCorrectionTool()
        assert tool.get_tool_name() == "cluster_correction"
        assert "cluster" in tool.get_tool_description()
        assert tool.get_args_schema() == ClusterCorrectionArgs

    def test_cluster_correction(self, temp_dir):
        """Test basic cluster-extent correction."""
        tool = ClusterCorrectionTool()

        # Create a stat map with clear clusters
        data = np.zeros((20, 20, 20))
        # Add two clusters
        data[5:8, 5:8, 5:8] = 4.0  # 27 voxels
        data[12:14, 12:14, 12:14] = 3.5  # 8 voxels

        stat_img = nib.Nifti1Image(data, np.eye(4))
        stat_path = os.path.join(temp_dir, "stat_map.nii.gz")
        nib.save(stat_img, stat_path)

        result = tool.run(
            stat_map_path=stat_path,
            method="cluster",
            cluster_threshold=3.0,
            min_cluster_size=10,
        )

        assert result["status"] == "success"
        assert result["data"]["n_clusters_found"] >= 1
        assert result["data"]["n_clusters_surviving"] >= 1
        assert os.path.exists(result["data"]["corrected_map_path"])

    def test_tfce_not_implemented(self, temp_dir, mock_3d_image):
        """Test that TFCE returns appropriate error."""
        tool = ClusterCorrectionTool()

        stat_path = os.path.join(temp_dir, "stat_map.nii.gz")
        nib.save(mock_3d_image, stat_path)

        result = tool.run(stat_map_path=stat_path, method="tfce")

        assert result["status"] == "error"
        assert "not yet implemented" in result["error"]


class TestVoxelwisePermutationTool:
    def test_properties(self):
        tool = VoxelwisePermutationTool()
        assert tool.get_tool_name() == "voxelwise_permutation_test"
        assert "permutation" in tool.get_tool_description()
        assert tool.get_args_schema() == VoxelwisePermutationArgs

    @patch("nilearn.mass_univariate.permuted_ols")
    def test_permutation_test(self, mock_permuted_ols, temp_dir, mock_3d_image):
        """Test voxelwise permutation testing."""
        tool = VoxelwisePermutationTool()

        # Mock permuted_ols result
        neg_log_p_data = np.random.uniform(0, 5, mock_3d_image.shape)
        mock_result = nib.Nifti1Image(neg_log_p_data, mock_3d_image.affine)
        mock_permuted_ols.return_value = mock_result

        # Create groups
        g1_paths = []
        g2_paths = []

        for i in range(3):
            path = os.path.join(temp_dir, f"g1_sub{i}.nii.gz")
            nib.save(mock_3d_image, path)
            g1_paths.append(path)

            path = os.path.join(temp_dir, f"g2_sub{i}.nii.gz")
            nib.save(mock_3d_image, path)
            g2_paths.append(path)

        result = tool.run(
            group1_paths=g1_paths,
            group2_paths=g2_paths,
            n_permutations=100,
            tfce=False,
            output_dir=temp_dir,
        )

        assert result["status"] == "success"
        assert os.path.exists(result["data"]["neg_log_p_map_path"])
        assert os.path.exists(result["data"]["p_map_path"])
        assert "n_significant_05" in result["data"]


class TestConnectivityStatisticsTool:
    def test_properties(self):
        tool = ConnectivityStatisticsTool()
        assert tool.get_tool_name() == "connectivity_statistics"
        assert "connectivity" in tool.get_tool_description()
        assert tool.get_args_schema() == ConnectivityStatsArgs

    def test_connectivity_matrices_list(self):
        """Test connectivity statistics on matrix data."""
        tool = ConnectivityStatisticsTool()

        # Create connectivity matrices
        n_subjects = 5
        n_nodes = 10
        matrices = []

        for i in range(n_subjects):
            # Create symmetric matrix
            mat = np.random.randn(n_nodes, n_nodes)
            mat = (mat + mat.T) / 2
            matrices.append(mat.tolist())

        result = tool.run(connectivity_matrices=matrices, test_type="one-sample")

        assert result["status"] == "success"
        assert "t_matrix_path" in result["data"]
        assert "p_matrix_path" in result["data"]
        assert result["data"]["n_edges_tested"] == n_nodes * (n_nodes - 1) // 2

    def test_connectivity_files(self, temp_dir):
        """Test loading connectivity matrices from files."""
        tool = ConnectivityStatisticsTool()

        # Create matrix files
        n_subjects = 3
        n_nodes = 5
        mat_paths = []

        for i in range(n_subjects):
            mat = np.random.randn(n_nodes, n_nodes)
            mat = (mat + mat.T) / 2

            # Save as .npy
            path = os.path.join(temp_dir, f"conn_mat_{i}.npy")
            np.save(path, mat)
            mat_paths.append(path)

        result = tool.run(
            connectivity_matrices=mat_paths,
            test_type="one-sample",
            correction_method="fdr",
        )

        assert result["status"] == "success"
        assert os.path.exists(result["data"]["t_matrix_path"])


class TestSurfaceStatisticsTool:
    def test_properties(self):
        tool = SurfaceStatisticsTool()
        assert tool.get_tool_name() == "surface_statistics"
        assert "surface" in tool.get_tool_description()
        assert tool.get_args_schema() == SurfaceStatisticsArgs

    @patch("nilearn.surface.vol_to_surf")
    @patch("nilearn.datasets.fetch_surf_fsaverage")
    def test_surface_projection(
        self, mock_fetch, mock_vol_to_surf, temp_dir, mock_3d_image
    ):
        """Test surface-based statistics."""
        tool = SurfaceStatisticsTool()

        # Mock surface mesh
        mock_mesh = Mock()
        mock_mesh.pial_left = "mock_left_mesh"
        mock_mesh.pial_right = "mock_right_mesh"
        mock_mesh.sulc_left = np.random.randn(1000)
        mock_mesh.sulc_right = np.random.randn(1000)
        mock_fetch.return_value = mock_mesh

        # Mock surface projection
        n_vertices = 1000
        mock_vol_to_surf.return_value = np.random.randn(n_vertices)

        # Create volume paths
        vol_paths = []
        for i in range(3):
            path = os.path.join(temp_dir, f"vol_{i}.nii.gz")
            nib.save(mock_3d_image, path)
            vol_paths.append(path)

        result = tool.run(
            volume_paths=vol_paths,
            surface_mesh="fsaverage5",
            hemisphere="left",
            output_dir=temp_dir,
        )

        assert result["status"] == "success"
        assert "results" in result["data"]
        assert "left" in result["data"]["results"]
        assert os.path.exists(result["data"]["results"]["left"]["t_values_path"])


class TestStatisticalTools:
    def test_collection(self):
        """Test the tools collection."""
        tools = StatisticalTools()
        all_tools = tools.get_all_tools()

        assert len(all_tools) == 7

        names = {t.get_tool_name() for t in all_tools}
        expected = {
            "glm_statistical_analysis",
            "group_comparison",
            "multiple_comparisons_correction",
            "cluster_correction",
            "voxelwise_permutation_test",
            "connectivity_statistics",
            "surface_statistics",
        }
        assert names == expected

    def test_get_tool_by_name(self):
        """Test retrieving tools by name."""
        tools = StatisticalTools()

        glm = tools.get_tool_by_name("glm_statistical_analysis")
        assert isinstance(glm, GLMStatisticalAnalysisTool)

        missing = tools.get_tool_by_name("nonexistent")
        assert missing is None

    def test_all_tools_have_output_dir(self):
        """Test that all tools have output_dir configuration."""
        tools = StatisticalTools()
        for tool in tools.get_all_tools():
            if hasattr(tool, "output_dir"):
                assert tool.output_dir is not None


class TestPydanticValidation:
    def test_glm_args_validation(self):
        """Test GLM arguments validation."""
        # Valid args
        args = GLMStatisticalArgs(
            data_paths=["test.nii.gz"],
            design_matrix="design.csv",
            contrasts={"main": [1, 0, -1]},
        )
        assert args.tr == 2.0  # Default

        # Invalid contrast values
        with pytest.raises(ValueError):
            GLMStatisticalArgs(
                data_paths=["test.nii.gz"],
                design_matrix="design.csv",
                contrasts={"bad": ["a", "b", "c"]},
            )

    def test_group_comparison_args_validation(self):
        """Test group comparison arguments validation."""
        # Valid args
        args = GroupComparisonArgs(
            group1_data=["g1.nii.gz"],
            group2_data=["g2.nii.gz"],
            test_type="independent",
        )
        assert args.test_type == "independent"

        # Invalid test type
        with pytest.raises(ValueError):
            GroupComparisonArgs(
                group1_data=["g1.nii.gz"],
                group2_data=["g2.nii.gz"],
                test_type="invalid",
            )
