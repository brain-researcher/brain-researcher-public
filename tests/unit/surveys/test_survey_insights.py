"""
Unit Tests for Survey AI Insights Engine

Comprehensive tests for AI-powered survey insights generation including
sentiment analysis, response patterns, neuroimaging correlations, quality
assessment, and predictive analytics.
"""

import pytest
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from collections import defaultdict

# Import survey insights system
from brain_researcher.services.orchestrator.survey_insights import (
    SurveyInsightsEngine, InsightResult, InsightType
)
from brain_researcher.services.orchestrator.survey_models import (
    Base, Survey, SurveyQuestion, SurveyResponse, SurveyInsight,
    SurveyResponseAnalytics, SurveyDistribution
)


@pytest.fixture
def db_engine():
    """Create in-memory SQLite database for testing"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create database session for testing"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def insights_engine():
    """Create insights engine instance for testing"""
    return SurveyInsightsEngine()


@pytest.fixture
def sample_survey(db_session):
    """Create a sample survey with questions"""
    survey = Survey(
        id=str(uuid.uuid4()),
        title='Test Survey',
        description='Survey for insights testing',
        category='cognitive_assessment',
        creator_id=str(uuid.uuid4()),
        status='active'
    )
    db_session.add(survey)
    
    # Add questions
    questions = [
        SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='How satisfied are you with the analysis tools?',
            question_type='scale',
            options={'scale_min': 1, 'scale_max': 5},
            order_index=0
        ),
        SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='Which brain regions did you analyze?',
            question_type='brain_region',
            options={'regions': ['Prefrontal Cortex', 'Motor Cortex', 'Visual Cortex']},
            order_index=1,
            neuroimaging_context={'category': 'analysis_regions'}
        ),
        SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='What scanner field strength did you use?',
            question_type='scanner_parameters',
            options={'field_strength': ['1.5T', '3T', '7T']},
            order_index=2,
            neuroimaging_context={'category': 'acquisition_parameters'}
        ),
        SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='Please provide additional comments',
            question_type='textarea',
            options={},
            order_index=3
        )
    ]
    
    for question in questions:
        db_session.add(question)
    
    db_session.commit()
    return survey


@pytest.fixture
def sample_responses(db_session, sample_survey):
    """Create sample survey responses"""
    responses = []
    
    # Create diverse responses for testing different patterns
    response_data = [
        {
            'participant_id': 'participant_001',
            'responses': {
                0: 5,  # Satisfaction scale
                1: ['Prefrontal Cortex', 'Motor Cortex'],
                2: {'field_strength': '3T'},
                3: 'The tools are excellent and very helpful for my research. Great job!'
            },
            'completion_time_seconds': 300,
            'completion_status': 'completed'
        },
        {
            'participant_id': 'participant_002',
            'responses': {
                0: 4,
                1: ['Visual Cortex'],
                2: {'field_strength': '3T'},
                3: 'Good tools overall, but could be faster and more intuitive'
            },
            'completion_time_seconds': 450,
            'completion_status': 'completed'
        },
        {
            'participant_id': 'participant_003',
            'responses': {
                0: 2,
                1: ['Motor Cortex'],
                2: {'field_strength': '1.5T'},
                3: 'Very difficult to use, confusing interface, slow processing'
            },
            'completion_time_seconds': 600,
            'completion_status': 'completed'
        },
        {
            'participant_id': 'participant_004',
            'responses': {
                0: 4,
                1: ['Prefrontal Cortex'],
                2: {'field_strength': '3T'},
                3: 'Satisfied with most features, excellent documentation'
            },
            'completion_time_seconds': 350,
            'completion_status': 'completed'
        },
        {
            'participant_id': 'participant_005',
            'responses': {
                0: 5,
                1: ['Prefrontal Cortex', 'Visual Cortex'],
                2: {'field_strength': '7T'},
                3: 'Outstanding software, clear interface, helpful support'
            },
            'completion_time_seconds': 400,
            'completion_status': 'completed'
        },
        {
            'participant_id': 'participant_006',
            'responses': {
                0: 3,
                1: ['Motor Cortex'],
                2: {'field_strength': '3T'},
                3: 'Average tools, could be better but functional'
            },
            'completion_time_seconds': 250,
            'completion_status': 'completed'
        },
        {
            'participant_id': 'participant_007',
            'responses': {
                0: 1,
                2: {'field_strength': '1.5T'}
            },
            'completion_time_seconds': 60,  # Very fast - potential quality issue
            'completion_status': 'in_progress'  # Incomplete
        },
        {
            'participant_id': 'participant_008',
            'responses': {
                0: 5,
                1: ['Prefrontal Cortex'],
                2: {'field_strength': '3T'},
                3: 'Excellent tools, very satisfied with performance'
            },
            'completion_time_seconds': 30,  # Suspiciously fast
            'completion_status': 'completed',
            'ip_address': '192.168.1.1'
        },
        {
            'participant_id': 'participant_009',
            'responses': {
                0: 5,
                1: ['Prefrontal Cortex'],
                2: {'field_strength': '3T'},
                3: 'Excellent tools, very satisfied with performance'
            },
            'completion_time_seconds': 35,  # Also fast
            'completion_status': 'completed',
            'ip_address': '192.168.1.1'  # Duplicate IP
        }
    ]
    
    # Get actual question IDs
    questions_list = db_session.query(SurveyQuestion).filter_by(survey_id=sample_survey.id).order_by(SurveyQuestion.order_index).all()
    
    for i, data in enumerate(response_data):
        # Map question indexes to actual question IDs
        mapped_responses = {}
        for q_idx, answer in data['responses'].items():
            if isinstance(q_idx, int) and q_idx < len(questions_list):
                mapped_responses[questions_list[q_idx].id] = answer
        
        response = SurveyResponse(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            participant_id=data['participant_id'],
            responses=mapped_responses,
            completion_time_seconds=data['completion_time_seconds'],
            completion_status=data['completion_status'],
            submitted_at=datetime.utcnow() - timedelta(days=i),  # Spread over time
            ip_address=data.get('ip_address')
        )
        responses.append(response)
        db_session.add(response)
    
    db_session.commit()
    return responses


class TestInsightResult:
    """Test InsightResult dataclass"""
    
    def test_insight_result_creation(self):
        """Test basic InsightResult creation"""
        result = InsightResult(
            insight_type='test_insight',
            title='Test Insight',
            description='This is a test insight',
            confidence_score=0.85,
            supporting_data={'key': 'value'},
            methodology={'algorithm': 'test_algo'}
        )
        
        assert result.insight_type == 'test_insight'
        assert result.title == 'Test Insight'
        assert result.confidence_score == 0.85
        assert result.recommendations == []  # Default empty list
    
    def test_insight_result_with_recommendations(self):
        """Test InsightResult with recommendations"""
        result = InsightResult(
            insight_type='test_insight',
            title='Test',
            description='Test',
            confidence_score=0.8,
            supporting_data={},
            methodology={},
            recommendations=['Recommendation 1', 'Recommendation 2']
        )
        
        assert len(result.recommendations) == 2
        assert 'Recommendation 1' in result.recommendations


class TestSurveyInsightsEngine:
    """Test SurveyInsightsEngine class"""
    
    def test_insights_engine_initialization(self, insights_engine):
        """Test insights engine initialization"""
        engine = insights_engine
        
        assert isinstance(engine.insight_generators, dict)
        assert isinstance(engine.neuroimaging_patterns, dict)
        
        # Check that all insight types have generators
        expected_types = [
            InsightType.SENTIMENT_ANALYSIS.value,
            InsightType.RESPONSE_PATTERNS.value,
            InsightType.COMPLETION_TRENDS.value,
            InsightType.DEMOGRAPHIC_ANALYSIS.value,
            InsightType.NEUROIMAGING_CORRELATIONS.value,
            InsightType.QUALITY_ASSESSMENT.value,
            InsightType.COMPARATIVE_ANALYSIS.value,
            InsightType.PREDICTIVE_INSIGHTS.value,
            InsightType.ANOMALY_DETECTION.value
        ]
        
        for insight_type in expected_types:
            assert insight_type in engine.insight_generators
    
    @patch('brain_researcher.services.orchestrator.survey_insights.get_db')
    @pytest.mark.asyncio
    async def test_process_new_response(self, mock_get_db, insights_engine, db_session, sample_responses):
        """Test processing new response and generating insights"""
        mock_get_db.return_value.__enter__ = Mock(return_value=db_session)
        mock_get_db.return_value.__exit__ = Mock(return_value=None)
        mock_get_db.return_value = db_session
        
        engine = insights_engine
        response = sample_responses[0]
        
        with patch.object(engine, '_generate_realtime_insights') as mock_realtime:
            with patch.object(engine, '_update_cumulative_analytics') as mock_analytics:
                
                await engine.process_new_response(response.survey_id, response.id)
                
                mock_realtime.assert_called_once()
                mock_analytics.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_generate_insights(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test generating comprehensive insights for surveys"""
        engine = insights_engine
        
        with patch.object(engine, '_generate_survey_insights', return_value=[
            {'type': 'sentiment_analysis', 'title': 'Positive Sentiment'}
        ]) as mock_generate:
            
            insights = await engine.generate_insights([sample_survey.id], db_session)
            
            assert sample_survey.id in insights
            mock_generate.assert_called_once_with(sample_survey.id, db_session)
    
    @pytest.mark.asyncio
    async def test_get_survey_insights(self, insights_engine, db_session, sample_survey):
        """Test retrieving specific insights for a survey"""
        engine = insights_engine
        
        # Create test insight
        insight = SurveyInsight(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            insight_type=InsightType.SENTIMENT_ANALYSIS.value,
            title='Test Sentiment',
            description='Test description',
            confidence_score=0.8,
            supporting_data={'test': 'data'},
            methodology={'algorithm': 'test'},
            generated_at=datetime.utcnow()
        )
        db_session.add(insight)
        db_session.commit()
        
        # Get all insights
        all_insights = await engine.get_survey_insights(sample_survey.id, None, db_session)
        assert len(all_insights) == 1
        assert all_insights[0]['title'] == 'Test Sentiment'
        
        # Get specific type
        sentiment_insights = await engine.get_survey_insights(
            sample_survey.id, InsightType.SENTIMENT_ANALYSIS.value, db_session
        )
        assert len(sentiment_insights) == 1
        
        # Get non-existent type
        pattern_insights = await engine.get_survey_insights(
            sample_survey.id, InsightType.RESPONSE_PATTERNS.value, db_session
        )
        assert len(pattern_insights) == 0
    
    @pytest.mark.asyncio
    async def test_calculate_response_rates(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test response rate calculation"""
        engine = insights_engine
        
        # Create distribution record
        distribution = SurveyDistribution(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            distribution_type='manual',
            sent_count=20,  # 20 invitations sent
            status='active'
        )
        db_session.add(distribution)
        db_session.commit()
        
        # Calculate response rates (6 completed responses out of 20 invitations)
        rates = await engine.calculate_response_rates([sample_survey.id], db_session)
        
        assert sample_survey.id in rates
        completed_count = len([r for r in sample_responses if r.completion_status == 'completed'])
        expected_rate = (completed_count / 20) * 100
        assert rates[sample_survey.id] == expected_rate
    
    @pytest.mark.asyncio
    async def test_calculate_completion_rates(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test completion rate calculation"""
        engine = insights_engine
        
        rates = await engine.calculate_completion_rates([sample_survey.id], db_session)
        
        assert sample_survey.id in rates
        
        total_responses = len(sample_responses)
        completed_responses = len([r for r in sample_responses if r.completion_status == 'completed'])
        expected_rate = (completed_responses / total_responses) * 100
        
        assert rates[sample_survey.id] == expected_rate
    
    @pytest.mark.asyncio
    async def test_analyze_demographics(self, insights_engine, db_session, sample_survey):
        """Test demographic analysis"""
        engine = insights_engine
        
        # Create responses with demographic data
        demographic_responses = []
        for i in range(5):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'demo_participant_{i}',
                responses={
                    'age': 25 + i * 5,  # Ages 25, 30, 35, 40, 45
                    'gender': 'Male' if i % 2 == 0 else 'Female',
                    'education_years': 16 + i
                },
                completion_status='completed'
            )
            demographic_responses.append(response)
            db_session.add(response)
        db_session.commit()
        
        demographics = await engine.analyze_demographics([sample_survey.id], db_session)
        
        assert sample_survey.id in demographics
        demo_data = demographics[sample_survey.id]
        
        assert demo_data['response_count'] == 5
        assert 'age_distribution' in demo_data
        assert 'gender_distribution' in demo_data
        assert 'education_distribution' in demo_data
        
        # Check gender distribution
        assert demo_data['gender_distribution']['Male'] == 3  # indices 0, 2, 4
        assert demo_data['gender_distribution']['Female'] == 2  # indices 1, 3


