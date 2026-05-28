import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging

import nibabel as nib
import nimare
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
        self.assertTrue(any("slices" in k or "glass" in k for k in vis.keys()))
        for v in vis.values():
            self.assertIsInstance(v, str)
            self.assertGreater(len(v), 0)

    def test_calculate_relevance_scores(self):
        if not self.has_data:
            self.skipTest(f"Neurosynth dataset not found at {self.dataset_path}")
        result = neurosynth_integration.get_neurosynth_mapping(self.test_keyword)
        scores = neurosynth_integration.calculate_relevance_scores(
            self.test_keyword, result["studies"]
        )
        self.assertIsInstance(scores, list)
        if scores:
            self.assertIsInstance(scores[0], float)

    def test_generate_activation_maps(self):
        if not self.has_data:
            self.skipTest(f"Neurosynth dataset not found at {self.dataset_path}")
        result = neurosynth_integration.get_neurosynth_mapping(self.test_keyword)
        if not result["coordinates"]:
            self.skipTest("No coordinates found for keyword.")
        try:
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
        self.assertIn("error_0", results)
        self.assertIsInstance(results["error_0"], str)


def test_visualize_activation_maps():
    """Test visualization of activation maps"""
    # Create mock activation map with non-zero values
    data = np.random.rand(20, 20, 20)
    # Add some structure to the data
    data[5:15, 5:15, 5:15] = data[5:15, 5:15, 5:15] * 2  # Create a "hot spot"
    affine = np.eye(4)
    activation_map = nib.Nifti1Image(data, affine)

    # Test visualization with default threshold
    results = neurosynth_integration.visualize_activation_maps([activation_map])
    assert isinstance(results, dict)
    assert "slices_0" in results
    assert "glass_0" in results
    assert "3d_0" in results

    # Test visualization with custom threshold
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map], threshold=2.0
    )
    assert isinstance(results, dict)
    assert "slices_0" in results
    assert "glass_0" in results
    assert "3d_0" in results

    # Test multiple activation maps
    activation_map2 = nib.Nifti1Image(np.random.rand(20, 20, 20), affine)
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map, activation_map2]
    )
    assert isinstance(results, dict)
    assert "slices_0" in results
    assert "slices_1" in results
    assert "glass_0" in results
    assert "glass_1" in results
    assert "3d_0" in results
    assert "3d_1" in results

    # Test error handling with invalid input
    results = neurosynth_integration.visualize_activation_maps([])
    assert isinstance(results, dict)
    assert len(results) == 0

    # Test error handling with invalid threshold
    results = neurosynth_integration.visualize_activation_maps(
        [activation_map], threshold=-1
    )
    assert isinstance(results, dict)
    assert "error_0" in results


if __name__ == "__main__":
    unittest.main()
