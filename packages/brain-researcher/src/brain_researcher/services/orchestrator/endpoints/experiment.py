"""
Backend endpoints for A/B testing and experiment management.
"""

from fastapi import APIRouter, HTTPException, WebSocket, Query, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import hashlib
import math
import random
from enum import Enum


router = APIRouter(prefix="/api/experiments", tags=["experiments"])


# Data Models
class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class TestType(str, Enum):
    AB = "ab"
    MULTIVARIATE = "multivariate"
    SEQUENTIAL = "sequential"


class AllocationMethod(str, Enum):
    RANDOM = "random"
    WEIGHTED = "weighted"
    DETERMINISTIC = "deterministic"


class MetricType(str, Enum):
    CONVERSION = "conversion"
    ENGAGEMENT = "engagement"
    REVENUE = "revenue"
    CUSTOM = "custom"


class MetricGoal(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class VariantMetrics(BaseModel):
    impressions: int
    conversions: int
    conversion_rate: float
    confidence: Optional[float] = None
    uplift: Optional[float] = None
    revenue: Optional[float] = None
    engagement_time: Optional[float] = None


class Variant(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    weight: float  # Traffic weight percentage
    changes: Dict[str, Any]
    metrics: Optional[VariantMetrics] = None


class Metric(BaseModel):
    id: str
    name: str
    type: MetricType
    goal: MetricGoal
    unit: Optional[str] = None


class ExperimentConfig(BaseModel):
    min_sample_size: int
    confidence_level: float
    test_type: TestType
    allocation: AllocationMethod
    mde: Optional[float] = None  # Minimum detectable effect


class Experiment(BaseModel):
    id: str
    name: str
    description: str
    status: ExperimentStatus
    variants: List[Variant]
    metrics: List[Metric]
    traffic: float  # Percentage of total traffic
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    winner: Optional[str] = None
    config: ExperimentConfig
    tags: List[str] = []
    created_by: Optional[str] = None
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class VariantAssignment(BaseModel):
    experiment_id: str
    variant_id: str
    user_id: str
    assigned_at: datetime


class EventTrack(BaseModel):
    name: str
    properties: Dict[str, Any]
    user_id: str
    timestamp: datetime
    variants: List[Dict[str, str]]


# Mock database
experiments_db: Dict[str, Experiment] = {}
assignments_db: Dict[str, List[VariantAssignment]] = {}
events_db: List[EventTrack] = []


# Helper Functions
def calculate_statistical_significance(
    control_conversions: int,
    control_impressions: int,
    variant_conversions: int,
    variant_impressions: int
) -> Dict[str, float]:
    """Calculate statistical significance between control and variant."""
    p1 = control_conversions / control_impressions if control_impressions > 0 else 0
    p2 = variant_conversions / variant_impressions if variant_impressions > 0 else 0
    
    # Calculate uplift
    uplift = ((p2 - p1) / p1 * 100) if p1 > 0 else 0
    
    # Calculate standard error
    if control_impressions > 0 and variant_impressions > 0:
        se = math.sqrt(
            p1 * (1 - p1) / control_impressions + 
            p2 * (1 - p2) / variant_impressions
        )
        
        # Calculate z-score
        z = abs(p2 - p1) / se if se > 0 else 0
        
        # Convert to confidence (simplified)
        confidence = min(99.9, 50 + z * 15)
    else:
        confidence = 0
    
    return {
        "uplift": uplift,
        "confidence": confidence,
        "is_significant": confidence >= 95
    }


def allocate_variant(user_id: str, experiment: Experiment) -> Variant:
    """Allocate a variant to a user based on experiment configuration."""
    if experiment.config.allocation == AllocationMethod.DETERMINISTIC:
        # Use consistent hashing for deterministic allocation
        hash_val = int(hashlib.md5(f"{user_id}:{experiment.id}".encode()).hexdigest()[:8], 16)
        position = hash_val % 100
    else:
        # Random allocation
        position = random.random() * 100
    
    cumulative_weight = 0
    for variant in experiment.variants:
        cumulative_weight += variant.weight
        if position < cumulative_weight:
            return variant
    
    return experiment.variants[-1]  # Fallback to last variant


def check_sample_size(experiment: Experiment) -> bool:
    """Check if experiment has reached minimum sample size."""
    total_impressions = sum(
        v.metrics.impressions if v.metrics else 0 
        for v in experiment.variants
    )
    return total_impressions >= experiment.config.min_sample_size


# API Endpoints
@router.get("/active", response_model=List[Experiment])
async def get_active_experiments():
    """Get all active experiments."""
    return [
        exp for exp in experiments_db.values()
        if exp.status == ExperimentStatus.RUNNING
    ]


@router.get("/{experiment_id}", response_model=Experiment)
async def get_experiment(experiment_id: str):
    """Get experiment by ID."""
    if experiment_id not in experiments_db:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiments_db[experiment_id]


@router.post("/", response_model=Experiment)
async def create_experiment(experiment: Experiment):
    """Create a new experiment."""
    if experiment.id in experiments_db:
        raise HTTPException(status_code=400, detail="Experiment already exists")
    
    # Validate variant weights sum to 100
    total_weight = sum(v.weight for v in experiment.variants)
    if abs(total_weight - 100) > 0.01:
        raise HTTPException(
            status_code=400, 
            detail=f"Variant weights must sum to 100, got {total_weight}"
        )
    
    experiments_db[experiment.id] = experiment
    return experiment


@router.put("/{experiment_id}/status")
async def update_experiment_status(
    experiment_id: str,
    status: ExperimentStatus
):
    """Update experiment status."""
    if experiment_id not in experiments_db:
        raise HTTPException(status_code=404, detail="Experiment not found")
    
    experiment = experiments_db[experiment_id]
    old_status = experiment.status
    
    # Validate status transitions
    valid_transitions = {
        ExperimentStatus.DRAFT: [ExperimentStatus.RUNNING],
        ExperimentStatus.RUNNING: [ExperimentStatus.PAUSED, ExperimentStatus.COMPLETED],
        ExperimentStatus.PAUSED: [ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED],
        ExperimentStatus.COMPLETED: []
    }
    
    if status not in valid_transitions.get(old_status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {old_status} to {status}"
        )
    
    experiment.status = status
    experiment.updated_at = datetime.now()
    
    # Set dates based on status change
    if status == ExperimentStatus.RUNNING and not experiment.start_date:
        experiment.start_date = datetime.now()
    elif status == ExperimentStatus.COMPLETED:
        experiment.end_date = datetime.now()
        # Determine winner if significant results
        experiment.winner = determine_winner(experiment)
    
    return {"status": "updated", "experiment_id": experiment_id}


@router.get("/assignments/{user_id}")
async def get_user_assignments(user_id: str):
    """Get all experiment assignments for a user."""
    user_assignments = assignments_db.get(user_id, [])
    
    result = []
    for assignment in user_assignments:
        if assignment.experiment_id in experiments_db:
            experiment = experiments_db[assignment.experiment_id]
            variant = next(
                (v for v in experiment.variants if v.id == assignment.variant_id),
                None
            )
            if variant:
                result.append({
                    "experiment_id": assignment.experiment_id,
                    "variant": variant.model_dump()
                })
    
    return result


@router.post("/assign")
async def assign_variant(user_id: str, experiment_id: str):
    """Assign a variant to a user for an experiment."""
    if experiment_id not in experiments_db:
        raise HTTPException(status_code=404, detail="Experiment not found")
    
    experiment = experiments_db[experiment_id]
    
    if experiment.status != ExperimentStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail="Can only assign variants for running experiments"
        )
    
    # Check if user already has assignment
    user_assignments = assignments_db.get(user_id, [])
    existing = next(
        (a for a in user_assignments if a.experiment_id == experiment_id),
        None
    )
    
    if existing:
        return {
            "experiment_id": experiment_id,
            "variant_id": existing.variant_id,
            "assigned": False
        }
    
    # Allocate variant
    variant = allocate_variant(user_id, experiment)
    
    # Store assignment
    assignment = VariantAssignment(
        experiment_id=experiment_id,
        variant_id=variant.id,
        user_id=user_id,
        assigned_at=datetime.now()
    )
    
    if user_id not in assignments_db:
        assignments_db[user_id] = []
    assignments_db[user_id].append(assignment)
    
    return {
        "experiment_id": experiment_id,
        "variant_id": variant.id,
        "assigned": True
    }


@router.post("/track")
async def track_event(event: EventTrack):
    """Track user event with experiment context."""
    events_db.append(event)
    
    # Update variant metrics based on event
    for variant_info in event.variants:
        experiment_id = variant_info["experiment_id"]
        variant_id = variant_info["variant_id"]
        
        if experiment_id in experiments_db:
            experiment = experiments_db[experiment_id]
            variant = next(
                (v for v in experiment.variants if v.id == variant_id),
                None
            )
            
            if variant:
                if not variant.metrics:
                    variant.metrics = VariantMetrics(
                        impressions=0,
                        conversions=0,
                        conversion_rate=0.0
                    )
                
                # Update metrics based on event type
                if event.name == "page_view":
                    variant.metrics.impressions += 1
                elif event.name in ["conversion", "purchase", "signup"]:
                    variant.metrics.conversions += 1
                
                # Recalculate conversion rate
                if variant.metrics.impressions > 0:
                    variant.metrics.conversion_rate = (
                        variant.metrics.conversions / variant.metrics.impressions * 100
                    )
    
    return {"status": "tracked", "event_id": len(events_db)}


@router.get("/{experiment_id}/results")
async def get_experiment_results(experiment_id: str):
    """Get detailed results for an experiment."""
    if experiment_id not in experiments_db:
        raise HTTPException(status_code=404, detail="Experiment not found")
    
    experiment = experiments_db[experiment_id]
    
    # Calculate statistical significance for each variant vs control
    control = experiment.variants[0] if experiment.variants else None
    
    if not control or not control.metrics:
        return {
            "experiment_id": experiment_id,
            "status": experiment.status,
            "message": "Insufficient data"
        }
    
    results = {
        "experiment_id": experiment_id,
        "status": experiment.status,
        "variants": []
    }
    
    for variant in experiment.variants:
        if not variant.metrics:
            continue
        
        variant_result = {
            "id": variant.id,
            "name": variant.name,
            "metrics": variant.metrics.model_dump()
        }
        
        if variant.id != control.id:
            # Calculate significance vs control
            significance = calculate_statistical_significance(
                control.metrics.conversions,
                control.metrics.impressions,
                variant.metrics.conversions,
                variant.metrics.impressions
            )
            
            variant.metrics.uplift = significance["uplift"]
            variant.metrics.confidence = significance["confidence"]
            variant_result["significance"] = significance
        
        results["variants"].append(variant_result)
    
    # Check if we can declare a winner
    if check_sample_size(experiment):
        results["sample_size_reached"] = True
        winner = determine_winner(experiment)
        if winner:
            results["winner"] = winner
    else:
        results["sample_size_reached"] = False
    
    return results


def determine_winner(experiment: Experiment) -> Optional[str]:
    """Determine the winning variant if statistically significant."""
    if not experiment.variants:
        return None
    
    control = experiment.variants[0]
    if not control.metrics:
        return None
    
    best_variant = control
    best_rate = control.metrics.conversion_rate
    
    for variant in experiment.variants[1:]:
        if not variant.metrics:
            continue
        
        # Check if variant beats control with required confidence
        significance = calculate_statistical_significance(
            control.metrics.conversions,
            control.metrics.impressions,
            variant.metrics.conversions,
            variant.metrics.impressions
        )
        
        if (significance["confidence"] >= experiment.config.confidence_level and
            variant.metrics.conversion_rate > best_rate):
            best_variant = variant
            best_rate = variant.metrics.conversion_rate
    
    return best_variant.id if best_variant != control else None


@router.post("/{experiment_id}/simulate")
async def simulate_experiment_data(
    experiment_id: str,
    impressions_per_variant: int = 1000
):
    """Simulate data for testing purposes."""
    if experiment_id not in experiments_db:
        raise HTTPException(status_code=404, detail="Experiment not found")
    
    experiment = experiments_db[experiment_id]
    
    for i, variant in enumerate(experiment.variants):
        # Simulate different conversion rates
        base_rate = 0.05  # 5% base conversion rate
        multiplier = 1 + (i * 0.2)  # Each variant 20% better
        conversion_rate = base_rate * multiplier
        
        conversions = int(impressions_per_variant * conversion_rate)
        
        variant.metrics = VariantMetrics(
            impressions=impressions_per_variant,
            conversions=conversions,
            conversion_rate=conversion_rate * 100
        )
    
    return {"status": "simulated", "experiment_id": experiment_id}


# WebSocket for real-time experiment updates
@router.websocket("/ws/{experiment_id}")
async def experiment_websocket(websocket: WebSocket, experiment_id: str):
    """WebSocket endpoint for real-time experiment updates."""
    await websocket.accept()
    
    try:
        while True:
            # Send experiment updates every 5 seconds
            if experiment_id in experiments_db:
                experiment = experiments_db[experiment_id]
                await websocket.send_json({
                    "type": "update",
                    "data": experiment.model_dump()
                })
            
            # Wait for client messages or timeout
            await websocket.receive_text()
            
    except Exception as e:
        await websocket.close()