"""Tests for spatial utilities module."""

import math

import pytest

from brain_researcher.core.utils.spatial import (
    AVAILABLE_ATLASES,
    euclidean_distance,
    find_nearby_rois,
    get_roi_coordinates,
    list_available_rois,
    mni_to_talairach,
    overlap_score,
    talairach_to_mni,
    validate_coordinates,
)


class TestROILookup:
    """Test ROI coordinate lookup functionality."""

    def test_get_roi_coordinates_mni(self):
        """Test getting ROI coordinates from MNI atlas."""
        # Test valid ROI
        coords = get_roi_coordinates("insula", "MNI")
        assert coords is not None
        assert len(coords) == 3
        assert coords == [36.0, 18.0, 6.0]

        # Test case-insensitive lookup
        coords_upper = get_roi_coordinates("INSULA", "MNI")
        assert coords_upper == coords

        # Test left/right variants
        left_coords = get_roi_coordinates("left_insula", "MNI")
        assert left_coords == [-36.0, 18.0, 6.0]

    def test_get_roi_coordinates_invalid(self):
        """Test handling of invalid ROI names."""
        coords = get_roi_coordinates("nonexistent_roi", "MNI")
        assert coords is None

    def test_get_roi_coordinates_invalid_atlas(self):
        """Test handling of invalid atlas names."""
        coords = get_roi_coordinates("insula", "InvalidAtlas")
        assert coords is None

    def test_list_available_rois(self):
        """Test listing available ROIs."""
        rois = list_available_rois("MNI")
        assert isinstance(rois, list)
        assert len(rois) > 0
        assert "insula" in rois
        assert "hippocampus" in rois
        assert "ba44" in rois

        # Test empty list for invalid atlas
        rois_invalid = list_available_rois("InvalidAtlas")
        assert rois_invalid == []

    def test_brodmann_areas(self):
        """Test Brodmann area lookups."""
        ba44 = get_roi_coordinates("ba44", "MNI")
        assert ba44 is not None
        assert len(ba44) == 3

        ba17 = get_roi_coordinates("ba17", "MNI")
        assert ba17 is not None


class TestCoordinateTransforms:
    """Test coordinate transformation functions."""

    def test_talairach_to_mni_lancaster(self):
        """Test Talairach to MNI conversion using Lancaster method."""
        tal_coords = [34.0, 16.0, 4.0]
        mni_coords = talairach_to_mni(tal_coords, method="lancaster")

        assert len(mni_coords) == 3
        # Check approximate values
        assert abs(mni_coords[0] - 34.34) < 0.1
        assert abs(mni_coords[1] - 15.816) < 0.1
        assert abs(mni_coords[2] - 4.324) < 0.1

    def test_mni_to_talairach_lancaster(self):
        """Test MNI to Talairach conversion using Lancaster method."""
        mni_coords = [36.0, 18.0, 6.0]
        tal_coords = mni_to_talairach(mni_coords, method="lancaster")

        assert len(tal_coords) == 3
        # Check approximate values
        assert abs(tal_coords[0] - 35.64) < 0.1
        assert abs(tal_coords[1] - 17.704) < 0.1
        assert abs(tal_coords[2] - 5.209) < 0.1

    def test_round_trip_conversion(self):
        """Test that round-trip conversion preserves coordinates approximately."""
        original = [40.0, 30.0, 20.0]

        # MNI -> Talairach -> MNI
        tal = mni_to_talairach(original)
        back_to_mni = talairach_to_mni(tal)

        for orig, final in zip(original, back_to_mni, strict=False):
            assert abs(orig - final) < 1.0  # Within 1mm tolerance

    def test_invalid_method(self):
        """Test handling of invalid transformation method."""
        with pytest.raises(ValueError):
            talairach_to_mni([0, 0, 0], method="invalid")


