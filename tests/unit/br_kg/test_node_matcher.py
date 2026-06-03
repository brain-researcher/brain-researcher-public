"""Tests for UnifiedNodeMatcher"""

import pytest
from brain_researcher.services.br_kg.matching.node_matcher import (
    UnifiedNodeMatcher,
    MatchResult
)


class TestUnifiedNodeMatcher:
    """Test node matching functionality."""

    def test_exact_match_task(self):
        """Test exact matching for Task nodes."""
        matcher = UnifiedNodeMatcher()

        candidate = {
            "id": "test:nback",
            "label": "n-back task"
        }

        existing = [
            {"id": "cogat:nback", "label": "n-back task"},
            {"id": "other:task", "label": "stroop task"}
        ]

        matches = matcher.match_node(candidate, "Task", existing)

        assert len(matches) > 0
        assert matches[0].target_node_id == "cogat:nback"
        assert matches[0].confidence == 1.0
        assert matches[0].method == "exact"

    def test_exact_concept_match_accepts_semantic_field_alignment(self):
        """Exact label matches should remain valid even when source IDs differ."""
        matcher = UnifiedNodeMatcher()

        candidate = {
            "id": "test:wm",
            "label": "working memory"
        }

        existing = [
            {"id": "mesh:D008570", "label": "Working Memory"},  # Capitalization diff
            {"id": "other:concept", "label": "episodic memory"}
        ]

        matches = matcher.match_node(candidate, "Concept", existing)

        assert len(matches) > 0
        assert matches[0].target_node_id == "mesh:D008570"
        assert matches[0].method == "exact"
        assert matches[0].confidence >= 0.9

    def test_spatial_match_coordinate(self):
        """Test spatial matching for Coordinate nodes."""
        matcher = UnifiedNodeMatcher()

        candidate = {
            "id": "coord:1",
            "x": 10.0,
            "y": 20.0,
            "z": 30.0,
            "space": "MNI"
        }

        existing = [
            {"id": "coord:2", "x": 10.5, "y": 20.0, "z": 30.0},  # Close enough for >=0.90 confidence
            {"id": "coord:3", "x": 50.0, "y": 50.0, "z": 50.0}   # Too far
        ]

        matches = matcher.match_node(candidate, "Coordinate", existing)

        assert len(matches) > 0
        assert matches[0].target_node_id == "coord:2"
        assert matches[0].method == "spatial"
        assert 0.9 < matches[0].confidence < 1.0  # Confidence decreases with distance

    def test_no_match_below_threshold(self):
        """Test that low-confidence matches are filtered out."""
        matcher = UnifiedNodeMatcher()

        candidate = {
            "id": "test:task",
            "label": "completely different task"
        }

        existing = [
            {"id": "cogat:other", "label": "unrelated paradigm"}
        ]

        matches = matcher.match_node(candidate, "Task", existing)

        # Should have no matches above threshold
        assert len(matches) == 0

    def test_canonical_selection(self):
        """Test canonical node selection with source priority."""
        matcher = UnifiedNodeMatcher()

        # Mock graph DB
        class MockDB:
            def __init__(self):
                self.graph = type('obj', (object,), {'degree': lambda x: 5})()

            def get_node(self, nid):
                return {"id": nid, "label": "test"}

        db = MockDB()

        # cogat should be selected over custom per priority rules
        node_ids = ["custom:task1", "cogat:task2", "bids:task3"]
        canonical = matcher.select_canonical(node_ids, "Task", db)

        assert canonical == "cogat:task2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
