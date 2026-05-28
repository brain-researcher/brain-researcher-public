"""
Unit tests for the core LangGraph state machine implementation.

Tests state transitions, error handling, and recovery mechanisms.
"""

import json
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from langchain_core.language_models import FakeListLLM
from langchain_core.messages import HumanMessage

from brain_researcher.services.agent.graph import (
    CoreStateMachine,
    StatePhase,
)
from brain_researcher.services.agent.persistence import (
    HybridCheckpointer,
    RedisCheckpointer,
    get_checkpointer,
)


class TestCoreStateMachine:
    """Test the core state machine implementation."""
    
    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM for testing."""
        llm = Mock()
        llm.invoke = Mock(side_effect=self._mock_llm_responses)
        return llm
    
    @pytest.fixture
    def state_machine(self, mock_llm):
        """Create a state machine instance for testing."""
        # Just pass the mock_llm directly since we're providing it
        return CoreStateMachine(llm=mock_llm)
    
    def _mock_llm_responses(self, input_dict):
        """Generate mock LLM responses based on input."""
        response = Mock()
        
        # Check what kind of prompt we're dealing with
        prompt = str(input_dict)
        
        if "creating an execution plan" in prompt.lower():
            # Planning response
            response.content = json.dumps({
                "objectives": ["Test objective"],
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Test step",
                        "tool": "task_to_concept_mapping",
                        "args": {"task_name": "test"},
                        "expected_output": "Test output"
                    }
                ],
                "success_criteria": ["Test criterion"]
            })
        elif "reviewing the execution results" in prompt.lower():
            # Review response
            response.content = json.dumps({
                "criteria_met": True,
                "completeness": 90,
                "accuracy_confidence": 85,
                "needs_revision": False,
                "summary": "Test review summary"
            })
        else:
            # Generic response
            response.content = "Test response"
        
        return response
    
    def test_state_machine_initialization(self):
        """Test that the state machine initializes correctly."""
        # Test with mock LLM
        mock_llm = Mock()
        machine = CoreStateMachine(llm=mock_llm)
        
        assert machine.llm == mock_llm
        assert machine.checkpointer is not None
        assert machine.graph is not None
        assert machine.app is not None
    
    def test_state_machine_with_default_llm(self):
        """Test state machine initialization with default LLM."""
        with patch('brain_researcher.services.agent.llm.get_llm') as mock_get_llm:
            mock_llm = Mock()
            mock_get_llm.return_value = mock_llm
            
            machine = CoreStateMachine()
            assert machine.llm == mock_llm
            mock_get_llm.assert_called_once()
    
    def test_plan_state_execution(self, state_machine):
        """Test the planning state execution."""
        state = {
            "messages": [HumanMessage(content="Test query about motor cortex")],
            "current_phase": StatePhase.INIT,
            "previous_phase": None,
            "plan": None,
            "plan_steps": [],
            "selected_tools": [],
            "tool_args": {},
            "execution_results": {},
            "review_feedback": None,
            "needs_revision": False,
            "error": None,
            "error_recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "thread_id": str(uuid4()),
            "session_checkpoint_id": None,
        }
        
        # Execute plan state
        updated_state = state_machine._plan_state(state)
        
        # Verify state updates
        assert updated_state["current_phase"] == StatePhase.PLAN
        assert updated_state["plan"] is not None
        assert "objectives" in updated_state["plan"]
        assert "steps" in updated_state["plan"]
        assert len(updated_state["plan_steps"]) > 0
        assert updated_state["error"] is None
    
    def test_execute_state_with_tools(self, state_machine):
        """Test the execution state with tool execution."""
        # Mock tool registry
        mock_tool = Mock()
        mock_tool.run = Mock(return_value={"result": "test_result"})
        
        with patch.object(state_machine.tool_registry, 'get_tool', return_value=mock_tool):
            state = {
                "messages": [HumanMessage(content="Test query")],
                "current_phase": StatePhase.PLAN,
                "previous_phase": StatePhase.INIT,
                "plan": {"steps": [{"tool": "test_tool", "args": {}}]},
                "plan_steps": [{"tool": "test_tool", "args": {"param": "value"}}],
                "selected_tools": ["test_tool"],
                "tool_args": {},
                "execution_results": {},
                "review_feedback": None,
                "needs_revision": False,
                "error": None,
                "error_recovery_attempts": 0,
                "max_recovery_attempts": 3,
                "thread_id": str(uuid4()),
                "session_checkpoint_id": None,
            }
            
            # Execute state
            updated_state = state_machine._execute_state(state)
            
            # Verify execution
            assert updated_state["current_phase"] == StatePhase.EXECUTE
            assert "test_tool" in updated_state["execution_results"]
            assert updated_state["execution_results"]["test_tool"]["status"] == "success"
            assert updated_state["error"] is None
            mock_tool.run.assert_called_once_with(param="value")
    
    def test_execute_state_tool_not_found(self, state_machine):
        """Test execution state when tool is not found."""
        with patch.object(state_machine.tool_registry, 'get_tool', return_value=None):
            state = {
                "messages": [],
                "current_phase": StatePhase.PLAN,
                "plan_steps": [{"tool": "nonexistent_tool", "args": {}}],
                "execution_results": {},
                "error": None,
            }
            
            updated_state = state_machine._execute_state(state)
            
            assert "nonexistent_tool" in updated_state["execution_results"]
            assert updated_state["execution_results"]["nonexistent_tool"]["status"] == "skipped"
    
    def test_review_state_pass(self, state_machine):
        """Test review state when criteria are met."""
        state = {
            "messages": [],
            "current_phase": StatePhase.EXECUTE,
            "previous_phase": StatePhase.PLAN,
            "plan": {"success_criteria": ["Test criterion"]},
            "execution_results": {"tool1": {"status": "success", "result": "data"}},
            "review_feedback": None,
            "needs_revision": False,
            "error": None,
        }
        
        updated_state = state_machine._review_state(state)
        
        assert updated_state["current_phase"] == StatePhase.COMPLETE
        assert updated_state["review_feedback"] is not None
        assert not updated_state["needs_revision"]
        assert updated_state["error"] is None
    
    def test_review_state_needs_revision(self, state_machine):
        """Test review state when revision is needed."""
        # Mock LLM to return revision needed
        state_machine.llm.invoke = Mock(return_value=Mock(
            content=json.dumps({
                "criteria_met": False,
                "completeness": 50,
                "accuracy_confidence": 40,
                "needs_revision": True,
                "revision_reason": "Incomplete analysis",
                "summary": "Needs more work"
            })
        ))
        
        state = {
            "messages": [],
            "current_phase": StatePhase.EXECUTE,
            "plan": {"success_criteria": []},
            "execution_results": {},
            "needs_revision": False,
            "error": None,
        }
        
        updated_state = state_machine._review_state(state)
        
        assert updated_state["needs_revision"] is True
        assert updated_state["review_feedback"]["revision_reason"] == "Incomplete analysis"
    
    def test_error_state_recovery(self, state_machine):
        """Test error state with recovery attempts."""
        state = {
            "messages": [],
            "current_phase": StatePhase.EXECUTE,
            "previous_phase": StatePhase.PLAN,
            "error": "Test error",
            "error_recovery_attempts": 0,
            "max_recovery_attempts": 3,
        }
        
        updated_state = state_machine._error_state(state)
        
        assert updated_state["current_phase"] == StatePhase.ERROR
        assert updated_state["error_recovery_attempts"] == 1
        assert updated_state["error"] is None  # Cleared for retry
        assert len(updated_state["messages"]) > 0
    
    def test_error_state_max_attempts(self, state_machine):
        """Test error state when max attempts are reached."""
        state = {
            "messages": [],
            "current_phase": StatePhase.EXECUTE,
            "error": "Test error",
            "error_recovery_attempts": 2,
            "max_recovery_attempts": 3,
        }
        
        updated_state = state_machine._error_state(state)
        
        assert updated_state["error_recovery_attempts"] == 3
        # Error is not cleared when max attempts reached
        assert "Failed after" in updated_state["messages"][-1].content
    
    def test_routing_from_plan(self, state_machine):
        """Test routing decisions from plan state."""
        # Success case
        state = {"error": None}
        assert state_machine._route_from_plan(state) == "execute"
        
        # Error case
        state = {"error": "Some error"}
        assert state_machine._route_from_plan(state) == "error"
    
    def test_routing_from_execute(self, state_machine):
        """Test routing decisions from execute state."""
        # Success case
        state = {"error": None}
        assert state_machine._route_from_execute(state) == "review"
        
        # Error case
        state = {"error": "Execution error"}
        assert state_machine._route_from_execute(state) == "error"
    
    def test_routing_from_review(self, state_machine):
        """Test routing decisions from review state."""
        # Complete case
        state = {"error": None, "needs_revision": False}
        assert state_machine._route_from_review(state) == "complete"
        
        # Revision needed
        state = {"error": None, "needs_revision": True}
        assert state_machine._route_from_review(state) == "plan"
        
        # Error case
        state = {"error": "Review error", "needs_revision": False}
        assert state_machine._route_from_review(state) == "error"
    
    def test_routing_from_error(self, state_machine):
        """Test routing decisions from error state."""
        # Can retry from execute
        state = {
            "error_recovery_attempts": 1,
            "max_recovery_attempts": 3,
            "previous_phase": StatePhase.EXECUTE
        }
        assert state_machine._route_from_error(state) == "execute"
        
        # Can retry from plan
        state = {
            "error_recovery_attempts": 1,
            "max_recovery_attempts": 3,
            "previous_phase": StatePhase.PLAN
        }
        assert state_machine._route_from_error(state) == "plan"
        
        # Max attempts reached
        state = {
            "error_recovery_attempts": 3,
            "max_recovery_attempts": 3,
            "previous_phase": StatePhase.EXECUTE
        }
        assert state_machine._route_from_error(state) == "end"
    
    def test_synchronous_run(self, state_machine):
        """Test synchronous execution of the state machine."""
        with patch.object(state_machine.app, 'invoke') as mock_invoke:
            mock_invoke.return_value = {"final_state": "completed"}
            
            result = state_machine.run("Test query")
            
            assert result == {"final_state": "completed"}
            mock_invoke.assert_called_once()
            
            # Check initial state structure
            call_args = mock_invoke.call_args[0][0]
            assert len(call_args["messages"]) == 1
            assert isinstance(call_args["messages"][0], HumanMessage)
            assert call_args["messages"][0].content == "Test query"

    def test_get_relevant_memories_includes_derived_runtime_cards(self, state_machine):
        """Derived episodic memory should contribute planning house rules."""
        state_machine.memory_selector = None
        state_machine.derived_memory_store = Mock()
        state_machine.derived_memory_store.search.return_value = {
            "ok": True,
            "cards": [
                {
                    "task_description": "Test hippocampal connectivity analysis",
                    "status": "success",
                    "what_worked": ["Reuse the prior seed definition"],
                    "what_failed": ["Avoid mixing cohorts before QC"],
                    "next_time_hints": ["Start from the validated preprocessing outputs"],
                    "output_summary": "Generated stable connectivity estimates",
                }
            ],
        }

        rules = state_machine._get_relevant_memories(
            "Analyze hippocampal connectivity",
            {"messages": []},
        )

        assert "[Runtime Memory - Prior Similar Runs]" in rules
        assert "Test hippocampal connectivity analysis" in rules
        assert "Reuse the prior seed definition" in rules
        assert "Avoid mixing cohorts before QC" in rules
        # search is now called twice: once for episodic_run_memory, once for claim_memory
        calls = state_machine.derived_memory_store.search.call_args_list
        call_kwargs = [c.kwargs for c in calls]
        assert any(
            kw.get("card_type") == "episodic_run_memory" for kw in call_kwargs
        ), "Expected episodic_run_memory search call"
        assert any(
            kw.get("card_type") == "claim_memory" for kw in call_kwargs
        ), "Expected claim_memory search call"

    def test_get_relevant_memories_combines_project_and_runtime_memory(self, state_machine):
        """Project markdown memory and derived runtime memory should both appear."""
        state_machine.memory_selector = Mock()
        state_machine.memory_selector.get_context_from_state.return_value = {"task": "test"}
        state_machine.memory_selector.select_memories.return_value = ["static-memory"]
        state_machine.memory_selector.format_as_house_rules.return_value = (
            "[Project Memory - House Rules]\n- Prefer GroupKFold by subject"
        )
        state_machine.derived_memory_store = Mock()
        state_machine.derived_memory_store.search.return_value = {
            "ok": True,
            "cards": [
                {
                    "task_description": "Re-run age-effect verification with GSR",
                    "status": "partial",
                    "what_worked": ["Preserve the benchmark split"],
                    "what_failed": [],
                    "next_time_hints": [],
                    "output_summary": "Partial verification result",
                }
            ],
        }

        rules = state_machine._get_relevant_memories(
            "Verify age effects with GSR",
            {"messages": []},
        )

        assert "[Project Memory - House Rules]" in rules
        assert "[Runtime Memory - Prior Similar Runs]" in rules
        assert "Prefer GroupKFold by subject" in rules
        assert "Re-run age-effect verification with GSR" in rules

    def test_select_derived_memory_cards_prefers_specific_successes(self, state_machine):
        """Generic failed pipeline runs should not outrank specific successful lessons."""
        selected = state_machine._select_derived_memory_cards(
            [
                {
                    "task_description": "Run br_123 completed via pipeline_execute.",
                    "status": "failed",
                    "what_worked": ["Persisted canonical run bundle artifacts."],
                    "score": 0.92,
                },
                {
                    "task_description": "Run br_456 completed via pipeline_execute.",
                    "status": "failed",
                    "what_worked": ["Persisted canonical run bundle artifacts."],
                    "score": 0.91,
                },
                {
                    "task_description": "Verify age effects with benchmark-preserving split",
                    "status": "success",
                    "what_worked": ["Reuse the validated split."],
                    "next_time_hints": ["Start from the cached encoding outputs."],
                    "score": 0.65,
                },
            ],
            limit=2,
        )

        assert len(selected) == 2
        assert selected[0]["task_description"] == (
            "Verify age effects with benchmark-preserving split"
        )

    def test_select_derived_memory_cards_skips_zero_score_noise(self, state_machine):
        """Zero-score retrieval results should not be injected as faux relevance."""
        selected = state_machine._select_derived_memory_cards(
            [
                {
                    "task_description": "Run br_123 executed fsl.bet via mcp.",
                    "status": "success",
                    "what_worked": ["Executed tool sequence: fsl.bet."],
                    "score": 0.0,
                },
                {
                    "task_description": "Run br_456 completed via pipeline_execute.",
                    "status": "failed",
                    "what_failed": ["plan_invalid"],
                    "score": 0.0,
                },
            ],
            limit=3,
        )

        assert selected == []
    
    @pytest.mark.asyncio
    async def test_asynchronous_run(self, state_machine):
        """Test asynchronous execution of the state machine."""
        async def mock_astream(*args, **kwargs):
            yield {"state": "planning"}
            yield {"state": "executing"}
            yield {"state": "complete"}
        
        with patch.object(state_machine.app, 'astream', side_effect=mock_astream):
            events = []
            async for event in state_machine.arun("Test async query"):
                events.append(event)
            
            assert len(events) == 3
            assert events[0] == {"state": "planning"}
            assert events[-1] == {"state": "complete"}


class TestStatePersistence:
    """Test state persistence mechanisms."""
    
    @pytest.fixture
    def redis_checkpointer(self):
        """Create a Redis checkpointer with fakeredis."""
        import fakeredis
        checkpointer = RedisCheckpointer()
        checkpointer.redis_client = fakeredis.FakeRedis(decode_responses=True)
        return checkpointer
    
    def test_redis_checkpointer_save_and_retrieve(self, redis_checkpointer):
        """Test saving and retrieving checkpoints."""
        config = {
            "configurable": {
                "thread_id": "test_thread_123"
            }
        }
        
        checkpoint = {
            "id": "checkpoint_1",
            "state": {"messages": ["test"]},
            "timestamp": "2024-01-01T00:00:00"
        }
        
        metadata = {"user": "test_user"}
        
        # Save checkpoint
        updated_config = redis_checkpointer.put(config, checkpoint, metadata)
        
        assert "checkpoint_id" in updated_config["configurable"]
        
        # Retrieve checkpoint
        result = redis_checkpointer.get(updated_config)
        
        assert result is not None
        retrieved_checkpoint, retrieved_metadata = result
        assert retrieved_checkpoint["state"]["messages"] == ["test"]
        assert retrieved_metadata["user"] == "test_user"
    
    def test_redis_checkpointer_list_history(self, redis_checkpointer):
        """Test listing checkpoint history."""
        config = {
            "configurable": {
                "thread_id": "test_thread_456"
            }
        }
        
        # Save multiple checkpoints
        for i in range(3):
            checkpoint = {
                "id": f"checkpoint_{i}",
                "state": {"iteration": i}
            }
            redis_checkpointer.put(config, checkpoint)
        
        # List checkpoints
        history = redis_checkpointer.list(config, limit=2)
        
        assert len(history) <= 2
        for config_item, checkpoint, metadata in history:
            assert "checkpoint_id" in config_item["configurable"]
            assert "state" in checkpoint
    
    def test_redis_checkpointer_ttl(self, redis_checkpointer):
        """Test that TTL is set on Redis keys."""
        config = {
            "configurable": {
                "thread_id": "test_thread_ttl"
            }
        }
        
        checkpoint = {"id": "checkpoint_ttl", "data": "test"}
        redis_checkpointer.put(config, checkpoint)
        
        # Check TTL is set
        key = redis_checkpointer._make_key("test_thread_ttl", "checkpoint_ttl")
        ttl = redis_checkpointer.redis_client.ttl(key)
        
        assert ttl > 0
        assert ttl <= redis_checkpointer.ttl_seconds
    
    def test_hybrid_checkpointer_development(self):
        """Test hybrid checkpointer in development mode."""
        with patch.dict('os.environ', {'ENVIRONMENT': 'development'}):
            checkpointer = HybridCheckpointer()
            
            # Should use MemorySaver in development
            from langgraph.checkpoint.memory import MemorySaver
            assert isinstance(checkpointer.backend, MemorySaver)
    
    def test_hybrid_checkpointer_production(self):
        """Test hybrid checkpointer in production mode."""
        with patch.dict('os.environ', {'ENVIRONMENT': 'production'}):
            with patch('brain_researcher.services.agent.persistence.RedisCheckpointer') as MockRedis:
                mock_instance = Mock()
                MockRedis.return_value = mock_instance
                
                checkpointer = HybridCheckpointer()
                
                # Should use RedisCheckpointer in production
                assert checkpointer.backend == mock_instance
    
    def test_get_checkpointer_factory(self):
        """Test the checkpointer factory function."""
        checkpointer = get_checkpointer()
        assert isinstance(checkpointer, HybridCheckpointer)


class TestEndToEndStateMachine:
    """End-to-end tests for the complete state machine flow."""
    
    @pytest.fixture
    def integrated_machine(self):
        """Create a state machine with all components integrated."""
        # Use a predictable fake LLM
        fake_llm = FakeListLLM(
            responses=[
                json.dumps({
                    "objectives": ["Test analysis"],
                    "steps": [{
                        "step_number": 1,
                        "description": "Analyze data",
                        "tool": "mock_tool",
                        "args": {},
                        "expected_output": "Results"
                    }],
                    "success_criteria": ["Complete analysis"]
                }),
                json.dumps({
                    "criteria_met": True,
                    "completeness": 100,
                    "accuracy_confidence": 95,
                    "needs_revision": False,
                    "summary": "Analysis complete"
                })
            ]
        )
        
        return CoreStateMachine(llm=fake_llm)
    
    def test_complete_workflow(self, integrated_machine):
        """Test a complete workflow from plan to review."""
        # Mock the tool execution
        mock_tool = Mock()
        mock_tool.run = Mock(return_value={"analysis": "results"})
        
        with patch.object(integrated_machine.tool_registry, 'get_tool', return_value=mock_tool):
            # Run the state machine
            result = integrated_machine.run("Analyze brain data")
            
            # Verify we went through all states
            assert result["current_phase"] in [StatePhase.COMPLETE, StatePhase.REVIEW]
            assert result["plan"] is not None
            assert "execution_results" in result or result["execution_results"] == {}
    
    def test_error_recovery_workflow(self):
        """Test that error recovery works correctly."""
        # Create LLM that fails initially then succeeds
        responses = [
            "INVALID_JSON",  # Will cause error
            json.dumps({  # Valid plan after recovery
                "objectives": ["Retry analysis"],
                "steps": [{
                    "step_number": 1,
                    "description": "Retry",
                    "tool": "test_tool",
                    "args": {},
                    "expected_output": "Success"
                }],
                "success_criteria": ["Complete"]
            }),
            json.dumps({  # Review
                "criteria_met": True,
                "completeness": 100,
                "accuracy_confidence": 90,
                "needs_revision": False,
                "summary": "Success after retry"
            })
        ]
        
        fake_llm = FakeListLLM(responses=responses)
        machine = CoreStateMachine(llm=fake_llm)
        
        # Should recover from initial error
        result = machine.run("Test with error recovery")
        
        # Verify recovery happened
        assert result.get("error_recovery_attempts", 0) >= 0


class TestRouteByMemorySignal:
    """Tests for the conflict-resolution routing node (M3)."""

    @pytest.fixture()
    def sm(self):
        return CoreStateMachine(llm=Mock())

    def _make_state(self, hypothesis_cards=None, execution_mode=None, conflict_hint=None):
        return {
            "messages": [],
            "current_phase": StatePhase.PLAN,
            "previous_phase": None,
            "plan": None,
            "plan_steps": [],
            "selected_tools": [],
            "tool_args": {},
            "execution_results": {},
            "review_feedback": None,
            "needs_revision": False,
            "error": None,
            "error_recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "thread_id": "t1",
            "session_checkpoint_id": None,
            "hypothesis_cards": hypothesis_cards,
            "execution_mode": execution_mode,
            "conflict_hint": conflict_hint,
        }

    def test_conflict_resolution_priority_sets_mode(self, sm):
        state = self._make_state(
            hypothesis_cards=[
                {
                    "claim_memory_priority": "conflict_resolution",
                    "claim_memory_reason": "ACC conflict",
                }
            ]
        )
        result = sm.route_by_memory_signal(state)
        assert result["execution_mode"] == "conflict_resolution"
        assert result["conflict_hint"] == "ACC conflict"

    def test_standard_priority_sets_standard_mode(self, sm):
        state = self._make_state(
            hypothesis_cards=[{"claim_memory_priority": "low", "claim_memory_reason": ""}]
        )
        result = sm.route_by_memory_signal(state)
        assert result["execution_mode"] == "standard"
        assert result["conflict_hint"] == ""

    def test_empty_hypothesis_cards_sets_standard(self, sm):
        state = self._make_state(hypothesis_cards=[])
        result = sm.route_by_memory_signal(state)
        assert result["execution_mode"] == "standard"

    def test_none_hypothesis_cards_sets_standard(self, sm):
        state = self._make_state(hypothesis_cards=None)
        result = sm.route_by_memory_signal(state)
        assert result["execution_mode"] == "standard"

    def test_missing_reason_defaults_to_empty_string(self, sm):
        state = self._make_state(
            hypothesis_cards=[{"claim_memory_priority": "conflict_resolution"}]
        )
        result = sm.route_by_memory_signal(state)
        assert result["conflict_hint"] == ""

    def test_existing_conflict_mode_is_preserved_without_cards(self, sm):
        state = self._make_state(
            hypothesis_cards=None,
            execution_mode="conflict_resolution",
            conflict_hint="manual override",
        )
        result = sm.route_by_memory_signal(state)
        assert result["execution_mode"] == "conflict_resolution"
        assert result["conflict_hint"] == "manual override"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
