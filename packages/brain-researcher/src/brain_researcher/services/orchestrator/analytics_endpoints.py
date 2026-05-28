"""
Advanced Analytics Dashboard Backend Endpoints.
Provides comprehensive analytics data for usage, performance, research, and system metrics.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Query
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib
import json
import random
import asyncio
from enum import Enum


router = APIRouter(prefix="/api", tags=["analytics"])


# Data Models
class EventCategory(str, Enum):
    INTERACTION = "interaction"
    NAVIGATION = "navigation"
    CONVERSION = "conversion"
    ERROR = "error"
    PERFORMANCE = "performance"


class TrackingEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    category: EventCategory
    properties: Dict[str, Any] = {}
    timestamp: int
    session_id: str = Field(alias="sessionId")
    user_id: Optional[str] = Field(None, alias="userId")
    page_url: str = Field(alias="pageUrl")
    user_agent: str = Field(alias="userAgent")


class EventBatch(BaseModel):
    events: List[TrackingEvent]


class ErrorSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCode(str, Enum):
    DEMO_UNAVAILABLE = "E_DEMO_UNAVAILABLE"
    TIMEOUT = "E_TIMEOUT"
    TOOL_ERROR = "E_TOOL_ERROR"
    STORAGE = "E_STORAGE"
    NETWORK = "E_NETWORK"
    AUTH = "E_AUTH"
    VALIDATION = "E_VALIDATION"
    RATE_LIMIT = "E_RATE_LIMIT"
    SERVER = "E_SERVER"
    UNKNOWN = "E_UNKNOWN"


class ErrorReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: Optional[ErrorCode] = ErrorCode.UNKNOWN
    message: str
    details: Optional[str] = None
    timestamp: int
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    url: str
    user_agent: str = Field(alias="userAgent")
    stack: Optional[str] = None
    context: Dict[str, Any] = {}
    user_id: Optional[str] = Field(None, alias="userId")
    session_id: Optional[str] = Field(None, alias="sessionId")


class AnalyticsMetrics(BaseModel):
    total_events: int
    events_by_category: Dict[str, int]
    top_events: List[Dict[str, Any]]
    unique_sessions: int
    unique_users: int
    avg_session_duration: float
    conversion_rate: float
    error_rate: float


# In-memory storage (replace with database in production)
events_storage: List[TrackingEvent] = []
errors_storage: List[ErrorReport] = []
session_data: Dict[str, Dict] = {}
funnel_data: Dict[str, Dict] = {}


# Helper Functions
def calculate_session_metrics(session_id: str) -> Dict[str, Any]:
    """Calculate metrics for a specific session."""
    session_events = [e for e in events_storage if e.session_id == session_id]
    
    if not session_events:
        return {}
    
    session_events.sort(key=lambda e: e.timestamp)
    
    return {
        "session_id": session_id,
        "event_count": len(session_events),
        "duration": session_events[-1].timestamp - session_events[0].timestamp,
        "start_time": session_events[0].timestamp,
        "end_time": session_events[-1].timestamp,
        "page_views": sum(1 for e in session_events if e.name == "page_view"),
        "interactions": sum(1 for e in session_events if e.category == EventCategory.INTERACTION),
        "errors": sum(1 for e in session_events if e.category == EventCategory.ERROR)
    }


def calculate_funnel_metrics(funnel_name: str) -> Dict[str, Any]:
    """Calculate conversion funnel metrics."""
    funnel = funnel_data.get(funnel_name, {})
    
    if not funnel:
        return {}
    
    completed_steps = sum(1 for step in funnel.get("steps", []) if step.get("completed"))
    total_steps = len(funnel.get("steps", []))
    
    return {
        "funnel_name": funnel_name,
        "completion_rate": (completed_steps / total_steps * 100) if total_steps > 0 else 0,
        "completed_steps": completed_steps,
        "total_steps": total_steps,
        "drop_off_points": [
            step["name"] for step in funnel.get("steps", [])
            if not step.get("completed")
        ]
    }


def aggregate_events_by_name() -> Dict[str, int]:
    """Aggregate events by name."""
    event_counts = defaultdict(int)
    for event in events_storage:
        event_counts[event.name] += 1
    return dict(event_counts)


# API Endpoints
@router.post("/events")
async def track_events(
    batch: EventBatch,
    background_tasks: BackgroundTasks,
    request: Request
):
    """Track a batch of analytics events."""
    tracking_id = request.headers.get("X-Tracking-Id")
    
    if not tracking_id:
        raise HTTPException(status_code=400, detail="Missing tracking ID")
    
    # Store events
    for event in batch.events:
        events_storage.append(event)
        
        # Update session data
        if event.session_id not in session_data:
            session_data[event.session_id] = {
                "start_time": event.timestamp,
                "last_activity": event.timestamp,
                "event_count": 0,
                "user_id": event.user_id
            }
        
        session_data[event.session_id]["last_activity"] = event.timestamp
        session_data[event.session_id]["event_count"] += 1
        
        # Process funnel events
        if event.name == "funnel_started":
            funnel_name = event.properties.get("funnel")
            funnel_data[funnel_name] = {
                "name": funnel_name,
                "steps": [
                    {"name": step, "completed": False}
                    for step in event.properties.get("steps", [])
                ],
                "start_time": event.timestamp
            }
        elif event.name == "funnel_step_completed":
            funnel_name = event.properties.get("funnel")
            step_name = event.properties.get("step")
            if funnel_name in funnel_data:
                for step in funnel_data[funnel_name].get("steps", []):
                    if step["name"] == step_name:
                        step["completed"] = True
                        step["timestamp"] = event.timestamp
    
    # Process events asynchronously
    background_tasks.add_task(process_events, batch.events, tracking_id)
    
    return {
        "status": "success",
        "events_received": len(batch.events),
        "tracking_id": tracking_id
    }


@router.post("/errors/report")
async def report_error(
    error: ErrorReport,
    background_tasks: BackgroundTasks
):
    """Report an error from the frontend."""
    # Store error
    errors_storage.append(error)
    
    # Process error asynchronously
    background_tasks.add_task(process_error, error)
    
    # For critical errors, trigger immediate alerts
    if error.severity == ErrorSeverity.CRITICAL:
        background_tasks.add_task(send_critical_error_alert, error)
    
    return {
        "status": "reported",
        "error_id": hashlib.md5(
            f"{error.code}:{error.timestamp}".encode()
        ).hexdigest()
    }


@router.get("/analytics/metrics", response_model=AnalyticsMetrics)
async def get_analytics_metrics(
    start_time: Optional[int] = None,
    end_time: Optional[int] = None
):
    """Get aggregated analytics metrics."""
    # Filter events by time range
    filtered_events = events_storage
    if start_time:
        filtered_events = [e for e in filtered_events if e.timestamp >= start_time]
    if end_time:
        filtered_events = [e for e in filtered_events if e.timestamp <= end_time]
    
    # Calculate metrics
    events_by_category = defaultdict(int)
    for event in filtered_events:
        events_by_category[event.category.value] += 1
    
    # Get top events
    event_counts = aggregate_events_by_name()
    top_events = sorted(
        [{"name": k, "count": v} for k, v in event_counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:10]
    
    # Calculate unique sessions and users
    unique_sessions = len(set(e.session_id for e in filtered_events))
    unique_users = len(set(e.user_id for e in filtered_events if e.user_id))
    
    # Calculate average session duration
    session_durations = []
    for session_id in set(e.session_id for e in filtered_events):
        metrics = calculate_session_metrics(session_id)
        if metrics and "duration" in metrics:
            session_durations.append(metrics["duration"])
    
    avg_session_duration = (
        sum(session_durations) / len(session_durations)
        if session_durations else 0
    )
    
    # Calculate conversion rate (simplified)
    conversions = sum(1 for e in filtered_events if e.name == "demo_completed")
    starts = sum(1 for e in filtered_events if e.name == "demo_started")
    conversion_rate = (conversions / starts * 100) if starts > 0 else 0
    
    # Calculate error rate
    total_events = len(filtered_events)
    error_events = sum(1 for e in filtered_events if e.category == EventCategory.ERROR)
    error_rate = (error_events / total_events * 100) if total_events > 0 else 0
    
    return AnalyticsMetrics(
        total_events=total_events,
        events_by_category=dict(events_by_category),
        top_events=top_events,
        unique_sessions=unique_sessions,
        unique_users=unique_users,
        avg_session_duration=avg_session_duration,
        conversion_rate=conversion_rate,
        error_rate=error_rate
    )


@router.get("/analytics/sessions/{session_id}")
async def get_session_details(session_id: str):
    """Get detailed information about a specific session."""
    session_events = [
        e for e in events_storage
        if e.session_id == session_id
    ]
    
    if not session_events:
        raise HTTPException(status_code=404, detail="Session not found")
    
    metrics = calculate_session_metrics(session_id)
    
    return {
        "session_id": session_id,
        "metrics": metrics,
        "events": [e.model_dump() for e in session_events],
        "user_id": session_data.get(session_id, {}).get("user_id")
    }


@router.get("/analytics/funnels/{funnel_name}")
async def get_funnel_metrics(funnel_name: str):
    """Get conversion funnel metrics."""
    if funnel_name not in funnel_data:
        raise HTTPException(status_code=404, detail="Funnel not found")
    
    metrics = calculate_funnel_metrics(funnel_name)
    
    return {
        "funnel": funnel_data[funnel_name],
        "metrics": metrics
    }


@router.get("/errors/recent")
async def get_recent_errors(
    limit: int = 100,
    severity: Optional[ErrorSeverity] = None
):
    """Get recent error reports."""
    filtered_errors = errors_storage
    
    if severity:
        filtered_errors = [e for e in filtered_errors if e.severity == severity]
    
    # Sort by timestamp descending
    filtered_errors.sort(key=lambda e: e.timestamp, reverse=True)
    
    return {
        "errors": [e.model_dump() for e in filtered_errors[:limit]],
        "total_count": len(filtered_errors)
    }


@router.get("/errors/summary")
async def get_error_summary():
    """Get error summary statistics."""
    error_counts_by_code = defaultdict(int)
    error_counts_by_severity = defaultdict(int)
    
    for error in errors_storage:
        error_counts_by_code[error.code.value] += 1
        error_counts_by_severity[error.severity.value] += 1
    
    return {
        "total_errors": len(errors_storage),
        "by_code": dict(error_counts_by_code),
        "by_severity": dict(error_counts_by_severity),
        "recent_critical": [
            e.model_dump() for e in errors_storage
            if e.severity == ErrorSeverity.CRITICAL
        ][-5:]
    }


# Background Tasks
async def process_events(events: List[TrackingEvent], tracking_id: str):
    """Process events for analytics (async)."""
    # Here you would typically:
    # - Store events in a database
    # - Send to analytics service (e.g., Google Analytics, Mixpanel)
    # - Update real-time dashboards
    # - Trigger automated actions based on events
    pass


async def process_error(error: ErrorReport):
    """Process error report (async)."""
    # Here you would typically:
    # - Store in error tracking service (e.g., Sentry)
    # - Send notifications for critical errors
    # - Update error dashboards
    # - Trigger automated recovery procedures
    pass


async def send_critical_error_alert(error: ErrorReport):
    """Send alert for critical errors."""
    # Here you would typically:
    # - Send email/Slack notification to team
    # - Create incident ticket
    # - Page on-call engineer if necessary
    pass


# Advanced Analytics Models
class UsageMetrics(BaseModel):
    totalUsers: int
    activeUsers: int
    newUsers: int
    sessionsPerUser: float
    avgSessionDuration: float
    pageViewsPerSession: float
    bounceRate: float
    topPages: List[Dict[str, Any]]
    userGrowth: List[Dict[str, Any]]
    hourlyActivity: List[Dict[str, Any]]

class PerformanceMetrics(BaseModel):
    avgResponseTime: float
    p50ResponseTime: float
    p95ResponseTime: float
    p99ResponseTime: float
    successRate: float
    errorRate: float
    throughput: float
    uptime: float
    responseTimeHistory: List[Dict[str, Any]]
    errorBreakdown: List[Dict[str, Any]]
    endpointPerformance: List[Dict[str, Any]]

class ResearchMetrics(BaseModel):
    analysesRun: int
    datasetsUsed: Dict[str, int]
    toolsUsed: Dict[str, int]
    popularWorkflows: List[Dict[str, Any]]
    publicationMetrics: Dict[str, Any]
    datasetStats: Dict[str, Any]
    toolUsageTrends: List[Dict[str, Any]]

class SystemMetrics(BaseModel):
    cpuUsage: float
    memoryUsage: float
    gpuUsage: float
    storageUsage: float
    queueLength: int
    activeJobs: int
    completedJobs: int
    failedJobs: int
    resourceHistory: List[Dict[str, Any]]
    jobQueue: List[Dict[str, Any]]

class EngagementMetrics(BaseModel):
    dailyActiveUsers: int
    weeklyActiveUsers: int
    monthlyActiveUsers: int
    retentionRate: float
    churnRate: float
    avgTimeOnSite: float
    conversionFunnels: List[Dict[str, Any]]
    featureAdoption: List[Dict[str, Any]]
    userSegments: List[Dict[str, Any]]

class CustomReport(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    charts: List[Dict[str, Any]]
    filters: Dict[str, Any]
    schedule: Optional[Dict[str, Any]] = None
    createdAt: datetime
    updatedAt: datetime

class AlertConfig(BaseModel):
    id: str
    name: str
    metric: str
    threshold: float
    condition: str
    severity: str
    enabled: bool
    recipients: List[str]
    lastTriggered: Optional[datetime] = None

# Mock data generators
def generate_usage_metrics(start_date: datetime, end_date: datetime) -> UsageMetrics:
    """Generate realistic usage metrics for the given date range."""
    days = (end_date - start_date).days
    
    # Base metrics with some variation
    base_users = 1250
    total_users = base_users + random.randint(-50, 200)
    active_users = int(total_users * random.uniform(0.3, 0.6))
    new_users = int(total_users * random.uniform(0.05, 0.15))
    
    # Growth data
    user_growth = []
    for i in range(min(days, 30)):
        date = start_date + timedelta(days=i)
        user_growth.append({
            'date': date.isoformat(),
            'newUsers': random.randint(10, 50),
            'activeUsers': random.randint(150, 400)
        })
    
    # Hourly activity
    hourly_activity = []
    for hour in range(24):
        # More activity during business hours
        if 9 <= hour <= 17:
            base_activity = random.randint(80, 200)
        elif 18 <= hour <= 22:
            base_activity = random.randint(40, 120)
        else:
            base_activity = random.randint(5, 40)
        
        hourly_activity.append({
            'hour': hour,
            'users': base_activity,
            'sessions': int(base_activity * random.uniform(1.2, 1.8))
        })
    
    # Top pages
    pages = ['/dashboard', '/datasets', '/analytics', '/chat', '/knowledge-graph']
    top_pages = []
    for page in pages:
        views = random.randint(500, 2000)
        top_pages.append({
            'page': page,
            'views': views,
            'uniqueUsers': int(views * random.uniform(0.6, 0.9))
        })
    
    return UsageMetrics(
        totalUsers=total_users,
        activeUsers=active_users,
        newUsers=new_users,
        sessionsPerUser=round(random.uniform(2.1, 4.5), 1),
        avgSessionDuration=round(random.uniform(12.0, 28.0), 1),
        pageViewsPerSession=round(random.uniform(3.2, 7.1), 1),
        bounceRate=round(random.uniform(25.0, 45.0), 1),
        topPages=top_pages,
        userGrowth=user_growth,
        hourlyActivity=hourly_activity
    )

def generate_performance_metrics(start_date: datetime, end_date: datetime) -> PerformanceMetrics:
    """Generate realistic performance metrics."""
    # Base response times with variation
    base_avg_time = random.uniform(180, 350)
    
    # Response time history
    history = []
    hours = min(int((end_date - start_date).total_seconds() / 3600), 48)
    for i in range(hours):
        timestamp = start_date + timedelta(hours=i)
        avg_time = base_avg_time + random.uniform(-50, 100)
        history.append({
            'timestamp': timestamp.isoformat(),
            'avgTime': round(avg_time, 1),
            'p95Time': round(avg_time * random.uniform(1.5, 2.2), 1)
        })
    
    # Error breakdown
    error_types = ['timeout', '500_internal', '404_not_found', 'auth_failed', 'validation']
    error_breakdown = []
    total_errors = random.randint(50, 200)
    for error_type in error_types:
        count = random.randint(5, 50)
        error_breakdown.append({
            'type': error_type,
            'count': count,
            'percentage': round(count / total_errors * 100, 1)
        })
    
    # Endpoint performance
    endpoints = [
        '/api/datasets', '/api/analyses', '/api/chat', '/api/kg/query', '/api/auth'
    ]
    endpoint_performance = []
    for endpoint in endpoints:
        calls = random.randint(1000, 10000)
        avg_time = base_avg_time + random.uniform(-100, 200)
        errors = random.randint(10, 100)
        
        endpoint_performance.append({
            'endpoint': endpoint,
            'avgTime': round(avg_time, 1),
            'calls': calls,
            'errors': errors
        })
    
    success_rate = random.uniform(97.5, 99.8)
    
    return PerformanceMetrics(
        avgResponseTime=round(base_avg_time, 1),
        p50ResponseTime=round(base_avg_time * 0.8, 1),
        p95ResponseTime=round(base_avg_time * 1.8, 1),
        p99ResponseTime=round(base_avg_time * 2.5, 1),
        successRate=round(success_rate, 2),
        errorRate=round(100 - success_rate, 2),
        throughput=round(random.uniform(45.0, 120.0), 1),
        uptime=round(random.uniform(99.2, 99.98), 2),
        responseTimeHistory=history,
        errorBreakdown=error_breakdown,
        endpointPerformance=endpoint_performance
    )

def generate_research_metrics(start_date: datetime, end_date: datetime) -> ResearchMetrics:
    """Generate realistic research metrics."""
    
    # Datasets used
    datasets = {
        'OpenNeuro ds000001': random.randint(50, 200),
        'HCP Young Adult': random.randint(30, 150),
        'ABCD Study': random.randint(25, 100),
        'UK Biobank': random.randint(15, 80),
        'OASIS-3': random.randint(20, 90)
    }
    
    # Tools used
    tools = {
        'FSL': random.randint(100, 300),
        'FreeSurfer': random.randint(80, 250),
        'AFNI': random.randint(60, 180),
        'ANTs': random.randint(40, 120),
        'SPM': random.randint(50, 150),
        'Nilearn': random.randint(70, 200)
    }
    
    # Popular workflows
    workflows = [
        {'workflow': 'fMRI Preprocessing', 'usage': random.randint(80, 200), 'successRate': random.uniform(85, 98)},
        {'workflow': 'Structural Analysis', 'usage': random.randint(60, 150), 'successRate': random.uniform(90, 99)},
        {'workflow': 'GLM Analysis', 'usage': random.randint(50, 120), 'successRate': random.uniform(88, 96)},
        {'workflow': 'Connectivity Analysis', 'usage': random.randint(30, 80), 'successRate': random.uniform(82, 94)},
        {'workflow': 'Group Comparison', 'usage': random.randint(40, 100), 'successRate': random.uniform(87, 97)}
    ]
    
    # Tool usage trends
    trends = []
    days = min((end_date - start_date).days, 30)
    for i in range(days):
        date = start_date + timedelta(days=i)
        tool_usage = {}
        for tool in list(tools.keys())[:5]:  # Top 5 tools
            tool_usage[tool] = random.randint(5, 25)
        
        trends.append({
            'date': date.isoformat(),
            'toolUsage': tool_usage
        })
    
    return ResearchMetrics(
        analysesRun=random.randint(450, 800),
        datasetsUsed=datasets,
        toolsUsed=tools,
        popularWorkflows=workflows,
        publicationMetrics={
            'totalCitations': random.randint(500, 2000),
            'hIndex': random.randint(25, 60),
            'recentPublications': random.randint(5, 20)
        },
        datasetStats={
            'totalDatasets': random.randint(50, 150),
            'totalSubjects': random.randint(10000, 50000),
            'modalityBreakdown': {
                'fmri': random.randint(15, 40),
                'smri': random.randint(20, 50),
                'dwi': random.randint(10, 25),
                'pet': random.randint(5, 15)
            }
        },
        toolUsageTrends=trends
    )

def generate_system_metrics(start_date: datetime, end_date: datetime) -> SystemMetrics:
    """Generate realistic system metrics."""
    
    # Resource usage with realistic patterns
    cpu_usage = random.uniform(25.0, 85.0)
    memory_usage = random.uniform(45.0, 78.0)
    gpu_usage = random.uniform(15.0, 65.0)
    storage_usage = random.uniform(35.0, 70.0)
    
    # Resource history
    history = []
    hours = min(int((end_date - start_date).total_seconds() / 3600), 48)
    for i in range(hours):
        timestamp = start_date + timedelta(hours=i)
        # Add some variation but keep it realistic
        history.append({
            'timestamp': timestamp.isoformat(),
            'cpu': round(cpu_usage + random.uniform(-15, 15), 1),
            'memory': round(memory_usage + random.uniform(-10, 10), 1),
            'gpu': round(gpu_usage + random.uniform(-20, 20), 1),
            'storage': round(storage_usage + random.uniform(-5, 5), 1)
        })
    
    # Job queue
    job_queue = []
    job_types = ['fmri_preproc', 'structural_analysis', 'group_stats', 'connectivity']
    statuses = ['running', 'queued', 'completed', 'failed']
    
    for i in range(random.randint(20, 50)):
        status = random.choice(statuses)
        start_time = start_date + timedelta(hours=random.randint(-24, 0))
        duration = random.randint(300, 7200) if status in ['completed', 'failed'] else None
        
        job_queue.append({
            'id': f'job_{i:04d}',
            'type': random.choice(job_types),
            'status': status,
            'startTime': start_time.isoformat() if status != 'queued' else None,
            'duration': duration,
            'user': f'user_{random.randint(1, 20):02d}'
        })
    
    queue_length = len([j for j in job_queue if j['status'] == 'queued'])
    active_jobs = len([j for j in job_queue if j['status'] == 'running'])
    completed_jobs = len([j for j in job_queue if j['status'] == 'completed'])
    failed_jobs = len([j for j in job_queue if j['status'] == 'failed'])
    
    return SystemMetrics(
        cpuUsage=cpu_usage,
        memoryUsage=memory_usage,
        gpuUsage=gpu_usage,
        storageUsage=storage_usage,
        queueLength=queue_length,
        activeJobs=active_jobs,
        completedJobs=completed_jobs,
        failedJobs=failed_jobs,
        resourceHistory=history,
        jobQueue=job_queue
    )

def generate_engagement_metrics(start_date: datetime, end_date: datetime) -> EngagementMetrics:
    """Generate realistic engagement metrics."""
    
    dau = random.randint(200, 500)
    wau = random.randint(800, 1500)  
    mau = random.randint(2000, 4000)
    
    # Conversion funnels
    funnels = [
        {
            'name': 'User Onboarding',
            'steps': [
                {'step': 'Sign Up', 'users': 1000, 'conversionRate': 100.0},
                {'step': 'First Login', 'users': 850, 'conversionRate': 85.0},
                {'step': 'Tutorial Complete', 'users': 680, 'conversionRate': 68.0},
                {'step': 'First Analysis', 'users': 520, 'conversionRate': 52.0}
            ]
        }
    ]
    
    # Feature adoption
    features = ['Dashboard', 'Dataset Explorer', 'Chat Interface', 'Analytics', 'Knowledge Graph']
    feature_adoption = []
    for feature in features:
        adoption_rate = random.uniform(25.0, 85.0)
        active_users = int(dau * adoption_rate / 100)
        feature_adoption.append({
            'feature': feature,
            'adoptionRate': round(adoption_rate, 1),
            'activeUsers': active_users
        })
    
    # User segments
    segments = [
        {'segment': 'New Users', 'users': random.randint(200, 400), 'engagement': random.uniform(60, 80)},
        {'segment': 'Active Researchers', 'users': random.randint(150, 300), 'engagement': random.uniform(85, 95)},
        {'segment': 'Casual Users', 'users': random.randint(100, 250), 'engagement': random.uniform(40, 65)},
        {'segment': 'Power Users', 'users': random.randint(50, 150), 'engagement': random.uniform(90, 98)}
    ]
    
    return EngagementMetrics(
        dailyActiveUsers=dau,
        weeklyActiveUsers=wau,
        monthlyActiveUsers=mau,
        retentionRate=round(random.uniform(72.0, 88.0), 1),
        churnRate=round(random.uniform(8.0, 15.0), 1),
        avgTimeOnSite=round(random.uniform(15.5, 32.0), 1),
        conversionFunnels=funnels,
        featureAdoption=feature_adoption,
        userSegments=segments
    )

# Storage for custom reports and alerts
custom_reports_storage: List[CustomReport] = []
alerts_storage: List[AlertConfig] = []

# Enhanced Analytics Endpoints
@router.get("/analytics/usage", response_model=UsageMetrics)
async def get_usage_metrics(
    start: str = Query(..., description="Start date in ISO format"),
    end: str = Query(..., description="End date in ISO format"),
    segment: Optional[str] = Query(None, description="User segment filter")
):
    """Get comprehensive usage analytics metrics."""
    try:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    return generate_usage_metrics(start_date, end_date)

@router.get("/analytics/performance", response_model=PerformanceMetrics)
async def get_performance_metrics(
    start: str = Query(..., description="Start date in ISO format"),
    end: str = Query(..., description="End date in ISO format")
):
    """Get comprehensive performance analytics metrics."""
    try:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    return generate_performance_metrics(start_date, end_date)

@router.get("/analytics/research", response_model=ResearchMetrics)
async def get_research_metrics(
    start: str = Query(..., description="Start date in ISO format"),
    end: str = Query(..., description="End date in ISO format")
):
    """Get comprehensive research analytics metrics."""
    try:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    return generate_research_metrics(start_date, end_date)

@router.get("/analytics/system", response_model=SystemMetrics)
async def get_system_metrics(
    start: str = Query(..., description="Start date in ISO format"),
    end: str = Query(..., description="End date in ISO format")
):
    """Get comprehensive system health metrics."""
    try:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    return generate_system_metrics(start_date, end_date)

@router.get("/analytics/engagement", response_model=EngagementMetrics)
async def get_engagement_metrics(
    start: str = Query(..., description="Start date in ISO format"),
    end: str = Query(..., description="End date in ISO format")
):
    """Get comprehensive user engagement metrics."""
    try:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    return generate_engagement_metrics(start_date, end_date)

# Export endpoints
@router.get("/analytics/export")
async def export_analytics_data(
    format: str = Query(..., description="Export format: csv, pdf, json"),
    start: str = Query(..., description="Start date in ISO format"),
    end: str = Query(..., description="End date in ISO format")
):
    """Export analytics data in various formats."""
    if format not in ['csv', 'pdf', 'json']:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    try:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    # Generate all metrics
    usage = generate_usage_metrics(start_date, end_date)
    performance = generate_performance_metrics(start_date, end_date)
    research = generate_research_metrics(start_date, end_date)
    system = generate_system_metrics(start_date, end_date)
    engagement = generate_engagement_metrics(start_date, end_date)
    
    export_data = {
        'usage': usage.model_dump(),
        'performance': performance.model_dump(),
        'research': research.model_dump(),
        'system': system.model_dump(),
        'engagement': engagement.model_dump(),
        'metadata': {
            'exportTime': datetime.now().isoformat(),
            'dateRange': {'start': start, 'end': end},
            'format': format
        }
    }
    
    if format == 'json':
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=export_data,
            headers={'Content-Disposition': f'attachment; filename=analytics-{start_date.strftime("%Y%m%d")}-{end_date.strftime("%Y%m%d")}.json'}
        )
    elif format == 'csv':
        # For demo purposes, return a simple CSV structure
        csv_content = "metric,category,value,timestamp\n"
        csv_content += f"totalUsers,usage,{usage.totalUsers},{start_date.isoformat()}\n"
        csv_content += f"activeUsers,usage,{usage.activeUsers},{start_date.isoformat()}\n"
        csv_content += f"avgResponseTime,performance,{performance.avgResponseTime},{start_date.isoformat()}\n"
        csv_content += f"successRate,performance,{performance.successRate},{start_date.isoformat()}\n"
        
        from fastapi.responses import Response
        return Response(
            content=csv_content,
            media_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename=analytics-{start_date.strftime("%Y%m%d")}-{end_date.strftime("%Y%m%d")}.csv'}
        )
    else:  # PDF
        # For demo purposes, return JSON with PDF instructions
        return {
            "message": "PDF export would be generated here",
            "data": export_data,
            "filename": f"analytics-{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}.pdf"
        }

# Custom Reports endpoints
@router.get("/analytics/reports", response_model=List[CustomReport])
async def get_custom_reports():
    """Get all custom reports."""
    return custom_reports_storage

@router.post("/analytics/reports", response_model=CustomReport)
async def create_custom_report(report_data: Dict[str, Any]):
    """Create a new custom report."""
    report = CustomReport(
        id=f"report_{len(custom_reports_storage) + 1:04d}",
        name=report_data['name'],
        description=report_data.get('description'),
        charts=report_data['charts'],
        filters=report_data['filters'],
        schedule=report_data.get('schedule'),
        createdAt=datetime.now(),
        updatedAt=datetime.now()
    )
    
    custom_reports_storage.append(report)
    return report

@router.patch("/analytics/reports/{report_id}", response_model=CustomReport)
async def update_custom_report(report_id: str, updates: Dict[str, Any]):
    """Update an existing custom report."""
    for i, report in enumerate(custom_reports_storage):
        if report.id == report_id:
            # Update fields
            for key, value in updates.items():
                if hasattr(report, key):
                    setattr(report, key, value)
            report.updatedAt = datetime.now()
            custom_reports_storage[i] = report
            return report
    
    raise HTTPException(status_code=404, detail="Report not found")

@router.delete("/analytics/reports/{report_id}")
async def delete_custom_report(report_id: str):
    """Delete a custom report."""
    for i, report in enumerate(custom_reports_storage):
        if report.id == report_id:
            del custom_reports_storage[i]
            return {"status": "deleted"}
    
    raise HTTPException(status_code=404, detail="Report not found")

# Alerts endpoints
@router.get("/analytics/alerts", response_model=List[AlertConfig])
async def get_alerts():
    """Get all alert configurations."""
    return alerts_storage

@router.post("/analytics/alerts", response_model=AlertConfig)
async def create_alert(alert_data: Dict[str, Any]):
    """Create a new alert configuration."""
    alert = AlertConfig(
        id=f"alert_{len(alerts_storage) + 1:04d}",
        name=alert_data['name'],
        metric=alert_data['metric'],
        threshold=alert_data['threshold'],
        condition=alert_data['condition'],
        severity=alert_data['severity'],
        enabled=alert_data.get('enabled', True),
        recipients=alert_data['recipients']
    )
    
    alerts_storage.append(alert)
    return alert

@router.patch("/analytics/alerts/{alert_id}", response_model=AlertConfig)
async def update_alert(alert_id: str, updates: Dict[str, Any]):
    """Update an existing alert configuration."""
    for i, alert in enumerate(alerts_storage):
        if alert.id == alert_id:
            for key, value in updates.items():
                if hasattr(alert, key):
                    setattr(alert, key, value)
            alerts_storage[i] = alert
            return alert
    
    raise HTTPException(status_code=404, detail="Alert not found")

@router.delete("/analytics/clear")
async def clear_analytics_data():
    """Clear all analytics data (for testing only)."""
    global events_storage, errors_storage, session_data, funnel_data, custom_reports_storage, alerts_storage
    events_storage = []
    errors_storage = []
    session_data = {}
    funnel_data = {}
    custom_reports_storage = []
    alerts_storage = []
    return {"status": "cleared"}
