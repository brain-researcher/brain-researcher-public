#!/usr/bin/env python3
"""Test subject and phenotype relationship functionality"""

import os
import sys
import tempfile
import unittest

# Add parent directory to path
br_kg_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, br_kg_path)

from graph.graph_database import BRKGGraphDB

from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.metadata_loader import (
    OpenNeuroMetadataLoader,
)


class TestSubjectPhenotypeRelationships(unittest.TestCase):
    """Test cases for subject-phenotype relationship functionality"""

    def setUp(self):
        """Set up test database"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.db = BRKGGraphDB(self.temp_db.name)

        # Create constraints
        self.db.create_constraint("SubjectGroup", "id", "UNIQUE")
        # Note: Subject.subject_id is not unique across datasets
        self.db.create_constraint("Phenotype", "record_id", "UNIQUE")

        self.loader = OpenNeuroMetadataLoader(self.db, dry_run=False)

    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        os.unlink(self.temp_db.name)

    def test_subject_phenotype_relationships(self):
        """Test creation of subject group, subjects, and phenotype relationships"""
        # Test data
        record = {
            "dataset_id": "ds_test",
            "title": "Test Dataset",
            "doi": "test_doi",
            "subjects": ["01", "02"],
            "modalities": ["fMRI"],
            "tasks": [],
            "phenotypes": ["control", "patient"],
        }

        # Load the dataset
        self.loader._upsert_dataset(record)

        # Verify Dataset node was created
        datasets = self.db.find_nodes(labels="Dataset")
        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0][1]["dataset_id"], "ds_test")

        # Verify SubjectGroup node was created
        sg_nodes = self.db.find_nodes(labels="SubjectGroup")
        self.assertEqual(len(sg_nodes), 1)
        self.assertEqual(sg_nodes[0][1]["dataset_id"], "ds_test")

        # Verify Subject nodes were created
        subject_nodes = self.db.find_nodes(labels="Subject")
        self.assertEqual(len(subject_nodes), 2)

        # Check subject properties
        subject_ids = [node_data["subject_id"] for _, node_data in subject_nodes]
        self.assertIn("01", subject_ids)
        self.assertIn("02", subject_ids)

        # Verify Phenotype nodes were created
        pheno_nodes = self.db.find_nodes(labels="Phenotype")
        self.assertEqual(len(pheno_nodes), 2)
        pheno_names = [node_data["name"] for _, node_data in pheno_nodes]
        self.assertIn("control", pheno_names)
        self.assertIn("patient", pheno_names)

        # Verify INCLUDES relationship (Dataset -> SubjectGroup)
        include_rels = self.db.find_relationships(rel_type="INCLUDES")
        self.assertEqual(len(include_rels), 1)
        self.assertEqual(include_rels[0][0], "ds_test")

        # Verify HAS_SUBJECT relationships (SubjectGroup -> Subject)
        has_subject_rels = self.db.find_relationships(rel_type="HAS_SUBJECT")
        self.assertEqual(len(has_subject_rels), 2)

        # Verify HAS_PHENOTYPE relationships (Subject -> Phenotype)
        pheno_rels = self.db.find_relationships(rel_type="HAS_PHENOTYPE")
        self.assertEqual(len(pheno_rels), 4)  # 2 subjects × 2 phenotypes

    def test_no_phenotypes(self):
        """Test handling when no phenotypes are provided"""
        record = {
            "dataset_id": "ds_test2",
            "title": "Test Dataset 2",
            "doi": "test_doi2",
            "subjects": ["01", "02"],
            "modalities": ["fMRI"],
            "tasks": [],
            # No phenotypes key
        }

        # Load the dataset
        self.loader._upsert_dataset(record)

        # Verify subjects were created but no phenotypes
        subject_nodes = self.db.find_nodes(labels="Subject")
        self.assertEqual(len(subject_nodes), 2)

        pheno_nodes = self.db.find_nodes(labels="Phenotype")
        self.assertEqual(len(pheno_nodes), 0)

        pheno_rels = self.db.find_relationships(rel_type="HAS_PHENOTYPE")
        self.assertEqual(len(pheno_rels), 0)

    def test_no_subjects(self):
        """Test handling when no subjects are provided"""
        record = {
            "dataset_id": "ds_test3",
            "title": "Test Dataset 3",
            "doi": "test_doi3",
            "subjects": [],
            "modalities": ["fMRI"],
            "tasks": [],
            "phenotypes": ["control"],
        }

        # Load the dataset
        self.loader._upsert_dataset(record)

        # Verify dataset was created but no subject group
        datasets = self.db.find_nodes(labels="Dataset")
        self.assertEqual(len(datasets), 1)

        sg_nodes = self.db.find_nodes(labels="SubjectGroup")
        self.assertEqual(len(sg_nodes), 0)

        subject_nodes = self.db.find_nodes(labels="Subject")
        self.assertEqual(len(subject_nodes), 0)

    def test_constraint_violations(self):
        """Test that constraint violations are handled gracefully"""
        record = {
            "dataset_id": "ds_test4",
            "title": "Test Dataset 4",
            "doi": "test_doi4",
            "subjects": ["01"],
            "modalities": ["fMRI"],
            "tasks": [],
            "phenotypes": ["control"],
        }

        # Load the dataset twice
        self.loader._upsert_dataset(record)
        self.loader._upsert_dataset(record)  # Should handle constraint violations

        # Verify no duplicates were created
        sg_nodes = self.db.find_nodes(labels="SubjectGroup")
        self.assertEqual(len(sg_nodes), 1)

        subject_nodes = self.db.find_nodes(labels="Subject")
        self.assertEqual(len(subject_nodes), 1)

        pheno_nodes = self.db.find_nodes(labels="Phenotype")
        self.assertEqual(len(pheno_nodes), 1)

    def test_unique_node_ids(self):
        """Test that node IDs are unique across datasets"""
        # First dataset
        record1 = {
            "dataset_id": "ds001",
            "title": "Dataset 1",
            "doi": "doi1",
            "subjects": ["01"],
            "modalities": ["fMRI"],
            "tasks": [],
            "phenotypes": [],
        }

        # Second dataset with same subject ID
        record2 = {
            "dataset_id": "ds002",
            "title": "Dataset 2",
            "doi": "doi2",
            "subjects": ["01"],
            "modalities": ["fMRI"],
            "tasks": [],
            "phenotypes": [],
        }

        # Load both datasets
        self.loader._upsert_dataset(record1)
        self.loader._upsert_dataset(record2)

        # Both subjects should be created with unique node IDs
        subject_nodes = self.db.find_nodes(labels="Subject")
        self.assertEqual(len(subject_nodes), 2)

        # Check that they have different node IDs but same subject_id
        node_ids = [node_id for node_id, _ in subject_nodes]
        self.assertEqual(len(set(node_ids)), 2)  # Two unique node IDs

        subject_ids = [node_data["subject_id"] for _, node_data in subject_nodes]
        self.assertTrue(all(sid == "01" for sid in subject_ids))


if __name__ == "__main__":
    unittest.main()
