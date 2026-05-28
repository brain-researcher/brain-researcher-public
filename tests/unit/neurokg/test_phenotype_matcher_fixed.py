import tempfile
import unittest
from pathlib import Path

from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB
from brain_researcher.services.neurokg.utils.phenotype_matcher_fixed import (
    PhenotypeMatcher,
    get_or_create_disease_trait,
)


class TestPhenotypeMatcher(unittest.TestCase):
    """Test phenotype matching functionality"""

    def setUp(self):
        """Set up test data"""
        # Create a temporary aliases file
        self.temp_dir = tempfile.mkdtemp()
        self.aliases_file = Path(self.temp_dir) / "test_aliases.tsv"

        # Write test data
        test_data = """phenotype_id\tlabel\talias
MONDO:0004975\tAlzheimer's disease\tAlzheimer Disease
MONDO:0004975\tAlzheimer's disease\tAD
MONDO:0005180\tParkinson's disease\tPD
MONDO:0003847\tMajor depressive disorder\tDepression"""

        self.aliases_file.write_text(test_data)

    def tearDown(self):
        """Clean up"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_exact_match(self):
        """Test exact matching"""
        matcher = PhenotypeMatcher(synonyms_path=self.aliases_file, embed_threshold=0.8)

        # Test exact label match
        result = matcher.match("Alzheimer's disease")
        self.assertIsNotNone(result)
        self.assertEqual(result["phenotype_id"], "MONDO:0004975")
        self.assertEqual(result["method"], "exact")
        self.assertEqual(result["score"], 1.0)

        # Test exact alias match
        result = matcher.match("AD")
        self.assertIsNotNone(result)
        self.assertEqual(result["phenotype_id"], "MONDO:0004975")
        self.assertEqual(result["method"], "exact")

    def test_fuzzy_match(self):
        """Test fuzzy matching"""
        matcher = PhenotypeMatcher(synonyms_path=self.aliases_file, fuzzy_threshold=80)

        # Test fuzzy match
        result = matcher.match("Alzheimers")  # Missing apostrophe
        self.assertIsNotNone(result)
        self.assertEqual(result["phenotype_id"], "MONDO:0004975")
        # Could be either embedding or fuzzy depending on threshold
        self.assertIn(result["method"], ["embedding", "fuzzy"])
        self.assertGreater(result["score"], 0.8)

    def test_no_match(self):
        """Test when no match is found"""
        matcher = PhenotypeMatcher(synonyms_path=self.aliases_file, fuzzy_threshold=90)

        result = matcher.match("Random disease name")
        self.assertIsNone(result)

    def test_empty_input(self):
        """Test empty input handling"""
        matcher = PhenotypeMatcher(synonyms_path=self.aliases_file)

        self.assertIsNone(matcher.match(""))
        self.assertIsNone(matcher.match(None))
        self.assertIsNone(matcher.match("   "))

    def test_case_insensitive(self):
        """Test case insensitive matching"""
        matcher = PhenotypeMatcher(synonyms_path=self.aliases_file)

        result1 = matcher.match("depression")
        result2 = matcher.match("DEPRESSION")
        result3 = matcher.match("Depression")

        self.assertIsNotNone(result1)
        self.assertEqual(result1["phenotype_id"], result2["phenotype_id"])
        self.assertEqual(result2["phenotype_id"], result3["phenotype_id"])

    def test_get_or_create_disease_trait(self):
        """Test database node creation"""
        db = FakeGraphDB()

        # First creation
        node_id1 = get_or_create_disease_trait(
            db, "MONDO:0004975", "Alzheimer's disease", "Alzheimer Disease"
        )

        # Verify node was created
        nodes = db.find_nodes("DiseaseTrait")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0][1]["phenotype_id"], "MONDO:0004975")
        self.assertEqual(nodes[0][1]["mesh_term"], "Alzheimer Disease")

        # Second call should return same node
        node_id2 = get_or_create_disease_trait(
            db, "MONDO:0004975", "Alzheimer's disease"
        )
        self.assertEqual(node_id1, node_id2)

        # Verify still only one node
        nodes = db.find_nodes("DiseaseTrait")
        self.assertEqual(len(nodes), 1)

    def test_real_phenotype_file(self):
        """Test with real phenotype aliases file if it exists"""
        real_file = Path(__file__).parent.parent / "data" / "phenotype_aliases.tsv"
        if real_file.exists():
            matcher = PhenotypeMatcher(synonyms_path=real_file)

            # Test some known diseases
            tests = [
                ("Alzheimer Disease", "MONDO:0004975"),
                ("Parkinson's disease", "MONDO:0005180"),
                ("Depression", "MONDO:0003847"),
                ("ADHD", "MONDO:0000425"),
                ("PTSD", "MONDO:0005083"),
            ]

            for term, expected_id in tests:
                with self.subTest(term=term):
                    result = matcher.match(term)
                    self.assertIsNotNone(result, f"Failed to match: {term}")
                    self.assertEqual(result["phenotype_id"], expected_id)


if __name__ == "__main__":
    unittest.main()
