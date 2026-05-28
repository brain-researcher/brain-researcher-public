"""
Unit tests for AGENT-022: Query Recommendation System

Tests the QueryRecommendationEngine class with comprehensive coverage including:
- Query similarity computation
- Pattern analysis and extraction
- User profiling and preference learning
- Recommendation ranking and filtering
- Cold start and sparse data scenarios
- Performance optimization
- Property-based testing

Author: Reviewer Subagent
Date: 2025-01-XX
"""

import pytest
import json
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List, Optional, Tuple
from hypothesis import given, strategies as st, settings, assume
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant
from datetime import datetime, timedelta

from brain_researcher.services.agent.recommendation_engine import (
    QueryRecommendationEngine,
    SimilarityEngine,
    PatternAnalyzer,
    QueryPattern,
    UserProfile,
    Recommendation
)

# Define missing enums and classes for testing
from enum import Enum

class SimilarityMetric(Enum):
    SEMANTIC = "semantic"
    SYNTACTIC = "syntactic"
    DOMAIN = "domain"
    COMBINED = "combined"

class PatternType(Enum):
    DOMAIN_TOPIC = "domain_topic"
    BRAIN_REGION = "brain_region"
    ANALYSIS_TYPE = "analysis_type"
    SEQUENTIAL_WORKFLOW = "sequential_workflow"

# Mock missing classes
class RecommendationScore:
    def __init__(self, score: float, reason: str):
        self.score = score
        self.reason = reason

class RecommendationContext:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestQueryRecommendationEngine:
    """Test suite for QueryRecommendationEngine class."""
    
    @pytest.fixture
    def query_history_dataset(self):
        """Load query history dataset from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-022" / "query_history_dataset.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    @pytest.fixture
    def expected_recommendations(self):
        """Load expected recommendations from fixtures."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "AGENT-022" / "expected_recommendations.json"
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    @pytest.fixture
    def mock_vector_store(self):
        """Create mock vector store for embeddings."""
        vector_store = Mock()
        
        # Mock embedding vectors (384-dimensional for sentence transformers)
        def mock_embedding(text):
            # Create deterministic embedding based on text hash
            hash_val = hash(text) % 1000000
            np.random.seed(hash_val)
            return np.random.normal(0, 1, 384).astype(np.float32)
        
        vector_store.embed_query.side_effect = mock_embedding
        vector_store.similarity_search.return_value = []  # Default empty
        
        return vector_store
    
    @pytest.fixture
    def recommendation_engine(self, query_history_dataset, mock_vector_store):
        """Create QueryRecommendationEngine with sample data."""
        engine = QueryRecommendationEngine(
            vector_store=mock_vector_store,
            similarity_threshold=0.7,
            max_recommendations=10,
            enable_user_profiling=True,
            enable_pattern_analysis=True
        )
        
        # Load historical queries
        for entry in query_history_dataset["query_history"]:
            engine.add_query_to_history(
                query=entry["query"],
                user_id=entry.get("user_id", "anonymous"),
                timestamp=datetime.fromisoformat(entry["timestamp"]),
                results_quality=entry.get("results_quality", 0.8),
                context=entry.get("context", {})
            )
        
        return engine
    
    @pytest.fixture
    def empty_recommendation_engine(self, mock_vector_store):
        """Create empty QueryRecommendationEngine for testing initialization."""
        return QueryRecommendationEngine(
            vector_store=mock_vector_store,
            similarity_threshold=0.7,
            max_recommendations=5
        )


