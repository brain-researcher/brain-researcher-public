"""Debugger Endpoints

FastAPI endpoints for workflow debugging tools including step-through debugging,
breakpoint management, variable inspection, trace analysis, and performance profiling.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from ..agent.debugger.workflow_debugger import WorkflowDebugger, DebugConfig, DAGDefinition, StepType
from ..agent.debugger.breakpoint_manager import BreakpointManager, BreakpointType, DataChangeType
from ..agent.debugger.inspector import Inspector, VariableScope
from ..agent.debugger.trace_analyzer import TraceAnalyzer
from ..agent.debugger.profiler import WorkflowProfiler, ProfilingType
from .models import ErrorResponse


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debug", tags=["debugging"])

# Global debugger instances
workflow_debugger: Optional[WorkflowDebugger] = None
trace_analyzer: Optional[TraceAnalyzer] = None
workflow_profiler: Optional[WorkflowProfiler] = None


# Request/Response Models

class StartDebugSessionRequest(BaseModel):
    """Request to start a debug session"""
    dag_id: str = Field(..., description="DAG identifier")
    dag_definition: Dict[str, Any] = Field(..., description="DAG definition")
    enable_tracing: bool = Field(True, description="Enable execution tracing")
    enable_profiling: bool = Field(True, description="Enable performance profiling")
    step_on_start: bool = Field(False, description="Pause on first node")
    break_on_error: bool = Field(True, description="Break on errors")


class DebugSessionResponse(BaseModel):
    """Debug session information"""
    session_id: str
    dag_id: str
    execution_state: str
    current_node: Optional[str]
    current_level: int
    current_level_index: int
    variables: Dict[str, Any]
    node_results: Dict[str, Any]
    execution_stack: List[str]
    breakpoints: List[Dict[str, Any]]
    started_at: Optional[str]
    completed_at: Optional[str]
    error: Optional[str]


class AddBreakpointRequest(BaseModel):
    """Request to add a breakpoint"""
    node_id: Optional[str] = Field(None, description="Node ID for breakpoint")
    breakpoint_type: str = Field("node", description="Breakpoint type")
    condition: Optional[str] = Field(None, description="Breakpoint condition")
    variable_name: Optional[str] = Field(None, description="Variable name for data breakpoints")
    change_type: str = Field("change", description="Data change type")
    hit_count: Optional[int] = Field(None, description="Hit count threshold")
    description: str = Field("", description="Breakpoint description")


class AddBreakpointResponse(BaseModel):
    """Response for adding breakpoint"""
    breakpoint_id: str
    message: str


class VariableInspectionRequest(BaseModel):
    """Request to inspect variables"""
    variable_name: Optional[str] = Field(None, description="Specific variable name")
    scope: str = Field("local", description="Variable scope")


class ModifyVariableRequest(BaseModel):
    """Request to modify a variable"""
    variable_name: str = Field(..., description="Variable name")
    new_value: Any = Field(..., description="New variable value")
    scope: str = Field("local", description="Variable scope")


class EvaluateExpressionRequest(BaseModel):
    """Request to evaluate an expression"""
    expression: str = Field(..., description="Expression to evaluate")


class StartTracingRequest(BaseModel):
    """Request to start trace recording"""
    dag_id: str = Field(..., description="DAG identifier")
    session_id: str = Field(..., description="Debug session ID")


class StartProfilingRequest(BaseModel):
    """Request to start profiling"""
    dag_id: str = Field(..., description="DAG identifier")
    profiling_types: List[str] = Field(["cpu", "memory"], description="Types of profiling")


# Dependency injection

def get_workflow_debugger():
    """Get workflow debugger dependency"""
    global workflow_debugger
    if workflow_debugger is None:
        workflow_debugger = WorkflowDebugger()
    return workflow_debugger


def get_trace_analyzer():
    """Get trace analyzer dependency"""
    global trace_analyzer
    if trace_analyzer is None:
        trace_analyzer = TraceAnalyzer()
    return trace_analyzer


def get_workflow_profiler():
    """Get workflow profiler dependency"""
    global workflow_profiler
    if workflow_profiler is None:
        workflow_profiler = WorkflowProfiler()
    return workflow_profiler


# Debug Session Endpoints

@router.post("/sessions/start", response_model=Dict[str, str])
async def start_debug_session(
    request: StartDebugSessionRequest,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Start a new debug session"""
    try:
        # Convert DAG definition (simplified)
        dag_def = DAGDefinition(
            dag_id=request.dag_id,
            name=request.dag_definition.get("name", request.dag_id),
            description=request.dag_definition.get("description", ""),
            nodes={},  # Would need proper conversion from request
            entry_points=request.dag_definition.get("entry_points", []),
            exit_points=request.dag_definition.get("exit_points", []),
            global_parameters=request.dag_definition.get("global_parameters", {})
        )

        # Create debug config
        debug_config = DebugConfig(
            session_id="",  # Will be set by debugger
            dag_id=request.dag_id,
            enable_tracing=request.enable_tracing,
            enable_profiling=request.enable_profiling,
            step_on_start=request.step_on_start,
            break_on_error=request.break_on_error
        )

        session_id = await debugger.start_debug_session(dag_def, debug_config)

        return {"session_id": session_id, "message": "Debug session started"}

    except Exception as e:
        logger.error(f"Failed to start debug session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}", response_model=DebugSessionResponse)
