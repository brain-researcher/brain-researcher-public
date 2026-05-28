#!/usr/bin/env python3
"""
Comprehensive tests for PubMed task linking functionality
"""

import os
import sys
import tempfile
import unittest

# Add neurokg to path
neurokg_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, neurokg_path)

from brain_researcher.services.neurokg.etl.pubmed_task_linker_improved import (
    build_comprehensive_task_index,
    ingest_publication_with_tasks,
    match_task_advanced,
)
from brain_researcher.services.neurokg.etl.task_extraction import GENERIC_TASK_BLACKLIST, extract_tasks_from_metadata
from graph.graph_database import NeuroKGGraphDB


class TestTaskExtraction(unittest.TestCase):
    """Test task extraction functionality"""

    def test_extract_known_tasks(self):
        """Test extraction of known task patterns"""
        title = "Neural correlates of the Stroop task"
        abstract = "We used the n-back task and go/no-go task to study working memory."
        mesh_terms = ["Wisconsin Card Sorting Test", "Memory, Short-Term"]
        keywords = ["flanker task", "cognitive control"]

        tasks = extract_tasks_from_metadata(title, abstract, mesh_terms, keywords)

        # Should find multiple tasks
        self.assertIn("stroop task", [t.lower() for t in tasks])
        self.assertIn("n-back task", [t.lower() for t in tasks])
        self.assertIn("go/no-go task", [t.lower() for t in tasks])
        self.assertIn("flanker task", [t.lower() for t in tasks])
        # MeSH term gets "task" appended
        self.assertTrue(any("Wisconsin Card Sorting Test" in task for task in tasks))

    def test_filter_generic_tasks(self):
        """Test that generic task phrases are filtered out"""
        abstract = "During this task, the task was difficult. Each task required the task completion."

        tasks = extract_tasks_from_metadata("", abstract, [], [])

        # Should not include generic phrases
        for task in tasks:
            self.assertNotIn(task.lower(), GENERIC_TASK_BLACKLIST)

    def test_empty_input(self):
        """Test handling of empty input"""
        tasks = extract_tasks_from_metadata("", "", [], [])
        self.assertEqual(len(tasks), 0)

    def test_mesh_term_conversion(self):
        """Test that MeSH terms with slashes are cleaned"""
        mesh_terms = ["Stroop/Test", "Memory/Working"]

        tasks = extract_tasks_from_metadata("", "", mesh_terms, [])

        # Should clean up slashes
        self.assertTrue(any("Stroop Test" in task for task in tasks))


