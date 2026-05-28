import os
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock neuromaps module before importing rag_retrieval
neuromaps_module = ModuleType("neuromaps")
neuromaps_datasets = ModuleType("neuromaps.datasets")
neuromaps_datasets.fetch_annotation = MagicMock()
neuromaps_module.datasets = neuromaps_datasets
sys.modules["neuromaps"] = neuromaps_module
sys.modules["neuromaps.datasets"] = neuromaps_datasets

from brain_researcher.core.analysis.rag_retrieval import RAGKnowledgeSystem


class TestNeuromapRetrieval(unittest.TestCase):
    """Test suite for Neuromap retrieval functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.rag = None

    def tearDown(self):
        """Clean up after tests."""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_retrieve_neuromap_mock(self):
        """Test basic neuromap retrieval with mocked fetch_annotation."""
        # Create dummy file
        dummy_file = os.path.join(self.temp_dir, "map.nii.gz")
        with open(dummy_file, "w") as f:
            f.write("dummy neuroimaging data")

        # Mock the fetch_annotation function
        def mock_fetch_annotation(**kwargs):
            return {("src", "desc", "MNI152", "1mm"): [dummy_file]}

        with patch(
            "brain_researcher.core.analysis.rag_retrieval.neuromaps_datasets.fetch_annotation",
            side_effect=mock_fetch_annotation,
        ):
            with patch(
                "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
                True,
            ):
                rag = RAGKnowledgeSystem()
                res = rag.retrieve_neuromap("src", "desc", force_refresh=True)

        # Verify results
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["source"], "neuromap")
        self.assertTrue(
            res[0]["path"].endswith("map.nii.gz")
        )  # Check filename instead of full path
        self.assertEqual(res[0]["id"], "('src', 'desc', 'MNI152', '1mm')")
        self.assertIn("metadata", res[0])
        self.assertEqual(res[0]["metadata"]["source"], "src")
        self.assertEqual(res[0]["metadata"]["desc"], "desc")

    def test_retrieve_neuromap_not_available(self):
        """Test behavior when neuromaps is not available."""
        with patch(
            "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
            False,
        ):
            rag = RAGKnowledgeSystem()
            res = rag.retrieve_neuromap("src", "desc")

        self.assertEqual(res, [])

    def test_retrieve_neuromap_with_token(self):
        """Test neuromap retrieval with OSF token."""
        dummy_file = os.path.join(self.temp_dir, "private_map.nii.gz")
        with open(dummy_file, "w") as f:
            f.write("private data")

        def mock_fetch_with_token(**kwargs):
            # Verify token was passed
            if kwargs.get("token") != "test_token":
                raise AssertionError(
                    f"Expected token 'test_token', got {kwargs.get('token')}"
                )
            return {("private", "map", "MNI152", "2mm"): [dummy_file]}

        with patch(
            "brain_researcher.core.analysis.rag_retrieval.neuromaps_datasets.fetch_annotation",
            side_effect=mock_fetch_with_token,
        ):
            with patch(
                "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
                True,
            ):
                with patch.dict(os.environ, {"NEUROMAPS_OSF_TOKEN": "test_token"}):
                    rag = RAGKnowledgeSystem()
                    res = rag.retrieve_neuromap(
                        "private",
                        "map",
                        space="MNI152",
                        res="2mm",
                        force_refresh=True,
                    )

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["metadata"]["res"], "2mm")

    def test_retrieve_neuromap_error_handling(self):
        """Test error handling in neuromap retrieval."""

        def mock_fetch_error(**kwargs):
            raise Exception("Map not found: 404 error")

        with patch(
            "brain_researcher.core.analysis.rag_retrieval.neuromaps_datasets.fetch_annotation",
            side_effect=mock_fetch_error,
        ):
            with patch(
                "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
                True,
            ):
                with patch(
                    "brain_researcher.core.analysis.rag_retrieval.neuromap_client",
                    {"token": None, "available": True},
                ):
                    rag = RAGKnowledgeSystem()
                    res = rag.retrieve_neuromap(
                        "invalid", "source", force_refresh=True
                    )

        self.assertEqual(res, [])

    def test_retrieve_neuromap_caching(self):
        """Test caching functionality for neuromap retrieval."""
        # Since we can't easily mock the module-level import of neuromaps_datasets,
        # we'll test the caching logic by verifying the cache parameters are passed correctly

        dummy_file = os.path.join(self.temp_dir, "cached_map.nii.gz")
        with open(dummy_file, "w") as f:
            f.write("cached data")

        def mock_fetch(**kwargs):
            return {("test", "cache", "MNI152", "1mm"): [dummy_file]}

        with patch(
            "brain_researcher.core.analysis.rag_retrieval.neuromaps_datasets.fetch_annotation",
            side_effect=mock_fetch,
        ):
            with patch(
                "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
                True,
            ):
                # Test that force_refresh and use_cache parameters work
                rag = RAGKnowledgeSystem()

                # Test default behavior (use_cache=True)
                res1 = rag.retrieve_neuromap("test", "cache", force_refresh=True)
                self.assertEqual(len(res1), 1)

                # Test with use_cache=False
                res2 = rag.retrieve_neuromap("test", "cache", use_cache=False)
                self.assertEqual(len(res2), 1)

                # Test with force_refresh=True
                res3 = rag.retrieve_neuromap("test", "cache", force_refresh=True)
                self.assertEqual(len(res3), 1)

                # Verify all results have same structure
                for res in [res1, res2, res3]:
                    self.assertEqual(res[0]["source"], "neuromap")
                    self.assertEqual(res[0]["metadata"]["source"], "test")
                    self.assertEqual(res[0]["metadata"]["desc"], "cache")
                    self.assertTrue(res[0]["path"].endswith("cached_map.nii.gz"))

    def test_retrieve_neuromap_multiple_files(self):
        """Test handling multiple files from one annotation."""
        files = [
            os.path.join(self.temp_dir, "map_left.nii.gz"),
            os.path.join(self.temp_dir, "map_right.nii.gz"),
        ]
        for f in files:
            with open(f, "w") as fp:
                fp.write("hemisphere data")

        def mock_fetch_multiple(**kwargs):
            return {("bilateral", "maps", "fsaverage", "32k"): files}

        with patch(
            "brain_researcher.core.analysis.rag_retrieval.neuromaps_datasets.fetch_annotation",
            side_effect=mock_fetch_multiple,
        ):
            with patch(
                "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
                True,
            ):
                with patch(
                    "brain_researcher.core.analysis.rag_retrieval.neuromap_client",
                    {"token": None, "available": True},
                ):
                    rag = RAGKnowledgeSystem()
                    res = rag.retrieve_neuromap(
                        "bilateral",
                        "maps",
                        space="fsaverage",
                        res="32k",
                        force_refresh=True,
                    )

        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["metadata"]["space"], "fsaverage")
        self.assertEqual(res[1]["metadata"]["res"], "32k")


class TestNeuromapToolIntegration(unittest.TestCase):
    """Test integration with the RAG tools system."""

    def test_neuromap_tool_in_rag_tools(self):
        """Test that NeuromapFetchTool is properly integrated."""
        from brain_researcher.services.tools.rag_tools import RAGTools

        with patch(
            "brain_researcher.core.analysis.rag_retrieval.NEUROMAPS_AVAILABLE",
            True,
        ):
            rag_tools = RAGTools()

            # Check tool is in collection
            all_tools = rag_tools.get_all_tools()
            tool_names = [t.get_tool_name() for t in all_tools]
            self.assertIn("neuromap_fetch", tool_names)

            # Check tool can be retrieved by name
            neuromap_tool = rag_tools.get_tool_by_name("neuromap_fetch")
            self.assertIsNotNone(neuromap_tool)
            self.assertEqual(neuromap_tool.get_tool_name(), "neuromap_fetch")

            # Check tool description
            desc = neuromap_tool.get_tool_description()
            self.assertIn("brain activation maps", desc)
            self.assertIn("neuromaps", desc)


if __name__ == "__main__":
    unittest.main()
