"""Workflow Debugger

Provides step-through debugging capabilities for DAG workflow execution
with pause/resume, stepping, and execution control.
"""

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .breakpoint_manager import BreakpointManager, BreakpointType
from .inspector import Inspector
from .trace_analyzer import EventType, ExecutionEvent, TraceAnalyzer

logger = logging.getLogger(__name__)


class ExecutionState(str, Enum):
    """Possible execution states"""

    RUNNING = "running"
    PAUSED = "paused"
    STEPPING = "stepping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepType(str, Enum):
    """Types of stepping operations"""

    STEP_OVER = "step_over"
    STEP_INTO = "step_into"
    STEP_OUT = "step_out"
    CONTINUE = "continue"


@dataclass
class DAGNode:
    """Represents a node in the DAG"""

    node_id: str
    node_type: str
    function: Callable
    dependencies: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        # Remove function from serialization
        data.pop("function", None)
        return data


@dataclass
class DAGDefinition:
    """Defines a complete DAG for execution"""

    dag_id: str
    name: str
    description: str
    nodes: dict[str, DAGNode]
    entry_points: list[str] = field(default_factory=list)
    exit_points: list[str] = field(default_factory=list)
    global_parameters: dict[str, Any] = field(default_factory=dict)

    def get_execution_order(self) -> list[list[str]]:
        """Calculate topological execution order"""
        # Simple topological sort
        in_degree = dict.fromkeys(self.nodes, 0)

        # Calculate in-degrees
        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep in in_degree:
                    in_degree[node.node_id] += 1

        # Start with nodes that have no dependencies
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            level = []
            next_queue = []

            for node_id in queue:
                level.append(node_id)

                # Reduce in-degree for dependent nodes
                for other_node in self.nodes.values():
                    if node_id in other_node.dependencies:
                        in_degree[other_node.node_id] -= 1
                        if in_degree[other_node.node_id] == 0:
                            next_queue.append(other_node.node_id)

            if level:
                result.append(level)
            queue = next_queue

        return result


@dataclass
class ExecutionContext:
    """Context for DAG execution"""

    dag_definition: DAGDefinition
    session_id: str
    variables: dict[str, Any] = field(default_factory=dict)
    node_results: dict[str, Any] = field(default_factory=dict)
    execution_stack: list[str] = field(default_factory=list)
    current_node: str | None = None
    execution_order: list[list[str]] = field(default_factory=list)
    current_level: int = 0
    current_level_index: int = 0

    def __post_init__(self):
        if not self.execution_order:
            self.execution_order = self.dag_definition.get_execution_order()


@dataclass
class DebugConfig:
    """Configuration for debug session"""

    session_id: str
    dag_id: str
    enable_tracing: bool = True
    enable_profiling: bool = True
    step_on_start: bool = False
    break_on_error: bool = True
    max_trace_events: int = 10000
    auto_save_state: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class DebugSession:
    """Manages a single debugging session"""

    def __init__(
        self, session_id: str, dag_definition: DAGDefinition, debug_config: DebugConfig
    ):
        self.session_id = session_id
        self.dag_definition = dag_definition
        self.debug_config = debug_config

        # Execution state
        self.execution_state = ExecutionState.RUNNING
        self.execution_context = ExecutionContext(dag_definition, session_id)

        # Debug components
        self.breakpoint_manager = BreakpointManager()
        self.inspector = Inspector(self.execution_context)
        self.trace_analyzer = TraceAnalyzer() if debug_config.enable_tracing else None

        # Control
        self._pause_event = asyncio.Event()
        self._step_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._current_step_type: StepType | None = None

        # State
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.error: str | None = None

        # Callbacks
        self.on_node_enter: Callable | None = None
        self.on_node_exit: Callable | None = None
        self.on_pause: Callable | None = None
        self.on_step: Callable | None = None

    def set_callbacks(
        self,
        on_node_enter: Callable = None,
        on_node_exit: Callable = None,
        on_pause: Callable = None,
        on_step: Callable = None,
    ):
        """Set debug event callbacks"""
        self.on_node_enter = on_node_enter
        self.on_node_exit = on_node_exit
        self.on_pause = on_pause
        self.on_step = on_step

    async def add_breakpoint(
        self,
        node_id: str,
        condition: str | None = None,
        hit_count: int | None = None,
    ) -> str:
        """Add a breakpoint"""
        breakpoint = await self.breakpoint_manager.add_breakpoint(
            node_id=node_id,
            breakpoint_type=BreakpointType.NODE,
            condition=condition,
            hit_count=hit_count,
        )
        return breakpoint.breakpoint_id

    async def remove_breakpoint(self, breakpoint_id: str) -> bool:
        """Remove a breakpoint"""
        return await self.breakpoint_manager.remove_breakpoint(breakpoint_id)

    def get_current_state(self) -> dict:
        """Get current debugging state"""
        return {
            "session_id": self.session_id,
            "dag_id": self.dag_definition.dag_id,
            "execution_state": self.execution_state.value,
            "current_node": self.execution_context.current_node,
            "current_level": self.execution_context.current_level,
            "current_level_index": self.execution_context.current_level_index,
            "variables": self.execution_context.variables,
            "node_results": self.execution_context.node_results,
            "execution_stack": self.execution_context.execution_stack,
            "breakpoints": [
                bp.to_dict() for bp in self.breakpoint_manager.get_all_breakpoints()
            ],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "error": self.error,
        }


