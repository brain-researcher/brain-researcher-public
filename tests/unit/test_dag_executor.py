"""
Unit tests for Complex DAG Executor

Tests for the DAG execution engine including:
- DAG validation and parsing
- Node execution logic
- Conditional branching
- Loop expansion and execution
- Parameter resolution
- Error handling and retries
- State management
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from typing import Dict, List, Any

from brain_researcher.services.agent.dag_executor import (
    ComplexDAGExecutor, ExecutionStatus, NodeExecution, DAGExecution,
    SchedulingStrategy
)
from brain_researcher.services.agent.dag_language import (
    DAGDefinition, DAGNode, NodeType, LoopType, LoopConfig, RetryPolicy
)
from brain_researcher.services.agent.conditional_logic import ConditionalExecutor


class TestComplexDAGExecutor:
    """Test suite for ComplexDAGExecutor"""
    
    @pytest.fixture
    def mock_parallel_executor(self):
        """Mock parallel executor"""
        executor = AsyncMock()
        executor.execute_tool = AsyncMock(return_value={"status": "success", "result": "mock_result"})
        executor.execute_parallel = AsyncMock(return_value=[{"status": "success"}])
        return executor
    
    @pytest.fixture
    def dag_executor(self, mock_parallel_executor):
        """Create DAG executor with mocked dependencies"""
        return ComplexDAGExecutor(mock_parallel_executor)
    
    @pytest.fixture
    def simple_dag(self):
        """Simple DAG for testing"""
        nodes = {
            "node1": DAGNode(
                id="node1",
                type=NodeType.TOOL,
                tool="test_tool",
                parameters={"param1": "value1"}
            ),
            "node2": DAGNode(
                id="node2",
                type=NodeType.TOOL,
                tool="test_tool2",
                parameters={"param2": "${node1_result}"},
                dependencies=["node1"]
            )
        }
        
        return DAGDefinition(
            name="test_dag",
            nodes=nodes,
            parameters={"global_param": "global_value"}
        )
    
    @pytest.fixture
    def conditional_dag(self):
        """DAG with conditional nodes"""
        nodes = {
            "preprocessing": DAGNode(
                id="preprocessing",
                type=NodeType.TOOL,
                tool="fmriprep",
                parameters={"input": "${subject_id}"}
            ),
            "quality_check": DAGNode(
                id="quality_check",
                type=NodeType.CONDITIONAL,
                condition="preprocessing_result.qc_score > 0.8",
                true_branch=["analysis"],
                false_branch=["reprocess"],
                dependencies=["preprocessing"]
            ),
            "analysis": DAGNode(
                id="analysis",
                type=NodeType.TOOL,
                tool="glm_analysis",
                parameters={"data": "${preprocessing_result}"}
            ),
            "reprocess": DAGNode(
                id="reprocess",
                type=NodeType.TOOL,
                tool="enhanced_preprocessing",
                parameters={"data": "${preprocessing_result}"}
            )
        }
        
        return DAGDefinition(
            name="conditional_dag",
            nodes=nodes,
            parameters={"subject_id": "sub-001"}
        )
    
    @pytest.fixture
    def loop_dag(self):
        """DAG with loop nodes"""
        loop_config = LoopConfig(
            loop_type=LoopType.FOR,
            items="subjects",
            max_iterations=10,
            body=["individual_analysis"]
        )
        
        nodes = {
            "setup": DAGNode(
                id="setup",
                type=NodeType.TOOL,
                tool="setup_analysis",
                parameters={}
            ),
            "group_analysis": DAGNode(
                id="group_analysis",
                type=NodeType.LOOP,
                loop_config=loop_config,
                dependencies=["setup"]
            ),
            "individual_analysis": DAGNode(
                id="individual_analysis",
                type=NodeType.TOOL,
                tool="individual_glm",
                parameters={"subject": "${loop_item}"}
            )
        }
        
        return DAGDefinition(
            name="loop_dag",
            nodes=nodes,
            parameters={"subjects": ["sub-001", "sub-002", "sub-003"]}
        )
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_simple_dag(self, dag_executor, simple_dag):
        """Test execution of a simple DAG"""
        execution = await dag_executor.execute_dag(simple_dag)
        
        assert execution.status == ExecutionStatus.SUCCESS
        assert len(execution.completed_nodes) == 2
        assert "node1" in execution.completed_nodes
        assert "node2" in execution.completed_nodes
        assert execution.start_time is not None
        assert execution.end_time is not None
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dag_validation_failure(self, dag_executor):
        """Test DAG validation failure"""
        # Create invalid DAG with circular dependency
        nodes = {
            "node1": DAGNode(id="node1", type=NodeType.TOOL, tool="tool1", dependencies=["node2"]),
            "node2": DAGNode(id="node2", type=NodeType.TOOL, tool="tool2", dependencies=["node1"])
        }
        
        invalid_dag = DAGDefinition(name="invalid", nodes=nodes)
        
        with patch.object(invalid_dag, 'validate', return_value=["Circular dependency"]):
            execution = await dag_executor.execute_dag(invalid_dag)
            
            assert execution.status == ExecutionStatus.FAILED
            assert len(execution.completed_nodes) == 0
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_node_dependency_resolution(self, dag_executor, simple_dag):
        """Test that nodes wait for dependencies to complete"""
        execution_order = []
        
        async def mock_execute_tool(tool_spec):
            execution_order.append(tool_spec['tool'])
            await asyncio.sleep(0.01)  # Simulate execution time
            return {"status": "success", "result": f"result_{tool_spec['tool']}"}
        
        dag_executor.parallel_executor.execute_tool.side_effect = mock_execute_tool
        
        await dag_executor.execute_dag(simple_dag)
        
        # node2 should execute after node1 due to dependency
        assert execution_order.index("test_tool") < execution_order.index("test_tool2")
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parameter_resolution(self, dag_executor, simple_dag):
        """Test parameter resolution and propagation"""
        executed_params = []
        
        async def mock_execute_tool(tool_spec):
            executed_params.append(tool_spec['parameters'])
            return {"status": "success", "result": f"result_{tool_spec['tool']}"}
        
        dag_executor.parallel_executor.execute_tool.side_effect = mock_execute_tool
        
        await dag_executor.execute_dag(simple_dag, {"dynamic_param": "dynamic_value"})
        
        # Check that global parameters are available
        assert len(executed_params) == 2
        
        # First node should have original parameters
        assert executed_params[0]["param1"] == "value1"
        
        # Second node should have resolved parameter reference
        # Note: In real implementation, this would resolve to actual result
        assert "param2" in executed_params[1]
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_conditional_execution(self, dag_executor, conditional_dag):
        """Test conditional node execution"""
        # Mock successful preprocessing with high QC score
        async def mock_execute_tool(tool_spec):
            if tool_spec['tool'] == 'fmriprep':
                return {"status": "success", "qc_score": 0.9}
            return {"status": "success", "result": "mock_result"}
        
        dag_executor.parallel_executor.execute_tool.side_effect = mock_execute_tool
        
        with patch.object(dag_executor.conditional_executor, 'execute_if_else') as mock_conditional:
            mock_conditional.return_value = ["analysis"]  # Should execute analysis branch
            
            execution = await dag_executor.execute_dag(conditional_dag)
            
            assert execution.status == ExecutionStatus.SUCCESS
            assert "preprocessing" in execution.completed_nodes
            assert "quality_check" in execution.completed_nodes
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_loop_expansion(self, dag_executor, loop_dag):
        """Test loop node expansion"""
        execution = await dag_executor.execute_dag(loop_dag)
        
        assert execution.status == ExecutionStatus.SUCCESS
        
        # Check that loop was expanded
        assert "group_analysis" in execution.expanded_nodes
        expanded_nodes = execution.expanded_nodes["group_analysis"]
        
        # Should have 3 iterations for 3 subjects
        assert len(expanded_nodes) == 3
        assert all("individual_analysis_iter_" in node_id for node_id in expanded_nodes)
    
    @pytest.mark.unit
    @pytest.mark.asyncio 
    async def test_loop_max_iterations_respected(self, dag_executor):
        """Test that loop respects max iterations limit"""
        loop_config = LoopConfig(
            loop_type=LoopType.FOR,
            items="subjects",
            max_iterations=2,  # Limit to 2 iterations
            body=["individual_analysis"]
        )
        
        nodes = {
            "loop_node": DAGNode(
                id="loop_node",
                type=NodeType.LOOP,
                loop_config=loop_config
            ),
            "individual_analysis": DAGNode(
                id="individual_analysis",
                type=NodeType.TOOL,
                tool="test_tool",
                parameters={}
            )
        }
        
        loop_dag = DAGDefinition(
            name="limited_loop",
            nodes=nodes,
            parameters={"subjects": ["sub-001", "sub-002", "sub-003", "sub-004"]}
        )
        
        execution = await dag_executor.execute_dag(loop_dag)
        
        # Should only create 2 iterations despite 4 subjects
        expanded_nodes = execution.expanded_nodes.get("loop_node", [])
        assert len(expanded_nodes) <= 2
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_node_retry_policy(self, dag_executor, simple_dag):
        """Test node retry on failure"""
        retry_policy = RetryPolicy(max_attempts=3, backoff_multiplier=1.5)
        simple_dag.nodes["node1"].retry_policy = retry_policy
        
        call_count = 0
        
        async def mock_execute_tool(tool_spec):
            nonlocal call_count
            call_count += 1
            if call_count < 3:  # Fail first 2 attempts
                raise Exception("Mock failure")
            return {"status": "success", "result": "success_after_retry"}
        
        dag_executor.parallel_executor.execute_tool.side_effect = mock_execute_tool
        
        # Mock the sleep to speed up test
        with patch('asyncio.sleep'):
            execution = await dag_executor.execute_dag(simple_dag)
            
            # Should succeed after retries
            assert call_count == 3
            node_exec = execution.node_executions["node1"]
            assert node_exec.attempt == 3
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parallel_node_execution(self, dag_executor):
        """Test parallel node execution"""
        nodes = {
            "parallel_node": DAGNode(
                id="parallel_node",
                type=NodeType.PARALLEL,
                parallel_nodes=["task1", "task2", "task3"],
                parallel_strategy="all_success"
            ),
            "task1": DAGNode(id="task1", type=NodeType.TOOL, tool="tool1"),
            "task2": DAGNode(id="task2", type=NodeType.TOOL, tool="tool2"),
            "task3": DAGNode(id="task3", type=NodeType.TOOL, tool="tool3")
        }
        
        parallel_dag = DAGDefinition(name="parallel_test", nodes=nodes)
        
        # Mock successful parallel execution
        dag_executor.parallel_executor.execute_parallel.return_value = [
            {"status": "success"}, {"status": "success"}, {"status": "success"}
        ]
        
        execution = await dag_executor.execute_dag(parallel_dag)
        
        assert execution.status == ExecutionStatus.SUCCESS
        assert "parallel_node" in execution.completed_nodes
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execution_cancellation(self, dag_executor, simple_dag):
        """Test DAG execution cancellation"""
        # Start execution
        execution_task = asyncio.create_task(dag_executor.execute_dag(simple_dag))
        
        # Cancel after short delay
        await asyncio.sleep(0.01)
        execution_id = None
        
        # Get execution ID from active executions
        if dag_executor.active_executions:
            execution_id = list(dag_executor.active_executions.keys())[0]
            success = dag_executor.cancel_execution(execution_id)
            assert success
        
        # Wait for execution to complete
        execution = await execution_task
        
        if execution_id:
            cancelled_execution = dag_executor.get_execution_status(execution_id)
            assert cancelled_execution.status in [ExecutionStatus.CANCELLED, ExecutionStatus.FAILED]
    
    @pytest.mark.unit
    def test_execution_status_retrieval(self, dag_executor, simple_dag):
        """Test execution status retrieval"""
        # Test non-existent execution
        status = dag_executor.get_execution_status("non-existent")
        assert status is None
        
        # Test existing execution status would be tested in integration
    
    @pytest.mark.unit
    def test_execution_summary_generation(self, dag_executor):
        """Test execution summary generation"""
        # Create mock execution
        execution = DAGExecution(
            execution_id="test-id",
            dag=DAGDefinition(name="test", nodes={}),
            status=ExecutionStatus.RUNNING,
            start_time=datetime.now() - timedelta(seconds=30)
        )
        
        # Add some mock node executions
        execution.node_executions = {
            "node1": NodeExecution("node1", ExecutionStatus.SUCCESS),
            "node2": NodeExecution("node2", ExecutionStatus.RUNNING),
            "node3": NodeExecution("node3", ExecutionStatus.PENDING)
        }
        execution.completed_nodes = {"node1"}
        execution.active_executions = {"node2"}
        
        dag_executor.active_executions["test-id"] = execution
        
        summary = dag_executor.get_execution_summary("test-id")
        
        assert summary is not None
        assert summary["execution_id"] == "test-id"
        assert summary["total_nodes"] == 3
        assert summary["completed_nodes"] == 1
        assert summary["active_nodes"] == 1
        assert summary["progress_percentage"] == pytest.approx(33.33, rel=1e-2)
        assert "duration_seconds" in summary
    
    @pytest.mark.unit
    def test_scheduling_strategies(self, dag_executor):
        """Test different scheduling strategies"""
        # Test eager scheduling (default)
        assert dag_executor.scheduling_strategy == SchedulingStrategy.EAGER
        
        # Test strategy change
        dag_executor.scheduling_strategy = SchedulingStrategy.LAZY
        assert dag_executor.scheduling_strategy == SchedulingStrategy.LAZY
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_subdag_execution(self, dag_executor, tmp_path):
        """Test sub-DAG execution"""
        # Create sub-DAG file
        subdag_content = """
