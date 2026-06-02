import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# import pdb; pdb.set_trace()

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from brain_researcher.services.br_kg.etl.mappers.contrast_concept_linker import (
    ContrastConceptLinker,
)


class DummyMatcher:
    def match_candidates(self, task_string: str, top_k: int = 1):
        return [{"label": task_string, "score": 1.0, "engine": "dummy"}]


class TestMultiSourceLinker(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        # the path of the repo root is: /data/ECoG-foundation-model/mnndl_temp/brain_researcher
        # import pdb; pdb.set_trace()
        repo_root = Path(__file__).resolve().parents[3]
        ca_path = repo_root / "tests" / "fixtures" / "sample_ca_weights.tsv"
        ann_path = repo_root / "tests" / "fixtures" / "sample_annotations.json"
        self.linker = ContrastConceptLinker(ca_path, matcher=DummyMatcher())
        with open(ann_path) as f:
            self.annotations = json.load(f)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_linking(self):
        edges = self.linker.link_from_annotations(self.annotations)
        self.assertEqual(len(edges), 15)
        pairs = {(e["start_node"], e["end_node"]) for e in edges}
        self.assertEqual(len(pairs), 15)
        for e in edges:
            props = e["properties"]
            self.assertIn("csv_w", props)
            self.assertIn("llm_w", props)
            self.assertIn("pubmed_w", props)
            self.assertIn("timestamp", props)
            self.assertEqual(props["method"], "multi_source")


# write a main function to run the tests
if __name__ == "__main__":
    unittest.main()
