"""
Survey System Data Models

SQLAlchemy models for survey management, response collection, and analytics.
Designed specifically for neuroimaging research workflows.
"""

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer, Float, 
    ForeignKey, JSON, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import uuid
from typing import Dict, Any, List, Optional
from enum import Enum

Base = declarative_base()

class SurveyStatus(Enum):
    """Survey status enumeration"""
    DRAFT = "draft"
    ACTIVE = "active" 
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"

class QuestionType(Enum):
    """Question type enumeration for neuroimaging surveys"""
    MULTIPLE_CHOICE = "multiple_choice"
    SINGLE_CHOICE = "single_choice"
    TEXT = "text"
    TEXTAREA = "textarea"
    SCALE = "scale"
    MATRIX = "matrix"
    NEUROIMAGING_PROTOCOL = "neuroimaging_protocol"
    BRAIN_REGION = "brain_region"
    COGNITIVE_BATTERY = "cognitive_battery"
    MEDICATION_HISTORY = "medication_history"
    SCANNER_PARAMETERS = "scanner_parameters"

class Survey(Base):
    """Main survey table"""
    __tablename__ = "surveys"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    category = Column(String(50), nullable=False, index=True)  # e.g., 'cognitive_assessment', 'demographics'
    creator_id = Column(String, nullable=False, index=True)
    target_audience = Column(String(100))  # e.g., 'researchers', 'participants', 'clinicians'
    
    # Survey configuration
    settings = Column(JSON, default=dict)  # Theme, logic, validation settings
    neuroimaging_context = Column(JSON, default=dict)  # Specific neuroimaging metadata
    
    # Status and lifecycle
    status = Column(String(20), nullable=False, default="draft", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    published_at = Column(DateTime)
    expires_at = Column(DateTime)
    
    # Analytics metadata
    expected_responses = Column(Integer, default=0)
    max_responses = Column(Integer)
    
    # Relationships
    questions = relationship("SurveyQuestion", back_populates="survey", cascade="all, delete-orphan")
    responses = relationship("SurveyResponse", back_populates="survey")
    distributions = relationship("SurveyDistribution", back_populates="survey")
    triggers = relationship("SurveyTrigger", back_populates="survey")
    insights = relationship("SurveyInsight", back_populates="survey")
    
    __table_args__ = (
        Index('ix_surveys_creator_status', 'creator_id', 'status'),
        Index('ix_surveys_category_status', 'category', 'status'),
        # SQLite does not enforce VARCHAR length; add an explicit check for unit tests.
        CheckConstraint("length(title) <= 200", name="ck_surveys_title_length"),
    )

class SurveyQuestion(Base):
    """Survey questions with neuroimaging-specific support"""
    __tablename__ = "survey_questions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False)
    
    # Question content
    question_text = Column(Text, nullable=False)
    question_type = Column(String(30), nullable=False)  # QuestionType enum values
    description = Column(Text)  # Additional context or instructions
    
    # Configuration
    options = Column(JSON, default=dict)  # Answer options, scale ranges, etc.
    validation_rules = Column(JSON, default=dict)  # Validation criteria
    conditional_logic = Column(JSON, default=dict)  # Show/hide logic
    
    # Neuroimaging-specific fields
    neuroimaging_context = Column(JSON, default=dict)  # Brain regions, protocols, etc.
    cognitive_domain = Column(String(50))  # Associated cognitive domain
    
    # Display and ordering
    order_index = Column(Integer, nullable=False)
    required = Column(Boolean, default=False)
    randomize_options = Column(Boolean, default=False)
    
    # Relationships
    survey = relationship("Survey", back_populates="questions")
    
    __table_args__ = (
        Index('ix_questions_survey_order', 'survey_id', 'order_index'),
        UniqueConstraint('survey_id', 'order_index', name='uq_survey_question_order'),
    )

class SurveyResponse(Base):
    """Individual survey responses"""
    __tablename__ = "survey_responses"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False, index=True)
    participant_id = Column(String, nullable=False, index=True)  # Can be anonymous
    
    # Response data
    responses = Column(JSON, nullable=False)  # Question ID -> response mapping
    response_metadata = Column(JSON, default=dict)  # Additional response metadata
    
    # Session information
    session_data = Column(JSON, default=dict)  # Browser, device, timing data
    ip_address = Column(String(45))  # IPv4/IPv6 support
    user_agent = Column(Text)
    
    # Status and timing
    completion_status = Column(String(20), default="in_progress")  # in_progress, completed, abandoned
    started_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime)
    completion_time_seconds = Column(Integer)  # Total completion time
    
    # Quality metrics
    quality_score = Column(Float)  # Automated quality assessment (0-1)
    flagged_for_review = Column(Boolean, default=False)
    review_notes = Column(Text)
    
    # Relationships
    survey = relationship("Survey", back_populates="responses")
    
    __table_args__ = (
        Index('ix_responses_survey_participant', 'survey_id', 'participant_id'),
        Index('ix_responses_submitted_at', 'submitted_at'),
        Index('ix_responses_completion_status', 'completion_status'),
    )

