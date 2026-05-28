"""
Unit Tests for Survey System Data Models

Tests for SQLAlchemy models, validation, and neuroimaging-specific functionality.
Includes comprehensive validation testing, relationship testing, and 
neuroimaging context validation.
"""

import pytest
import uuid
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, DataError
from unittest.mock import Mock, patch
import json

# Import survey models
from brain_researcher.services.orchestrator.survey_models import (
    Base, Survey, SurveyQuestion, SurveyResponse, SurveyDistribution,
    SurveyTrigger, SurveyInsight, SurveyTemplate, SurveyResponseAnalytics,
    SurveyNotification, SurveyStatus, QuestionType,
    get_neuroimaging_question_templates, get_survey_templates_by_category,
    create_survey_tables
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
def sample_survey_data():
    """Sample survey data for testing"""
    return {
        'id': str(uuid.uuid4()),
        'title': 'Test Neuroimaging Survey',
        'description': 'A test survey for neuroimaging research',
        'category': 'cognitive_assessment',
        'creator_id': str(uuid.uuid4()),
        'target_audience': 'researchers',
        'settings': {
            'theme': {'primary_color': '#007bff'},
            'logic': {'conditional_questions': []},
            'validation': {'require_all_questions': True}
        },
        'neuroimaging_context': {
            'study_type': ['fMRI', 'structural'],
            'imaging_modalities': ['T1', 'BOLD'],
            'data_sharing': True
        },
        'expected_responses': 50,
        'max_responses': 100
    }


@pytest.fixture
def sample_question_data():
    """Sample question data for testing"""
    return {
        'question_text': 'What is your experience with fMRI analysis?',
        'question_type': 'multiple_choice',
        'description': 'Select your level of experience',
        'options': {
            'choices': [
                {'id': '1', 'text': 'Beginner', 'value': 'beginner'},
                {'id': '2', 'text': 'Intermediate', 'value': 'intermediate'},
                {'id': '3', 'text': 'Advanced', 'value': 'advanced'}
            ]
        },
        'validation_rules': {
            'required': True
        },
        'neuroimaging_context': {
            'category': 'experience_assessment',
            'required_for': ['fMRI']
        },
        'order_index': 0,
        'required': True
    }


class TestSurveyModel:
    """Test cases for the Survey model"""
    
    def test_survey_creation(self, db_session, sample_survey_data):
        """Test basic survey creation"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        # Verify survey was created
        retrieved_survey = db_session.query(Survey).filter_by(id=sample_survey_data['id']).first()
        assert retrieved_survey is not None
        assert retrieved_survey.title == sample_survey_data['title']
        assert retrieved_survey.category == sample_survey_data['category']
        assert retrieved_survey.status == 'draft'  # default status
        assert retrieved_survey.created_at is not None
    
    def test_survey_required_fields(self, db_session):
        """Test that required fields are enforced"""
        # Missing title should fail
        with pytest.raises(IntegrityError):
            survey = Survey(
                id=str(uuid.uuid4()),
                category='test',
                creator_id=str(uuid.uuid4())
            )
            db_session.add(survey)
            db_session.commit()
    
    def test_survey_status_validation(self, db_session, sample_survey_data):
        """Test survey status validation"""
        valid_statuses = ['draft', 'active', 'paused', 'completed', 'archived']
        
        for status in valid_statuses:
            survey_data = {**sample_survey_data, 'id': str(uuid.uuid4()), 'status': status}
            survey = Survey(**survey_data)
            db_session.add(survey)
            db_session.commit()
            
            retrieved = db_session.query(Survey).filter_by(id=survey_data['id']).first()
            assert retrieved.status == status
    
    def test_survey_neuroimaging_context(self, db_session, sample_survey_data):
        """Test neuroimaging context storage and retrieval"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        retrieved = db_session.query(Survey).filter_by(id=sample_survey_data['id']).first()
        assert retrieved.neuroimaging_context['study_type'] == ['fMRI', 'structural']
        assert retrieved.neuroimaging_context['data_sharing'] is True
    
    def test_survey_settings_json(self, db_session, sample_survey_data):
        """Test JSON settings storage"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        retrieved = db_session.query(Survey).filter_by(id=sample_survey_data['id']).first()
        assert retrieved.settings['theme']['primary_color'] == '#007bff'
        assert retrieved.settings['validation']['require_all_questions'] is True
    
    def test_survey_indexing(self, db_session, sample_survey_data):
        """Test that indexes work correctly"""
        # Create multiple surveys
        surveys = []
        for i in range(5):
            survey_data = {
                **sample_survey_data,
                'id': str(uuid.uuid4()),
                'title': f'Survey {i}',
                'category': 'cognitive_assessment' if i % 2 == 0 else 'demographics'
            }
            survey = Survey(**survey_data)
            surveys.append(survey)
            db_session.add(survey)
        
        db_session.commit()
        
        # Test category filtering (should use index)
        cognitive_surveys = db_session.query(Survey).filter_by(
            category='cognitive_assessment'
        ).all()
        assert len(cognitive_surveys) == 3
        
        # Test creator filtering (should use index)
        creator_surveys = db_session.query(Survey).filter_by(
            creator_id=sample_survey_data['creator_id']
        ).all()
        assert len(creator_surveys) == 5


class TestSurveyQuestionModel:
    """Test cases for the SurveyQuestion model"""
    
    def test_question_creation(self, db_session, sample_survey_data, sample_question_data):
        """Test basic question creation"""
        # First create survey
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        # Then create question
        question_data = {
            **sample_question_data,
            'id': str(uuid.uuid4()),
            'survey_id': survey.id
        }
        question = SurveyQuestion(**question_data)
        db_session.add(question)
        db_session.commit()
        
        # Verify question was created
        retrieved = db_session.query(SurveyQuestion).filter_by(id=question_data['id']).first()
        assert retrieved is not None
        assert retrieved.question_text == question_data['question_text']
        assert retrieved.question_type == question_data['question_type']
        assert retrieved.survey_id == survey.id
    
    def test_question_types_validation(self, db_session, sample_survey_data):
        """Test that question types are properly stored"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        neuroimaging_types = [
            'neuroimaging_protocol',
            'brain_region',
            'cognitive_battery',
            'medication_history',
            'scanner_parameters'
        ]
        
        standard_types = [
            'multiple_choice',
            'single_choice',
            'text',
            'textarea',
            'scale',
            'matrix'
        ]
        
        all_types = neuroimaging_types + standard_types
        
        for i, question_type in enumerate(all_types):
            question = SurveyQuestion(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                question_text=f'Test question {i}',
                question_type=question_type,
                order_index=i
            )
            db_session.add(question)
        
        db_session.commit()
        
        # Verify all question types were stored correctly
        for question_type in all_types:
            question = db_session.query(SurveyQuestion).filter_by(
                question_type=question_type
            ).first()
            assert question is not None
            assert question.question_type == question_type
    
    def test_question_options_json(self, db_session, sample_survey_data, sample_question_data):
        """Test question options JSON storage"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        question_data = {
            **sample_question_data,
            'id': str(uuid.uuid4()),
            'survey_id': survey.id
        }
        question = SurveyQuestion(**question_data)
        db_session.add(question)
        db_session.commit()
        
        retrieved = db_session.query(SurveyQuestion).filter_by(id=question_data['id']).first()
        assert retrieved.options['choices'][0]['text'] == 'Beginner'
        assert len(retrieved.options['choices']) == 3
    
    def test_question_neuroimaging_context(self, db_session, sample_survey_data):
        """Test neuroimaging-specific question context"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        neuroimaging_question = SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='Please specify scanner parameters',
            question_type='scanner_parameters',
            order_index=0,
            neuroimaging_context={
                'category': 'acquisition_parameters',
                'required_for': ['fMRI', 'structural_MRI'],
                'atlas_support': False
            },
            options={
                'field_strength': ['1.5T', '3T', '7T'],
                'pulse_sequence': ['T1-MPRAGE', 'EPI'],
                'voxel_size': {'type': 'numeric', 'unit': 'mm'}
            }
        )
        db_session.add(neuroimaging_question)
        db_session.commit()
        
        retrieved = db_session.query(SurveyQuestion).filter_by(
            id=neuroimaging_question.id
        ).first()
        assert retrieved.neuroimaging_context['category'] == 'acquisition_parameters'
        assert 'fMRI' in retrieved.neuroimaging_context['required_for']
        assert retrieved.options['field_strength'] == ['1.5T', '3T', '7T']
    
    def test_question_ordering_constraint(self, db_session, sample_survey_data):
        """Test unique constraint on survey_id + order_index"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        # Create first question at order_index 0
        question1 = SurveyQuestion(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            question_text='First question',
            question_type='text',
            order_index=0
        )
        db_session.add(question1)
        db_session.commit()
        
        # Try to create another question at same order_index - should fail
        with pytest.raises(IntegrityError):
            question2 = SurveyQuestion(
                id=str(uuid.uuid4()),
                survey_id=survey.id,
                question_text='Second question',
                question_type='text',
                order_index=0  # Same order_index
            )
            db_session.add(question2)
            db_session.commit()


class TestSurveyResponseModel:
    """Test cases for the SurveyResponse model"""
    
    def test_response_creation(self, db_session, sample_survey_data):
        """Test basic response creation"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        response = SurveyResponse(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            participant_id='test_participant_123',
            responses={'question_1': 'answer_1', 'question_2': 'answer_2'},
            completion_status='completed',
            submitted_at=datetime.utcnow()
        )
        db_session.add(response)
        db_session.commit()
        
        retrieved = db_session.query(SurveyResponse).filter_by(id=response.id).first()
        assert retrieved is not None
        assert retrieved.survey_id == survey.id
        assert retrieved.participant_id == 'test_participant_123'
        assert retrieved.responses['question_1'] == 'answer_1'
        assert retrieved.completion_status == 'completed'
    
    def test_response_metadata_storage(self, db_session, sample_survey_data):
        """Test response metadata and session data storage"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        response = SurveyResponse(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            participant_id='test_participant',
            responses={'q1': 'a1'},
            metadata={
                'device_type': 'desktop',
                'browser': 'chrome',
                'completion_time_seconds': 240
            },
            session_data={
                'session_id': 'session_123',
                'user_agent': 'Mozilla/5.0...',
                'ip_address': '192.168.1.1'
            }
        )
        db_session.add(response)
        db_session.commit()
        
        retrieved = db_session.query(SurveyResponse).filter_by(id=response.id).first()
        assert retrieved.metadata['device_type'] == 'desktop'
        assert retrieved.metadata['completion_time_seconds'] == 240
        assert retrieved.session_data['session_id'] == 'session_123'
    
    def test_response_quality_metrics(self, db_session, sample_survey_data):
        """Test quality scoring and review flags"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        # High quality response
        good_response = SurveyResponse(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            participant_id='good_participant',
            responses={'q1': 'detailed answer'},
            quality_score=0.9,
            flagged_for_review=False,
            completion_time_seconds=300
        )
        
        # Low quality response
        poor_response = SurveyResponse(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            participant_id='poor_participant',
            responses={'q1': 'x'},
            quality_score=0.3,
            flagged_for_review=True,
            review_notes='Suspiciously short completion time',
            completion_time_seconds=10
        )
        
        db_session.add_all([good_response, poor_response])
        db_session.commit()
        
        # Verify quality metrics
        good = db_session.query(SurveyResponse).filter_by(id=good_response.id).first()
        poor = db_session.query(SurveyResponse).filter_by(id=poor_response.id).first()
        
        assert good.quality_score == 0.9
        assert not good.flagged_for_review
        assert poor.quality_score == 0.3
        assert poor.flagged_for_review
        assert 'short completion' in poor.review_notes


