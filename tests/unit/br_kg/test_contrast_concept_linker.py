#!/usr/bin/env python3
"""
Unit tests for Contrast to Concept linker

Tests the weight aggregation and edge creation logic.
"""

import os
import sys
import tempfile
import unittest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.mappers.contrast_concept_linker import (
    ContrastConceptLinker,
)


class TestContrastConceptLinker(unittest.TestCase):
    """Test cases for ContrastConceptLinker class"""

    def setUp(self):
        """Set up test fixtures"""
        # Create temporary ca_weights file
        self.temp_dir = tempfile.mkdtemp()
        self.ca_weights_path = os.path.join(
            self.temp_dir, "ca_task_concept_weights.tsv"
        )

        # Create sample CA weights data (TSV format expected by load_task_concept_weights)
        with open(self.ca_weights_path, "w") as f:
            f.write("task\tconcept\tweight\n")
            f.write("n-back task\tworking memory\t0.9\n")
            f.write("n-back task\texecutive control\t0.7\n")
            f.write("n-back task\tattention\t0.5\n")
            f.write("stroop task\tattention\t0.8\n")
            f.write("stroop task\tresponse inhibition\t0.6\n")
            f.write("stroop task\texecutive control\t0.5\n")
            f.write("face matching\tface recognition\t0.9\n")
            f.write("face matching\temotion\t0.6\n")
            f.write("face matching\tvisual perception\t0.4\n")

        # Initialize linker
        self.linker = ContrastConceptLinker(self.ca_weights_path)

        # Sample concept nodes (not used in new API but kept for reference)
        self.concept_nodes = [
            ("concept_wm", {"name": "working memory"}),
            ("concept_att", {"name": "attention"}),
            ("concept_exec", {"name": "executive control"}),
            ("concept_face", {"name": "face recognition"}),
            ("concept_emo", {"name": "emotion"}),
            ("concept_inhib", {"name": "response inhibition"}),
            ("concept_motor", {"name": "motor control"}),
            ("concept_vis", {"name": "visual perception"}),
        ]

    def tearDown(self):
        """Clean up temporary files"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_ca_weights(self):
        """Test loading of CA weights data"""
        self.assertIn("n-back task", self.linker.ca_weights)
        self.assertEqual(len(self.linker.ca_weights["n-back task"]), 3)
        self.assertEqual(self.linker.ca_weights["n-back task"]["working memory"], 0.9)

    def test_link_contrast(self):
        """Test single contrast linking"""
        # Create contrast with concepts
        contrast = {
            "contrast_id": "contrast_001",
            "task": "n-back task",
            "concepts": [
                {
                    "concept_id": "concept_wm",
                    "name": "working memory",
                    "llm_w": 0.8,
                    "pubmed_w": 0.6,
                },
                {
                    "concept_id": "concept_att",
                    "name": "attention",
                    "llm_w": 0.5,
                    "pubmed_w": 0.3,
                },
            ],
        }

        edges = self.linker.link_contrast(contrast)

        # Should create edges with multi-source weights
        self.assertGreaterEqual(len(edges), 2)

        # Check edge structure
        edge = edges[0]
        self.assertEqual(edge["start_node"], "contrast_001")
        self.assertEqual(edge["type"], "HAS_CONCEPT")
        self.assertIn("csv_w", edge["properties"])
        self.assertIn("llm_w", edge["properties"])
        self.assertIn("pubmed_w", edge["properties"])
        self.assertIn("sources", edge["properties"])

        # Check that CSV weights from CA are included
        wm_edge = next(e for e in edges if e["end_node"] == "concept_wm")
        self.assertEqual(wm_edge["properties"]["csv_w"], 0.9)  # From CA weights
        self.assertEqual(wm_edge["properties"]["llm_w"], 0.8)  # From contrast concepts

    def test_link_from_annotations(self):
        """Test batch processing from annotations"""
        annotations = [
            {
                "contrast_id": "contrast_001",
                "task": "n-back task",
                "concepts": [
                    {
                        "concept_id": "concept_wm",
                        "name": "working memory",
                        "llm_w": 0.8,
                        "pubmed_w": 0.6,
                    }
                ],
            },
            {
                "contrast_id": "contrast_002",
                "task": "stroop task",
                "concepts": [
                    {
                        "concept_id": "concept_att",
                        "name": "attention",
                        "llm_w": 0.7,
                        "pubmed_w": 0.5,
                    }
                ],
            },
        ]

        edges = self.linker.link_from_annotations(annotations)

        # Should have edges from both contrasts
        self.assertGreaterEqual(len(edges), 2)

        # Check stats
        self.assertEqual(self.linker.stats["total_contrasts"], 2)
        self.assertEqual(self.linker.stats["linked_contrasts"], 2)
        self.assertGreater(self.linker.stats["total_edges_created"], 0)

    def test_merge_weights(self):
        """Test weight merging from multiple sources"""
        contrast = {
            "task": "n-back task",
            "concepts": [
                {
                    "concept_id": "concept_exec",
                    "name": "executive control",
                    "llm_w": 0.6,
                    "pubmed_w": 0.4,
                }
            ],
        }

        weights = self.linker._merge_weights(contrast, "n-back task")

        # Should have executive control with weights from both CA and concepts
        self.assertIn("executive control", weights)
        self.assertEqual(weights["executive control"]["csv_w"], 0.7)  # From CA
        self.assertEqual(weights["executive control"]["llm_w"], 0.6)  # From concepts
        self.assertEqual(weights["executive control"]["pubmed_w"], 0.4)  # From concepts

    def test_task_matching(self):
        """Test task name matching functionality"""
        # Test caching
        self.linker._match_task("N-Back Task")
        self.linker._match_task("N-Back Task")

        # Should use cache on second call
        self.assertEqual(self.linker.stats["cache_hits"], 1)
        self.assertEqual(self.linker.stats["cache_misses"], 1)

    def test_stats_tracking(self):
        """Test statistics tracking"""
        # Reset stats
        self.linker.stats = {
            "total_contrasts": 0,
            "linked_contrasts": 0,
            "total_edges_created": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

        annotations = [
            {
                "contrast_id": "c1",
                "task": "n-back task",
                "concepts": [
                    {"concept_id": "concept_wm", "name": "working memory", "llm_w": 0.8}
                ],
            },
            {
                "contrast_id": "c2",
                "task": "stroop task",
                "concepts": [
                    {"concept_id": "concept_att", "name": "attention", "llm_w": 0.7}
                ],
            },
        ]

        self.linker.link_from_annotations(annotations)

        # Check stats
        self.assertEqual(self.linker.stats["total_contrasts"], 2)
        self.assertEqual(self.linker.stats["linked_contrasts"], 2)
        self.assertGreater(self.linker.stats["total_edges_created"], 0)

    def test_invalid_input_handling(self):
        """Test handling of invalid inputs"""
        # Invalid annotations format
        edges = self.linker.link_from_annotations("not a list")
        self.assertEqual(len(edges), 0)

        # Contrast without required fields
        contrast = {"task": "some task"}  # Missing contrast_id
        edges = self.linker.link_contrast(contrast)
        self.assertEqual(len(edges), 0)

    def test_duplicate_edge_prevention(self):
        """Test that duplicate edges are not created"""
        contrast = {
            "contrast_id": "contrast_001",
            "task": "n-back task",
            "concepts": [
                {
                    "concept_id": "concept_wm",
                    "name": "working memory",
                    "llm_w": 0.8,
                    "pubmed_w": 0.6,
                }
            ],
        }

        # Link the same contrast twice
        edges1 = self.linker.link_contrast(contrast)
        edges2 = self.linker.link_contrast(contrast)

        # Second call should not create any edges (duplicates prevented)
        self.assertGreater(len(edges1), 0)
        self.assertEqual(len(edges2), 0)

    def test_sources_list(self):
        """Test that sources list is correctly populated"""
        contrast = {
            "contrast_id": "contrast_001",
            "task": "n-back task",
            "concepts": [
                {
                    "concept_id": "concept_wm",
                    "name": "working memory",
                    "llm_w": 0.8,
                    "pubmed_w": 0.0,  # Zero weight
                }
            ],
        }

        edges = self.linker.link_contrast(contrast)

        # Check sources list only includes non-zero weights
        edge = edges[0]
        self.assertIn("csv", edge["properties"]["sources"])  # Has CA weight
        self.assertIn("llm", edge["properties"]["sources"])  # Has llm weight
        self.assertNotIn("pubmed", edge["properties"]["sources"])  # Zero weight


class TestContrastConceptIntegration(unittest.TestCase):
    """Integration tests with real-world scenarios"""

    def test_openneuro_style_annotations(self):
        """Test with OpenNeuro-style annotation format"""
        # Create temporary CA weights
        temp_dir = tempfile.mkdtemp()
        ca_weights_path = os.path.join(temp_dir, "ca_task_concept_weights.tsv")

        with open(ca_weights_path, "w") as f:
            f.write("task\tconcept\tweight\n")
            f.write("flanker task\tattention\t0.8\n")
            f.write("flanker task\tconflict monitoring\t0.7\n")
            f.write("flanker task\texecutive control\t0.6\n")
            f.write("emotion regulation\temotion\t0.9\n")
            f.write("emotion regulation\tcognitive control\t0.7\n")

        linker = ContrastConceptLinker(ca_weights_path)

        # OpenNeuro-style annotations
        annotations = [
            {
                "contrast_id": "ds000001_task-flanker_contrast-incongruent_vs_congruent",
                "task": "flanker task",
                "concepts": [
                    {
                        "concept_id": "c1",
                        "name": "attention",
                        "llm_w": 0.9,
                        "pubmed_w": 0.5,
                    },
                    {
                        "concept_id": "c3",
                        "name": "conflict monitoring",
                        "llm_w": 0.8,
                        "pubmed_w": 0.6,
                    },
                ],
            },
            {
                "contrast_id": "ds000002_task-emotion_contrast-negative_vs_neutral",
                "task": "emotion regulation",
                "concepts": [
                    {
                        "concept_id": "c2",
                        "name": "emotion",
                        "llm_w": 0.9,
                        "pubmed_w": 0.7,
                    }
                ],
            },
        ]

        edges = linker.link_from_annotations(annotations)

        # Should create edges with combined weights
        self.assertGreaterEqual(len(edges), 3)

        # Check that CA weights are included
        attention_edge = next(e for e in edges if e["end_node"] == "c1")
        self.assertEqual(attention_edge["properties"]["csv_w"], 0.8)

        # Clean up
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
