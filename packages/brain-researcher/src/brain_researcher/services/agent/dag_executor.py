"""
Complex DAG Executor for Brain Researcher

This module provides execution of complex DAG workflows with support for:
- Topological execution with conditional branches
- Loop expansion and bounded execution
- Dynamic parameter propagation
- Sub-DAG composition and execution
- Parallel node execution strategies
- Error handling and retry policies
- State management and checkpointing
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import uuid
import copy
import traceback

from .dag_language import DAGDefinition, DAGNode, NodeType, LoopType, ParameterResolver
from .checkpoint_manager import CheckpointManager, ExecutionState
from .conditional_logic import ConditionalExecutor, LoopManager
from .parallel_executor import AdaptiveParallelExecutionOrchestrator as ParallelExecutor

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """Execution status for nodes and DAGs"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class SchedulingStrategy(Enum):
    """Node scheduling strategies"""
    EAGER = "eager"  # Schedule as soon as dependencies are met
    LAZY = "lazy"    # Schedule only when explicitly triggered
    BATCH = "batch"  # Batch similar nodes together


@dataclass
class NodeExecution:
    """State of a single node execution"""
    node_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    attempt: int = 0
    max_attempts: int = 3
    result: Optional[Any] = None
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    dependencies_met: bool = False
    retry_delay: float = 0.0


@dataclass
class DAGExecution:
    """State of a complete DAG execution"""
    execution_id: str
    dag: DAGDefinition
    status: ExecutionStatus = ExecutionStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    node_executions: Dict[str, NodeExecution] = field(default_factory=dict)
    global_context: Dict[str, Any] = field(default_factory=dict)
    expanded_nodes: Dict[str, List[str]] = field(default_factory=dict)  # For loops
    active_executions: Set[str] = field(default_factory=set)
    completed_nodes: Set[str] = field(default_factory=set)
    failed_nodes: Set[str] = field(default_factory=set)
    last_checkpoint_id: Optional[str] = None


