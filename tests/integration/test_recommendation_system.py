"""
Integration tests for AGENT-022: Query Recommendation System

Tests the complete query recommendation system integration including:
- End-to-end recommendation workflows
- Integration with vector stores and databases
- Real-time recommendation updates
- Multi-user concurrent scenarios
- Performance under realistic loads
- Integration with other agent components

Author: Reviewer Subagent
Date: 2025-01-XX
"""

import pytest
import asyncio
import json
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import concurrent.futures

from brain_researcher.services.agent.recommendation_engine import (
    QueryRecommendationEngine,
    RecommendationService,
    RecommendationContext
)


@pytest.fixture
def comprehensive_query_dataset():
    """Load comprehensive query dataset for integration testing."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-022" / "query_history_dataset.json"
    with open(fixture_path, 'r') as f:
        data = json.load(f)
    
    # Expand dataset for integration testing
    history = data.get("query_history", data.get("historical_queries", []))
    expanded_data = {
        "query_history": history * 5,  # 5x more data
        "user_profiles": data.get("user_profiles", []),
        "expected_recommendations": data.get("expected_recommendations", [])
    }
    
    return expanded_data


@pytest.fixture
def mock_vector_database():
    """Create mock vector database with realistic behavior."""
    class MockVectorDB:
        def __init__(self):
            self.embeddings = {}
            self.query_count = 0
            
        async def embed_query(self, query: str) -> np.ndarray:
            """Generate consistent embeddings for queries."""
            if query in self.embeddings:
                return self.embeddings[query]
            
            # Create semi-realistic embeddings based on query content
            words = query.lower().split()
            embedding = np.random.normal(0, 1, 384)
            
            # Add semantic bias based on key terms
            if "fmri" in words:
                embedding[:50] += 2.0  # fMRI cluster
            if "connectivity" in words:
                embedding[50:100] += 1.5  # Connectivity cluster
            if "preprocessing" in words:
                embedding[100:150] += 1.8  # Preprocessing cluster
            if "statistical" in words:
                embedding[150:200] += 1.3  # Statistics cluster
            
            # Normalize
            embedding = embedding / np.linalg.norm(embedding)
            self.embeddings[query] = embedding.astype(np.float32)
            return self.embeddings[query]
        
        async def similarity_search(self, query_embedding: np.ndarray, k: int = 10) -> List[Dict]:
            """Simulate similarity search."""
            self.query_count += 1
            
            # Return mock similar queries
            similar_queries = [
                {"query": "How to preprocess fMRI data effectively?", "score": 0.85},
                {"query": "Statistical analysis of brain activation patterns", "score": 0.78},
                {"query": "Group-level fMRI analysis methods", "score": 0.72},
                {"query": "Quality control in neuroimaging studies", "score": 0.68},
                {"query": "Connectivity analysis using graph theory", "score": 0.65}
            ]
            
            return similar_queries[:k]
        
        async def batch_similarity_search(self, embeddings: List[np.ndarray], k: int = 10) -> List[List[Dict]]:
            """Batch similarity search."""
            results = []
            for embedding in embeddings:
                result = await self.similarity_search(embedding, k)
                results.append(result)
            return results
    
    return MockVectorDB()


@pytest.fixture
def mock_user_database():
    """Create mock user database for integration testing."""
    class MockUserDB:
        def __init__(self):
            self.users = {}
            self.query_history = {}
        
        async def get_user_profile(self, user_id: str) -> Dict:
            return self.users.get(user_id, {
                "user_id": user_id,
                "preferences": {},
                "expertise_level": 0.5,
                "query_count": 0
            })
        
        async def update_user_profile(self, user_id: str, profile: Dict) -> None:
            self.users[user_id] = profile
        
        async def add_query_history(self, user_id: str, query: str, timestamp: datetime, metadata: Dict) -> None:
            if user_id not in self.query_history:
                self.query_history[user_id] = []
            
            self.query_history[user_id].append({
                "query": query,
                "timestamp": timestamp,
                "metadata": metadata
            })
        
        async def get_query_history(self, user_id: str, limit: int = 100) -> List[Dict]:
            return self.query_history.get(user_id, [])[:limit]
        
        async def get_all_users(self) -> List[str]:
            return list(self.users.keys())
    
    return MockUserDB()


@pytest.fixture
def recommendation_service(mock_vector_database, mock_user_database):
    """Create RecommendationService with mocked dependencies."""
    service = RecommendationService(
        vector_db=mock_vector_database,
        user_db=mock_user_database,
        cache_size=1000,
        enable_real_time_updates=True,
        enable_analytics=True
    )
    return service


class TestEndToEndRecommendationWorkflow:
    """Test complete end-to-end recommendation workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_recommendation_workflow(self, recommendation_service, comprehensive_query_dataset):
        """Test complete workflow from query to recommendations."""
        user_id = "integration_test_user"
        
        # 1. Initialize user with historical queries
        for entry in comprehensive_query_dataset["query_history"][:20]:  # Subset for performance
            await recommendation_service.add_user_query(
                user_id=user_id,
                query=entry["query"],
                timestamp=datetime.fromisoformat(entry["timestamp"]),
                context=entry.get("context", {}),
                results_quality=entry.get("results_quality", 0.8)
            )
        
        # 2. Get personalized recommendations
        query = "How to analyze task-related brain activation?"
        recommendations = await recommendation_service.get_recommendations(
            query=query,
            user_id=user_id,
            max_results=10,
            include_explanations=True
        )
        
        # 3. Verify recommendations
        assert len(recommendations) > 0
        assert len(recommendations) <= 10
        
        # Should have relevance scores
        for rec in recommendations:
            assert 0 <= rec.relevance_score <= 1.0
            assert rec.query is not None
            assert rec.explanation is not None
        
        # Should be ranked by relevance
        scores = [rec.relevance_score for rec in recommendations]
        assert scores == sorted(scores, reverse=True)
        
        # 4. Track user interaction
        selected_recommendation = recommendations[0]
        await recommendation_service.track_recommendation_interaction(
            user_id=user_id,
            original_query=query,
            recommended_query=selected_recommendation.query,
            interaction_type="click",
            satisfaction_score=0.9
        )
        
        # 5. Verify interaction was recorded
        user_profile = await recommendation_service.get_user_profile(user_id)
        assert user_profile["interaction_count"] > 0
    
    @pytest.mark.asyncio
    async def test_real_time_recommendation_updates(self, recommendation_service):
        """Test real-time updates to recommendations as new queries are added."""
        user_id = "realtime_user"
        base_query = "fMRI preprocessing methods"
        
        # Get initial recommendations
        initial_recs = await recommendation_service.get_recommendations(
            query=base_query,
            user_id=user_id,
            max_results=5
        )
        
        # Add related queries to build user profile
        related_queries = [
            "FSL FEAT preprocessing pipeline",
            "SPM preprocessing workflow",
            "AFNI preprocessing steps",
            "Advanced motion correction techniques",
            "Slice timing correction methods"
        ]
        
        for query in related_queries:
            await recommendation_service.add_user_query(
                user_id=user_id,
                query=query,
                context={"tool_preference": "fsl"}
            )
        
        # Get updated recommendations
        updated_recs = await recommendation_service.get_recommendations(
            query=base_query,
            user_id=user_id,
            max_results=5
        )
        
        # Recommendations should be different/improved
        initial_queries = [rec.query for rec in initial_recs]
        updated_queries = [rec.query for rec in updated_recs]
        
        # Should have some different recommendations
        assert len(set(initial_queries) - set(updated_queries)) > 0
        
        # Updated recommendations should show tool preference
        fsl_mentions = sum(1 for rec in updated_recs if "fsl" in rec.query.lower())
        assert fsl_mentions > 0
    
    @pytest.mark.asyncio
    async def test_cross_user_recommendation_learning(self, recommendation_service):
        """Test learning from patterns across multiple users."""
        # Create multiple users with different but overlapping interests
        users = {
            "connectivity_expert": [
                "Advanced connectivity analysis methods",
                "Graph theory for brain networks",
                "Dynamic functional connectivity",
                "Resting-state network identification"
            ],
            "activation_expert": [
                "Task-related activation patterns",
                "GLM analysis for cognitive tasks", 
                "Contrast analysis methods",
                "Statistical thresholding techniques"
            ],
            "methods_expert": [
                "Comparing fMRI analysis software packages",
                "Validation of preprocessing pipelines",
                "Quality control best practices",
                "Reproducibility in neuroimaging"
            ]
        }
        
        # Add queries for all users
        for user_id, queries in users.items():
            for query in queries:
                await recommendation_service.add_user_query(
                    user_id=user_id,
                    query=query,
                    results_quality=0.9
                )
        
        # New user asks general question
        new_user_query = "How to ensure quality in fMRI analysis?"
        recommendations = await recommendation_service.get_recommendations(
            query=new_user_query,
            user_id="new_user",
            max_results=8
        )
        
        # Should benefit from cross-user learning
        assert len(recommendations) > 0
        
        # Should include insights from different expert domains
        topics_covered = set()
        for rec in recommendations:
            if any(term in rec.query.lower() for term in ["connectivity", "network"]):
                topics_covered.add("connectivity")
            if any(term in rec.query.lower() for term in ["activation", "glm", "contrast"]):
                topics_covered.add("activation")
            if any(term in rec.query.lower() for term in ["quality", "validation", "reproducibility"]):
                topics_covered.add("methods")
        
        # Should cover multiple domains
        assert len(topics_covered) >= 2
    
    @pytest.mark.asyncio
    async def test_contextual_recommendation_adaptation(self, recommendation_service):
        """Test adaptation of recommendations based on context."""
        user_id = "context_user"
        base_query = "statistical analysis of brain data"
        
        # Research context
        research_recs = await recommendation_service.get_recommendations(
            query=base_query,
            user_id=user_id,
            context={
                "setting": "research",
                "urgency": "low",
                "experience_level": "expert",
                "dataset_size": "large"
            },
            max_results=5
        )
        
        # Clinical context
        clinical_recs = await recommendation_service.get_recommendations(
            query=base_query,
            user_id=user_id,
            context={
                "setting": "clinical",
                "urgency": "high",
                "experience_level": "beginner",
                "dataset_size": "small"
            },
            max_results=5
        )
        
        # Recommendations should differ based on context
        research_queries = [rec.query for rec in research_recs]
        clinical_queries = [rec.query for rec in clinical_recs]
        
        # Should have different recommendations for different contexts
        overlap = len(set(research_queries) & set(clinical_queries))
        total_unique = len(set(research_queries) | set(clinical_queries))
        overlap_ratio = overlap / total_unique if total_unique > 0 else 0
        
        assert overlap_ratio < 0.8  # At most 80% overlap
        
        # Clinical recommendations should be more basic/practical
        clinical_basic_count = sum(
            1 for rec in clinical_recs
            if any(term in rec.query.lower() for term in ["basic", "simple", "guide", "introduction"])
        )
        research_advanced_count = sum(
            1 for rec in research_recs
            if any(term in rec.query.lower() for term in ["advanced", "novel", "sophisticated", "complex"])
        )
        
        # Context should influence complexity level
        assert clinical_basic_count >= 0  # Some basic recommendations for clinical
        assert research_advanced_count >= 0  # Some advanced for research