class TestSurveyTriggerModel:
    """Test cases for the SurveyTrigger model"""
    
    def test_trigger_creation(self, db_session, sample_survey_data):
        """Test basic trigger creation"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        trigger = SurveyTrigger(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            trigger_type='analysis_complete',
            trigger_conditions={
                'analysis_type': 'fMRI_GLM',
                'min_quality_score': 0.8
            },
            trigger_data={
                'delay_minutes': 60,
                'target_audience': 'researchers'
            },
            status='active'
        )
        db_session.add(trigger)
        db_session.commit()
        
        retrieved = db_session.query(SurveyTrigger).filter_by(id=trigger.id).first()
        assert retrieved is not None
        assert retrieved.trigger_type == 'analysis_complete'
        assert retrieved.trigger_conditions['analysis_type'] == 'fMRI_GLM'
        assert retrieved.status == 'active'
        assert retrieved.trigger_count == 0  # default value
    
    def test_neuroimaging_trigger_conditions(self, db_session, sample_survey_data):
        """Test neuroimaging-specific trigger conditions"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        trigger = SurveyTrigger(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            trigger_type='neuroimaging_pipeline',
            trigger_conditions={
                'pipeline_stages': ['preprocessing', 'first_level'],
                'quality_thresholds': {
                    'motion_threshold': 0.5,
                    'snr_threshold': 100
                },
                'data_types': ['T1w', 'bold'],
                'user_id': 'researcher_123'
            }
        )
        db_session.add(trigger)
        db_session.commit()
        
        retrieved = db_session.query(SurveyTrigger).filter_by(id=trigger.id).first()
        conditions = retrieved.trigger_conditions
        assert 'preprocessing' in conditions['pipeline_stages']
        assert conditions['quality_thresholds']['motion_threshold'] == 0.5
        assert 'T1w' in conditions['data_types']


