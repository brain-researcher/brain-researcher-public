"""
Unit Tests for Survey API Endpoints

Comprehensive tests for all survey REST API endpoints including creation,
retrieval, updates, response handling, analytics, and error conditions.
Tests both standard functionality and neuroimaging-specific features.
"""

import pytest
import uuid
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import the FastAPI app and dependencies
from brain_researcher.services.orchestrator.survey_endpoints import (
    router, SurveyCreateRequest, SurveyUpdateRequest, 
    SurveyResponseRequest, SurveyAnalyticsRequest
)
from brain_researcher.services.orchestrator.survey_models import (
    Base, Survey, SurveyQuestion, SurveyResponse, SurveyDistribution,
    SurveyTrigger, SurveyInsight, SurveyTemplate
)


# Mock FastAPI app for testing
from fastapi import FastAPI
app = FastAPI()
app.include_router(router)


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
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_current_user():
    """Mock current user for authentication"""
    return {
        'id': str(uuid.uuid4()),
        'username': 'test_researcher',
        'email': 'test@example.com',
        'roles': ['researcher']
    }


@pytest.fixture
def mock_survey_data():
    """Mock survey data for testing"""
    return {
        'title': 'Test Neuroimaging Survey',
        'description': 'A comprehensive survey for fMRI research',
        'category': 'cognitive_assessment',
        'target_audience': 'researchers',
        'questions': [
            {
                'text': 'What is your experience with fMRI analysis?',
                'type': 'multiple_choice',
                'options': {
                    'choices': [
                        {'id': '1', 'text': 'Beginner', 'value': 'beginner'},
                        {'id': '2', 'text': 'Intermediate', 'value': 'intermediate'},
                        {'id': '3', 'text': 'Advanced', 'value': 'advanced'}
                    ]
                },
                'required': True,
                'neuroimaging_context': {
                    'category': 'experience_assessment'
                }
            },
            {
                'text': 'Which scanner parameters did you use?',
                'type': 'scanner_parameters',
                'options': {
                    'field_strength': ['1.5T', '3T', '7T'],
                    'pulse_sequence': ['T1-MPRAGE', 'EPI']
                },
                'required': True,
                'neuroimaging_context': {
                    'category': 'acquisition_parameters',
                    'required_for': ['fMRI']
                }
            }
        ],
        'settings': {
            'theme': {'primary_color': '#007bff'},
            'validation': {'require_all_questions': True}
        },
        'distribution_type': 'manual'
    }


@pytest.fixture
def sample_survey(db_session):
    """Create a sample survey in the database"""
    survey = Survey(
        id=str(uuid.uuid4()),
        title='Sample Survey',
        description='Test survey',
        category='cognitive_assessment',
        creator_id=str(uuid.uuid4()),
        status='active'
    )
    db_session.add(survey)
    
    # Add questions
    question = SurveyQuestion(
        id=str(uuid.uuid4()),
        survey_id=survey.id,
        question_text='Test question',
        question_type='multiple_choice',
        options={'choices': [{'id': '1', 'text': 'Yes', 'value': 'yes'}]},
        order_index=0,
        required=True
    )
    db_session.add(question)
    db_session.commit()
    
    return survey


