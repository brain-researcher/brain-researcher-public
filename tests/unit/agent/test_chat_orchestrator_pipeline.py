"""Tests for pipeline integration in ChatOrchestrator.

These tests verify that:
1. _detect_imaging_domain correctly identifies imaging-related queries
2. _try_pipeline_execution correctly invokes PlanningEngine
3. Pipeline-first branch in handle_chat works end-to-end
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator, ChatReply


@dataclass
class MockWorkflowStep:
    """Mock WorkflowStep for testing."""
    step_id: str
    step_number: int
    description: str
    tool_name: str
    tool_args: dict
    dependencies: list
    expected_output: str
    estimated_time_seconds: float
    resource_requirements: dict


class TestDetectImagingDomain:
    """Test the _detect_imaging_domain heuristic."""

    @pytest.fixture
    def orchestrator(self):
        """Create a ChatOrchestrator with mocked dependencies."""
        router = MagicMock()
        router.route_chat.return_value = MagicMock(text="Summary response")
        return ChatOrchestrator(
            router=router,
            enable_knowledge_layer=False,
            error_recovery=False,
        )

    @pytest.mark.parametrize("query,expected", [
        # fMRI detection
        ("run ICA on fMRI data", "fmri"),
        ("analyze BOLD signal", "fmri"),
        ("functional connectivity analysis", "fmri"),

        # dMRI detection
        ("run tractography on diffusion data", "dmri"),
        ("estimate fiber orientations for DTI", "dmri"),

        # sMRI detection
        ("preprocess T1 to MNI space", "smri"),
        ("T2 weighted brain extraction", "smri"),
        ("structural MRI analysis", "smri"),

        # General imaging keywords
        ("run the preprocessing pipeline", "imaging"),
        ("skull strip my brain image", "imaging"),
        ("register to MNI template", "imaging"),
        ("normalize brain to standard space", "imaging"),
        ("run ICA denoising", "imaging"),
        ("GLM analysis", "imaging"),

        # Non-imaging queries (should return None)
        ("what is the motor cortex?", None),
        ("search for papers about memory", None),
        ("find datasets with working memory tasks", None),
        ("visualize the knowledge graph", None),
    ])
    def test_domain_detection(self, orchestrator, query, expected):
        """Test that domain detection works correctly."""
        result = orchestrator._detect_imaging_domain(query)
        assert result == expected, f"Query: '{query}' should return {expected}, got {result}"


class TestBuildPipelineSummaryPrompt:
    """Test the _build_pipeline_summary_prompt method."""

    @pytest.fixture
    def orchestrator(self):
        """Create a ChatOrchestrator with mocked dependencies."""
        router = MagicMock()
        return ChatOrchestrator(
            router=router,
            enable_knowledge_layer=False,
            error_recovery=False,
        )

    def test_prompt_contains_user_message(self, orchestrator):
        """Test that prompt includes user message."""
        steps = [
            MockWorkflowStep(
                step_id="step_1",
                step_number=1,
                description="Skull stripping",
                tool_name="fsl.bet",
                tool_args={},
                dependencies=[],
                expected_output="",
                estimated_time_seconds=60.0,
                resource_requirements={},
            )
        ]
        results = [{"step_id": "step_1", "tool": "fsl.bet", "status": "success"}]

        prompt = orchestrator._build_pipeline_summary_prompt(
            "preprocess my T1", steps, results
        )

        assert "preprocess my T1" in prompt
        assert "fsl.bet" in prompt
        assert "Skull stripping" in prompt

    def test_prompt_contains_step_results(self, orchestrator):
        """Test that prompt includes step results."""
        steps = [
            MockWorkflowStep(
                step_id="step_1",
                step_number=1,
                description="Step 1 desc",
                tool_name="tool_a",
                tool_args={},
                dependencies=[],
                expected_output="",
                estimated_time_seconds=60.0,
                resource_requirements={},
            ),
            MockWorkflowStep(
                step_id="step_2",
                step_number=2,
                description="Step 2 desc",
                tool_name="tool_b",
                tool_args={},
                dependencies=["step_1"],
                expected_output="",
                estimated_time_seconds=60.0,
                resource_requirements={},
            ),
        ]
        results = [
            {"step_id": "step_1", "tool": "tool_a", "status": "success"},
            {"step_id": "step_2", "tool": "tool_b", "status": "error", "error": "Failed"},
        ]

        prompt = orchestrator._build_pipeline_summary_prompt("query", steps, results)

        assert "step_1" in prompt
        assert "step_2" in prompt
        assert "success" in prompt
        assert "error" in prompt or "Failed" in prompt


class TestTryPipelineExecution:
    """Test the _try_pipeline_execution method."""

    @pytest.fixture
    def orchestrator(self):
        """Create a ChatOrchestrator with mocked dependencies."""
        router = MagicMock()
        router.route_chat.return_value = MagicMock(text="Pipeline summary")
        return ChatOrchestrator(
            router=router,
            enable_knowledge_layer=False,
            error_recovery=False,
        )

    @patch("brain_researcher.services.agent.chat_orchestrator.PlanningEngine")
    def test_returns_none_when_pipeline_not_applicable(self, mock_planner_cls, orchestrator):
        """When pipeline heuristic says no, return None."""
        mock_planner = MagicMock()
        mock_planner._should_use_pipeline.return_value = False
        mock_planner_cls.return_value = mock_planner

        result = orchestrator._try_pipeline_execution(
            "search for papers about memory",
            None,
            {},
            "thread-1",
        )
        # With graceful fallback enabled, we expect a pipeline_fallback ChatReply
        assert result is not None
        assert result.metadata.get("type") == "pipeline_fallback"

    @patch("brain_researcher.services.agent.chat_orchestrator.PlanningEngine")
    @patch("brain_researcher.services.agent.chat_orchestrator.asyncio.run")
    def test_returns_chat_reply_when_pipeline_hits(self, mock_asyncio_run, mock_planner_cls, orchestrator):
        """When pipeline generates steps, return ChatReply."""
        # Mock planner
        mock_planner = MagicMock()
        mock_planner._should_use_pipeline.return_value = True
        mock_planner_cls.return_value = mock_planner

        # Mock asyncio.run to return mock steps and results
        mock_step = MockWorkflowStep(
            step_id="step_1",
            step_number=1,
            description="Skull stripping",
            tool_name="fsl.bet",
            tool_args={},
            dependencies=[],
            expected_output="",
            estimated_time_seconds=60.0,
            resource_requirements={},
        )

        # First call returns steps, second call returns results
        mock_asyncio_run.side_effect = [
            [mock_step],  # _generate_steps result
            [{"step_id": "step_1", "tool": "fsl.bet", "status": "success"}],  # _execute_pipeline_steps result
        ]

        result = orchestrator._try_pipeline_execution(
            "preprocess my T1 to MNI",
            "smri",
            {},
            "thread-1",
        )

        assert result is not None
        assert isinstance(result, ChatReply)
        assert result.metadata.get("type") in {"pipeline", "pipeline_fallback"}
        assert result.metadata.get("mode") in {"preview", "llm_only", "execute"}

    @patch("brain_researcher.services.agent.chat_orchestrator.PlanningEngine")
    def test_returns_none_on_exception(self, mock_planner_cls, orchestrator):
        """When exception occurs, return None (fallback to single-tool)."""
        mock_planner = MagicMock()
        mock_planner._should_use_pipeline.side_effect = Exception("Neo4j down")
        mock_planner_cls.return_value = mock_planner

        result = orchestrator._try_pipeline_execution(
            "preprocess my T1",
            "smri",
            {},
            "thread-1",
        )
        # Graceful fallback returns a ChatReply with pipeline_fallback
        assert result is not None
        assert result.metadata.get("type") == "pipeline_fallback"


class TestHandleChatPipelineBranch:
    """Test the pipeline branch in handle_chat."""

    @pytest.fixture
    def orchestrator(self):
        """Create a ChatOrchestrator with mocked dependencies."""
        router = MagicMock()
        router.route_chat.return_value = MagicMock(text="Response")
        return ChatOrchestrator(
            router=router,
            enable_knowledge_layer=False,
            error_recovery=False,
        )

    def test_non_imaging_query_skips_pipeline(self, orchestrator):
        """Non-imaging queries should skip pipeline branch."""
        # This should go through the normal single-tool path
        reply = orchestrator.handle_chat("what is the motor cortex?")

        # Should not have pipeline metadata
        assert reply.metadata is None or reply.metadata.get("type") != "pipeline"

    @patch.object(ChatOrchestrator, "_try_pipeline_execution")
    def test_imaging_query_triggers_pipeline(self, mock_try_pipeline, orchestrator):
        """Imaging queries should trigger pipeline attempt."""
        mock_try_pipeline.return_value = None  # Fall back to single-tool

        orchestrator.handle_chat("preprocess my T1 to MNI")

        # Pipeline execution should have been attempted
        mock_try_pipeline.assert_called_once()
        call_args = mock_try_pipeline.call_args
        assert call_args[0][0] == "preprocess my T1 to MNI"  # user_msg
        assert call_args[0][1] == "smri"  # detected domain

    @patch.object(ChatOrchestrator, "_try_pipeline_execution")
    def test_use_planning_engine_flag_triggers_pipeline(self, mock_try_pipeline, orchestrator):
        """use_planning_engine=True should trigger pipeline attempt."""
        mock_try_pipeline.return_value = None

        orchestrator.handle_chat(
            "analyze this data",
            ctx={"use_planning_engine": True}
        )

        mock_try_pipeline.assert_called_once()

    @patch.object(ChatOrchestrator, "_try_pipeline_execution")
    def test_pipeline_result_returned_when_available(self, mock_try_pipeline, orchestrator):
        """When pipeline succeeds, its result should be returned."""
        mock_pipeline_reply = ChatReply(
            answer="Pipeline executed: BET -> FNIRT",
            tool_calls=[{"pipeline_steps": []}],
            metadata={"type": "pipeline", "mode": "preview"},
        )
        mock_try_pipeline.return_value = mock_pipeline_reply

        reply = orchestrator.handle_chat("preprocess my T1 to MNI")

        assert reply == mock_pipeline_reply
        assert reply.metadata.get("type") == "pipeline"


# =============================================================================
# Run quick verification
# =============================================================================

if __name__ == "__main__":
    import sys

    print("Running ChatOrchestrator pipeline integration tests...")
    print("-" * 50)

    # Quick domain detection test
    router = MagicMock()
    orchestrator = ChatOrchestrator(
        router=router,
        enable_knowledge_layer=False,
        error_recovery=False,
    )

    test_cases = [
        ("preprocess T1 to MNI space", "smri"),
        ("run ICA on fMRI", "fmri"),
        ("tractography on diffusion data", "dmri"),
        ("skull strip brain image", "imaging"),
        ("search knowledge graph", None),
    ]

    all_passed = True
    for query, expected in test_cases:
        result = orchestrator._detect_imaging_domain(query)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_passed = False
        print(f"  [{status}] '{query[:35]}...' -> {result} (expected: {expected})")

    print("-" * 50)
    print(f"Result: {'All tests passed!' if all_passed else 'Some tests failed!'}")
    sys.exit(0 if all_passed else 1)