class TestSimilarityEngine:
    """Test query similarity computation."""
    
    def test_semantic_similarity_computation(self, recommendation_engine):
        """Test semantic similarity between queries."""
        query1 = "What brain regions are active during working memory tasks?"
        query2 = "Which areas of the brain show activation in working memory?"
        query3 = "How does sleep affect brain connectivity?"
        
        # Similar queries should have high similarity
        sim_12 = recommendation_engine.similarity_engine.compute_similarity(query1, query2)
        assert sim_12 > 0.7
        
        # Different queries should have lower similarity
        sim_13 = recommendation_engine.similarity_engine.compute_similarity(query1, query3)
        assert sim_13 < 0.5
        
        # Self-similarity should be 1.0
        sim_11 = recommendation_engine.similarity_engine.compute_similarity(query1, query1)
        assert abs(sim_11 - 1.0) < 0.01
    
    def test_syntactic_similarity_computation(self, recommendation_engine):
        """Test syntactic similarity computation."""
        query1 = "fMRI analysis of visual cortex activation"
        query2 = "fMRI analysis of motor cortex activation"
        query3 = "DTI analysis of white matter integrity"
        
        # Syntactically similar queries
        sim_12 = recommendation_engine.similarity_engine.compute_syntactic_similarity(query1, query2)
        assert sim_12 > 0.6  # Share "fMRI analysis" and "cortex activation"
        
        # Less syntactically similar
        sim_13 = recommendation_engine.similarity_engine.compute_syntactic_similarity(query1, query3)
        assert sim_13 < sim_12  # Only share "analysis"
    
    def test_domain_specific_similarity(self, recommendation_engine):
        """Test domain-specific neuroimaging similarity."""
        # Queries with neuroimaging domain terms
        query1 = "GLM analysis of task-related BOLD activation"
        query2 = "General linear model for BOLD signal analysis"
        query3 = "Machine learning classification of brain states"
        
        # Domain-specific similarity should recognize GLM = General Linear Model
        sim_12 = recommendation_engine.similarity_engine.compute_domain_similarity(query1, query2)
        assert sim_12 > 0.8
        
        # Different domain concepts
        sim_13 = recommendation_engine.similarity_engine.compute_domain_similarity(query1, query3)
        assert sim_13 < 0.4
    
    def test_similarity_metric_combinations(self, recommendation_engine):
        """Test combination of different similarity metrics."""
        query1 = "fMRI GLM analysis of working memory"
        query2 = "fMRI general linear model for working memory tasks"
        
        semantic_sim = recommendation_engine.similarity_engine.compute_similarity(
            query1, query2, metric=SimilarityMetric.SEMANTIC
        )
        syntactic_sim = recommendation_engine.similarity_engine.compute_similarity(
            query1, query2, metric=SimilarityMetric.SYNTACTIC
        )
        domain_sim = recommendation_engine.similarity_engine.compute_similarity(
            query1, query2, metric=SimilarityMetric.DOMAIN
        )
        combined_sim = recommendation_engine.similarity_engine.compute_similarity(
            query1, query2, metric=SimilarityMetric.COMBINED
        )
        
        # All should be positive
        assert semantic_sim > 0.5
        assert syntactic_sim > 0.5
        assert domain_sim > 0.5
        
        # Combined should be influenced by all metrics
        assert 0.5 < combined_sim < 1.0
    
    @given(
        query1=st.text(min_size=10, max_size=100),
        query2=st.text(min_size=10, max_size=100)
    )
    @settings(max_examples=20)
    def test_similarity_properties(self, recommendation_engine, query1, query2):
        """Property-based test for similarity computation."""
        assume(len(query1.strip()) >= 5 and len(query2.strip()) >= 5)
        
        sim_12 = recommendation_engine.similarity_engine.compute_similarity(query1, query2)
        sim_21 = recommendation_engine.similarity_engine.compute_similarity(query2, query1)
        
        # Similarity should be symmetric
        assert abs(sim_12 - sim_21) < 0.001
        
        # Similarity should be between 0 and 1
        assert 0 <= sim_12 <= 1
        assert 0 <= sim_21 <= 1
        
        # Self-similarity should be 1.0
        sim_11 = recommendation_engine.similarity_engine.compute_similarity(query1, query1)
        assert abs(sim_11 - 1.0) < 0.01


