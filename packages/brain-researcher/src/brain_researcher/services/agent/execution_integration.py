"""
Integration of execution status tracking with LangGraph state machine.

Provides seamless status tracking for the Brain Researcher agent execution.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage

from brain_researcher.services.agent.execution_status import (
    AsyncExecutionTracker,
    ExecutionStatus,
    ExecutionStep,
    ExecutionTracker,
)
from brain_researcher.services.agent.status_updates import status_service

logger = logging.getLogger(__name__)


class ExecutionState(TypedDict):
    """Extended state with execution tracking."""
    
    messages: List[BaseMessage]
    plan: Optional[Dict[str, Any]]
    execution_id: Optional[str]
    tracker: Optional[ExecutionTracker]
    status: Optional[str]
    progress: Optional[float]


class TrackedExecution:
    """Wrapper for tracked execution in LangGraph."""
    
    def __init__(
        self,
        execution_id: Optional[str] = None,
        use_async: bool = True,
        enable_updates: bool = True
    ):
        """
        Initialize tracked execution.
        
        Args:
            execution_id: Optional execution ID
            use_async: Use async tracker
            enable_updates: Enable real-time updates
        """
        self.use_async = use_async
        self.enable_updates = enable_updates
        
        # Create tracker
        if use_async:
            self.tracker = AsyncExecutionTracker(execution_id=execution_id)
        else:
            self.tracker = ExecutionTracker(execution_id=execution_id)
            
        self.execution_id = self.tracker.execution_id
        
        # Register with status service if updates enabled
        if enable_updates and use_async:
            asyncio.create_task(
                status_service.register_execution(self.execution_id, self.tracker)
            )
            
    async def track_planning(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Track planning phase.
        
        Args:
            state: Current state
            
        Returns:
            Updated state
        """
        # Add planning step
        step = self.tracker.add_step(
            name="Planning",
            description="Analyzing query and creating execution plan",
            estimated_duration=5.0
        )
        
        # Start execution
        self.tracker.start_execution()
        
        if self.use_async:
            await self.tracker.start_step_async()
        else:
            self.tracker.start_step()
            
        # Update state
        state["execution_id"] = self.execution_id
        state["tracker"] = self.tracker
        state["status"] = "planning"
        
        return state
        
    async def track_plan_complete(
        self,
        state: Dict[str, Any],
        plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Track plan completion.
        
        Args:
            state: Current state
            plan: Generated plan
            
        Returns:
            Updated state
        """
        # Add steps from plan
        if "steps" in plan:
            for i, plan_step in enumerate(plan["steps"]):
                self.tracker.add_step(
                    name=plan_step.get("tool", f"Step {i+1}"),
                    description=plan_step.get("description", ""),
                    estimated_duration=plan_step.get("estimated_duration", 10.0),
                    metadata=plan_step
                )
                
        # Complete planning step
        if self.use_async:
            await self.tracker.complete_step_async(
                step_index=0,
                result={"plan_steps": len(plan.get("steps", []))}
            )
        else:
            self.tracker.complete_step(
                step_index=0,
                result={"plan_steps": len(plan.get("steps", []))}
            )
            
        state["status"] = "executing"
        return state
        
    async def track_tool_execution(
        self,
        state: Dict[str, Any],
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Track tool execution.
        
        Args:
            state: Current state
            tool_name: Tool being executed
            tool_input: Tool input parameters
            
        Returns:
            Updated state
        """
        # Find or create step for this tool
        current_step = None
        for i, step in enumerate(self.tracker.steps):
            if step.name == tool_name and step.status == "waiting":
                current_step = step
                if self.use_async:
                    await self.tracker.start_step_async(i)
                else:
                    self.tracker.start_step(i)
                break
                
        if not current_step:
            # Create new step if not in plan
            step = self.tracker.add_step(
                name=tool_name,
                description=f"Executing {tool_name}",
                metadata={"input": tool_input}
            )
            if self.use_async:
                await self.tracker.start_step_async(len(self.tracker.steps) - 1)
            else:
                self.tracker.start_step(len(self.tracker.steps) - 1)
                
        state["status"] = f"executing_{tool_name}"
        return state
        
    async def track_tool_progress(
        self,
        progress: float,
        message: Optional[str] = None
    ):
        """
        Update tool execution progress.
        
        Args:
            progress: Progress percentage
            message: Optional progress message
        """
        if self.use_async:
            await self.tracker.update_step_progress_async(
                progress=progress,
                message=message
            )
        else:
            self.tracker.update_step_progress(
                progress=progress,
                message=message
            )
            
    async def track_tool_complete(
        self,
        state: Dict[str, Any],
        tool_name: str,
        result: Any,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Track tool completion.
        
        Args:
            state: Current state
            tool_name: Tool that completed
            result: Tool result
            error: Optional error
            
        Returns:
            Updated state
        """
        if self.use_async:
            await self.tracker.complete_step_async(
                error=error,
                result=result
            )
        else:
            self.tracker.complete_step(
                error=error,
                result=result
            )
            
        # Update progress in state
        state["progress"] = self.tracker.overall_progress
        
        return state
        
    async def track_review(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Track review phase.
        
        Args:
            state: Current state
            
        Returns:
            Updated state
        """
        # Add review step if not exists
        review_step_exists = any(
            step.name == "Review" for step in self.tracker.steps
        )
        
        if not review_step_exists:
            step = self.tracker.add_step(
                name="Review",
                description="Reviewing and validating results",
                estimated_duration=3.0
            )
            
        # Start review
        if self.use_async:
            await self.tracker.start_step_async()
        else:
            self.tracker.start_step()
            
        state["status"] = "reviewing"
        return state
        
    async def track_completion(
        self,
        state: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Track execution completion.
        
        Args:
            state: Current state
            result: Final result
            error: Optional error
            
        Returns:
            Updated state
        """
        # Complete any running steps
        for i, step in enumerate(self.tracker.steps):
            if step.status == "running":
                if self.use_async:
                    await self.tracker.complete_step_async(i)
                else:
                    self.tracker.complete_step(i)
                    
        # Complete execution
        self.tracker.complete_execution(error=error, result=result)
        
        state["status"] = "completed" if not error else "failed"
        state["progress"] = 100.0 if not error else self.tracker.overall_progress
        
        # Unregister from status service
        if self.enable_updates and self.use_async:
            await status_service.unregister_execution(self.execution_id)
            
        return state
        
    def get_status(self) -> Dict[str, Any]:
        """Get current execution status."""
        return self.tracker.get_status()
        
    def get_progress_summary(self) -> Dict[str, Any]:
        """Get progress summary."""
        return self.tracker.get_progress_summary()


def create_tracked_node(node_func):
    """
    Decorator to add execution tracking to a LangGraph node.
    
    Example:
    ```python
    @create_tracked_node
    async def plan_node(state: State) -> State:
        # Node implementation
        return state
    ```
    """
    async def tracked_wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
        """Wrapped node with tracking."""
        # Get or create tracker
        tracker = state.get("tracker")
        if not tracker:
            tracked_exec = TrackedExecution()
            state = await tracked_exec.track_planning(state)
            tracker = tracked_exec.tracker
            
        # Get node name
        node_name = node_func.__name__.replace("_node", "").title()
        
        # Track node start
        step = tracker.add_step(
            name=node_name,
            description=f"Executing {node_name}",
            estimated_duration=10.0
        )
        
        if hasattr(tracker, 'start_step_async'):
            await tracker.start_step_async()
        else:
            tracker.start_step()
            
        try:
            # Execute original node
            result = await node_func(state)
            
            # Track completion
            if hasattr(tracker, 'complete_step_async'):
                await tracker.complete_step_async()
            else:
                tracker.complete_step()
                
            return result
            
        except Exception as e:
            # Track error
            if hasattr(tracker, 'complete_step_async'):
                await tracker.complete_step_async(error=str(e))
            else:
                tracker.complete_step(error=str(e))
            raise
            
    return tracked_wrapper


class ExecutionMonitor:
    """Monitor for tracking multiple executions."""
    
    def __init__(self):
        """Initialize execution monitor."""
        self.active_executions: Dict[str, TrackedExecution] = {}
        
    def start_execution(
        self,
        execution_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TrackedExecution:
        """
        Start a new tracked execution.
        
        Args:
            execution_id: Optional execution ID
            metadata: Optional metadata
            
        Returns:
            TrackedExecution instance
        """
        tracked = TrackedExecution(execution_id=execution_id)
        
        if metadata:
            tracked.tracker.metadata.update(metadata)
            
        self.active_executions[tracked.execution_id] = tracked
        
        return tracked
        
    def get_execution(self, execution_id: str) -> Optional[TrackedExecution]:
        """
        Get tracked execution by ID.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            TrackedExecution or None
        """
        return self.active_executions.get(execution_id)
        
    def list_executions(self) -> List[Dict[str, Any]]:
        """
        List all active executions.
        
        Returns:
            List of execution summaries
        """
        return [
            {
                "execution_id": exec_id,
                "status": tracked.tracker.status,
                "progress": tracked.tracker.overall_progress,
                "started_at": tracked.tracker.started_at,
                "current_step": tracked.tracker.steps[tracked.tracker.current_step_index].name
                    if tracked.tracker.current_step_index is not None else None
            }
            for exec_id, tracked in self.active_executions.items()
        ]
        
    def cleanup_completed(self):
        """Remove completed executions."""
        completed = [
            exec_id for exec_id, tracked in self.active_executions.items()
            if tracked.tracker.status in [
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED
            ]
        ]
        
        for exec_id in completed:
            del self.active_executions[exec_id]
            
            
# Global monitor instance
execution_monitor = ExecutionMonitor()


# Example integration with LangGraph
async def tracked_graph_execution(query: str) -> Dict[str, Any]:
    """
    Example of executing a LangGraph with tracking.
    
    Args:
        query: User query
        
    Returns:
        Execution result with tracking info
    """
    from brain_researcher.services.agent.graph import CoreStateMachine
    
    # Create state machine
    state_machine = CoreStateMachine()
    
    # Start tracked execution
    tracked = execution_monitor.start_execution(
        metadata={"query": query, "timestamp": time.time()}
    )
    
    # Create initial state with tracker
    initial_state = {
        "messages": [{"role": "user", "content": query}],
        "tracker": tracked.tracker,
        "execution_id": tracked.execution_id
    }
    
    # Track planning
    initial_state = await tracked.track_planning(initial_state)
    
    try:
        # Run the graph
        result = await state_machine.run_async(initial_state)
        
        # Track completion
        final_state = await tracked.track_completion(
            result,
            result=result.get("output")
        )
        
        return {
            "result": result,
            "execution_id": tracked.execution_id,
            "status": tracked.get_status(),
            "summary": tracked.get_progress_summary()
        }
        
    except Exception as e:
        # Track failure
        await tracked.track_completion(
            initial_state,
            error=str(e)
        )
        raise