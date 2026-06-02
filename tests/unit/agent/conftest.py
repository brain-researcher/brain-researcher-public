"""
Shared test fixtures for agent_langgraph tests.
"""

import os
import sys

# Add parent directory to path for br_kg imports
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Silence noisy third-party warnings that are not actionable for unit tests
import warnings
from unittest.mock import Mock

import pytest

warnings.filterwarnings(
    "ignore",
    message="builtin type SwigPy.* has no __module__ attribute",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message="Skipping collection of '.hypothesis' directory",
    category=UserWarning,
)
from langchain_core.messages import AIMessage, HumanMessage

from brain_researcher.services.agent.states.base import NeuroAgentState, ResearchState
from brain_researcher.services.tools.tool_base import BRKGToolWrapper


# Mock API responses
@pytest.fixture
def mock_fmri_api():
    """Mock fMRI foundation model API responses."""
    mock = Mock()

    # GLM analysis response
    mock.run_glm_analysis.return_value = {
        "status": "success",
        "contrasts": {
            "motor_vs_rest": {
                "z_map": "/data/results/motor_zmap.nii.gz",
                "peak_coordinates": [[-42, -22, 54], [42, -22, 54]],
                "cluster_count": 5,
                "peak_z_scores": [5.2, 4.8],
            }
        },
        "dataset_id": "ds000001",
    }

    # Encoding model response
    mock.run_encoding_model.return_value = {
        "status": "success",
        "r2_scores": {
            "mean": 0.72,
            "std": 0.15,
            "by_region": {
                "visual_cortex": 0.85,
                "motor_cortex": 0.68,
                "frontal_cortex": 0.55,
            },
        },
        "model_path": "/data/models/encoding_model.pkl",
    }

    # Contrast analysis response
    mock.analyze_contrast.return_value = {
        "status": "success",
        "significant_clusters": [
            {
                "peak_coordinate": [-42, -22, 54],
                "cluster_size": 125,
                "peak_z": 5.2,
                "region": "Left Primary Motor Cortex",
            }
        ],
        "cognitive_interpretation": "Strong motor activation consistent with finger tapping task",
    }

    return mock


@pytest.fixture
def mock_br_kg_api():
    """Mock BR-KG API responses."""
    mock = Mock()

    # Subgraph query response
    mock.get_subgraph.return_value = {
        "nodes": [
            {"id": "1", "label": "Concept", "name": "motor cortex"},
            {"id": "2", "label": "Task", "name": "finger tapping"},
            {"id": "3", "label": "Concept", "name": "movement"},
            {
                "id": "4",
                "label": "Study",
                "pmid": "12345",
                "title": "Motor cortex activation study",
            },
        ],
        "edges": [
            {"source": "1", "target": "2", "type": "involves", "weight": 0.9},
            {"source": "1", "target": "3", "type": "related_to", "weight": 0.85},
            {"source": "1", "target": "4", "type": "studied_in", "weight": 0.7},
        ],
    }

    # Coordinate to concept mapping
    mock.find_concepts_by_coordinates.return_value = [
        {"concept": "motor cortex", "confidence": 0.92},
        {"concept": "primary motor area", "confidence": 0.88},
        {"concept": "movement execution", "confidence": 0.75},
    ]

    # Literature search response
    mock.search_literature.return_value = [
        {
            "pmid": "12345",
            "title": "Motor cortex activation during finger tapping",
            "year": 2023,
            "authors": ["Smith J", "Doe A"],
            "abstract": "Study of motor cortex activation...",
        },
        {
            "pmid": "67890",
            "title": "Neural basis of motor control",
            "year": 2022,
            "authors": ["Johnson K", "Lee M"],
        },
    ]

    return mock


@pytest.fixture
def sample_messages():
    """Sample conversation messages for testing."""
    return [
        HumanMessage(content="Analyze motor task activation in dataset ds000001"),
        AIMessage(
            content="I'll analyze the motor task activation for you. Let me start by running a GLM analysis."
        ),
        HumanMessage(content="What brain regions are most active?"),
        AIMessage(
            content="Based on the analysis, the primary motor cortex shows the strongest activation."
        ),
    ]


@pytest.fixture
def sample_neuro_state():
    """Sample NeuroAgentState for testing."""
    return NeuroAgentState(
        messages=[HumanMessage(content="Test query")],
        current_phase="planning",
        selected_tools=["glm_analysis", "coordinate_to_concept"],
        tool_args={
            "glm_analysis": {
                "dataset_id": "ds000001",
                "contrasts": {"motor_vs_rest": [1, -1]},
            }
        },
        results=None,
        error=None,
    )


