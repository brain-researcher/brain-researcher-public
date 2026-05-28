"""Tests for the enhanced statistical analysis module."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

# This module exercises a legacy/optional statistical analyzer that may not be
# installed in minimal environments. Skip cleanly when it's absent so the core
# suite can run without pulling heavy deps (statsmodels/nilearn, etc.).
import pytest

StatisticalAnalyzer = pytest.importorskip(
    "brain_researcher.core.analysis.statistical_analysis",
    reason="legacy statistical_analysis module not available in this environment",
).StatisticalAnalyzer
from brain_researcher.services.tools.statistical_tools import (
    ConnectivityStatisticsTool,
    MultipleComparisonsCorrectionTool,
    VoxelwisePermutationTool,
)


class TestStatisticalAnalyzer(unittest.TestCase):
    """Test the enhanced StatisticalAnalyzer with real computations."""

    def setUp(self):
        self.output_dir = Path("test_stat_output")
        self.output_dir.mkdir(exist_ok=True)
        self.analyzer = StatisticalAnalyzer()

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _create_4d_image(self, name: str, n_scans: int = 20) -> str:
        """Create a 4D fMRI image with some structure."""
        # Create data with spatial structure
        shape = (10, 10, 10, n_scans)
        data = np.random.randn(*shape) * 0.5

        # Add activation in a region for half the scans
        activation_scans = np.arange(0, n_scans, 2)
        data[4:7, 4:7, 4:7, activation_scans] += 2.0

        img = nib.Nifti1Image(data, np.eye(4))
        path = self.output_dir / name
        nib.save(img, path)
        return str(path)

    def _create_3d_image(self, name: str, mean: float = 0.0) -> str:
        """Create a 3D image with specified mean."""
        data = np.random.randn(10, 10, 10) * 0.5 + mean
        # Add some structure
        data[4:7, 4:7, 4:7] += 1.0

        img = nib.Nifti1Image(data, np.eye(4))
        path = self.output_dir / name
        nib.save(img, path)
        return str(path)

    def test_glm_analysis_with_validation(self):
        """Test GLM analysis with proper validation."""
        # Create test data
        n_scans = 20
        img_path = self._create_4d_image("test_bold.nii.gz", n_scans)

        # Create design matrix
        design = pd.DataFrame(
            {
                "intercept": np.ones(n_scans),
                "task": np.tile([0, 1], n_scans // 2),
                "linear": np.linspace(0, 1, n_scans),
            }
        )
        design_path = self.output_dir / "design.csv"
        design.to_csv(design_path, index=False)

        # Test successful GLM
        request = {
            "analysis_type": "glm",
            "data_paths": [img_path],
            "design_matrix": str(design_path),
            "contrasts": {"task_effect": [0, 1, 0]},
            "tr": 2.0,
            "output_dir": str(self.output_dir),
        }

        result = self.analyzer.run_statistical_analysis(request)

        self.assertTrue(result["success"])
        self.assertIn("task_effect", result["results"])

        # Check that all maps were created
        task_result = result["results"]["task_effect"]
        self.assertTrue(Path(task_result["z_map_path"]).exists())
        self.assertTrue(Path(task_result["t_map_path"]).exists())
        self.assertTrue(Path(task_result["p_map_path"]).exists())
        self.assertTrue(Path(task_result["effect_map_path"]).exists())

        # Check significant voxels were found
        self.assertGreater(task_result["n_significant_voxels"], 0)

    def test_glm_validation_errors(self):
        """Test GLM validation catches errors."""
        # Create test data
        n_scans = 20
        img_path = self._create_4d_image("test_bold.nii.gz", n_scans)

        # Create WRONG design matrix (wrong number of rows)
        bad_design = pd.DataFrame(
            {
                "intercept": np.ones(10),  # Only 10 rows instead of 20
                "task": np.tile([0, 1], 5),
            }
        )
        bad_design_path = self.output_dir / "bad_design.csv"
        bad_design.to_csv(bad_design_path, index=False)

        request = {
            "analysis_type": "glm",
            "data_paths": [img_path],
            "design_matrix": str(bad_design_path),
            "contrasts": {"task": [0, 1]},
            "output_dir": str(self.output_dir),
        }

        result = self.analyzer.run_statistical_analysis(request)

        self.assertFalse(result["success"])
        self.assertIn("must match number of scans", result["error"])

    def test_group_comparison_with_correction(self):
        """Test group comparison with multiple comparison correction."""
        # Create two groups with different means
        g1_paths = [
            self._create_3d_image(f"g1_sub{i}.nii.gz", mean=0.0) for i in range(3)
        ]
        g2_paths = [
            self._create_3d_image(f"g2_sub{i}.nii.gz", mean=1.0) for i in range(3)
        ]

        request = {
            "analysis_type": "group_comparison",
            "group1_data": g1_paths,
            "group2_data": g2_paths,
            "test_type": "independent",
            "correction_method": "fdr",
            "output_dir": str(self.output_dir),
        }

        result = self.analyzer.run_statistical_analysis(request)

        self.assertTrue(result["success"])
        self.assertTrue(Path(result["results"]["t_map_path"]).exists())
        self.assertTrue(Path(result["results"]["p_map_path"]).exists())
        self.assertTrue(Path(result["results"]["cohen_d_map_path"]).exists())

        # Should have corrected p-values
        self.assertIn("p_map_corrected_path", result["results"])
        self.assertTrue(Path(result["results"]["p_map_corrected_path"]).exists())

        # Check effect size is reasonable
        self.assertGreater(result["results"]["effect_size"], 0)

    def test_paired_group_comparison(self):
        """Test paired t-test functionality."""
        # Create paired data
        n_pairs = 3
        g1_paths = []
        g2_paths = []

        for i in range(n_pairs):
            # Create paired images with systematic difference
            base = self._create_3d_image(f"base_{i}.nii.gz", mean=0.0)

            # Load and modify for second condition
            base_img = nib.load(base)
            base_data = base_img.get_fdata()

            # Add effect
            modified_data = base_data + 0.5 + np.random.randn(*base_data.shape) * 0.1
            modified_img = nib.Nifti1Image(modified_data, base_img.affine)

            g1_path = self.output_dir / f"paired_g1_sub{i}.nii.gz"
            g2_path = self.output_dir / f"paired_g2_sub{i}.nii.gz"

            nib.save(base_img, g1_path)
            nib.save(modified_img, g2_path)

            g1_paths.append(str(g1_path))
            g2_paths.append(str(g2_path))

        request = {
            "analysis_type": "group_comparison",
            "group1_data": g1_paths,
            "group2_data": g2_paths,
            "test_type": "paired",
            "output_dir": str(self.output_dir),
        }

        result = self.analyzer.run_statistical_analysis(request)

        self.assertTrue(result["success"])
        # Paired test should detect the systematic difference
        self.assertGreater(result["results"]["n_significant_voxels"], 0)


class TestStatisticalToolsIndividual(unittest.TestCase):
    """Test individual statistical tools."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multiple_comparisons_methods(self):
        """Test different multiple comparison correction methods."""
        tool = MultipleComparisonsCorrectionTool()

        # Create p-values with some structure
        p_values = np.concatenate(
            [
                np.random.uniform(0, 0.001, 10),  # Very significant
                np.random.uniform(0.001, 0.05, 20),  # Significant
                np.random.uniform(0.05, 1.0, 70),  # Not significant
            ]
        )
        np.random.shuffle(p_values)

        # Test FDR
        fdr_result = tool.run(p_values=p_values.tolist(), method="fdr", alpha=0.05)
        self.assertEqual(fdr_result["status"], "success")
        self.assertGreaterEqual(fdr_result["data"]["n_significant"], 10)

        # Test Bonferroni (should be more conservative)
        bonf_result = tool.run(
            p_values=p_values.tolist(), method="bonferroni", alpha=0.05
        )
        self.assertEqual(bonf_result["status"], "success")
        self.assertLessEqual(
            bonf_result["data"]["n_significant"], fdr_result["data"]["n_significant"]
        )

    def test_connectivity_statistics_paired(self):
        """Test paired connectivity analysis."""
        tool = ConnectivityStatisticsTool()

        # Create paired connectivity matrices (pre/post)
        n_nodes = 10
        n_subjects = 6

        # Pre matrices
        pre_matrices = []
        for i in range(n_subjects // 2):
            mat = np.random.randn(n_nodes, n_nodes) * 0.3
            mat = (mat + mat.T) / 2  # Symmetric
            pre_matrices.append(mat)

        # Post matrices (with increased connectivity)
        post_matrices = []
        for i in range(n_subjects // 2):
            mat = pre_matrices[i] + np.random.randn(n_nodes, n_nodes) * 0.1 + 0.2
            mat = (mat + mat.T) / 2
            post_matrices.append(mat)

        # Combine for paired test
        all_matrices = pre_matrices + post_matrices

        result = tool.run(
            connectivity_matrices=[m.tolist() for m in all_matrices], test_type="paired"
        )

        self.assertEqual(result["status"], "success")
        self.assertGreater(result["data"]["n_significant_edges"], 0)

    def test_voxelwise_permutation_small(self):
        """Test permutation with very small number of permutations."""
        tool = VoxelwisePermutationTool()

        # Create small test images
        shape = (5, 5, 5)
        g1_paths = []
        g2_paths = []

        for i in range(2):
            # Group 1
            data1 = np.random.randn(*shape)
            img1 = nib.Nifti1Image(data1, np.eye(4))
            path1 = os.path.join(self.temp_dir, f"perm_g1_{i}.nii.gz")
            nib.save(img1, path1)
            g1_paths.append(path1)

            # Group 2 (with effect)
            data2 = np.random.randn(*shape) + 1.0
            img2 = nib.Nifti1Image(data2, np.eye(4))
            path2 = os.path.join(self.temp_dir, f"perm_g2_{i}.nii.gz")
            nib.save(img2, path2)
            g2_paths.append(path2)

        # Use mock to avoid actual permutation test
        with unittest.mock.patch("nilearn.mass_univariate.permuted_ols") as mock_perm:
            # Mock the result
            neg_log_p = np.random.uniform(0, 3, shape)
            mock_perm.return_value = nib.Nifti1Image(neg_log_p, np.eye(4))

            result = tool.run(
                group1_paths=g1_paths,
                group2_paths=g2_paths,
                n_permutations=10,
                output_dir=self.temp_dir,
            )

            self.assertEqual(result["status"], "success")
            self.assertTrue(os.path.exists(result["data"]["p_map_path"]))


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility with original API."""

    def setUp(self):
        self.analyzer = StatisticalAnalyzer()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_legacy_group_format(self):
        """Test legacy group comparison format still works."""
        # Create dummy files
        g1_path = os.path.join(self.temp_dir, "g1.nii.gz")
        g2_path = os.path.join(self.temp_dir, "g2.nii.gz")

        for path in [g1_path, g2_path]:
            data = np.random.randn(5, 5, 5)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)

        # Legacy format
        request = {
            "analysis_type": "group_comparison",
            "data_paths": {"GroupA": [g1_path], "GroupB": [g2_path]},
            "group1": "GroupA",
            "group2": "GroupB",
            "output_dir": self.temp_dir,
        }

        result = self.analyzer.run_statistical_analysis(request)
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
