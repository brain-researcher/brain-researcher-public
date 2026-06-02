import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from brain_researcher.services.br_kg.graph.graph_database import BRKGGraphDB


class TestGLMFitLinsLoadToBRKG(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.db_path = Path(self.tempdir) / "test.db"
        self.manifest_path = Path(self.tempdir) / "manifest.json"
        self.contrasts_path = Path(self.tempdir) / "contrasts.csv"

        # Create test manifest CSV
        specs_path = Path(self.tempdir) / "specs" / "ds000test.json"
        ann_path = Path(self.tempdir) / "annotations" / "ds000test.json"
        with open(self.manifest_path, "w") as f:
            f.write("dataset_id,spec_hash,annotation_path,spec_path\n")
            f.write(f"ds000test,test_hash,{ann_path},{specs_path}\n")

        # Create test contrasts CSV
        with open(self.contrasts_path, "w") as f:
            f.write("dataset_id,contrast_name,task_label\n")
            f.write("ds000test,conA,task1\n")
            f.write("ds000test,conB,task1\n")

        # Create specs directory and details file
        specs_dir = Path(self.tempdir) / "specs"
        specs_dir.mkdir(parents=True)

        details_path = specs_dir / "ds000test_basic-details.json"
        details = {
            "Name": "Test Dataset",
            "Tasks": {"task1": {"cite_links": ["10.1000/testpub"]}},
        }
        with open(details_path, "w") as f:
            json.dump(details, f)

        # Create empty annotations directory
        ann_dir = Path(self.tempdir) / "annotations"
        ann_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_load_creates_belongs_to_relationships(self):
        """Test that load_to_br_kg creates BELONGS_TO relationships"""
        # Import here to avoid circular imports
        from brain_researcher.services.br_kg.etl.glmfitlins_ingest.load_to_br_kg import (
            load_to_br_kg,
        )

        # Run the loader
        load_to_br_kg(
            manifest_path=self.manifest_path,
            contrasts_path=self.contrasts_path,
            db_path=self.db_path,
        )

        # Open the database to check results
        db = BRKGGraphDB(str(self.db_path))

        try:
            # Check Study nodes were created
            studies = db.find_nodes("Study")
            self.assertEqual(len(studies), 1)
            study_id = studies[0][0]
            study_data = studies[0][1]
            self.assertEqual(study_data["doi"], "10.1000/testpub")

            # Check Contrast nodes were created
            contrasts = db.find_nodes("Contrast")
            self.assertEqual(len(contrasts), 2)  # conA and conB

            # Check all contrasts have BELONGS_TO relationships
            for con_id, con_data in contrasts:
                rels = db.find_relationships(start_node=con_id, rel_type="BELONGS_TO")
                self.assertEqual(len(rels), 1)
                self.assertEqual(rels[0][1], study_id)

        finally:
            db.close()

    def test_load_without_doi(self):
        """Test loading dataset without DOI"""
        # Update details without cite_links
        specs_dir = Path(self.tempdir) / "specs"
        details_path = specs_dir / "ds000test_basic-details.json"
        details = {
            "Name": "Test Dataset",
            "Tasks": {
                "task1": {
                    # No cite_links
                }
            },
        }
        with open(details_path, "w") as f:
            json.dump(details, f)

        # Import and run loader
        from brain_researcher.services.br_kg.etl.glmfitlins_ingest.load_to_br_kg import (
            load_to_br_kg,
        )

        load_to_br_kg(
            manifest_path=self.manifest_path,
            contrasts_path=self.contrasts_path,
            db_path=self.db_path,
        )

        # Check results
        db = BRKGGraphDB(str(self.db_path))

        try:
            # No Study nodes should be created
            studies = db.find_nodes("Study")
            self.assertEqual(len(studies), 0)

            # Contrasts should still be created
            contrasts = db.find_nodes("Contrast")
            self.assertEqual(len(contrasts), 2)

            # No BELONGS_TO relationships
            for con_id, _ in contrasts:
                rels = db.find_relationships(start_node=con_id, rel_type="BELONGS_TO")
                self.assertEqual(len(rels), 0)

        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