@pytest.fixture
def sample_research_state():
    """Sample ResearchState for complex workflows."""
    return ResearchState(
        messages=[HumanMessage(content="Comprehensive analysis request")],
        current_phase="analysis",
        selected_tools=["glm_analysis", "find_related_concepts"],
        dataset_id="ds000001",
        analysis_type="glm",
        analysis_results={
            "glm": {"contrasts": {"motor": [1, -1]}, "peaks": [[-42, -22, 54]]}
        },
        coordinates=[[-42, -22, 54], [42, -22, 54]],
        concepts=["motor cortex", "movement"],
        concept_relationships={
            "motor cortex": ["movement", "motor control"],
            "movement": ["motor cortex", "action"],
        },
        literature_findings=[
            {"pmid": "12345", "title": "Motor study", "relevance": 0.9}
        ],
        synthesis={"summary": "Motor cortex activation identified", "confidence": 0.85},
        confidence_scores={"motor_activation": 0.92},
    )


@pytest.fixture
def mock_tool_registry():
    """Mock tool registry with common tools."""
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    registry = Mock(spec=ToolRegistry)

    # Create mock tools
    glm_tool = Mock()
    glm_tool.get_tool_name.return_value = "glm_analysis"
    glm_tool.get_tool_description.return_value = "Run GLM analysis"
    glm_tool.run.return_value = {
        "status": "success",
        "data": {"dataset_id": "ds000001", "n_contrasts": 1},
    }

    concept_tool = Mock()
    concept_tool.get_tool_name.return_value = "find_related_concepts"
    concept_tool.get_tool_description.return_value = "Find related concepts"
    concept_tool.run.return_value = {
        "status": "success",
        "data": {"concepts": ["motor cortex", "movement"]},
    }

    # Registry methods
    registry.get_tool.side_effect = lambda name: {
        "glm_analysis": glm_tool,
        "find_related_concepts": concept_tool,
    }.get(name)

    registry.get_all_tools.return_value = [glm_tool, concept_tool]
    registry.get_tools_for_task.return_value = [glm_tool]

    return registry


@pytest.fixture
def mock_langchain_llm():
    """Mock LangChain LLM for testing agent reasoning."""
    llm = Mock()

    # Mock responses for different prompts
    def mock_invoke(prompt):
        if "analyze" in prompt.lower():
            return "Based on the query, I should run GLM analysis followed by concept mapping."
        elif "tools" in prompt.lower():
            return "The appropriate tools are: glm_analysis, coordinate_to_concept"
        else:
            return "I'll help you with that analysis."

    llm.invoke.side_effect = mock_invoke
    return llm


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary directory structure for test data."""
    # Create subdirectories
    (tmp_path / "results").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "cache").mkdir()

    # Create sample files
    (tmp_path / "results" / "test_zmap.nii.gz").touch()
    (tmp_path / "models" / "test_model.pkl").touch()

    return tmp_path


@pytest.fixture
def mock_requests_success():
    """Mock successful HTTP requests."""
    import responses

    with responses.RequestsMock() as rsps:
        # Mock BR-KG API endpoints
        rsps.add(
            responses.GET,
            "http://localhost:5000/subgraph",
            json={
                "nodes": [{"id": "1", "label": "Concept", "name": "test_concept"}],
                "edges": [],
            },
            status=200,
        )

        rsps.add(
            responses.GET,
            "http://localhost:5000/health",
            json={"status": "healthy"},
            status=200,
        )

        yield rsps


@pytest.fixture
def mock_redis_client():
    """Mock Redis client for memory/caching tests."""
    import fakeredis

    # Use fakeredis for testing
    client = fakeredis.FakeRedis()
    return client


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")
    config.addinivalue_line(
        "markers", "requires_api: marks tests that require API access"
    )


# Utility functions for tests
def create_mock_tool(name: str, description: str, success: bool = True) -> Mock:
    """Create a mock tool for testing."""
    tool = Mock(spec=BRKGToolWrapper)
    tool.get_tool_name.return_value = name
    tool.get_tool_description.return_value = description

    if success:
        tool.run.return_value = {
            "status": "success",
            "data": {"tool": name, "result": "mock_result"},
        }
    else:
        tool.run.return_value = {"status": "error", "error": f"Mock error from {name}"}

    return tool


def create_test_state(**kwargs) -> NeuroAgentState:
    """Create a test state with default values."""
    defaults = {
        "messages": [HumanMessage(content="Test message")],
        "current_phase": "init",
        "selected_tools": [],
        "tool_args": None,
        "results": None,
        "error": None,
    }
    defaults.update(kwargs)
    return NeuroAgentState(**defaults)
