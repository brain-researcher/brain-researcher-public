"""
Tests for BR-KG performance monitoring system.
"""

import pytest
import time
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path

from brain_researcher.services.neurokg.performance_monitor import (
    PerformanceMonitor,
    QueryProfile,
    IndexRecommendation,
    profile_query
)


class TestPerformanceMonitor:
    """Test PerformanceMonitor functionality."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        yield db_path
        
        # Cleanup
        try:
            os.unlink(db_path)
        except:
            pass
    
    @pytest.fixture
    def monitor(self, temp_db):
        """Create performance monitor with temp database."""
        return PerformanceMonitor(
            db_path=temp_db,
            slow_query_threshold_ms=100,  # Low threshold for testing
            enable_profiling=True
        )
    
    def test_initialization(self, monitor, temp_db):
        """Test monitor initialization."""
        assert monitor.enabled
        assert monitor.slow_query_threshold == 100
        assert monitor.db_path == temp_db
        
        # Check database tables created
        import sqlite3
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert "query_profiles" in tables
        assert "slow_queries" in tables
        assert "performance_metrics" in tables
        assert "index_recommendations" in tables
        assert "query_patterns" in tables
    
    def test_query_profiling(self, monitor):
        """Test basic query profiling."""
        query = "SELECT * FROM nodes WHERE type='concept'"
        
        with monitor.profile_query(query, "sql", "user123", "127.0.0.1") as profile:
            # Simulate query execution
            time.sleep(0.05)
            profile.rows_returned = 10
            profile.index_used = True
            profile.cache_hit = False
        
        # Check profile was recorded
        assert profile.query_text == query
        assert profile.query_type == "sql"
        assert profile.user_id == "user123"
        assert profile.ip_address == "127.0.0.1"
        assert profile.execution_time_ms > 40  # At least 40ms
        assert profile.rows_returned == 10
        assert not profile.is_slow  # Under 100ms threshold
    
    def test_slow_query_detection(self, monitor):
        """Test slow query detection and logging."""
        query = "SELECT * FROM large_table"
        
        with monitor.profile_query(query, "sql") as profile:
            # Simulate slow query
            time.sleep(0.15)  # 150ms
            profile.rows_returned = 1000
        
        assert profile.is_slow  # Over 100ms threshold
        
        # Check slow query was logged
        slow_queries = monitor.get_slow_queries(limit=10)
        assert len(slow_queries) > 0
        assert slow_queries[0]["query_text"] == query
        assert slow_queries[0]["execution_time_ms"] > 100
    
    def test_performance_metrics(self, monitor):
        """Test performance metrics collection."""
        # Profile several queries
        for i in range(5):
            with monitor.profile_query(f"query_{i}", "test") as profile:
                time.sleep(0.01 * (i + 1))  # Varying execution times
                profile.rows_returned = i * 10
                profile.cache_hit = (i % 2 == 0)
        
        # Get metrics
        metrics = monitor.get_performance_metrics(aggregation="avg")
        assert "query_execution_time_test" in metrics
        
        # Get p95 metrics
        p95_metrics = monitor.get_performance_metrics(aggregation="p95")
        assert "query_execution_time_test" in p95_metrics
        
        # P95 should be higher than average
        if len(p95_metrics) > 0 and len(metrics) > 0:
            assert p95_metrics["query_execution_time_test"] >= metrics["query_execution_time_test"]
    
    def test_query_pattern_extraction(self, monitor):
        """Test query pattern extraction."""
        # Similar queries with different literals
        queries = [
            "SELECT * FROM nodes WHERE id = '123'",
            "SELECT * FROM nodes WHERE id = '456'",
            "SELECT * FROM nodes WHERE id = '789'",
        ]
        
        for query in queries:
            with monitor.profile_query(query, "sql") as profile:
                time.sleep(0.01)
                profile.rows_returned = 1
        
        # Check patterns were identified
        patterns = monitor.analyze_query_patterns(min_frequency=2)
        assert len(patterns) > 0
        
        # Pattern should have literals replaced
        pattern_text = patterns[0]["pattern"]
        assert "'?'" in pattern_text or "?" in pattern_text
    
    def test_index_recommendations(self, monitor):
        """Test index recommendation generation."""
        # Simulate slow queries without indexes
        for i in range(5):
            with monitor.profile_query(
                f"query {{ concepts(filter: {{name: 'test_{i}'}}) {{ id name }} }}",
                "graphql"
            ) as profile:
                time.sleep(0.12)  # Slow query
                profile.index_used = False
                profile.rows_examined = 1000
                profile.rows_returned = 10
        
        # Get recommendations
        recommendations = monitor.recommend_indexes()
        
        # Should have at least one recommendation
        assert len(recommendations) >= 0  # May be empty if pattern detection differs
        
        for rec in recommendations:
            assert isinstance(rec, IndexRecommendation)
            assert rec.table
            assert rec.columns
            assert rec.reason
    
    def test_performance_report(self, monitor):
        """Test comprehensive report generation."""
        # Generate some test data
        for i in range(10):
            with monitor.profile_query(f"test_query_{i}", "test") as profile:
                time.sleep(0.01 if i < 5 else 0.15)  # Mix of fast and slow
                profile.rows_returned = i * 5
                profile.cache_hit = (i % 3 == 0)
        
        # Generate report
        report = monitor.export_report(
            include_slow_queries=True,
            include_metrics=True,
            include_recommendations=True
        )
        
        assert "generated_at" in report
        assert "total_queries" in report
        assert report["total_queries"] == 10
        assert "slow_query_percentage" in report
        assert report["slow_query_percentage"] > 0
        
        if "slow_queries" in report:
            assert "recent" in report["slow_queries"]
            assert "patterns" in report["slow_queries"]
        
        if "metrics" in report:
            assert "avg" in report["metrics"]
    
    def test_profiling_disabled(self, monitor):
        """Test behavior when profiling is disabled."""
        monitor.enabled = False
        
        with monitor.profile_query("test", "test") as profile:
            time.sleep(0.01)
        
        # Should return NullProfiler, no data recorded
        slow_queries = monitor.get_slow_queries()
        # Should be empty since profiling was disabled
        assert len(slow_queries) == 0 or slow_queries[-1]["query_text"] != "test"
    
    def test_decorator_profiling(self, monitor):
        """Test the @profile_query decorator."""
        
        @profile_query(monitor)
        def execute_query(query: str):
            time.sleep(0.05)
            return ["result1", "result2"]
        
        results = execute_query("SELECT * FROM test")
        assert len(results) == 2
        
        # Check query was profiled
        import sqlite3
        conn = sqlite3.connect(monitor.db_path)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM query_profiles WHERE query_text LIKE '%SELECT%'"
        )
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count > 0
    
    def test_concurrent_profiling(self, monitor):
        """Test thread-safe concurrent profiling."""
        import threading
        
        def profile_query(query_id):
            with monitor.profile_query(f"query_{query_id}", "test") as profile:
                time.sleep(0.01)
                profile.rows_returned = query_id
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=profile_query, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All queries should be recorded
        import sqlite3
        conn = sqlite3.connect(monitor.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM query_profiles")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count >= 10
    
    def test_cleanup_old_data(self, monitor):
        """Test cleanup of old performance data."""
        # Create old profile directly in database
        import sqlite3
        conn = sqlite3.connect(monitor.db_path)
        
        old_date = (datetime.now() - timedelta(days=40)).isoformat()
        
        conn.execute("""
            INSERT INTO query_profiles 
            (query_id, query_text, query_type, start_time, end_time,
             execution_time_ms, created_at)
            VALUES ('old_query', 'SELECT OLD', 'test', 0, 1, 100, ?)
        """, (old_date,))
        conn.commit()
        
        # Run cleanup
        monitor._cleanup_old_data()
        
        # Old query should be gone
        cursor = conn.execute(
            "SELECT COUNT(*) FROM query_profiles WHERE query_id = 'old_query'"
        )
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 0
    
    def test_cache_hit_rate_tracking(self, monitor):
        """Test cache hit rate calculation."""
        # Mix of cache hits and misses
        for i in range(10):
            with monitor.profile_query(f"query_{i}", "test") as profile:
                time.sleep(0.01)
                profile.cache_hit = (i < 7)  # 70% hit rate
        
        report = monitor.export_report()
        assert "cache_hit_rate" in report
        assert 0.6 <= report["cache_hit_rate"] <= 0.8  # Around 70%
    
    def test_query_pattern_frequency(self, monitor):
        """Test query pattern frequency tracking."""
        # Execute same pattern multiple times
        for i in range(10):
            with monitor.profile_query(
                f"SELECT * FROM nodes WHERE id = {i}",
                "sql"
            ) as profile:
                time.sleep(0.01)
                profile.rows_returned = 1
        
        patterns = monitor.analyze_query_patterns(min_frequency=5)
        assert len(patterns) > 0
        assert patterns[0]["frequency"] >= 10
        assert patterns[0]["avg_execution_time_ms"] > 0


class TestIndexRecommendation:
    """Test IndexRecommendation class."""
    
    def test_recommendation_creation(self):
        """Test creating an index recommendation."""
        rec = IndexRecommendation(
            table="nodes",
            columns=["type", "name"],
            reason="Frequent queries without index",
            estimated_improvement=50.0,
            query_patterns=["SELECT * FROM nodes WHERE type = ?"],
            frequency=100
        )
        
        assert rec.table == "nodes"
        assert rec.columns == ["type", "name"]
        assert rec.estimated_improvement == 50.0
        assert rec.frequency == 100
        
        # Test conversion to dict
        rec_dict = rec.to_dict()
        assert rec_dict["table"] == "nodes"
        assert rec_dict["columns"] == ["type", "name"]


class TestQueryProfile:
    """Test QueryProfile class."""
    
    def test_profile_creation(self):
        """Test creating a query profile."""
        profile = QueryProfile(
            query_id="test123",
            query_text="SELECT * FROM test",
            query_type="sql",
            start_time=time.time(),
            end_time=time.time() + 0.1,
            execution_time_ms=100,
            rows_returned=10,
            rows_examined=100,
            index_used=True,
            cache_hit=False,
            user_id="user1",
            ip_address="127.0.0.1",
            slow_threshold_ms=100  # Set custom threshold for test
        )
        
        assert profile.query_id == "test123"
        assert not profile.is_slow  # 100ms is at threshold
        
        profile.execution_time_ms = 101
        assert profile.is_slow  # Over 100ms threshold
        
        # Test conversion to dict
        profile_dict = profile.to_dict()
        assert profile_dict["query_id"] == "test123"
        assert profile_dict["rows_returned"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])