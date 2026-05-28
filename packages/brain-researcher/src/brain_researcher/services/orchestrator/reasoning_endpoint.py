"""
Chain-of-Thought Reasoning API Endpoints for Brain Researcher Orchestrator (AGENT-011)

This module provides REST API endpoints for Chain-of-Thought reasoning functionality,
allowing clients to request reasoning traces and retrieve reasoning analysis.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# API Models
class ReasoningRequest(BaseModel):
    """Request model for reasoning trace generation."""
    
    query: str = Field(..., description="The query to reason about", min_length=1)
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context for reasoning")
    max_steps: Optional[int] = Field(default=10, description="Maximum number of reasoning steps", ge=1, le=20)
    reasoning_type: Optional[str] = Field(
        default=None, 
        description="Specific reasoning type (analytical, deductive, inductive, causal, comparative)"
    )


class ReasoningStepResponse(BaseModel):
    """Response model for individual reasoning step."""
    
    step_id: str
    step_number: int
    reasoning_type: str
    premise: str
    inference: str
    conclusion: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[str]
    assumptions: List[str]
    dependencies: List[str]
    timestamp: float


class ReasoningResponse(BaseModel):
    """Response model for complete reasoning trace."""
    
    trace_id: str
    query: str
    steps: List[ReasoningStepResponse]
    final_conclusion: str
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    explanation: str
    reasoning_path: List[str]
    metadata: Dict[str, Any]
    created_at: float


class ReasoningStepsRequest(BaseModel):
    """Request model for retrieving specific reasoning steps."""
    
    trace_id: str
    step_range: Optional[tuple[int, int]] = Field(default=None, description="Range of steps to retrieve (start, end)")


class ReasoningValidationResponse(BaseModel):
    """Response model for reasoning validation."""
    
    is_valid: bool
    issues: List[str]
    confidence_assessment: str
    recommendations: List[str]


# Initialize router
reasoning_router = APIRouter(prefix="/api/reasoning", tags=["reasoning"])

# In-memory storage for reasoning traces (in production, use Redis or database)
_reasoning_traces: Dict[str, Dict[str, Any]] = {}


@reasoning_router.post("/trace", response_model=ReasoningResponse, status_code=status.HTTP_201_CREATED)
async def create_reasoning_trace(
    request: ReasoningRequest,
    background_tasks: BackgroundTasks
) -> ReasoningResponse:
    """
    Generate a Chain-of-Thought reasoning trace for a query.
    
    Args:
        request: Reasoning request parameters
        background_tasks: Background tasks for async processing
        
    Returns:
        Complete reasoning trace with steps and analysis
        
    Raises:
        HTTPException: If reasoning generation fails
    """
    try:
        # Import here to avoid circular imports
        from brain_researcher.services.agent.cot_reasoning import (
            get_cot_reasoner, ReasoningType
        )
        from brain_researcher.services.agent.llm import get_llm
        
        # Initialize reasoner
        llm = get_llm()
        reasoner = get_cot_reasoner(llm)
        
        # Convert reasoning type if provided
        reasoning_type = None
        if request.reasoning_type:
            try:
                reasoning_type = ReasoningType(request.reasoning_type.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid reasoning type: {request.reasoning_type}"
                )
        
        # Generate reasoning trace
        trace = await reasoner.reason(
            query=request.query,
            context=request.context,
            reasoning_type=reasoning_type,
            max_steps=request.max_steps
        )
        
        # Convert to response format
        steps_response = [
            ReasoningStepResponse(
                step_id=step.step_id,
                step_number=step.step_number,
                reasoning_type=step.reasoning_type.value,
                premise=step.premise,
                inference=step.inference,
                conclusion=step.conclusion,
                confidence=step.confidence,
                evidence=step.evidence,
                assumptions=step.assumptions,
                dependencies=step.dependencies,
                timestamp=step.timestamp
            )
            for step in trace.steps
        ]
        
        response = ReasoningResponse(
            trace_id=trace.trace_id,
            query=trace.query,
            steps=steps_response,
            final_conclusion=trace.final_conclusion,
            overall_confidence=trace.overall_confidence,
            explanation=trace.explanation,
            reasoning_path=trace.reasoning_path,
            metadata=trace.metadata,
            created_at=trace.created_at
        )
        
        # Store trace for later retrieval
        _reasoning_traces[trace.trace_id] = {
            "trace": trace,
            "response": response,
            "created_at": datetime.now().isoformat()
        }
        
        # Schedule background validation
        background_tasks.add_task(
            _validate_reasoning_trace_background,
            trace.trace_id
        )
        
        logger.info(
            f"Generated reasoning trace {trace.trace_id} with {len(trace.steps)} steps "
            f"(confidence: {trace.overall_confidence:.3f})"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to generate reasoning trace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reasoning generation failed: {str(e)}"
        )


@reasoning_router.get("/trace/{trace_id}", response_model=ReasoningResponse)
async def get_reasoning_trace(trace_id: str) -> ReasoningResponse:
    """
    Retrieve a reasoning trace by ID.
    
    Args:
        trace_id: ID of the reasoning trace
        
    Returns:
        Complete reasoning trace
        
    Raises:
        HTTPException: If trace not found
    """
    if trace_id not in _reasoning_traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reasoning trace {trace_id} not found"
        )
    
    return _reasoning_traces[trace_id]["response"]


@reasoning_router.get("/trace/{trace_id}/steps", response_model=List[ReasoningStepResponse])
async def get_reasoning_steps(
    trace_id: str,
    start: Optional[int] = None,
    end: Optional[int] = None
) -> List[ReasoningStepResponse]:
    """
    Retrieve specific steps from a reasoning trace.
    
    Args:
        trace_id: ID of the reasoning trace
        start: Starting step number (1-indexed, optional)
        end: Ending step number (1-indexed, optional)
        
    Returns:
        List of reasoning steps
        
    Raises:
        HTTPException: If trace not found or invalid step range
    """
    if trace_id not in _reasoning_traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reasoning trace {trace_id} not found"
        )
    
    steps = _reasoning_traces[trace_id]["response"].steps
    
    # Apply step range filtering
    if start is not None or end is not None:
        start_idx = (start - 1) if start is not None else 0
        end_idx = end if end is not None else len(steps)
        
        if start_idx < 0 or end_idx > len(steps) or start_idx >= end_idx:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid step range: {start}-{end} (total steps: {len(steps)})"
            )
        
        steps = steps[start_idx:end_idx]
    
    return steps


@reasoning_router.get("/trace/{trace_id}/summary", response_model=Dict[str, Any])
async def get_reasoning_summary(trace_id: str) -> Dict[str, Any]:
    """
    Get a summary of the reasoning trace for display.
    
    Args:
        trace_id: ID of the reasoning trace
        
    Returns:
        Summary information about the reasoning trace
        
    Raises:
        HTTPException: If trace not found
    """
    if trace_id not in _reasoning_traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reasoning trace {trace_id} not found"
        )
    
    trace_data = _reasoning_traces[trace_id]
    trace = trace_data["trace"]
    
    # Import here to avoid circular imports
    from brain_researcher.services.agent.cot_reasoning import get_cot_reasoner
    from brain_researcher.services.agent.llm import get_llm
    
    llm = get_llm()
    reasoner = get_cot_reasoner(llm)
    
    summary = reasoner.get_reasoning_summary(trace)
    summary["stored_at"] = trace_data["created_at"]
    
    return summary


@reasoning_router.post("/trace/{trace_id}/validate", response_model=ReasoningValidationResponse)
async def validate_reasoning_trace(trace_id: str) -> ReasoningValidationResponse:
    """
    Validate the logical consistency of a reasoning trace.
    
    Args:
        trace_id: ID of the reasoning trace to validate
        
    Returns:
        Validation results with issues and recommendations
        
    Raises:
        HTTPException: If trace not found
    """
    if trace_id not in _reasoning_traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reasoning trace {trace_id} not found"
        )
    
    trace = _reasoning_traces[trace_id]["trace"]
    
    # Import validator
    from brain_researcher.services.agent.cot_reasoning import ReasoningValidator
    
    validator = ReasoningValidator()
    issues = validator.validate_trace(trace)
    
    # Assess confidence level
    if trace.overall_confidence >= 0.8:
        confidence_assessment = "High - reasoning is well-supported and logical"
    elif trace.overall_confidence >= 0.6:
        confidence_assessment = "Medium - reasoning is generally sound with minor concerns"
    else:
        confidence_assessment = "Low - reasoning has significant gaps or inconsistencies"
    
    # Generate recommendations
    recommendations = []
    if issues:
        recommendations.extend([
            "Review and strengthen weak reasoning steps",
            "Provide additional evidence for low-confidence conclusions",
            "Consider alternative reasoning approaches"
        ])
    else:
        recommendations.append("Reasoning trace is logically consistent")
    
    return ReasoningValidationResponse(
        is_valid=len(issues) == 0,
        issues=issues,
        confidence_assessment=confidence_assessment,
        recommendations=recommendations
    )


@reasoning_router.get("/traces", response_model=List[Dict[str, Any]])
async def list_reasoning_traces(
    limit: int = 10,
    offset: int = 0,
    query_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List stored reasoning traces with pagination and filtering.
    
    Args:
        limit: Maximum number of traces to return
        offset: Number of traces to skip
        query_filter: Filter traces by query content
        
    Returns:
        List of reasoning trace summaries
    """
    traces = []
    for trace_id, trace_data in _reasoning_traces.items():
        trace = trace_data["trace"]
        
        # Apply query filter if provided
        if query_filter and query_filter.lower() not in trace.query.lower():
            continue
        
        summary = {
            "trace_id": trace_id,
            "query": trace.query[:100] + "..." if len(trace.query) > 100 else trace.query,
            "step_count": len(trace.steps),
            "overall_confidence": trace.overall_confidence,
            "created_at": trace_data["created_at"],
            "reasoning_type": trace.metadata.get("reasoning_type", "unknown")
        }
        traces.append(summary)
    
    # Sort by creation time (most recent first)
    traces.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Apply pagination
    return traces[offset:offset + limit]