class TestPatternAnalyzer:
    """Test pattern analysis functionality."""
    
    def test_query_pattern_extraction(self, recommendation_engine):
        """Test extraction of patterns from queries."""
        queries = [
            "What brain regions show activation during working memory tasks?",
            "Which areas activate during episodic memory retrieval?", 
            "What regions are involved in spatial working memory?",
            "How do brain networks change during memory encoding?",
            "What is the role of hippocampus in memory formation?"
        ]
        
        patterns = recommendation_engine.pattern_analyzer.extract_patterns(queries)
        
        # Should identify memory-related patterns
        pattern_types = [p.pattern_type for p in patterns]
        assert PatternType.DOMAIN_TOPIC in pattern_types
        assert PatternType.BRAIN_REGION in pattern_types
        assert PatternType.ANALYSIS_TYPE in pattern_types
        
        # Should identify "memory" as a frequent pattern
        topic_patterns = [p for p in patterns if p.pattern_type == PatternType.DOMAIN_TOPIC]
        memory_pattern = next((p for p in topic_patterns if "memory" in p.pattern_text.lower()), None)
        assert memory_pattern is not None
        assert memory_pattern.frequency >= 4  # Appears in 4+ queries
    
    def test_temporal_pattern_detection(self, recommendation_engine):
        """Test detection of temporal patterns in queries."""
        # Add queries with timestamps
        base_time = datetime.now() - timedelta(days=30)
        
        for i, query in enumerate([
            "fMRI preprocessing pipeline setup",
            "First-level GLM analysis",
            "Group-level statistical analysis", 
            "Multiple comparisons correction",
            "Results visualization and reporting"
        ]):
            recommendation_engine.add_query_to_history(
                query=query,
                user_id="user_workflow",
                timestamp=base_time + timedelta(hours=i),
                results_quality=0.9
            )
        
        patterns = recommendation_engine.pattern_analyzer.extract_temporal_patterns(
            user_id="user_workflow",
            time_window=timedelta(days=7)
        )
        
        # Should identify sequential workflow pattern
        workflow_patterns = [p for p in patterns if p.pattern_type == PatternType.SEQUENTIAL_WORKFLOW]
        assert len(workflow_patterns) > 0
        
        # Should capture the analysis pipeline sequence
        pipeline_pattern = workflow_patterns[0]
        assert "preprocessing" in pipeline_pattern.pattern_text.lower()
        assert "glm" in pipeline_pattern.pattern_text.lower()
    
    def test_user_specific_patterns(self, recommendation_engine):
        """Test extraction of user-specific patterns."""
        # Add queries for specific users
        user1_queries = [
            "fMRI connectivity analysis methods",
            "Resting-state network identification", 
            "Graph theory measures for brain networks",
            "Dynamic connectivity analysis"
        ]
        
        user2_queries = [
            "Task-related activation patterns",
            "GLM contrasts for cognitive tasks",
            "ROI analysis for specific brain regions",
            "Statistical thresholding methods"
        ]
        
        for query in user1_queries:
            recommendation_engine.add_query_to_history(query, user_id="user1")
        
        for query in user2_queries:
            recommendation_engine.add_query_to_history(query, user_id="user2")
        
        # Extract user-specific patterns
        user1_patterns = recommendation_engine.pattern_analyzer.extract_user_patterns("user1")
        user2_patterns = recommendation_engine.pattern_analyzer.extract_user_patterns("user2")
        
        # User 1 should have connectivity-focused patterns
        user1_topics = [p.pattern_text for p in user1_patterns if p.pattern_type == PatternType.DOMAIN_TOPIC]
        assert any("connectivity" in topic.lower() for topic in user1_topics)
        
        # User 2 should have activation-focused patterns  
        user2_topics = [p.pattern_text for p in user2_patterns if p.pattern_type == PatternType.DOMAIN_TOPIC]
        assert any("activation" in topic.lower() for topic in user2_topics)
    
    def test_pattern_confidence_scoring(self, recommendation_engine):
        """Test confidence scoring for extracted patterns."""
        queries = [
            "What is the default mode network?",
            "How to analyze default mode network connectivity?",
            "Default mode network in aging",
            "DMN alterations in Alzheimer's disease",
            "Default mode network resting state analysis"
        ]
        
        patterns = recommendation_engine.pattern_analyzer.extract_patterns(queries)
        
        # Find default mode network pattern
        dmn_pattern = next(
            p for p in patterns 
            if ("default mode" in p.pattern_text.lower() or "dmn" in p.pattern_text.lower())
        )
        
        # Should have high confidence (appears in all queries)
        assert dmn_pattern.confidence > 0.8
        assert dmn_pattern.frequency == 5
    
    def test_pattern_trend_analysis(self, recommendation_engine):
        """Test analysis of pattern trends over time."""
        # Add queries with different time periods
        old_time = datetime.now() - timedelta(days=90)
        recent_time = datetime.now() - timedelta(days=10)
        
        # Old pattern: traditional analysis
        for i in range(5):
            recommendation_engine.add_query_to_history(
                f"GLM analysis approach {i}",
                timestamp=old_time + timedelta(days=i)
            )
        
        # Recent pattern: machine learning
        for i in range(8):
            recommendation_engine.add_query_to_history(
                f"Machine learning classification method {i}",
                timestamp=recent_time + timedelta(days=i)
            )
        
        trends = recommendation_engine.pattern_analyzer.analyze_pattern_trends(
            time_window=timedelta(days=120)
        )
        
        # Should identify declining GLM trend and rising ML trend
        glm_trend = next((t for t in trends if "glm" in t.pattern_text.lower()), None)
        ml_trend = next((t for t in trends if "machine learning" in t.pattern_text.lower()), None)
        
        assert glm_trend is not None
        assert ml_trend is not None
        assert ml_trend.trend_score > glm_trend.trend_score  # ML trending up