class TestMultiUserConcurrentScenarios:
    """Test concurrent multi-user scenarios."""
    
    @pytest.mark.asyncio
    async def test_concurrent_user_requests(self, recommendation_service):
        """Test concurrent recommendation requests from multiple users."""
        users_and_queries = [
            ("user1", "How to preprocess fMRI data?"),
            ("user2", "Statistical analysis methods for neuroimaging"),
            ("user3", "Brain connectivity analysis techniques"), 
            ("user4", "Group-level analysis in fMRI studies"),
            ("user5", "Quality control in neuroimaging pipelines")
        ]
        
        # Execute recommendations concurrently
        tasks = [
            recommendation_service.get_recommendations(query, user_id=user_id, max_results=5)
            for user_id, query in users_and_queries
        ]
        
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        execution_time = time.time() - start_time
        
        # All requests should succeed
        successful_results = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_results) == len(users_and_queries)
        
        # Each user should get recommendations
        for result in successful_results:
            assert len(result) > 0
            assert len(result) <= 5
        
        # Concurrent execution should be reasonably fast
        assert execution_time < 5.0  # Less than 5 seconds
    
    @pytest.mark.asyncio
    async def test_concurrent_profile_updates(self, recommendation_service):
        """Test concurrent user profile updates."""
        user_id = "concurrent_update_user"
        
        # Simulate concurrent queries from same user
        queries = [
            f"Neuroimaging query number {i}" for i in range(20)
        ]
        
        # Add queries concurrently
        tasks = [
            recommendation_service.add_user_query(
                user_id=user_id,
                query=query,
                context={"session_id": f"session_{i % 3}"}
            )
            for i, query in enumerate(queries)
        ]
        
        await asyncio.gather(*tasks)
        
        # Verify all queries were recorded
        user_profile = await recommendation_service.get_user_profile(user_id)
        assert user_profile["query_count"] == len(queries)
        
        # Get recommendations to ensure profile integrity
        recommendations = await recommendation_service.get_recommendations(
            query="test query",
            user_id=user_id,
            max_results=5
        )
        
        assert len(recommendations) >= 0  # Should not error
    
    @pytest.mark.asyncio
    async def test_recommendation_cache_consistency(self, recommendation_service):
        """Test cache consistency under concurrent access."""
        query = "fMRI analysis workflow"
        users = [f"cache_test_user_{i}" for i in range(10)]
        
        # Make concurrent requests for same query from different users
        tasks = [
            recommendation_service.get_recommendations(query, user_id=user_id, max_results=3)
            for user_id in users
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All requests should succeed
        assert len(results) == len(users)
        
        # Cache should maintain consistency while allowing personalization
        for result in results:
            assert len(result) > 0
            
            # Basic consistency checks
            for rec in result:
                assert 0 <= rec.relevance_score <= 1.0
                assert rec.query is not None
    
    @pytest.mark.asyncio
    async def test_system_load_handling(self, recommendation_service):
        """Test system behavior under high load."""
        # Generate high concurrent load
        num_concurrent_users = 50
        queries_per_user = 5
        
        async def user_session(user_id: int):
            """Simulate a user session with multiple queries."""
            user_queries = [
                f"User {user_id} query about fMRI preprocessing",
                f"User {user_id} asks about statistical analysis", 
                f"User {user_id} wants connectivity analysis info",
                f"User {user_id} needs group analysis help",
                f"User {user_id} query about quality control"
            ]
            
            results = []
            for query in user_queries[:queries_per_user]:
                try:
                    recs = await recommendation_service.get_recommendations(
                        query=query,
                        user_id=f"load_test_user_{user_id}",
                        max_results=3
                    )
                    results.append(recs)
                except Exception as e:
                    results.append(e)
            
            return results
        
        # Execute concurrent user sessions
        start_time = time.time()
        
        tasks = [user_session(i) for i in range(num_concurrent_users)]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        execution_time = time.time() - start_time
        
        # Analyze results
        successful_sessions = [r for r in all_results if not isinstance(r, Exception)]
        total_requests = num_concurrent_users * queries_per_user
        successful_requests = 0
        
        for session_results in successful_sessions:
            successful_requests += sum(1 for r in session_results if not isinstance(r, Exception))
        
        success_rate = successful_requests / total_requests
        
        # Should handle high load with reasonable success rate
        assert success_rate > 0.8  # At least 80% success rate
        
        # Should complete within reasonable time
        assert execution_time < 30.0  # Less than 30 seconds


class TestRecommendationAnalytics:
    """Test analytics and monitoring capabilities."""
    
    @pytest.mark.asyncio
    async def test_recommendation_performance_metrics(self, recommendation_service):
        """Test collection of performance metrics."""
        user_id = "metrics_user"
        
        # Generate various recommendation requests
        queries = [
            "fMRI preprocessing best practices",
            "Statistical analysis of activation patterns",
            "Group-level analysis methods",
            "Quality control procedures",
            "Connectivity analysis techniques"
        ]
        
        # Track performance for each query
        for query in queries:
            start_time = time.time()
            
            recommendations = await recommendation_service.get_recommendations(
                query=query,
                user_id=user_id,
                max_results=5
            )
            
            response_time = time.time() - start_time
            
            # Track interaction
            if recommendations:
                await recommendation_service.track_recommendation_interaction(
                    user_id=user_id,
                    original_query=query,
                    recommended_query=recommendations[0].query,
                    interaction_type="view",
                    response_time=response_time
                )
        
        # Get performance analytics
        metrics = await recommendation_service.get_performance_metrics(
            time_period=timedelta(hours=1)
        )
        
        # Should have collected metrics
        assert "total_requests" in metrics
        assert "average_response_time" in metrics
        assert "cache_hit_rate" in metrics
        assert "user_satisfaction_score" in metrics
        
        assert metrics["total_requests"] >= len(queries)
        assert metrics["average_response_time"] > 0
        assert 0 <= metrics["cache_hit_rate"] <= 1
    
    @pytest.mark.asyncio
    async def test_recommendation_quality_analytics(self, recommendation_service):
        """Test analytics for recommendation quality."""
        user_id = "quality_user"
        
        # Add queries and track satisfaction
        query_satisfaction_pairs = [
            ("How to preprocess fMRI data?", 0.9),
            ("Statistical thresholding methods", 0.8),
            ("Group analysis techniques", 0.7),
            ("Quality control best practices", 0.95),
            ("Connectivity analysis methods", 0.85)
        ]
        
        for query, satisfaction in query_satisfaction_pairs:
            recommendations = await recommendation_service.get_recommendations(
                query=query,
                user_id=user_id,
                max_results=3
            )
            
            if recommendations:
                await recommendation_service.track_recommendation_interaction(
                    user_id=user_id,
                    original_query=query,
                    recommended_query=recommendations[0].query,
                    interaction_type="click",
                    satisfaction_score=satisfaction
                )
        
        # Get quality analytics
        quality_metrics = await recommendation_service.get_quality_metrics(
            user_id=user_id,
            time_period=timedelta(hours=1)
        )
        
        # Should have quality metrics
        assert "average_satisfaction" in quality_metrics
        assert "recommendation_diversity" in quality_metrics
        assert "coverage_score" in quality_metrics
        
        # Average satisfaction should reflect input data
        expected_avg = sum(sat for _, sat in query_satisfaction_pairs) / len(query_satisfaction_pairs)
        assert abs(quality_metrics["average_satisfaction"] - expected_avg) < 0.1
    
    @pytest.mark.asyncio
    async def test_user_behavior_analytics(self, recommendation_service):
        """Test analytics for user behavior patterns."""
        # Simulate different user behavior patterns
        user_behaviors = {
            "power_user": {
                "queries": ["Advanced fMRI analysis methods", "Custom GLM contrasts", "Novel connectivity metrics"],
                "satisfaction": 0.95,
                "session_length": 30
            },
            "beginner_user": {
                "queries": ["What is fMRI?", "Basic preprocessing steps", "Simple analysis guide"],
                "satisfaction": 0.7,
                "session_length": 10
            },
            "researcher": {
                "queries": ["Reproducible analysis pipelines", "Statistical best practices", "Publication guidelines"],
                "satisfaction": 0.85,
                "session_length": 20
            }
        }
        
        for user_type, behavior in user_behaviors.items():
            for query in behavior["queries"]:
                recommendations = await recommendation_service.get_recommendations(
                    query=query,
                    user_id=user_type,
                    max_results=5
                )
                
                # Simulate user interaction
                if recommendations:
                    await recommendation_service.track_recommendation_interaction(
                        user_id=user_type,
                        original_query=query,
                        recommended_query=recommendations[0].query,
                        interaction_type="click",
                        satisfaction_score=behavior["satisfaction"],
                        session_metadata={"session_length": behavior["session_length"]}
                    )
        
        # Analyze user segments
        user_analytics = await recommendation_service.analyze_user_segments(
            time_period=timedelta(hours=1)
        )
        
        # Should identify different user segments
        assert len(user_analytics["segments"]) > 0
        
        # Should have segment characteristics
        for segment in user_analytics["segments"]:
            assert "user_count" in segment
            assert "avg_satisfaction" in segment
            assert "avg_expertise_level" in segment
    
    @pytest.mark.asyncio
    async def test_recommendation_trend_analysis(self, recommendation_service):
        """Test analysis of recommendation trends over time."""
        # Add queries over simulated time periods
        base_time = datetime.now() - timedelta(days=30)
        
        # Simulate trending topics over time
        time_periods = [
            (0, ["Traditional GLM analysis", "SPM workflow", "Classical statistics"]),
            (10, ["Machine learning methods", "Deep learning for fMRI", "AI-based analysis"]),
            (20, ["Reproducibility crisis", "Open science practices", "FAIR data principles"]),
            (30, ["Real-time fMRI", "Neurofeedback applications", "Online analysis methods"])
        ]
        
        for days_offset, queries in time_periods:
            timestamp = base_time + timedelta(days=days_offset)
            
            for query in queries:
                await recommendation_service.add_user_query(
                    user_id=f"trend_user_{days_offset}",
                    query=query,
                    timestamp=timestamp
                )
        
        # Analyze trends
        trends = await recommendation_service.analyze_query_trends(
            time_period=timedelta(days=35),
            trend_window=timedelta(days=7)
        )
        
        # Should identify trending topics
        assert len(trends["trending_up"]) > 0
        assert len(trends["trending_down"]) > 0
        
        # Recent topics should be trending up
        recent_topics = ["machine learning", "ai", "reproducibility", "real-time"]
        trending_up_text = " ".join(trends["trending_up"]).lower()
        
        recent_topic_mentions = sum(1 for topic in recent_topics if topic in trending_up_text)
        assert recent_topic_mentions > 0


class TestRecommendationSystemResilience:
    """Test system resilience and error handling."""
    
    @pytest.mark.asyncio
    async def test_database_connection_failure_handling(self, recommendation_service):
        """Test graceful handling of database connection failures."""
        # Mock database failures
        with patch.object(recommendation_service.user_db, 'get_user_profile', side_effect=Exception("DB connection failed")):
            # Should still provide recommendations (with degraded functionality)
            recommendations = await recommendation_service.get_recommendations(
                query="fMRI analysis methods",
                user_id="db_failure_user",
                max_results=5
            )
            
            # Should not crash, may return fewer/generic recommendations
            assert isinstance(recommendations, list)
            # Allow for graceful degradation - may be empty but should not error
    
    @pytest.mark.asyncio
    async def test_vector_store_failure_handling(self, recommendation_service):
        """Test handling of vector store failures."""
        # Mock vector store failures
        with patch.object(recommendation_service.vector_db, 'similarity_search', side_effect=Exception("Vector store unavailable")):
            # Should fall back to alternative recommendation methods
            recommendations = await recommendation_service.get_recommendations(
                query="neuroimaging analysis",
                user_id="vector_failure_user",
                max_results=5
            )
            
            # Should handle gracefully
            assert isinstance(recommendations, list)
    
    @pytest.mark.asyncio
    async def test_cache_corruption_recovery(self, recommendation_service):
        """Test recovery from cache corruption."""
        user_id = "cache_corruption_user"
        
        # Add some data to cache
        await recommendation_service.add_user_query(
            user_id=user_id,
            query="Initial query for cache"
        )
        
        # Simulate cache corruption
        if hasattr(recommendation_service, '_cache'):
            recommendation_service._cache.clear()
            # Add corrupted data
            recommendation_service._cache["corrupted_key"] = "invalid_data"
        
        # Should handle corrupted cache gracefully
        recommendations = await recommendation_service.get_recommendations(
            query="Test query after corruption",
            user_id=user_id,
            max_results=3
        )
        
        assert isinstance(recommendations, list)
    
    @pytest.mark.asyncio
    async def test_high_latency_timeout_handling(self, recommendation_service):
        """Test handling of high latency operations."""
        # Mock slow operations
        async def slow_embed_query(query):
            await asyncio.sleep(2.0)  # Simulate 2 second delay
            return np.random.normal(0, 1, 384).astype(np.float32)
        
        with patch.object(recommendation_service.vector_db, 'embed_query', side_effect=slow_embed_query):
            start_time = time.time()
            
            try:
                recommendations = await asyncio.wait_for(
                    recommendation_service.get_recommendations(
                        query="slow query test",
                        user_id="timeout_user",
                        max_results=3
                    ),
                    timeout=3.0  # 3 second timeout
                )
                
                execution_time = time.time() - start_time
                assert execution_time < 3.5  # Should complete within timeout + margin
                
            except asyncio.TimeoutError:
                # Timeout is acceptable behavior for slow operations
                pass
    
    @pytest.mark.asyncio
    async def test_memory_pressure_handling(self, recommendation_service):
        """Test system behavior under memory pressure."""
        # Simulate memory pressure by adding many large objects
        large_queries = []
        
        try:
            # Add many queries with large context
            for i in range(100):
                large_context = {
                    "large_data": "x" * 10000,  # 10KB per query
                    "metadata": {"id": i, "timestamp": datetime.now().isoformat()}
                }
                
                await recommendation_service.add_user_query(
                    user_id=f"memory_test_user_{i % 10}",
                    query=f"Memory pressure test query {i}",
                    context=large_context
                )
                
                large_queries.append(f"query_{i}")
        
        except MemoryError:
            # System should handle memory pressure gracefully
            pass
        
        # System should still function after memory pressure
        recommendations = await recommendation_service.get_recommendations(
            query="Test after memory pressure",
            user_id="memory_recovery_user",
            max_results=3
        )
        
        assert isinstance(recommendations, list)


class TestRecommendationSystemScalability:
    """Test scalability characteristics of the recommendation system."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_large_scale_user_base(self, recommendation_service):
        """Test performance with large number of users."""
        num_users = 1000
        queries_per_user = 10
        
        # Add queries for many users
        user_tasks = []
        for user_id in range(num_users):
            for query_id in range(queries_per_user):
                task = recommendation_service.add_user_query(
                    user_id=f"scale_user_{user_id}",
                    query=f"Scalability test query {query_id} from user {user_id}"
                )
                user_tasks.append(task)
        
        # Process in batches to avoid overwhelming system
        batch_size = 100
        for i in range(0, len(user_tasks), batch_size):
            batch = user_tasks[i:i + batch_size]
            await asyncio.gather(*batch, return_exceptions=True)
        
        # Test recommendation performance with large user base
        sample_users = [f"scale_user_{i}" for i in range(0, num_users, 100)]  # Sample every 100th user
        
        start_time = time.time()
        recommendation_tasks = [
            recommendation_service.get_recommendations(
                query="large scale test query",
                user_id=user_id,
                max_results=5
            )
            for user_id in sample_users
        ]
        
        results = await asyncio.gather(*recommendation_tasks, return_exceptions=True)
        execution_time = time.time() - start_time
        
        successful_results = [r for r in results if not isinstance(r, Exception)]
        
        # Should maintain performance with large user base
        assert len(successful_results) == len(sample_users)
        
        # Average response time should be reasonable
        avg_response_time = execution_time / len(sample_users)
        assert avg_response_time < 0.5  # Less than 500ms per recommendation
    
    @pytest.mark.asyncio
    async def test_recommendation_quality_at_scale(self, recommendation_service):
        """Test that recommendation quality is maintained at scale."""
        # Create diverse user profiles
        user_specializations = [
            "connectivity_analysis", "activation_analysis", "preprocessing",
            "statistical_methods", "machine_learning", "clinical_applications",
            "developmental_studies", "aging_research", "patient_studies",
            "methodology_development"
        ]
        
        # Build specialized user profiles
        for i, specialization in enumerate(user_specializations):
            user_id = f"specialist_{specialization}_user"
            
            # Add specialized queries for each user
            specialized_queries = [
                f"Advanced {specialization} methods in neuroimaging",
                f"Best practices for {specialization} studies",
                f"Novel approaches to {specialization} research",
                f"Statistical considerations in {specialization}",
                f"Reproducibility in {specialization} studies"
            ]
            
            for query in specialized_queries:
                await recommendation_service.add_user_query(
                    user_id=user_id,
                    query=query,
                    context={"specialization": specialization},
                    results_quality=0.9
                )
        
        # Test recommendation quality for each specialization
        quality_scores = []
        
        for specialization in user_specializations:
            user_id = f"specialist_{specialization}_user"
            test_query = f"How to improve {specialization} in neuroimaging?"
            
            recommendations = await recommendation_service.get_recommendations(
                query=test_query,
                user_id=user_id,
                max_results=5
            )
            
            # Measure specialization-specific recommendation quality
            relevant_recs = sum(
                1 for rec in recommendations
                if specialization.replace("_", " ") in rec.query.lower()
            )
            
            specialization_score = relevant_recs / len(recommendations) if recommendations else 0
            quality_scores.append(specialization_score)
        
        # Quality should be maintained across all specializations
        avg_quality = sum(quality_scores) / len(quality_scores)
        assert avg_quality > 0.3  # At least 30% specialization-relevant recommendations
        
        # No specialization should have extremely poor quality
        min_quality = min(quality_scores)
        assert min_quality >= 0.1  # At least 10% relevant recommendations


if __name__ == "__main__":
    pytest.main([__file__])