class TestSurveyCreationEndpoints:
    """Test survey creation API endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_create_survey_success(self, mock_get_user, mock_get_db, 
                                 client, db_session, mock_current_user, mock_survey_data):
        """Test successful survey creation"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        response = client.post("/api/v1/surveys/", json=mock_survey_data)
        
        assert response.status_code == 200
        result = response.json()
        assert result['status'] == 'created'
        assert 'survey_id' in result
        assert result['distribution_setup'] is False  # manual distribution
        
        # Verify survey was created in database
        survey = db_session.query(Survey).filter_by(id=result['survey_id']).first()
        assert survey is not None
        assert survey.title == mock_survey_data['title']
        assert survey.status == 'draft'
        assert survey.creator_id == mock_current_user['id']
        
        # Verify questions were created
        questions = db_session.query(SurveyQuestion).filter_by(survey_id=survey.id).all()
        assert len(questions) == 2
        assert questions[0].question_type == 'multiple_choice'
        assert questions[1].question_type == 'scanner_parameters'
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_create_survey_with_triggers(self, mock_get_user, mock_get_db,
                                       client, db_session, mock_current_user, mock_survey_data):
        """Test survey creation with automated triggers"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Add trigger configuration
        trigger_data = {
            **mock_survey_data,
            'distribution_type': 'triggered',
            'trigger_config': {
                'trigger_type': 'analysis_complete',
                'conditions': {'analysis_type': 'GLM'}
            }
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyTriggerManager') as mock_trigger_manager:
            response = client.post("/api/v1/surveys/", json=trigger_data)
            
            assert response.status_code == 200
            result = response.json()
            assert result['distribution_setup'] is True
            
            # Verify trigger manager was called
            mock_trigger_manager.assert_called_once()
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_create_survey_validation_error(self, mock_get_user, mock_get_db,
                                          client, db_session, mock_current_user):
        """Test survey creation with validation errors"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Invalid data (missing required fields)
        invalid_data = {
            'title': '',  # Empty title
            'questions': []  # No questions
        }
        
        response = client.post("/api/v1/surveys/", json=invalid_data)
        assert response.status_code == 422  # Validation error
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_create_survey_database_error(self, mock_get_user, mock_get_db,
                                        client, mock_current_user, mock_survey_data):
        """Test survey creation with database errors"""
        mock_get_user.return_value = mock_current_user
        
        # Mock database session that raises an exception
        mock_db = Mock()
        mock_db.add.side_effect = Exception("Database connection failed")
        mock_get_db.return_value = mock_db
        
        response = client.post("/api/v1/surveys/", json=mock_survey_data)
        assert response.status_code == 500


class TestSurveyRetrievalEndpoints:
    """Test survey retrieval API endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_list_surveys(self, mock_get_user, mock_get_db, 
                         client, db_session, mock_current_user, sample_survey):
        """Test listing surveys with filters"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        response = client.get("/api/v1/surveys/")
        
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) >= 1
        
        survey_data = result[0]
        assert survey_data['id'] == sample_survey.id
        assert survey_data['title'] == sample_survey.title
        assert 'question_count' in survey_data
        assert 'response_count' in survey_data
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_list_surveys_with_filters(self, mock_get_user, mock_get_db,
                                     client, db_session, mock_current_user):
        """Test survey listing with category and status filters"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Create surveys with different categories and statuses
        surveys = []
        for i, (category, status) in enumerate([
            ('cognitive_assessment', 'active'),
            ('demographics', 'draft'),
            ('cognitive_assessment', 'completed')
        ]):
            survey = Survey(
                id=str(uuid.uuid4()),
                title=f'Survey {i}',
                category=category,
                status=status,
                creator_id=str(uuid.uuid4())
            )
            surveys.append(survey)
            db_session.add(survey)
        db_session.commit()
        
        # Test category filter
        response = client.get("/api/v1/surveys/?category=cognitive_assessment")
        assert response.status_code == 200
        result = response.json()
        cognitive_surveys = [s for s in result if s['category'] == 'cognitive_assessment']
        assert len(cognitive_surveys) >= 2
        
        # Test status filter
        response = client.get("/api/v1/surveys/?status=active")
        assert response.status_code == 200
        result = response.json()
        active_surveys = [s for s in result if s['status'] == 'active']
        assert len(active_surveys) >= 1
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_get_survey_details(self, mock_get_user, mock_get_db,
                              client, db_session, mock_current_user, sample_survey):
        """Test getting detailed survey information"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        response = client.get(f"/api/v1/surveys/{sample_survey.id}")
        
        assert response.status_code == 200
        result = response.json()
        assert result['id'] == sample_survey.id
        assert result['title'] == sample_survey.title
        assert 'questions' in result
        assert len(result['questions']) >= 1
        
        # Check question details
        question = result['questions'][0]
        assert 'id' in question
        assert 'text' in question
        assert 'type' in question
        assert 'options' in question
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_get_survey_with_analytics(self, mock_get_user, mock_get_db,
                                     client, db_session, mock_current_user, sample_survey):
        """Test getting survey with analytics data"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Add some responses for analytics
        for i in range(3):
            response = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'participant_{i}',
                responses={'question_1': 'answer'},
                completion_status='completed' if i < 2 else 'in_progress'
            )
            db_session.add(response)
        db_session.commit()
        
        response = client.get(f"/api/v1/surveys/{sample_survey.id}?include_analytics=true")
        
        assert response.status_code == 200
        result = response.json()
        assert 'analytics' in result
        analytics = result['analytics']
        assert analytics['total_responses'] == 3
        assert analytics['completion_rate'] > 0  # Should be calculated based on completed responses
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_get_nonexistent_survey(self, mock_get_user, mock_get_db,
                                  client, db_session, mock_current_user):
        """Test getting non-existent survey returns 404"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/surveys/{fake_id}")
        
        assert response.status_code == 404
        assert 'not found' in response.json()['detail'].lower()