class TestSentimentAnalysis:
    """Test sentiment analysis functionality"""
    
    @pytest.mark.asyncio
    async def test_analyze_sentiment_positive(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test sentiment analysis with positive responses"""
        engine = insights_engine
        
        # Filter to get responses with positive text
        positive_responses = [r for r in sample_responses 
                            if r.completion_status == 'completed' and 
                            any('excellent' in str(v).lower() or 'good' in str(v).lower() 
                                for v in r.responses.values() if isinstance(v, str))]
        
        result = await engine._analyze_sentiment(sample_survey, positive_responses, db_session)
        
        # Should detect positive sentiment
        assert result is not None
        assert result.insight_type == InsightType.SENTIMENT_ANALYSIS.value
        assert 'Positive' in result.title
        assert result.confidence_score > 0
        assert 'supporting_data' in result.__dict__
        assert result.supporting_data['average_sentiment'] > 0
    
    @pytest.mark.asyncio
    async def test_analyze_sentiment_insufficient_data(self, insights_engine, db_session, sample_survey):
        """Test sentiment analysis with insufficient text responses"""
        engine = insights_engine
        
        # Create responses with no meaningful text
        minimal_responses = [
            SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id='minimal_1',
                responses={'scale_q': 3},  # No text
                completion_status='completed'
            )
        ]
        
        result = await engine._analyze_sentiment(sample_survey, minimal_responses, db_session)
        
        # Should return None due to insufficient text data
        assert result is None
    
    @pytest.mark.asyncio
    async def test_analyze_sentiment_mixed(self, insights_engine, db_session, sample_survey):
        """Test sentiment analysis with mixed positive and negative responses"""
        engine = insights_engine
        
        mixed_responses = []
        texts = [
            "Excellent software, very good and helpful",
            "Bad interface, difficult and confusing to use", 
            "Good features but slow performance",
            "Terrible experience, very frustrated",
            "Excellent support, clear documentation"
        ]
        
        for i, text in enumerate(texts):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'mixed_{i}',
                responses={'text_field': text},
                completion_status='completed'
            )
            mixed_responses.append(response)
        
        result = await engine._analyze_sentiment(sample_survey, mixed_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.SENTIMENT_ANALYSIS.value
        assert 'sentiment_distribution' in result.supporting_data
        
        # Should have both positive and negative responses
        dist = result.supporting_data['sentiment_distribution']
        assert dist['positive'] > 0
        assert dist['negative'] > 0


class TestResponsePatterns:
    """Test response pattern analysis"""
    
    @pytest.mark.asyncio
    async def test_analyze_response_patterns(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test response pattern analysis"""
        engine = insights_engine
        
        # Use completed responses
        completed_responses = [r for r in sample_responses if r.completion_status == 'completed']
        
        result = await engine._analyze_response_patterns(sample_survey, completed_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.RESPONSE_PATTERNS.value
        assert 'patterns' in result.supporting_data
        assert 'questions_analyzed' in result.supporting_data
        
        # Should identify pattern in scale question (satisfaction ratings)
        patterns = result.supporting_data['patterns']
        assert len(patterns) > 0
    
    @pytest.mark.asyncio
    async def test_analyze_response_patterns_insufficient_responses(self, insights_engine, db_session, sample_survey):
        """Test response pattern analysis with insufficient data"""
        engine = insights_engine
        
        # Too few responses
        few_responses = [
            SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id='few_1',
                responses={'q1': 'answer'},
                completion_status='completed'
            )
        ]
        
        result = await engine._analyze_response_patterns(sample_survey, few_responses, db_session)
        
        # Should return None due to insufficient data
        assert result is None
    
    @pytest.mark.asyncio
    async def test_analyze_scale_patterns(self, insights_engine, db_session, sample_survey):
        """Test analysis of scale response patterns"""
        engine = insights_engine
        
        # Create scale question
        scale_question = SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            question_text='Rate satisfaction',
            question_type='scale',
            options={'scale_min': 1, 'scale_max': 5},
            order_index=10
        )
        db_session.add(scale_question)
        db_session.commit()
        
        # Create responses with consistent scale ratings
        scale_responses = []
        for i in range(10):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'scale_{i}',
                responses={scale_question.id: 4},  # Consistent rating
                completion_status='completed'
            )
            scale_responses.append(response)
            db_session.add(response)
        db_session.commit()
        
        result = await engine._analyze_response_patterns(sample_survey, scale_responses, db_session)
        
        assert result is not None
        # Should detect low variability pattern
        patterns = result.supporting_data['patterns']
        assert scale_question.id in patterns
        assert patterns[scale_question.id]['type'] == 'scale_distribution'
        assert patterns[scale_question.id]['mean'] == 4.0


