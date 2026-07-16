import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging

import nibabel as nib
import numpy as np
import pandas as pd

from brain_researcher.core.analysis import neurosynth_integration

logger = logging.getLogger(__name__)


class TestNeurosynthIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset_path = os.path.join(
            "data", "neurosynth_nimare", "neurosynth_dataset_v7.pkl"
        )
        cls.has_data = os.path.exists(cls.dataset_path)
        cls.test_keyword = "fear"

    def test_get_neurosynth_mapping(self):
        if not self.has_data:
            self.skipTest(f"Neurosynth dataset not found at {self.dataset_path}")
        result = neurosynth_integration.get_neurosynth_mapping(self.test_keyword)
        self.assertIsInstance(result, dict)
        self.assertIn("keyword", result)
        self.assertIn(self.test_keyword, result["keyword"])
        self.assertIn("activation_maps", result)
        self.assertIn("coordinate_density_maps", result)
        self.assertEqual(result["analysis_semantics"], "descriptive_coordinate_density")
        self.assertFalse(result["inferential_statistics"])
        self.assertIn("coordinates", result)
        self.assertIn("studies", result)
        self.assertIn("scores", result)

    def test_visualize_activation_maps(self):
        if not self.has_data:
            self.skipTest(f"Neurosynth dataset not found at {self.dataset_path}")
        result = neurosynth_integration.get_neurosynth_mapping(self.test_keyword)
        if not result["activation_maps"]:
            self.skipTest("No activation maps generated for keyword.")
        vis = neurosynth_integration.visualize_activation_maps(
            result["activation_maps"], threshold=3.0
        )
        self.assertIsInstance(vis, dict)
        self.assertEqual(vis["n_plots"], len(result["activation_maps"]))
        self.assertFalse(vis["inferential_statistics"])
        self.assertTrue(all(Path(path).is_file() for path in vis["plots"]))

    def test_calculate_relevance_scores(self):
        if not self.has_data:
            self.skipTest(f"Neurosynth dataset not found at {self.dataset_path}")
        result = neurosynth_integration.get_neurosynth_mapping(self.test_keyword)
        scores = neurosynth_integration.calculate_relevance_scores(
            self.test_keyword,
            [result.get("term_used", self.test_keyword)],
            [1.0],
        )
        self.assertIsInstance(scores, dict)

    def test_generate_activation_maps(self):
        if not self.has_data:
            self.skipTest(f"Neurosynth dataset not found at {self.dataset_path}")
        result = neurosynth_integration.get_neurosynth_mapping(self.test_keyword)
        if not result["coordinates"]:
            self.skipTest("No coordinates found for keyword.")
        try:
            import nimare

            coords_df = pd.DataFrame(result["coordinates"], columns=["x", "y", "z"])
            coords_df["id"] = "dummy"
            activation_map = nimare.meta.kernel.ALEKernel().transform(coords_df)
            result["activation_maps"].append(activation_map)
        except Exception as e:
            logger.error(f"Failed to generate activation map: {e}")

    def test_visualize_activation_maps_debug(self):
        """Debug test for visualization with negative threshold"""
        # Create mock activation map
        data = np.random.rand(20, 20, 20)
        data[5:15, 5:15, 5:15] = data[5:15, 5:15, 5:15] * 2
        affine = np.eye(4)
        activation_map = nib.Nifti1Image(data, affine)

        # Test with negative threshold
        results = neurosynth_integration.visualize_activation_maps(
            [activation_map], threshold=-1
        )
        print("\nDebug Results:")
        print(f"Keys in results: {list(results.keys())}")
        print(f"Results content: {results}")

        # Add assertions
        self.assertIsInstance(results, dict)
        self.assertIn("error", results)
        self.assertIn("non-negative", results["error"])


def test_visualize_activation_maps(tmp_path):
    """Descriptive visualization returns real PNG paths and semantics."""
    # Create mock activation map with non-zero values
    data = np.random.rand(20, 20, 20)
    # Add some structure to the data
    data[5:15, 5:15, 5:15] = data[5:15, 5:15, 5:15] * 2  # Create a "hot spot"
    affine = np.eye(4)
    activation_map = nib.Nifti1Image(data, affine)

    # Test visualization with default threshold
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map], output_dir=tmp_path
    )
    assert isinstance(results, dict)
    assert results["n_plots"] == 1
    assert results["inferential_statistics"] is False
    assert Path(results["plots"][0]).is_file()

    # Test visualization with custom threshold
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map], threshold=2.0, output_dir=tmp_path
    )
    assert results["display_threshold"] == 2.0
    assert results["threshold_semantics"] == (
        "absolute_display_threshold_in_map_native_units"
    )

    # Test multiple activation maps
    activation_map2 = nib.Nifti1Image(np.random.rand(20, 20, 20), affine)
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map, activation_map2], output_dir=tmp_path
    )
    assert results["n_plots"] == 2
    assert all(Path(path).is_file() for path in results["plots"])

    # Test error handling with invalid input
    results = neurosynth_integration.visualize_activation_maps([], output_dir=tmp_path)
    assert results["plots"] == []
    assert results["n_plots"] == 0

    # Test error handling with invalid threshold
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map], threshold=-1, output_dir=tmp_path
    )
    assert "non-negative" in results["error"]


if __name__ == "__main__":
    unittest.main()