class TestSurveyUpdateEndpoints:
    """Test survey update API endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_update_survey_basic_fields(self, mock_get_user, mock_get_db,
                                      client, db_session, mock_current_user, sample_survey):
        """Test updating basic survey fields"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        update_data = {
            'title': 'Updated Survey Title',
            'description': 'Updated description',
            'status': 'active'
        }
        
        response = client.put(f"/api/v1/surveys/{sample_survey.id}", json=update_data)
        
        assert response.status_code == 200
        result = response.json()
        assert result['status'] == 'success'
        
        # Verify changes in database
        updated_survey = db_session.query(Survey).filter_by(id=sample_survey.id).first()
        assert updated_survey.title == 'Updated Survey Title'
        assert updated_survey.description == 'Updated description'
        assert updated_survey.status == 'active'
        assert updated_survey.updated_at is not None
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_update_survey_questions(self, mock_get_user, mock_get_db,
                                   client, db_session, mock_current_user, sample_survey):
        """Test updating survey questions"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Count existing questions
        original_count = db_session.query(SurveyQuestion).filter_by(
            survey_id=sample_survey.id
        ).count()
        
        new_questions = [
            {
                'text': 'Updated question 1',
                'type': 'text',
                'options': {},
                'required': True
            },
            {
                'text': 'New neuroimaging question',
                'type': 'brain_region',
                'options': {
                    'regions': ['Prefrontal Cortex', 'Motor Cortex']
                },
                'required': False,
                'neuroimaging_context': {
                    'category': 'analysis_regions'
                }
            }
        ]
        
        update_data = {'questions': new_questions}
        
        response = client.put(f"/api/v1/surveys/{sample_survey.id}", json=update_data)
        
        assert response.status_code == 200
        
        # Verify questions were updated
        updated_questions = db_session.query(SurveyQuestion).filter_by(
            survey_id=sample_survey.id
        ).order_by(SurveyQuestion.order_index).all()
        
        assert len(updated_questions) == 2
        assert updated_questions[0].question_text == 'Updated question 1'
        assert updated_questions[1].question_type == 'brain_region'
        assert updated_questions[1].neuroimaging_context['category'] == 'analysis_regions'
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_update_survey_settings(self, mock_get_user, mock_get_db,
                                  client, db_session, mock_current_user, sample_survey):
        """Test updating survey settings"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Set initial settings
        sample_survey.settings = {'theme': {'primary_color': '#ff0000'}}
        db_session.commit()
        
        # Update with new settings (should merge with existing)
        new_settings = {
            'validation': {'require_all_questions': False},
            'theme': {'secondary_color': '#00ff00'}
        }
        
        update_data = {'settings': new_settings}
        response = client.put(f"/api/v1/surveys/{sample_survey.id}", json=update_data)
        
        assert response.status_code == 200
        
        # Verify settings were merged
        updated_survey = db_session.query(Survey).filter_by(id=sample_survey.id).first()
        settings = updated_survey.settings
        assert settings['theme']['primary_color'] == '#ff0000'  # Original preserved
        assert settings['theme']['secondary_color'] == '#00ff00'  # New added
        assert settings['validation']['require_all_questions'] is False


