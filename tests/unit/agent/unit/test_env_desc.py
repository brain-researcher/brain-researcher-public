"""Unit tests for environment description generator."""

import json
import os
import tempfile
from unittest.mock import patch

from brain_researcher.services.tools.tool_registry import ToolRegistry


class TestEnvDesc:
    def test_registry_get_tool_info(self):
        """Test that ToolRegistry.get_tool_info() returns correct format."""
        registry = ToolRegistry(auto_discover=True)
        info = registry.get_tool_info()

        assert isinstance(info, dict)
        assert "n_tools" in info
        assert "tools" in info
        assert isinstance(info["tools"], list)
        assert info["n_tools"] == len(info["tools"])

        # Check each tool has required fields
        for tool in info["tools"]:
            assert isinstance(tool, dict)
            assert "name" in tool
            assert "description" in tool
            assert "type" in tool
            assert isinstance(tool["name"], str)
            assert isinstance(tool["description"], str)
            assert isinstance(tool["type"], str)

    def test_env_desc_script_content(self):
        """Test the env_desc.py script logic."""
        from brain_researcher.services.tools import env_desc

        # Mock the file writing
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "env_desc.json")

            # Patch os.path.dirname to return our temp directory
            with patch("os.path.dirname") as mock_dirname:
                mock_dirname.return_value = tmpdir

                # Capture print output
                with patch("builtins.print") as mock_print:
                    env_desc.main()

                # Check file was created
                assert os.path.exists(test_file)

                # Check content
                with open(test_file) as f:
                    data = json.load(f)

                assert isinstance(data, dict)
                assert data["n_tools"] > 0
                assert len(data["tools"]) == data["n_tools"]

                # Check print statements
                mock_print.assert_any_call(
                    f"Environment description written to {test_file}"
                )
                mock_print.assert_any_call(f"Total tools documented: {data['n_tools']}")

    def test_all_tools_registered(self):
        """Test that all expected tool collections are registered."""
        registry = ToolRegistry(auto_discover=True)
        tool_names = list(registry.tools.keys())

        # Check for tools from each collection
        expected_tool_samples = [
            # fMRI tools
            "glm_analysis",
            "encoding_model",
            # BR-KG tools
            "find_related_concepts",
            "coordinate_to_concept",
            # BIDS tools
            "validate_bids",
            "query_bids_layout",
            "bids.manifest",
            # NWB tools
            "read_nwb",
            "write_nwb",
            # Archive tools
            "openneuro_download",
            "prefetch.openneuro_cache",
            "dandi_search",
            # Pipeline tools
            "run_fmriprep",
            "run_mriqc",
            # QC tools
            "mriqc_group_report",
            "visual_qc_launch",
            "coreg_qc_gallery",
        ]

        for expected in expected_tool_samples:
            assert expected in tool_names, (
                f"Expected tool '{expected}' not found in registry"
            )
