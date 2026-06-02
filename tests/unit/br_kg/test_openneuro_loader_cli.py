import os
import runpy
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

CLI_PATH = "brain_researcher/services/br_kg/etl/loaders/openneuro_loader.py"


class TestOpenNeuroLoaderCLI(unittest.TestCase):
    @patch("requests.post")
    def test_cli_dry_run(self, mock_post):
        data = {
            "data": {
                "datasets": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [],
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = data
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        sys.argv = [CLI_PATH, "--limit", "5", "--dry-run"]
        runpy.run_path(CLI_PATH, run_name="__main__")


if __name__ == "__main__":
    unittest.main()
