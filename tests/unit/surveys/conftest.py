"""
Test configuration for survey system unit tests.
Provides SQLAlchemy fixtures for database testing.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Import the Base from survey models
from brain_researcher.services.orchestrator.survey_models import Base

@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite database for testing."""
    # Use StaticPool to ensure connections are not closed
    # This is important for SQLite in-memory databases
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    # Create all tables
    Base.metadata.create_all(eng)
    yield eng
    # Clean up
    Base.metadata.drop_all(eng)
    eng.dispose()

@pytest.fixture
def db(engine) -> Session:
    """Create a new database session for each test."""
    # Create a sessionmaker
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )
    
    # Create a new session
    session = TestingSessionLocal()
    
    # Start a transaction
    session.begin()
    
    try:
        yield session
    finally:
        # Rollback the transaction to keep tests isolated
        session.rollback()
        session.close()

@pytest.fixture
def sample_survey_data():
    """Provide sample survey data for testing."""
    return {
        "title": "Neuroimaging Research Experience Survey",
        "description": "Understanding researcher experiences with neuroimaging tools",
        "neuroimaging_specific": True,
        "questions": [
            {
                "text": "Which fMRI analysis software do you primarily use?",
                "type": "single_choice",
                "options": ["FSL", "SPM", "AFNI", "FreeSurfer", "Other"],
                "required": True
            },
            {
                "text": "Rate your experience with the software",
                "type": "rating",
                "scale_min": 1,
                "scale_max": 5,
                "required": True
            },
            {
                "text": "Select brain regions of interest",
                "type": "brain_region",
                "multiple": True,
                "required": False
            }
        ],
        "targeting": {
            "min_experience_years": 1,
            "research_areas": ["fMRI", "structural MRI"],
            "tool_experience": ["FSL", "SPM"]
        }
    }

@pytest.fixture
def sample_response_data():
    """Provide sample survey response data for testing."""
    return {
        "survey_id": "test_survey_123",
        "user_id": "test_user_456",
        "answers": [
            {
                "question_id": "q1",
                "value": "FSL"
            },
            {
                "question_id": "q2",
                "value": 4
            },
            {
                "question_id": "q3",
                "value": ["Hippocampus", "Amygdala", "Prefrontal Cortex"]
            }
        ],
        "metadata": {
            "completion_time_seconds": 180,
            "device_type": "desktop",
            "browser": "Chrome"
        }
    }

@pytest.fixture
def mock_ai_client():
    """Mock AI client for insight generation tests."""
    class MockAIClient:
        async def generate_insights(self, data):
            return {
                "summary": "Test insight summary",
                "key_findings": ["Finding 1", "Finding 2"],
                "recommendations": ["Recommendation 1"],
                "sentiment_score": 0.75
            }
    
    return MockAIClient()

@pytest.fixture
def mock_event_system():
    """Mock event system for trigger tests."""
    class MockEventSystem:
        def __init__(self):
            self.triggered_events = []
        
        def trigger(self, event_type, data):
            self.triggered_events.append({
                "type": event_type,
                "data": data,
                "timestamp": datetime.now()
            })
            return True
        
        def get_triggered_events(self):
            return self.triggered_events
    
    return MockEventSystem()

# Import datetime for mock fixtures
from datetime import datetime