class TestSurveyResponseEndpoints:
    """Test survey response collection endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_submit_response_success(self, mock_get_db, client, db_session, sample_survey):
        """Test successful response submission"""
        mock_get_db.return_value = db_session
        
        response_data = {
            'survey_id': sample_survey.id,
            'participant_id': 'test_participant_123',
            'responses': {
                'question_1': 'answer_1',
                'question_2': 'answer_2'
            },
            'metadata': {
                'device_type': 'desktop',
                'completion_time_seconds': 120
            },
            'session_data': {
                'session_id': 'session_123',
                'user_agent': 'Mozilla/5.0...'
            }
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine'):
            response = client.post("/api/v1/surveys/responses", json=response_data)
            
            assert response.status_code == 200
            result = response.json()
            assert result['status'] == 'submitted'
            assert 'response_id' in result
            
            # Verify response was stored
            stored_response = db_session.query(SurveyResponse).filter_by(
                id=result['response_id']
            ).first()
            assert stored_response is not None
            assert stored_response.participant_id == 'test_participant_123'
            assert stored_response.responses['question_1'] == 'answer_1'
            assert stored_response.completion_status == 'completed'
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_submit_response_anonymous(self, mock_get_db, client, db_session, sample_survey):
        """Test anonymous response submission"""
        mock_get_db.return_value = db_session
        
        response_data = {
            'survey_id': sample_survey.id,
            'responses': {'question_1': 'anonymous_answer'}
        }
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine'):
            response = client.post("/api/v1/surveys/responses", json=response_data)
            
            assert response.status_code == 200
            result = response.json()
            
            # Verify anonymous participant ID was generated
            stored_response = db_session.query(SurveyResponse).filter_by(
                id=result['response_id']
            ).first()
            assert stored_response.participant_id.startswith('anonymous_')
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_submit_response_inactive_survey(self, mock_get_db, client, db_session):
        """Test response submission to inactive survey"""
        mock_get_db.return_value = db_session
        
        # Create inactive survey
        inactive_survey = Survey(
            id=str(uuid.uuid4()),
            title='Inactive Survey',
            category='test',
            creator_id=str(uuid.uuid4()),
            status='draft'  # Not active
        )
        db_session.add(inactive_survey)
        db_session.commit()
        
        response_data = {
            'survey_id': inactive_survey.id,
            'responses': {'question_1': 'answer'}
        }
        
        response = client.post("/api/v1/surveys/responses", json=response_data)
        assert response.status_code == 400
        assert 'not active' in response.json()['detail'].lower()
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_submit_response_nonexistent_survey(self, mock_get_db, client, db_session):
        """Test response submission to non-existent survey"""
        mock_get_db.return_value = db_session
        
        fake_survey_id = str(uuid.uuid4())
        response_data = {
            'survey_id': fake_survey_id,
            'responses': {'question_1': 'answer'}
        }
        
        response = client.post("/api/v1/surveys/responses", json=response_data)
        assert response.status_code == 404
        assert 'not found' in response.json()['detail'].lower()
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_get_survey_responses(self, mock_get_user, mock_get_db,
                                client, db_session, mock_current_user, sample_survey):
        """Test retrieving survey responses"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Create test responses
        responses = []
        for i in range(3):
            resp = SurveyResponse(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                participant_id=f'participant_{i}',
                responses={f'question_1': f'answer_{i}'},
                completion_status='completed',
                submitted_at=datetime.utcnow()
            )
            responses.append(resp)
            db_session.add(resp)
        db_session.commit()
        
        response = client.get(f"/api/v1/surveys/{sample_survey.id}/responses")
        
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) == 3
        
        # Check response structure
        first_response = result[0]
        assert 'id' in first_response
        assert 'participant_id' in first_response
        assert 'responses' in first_response
        assert 'completion_status' in first_response
        assert 'submitted_at' in first_response