class TestUserProfiler:
    """Test user profiling functionality."""
    
    def test_user_profile_creation(self, recommendation_engine):
        """Test creation of user profiles from query history."""
        user_id = "test_user"
        queries = [
            "fMRI preprocessing with FSL",
            "FSL FEAT analysis setup",
            "FSL group analysis workflow", 
            "How to use FSL randomise?",
            "FSL atlases for ROI analysis"
        ]
        
        for query in queries:
            recommendation_engine.add_query_to_history(query, user_id=user_id)
        
        profile = recommendation_engine.user_profiler.get_user_profile(user_id)
        
        # Should identify FSL preference
        assert "fsl" in profile.preferred_tools
        assert profile.preferred_tools["fsl"] >= 5
        
        # Should identify analysis type preferences
        assert "preprocessing" in profile.domain_interests
        assert "group_analysis" in profile.domain_interests
    
    def test_user_expertise_estimation(self, recommendation_engine):
        """Test estimation of user expertise levels."""
        # Beginner user queries
        beginner_queries = [
            "What is fMRI?",
            "How to get started with neuroimaging?",
            "Basic fMRI analysis steps",
            "Introduction to brain anatomy"
        ]
        
        # Expert user queries
        expert_queries = [
            "Optimize HRF deconvolution parameters for event-related designs",
            "Implement custom GLM contrasts for complex factorial designs",
            "Compare ICA-based vs regression-based motion artifact removal",
            "Develop novel connectivity metrics using graph theory"
        ]
        
        for query in beginner_queries:
            recommendation_engine.add_query_to_history(query, user_id="beginner")
        
        for query in expert_queries:
            recommendation_engine.add_query_to_history(query, user_id="expert")
        
        beginner_profile = recommendation_engine.user_profiler.get_user_profile("beginner")
        expert_profile = recommendation_engine.user_profiler.get_user_profile("expert")
        
        # Expert should have higher expertise score
        assert expert_profile.expertise_level > beginner_profile.expertise_level
        assert expert_profile.expertise_level > 0.7
        assert beginner_profile.expertise_level < 0.4
    
    def test_user_preference_learning(self, recommendation_engine):
        """Test learning of user preferences over time."""
        user_id = "learning_user"
        
        # Initial phase: SPM preference
        spm_queries = [
            "SPM12 preprocessing pipeline",
            "SPM first-level analysis",
            "SPM group statistics"
        ]
        
        for query in spm_queries:
            recommendation_engine.add_query_to_history(
                query, user_id=user_id,
                timestamp=datetime.now() - timedelta(days=60)
            )
        
        # Later phase: switch to FSL
        fsl_queries = [
            "Converting from SPM to FSL workflow",
            "FSL FEAT vs SPM analysis",
            "FSL group analysis best practices",
            "FSL melodic for ICA denoising"
        ]
        
        for query in fsl_queries:
            recommendation_engine.add_query_to_history(
                query, user_id=user_id,
                timestamp=datetime.now() - timedelta(days=10)
            )
        
        profile = recommendation_engine.user_profiler.get_user_profile(user_id)
        
        # Should show recent preference for FSL
        recent_preferences = profile.get_recent_preferences(days=30)
        assert "fsl" in recent_preferences
        assert recent_preferences["fsl"] > recent_preferences.get("spm", 0)
    
    def test_user_context_awareness(self, recommendation_engine):
        """Test context-aware user profiling."""
        user_id = "context_user"
        
        # Research context queries
        research_queries = [
            "Novel connectivity analysis methods",
            "Publication-quality brain visualizations",
            "Statistical power analysis for fMRI studies"
        ]
        
        # Clinical context queries  
        clinical_queries = [
            "fMRI protocols for patient populations",
            "Motion artifact handling in clinical data",
            "Diagnostic markers from neuroimaging"
        ]
        
        for query in research_queries:
            recommendation_engine.add_query_to_history(
                query, user_id=user_id,
                context={"setting": "research", "urgency": "low"}
            )
        
        for query in clinical_queries:
            recommendation_engine.add_query_to_history(
                query, user_id=user_id,
                context={"setting": "clinical", "urgency": "high"}
            )
        
        profile = recommendation_engine.user_profiler.get_user_profile(user_id)
        
        # Should identify context preferences
        assert "research" in profile.context_preferences
        assert "clinical" in profile.context_preferences
        
        # Should have context-specific recommendations
        research_recs = profile.get_context_recommendations("research")
        clinical_recs = profile.get_context_recommendations("clinical")
        
        assert len(research_recs) > 0
        assert len(clinical_recs) > 0
    
    def test_user_profile_privacy(self, recommendation_engine):
        """Test privacy controls in user profiling."""
        user_id = "privacy_user"
        
        # Add queries with privacy settings
        recommendation_engine.add_query_to_history(
            "Sensitive patient data analysis",
            user_id=user_id,
            context={"privacy_level": "high", "store_profile": False}
        )
        
        recommendation_engine.add_query_to_history(
            "General fMRI analysis question",
            user_id=user_id,
            context={"privacy_level": "low", "store_profile": True}
        )
        
        profile = recommendation_engine.user_profiler.get_user_profile(user_id)
        
        # Should only include queries with appropriate privacy settings
        stored_queries = profile.get_stored_queries()
        assert len(stored_queries) == 1
        assert "general fmri" in stored_queries[0].lower()