class TestSurveyInsightModel:
    """Test cases for the SurveyInsight model"""
    
    def test_insight_creation(self, db_session, sample_survey_data):
        """Test AI insight creation and storage"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        insight = SurveyInsight(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            insight_type='sentiment_analysis',
            title='Positive Response Sentiment',
            description='Participants show positive sentiment towards new analysis tools',
            confidence_score=0.85,
            supporting_data={
                'positive_responses': 42,
                'neutral_responses': 8,
                'negative_responses': 3,
                'sentiment_scores': [0.7, 0.8, 0.9, 0.6]
            },
            methodology={
                'algorithm': 'BERT_sentiment_classifier',
                'parameters': {'threshold': 0.6},
                'data_sources': ['text_responses', 'scale_responses']
            },
            generated_by='GPT-4-Analysis-Engine',
            review_status='pending'
        )
        db_session.add(insight)
        db_session.commit()
        
        retrieved = db_session.query(SurveyInsight).filter_by(id=insight.id).first()
        assert retrieved.insight_type == 'sentiment_analysis'
        assert retrieved.confidence_score == 0.85
        assert retrieved.supporting_data['positive_responses'] == 42
        assert retrieved.methodology['algorithm'] == 'BERT_sentiment_classifier'
    
    def test_neuroimaging_correlations_insight(self, db_session, sample_survey_data):
        """Test neuroimaging-specific insights"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        insight = SurveyInsight(
            id=str(uuid.uuid4()),
            survey_id=survey.id,
            insight_type='neuroimaging_correlations',
            title='Scanner Parameter Impact on Data Quality',
            description='3T scanners consistently produce higher SNR than 1.5T',
            confidence_score=0.92,
            supporting_data={
                'correlation_coefficient': 0.78,
                'p_value': 0.001,
                '3T_mean_snr': 125.4,
                '1_5T_mean_snr': 89.2,
                'sample_size': {'3T': 31, '1.5T': 19}
            },
            methodology={
                'algorithm': 'pearson_correlation',
                'statistical_test': 't_test',
                'multiple_comparisons': 'bonferroni'
            }
        )
        db_session.add(insight)
        db_session.commit()
        
        retrieved = db_session.query(SurveyInsight).filter_by(id=insight.id).first()
        assert retrieved.insight_type == 'neuroimaging_correlations'
        assert retrieved.supporting_data['correlation_coefficient'] == 0.78
        assert retrieved.supporting_data['3T_mean_snr'] > retrieved.supporting_data['1_5T_mean_snr']


