"""Feedback endpoints for A/B testing and RL data collection."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
import numpy as np
import redis

from ...feedback.ab_testing import ABTestingFramework
from ...feedback.experiment_manager import ExperimentManager
from ...feedback.metrics_collector import MetricsCollector
from ...feedback.reward_tracker import RewardTracker
from ...agent.rl.training_pipeline import RLTrainingPipeline, TrainingConfig, TrainingMode
from ...agent.bandits.tool_selector import BanditToolSelector, TaskContext, TaskType

logger = logging.getLogger(__name__)

# Initialize components
redis_client = redis.Redis(decode_responses=True)
ab_framework = ABTestingFramework(redis_client)
metrics_collector = MetricsCollector(redis_client)
reward_tracker = RewardTracker(redis_client)
experiment_manager = ExperimentManager(ab_framework, redis_client)

# Router
router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


# Pydantic models for request/response
class ExperimentCreateRequest(BaseModel):
    name: str = Field(..., description="Experiment name")
    description: str = Field(..., description="Experiment description")
    variants: List[str] = Field(..., description="List of variant names")
    allocation: Dict[str, float] = Field(..., description="Allocation ratios for variants")
    metrics: List[str] = Field(..., description="Metrics to track")
    sample_size: Optional[int] = Field(None, description="Target sample size")
    significance_level: float = Field(0.05, description="Statistical significance level")


class ExperimentAssignmentRequest(BaseModel):
    user_id: str = Field(..., description="User ID for assignment")
    experiment_id: str = Field(..., description="Experiment ID")


class MetricsTrackingRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    event_type: str = Field(..., description="Event type")
    experiment_id: Optional[str] = Field(None, description="Experiment ID")
    variant: Optional[str] = Field(None, description="Experiment variant")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    value: Optional[float] = Field(None, description="Event value")
    session_id: Optional[str] = Field(None, description="Session ID")


class RewardTrackingRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    session_id: str = Field(..., description="Session ID")
    state: Dict[str, Any] = Field(..., description="Current state")
    action: str = Field(..., description="Action taken")
    reward: Optional[float] = Field(None, description="Reward value")
    next_state: Optional[Dict[str, Any]] = Field(None, description="Next state")
    reward_type: str = Field("custom", description="Type of reward")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    terminal: bool = Field(False, description="Whether this is a terminal state")
    execution_result: Optional[Dict[str, Any]] = Field(None, description="Execution result")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    execution_cost: Optional[float] = Field(None, description="Execution cost")
    quality_metrics: Optional[Dict[str, float]] = Field(None, description="Quality metrics")
    user_feedback: Optional[Dict[str, Any]] = Field(None, description="User feedback")


class RLTrainingRequest(BaseModel):
    mode: str = Field("iql", description="Training mode (iql, cql, both)")
    epochs: int = Field(50, description="Number of training epochs")
    batch_size: int = Field(256, description="Training batch size")
    learning_rate: float = Field(0.0003, description="Learning rate")


class ToolSelectionRequest(BaseModel):
    task_type: str = Field(..., description="Type of task")
    data_size: float = Field(..., description="Data size in MB")
    data_complexity: float = Field(0.5, description="Data complexity (0-1)")
    available_memory: float = Field(8000, description="Available memory in MB")
    available_cpu_cores: int = Field(4, description="Available CPU cores")
    time_constraints: float = Field(3600, description="Time constraints in seconds")
    quality_requirements: float = Field(0.7, description="Quality requirements (0-1)")
    user_expertise: float = Field(0.5, description="User expertise level (0-1)")
    previous_tools_used: List[str] = Field([], description="Previously used tools")
    session_history: List[Dict[str, Any]] = Field([], description="Session history")
    user_preferences: Dict[str, Any] = Field({}, description="User preferences")
    available_tools: Optional[List[str]] = Field(None, description="Available tools")
    exploit: bool = Field(False, description="Whether to exploit or explore")


class ToolPerformanceRequest(BaseModel):
    task_type: str = Field(..., description="Type of task")
    tool_name: str = Field(..., description="Tool that was used")
    performance_metrics: Dict[str, Any] = Field(..., description="Performance metrics")
    execution_time: float = Field(..., description="Actual execution time")
    success: bool = Field(..., description="Whether execution was successful")
    data_size: float = Field(..., description="Data size in MB")
    data_complexity: float = Field(0.5, description="Data complexity (0-1)")
    available_memory: float = Field(8000, description="Available memory in MB")
    available_cpu_cores: int = Field(4, description="Available CPU cores")
    time_constraints: float = Field(3600, description="Time constraints in seconds")
    quality_requirements: float = Field(0.7, description="Quality requirements (0-1)")
    user_expertise: float = Field(0.5, description="User expertise level (0-1)")


# A/B Testing Endpoints

@router.post("/experiments", response_model=Dict[str, Any])
async def create_experiment(request: ExperimentCreateRequest):
    """Create a new A/B test experiment."""
    try:
        experiment = ab_framework.create_experiment(
            name=request.name,
            description=request.description,
            variants=request.variants,
            allocation=request.allocation,
            metrics=request.metrics,
            sample_size=request.sample_size,
            significance_level=request.significance_level
        )
        
        return {
            "experiment_id": experiment.id,
            "name": experiment.name,
            "status": experiment.status.value,
            "created_at": experiment.created_at.isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error creating experiment: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experiments/{experiment_id}/start")
async def start_experiment(experiment_id: str):
    """Start an A/B test experiment."""
    try:
        ab_framework.start_experiment(experiment_id)
        return {"status": "started", "experiment_id": experiment_id}
    
    except Exception as e:
        logger.error(f"Error starting experiment {experiment_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experiments/{experiment_id}/stop")
async def stop_experiment(experiment_id: str):
    """Stop an A/B test experiment."""
    try:
        ab_framework.stop_experiment(experiment_id)
        return {"status": "stopped", "experiment_id": experiment_id}
    
    except Exception as e:
        logger.error(f"Error stopping experiment {experiment_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experiments/assign", response_model=Dict[str, Any])
async def assign_user_to_experiment(request: ExperimentAssignmentRequest):
    """Assign user to experiment variant."""
    try:
        variant = ab_framework.assign_user(request.user_id, request.experiment_id)
        
        return {
            "user_id": request.user_id,
            "experiment_id": request.experiment_id,
            "variant": variant,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error assigning user to experiment: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/experiments/{experiment_id}/results")
async def get_experiment_results(experiment_id: str):
    """Get A/B test experiment results."""
    try:
        results = ab_framework.get_experiment_results(experiment_id)
        status = ab_framework.get_experiment_status(experiment_id)
        
        return {
            "experiment_id": experiment_id,
            "results": results,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting experiment results: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/experiments")
async def list_experiments(status: Optional[str] = None):
    """List all experiments, optionally filtered by status."""
    try:
        experiment_status = None
        if status:
            from ...feedback.ab_testing import ExperimentStatus
            experiment_status = ExperimentStatus(status)
        
        experiments = ab_framework.list_experiments(experiment_status)
        
        return {
            "experiments": experiments,
            "count": len(experiments),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error listing experiments: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Metrics Collection Endpoints

@router.post("/metrics/track")
async def track_metrics(request: MetricsTrackingRequest):
    """Track user metrics for experiments."""
    try:
        metrics_collector.track_event(
            user_id=request.user_id,
            event_type=request.event_type,
            experiment_id=request.experiment_id,
            variant=request.variant,
            metadata=request.metadata,
            value=request.value,
            session_id=request.session_id
        )
        
        return {
            "status": "tracked",
            "user_id": request.user_id,
            "event_type": request.event_type,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error tracking metrics: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/metrics/experiments/{experiment_id}")
async def get_experiment_metrics(experiment_id: str, 
                                start_time: Optional[str] = None,
                                end_time: Optional[str] = None):
    """Get metrics for an experiment."""
    try:
        start_dt = datetime.fromisoformat(start_time) if start_time else None
        end_dt = datetime.fromisoformat(end_time) if end_time else None
        
        metrics = metrics_collector.get_experiment_metrics(
            experiment_id=experiment_id,
            start_time=start_dt,
            end_time=end_dt
        )
        
        return {
            "experiment_id": experiment_id,
            "metrics": {variant: asdict(metric_data) for variant, metric_data in metrics.items()},
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting experiment metrics: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/metrics/realtime/{experiment_id}")
async def get_realtime_metrics(experiment_id: str, time_window_minutes: int = 60):
    """Get real-time metrics for an experiment."""
    try:
        metrics = metrics_collector.get_real_time_metrics(
            experiment_id=experiment_id,
            time_window_minutes=time_window_minutes
        )
        
        return {
            "experiment_id": experiment_id,
            "time_window_minutes": time_window_minutes,
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting real-time metrics: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/metrics/dashboard/{experiment_id}")
async def get_metrics_dashboard(experiment_id: str):
    """Get comprehensive dashboard data for an experiment."""
    try:
        dashboard_data = metrics_collector.get_metrics_dashboard_data(experiment_id)
        
        return {
            "experiment_id": experiment_id,
            "dashboard_data": dashboard_data,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting metrics dashboard: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Reward Tracking Endpoints

@router.post("/rewards/track")
async def track_reward(request: RewardTrackingRequest):
    """Track reward for RL training."""
    try:
        reward_value = reward_tracker.track_reward(
            user_id=request.user_id,
            session_id=request.session_id,
            state=request.state,
            action=request.action,
            reward=request.reward,
            next_state=request.next_state,
            reward_type=request.reward_type,
            metadata=request.metadata,
            terminal=request.terminal,
            execution_result=request.execution_result,
            execution_time=request.execution_time,
            execution_cost=request.execution_cost,
            quality_metrics=request.quality_metrics,
            user_feedback=request.user_feedback
        )
        
        return {
            "status": "tracked",
            "calculated_reward": reward_value,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error tracking reward: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/rewards/statistics")
async def get_reward_statistics(user_id: Optional[str] = None,
                               action: Optional[str] = None,
                               hours_back: int = 24):
    """Get reward statistics."""
    try:
        stats = reward_tracker.get_reward_statistics(
            user_id=user_id,
            action=action,
            hours_back=hours_back
        )
        
        return {
            "statistics": stats,
            "filters": {
                "user_id": user_id,
                "action": action,
                "hours_back": hours_back
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting reward statistics: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/rewards/actions/{hours_back}")
async def get_action_performance(hours_back: int = 24):
    """Get performance statistics by action."""
    try:
        performance = reward_tracker.get_action_performance(hours_back=hours_back)
        
        return {
            "action_performance": performance,
            "hours_back": hours_back,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting action performance: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/rewards/training-data")
async def get_training_data(batch_size: Optional[int] = None,
                           min_reward: Optional[float] = None,
                           max_age_hours: int = 24,
                           balance_actions: bool = True):
    """Get formatted training data for RL."""
    try:
        states, actions, rewards, next_states, dones, weights = reward_tracker.get_training_data(
            batch_size=batch_size,
            min_reward=min_reward,
            max_age_hours=max_age_hours,
            balance_actions=balance_actions
        )
        
        return {
            "training_data": {
                "states": states.tolist() if states.size > 0 else [],
                "actions": actions.tolist() if actions.size > 0 else [],
                "rewards": rewards.tolist() if rewards.size > 0 else [],
                "next_states": next_states.tolist() if next_states.size > 0 else [],
                "dones": dones.tolist() if dones.size > 0 else [],
                "importance_weights": weights.tolist() if weights.size > 0 else []
            },
            "batch_size": len(states) if states.size > 0 else 0,
            "parameters": {
                "batch_size": batch_size,
                "min_reward": min_reward,
                "max_age_hours": max_age_hours,
                "balance_actions": balance_actions
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting training data: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# RL Training Endpoints

@router.post("/rl/train")
async def train_rl_model(request: RLTrainingRequest, background_tasks: BackgroundTasks):
    """Train RL models on collected data."""
    try:
        # Create training configuration
        config = TrainingConfig(
            mode=TrainingMode(request.mode.lower()),
            state_dim=64,  # Would be determined from actual data
            action_dim=10,  # Would be determined from actual data
            epochs=request.epochs,
            batch_size=request.batch_size,
            learning_rate=request.learning_rate
        )
        
        # Initialize training pipeline
        training_pipeline = RLTrainingPipeline(
            config=config,
            reward_tracker=reward_tracker
        )
        
        # Run training in background
        background_tasks.add_task(
            run_rl_training,
            training_pipeline,
            request.epochs
        )
        
        return {
            "status": "training_started",
            "mode": request.mode,
            "epochs": request.epochs,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error starting RL training: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/rl/training/status")
async def get_training_status():
    """Get RL training status."""
    # This would need to be implemented with persistent training state
    return {
        "status": "not_implemented",
        "message": "Training status tracking not yet implemented",
        "timestamp": datetime.utcnow().isoformat()
    }


# Tool Selection Endpoints

@router.post("/tools/select")
async def select_tool(request: ToolSelectionRequest):
    """Select optimal tool using bandit algorithms."""
    try:
        # Create task context
        task_context = TaskContext(
            task_type=TaskType(request.task_type.upper()),
            data_size=request.data_size,
            data_complexity=request.data_complexity,
            available_memory=request.available_memory,
            available_cpu_cores=request.available_cpu_cores,
            time_constraints=request.time_constraints,
            quality_requirements=request.quality_requirements,
            user_expertise=request.user_expertise,
            previous_tools_used=request.previous_tools_used,
            session_history=request.session_history,
            user_preferences=request.user_preferences
        )
        
        # This would need actual BanditToolSelector instance
        # For now, return mock response
        selected_tool = "mock_tool"
        
        return {
            "selected_tool": selected_tool,
            "task_context": {
                "task_type": request.task_type,
                "data_size": request.data_size,
                "data_complexity": request.data_complexity
            },
            "selection_metadata": {
                "exploit": request.exploit,
                "available_tools": request.available_tools
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error selecting tool: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tools/performance")
async def update_tool_performance(request: ToolPerformanceRequest):
    """Update tool performance for bandit learning."""
    try:
        # Create task context
        task_context = TaskContext(
            task_type=TaskType(request.task_type.upper()),
            data_size=request.data_size,
            data_complexity=request.data_complexity,
            available_memory=request.available_memory,
            available_cpu_cores=request.available_cpu_cores,
            time_constraints=request.time_constraints,
            quality_requirements=request.quality_requirements,
            user_expertise=request.user_expertise,
            previous_tools_used=[],
            session_history=[],
            user_preferences={}
        )
        
        # This would update actual BanditToolSelector instance
        # For now, return mock response
        
        return {
            "status": "performance_updated",
            "tool_name": request.tool_name,
            "success": request.success,
            "execution_time": request.execution_time,
            "performance_metrics": request.performance_metrics,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error updating tool performance: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# System Health Endpoints

@router.get("/health")
async def get_system_health():
    """Get overall feedback system health."""
    try:
        # Get component health
        exp_manager_health = experiment_manager.get_system_health()
        
        # Redis health
        try:
            redis_client.ping()
            redis_healthy = True
            redis_info = redis_client.info()
            redis_memory = redis_info.get("used_memory_human", "unknown")
        except Exception:
            redis_healthy = False
            redis_memory = "unknown"
        
        # Reward tracker stats
        reward_stats = reward_tracker.get_reward_statistics()
        
        return {
            "overall_status": "healthy" if redis_healthy else "degraded",
            "components": {
                "redis": {
                    "healthy": redis_healthy,
                    "memory_usage": redis_memory
                },
                "experiment_manager": exp_manager_health,
                "reward_tracker": {
                    "healthy": True,
                    "statistics": reward_stats
                },
                "ab_testing": {
                    "healthy": True,
                    "total_experiments": len(ab_framework.experiments)
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_system_statistics():
    """Get comprehensive system statistics."""
    try:
        # A/B testing stats
        ab_stats = {
            "total_experiments": len(ab_framework.experiments),
            "running_experiments": len([
                exp for exp in ab_framework.experiments.values() 
                if exp.status.value == "running"
            ]),
            "total_assignments": sum(
                sum(ab_framework._count_variant_assignments(exp.id, variant) 
                    for variant in exp.variants)
                for exp in ab_framework.experiments.values()
            )
        }
        
        # Reward tracking stats
        reward_stats = reward_tracker.get_reward_statistics()
        
        # Metrics collection stats
        metrics_stats = {
            "events_tracked": "not_implemented",  # Would need to track this
            "active_experiments": len([
                exp for exp in ab_framework.experiments.values() 
                if exp.status.value == "running"
            ])
        }
        
        return {
            "ab_testing": ab_stats,
            "reward_tracking": reward_stats,
            "metrics_collection": metrics_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error getting system statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions

async def run_rl_training(training_pipeline: RLTrainingPipeline, epochs: int):
    """Run RL training in background."""
    try:
        logger.info(f"Starting RL training with {epochs} epochs")
        
        # Update dataset
        dataset_size = training_pipeline.update_dataset()
        logger.info(f"Updated dataset with {dataset_size} samples")
        
        # Run training loop
        if dataset_size > 0:
            metrics = training_pipeline.run_training_loop(max_epochs=epochs)
            logger.info(f"RL training completed with {len(metrics)} epochs")
        else:
            logger.warning("No training data available for RL training")
        
    except Exception as e:
        logger.error(f"RL training failed: {e}")


# Import fix for asdict
from dataclasses import asdict
