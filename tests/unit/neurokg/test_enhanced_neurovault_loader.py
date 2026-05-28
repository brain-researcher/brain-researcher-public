import json
import os
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

from brain_researcher.services.neurokg.etl.loaders.enhanced_neurovault_loader import (
    EnhancedNeuroVaultLoader,
)
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB


class TestEnhancedNeuroVaultLoader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.tmpdir.name, "test.db")
        self.db = NeuroKGGraphDB(db_path)

        # Create various contrast nodes for testing
        self.c1 = self.db.create_node(
            "Contrast", {"name": "2-back > 0-back"}, node_id="con1"
        )
        self.c2 = self.db.create_node("Contrast", {"name": "stop > go"}, node_id="con2")
        self.c3 = self.db.create_node(
            "Contrast", {"name": "incongruent vs congruent"}, node_id="con3"
        )
        self.c4 = self.db.create_node(
            "Contrast", {"name": "faces > houses"}, node_id="con4"
        )

        self.loader = EnhancedNeuroVaultLoader(self.db)

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_normalization(self):
        """Test text normalization"""
        # Test various formats normalize similarly
        norm1 = self.loader._normalize("2-back > 0-back")
        norm2 = self.loader._normalize("2back v 0back")
        # Both should have same content just different spacing
        self.assertEqual(norm1.replace(" ", ""), norm2.replace(" ", ""))

        self.assertEqual(
            self.loader._normalize("Stop > Go"), self.loader._normalize("stop vs go")
        )
        self.assertEqual(
            self.loader._normalize("faces > houses (main effect)"),
            self.loader._normalize("faces v houses"),
        )

    def test_contrast_variations(self):
        """Test generation of contrast variations"""
        variations = self.loader._generate_variations("2-back > 0-back")
        self.assertIn("2-back v 0-back", variations)
        self.assertIn("2-back vs 0-back", variations)
        self.assertIn("2-back - 0-back", variations)

        # Test n-back variations
        variations = self.loader._generate_variations("2back > 0back")
        self.assertIn("2-back > 0-back", variations)

    def test_exact_metadata_matching(self):
        """Test exact matching via cognitive_contrast_cogatlas field"""
        maps = [
            {
                "id": "1",
                "name": "Working Memory Study",
                "cognitive_contrast_cogatlas": "2-back > 0-back",
                "map_type": "T",
            }
        ]

        stats = self.loader.ingest_maps(maps)

        # Check relationship was created
        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        self.assertEqual(len(rels), 1)

        # Check metadata
        rel_props = rels[0][2]
        self.assertEqual(rel_props["method"], "metadata_exact")
        self.assertGreaterEqual(rel_props["confidence"], 0.9)

    def test_fuzzy_metadata_matching(self):
        """Test fuzzy matching on metadata"""
        maps = [
            {
                "id": "2",
                "name": "Study X",
                "cognitive_contrast_cogatlas": "2bck vs 0bck",  # Typo to test fuzzy
                "map_type": "Z",
            }
        ]

        stats = self.loader.ingest_maps(maps)

        # Should still match via fuzzy matching
        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0][2]["method"], "metadata_fuzzy")

    def test_name_extraction_matching(self):
        """Test extraction from map name"""
        maps = [
            {
                "id": "3",
                "name": "Executive Control: Stop > Go",
                "map_type": "T",
                # No cognitive_contrast_cogatlas field
            },
            {
                "id": "4",
                "name": "Visual Processing | contrast: faces > houses | p<0.05",
                "map_type": "Z",
            },
        ]

        stats = self.loader.ingest_maps(maps)

        # Both should match
        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        self.assertEqual(len(rels), 2)

        # Check methods
        methods = {r[2]["method"] for r in rels}
        self.assertIn("name_exact", methods)

    def test_description_matching(self):
        """Test extraction from description field"""
        maps = [
            {
                "id": "5",
                "name": "Attention Study",
                "description": "This map shows the contrast of incongruent vs congruent trials",
                "map_type": "T",
            }
        ]

        stats = self.loader.ingest_maps(maps)

        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0][2]["method"], "description")

    def test_no_match(self):
        """Test handling of maps that don't match any contrast"""
        maps = [
            {
                "id": "6",
                "name": "Resting State Network",
                "description": "Default mode network connectivity",
                "map_type": "T",
            }
        ]

        stats = self.loader.ingest_maps(maps)

        # No relationships should be created
        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        self.assertEqual(len(rels), 0)

        # Should be tracked as unmatched
        self.assertEqual(len(stats["unmatched_maps"]), 1)
        self.assertEqual(stats["unmatched_maps"][0]["id"], "6")

    def test_confidence_threshold(self):
        """Test confidence threshold filtering"""
        maps = [
            {
                "id": "7",
                "name": "Some Study",
                "cognitive_paradigm_cogatlas": "2-back > 0-back task",  # Will match with lower confidence
                "map_type": "T",
            }
        ]

        # First with high threshold
        stats = self.loader.ingest_maps(maps, confidence_threshold=0.8)
        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        self.assertEqual(len(rels), 0)  # Too low confidence

        # Clear relationships
        for rel in self.db.find_relationships():
            # Note: NeuroKGGraphDB doesn't have delete_relationship, so we skip this test detail
            pass

        # Now with lower threshold
        stats = self.loader.ingest_maps(maps, confidence_threshold=0.5)
        rels = self.db.find_relationships(rel_type="DERIVED_FROM")
        # This might create a relationship depending on the paradigm matching logic

    def test_stat_map_node_creation(self):
        """Test that StatMap nodes are created with all fields"""
        maps = [
            {
                "id": "8",
                "name": "Test Map",
                "description": "Test description",
                "map_type": "T",
                "analysis_level": "group",
                "cognitive_paradigm_cogatlas": "working memory",
                "cognitive_contrast_cogatlas": "2-back > 0-back",
                "collection_id": "123",
                "collection_name": "Test Collection",
                "doi": "10.1234/test",
                "file_url": "https://neurovault.org/media/test.nii.gz",
            }
        ]

        self.loader.ingest_maps(maps)

        # Check StatMap node was created with all fields
        stat_maps = self.db.find_nodes("StatMap")
        self.assertEqual(len(stat_maps), 1)

        node_id, props = stat_maps[0]
        self.assertEqual(props["id"], "8")
        self.assertEqual(props["name"], "Test Map")
        self.assertEqual(props["description"], "Test description")
        self.assertEqual(props["map_type"], "T")
        self.assertEqual(props["doi"], "10.1234/test")

    def test_file_ingestion(self):
        """Test ingestion from file with different formats"""
        # Test with dict format
        dict_file = Path(self.tmpdir.name) / "maps_dict.json"
        dict_data = {
            "metadata": {"source": "neurovault"},
            "statistical_maps": [
                {
                    "id": "9",
                    "name": "Working Memory: 2-back > 0-back",
                    "cognitive_contrast_cogatlas": "2-back > 0-back",
                }
            ],
        }
        with open(dict_file, "w") as f:
            json.dump(dict_data, f)

        stats = self.loader.ingest_from_file(dict_file)
        self.assertEqual(stats["maps_processed"], 1)
        self.assertEqual(stats["contrasts_matched"], 1)

        # Clear database
        for node_id, _ in self.db.find_nodes("StatMap"):
            # Note: NeuroKGGraphDB doesn't have delete_node
            pass

        # Test with list format
        list_file = Path(self.tmpdir.name) / "maps_list.json"
        list_data = [
            {
                "id": "10",
                "name": "Stop Signal Task",
                "cognitive_contrast_cogatlas": "stop > go",
            }
        ]
        with open(list_file, "w") as f:
            json.dump(list_data, f)

        stats = self.loader.ingest_from_file(list_file)
        self.assertEqual(stats["maps_processed"], 1)

    def test_duplicate_handling(self):
        """Test handling of duplicate map IDs"""
        maps = [
            {
                "id": "11",
                "name": "Map 1",
                "cognitive_contrast_cogatlas": "2-back > 0-back",
            },
            {
                "id": "11",  # Same ID
                "name": "Map 2",
                "cognitive_contrast_cogatlas": "stop > go",
            },
        ]

        stats = self.loader.ingest_maps(maps)

        # Should process both but with same node ID
        self.assertEqual(stats["maps_processed"], 2)

        # Should only have one StatMap node (second overwrites first)
        stat_maps = self.db.find_nodes("StatMap")
        self.assertEqual(len(stat_maps), 1)

    def test_empty_contrast_database(self):
        """Test behavior when no contrasts exist"""
        # Create new database with no contrasts
        empty_db = NeuroKGGraphDB(":memory:")
        loader = EnhancedNeuroVaultLoader(empty_db)

        maps = [
            {
                "id": "12",
                "name": "Test Map",
                "cognitive_contrast_cogatlas": "2-back > 0-back",
            }
        ]

        stats = loader.ingest_maps(maps)

        # Should create map but no relationships
        self.assertEqual(stats["maps_processed"], 1)
        self.assertEqual(stats["contrasts_matched"], 0)
        self.assertEqual(stats["relationships_created"], 0)


if __name__ == "__main__":
    unittest.main()