class SurveyDistribution(Base):
    """Survey distribution and scheduling"""
    __tablename__ = "survey_distributions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False)
    
    # Distribution configuration
    distribution_type = Column(String(20), nullable=False)  # manual, scheduled, triggered
    schedule_config = Column(JSON, default=dict)  # Cron expressions, dates
    target_criteria = Column(JSON, default=dict)  # Audience targeting
    
    # Distribution status
    status = Column(String(20), default="pending")  # pending, active, completed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    activated_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Metrics
    sent_count = Column(Integer, default=0)
    opened_count = Column(Integer, default=0)
    response_count = Column(Integer, default=0)
    
    # Relationships
    survey = relationship("Survey", back_populates="distributions")

class SurveyTrigger(Base):
    """Automated survey triggers based on system events"""
    __tablename__ = "survey_triggers"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False)
    
    # Trigger configuration
    trigger_type = Column(String(30), nullable=False)  # analysis_complete, data_upload, etc.
    trigger_conditions = Column(JSON, default=dict)  # Conditions to match
    trigger_data = Column(JSON, default=dict)  # Additional trigger metadata
    
    # Status and execution
    status = Column(String(20), default="active")  # active, paused, expired
    created_at = Column(DateTime, default=datetime.utcnow)
    last_triggered_at = Column(DateTime)
    trigger_count = Column(Integer, default=0)
    
    # Relationships
    survey = relationship("Survey", back_populates="triggers")

class SurveyInsight(Base):
    """AI-generated insights from survey responses"""
    __tablename__ = "survey_insights"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False, index=True)
    
    # Insight content
    insight_type = Column(String(30), nullable=False)  # sentiment, trends, correlations
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    confidence_score = Column(Float)  # 0-1 confidence in insight
    
    # Supporting data
    supporting_data = Column(JSON, default=dict)  # Charts, statistics, etc.
    methodology = Column(JSON, default=dict)  # How insight was generated
    
    # Metadata
    generated_at = Column(DateTime, default=datetime.utcnow)
    generated_by = Column(String(50))  # AI model or algorithm used
    review_status = Column(String(20), default="pending")  # pending, approved, rejected
    
    # Relationships
    survey = relationship("Survey", back_populates="insights")
    
    __table_args__ = (
        Index('ix_insights_survey_type', 'survey_id', 'insight_type'),
    )

class SurveyTemplate(Base):
    """Pre-built survey templates for common neuroimaging studies"""
    __tablename__ = "survey_templates"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(50), nullable=False, index=True)
    
    # Neuroimaging-specific categorization
    # Use JSON-backed lists for SQLite-friendly unit tests; compatible with Postgres too.
    neuroimaging_focus = Column(JSON, default=list)  # fMRI, EEG, MEG, etc.
    study_types = Column(JSON, default=list)  # task-based, resting-state, etc.
    cognitive_domains = Column(JSON, default=list)  # attention, memory, etc.
    
    # Template content
    template_questions = Column(JSON, nullable=False)  # Question definitions
    default_settings = Column(JSON, default=dict)  # Default survey settings
    
    # Usage tracking
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String)  # Creator ID
    
    # Tags and search
    tags = Column(JSON, default=list)
    is_public = Column(Boolean, default=True)

class SurveyResponseAnalytics(Base):
    """Pre-computed analytics for survey responses"""
    __tablename__ = "survey_response_analytics"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False, index=True)
    
    # Analytics data
    analytics_type = Column(String(30), nullable=False)  # demographics, completion_rates, etc.
    time_period = Column(String(20))  # daily, weekly, monthly
    analytics_data = Column(JSON, nullable=False)  # The actual analytics
    
    # Metadata
    computed_at = Column(DateTime, default=datetime.utcnow)
    data_from = Column(DateTime)  # Start of data range
    data_to = Column(DateTime)  # End of data range
    record_count = Column(Integer)  # Number of responses analyzed
    
    __table_args__ = (
        Index('ix_analytics_survey_type_period', 'survey_id', 'analytics_type', 'time_period'),
        UniqueConstraint('survey_id', 'analytics_type', 'time_period', 'data_from', 'data_to',
                        name='uq_survey_analytics_period'),
    )

class SurveyNotification(Base):
    """Survey notifications and reminders"""
    __tablename__ = "survey_notifications"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False)
    participant_id = Column(String, nullable=False)
    
    # Notification content
    notification_type = Column(String(20), nullable=False)  # invitation, reminder, follow_up
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    
    # Delivery configuration
    delivery_method = Column(String(20), nullable=False)  # email, in_app, push
    delivery_config = Column(JSON, default=dict)  # Method-specific configuration
    
    # Status and timing
    status = Column(String(20), default="pending")  # pending, sent, delivered, failed
    scheduled_for = Column(DateTime)
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    opened_at = Column(DateTime)
    clicked_at = Column(DateTime)
    
    # Error handling
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    __table_args__ = (
        Index('ix_notifications_survey_participant', 'survey_id', 'participant_id'),
        Index('ix_notifications_status_scheduled', 'status', 'scheduled_for'),
    )