@reasoning_router.delete("/trace/{trace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reasoning_trace(trace_id: str):
    """
    Delete a reasoning trace.
    
    Args:
        trace_id: ID of the reasoning trace to delete
        
    Raises:
        HTTPException: If trace not found
    """
    if trace_id not in _reasoning_traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reasoning trace {trace_id} not found"
        )
    
    del _reasoning_traces[trace_id]
    logger.info(f"Deleted reasoning trace {trace_id}")


@reasoning_router.get("/health")
async def reasoning_health_check() -> Dict[str, Any]:
    """
    Health check endpoint for reasoning service.
    
    Returns:
        Service health status
    """
    try:
        # Test reasoning system availability
        from brain_researcher.services.agent.cot_reasoning import get_cot_reasoner
        from brain_researcher.services.agent.llm import get_llm
        
        llm = get_llm()
        reasoner = get_cot_reasoner(llm)
        
        return {
            "status": "healthy",
            "service": "chain-of-thought-reasoning",
            "active_traces": len(_reasoning_traces),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "chain-of-thought-reasoning",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Background task functions
async def _validate_reasoning_trace_background(trace_id: str):
    """Background task to validate reasoning trace."""
    try:
        if trace_id in _reasoning_traces:
            trace = _reasoning_traces[trace_id]["trace"]
            
            from brain_researcher.services.agent.cot_reasoning import ReasoningValidator
            validator = ReasoningValidator()
            
            issues = validator.validate_trace(trace)
            if issues:
                logger.warning(f"Reasoning trace {trace_id} has validation issues: {issues}")
            else:
                logger.info(f"Reasoning trace {trace_id} passed validation")
                
    except Exception as e:
        logger.error(f"Background validation failed for trace {trace_id}: {e}")


# Export router
__all__ = ["reasoning_router"]