class TestRecommendationRanking:
    """Test recommendation ranking and filtering."""
    
    def test_basic_recommendation_ranking(self, recommendation_engine, expected_recommendations):
        """Test basic recommendation ranking algorithm."""
        query = "How to analyze working memory fMRI data?"
        
        recommendations = recommendation_engine.get_recommendations(query, max_results=5)
        
        # Should return recommendations
        assert len(recommendations) > 0
        assert len(recommendations) <= 5
        
        # Should be ranked by relevance score
        scores = [rec.relevance_score for rec in recommendations]
        assert scores == sorted(scores, reverse=True)
        
        # Should include similarity-based recommendations
        memory_related = any("memory" in rec.query.lower() for rec in recommendations)
        assert memory_related
    
    def test_personalized_recommendations(self, recommendation_engine):
        """Test personalized recommendations based on user profile."""
        user_id = "personalized_user"
        
        # Build user profile with SPM preference
        spm_queries = [
            "SPM12 installation guide",
            "SPM first-level analysis tutorial",
            "SPM group analysis workflow",
            "SPM connectivity toolbox usage"
        ]
        
        for query in spm_queries:
            recommendation_engine.add_query_to_history(query, user_id=user_id)
        
        # Get personalized recommendations
        query = "How to perform statistical analysis?"
        recommendations = recommendation_engine.get_recommendations(
            query, user_id=user_id, max_results=5
        )
        
        # Should prefer SPM-related recommendations
        spm_recs = [rec for rec in recommendations if "spm" in rec.query.lower()]
        assert len(spm_recs) > 0
        
        # SPM recommendations should be highly ranked
        if spm_recs:
            assert spm_recs[0].relevance_score > 0.6
    
    def test_contextual_recommendations(self, recommendation_engine):
        """Test context-aware recommendations."""
        query = "fMRI analysis workflow"
        
        # Research context
        research_recs = recommendation_engine.get_recommendations(
            query,
            context={"setting": "research", "experience_level": "expert"},
            max_results=5
        )
        
        # Clinical context
        clinical_recs = recommendation_engine.get_recommendations(
            query,
            context={"setting": "clinical", "experience_level": "beginner"},
            max_results=5
        )
        
        # Should provide different recommendations for different contexts
        research_queries = [rec.query for rec in research_recs]
        clinical_queries = [rec.query for rec in clinical_recs]
        
        # Some recommendations should be different
        assert len(set(research_queries) - set(clinical_queries)) > 0
        
        # Clinical recommendations should be more basic/practical
        clinical_complexity = sum(1 for rec in clinical_recs 
                                if any(word in rec.query.lower() 
                                      for word in ["basic", "guide", "tutorial", "simple"]))
        assert clinical_complexity > 0
    
    def test_diversity_in_recommendations(self, recommendation_engine):
        """Test diversity in recommendation results."""
        query = "brain network analysis"
        
        recommendations = recommendation_engine.get_recommendations(
            query, max_results=10, diversity_factor=0.8
        )
        
        # Should have recommendations covering different aspects
        topics = set()
        for rec in recommendations:
            if "connectivity" in rec.query.lower():
                topics.add("connectivity")
            if "graph" in rec.query.lower():
                topics.add("graph_theory")
            if "ica" in rec.query.lower():
                topics.add("ica")
            if "clustering" in rec.query.lower():
                topics.add("clustering")
        
        # Should cover multiple topics
        assert len(topics) >= 2
    
    def test_recommendation_filtering(self, recommendation_engine):
        """Test filtering of recommendations."""
        query = "fMRI preprocessing"
        
        # Test filtering by tool preference
        recommendations = recommendation_engine.get_recommendations(
            query,
            filters={"preferred_tools": ["fsl"]},
            max_results=5
        )
        
        fsl_recs = [rec for rec in recommendations if "fsl" in rec.query.lower()]
        assert len(fsl_recs) > 0
        
        # Test filtering by complexity level
        beginner_recs = recommendation_engine.get_recommendations(
            query,
            filters={"complexity_level": "beginner"},
            max_results=5
        )
        
        # Should prefer simpler recommendations
        simple_indicators = ["basic", "introduction", "guide", "tutorial", "simple"]
        beginner_matches = sum(
            1 for rec in beginner_recs
            if any(indicator in rec.query.lower() for indicator in simple_indicators)
        )
        assert beginner_matches > 0
    
    def test_temporal_relevance_decay(self, recommendation_engine):
        """Test temporal decay of recommendation relevance."""
        # Add old and recent queries
        old_time = datetime.now() - timedelta(days=365)  # 1 year ago
        recent_time = datetime.now() - timedelta(days=7)  # 1 week ago
        
        old_query = "Old fMRI analysis method"
        recent_query = "Recent fMRI analysis method"
        
        recommendation_engine.add_query_to_history(old_query, timestamp=old_time)
        recommendation_engine.add_query_to_history(recent_query, timestamp=recent_time)
        
        recommendations = recommendation_engine.get_recommendations("fMRI analysis")
        
        # Recent query should be ranked higher due to temporal relevance
        recent_rec = next((rec for rec in recommendations if "recent" in rec.query.lower()), None)
        old_rec = next((rec for rec in recommendations if "old" in rec.query.lower()), None)
        
        if recent_rec and old_rec:
            assert recent_rec.relevance_score > old_rec.relevance_score