class TestDistanceAndOverlap:
    """Test distance calculation and overlap scoring."""

    def test_euclidean_distance(self):
        """Test Euclidean distance calculation."""
        coord1 = [0.0, 0.0, 0.0]
        coord2 = [3.0, 4.0, 0.0]

        dist = euclidean_distance(coord1, coord2)
        assert dist == 5.0  # 3-4-5 triangle

        # Test same point
        dist_same = euclidean_distance(coord1, coord1)
        assert dist_same == 0.0

    def test_overlap_score_gaussian(self):
        """Test Gaussian overlap scoring."""
        coord = [36.0, 18.0, 6.0]  # Exact insula location

        # Perfect overlap
        score = overlap_score(coord, "insula", "MNI", method="gaussian")
        assert score == 1.0

        # Test decay with distance
        coord_5mm = [41.0, 18.0, 6.0]  # 5mm away
        score_5mm = overlap_score(
            coord_5mm, "insula", "MNI", method="gaussian", sigma=10.0
        )
        assert 0 < score_5mm < 1.0
        assert abs(score_5mm - math.exp(-0.125)) < 0.01  # exp(-(5^2)/(2*10^2))

    def test_overlap_score_sphere(self):
        """Test sphere overlap scoring."""
        coord = [36.0, 18.0, 6.0]  # Exact insula location

        # Inside sphere
        score = overlap_score(coord, "insula", "MNI", method="sphere", roi_radius=15.0)
        assert score == 1.0

        # Outside sphere but in transition zone
        coord_20mm = [56.0, 18.0, 6.0]  # 20mm away
        score_20mm = overlap_score(
            coord_20mm, "insula", "MNI", method="sphere", roi_radius=15.0
        )
        assert 0 < score_20mm < 1.0

        # Far outside
        coord_far = [100.0, 18.0, 6.0]  # Very far
        score_far = overlap_score(
            coord_far, "insula", "MNI", method="sphere", roi_radius=15.0
        )
        assert score_far == 0.0

    def test_overlap_score_invalid_roi(self):
        """Test overlap score with invalid ROI."""
        score = overlap_score([0, 0, 0], "invalid_roi", "MNI")
        assert score == 0.0


class TestSpatialSearch:
    """Test spatial search utilities."""

    def test_find_nearby_rois(self):
        """Test finding nearby ROIs."""
        # Search near insula
        coord = [36.0, 18.0, 6.0]
        nearby = find_nearby_rois(coord, atlas="MNI", radius=30.0)

        assert isinstance(nearby, list)
        assert len(nearby) > 0

        # First result should be insula itself (distance 0)
        assert nearby[0][0] == "insula"
        assert nearby[0][1] == 0.0

        # Results should be sorted by distance
        distances = [dist for _, dist in nearby]
        assert distances == sorted(distances)

    def test_find_nearby_rois_with_limit(self):
        """Test finding nearby ROIs with top_k limit."""
        coord = [0.0, 0.0, 0.0]  # Central location
        nearby = find_nearby_rois(coord, atlas="MNI", radius=100.0, top_k=3)

        assert len(nearby) <= 3


class TestCoordinateValidation:
    """Test coordinate validation."""

    def test_validate_mni_coordinates(self):
        """Test MNI coordinate validation."""
        # Valid coordinates
        is_valid, msg = validate_coordinates([36.0, 18.0, 6.0], "MNI")
        assert is_valid is True

        # Outside bounds
        is_valid, msg = validate_coordinates([100.0, 18.0, 6.0], "MNI")
        assert is_valid is False
        assert "outside MNI bounds" in msg

    def test_validate_talairach_coordinates(self):
        """Test Talairach coordinate validation."""
        # Valid coordinates
        is_valid, msg = validate_coordinates([34.0, 16.0, 4.0], "Talairach")
        assert is_valid is True

        # Outside bounds
        is_valid, msg = validate_coordinates([90.0, 16.0, 4.0], "Talairach")
        assert is_valid is False
        assert "outside Talairach bounds" in msg

    def test_validate_wrong_length(self):
        """Test validation with wrong number of coordinates."""
        is_valid, msg = validate_coordinates([36.0, 18.0], "MNI")
        assert is_valid is False
        assert "must have 3 values" in msg

    def test_validate_unknown_space(self):
        """Test validation with unknown coordinate space."""
        is_valid, msg = validate_coordinates([0, 0, 0], "Unknown")
        assert is_valid is False
        assert "Unknown coordinate space" in msg


class TestAtlasData:
    """Test atlas data integrity."""

    def test_available_atlases(self):
        """Test that expected atlases are available."""
        assert "MNI" in AVAILABLE_ATLASES
        assert "Talairach" in AVAILABLE_ATLASES
        assert "AAL" in AVAILABLE_ATLASES
        assert "HarvardOxford" in AVAILABLE_ATLASES

    def test_atlas_roi_counts(self):
        """Test that atlases have reasonable number of ROIs."""
        for atlas in AVAILABLE_ATLASES:
            rois = list_available_rois(atlas)
            assert len(rois) > 0

        # MNI should have the most ROIs
        mni_rois = list_available_rois("MNI")
        assert len(mni_rois) > 30
