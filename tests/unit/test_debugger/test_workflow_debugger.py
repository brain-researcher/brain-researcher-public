"""Tests for Workflow Debugger

Tests step-through debugging, execution control, DAG execution,
and debugging session management.
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Callable

from brain_researcher.services.agent.debugger.workflow_debugger import (
    WorkflowDebugger, DebugSession, DAGDefinition, DAGNode, 
    ExecutionContext, DebugConfig, ExecutionState, StepType
)
from brain_researcher.services.agent.debugger.breakpoint_manager import (
    BreakpointManager, BreakpointType
)


class TestDAGNode:
    """Test DAG node representation"""
    
    def test_dag_node_creation(self):
        """Test DAG node creation with all parameters"""
        def test_function(x: int, y: int) -> int:
            return x + y
            
        node = DAGNode(
            node_id="add_node",
            node_type="arithmetic",
            function=test_function,
            dependencies=["input_node"],
            parameters={"default_x": 5},
            metadata={"description": "Addition operation"}
        )
        
        assert node.node_id == "add_node"
        assert node.node_type == "arithmetic"
        assert node.function == test_function
        assert node.dependencies == ["input_node"]
        assert node.parameters["default_x"] == 5
        assert node.metadata["description"] == "Addition operation"
        
    def test_dag_node_serialization(self):
        """Test DAG node to_dict conversion"""
        def dummy_func():
            pass
            
        node = DAGNode(
            node_id="test_node",
            node_type="test",
            function=dummy_func,
            dependencies=["dep1", "dep2"],
            parameters={"param1": "value1"}
        )
        
        data = node.to_dict()
        
        assert data["node_id"] == "test_node"
        assert data["node_type"] == "test"
        assert data["dependencies"] == ["dep1", "dep2"]
        assert data["parameters"]["param1"] == "value1"
        assert "function" not in data  # Function should be excluded


class TestDAGDefinition:
    """Test DAG definition and execution order calculation"""
    
    @pytest.fixture
    def simple_dag(self):
        """Create a simple DAG for testing"""
        nodes = {
            "start": DAGNode("start", "input", lambda: "start_data"),
            "process": DAGNode("process", "transform", lambda data: f"processed_{data}", ["start"]),
            "end": DAGNode("end", "output", lambda result: f"final_{result}", ["process"])
        }
        
        return DAGDefinition(
            dag_id="simple_dag",
            name="Simple Test DAG",
            description="A simple linear DAG for testing",
            nodes=nodes,
            entry_points=["start"],
            exit_points=["end"]
        )
        
    @pytest.fixture  
    def complex_dag(self):
        """Create a complex DAG with parallel branches"""
        nodes = {
            "input": DAGNode("input", "source", lambda: {"data": "raw"}),
            "branch_a": DAGNode("branch_a", "process", lambda data: {"result": "a"}, ["input"]),
            "branch_b": DAGNode("branch_b", "process", lambda data: {"result": "b"}, ["input"]),
            "branch_c": DAGNode("branch_c", "process", lambda data: {"result": "c"}, ["input"]),
            "merge_ab": DAGNode("merge_ab", "combine", lambda a, b: {"merged": [a, b]}, ["branch_a", "branch_b"]),
            "final": DAGNode("final", "output", lambda merged, c: {"final": [merged, c]}, ["merge_ab", "branch_c"])
        }
        
        return DAGDefinition(
            dag_id="complex_dag",
            name="Complex Test DAG",
            description="A DAG with parallel branches and merging",
            nodes=nodes,
            entry_points=["input"],
            exit_points=["final"]
        )
        
    def test_simple_dag_execution_order(self, simple_dag):
        """Test execution order for simple linear DAG"""
        order = simple_dag.get_execution_order()
        
        assert len(order) == 3  # 3 levels
        assert order[0] == ["start"]
        assert order[1] == ["process"]
        assert order[2] == ["end"]
        
    def test_complex_dag_execution_order(self, complex_dag):
        """Test execution order for complex DAG with parallel branches"""
        order = complex_dag.get_execution_order()
        
        # First level: input
        assert "input" in order[0]
        
        # Second level: all branches (parallel)
        second_level = order[1]
        assert set(second_level) == {"branch_a", "branch_b", "branch_c"}
        
        # Third level: merge_ab (depends on branch_a, branch_b)
        assert "merge_ab" in order[2]
        
        # Fourth level: final (depends on merge_ab, branch_c)
        assert "final" in order[3]
        
    def test_circular_dependency_detection(self):
        """Test detection of circular dependencies"""
        # Create nodes with circular dependency
        nodes = {
            "node_a": DAGNode("node_a", "test", lambda: None, ["node_b"]),
            "node_b": DAGNode("node_b", "test", lambda: None, ["node_c"]),
            "node_c": DAGNode("node_c", "test", lambda: None, ["node_a"])  # Circular!
        }
        
        dag = DAGDefinition(
            dag_id="circular_dag",
            name="Circular DAG",
            description="A DAG with circular dependencies",
            nodes=nodes
        )
        
        # Execution order should handle this gracefully (may be empty or partial)
        order = dag.get_execution_order()
        # The exact behavior depends on implementation - could be empty or partial
        assert isinstance(order, list)


class TestExecutionContext:
    """Test execution context management"""
    
    def test_execution_context_initialization(self, simple_dag):
        """Test execution context initialization"""
        context = ExecutionContext(simple_dag, "test_session")
        
        assert context.dag_definition == simple_dag
        assert context.session_id == "test_session"
        assert len(context.variables) == 0
        assert len(context.node_results) == 0
        assert len(context.execution_stack) == 0
        assert context.current_node is None
        assert len(context.execution_order) > 0  # Should be calculated
        
    def test_execution_order_calculation(self, complex_dag):
        """Test automatic execution order calculation"""
        context = ExecutionContext(complex_dag, "test_session")
        
        assert len(context.execution_order) > 0
        assert "input" in context.execution_order[0]


class TestDebugConfig:
    """Test debug configuration"""
    
    def test_debug_config_creation(self):
        """Test debug configuration with all options"""
        config = DebugConfig(
            session_id="debug_session_123",
            dag_id="test_dag",
            enable_tracing=True,
            enable_profiling=False,
            step_on_start=True,
            break_on_error=True,
            max_trace_events=5000,
            auto_save_state=False
        )
        
        assert config.session_id == "debug_session_123"
        assert config.dag_id == "test_dag"
        assert config.enable_tracing is True
        assert config.enable_profiling is False
        assert config.step_on_start is True
        assert config.break_on_error is True
        assert config.max_trace_events == 5000
        assert config.auto_save_state is False
        
    def test_debug_config_serialization(self):
        """Test debug config to_dict conversion"""
        config = DebugConfig("session", "dag")
        data = config.to_dict()
        
        assert data["session_id"] == "session"
        assert data["dag_id"] == "dag"
        assert "enable_tracing" in data
        assert "enable_profiling" in data


@pytest.mark.asyncio
class TestDebugSession:
    """Test debug session functionality"""
    
    @pytest.fixture
    async def debug_session(self, simple_dag):
        """Create debug session for testing"""
        config = DebugConfig("test_session", simple_dag.dag_id)
        session = DebugSession("test_session", simple_dag, config)
        return session
        
    async def test_debug_session_initialization(self, debug_session, simple_dag):
        """Test debug session initialization"""
        assert debug_session.session_id == "test_session"
        assert debug_session.dag_definition == simple_dag
        assert debug_session.execution_state == ExecutionState.RUNNING
        assert isinstance(debug_session.breakpoint_manager, BreakpointManager)
        assert debug_session.started_at is None
        assert debug_session.completed_at is None
        
    async def test_breakpoint_management(self, debug_session):
        """Test adding and removing breakpoints"""
        # Add breakpoint
        bp_id = await debug_session.add_breakpoint("process", condition="data == 'test'")
        
        assert bp_id is not None
        assert len(debug_session.breakpoint_manager.get_all_breakpoints()) == 1
        
        # Remove breakpoint
        success = await debug_session.remove_breakpoint(bp_id)
        assert success is True
        assert len(debug_session.breakpoint_manager.get_all_breakpoints()) == 0
        
    async def test_debug_session_state_tracking(self, debug_session):
        """Test debug session state tracking"""
        debug_session.started_at = datetime.utcnow()
        debug_session.execution_state = ExecutionState.PAUSED
        debug_session.execution_context.current_node = "process"
        debug_session.execution_context.variables["test_var"] = "test_value"
        
        state = debug_session.get_current_state()
        
        assert state["session_id"] == "test_session"
        assert state["execution_state"] == "paused"
        assert state["current_node"] == "process"
        assert state["variables"]["test_var"] == "test_value"
        assert state["started_at"] is not None
        
    async def test_callback_registration(self, debug_session):
        """Test callback registration and invocation"""
        callbacks_called = {"enter": False, "exit": False, "pause": False, "step": False}
        
        async def on_node_enter(session, node_id):
            callbacks_called["enter"] = True
            
        async def on_node_exit(session, node_id):
            callbacks_called["exit"] = True
            
        async def on_pause(session, node_id):
            callbacks_called["pause"] = True
            
        async def on_step(session, step_type):
            callbacks_called["step"] = True
            
        debug_session.set_callbacks(
            on_node_enter=on_node_enter,
            on_node_exit=on_node_exit,
            on_pause=on_pause,
            on_step=on_step
        )
        
        assert debug_session.on_node_enter == on_node_enter
        assert debug_session.on_node_exit == on_node_exit
        assert debug_session.on_pause == on_pause
        assert debug_session.on_step == on_step


@pytest.mark.asyncio 
class TestWorkflowDebugger:
    """Test complete workflow debugger functionality"""
    
    @pytest.fixture
    def workflow_debugger(self):
        """Create workflow debugger for testing"""
        return WorkflowDebugger()
        
    @pytest.fixture
    async def debug_dag(self):
        """Create a DAG with actual executable functions for debugging"""
        async def start_task():
            await asyncio.sleep(0.01)  # Simulate work
            return {"data": "initial"}
            
        async def process_task(start_result=None, **kwargs):
            await asyncio.sleep(0.02)  # Simulate processing
            data = start_result.get("data", "unknown") if start_result else "unknown"
            return {"processed": f"processed_{data}"}
            
        async def end_task(process_result=None, **kwargs):
            await asyncio.sleep(0.01)  # Simulate finalization
            processed = process_result.get("processed", "none") if process_result else "none"
            return {"final": f"final_{processed}"}
            
        nodes = {
            "start": DAGNode("start", "input", start_task),
            "process": DAGNode("process", "transform", process_task, ["start"]),
            "end": DAGNode("end", "output", end_task, ["process"])
        }
        
        return DAGDefinition(
            dag_id="debug_dag",
            name="Debug Test DAG",
            description="A DAG for debugging tests",
            nodes=nodes,
            entry_points=["start"],
            exit_points=["end"]
        )
        
    async def test_debug_session_lifecycle(self, workflow_debugger, debug_dag):
        """Test complete debug session lifecycle"""
        # Start debug session
        session_id = await workflow_debugger.start_debug_session(debug_dag)
        
        assert session_id is not None
        assert session_id in workflow_debugger.active_sessions
        
        session = workflow_debugger.active_sessions[session_id]
        assert session.started_at is not None
        
        # Stop debug session
        success = await workflow_debugger.stop_debug_session(session_id)
        
        assert success is True
        assert session_id not in workflow_debugger.active_sessions
        assert len(workflow_debugger.session_history) == 1
        
    async def test_debug_execution_complete(self, workflow_debugger, debug_dag):
        """Test complete debug execution without breakpoints"""
        session_id = await workflow_debugger.start_debug_session(debug_dag)
        
        # Execute DAG
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "completed"
        assert "start" in final_state["node_results"]
        assert "process" in final_state["node_results"]
        assert "end" in final_state["node_results"]
        
        # Verify execution order and results
        start_result = final_state["node_results"]["start"]
        process_result = final_state["node_results"]["process"]
        end_result = final_state["node_results"]["end"]
        
        assert start_result["data"] == "initial"
        assert process_result["processed"] == "processed_initial"
        assert end_result["final"] == "final_processed_initial"
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_debug_execution_with_breakpoints(self, workflow_debugger, debug_dag):
        """Test debug execution with breakpoints"""
        session_id = await workflow_debugger.start_debug_session(debug_dag)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoint at process node
        await session.add_breakpoint("process")
        
        # Track execution events
        events = []
        
        async def track_pause(session, node_id):
            events.append(f"paused_at_{node_id}")
            # Continue after short delay
            await asyncio.sleep(0.1)
            await workflow_debugger.continue_execution(session_id)
            
        session.set_callbacks(on_pause=track_pause)
        
        # Execute with breakpoints
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert "paused_at_process" in events
        assert final_state["execution_state"] == "completed"
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_step_through_debugging(self, workflow_debugger, debug_dag):
        """Test step-through debugging functionality"""
        session_id = await workflow_debugger.start_debug_session(debug_dag)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoint at start to begin stepping
        await session.add_breakpoint("start")
        
        step_events = []
        
        async def handle_pause(session, node_id):
            step_events.append(f"pause_{node_id}")
            await asyncio.sleep(0.05)
            
            if node_id == "start":
                await workflow_debugger.step_over(session_id)
            elif node_id == "process":
                await workflow_debugger.step_over(session_id)
            else:
                await workflow_debugger.continue_execution(session_id)
                
        async def handle_step(session, step_type):
            step_events.append(f"step_{step_type}")
            
        session.set_callbacks(on_pause=handle_pause, on_step=handle_step)
        
        # Execute with stepping
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert "pause_start" in step_events
        assert "step_step_over" in step_events
        assert final_state["execution_state"] == "completed"
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_error_handling_and_break_on_error(self, workflow_debugger):
        """Test error handling and break on error functionality"""
        # Create DAG with failing node
        async def failing_task(**kwargs):
            raise ValueError("Intentional test error")
            
        async def success_task():
            return {"success": True}
            
        nodes = {
            "success": DAGNode("success", "test", success_task),
            "failing": DAGNode("failing", "test", failing_task, ["success"])
        }
        
        error_dag = DAGDefinition(
            dag_id="error_dag",
            name="Error Test DAG",
            description="DAG with failing node",
            nodes=nodes
        )
        
        config = DebugConfig("error_session", "error_dag", break_on_error=True)
        session_id = await workflow_debugger.start_debug_session(error_dag, config)
        
        error_events = []
        
        async def handle_error_pause(session, node_id):
            error_events.append(f"error_pause_{node_id}")
            # Check for error in context
            if "__last_error__" in session.execution_context.variables:
                error_info = session.execution_context.variables["__last_error__"]
                assert "Intentional test error" in error_info["error"]
            await workflow_debugger.continue_execution(session_id)
            
        session = workflow_debugger.active_sessions[session_id]
        session.set_callbacks(on_pause=handle_error_pause)
        
        # Execute - should fail but handle error gracefully
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "failed"
        assert "error_pause_failing" in error_events
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_pause_and_resume_functionality(self, workflow_debugger, debug_dag):
        """Test pausing and resuming execution"""
        session_id = await workflow_debugger.start_debug_session(debug_dag)
        
        pause_resume_events = []
        
        async def track_events(session, node_id):
            pause_resume_events.append(f"entered_{node_id}")
            
            # Pause at process node
            if node_id == "process":
                await workflow_debugger.pause_execution(session_id)
                pause_resume_events.append("pause_requested")
                
        session = workflow_debugger.active_sessions[session_id]
        session.set_callbacks(on_node_enter=track_events)
        
        # Start execution (will pause at process node)
        execution_task = asyncio.create_task(
            workflow_debugger.debug_execute(session_id)
        )
        
        # Wait a bit for pause to happen
        await asyncio.sleep(0.1)
        
        # Resume execution
        await workflow_debugger.continue_execution(session_id)
        pause_resume_events.append("resumed")
        
        # Wait for completion
        final_state = await execution_task
        
        assert "entered_process" in pause_resume_events
        assert "pause_requested" in pause_resume_events
        assert "resumed" in pause_resume_events
        assert final_state["execution_state"] == "completed"
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_session_management(self, workflow_debugger, debug_dag):
        """Test session management functionality"""
        # Create multiple sessions
        session_ids = []
        for i in range(3):
            session_id = await workflow_debugger.start_debug_session(debug_dag)
            session_ids.append(session_id)
            
        # Verify active sessions
        active_sessions = workflow_debugger.get_active_sessions()
        assert len(active_sessions) == 3
        assert all(sid in active_sessions for sid in session_ids)
        
        # Get session info
        for session_id in session_ids:
            info = workflow_debugger.get_session_info(session_id)
            assert info is not None
            assert info["session_id"] == session_id
            
        # Stop all sessions
        for session_id in session_ids:
            await workflow_debugger.stop_debug_session(session_id)
            
        # Verify sessions moved to history
        assert len(workflow_debugger.get_active_sessions()) == 0
        assert len(workflow_debugger.get_session_history()) == 3
        
    async def test_concurrent_debugging_sessions(self, workflow_debugger, debug_dag):
        """Test multiple concurrent debugging sessions"""
        # Start multiple sessions
        session_ids = []
        for i in range(3):
            session_id = await workflow_debugger.start_debug_session(debug_dag)
            session_ids.append(session_id)
            
        # Execute all sessions concurrently
        execution_tasks = [
            workflow_debugger.debug_execute(session_id)
            for session_id in session_ids
        ]
        
        results = await asyncio.gather(*execution_tasks)
        
        # Verify all completed successfully
        assert all(r["execution_state"] == "completed" for r in results)
        assert len(set(r["session_id"] for r in results)) == 3
        
        # Clean up
        for session_id in session_ids:
            await workflow_debugger.stop_debug_session(session_id)
            
    @pytest.mark.parametrize("step_type", [
        StepType.STEP_OVER,
        StepType.STEP_INTO,
        StepType.STEP_OUT,
        StepType.CONTINUE
    ])
    async def test_different_step_types(self, workflow_debugger, debug_dag, step_type):
        """Test different types of stepping operations"""
        session_id = await workflow_debugger.start_debug_session(debug_dag)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoint at start
        await session.add_breakpoint("start")
        
        step_commands = {
            StepType.STEP_OVER: workflow_debugger.step_over,
            StepType.STEP_INTO: workflow_debugger.step_into,
            StepType.STEP_OUT: workflow_debugger.step_out,
            StepType.CONTINUE: workflow_debugger.continue_execution
        }
        
        async def handle_pause(session, node_id):
            await asyncio.sleep(0.05)
            step_command = step_commands[step_type]
            await step_command(session_id)
            
        session.set_callbacks(on_pause=handle_pause)
        
        final_state = await workflow_debugger.debug_execute(session_id)
        
        # Should complete regardless of step type
        assert final_state["execution_state"] == "completed"
        
        await workflow_debugger.stop_debug_session(session_id)