class TestColdStartScenarios:
    """Test recommendation system behavior with sparse data."""
    
    def test_new_user_recommendations(self, empty_recommendation_engine):
        """Test recommendations for users with no history."""
        query = "How to start fMRI analysis?"
        
        recommendations = empty_recommendation_engine.get_recommendations(
            query, user_id="new_user", max_results=5
        )
        
        # Should provide general recommendations
        assert len(recommendations) >= 0  # May be empty with no data
        
        # If recommendations exist, should be general/beginner-oriented
        for rec in recommendations:
            assert rec.relevance_score > 0
    
    def test_sparse_query_history(self, empty_recommendation_engine):
        """Test behavior with very limited query history."""
        # Add minimal history
        empty_recommendation_engine.add_query_to_history(
            "What is fMRI preprocessing?"
        )
        
        query = "How to do fMRI analysis?"
        recommendations = empty_recommendation_engine.get_recommendations(query, max_results=5)
        
        # Should make best effort with available data
        assert len(recommendations) >= 0
    
    def test_domain_transfer_recommendations(self, recommendation_engine):
        """Test recommendations when user asks about new domain."""
        user_id = "domain_transfer_user"
        
        # User has only connectivity analysis history
        connectivity_queries = [
            "Resting-state network analysis",
            "Functional connectivity methods",
            "Graph theory for brain networks"
        ]
        
        for query in connectivity_queries:
            recommendation_engine.add_query_to_history(query, user_id=user_id)
        
        # Ask about different domain (task activation)
        query = "How to analyze task activation patterns?"
        recommendations = recommendation_engine.get_recommendations(
            query, user_id=user_id, max_results=5
        )
        
        # Should provide relevant recommendations despite different domain
        assert len(recommendations) > 0
        
        # May include some general analysis concepts that transfer
        general_terms = ["analysis", "fmri", "brain", "statistical"]
        has_general = any(
            any(term in rec.query.lower() for term in general_terms)
            for rec in recommendations
        )
        assert has_general
    
    def test_popularity_based_fallback(self, recommendation_engine):
        """Test fallback to popularity-based recommendations."""
        # Simulate popular queries by frequency
        popular_queries = [
            ("How to preprocess fMRI data?", 50),
            ("Statistical analysis of brain activation", 35), 
            ("Group-level fMRI analysis", 28),
            ("Motion correction in fMRI", 22),
            ("fMRI quality control methods", 18)
        ]
        
        for query, count in popular_queries:
            for _ in range(count):
                recommendation_engine.add_query_to_history(
                    query,
                    user_id=f"user_{_}",
                    results_quality=0.8
                )
        
        # Query with no good semantic matches should fall back to popular queries
        obscure_query = "Quantum mechanics in neuroscience applications"
        recommendations = recommendation_engine.get_recommendations(obscure_query, max_results=3)
        
        # Should include some popular queries as fallback
        popular_in_recs = sum(
            1 for rec in recommendations 
            for pop_query, _ in popular_queries
            if pop_query.lower() in rec.query.lower()
        )
        assert popular_in_recs > 0