class ComplexDAGExecutor:
    """Executes complex DAG workflows with advanced features"""
    
    def __init__(self, parallel_executor: Optional[ParallelExecutor] = None, checkpoint_manager: Optional[CheckpointManager] = None):
        self.parallel_executor = parallel_executor or ParallelExecutor()
        self.conditional_executor = ConditionalExecutor()
        self.loop_manager = LoopManager()
        self.active_executions: Dict[str, DAGExecution] = {}
        self.scheduling_strategy = SchedulingStrategy.EAGER
        self.max_concurrent_nodes = 10
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(storage_backend="memory")
        
    async def execute_dag(self, dag: DAGDefinition, initial_params: Dict[str, Any] = None,
                         execution_id: Optional[str] = None,
                         resume_checkpoint_id: Optional[str] = None) -> DAGExecution:
        """Execute a complete DAG workflow"""
        if execution_id is None:
            execution_id = str(uuid.uuid4())
        
        # Initialize execution state
        execution = DAGExecution(
            execution_id=execution_id,
            dag=dag,
            start_time=datetime.now(),
            global_context=initial_params or {}
        )
        
        # Validate DAG before execution
        validation_errors = dag.validate()
        if validation_errors:
            execution.status = ExecutionStatus.FAILED
            execution.end_time = datetime.now()
            logger.error(f"DAG validation failed: {validation_errors}")
            return execution
        
        # Store execution
        self.active_executions[execution_id] = execution

        # Apply resume checkpoint if provided
        if resume_checkpoint_id and self.checkpoint_manager:
            try:
                state = self.checkpoint_manager.restore_from_checkpoint(resume_checkpoint_id)
                if state:
                    self._apply_checkpoint_state(execution, state)
                    logger.info("Resumed DAG %s from checkpoint %s", execution_id, resume_checkpoint_id)
            except Exception as exc:
                logger.warning("Failed to apply checkpoint %s: %s", resume_checkpoint_id, exc)
        
        try:
            # Resolve global parameters
            execution.global_context.update(
                ParameterResolver.resolve_parameters(dag.parameters, execution.global_context)
            )
            
            # Initialize node executions
            for node_id, node in dag.nodes.items():
                execution.node_executions[node_id] = NodeExecution(
                    node_id=node_id,
                    max_attempts=node.retry_policy.max_attempts if node.retry_policy else 3
                )
            
            # Execute DAG
            execution.status = ExecutionStatus.RUNNING
            await self._execute_dag_workflow(execution)

            # Persist final checkpoint
            self._persist_checkpoint(execution)
            
            # Determine final status
            if execution.failed_nodes:
                execution.status = ExecutionStatus.FAILED
            else:
                execution.status = ExecutionStatus.SUCCESS
                
        except Exception as e:
            logger.error(f"DAG execution failed: {e}")
            logger.error(traceback.format_exc())
            execution.status = ExecutionStatus.FAILED
            
        finally:
            execution.end_time = datetime.now()
            
        return execution
    
    async def _execute_dag_workflow(self, execution: DAGExecution) -> None:
        """Execute the main DAG workflow"""
        dag = execution.dag
        
        # Expand any loop nodes first
        await self._expand_loop_nodes(execution)
        
        # Get initial ready nodes
        ready_nodes = self._get_ready_nodes(execution)
        
        while ready_nodes or execution.active_executions:
            # Schedule ready nodes
            for node_id in ready_nodes:
                if len(execution.active_executions) < self.max_concurrent_nodes:
                    await self._schedule_node(execution, node_id)
            
            # Wait for at least one node to complete
            if execution.active_executions:
                await self._wait_for_completion(execution)
                self._persist_checkpoint(execution)
            
            # Update ready nodes
            ready_nodes = self._get_ready_nodes(execution)
            
            # Check for deadlock
            if not ready_nodes and not execution.active_executions:
                remaining_nodes = set(execution.node_executions.keys()) - execution.completed_nodes
                if remaining_nodes:
                    logger.warning(f"Deadlock detected. Remaining nodes: {remaining_nodes}")
                break
    
    async def _expand_loop_nodes(self, execution: DAGExecution) -> None:
        """Expand loop nodes into individual iterations"""
        dag = execution.dag
        
        for node_id, node in dag.nodes.items():
            if node.type == NodeType.LOOP and node.loop_config:
                expanded_nodes = await self._expand_single_loop(execution, node)
                execution.expanded_nodes[node_id] = expanded_nodes
                
                # Mark original loop node as completed
                execution.node_executions[node_id].status = ExecutionStatus.SUCCESS
                execution.completed_nodes.add(node_id)
    
    async def _expand_single_loop(self, execution: DAGExecution, loop_node: DAGNode) -> List[str]:
        """Expand a single loop node into iterations"""
        loop_config = loop_node.loop_config
        context = execution.global_context.copy()
        
        # Resolve loop parameters
        context.update(ParameterResolver.resolve_parameters(loop_node.parameters, context))
        
        expanded_nodes = []
        
        if loop_config.loop_type == LoopType.FOR:
            # For loop with items
            items = context.get(loop_config.items, [])
            if not isinstance(items, (list, tuple)):
                logger.error(f"For loop items '{loop_config.items}' is not iterable")
                return []
            
            for i, item in enumerate(items[:loop_config.max_iterations]):
                iteration_nodes = self._create_loop_iteration_nodes(
                    execution, loop_node, i, item, context
                )
                expanded_nodes.extend(iteration_nodes)
                
        elif loop_config.loop_type == LoopType.FOREACH:
            # Foreach loop
            loop_results = self.loop_manager.execute_foreach_loop(
                loop_config.items, loop_config.body, loop_config.max_iterations,
                context, loop_config.break_condition
            )
            
            for i, loop_result in enumerate(loop_results):
                iteration_nodes = self._create_loop_iteration_nodes(
                    execution, loop_node, i, loop_result['item'], loop_result['context']
                )
                expanded_nodes.extend(iteration_nodes)
                
        elif loop_config.loop_type == LoopType.WHILE:
            # While loop - evaluate condition iteratively
            iteration = 0
            while iteration < loop_config.max_iterations:
                # Check while condition
                if loop_config.condition:
                    try:
                        condition_result = self.conditional_executor.evaluate_condition(
                            loop_config.condition, context
                        )
                        if not condition_result.value:
                            break
                    except Exception as e:
                        logger.error(f"Error evaluating while condition: {e}")
                        break
                
                iteration_nodes = self._create_loop_iteration_nodes(
                    execution, loop_node, iteration, None, context
                )
                expanded_nodes.extend(iteration_nodes)
                iteration += 1
        
        return expanded_nodes
    
    def _create_loop_iteration_nodes(self, execution: DAGExecution, loop_node: DAGNode,
                                   iteration: int, item: Any, context: Dict[str, Any]) -> List[str]:
        """Create nodes for a single loop iteration"""
        iteration_nodes = []
        
        for body_node_id in loop_node.loop_config.body:
            if body_node_id not in execution.dag.nodes:
                logger.warning(f"Loop body node '{body_node_id}' not found in DAG")
                continue
            
            # Create unique node ID for this iteration
            iteration_node_id = f"{body_node_id}_iter_{iteration}"
            
            # Clone the original node
            original_node = execution.dag.nodes[body_node_id]
            iteration_node = copy.deepcopy(original_node)
            iteration_node.id = iteration_node_id
            
            # Update context with loop variables
            iteration_context = context.copy()
            iteration_context.update({
                'loop_iteration': iteration,
                'loop_item': item,
                'loop_node_id': loop_node.id
            })
            
            # Resolve parameters for this iteration
            iteration_node.parameters = ParameterResolver.resolve_parameters(
                iteration_node.parameters, iteration_context
            )
            
            # Create node execution
            execution.node_executions[iteration_node_id] = NodeExecution(
                node_id=iteration_node_id,
                context=iteration_context,
                max_attempts=iteration_node.retry_policy.max_attempts if iteration_node.retry_policy else 3
            )
            
            # Add to DAG (temporarily)
            execution.dag.nodes[iteration_node_id] = iteration_node
            iteration_nodes.append(iteration_node_id)
        
        # Handle dependencies between iterations
        if iteration > 0:
            for i, node_id in enumerate(iteration_nodes):
                prev_iteration_node_id = f"{loop_node.loop_config.body[i]}_iter_{iteration-1}"
                if prev_iteration_node_id in execution.node_executions:
                    execution.dag.nodes[node_id].dependencies.append(prev_iteration_node_id)
        
        return iteration_nodes
    
    def _get_ready_nodes(self, execution: DAGExecution) -> List[str]:
        """Get nodes that are ready to execute"""
        ready_nodes = []
        
        for node_id, node_exec in execution.node_executions.items():
            if (node_exec.status == ExecutionStatus.PENDING and 
                node_id not in execution.active_executions and
                node_id not in execution.completed_nodes):
                
                # Check if all dependencies are completed
                node = execution.dag.nodes.get(node_id)
                if node and self._are_dependencies_met(execution, node):
                    ready_nodes.append(node_id)
        
        return ready_nodes
    
    def _are_dependencies_met(self, execution: DAGExecution, node: DAGNode) -> bool:
        """Check if all node dependencies are completed successfully"""
        for dep_id in node.dependencies:
            if dep_id not in execution.completed_nodes:
                return False
            
            # Check if dependency completed successfully
            dep_exec = execution.node_executions.get(dep_id)
            if dep_exec and dep_exec.status != ExecutionStatus.SUCCESS:
                return False
        
        return True
    
    async def _schedule_node(self, execution: DAGExecution, node_id: str) -> None:
        """Schedule a node for execution"""
        node = execution.dag.nodes.get(node_id)
        node_exec = execution.node_executions.get(node_id)
        
        if not node or not node_exec:
            logger.error(f"Node or execution not found: {node_id}")
            return
        
        # Mark as active
        execution.active_executions.add(node_id)
        node_exec.status = ExecutionStatus.RUNNING
        node_exec.start_time = datetime.now()
        
        logger.info(f"Scheduling node {node_id} (type: {node.type.value})")
        
        # Execute based on node type
        try:
            if node.type == NodeType.TOOL:
                await self._execute_tool_node(execution, node, node_exec)
            elif node.type == NodeType.CONDITIONAL:
                await self._execute_conditional_node(execution, node, node_exec)
            elif node.type == NodeType.SUBDAG:
                await self._execute_subdag_node(execution, node, node_exec)
            elif node.type == NodeType.PARALLEL:
                await self._execute_parallel_node(execution, node, node_exec)
            else:
                logger.warning(f"Unknown node type: {node.type}")
                node_exec.status = ExecutionStatus.SKIPPED
                
        except Exception as e:
            logger.error(f"Error executing node {node_id}: {e}")
            node_exec.status = ExecutionStatus.FAILED
            node_exec.error = str(e)
        
        finally:
            # Mark as completed
            execution.active_executions.discard(node_id)
            node_exec.end_time = datetime.now()
            
            if node_exec.status == ExecutionStatus.SUCCESS:
                execution.completed_nodes.add(node_id)
            elif node_exec.status == ExecutionStatus.FAILED:
                execution.failed_nodes.add(node_id)
    
    async def _execute_tool_node(self, execution: DAGExecution, node: DAGNode, 
                                node_exec: NodeExecution) -> None:
        """Execute a tool node"""
        # Prepare execution context
        context = execution.global_context.copy()
        context.update(node_exec.context)
        
        # Resolve parameters
        resolved_params = ParameterResolver.resolve_parameters(node.parameters, context)
        
        # Execute tool using parallel executor
        tool_spec = {
            'tool': node.tool,
            'parameters': resolved_params,
            'timeout': node.timeout
        }
        
        try:
            result = await self.parallel_executor.execute_tool(tool_spec)
            node_exec.result = result
            node_exec.status = ExecutionStatus.SUCCESS
            
            # Update global context with results
            execution.global_context[f"{node.id}_result"] = result
            
        except Exception as e:
            logger.error(f"Tool execution failed for node {node.id}: {e}")
            
            # Check retry policy
            if await self._should_retry(node, node_exec):
                await self._schedule_retry(execution, node, node_exec)
            else:
                node_exec.status = ExecutionStatus.FAILED
                node_exec.error = str(e)
    
    async def _execute_conditional_node(self, execution: DAGExecution, node: DAGNode,
                                       node_exec: NodeExecution) -> None:
        """Execute a conditional node"""
        context = execution.global_context.copy()
        context.update(node_exec.context)
        
        try:
            if node.condition:
                # Simple if-else
                branch_nodes = self.conditional_executor.execute_if_else(
                    node.condition, node.true_branch, node.false_branch, context
                )
            elif node.switch_branches:
                # Switch-case logic
                switch_value = context.get('switch_value')  # Should be set by previous node
                branch_nodes = self.conditional_executor.execute_switch(
                    switch_value, node.switch_branches, node.default_branch
                )
            else:
                logger.warning(f"Conditional node {node.id} has no condition or switch")
                branch_nodes = []
            
            # Schedule branch nodes
            for branch_node_id in branch_nodes:
                if branch_node_id in execution.dag.nodes:
                    # Add conditional dependency
                    execution.dag.nodes[branch_node_id].dependencies.append(node.id)
                    
            node_exec.result = {'executed_branch': branch_nodes}
            node_exec.status = ExecutionStatus.SUCCESS
            
        except Exception as e:
            logger.error(f"Conditional execution failed for node {node.id}: {e}")
            node_exec.status = ExecutionStatus.FAILED
            node_exec.error = str(e)
    
    async def _execute_subdag_node(self, execution: DAGExecution, node: DAGNode,
                                  node_exec: NodeExecution) -> None:
        """Execute a sub-DAG node"""
        try:
            # Load sub-DAG
            subdag = DAGDefinition.from_file(node.subdag_path)
            
            # Prepare sub-DAG context
            subdag_context = execution.global_context.copy()
            subdag_context.update(node.subdag_parameters)
            subdag_context.update(node_exec.context)
            
            # Execute sub-DAG
            subdag_execution = await self.execute_dag(subdag, subdag_context)
            
            # Check sub-DAG result
            if subdag_execution.status == ExecutionStatus.SUCCESS:
                node_exec.status = ExecutionStatus.SUCCESS
                node_exec.result = {
                    'subdag_execution_id': subdag_execution.execution_id,
                    'subdag_results': {
                        node_id: exec.result for node_id, exec in subdag_execution.node_executions.items()
                        if exec.status == ExecutionStatus.SUCCESS
                    }
                }
                
                # Merge sub-DAG context back
                execution.global_context.update(subdag_execution.global_context)
                
            else:
                node_exec.status = ExecutionStatus.FAILED
                node_exec.error = f"Sub-DAG execution failed: {subdag_execution.execution_id}"
                
        except Exception as e:
            logger.error(f"Sub-DAG execution failed for node {node.id}: {e}")
            node_exec.status = ExecutionStatus.FAILED
            node_exec.error = str(e)
    
    async def _execute_parallel_node(self, execution: DAGExecution, node: DAGNode,
                                    node_exec: NodeExecution) -> None:
        """Execute a parallel node"""
        try:
            # Prepare parallel tasks
            parallel_tasks = []
            for parallel_node_id in node.parallel_nodes:
                if parallel_node_id in execution.dag.nodes:
                    parallel_node = execution.dag.nodes[parallel_node_id]
                    if parallel_node.type == NodeType.TOOL:
                        task_spec = {
                            'tool': parallel_node.tool,
                            'parameters': ParameterResolver.resolve_parameters(
                                parallel_node.parameters, execution.global_context
                            )
                        }
                        parallel_tasks.append(task_spec)
            
            # Execute in parallel
            if parallel_tasks:
                results = await self.parallel_executor.execute_parallel(parallel_tasks)
                
                # Process results based on strategy
                if node.parallel_strategy == "all_success":
                    if all(result.get('status') == 'success' for result in results):
                        node_exec.status = ExecutionStatus.SUCCESS
                    else:
                        node_exec.status = ExecutionStatus.FAILED
                elif node.parallel_strategy == "any_success":
                    if any(result.get('status') == 'success' for result in results):
                        node_exec.status = ExecutionStatus.SUCCESS
                    else:
                        node_exec.status = ExecutionStatus.FAILED
                elif node.parallel_strategy == "continue_on_failure":
                    node_exec.status = ExecutionStatus.SUCCESS  # Always succeed
                
                node_exec.result = {'parallel_results': results}
            else:
                node_exec.status = ExecutionStatus.SKIPPED
                
        except Exception as e:
            logger.error(f"Parallel execution failed for node {node.id}: {e}")
            node_exec.status = ExecutionStatus.FAILED
            node_exec.error = str(e)
    
    async def _should_retry(self, node: DAGNode, node_exec: NodeExecution) -> bool:
        """Check if node should be retried"""
        if node_exec.attempt >= node_exec.max_attempts:
            return False
        
        # Check retry policy
        if node.retry_policy:
            # Could add more sophisticated retry logic based on error type
            return True
        
        return False
    
    async def _schedule_retry(self, execution: DAGExecution, node: DAGNode,
                             node_exec: NodeExecution) -> None:
        """Schedule a node retry"""
        node_exec.attempt += 1
        node_exec.status = ExecutionStatus.RETRYING
        
        # Calculate retry delay
        if node.retry_policy:
            delay = min(
                node.retry_policy.backoff_multiplier ** (node_exec.attempt - 1),
                node.retry_policy.max_delay
            )
        else:
            delay = 2.0 ** (node_exec.attempt - 1)  # Default exponential backoff
        
        logger.info(f"Retrying node {node.id} in {delay} seconds (attempt {node_exec.attempt})")
        
        # Schedule retry after delay
        await asyncio.sleep(delay)
        
        # Reset status and reschedule
        node_exec.status = ExecutionStatus.PENDING
        execution.active_executions.discard(node.id)
    
    async def _wait_for_completion(self, execution: DAGExecution) -> None:
        """Wait for at least one active execution to complete"""
        # Simple polling implementation - in production, use event-driven approach
        while execution.active_executions:
            await asyncio.sleep(0.1)
            
            # Check for completed executions
            completed = []
            for node_id in execution.active_executions:
                node_exec = execution.node_executions.get(node_id)
                if node_exec and node_exec.status not in [ExecutionStatus.RUNNING, ExecutionStatus.RETRYING]:
                    completed.append(node_id)
            
            # Remove completed executions
            for node_id in completed:
                execution.active_executions.discard(node_id)
                if execution.node_executions[node_id].status == ExecutionStatus.SUCCESS:
                    execution.completed_nodes.add(node_id)
                elif execution.node_executions[node_id].status == ExecutionStatus.FAILED:
                    execution.failed_nodes.add(node_id)
            
            if completed:
                break
    
    def get_execution_status(self, execution_id: str) -> Optional[DAGExecution]:
        """Get the status of a DAG execution"""
        return self.active_executions.get(execution_id)

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------
    def _persist_checkpoint(self, execution: DAGExecution) -> Optional[str]:
        if not self.checkpoint_manager:
            return None
        try:
            step_results = {}
            for nid, nexec in execution.node_executions.items():
                if nexec.status in {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED}:
                    step_results[nid] = {
                        "status": nexec.status.value,
                        "result": nexec.result,
                        "error": nexec.error,
                    }

            state = ExecutionState(
                execution_id=execution.execution_id,
                current_step=len(execution.completed_nodes),
                completed_steps=list(execution.completed_nodes),
                step_results=step_results,
                variables={
                    "global_context": execution.global_context,
                    "dag_name": execution.dag.name,
                },
                timestamp=datetime.now().timestamp(),
                metadata={"kind": "dag_checkpoint"},
            )
            ckpt_id = self.checkpoint_manager.create_checkpoint(state)
            execution.last_checkpoint_id = ckpt_id
            return ckpt_id
        except Exception as exc:
            logger.debug("Failed to persist checkpoint: %s", exc)
            return None

    def _apply_checkpoint_state(self, execution: DAGExecution, state: ExecutionState) -> None:
        completed = set(state.completed_steps or [])
        execution.completed_nodes.update(completed)
        # Rehydrate node executions
        for nid in completed:
            execution.node_executions[nid] = NodeExecution(
                node_id=nid,
                status=ExecutionStatus.SUCCESS,
                start_time=datetime.now(),
                end_time=datetime.now(),
                result=(state.step_results or {}).get(nid, {}).get("result"),
                error=(state.step_results or {}).get(nid, {}).get("error"),
            )
        # Restore global context if present
        if isinstance(state.variables, dict):
            gc = state.variables.get("global_context")
            if isinstance(gc, dict):
                execution.global_context.update(gc)
    
    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running DAG execution"""
        execution = self.active_executions.get(execution_id)
        if execution and execution.status == ExecutionStatus.RUNNING:
            execution.status = ExecutionStatus.CANCELLED
            execution.end_time = datetime.now()
            
            # Cancel all active nodes
            for node_id in execution.active_executions.copy():
                node_exec = execution.node_executions.get(node_id)
                if node_exec:
                    node_exec.status = ExecutionStatus.CANCELLED
                    node_exec.end_time = datetime.now()
                execution.active_executions.discard(node_id)
            
            return True
        
        return False
    
    def get_execution_summary(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of DAG execution"""
        execution = self.active_executions.get(execution_id)
        if not execution:
            return None
        
        total_nodes = len(execution.node_executions)
        completed_nodes = len(execution.completed_nodes)
        failed_nodes = len(execution.failed_nodes)
        active_nodes = len(execution.active_executions)
        
        duration = None
        if execution.start_time:
            end_time = execution.end_time or datetime.now()
            duration = (end_time - execution.start_time).total_seconds()
        
        summary = {
            'execution_id': execution_id,
            'dag_name': execution.dag.name,
            'status': execution.status.value,
            'start_time': execution.start_time.isoformat() if execution.start_time else None,
            'end_time': execution.end_time.isoformat() if execution.end_time else None,
            'duration_seconds': duration,
            'total_nodes': total_nodes,
            'completed_nodes': completed_nodes,
            'failed_nodes': failed_nodes,
            'active_nodes': active_nodes,
            'progress_percentage': (completed_nodes / total_nodes * 100) if total_nodes > 0 else 0,
            'checkpoint_id': getattr(execution, 'last_checkpoint_id', None),
        }
        return summary


# Example usage
if __name__ == "__main__":
    import yaml
    from .dag_language import EXAMPLE_DAG_YAML
    
    async def test_dag_executor():
        # Create DAG from example
        dag = DAGDefinition.from_yaml(EXAMPLE_DAG_YAML)
        
        # Create executor
        executor = ComplexDAGExecutor()
        
        # Execute DAG
        initial_params = {
            'SUBJECT_ID': 'sub-001',
            'subjects': ['sub-001', 'sub-002', 'sub-003']
        }
        
        execution = await executor.execute_dag(dag, initial_params)
        
        # Print results
        summary = executor.get_execution_summary(execution.execution_id)
        print(f"Execution summary: {summary}")
    
    # Run test
    asyncio.run(test_dag_executor())
