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

from brain_researcher.services.br_kg.etl.loaders.openneuro_loader.fitlins_loader import (
    OpenNeuroFitLinsLoader,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB


class TestFitLinsLoaderPublication(unittest.TestCase):
    def setUp(self):
        self.db = FakeGraphDB()
        self.tempdir = tempfile.mkdtemp()
        self.dataset_id = "ds000test"
        ds_dir = Path(self.tempdir) / "statsmodel_specs" / self.dataset_id
        ds_dir.mkdir(parents=True)

        details = {
            "Subjects": ["01"],
            "Tasks": {
                "task1": {
                    "bold_volumes": 1,
                    "dummy_volumes": 0,
                    "cite_links": ["10.1000/testpub"],
                }
            },
        }
        with open(ds_dir / f"{self.dataset_id}_basic-details.json", "w") as f:
            json.dump(details, f)

        contrasts = {
            "Contrasts": [{"Name": "conA", "ConditionList": ["a"], "Weights": [1]}]
        }
        with open(ds_dir / f"{self.dataset_id}-task1_contrasts.json", "w") as f:
            json.dump(contrasts, f)

        self.loader = OpenNeuroFitLinsLoader(self.db, openneuro_dir=self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_belongs_to_created(self):
        """Test that BELONGS_TO relationship is created between contrast and publication"""
        self.loader.load_dataset(self.dataset_id)

        # Check Study nodes were created
        pubs = self.db.find_nodes("Study")
        self.assertEqual(len(pubs), 1)
        pub_id = pubs[0][0]
        pub_data = pubs[0][1]
        self.assertEqual(pub_data["doi"], "10.1000/testpub")

        # Check Contrast nodes were created
        contrasts = self.db.find_nodes("Contrast")
        self.assertEqual(len(contrasts), 1)
        con_id = contrasts[0][0]

        # Check BELONGS_TO relationship exists
        rels = self.db.find_relationships(start_node=con_id, rel_type="BELONGS_TO")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0][1], pub_id)

    def test_no_doi_no_publication(self):
        """Test that no publication is created when DOI is missing"""
        # Create dataset without cite_links
        ds_dir = Path(self.tempdir) / "statsmodel_specs" / "ds000test2"
        ds_dir.mkdir(parents=True)

        details = {
            "Subjects": ["01"],
            "Tasks": {
                "task1": {
                    "bold_volumes": 1,
                    "dummy_volumes": 0,
                    # No cite_links
                }
            },
        }
        with open(ds_dir / "ds000test2_basic-details.json", "w") as f:
            json.dump(details, f)

        contrasts = {
            "Contrasts": [{"Name": "conA", "ConditionList": ["a"], "Weights": [1]}]
        }
        with open(ds_dir / "ds000test2-task1_contrasts.json", "w") as f:
            json.dump(contrasts, f)

        self.loader.load_dataset("ds000test2")

        # No Study nodes should be created
        pubs = self.db.find_nodes("Study")
        self.assertEqual(len(pubs), 0)

        # Contrast should still be created
        contrasts = self.db.find_nodes("Contrast", {"dataset": "ds000test2"})
        self.assertEqual(len(contrasts), 1)
        con_id = contrasts[0][0]

        # No BELONGS_TO relationships
        rels = self.db.find_relationships(start_node=con_id, rel_type="BELONGS_TO")
        self.assertEqual(len(rels), 0)

    def test_existing_publication_reused(self):
        """Test that existing publication nodes are reused"""
        # Create a publication node first
        existing_pub_id = self.db.create_node(
            "Study",
            {"doi": "10.1000/testpub", "title": "Existing Publication"},
        )

        # Load dataset with same DOI
        self.loader.load_dataset(self.dataset_id)

        # Should still only have one Study node
        pubs = self.db.find_nodes("Study")
        self.assertEqual(len(pubs), 1)
        self.assertEqual(pubs[0][0], existing_pub_id)

        # Check that contrast links to existing publication
        contrasts = self.db.find_nodes("Contrast")
        con_id = contrasts[0][0]

        rels = self.db.find_relationships(start_node=con_id, rel_type="BELONGS_TO")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0][1], existing_pub_id)

    def test_multiple_contrasts_same_publication(self):
        """Test multiple contrasts linking to same publication"""
        # Update contrasts file with multiple contrasts
        ds_dir = Path(self.tempdir) / "statsmodel_specs" / self.dataset_id
        contrasts = {
            "Contrasts": [
                {"Name": "conA", "ConditionList": ["a"], "Weights": [1]},
                {"Name": "conB", "ConditionList": ["b"], "Weights": [1]},
                {"Name": "conC", "ConditionList": ["c"], "Weights": [1]},
            ]
        }
        with open(ds_dir / f"{self.dataset_id}-task1_contrasts.json", "w") as f:
            json.dump(contrasts, f)

        self.loader.load_dataset(self.dataset_id)

        # Should have one publication
        pubs = self.db.find_nodes("Study")
        self.assertEqual(len(pubs), 1)
        pub_id = pubs[0][0]

        # Should have three contrasts
        contrasts = self.db.find_nodes("Contrast")
        self.assertEqual(len(contrasts), 3)

        # All contrasts should link to same publication
        for con_id, _ in contrasts:
            rels = self.db.find_relationships(start_node=con_id, rel_type="BELONGS_TO")
            self.assertEqual(len(rels), 1)
            self.assertEqual(rels[0][1], pub_id)


if __name__ == "__main__":
    unittest.main()