class TestPerformanceOptimization:
    """Test performance aspects of recommendation system."""
    
    def test_recommendation_response_time(self, recommendation_engine):
        """Test that recommendations are generated quickly."""
        import time
        
        query = "How to analyze resting-state fMRI connectivity?"
        
        start_time = time.time()
        recommendations = recommendation_engine.get_recommendations(query, max_results=10)
        response_time = time.time() - start_time
        
        # Should respond quickly (< 500ms for unit test with mocked components)
        assert response_time < 0.5
        assert len(recommendations) > 0
    
    def test_batch_recommendation_efficiency(self, recommendation_engine):
        """Test efficiency of batch recommendation generation."""
        import time
        
        queries = [
            "fMRI preprocessing workflow",
            "Statistical analysis methods",
            "Brain connectivity analysis", 
            "Group-level analysis techniques",
            "Quality control procedures"
        ]
        
        # Individual recommendations
        start_time = time.time()
        individual_results = []
        for query in queries:
            recs = recommendation_engine.get_recommendations(query, max_results=3)
            individual_results.append(recs)
        individual_time = time.time() - start_time
        
        # Batch recommendations (if implemented)
        start_time = time.time()
        batch_results = recommendation_engine.get_batch_recommendations(queries, max_results=3)
        batch_time = time.time() - start_time
        
        # Batch should be more efficient
        assert batch_time < individual_time * 0.8  # At least 20% improvement
        assert len(batch_results) == len(queries)
    
    def test_caching_effectiveness(self, recommendation_engine):
        """Test effectiveness of recommendation caching."""
        import time
        
        query = "fMRI group analysis statistical methods"
        
        # First call - should compute recommendations
        start_time = time.time()
        recs1 = recommendation_engine.get_recommendations(query, max_results=5)
        first_call_time = time.time() - start_time
        
        # Second call - should use cache
        start_time = time.time()
        recs2 = recommendation_engine.get_recommendations(query, max_results=5)
        second_call_time = time.time() - start_time
        
        # Results should be identical
        assert len(recs1) == len(recs2)
        for r1, r2 in zip(recs1, recs2):
            assert r1.query == r2.query
            assert abs(r1.relevance_score - r2.relevance_score) < 0.001
        
        # Second call should be much faster
        assert second_call_time < first_call_time * 0.5
    
    def test_memory_usage_with_large_history(self, empty_recommendation_engine):
        """Test memory usage with large query history."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Add large number of queries
        for i in range(1000):
            query = f"Test query number {i} with various neuroimaging analysis methods"
            empty_recommendation_engine.add_query_to_history(
                query,
                user_id=f"user_{i % 100}",  # 100 different users
                results_quality=0.7 + 0.3 * (i % 10) / 10
            )
        
        # Generate recommendations
        recommendations = empty_recommendation_engine.get_recommendations(
            "neuroimaging analysis", max_results=10
        )
        
        final_memory = process.memory_info().rss
        memory_increase = (final_memory - initial_memory) / 1024 / 1024  # MB
        
        # Memory increase should be reasonable (< 100MB for this test)
        assert memory_increase < 100
        assert len(recommendations) >= 0


class TestRecommendationQuality:
    """Test quality and accuracy of recommendations."""
    
    def test_recommendation_relevance_accuracy(self, recommendation_engine, expected_recommendations):
        """Test accuracy of recommendation relevance against expected results."""
        for test_case in expected_recommendations["test_cases"]:
            query = test_case["query"]
            expected_topics = test_case["expected_topics"]
            
            recommendations = recommendation_engine.get_recommendations(query, max_results=5)
            
            # Check if expected topics are covered in recommendations
            covered_topics = set()
            for rec in recommendations:
                for topic in expected_topics:
                    if topic.lower() in rec.query.lower():
                        covered_topics.add(topic)
            
            # Should cover at least half of expected topics
            coverage_ratio = len(covered_topics) / len(expected_topics)
            assert coverage_ratio >= 0.5, f"Poor topic coverage for query: {query}"
    
    def test_recommendation_diversity_quality(self, recommendation_engine):
        """Test quality of recommendation diversity."""
        query = "brain analysis methods"
        
        recommendations = recommendation_engine.get_recommendations(
            query, max_results=10, diversity_factor=0.9
        )
        
        # Measure diversity by checking semantic similarity between recommendations
        if len(recommendations) >= 2:
            similarities = []
            for i in range(len(recommendations)):
                for j in range(i + 1, len(recommendations)):
                    sim = recommendation_engine.similarity_engine.compute_similarity(
                        recommendations[i].query, recommendations[j].query
                    )
                    similarities.append(sim)
            
            # Average similarity should not be too high (indicating good diversity)
            avg_similarity = sum(similarities) / len(similarities)
            assert avg_similarity < 0.8  # Diverse recommendations should differ
    
    def test_recommendation_consistency(self, recommendation_engine):
        """Test consistency of recommendations across similar queries."""
        similar_queries = [
            "How to preprocess fMRI data?",
            "What are the steps for fMRI preprocessing?",
            "fMRI data preprocessing workflow"
        ]
        
        recommendation_sets = []
        for query in similar_queries:
            recs = recommendation_engine.get_recommendations(query, max_results=5)
            recommendation_sets.append(set(rec.query for rec in recs))
        
        # Should have significant overlap between recommendation sets
        common_recs = recommendation_sets[0]
        for rec_set in recommendation_sets[1:]:
            common_recs = common_recs.intersection(rec_set)
        
        # At least some recommendations should be common across similar queries
        overlap_ratio = len(common_recs) / max(len(rs) for rs in recommendation_sets)
        assert overlap_ratio > 0.2  # At least 20% overlap
    
    @given(
        query_length=st.integers(min_value=5, max_value=100),
        num_results=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=10)
    def test_recommendation_robustness(self, recommendation_engine, query_length, num_results):
        """Property-based test for recommendation robustness."""
        # Generate test query
        test_query = "neuroimaging analysis " * (query_length // 20 + 1)
        test_query = test_query[:query_length]
        
        recommendations = recommendation_engine.get_recommendations(
            test_query, max_results=num_results
        )
        
        # Should handle various query lengths and result counts gracefully
        assert len(recommendations) <= num_results
        
        # All recommendations should have valid scores
        for rec in recommendations:
            assert 0 <= rec.relevance_score <= 1.0
            assert rec.query is not None
            assert len(rec.query) > 0


class RecommendationEngineStateMachine(RuleBasedStateMachine):
    """Property-based state machine testing for recommendation engine."""
    
    def __init__(self):
        super().__init__()
        mock_vector_store = Mock()
        mock_vector_store.embed_query.return_value = np.random.normal(0, 1, 384).astype(np.float32)
        mock_vector_store.similarity_search.return_value = []
        
        self.engine = QueryRecommendationEngine(vector_store=mock_vector_store)
        self.queries = []
        self.users = set()
    
    @rule(query=st.text(min_size=10, max_size=100))
    def add_query(self, query):
        """Add a query to the system."""
        user_id = f"user_{len(self.users) % 5}"  # Cycle through 5 users
        self.users.add(user_id)
        
        self.engine.add_query_to_history(query, user_id=user_id)
        self.queries.append((query, user_id))
    
    @rule(query=st.text(min_size=5, max_size=50))
    def get_recommendations(self, query):
        """Get recommendations for a query."""
        recommendations = self.engine.get_recommendations(query, max_results=5)
        
        # Should return valid recommendations
        assert len(recommendations) <= 5
        
        for rec in recommendations:
            assert 0 <= rec.relevance_score <= 1.0
            assert rec.query is not None
    
    @invariant()
    def query_history_consistent(self):
        """Query history should remain consistent."""
        total_queries = len(self.queries)
        stored_queries = len(self.engine.get_all_queries())
        
        # Stored queries should match added queries
        assert stored_queries == total_queries


if __name__ == "__main__":
    pytest.main([__file__])