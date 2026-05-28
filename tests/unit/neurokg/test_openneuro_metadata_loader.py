import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from brain_researcher.services.neurokg.etl.loaders.openneuro_loader.metadata_loader import (
    OpenNeuroMetadataLoader,
)
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB


class TestOpenNeuroMetadataLoader(unittest.TestCase):
    def setUp(self):
        self.db = NeuroKGGraphDB(":memory:")
        self.db.create_node(
            "Task", {"name": "balloon analogue risk task"}, node_id="t1"
        )
        self.db.create_node("Task", {"name": "stroop task"}, node_id="t2")
        self.loader = OpenNeuroMetadataLoader(self.db, dry_run=False)

    def _mock_response(self):
        return {
            "data": {
                "datasets": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [
                        {
                            "node": {
                                "id": "ds001",
                                "name": "ds001",
                                "latestSnapshot": {
                                    "description": {
                                        "Name": "DS1",
                                        "DatasetDOI": "doi1",
                                    },
                                    "summary": {
                                        "subjects": ["01"],
                                        "modalities": ["mri"],
                                        "tasks": ["BART", "UnknownTask"],
                                    },
                                },
                            }
                        },
                        {
                            "node": {
                                "id": "ds002",
                                "name": "ds002",
                                "latestSnapshot": {
                                    "description": {
                                        "Name": "DS2",
                                        "DatasetDOI": "doi2",
                                    },
                                    "summary": {
                                        "subjects": ["01", "02"],
                                        "modalities": ["eeg"],
                                        "tasks": ["BalloonAnalogueRiskTask"],
                                    },
                                },
                            }
                        },
                    ],
                }
            }
        }

    def tearDown(self):
        import os

        if os.path.exists("test_unmatched.csv"):
            os.remove("test_unmatched.csv")

    @patch("requests.post")
    def test_loader(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._mock_response()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        self.loader.load_datasets(limit=2)
        self.loader.save_unmatched("test_unmatched.csv")

        datasets = self.db.find_nodes("Dataset")
        self.assertEqual(len(datasets), 2)
        rels = self.db.find_relationships(rel_type="USES_PARADIGM")
        self.assertEqual(len(rels), 2)

        with open("test_unmatched.csv") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)  # header + one unmatched


if __name__ == "__main__":
    unittest.main()
