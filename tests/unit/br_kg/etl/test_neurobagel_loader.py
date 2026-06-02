#!/usr/bin/env python3
"""Tests for Neurobagel phenotype loader"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Add project root to path for direct imports
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brain_researcher.services.br_kg.etl.loaders.neurobagel_loader import (
    fetch_neurobagel_data,
    load_neurobagel_data,
)
from brain_researcher.services.br_kg.etl.loaders.neurobagel_public_loader import (
    NeurobagelPublicLoader,
    summarize_subject_records,
)


class TestNeurobagelLoader(unittest.TestCase):
    """Test cases for Neurobagel data loader"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_tsv_content = (
            "participant_id\tsession_id\tpheno_age\tpheno_sex\tpheno_group\n"
            "sub-01\tses-01\t34\tF\tCTRL\n"
            "sub-02\tses-01\t40\tM\tPAT\n"
            "sub-03\tses-02\t25\tF\tCTRL\n"
        )

    def tearDown(self):
        """Clean up test fixtures"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("requests.get")
    def test_fetch_neurobagel_data_success(self, mock_get):
        """Test successful download of Neurobagel data"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.content = self.test_tsv_content.encode()
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Fetch data
        result_path = fetch_neurobagel_data(self.temp_dir, use_cache=False)

        # Verify
        self.assertTrue(os.path.exists(result_path))
        with open(result_path) as f:
            content = f.read()
        self.assertEqual(content, self.test_tsv_content)

    @patch("requests.get")
    def test_fetch_neurobagel_data_fallback(self, mock_get):
        """Test fallback to embedded data when download fails"""
        # Mock failed response
        mock_get.side_effect = Exception("Network error")

        # Fetch data
        result_path = fetch_neurobagel_data(self.temp_dir, use_cache=False)

        # Verify fallback data was used
        self.assertTrue(os.path.exists(result_path))
        with open(result_path) as f:
            content = f.read()
        self.assertIn("sub-01", content)
        self.assertIn("sub-02", content)

    def test_fetch_neurobagel_data_cache(self):
        """Test using cached data"""
        # Create cache file
        cache_file = Path(self.temp_dir) / "neurobagel_phenotypes.tsv"
        cache_file.write_text("cached_data")

        # Fetch with cache
        result_path = fetch_neurobagel_data(self.temp_dir, use_cache=True)

        # Verify cached data was used
        self.assertEqual(str(cache_file), result_path)
        with open(result_path) as f:
            content = f.read()
        self.assertEqual(content, "cached_data")

    def test_load_neurobagel_data_success(self):
        """Test successful loading of neurobagel data"""
        # Create test TSV file
        tsv_file = Path(self.temp_dir) / "test.tsv"
        tsv_file.write_text(self.test_tsv_content)

        # Mock database
        mock_db = MagicMock()
        mock_db.create_node.side_effect = [
            "subject-1",
            "pheno-1",
            "pheno-2",
            "pheno-3",  # sub-01
            "subject-2",
            "pheno-4",
            "pheno-5",
            "pheno-6",  # sub-02
            "subject-3",
            "pheno-7",
            "pheno-8",
            "pheno-9",  # sub-03
        ]
        mock_db.create_relationship.return_value = True
        mock_db.find_nodes.return_value = []

        # Load data
        stats = load_neurobagel_data(mock_db, str(tsv_file))

        # Verify stats
        self.assertEqual(stats["subjects_created"], 3)
        self.assertEqual(
            stats["phenotypes_created"], 9
        )  # 3 subjects x 3 phenotypes each
        self.assertEqual(stats["relationships_created"], 9)
        self.assertEqual(len(stats["errors"]), 0)
        self.assertEqual(
            stats["cohort_metadata"]["group_audit"]["group_counts"]["sex"][
                "participant_counts"
            ],
            {"F": 2, "M": 1},
        )

        # Verify create_node preserved cohort assignments on subjects
        subject_calls = [
            args
            for args, _ in mock_db.create_node.call_args_list
            if args[0] == "Subject"
        ]
        assert len(subject_calls) == 3
        first_subject = subject_calls[0][1]
        self.assertEqual(first_subject["subject_id"], "sub-01")
        self.assertEqual(first_subject["cohort_assignments"]["sex"], "F")
        self.assertEqual(first_subject["cohort_assignments"]["group"], "CTRL")
        self.assertEqual(first_subject["group"], "CTRL")

    def test_load_neurobagel_data_constraint_violation(self):
        """Test handling of constraint violations (duplicate nodes)"""
        # Create test TSV file with duplicate subjects
        tsv_content = (
            "participant_id\tsession_id\tpheno_age\n"
            "sub-01\tses-01\t34\n"
            "sub-01\tses-02\t35\n"  # Duplicate subject
        )
        tsv_file = Path(self.temp_dir) / "test.tsv"
        tsv_file.write_text(tsv_content)

        # Mock database
        mock_db = MagicMock()

        # First subject succeeds, second fails with constraint violation
        def create_node_side_effect(label, props):
            if label == "Subject" and props["subject_id"] == "sub-01":
                if props["session_id"] == "ses-01":
                    return "subject-1"
                else:
                    raise ValueError(
                        "Constraint violation: Subject.subject_id = 'sub-01' already exists"
                    )
            elif label == "Phenotype":
                return f"pheno-{props['record_id']}"

        mock_db.create_node.side_effect = create_node_side_effect
        mock_db.create_relationship.return_value = True
        mock_db.find_nodes.return_value = [("subject-1", {"subject_id": "sub-01"})]

        # Load data
        stats = load_neurobagel_data(mock_db, str(tsv_file))

        # Verify stats
        self.assertEqual(stats["subjects_created"], 1)
        self.assertEqual(stats["subjects_skipped"], 1)
        self.assertEqual(stats["phenotypes_created"], 2)
        self.assertEqual(stats["relationships_created"], 2)
        self.assertEqual(
            stats["cohort_metadata"]["group_audit"]["group_counts"]["session_id"][
                "participant_counts"
            ],
            {"ses-01": 1, "ses-02": 1},
        )

    def test_load_neurobagel_data_missing_columns(self):
        """Test handling of missing required columns"""
        # Create TSV without participant_id
        tsv_content = "session_id\tpheno_age\nses-01\t34\n"
        tsv_file = Path(self.temp_dir) / "test.tsv"
        tsv_file.write_text(tsv_content)

        # Mock database
        mock_db = MagicMock()

        # Load data
        stats = load_neurobagel_data(mock_db, str(tsv_file))

        # Verify error was recorded
        self.assertEqual(len(stats["errors"]), 1)
        self.assertIn("Missing required columns", stats["errors"][0])
        self.assertEqual(stats["subjects_created"], 0)

    def test_load_neurobagel_data_invalid_file(self):
        """Test handling of invalid TSV file"""
        # Create invalid file
        tsv_file = Path(self.temp_dir) / "test.tsv"
        tsv_file.write_text("not a valid tsv file\n@#$%")

        # Mock database
        mock_db = MagicMock()

        # Load data - should handle gracefully
        stats = load_neurobagel_data(mock_db, str(tsv_file))

        # Should still return stats but with potential issues
        self.assertIsInstance(stats, dict)
        self.assertIn("subjects_created", stats)

    def test_load_neurobagel_data_empty_values(self):
        """Test handling of empty/NaN values"""
        # Create TSV with empty values
        tsv_content = (
            "participant_id\tsession_id\tpheno_age\tpheno_sex\n"
            "sub-01\t\t34\t\n"  # Empty session_id and pheno_sex
            "\tses-02\t25\tF\n"  # Empty participant_id
            "sub-03\tses-03\t\tM"  # Empty pheno_age, no trailing newline
        )
        tsv_file = Path(self.temp_dir) / "test.tsv"
        tsv_file.write_text(tsv_content)

        # Mock database
        mock_db = MagicMock()
        mock_db.create_node.return_value = "node-id"
        mock_db.create_relationship.return_value = True
        mock_db.find_nodes.return_value = []

        # Load data
        stats = load_neurobagel_data(mock_db, str(tsv_file))

        # Verify handling of empty values
        # sub-01 should be created with default session_id
        # Row with empty participant_id should be skipped
        # sub-03 should be created, empty pheno_age should be skipped
        self.assertEqual(stats["subjects_created"], 2)  # sub-01 and sub-03

    def test_load_neurobagel_data_relationship_creation(self):
        """Test that relationships are properly created between subjects and phenotypes"""
        # Create test TSV
        tsv_content = "participant_id\tsession_id\tpheno_age\n" "sub-01\tses-01\t34\n"
        tsv_file = Path(self.temp_dir) / "test.tsv"
        tsv_file.write_text(tsv_content)

        # Mock database
        mock_db = MagicMock()
        mock_db.create_node.side_effect = ["subject-1", "pheno-1"]
        mock_db.create_relationship.return_value = True
        mock_db.find_nodes.return_value = []

        # Load data
        stats = load_neurobagel_data(mock_db, str(tsv_file))

        # Verify relationship was created
        mock_db.create_relationship.assert_called_once_with(
            "subject-1",
            "pheno-1",
            "HAS_PHENOTYPE",
            {"created_from": "neurobagel_loader"},
        )
        self.assertEqual(stats["relationships_created"], 1)


