"""
Test Node Label Linker

Comprehensive tests for the NodeLabelLinker utility including:
- Basic matching functionality
- Edge creation with various thresholds
- Duplicate edge prevention
- Error handling and fallback behavior
"""

import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.core.ingestion.utils.label_embedder import EmbeddingBatch
from brain_researcher.services.neurokg.utils.matching_profile import (
    MatchingProfile,
    NormalizationRules,
)
from brain_researcher.services.neurokg.utils.node_label_linker import NodeLabelLinker


@contextmanager
def patch_sentence_transformer():
    """Patch all SentenceTransformer access points used by NodeLabelLinker."""
    target = "brain_researcher.core.ingestion.utils.label_embedder.SentenceTransformer"
    linker_target = "brain_researcher.services.neurokg.utils.node_label_linker"
    with patch(target) as mock_model:
        with patch(f"{linker_target}.SentenceTransformer", mock_model):
            yield mock_model


class DummyDB:
    """Mock database for testing."""

    def __init__(self):
        self.created = []
        self.nodes = {}

    def create_relationship(self, start, end, rel_type, props):
        """Mock relationship creation."""
        self.created.append((start, end, rel_type, props))
        return True

    def find_relationships(self, start_node=None, end_node=None, rel_type=None):
        """Mock relationship finding."""
        return [
            r
            for r in self.created
            if (start_node is None or r[0] == start_node)
            and (end_node is None or r[1] == end_node)
            and (rel_type is None or r[2] == rel_type)
        ]

    def find_nodes(self, labels=None, properties=None):
        """Mock node finding."""
        results = []
        for node_id, (node_labels, node_props) in self.nodes.items():
            if labels and labels not in node_labels:
                continue
            if properties:
                match = all(node_props.get(k) == v for k, v in properties.items())
                if not match:
                    continue
            results.append((node_id, node_props))
        return results


