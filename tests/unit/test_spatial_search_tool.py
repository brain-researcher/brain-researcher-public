"""Tests for enhanced SpatialSearchTool with ROI support."""

from unittest.mock import Mock

import pytest

from brain_researcher.services.tools.rag_tools import (
    SpatialSearchArgs,
    SpatialSearchTool,
)


class TestSpatialSearchToolEnhanced:
    """Test the enhanced SpatialSearchTool with ROI support."""

    @pytest.fixture
    def mock_rag_system(self):
        """Create a mock RAG system."""
        mock = Mock()
        # Mock spatial retrieval results
        mock.retrieve_spatial.return_value = [
            {
                "id": "study1_coord1",
                "title": "Study 1",
                "abstract": "Coordinates: [35, 20, 5]",
                "source": "nimare_dataset",
                "coordinates": [35.0, 20.0, 5.0],
                "distance_to_query": 2.5,
                "study_id": "study1",
                "score": 0.286,
            },
            {
                "id": "study2_coord1",
                "title": "Study 2",
                "abstract": "Coordinates: [38, 15, 8]",
                "source": "nimare_dataset",
                "coordinates": [38.0, 15.0, 8.0],
                "distance_to_query": 4.2,
                "study_id": "study2",
                "score": 0.192,
            },
        ]
        return mock

    @pytest.fixture
    def spatial_tool(self, mock_rag_system):
        """Create SpatialSearchTool with mock RAG system."""
        return SpatialSearchTool(rag_system=mock_rag_system)

    def test_search_with_roi_name(self, spatial_tool):
        """Test searching with ROI name instead of coordinates."""
        result = spatial_tool._run(
            roi_name="insula", atlas_name="MNI", radius=15.0, top_k=5
        )

        assert result.status == "success"
        assert result.data["n_results"] == 2
        assert "nearby_rois" in result.data
        assert "search_summary" in result.data
        assert "insula" in result.data["search_summary"]

        # Check that overlap scores were added
        for r in result.data["results"]:
            assert "overlap_score" in r
            assert 0 <= r["overlap_score"] <= 1

    def test_search_with_talairach_coordinates(self, spatial_tool):
        """Test searching with Talairach coordinates."""
        result = spatial_tool._run(
            coordinates=[34.0, 16.0, 4.0], coord_space="Talairach", radius=10.0, top_k=5
        )

        assert result.status == "success"
        # Coordinates should have been converted to MNI
        query_coords = result.data["query_params"]["coordinates"]
        assert query_coords != [34.0, 16.0, 4.0]  # Should be transformed

    def test_search_with_invalid_roi(self, spatial_tool):
        """Test error handling for invalid ROI name."""
        result = spatial_tool._run(roi_name="nonexistent_region", atlas_name="MNI")

        assert result.status == "error"
        assert "not found" in result.error
        assert "Available ROIs include" in result.error

    def test_search_with_invalid_atlas(self):
        """Test validation of invalid atlas name."""
        with pytest.raises(ValueError) as exc_info:
            args = SpatialSearchArgs(roi_name="insula", atlas_name="InvalidAtlas")
        assert "atlas_name must be one of" in str(exc_info.value)

    def test_search_requires_input(self):
        """Test that either coordinates or ROI name is required."""
        with pytest.raises(ValueError) as exc_info:
            args = SpatialSearchArgs()
        assert "Either 'coordinates' or 'roi_name' must be provided" in str(
            exc_info.value
        )

    def test_search_exclusive_inputs(self):
        """Test that both coordinates and ROI name cannot be provided."""
        with pytest.raises(ValueError) as exc_info:
            args = SpatialSearchArgs(coordinates=[36.0, 18.0, 6.0], roi_name="insula")
        assert "Provide either 'coordinates' or 'roi_name', not both" in str(
            exc_info.value
        )

    def test_nearby_rois_in_response(self, spatial_tool):
        """Test that nearby ROIs are included in response."""
        result = spatial_tool._run(coordinates=[36.0, 18.0, 6.0], radius=10.0)

        assert result.status == "success"
        assert "nearby_rois" in result.data
        nearby = result.data["nearby_rois"]
        assert isinstance(nearby, list)
        if nearby:  # If any nearby ROIs found
            assert "name" in nearby[0]
            assert "distance_mm" in nearby[0]

    def test_roi_from_different_atlas(self, spatial_tool):
        """Test using ROI from AAL atlas."""
        result = spatial_tool._run(
            roi_name="hippocampus_l", atlas_name="AAL", radius=20.0
        )

        assert result.status == "success"
        # Should find the ROI and convert to MNI if needed
        assert result.data["query_params"]["roi_name"] == "hippocampus_l"
        assert result.data["query_params"]["atlas_name"] == "AAL"

    def test_coordinate_validation_warning(self, spatial_tool):
        """Test that out-of-bounds coordinates generate warning but still work."""
        # Coordinates slightly outside standard MNI bounds
        result = spatial_tool._run(
            coordinates=[95.0, 0.0, 0.0],  # X coordinate out of bounds
            radius=10.0,
        )

        # Should still return results (with warning logged)
        assert result.status == "success"

    def test_search_summary_generation(self, spatial_tool):
        """Test that search summaries are generated correctly."""
        # Test with ROI
        result_roi = spatial_tool._run(roi_name="ba44", atlas_name="MNI", radius=15.0)
        assert "search_summary" in result_roi.data
        assert "ba44" in result_roi.data["search_summary"]
        assert "MNI atlas" in result_roi.data["search_summary"]

        # Test with coordinates
        result_coords = spatial_tool._run(
            coordinates=[10.0, 20.0, 30.0], coord_space="MNI", radius=10.0
        )
        assert "search_summary" in result_coords.data
        assert "[10.0, 20.0, 30.0]" in result_coords.data["search_summary"]
        assert "MNI space" in result_coords.data["search_summary"]


class TestSpatialSearchArgsValidation:
    """Test validation of SpatialSearchArgs."""

    def test_valid_coordinates_args(self):
        """Test valid arguments with coordinates."""
        args = SpatialSearchArgs(coordinates=[36.0, 18.0, 6.0], radius=15.0, top_k=10)
        assert args.coordinates == [36.0, 18.0, 6.0]
        assert args.roi_name is None

    def test_valid_roi_args(self):
        """Test valid arguments with ROI name."""
        args = SpatialSearchArgs(roi_name="hippocampus", atlas_name="MNI", radius=20.0)
        assert args.roi_name == "hippocampus"
        assert args.coordinates is None

    def test_coordinate_space_validation(self):
        """Test coordinate space validation."""
        # Valid spaces
        args1 = SpatialSearchArgs(roi_name="insula", coord_space="MNI")
        args2 = SpatialSearchArgs(roi_name="insula", coord_space="Talairach")

        # Invalid space
        with pytest.raises(ValueError) as exc_info:
            SpatialSearchArgs(roi_name="insula", coord_space="Unknown")
        assert "coord_space must be" in str(exc_info.value)

    def test_radius_bounds(self):
        """Test radius parameter bounds."""
        # Valid radius
        args = SpatialSearchArgs(roi_name="insula", radius=25.0)
        assert args.radius == 25.0

        # Too small
        with pytest.raises(ValueError):
            SpatialSearchArgs(roi_name="insula", radius=0.0)

        # Too large
        with pytest.raises(ValueError):
            SpatialSearchArgs(roi_name="insula", radius=51.0)
