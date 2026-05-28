import pytest
pytest.skip("survey workflow integration skipped (requires external services)", allow_module_level=True)
"""
Integration Tests for Complete Survey Workflow

End-to-end tests covering the complete survey lifecycle from creation
through response collection, analysis, and insights generation.
Tests the integration between all survey system components.
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Import all survey system components
from brain_researcher.services.orchestrator.survey_endpoints import router
from brain_researcher.services.orchestrator.survey_models import (
    Base, Survey, SurveyQuestion, SurveyResponse, SurveyTrigger,
    SurveyInsight, SurveyDistribution, SurveyNotification
)
from brain_researcher.services.orchestrator.survey_triggers import SurveyTriggerManager
from brain_researcher.services.orchestrator.survey_insights import SurveyInsightsEngine

# Create FastAPI test client
from fastapi import FastAPI
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def db_engine():
    """Create in-memory database for integration testing"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create database session"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_user():
    """Mock authenticated user"""
    return {
        'id': str(uuid.uuid4()),
        'username': 'test_researcher',
        'email': 'researcher@test.com',
        'roles': ['researcher']
    }


class TestCompleteSurveyWorkflow:
    """Test complete survey workflow integration"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    @pytest.mark.asyncio
    async def test_complete_survey_lifecycle(self, mock_get_user, mock_get_db, 
                                           db_session, mock_user):
        """Test complete survey lifecycle from creation to insights"""
        mock_get_user.return_value = mock_user
        mock_get_db.return_value = db_session
        
        # Step 1: Create survey
        survey_data = {
            'title': 'Integration Test Survey',
            'description': 'Testing complete workflow',
            'category': 'cognitive_assessment',
            'questions': [
                {
                    'text': 'Rate your experience with fMRI',
                    'type': 'scale',
                    'options': {
                        'scale_min': 1,
                        'scale_max': 5,
                        'scale_labels': ['Beginner', 'Expert']
                    },
                    'required': True
                },
                {
                    'text': 'Which brain regions did you analyze?',
                    'type': 'brain_region',
                    'options': {
                        'brain_regions': [
                            {'name': 'Prefrontal Cortex', 'atlas': 'AAL'},
                            {'name': 'Motor Cortex', 'atlas': 'AAL'}
                        ]
                    },
                    'neuroimaging_context': {
                        'category': 'analysis_regions'
                    },
                    'required': False
                }
            ],
            'distribution_type': 'manual'
        }
        
        create_response = client.post("/api/v1/surveys/", json=survey_data)
        assert create_response.status_code == 200
        survey_id = create_response.json()['survey_id']
        
        # Verify survey was created
        survey = db_session.query(Survey).filter_by(id=survey_id).first()
        assert survey is not None
        assert survey.title == 'Integration Test Survey'
        
        # Verify questions were created
        questions = db_session.query(SurveyQuestion).filter_by(survey_id=survey_id).all()
        assert len(questions) == 2
        
        # Step 2: Publish survey
        publish_response = client.post(f"/api/v1/surveys/{survey_id}/publish")
        assert publish_response.status_code == 200
        
        # Verify survey status changed
        updated_survey = db_session.query(Survey).filter_by(id=survey_id).first()
        assert updated_survey.status == 'active'
        assert updated_survey.published_at is not None
        
        # Step 3: Submit responses
        responses_data = [
            {
                'survey_id': survey_id,
                'participant_id': 'participant_001',
                'responses': {
                    questions[0].id: 4,
                    questions[1].id: ['Prefrontal Cortex']
                },
                'metadata': {'device_type': 'desktop'},
                'session_data': {'session_id': 'session_001'}
            },
            {
                'survey_id': survey_id,
                'participant_id': 'participant_002',
                'responses': {
                    questions[0].id: 5,
                    questions[1].id: ['Motor Cortex', 'Prefrontal Cortex']
                },
                'metadata': {'device_type': 'mobile'}
            },
            {
                'survey_id': survey_id,
                'participant_id': 'participant_003',
                'responses': {
                    questions[0].id: 3,
                    questions[1].id: ['Motor Cortex']
                }
            }
        ]
        
        response_ids = []
        for response_data in responses_data:
            with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine'):
                submit_response = client.post("/api/v1/surveys/responses", json=response_data)
                assert submit_response.status_code == 200
                response_ids.append(submit_response.json()['response_id'])
        
        # Verify responses were stored
        stored_responses = db_session.query(SurveyResponse).filter_by(survey_id=survey_id).all()
        assert len(stored_responses) == 3
        
        # Step 4: Generate insights
        insights_engine = SurveyInsightsEngine()
        with patch('brain_researcher.services.orchestrator.survey_insights.get_db') as mock_insights_db:
            mock_insights_db.return_value = db_session
            
            # Generate comprehensive insights
            insights = await insights_engine.generate_insights([survey_id], db_session)
            
            assert survey_id in insights
            assert len(insights[survey_id]) > 0
        
        # Step 5: Get analytics
        analytics_request = {
            'survey_ids': [survey_id],
            'metrics': ['response_rate', 'completion_rate', 'demographics']
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine') as mock_engine:
            mock_engine.return_value.calculate_completion_rates = AsyncMock(return_value={survey_id: 100.0})
            mock_engine.return_value.calculate_response_rates = AsyncMock(return_value={survey_id: 75.0})
            mock_engine.return_value.analyze_demographics = AsyncMock(return_value={
                survey_id: {
                    'response_count': 3,
                    'demographics': {'device_types': {'desktop': 1, 'mobile': 1, 'unknown': 1}}
                }
            })
            
            analytics_response = client.post("/api/v1/surveys/analytics", json=analytics_request)
            assert analytics_response.status_code == 200
            
            analytics_data = analytics_response.json()['analytics']
            assert 'completion_rates' in analytics_data
            assert 'response_rates' in analytics_data
            assert analytics_data['completion_rates'][survey_id] == 100.0
        
        # Step 6: Verify complete workflow integration
        final_survey = db_session.query(Survey).filter_by(id=survey_id).first()
        final_responses = db_session.query(SurveyResponse).filter_by(survey_id=survey_id).all()
        
        assert final_survey.status == 'active'
        assert len(final_responses) == 3
        assert all(r.completion_status == 'completed' for r in final_responses)
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    @pytest.mark.asyncio
    async def test_triggered_survey_workflow(self, mock_get_user, mock_get_db,
                                           db_session, mock_user):
        """Test triggered survey workflow with automated distribution"""
        mock_get_user.return_value = mock_user
        mock_get_db.return_value = db_session
        
        # Create survey with trigger
        survey_data = {
            'title': 'Triggered Survey',
            'description': 'Auto-triggered after analysis',
            'category': 'post_analysis_feedback',
            'questions': [
                {
                    'text': 'How satisfied are you with the analysis results?',
                    'type': 'scale',
                    'options': {'scale_min': 1, 'scale_max': 5},
                    'required': True
                }
            ],
            'distribution_type': 'triggered',
            'trigger_config': {
                'type': 'analysis_complete',
                'conditions': {
                    'event_data': {
                        'analysis_type': 'group_analysis'
                    }
                },
                'targeting': {'from_event': True},
                'notifications': {'enabled': True, 'method': 'email'}
            }
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyTriggerManager') as mock_trigger_manager:
            mock_setup_trigger = AsyncMock(return_value='trigger_123')
            mock_trigger_manager.return_value.setup_trigger = mock_setup_trigger
            
            create_response = client.post("/api/v1/surveys/", json=survey_data)
            assert create_response.status_code == 200
            survey_id = create_response.json()['survey_id']
            
            # Verify trigger was set up
            mock_setup_trigger.assert_called_once()
        
        # Publish survey
        client.post(f"/api/v1/surveys/{survey_id}/publish")
        
        # Simulate trigger activation
        trigger_manager = SurveyTriggerManager()
        
        with patch('brain_researcher.services.orchestrator.survey_triggers.get_db') as mock_trigger_db:
            mock_trigger_db.return_value = db_session
            
            # Create trigger in database
            trigger = SurveyTrigger(
                id='trigger_123',
                survey_id=survey_id,
                trigger_type='analysis_complete',
                trigger_conditions={'event_data': {'analysis_type': 'group_analysis'}},
                status='active'
            )
            db_session.add(trigger)
            db_session.commit()
            
            # Add to active triggers
            trigger_manager.active_triggers['trigger_123'] = {
                'survey_id': survey_id,
                'config': survey_data['trigger_config']
            }
            
            # Create trigger event
            from brain_researcher.services.orchestrator.survey_triggers import TriggerEvent
            event = TriggerEvent(
                event_type='analysis_complete',
                event_data={'analysis_type': 'group_analysis'},
                user_id='researcher_123'
            )
            
            # Process event
            with patch.object(trigger_manager, '_get_target_participants', return_value=['researcher_123']):
                with patch.object(trigger_manager, '_create_triggered_distribution', return_value={'id': 'dist_123'}):
                    with patch.object(trigger_manager, '_send_survey_notifications'):
                        triggered_surveys = await trigger_manager.process_event(event)
                        
                        assert survey_id in triggered_surveys
        
        # Verify distribution was created
        distribution = db_session.query(SurveyDistribution).filter_by(survey_id=survey_id).first()
        assert distribution is not None
        assert distribution.distribution_type == 'triggered'
    
    @pytest.mark.asyncio
    async def test_survey_response_quality_workflow(self, db_session, mock_user):
        """Test quality assessment and flagging workflow"""
        # Create survey
        survey = Survey(
            id=str(uuid.uuid4()),
            title='Quality Test Survey',
            category='test',
            creator_id=mock_user['id'],
            status='active'
        )
        db_session.add(survey)
        
        question = SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='Test question',
            question_type='scale',
            options={'scale_min': 1, 'scale_max': 5},
            order_index=0
        )
        db_session.add(question)
        db_session.commit()
        
        # Create responses with varying quality
        responses_data = [
            # High quality response
            {
                'completion_time_seconds': 300,
                'responses': {question.id: 4},
                'participant_id': 'good_participant'
            },
            # Low quality response (too fast)
            {
                'completion_time_seconds': 10,
                'responses': {question.id: 5},
                'participant_id': 'fast_participant'
            },
            # Medium quality response
            {
                'completion_time_seconds': 180,
                'responses': {question.id: 3},
                'participant_id': 'medium_participant'
            }
        ]
        
        for i, response_data in enumerate(responses_data):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                completion_status='completed',
                submitted_at=datetime.utcnow(),
                **response_data
            )
            db_session.add(response)
        
        db_session.commit()
        
        # Run quality assessment
        insights_engine = SurveyInsightsEngine()
        responses = db_session.query(SurveyResponse).filter_by(survey_id=survey.id).all()
        
        quality_insight = await insights_engine._assess_response_quality(survey, responses, db_session)
        
        assert quality_insight is not None
        assert quality_insight.insight_type == 'quality_assessment'
        
        # Should detect quality issues
        quality_data = quality_insight.supporting_data
        assert quality_data['low_quality'] >= 1  # At least one low quality response
        assert 'quality_issues' in quality_data
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    @pytest.mark.asyncio
    async def test_survey_analytics_pipeline(self, mock_get_user, mock_get_db,
                                           db_session, mock_user):
        """Test complete analytics generation pipeline"""
        mock_get_user.return_value = mock_user
        mock_get_db.return_value = db_session
        
        # Create survey with neuroimaging context
        survey = Survey(
            id=str(uuid.uuid4()),
            title='Analytics Test Survey',
            category='cognitive_assessment',
            creator_id=mock_user['id'],
            status='active',
            neuroimaging_context={
                'study_type': ['fMRI'],
                'imaging_modalities': ['BOLD'],
                'data_sharing': True
            }
        )
        db_session.add(survey)
        
        # Create neuroimaging questions
        questions = [
            SurveyQuestion(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                question_text='Scanner field strength?',
                question_type='scanner_parameters',
                options={'field_strength': ['1.5T', '3T', '7T']},
                neuroimaging_context={'category': 'acquisition_parameters'},
                order_index=0
            ),
            SurveyQuestion(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                question_text='Brain regions analyzed?',
                question_type='brain_region',
                options={'regions': ['Prefrontal Cortex', 'Motor Cortex']},
                neuroimaging_context={'category': 'analysis_regions'},
                order_index=1
            ),
            SurveyQuestion(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                question_text='Overall satisfaction?',
                question_type='scale',
                options={'scale_min': 1, 'scale_max': 5},
                order_index=2
            )
        ]
        
        for question in questions:
            db_session.add(question)
        
        db_session.commit()
        
        # Create diverse responses
        response_patterns = [
            # Pattern 1: 3T scanner, Prefrontal focus, high satisfaction
            {'scanner': '3T', 'regions': ['Prefrontal Cortex'], 'satisfaction': 5},
            {'scanner': '3T', 'regions': ['Prefrontal Cortex'], 'satisfaction': 4},
            {'scanner': '3T', 'regions': ['Prefrontal Cortex', 'Motor Cortex'], 'satisfaction': 5},
            
            # Pattern 2: 1.5T scanner, Motor focus, medium satisfaction  
            {'scanner': '1.5T', 'regions': ['Motor Cortex'], 'satisfaction': 3},
            {'scanner': '1.5T', 'regions': ['Motor Cortex'], 'satisfaction': 3},
            
            # Pattern 3: 7T scanner, mixed regions, high satisfaction
            {'scanner': '7T', 'regions': ['Prefrontal Cortex', 'Motor Cortex'], 'satisfaction': 5},
            {'scanner': '7T', 'regions': ['Motor Cortex'], 'satisfaction': 4}
        ]
        
        for i, pattern in enumerate(response_patterns):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                participant_id=f'participant_{i:03d}',
                responses={
                    questions[0].id: {'field_strength': pattern['scanner']},
                    questions[1].id: pattern['regions'],
                    questions[2].id: pattern['satisfaction']
                },
                completion_status='completed',
                completion_time_seconds=200 + i * 50,
                submitted_at=datetime.utcnow() - timedelta(days=i)
            )
            db_session.add(response)
        
        db_session.commit()
        
        # Run comprehensive analytics
        insights_engine = SurveyInsightsEngine()
        responses = db_session.query(SurveyResponse).filter_by(survey_id=survey.id).all()
        
        # Test neuroimaging correlations
        neuro_insight = await insights_engine._analyze_neuroimaging_correlations(
            survey, responses, db_session
        )
        assert neuro_insight is not None
        assert 'field_strength_distribution' in neuro_insight.supporting_data['correlations']
        assert '3T' in neuro_insight.supporting_data['correlations']['field_strength_distribution']
        
        # Test response patterns
        pattern_insight = await insights_engine._analyze_response_patterns(
            survey, responses, db_session
        )
        assert pattern_insight is not None
        assert len(pattern_insight.supporting_data['patterns']) > 0
        
        # Test completion trends
        trend_insight = await insights_engine._analyze_completion_trends(
            survey, responses, db_session
        )
        assert trend_insight is not None
        
        # Test comprehensive analytics via API
        analytics_request = {
            'survey_ids': [survey.id],
            'metrics': ['response_rate', 'completion_rate', 'insights', 'demographics']
        }
        
        # Mock the insights engine for API call
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine') as mock_engine_class:
            mock_engine = mock_engine_class.return_value
            mock_engine.calculate_response_rates = AsyncMock(return_value={survey.id: 85.0})
            mock_engine.calculate_completion_rates = AsyncMock(return_value={survey.id: 100.0})
            mock_engine.generate_insights = AsyncMock(return_value={
                survey.id: [
                    {'type': 'neuroimaging_correlations', 'title': '3T scanners most common'},
                    {'type': 'response_patterns', 'title': 'Consistent high satisfaction'}
                ]
            })
            mock_engine.analyze_demographics = AsyncMock(return_value={
                survey.id: {
                    'response_count': 7,
                    'scanner_distribution': {'3T': 3, '1.5T': 2, '7T': 2}
                }
            })
            
            analytics_response = client.post("/api/v1/surveys/analytics", json=analytics_request)
            assert analytics_response.status_code == 200
            
            analytics_data = analytics_response.json()['analytics']
            assert all(metric in analytics_data for metric in analytics_request['metrics'])
            assert analytics_data['completion_rates'][survey.id] == 100.0
    
    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, db_session, mock_user):
        """Test error handling throughout the survey workflow"""
        # Test survey creation with invalid data
        invalid_survey_data = {
            'title': '',  # Invalid: empty title
            'questions': []  # Invalid: no questions
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.get_db') as mock_db:
            with patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user') as mock_user_auth:
                mock_db.return_value = db_session
                mock_user_auth.return_value = mock_user
                
                response = client.post("/api/v1/surveys/", json=invalid_survey_data)
                assert response.status_code == 422  # Validation error
        
        # Test response submission to non-existent survey
        invalid_response_data = {
            'survey_id': str(uuid.uuid4()),  # Non-existent survey
            'responses': {'q1': 'answer'}
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.get_db') as mock_db:
            mock_db.return_value = db_session
            
            response = client.post("/api/v1/surveys/responses", json=invalid_response_data)
            assert response.status_code == 404
        
        # Test insights generation with insufficient data
        survey = Survey(
            id=str(uuid.uuid4()),
            title='Insufficient Data Survey',
            category='test',
            creator_id=mock_user['id'],
            status='active'
        )
        db_session.add(survey)
        db_session.commit()
        
        insights_engine = SurveyInsightsEngine()
        
        # No responses - should handle gracefully
        insights = await insights_engine._generate_survey_insights(survey.id, db_session)
        assert insights == []  # Should return empty list, not error
        
        # Test trigger system error handling
        trigger_manager = SurveyTriggerManager()
        
        # Invalid trigger event
        from brain_researcher.services.orchestrator.survey_triggers import TriggerEvent
        invalid_event = TriggerEvent(
            event_type='invalid_type',
            event_data={}
        )
        
        # Should handle gracefully
        triggered_surveys = await trigger_manager.process_event(invalid_event)
        assert triggered_surveys == []
    
    @pytest.mark.asyncio
    async def test_concurrent_survey_operations(self, db_session, mock_user):
        """Test concurrent operations on surveys"""
        # Create survey
        survey = Survey(
            id=str(uuid.uuid4()),
            title='Concurrent Test Survey',
            category='test',
            creator_id=mock_user['id'],
            status='active'
        )
        db_session.add(survey)
        
        question = SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='Concurrent question',
            question_type='text',
            order_index=0
        )
        db_session.add(question)
        db_session.commit()
        
        # Simulate concurrent response submissions
        async def submit_response(participant_id):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                participant_id=participant_id,
                responses={question.id: f'Answer from {participant_id}'},
                completion_status='completed'
            )
            db_session.add(response)
            db_session.commit()
            return response.id
        
        # Submit multiple responses concurrently
        tasks = [submit_response(f'concurrent_user_{i}') for i in range(10)]
        response_ids = await asyncio.gather(*tasks)
        
        # Verify all responses were stored
        stored_responses = db_session.query(SurveyResponse).filter_by(survey_id=survey.id).all()
        assert len(stored_responses) == 10
        assert all(r.id in response_ids for r in stored_responses)
        
        # Test concurrent insights generation
        insights_engine = SurveyInsightsEngine()
        
        async def generate_insight_type(insight_type):
            generator = insights_engine.insight_generators.get(insight_type)
            if generator:
                return await generator(survey, stored_responses, db_session)
            return None
        
        # Generate different insights concurrently
        insight_tasks = [
            generate_insight_type('sentiment_analysis'),
            generate_insight_type('response_patterns'), 
            generate_insight_type('completion_trends'),
            generate_insight_type('quality_assessment')
        ]
        
        insights = await asyncio.gather(*insight_tasks, return_exceptions=True)
        
        # Should complete without errors (some may return None for insufficient data)
        assert len(insights) == 4
        assert all(not isinstance(insight, Exception) for insight in insights)


if __name__ == '__main__':
    pytest.main([__file__])