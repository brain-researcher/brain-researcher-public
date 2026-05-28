import os
import sys
import unittest
from unittest.mock import patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOpenNeuroLoaderCLI(unittest.TestCase):
    def test_cli_dry_run(self):
        # Import the openneuro_loader script directly
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "openneuro_loader_script",
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "neurokg",
                "etl",
                "loaders",
                "openneuro_loader.py",
            ),
        )
        openneuro_loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(openneuro_loader)

        sample = {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "edges": [
                {
                    "node": {
                        "id": "ds000001",
                        "name": "Example",
                        "latestSnapshot": {
                            "description": {"DatasetDOI": "doi", "Name": "title"},
                            "summary": {
                                "subjects": ["1"],
                                "modalities": ["fMRI"],
                                "tasks": ["task1"],
                            },
                        },
                    }
                }
            ],
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"data": {"datasets": sample}}
            mock_post.return_value.raise_for_status = lambda: None
            with patch.object(
                sys, "argv", ["openneuro_loader.py", "--limit", "5", "--dry-run"]
            ):
                openneuro_loader.main()
            self.assertTrue(mock_post.called)


if __name__ == "__main__":
    unittest.main()
