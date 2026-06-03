"""
Survey Trigger System

Automated survey distribution based on system events, user actions,
and neuroimaging analysis milestones.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
import logging
from dataclasses import dataclass
from enum import Enum
import json
import uuid
import inspect
from contextlib import contextmanager

from sqlalchemy.orm import Session
from .database import get_db
from .survey_models import Survey, SurveyTrigger, SurveyNotification, SurveyDistribution

logger = logging.getLogger(__name__)


@contextmanager
def _get_db_session():
    """Get a SQLAlchemy session from get_db(), supporting patched test deps."""
    db_source = get_db()

    if isinstance(db_source, Session):
        # Borrowed session (common in unit tests).
        yield db_source
        return

    if hasattr(db_source, "__enter__") and hasattr(db_source, "__exit__"):
        with db_source as db:
            yield db
        return

    if inspect.isgenerator(db_source):
        try:
            yield next(db_source)
        finally:
            db_source.close()
        return

    yield db_source

class TriggerType(Enum):
    """Types of survey triggers"""
    ANALYSIS_COMPLETE = "analysis_complete"
    DATA_UPLOAD = "data_upload"
    STUDY_MILESTONE = "study_milestone"
    TIME_BASED = "time_based"
    USER_ACTION = "user_action"
    SYSTEM_EVENT = "system_event"
    QUALITY_THRESHOLD = "quality_threshold"
    COMPLETION_RATE = "completion_rate"
    NEUROIMAGING_PIPELINE = "neuroimaging_pipeline"

class TriggerStatus(Enum):
    """Trigger execution status"""
    ACTIVE = "active"
    PAUSED = "paused"
    EXPIRED = "expired"
    ERROR = "error"

@dataclass
class TriggerEvent:
    """Represents a trigger event"""
    event_type: str
    event_data: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}

class SurveyTriggerManager:
    """Manages automated survey triggers and distribution"""

    def __init__(self):
        self.active_triggers: Dict[str, Dict[str, Any]] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self._setup_default_handlers()

    def _setup_default_handlers(self):
        """Set up default event handlers for common neuroimaging events"""

        # Analysis completion triggers
        self.register_handler(
            TriggerType.ANALYSIS_COMPLETE.value,
            self._handle_analysis_complete
        )

        # Data upload triggers
        self.register_handler(
            TriggerType.DATA_UPLOAD.value,
            self._handle_data_upload
        )

        # Study milestone triggers
        self.register_handler(
            TriggerType.STUDY_MILESTONE.value,
            self._handle_study_milestone
        )

        # Time-based triggers
        self.register_handler(
            TriggerType.TIME_BASED.value,
            self._handle_time_based
        )

        # Neuroimaging pipeline triggers
        self.register_handler(
            TriggerType.NEUROIMAGING_PIPELINE.value,
            self._handle_pipeline_event
        )

    def register_handler(self, event_type: str, handler: Callable):
        """Register an event handler for a trigger type"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.info(f"Registered handler for event type: {event_type}")

    async def setup_trigger(self, survey_id: str, trigger_config: Dict[str, Any]):
        """Set up a new survey trigger"""
        with _get_db_session() as db:
            try:
                # Validate survey exists
                survey = db.query(Survey).filter(Survey.id == survey_id).first()
                if not survey:
                    raise ValueError(f"Survey {survey_id} not found")

                # Create trigger record
                trigger = SurveyTrigger(
                    id=str(uuid.uuid4()),
                    survey_id=survey_id,
                    trigger_type=trigger_config["type"],
                    trigger_conditions=trigger_config.get("conditions", {}),
                    trigger_data=trigger_config.get("data", {}),
                    status="active",
                )

                db.add(trigger)
                db.commit()

                # Add to active triggers
                self.active_triggers[trigger.id] = {
                    "survey_id": survey_id,
                    "config": trigger_config,
                    "trigger_record": trigger,
                }

                logger.info(f"Set up trigger {trigger.id} for survey {survey_id}")

                return trigger.id

            except Exception as e:
                logger.error(f"Error setting up trigger: {e}")
                db.rollback()
                raise

    async def process_event(self, event: TriggerEvent) -> List[str]:
        """Process an event and trigger appropriate surveys"""
        triggered_surveys = []

        try:
            # Find handlers for this event type
            handlers = self.event_handlers.get(event.event_type, [])

            for handler in handlers:
                try:
                    survey_ids = await handler(event)
                    triggered_surveys.extend(survey_ids)
                except Exception as e:
                    logger.error(f"Error in handler for {event.event_type}: {e}")

            # Check active triggers
            matching_triggers = await self._find_matching_triggers(event)

            for trigger_id, trigger_data in matching_triggers.items():
                try:
                    survey_id = await self._execute_trigger(trigger_id, trigger_data, event)
                    if survey_id:
                        triggered_surveys.append(survey_id)
                except Exception as e:
                    logger.error(f"Error executing trigger {trigger_id}: {e}")

            logger.info(f"Event {event.event_type} triggered {len(triggered_surveys)} surveys")

        except Exception as e:
            logger.error(f"Error processing event {event.event_type}: {e}")

        return list(set(triggered_surveys))  # Remove duplicates

    async def _find_matching_triggers(self, event: TriggerEvent) -> Dict[str, Dict[str, Any]]:
        """Find triggers that match the given event"""
        matching = {}

        for trigger_id, trigger_data in self.active_triggers.items():
            try:
                config = trigger_data["config"]
                conditions = config.get("conditions", {})

                # Check if trigger type matches
                if config["type"] != event.event_type:
                    continue

                # Check specific conditions
                if await self._evaluate_trigger_conditions(conditions, event):
                    matching[trigger_id] = trigger_data

            except Exception as e:
                logger.error(f"Error evaluating trigger {trigger_id}: {e}")

        return matching

    async def _evaluate_trigger_conditions(self, conditions: Dict[str, Any], event: TriggerEvent) -> bool:
        """Evaluate if event matches trigger conditions"""

        # User-based conditions
        if "user_id" in conditions:
            if event.user_id != conditions["user_id"]:
                return False

        # Event data conditions
        event_conditions = conditions.get("event_data", {})
        for key, expected_value in event_conditions.items():
            if key not in event.event_data:
                return False

            actual_value = event.event_data[key]

            # Support different comparison operators
            if isinstance(expected_value, dict):
                operator = expected_value.get("operator", "equals")
                value = expected_value.get("value")

                if operator == "equals" and actual_value != value:
                    return False
                elif operator == "greater_than" and actual_value <= value:
                    return False
                elif operator == "less_than" and actual_value >= value:
                    return False
                elif operator == "contains" and value not in str(actual_value):
                    return False
            else:
                if actual_value != expected_value:
                    return False

        # Time-based conditions
        time_conditions = conditions.get("time", {})
        if time_conditions:
            if not await self._evaluate_time_conditions(time_conditions, event):
                return False

        return True

    async def _evaluate_time_conditions(self, time_conditions: Dict[str, Any], event: TriggerEvent) -> bool:
        """Evaluate time-based trigger conditions"""

        # Day of week
        if "day_of_week" in time_conditions:
            allowed_days = time_conditions["day_of_week"]
            current_day = event.timestamp.strftime("%A").lower()
            if current_day not in [d.lower() for d in allowed_days]:
                return False

        # Time range
        if "time_range" in time_conditions:
            start_time = time_conditions["time_range"]["start"]
            end_time = time_conditions["time_range"]["end"]
            current_time = event.timestamp.time()

            start = datetime.strptime(start_time, "%H:%M").time()
            end = datetime.strptime(end_time, "%H:%M").time()

            if not (start <= current_time <= end):
                return False

        # Delay condition
        if "delay_minutes" in time_conditions:
            delay = time_conditions["delay_minutes"]
            # Schedule for later execution
            await self._schedule_delayed_trigger(delay, event)
            return False  # Don't trigger now

        return True

    async def _execute_trigger(self, trigger_id: str, trigger_data: Dict[str, Any], event: TriggerEvent) -> Optional[str]:
        """Execute a trigger and distribute survey"""

        try:
            survey_id = trigger_data["survey_id"]
            config = trigger_data["config"]

            # Update trigger record
            with _get_db_session() as db:
                trigger = (
                    db.query(SurveyTrigger).filter(SurveyTrigger.id == trigger_id).first()
                )
                if trigger:
                    trigger.last_triggered_at = datetime.utcnow()
                    trigger.trigger_count += 1
                    db.commit()

            # Determine target participants
            participants = await self._get_target_participants(config, event)

            if not participants:
                logger.warning(f"No target participants found for trigger {trigger_id}")
                return None

            # Create distribution
            distribution = await self._create_triggered_distribution(
                survey_id, participants, config, event
            )

            # Send notifications
            await self._send_survey_notifications(
                survey_id, participants, distribution["id"], config
            )

            logger.info(f"Executed trigger {trigger_id} for survey {survey_id}, {len(participants)} participants")

            return survey_id

        except Exception as e:
            logger.error(f"Error executing trigger {trigger_id}: {e}")
            return None

    async def _get_target_participants(self, config: Dict[str, Any], event: TriggerEvent) -> List[str]:
        """Get target participants for triggered survey"""
        participants = []

        targeting = config.get("targeting", {})

        # Event-based targeting
        if "from_event" in targeting:
            if event.user_id:
                participants.append(event.user_id)

        # Role-based targeting
        if "roles" in targeting:
            # Would integrate with user management system
            # For now, use event user or system users
            if event.user_id:
                participants.append(event.user_id)

        # Study-based targeting
        if "study_participants" in targeting:
            study_id = targeting["study_participants"]
            # Would query study participant database
            # Placeholder implementation
            participants.extend(["participant_1", "participant_2"])

        # Custom participant list
        if "participant_ids" in targeting:
            participants.extend(targeting["participant_ids"])

        return list(set(participants))  # Remove duplicates

    async def _create_triggered_distribution(self, survey_id: str, participants: List[str],
                                           config: Dict[str, Any], event: TriggerEvent) -> Dict[str, Any]:
        """Create a distribution record for triggered survey"""

        with _get_db_session() as db:
            try:
                distribution = SurveyDistribution(
                    id=str(uuid.uuid4()),
                    survey_id=survey_id,
                    distribution_type="triggered",
                    target_criteria={
                        "trigger_event": event.event_type,
                        "participant_count": len(participants),
                        "trigger_metadata": event.metadata,
                    },
                    status="active",
                    activated_at=datetime.utcnow(),
                )

                db.add(distribution)
                db.commit()

                return {"id": distribution.id, "status": "created"}

            except Exception as e:
                logger.error(f"Error creating distribution: {e}")
                db.rollback()
                raise

    async def _send_survey_notifications(self, survey_id: str, participants: List[str],
                                       distribution_id: str, config: Dict[str, Any]):
        """Send survey notifications to participants"""

        notification_config = config.get("notifications", {})
        if not notification_config.get("enabled", True):
            return

        with _get_db_session() as db:
            try:
                survey = db.query(Survey).filter(Survey.id == survey_id).first()

                for participant_id in participants:
                    notification = SurveyNotification(
                        id=str(uuid.uuid4()),
                        survey_id=survey_id,
                        participant_id=participant_id,
                        notification_type="invitation",
                        title=notification_config.get("title", f"Survey: {survey.title}"),
                        message=notification_config.get(
                            "message",
                            "You have been invited to participate in a survey.",
                        ),
                        delivery_method=notification_config.get("method", "email"),
                        delivery_config=notification_config.get("delivery_config", {}),
                        scheduled_for=datetime.utcnow()
                        + timedelta(minutes=notification_config.get("delay_minutes", 0)),
                    )

                    db.add(notification)

                db.commit()
                logger.info(
                    f"Created {len(participants)} notifications for survey {survey_id}"
                )

            except Exception as e:
                logger.error(f"Error creating notifications: {e}")
                db.rollback()

    # Event-specific handlers

    async def _handle_analysis_complete(self, event: TriggerEvent) -> List[str]:
        """Handle analysis completion events"""
        triggered_surveys = []

        # Check if this is a significant analysis completion
        analysis_data = event.event_data

        if analysis_data.get("analysis_type") in ["group_analysis", "statistical_analysis"]:
            # Trigger post-analysis feedback survey
            post_analysis_surveys = await self._get_surveys_by_category("post_analysis_feedback")
            triggered_surveys.extend(post_analysis_surveys)

        if analysis_data.get("quality_score", 0) < 0.7:
            # Trigger quality assessment survey
            quality_surveys = await self._get_surveys_by_category("quality_assessment")
            triggered_surveys.extend(quality_surveys)

        return triggered_surveys

    async def _handle_data_upload(self, event: TriggerEvent) -> List[str]:
        """Handle data upload events"""
        triggered_surveys = []

        upload_data = event.event_data

        # Check file type
        if upload_data.get("file_type") in ["nifti", "dicom"]:
            # Trigger data quality survey
            data_quality_surveys = await self._get_surveys_by_category("data_quality")
            triggered_surveys.extend(data_quality_surveys)

        # Check upload size
        if upload_data.get("size_mb", 0) > 1000:  # Large dataset
            # Trigger dataset description survey
            dataset_surveys = await self._get_surveys_by_category("dataset_description")
            triggered_surveys.extend(dataset_surveys)

        return triggered_surveys

    async def _handle_study_milestone(self, event: TriggerEvent) -> List[str]:
        """Handle study milestone events"""
        triggered_surveys = []

        milestone_data = event.event_data
        milestone_type = milestone_data.get("milestone_type")

        if milestone_type == "participant_enrolled":
            # Trigger baseline assessment
            baseline_surveys = await self._get_surveys_by_category("baseline_assessment")
            triggered_surveys.extend(baseline_surveys)

        elif milestone_type == "scanning_complete":
            # Trigger post-scan feedback
            post_scan_surveys = await self._get_surveys_by_category("post_scan_feedback")
            triggered_surveys.extend(post_scan_surveys)

        elif milestone_type == "study_complete":
            # Trigger final assessment
            final_surveys = await self._get_surveys_by_category("final_assessment")
            triggered_surveys.extend(final_surveys)

        return triggered_surveys

    async def _handle_time_based(self, event: TriggerEvent) -> List[str]:
        """Handle time-based trigger events"""
        # This would typically be called by a scheduler
        time_data = event.event_data
        trigger_type = time_data.get("trigger_type")

        triggered_surveys = []

        if trigger_type == "weekly_reminder":
            # Get surveys that need weekly reminders
            weekly_surveys = await self._get_active_surveys_with_reminders("weekly")
            triggered_surveys.extend(weekly_surveys)

        elif trigger_type == "study_followup":
            # Get follow-up surveys
            followup_surveys = await self._get_surveys_by_category("followup")
            triggered_surveys.extend(followup_surveys)

        return triggered_surveys

    async def _handle_pipeline_event(self, event: TriggerEvent) -> List[str]:
        """Handle neuroimaging pipeline events"""
        triggered_surveys = []

        pipeline_data = event.event_data
        pipeline_stage = pipeline_data.get("stage")

        if pipeline_stage == "preprocessing_complete":
            # Trigger preprocessing quality check
            qc_surveys = await self._get_surveys_by_category("preprocessing_qc")
            triggered_surveys.extend(qc_surveys)

        elif pipeline_stage == "first_level_complete":
            # Trigger first-level analysis feedback
            first_level_surveys = await self._get_surveys_by_category("first_level_feedback")
            triggered_surveys.extend(first_level_surveys)

        elif pipeline_stage == "group_analysis_complete":
            # Trigger group analysis validation
            group_surveys = await self._get_surveys_by_category("group_analysis_validation")
            triggered_surveys.extend(group_surveys)

        return triggered_surveys

    # Utility methods

    async def _get_surveys_by_category(self, category: str) -> List[str]:
        """Get active survey IDs by category"""
        with _get_db_session() as db:
            try:
                surveys = db.query(Survey).filter(
                    Survey.category == category,
                    Survey.status == "active",
                ).all()
                return [s.id for s in surveys]
            except Exception as e:
                logger.error(f"Error getting surveys by category {category}: {e}")
                return []

    async def _get_active_surveys_with_reminders(self, reminder_frequency: str) -> List[str]:
        """Get surveys that have reminder settings"""
        with _get_db_session() as db:
            try:
                surveys = db.query(Survey).filter(Survey.status == "active").all()

                reminder_surveys = []
                for survey in surveys:
                    settings = survey.settings or {}
                    reminders = settings.get("reminders", {})
                    if reminders.get("frequency") == reminder_frequency:
                        reminder_surveys.append(survey.id)

                return reminder_surveys
            except Exception as e:
                logger.error(
                    f"Error getting surveys with {reminder_frequency} reminders: {e}"
                )
                return []

    async def _schedule_delayed_trigger(self, delay_minutes: int, event: TriggerEvent):
        """Schedule a trigger for later execution"""
        # This would integrate with a task scheduler like Celery
        # For now, just log the scheduled trigger
        scheduled_time = datetime.utcnow() + timedelta(minutes=delay_minutes)
        logger.info(f"Scheduled delayed trigger for {scheduled_time} with event {event.event_type}")

    # Management methods

    async def pause_trigger(self, trigger_id: str):
        """Pause a specific trigger"""
        if trigger_id in self.active_triggers:
            with _get_db_session() as db:
                try:
                    trigger = (
                        db.query(SurveyTrigger)
                        .filter(SurveyTrigger.id == trigger_id)
                        .first()
                    )
                    if trigger:
                        trigger.status = "paused"
                        db.commit()

                    self.active_triggers[trigger_id]["status"] = "paused"
                    logger.info(f"Paused trigger {trigger_id}")
                except Exception as e:
                    logger.error(f"Error pausing trigger {trigger_id}: {e}")

    async def resume_trigger(self, trigger_id: str):
        """Resume a paused trigger"""
        if trigger_id in self.active_triggers:
            with _get_db_session() as db:
                try:
                    trigger = (
                        db.query(SurveyTrigger)
                        .filter(SurveyTrigger.id == trigger_id)
                        .first()
                    )
                    if trigger:
                        trigger.status = "active"
                        db.commit()

                    self.active_triggers[trigger_id]["status"] = "active"
                    logger.info(f"Resumed trigger {trigger_id}")
                except Exception as e:
                    logger.error(f"Error resuming trigger {trigger_id}: {e}")

    async def get_trigger_statistics(self) -> Dict[str, Any]:
        """Get statistics about trigger performance"""
        with _get_db_session() as db:
            try:
                total_triggers = db.query(SurveyTrigger).count()
                active_triggers = db.query(SurveyTrigger).filter(
                    SurveyTrigger.status == "active"
                ).count()

                # Get trigger counts by type
                trigger_types = db.query(SurveyTrigger.trigger_type).distinct().all()
                type_counts = {}
                for (trigger_type,) in trigger_types:
                    count = db.query(SurveyTrigger).filter(
                        SurveyTrigger.trigger_type == trigger_type
                    ).count()
                    type_counts[trigger_type] = count

                return {
                    "total_triggers": total_triggers,
                    "active_triggers": active_triggers,
                    "trigger_types": type_counts,
                    "in_memory_triggers": len(self.active_triggers),
                }
            except Exception as e:
                logger.error(f"Error getting trigger statistics: {e}")
                return {}

# Global trigger manager instance
trigger_manager = SurveyTriggerManager()

# Convenience functions for external use

async def trigger_survey_event(event_type: str, event_data: Dict[str, Any],
                             user_id: Optional[str] = None, **kwargs) -> List[str]:
    """Convenience function to trigger survey events"""
    event = TriggerEvent(
        event_type=event_type,
        event_data=event_data,
        user_id=user_id,
        **kwargs
    )
    return await trigger_manager.process_event(event)

async def setup_analysis_complete_trigger(survey_id: str, analysis_types: List[str] = None):
    """Set up trigger for analysis completion"""
    config = {
        "type": TriggerType.ANALYSIS_COMPLETE.value,
        "conditions": {
            "event_data": {
                "analysis_type": {"operator": "contains", "value": analysis_types or ["any"]}
            }
        },
        "targeting": {"from_event": True},
        "notifications": {"enabled": True, "method": "email"}
    }
    return await trigger_manager.setup_trigger(survey_id, config)