name: sub_dag
nodes:
  sub_node:
    type: tool
    tool: sub_tool
    parameters:
      param: value
"""
        subdag_file = tmp_path / "subdag.yaml"
        subdag_file.write_text(subdag_content)
        
        # Create main DAG with sub-DAG node
        nodes = {
            "main_node": DAGNode(
                id="main_node",
                type=NodeType.SUBDAG,
                subdag_path=str(subdag_file),
                subdag_parameters={"sub_param": "sub_value"}
            )
        }
        
        main_dag = DAGDefinition(name="main_dag", nodes=nodes)
        
        with patch.object(DAGDefinition, 'from_file') as mock_from_file:
            mock_subdag = DAGDefinition(
                name="sub_dag", 
                nodes={"sub_node": DAGNode(id="sub_node", type=NodeType.TOOL, tool="sub_tool")}
            )
            mock_from_file.return_value = mock_subdag
            
            # Mock sub-DAG execution
            original_execute = dag_executor.execute_dag
            async def mock_execute_dag(dag, params=None, execution_id=None):
                if dag.name == "sub_dag":
                    # Return successful sub-DAG execution
                    sub_execution = DAGExecution(
                        execution_id="sub-exec-id",
                        dag=dag,
                        status=ExecutionStatus.SUCCESS
                    )
                    return sub_execution
                else:
                    # Call original for main DAG
                    return await original_execute(dag, params, execution_id)
            
            dag_executor.execute_dag = mock_execute_dag
            
            execution = await dag_executor.execute_dag(main_dag)
            
            assert execution.status == ExecutionStatus.SUCCESS
            assert "main_node" in execution.completed_nodes


class TestDAGValidation:
    """Test DAG validation logic"""
    
    @pytest.mark.unit
    def test_dag_cycle_detection(self):
        """Test detection of cycles in DAG"""
        # Create DAG with cycle
        nodes = {
            "A": DAGNode(id="A", type=NodeType.TOOL, tool="toolA", dependencies=["C"]),
            "B": DAGNode(id="B", type=NodeType.TOOL, tool="toolB", dependencies=["A"]),
            "C": DAGNode(id="C", type=NodeType.TOOL, tool="toolC", dependencies=["B"])
        }
        
        dag = DAGDefinition(name="cyclic_dag", nodes=nodes)
        errors = dag.validate()
        
        assert len(errors) > 0
        assert any("cycle" in error.lower() or "circular" in error.lower() for error in errors)
    
    @pytest.mark.unit
    def test_dag_missing_dependencies(self):
        """Test detection of missing dependencies"""
        nodes = {
            "A": DAGNode(id="A", type=NodeType.TOOL, tool="toolA", dependencies=["missing_node"]),
        }
        
        dag = DAGDefinition(name="missing_dep_dag", nodes=nodes)
        errors = dag.validate()
        
        assert len(errors) > 0
        assert any("missing_node" in error for error in errors)
    
    @pytest.mark.unit
    def test_valid_dag_passes_validation(self):
        """Test that valid DAG passes validation"""
        nodes = {
            "A": DAGNode(id="A", type=NodeType.TOOL, tool="toolA"),
            "B": DAGNode(id="B", type=NodeType.TOOL, tool="toolB", dependencies=["A"]),
            "C": DAGNode(id="C", type=NodeType.TOOL, tool="toolC", dependencies=["A", "B"])
        }
        
        dag = DAGDefinition(name="valid_dag", nodes=nodes)
        errors = dag.validate()
        
        assert len(errors) == 0


@pytest.mark.integration
class TestDAGExecutorIntegration:
    """Integration tests for DAG executor"""
    
    @pytest.mark.asyncio
    async def test_full_neuroimaging_workflow(self):
        """Test a complete neuroimaging analysis workflow"""
        # This would test with actual neuroimaging tools
        # For now, just verify the test structure
        pass
    
    @pytest.mark.asyncio
    async def test_error_propagation_and_recovery(self):
        """Test error propagation and recovery mechanisms"""
        # This would test complex error scenarios
        pass
    
    @pytest.mark.asyncio
    async def test_resource_intensive_dag(self):
        """Test DAG with resource-intensive operations"""
        # This would test performance and resource management
        pass


# Property-based testing
@pytest.mark.property
class TestDAGProperties:
    """Property-based tests for DAG execution"""
    
    def test_dag_execution_deterministic(self):
        """Test that DAG execution is deterministic for same inputs"""
        # Would use hypothesis for property-based testing
        pass
    
    def test_parameter_resolution_consistency(self):
        """Test parameter resolution consistency"""
        pass
    
    def test_loop_bounds_always_respected(self):
        """Test that loop iterations never exceed max_iterations"""
        pass