async def get_debug_session(
    session_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Get debug session information"""
    try:
        session_info = debugger.get_session_info(session_id)

        if not session_info:
            raise HTTPException(status_code=404, detail="Debug session not found")

        return DebugSessionResponse(**session_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get debug session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def stop_debug_session(
    session_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Stop a debug session"""
    try:
        success = await debugger.stop_debug_session(session_id)

        if success:
            return {"message": "Debug session stopped"}
        else:
            raise HTTPException(status_code=404, detail="Debug session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop debug session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_debug_sessions(
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """List all active debug sessions"""
    try:
        sessions = debugger.get_active_sessions()
        return {"active_sessions": sessions, "count": len(sessions)}

    except Exception as e:
        logger.error(f"Failed to list debug sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Execution Control Endpoints

@router.post("/sessions/{session_id}/execute")
async def execute_with_debugging(
    session_id: str,
    background_tasks: BackgroundTasks,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Execute DAG with debugging"""
    try:
        # Run execution in background
        background_tasks.add_task(debugger.debug_execute, session_id)

        return {"message": "Debug execution started"}

    except Exception as e:
        logger.error(f"Failed to start debug execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/step/{step_type}")
async def step_execution(
    session_id: str,
    step_type: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Step through execution"""
    try:
        if step_type == "over":
            success = await debugger.step_over(session_id)
        elif step_type == "into":
            success = await debugger.step_into(session_id)
        elif step_type == "out":
            success = await debugger.step_out(session_id)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid step type: {step_type}")

        if success:
            return {"message": f"Step {step_type} executed"}
        else:
            raise HTTPException(status_code=404, detail="Debug session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to step execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/continue")
async def continue_execution(
    session_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Continue execution"""
    try:
        success = await debugger.continue_execution(session_id)

        if success:
            return {"message": "Execution continued"}
        else:
            raise HTTPException(status_code=404, detail="Debug session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to continue execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/pause")
async def pause_execution(
    session_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Pause execution"""
    try:
        success = await debugger.pause_execution(session_id)

        if success:
            return {"message": "Execution paused"}
        else:
            raise HTTPException(status_code=404, detail="Debug session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Breakpoint Management Endpoints

@router.post("/sessions/{session_id}/breakpoints", response_model=AddBreakpointResponse)
async def add_breakpoint(
    session_id: str,
    request: AddBreakpointRequest,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Add a breakpoint"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]

        breakpoint_id = await session.add_breakpoint(
            node_id=request.node_id,
            condition=request.condition,
            hit_count=request.hit_count
        )

        return AddBreakpointResponse(
            breakpoint_id=breakpoint_id,
            message="Breakpoint added successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add breakpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}/breakpoints/{breakpoint_id}")
async def remove_breakpoint(
    session_id: str,
    breakpoint_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Remove a breakpoint"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]
        success = await session.remove_breakpoint(breakpoint_id)

        if success:
            return {"message": "Breakpoint removed"}
        else:
            raise HTTPException(status_code=404, detail="Breakpoint not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove breakpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/breakpoints")
async def list_breakpoints(
    session_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """List all breakpoints for a session"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]
        breakpoints = session.breakpoint_manager.get_all_breakpoints()

        return {
            "breakpoints": [bp.to_dict() for bp in breakpoints],
            "count": len(breakpoints)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list breakpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Variable Inspection Endpoints

@router.get("/sessions/{session_id}/variables")
async def inspect_variables(
    session_id: str,
    variable_name: Optional[str] = None,
    scope: str = "local",
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Inspect variables"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]
        inspector = session.inspector

        try:
            variable_scope = VariableScope(scope)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}")

        if variable_name:
            # Inspect specific variable
            var_info = await inspector.inspect_variable(variable_name, variable_scope)
            if var_info:
                return {"variable": var_info.to_dict()}
            else:
                raise HTTPException(status_code=404, detail="Variable not found")
        else:
            # Inspect all variables
            all_vars = inspector.inspect_all_variables()
            return {
                "variables": {
                    scope_name.value: {
                        name: var.to_dict() for name, var in scope_vars.items()
                    }
                    for scope_name, scope_vars in all_vars.items()
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to inspect variables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/variables/modify")
async def modify_variable(
    session_id: str,
    request: ModifyVariableRequest,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Modify a variable value"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]
        inspector = session.inspector

        try:
            variable_scope = VariableScope(request.scope)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {request.scope}")

        success = inspector.modify_variable(
            request.variable_name,
            request.new_value,
            variable_scope
        )

        if success:
            return {"message": f"Variable {request.variable_name} modified"}
        else:
            raise HTTPException(status_code=404, detail="Variable not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to modify variable: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/evaluate")
async def evaluate_expression(
    session_id: str,
    request: EvaluateExpressionRequest,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Evaluate an expression"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]
        inspector = session.inspector

        result = inspector.evaluate_expression(request.expression)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to evaluate expression: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/call-stack")
async def get_call_stack(
    session_id: str,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Get current call stack"""
    try:
        if session_id not in debugger.active_sessions:
            raise HTTPException(status_code=404, detail="Debug session not found")

        session = debugger.active_sessions[session_id]
        inspector = session.inspector

        call_stack = inspector.get_call_stack()

        return {
            "call_stack": [frame.to_dict() for frame in call_stack],
            "depth": len(call_stack)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get call stack: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Trace Analysis Endpoints

@router.post("/traces/start", response_model=Dict[str, str])
async def start_trace(
    request: StartTracingRequest,
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer)
):
    """Start trace recording"""
    try:
        trace_id = await analyzer.start_trace(request.dag_id, request.session_id)

        return {"trace_id": trace_id, "message": "Trace recording started"}

    except Exception as e:
        logger.error(f"Failed to start trace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/traces/{trace_id}/end")
async def end_trace(
    trace_id: str,
    success: bool = True,
    error_message: Optional[str] = None,
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer)
):
    """End trace recording"""
    try:
        result = await analyzer.end_trace(trace_id, success, error_message)

        if result:
            return {"message": "Trace recording ended"}
        else:
            raise HTTPException(status_code=404, detail="Trace not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end trace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces/{trace_id}")
async def get_trace(
    trace_id: str,
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer)
):
    """Get trace data"""
    try:
        trace = await analyzer.get_trace(trace_id)

        if trace:
            return trace.to_dict()
        else:
            raise HTTPException(status_code=404, detail="Trace not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces/{trace_id}/analyze")
async def analyze_trace(
    trace_id: str,
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer)
):
    """Analyze execution trace"""
    try:
        analysis = await analyzer.analyze_trace(trace_id)

        if analysis:
            return analysis.to_dict()
        else:
            raise HTTPException(status_code=404, detail="Trace not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze trace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/traces/{trace_id}/replay")
async def replay_trace(
    trace_id: str,
    speed: float = 1.0,
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer)
):
    """Start trace replay"""
    try:
        replay_id = await analyzer.replay_trace(trace_id, speed)

        if replay_id:
            return {"replay_id": replay_id, "message": "Trace replay started"}
        else:
            raise HTTPException(status_code=404, detail="Trace not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start trace replay: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/replays/{replay_id}/control")
async def control_replay(
    replay_id: str,
    action: str,
    speed: Optional[float] = None,
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer)
):
    """Control trace replay"""
    try:
        kwargs = {}
        if speed is not None:
            kwargs['speed'] = speed

        success = await analyzer.control_replay(replay_id, action, **kwargs)

        if success:
            return {"message": f"Replay {action} executed"}
        else:
            return {"message": f"Replay {action} failed"}

    except Exception as e:
        logger.error(f"Failed to control replay: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Profiling Endpoints

@router.post("/profiling/start", response_model=Dict[str, str])
async def start_profiling(
    request: StartProfilingRequest,
    profiler: WorkflowProfiler = Depends(get_workflow_profiler)
):
    """Start performance profiling"""
    try:
        profiling_types = set()
        for prof_type in request.profiling_types:
            try:
                profiling_types.add(ProfilingType(prof_type))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid profiling type: {prof_type}")

        session_id = await profiler.start_profiling_session(request.dag_id, profiling_types)

        return {"session_id": session_id, "message": "Profiling started"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start profiling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiling/{session_id}/end")
async def end_profiling(
    session_id: str,
    profiler: WorkflowProfiler = Depends(get_workflow_profiler)
):
    """End performance profiling"""
    try:
        success = await profiler.end_profiling_session(session_id)

        if success:
            return {"message": "Profiling ended"}
        else:
            raise HTTPException(status_code=404, detail="Profiling session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end profiling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiling/{session_id}/analyze")
async def analyze_performance(
    session_id: str,
    profiler: WorkflowProfiler = Depends(get_workflow_profiler)
):
    """Analyze performance profiling data"""
    try:
        analysis = await profiler.analyze_performance(session_id)

        if analysis:
            return analysis.to_dict()
        else:
            raise HTTPException(status_code=404, detail="Profiling session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiling/{session_id}/flamegraph")
async def get_flamegraph(
    session_id: str,
    profiler: WorkflowProfiler = Depends(get_workflow_profiler)
):
    """Generate flamegraph data"""
    try:
        flamegraph_data = await profiler.generate_flamegraph(session_id)

        if flamegraph_data:
            return flamegraph_data
        else:
            raise HTTPException(status_code=404, detail="Profiling session not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate flamegraph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiling/{session_id}/optimization")
async def get_optimization_opportunities(
    session_id: str,
    profiler: WorkflowProfiler = Depends(get_workflow_profiler)
):
    """Get optimization opportunities"""
    try:
        opportunities = await profiler.find_optimization_opportunities(session_id)

        return {
            "opportunities": opportunities,
            "count": len(opportunities)
        }

    except Exception as e:
        logger.error(f"Failed to get optimization opportunities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Statistics and Status Endpoints

@router.get("/status")
async def get_debugger_status(
    debugger: WorkflowDebugger = Depends(get_workflow_debugger),
    analyzer: TraceAnalyzer = Depends(get_trace_analyzer),
    profiler: WorkflowProfiler = Depends(get_workflow_profiler)
):
    """Get overall debugger system status"""
    try:
        return {
            "active_debug_sessions": len(debugger.get_active_sessions()),
            "debug_session_history": len(debugger.get_session_history()),
            "trace_summary": analyzer.get_trace_summary(),
            "profiler_statistics": profiler.get_profiler_statistics(),
            "system_status": "healthy"
        }

    except Exception as e:
        logger.error(f"Failed to get debugger status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_debug_history(
    limit: int = 50,
    debugger: WorkflowDebugger = Depends(get_workflow_debugger)
):
    """Get debug session history"""
    try:
        history = debugger.get_session_history(limit)

        return {
            "history": history,
            "count": len(history)
        }

    except Exception as e:
        logger.error(f"Failed to get debug history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
