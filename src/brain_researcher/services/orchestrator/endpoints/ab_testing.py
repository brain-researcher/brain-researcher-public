"""
A/B Testing and Analytics endpoints for the orchestrator service.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import random
import uuid
from fastapi import APIRouter, Request, Response, Query, Body, Cookie
from pydantic import BaseModel

# ============================================================================
# Models for A/B Testing
# ============================================================================

class ABTestVariant(BaseModel):
    test: str
    variant: str
    assigned_at: datetime

class ABTestAssignment(BaseModel):
    variant: str
    test_name: str
    cookie_name: str
    expires_at: datetime

class ABTestEvent(BaseModel):
    test: str
    variant: str
    event: str
    conversion_type: Optional[str] = None
    timestamp: datetime
    metadata: Dict[str, Any] = {}

class AnalyticsEvent(BaseModel):
    event: str
    data: Dict[str, Any]
    timestamp: datetime
    session_id: Optional[str] = None
    user_id: Optional[str] = None

class AnalyticsBatch(BaseModel):
    events: List[AnalyticsEvent]

# ============================================================================
# Router setup
# ============================================================================

router = APIRouter(prefix="/api", tags=["ab_testing", "analytics"])

# In-memory storage for A/B tests and analytics
ab_test_assignments: Dict[str, Dict[str, ABTestVariant]] = {}  # session_id -> test -> variant
analytics_events: List[AnalyticsEvent] = []
ab_test_configs: Dict[str, Dict] = {
    "landing_hero_v1": {
        "variants": ["A", "B"],
        "traffic_split": {"A": 50, "B": 50},
        "status": "active"
    },
    "demo_cta_v1": {
        "variants": ["button", "banner", "both"],
        "traffic_split": {"button": 33, "banner": 33, "both": 34},
        "status": "active"
    },
    "onboarding_v1": {
        "variants": ["simple", "guided", "interactive"],
        "traffic_split": {"simple": 33, "guided": 33, "interactive": 34},
        "status": "active"
    }
}

# ============================================================================
# A/B Testing Endpoints
# ============================================================================

@router.get("/ab/assign")
async def assign_ab_variant(
    request: Request,
    response: Response,
    test: str = Query(..., description="Test name"),
    session_id: Optional[str] = Cookie(None)
):
    """Assign or retrieve A/B test variant for a user."""

    # Get or create session ID
    if not session_id:
        session_id = f"session_{uuid.uuid4().hex[:16]}"
        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=30 * 24 * 60 * 60,  # 30 days
            httponly=True,
            samesite="lax"
        )

    # Check if test exists
    if test not in ab_test_configs:
        return {"error": "Test not found", "test": test}

    test_config = ab_test_configs[test]

    # Check if already assigned
    if session_id in ab_test_assignments and test in ab_test_assignments[session_id]:
        variant_info = ab_test_assignments[session_id][test]
        return {"variant": variant_info.variant, "test": test}

    # Assign new variant based on traffic split
    variants = test_config["variants"]
    traffic_split = test_config["traffic_split"]

    # Weighted random selection
    rand_num = random.randint(1, 100)
    cumulative = 0
    selected_variant = variants[0]  # default

    for variant, percentage in traffic_split.items():
        cumulative += percentage
        if rand_num <= cumulative:
            selected_variant = variant
            break

    # Store assignment
    if session_id not in ab_test_assignments:
        ab_test_assignments[session_id] = {}

    ab_test_assignments[session_id][test] = ABTestVariant(
        test=test,
        variant=selected_variant,
        assigned_at=datetime.utcnow()
    )

    # Set cookie for this specific test
    cookie_name = f"ab_{test}"
    response.set_cookie(
        key=cookie_name,
        value=selected_variant,
        max_age=30 * 24 * 60 * 60,  # 30 days
        httponly=False,  # Allow JavaScript access
        samesite="lax"
    )

    # Track assignment event
    analytics_events.append(AnalyticsEvent(
        event="ab_test_assigned",
        data={
            "test": test,
            "variant": selected_variant,
            "session_id": session_id
        },
        timestamp=datetime.utcnow(),
        session_id=session_id
    ))

    return {"variant": selected_variant, "test": test}

@router.post("/ab/track")
async def track_ab_conversion(
    event: ABTestEvent,
    session_id: Optional[str] = Cookie(None)
):
    """Track conversion or other events for A/B tests."""

    # Store event
    analytics_events.append(AnalyticsEvent(
        event=f"ab_{event.event}",
        data={
            "test": event.test,
            "variant": event.variant,
            "conversion_type": event.conversion_type,
            **event.metadata
        },
        timestamp=event.timestamp,
        session_id=session_id
    ))

    return {"status": "success", "tracked": True}

@router.post("/ab/event")
async def track_ab_event(
    request: Request,
    event_data: Dict[str, Any] = Body(...),
    session_id: Optional[str] = Cookie(None)
):
    """Track custom events with A/B test context."""

    # Add session context
    if session_id and session_id in ab_test_assignments:
        event_data["ab_variants"] = {
            test: variant.variant
            for test, variant in ab_test_assignments[session_id].items()
        }

    # Store event
    analytics_events.append(AnalyticsEvent(
        event=event_data.get("event", "custom_event"),
        data=event_data.get("data", {}),
        timestamp=datetime.fromisoformat(event_data.get("timestamp", datetime.utcnow().isoformat())),
        session_id=session_id
    ))

    return {"status": "success"}

@router.get("/ab/status/{test}")
async def get_ab_test_status(test: str):
    """Get status and metrics for an A/B test."""

    if test not in ab_test_configs:
        return {"error": "Test not found", "test": test}

    config = ab_test_configs[test]

    # Calculate metrics
    test_events = [e for e in analytics_events if
                   e.event.startswith("ab_") and
                   e.data.get("test") == test]

    assignments = {}
    conversions = {}

    for variant in config["variants"]:
        variant_events = [e for e in test_events if e.data.get("variant") == variant]
        assignments[variant] = sum(1 for e in variant_events if "assigned" in e.event)
        conversions[variant] = sum(1 for e in variant_events if "conversion" in e.event)

    # Calculate conversion rates
    conversion_rates = {}
    for variant in config["variants"]:
        if assignments[variant] > 0:
            conversion_rates[variant] = (conversions[variant] / assignments[variant]) * 100
        else:
            conversion_rates[variant] = 0

    return {
        "test": test,
        "status": config["status"],
        "variants": config["variants"],
        "traffic_split": config["traffic_split"],
        "assignments": assignments,
        "conversions": conversions,
        "conversion_rates": conversion_rates
    }

# ============================================================================
# Analytics Endpoints
# ============================================================================

@router.post("/ab/events")
async def track_analytics_events(
    batch: AnalyticsBatch,
    session_id: Optional[str] = Cookie(None)
):
    """Track batch of analytics events."""

    for event in batch.events:
        # Add session ID if not present
        if not event.session_id and session_id:
            event.session_id = session_id

        analytics_events.append(event)

    return {
        "status": "success",
        "events_tracked": len(batch.events)
    }

@router.get("/ab/events/stats")
async def get_analytics_stats(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    event_type: Optional[str] = None
):
    """Get analytics statistics."""

    # Filter events
    filtered_events = analytics_events

    if start_time:
        filtered_events = [e for e in filtered_events if e.timestamp >= start_time]

    if end_time:
        filtered_events = [e for e in filtered_events if e.timestamp <= end_time]

    if event_type:
        filtered_events = [e for e in filtered_events if e.event == event_type]

    # Calculate stats
    event_counts = {}
    for event in filtered_events:
        event_counts[event.event] = event_counts.get(event.event, 0) + 1

    # Get unique sessions
    unique_sessions = set(e.session_id for e in filtered_events if e.session_id)
    unique_users = set(e.user_id for e in filtered_events if e.user_id)

    return {
        "total_events": len(filtered_events),
        "unique_sessions": len(unique_sessions),
        "unique_users": len(unique_users),
        "event_counts": event_counts,
        "time_range": {
            "start": start_time.isoformat() if start_time else None,
            "end": end_time.isoformat() if end_time else None
        }
    }

@router.get("/ab/events/funnel/{funnel_name}")
async def get_funnel_analytics(
    funnel_name: str,
    session_id: Optional[str] = Query(None)
):
    """Get funnel analytics for conversion tracking."""

    # Define funnels
    funnels = {
        "demo_completion": [
            "hero_demo_clicked",
            "demo_started",
            "demo_processing",
            "demo_completed"
        ],
        "signup": [
            "signup_button_clicked",
            "signup_form_viewed",
            "signup_form_submitted",
            "signup_completed"
        ],
        "first_execution": [
            "landing_viewed",
            "demo_clicked",
            "run_submitted",
            "first_successful_execution"
        ]
    }

    if funnel_name not in funnels:
        return {"error": "Funnel not found", "funnel": funnel_name}

    funnel_steps = funnels[funnel_name]

    # Calculate funnel metrics
    step_counts = {}
    for step in funnel_steps:
        if session_id:
            count = sum(1 for e in analytics_events
                       if e.event == step and e.session_id == session_id)
        else:
            count = sum(1 for e in analytics_events if e.event == step)
        step_counts[step] = count

    # Calculate conversion rates
    conversion_rates = []
    for i, step in enumerate(funnel_steps):
        if i == 0:
            conversion_rates.append(100.0)
        else:
            prev_count = step_counts[funnel_steps[i-1]]
            curr_count = step_counts[step]
            if prev_count > 0:
                rate = (curr_count / prev_count) * 100
            else:
                rate = 0
            conversion_rates.append(rate)

    return {
        "funnel": funnel_name,
        "steps": funnel_steps,
        "step_counts": step_counts,
        "conversion_rates": conversion_rates,
        "overall_conversion": conversion_rates[-1] if conversion_rates else 0
    }

@router.post("/ab/events/error")
async def track_error_event(
    error_data: Dict[str, Any] = Body(...),
    session_id: Optional[str] = Cookie(None)
):
    """Track error events for monitoring."""

    analytics_events.append(AnalyticsEvent(
        event="error",
        data=error_data,
        timestamp=datetime.utcnow(),
        session_id=session_id
    ))

    return {"status": "success", "tracked": True}

# Export router to be included in main app
__all__ = ["router"]