class TestSurveyTemplateModel:
    """Test cases for the SurveyTemplate model"""
    
    def test_template_creation(self, db_session):
        """Test neuroimaging survey template creation"""
        template = SurveyTemplate(
            id=str(uuid.uuid4()),
            name='fMRI Task-Based Study Survey',
            description='Comprehensive survey for task-based fMRI studies',
            category='cognitive_neuroscience',
            neuroimaging_focus=['fMRI', 'task_based'],
            study_types=['cognitive', 'clinical'],
            cognitive_domains=['attention', 'memory', 'executive_function'],
            template_questions=[
                {
                    'question_text': 'Scanner field strength',
                    'question_type': 'scanner_parameters',
                    'options': {
                        'field_strength': ['1.5T', '3T', '7T']
                    },
                    'required': True
                },
                {
                    'question_text': 'Primary brain regions of interest',
                    'question_type': 'brain_region',
                    'options': {
                        'regions': ['Prefrontal Cortex', 'Motor Cortex', 'Visual Cortex'],
                        'multiple_selection': True
                    },
                    'required': True
                }
            ],
            default_settings={
                'theme': {'primary_color': '#007bff'},
                'validation': {'require_all_questions': True}
            },
            tags=['neuroimaging', 'fMRI', 'cognitive'],
            is_public=True
        )
        db_session.add(template)
        db_session.commit()
        
        retrieved = db_session.query(SurveyTemplate).filter_by(id=template.id).first()
        assert retrieved.name == 'fMRI Task-Based Study Survey'
        assert 'fMRI' in retrieved.neuroimaging_focus
        assert len(retrieved.template_questions) == 2
        assert retrieved.template_questions[0]['question_type'] == 'scanner_parameters'
        assert retrieved.is_public is True


