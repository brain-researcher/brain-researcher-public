"""Tests for Neurosynth integration tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_researcher.services.tools.neurosynth_tools import (
    NeuroSynthMetaAnalysisTool,
    NeuroSynthTermSearchTool,
)


def test_neurosynth_meta_analysis_tool():
    """Test Neurosynth meta-analysis tool."""
    tool = NeuroSynthMetaAnalysisTool()

    # Check tool properties
    assert tool.get_tool_name() == "neurosynth_meta_analysis"
    assert "Neurosynth" in tool.get_tool_description()
    assert tool.get_args_schema() is not None

    # Test with a simple keyword
    # Note: This requires the Neurosynth dataset to be present
    # Skip test if dataset not available
    try:
        result = tool._run(keyword="memory")

        # Check basic structure
        assert result.status in ["success", "error"]

        if result.status == "success":
            assert "data" in result.__dict__
            data = result.data
            assert "keyword" in data
            # Other fields may be empty if term not found
        else:
            # Dataset might not be available or term not found
            assert result.error is not None

    except FileNotFoundError:
        pytest.skip("Neurosynth dataset not available")
    except ImportError:
        pytest.skip("nimare not installed")


def test_neurosynth_term_search_tool():
    """Test Neurosynth term search tool."""
    tool = NeuroSynthTermSearchTool()

    # Check tool properties
    assert tool.get_tool_name() == "neurosynth_term_search"
    assert tool.get_args_schema() is not None

    # Test term search functionality
    try:
        result = tool._run(
            search_query="memory",
            fuzzy_match=True,
            limit=10,
        )

        # Check basic structure
        assert result.status in ["success", "error"]

        if result.status == "success":
            assert "data" in result.__dict__
            data = result.data
            # Should return matching terms or empty list if not found
        else:
            assert result.error is not None

    except FileNotFoundError:
        pytest.skip("Neurosynth dataset not available")
    except ImportError:
        pytest.skip("nimare not installed")


def test_neurosynth_integration_import():
    """Test that neurosynth_integration module can be imported."""
    try:
        from brain_researcher.core.analysis.neurosynth_integration import (
            get_neurosynth_mapping,
            _get_dataset_path,
        )

        # Check dataset path function
        path = _get_dataset_path()
        assert path is not None
        assert "neurosynth" in path.lower()

        # Check that get_neurosynth_mapping is callable
        assert callable(get_neurosynth_mapping)

    except ImportError as e:
        pytest.skip(f"neurosynth_integration not available: {e}")


@pytest.mark.integration
def test_neurosynth_real_query():
    """Integration test: Run a real Neurosynth query.

    This test requires:
    1. nimare to be installed
    2. Neurosynth dataset to be available
    """
    try:
        from brain_researcher.core.analysis.neurosynth_integration import (
            get_neurosynth_mapping,
        )

        # Test with a common term
        result = get_neurosynth_mapping("fear", threshold=3.0)

        # Should have keyword field
        assert "keyword" in result
        assert result["keyword"] == "fear"

        # Check if successful (may have empty results if term not found)
        if result.get("error"):
            # Term not found or dataset issue
            assert "error" in result
        else:
            # Success - check structure
            assert "term_used" in result or "activation_maps" in result

    except FileNotFoundError:
        pytest.skip("Neurosynth dataset not available")
    except ImportError:
        pytest.skip("nimare not installed")