class TestNodeLabelLinker(unittest.TestCase):
    """Test cases for NodeLabelLinker."""

    def setUp(self):
        """Set up test fixtures."""
        self.db = DummyDB()

    def test_basic_embedding_matching(self):
        """Test basic matching using embeddings."""
        nodes_a = [("a1", {"name": "working memory"})]
        nodes_b = [("b1", {"name": "working memory"})]

        with patch_sentence_transformer() as mock_model:
            # Mock the model to return identical embeddings
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            inst.encode.side_effect = [
                np.array([[1.0, 0.0]], dtype=np.float32),  # nodes_a
                np.array([[1.0, 0.0]], dtype=np.float32),  # nodes_b
            ]
            mock_model.return_value = inst

            linker = NodeLabelLinker(self.db)
            created = linker.create_maps_to_edges(nodes_a, nodes_b, embed_threshold=0.5)

        self.assertEqual(created, 1)
        self.assertEqual(len(self.db.created), 1)

        # Check relationship properties
        _, _, rel_type, props = self.db.created[0]
        self.assertEqual(rel_type, "MAPS_TO")
        self.assertIn("confidence", props)
        self.assertEqual(props["method"], "embedding")
        self.assertIn("created_at", props)

    def test_fuzzy_matching_fallback(self):
        """Test fallback to fuzzy matching when embeddings unavailable."""
        nodes_a = [("a1", {"name": "n-back task"})]
        nodes_b = [("b1", {"name": "n back task"})]  # Slightly different

        # Test without embeddings
        with patch(
            "brain_researcher.services.neurokg.utils.node_label_linker.EMBEDDINGS_AVAILABLE",
            False,
        ):
            linker = NodeLabelLinker(self.db)
            created = linker.create_maps_to_edges(nodes_a, nodes_b, fuzzy_threshold=80)

        self.assertEqual(created, 1)
        props = self.db.created[0][3]
        self.assertEqual(props["method"], "fuzzy")

    def test_multiple_node_matching(self):
        """Test matching multiple nodes."""
        nodes_a = [
            ("a1", {"name": "working memory"}),
            ("a2", {"name": "attention"}),
            ("a3", {"name": "executive control"}),
        ]
        nodes_b = [
            ("b1", {"name": "attention"}),
            ("b2", {"name": "working memory"}),
            ("b3", {"name": "visual processing"}),
        ]

        with patch_sentence_transformer() as mock_model:
            # Mock embeddings - make working memory and attention match
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            inst.encode.side_effect = [
                # Embeddings for nodes_a
                np.array(
                    [
                        [1.0, 0.0, 0.0],  # working memory
                        [0.0, 1.0, 0.0],  # attention
                        [0.0, 0.0, 1.0],  # executive control
                    ],
                    dtype=np.float32,
                ),
                # Embeddings for nodes_b
                np.array(
                    [
                        [0.0, 1.0, 0.0],  # attention
                        [1.0, 0.0, 0.0],  # working memory
                        [0.0, 0.0, 0.0],  # visual processing
                    ],
                    dtype=np.float32,
                ),
            ]
            mock_model.return_value = inst

            linker = NodeLabelLinker(self.db)
            created = linker.create_maps_to_edges(nodes_a, nodes_b, embed_threshold=0.9)

        self.assertEqual(created, 2)

        # Check that correct pairs were matched
        created_pairs = [(r[0], r[1]) for r in self.db.created]
        self.assertIn(("a1", "b2"), created_pairs)  # working memory
        self.assertIn(("a2", "b1"), created_pairs)  # attention

    def test_skip_existing_edges(self):
        """Test skipping existing MAPS_TO edges."""
        # Pre-create an edge
        self.db.create_relationship(
            "a1", "b1", "MAPS_TO", {"method": "embedding", "confidence": 1.0}
        )

        nodes_a = [("a1", {"name": "alpha"})]
        nodes_b = [("b1", {"name": "alpha"})]

        with patch_sentence_transformer() as mock_model:
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            inst.encode.side_effect = [
                np.array([[1.0, 0.0]], dtype=np.float32),
                np.array([[1.0, 0.0]], dtype=np.float32),
            ]
            mock_model.return_value = inst

            linker = NodeLabelLinker(self.db)
            created = linker.create_maps_to_edges(
                nodes_a, nodes_b, embed_threshold=0.5, skip_existing=True
            )

        self.assertEqual(created, 0)
        self.assertEqual(len(self.db.created), 1)  # Only the pre-existing edge

    def test_label_extraction(self):
        """Test label extraction from various property names."""
        test_cases = [
            ({"name": "test"}, "test"),
            ({"label": "test"}, "test"),
            ({"title": "test"}, "test"),
            ({"abbreviation": "test"}, "test"),
            ({"task_name": "test"}, "test"),
            ({"concept_name": "test"}, "test"),
            ({}, ""),  # No suitable property
        ]

        for props, expected in test_cases:
            result = NodeLabelLinker._get_label(props)
            self.assertEqual(result, expected)

    def test_empty_node_lists(self):
        """Test handling of empty node lists."""
        linker = NodeLabelLinker(self.db)

        # Empty source A
        created = linker.create_maps_to_edges([], [("b1", {"name": "test"})])
        self.assertEqual(created, 0)

        # Empty source B
        created = linker.create_maps_to_edges([("a1", {"name": "test"})], [])
        self.assertEqual(created, 0)

        # Both empty
        created = linker.create_maps_to_edges([], [])
        self.assertEqual(created, 0)

    def test_nodes_without_labels(self):
        """Test handling of nodes without valid labels."""
        nodes_a = [
            ("a1", {}),  # No label
            ("a2", {"other_prop": "value"}),  # No recognized label property
        ]
        nodes_b = [("b1", {"name": "test"})]

        linker = NodeLabelLinker(self.db)
        created = linker.create_maps_to_edges(nodes_a, nodes_b)
        self.assertEqual(created, 0)

    def test_faiss_indexing(self):
        """Test FAISS indexing for large datasets."""
        # Create many nodes
        nodes_a = [(f"a{i}", {"name": f"concept_{i}"}) for i in range(10)]
        nodes_b = [
            (f"b{i}", {"name": f"concept_{i}"}) for i in range(150)
        ]  # > 100 triggers FAISS

        with patch_sentence_transformer() as mock_model:
            # Mock embeddings
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            emb_a = np.random.randn(10, 384).astype(np.float32)
            emb_b = np.random.randn(150, 384).astype(np.float32)

            # Normalize
            emb_a = emb_a / np.linalg.norm(emb_a, axis=1, keepdims=True)
            emb_b = emb_b / np.linalg.norm(emb_b, axis=1, keepdims=True)

            inst.encode.side_effect = [emb_a, emb_b]
            mock_model.return_value = inst

            with patch(
                "brain_researcher.services.neurokg.utils.node_label_linker.faiss"
            ) as mock_faiss:
                # Mock FAISS index
                mock_index = Mock()
                mock_index.search.return_value = (
                    np.array([[0.95]] * 10),  # High similarities
                    np.arange(10).reshape(-1, 1),  # Match indices
                )
                mock_faiss.IndexHNSWFlat.return_value = mock_index

                linker = NodeLabelLinker(self.db)
                created = linker.create_maps_to_edges(
                    nodes_a, nodes_b, embed_threshold=0.9
                )

                # Verify FAISS was used
                mock_faiss.IndexHNSWFlat.assert_called_once()
                mock_index.add.assert_called_once()

    def test_additional_properties(self):
        """Test adding additional properties to relationships."""
        nodes_a = [("a1", {"name": "test"})]
        nodes_b = [("b1", {"name": "test"})]

        additional_props = {
            "source_a": "cognitive_atlas",
            "source_b": "neurosynth",
            "version": "1.0",
        }

        with patch_sentence_transformer() as mock_model:
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            inst.encode.side_effect = [
                np.array([[1.0, 0.0]], dtype=np.float32),
                np.array([[1.0, 0.0]], dtype=np.float32),
            ]
            mock_model.return_value = inst

            linker = NodeLabelLinker(self.db)
            created = linker.create_maps_to_edges(
                nodes_a, nodes_b, additional_props=additional_props
            )

        props = self.db.created[0][3]
        self.assertEqual(props["source_a"], "cognitive_atlas")
        self.assertEqual(props["source_b"], "neurosynth")
        self.assertEqual(props["version"], "1.0")

    def test_link_nodes_by_label(self):
        """Test convenience method for linking by node labels."""
        # Set up mock nodes in database
        self.db.nodes = {
            "c1": (["Concept"], {"name": "working memory", "source": "ca"}),
            "c2": (["Concept"], {"name": "attention", "source": "ca"}),
            "t1": (["Task"], {"name": "n-back", "source": "openneuro"}),
            "t2": (["Task"], {"name": "stroop", "source": "openneuro"}),
        }

        with patch_sentence_transformer() as mock_model:
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            # Return some embeddings
            inst.encode.return_value = np.random.randn(2, 384).astype(np.float32)
            mock_model.return_value = inst

            linker = NodeLabelLinker(self.db)
            created = linker.link_nodes_by_label(
                "Concept",
                "Task",
                source_a="ca",
                source_b="openneuro",
                embed_threshold=0.0,  # Accept all matches for test
            )

        # Should create some relationships
        self.assertGreater(created, 0)

        # Check that source information was added
        if self.db.created:
            props = self.db.created[0][3]
            self.assertEqual(props["source_label_a"], "Concept")
            self.assertEqual(props["source_label_b"], "Task")
            self.assertEqual(props["source_a"], "ca")
            self.assertEqual(props["source_b"], "openneuro")

    @patch.object(
        NodeLabelLinker,
        "_load_alias_map",
        return_value=({"nback": "n-back"}, {"n-back": ["n-back"]}),
    )
    def test_alias_canonicalization_promotes_embeddings(self, _mock_alias_map):
        """Ensure alias canonicalization feeds canonical labels into the embedder."""
        # Clear cached alias map if another test populated it.
        if hasattr(NodeLabelLinker, "_alias_cache"):
            delattr(NodeLabelLinker, "_alias_cache")

        nodes_a = [("a1", {"name": "nback"})]
        nodes_b = [("b1", {"name": "n-back"})]

        class RecordingEmbedder:
            def __init__(self):
                self.calls = []

            def compute_embeddings(self, labels_a, labels_b):
                self.calls.append((list(labels_a), list(labels_b)))
                emb_a = np.array([[1.0, 0.0]], dtype=np.float32)
                emb_b = np.array([[1.0, 0.0]], dtype=np.float32)
                mask = [True]
                return EmbeddingBatch(emb_a, mask, emb_b, mask, "test")

        linker = NodeLabelLinker(self.db)
        embedder = RecordingEmbedder()
        linker.embedder = embedder

        matches = linker.match_nodes(
            nodes_a,
            nodes_b,
            embed_threshold=0.9,
            fuzzy_threshold=0,
            use_faiss=False,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], "a1")
        self.assertEqual(matches[0][1], "b1")
        # Canonical label should have been passed to the embedder on both sides.
        self.assertTrue(embedder.calls)
        labels_a, labels_b = embedder.calls[0]
        self.assertEqual(labels_a, ["n-back"])
        self.assertEqual(labels_b, ["n-back"])

    @patch.object(NodeLabelLinker, "_load_alias_map", return_value=({}, {}))
    def test_build_faiss_index_uses_gpu_when_available(self, _mock_alias_map):
        """Verify that GPU indexing is preferred when FAISS reports GPU support."""
        if hasattr(NodeLabelLinker, "_alias_cache"):
            delattr(NodeLabelLinker, "_alias_cache")

        module_path = "brain_researcher.services.neurokg.utils.node_label_linker"

        with patch.dict(os.environ, {"NICLIP_USE_GPU": "1"}):
            with patch(f"{module_path}.FAISS_AVAILABLE", True):
                with patch(f"{module_path}.faiss") as mock_faiss:
                    mock_faiss.get_num_gpus.return_value = 1
                    mock_faiss.StandardGpuResources.return_value = Mock()
                    mock_cpu_index = Mock()
                    mock_gpu_index = Mock()
                    mock_faiss.IndexFlatIP.return_value = mock_cpu_index
                    mock_faiss.index_cpu_to_gpu.return_value = mock_gpu_index

                    linker = NodeLabelLinker(self.db)

                    embeddings = np.random.randn(10, 64).astype(np.float32)
                    index = linker._build_faiss_index(embeddings)

                    mock_faiss.StandardGpuResources.assert_called_once()
                    mock_faiss.index_cpu_to_gpu.assert_called_once()
                    mock_cpu_index.add.assert_not_called()
                    mock_gpu_index.add.assert_called_once_with(embeddings)
                    mock_faiss.IndexHNSWFlat.assert_not_called()
                    self.assertIs(index, mock_gpu_index)

    @patch.object(NodeLabelLinker, "_load_alias_map", return_value=({}, {}))
    def test_build_faiss_index_falls_back_to_cpu(self, _mock_alias_map):
        """GPU requests should fall back gracefully when no GPUs are available."""
        if hasattr(NodeLabelLinker, "_alias_cache"):
            delattr(NodeLabelLinker, "_alias_cache")

        module_path = "brain_researcher.services.neurokg.utils.node_label_linker"

        with patch.dict(os.environ, {"NICLIP_USE_GPU": "1"}):
            with patch(f"{module_path}.FAISS_AVAILABLE", True):
                with patch(f"{module_path}.faiss") as mock_faiss:
                    mock_faiss.get_num_gpus.return_value = 0
                    mock_faiss.StandardGpuResources.return_value = Mock()
                    mock_cpu_index = Mock()
                    mock_cpu_index.hnsw = Mock()
                    mock_faiss.IndexHNSWFlat.return_value = mock_cpu_index
                    mock_faiss.METRIC_INNER_PRODUCT = 42

                    linker = NodeLabelLinker(self.db)

                    embeddings = np.random.randn(5, 32).astype(np.float32)
                    index = linker._build_faiss_index(embeddings)

                    mock_faiss.IndexHNSWFlat.assert_called_once()
                    mock_cpu_index.add.assert_called_once()
                    self.assertIs(index, mock_cpu_index)

    def test_profile_provenance_hash_depends_on_profile_content(self):
        """MAPS_TO provenance hash should capture profile content changes."""
        linker = NodeLabelLinker(self.db)

        profile_a = MatchingProfile(
            name="default",
            entity_type="task",
            normalization=NormalizationRules(),
            alias_to_canonical={"nback": "n-back"},
            canonical_to_aliases={"n-back": ["n-back", "nback"]},
            fuzzy_threshold=85,
            embed_threshold=0.9,
        )
        profile_b = MatchingProfile(
            name="default",
            entity_type="task",
            normalization=NormalizationRules(),
            alias_to_canonical={"nback": "n-back"},
            canonical_to_aliases={"n-back": ["n-back", "nback"]},
            fuzzy_threshold=90,
            embed_threshold=0.9,
        )

        prov_a1 = linker._profile_provenance(profile_a)
        prov_a2 = linker._profile_provenance(profile_a)
        prov_b = linker._profile_provenance(profile_b)

        self.assertEqual(prov_a1["mapping_profile"], "default")
        self.assertEqual(
            prov_a1["mapping_profile_hash"], prov_a2["mapping_profile_hash"]
        )
        self.assertNotEqual(
            prov_a1["mapping_profile_hash"], prov_b["mapping_profile_hash"]
        )

    def test_additional_props_override_provenance_order(self):
        """additional_props should be the final override layer for edge properties."""
        nodes_a = [("a1", {"name": "working memory"})]
        nodes_b = [("b1", {"name": "working memory"})]
        additional_props = {
            "mapping_profile": "manual_profile",
            "mapping_profile_hash": "manual_hash",
            "method": "manual",
        }

        with patch_sentence_transformer() as mock_model:
            inst = Mock()
            inst.get_sentence_embedding_dimension.return_value = 384
            inst.encode.side_effect = [
                np.array([[1.0, 0.0]], dtype=np.float32),
                np.array([[1.0, 0.0]], dtype=np.float32),
            ]
            mock_model.return_value = inst

            linker = NodeLabelLinker(self.db)
            created = linker.create_maps_to_edges(
                nodes_a,
                nodes_b,
                embed_threshold=0.5,
                additional_props=additional_props,
            )

        self.assertEqual(created, 1)
        props = self.db.created[0][3]
        self.assertEqual(props["mapping_profile"], "manual_profile")
        self.assertEqual(props["mapping_profile_hash"], "manual_hash")
        self.assertEqual(props["method"], "manual")


if __name__ == "__main__":
    unittest.main()
