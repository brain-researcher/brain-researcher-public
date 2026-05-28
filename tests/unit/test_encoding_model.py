import unittest

import nibabel as nib
import numpy as np
import pandas as pd

from brain_researcher.core.analysis.encoding_model import EncodingModel


class TestEncodingModel(unittest.TestCase):
    def setUp(self):
        self.model = EncodingModel(cache_dir="test_cache")
        self.test_constructs = [
            {"constructs": ["decision making", "reward processing"], "confidence": 0.9},
            {"constructs": ["decision making", "cognitive control"], "confidence": 0.8},
        ]

    def test_prepare_design_matrix(self):
        """Test design matrix preparation"""
        X = self.model.prepare_design_matrix(self.test_constructs)
        self.assertIsInstance(X, pd.DataFrame)
        self.assertEqual(X.shape[0], len(self.test_constructs))
        self.assertIn("decision making", X.columns)

    def test_fit(self):
        """Test model fitting"""
        # Create dummy z-maps
        z_maps = []
        for i in range(2):
            data = np.random.randn(10, 10, 10)
            img = nib.Nifti1Image(data, np.eye(4))
            path = f"test_cache/z_map_{i}.nii.gz"
            nib.save(img, path)
            z_maps.append(path)

        results = self.model.fit(z_maps, self.test_constructs)

        self.assertIn("weight_maps", results)
        self.assertIn("cv_scores", results)
        self.assertIn("model_params", results)

    def test_predict(self):
        """Test prediction"""
        # Create dummy weight maps
        weight_maps = {}
        for construct in ["decision making", "reward processing"]:
            data = np.random.randn(10, 10, 10)
            img = nib.Nifti1Image(data, np.eye(4))
            path = f"test_cache/{construct}_weights.nii.gz"
            nib.save(img, path)
            weight_maps[construct] = path

        pred_map = self.model.predict(weight_maps, ["decision making"])
        self.assertIsInstance(pred_map, nib.Nifti1Image)

    def tearDown(self):
        """Clean up test files"""
        import shutil

        shutil.rmtree("test_cache", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
