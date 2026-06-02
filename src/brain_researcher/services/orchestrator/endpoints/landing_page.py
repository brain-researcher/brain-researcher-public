"""
Landing page API endpoints for demos and examples

NOTE: Endpoints using DEMO_SCENARIOS are legacy/fake demos for UI prototyping.
These are blocked in production mode. Use /api/demo/* endpoints for real demos.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/landing", tags=["landing"])


def require_dev_mode(func: Callable) -> Callable:
    """
    Decorator to block endpoints in production mode.

    Legacy demo endpoints using DEMO_SCENARIOS should only be
    accessible in development mode (BR_DEMO_MODE=development).

    In production, returns 404 with migration instructions.
    """

    @wraps(func)
    async def wrapper(*args, response: Response = None, **kwargs):
        if config.is_production_mode():
            # Block access in production
            logger.warning(
                f"Blocked access to legacy demo endpoint {func.__name__} "
                f"in production mode. Set BR_DEMO_MODE=development to enable."
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "Legacy demo endpoint not available in production",
                    "message": "This endpoint serves fake/mock demo data and is disabled in production mode.",
                    "migration": "Use /api/demo/real-* endpoints for production demo results",
                    "docs": "See /docs for available endpoints",
                },
            )

        # Add deprecation headers
        if response:
            response.headers["X-Deprecated"] = "true"
            response.headers["X-Migration-Path"] = "/api/demo/real-*"
            response.headers["Warning"] = (
                '299 - "This endpoint serves mock data. Use /api/demo/real-* for production."'
            )

        logger.info(f"Serving legacy demo endpoint {func.__name__} in development mode")

        return await func(*args, response=response, **kwargs)

    return wrapper


# Enums
class DemoType(str, Enum):
    GLM = "glm"
    CONNECTIVITY = "connectivity"
    DMN = "dmn"
    PREPROCESSING = "preprocessing"
    GROUP = "group"
    META = "meta"


class DemoStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# Models
class DemoRequest(BaseModel):
    demo_type: DemoType
    user_email: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = {}


class DemoProgress(BaseModel):
    demo_id: str
    status: DemoStatus
    progress: int = Field(0, ge=0, le=100)
    current_step: str
    steps_completed: List[str] = []
    estimated_time_remaining: Optional[int] = None  # seconds


class DemoResult(BaseModel):
    demo_id: str
    demo_type: DemoType
    status: DemoStatus
    duration: int  # seconds
    outputs: List[Dict[str, Any]]
    visualizations: List[Dict[str, Any]]
    evidence_rail: List[Dict[str, Any]]
    run_card: Dict[str, Any]
    share_link: str
    citation: str


class ExampleCard(BaseModel):
    id: str
    title: str
    description: str
    demo_type: DemoType
    duration: str
    difficulty: str
    tags: List[str]
    popularity: int
    thumbnail_url: str


class TrustMetric(BaseModel):
    metric: str
    value: str
    label: str
    updated_at: datetime


# In-memory storage (replace with database in production)
demo_results: Dict[str, DemoResult] = {}
demo_progress: Dict[str, DemoProgress] = {}
demo_queue: List[str] = []

# Pre-configured demo scenarios
DEMO_SCENARIOS = {
    DemoType.GLM: {
        "title": "Motor Task GLM Analysis",
        "steps": [
            "Loading sample fMRI data",
            "Preprocessing: Motion correction",
            "Preprocessing: Spatial smoothing",
            "Running GLM analysis",
            "Generating statistical maps",
            "Creating visualizations",
        ],
        "duration": 85,
        "outputs": [
            {"name": "zmap.nii.gz", "type": "nifti", "size": "12.3 MB"},
            {"name": "peaks_table.csv", "type": "csv", "size": "45 KB"},
            {"name": "design_matrix.png", "type": "image", "size": "156 KB"},
        ],
    },
    DemoType.CONNECTIVITY: {
        "title": "Resting State Connectivity Analysis",
        "steps": [
            "Loading resting state data",
            "Extracting time series",
            "Computing correlation matrix",
            "Applying network analysis",
            "Generating connectivity maps",
        ],
        "duration": 120,
        "outputs": [
            {"name": "correlation_matrix.csv", "type": "csv", "size": "2.1 MB"},
            {"name": "network_graph.html", "type": "html", "size": "456 KB"},
        ],
    },
    DemoType.DMN: {
        "title": "Default Mode Network Analysis",
        "steps": [
            "Loading preprocessed data",
            "Seed-based correlation",
            "ICA decomposition",
            "Component selection",
            "3D visualization generation",
        ],
        "duration": 60,
        "outputs": [
            {"name": "dmn_map.nii.gz", "type": "nifti", "size": "8.7 MB"},
            {"name": "components.json", "type": "json", "size": "234 KB"},
        ],
    },
}


# Demo execution
async def execute_demo(demo_id: str, demo_type: DemoType):
    """Execute a demo scenario"""
    scenario = DEMO_SCENARIOS.get(demo_type)
    if not scenario:
        raise ValueError(f"Unknown demo type: {demo_type}")

    # Initialize progress
    demo_progress[demo_id] = DemoProgress(
        demo_id=demo_id,
        status=DemoStatus.RUNNING,
        progress=0,
        current_step=scenario["steps"][0],
        steps_completed=[],
        estimated_time_remaining=scenario["duration"],
    )

    # Simulate step execution
    total_steps = len(scenario["steps"])
    for i, step in enumerate(scenario["steps"]):
        # Update progress
        demo_progress[demo_id].current_step = step
        demo_progress[demo_id].progress = int((i / total_steps) * 100)
        demo_progress[demo_id].estimated_time_remaining = scenario["duration"] - int(
            (i / total_steps) * scenario["duration"]
        )

        # Simulate processing time
        await asyncio.sleep(
            scenario["duration"] / total_steps / 10
        )  # Speed up for demo

        demo_progress[demo_id].steps_completed.append(step)

    # Generate result
    from brain_researcher.core.contracts.ids import IdsV1
    from brain_researcher.core.contracts.run_card import RunCardV1

    run_id = f"run_{demo_id}"
    run_card = RunCardV1(
        ids=IdsV1(
            analysis_id=run_id,
            run_id=run_id,
            job_id=run_id,
        ),
        id=run_id,
        version="1.0",
        timestamp=datetime.utcnow(),
        title=scenario.get("title"),
        description="Legacy demo run (dev-only).",
        reproducibility_score=None,
        parameters={
            "smoothing": "6mm",
            "threshold": "p<0.001",
            "correction": "FWE",
        },
        environment={
            "fsl_version": "6.0.5",
            "python_version": "3.9.16",
            "dependencies": ["nipype==1.8.6", "nilearn==0.10.1"],
        },
    ).model_dump(mode="json", exclude_none=True)
    run_card.setdefault("run_id", run_id)

    demo_results[demo_id] = DemoResult(
        demo_id=demo_id,
        demo_type=demo_type,
        status=DemoStatus.COMPLETED,
        duration=scenario["duration"],
        outputs=scenario["outputs"],
        visualizations=[
            {
                "type": "3d_brain",
                "url": f"/api/landing/demos/{demo_id}/viz/brain",
                "thumbnail": f"/api/landing/demos/{demo_id}/viz/brain/thumb",
            },
            {
                "type": "statistical_map",
                "url": f"/api/landing/demos/{demo_id}/viz/stats",
                "thumbnail": f"/api/landing/demos/{demo_id}/viz/stats/thumb",
            },
        ],
        evidence_rail=[
            {
                "type": "dataset",
                "name": "OpenNeuro ds000114",
                "description": "Motor task fMRI dataset",
                "url": "https://openneuro.org/datasets/ds000114",
            },
            {
                "type": "tool",
                "name": "FSL FEAT",
                "version": "6.0.5",
                "citation": "Smith et al., NeuroImage 2004",
            },
            {"type": "parameter", "name": "Smoothing kernel", "value": "6mm FWHM"},
        ],
        run_card=run_card,
        share_link=f"https://brain-researcher.ai/share/{demo_id}",
        citation=f"Brain Researcher (2024). {scenario['title']}. Demo ID: {demo_id}. https://brain-researcher.ai/share/{demo_id}",
    )

    # Update final progress
    demo_progress[demo_id].status = DemoStatus.COMPLETED
    demo_progress[demo_id].progress = 100


# Endpoints
@router.post("/demos/start")
@require_dev_mode
async def start_demo(
    request: DemoRequest, background_tasks: BackgroundTasks, response: Response
) -> Dict[str, Any]:
    """
    [LEGACY/DEV-ONLY] Start a new fake demo execution.

    This endpoint uses DEMO_SCENARIOS mock data and is only available
    in development mode (BR_DEMO_MODE=development).

    For production, use /api/demo/real-* endpoints instead.
    """
    demo_id = str(uuid.uuid4())[:8]

    # Add to queue
    demo_queue.append(demo_id)

    # Start execution in background
    background_tasks.add_task(execute_demo, demo_id, request.demo_type)

    return {
        "demo_id": demo_id,
        "status": "started",
        "estimated_duration": DEMO_SCENARIOS[request.demo_type]["duration"],
        "queue_position": len(demo_queue),
    }


@router.get("/demos/{demo_id}/progress")
@require_dev_mode
async def get_demo_progress(demo_id: str, response: Response) -> DemoProgress:
    """[LEGACY/DEV-ONLY] Get current progress of a fake demo"""
    if demo_id not in demo_progress:
        raise HTTPException(status_code=404, detail="Demo not found")

    return demo_progress[demo_id]


@router.get("/demos/{demo_id}/result")
@require_dev_mode
async def get_demo_result(demo_id: str, response: Response) -> DemoResult:
    """[LEGACY/DEV-ONLY] Get fake demo results"""
    if demo_id not in demo_results:
        raise HTTPException(status_code=404, detail="Demo result not found")

    return demo_results[demo_id]


@router.get("/demos/{demo_id}/stream")
@require_dev_mode
async def stream_demo_progress(demo_id: str, response: Response):
    """[LEGACY/DEV-ONLY] Stream fake demo progress via SSE"""

    async def generate():
        while demo_id in demo_progress:
            progress = demo_progress[demo_id]
            yield f"data: {progress.json()}\n\n"

            if progress.status in [DemoStatus.COMPLETED, DemoStatus.FAILED]:
                break

            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/examples")
async def get_example_cards() -> List[ExampleCard]:
    """Get example cards for the gallery"""
    return [
        ExampleCard(
            id="motor-glm",
            title="Motor Task GLM Analysis",
            description="Analyze brain activation during finger-tapping",
            demo_type=DemoType.GLM,
            duration="90 seconds",
            difficulty="Beginner",
            tags=["fMRI", "GLM", "Motor"],
            popularity=95,
            thumbnail_url="/images/motor-glm-thumb.jpg",
        ),
        ExampleCard(
            id="resting-connectivity",
            title="Resting State Networks",
            description="Discover functional brain networks",
            demo_type=DemoType.CONNECTIVITY,
            duration="2 minutes",
            difficulty="Intermediate",
            tags=["Resting State", "Networks"],
            popularity=88,
            thumbnail_url="/images/resting-thumb.jpg",
        ),
        ExampleCard(
            id="dmn-analysis",
            title="Default Mode Network",
            description="Interactive 3D DMN visualization",
            demo_type=DemoType.DMN,
            duration="60 seconds",
            difficulty="Beginner",
            tags=["DMN", "3D", "ICA"],
            popularity=92,
            thumbnail_url="/images/dmn-thumb.jpg",
        ),
    ]


@router.get("/trust-metrics")
async def get_trust_metrics() -> List[TrustMetric]:
    """Get trust metrics for the trust strip"""
    return [
        TrustMetric(
            metric="users",
            value="10,000+",
            label="Active Researchers",
            updated_at=datetime.now(),
        ),
        TrustMetric(
            metric="publications",
            value="500+",
            label="Publications",
            updated_at=datetime.now(),
        ),
        TrustMetric(
            metric="uptime",
            value="99.9%",
            label="Uptime SLA",
            updated_at=datetime.now(),
        ),
        TrustMetric(
            metric="rating",
            value="4.9/5",
            label="User Rating",
            updated_at=datetime.now(),
        ),
    ]


@router.get("/testimonials")
async def get_testimonials() -> List[Dict[str, Any]]:
    """Get user testimonials"""
    return [
        {
            "id": "test_1",
            "quote": "Brain Researcher transformed our lab's productivity. What took weeks now takes hours.",
            "author": "Dr. Sarah Chen",
            "title": "Principal Investigator",
            "institution": "Stanford Neuroscience Lab",
            "rating": 5,
        },
        {
            "id": "test_2",
            "quote": "The reproducibility features have made collaboration seamless across our multi-site study.",
            "author": "Prof. Michael Zhang",
            "title": "Department Chair",
            "institution": "Harvard Medical School",
            "rating": 5,
        },
    ]


@router.post("/demos/{demo_id}/share")
@require_dev_mode
async def create_share_link(demo_id: str, response: Response) -> Dict[str, str]:
    """[LEGACY/DEV-ONLY] Create a shareable link for fake demo results"""
    if demo_id not in demo_results:
        raise HTTPException(status_code=404, detail="Demo not found")

    share_token = str(uuid.uuid4())[:12]
    share_url = f"https://brain-researcher.ai/share/{share_token}"

    # In production, save share token to database

    return {
        "share_url": share_url,
        "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
    }


@router.get("/demos/{demo_id}/download/{file_type}")
async def download_demo_output(demo_id: str, file_type: str):
    """Download demo output files"""
    # Validate file_type
    if file_type not in ["pdf", "png", "nifti", "csv"]:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if demo_id not in demo_results:
        raise HTTPException(status_code=404, detail="Demo not found")

    # In production, generate actual files
    content = f"Demo output for {demo_id} in {file_type} format"

    return StreamingResponse(
        iter([content.encode()]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=demo_{demo_id}.{file_type}"
        },
    )


@router.post("/analytics/event")
async def track_analytics_event(
    event_name: str, event_data: Dict[str, Any]
) -> Dict[str, str]:
    """Track analytics events from landing page"""
    # In production, send to analytics service
    print(f"Analytics Event: {event_name} - {event_data}")

    return {"status": "tracked", "event_id": str(uuid.uuid4())}


@router.get("/status")
async def get_landing_page_status() -> Dict[str, Any]:
    """Get landing page component status"""
    return {
        "demos_available": len(DEMO_SCENARIOS),
        "queue_length": len(demo_queue),
        "active_demos": len(
            [d for d in demo_progress.values() if d.status == DemoStatus.RUNNING]
        ),
        "completed_demos": len(
            [d for d in demo_results.values() if d.status == DemoStatus.COMPLETED]
        ),
        "server_status": "healthy",
        "cache_status": "warm",
    }
