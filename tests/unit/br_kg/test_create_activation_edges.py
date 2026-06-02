#!/usr/bin/env python3
import unittest

from brain_researcher.services.br_kg.spatial.create_activation_edges import (
    collect_coordinate_evidence,
    create_activation_edges,
    validate_database_structure,
)
from tests.unit.br_kg._graph_test_utils import UnitGraphDB


class TestCreateActivationEdges(unittest.TestCase):
    """Test activation edge creation functionality."""

    def setUp(self):
        """Create a test database with sample data."""
        self.db = UnitGraphDB()

        # Create sample data
        self._create_sample_data()

    def tearDown(self):
        """Clean up test database."""
        self.db.close()

    def _create_sample_data(self):
        """Create sample nodes and relationships for testing."""
        # Create concepts
        self.concept1 = self.db.create_node(
            "Concept", {"name": "working_memory", "definition": "Test concept 1"}
        )
        self.concept2 = self.db.create_node(
            "Concept", {"name": "attention", "definition": "Test concept 2"}
        )

        # Create tasks
        self.task1 = self.db.create_node(
            "Task", {"name": "n-back", "description": "Test task 1"}
        )

        # Create publications (need more to avoid overlap)
        self.pub1 = self.db.create_node("Study", {"pmid": "12345", "title": "Study 1"})
        self.pub2 = self.db.create_node("Study", {"pmid": "23456", "title": "Study 2"})
        self.pub3 = self.db.create_node("Study", {"pmid": "34567", "title": "Study 3"})
        self.pub4 = self.db.create_node("Study", {"pmid": "45678", "title": "Study 4"})

        # Create brain regions
        self.region1 = self.db.create_node(
            "BrainRegion",
            {"name": "dorsolateral_prefrontal_cortex", "abbreviation": "dlPFC"},
        )
        self.region2 = self.db.create_node(
            "BrainRegion", {"name": "anterior_cingulate_cortex", "abbreviation": "ACC"}
        )

        # Create coordinates and relationships for concept1 -> region1 (6 coordinates)
        # This should exceed the default threshold of 5
        for i in range(6):
            coord_id = self.db.create_node(
                "Coordinate", {"x": -45 + i, "y": 20 + i, "z": 30 + i, "space": "MNI"}
            )

            # Connect: pub -> concept -> coord -> region
            if i < 3:
                self.db.create_relationship(self.pub1, self.concept1, "STUDIES")
                self.db.create_relationship(self.pub1, coord_id, "HAS_COORDINATE")
            else:
                self.db.create_relationship(
                    self.pub2, self.concept1, "MENTIONS_CONCEPT"
                )
                self.db.create_relationship(self.pub2, coord_id, "HAS_COORDINATE")

            self.db.create_relationship(coord_id, self.region1, "LOCATED_IN")

        # Create coordinates for concept2 -> region2 (3 coordinates)
        # This should NOT exceed the threshold
        for i in range(3):
            coord_id = self.db.create_node(
                "Coordinate", {"x": 0 + i, "y": 30 + i, "z": 20 + i, "space": "MNI"}
            )
            self.db.create_relationship(self.pub3, self.concept2, "STUDIES")
            self.db.create_relationship(self.pub3, coord_id, "HAS_COORDINATE")
            self.db.create_relationship(coord_id, self.region2, "LOCATED_IN")

        # Create coordinates for task1 -> region1 (5 coordinates)
        # This should exactly meet the threshold
        for i in range(5):
            coord_id = self.db.create_node(
                "Coordinate", {"x": 40 + i, "y": 15 + i, "z": 35 + i, "space": "MNI"}
            )
            self.db.create_relationship(self.pub4, self.task1, "STUDIES")
            self.db.create_relationship(self.pub4, coord_id, "HAS_COORDINATE")
            self.db.create_relationship(coord_id, self.region1, "LOCATED_IN")

    def test_validate_database_structure(self):
        """Test database structure validation."""
        # Should pass with our test data
        self.assertTrue(validate_database_structure(self.db))

    def test_collect_coordinate_evidence_concepts(self):
        """Test evidence collection for concepts."""
        evidence = collect_coordinate_evidence(self.db, "Concept")

        # Check that we found evidence for concept1
        self.assertIn(self.concept1, evidence)
        self.assertIn("dorsolateral_prefrontal_cortex", evidence[self.concept1])
        self.assertEqual(
            len(evidence[self.concept1]["dorsolateral_prefrontal_cortex"]), 6
        )

        # Check that we found evidence for concept2
        self.assertIn(self.concept2, evidence)
        self.assertIn("anterior_cingulate_cortex", evidence[self.concept2])
        self.assertEqual(len(evidence[self.concept2]["anterior_cingulate_cortex"]), 3)

    def test_collect_coordinate_evidence_tasks(self):
        """Test evidence collection for tasks."""
        evidence = collect_coordinate_evidence(self.db, "Task")

        # Check that we found evidence for task1
        self.assertIn(self.task1, evidence)
        self.assertIn("dorsolateral_prefrontal_cortex", evidence[self.task1])
        self.assertEqual(len(evidence[self.task1]["dorsolateral_prefrontal_cortex"]), 5)

    def test_create_activation_edges_threshold(self):
        """Test edge creation with threshold."""
        # Collect evidence
        evidence = collect_coordinate_evidence(self.db, "Concept")

        # Create edges with threshold=5
        stats = create_activation_edges(self.db, evidence, "Concept", threshold=5)

        # Check statistics
        self.assertEqual(stats["edges_created"], 1)  # Only concept1->region1
        self.assertEqual(stats["edges_skipped_threshold"], 1)  # concept2->region2
        self.assertEqual(stats["edges_skipped_exists"], 0)
        self.assertEqual(stats["errors"], 0)

        # Verify the edge was created
        edges = self.db.find_relationships(
            start_node=self.concept1, end_node=self.region1, rel_type="ACTIVATES"
        )
        self.assertEqual(len(edges), 1)

        # Check edge properties
        edge_data = edges[0][2]
        self.assertEqual(edge_data["evidence_count"], 6)
        self.assertEqual(edge_data["confidence"], 0.6)
        self.assertEqual(edge_data["method"], "coordinate_aggregation")

    def test_create_activation_edges_dry_run(self):
        """Test dry run mode."""
        # Collect evidence
        evidence = collect_coordinate_evidence(self.db, "Task")

        # Create edges in dry run mode
        stats = create_activation_edges(
            self.db, evidence, "Task", threshold=5, dry_run=True
        )

        # Check statistics
        self.assertEqual(stats["edges_created"], 1)  # Would create task1->region1

        # Verify no edge was actually created
        edges = self.db.find_relationships(
            start_node=self.task1, end_node=self.region1, rel_type="ACTIVATES"
        )
        self.assertEqual(len(edges), 0)

    def test_create_activation_edges_existing(self):
        """Test handling of existing edges."""
        # Create an existing edge
        self.db.create_relationship(
            self.concept1,
            self.region1,
            "ACTIVATES",
            {"evidence_count": 3, "method": "manual"},
        )

        # Collect evidence and try to create edges
        evidence = collect_coordinate_evidence(self.db, "Concept")
        stats = create_activation_edges(self.db, evidence, "Concept", threshold=5)

        # Check statistics - should skip the existing edge
        self.assertEqual(stats["edges_created"], 0)
        self.assertEqual(stats["edges_skipped_exists"], 1)

    def test_empty_database(self):
        """Test with empty database."""
        empty_db = UnitGraphDB()

        # Should handle empty database gracefully
        evidence = collect_coordinate_evidence(empty_db, "Concept")
        self.assertEqual(len(evidence), 0)

        stats = create_activation_edges(empty_db, evidence, "Concept")
        self.assertEqual(stats["edges_created"], 0)
        self.assertEqual(stats["errors"], 0)

        empty_db.close()


if __name__ == "__main__":
    unittest.main()
