"""
Simplified unit tests for AGENT-022: Query Recommendation System

Tests the QueryRecommendationEngine class with focus on actually implemented functionality.
"""

import pytest
import numpy as np
from unittest.mock import Mock
from brain_researcher.services.agent.recommendation_engine import (
    QueryRecommendationEngine,
    SimilarityEngine,
    PatternAnalyzer,
    QueryPattern,
    UserProfile,
    Recommendation
)


class TestQueryRecommendationEngineBasic:
    """Basic tests for QueryRecommendationEngine."""
    
    @pytest.fixture
    def mock_embedding_model(self):
        """Create mock embedding model."""
        model = Mock()
        model.embed_query.return_value = np.random.normal(0, 1, 384).astype(np.float32)
        return model
    
    @pytest.fixture
    def mock_history_store(self):
        """Create mock history store."""
        store = Mock()
        store.get_recent_queries.return_value = [
            "How to preprocess fMRI data?",
            "Statistical analysis methods",
            "Brain connectivity analysis",
            "Group-level fMRI analysis",
            "Quality control procedures"
        ]
        return store
    
    @pytest.fixture
    def recommendation_engine(self, mock_embedding_model, mock_history_store):
        """Create recommendation engine with mocks."""
        return QueryRecommendationEngine(
            embedding_model=mock_embedding_model,
            history_store=mock_history_store
        )
    
    def test_recommendation_engine_initialization(self, recommendation_engine):
        """Test basic initialization."""
        assert recommendation_engine is not None
        assert recommendation_engine.similarity_engine is not None
        assert recommendation_engine.pattern_analyzer is not None
        assert isinstance(recommendation_engine.user_profiles, dict)
    
    def test_basic_recommendations(self, recommendation_engine):
        """Test generating basic recommendations."""
        query = "How to analyze fMRI data?"
        
        recommendations = recommendation_engine.recommend(query, limit=3)
        
        assert isinstance(recommendations, list)
        assert len(recommendations) <= 3
        
        for rec in recommendations:
            assert isinstance(rec, Recommendation)
            assert rec.query is not None
            assert 0 <= rec.confidence <= 1.0
            assert rec.category is not None
    
    def test_user_profile_update(self, recommendation_engine):
        """Test updating user profiles."""
        user_id = "test_user"
        query = "fMRI preprocessing pipeline"
        tools_used = ["fsl_preprocessing", "motion_correction"]
        
        # Should not crash
        recommendation_engine.update_user_profile(
            user_id=user_id,
            query=query,
            tools_used=tools_used,
            execution_time=10.5,
            success=True
        )
        
        # Check that profile was created
        assert user_id in recommendation_engine.user_profiles
        profile = recommendation_engine.user_profiles[user_id]
        assert isinstance(profile, UserProfile)
        assert profile.user_id == user_id


class TestSimilarityEngine:
    """Test similarity engine functionality."""
    
    @pytest.fixture
    def similarity_engine(self):
        """Create basic similarity engine."""
        return SimilarityEngine()
    
    def test_lexical_similarity(self, similarity_engine):
        """Test lexical similarity calculation."""
        query1 = "fMRI preprocessing analysis"
        query2 = "preprocessing fMRI data analysis"
        query3 = "completely different topic"
        
        # Similar queries should have higher similarity
        sim_12 = similarity_engine.calculate_similarity(query1, query2, method="lexical")
        sim_13 = similarity_engine.calculate_similarity(query1, query3, method="lexical")
        
        assert 0 <= sim_12 <= 1.0
        assert 0 <= sim_13 <= 1.0
        assert sim_12 > sim_13
    
    def test_domain_terms_loaded(self, similarity_engine):
        """Test that domain terms are loaded."""
        assert len(similarity_engine.domain_terms) > 0
        assert "fmri" in similarity_engine.domain_terms
        assert "connectivity" in similarity_engine.domain_terms
        assert "preprocessing" in similarity_engine.domain_terms


class TestPatternAnalyzer:
    """Test pattern analyzer functionality."""
    
    @pytest.fixture
    def pattern_analyzer(self):
        """Create pattern analyzer."""
        return PatternAnalyzer()
    
    def test_add_query_execution(self, pattern_analyzer):
        """Test adding query executions."""
        query = "Run GLM analysis on preprocessed data"
        tools_used = ["glm_tool", "stats_tool"]
        
        # Should not crash
        pattern_analyzer.add_query_execution(
            query=query,
            tools_used=tools_used,
            execution_time=15.0,
            success=True,
            domain="fmri"
        )
        
        # Check that patterns were created
        assert len(pattern_analyzer.patterns) > 0
    
    def test_get_popular_patterns(self, pattern_analyzer):
        """Test getting popular patterns."""
        # Add some query executions first
        queries = [
            ("fMRI preprocessing workflow", ["preprocessing_tool"], "preprocessing"),
            ("GLM statistical analysis", ["glm_tool"], "statistics"),
            ("Connectivity analysis methods", ["connectivity_tool"], "connectivity")
        ]
        
        for query, tools, domain in queries:
            pattern_analyzer.add_query_execution(
                query=query,
                tools_used=tools,
                execution_time=10.0,
                success=True,
                domain=domain
            )
        
        popular_patterns = pattern_analyzer.get_popular_patterns(limit=5)
        assert isinstance(popular_patterns, list)
        assert len(popular_patterns) <= 5
        
        for pattern in popular_patterns:
            assert isinstance(pattern, QueryPattern)
            assert pattern.frequency > 0


class TestUserProfile:
    """Test user profile functionality."""
    
    def test_user_profile_creation(self):
        """Test creating user profiles."""
        profile = UserProfile(user_id="test_user")
        
        assert profile.user_id == "test_user"
        assert isinstance(profile.preferred_domains, dict)
        assert isinstance(profile.preferred_tools, dict)
        assert 0 <= profile.query_complexity_preference <= 1


class TestRecommendation:
    """Test recommendation object."""
    
    def test_recommendation_creation(self):
        """Test creating recommendations."""
        rec = Recommendation(
            query="Test query",
            confidence=0.8,
            reason="Test reason",
            category="test"
        )
        
        assert rec.query == "Test query"
        assert rec.confidence == 0.8
        assert rec.reason == "Test reason"
        assert rec.category == "test"
        assert isinstance(rec.metadata, dict)


if __name__ == "__main__":
    pytest.main([__file__])