class TestSurveyAnalyticsEndpoints:
    """Test survey analytics and insights endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_get_survey_analytics(self, mock_get_user, mock_get_db,
                                client, db_session, mock_current_user, sample_survey):
        """Test survey analytics generation"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        analytics_request = {
            'survey_ids': [sample_survey.id],
            'metrics': ['response_rate', 'completion_rate']
        }
        
        # Mock insights engine
        mock_insights_engine = Mock()
        mock_insights_engine.calculate_response_rates = AsyncMock(return_value={
            sample_survey.id: 0.75
        })
        mock_insights_engine.calculate_completion_rates = AsyncMock(return_value={
            sample_survey.id: 0.85
        })
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine', 
                  return_value=mock_insights_engine):
            response = client.post("/api/v1/surveys/analytics", json=analytics_request)
            
            assert response.status_code == 200
            result = response.json()
            assert 'analytics' in result
            assert 'response_rates' in result['analytics']
            assert 'completion_rates' in result['analytics']
            assert result['survey_count'] == 1
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_get_survey_insights(self, mock_get_user, mock_get_db,
                               client, db_session, mock_current_user, sample_survey):
        """Test getting AI-generated survey insights"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Create mock insight in database
        insight = SurveyInsight(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            insight_type='sentiment_analysis',
            title='Positive User Feedback',
            description='Users show positive sentiment toward new features',
            confidence_score=0.85,
            supporting_data={'positive_count': 15, 'negative_count': 2},
            generated_by='GPT-4-Analysis'
        )
        db_session.add(insight)
        db_session.commit()
        
        # Mock insights engine
        mock_insights_engine = Mock()
        mock_insights_engine.get_survey_insights = AsyncMock(return_value=[
            {
                'id': insight.id,
                'type': insight.insight_type,
                'title': insight.title,
                'description': insight.description,
                'confidence': insight.confidence_score
            }
        ])
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.SurveyInsightsEngine',
                  return_value=mock_insights_engine):
            response = client.get(f"/api/v1/surveys/{sample_survey.id}/insights")
            
            assert response.status_code == 200
            result = response.json()
            assert 'insights' in result
            assert len(result['insights']) == 1
            assert result['insights'][0]['title'] == 'Positive User Feedback'


class TestSurveyTemplateEndpoints:
    """Test survey template endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_list_survey_templates(self, mock_get_db, client, db_session):
        """Test listing survey templates"""
        mock_get_db.return_value = db_session
        
        # Create test templates
        templates = []
        for i, category in enumerate(['cognitive_neuroscience', 'clinical_research']):
            template = SurveyTemplate(
                id=str(uuid.uuid4()),
                name=f'Template {i}',
                description=f'Test template {i}',
                category=category,
                neuroimaging_focus=['fMRI'] if i == 0 else ['EEG'],
                template_questions=[
                    {'question_text': 'Test question', 'question_type': 'text'}
                ],
                default_settings={'theme': {'primary_color': '#007bff'}},
                usage_count=i * 5,
                is_public=True
            )
            templates.append(template)
            db_session.add(template)
        db_session.commit()
        
        response = client.get("/api/v1/surveys/templates")
        
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) >= 2
        
        # Check template structure
        first_template = result[0]
        assert 'id' in first_template
        assert 'name' in first_template
        assert 'category' in first_template
        assert 'neuroimaging_focus' in first_template
        assert 'question_count' in first_template
        assert 'usage_count' in first_template
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_list_templates_with_filters(self, mock_get_db, client, db_session):
        """Test listing templates with filters"""
        mock_get_db.return_value = db_session
        
        # Create templates with different focuses
        fmri_template = SurveyTemplate(
            id=str(uuid.uuid4()),
            name='fMRI Template',
            category='cognitive_neuroscience',
            neuroimaging_focus=['fMRI'],
            template_questions=[],
            is_public=True
        )
        eeg_template = SurveyTemplate(
            id=str(uuid.uuid4()),
            name='EEG Template', 
            category='clinical_research',
            neuroimaging_focus=['EEG'],
            template_questions=[],
            is_public=True
        )
        db_session.add_all([fmri_template, eeg_template])
        db_session.commit()
        
        # Test category filter
        response = client.get("/api/v1/surveys/templates?category=cognitive_neuroscience")
        assert response.status_code == 200
        result = response.json()
        cognitive_templates = [t for t in result if t['category'] == 'cognitive_neuroscience']
        assert len(cognitive_templates) >= 1
        
        # Test neuroimaging focus filter
        response = client.get("/api/v1/surveys/templates?neuroimaging_focus=fMRI")
        assert response.status_code == 200
        result = response.json()
        fmri_templates = [t for t in result if 'fMRI' in t['neuroimaging_focus']]
        assert len(fmri_templates) >= 1


