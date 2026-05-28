import json
import os
import sys
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

# import pdb; pdb.set_trace()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer

from brain_researcher.core.analysis.contrast_analysis import ContrastAnalyzer


class TestContrastAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = ContrastAnalyzer(output_dir="test_reports")
        self.test_constructs = [
            {"constructs": ["decision making", "reward processing"], "confidence": 0.9}
        ]

    def test_analyze_contrast(self):
        """Test single contrast analysis"""
        # Create dummy z-map
        data = np.random.randn(10, 10, 10)
        img = nib.Nifti1Image(data, np.eye(4))
        z_map = "test_reports/z_map.nii.gz"
        nib.save(img, z_map)

        report = self.analyzer.analyze_contrast(
            z_map=z_map,
            contrast_name="test_contrast",
            task_description="Test task",
            constructs=self.test_constructs,
        )

        self.assertIn("utility_score", report)
        self.assertIn("clusters", report)
        self.assertIn("plots", report)

    def test_analyze_dataset(self):
        """Test dataset analysis"""
        # Create dummy dataset
        dataset_path = Path("test_dataset")
        dataset_path.mkdir(exist_ok=True)

        contrast_dir = dataset_path / "test_contrast"
        contrast_dir.mkdir()

        # Create dummy files
        data = np.random.randn(10, 10, 10)
        img = nib.Nifti1Image(data, np.eye(4))
        nib.save(img, contrast_dir / "z_map.nii.gz")

        metadata = {"task_description": "Test task", "constructs": self.test_constructs}
        with open(contrast_dir / "metadata.json", "w") as f:
            json.dump(metadata, f)

        results = self.analyzer.analyze_dataset(str(dataset_path))

        self.assertIn("test_contrast", results)
        self.assertTrue((Path("test_reports") / "analysis_summary.json").exists())

    def test_get_significant_clusters(self):
        """Test cluster identification and statistics extraction"""
        # Create test data with known clusters
        data = np.zeros((10, 10, 10))

        # Positive cluster (2x2x2 = 8 voxels)
        data[2:4, 2:4, 2:4] = 5.0
        data[2, 2, 2] = 7.0  # peak value

        # Negative cluster (2x2x2 = 8 voxels)
        data[6:8, 6:8, 6:8] = -4.0
        data[6, 6, 6] = -6.0  # peak value

        # Small cluster that should be filtered out (< min_size)
        data[0, 0, 0] = 4.0
        data[0, 0, 1] = 3.5

        # Save as NIfTI image
        img = nib.Nifti1Image(data, np.eye(4))
        z_map_path = "test_reports/test_clusters.nii.gz"
        nib.save(img, z_map_path)

        # Test with threshold that includes both positive and negative clusters
        clusters = self.analyzer._get_significant_clusters(
            z_map_path, threshold=3.0, min_size=5
        )

        # Should find 2 clusters (small one filtered out)
        self.assertEqual(len(clusters), 2)

        # Check cluster properties
        for cluster in clusters:
            self.assertIn("index", cluster)
            self.assertIn("size", cluster)
            self.assertIn("peak_value", cluster)
            self.assertIn("peak_coords", cluster)
            self.assertIn("center_of_mass", cluster)
            self.assertEqual(cluster["size"], 8)  # Both clusters are 8 voxels
            self.assertGreaterEqual(abs(cluster["peak_value"]), 6.0)

        # Test with high threshold - should exclude all clusters
        clusters_high = self.analyzer._get_significant_clusters(
            z_map_path, threshold=8.0, min_size=5
        )
        self.assertEqual(len(clusters_high), 0)

        # Test with very small min_size - should include small cluster
        clusters_small = self.analyzer._get_significant_clusters(
            z_map_path, threshold=3.0, min_size=1
        )
        self.assertEqual(len(clusters_small), 3)

    def tearDown(self):
        """Clean up test files"""
        import shutil

        shutil.rmtree("test_reports", ignore_errors=True)
        shutil.rmtree("test_dataset", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

# Example documents
documents = [
    "decision making and reward processing",
    "visual perception and attention",
    "language comprehension and production",
]

# Convert documents to a document-term matrix
vectorizer = CountVectorizer()
X = vectorizer.fit_transform(documents)

# Fit LDA model
n_topics = 2
lda = LatentDirichletAllocation(n_components=n_topics, random_state=42)
lda.fit(X)

# Display top words for each topic
n_top_words = 5
feature_names = vectorizer.get_feature_names_out()
for topic_idx, topic in enumerate(lda.components_):
    top_features = [feature_names[i] for i in topic.argsort()[: -n_top_words - 1 : -1]]
    print(f"Topic #{topic_idx + 1}: {', '.join(top_features)}")

# Transform documents to topic distribution
topic_distributions = lda.transform(X)
print("Document-topic distributions:")
print(topic_distributions)
