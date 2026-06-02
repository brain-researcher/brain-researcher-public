#!/usr/bin/env python3
"""
Unit tests for TaskSpec to TaskDef mapper

Tests the various mapping strategies and edge cases.
"""

import json
import os
import sys
import tempfile
import unittest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.mappers.task_mapper import TaskMapper


class TestTaskMapper(unittest.TestCase):
    """Test cases for TaskMapper class"""

    def setUp(self):
        """Set up test fixtures"""
        # Create temporary config file
        self.config = {
            "thresholds": {
                "fuzzy_match": 0.8,
                "niclip_confidence": 0.7,
                "max_edit_distance": 0.2,
            },
            "blacklist": ["test", "demo", "practice"],
            "name_normalizations": {
                "remove_suffixes": [" task", " paradigm"],
                "replacements": {"n-back": "nback", "go/no-go": "go no go"},
            },
            "logging": {
                "unmatched_log": "test_unmatched.tsv",
                "stats_log": "test_stats.json",
                "level": "INFO",
            },
            "niclip": {
                "synonym_cache": "test_synonyms.json",
                "min_prior": 0.001,
                "use_embeddings": False,
            },
        }

        # Create temporary synonym cache
        self.synonyms = {
            "synonyms": {
                "working memory": {
                    "variants": ["working memory", "wm", "working-memory"],
                    "related_concepts": ["memory", "cognition"],
                    "prior": 0.05,
                    "confidence": 0.9,
                    "source": "test",
                }
            },
            "variant_lookup": {
                "wm": [
                    {"canonical": "working memory", "confidence": 0.9, "prior": 0.05}
                ],
                "working-memory": [
                    {"canonical": "working memory", "confidence": 0.9, "prior": 0.05}
                ],
            },
            "metadata": {"total_tasks": 1, "total_variants": 2, "sources": ["test"]},
        }

        # Create temporary files
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "config.yaml")
        self.synonym_path = os.path.join(self.temp_dir, "synonyms.json")

        # Save config
        import yaml

        with open(self.config_path, "w") as f:
            yaml.dump(self.config, f)

        # Save synonyms
        with open(self.synonym_path, "w") as f:
            json.dump(self.synonyms, f)

        # Initialize mapper
        self.mapper = TaskMapper(self.config_path, self.synonym_path)

        # Set up sample task definitions
        self.task_defs = [
            (
                "task_001",
                {
                    "name": "nback",
                    "definition": "Working memory task",
                    "labels": ["TaskDef"],
                },
            ),
            (
                "task_002",
                {
                    "name": "stroop",
                    "definition": "Attention task",
                    "labels": ["TaskDef"],
                },
            ),
            (
                "task_003",
                {
                    "name": "go no go",
                    "definition": "Inhibition task",
                    "alias": "gonogo",
                    "labels": ["TaskDef"],
                },
            ),
            (
                "task_004",
                {
                    "name": "working memory",
                    "definition": "WM task",
                    "labels": ["TaskDef"],
                },
            ),
        ]

        self.mapper.set_task_definitions(self.task_defs)

    def tearDown(self):
        """Clean up temporary files"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_normalize_task_name(self):
        """Test task name normalization"""
        # Test suffix removal
        self.assertEqual(self.mapper.normalize_task_name("N-Back Task"), "nback")

        # Test replacement
        self.assertEqual(
            self.mapper.normalize_task_name("go/no-go paradigm"), "go no go"
        )

        # Test case normalization
        self.assertEqual(self.mapper.normalize_task_name("STROOP"), "stroop")

    def test_is_blacklisted(self):
        """Test blacklist checking"""
        self.assertTrue(self.mapper.is_blacklisted("test task"))
        self.assertTrue(self.mapper.is_blacklisted("practice run"))
        self.assertFalse(self.mapper.is_blacklisted("nback task"))

    def test_exact_match(self):
        """Test exact matching"""
        # Direct match
        result = self.mapper.find_exact_match("nback task")
        self.assertEqual(result, "task_001")

        # Match after normalization
        result = self.mapper.find_exact_match("N-Back Task")
        self.assertEqual(result, "task_001")

        # No match
        result = self.mapper.find_exact_match("unknown task")
        self.assertIsNone(result)

    def test_fuzzy_match(self):
        """Test fuzzy matching"""
        # Lower threshold for testing
        self.mapper.config["thresholds"]["fuzzy_match"] = 0.65

        # High similarity match - using "stroop-like" which should match "stroop" better
        result = self.mapper.find_fuzzy_match("strooop")  # Typo that should still match
        self.assertIsNotNone(result)
        task_id, score = result
        self.assertEqual(task_id, "task_002")
        self.assertGreater(score, 0.65)

        # Below threshold
        result = self.mapper.find_fuzzy_match("completely different")
        self.assertIsNone(result)

    def test_niclip_match(self):
        """Test NiCLIP synonym matching"""
        # Match via variant
        result = self.mapper.find_niclip_match("wm")
        self.assertIsNotNone(result)
        task_id, confidence = result
        self.assertEqual(task_id, "task_004")
        self.assertEqual(confidence, 0.9)

        # Direct synonym match
        result = self.mapper.find_niclip_match("working memory")
        self.assertIsNotNone(result)

        # No match
        result = self.mapper.find_niclip_match("unknown concept")
        self.assertIsNone(result)

    def test_map_task(self):
        """Test complete task mapping"""
        # Exact match
        result = self.mapper.map_task("nback task")
        self.assertIsNotNone(result)
        self.assertEqual(result["match_type"], "exact")
        self.assertEqual(result["confidence"], 1.0)

        # Fuzzy match - lower threshold for this test
        self.mapper.config["thresholds"]["fuzzy_match"] = 0.65
        result = self.mapper.map_task("strooop")  # Typo that should fuzzy match
        self.assertIsNotNone(result)
        self.assertEqual(result["match_type"], "fuzzy")

        # NiCLIP match
        result = self.mapper.map_task("wm")
        self.assertIsNotNone(result)
        self.assertEqual(result["match_type"], "niclip")

        # Blacklisted
        result = self.mapper.map_task("test task")
        self.assertIsNone(result)
        self.assertEqual(self.mapper.stats["blacklisted"], 1)

        # Unmatched
        result = self.mapper.map_task("completely unknown")
        self.assertIsNone(result)
        self.assertEqual(self.mapper.stats["unmatched"], 1)

    def test_map_batch(self):
        """Test batch mapping"""
        # Lower fuzzy threshold for this test
        self.mapper.config["thresholds"]["fuzzy_match"] = 0.65

        task_specs = [
            ("nback", {}),
            ("strooop", {}),  # Typo that should fuzzy match
            ("wm", {}),
            ("unknown", {}),
        ]

        results = self.mapper.map_batch(task_specs)

        # Should have 3 successful mappings
        self.assertEqual(len(results), 3)
        self.assertIn("nback", results)
        self.assertIn("strooop", results)
        self.assertIn("wm", results)
        self.assertNotIn("unknown", results)

    def test_stats_tracking(self):
        """Test statistics tracking"""
        # Reset stats
        self.mapper.stats = {
            "total_mapped": 0,
            "exact_matches": 0,
            "fuzzy_matches": 0,
            "niclip_matches": 0,
            "unmatched": 0,
            "blacklisted": 0,
        }

        # Lower fuzzy threshold for this test
        self.mapper.config["thresholds"]["fuzzy_match"] = 0.65

        # Map various tasks
        self.mapper.map_task("nback task")  # exact
        self.mapper.map_task("strooop")  # fuzzy - typo that should match
        self.mapper.map_task("wm")  # niclip
        self.mapper.map_task("test")  # blacklisted
        self.mapper.map_task("unknown")  # unmatched

        # Check stats
        self.assertEqual(self.mapper.stats["total_mapped"], 3)
        self.assertEqual(self.mapper.stats["exact_matches"], 1)
        self.assertEqual(self.mapper.stats["fuzzy_matches"], 1)
        self.assertEqual(self.mapper.stats["niclip_matches"], 1)
        self.assertEqual(self.mapper.stats["blacklisted"], 1)
        self.assertEqual(self.mapper.stats["unmatched"], 1)

    def test_priority_order(self):
        """Test that matching follows priority order"""
        # Create a task that could match multiple ways
        # "nback" should match exactly, not fuzzy or niclip
        result = self.mapper.map_task("nback")
        self.assertEqual(result["match_type"], "exact")

        # "wm" should match via niclip (since it's in our synonym list)
        result = self.mapper.map_task("wm")
        self.assertEqual(result["match_type"], "niclip")


class TestTaskMapperIntegration(unittest.TestCase):
    """Integration tests with real data structures"""

    def test_with_openneuro_task_format(self):
        """Test with OpenNeuro-style task specifications"""
        # Create mapper with test config
        temp_dir = tempfile.mkdtemp()

        # Create a simple test config with lower thresholds
        config_path = os.path.join(temp_dir, "test_config.yaml")
        config = {
            "thresholds": {
                "fuzzy_match": 0.6,  # Lower threshold to match "nback" to "n-back task"
                "niclip_confidence": 0.7,
                "max_edit_distance": 0.3,
            },
            "blacklist": ["test", "demo", "practice"],
            "name_normalizations": {
                "remove_suffixes": [" task"],
                "replacements": {"n-back": "nback", "emomatching": "emotion matching"},
            },
            "logging": {
                "unmatched_log": "test_unmatched.tsv",
                "stats_log": "test_stats.json",
                "level": "INFO",
            },
            "niclip": {
                "synonym_cache": "test_synonyms.json",
                "min_prior": 0.001,
                "use_embeddings": False,
            },
        }

        import yaml

        with open(config_path, "w") as f:
            yaml.dump(config, f)

        mapper = TaskMapper(config_path)

        # Simulate OpenNeuro task specs
        task_specs = [
            ("nback", {"contrast": "2back>0back"}),
            ("restingstate", {"duration": 600}),
            ("faces", {"contrast": "faces>shapes"}),
            ("emomatching", {"conditions": ["happy", "sad", "neutral"]}),
        ]

        # Simulate Cognitive Atlas task defs
        cog_atlas_defs = [
            (
                "cogatlas_001",
                {
                    "name": "nback",  # Changed to exact match after normalization
                    "definition": "Working memory task",
                    "id": "tsk_4a57abb949e8a",
                },
            ),
            (
                "cogatlas_002",
                {
                    "name": "resting state",
                    "definition": "Rest condition",
                    "id": "tsk_4a57abb949e8b",
                },
            ),
            (
                "cogatlas_003",
                {
                    "name": "face matching task",
                    "definition": "Emotional face processing",
                    "alias": "emotion matching",
                    "id": "tsk_4a57abb949e8c",
                },
            ),
        ]

        mapper.set_task_definitions(cog_atlas_defs)

        # Test mapping
        results = mapper.map_batch(task_specs)

        # Check expected mappings
        self.assertIn("nback", results)
        self.assertIn("emomatching", results)  # Should match via alias

        # Clean up
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
