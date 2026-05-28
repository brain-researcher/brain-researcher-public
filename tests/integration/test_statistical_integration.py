"""Integration tests for statistical analysis workflow."""

import os
import tempfile

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

# Check if required packages are available
try:
    import nilearn
    from nilearn import image, plotting
    from nilearn.glm.first_level import FirstLevelModel

    HAS_NILEARN = True
except ImportError:
    HAS_NILEARN = False

try:
    import statsmodels

    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

from brain_researcher.core.analysis.statistical_analysis import StatisticalAnalyzer
from brain_researcher.services.tools.statistical_tools import (
    ClusterCorrectionTool,
    GLMStatisticalAnalysisTool,
    GroupComparisonTool,
    MultipleComparisonsCorrectionTool,
    VoxelwisePermutationTool,
)


def create_synthetic_fmri_data(
    n_subjects=5, n_scans=100, shape=(20, 20, 20), effect_size=2.0, noise_level=1.0
):
    """Create synthetic fMRI data with a known effect."""
    np.random.seed(42)

    data_list = []
    design_list = []

    for subj in range(n_subjects):
        # Create design with alternating blocks
        block_size = 10
        n_blocks = n_scans // block_size
        condition = np.repeat(np.tile([0, 1], n_blocks // 2), block_size)[:n_scans]

        # Create design matrix
        design = pd.DataFrame(
            {
                "intercept": np.ones(n_scans),
                "condition": condition,
                "linear_drift": np.linspace(0, 1, n_scans),
            }
        )

        # Create data with effect in a specific region
        data = np.random.randn(*shape, n_scans) * noise_level

        # Add effect in a 5x5x5 cube
        effect_region = slice(8, 13)
        for t in range(n_scans):
            if condition[t] == 1:
                data[effect_region, effect_region, effect_region, t] += effect_size

        # Add some subject-specific noise
        data += np.random.randn(*shape, n_scans) * 0.5

        data_list.append(data)
        design_list.append(design)

    return data_list, design_list


@pytest.fixture
def synthetic_data():
    """Create synthetic fMRI dataset."""
    return create_synthetic_fmri_data(n_subjects=5, n_scans=50)


@pytest.fixture
def temp_data_dir():
    """Create temporary directory with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.slow
@pytest.mark.skipif(not HAS_NILEARN, reason="nilearn not installed")
class TestStatisticalWorkflow:
    """Test complete statistical analysis workflow."""

    def test_glm_to_correction_workflow(self, synthetic_data, temp_data_dir):
        """Test GLM analysis followed by multiple comparison correction."""
        data_list, design_list = synthetic_data

        # Save first subject's data
        subj_data = data_list[0]
        subj_design = design_list[0]

        img = nib.Nifti1Image(subj_data, np.eye(4))
        img_path = os.path.join(temp_data_dir, "subject1_bold.nii.gz")
        nib.save(img, img_path)

        design_path = os.path.join(temp_data_dir, "design.csv")
        subj_design.to_csv(design_path, index=False)

        # Step 1: Run GLM
        glm_tool = GLMStatisticalAnalysisTool()
        glm_result = glm_tool.run(
            data_paths=[img_path],
            design_matrix=design_path,
            contrasts={"task_effect": [0, 1, 0]},  # Test condition effect
            tr=2.0,
            output_dir=temp_data_dir,
        )

        assert glm_result["status"] == "success"
        p_map_path = glm_result["data"]["results"]["task_effect"]["p_map_path"]

        # Step 2: Apply FDR correction
        correction_tool = MultipleComparisonsCorrectionTool()
        corr_result = correction_tool.run(
            p_values=p_map_path, method="fdr", alpha=0.05, is_image=True
        )

        assert corr_result["status"] == "success"
        assert corr_result["data"]["n_significant"] > 0

        # Step 3: Apply cluster correction
        z_map_path = glm_result["data"]["results"]["task_effect"]["z_map_path"]
        cluster_tool = ClusterCorrectionTool()
        cluster_result = cluster_tool.run(
            stat_map_path=z_map_path,
            method="cluster",
            cluster_threshold=2.0,  # Lower threshold for synthetic data
            min_cluster_size=20,
        )

        assert cluster_result["status"] == "success"
        assert cluster_result["data"]["n_clusters_surviving"] > 0

        # Verify the effect was detected in the expected region
        clusters = cluster_result["data"]["clusters"]
        assert len(clusters) > 0

        # Check if any cluster is near the true effect location (center at 10,10,10)
        found_effect = False
        for cluster in clusters:
            peak = cluster["peak_voxel"]
            # Check if peak is within the effect region (8-13 for each dimension)
            if all(8 <= coord <= 13 for coord in peak):
                found_effect = True
                break

        assert found_effect, "Effect region not detected in clusters"

    def test_group_comparison_workflow(self, synthetic_data, temp_data_dir):
        """Test group comparison with correction."""
        data_list, design_list = synthetic_data

        # Create two groups with different effect sizes
        group1_paths = []
        group2_paths = []

        # Group 1: Normal effect
        for i in range(2):
            # Average across time to get activation map
            activation = data_list[i].mean(axis=3)
            img = nib.Nifti1Image(activation, np.eye(4))
            path = os.path.join(temp_data_dir, f"group1_sub{i}.nii.gz")
            nib.save(img, path)
            group1_paths.append(path)

        # Group 2: Stronger effect (simulate by adding to activation)
        for i in range(2, 4):
            activation = data_list[i].mean(axis=3)
            # Add extra activation in effect region
            activation[8:13, 8:13, 8:13] += 1.0
            img = nib.Nifti1Image(activation, np.eye(4))
            path = os.path.join(temp_data_dir, f"group2_sub{i}.nii.gz")
            nib.save(img, path)
            group2_paths.append(path)

        # Run group comparison
        group_tool = GroupComparisonTool()
        group_result = group_tool.run(
            group1_data=group1_paths,
            group2_data=group2_paths,
            test_type="independent",
            correction_method="fdr",
            output_dir=temp_data_dir,
        )

        assert group_result["status"] == "success"
        assert group_result["data"]["n_significant_voxels"] > 0

        # Load and check results
        t_img = nib.load(group_result["data"]["t_map_path"])
        t_data = t_img.get_fdata()

        # Check that maximum t-value is in the effect region
        max_idx = np.unravel_index(np.abs(t_data).argmax(), t_data.shape)
        assert all(8 <= idx <= 13 for idx in max_idx), "Peak not in effect region"

    def test_statistical_analyzer_integration(self, synthetic_data, temp_data_dir):
        """Test the StatisticalAnalyzer class."""
        data_list, design_list = synthetic_data

        # Save test data
        img_path = os.path.join(temp_data_dir, "test_4d.nii.gz")
        img = nib.Nifti1Image(data_list[0], np.eye(4))
        nib.save(img, img_path)

        design_path = os.path.join(temp_data_dir, "design.csv")
        design_list[0].to_csv(design_path, index=False)

        # Test GLM through StatisticalAnalyzer
        analyzer = StatisticalAnalyzer()

        glm_request = {
            "analysis_type": "glm",
            "data_paths": [img_path],
            "design_matrix": design_path,
            "contrasts": {"main_effect": [0, 1, 0]},
            "tr": 2.0,
            "output_dir": temp_data_dir,
        }

        result = analyzer.run_statistical_analysis(glm_request)

        assert result["success"]
        assert "results" in result
        assert "main_effect" in result["results"]

        # Verify files were created
        assert os.path.exists(result["results"]["main_effect"]["z_map_path"])
        assert os.path.exists(result["results"]["main_effect"]["t_map_path"])


@pytest.mark.slow
@pytest.mark.skipif(
    not HAS_NILEARN or not HAS_STATSMODELS,
    reason="nilearn or statsmodels not installed",
)
class TestAdvancedStatistics:
    """Test advanced statistical features."""

    def test_connectivity_statistics_workflow(self, temp_data_dir):
        """Test connectivity analysis statistics."""
        # Create synthetic connectivity matrices
        n_subjects = 10
        n_nodes = 20

        # Create matrices with known structure
        matrices = []
        for i in range(n_subjects):
            # Base random connectivity
            mat = np.random.randn(n_nodes, n_nodes) * 0.3

            # Add structured connectivity (e.g., two modules)
            mat[0:10, 0:10] += 0.5  # Within-module 1
            mat[10:20, 10:20] += 0.5  # Within-module 2

            # Make symmetric
            mat = (mat + mat.T) / 2
            np.fill_diagonal(mat, 1)  # Self-connections

            # Add subject variability
            mat += np.random.randn(n_nodes, n_nodes) * 0.1

            matrices.append(mat)

        # Save matrices
        mat_paths = []
        for i, mat in enumerate(matrices):
            path = os.path.join(temp_data_dir, f"connectivity_sub{i:02d}.npy")
            np.save(path, mat)
            mat_paths.append(path)

        # Run connectivity statistics
        from brain_researcher.services.tools.statistical_tools import (
            ConnectivityStatisticsTool,
        )

        conn_tool = ConnectivityStatisticsTool()
        result = conn_tool.run(
            connectivity_matrices=mat_paths,
            test_type="one-sample",
            correction_method="fdr",
        )

        assert result["status"] == "success"
        assert result["data"]["n_significant_edges"] > 0

        # Load results
        t_matrix = np.load(result["data"]["t_matrix_path"])

        # Check that within-module connections have higher t-values
        module1_t = np.abs(t_matrix[0:10, 0:10]).mean()
        module2_t = np.abs(t_matrix[10:20, 10:20]).mean()
        between_t = np.abs(t_matrix[0:10, 10:20]).mean()

        assert module1_t > between_t
        assert module2_t > between_t

    @pytest.mark.skipif(True, reason="Permutation tests are slow")
    def test_permutation_workflow(self, synthetic_data, temp_data_dir):
        """Test voxelwise permutation testing (slow)."""
        data_list, _ = synthetic_data

        # Create two groups
        group1_paths = []
        group2_paths = []

        for i in range(2):
            activation = data_list[i].mean(axis=3)
            img = nib.Nifti1Image(activation, np.eye(4))
            path = os.path.join(temp_data_dir, f"perm_g1_sub{i}.nii.gz")
            nib.save(img, path)
            group1_paths.append(path)

        for i in range(2, 4):
            activation = data_list[i].mean(axis=3)
            activation[8:13, 8:13, 8:13] += 1.5  # Add effect
            img = nib.Nifti1Image(activation, np.eye(4))
            path = os.path.join(temp_data_dir, f"perm_g2_sub{i}.nii.gz")
            nib.save(img, path)
            group2_paths.append(path)

        # Run permutation test
        perm_tool = VoxelwisePermutationTool()
        result = perm_tool.run(
            group1_paths=group1_paths,
            group2_paths=group2_paths,
            n_permutations=100,  # Small number for testing
            tfce=False,
            output_dir=temp_data_dir,
        )

        assert result["status"] == "success"
        assert result["data"]["n_significant_05"] > 0


def test_statistical_tools_registry():
    """Test that statistical tools are properly registered."""
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    registry = ToolRegistry()

    # Check that all statistical tools are registered
    expected_tools = [
        "glm_statistical_analysis",
        "group_comparison",
        "multiple_comparisons_correction",
        "cluster_correction",
        "voxelwise_permutation_test",
        "connectivity_statistics",
        "surface_statistics",
    ]

    for tool_name in expected_tools:
        tool = registry.get_tool(tool_name)
        assert tool is not None, f"Tool {tool_name} not found in registry"

        # Verify tool has proper methods
        assert hasattr(tool, "get_tool_name")
        assert hasattr(tool, "get_tool_description")
        assert hasattr(tool, "run")


if __name__ == "__main__":
    # Run a simple test
    data, designs = create_synthetic_fmri_data(n_subjects=2, n_scans=50)
    print(f"Created synthetic data with shape: {data[0].shape}")
    print(f"Design matrix shape: {designs[0].shape}")
    print("Effect should be in region [8:13, 8:13, 8:13]")