class TestCompletionTrends:
    """Test completion trend analysis"""
    
    @pytest.mark.asyncio
    async def test_analyze_completion_trends(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test completion trend analysis"""
        engine = insights_engine
        
        result = await engine._analyze_completion_trends(sample_survey, sample_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.COMPLETION_TRENDS.value
        
        supporting_data = result.supporting_data
        
        # Should have completion time analysis
        if 'completion_times' in supporting_data:
            assert 'average_seconds' in supporting_data['completion_times']
            assert 'median_seconds' in supporting_data['completion_times']
        
        # Should have abandonment analysis
        if 'abandonment_patterns' in supporting_data:
            assert isinstance(supporting_data['abandonment_patterns'], dict)
    
    @pytest.mark.asyncio
    async def test_analyze_completion_trends_long_survey(self, insights_engine, db_session, sample_survey):
        """Test completion trend analysis for long survey times"""
        engine = insights_engine
        
        # Create responses with long completion times
        long_responses = []
        for i in range(5):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'long_{i}',
                responses={'q1': 'answer'},
                completion_time_seconds=2400,  # 40 minutes
                completion_status='completed'
            )
            long_responses.append(response)
        
        result = await engine._analyze_completion_trends(sample_survey, long_responses, db_session)
        
        assert result is not None
        # Should detect survey fatigue
        assert 'fatigue' in result.description.lower() or 'long' in result.description.lower()


class TestNeuroimagingCorrelations:
    """Test neuroimaging-specific analysis"""
    
    @pytest.mark.asyncio
    async def test_analyze_neuroimaging_correlations(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test neuroimaging correlation analysis"""
        engine = insights_engine
        
        # Use responses that have neuroimaging data
        neuro_responses = [r for r in sample_responses if r.completion_status == 'completed']
        
        result = await engine._analyze_neuroimaging_correlations(sample_survey, neuro_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.NEUROIMAGING_CORRELATIONS.value
        
        correlations = result.supporting_data['correlations']
        
        # Should detect field strength distribution
        if 'field_strength_distribution' in correlations:
            assert isinstance(correlations['field_strength_distribution'], dict)
            assert '3T' in correlations['field_strength_distribution']  # Most common in test data
        
        # Should detect brain region patterns
        if 'popular_brain_regions' in correlations:
            assert isinstance(correlations['popular_brain_regions'], dict)
            assert 'Prefrontal Cortex' in correlations['popular_brain_regions']
    
    @pytest.mark.asyncio
    async def test_analyze_neuroimaging_correlations_no_data(self, insights_engine, db_session, sample_survey):
        """Test neuroimaging analysis with no neuroimaging data"""
        engine = insights_engine
        
        # Create responses without neuroimaging context
        non_neuro_responses = [
            SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id='non_neuro',
                responses={'general_q': 'answer'},
                completion_status='completed'
            )
        ]
        
        result = await engine._analyze_neuroimaging_correlations(sample_survey, non_neuro_responses, db_session)
        
        # Should return None when no neuroimaging data is present
        assert result is None


class TestQualityAssessment:
    """Test response quality assessment"""
    
    @pytest.mark.asyncio
    async def test_assess_response_quality(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test response quality assessment"""
        engine = insights_engine
        
        result = await engine._assess_response_quality(sample_survey, sample_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.QUALITY_ASSESSMENT.value
        
        supporting_data = result.supporting_data
        assert 'average_quality_score' in supporting_data
        assert 'quality_distribution' in supporting_data
        assert 'sample_size' in supporting_data
        
        # Should have quality distribution
        quality_dist = supporting_data['quality_distribution']
        assert 'high_quality' in quality_dist
        assert 'medium_quality' in quality_dist
        assert 'low_quality' in quality_dist
        
        # Should detect some quality issues from test data (very fast responses)
        assert supporting_data['low_quality'] > 0
    
    @pytest.mark.asyncio
    async def test_assess_quality_fast_completion(self, insights_engine, db_session, sample_survey):
        """Test quality assessment with fast completion times"""
        engine = insights_engine
        
        # Create responses with suspiciously fast completion
        fast_responses = []
        for i in range(5):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'fast_{i}',
                responses={'q1': str(i), 'q2': str(i), 'q3': str(i)},
                completion_time_seconds=30,  # Very fast
                completion_status='completed'
            )
            fast_responses.append(response)
        
        result = await engine._assess_response_quality(sample_survey, fast_responses, db_session)
        
        assert result is not None
        # Should detect low quality due to fast completion
        assert result.supporting_data['average_quality_score'] < 0.8
        assert 'too_fast' in str(result.supporting_data.get('quality_issues', []))


class TestComparativeAnalysis:
    """Test comparative analysis"""
    
    @pytest.mark.asyncio
    async def test_comparative_analysis(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test comparative analysis with similar surveys"""
        engine = insights_engine
        
        # Create similar surveys
        similar_surveys = []
        for i in range(3):
            similar_survey = Survey(
                id=str(uuid.uuid4()),
                title=f'Similar Survey {i}',
                category=sample_survey.category,  # Same category
                creator_id=str(uuid.uuid4()),
                status='completed'
            )
            similar_surveys.append(similar_survey)
            db_session.add(similar_survey)
        
        # Add responses to similar surveys
        for i, similar_survey in enumerate(similar_surveys):
            for j in range(i + 2):  # Varying response counts: 2, 3, 4
                response = SurveyResponse(
                    id=str(uuid.uuid4()),
                    survey_id=similar_survey.id,
                    participant_id=f'similar_{i}_{j}',
                    responses={'q1': 'answer'},
                    completion_status='completed'
                )
                db_session.add(response)
        
        db_session.commit()
        
        completed_responses = [r for r in sample_responses if r.completion_status == 'completed']
        result = await engine._comparative_analysis(sample_survey, completed_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.COMPARATIVE_ANALYSIS.value
        
        supporting_data = result.supporting_data
        assert 'current_responses' in supporting_data
        assert 'similar_surveys_count' in supporting_data
        assert 'average_similar_responses' in supporting_data
        assert 'percentile_rank' in supporting_data
    
    @pytest.mark.asyncio
    async def test_comparative_analysis_no_similar_surveys(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test comparative analysis with no similar surveys"""
        engine = insights_engine
        
        completed_responses = [r for r in sample_responses if r.completion_status == 'completed']
        result = await engine._comparative_analysis(sample_survey, completed_responses, db_session)
        
        # Should return None when no similar surveys exist
        assert result is None


class TestPredictiveInsights:
    """Test predictive insights generation"""
    
    @pytest.mark.asyncio
    async def test_generate_predictions(self, insights_engine, db_session, sample_survey):
        """Test predictive insights generation"""
        engine = insights_engine
        
        # Create responses over time to establish trend
        prediction_responses = []
        base_time = datetime.utcnow() - timedelta(days=10)
        
        # Create increasing response pattern (2, 3, 4 responses per day)
        day_responses = [2, 3, 4, 3, 4, 5, 4, 5, 6, 7]
        
        for day, count in enumerate(day_responses):
            for i in range(count):
                response = SurveyResponse(
                    id=str(uuid.uuid4()),
                    survey_id=sample_survey.id,
                    participant_id=f'pred_{day}_{i}',
                    responses={'q1': 'answer'},
                    completion_status='completed',
                    submitted_at=base_time + timedelta(days=day, hours=i)
                )
                prediction_responses.append(response)
                db_session.add(response)
        
        db_session.commit()
        
        result = await engine._generate_predictions(sample_survey, prediction_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.PREDICTIVE_INSIGHTS.value
        
        supporting_data = result.supporting_data
        assert 'trend' in supporting_data
        assert 'recent_daily_rate' in supporting_data
        assert 'overall_daily_rate' in supporting_data
        assert 'projected_total_responses' in supporting_data
        
        # Should detect increasing trend
        assert supporting_data['trend'] in ['Increasing', 'Stable']
    
    @pytest.mark.asyncio
    async def test_generate_predictions_insufficient_data(self, insights_engine, db_session, sample_survey):
        """Test predictions with insufficient data"""
        engine = insights_engine
        
        # Too few responses for prediction
        few_responses = []
        for i in range(3):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'few_{i}',
                responses={'q1': 'answer'},
                completion_status='completed'
            )
            few_responses.append(response)
        
        result = await engine._generate_predictions(sample_survey, few_responses, db_session)
        
        # Should return None due to insufficient data
        assert result is None


class TestAnomalyDetection:
    """Test anomaly detection"""
    
    @pytest.mark.asyncio
    async def test_detect_anomalies(self, insights_engine, db_session, sample_survey, sample_responses):
        """Test anomaly detection"""
        engine = insights_engine
        
        result = await engine._detect_anomalies(sample_survey, sample_responses, db_session)
        
        assert result is not None
        assert result.insight_type == InsightType.ANOMALY_DETECTION.value
        
        supporting_data = result.supporting_data
        assert 'anomalies' in supporting_data
        assert 'sample_size' in supporting_data
        
        # Should detect duplicate IP addresses from test data
        assert supporting_data['duplicate_ip_count'] > 0
        
        # Should have recommendations
        assert len(result.recommendations) > 0
    
    @pytest.mark.asyncio
    async def test_detect_completion_time_anomalies(self, insights_engine, db_session, sample_survey):
        """Test detection of completion time anomalies"""
        engine = insights_engine
        
        # Create responses with normal and outlier completion times
        anomaly_responses = []
        
        # Normal responses (300-400 seconds)
        for i in range(20):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'normal_{i}',
                responses={'q1': 'answer'},
                completion_time_seconds=300 + i * 5,
                completion_status='completed'
            )
            anomaly_responses.append(response)
        
        # Outlier responses (very fast and very slow)
        outliers = [
            SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id='outlier_fast',
                responses={'q1': 'answer'},
                completion_time_seconds=10,  # Very fast
                completion_status='completed'
            ),
            SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id='outlier_slow',
                responses={'q1': 'answer'},
                completion_time_seconds=3000,  # Very slow
                completion_status='completed'
            )
        ]
        
        anomaly_responses.extend(outliers)
        
        result = await engine._detect_anomalies(sample_survey, anomaly_responses, db_session)
        
        assert result is not None
        # Should detect completion time outliers
        assert result.supporting_data['completion_time_outliers'] >= 2


class TestUtilityMethods:
    """Test utility methods"""
    
    @patch('brain_researcher.services.orchestrator.survey_insights.get_db')
    @pytest.mark.asyncio
    async def test_generate_realtime_insights(self, mock_get_db, insights_engine, db_session):
        """Test real-time insights generation"""
        mock_get_db.return_value = db_session
        
        engine = insights_engine
        
        # Create response
        response = SurveyResponse(
            id=str(uuid.uuid4()),
            survey_id=str(uuid.uuid4()),
            participant_id='test_user',
            responses={'q1': 'answer'},
            completion_time_seconds=15,  # Very fast - should affect quality
            completion_status='completed'
        )
        db_session.add(response)
        db_session.commit()
        
        await engine._generate_realtime_insights(response.survey_id, response, db_session)
        
        # Should update response metadata with quality score
        assert response.response_metadata is not None
        assert 'quality_score' in response.response_metadata
        assert response.response_metadata['quality_score'] < 1.0  # Should be penalized for fast completion
    
    @patch('brain_researcher.services.orchestrator.survey_insights.get_db')
    @pytest.mark.asyncio
    async def test_update_cumulative_analytics(self, mock_get_db, insights_engine, db_session, sample_survey, sample_responses):
        """Test cumulative analytics update"""
        mock_get_db.return_value = db_session
        
        engine = insights_engine
        
        await engine._update_cumulative_analytics(sample_survey.id, db_session)
        
        # Should create analytics record
        analytics = db_session.query(SurveyResponseAnalytics).filter_by(
            survey_id=sample_survey.id,
            analytics_type='daily_summary'
        ).first()
        
        assert analytics is not None
        assert 'total_responses' in analytics.analytics_data
        assert 'completed_responses' in analytics.analytics_data
        assert 'completion_rate' in analytics.analytics_data
    
    @pytest.mark.asyncio
    async def test_save_insight(self, insights_engine, db_session, sample_survey):
        """Test saving insight to database"""
        engine = insights_engine
        
        insight_result = InsightResult(
            insight_type=InsightType.SENTIMENT_ANALYSIS.value,
            title='Test Insight',
            description='Test description',
            confidence_score=0.85,
            supporting_data={'test': 'data'},
            methodology={'algorithm': 'test_algo'}
        )
        
        saved_insight = await engine._save_insight(sample_survey.id, insight_result, db_session)
        
        assert saved_insight is not None
        assert saved_insight.survey_id == sample_survey.id
        assert saved_insight.insight_type == insight_result.insight_type
        assert saved_insight.title == insight_result.title
        assert saved_insight.confidence_score == insight_result.confidence_score
        assert saved_insight.generated_by == 'survey_insights_engine_v1'
    
    def test_analyze_numeric_distribution(self, insights_engine):
        """Test numeric distribution analysis"""
        engine = insights_engine
        
        # Test with valid numeric data
        numeric_data = [1, 2, 3, 4, 5, 4, 3, 2, 1]
        result = engine._analyze_numeric_distribution(numeric_data)
        
        assert 'mean' in result
        assert 'median' in result
        assert 'std' in result
        assert 'min' in result
        assert 'max' in result
        assert 'count' in result
        
        assert result['mean'] == np.mean(numeric_data)
        assert result['min'] == 1
        assert result['max'] == 5
        assert result['count'] == 9
        
        # Test with empty data
        empty_result = engine._analyze_numeric_distribution([])
        assert empty_result == {}
        
        # Test with non-numeric data
        non_numeric_result = engine._analyze_numeric_distribution(['a', 'b', 'c'])
        assert non_numeric_result == {}


class TestErrorHandling:
    """Test error handling in insights engine"""
    
    @patch('brain_researcher.services.orchestrator.survey_insights.get_db')
    @pytest.mark.asyncio
    async def test_process_new_response_not_found(self, mock_get_db, insights_engine, db_session):
        """Test processing non-existent response"""
        mock_get_db.return_value = db_session
        
        engine = insights_engine
        
        # Should handle gracefully when response not found
        await engine.process_new_response('fake_survey_id', 'fake_response_id')
        
        # Should not raise exception
        assert True
    
    @pytest.mark.asyncio
    async def test_generate_insights_error_handling(self, insights_engine, db_session):
        """Test error handling in insights generation"""
        engine = insights_engine
        
        # Mock a generator that raises an exception
        async def failing_generator(survey, responses, db):
            raise Exception("Test error")
        
        # Replace one generator with failing one
        original_generator = engine.insight_generators[InsightType.SENTIMENT_ANALYSIS.value]
        engine.insight_generators[InsightType.SENTIMENT_ANALYSIS.value] = failing_generator
        
        try:
            # Should handle exception and continue with other generators
            insights = await engine.generate_insights(['fake_survey_id'], db_session)
            
            assert 'fake_survey_id' in insights
            assert insights['fake_survey_id']['error'] is not None
            
        finally:
            # Restore original generator
            engine.insight_generators[InsightType.SENTIMENT_ANALYSIS.value] = original_generator


if __name__ == '__main__':
    pytest.main([__file__])
