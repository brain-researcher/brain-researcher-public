"""
Cost Optimization API Endpoints

This module provides FastAPI endpoints for advanced cost optimization including:
- Cost estimation with confidence intervals
- Spot instance optimization recommendations
- Budget management and monitoring
- Cost analytics and reporting
- Real-time cost tracking
- Savings recommendations
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any, Union
import asyncio
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
import io
import csv

# Import cost optimization components
from ..agent.cost_predictor import (
    CostPredictor, JobSpecification, JobType, ComplexityLevel, 
    CostPrediction, HistoricalJob
)
from ..agent.spot_optimizer import (
    SpotInstanceOptimizer, ResourceRequirements, CloudProvider, 
    InstanceType, BiddingStrategy, SpotRecommendation
)
from ..agent.budget_manager import (
    BudgetManager, Budget, BudgetPeriod, BudgetType, SpendingCategory,
    BudgetDecision, BudgetAlert, SpendingRecord
)

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/api/cost", tags=["Cost Optimization"])

# Global instances (in production, use dependency injection)
cost_predictor = CostPredictor("ensemble")
spot_optimizer = SpotInstanceOptimizer()
# budget_manager would be initialized with Redis client
budget_manager = None  # Will be initialized with proper Redis client


# Pydantic models for API contracts
class JobSpecificationRequest(BaseModel):
    """Request model for job specification"""
    job_type: str = Field(..., description="Type of neuroimaging job")
    n_subjects: int = Field(..., ge=1, description="Number of subjects")
    n_sessions: int = Field(default=1, ge=1, description="Number of sessions per subject")
    n_runs: int = Field(default=1, ge=1, description="Number of runs per session")
    file_size_gb: float = Field(default=0.0, ge=0, description="Total file size in GB")
    
    # Processing requirements
    preprocessing_steps: List[str] = Field(default=[], description="List of preprocessing steps")
    analysis_methods: List[str] = Field(default=[], description="Analysis methods to apply")
    smoothing_fwhm: float = Field(default=0.0, ge=0, description="Smoothing FWHM")
    
    # Resource requirements
    cpu_cores: int = Field(default=4, ge=1, le=128, description="Required CPU cores")
    memory_gb: float = Field(default=16.0, ge=1, le=1024, description="Required memory in GB")
    storage_gb: float = Field(default=100.0, ge=1, description="Required storage in GB")
    gpu_required: bool = Field(default=False, description="Whether GPU is required")
    
    # Configuration
    complexity_level: str = Field(default="medium", description="Job complexity level")
    quality_level: str = Field(default="standard", description="Quality level")
    priority: str = Field(default="normal", description="Job priority")
    software_stack: List[str] = Field(default=[], description="Required software packages")
    
    # Optional metadata
    deadline: Optional[str] = Field(default=None, description="Job deadline (ISO format)")
    user_id: Optional[str] = Field(default=None, description="User identifier")
    project_id: Optional[str] = Field(default=None, description="Project identifier")


class ResourceRequirementsRequest(BaseModel):
    """Request model for resource requirements"""
    cpu_cores: int = Field(..., ge=1, le=128)
    memory_gb: float = Field(..., ge=1, le=1024)
    storage_gb: float = Field(..., ge=1)
    gpu_count: int = Field(default=0, ge=0, le=8)
    gpu_memory_gb: float = Field(default=0, ge=0)
    
    # Neuroimaging-specific
    fsl_required: bool = Field(default=False)
    freesurfer_required: bool = Field(default=False)
    matlab_required: bool = Field(default=False)
    cuda_required: bool = Field(default=False)


class CostEstimationRequest(BaseModel):
    """Request for cost estimation"""
    job_specification: JobSpecificationRequest
    backend: str = Field(default="aws", description="Cloud backend")
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.99, description="Confidence level for intervals")
    include_alternatives: bool = Field(default=True, description="Include alternative configurations")


class SpotOptimizationRequest(BaseModel):
    """Request for spot instance optimization"""
    resource_requirements: ResourceRequirementsRequest
    duration_hours: float = Field(..., gt=0, description="Expected job duration in hours")
    budget: Optional[float] = Field(default=None, description="Budget constraint")
    preferred_providers: List[str] = Field(default=[], description="Preferred cloud providers")
    bidding_strategy: str = Field(default="dynamic", description="Bidding strategy")


class BudgetRequest(BaseModel):
    """Request to create or update budget"""
    name: str = Field(..., description="Budget name")
    total_amount: float = Field(..., gt=0, description="Total budget amount")
    period: str = Field(..., description="Budget period")
    budget_type: str = Field(default="soft_limit", description="Budget enforcement type")
    
    # Time configuration
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")
    
    # Alert configuration
    alert_thresholds: List[float] = Field(default=[50.0, 80.0, 95.0], description="Alert thresholds (%)")
    notification_emails: List[str] = Field(default=[], description="Notification email addresses")
    
    # Optional configuration
    auto_renew: bool = Field(default=False, description="Auto-renew budget")
    rollover_unused: bool = Field(default=False, description="Rollover unused budget")


class SpendingRecordRequest(BaseModel):
    """Request to record spending"""
    budget_id: str = Field(..., description="Budget identifier")
    amount: float = Field(..., gt=0, description="Spending amount")
    category: str = Field(..., description="Spending category")
    description: str = Field(..., description="Spending description")
    
    # Optional context
    resource_id: Optional[str] = Field(default=None, description="Resource identifier")
    job_id: Optional[str] = Field(default=None, description="Job identifier")
    user_id: Optional[str] = Field(default=None, description="User identifier")
    provider: Optional[str] = Field(default=None, description="Cloud provider")
    region: Optional[str] = Field(default=None, description="Cloud region")


# Response models
class CostPredictionResponse(BaseModel):
    """Cost prediction response"""
    estimated_cost: float
    confidence_interval: tuple
    confidence_level: float
    breakdown: Dict[str, float]
    model_confidence: float
    prediction_method: str
    
    # Timing
    estimated_duration_hours: float
    duration_confidence_interval: tuple
    
    # Optimization
    cost_optimization_suggestions: List[str]
    alternative_configurations: List[Dict[str, Any]] = []
    
    # Metadata
    prediction_timestamp: str


class SpotRecommendationResponse(BaseModel):
    """Spot instance recommendation response"""
    provider: str
    region: str
    availability_zone: str
    instance_type: str
    current_price: float
    on_demand_price: float
    savings_percentage: float
    
    # Risk assessment
    interruption_probability: float
    price_volatility: float
    availability_score: float
    
    # Cost analysis
    expected_cost: float
    risk_adjusted_cost: float
    total_cost_with_interruptions: float
    
    # Metadata
    recommendation_confidence: float
    instance_specs: Dict[str, Any]
    suitability_score: float


class BudgetResponse(BaseModel):
    """Budget response"""
    budget_id: str
    name: str
    total_amount: float
    period: str
    budget_type: str
    start_date: str
    end_date: Optional[str]
    alert_thresholds: List[float]
    created_at: str


class BudgetStatusResponse(BaseModel):
    """Budget status response"""
    budget_id: str
    budget_name: str
    total_budget: float
    spent: float
    remaining: float
    percentage_used: float
    daily_burn_rate: float
    projected_days_remaining: Optional[int]
    alert_count: int
    status: str  # "healthy", "warning", "critical", "exceeded"


class CostReportResponse(BaseModel):
    """Cost report response"""
    period: str
    total_budget: float
    spent: float
    remaining: float
    percentage_used: float
    daily_burn_rate: float
    category_breakdown: Dict[str, Dict[str, float]]
    top_consumers: List[Dict[str, Any]]
    spending_history: List[Dict[str, Any]]
    recommendations: List[str]
    generated_at: str


# API Endpoints

@router.post("/estimate", response_model=CostPredictionResponse)
async def estimate_cost(request: CostEstimationRequest):
    """Estimate cost for a job specification"""
    try:
        # Convert request to internal format
        job_spec = JobSpecification(
            job_type=JobType(request.job_specification.job_type),
            n_subjects=request.job_specification.n_subjects,
            n_sessions=request.job_specification.n_sessions,
            n_runs=request.job_specification.n_runs,
            file_size_gb=request.job_specification.file_size_gb,
            preprocessing_steps=request.job_specification.preprocessing_steps,
            analysis_methods=request.job_specification.analysis_methods,
            smoothing_fwhm=request.job_specification.smoothing_fwhm,
            cpu_cores=request.job_specification.cpu_cores,
            memory_gb=request.job_specification.memory_gb,
            storage_gb=request.job_specification.storage_gb,
            gpu_required=request.job_specification.gpu_required,
            complexity_level=ComplexityLevel(request.job_specification.complexity_level),
            quality_level=request.job_specification.quality_level,
            priority=request.job_specification.priority,
            software_stack=request.job_specification.software_stack,
            user_id=request.job_specification.user_id,
            project_id=request.job_specification.project_id
        )
        
        # Parse deadline if provided
        if request.job_specification.deadline:
            job_spec.deadline = datetime.fromisoformat(request.job_specification.deadline)
        
        # Get cost prediction
        prediction = cost_predictor.predict_job_cost(
            job_spec, request.backend, request.confidence_level
        )
        
        # Generate alternative configurations if requested
        alternatives = []
        if request.include_alternatives:
            alternatives = await _generate_alternative_configurations(job_spec, request.backend)
        
        return CostPredictionResponse(
            estimated_cost=prediction.estimated_cost,
            confidence_interval=prediction.confidence_interval,
            confidence_level=prediction.confidence_level,
            breakdown=prediction.breakdown,
            model_confidence=prediction.model_confidence,
            prediction_method=prediction.prediction_method,
            estimated_duration_hours=prediction.estimated_duration_hours,
            duration_confidence_interval=prediction.duration_confidence_interval,
            cost_optimization_suggestions=prediction.cost_optimization_suggestions,
            alternative_configurations=alternatives,
            prediction_timestamp=datetime.now().isoformat()
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
    except Exception as e:
        logger.error(f"Error estimating cost: {e}")
        raise HTTPException(status_code=500, detail=f"Cost estimation failed: {str(e)}")


@router.post("/optimize", response_model=List[SpotRecommendationResponse])
async def optimize_spot_instances(request: SpotOptimizationRequest):
    """Get spot instance optimization recommendations"""
    try:
        # Convert request to internal format
        requirements = ResourceRequirements(
            cpu_cores=request.resource_requirements.cpu_cores,
            memory_gb=request.resource_requirements.memory_gb,
            storage_gb=request.resource_requirements.storage_gb,
            gpu_count=request.resource_requirements.gpu_count,
            gpu_memory_gb=request.resource_requirements.gpu_memory_gb,
            fsl_required=request.resource_requirements.fsl_required,
            freesurfer_required=request.resource_requirements.freesurfer_required,
            matlab_required=request.resource_requirements.matlab_required,
            cuda_required=request.resource_requirements.cuda_required
        )
        
        # Convert providers
        preferred_providers = []
        for provider_str in request.preferred_providers:
            try:
                preferred_providers.append(CloudProvider(provider_str))
            except ValueError:
                logger.warning(f"Unknown cloud provider: {provider_str}")
        
        # Get recommendations
        duration = timedelta(hours=request.duration_hours)
        recommendations = await spot_optimizer.get_spot_recommendations(
            requirements, duration, request.budget, preferred_providers
        )
        
        # Convert to response format
        response_recommendations = []
        for rec in recommendations:
            response_recommendations.append(SpotRecommendationResponse(
                provider=rec.provider.value,
                region=rec.region,
                availability_zone=rec.availability_zone,
                instance_type=rec.instance_type,
                current_price=rec.current_price,
                on_demand_price=rec.on_demand_price,
                savings_percentage=rec.savings_percentage,
                interruption_probability=rec.interruption_probability,
                price_volatility=rec.price_volatility,
                availability_score=rec.availability_score,
                expected_cost=rec.expected_cost,
                risk_adjusted_cost=rec.risk_adjusted_cost,
                total_cost_with_interruptions=rec.total_cost_with_interruptions,
                recommendation_confidence=rec.recommendation_confidence,
                instance_specs=rec.instance_specs,
                suitability_score=rec.suitability_score
            ))
        
        return response_recommendations
        
    except Exception as e:
        logger.error(f"Error optimizing spot instances: {e}")
        raise HTTPException(status_code=500, detail=f"Spot optimization failed: {str(e)}")


@router.post("/budget", response_model=BudgetResponse)
async def create_budget(request: BudgetRequest):
    """Create a new budget"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        # Create budget object
        budget = Budget(
            budget_id=f"budget_{datetime.now().timestamp()}",
            name=request.name,
            total_amount=Decimal(str(request.total_amount)),
            period=BudgetPeriod(request.period),
            budget_type=BudgetType(request.budget_type),
            start_date=date.fromisoformat(request.start_date),
            alert_thresholds=request.alert_thresholds,
            auto_renew=request.auto_renew,
            rollover_unused=request.rollover_unused,
            notification_emails=request.notification_emails
        )
        
        if request.end_date:
            budget.end_date = date.fromisoformat(request.end_date)
        
        # Create budget
        budget_id = budget_manager.create_budget(budget)
        
        return BudgetResponse(
            budget_id=budget_id,
            name=budget.name,
            total_amount=float(budget.total_amount),
            period=budget.period.value,
            budget_type=budget.budget_type.value,
            start_date=budget.start_date.isoformat(),
            end_date=budget.end_date.isoformat() if budget.end_date else None,
            alert_thresholds=budget.alert_thresholds,
            created_at=budget.created_at.isoformat()
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid budget configuration: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating budget: {e}")
        raise HTTPException(status_code=500, detail=f"Budget creation failed: {str(e)}")


@router.get("/budget/{budget_id}/status", response_model=BudgetStatusResponse)
async def get_budget_status(budget_id: str):
    """Get budget status"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        # Get budget summary
        summary = budget_manager.generate_budget_report(budget_id)
        
        if "error" in summary:
            raise HTTPException(status_code=404, detail=summary["error"])
        
        # Determine status
        percentage_used = summary["percentage_used"]
        if percentage_used >= 100:
            status = "exceeded"
        elif percentage_used >= 90:
            status = "critical"
        elif percentage_used >= 75:
            status = "warning"
        else:
            status = "healthy"
        
        return BudgetStatusResponse(
            budget_id=budget_id,
            budget_name=summary["budget_name"],
            total_budget=summary["total_budget"],
            spent=summary["spent"],
            remaining=summary["remaining"],
            percentage_used=summary["percentage_used"],
            daily_burn_rate=summary["daily_burn_rate"],
            projected_days_remaining=summary.get("projected_days_remaining"),
            alert_count=summary["alert_count"],
            status=status
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting budget status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/spending")
async def record_spending(request: SpendingRecordRequest):
    """Record spending against a budget"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        # Record spending
        record_id = budget_manager.record_spending(
            budget_id=request.budget_id,
            amount=Decimal(str(request.amount)),
            category=SpendingCategory(request.category),
            description=request.description,
            resource_id=request.resource_id,
            job_id=request.job_id,
            user_id=request.user_id,
            provider=request.provider,
            region=request.region
        )
        
        return {
            "record_id": record_id,
            "message": "Spending recorded successfully",
            "amount": request.amount,
            "budget_id": request.budget_id
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid spending record: {str(e)}")
    except Exception as e:
        logger.error(f"Error recording spending: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report/{budget_id}", response_model=CostReportResponse)
async def get_cost_report(budget_id: str, period: str = Query(default="current", description="Report period")):
    """Generate comprehensive cost report"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        report = budget_manager.generate_budget_report(budget_id, period)
        
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])
        
        return CostReportResponse(
            period=period,
            total_budget=report["total_budget"],
            spent=report["spent"],
            remaining=report["remaining"],
            percentage_used=report["percentage_used"],
            daily_burn_rate=report["daily_burn_rate"],
            category_breakdown=report["category_breakdown"],
            top_consumers=report["top_consumers"],
            spending_history=report["spending_history"],
            recommendations=report["recommendations"],
            generated_at=report["generated_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating cost report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/budget/{budget_id}/check")
async def check_budget_approval(budget_id: str, estimated_cost: float):
    """Check if spending is approved within budget"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        decision = await budget_manager.check_budget(budget_id, Decimal(str(estimated_cost)))
        
        return {
            "approved": decision.approved,
            "remaining_budget": float(decision.remaining_budget),
            "estimated_cost": float(decision.estimated_cost),
            "decision_reason": decision.decision_reason,
            "risk_level": decision.risk_level,
            "alternative_suggestions": decision.alternative_suggestions,
            "projected_end_date_impact": decision.projected_end_date_impact.isoformat() if decision.projected_end_date_impact else None
        }
        
    except Exception as e:
        logger.error(f"Error checking budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/savings/analysis")
async def analyze_savings(on_demand_cost: float, spot_cost: float, 
                         interruption_probability: float = Query(default=0.0, ge=0, le=1)):
    """Analyze potential savings from spot instances"""
    try:
        savings = spot_optimizer.calculate_savings(on_demand_cost, spot_cost, interruption_probability)
        
        return {
            "savings_analysis": savings,
            "recommendation": _get_savings_recommendation(savings),
            "risk_assessment": _assess_savings_risk(savings)
        }
        
    except Exception as e:
        logger.error(f"Error analyzing savings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recommendations/{job_type}")
async def get_cost_recommendations(job_type: str, budget: Optional[float] = None):
    """Get cost optimization recommendations for job type"""
    try:
        # Generate recommendations based on job type and budget
        recommendations = []
        
        if job_type in ["preprocessing", "first_level_analysis"]:
            recommendations.extend([
                "Use spot instances for batch preprocessing jobs",
                "Consider CPU-optimized instances for FSL/FreeSurfer workflows",
                "Enable data compression to reduce storage costs"
            ])
        elif job_type in ["group_analysis", "connectivity_analysis"]:
            recommendations.extend([
                "Use memory-optimized instances for large group analyses",
                "Consider reserved instances for long-running studies",
                "Implement result caching to avoid recomputation"
            ])
        elif job_type == "machine_learning":
            recommendations.extend([
                "Use GPU instances only when necessary",
                "Consider preemptible instances for training jobs",
                "Implement checkpointing to handle interruptions"
            ])
        
        # Budget-specific recommendations
        if budget:
            if budget < 100:
                recommendations.append("Focus on spot instances and basic instance types")
            elif budget > 1000:
                recommendations.append("Consider reserved instances for long-term savings")
        
        return {
            "job_type": job_type,
            "budget_constraint": budget,
            "recommendations": recommendations,
            "estimated_savings": "20-70% with spot instances",
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts/{budget_id}")
async def get_budget_alerts(budget_id: str):
    """Get active budget alerts"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        # Get alerts for budget
        active_alerts = [
            alert for alert in budget_manager.alerts.active_alerts.values()
            if alert.budget_id == budget_id
        ]
        
        alerts_data = []
        for alert in active_alerts:
            alerts_data.append({
                "alert_id": alert.alert_id,
                "severity": alert.severity.value,
                "threshold_percentage": alert.threshold_percentage,
                "current_percentage": alert.current_percentage,
                "message": alert.message,
                "triggered_at": alert.triggered_at.isoformat(),
                "acknowledged": alert.acknowledged,
                "acknowledged_by": alert.acknowledged_by,
                "auto_actions_triggered": alert.auto_actions_triggered
            })
        
        return {
            "budget_id": budget_id,
            "active_alerts": alerts_data,
            "alert_count": len(alerts_data)
        }
        
    except Exception as e:
        logger.error(f"Error getting budget alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, acknowledged_by: str):
    """Acknowledge a budget alert"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        success = budget_manager.alerts.acknowledge_alert(alert_id, acknowledged_by)
        
        if success:
            return {"message": "Alert acknowledged successfully", "alert_id": alert_id}
        else:
            raise HTTPException(status_code=404, detail="Alert not found")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/spending/{budget_id}")
async def export_spending_data(budget_id: str, format: str = Query(default="csv", description="Export format")):
    """Export spending data"""
    try:
        if not budget_manager:
            raise HTTPException(status_code=503, detail="Budget manager not available")
        
        # Get spending data (simplified - would need proper implementation)
        report = budget_manager.generate_budget_report(budget_id)
        
        if format.lower() == "csv":
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            writer.writerow(["Date", "Amount", "Category", "Description"])
            for day in report["spending_history"]:
                writer.writerow([day["date"], day["spending"], "mixed", "Daily total"])
            
            output.seek(0)
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode()),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=spending_{budget_id}.csv"}
            )
        else:
            # JSON format
            return JSONResponse(content=report["spending_history"])
            
    except Exception as e:
        logger.error(f"Error exporting spending data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions

async def _generate_alternative_configurations(job_spec: JobSpecification, backend: str) -> List[Dict[str, Any]]:
    """Generate alternative configurations for cost optimization"""
    
    alternatives = []
    
    # Spot instance alternative
    if job_spec.priority != "urgent":
        spot_config = {
            "name": "Spot Instance Configuration",
            "description": "Use spot instances for 50-80% cost savings",
            "changes": ["Use spot instances", "Add fault tolerance"],
            "estimated_savings": "50-80%",
            "trade_offs": ["Potential interruptions", "Longer completion time"]
        }
        alternatives.append(spot_config)
    
    # CPU optimization alternative
    if job_spec.cpu_cores > 8:
        cpu_config = {
            "name": "CPU-Optimized Configuration",
            "description": "Reduce CPU cores and increase memory efficiency",
            "changes": [f"Reduce CPU cores from {job_spec.cpu_cores} to {job_spec.cpu_cores//2}"],
            "estimated_savings": "20-40%",
            "trade_offs": ["Longer execution time", "Same result quality"]
        }
        alternatives.append(cpu_config)
    
    # Storage optimization alternative
    if job_spec.storage_gb > 200:
        storage_config = {
            "name": "Storage-Optimized Configuration", 
            "description": "Use compressed storage and cleanup intermediate files",
            "changes": ["Enable compression", "Cleanup intermediate files"],
            "estimated_savings": "10-30%",
            "trade_offs": ["Slightly longer I/O", "Manual cleanup required"]
        }
        alternatives.append(storage_config)
    
    return alternatives


def _get_savings_recommendation(savings: Dict[str, Any]) -> str:
    """Get savings recommendation based on analysis"""
    
    expected_percentage = savings.get("expected_percentage", 0)
    interruption_prob = savings.get("interruption_probability", 0)
    
    if expected_percentage > 50 and interruption_prob < 0.1:
        return "Highly recommended - excellent savings with low risk"
    elif expected_percentage > 30 and interruption_prob < 0.3:
        return "Recommended - good savings with acceptable risk"
    elif expected_percentage > 10:
        return "Consider carefully - moderate savings but evaluate risk tolerance"
    else:
        return "Not recommended - savings may not justify the risk"


def _assess_savings_risk(savings: Dict[str, Any]) -> Dict[str, str]:
    """Assess risk level of savings strategy"""
    
    interruption_prob = savings.get("interruption_probability", 0)
    
    if interruption_prob < 0.1:
        risk_level = "Low"
        risk_description = "Very low chance of interruption"
    elif interruption_prob < 0.3:
        risk_level = "Medium"
        risk_description = "Some chance of interruption - implement checkpointing"
    elif interruption_prob < 0.5:
        risk_level = "High"
        risk_description = "High chance of interruption - only for fault-tolerant workloads"
    else:
        risk_level = "Very High"
        risk_description = "Very high chance of interruption - not recommended"
    
    return {
        "risk_level": risk_level,
        "description": risk_description,
        "mitigation_strategies": [
            "Implement checkpointing",
            "Use multiple availability zones",
            "Set up automated restart"
        ]
    }