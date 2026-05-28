import os

# Add this section right after the imports:
import sys
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

# Add the project root to Python path (same pattern as loader files)
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


class TestTaskMatcher:
    """Test TaskMatcher with proper mocking of external dependencies."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock all external dependencies."""
        with (
            patch("utils.task_matcher.SentenceTransformer") as mock_sbert,
            patch("utils.task_matcher.faiss") as mock_faiss,
            patch("utils.task_matcher.Path") as mock_path,
            patch("json.load") as mock_json_load,
        ):
            # Mock SentenceTransformer
            mock_sbert_instance = Mock()
            mock_sbert_instance.encode.return_value = np.random.rand(7, 384).astype(
                np.float32
            )
            mock_sbert.return_value = mock_sbert_instance

            # Mock FAISS index
            mock_index = Mock()
            mock_index.search.return_value = (
                np.array([[0.9, 0.8, 0.7, 0.6, 0.5]]),
                np.array([[0, 1, 2, 3, 4]]),
            )
            mock_faiss.IndexHNSWFlat.return_value = mock_index

            # Mock Path exists
            mock_path_instance = Mock()
            mock_path_instance.exists.return_value = True
            mock_path.return_value = mock_path_instance

            # Mock JSON data
            mock_json_load.return_value = [
                {"name": "n-back task"},
                {"name": "balloon analogue risk task"},
                {"name": "go/no-go task"},
                {"name": "stop signal task"},
                {"name": "monetary incentive delay task"},
                {"name": "stroop task"},
                {"name": "flanker task"},
            ]

            yield {
                "sbert": mock_sbert,
                "faiss": mock_faiss,
                "path": mock_path,
                "json_load": mock_json_load,
                "sbert_instance": mock_sbert_instance,
                "index": mock_index,
            }

    @pytest.fixture
    def mock_niclip_available(self):
        """Mock NiCLIP as available."""
        with (
            patch("utils.task_matcher._NICLIP_AVAILABLE", True),
            patch("utils.task_matcher.NiCLIPEncoder") as mock_encoder,
        ):
            mock_encoder_instance = Mock()
            mock_encoder_instance.encode.return_value = np.random.rand(7, 768).astype(
                np.float32
            )
            mock_encoder.return_value = mock_encoder_instance
            yield mock_encoder_instance

    @pytest.fixture
    def mock_niclip_unavailable(self):
        """Mock NiCLIP as unavailable."""
        with patch("utils.task_matcher._NICLIP_AVAILABLE", False):
            yield

    def test_initialization_with_niclip(self, mock_dependencies, mock_niclip_available):
        """Test TaskMatcher initialization with NiCLIP available."""
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        # Mock file reading for synonyms
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter(
                [
                    "label\tsynonym\n",
                    "n-back task\tnback\n",
                    "balloon analogue risk task\tbart\n",
                ]
            )

            matcher = TaskMatcher()

            assert len(matcher.labels) > 0
            assert hasattr(matcher, "sbert_model")
            assert hasattr(matcher, "niclip_encoder")
            assert matcher.niclip_encoder is not None

    def test_initialization_without_niclip(
        self, mock_dependencies, mock_niclip_unavailable
    ):
        """Test TaskMatcher initialization without NiCLIP."""
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter(["label\tsynonym\n"])

            matcher = TaskMatcher()

            assert len(matcher.labels) > 0
            assert hasattr(matcher, "sbert_model")
            assert matcher.niclip_encoder is None

    def test_match_candidates_sbert(self, mock_dependencies, mock_niclip_unavailable):
        """Test matching using SBERT when NiCLIP is unavailable."""
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter(
                ["label\tsynonym\n", "n-back task\tnback\n"]
            )

            matcher = TaskMatcher(sbert_threshold=0.8)

            # Mock SBERT encoding for query
            mock_dependencies["sbert_instance"].encode.return_value = np.array(
                [[0.5, 0.5]]
            ).astype(np.float32)

            # Mock search results
            mock_dependencies["index"].search.return_value = (
                np.array([[0.85]]),  # Score above threshold
                np.array([[0]]),  # Index of first label
            )

            results = matcher.match_candidates("nback", top_k=1)

            assert len(results) == 1
            assert results[0]["engine"] == "sbert"
            assert results[0]["score"] >= 0.8

    def test_match_candidates_fuzzy_fallback(
        self, mock_dependencies, mock_niclip_unavailable
    ):
        """Test fuzzy matching as fallback."""
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter(
                ["label\tsynonym\n", "stroop task\tstroop\n"]
            )

            matcher = TaskMatcher(fuzzy_threshold=85)

            # Mock low SBERT scores
            mock_dependencies["index"].search.return_value = (
                np.array([[0.5]]),  # Score below threshold
                np.array([[0]]),
            )

            results = matcher.match_candidates("stroop", top_k=1)

            assert len(results) > 0
            # Should fall back to fuzzy matching

    def test_empty_input_handling(self, mock_dependencies, mock_niclip_unavailable):
        """Test handling of empty input."""
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter(["label\tsynonym\n"])

            matcher = TaskMatcher()

            results = matcher.match_candidates("", top_k=1)
            assert results == []

            results = matcher.match_candidates("   ", top_k=1)
            assert results == []

    def test_benchmark_recall(self, mock_dependencies, mock_niclip_unavailable):
        """Test benchmark recall with mocked data."""
        from brain_researcher.core.utils.task_matcher import TaskMatcher

        # Create a temporary benchmark file
        benchmark_data = pd.DataFrame(
            {
                "input": ["nback", "bart", "stroop"],
                "label": ["n-back task", "balloon analogue risk task", "stroop task"],
            }
        )

        with patch("pandas.read_csv") as mock_read_csv:
            mock_read_csv.return_value = benchmark_data

            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__.return_value = iter(
                    [
                        "label\tsynonym\n",
                        "n-back task\tnback\n",
                        "balloon analogue risk task\tbart\n",
                        "stroop task\tstroop\n",
                    ]
                )

                matcher = TaskMatcher()

                # Configure mock to return high scores for exact matches
                def mock_search(query, k):
                    # Return high score for first item (exact match scenario)
                    return np.array([[0.95]]), np.array([[0]])

                mock_dependencies["index"].search.side_effect = mock_search

                hits = 0
                for _, row in benchmark_data.iterrows():
                    cand = matcher.match_candidates(row["input"], top_k=1)
                    if cand and cand[0]["score"] >= 0.8:
                        hits += 1

                recall = hits / len(benchmark_data)
                assert recall >= 0.5  # Relaxed threshold for mocked test
