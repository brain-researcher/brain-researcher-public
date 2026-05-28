"""Integration Tests for Workflow Debugging System

End-to-end tests for complete workflow debugging including debugger,
breakpoint manager, inspector integration, and real debugging scenarios.
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any
from unittest.mock import AsyncMock, MagicMock, patch

from brain_researcher.services.agent.debugger.workflow_debugger import (
    WorkflowDebugger, DAGDefinition, DAGNode, DebugConfig, ExecutionState, StepType
)
from brain_researcher.services.agent.debugger.breakpoint_manager import (
    BreakpointType, DataChangeType
)
from brain_researcher.services.agent.debugger.inspector import Inspector, InspectionFilter


@pytest.mark.integration
@pytest.mark.asyncio
class TestWorkflowDebuggingIntegration:
    """Integration tests for complete workflow debugging system"""
    
    @pytest.fixture
    async def neuroimaging_dag(self):
        """Create a realistic neuroimaging analysis DAG for testing"""
        
        async def load_data(input_path: str = None, **kwargs):
            """Simulate loading neuroimaging data"""
            await asyncio.sleep(0.1)
            return {
                "data": f"loaded_from_{input_path}",
                "shape": (64, 64, 64),
                "voxels": 262144,
                "metadata": {"TR": 2.0, "subjects": 20}
            }
            
        async def preprocess_data(load_data_result=None, **kwargs):
            """Simulate preprocessing neuroimaging data"""
            await asyncio.sleep(0.2)
            data = load_data_result or {}
            return {
                "preprocessed_data": f"preprocessed_{data.get('data', 'unknown')}",
                "cleaned_voxels": data.get("voxels", 0) * 0.95,
                "motion_correction": True,
                "slice_timing": True
            }
            
        async def statistical_analysis(preprocess_data_result=None, design_matrix=None, **kwargs):
            """Simulate statistical analysis"""
            await asyncio.sleep(0.15)
            preprocessed = preprocess_data_result or {}
            
            if not design_matrix:
                raise ValueError("Design matrix is required for statistical analysis")
                
            return {
                "t_stats": [2.5, 3.1, 1.8, 4.2, 2.9],
                "p_values": [0.01, 0.002, 0.07, 0.0001, 0.004],
                "significant_voxels": 15000,
                "effect_sizes": [0.5, 0.7, 0.3, 0.9, 0.6]
            }
            
        async def generate_report(statistical_analysis_result=None, **kwargs):
            """Generate analysis report"""
            await asyncio.sleep(0.05)
            stats = statistical_analysis_result or {}
            
            sig_voxels = stats.get("significant_voxels", 0)
            if sig_voxels < 1000:
                raise ValueError(f"Too few significant voxels: {sig_voxels}")
                
            return {
                "report": f"Analysis complete: {sig_voxels} significant voxels found",
                "summary_stats": {
                    "max_t": max(stats.get("t_stats", [0])),
                    "min_p": min(stats.get("p_values", [1]))
                },
                "output_files": ["results.nii.gz", "report.html", "stats.csv"]
            }
            
        nodes = {
            "load_data": DAGNode(
                "load_data", "input", load_data,
                parameters={"input_path": "/data/fmri_study.nii.gz"}
            ),
            "preprocess": DAGNode(
                "preprocess", "preprocessing", preprocess_data, 
                ["load_data"]
            ),
            "stats_analysis": DAGNode(
                "stats_analysis", "statistics", statistical_analysis,
                ["preprocess"],
                parameters={"design_matrix": [[1, 0], [0, 1], [1, 1]]}
            ),
            "report": DAGNode(
                "report", "output", generate_report,
                ["stats_analysis"]
            )
        }
        
        return DAGDefinition(
            dag_id="neuroimaging_analysis",
            name="Neuroimaging Analysis Pipeline",
            description="Complete fMRI analysis pipeline with preprocessing and statistics",
            nodes=nodes,
            entry_points=["load_data"],
            exit_points=["report"],
            global_parameters={"study_name": "working_memory", "n_subjects": 20}
        )
        
    @pytest.fixture
    def workflow_debugger(self):
        """Create workflow debugger for integration testing"""
        return WorkflowDebugger()
        
    async def test_complete_debugging_workflow(self, workflow_debugger, neuroimaging_dag):
        """Test complete debugging workflow from start to finish"""
        debug_config = DebugConfig(
            session_id="integration_test",
            dag_id=neuroimaging_dag.dag_id,
            enable_tracing=True,
            enable_profiling=True,
            break_on_error=True
        )
        
        # Start debug session
        session_id = await workflow_debugger.start_debug_session(neuroimaging_dag, debug_config)
        session = workflow_debugger.active_sessions[session_id]
        
        execution_events = []
        
        async def track_execution(session, node_id):
            execution_events.append(f"entered_{node_id}")
            
        session.set_callbacks(on_node_enter=track_execution)
        
        # Execute complete workflow
        final_state = await workflow_debugger.debug_execute(session_id)
        
        # Verify successful execution
        assert final_state["execution_state"] == "completed"
        assert "load_data" in final_state["node_results"]
        assert "preprocess" in final_state["node_results"]
        assert "stats_analysis" in final_state["node_results"]
        assert "report" in final_state["node_results"]
        
        # Verify execution order
        assert "entered_load_data" in execution_events
        assert "entered_preprocess" in execution_events
        assert "entered_stats_analysis" in execution_events
        assert "entered_report" in execution_events
        
        # Verify results structure
        load_result = final_state["node_results"]["load_data"]
        assert "shape" in load_result
        assert load_result["voxels"] == 262144
        
        stats_result = final_state["node_results"]["stats_analysis"]
        assert "t_stats" in stats_result
        assert len(stats_result["t_stats"]) == 5
        
        report_result = final_state["node_results"]["report"]
        assert "report" in report_result
        assert "output_files" in report_result
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_breakpoint_debugging_with_inspection(self, workflow_debugger, neuroimaging_dag):
        """Test debugging with breakpoints and variable inspection"""
        session_id = await workflow_debugger.start_debug_session(neuroimaging_dag)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoints at key stages
        await session.add_breakpoint("preprocess", description="Check preprocessing results")
        await session.add_breakpoint("stats_analysis", 
                                   condition="design_matrix is not None",
                                   description="Verify design matrix")
        
        breakpoint_hits = []
        inspection_results = []
        
        async def handle_breakpoint(session, node_id):
            breakpoint_hits.append(node_id)
            
            # Perform inspection at breakpoint
            inspector = session.inspector
            variables = await inspector.inspect_variables()
            
            inspection_results.append({
                "node": node_id,
                "variables": {name: var.value for name, var in variables.items()},
                "execution_stack": session.execution_context.execution_stack.copy()
            })
            
            # Continue after inspection
            await asyncio.sleep(0.1)
            await workflow_debugger.continue_execution(session_id)
            
        session.set_callbacks(on_pause=handle_breakpoint)
        
        # Execute with breakpoints
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "completed"
        
        # Verify breakpoints were hit
        assert "preprocess" in breakpoint_hits
        assert "stats_analysis" in breakpoint_hits
        
        # Verify inspection data
        assert len(inspection_results) == 2
        
        # Check preprocessing inspection
        preprocess_inspection = next(r for r in inspection_results if r["node"] == "preprocess")
        assert "load_data_result" in preprocess_inspection["variables"]
        
        # Check stats analysis inspection  
        stats_inspection = next(r for r in inspection_results if r["node"] == "stats_analysis")
        assert "design_matrix" in stats_inspection["variables"]
        assert stats_inspection["variables"]["design_matrix"] is not None
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_error_handling_and_debugging(self, workflow_debugger):
        """Test error handling and debugging capabilities"""
        
        # Create DAG with intentional error
        async def failing_node(**kwargs):
            # Simulate different types of errors
            import random
            error_types = [
                ValueError("Invalid input data format"),
                RuntimeError("Processing pipeline failed"),
                KeyError("Missing required parameter"),
            ]
            raise random.choice(error_types)
            
        async def recovery_node(failing_node_result=None, **kwargs):
            # This should not execute due to dependency failure
            return {"recovered": True}
            
        error_nodes = {
            "start": DAGNode("start", "input", lambda: {"data": "test"}),
            "failing": DAGNode("failing", "process", failing_node, ["start"]),
            "recovery": DAGNode("recovery", "recovery", recovery_node, ["failing"])
        }
        
        error_dag = DAGDefinition(
            "error_test_dag", "Error Test DAG", "DAG for testing error handling",
            error_nodes
        )
        
        debug_config = DebugConfig(
            session_id="error_test",
            dag_id="error_test_dag",
            break_on_error=True,
            enable_tracing=True
        )
        
        session_id = await workflow_debugger.start_debug_session(error_dag, debug_config)
        session = workflow_debugger.active_sessions[session_id]
        
        error_details = []
        
        async def handle_error_pause(session, node_id):
            error_details.append({
                "node": node_id,
                "error_context": session.execution_context.variables.get("__last_error__"),
                "timestamp": datetime.utcnow()
            })
            
            # Inspect error details
            inspector = session.inspector
            state = await inspector.inspect_execution_state()
            error_details[-1]["full_state"] = state
            
            # Continue to let error propagate
            await workflow_debugger.continue_execution(session_id)
            
        session.set_callbacks(on_pause=handle_error_pause)
        
        # Execute - should fail
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "failed"
        
        # Verify error was captured and debugged
        assert len(error_details) == 1
        assert error_details[0]["node"] == "failing"
        
        error_context = error_details[0]["error_context"]
        assert error_context is not None
        assert "error" in error_context
        assert error_context["node_id"] == "failing"
        
        # Verify recovery node did not execute
        assert "recovery" not in final_state["node_results"]
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_step_through_debugging(self, workflow_debugger, neuroimaging_dag):
        """Test step-through debugging functionality"""
        session_id = await workflow_debugger.start_debug_session(neuroimaging_dag)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoint at start to begin stepping
        await session.add_breakpoint("load_data")
        
        step_sequence = []
        
        async def handle_pause_and_step(session, node_id):
            step_sequence.append(f"pause_{node_id}")
            
            # Inspect state before stepping
            inspector = session.inspector
            current_state = await inspector.inspect_execution_state()
            step_sequence.append(f"inspect_{node_id}")
            
            await asyncio.sleep(0.05)
            
            # Step through different nodes with different step types
            if node_id == "load_data":
                await workflow_debugger.step_over(session_id)
            elif node_id == "preprocess":
                # Step over preprocessing
                await workflow_debugger.step_over(session_id)
            elif node_id == "stats_analysis":
                # Continue from statistics
                await workflow_debugger.continue_execution(session_id)
            else:
                await workflow_debugger.continue_execution(session_id)
                
        async def handle_step(session, step_type):
            step_sequence.append(f"step_{step_type.value}")
            
            # Add temporary breakpoint at next likely node
            if step_type == StepType.STEP_OVER:
                context = session.execution_context
                if context.current_level < len(context.execution_order) - 1:
                    next_level = context.execution_order[context.current_level + 1]
                    if next_level:
                        await session.add_breakpoint(next_level[0])
                        
        session.set_callbacks(on_pause=handle_pause_and_step, on_step=handle_step)
        
        # Execute with stepping
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "completed"
        
        # Verify step sequence
        assert "pause_load_data" in step_sequence
        assert "step_step_over" in step_sequence
        assert "inspect_load_data" in step_sequence
        
        # Should have paused at multiple nodes
        pause_events = [event for event in step_sequence if event.startswith("pause_")]
        assert len(pause_events) >= 2
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_data_breakpoint_integration(self, workflow_debugger, neuroimaging_dag):
        """Test data breakpoints with realistic data changes"""
        session_id = await workflow_debugger.start_debug_session(neuroimaging_dag)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add data breakpoints to watch for specific data changes
        await session.add_breakpoint(
            breakpoint_type=BreakpointType.DATA,
            variable_name="voxels",
            change_type=DataChangeType.CHANGE,
            description="Watch voxel count changes"
        )
        
        await session.add_breakpoint(
            breakpoint_type=BreakpointType.DATA,
            variable_name="significant_voxels",
            change_type=DataChangeType.WRITE,
            description="Watch significant voxels creation"
        )
        
        data_changes = []
        
        async def handle_data_breakpoint(session, node_id):
            # Identify what data changed
            inspector = session.inspector
            variables = await inspector.inspect_variables()
            
            changed_vars = {}
            for name, var in variables.items():
                if name in ["voxels", "significant_voxels"]:
                    changed_vars[name] = var.value
                    
            data_changes.append({
                "node": node_id,
                "changed_variables": changed_vars,
                "timestamp": datetime.utcnow()
            })
            
            await workflow_debugger.continue_execution(session_id)
            
        session.set_callbacks(on_pause=handle_data_breakpoint)
        
        # Execute and monitor data changes
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "completed"
        
        # Verify data breakpoints were triggered
        assert len(data_changes) >= 1
        
        # Check that we detected voxel changes
        voxel_changes = [c for c in data_changes if "voxels" in c["changed_variables"]]
        assert len(voxel_changes) > 0
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_concurrent_debugging_sessions(self, workflow_debugger, neuroimaging_dag):
        """Test multiple concurrent debugging sessions"""
        
        # Start multiple sessions with different configurations
        sessions = []
        for i in range(3):
            config = DebugConfig(
                session_id=f"concurrent_{i}",
                dag_id=f"concurrent_dag_{i}",
                enable_tracing=i % 2 == 0,  # Alternate tracing
                enable_profiling=True,
                break_on_error=True
            )
            
            session_id = await workflow_debugger.start_debug_session(neuroimaging_dag, config)
            sessions.append(session_id)
            
            # Add different breakpoints to each session
            session = workflow_debugger.active_sessions[session_id]
            if i == 0:
                await session.add_breakpoint("preprocess")
            elif i == 1:
                await session.add_breakpoint("stats_analysis")
            else:
                await session.add_breakpoint("report")
                
        # Track execution of each session
        session_results = {}
        
        async def create_session_handler(session_id):
            async def handle_pause(session, node_id):
                if session_id not in session_results:
                    session_results[session_id] = []
                session_results[session_id].append(f"pause_{node_id}")
                await asyncio.sleep(0.05)
                await workflow_debugger.continue_execution(session_id)
            return handle_pause
            
        # Set up handlers for each session
        for session_id in sessions:
            session = workflow_debugger.active_sessions[session_id]
            handler = await create_session_handler(session_id)
            session.set_callbacks(on_pause=handler)
            
        # Execute all sessions concurrently
        execution_tasks = [
            workflow_debugger.debug_execute(session_id)
            for session_id in sessions
        ]
        
        results = await asyncio.gather(*execution_tasks, return_exceptions=True)
        
        # Verify all sessions completed successfully
        assert len(results) == 3
        assert all(isinstance(r, dict) and r["execution_state"] == "completed" 
                  for r in results)
                  
        # Verify each session hit its expected breakpoint
        assert len(session_results) == 3
        
        # Clean up sessions
        for session_id in sessions:
            await workflow_debugger.stop_debug_session(session_id)
            
    async def test_memory_and_performance_debugging(self, workflow_debugger):
        """Test memory and performance debugging capabilities"""
        
        # Create DAG with memory-intensive operations
        async def create_large_data(**kwargs):
            # Create large data structures
            large_list = list(range(100000))
            large_dict = {f"key_{i}": f"value_{i}" * 10 for i in range(10000)}
            return {
                "large_list": large_list,
                "large_dict": large_dict,
                "metadata": {"size": "large"}
            }
            
        async def process_large_data(create_large_data_result=None, **kwargs):
            data = create_large_data_result or {}
            large_list = data.get("large_list", [])
            
            # Memory-intensive processing
            processed = [x * 2 for x in large_list[:50000]]  # Process half
            return {
                "processed_data": processed,
                "processing_stats": {
                    "input_size": len(large_list),
                    "output_size": len(processed)
                }
            }
            
        memory_nodes = {
            "create_data": DAGNode("create_data", "generator", create_large_data),
            "process_data": DAGNode("process_data", "processor", process_large_data, ["create_data"])
        }
        
        memory_dag = DAGDefinition(
            "memory_test_dag", "Memory Test DAG", "DAG for testing memory usage",
            memory_nodes
        )
        
        config = DebugConfig(
            session_id="memory_test",
            dag_id="memory_test_dag",
            enable_profiling=True,
            enable_tracing=True
        )
        
        session_id = await workflow_debugger.start_debug_session(memory_dag, config)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoints to monitor memory usage
        await session.add_breakpoint("create_data", description="Monitor data creation")
        await session.add_breakpoint("process_data", description="Monitor data processing")
        
        memory_snapshots = []
        
        async def monitor_memory(session, node_id):
            inspector = session.inspector
            
            # Get memory usage snapshot
            memory_info = await inspector.inspect_memory_usage()
            variables = await inspector.inspect_variables()
            
            memory_snapshots.append({
                "node": node_id,
                "memory_info": memory_info,
                "variable_count": len(variables),
                "timestamp": datetime.utcnow()
            })
            
            await workflow_debugger.continue_execution(session_id)
            
        session.set_callbacks(on_pause=monitor_memory)
        
        # Execute with memory monitoring
        start_time = time.time()
        final_state = await workflow_debugger.debug_execute(session_id)
        execution_time = time.time() - start_time
        
        assert final_state["execution_state"] == "completed"
        
        # Verify memory monitoring
        assert len(memory_snapshots) == 2
        
        # Check memory growth between snapshots
        create_snapshot = next(s for s in memory_snapshots if s["node"] == "create_data")
        process_snapshot = next(s for s in memory_snapshots if s["node"] == "process_data")
        
        assert create_snapshot["memory_info"]["total_size_bytes"] > 0
        assert process_snapshot["memory_info"]["total_size_bytes"] > 0
        
        # Verify performance tracking
        assert execution_time < 10.0  # Should complete reasonably quickly
        
        # Check for large variables in memory info
        create_largest = create_snapshot["memory_info"]["largest_variables"]
        assert any(var["name"] in ["large_list", "large_dict"] for var in create_largest)
        
        await workflow_debugger.stop_debug_session(session_id)
        
    async def test_debugging_session_persistence_and_recovery(self, workflow_debugger, neuroimaging_dag):
        """Test debugging session persistence and recovery capabilities"""
        
        # Start session with auto-save enabled
        config = DebugConfig(
            session_id="persistence_test",
            dag_id=neuroimaging_dag.dag_id,
            auto_save_state=True,
            enable_tracing=True
        )
        
        session_id = await workflow_debugger.start_debug_session(neuroimaging_dag, config)
        session = workflow_debugger.active_sessions[session_id]
        
        # Add breakpoints and configure session
        await session.add_breakpoint("preprocess", description="Midpoint checkpoint")
        
        saved_states = []
        
        async def save_state_at_breakpoint(session, node_id):
            # Create state snapshot
            inspector = session.inspector
            snapshot = await inspector.create_state_snapshot()
            saved_states.append(snapshot)
            
            # Simulate session persistence
            session_state = session.get_current_state()
            saved_states.append(("session_state", session_state))
            
            await workflow_debugger.continue_execution(session_id)
            
        session.set_callbacks(on_pause=save_state_at_breakpoint)
        
        # Execute until breakpoint
        final_state = await workflow_debugger.debug_execute(session_id)
        
        assert final_state["execution_state"] == "completed"
        assert len(saved_states) >= 1
        
        # Verify state snapshots were created
        state_snapshot = saved_states[0]
        assert state_snapshot.session_id == session_id
        assert len(state_snapshot.variables) > 0
        
        # Verify session state was captured
        session_state_entry = next(s for s in saved_states if isinstance(s, tuple))
        session_state = session_state_entry[1]
        
        assert session_state["session_id"] == session_id
        assert "node_results" in session_state
        assert "variables" in session_state
        
        # Test session history
        session_history = workflow_debugger.get_session_history()
        
        await workflow_debugger.stop_debug_session(session_id)
        
        # Verify session was moved to history
        updated_history = workflow_debugger.get_session_history()
        assert len(updated_history) == len(session_history) + 1
        
        # Verify we can retrieve historical session info
        historical_session = updated_history[-1]  # Most recent
        assert historical_session["session_id"] == session_id
        assert historical_session["dag_id"] == neuroimaging_dag.dag_id