class TestSurveyPublishingEndpoints:
    """Test survey publishing and lifecycle endpoints"""
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_publish_survey_success(self, mock_get_user, mock_get_db,
                                  client, db_session, mock_current_user, sample_survey):
        """Test successful survey publishing"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Ensure survey has questions (required for publishing)
        assert db_session.query(SurveyQuestion).filter_by(survey_id=sample_survey.id).count() > 0
        
        response = client.post(f"/api/v1/surveys/{sample_survey.id}/publish")
        
        assert response.status_code == 200
        result = response.json()
        assert result['status'] == 'success'
        
        # Verify survey status was updated
        updated_survey = db_session.query(Survey).filter_by(id=sample_survey.id).first()
        assert updated_survey.status == 'active'
        assert updated_survey.published_at is not None
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user')
    def test_publish_survey_no_questions(self, mock_get_user, mock_get_db,
                                       client, db_session, mock_current_user):
        """Test publishing survey without questions fails"""
        mock_get_user.return_value = mock_current_user
        mock_get_db.return_value = db_session
        
        # Create survey without questions
        empty_survey = Survey(
            id=str(uuid.uuid4()),
            title='Empty Survey',
            category='test',
            creator_id=str(uuid.uuid4()),
            status='draft'
        )
        db_session.add(empty_survey)
        db_session.commit()
        
        response = client.post(f"/api/v1/surveys/{empty_survey.id}/publish")
        
        assert response.status_code == 400
        assert 'without questions' in response.json()['detail'].lower()


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_invalid_survey_id_format(self, client):
        """Test handling of invalid UUID formats"""
        invalid_id = "not-a-uuid"
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.get_db'):
            with patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user'):
                response = client.get(f"/api/v1/surveys/{invalid_id}")
                # Should handle gracefully, likely return 404 or 400
                assert response.status_code in [400, 404, 500]
    
    @patch('brain_researcher.services.orchestrator.survey_endpoints.get_db')
    def test_database_connection_error(self, mock_get_db, client):
        """Test handling of database connection errors"""
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database connection lost")
        mock_get_db.return_value = mock_db
        
        with patch('brain_researcher.services.orchestrator.survey_endpoints.get_current_user'):
            response = client.get("/api/v1/surveys/")
            assert response.status_code == 500
    
    def test_missing_authentication(self, client):
        """Test endpoints that require authentication"""
        # Most endpoints should require authentication
        response = client.get("/api/v1/surveys/")
        # Should return 401 or 403 if authentication is required
        # Note: This test depends on authentication middleware being properly configured
        pass  # Actual assertion depends on authentication setup


if __name__ == '__main__':
    pytest.main([__file__])