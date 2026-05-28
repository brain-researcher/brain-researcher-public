"""Tests for query history management."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_researcher.services.agent.history import QueryHistory, get_history_manager


class TestQueryHistory:
    """Test QueryHistory class functionality."""

    @pytest.fixture
    def temp_history_dir(self):
        """Create a temporary directory for history files."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def history(self, temp_history_dir):
        """Create a QueryHistory instance with temp directory."""
        return QueryHistory(history_dir=temp_history_dir)

    def test_initialization(self, temp_history_dir):
        """Test history manager initialization."""
        history = QueryHistory(history_dir=temp_history_dir)
        assert history.history_dir == Path(temp_history_dir)
        assert history.history_dir.exists()

    def test_add_query(self, history):
        """Test adding a query to history."""
        user_id = "test_user"
        query_text = "hippocampus memory"
        query_params = {"retrieval_mode": "semantic", "top_k": 10}
        results = [
            {"id": "1", "title": "Paper 1", "source": "pubmed"},
            {"id": "2", "title": "Paper 2", "source": "pubmed"},
        ]

        query_id = history.add_query(user_id, query_text, query_params, results)

        assert query_id  # Should return a valid ID

        # Check that history was saved
        user_history = history.get_user_history(user_id)
        assert len(user_history) == 1

        record = user_history[0]
        assert record["query_id"] == query_id
        assert record["query_text"] == query_text
        assert record["query_params"] == query_params
        assert record["results_count"] == 2
        assert record["feedback"] is None

    def test_add_feedback(self, history):
        """Test adding feedback to a query."""
        user_id = "test_user"

        # First add a query
        query_id = history.add_query(
            user_id, "test query", {}, [{"id": "1", "title": "Test"}]
        )

        # Add feedback
        success = history.add_feedback(user_id, query_id, 4, "Great results!")
        assert success

        # Check feedback was saved
        user_history = history.get_user_history(user_id)
        record = user_history[0]
        assert record["feedback"]["rating"] == 4
        assert record["feedback"]["comment"] == "Great results!"
        assert record["feedback_timestamp"] is not None

    def test_invalid_feedback(self, history):
        """Test handling of invalid feedback."""
        user_id = "test_user"

        # Add a query
        query_id = history.add_query(user_id, "test", {}, [])

        # Invalid rating
        success = history.add_feedback(user_id, query_id, 0, "Bad")
        assert not success

        success = history.add_feedback(user_id, query_id, 6, "Bad")
        assert not success

        # Non-existent query
        success = history.add_feedback(user_id, "fake_id", 3, "OK")
        assert not success

    def test_get_user_history(self, history):
        """Test retrieving user history with pagination."""
        user_id = "test_user"

        # Add multiple queries
        for i in range(15):
            history.add_query(user_id, f"query {i}", {"num": i}, [{"id": str(i)}])

        # Test pagination
        page1 = history.get_user_history(user_id, limit=10, offset=0)
        assert len(page1) == 10
        assert page1[0]["query_text"] == "query 14"  # Newest first

        page2 = history.get_user_history(user_id, limit=10, offset=10)
        assert len(page2) == 5
        assert page2[0]["query_text"] == "query 4"

    def test_user_statistics(self, history):
        """Test user statistics calculation."""
        user_id = "test_user"

        # Empty stats
        stats = history.get_user_statistics(user_id)
        assert stats["total_queries"] == 0
        assert stats["average_rating"] is None

        # Add queries with different types
        query_id1 = history.add_query(user_id, "q1", {"retrieval_mode": "semantic"}, [])
        query_id2 = history.add_query(user_id, "q2", {"retrieval_mode": "spatial"}, [])
        query_id3 = history.add_query(user_id, "q3", {"retrieval_mode": "semantic"}, [])

        # Add feedback to some
        history.add_feedback(user_id, query_id1, 5)
        history.add_feedback(user_id, query_id2, 3)

        stats = history.get_user_statistics(user_id)
        assert stats["total_queries"] == 3
        assert stats["queries_with_feedback"] == 2
        assert stats["average_rating"] == 4.0
        assert stats["feedback_rate"] == pytest.approx(66.7, 0.1)
        assert stats["queries_by_type"]["semantic"] == 2
        assert stats["queries_by_type"]["spatial"] == 1
        assert len(stats["recent_activity"]) == 3

    def test_global_statistics(self, history):
        """Test global statistics across users."""
        # Add data for multiple users
        for user_num in range(3):
            user_id = f"user_{user_num}"
            for query_num in range(5):
                query_id = history.add_query(user_id, f"query {query_num}", {}, [])
                if query_num < 2:  # Add feedback to first 2 queries
                    history.add_feedback(user_id, query_id, 4)

        stats = history.get_global_statistics()
        assert stats["total_users"] == 3
        assert stats["total_queries"] == 15
        assert stats["total_feedback"] == 6
        assert stats["average_rating"] == 4.0
        assert stats["feedback_rate"] == 40.0

    def test_clear_user_history(self, history):
        """Test clearing user history."""
        user_id = "test_user"

        # Add some queries
        for i in range(5):
            history.add_query(user_id, f"query {i}", {}, [])

        # Clear history
        success = history.clear_user_history(user_id)
        assert success

        # Check it's empty
        user_history = history.get_user_history(user_id)
        assert len(user_history) == 0

        # Check backup was created
        backup_files = list(
            history.history_dir.glob(f"user_{user_id}_history.json.backup_*")
        )
        assert len(backup_files) == 1

    def test_corrupted_history_handling(self, history, temp_history_dir):
        """Test handling of corrupted history files."""
        user_id = "test_user"

        # Create a corrupted history file
        file_path = Path(temp_history_dir) / f"user_{user_id}_history.json"
        file_path.write_text("invalid json {")

        # Should handle gracefully
        user_history = history._load_user_history(user_id)
        assert user_history == []

        # Check corrupted file was backed up
        backup_files = list(Path(temp_history_dir).glob("*.corrupted"))
        assert len(backup_files) == 1

    def test_history_size_limit(self, history):
        """Test that history is limited to 1000 queries."""
        user_id = "test_user"

        # Add 1001 queries
        for i in range(1001):
            history.add_query(user_id, f"query {i}", {}, [])

        # Check only 1000 are kept
        user_history = history._load_user_history(user_id)
        assert len(user_history) == 1000

        # Newest should be first
        assert user_history[0]["query_text"] == "query 1000"

    def test_thread_safety(self, history):
        """Test thread-safe operations."""
        import threading
        import time

        user_id = "test_user"
        errors = []

        def add_queries():
            try:
                for i in range(10):
                    history.add_query(
                        user_id,
                        f"query from thread {threading.current_thread().name} - {i}",
                        {},
                        [],
                    )
                    time.sleep(0.001)  # Small delay to increase chance of conflicts
            except Exception as e:
                errors.append(e)

        # Run multiple threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=add_queries, name=f"Thread-{i}")
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check no errors occurred
        assert len(errors) == 0

        # Check all queries were saved
        user_history = history._load_user_history(user_id)
        assert len(user_history) == 30

    def test_results_summary(self, history):
        """Test results summary generation."""
        results = [
            {"id": "1", "title": "Long title " * 20, "source": "pubmed"},
            {"id": "2", "title": "Paper 2", "source": "pubmed"},
            {"id": "3", "title": "Paper 3", "source": "nimare"},
            {"id": "4", "title": "Paper 4", "source": "nimare"},
            {"id": "5", "title": "Paper 5", "source": "unknown"},
        ]

        summary = history._summarize_results(results)

        assert summary["count"] == 5
        assert summary["sources"]["pubmed"] == 2
        assert summary["sources"]["nimare"] == 2
        assert summary["sources"]["unknown"] == 1
        assert len(summary["top_papers"]) == 3

        # Check title truncation
        assert summary["top_papers"][0]["title"].endswith("...")
        assert len(summary["top_papers"][0]["title"]) == 103  # 100 + "..."


def test_get_history_manager():
    """Test global history manager singleton."""
    manager1 = get_history_manager()
    manager2 = get_history_manager()

    assert manager1 is manager2  # Should be same instance


@patch.dict(os.environ, {"HISTORY_DIR": "/custom/history/path"})
def test_custom_history_dir():
    """Test custom history directory from environment."""
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        history = QueryHistory()
        assert str(history.history_dir) == "/custom/history/path"
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