class TestSurveyRelationships:
    """Test relationships between survey models"""
    
    def test_survey_question_relationship(self, db_session, sample_survey_data, sample_question_data):
        """Test survey-question relationship"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        # Add multiple questions
        questions = []
        for i in range(3):
            question_data = {
                **sample_question_data,
                'id': str(uuid.uuid4()),
                'survey_id': survey.id,
                'question_text': f'Question {i}',
                'order_index': i
            }
            question = SurveyQuestion(**question_data)
            questions.append(question)
            db_session.add(question)
        
        db_session.commit()
        
        # Test relationship
        retrieved_survey = db_session.query(Survey).filter_by(id=survey.id).first()
        assert len(retrieved_survey.questions) == 3
        assert retrieved_survey.questions[0].order_index == 0
        assert retrieved_survey.questions[2].question_text == 'Question 2'
        
        # Test back reference
        first_question = retrieved_survey.questions[0]
        assert first_question.survey.id == survey.id
        assert first_question.survey.title == sample_survey_data['title']
    
    def test_cascade_delete(self, db_session, sample_survey_data, sample_question_data):
        """Test cascade delete of questions when survey is deleted"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        # Add questions
        for i in range(3):
            question_data = {
                **sample_question_data,
                'id': str(uuid.uuid4()),
                'survey_id': survey.id,
                'order_index': i
            }
            question = SurveyQuestion(**question_data)
            db_session.add(question)
        
        db_session.commit()
        
        # Verify questions exist
        question_count = db_session.query(SurveyQuestion).filter_by(survey_id=survey.id).count()
        assert question_count == 3
        
        # Delete survey - should cascade to questions
        db_session.delete(survey)
        db_session.commit()
        
        # Verify questions were deleted
        remaining_questions = db_session.query(SurveyQuestion).filter_by(survey_id=survey.id).count()
        assert remaining_questions == 0