# Utility functions for database management

def create_survey_tables(engine=None):
    """Create all survey-related database tables"""
    if engine:
        Base.metadata.create_all(bind=engine)
    else:
        # Import engine from main database module
        try:
            from .database import engine as db_engine
            Base.metadata.create_all(bind=db_engine)
        except ImportError:
            # Fallback - tables will be created when engine is available
            pass

def get_neuroimaging_question_templates() -> Dict[str, Dict[str, Any]]:
    """Get pre-defined question templates for neuroimaging studies"""
    return {
        "scanner_parameters": {
            "type": "neuroimaging_protocol",
            "text": "Please specify the MRI scanner parameters used in this study",
            "options": {
                "field_strength": ["1.5T", "3T", "7T", "Other"],
                "pulse_sequence": ["T1-MPRAGE", "T2-FLAIR", "EPI", "DTI", "Other"],
                "voxel_size": {"type": "text", "validation": "numeric"},
                "repetition_time": {"type": "text", "validation": "numeric", "unit": "ms"},
                "echo_time": {"type": "text", "validation": "numeric", "unit": "ms"}
            },
            "neuroimaging_context": {
                "category": "acquisition_parameters",
                "required_for": ["fMRI", "structural_MRI"]
            }
        },
        "brain_regions": {
            "type": "brain_region",
            "text": "Which brain regions were analyzed in this study?",
            "options": {
                "selection_type": "multiple",
                "regions": [
                    "Prefrontal Cortex", "Motor Cortex", "Visual Cortex", "Auditory Cortex",
                    "Hippocampus", "Amygdala", "Thalamus", "Cerebellum", "Brainstem",
                    "Default Mode Network", "Salience Network", "Executive Control Network"
                ],
                "custom_allowed": True
            },
            "neuroimaging_context": {
                "category": "analysis_regions",
                "atlas_support": True
            }
        },
        "cognitive_assessment": {
            "type": "cognitive_battery",
            "text": "Which cognitive assessments were administered?",
            "options": {
                "assessments": [
                    "Stroop Task", "N-Back Task", "Go/No-Go Task", "Wisconsin Card Sort",
                    "Tower of London", "Digit Span", "Trail Making Test", "MMSE", "MoCA"
                ],
                "custom_allowed": True,
                "timing_info": True
            },
            "neuroimaging_context": {
                "category": "behavioral_measures",
                "synchronized_with_imaging": True
            }
        },
        "medication_history": {
            "type": "medication_history",
            "text": "Please provide medication history relevant to neuroimaging",
            "options": {
                "categories": [
                    "Antidepressants", "Antipsychotics", "Stimulants", "Sedatives",
                    "Neurological medications", "None", "Prefer not to answer"
                ],
                "dosage_info": True,
                "duration_info": True,
                "washout_period": True
            },
            "validation_rules": {
                "required_if": "participant_study",
                "privacy_level": "high"
            }
        },
        "study_demographics": {
            "type": "matrix",
            "text": "Participant demographics for neuroimaging study",
            "options": {
                "fields": {
                    "age": {"type": "number", "min": 18, "max": 100},
                    "gender": {"type": "select", "options": ["Male", "Female", "Other", "Prefer not to say"]},
                    "education_years": {"type": "number", "min": 0, "max": 25},
                    "handedness": {"type": "select", "options": ["Right", "Left", "Ambidextrous"]},
                    "vision_correction": {"type": "select", "options": ["None", "Glasses", "Contacts", "Both"]}
                }
            },
            "neuroimaging_context": {
                "category": "participant_characteristics",
                "statistical_covariates": True
            }
        }
    }

def get_survey_templates_by_category() -> Dict[str, List[Dict[str, Any]]]:
    """Get organized survey templates by research category"""
    return {
        "cognitive_neuroscience": [
            {
                "name": "fMRI Task-Based Study Survey",
                "description": "Comprehensive survey for task-based fMRI studies",
                "questions": ["scanner_parameters", "brain_regions", "cognitive_assessment", "study_demographics"]
            },
            {
                "name": "Resting-State fMRI Study Survey", 
                "description": "Survey for resting-state connectivity studies",
                "questions": ["scanner_parameters", "brain_regions", "medication_history", "study_demographics"]
            }
        ],
        "clinical_research": [
            {
                "name": "Clinical Neuroimaging Survey",
                "description": "Survey for clinical neuroimaging research",
                "questions": ["scanner_parameters", "brain_regions", "medication_history", "cognitive_assessment", "study_demographics"]
            }
        ],
        "user_experience": [
            {
                "name": "Analysis Platform Feedback",
                "description": "Collect feedback on neuroimaging analysis tools",
                "questions": ["platform_usability", "feature_requests", "technical_issues"]
            }
        ]
    }