class WorkflowDebugger:
    """Main workflow debugger"""

    def __init__(self):
        # Active debug sessions
        self.active_sessions: dict[str, DebugSession] = {}

        # Session history
        self.session_history: list[dict] = []
        self.max_history_size = 1000

        # Global settings
        self.global_debug_enabled = True

        logger.info("Workflow debugger initialized")

    async def start_debug_session(
        self, dag_definition: DAGDefinition, debug_config: DebugConfig | None = None
    ) -> str:
        """Start a new debug session"""
        session_id = f"debug_session_{int(time.time())}_{uuid.uuid4().hex[:8]}"

        if debug_config is None:
            debug_config = DebugConfig(
                session_id=session_id, dag_id=dag_definition.dag_id
            )
        else:
            debug_config.session_id = session_id

        # Create debug session
        session = DebugSession(session_id, dag_definition, debug_config)
        session.started_at = datetime.utcnow()

        # Store session
        self.active_sessions[session_id] = session

        logger.info(
            f"Started debug session {session_id} for DAG {dag_definition.dag_id}"
        )
        return session_id

    async def stop_debug_session(self, session_id: str) -> bool:
        """Stop a debug session"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Stop execution
        session._stop_event.set()
        session.execution_state = ExecutionState.CANCELLED
        session.completed_at = datetime.utcnow()

        # Move to history
        self.session_history.append(session.get_current_state())

        # Trim history if needed
        if len(self.session_history) > self.max_history_size:
            self.session_history = self.session_history[-self.max_history_size // 2 :]

        # Remove from active sessions
        del self.active_sessions[session_id]

        logger.info(f"Stopped debug session {session_id}")
        return True

    async def debug_execute(self, session_id: str) -> dict:
        """Execute DAG with debugging"""
        if session_id not in self.active_sessions:
            raise ValueError(f"Debug session {session_id} not found")

        session = self.active_sessions[session_id]

        try:
            session.execution_state = ExecutionState.RUNNING

            # Execute DAG with debugging hooks
            await self._debug_execute_dag(session)

            if session.execution_state == ExecutionState.RUNNING:
                session.execution_state = ExecutionState.COMPLETED
                session.completed_at = datetime.utcnow()

            return session.get_current_state()

        except Exception as e:
            session.execution_state = ExecutionState.FAILED
            session.error = str(e)
            session.completed_at = datetime.utcnow()

            logger.error(f"Debug execution failed for session {session_id}: {e}")
            raise

    async def _debug_execute_dag(self, session: DebugSession):
        """Execute DAG with debugging hooks"""
        context = session.execution_context

        # Record start event
        if session.trace_analyzer:
            await session.trace_analyzer.record_event(
                ExecutionEvent(
                    event_id=str(uuid.uuid4()),
                    event_type=EventType.EXECUTION_START,
                    node_id="__dag_start__",
                    timestamp=datetime.utcnow(),
                    metadata={"dag_id": context.dag_definition.dag_id},
                )
            )

        try:
            # Execute levels in order
            for level_index, level_nodes in enumerate(context.execution_order):
                context.current_level = level_index

                # Execute nodes in parallel within level
                tasks = []
                for node_index, node_id in enumerate(level_nodes):
                    context.current_level_index = node_index
                    task = asyncio.create_task(
                        self._debug_execute_node(session, node_id)
                    )
                    tasks.append(task)

                # Wait for level completion
                await asyncio.gather(*tasks)

                # Check if execution should stop
                if session._stop_event.is_set():
                    break

        finally:
            # Record end event
            if session.trace_analyzer:
                await session.trace_analyzer.record_event(
                    ExecutionEvent(
                        event_id=str(uuid.uuid4()),
                        event_type=EventType.EXECUTION_END,
                        node_id="__dag_end__",
                        timestamp=datetime.utcnow(),
                        metadata={"dag_id": context.dag_definition.dag_id},
                    )
                )

    async def _debug_execute_node(self, session: DebugSession, node_id: str):
        """Execute a single node with debugging"""
        context = session.execution_context
        node = context.dag_definition.nodes[node_id]

        context.current_node = node_id
        context.execution_stack.append(node_id)

        try:
            # Record node entry event
            if session.trace_analyzer:
                await session.trace_analyzer.record_event(
                    ExecutionEvent(
                        event_id=str(uuid.uuid4()),
                        event_type=EventType.NODE_ENTER,
                        node_id=node_id,
                        timestamp=datetime.utcnow(),
                        metadata={"node_type": node.node_type},
                    )
                )

            # Check for breakpoints before execution
            should_break = await session.breakpoint_manager.should_break(
                node_id=node_id, context=context.variables
            )

            if should_break:
                await self._handle_breakpoint(session, node_id)

            # Call node enter callback
            if session.on_node_enter:
                await session.on_node_enter(session, node_id)

            # Execute node function
            start_time = time.time()

            try:
                # Prepare parameters
                node_params = self._prepare_node_parameters(context, node)

                # Execute node function
                if asyncio.iscoroutinefunction(node.function):
                    result = await node.function(**node_params)
                else:
                    result = node.function(**node_params)

                context.node_results[node_id] = result

                # Record success event
                if session.trace_analyzer:
                    await session.trace_analyzer.record_event(
                        ExecutionEvent(
                            event_id=str(uuid.uuid4()),
                            event_type=EventType.NODE_SUCCESS,
                            node_id=node_id,
                            timestamp=datetime.utcnow(),
                            metadata={
                                "execution_time": time.time() - start_time,
                                "result_type": type(result).__name__,
                            },
                        )
                    )

            except Exception as e:
                # Record error event
                if session.trace_analyzer:
                    await session.trace_analyzer.record_event(
                        ExecutionEvent(
                            event_id=str(uuid.uuid4()),
                            event_type=EventType.NODE_ERROR,
                            node_id=node_id,
                            timestamp=datetime.utcnow(),
                            metadata={
                                "error": str(e),
                                "traceback": traceback.format_exc(),
                            },
                        )
                    )

                # Break on error if configured
                if session.debug_config.break_on_error:
                    await self._handle_error_breakpoint(session, node_id, e)

                raise

            # Call node exit callback
            if session.on_node_exit:
                await session.on_node_exit(session, node_id)

        finally:
            # Record node exit event
            if session.trace_analyzer:
                await session.trace_analyzer.record_event(
                    ExecutionEvent(
                        event_id=str(uuid.uuid4()),
                        event_type=EventType.NODE_EXIT,
                        node_id=node_id,
                        timestamp=datetime.utcnow(),
                        metadata={},
                    )
                )

            # Remove from execution stack
            if context.execution_stack and context.execution_stack[-1] == node_id:
                context.execution_stack.pop()

    def _prepare_node_parameters(
        self, context: ExecutionContext, node: DAGNode
    ) -> dict[str, Any]:
        """Prepare parameters for node execution"""
        params = {}

        # Add global parameters
        params.update(context.dag_definition.global_parameters)

        # Add node-specific parameters
        params.update(node.parameters)

        # Add dependency results
        for dep_node_id in node.dependencies:
            if dep_node_id in context.node_results:
                # Use dependency result as parameter
                dep_result = context.node_results[dep_node_id]
                params[f"{dep_node_id}_result"] = dep_result

        # Add context variables
        for var_name, var_value in context.variables.items():
            if var_name not in params:  # Don't override explicit parameters
                params[var_name] = var_value

        return params

    async def _handle_breakpoint(self, session: DebugSession, node_id: str):
        """Handle breakpoint hit"""
        logger.info(f"Breakpoint hit at node {node_id}")

        session.execution_state = ExecutionState.PAUSED

        # Call pause callback
        if session.on_pause:
            await session.on_pause(session, node_id)

        # Wait for continue or step command
        session._pause_event.clear()
        await session._pause_event.wait()

        # Reset execution state based on step type
        if session._current_step_type in [
            StepType.STEP_OVER,
            StepType.STEP_INTO,
            StepType.STEP_OUT,
        ]:
            session.execution_state = ExecutionState.STEPPING
        else:
            session.execution_state = ExecutionState.RUNNING

    async def _handle_error_breakpoint(
        self, session: DebugSession, node_id: str, error: Exception
    ):
        """Handle error breakpoint"""
        logger.info(f"Error breakpoint hit at node {node_id}: {error}")

        session.execution_state = ExecutionState.PAUSED

        # Add error to context for inspection
        session.execution_context.variables["__last_error__"] = {
            "error": str(error),
            "type": type(error).__name__,
            "node_id": node_id,
            "traceback": traceback.format_exc(),
        }

        # Call pause callback
        if session.on_pause:
            await session.on_pause(session, node_id)

        # Wait for continue or step command
        session._pause_event.clear()
        await session._pause_event.wait()

    # Step control methods

    async def step_over(self, session_id: str) -> bool:
        """Execute current node and pause at next node"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        session._current_step_type = StepType.STEP_OVER
        session.execution_state = ExecutionState.STEPPING

        # Resume execution
        session._pause_event.set()

        if session.on_step:
            await session.on_step(session, StepType.STEP_OVER)

        return True

    async def step_into(self, session_id: str) -> bool:
        """Step into sub-DAG or function"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        session._current_step_type = StepType.STEP_INTO
        session.execution_state = ExecutionState.STEPPING

        session._pause_event.set()

        if session.on_step:
            await session.on_step(session, StepType.STEP_INTO)

        return True

    async def step_out(self, session_id: str) -> bool:
        """Complete current scope and return to parent"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        session._current_step_type = StepType.STEP_OUT
        session.execution_state = ExecutionState.STEPPING

        session._pause_event.set()

        if session.on_step:
            await session.on_step(session, StepType.STEP_OUT)

        return True

    async def continue_execution(self, session_id: str) -> bool:
        """Continue execution without stepping"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        session._current_step_type = StepType.CONTINUE
        session.execution_state = ExecutionState.RUNNING

        session._pause_event.set()

        return True

    async def pause_execution(self, session_id: str) -> bool:
        """Pause execution at next opportunity"""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Add temporary breakpoint at next node
        context = session.execution_context
        if context.current_level < len(context.execution_order):
            current_level_nodes = context.execution_order[context.current_level]
            if context.current_level_index + 1 < len(current_level_nodes):
                next_node = current_level_nodes[context.current_level_index + 1]
                await session.add_breakpoint(next_node)
            elif context.current_level + 1 < len(context.execution_order):
                next_level_nodes = context.execution_order[context.current_level + 1]
                if next_level_nodes:
                    await session.add_breakpoint(next_level_nodes[0])

        return True

    # Session management

    def get_active_sessions(self) -> list[str]:
        """Get list of active session IDs"""
        return list(self.active_sessions.keys())

    def get_session_info(self, session_id: str) -> dict | None:
        """Get information about a session"""
        if session_id in self.active_sessions:
            return self.active_sessions[session_id].get_current_state()
        return None

    def get_session_history(self, limit: int = 50) -> list[dict]:
        """Get session history"""
        return self.session_history[-limit:] if self.session_history else []
