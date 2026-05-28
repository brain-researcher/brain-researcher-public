"""
Unit Tests for Survey Trigger System

Comprehensive tests for automated survey triggering based on system events,
neuroimaging analysis milestones, and user actions. Tests both the trigger
manager and individual event handlers.
"""

import pytest
import uuid
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import survey trigger system
from brain_researcher.services.orchestrator.survey_triggers import (
    SurveyTriggerManager, TriggerEvent, TriggerType, TriggerStatus,
    trigger_survey_event, setup_analysis_complete_trigger, trigger_manager
)
from brain_researcher.services.orchestrator.survey_models import (
    Base, Survey, SurveyTrigger, SurveyDistribution, SurveyNotification
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
def trigger_manager_instance():
    """Create fresh trigger manager instance for testing"""
    return SurveyTriggerManager()


@pytest.fixture
def sample_survey(db_session):
    """Create a sample survey in the database"""
    survey = Survey(
        id=str(uuid.uuid4()),
        title='Test Survey',
        description='Survey for trigger testing',
        category='post_analysis_feedback',
        creator_id=str(uuid.uuid4()),
        status='active'
    )
    db_session.add(survey)
    db_session.commit()
    return survey


@pytest.fixture
def sample_trigger_event():
    """Create sample trigger event for testing"""
    return TriggerEvent(
        event_type=TriggerType.ANALYSIS_COMPLETE.value,
        event_data={
            'analysis_type': 'group_analysis',
            'quality_score': 0.85,
            'analysis_id': str(uuid.uuid4()),
            'dataset_size': 50
        },
        user_id=str(uuid.uuid4()),
        session_id='session_123',
        metadata={'source': 'test_suite'}
    )


class TestTriggerEvent:
    """Test TriggerEvent dataclass"""
    
    def test_trigger_event_creation(self):
        """Test basic trigger event creation"""
        event = TriggerEvent(
            event_type='test_event',
            event_data={'key': 'value'}
        )
        
        assert event.event_type == 'test_event'
        assert event.event_data['key'] == 'value'
        assert event.timestamp is not None
        assert event.metadata == {}
        assert event.user_id is None
        assert event.session_id is None
    
    def test_trigger_event_with_timestamp(self):
        """Test trigger event with explicit timestamp"""
        test_time = datetime(2023, 1, 1, 12, 0, 0)
        event = TriggerEvent(
            event_type='test_event',
            event_data={'key': 'value'},
            timestamp=test_time
        )
        
        assert event.timestamp == test_time
    
    def test_trigger_event_metadata_initialization(self):
        """Test that metadata is properly initialized"""
        event = TriggerEvent(
            event_type='test_event',
            event_data={'key': 'value'},
            metadata={'custom': 'metadata'}
        )
        
        assert event.metadata['custom'] == 'metadata'


class TestSurveyTriggerManager:
    """Test SurveyTriggerManager class"""
    
    def test_trigger_manager_initialization(self, trigger_manager_instance):
        """Test trigger manager initialization"""
        manager = trigger_manager_instance
        
        assert isinstance(manager.active_triggers, dict)
        assert isinstance(manager.event_handlers, dict)
        assert len(manager.active_triggers) == 0
        
        # Check that default handlers are registered
        expected_handlers = [
            TriggerType.ANALYSIS_COMPLETE.value,
            TriggerType.DATA_UPLOAD.value,
            TriggerType.STUDY_MILESTONE.value,
            TriggerType.TIME_BASED.value,
            TriggerType.NEUROIMAGING_PIPELINE.value
        ]
        
        for handler_type in expected_handlers:
            assert handler_type in manager.event_handlers
            assert len(manager.event_handlers[handler_type]) >= 1
    
    def test_register_handler(self, trigger_manager_instance):
        """Test registering custom event handlers"""
        manager = trigger_manager_instance
        
        async def custom_handler(event):
            return ['survey_123']
        
        manager.register_handler('custom_event', custom_handler)
        
        assert 'custom_event' in manager.event_handlers
        assert custom_handler in manager.event_handlers['custom_event']
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_setup_trigger_success(self, mock_get_db, trigger_manager_instance, db_session, sample_survey):
        """Test successful trigger setup"""
        mock_get_db.return_value.__enter__ = Mock(return_value=db_session)
        mock_get_db.return_value.__exit__ = Mock(return_value=None)
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        trigger_config = {
            'type': TriggerType.ANALYSIS_COMPLETE.value,
            'conditions': {
                'event_data': {
                    'analysis_type': 'group_analysis'
                }
            },
            'data': {
                'delay_minutes': 30
            }
        }
        
        trigger_id = await manager.setup_trigger(sample_survey.id, trigger_config)
        
        assert trigger_id is not None
        assert trigger_id in manager.active_triggers
        
        # Verify trigger data
        trigger_data = manager.active_triggers[trigger_id]
        assert trigger_data['survey_id'] == sample_survey.id
        assert trigger_data['config'] == trigger_config
        
        # Verify database record was created
        db_trigger = db_session.query(SurveyTrigger).filter_by(id=trigger_id).first()
        assert db_trigger is not None
        assert db_trigger.survey_id == sample_survey.id
        assert db_trigger.trigger_type == TriggerType.ANALYSIS_COMPLETE.value
        assert db_trigger.status == 'active'
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_setup_trigger_nonexistent_survey(self, mock_get_db, trigger_manager_instance, db_session):
        """Test setup trigger with non-existent survey"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        fake_survey_id = str(uuid.uuid4())
        
        trigger_config = {
            'type': TriggerType.ANALYSIS_COMPLETE.value,
            'conditions': {}
        }
        
        with pytest.raises(ValueError, match="Survey .* not found"):
            await manager.setup_trigger(fake_survey_id, trigger_config)
    
    @pytest.mark.asyncio
    async def test_process_event_no_handlers(self, trigger_manager_instance):
        """Test processing event with no registered handlers"""
        manager = trigger_manager_instance
        
        event = TriggerEvent(
            event_type='unknown_event',
            event_data={'test': 'data'}
        )
        
        triggered_surveys = await manager.process_event(event)
        
        assert triggered_surveys == []
    
    @pytest.mark.asyncio
    async def test_process_event_with_handlers(self, trigger_manager_instance):
        """Test processing event with registered handlers"""
        manager = trigger_manager_instance
        
        # Register mock handler
        mock_handler = AsyncMock(return_value=['survey_123', 'survey_456'])
        manager.register_handler('test_event', mock_handler)
        
        event = TriggerEvent(
            event_type='test_event',
            event_data={'test': 'data'}
        )
        
        triggered_surveys = await manager.process_event(event)
        
        assert 'survey_123' in triggered_surveys
        assert 'survey_456' in triggered_surveys
        mock_handler.assert_called_once_with(event)
    
    @pytest.mark.asyncio
    async def test_find_matching_triggers(self, trigger_manager_instance, sample_survey):
        """Test finding triggers that match an event"""
        manager = trigger_manager_instance
        
        # Add a trigger to active triggers
        trigger_id = str(uuid.uuid4())
        manager.active_triggers[trigger_id] = {
            'survey_id': sample_survey.id,
            'config': {
                'type': TriggerType.ANALYSIS_COMPLETE.value,
                'conditions': {
                    'event_data': {
                        'analysis_type': 'group_analysis'
                    }
                }
            }
        }
        
        # Matching event
        matching_event = TriggerEvent(
            event_type=TriggerType.ANALYSIS_COMPLETE.value,
            event_data={'analysis_type': 'group_analysis'}
        )
        
        # Non-matching event
        non_matching_event = TriggerEvent(
            event_type=TriggerType.DATA_UPLOAD.value,
            event_data={'file_type': 'nifti'}
        )
        
        matching_triggers = await manager._find_matching_triggers(matching_event)
        non_matching_triggers = await manager._find_matching_triggers(non_matching_event)
        
        assert trigger_id in matching_triggers
        assert len(non_matching_triggers) == 0
    
    @pytest.mark.asyncio
    async def test_evaluate_trigger_conditions_basic(self, trigger_manager_instance):
        """Test basic trigger condition evaluation"""
        manager = trigger_manager_instance
        
        conditions = {
            'user_id': 'user_123',
            'event_data': {
                'analysis_type': 'group_analysis',
                'quality_score': {'operator': 'greater_than', 'value': 0.8}
            }
        }
        
        matching_event = TriggerEvent(
            event_type='test_event',
            event_data={'analysis_type': 'group_analysis', 'quality_score': 0.9},
            user_id='user_123'
        )
        
        non_matching_event = TriggerEvent(
            event_type='test_event',
            event_data={'analysis_type': 'first_level', 'quality_score': 0.7},
            user_id='user_456'
        )
        
        assert await manager._evaluate_trigger_conditions(conditions, matching_event)
        assert not await manager._evaluate_trigger_conditions(conditions, non_matching_event)
    
    @pytest.mark.asyncio
    async def test_evaluate_time_conditions_day_of_week(self, trigger_manager_instance):
        """Test time-based condition evaluation for day of week"""
        manager = trigger_manager_instance
        
        # Create event on Monday
        monday_event = TriggerEvent(
            event_type='test_event',
            event_data={},
            timestamp=datetime(2023, 1, 2)  # Monday
        )
        
        # Create event on Sunday
        sunday_event = TriggerEvent(
            event_type='test_event', 
            event_data={},
            timestamp=datetime(2023, 1, 1)  # Sunday
        )
        
        weekday_conditions = {
            'day_of_week': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        }
        
        assert await manager._evaluate_time_conditions(weekday_conditions, monday_event)
        assert not await manager._evaluate_time_conditions(weekday_conditions, sunday_event)
    
    @pytest.mark.asyncio
    async def test_evaluate_time_conditions_time_range(self, trigger_manager_instance):
        """Test time-based condition evaluation for time ranges"""
        manager = trigger_manager_instance
        
        # Create events at different times
        morning_event = TriggerEvent(
            event_type='test_event',
            event_data={},
            timestamp=datetime(2023, 1, 1, 9, 30)  # 9:30 AM
        )
        
        evening_event = TriggerEvent(
            event_type='test_event',
            event_data={},
            timestamp=datetime(2023, 1, 1, 19, 30)  # 7:30 PM
        )
        
        business_hours_conditions = {
            'time_range': {
                'start': '09:00',
                'end': '17:00'
            }
        }
        
        assert await manager._evaluate_time_conditions(business_hours_conditions, morning_event)
        assert not await manager._evaluate_time_conditions(business_hours_conditions, evening_event)
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_execute_trigger(self, mock_get_db, trigger_manager_instance, db_session, sample_survey):
        """Test trigger execution"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create trigger in database
        trigger = SurveyTrigger(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            trigger_type=TriggerType.ANALYSIS_COMPLETE.value,
            trigger_conditions={},
            status='active',
            trigger_count=0
        )
        db_session.add(trigger)
        db_session.commit()
        
        trigger_data = {
            'survey_id': sample_survey.id,
            'config': {
                'targeting': {'from_event': True},
                'notifications': {'enabled': True}
            }
        }
        
        event = TriggerEvent(
            event_type=TriggerType.ANALYSIS_COMPLETE.value,
            event_data={},
            user_id='test_user_123'
        )
        
        with patch.object(manager, '_get_target_participants', return_value=['user_123']) as mock_participants:
            with patch.object(manager, '_create_triggered_distribution', return_value={'id': 'dist_123'}) as mock_dist:
                with patch.object(manager, '_send_survey_notifications') as mock_notifications:
                    
                    result = await manager._execute_trigger(trigger.id, trigger_data, event)
                    
                    assert result == sample_survey.id
                    mock_participants.assert_called_once()
                    mock_dist.assert_called_once()
                    mock_notifications.assert_called_once()
                    
                    # Verify trigger count was incremented
                    updated_trigger = db_session.query(SurveyTrigger).filter_by(id=trigger.id).first()
                    assert updated_trigger.trigger_count == 1
                    assert updated_trigger.last_triggered_at is not None
    
    @pytest.mark.asyncio
    async def test_get_target_participants(self, trigger_manager_instance):
        """Test getting target participants from various sources"""
        manager = trigger_manager_instance
        
        event = TriggerEvent(
            event_type='test_event',
            event_data={},
            user_id='event_user_123'
        )
        
        # Test event-based targeting
        event_config = {'targeting': {'from_event': True}}
        participants = await manager._get_target_participants(event_config, event)
        assert 'event_user_123' in participants
        
        # Test role-based targeting  
        role_config = {'targeting': {'roles': ['researcher']}}
        participants = await manager._get_target_participants(role_config, event)
        assert 'event_user_123' in participants  # Falls back to event user
        
        # Test custom participant list
        custom_config = {'targeting': {'participant_ids': ['user_1', 'user_2', 'user_3']}}
        participants = await manager._get_target_participants(custom_config, event)
        assert 'user_1' in participants
        assert 'user_2' in participants
        assert 'user_3' in participants
        assert len(participants) == 3
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_create_triggered_distribution(self, mock_get_db, trigger_manager_instance, db_session, sample_survey):
        """Test creating triggered distribution record"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        participants = ['user_1', 'user_2']
        config = {'targeting': {'from_event': True}}
        event = TriggerEvent(
            event_type='test_event',
            event_data={'test': 'data'},
            metadata={'source': 'test'}
        )
        
        result = await manager._create_triggered_distribution(sample_survey.id, participants, config, event)
        
        assert result['status'] == 'created'
        assert 'id' in result
        
        # Verify distribution was created in database
        distribution = db_session.query(SurveyDistribution).filter_by(id=result['id']).first()
        assert distribution is not None
        assert distribution.survey_id == sample_survey.id
        assert distribution.distribution_type == 'triggered'
        assert distribution.target_criteria['participant_count'] == 2
        assert distribution.status == 'active'
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_send_survey_notifications(self, mock_get_db, trigger_manager_instance, db_session, sample_survey):
        """Test sending survey notifications"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        participants = ['user_1', 'user_2']
        distribution_id = str(uuid.uuid4())
        config = {
            'notifications': {
                'enabled': True,
                'title': 'Custom Survey Title',
                'message': 'Custom survey message',
                'method': 'email',
                'delay_minutes': 15
            }
        }
        
        await manager._send_survey_notifications(sample_survey.id, participants, distribution_id, config)
        
        # Verify notifications were created
        notifications = db_session.query(SurveyNotification).filter_by(survey_id=sample_survey.id).all()
        assert len(notifications) == 2
        
        for notification in notifications:
            assert notification.participant_id in participants
            assert notification.title == 'Custom Survey Title'
            assert notification.message == 'Custom survey message'
            assert notification.delivery_method == 'email'
            assert notification.notification_type == 'invitation'
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_pause_resume_trigger(self, mock_get_db, trigger_manager_instance, db_session, sample_survey):
        """Test pausing and resuming triggers"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create trigger
        trigger = SurveyTrigger(
            id=str(uuid.uuid4()),
            survey_id=sample_survey.id,
            trigger_type='test_trigger',
            trigger_conditions={},
            status='active'
        )
        db_session.add(trigger)
        db_session.commit()
        
        # Add to active triggers
        manager.active_triggers[trigger.id] = {
            'survey_id': sample_survey.id,
            'config': {},
            'status': 'active'
        }
        
        # Test pause
        await manager.pause_trigger(trigger.id)
        
        updated_trigger = db_session.query(SurveyTrigger).filter_by(id=trigger.id).first()
        assert updated_trigger.status == 'paused'
        assert manager.active_triggers[trigger.id]['status'] == 'paused'
        
        # Test resume
        await manager.resume_trigger(trigger.id)
        
        updated_trigger = db_session.query(SurveyTrigger).filter_by(id=trigger.id).first()
        assert updated_trigger.status == 'active'
        assert manager.active_triggers[trigger.id]['status'] == 'active'
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_get_trigger_statistics(self, mock_get_db, trigger_manager_instance, db_session, sample_survey):
        """Test getting trigger statistics"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create test triggers
        triggers = [
            SurveyTrigger(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                trigger_type=TriggerType.ANALYSIS_COMPLETE.value,
                trigger_conditions={},
                status='active'
            ),
            SurveyTrigger(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                trigger_type=TriggerType.DATA_UPLOAD.value,
                trigger_conditions={},
                status='paused'
            ),
            SurveyTrigger(
                id=str(uuid.uuid4()),
                survey_id=sample_survey.id,
                trigger_type=TriggerType.ANALYSIS_COMPLETE.value,
                trigger_conditions={},
                status='active'
            )
        ]
        
        for trigger in triggers:
            db_session.add(trigger)
        db_session.commit()
        
        # Add some to active triggers
        manager.active_triggers[triggers[0].id] = {'status': 'active'}
        
        stats = await manager.get_trigger_statistics()
        
        assert stats['total_triggers'] == 3
        assert stats['active_triggers'] == 2  # Two active triggers
        assert stats['trigger_types'][TriggerType.ANALYSIS_COMPLETE.value] == 2
        assert stats['trigger_types'][TriggerType.DATA_UPLOAD.value] == 1
        assert stats['in_memory_triggers'] == 1


class TestEventHandlers:
    """Test event-specific handlers"""
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_handle_analysis_complete(self, mock_get_db, trigger_manager_instance, db_session):
        """Test analysis completion event handler"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create surveys in relevant categories
        post_analysis_survey = Survey(
            id=str(uuid.uuid4()),
            title='Post Analysis Survey',
            category='post_analysis_feedback',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        quality_survey = Survey(
            id=str(uuid.uuid4()),
            title='Quality Assessment Survey',
            category='quality_assessment', 
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        db_session.add_all([post_analysis_survey, quality_survey])
        db_session.commit()
        
        # Test high-quality group analysis
        high_quality_event = TriggerEvent(
            event_type=TriggerType.ANALYSIS_COMPLETE.value,
            event_data={
                'analysis_type': 'group_analysis',
                'quality_score': 0.85
            }
        )
        
        triggered_surveys = await manager._handle_analysis_complete(high_quality_event)
        assert post_analysis_survey.id in triggered_surveys
        assert quality_survey.id not in triggered_surveys  # Quality score is high
        
        # Test low-quality analysis
        low_quality_event = TriggerEvent(
            event_type=TriggerType.ANALYSIS_COMPLETE.value,
            event_data={
                'analysis_type': 'statistical_analysis',
                'quality_score': 0.5
            }
        )
        
        triggered_surveys = await manager._handle_analysis_complete(low_quality_event)
        assert post_analysis_survey.id in triggered_surveys
        assert quality_survey.id in triggered_surveys  # Quality score is low
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_handle_data_upload(self, mock_get_db, trigger_manager_instance, db_session):
        """Test data upload event handler"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create surveys in relevant categories
        data_quality_survey = Survey(
            id=str(uuid.uuid4()),
            title='Data Quality Survey',
            category='data_quality',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        dataset_desc_survey = Survey(
            id=str(uuid.uuid4()),
            title='Dataset Description Survey',
            category='dataset_description',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        db_session.add_all([data_quality_survey, dataset_desc_survey])
        db_session.commit()
        
        # Test neuroimaging file upload
        nifti_upload_event = TriggerEvent(
            event_type=TriggerType.DATA_UPLOAD.value,
            event_data={
                'file_type': 'nifti',
                'size_mb': 500
            }
        )
        
        triggered_surveys = await manager._handle_data_upload(nifti_upload_event)
        assert data_quality_survey.id in triggered_surveys
        assert dataset_desc_survey.id not in triggered_surveys  # Size < 1000MB
        
        # Test large dataset upload
        large_upload_event = TriggerEvent(
            event_type=TriggerType.DATA_UPLOAD.value,
            event_data={
                'file_type': 'dicom',
                'size_mb': 1500
            }
        )
        
        triggered_surveys = await manager._handle_data_upload(large_upload_event)
        assert data_quality_survey.id in triggered_surveys
        assert dataset_desc_survey.id in triggered_surveys  # Size > 1000MB
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_handle_study_milestone(self, mock_get_db, trigger_manager_instance, db_session):
        """Test study milestone event handler"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create surveys for different milestones
        baseline_survey = Survey(
            id=str(uuid.uuid4()),
            title='Baseline Assessment',
            category='baseline_assessment',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        final_survey = Survey(
            id=str(uuid.uuid4()),
            title='Final Assessment',
            category='final_assessment',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        db_session.add_all([baseline_survey, final_survey])
        db_session.commit()
        
        # Test participant enrollment milestone
        enrollment_event = TriggerEvent(
            event_type=TriggerType.STUDY_MILESTONE.value,
            event_data={
                'milestone_type': 'participant_enrolled',
                'participant_id': 'P001'
            }
        )
        
        triggered_surveys = await manager._handle_study_milestone(enrollment_event)
        assert baseline_survey.id in triggered_surveys
        assert final_survey.id not in triggered_surveys
        
        # Test study completion milestone
        completion_event = TriggerEvent(
            event_type=TriggerType.STUDY_MILESTONE.value,
            event_data={
                'milestone_type': 'study_complete',
                'study_id': 'STUDY001'
            }
        )
        
        triggered_surveys = await manager._handle_study_milestone(completion_event)
        assert final_survey.id in triggered_surveys
        assert baseline_survey.id not in triggered_surveys
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_handle_pipeline_event(self, mock_get_db, trigger_manager_instance, db_session):
        """Test neuroimaging pipeline event handler"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create surveys for different pipeline stages
        preproc_qc_survey = Survey(
            id=str(uuid.uuid4()),
            title='Preprocessing QC',
            category='preprocessing_qc',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        group_analysis_survey = Survey(
            id=str(uuid.uuid4()),
            title='Group Analysis Validation',
            category='group_analysis_validation',
            creator_id=str(uuid.uuid4()),
            status='active'
        )
        
        db_session.add_all([preproc_qc_survey, group_analysis_survey])
        db_session.commit()
        
        # Test preprocessing completion
        preproc_event = TriggerEvent(
            event_type=TriggerType.NEUROIMAGING_PIPELINE.value,
            event_data={
                'stage': 'preprocessing_complete',
                'subject_id': 'sub-01'
            }
        )
        
        triggered_surveys = await manager._handle_pipeline_event(preproc_event)
        assert preproc_qc_survey.id in triggered_surveys
        assert group_analysis_survey.id not in triggered_surveys
        
        # Test group analysis completion
        group_event = TriggerEvent(
            event_type=TriggerType.NEUROIMAGING_PIPELINE.value,
            event_data={
                'stage': 'group_analysis_complete',
                'analysis_id': 'group_001'
            }
        )
        
        triggered_surveys = await manager._handle_pipeline_event(group_event)
        assert group_analysis_survey.id in triggered_surveys
        assert preproc_qc_survey.id not in triggered_surveys


class TestUtilityFunctions:
    """Test utility functions and convenience methods"""
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_get_surveys_by_category(self, mock_get_db, trigger_manager_instance, db_session):
        """Test getting surveys by category"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create surveys in different categories
        surveys = [
            Survey(
                id=str(uuid.uuid4()),
                title=f'Survey {i}',
                category='test_category' if i % 2 == 0 else 'other_category',
                creator_id=str(uuid.uuid4()),
                status='active' if i < 3 else 'draft'  # Only first 3 are active
            )
            for i in range(5)
        ]
        
        for survey in surveys:
            db_session.add(survey)
        db_session.commit()
        
        # Get active surveys in test_category
        test_surveys = await manager._get_surveys_by_category('test_category')
        
        # Should return 2 surveys (indices 0, 2 are test_category and active)
        assert len(test_surveys) == 2
        
        # Get surveys in non-existent category
        empty_surveys = await manager._get_surveys_by_category('nonexistent_category')
        assert len(empty_surveys) == 0
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_get_active_surveys_with_reminders(self, mock_get_db, trigger_manager_instance, db_session):
        """Test getting surveys with reminder settings"""
        mock_get_db.return_value = db_session
        
        manager = trigger_manager_instance
        
        # Create surveys with different reminder settings
        weekly_survey = Survey(
            id=str(uuid.uuid4()),
            title='Weekly Reminder Survey',
            category='test',
            creator_id=str(uuid.uuid4()),
            status='active',
            settings={
                'reminders': {
                    'enabled': True,
                    'frequency': 'weekly'
                }
            }
        )
        
        daily_survey = Survey(
            id=str(uuid.uuid4()),
            title='Daily Reminder Survey',
            category='test',
            creator_id=str(uuid.uuid4()),
            status='active',
            settings={
                'reminders': {
                    'enabled': True,
                    'frequency': 'daily'
                }
            }
        )
        
        no_reminder_survey = Survey(
            id=str(uuid.uuid4()),
            title='No Reminder Survey',
            category='test',
            creator_id=str(uuid.uuid4()),
            status='active',
            settings={}
        )
        
        db_session.add_all([weekly_survey, daily_survey, no_reminder_survey])
        db_session.commit()
        
        # Get weekly reminder surveys
        weekly_surveys = await manager._get_active_surveys_with_reminders('weekly')
        assert weekly_survey.id in weekly_surveys
        assert daily_survey.id not in weekly_surveys
        assert no_reminder_survey.id not in weekly_surveys
        
        # Get daily reminder surveys
        daily_surveys = await manager._get_active_surveys_with_reminders('daily')
        assert daily_survey.id in daily_surveys
        assert weekly_survey.id not in daily_surveys
    
    @pytest.mark.asyncio
    async def test_schedule_delayed_trigger(self, trigger_manager_instance):
        """Test scheduling delayed triggers"""
        manager = trigger_manager_instance
        
        event = TriggerEvent(
            event_type='test_event',
            event_data={}
        )
        
        # This is mostly a logging function currently
        # Test that it doesn't raise an exception
        await manager._schedule_delayed_trigger(60, event)
        
        # In a real implementation, this would verify the task was scheduled
        # For now, we just verify no exception was raised
        assert True


class TestConvenienceFunctions:
    """Test module-level convenience functions"""
    
    @pytest.mark.asyncio
    async def test_trigger_survey_event(self):
        """Test trigger_survey_event convenience function"""
        with patch('brain_researcher.services.orchestrator.survey_triggers.trigger_manager') as mock_manager:
            mock_manager.process_event = AsyncMock(return_value=['survey_123'])
            
            result = await trigger_survey_event(
                'test_event',
                {'key': 'value'},
                user_id='user_123'
            )
            
            assert result == ['survey_123']
            mock_manager.process_event.assert_called_once()
            
            # Verify the event was created correctly
            call_args = mock_manager.process_event.call_args[0][0]
            assert call_args.event_type == 'test_event'
            assert call_args.event_data['key'] == 'value'
            assert call_args.user_id == 'user_123'
    
    @pytest.mark.asyncio
    async def test_setup_analysis_complete_trigger(self):
        """Test setup_analysis_complete_trigger convenience function"""
        with patch('brain_researcher.services.orchestrator.survey_triggers.trigger_manager') as mock_manager:
            mock_manager.setup_trigger = AsyncMock(return_value='trigger_123')
            
            trigger_id = await setup_analysis_complete_trigger(
                'survey_123',
                ['group_analysis', 'statistical_analysis']
            )
            
            assert trigger_id == 'trigger_123'
            mock_manager.setup_trigger.assert_called_once()
            
            # Verify the config was created correctly
            call_args = mock_manager.setup_trigger.call_args
            survey_id, config = call_args[0]
            
            assert survey_id == 'survey_123'
            assert config['type'] == TriggerType.ANALYSIS_COMPLETE.value
            assert config['conditions']['event_data']['analysis_type']['value'] == ['group_analysis', 'statistical_analysis']
            assert config['targeting']['from_event'] is True
            assert config['notifications']['enabled'] is True


class TestErrorHandling:
    """Test error handling in trigger system"""
    
    @pytest.mark.asyncio
    async def test_handler_error_handling(self, trigger_manager_instance):
        """Test that handler errors don't stop event processing"""
        manager = trigger_manager_instance
        
        # Register handlers that raise exceptions
        async def failing_handler(event):
            raise Exception("Handler failed")
        
        async def working_handler(event):
            return ['survey_123']
        
        manager.register_handler('test_event', failing_handler)
        manager.register_handler('test_event', working_handler)
        
        event = TriggerEvent(
            event_type='test_event',
            event_data={}
        )
        
        # Should continue processing despite failing handler
        triggered_surveys = await manager.process_event(event)
        assert 'survey_123' in triggered_surveys
    
    @patch('brain_researcher.services.orchestrator.survey_triggers.get_db')
    @pytest.mark.asyncio
    async def test_database_error_handling(self, mock_get_db, trigger_manager_instance):
        """Test handling of database errors"""
        # Mock database that raises exception
        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database connection failed")
        mock_get_db.return_value = mock_db
        
        manager = trigger_manager_instance
        
        # Should handle database errors gracefully
        surveys = await manager._get_surveys_by_category('test_category')
        assert surveys == []
        
        stats = await manager.get_trigger_statistics()
        assert stats == {}


if __name__ == '__main__':
    pytest.main([__file__])