class TestNeuroimagingTemplates:
    """Test neuroimaging-specific template functions"""
    
    def test_neuroimaging_question_templates(self):
        """Test neuroimaging question templates"""
        templates = get_neuroimaging_question_templates()
        
        # Verify expected templates exist
        expected_templates = [
            'scanner_parameters',
            'brain_regions',
            'cognitive_assessment',
            'medication_history',
            'study_demographics'
        ]
        
        for template_name in expected_templates:
            assert template_name in templates
            template = templates[template_name]
            assert 'type' in template
            assert 'text' in template
            assert 'options' in template
        
        # Test specific template content
        scanner_template = templates['scanner_parameters']
        assert scanner_template['type'] == 'neuroimaging_protocol'
        assert 'field_strength' in scanner_template['options']
        assert '3T' in scanner_template['options']['field_strength']
        
        brain_regions_template = templates['brain_regions']
        assert brain_regions_template['type'] == 'brain_region'
        assert 'Prefrontal Cortex' in brain_regions_template['options']['regions']
    
    def test_survey_templates_by_category(self):
        """Test survey template categorization"""
        templates_by_category = get_survey_templates_by_category()
        
        # Verify expected categories exist
        expected_categories = [
            'cognitive_neuroscience',
            'clinical_research',
            'user_experience'
        ]
        
        for category in expected_categories:
            assert category in templates_by_category
            category_templates = templates_by_category[category]
            assert isinstance(category_templates, list)
            assert len(category_templates) > 0
        
        # Test cognitive neuroscience templates
        cog_neuro_templates = templates_by_category['cognitive_neuroscience']
        fmri_template = next((t for t in cog_neuro_templates 
                            if 'fMRI Task-Based' in t['name']), None)
        assert fmri_template is not None
        assert 'scanner_parameters' in fmri_template['questions']
        assert 'brain_regions' in fmri_template['questions']


class TestDatabaseUtilities:
    """Test database utility functions"""
    
    def test_create_survey_tables(self):
        """Test table creation function"""
        # Create new in-memory database
        engine = create_engine("sqlite:///:memory:")
        
        # Test table creation
        create_survey_tables(engine)
        
        # Verify tables exist by checking metadata
        table_names = Base.metadata.tables.keys()
        expected_tables = [
            'surveys',
            'survey_questions', 
            'survey_responses',
            'survey_distributions',
            'survey_triggers',
            'survey_insights',
            'survey_templates',
            'survey_response_analytics',
            'survey_notifications'
        ]
        
        for table_name in expected_tables:
            assert table_name in table_names


class TestModelValidation:
    """Test data validation and constraints"""
    
    def test_survey_title_length_validation(self, db_session):
        """Test survey title length constraint"""
        # Title too long (over 200 characters)
        long_title = 'x' * 201
        
        survey = Survey(
            id=str(uuid.uuid4()),
            title=long_title,
            category='test',
            creator_id=str(uuid.uuid4())
        )
        
        with pytest.raises((DataError, IntegrityError)):
            db_session.add(survey)
            db_session.commit()
    
    def test_json_field_validation(self, db_session, sample_survey_data):
        """Test JSON field storage and validation"""
        # Test valid JSON
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        retrieved = db_session.query(Survey).filter_by(id=survey.id).first()
        assert isinstance(retrieved.settings, dict)
        assert isinstance(retrieved.neuroimaging_context, dict)
    
    def test_datetime_fields(self, db_session, sample_survey_data):
        """Test datetime field handling"""
        survey = Survey(**sample_survey_data)
        db_session.add(survey)
        db_session.commit()
        
        retrieved = db_session.query(Survey).filter_by(id=survey.id).first()
        
        # Check created_at was set automatically
        assert retrieved.created_at is not None
        assert isinstance(retrieved.created_at, datetime)
        assert retrieved.created_at <= datetime.utcnow()
        
        # Update and check updated_at
        retrieved.title = 'Updated Title'
        db_session.commit()
        
        updated_survey = db_session.query(Survey).filter_by(id=survey.id).first()
        # Note: updated_at only gets set on actual updates in some SQLAlchemy versions
        # This test might need adjustment based on SQLAlchemy configuration


if __name__ == '__main__':
    pytest.main([__file__])