class TestTaskIndexBuilding(unittest.TestCase):
    """Test task index building from multiple node types"""

    def setUp(self):
        """Set up test database with various task nodes"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.db = NeuroKGGraphDB(self.temp_db.name)

        # Create different types of task nodes
        self.db.create_node("Task", {"name": "working memory task"}, node_id="t1")
        self.db.create_node("TaskDef", {"task": "n-back task"}, node_id="td1")
        self.db.create_node("TaskSpec", {"task_name": "stroop task"}, node_id="ts1")
        # Duplicate normalized name to test handling
        self.db.create_node("Task", {"name": "Working Memory Task"}, node_id="t2")

    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        os.unlink(self.temp_db.name)

    def test_build_comprehensive_index(self):
        """Test building index from all task node types"""
        index = build_comprehensive_task_index(self.db)

        # Should include all unique normalized names
        self.assertIn("working memory task", index)
        self.assertIn("n back task", index)  # normalized
        self.assertIn("stroop task", index)

        # Should have correct node IDs
        self.assertEqual(index["working memory task"]["id"], "t1")  # First one wins
        self.assertEqual(index["n back task"]["id"], "td1")
        self.assertEqual(index["stroop task"]["id"], "ts1")

        # Should track label types
        self.assertEqual(index["working memory task"]["label"], "Task")
        self.assertEqual(index["n back task"]["label"], "TaskDef")
        self.assertEqual(index["stroop task"]["label"], "TaskSpec")


class TestTaskMatching(unittest.TestCase):
    """Test task matching functionality"""

    def setUp(self):
        """Set up test index"""
        self.index = {
            "working memory task": {
                "id": "t1",
                "name": "working memory task",
                "original_name": "Working Memory Task",
            },
            "n back task": {
                "id": "t2",
                "name": "n-back task",
                "original_name": "N-Back Task",
            },
            "stroop task": {
                "id": "t3",
                "name": "stroop task",
                "original_name": "Stroop Task",
            },
        }

    def test_exact_match(self):
        """Test exact matching after normalization"""
        task_id, score, method = match_task_advanced("Working Memory Task", self.index)
        self.assertEqual(task_id, "t1")
        self.assertEqual(score, 1.0)
        self.assertEqual(method, "exact")

    def test_fuzzy_match(self):
        """Test fuzzy matching with SequenceMatcher"""
        # Close but not exact
        task_id, score, method = match_task_advanced(
            "wroking memory task", self.index, threshold=0.8
        )
        self.assertEqual(task_id, "t1")
        self.assertGreater(score, 0.8)
        self.assertEqual(method, "sequence")

    def test_no_match(self):
        """Test when no match is found"""
        task_id, score, method = match_task_advanced(
            "completely different task", self.index, threshold=0.9
        )
        self.assertIsNone(task_id)
        self.assertEqual(score, 0.0)
        self.assertEqual(method, "none")

    def test_empty_input(self):
        """Test empty input handling"""
        task_id, score, method = match_task_advanced("", self.index)
        self.assertIsNone(task_id)
        self.assertEqual(score, 0.0)
        self.assertEqual(method, "none")


class TestPublicationIngestion(unittest.TestCase):
    """Test publication ingestion with task linking"""

    def setUp(self):
        """Set up test database and index"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.db = NeuroKGGraphDB(self.temp_db.name)

        # Create some task nodes
        self.db.create_node("Task", {"name": "working memory task"}, node_id="t1")
        self.db.create_node("Task", {"name": "stroop task"}, node_id="t2")

        # Build index
        self.index = build_comprehensive_task_index(self.db)

    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        os.unlink(self.temp_db.name)

    def test_ingest_publication_with_matching_tasks(self):
        """Test ingesting publication that matches existing tasks"""
        paper = {
            "pmid": "12345678",
            "title": "Working memory task performance in healthy adults",
            "abstract": "We studied the Stroop task to examine cognitive control.",
            "authors": [
                {"first_name": "John", "last_name": "Smith"},
                {"first_name": "Jane", "last_name": "Doe"},
            ],
            "tasks": ["working memory task", "Stroop Task", "unknown task"],
        }

        pub_id, stats = ingest_publication_with_tasks(self.db, paper, self.index)

        # Verify publication was created
        pubs = self.db.find_nodes("Study")
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0][1]["pmid"], "12345678")

        # Verify relationships were created
        rels = self.db.find_relationships(rel_type="USES_PARADIGM")
        self.assertEqual(len(rels), 2)  # Should match 2 out of 3 tasks

        # Verify statistics
        self.assertEqual(stats["tasks_extracted"], 3)
        self.assertEqual(stats["tasks_matched"], 2)
        self.assertEqual(stats["relationships_created"], 2)
        self.assertEqual(len(stats["unmatched_tasks"]), 1)
        self.assertIn("unknown task", stats["unmatched_tasks"])

    def test_ingest_publication_no_tasks(self):
        """Test ingesting publication with no tasks"""
        paper = {
            "pmid": "87654321",
            "title": "A theoretical review",
            "abstract": "This paper reviews theories.",
            "authors": ["Smith, J.", "Doe, J."],  # Test string format
            "tasks": [],
        }

        pub_id, stats = ingest_publication_with_tasks(self.db, paper, self.index)

        # Publication should still be created
        pubs = self.db.find_nodes("Study")
        self.assertEqual(len(pubs), 1)

        # No relationships
        rels = self.db.find_relationships(rel_type="USES_PARADIGM")
        self.assertEqual(len(rels), 0)

        # Verify statistics
        self.assertEqual(stats["tasks_extracted"], 0)
        self.assertEqual(stats["tasks_matched"], 0)

    def test_deduplication(self):
        """Test that duplicate tasks are deduplicated"""
        paper = {
            "pmid": "11111111",
            "title": "Test",
            "abstract": "Test",
            "authors": [],
            "tasks": [
                "working memory task",
                "Working Memory Task",
                "WORKING MEMORY TASK",
            ],
        }

        pub_id, stats = ingest_publication_with_tasks(self.db, paper, self.index)

        # Should only create one relationship despite 3 variations
        rels = self.db.find_relationships(rel_type="USES_PARADIGM")
        self.assertEqual(len(rels), 1)
        self.assertEqual(stats["tasks_matched"], 1)


class TestIntegration(unittest.TestCase):
    """Integration tests with sample data"""

    def test_full_pipeline(self):
        """Test the full pipeline from extraction to linking"""
        # This would test the complete flow with real sample data
        # For brevity, using a simple example

        temp_db = tempfile.NamedTemporaryFile(delete=False)
        db = NeuroKGGraphDB(temp_db.name)

        try:
            # Create tasks
            db.create_node("Task", {"name": "working memory fMRI task"}, node_id="t1")
            db.create_node("TaskDef", {"task": "executive control task"}, node_id="td1")

            # Build index
            index = build_comprehensive_task_index(db)

            # Sample publication with extracted tasks
            paper = {
                "pmid": "99999999",
                "title": "Neural mechanisms of working memory",
                "abstract": "Using fMRI during a working memory task...",
                "mesh_terms": ["Memory, Working", "Magnetic Resonance Imaging"],
                "keywords": ["working memory", "fMRI"],
                "authors": [{"first_name": "Test", "last_name": "Author"}],
                "tasks": [],  # Would be populated by extraction
            }

            # Extract tasks
            paper["tasks"] = extract_tasks_from_metadata(
                paper["title"],
                paper["abstract"],
                paper["mesh_terms"],
                paper["keywords"],
            )

            # Ingest
            pub_id, stats = ingest_publication_with_tasks(db, paper, index)

            # Verify
            self.assertGreater(stats["tasks_matched"], 0)

        finally:
            db.close()
            os.unlink(temp_db.name)


if __name__ == "__main__":
    unittest.main()