class TestNeurobagelPublicLoader(unittest.TestCase):
    """Tests for Neurobagel public node aggregation."""

    def test_summarize_subject_records(self):
        """Subject rows should aggregate into phenotype summaries."""
        record = {
            "dataset_uuid": "http://neurobagel.org/vocab/demo",
            "dataset_name": "Demo Dataset",
            "dataset_portal_uri": "https://github.com/OpenNeuroDatasets-JSONLD/ds123456.git",
            "dataset_total_subjects": 2,
            "records_protected": False,
            "subject_data": [
                {
                    "sub_id": "sub-01",
                    "session_id": "ses-01",
                    "session_type": "http://neurobagel.org/vocab/ImagingSession",
                    "age": 34,
                    "sex": "vocab:FEMALE",
                    "subject_group": "CTRL",
                    "diagnosis": ["vocab:DX1"],
                    "assessment": ["vocab:MMSE"],
                    "image_modal": ["http://purl.org/nidash/nidm#T1Weighted"],
                },
                {
                    "sub_id": "sub-01",
                    "session_id": "ses-01",
                    "session_type": "http://neurobagel.org/vocab/PhenotypicSession",
                    "age": 34,
                    "sex": "vocab:FEMALE",
                    "subject_group": "CTRL",
                    "diagnosis": ["vocab:DX2"],
                    "assessment": ["vocab:MMSE"],
                    "image_modal": [],
                },
            ],
        }

        summary = summarize_subject_records(record)
        self.assertIsNotNone(summary)
        assert summary  # appease type checker
        self.assertEqual(summary.unique_subjects, 1)
        self.assertEqual(summary.imaging_sessions, 1)
        self.assertEqual(summary.phenotypic_sessions, 1)
        self.assertEqual(summary.openneuro_id, "ds123456")
        self.assertEqual(
            summary.cohort_metadata["schema_version"], "br-cohort-metadata-v1"
        )
        self.assertEqual(
            summary.cohort_metadata["group_audit"]["resolved_group_keys"],
            ["sex", "subject_group"],
        )
        self.assertEqual(
            summary.cohort_metadata["group_audit"]["group_counts"]["sex"][
                "participant_counts"
            ],
            {"FEMALE": 1},
        )
        phenotype_names = {item["name"] for item in summary.phenotypes}
        self.assertIn("Age", phenotype_names)
        self.assertIn("Sex", phenotype_names)
        age_entry = next(item for item in summary.phenotypes if item["name"] == "Age")
        self.assertAlmostEqual(age_entry["numeric_summary"]["mean"], 34.0)

    def test_public_loader_persists_summary(self):
        """Loader should create subject group and phenotype nodes without subjects."""
        db = MagicMock()
        db.find_nodes.return_value = []
        db.find_relationships.return_value = []

        def create_node_side_effect(label, props, node_id=None):
            return node_id or f"{label.lower()}-node"

        db.create_node.side_effect = create_node_side_effect
        db.create_relationship.return_value = "rel"

        loader = NeurobagelPublicLoader(db, session=MagicMock())

        record = {
            "dataset_uuid": "http://neurobagel.org/vocab/demo",
            "dataset_name": "Demo Dataset",
            "dataset_portal_uri": None,
            "dataset_total_subjects": 3,
            "records_protected": False,
            "subject_data": [
                {
                    "sub_id": "sub-01",
                    "session_id": "ses-01",
                    "session_type": "http://neurobagel.org/vocab/ImagingSession",
                    "age": 30,
                    "sex": "vocab:MALE",
                    "subject_group": "PAT",
                    "diagnosis": ["vocab:DX3"],
                    "assessment": [],
                    "image_modal": [],
                }
            ],
        }

        summary = summarize_subject_records(record)
        assert summary
        loader._persist_summary(record, summary, "OpenNeuro")

        labels = [args[0] for args, _ in db.create_node.call_args_list]
        self.assertIn("Dataset", labels)
        self.assertIn("SubjectGroup", labels)
        self.assertIn("Phenotype", labels)
        self.assertNotIn("Subject", labels)

        rel_types = [args[2] for args, _ in db.create_relationship.call_args_list]
        self.assertIn("INCLUDES", rel_types)
        self.assertIn("HAS_PHENOTYPE", rel_types)
        dataset_calls = [
            args for args, _ in db.create_node.call_args_list if args[0] == "Dataset"
        ]
        subject_group_calls = [
            args
            for args, _ in db.create_node.call_args_list
            if args[0] == "SubjectGroup"
        ]
        self.assertEqual(
            dataset_calls[0][1]["audit_group_keys"], ["sex", "subject_group"]
        )
        self.assertEqual(
            dataset_calls[0][1]["cohort_metadata"]["group_audit"]["group_counts"][
                "subject_group"
            ]["participant_counts"],
            {"PAT": 1},
        )
        self.assertEqual(
            subject_group_calls[0][1]["cohort_metadata"]["group_audit"][
                "resolved_group_keys"
            ],
            ["sex", "subject_group"],
        )
        self.assertEqual(
            loader.stats["cohort_metadata"]["group_audit"]["group_counts"]["sex"][
                "participant_counts"
            ],
            {"MALE": 1},
        )

    def test_public_loader_offline_cache(self):
        """Loader should read datasets and subjects from offline cache when provided."""
        dataset_uuid = "http://neurobagel.org/vocab/test-dataset"
        dataset_name = "Offline Dataset"

        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            node_slug = "test_node"
            node_dir = cache_root / node_slug
            subjects_dir = node_dir / "subjects"
            subjects_dir.mkdir(parents=True, exist_ok=True)

            datasets_payload = [
                {
                    "dataset_uuid": dataset_uuid,
                    "dataset_name": dataset_name,
                    "dataset_total_subjects": 2,
                    "records_protected": False,
                }
            ]
            (node_dir / "datasets.json").write_text(json.dumps(datasets_payload))

            subject_record = {
                "dataset_uuid": dataset_uuid,
                "dataset_name": dataset_name,
                "dataset_portal_uri": None,
                "dataset_total_subjects": 2,
                "records_protected": False,
                "subject_data": [
                    {
                        "sub_id": "sub-01",
                        "session_type": "http://neurobagel.org/vocab/ImagingSession",
                        "age": 28,
                        "sex": "vocab:FEMALE",
                        "image_modal": ["http://purl.org/nidash/nidm#T1Weighted"],
                        "diagnosis": [],
                        "assessment": [],
                        "subject_group": "CTRL",
                    }
                ],
            }
            subject_slug = (
                re.sub(r"[^A-Za-z0-9]+", "_", dataset_uuid).strip("_").lower()
            )
            (subjects_dir / f"{subject_slug}.json").write_text(
                json.dumps(subject_record)
            )

            db = MagicMock()
            db.find_nodes.return_value = []
            db.find_relationships.return_value = []
            db.create_node.side_effect = (
                lambda label, props, node_id=None: node_id or f"{label.lower()}-node"
            )
            db.create_relationship.return_value = "rel"

            loader = NeurobagelPublicLoader(
                db,
                session=MagicMock(),
                offline_cache_dir=cache_root,
            )
            loader._fetch_nodes = MagicMock(
                return_value=[
                    {"NodeName": "Test Node", "ApiURL": "https://offline.invalid/"}
                ]
            )

            stats = loader.load()

            self.assertEqual(stats["datasets_discovered"], 1)
            created_labels = [args[0] for args, _ in db.create_node.call_args_list]
            self.assertIn("Dataset", created_labels)
            self.assertIn("SubjectGroup", created_labels)
            self.assertIn("Phenotype", created_labels)
            self.assertEqual(
                stats["cohort_metadata"]["group_audit"]["resolved_group_keys"],
                ["sex", "subject_group"],
            )
            self.assertEqual(
                stats["cohort_metadata"]["group_audit"]["group_counts"][
                    "subject_group"
                ]["participant_counts"],
                {"CTRL": 1},
            )


if __name__ == "__main__":
    unittest.main()
