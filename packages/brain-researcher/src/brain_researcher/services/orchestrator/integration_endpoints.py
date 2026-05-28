"""
Integration endpoints for Chat, Evidence Rail, and Dataset components

This module provides REST endpoints for:
- Chat integration (threads, messages, streaming)
- Evidence Rail (provenance, run cards, artifacts)
- Dataset search and management

The Evidence Rail endpoints support real job data with mock fallback when:
- ENABLE_EVIDENCE_MOCK_FALLBACK=true (default)
- Job not found in jobs_db
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Response
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import json
import hashlib
import logging
import tempfile
import os
import platform
import psutil
import sys
from pathlib import Path
from sse_starlette.sse import EventSourceResponse

from brain_researcher.config.paths import get_data_root
from brain_researcher.core.contracts.run_card import RunCardV1 as RunCard

logger = logging.getLogger(__name__)

# Feature flag for mock fallback behavior
ENABLE_MOCK_FALLBACK = os.getenv("ENABLE_EVIDENCE_MOCK_FALLBACK", "true").lower() == "true"


# Chat Integration Models
class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content")
    attachments: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None

class ChatThread(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    status: str = "active"

class ChatRequest(BaseModel):
    content: str
    attachments: Optional[List[Dict[str, Any]]] = None
    stream: bool = True
    thread_id: Optional[str] = None


# Evidence Rail Models
class ProvenanceNode(BaseModel):
    id: str
    type: str = Field(..., description="Node type: dataset, tool, parameter, output")
    label: str
    metadata: Optional[Dict[str, Any]] = None

class ProvenanceEdge(BaseModel):
    source: str
    target: str
    label: Optional[str] = None

class ProvenanceGraph(BaseModel):
    nodes: List[ProvenanceNode]
    edges: List[ProvenanceEdge]


# Dataset Integration Models
class DatasetFilter(BaseModel):
    sources: Optional[List[str]] = None
    modalities: Optional[List[str]] = None
    subject_range: Optional[Dict[str, int]] = None
    tasks: Optional[List[str]] = None
    quality_score_min: Optional[float] = None
    has_derivatives: Optional[bool] = None
    bids_compliant: Optional[bool] = None

class Dataset(BaseModel):
    id: str
    name: str
    source: str
    modality: List[str]
    n_subjects: int
    n_sessions: Optional[int] = None
    tasks: Optional[List[str]] = None
    quality_score: Optional[float] = None
    size_gb: Optional[float] = None
    bids_version: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class DatasetSearchResult(BaseModel):
    datasets: List[Dataset]
    total_count: int
    page: int
    page_size: int
    facets: Dict[str, List[Dict[str, Any]]]


# =============================================================================
# Job Access Helpers (via adapter pattern, not direct dict access)
# =============================================================================

def _get_jobs_db():
    """
    Lazy import to get jobs_db from main_enhanced.

    Uses adapter pattern to avoid circular imports and maintain
    separation between integration_endpoints and main_enhanced.
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        return {}
    try:
        from .main_enhanced import jobs_db
        return jobs_db
    except ImportError:
        logger.warning("Could not import jobs_db from main_enhanced")
        return {}


def _get_enhanced_job_manager():
    """
    Lazy import to get EnhancedJobManager from main_enhanced.
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None
    try:
        from .main_enhanced import EnhancedJobManager
        return EnhancedJobManager
    except ImportError:
        logger.warning("Could not import EnhancedJobManager from main_enhanced")
        return None


async def get_job_safe(job_id: str) -> Optional[Any]:
    """
    Get job via adapter pattern, not direct dict access.

    This wrapper allows the integration endpoints to access job data
    without directly importing the jobs_db dict, which could bypass
    any JobStore adapters or caching layers.

    Args:
        job_id: The job identifier to look up

    Returns:
        Job object if found, None otherwise
    """
    jobs_db = _get_jobs_db()
    return jobs_db.get(job_id)


def _mock_provenance_graph() -> ProvenanceGraph:
    """Generate mock provenance graph for demo/fallback mode."""
    return ProvenanceGraph(
        nodes=[
            ProvenanceNode(id="ds_1", type="dataset", label="Input Dataset"),
            ProvenanceNode(id="tool_1", type="tool", label="Analysis Tool"),
            ProvenanceNode(id="out_1", type="output", label="Results")
        ],
        edges=[
            ProvenanceEdge(source="ds_1", target="tool_1", label="input"),
            ProvenanceEdge(source="tool_1", target="out_1", label="generated")
        ]
    )


def _mock_artifacts(job_id: str = "mock") -> List[Dict[str, Any]]:
    """Generate mock artifacts list for demo/fallback mode."""
    return [
        {
            "id": f"artifact_{i}",
            "name": f"output_{i}.nii.gz",
            "type": "nifti",
            "size": 1024000 * (i + 1),
            "created_at": datetime.now().isoformat()
        }
        for i in range(3)
    ]


# Create routers
chat_router = APIRouter(prefix="/api/chat", tags=["chat"])
evidence_router = APIRouter(prefix="/api/evidence", tags=["evidence"])
dataset_router = APIRouter(prefix="/api/datasets", tags=["datasets"])


# Chat Endpoints
@chat_router.post("/threads")
async def create_thread(title: Optional[str] = "New Chat") -> ChatThread:
    """Create a new chat thread"""
    thread = ChatThread(
        id=f"thread_{datetime.now().timestamp()}",
        title=title,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        message_count=0,
        status="active"
    )
    return thread


@chat_router.get("/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Get messages for a thread"""
    # Mock implementation
    messages = [
        {
            "id": f"msg_{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i}",
            "timestamp": datetime.now().isoformat()
        }
        for i in range(offset, min(offset + limit, 10))
    ]
    
    return {"messages": messages, "total": 10}


@chat_router.post("/threads/{thread_id}/messages")
async def send_message(
    thread_id: str,
    request: ChatRequest,
    background_tasks: BackgroundTasks
) -> Dict[str, str]:
    """Send a message to the chat thread"""
    message_id = f"msg_{datetime.now().timestamp()}"
    
    # Queue processing in background
    background_tasks.add_task(
        process_chat_message,
        thread_id,
        message_id,
        request
    )
    
    return {"message_id": message_id}


@chat_router.get("/threads/{thread_id}/stream")
async def stream_response(thread_id: str, message_id: str):
    """Stream chat response using SSE"""
    async def event_generator():
        # Simulate streaming response
        messages = [
            "Processing your request...",
            "Running analysis...",
            "Generating results...",
            "Analysis complete!"
        ]
        
        for msg in messages:
            await asyncio.sleep(0.5)
            yield {
                "event": "message",
                "data": json.dumps({"content": msg})
            }
        
        yield {
            "event": "done",
            "data": json.dumps({"status": "success"})
        }
    
    return EventSourceResponse(event_generator())


# Evidence Rail Endpoints
@evidence_router.get("/jobs/{job_id}/provenance")
async def get_provenance(job_id: str) -> ProvenanceGraph:
    """
    Get provenance graph for a job.

    The provenance graph shows the data flow through the analysis pipeline:
    - Nodes represent datasets, tools, parameters, and outputs
    - Edges represent data dependencies and transformations

    If the job has an explicit provenance_graph field, that is returned.
    Otherwise, the graph is generated from the job's execution steps.

    Falls back to mock data if:
    - Job not found and ENABLE_MOCK_FALLBACK=true
    - Job found but has no steps or provenance data
    """
    job = await get_job_safe(job_id)

    if job is None:
        if ENABLE_MOCK_FALLBACK:
            logger.debug(f"Job {job_id} not found, returning mock provenance graph")
            return _mock_provenance_graph()
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Check if job has explicit provenance graph
    if hasattr(job, 'provenance_graph') and job.provenance_graph:
        logger.debug(f"Returning explicit provenance graph for job {job_id}")
        return job.provenance_graph

    # Generate provenance graph from job steps
    nodes: List[ProvenanceNode] = []
    edges: List[ProvenanceEdge] = []

    # Add input dataset nodes from job metadata
    datasets = job.metadata.get("datasets", []) if hasattr(job, 'metadata') else []
    for i, ds in enumerate(datasets):
        ds_id = ds.get("id", f"ds_{i}")
        nodes.append(ProvenanceNode(
            id=ds_id,
            type="dataset",
            label=ds.get("name", f"Dataset {i+1}"),
            metadata={"source": ds.get("source"), "n_subjects": ds.get("n_subjects")}
        ))

    # Add nodes from execution steps
    steps = job.steps if hasattr(job, 'steps') else []
    for i, step in enumerate(steps):
        step_id = step.id if hasattr(step, 'id') else f"step_{i}"
        tool_name = step.tool if hasattr(step, 'tool') else step.name if hasattr(step, 'name') else f"Tool {i+1}"
        step_name = step.name if hasattr(step, 'name') else tool_name

        nodes.append(ProvenanceNode(
            id=step_id,
            type="tool",
            label=step_name,
            metadata={"tool": tool_name, "status": step.status.value if hasattr(step, 'status') else "unknown"}
        ))

        # Connect to previous step or input datasets
        if i == 0:
            # First step connects to all input datasets
            for ds in datasets:
                ds_id = ds.get("id", f"ds_{datasets.index(ds)}")
                edges.append(ProvenanceEdge(source=ds_id, target=step_id, label="input"))
        else:
            # Subsequent steps connect to previous step
            prev_step = steps[i-1]
            prev_id = prev_step.id if hasattr(prev_step, 'id') else f"step_{i-1}"
            edges.append(ProvenanceEdge(source=prev_id, target=step_id, label="output"))

    # Add output artifact nodes
    artifacts = job.artifacts if hasattr(job, 'artifacts') else []
    for i, artifact in enumerate(artifacts):
        art_id = artifact.id if hasattr(artifact, 'id') else f"artifact_{i}"
        art_name = artifact.name if hasattr(artifact, 'name') else f"Output {i+1}"
        art_type = artifact.type if hasattr(artifact, 'type') else "output"

        nodes.append(ProvenanceNode(
            id=art_id,
            type="output",
            label=art_name,
            metadata={"artifact_type": art_type}
        ))

        # Connect artifacts to last step
        if steps:
            last_step = steps[-1]
            last_id = last_step.id if hasattr(last_step, 'id') else f"step_{len(steps)-1}"
            edges.append(ProvenanceEdge(source=last_id, target=art_id, label="generated"))

    # If no real data, fall back to mock
    if not nodes and ENABLE_MOCK_FALLBACK:
        logger.debug(f"Job {job_id} has no provenance data, returning mock graph")
        return _mock_provenance_graph()

    return ProvenanceGraph(nodes=nodes, edges=edges)


def generate_comprehensive_run_card(job_id: str) -> Dict[str, Any]:
    """Generate comprehensive run card with full metadata"""
    from brain_researcher.core.contracts.ids import IdsV1
    
    # Get system information
    system_info = {
        "platform": platform.platform(),
        "python_version": sys.version,
        "os_version": platform.release(),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "cpu_cores": psutil.cpu_count(),
        "gpu_info": None  # Would query GPU if available
    }
    
    # Mock execution steps
    execution_steps = [
        {
            "id": "step_1",
            "name": "Load Dataset",
            "tool": "nilearn",
            "args": {"dataset_id": "ds000114", "subjects": ["sub-01", "sub-02"]},
            "status": "completed",
            "start_time": datetime.now().isoformat(),
            "duration_ms": 2500
        },
        {
            "id": "step_2", 
            "name": "Preprocess Data",
            "tool": "fmriprep",
            "args": {"smoothing": 6, "normalization": "mni152"},
            "status": "completed",
            "start_time": datetime.now().isoformat(),
            "duration_ms": 45000
        },
        {
            "id": "step_3",
            "name": "GLM Analysis",
            "tool": "nilearn",
            "args": {"model": "glm", "contrasts": ["motor > rest"]},
            "status": "completed", 
            "start_time": datetime.now().isoformat(),
            "duration_ms": 15000
        }
    ]
    
    # Mock datasets used
    datasets = [
        {
            "id": "ds000114",
            "name": "Finger-foot-lips motor task",
            "source": "OpenNeuro",
            "version": "1.0.1",
            "n_subjects": 10,
            "n_sessions": 1,
            "tasks": ["motor"],
            # Avoid fake hashes in mock fallback mode; real producers should
            # populate checksums from actual data snapshots/manifests.
            "checksum": None,
            "bids_version": "1.6.0"
        }
    ]
    
    # Mock tools and versions
    tools = [
        {
            "name": "nilearn",
            "version": "0.10.0",
            "citation": "Abraham et al. (2014). Machine learning for neuroimaging with scikit-learn",
            "doi": "10.3389/fninf.2014.00014"
        },
        {
            "name": "fmriprep",
            "version": "23.1.4",
            "citation": "Esteban et al. (2019). fMRIPrep: a robust preprocessing pipeline for functional MRI",
            "doi": "10.1038/s41592-018-0235-4"
        },
        {
            "name": "FSL",
            "version": "6.0.5",
            "citation": "Jenkinson et al. (2012). FSL. NeuroImage, 62(2), 782-790",
            "doi": "10.1016/j.neuroimage.2011.09.015"
        }
    ]
    
    # Mock artifacts
    artifacts = [
        {
            "id": f"artifact_{job_id}_1",
            "name": "statistical_map.nii.gz",
            "type": "brain_map",
            "path": f"/data/outputs/job_{job_id}/statistical_map.nii.gz",
            "size_bytes": 2048576,
            # Avoid fake hashes in mock fallback mode.
            "checksum": None,
            "description": "Statistical parametric map for motor > rest contrast",
            "metadata": {"space": "MNI152NLin2009cAsym", "smoothing": 6}
        },
        {
            "id": f"artifact_{job_id}_2", 
            "name": "design_matrix.png",
            "type": "image",
            "path": f"/data/outputs/job_{job_id}/design_matrix.png",
            "size_bytes": 156789,
            # Avoid fake hashes in mock fallback mode.
            "checksum": None,
            "description": "Design matrix visualization"
        }
    ]
    
    # Mock citations
    citations = [
        {
            "id": "cite_1",
            "type": "dataset",
            "title": "A high-resolution 7-Tesla fMRI dataset from complex natural stimulation with an audio movie",
            "authors": ["Hanke, M.", "Baumgartner, F.J.", "Ibe, P."],
            "year": 2014,
            "journal": "Scientific Data",
            "doi": "10.1038/sdata.2014.3"
        }
    ]
    
    # Calculate resource usage (mock)
    resource_usage = {
        "peak_memory_mb": 4096.5,
        "cpu_time_seconds": 62.5,
        "gpu_time_seconds": None,
        "disk_io_mb": 1024.2,
        "network_io_mb": 156.7
    }
    
    total_duration = sum(step["duration_ms"] for step in execution_steps) / 1000

    parameters = {
        "smoothing_fwhm": 6,
        "statistical_threshold": 0.001,
        "cluster_threshold": 10,
        "normalization_template": "MNI152NLin2009cAsym",
        "random_seed": 42,
    }
    container_info = {
        "image": "nipreps/fmriprep:23.1.4",
        # Avoid fake digests in mock fallback mode.
        "digest": None,
    }
    # Derive reproducibility score from explicit evidence presence rather than
    # hard-coding a "nice looking" placeholder number.
    checks = [
        bool(datasets),
        all(ds.get("version") for ds in datasets if isinstance(ds, dict)),
        bool(parameters),
        bool(execution_steps),
        bool(tools),
        all(tool.get("version") for tool in tools if isinstance(tool, dict)),
        bool(citations),
        bool(system_info.get("python_version")),
        bool(artifacts),
        parameters.get("random_seed") is not None,
        bool(container_info.get("image")),
        bool(resource_usage),
        bool(container_info.get("digest")),
    ]
    reproducibility_score = round(sum(1 for ok in checks if ok) / len(checks), 2)
    
    run_card = RunCard(
        ids=IdsV1(
            analysis_id=job_id,
            run_id=job_id,
            job_id=job_id,
        ),
        version="1.0",
        id=f"rc_{job_id}",
        timestamp=datetime.now().isoformat(),
        title="Motor Task GLM Analysis",
        description="First-level GLM analysis of motor task fMRI data with contrast estimation",
        execution={
            "duration_seconds": total_duration,
            "steps": execution_steps,
            "environment": system_info,
            "resource_usage": resource_usage,
        },
        inputs={
            "datasets": datasets,
            "parameters": parameters,
            "attachments": [],
        },
        outputs={
            "artifacts": artifacts,
            "metrics": {
                "max_t_stat": 8.45,
                "n_significant_voxels": 1847,
                "cluster_count": 5,
                "analysis_success": True,
            },
            "plots": [
                {"name": "design_matrix.png", "type": "design_matrix"},
                {"name": "statistical_map.png", "type": "brain_map"},
            ],
        },
        provenance={
            "tools": tools,
            "citations": citations,
            "dependencies": [
                {"name": "numpy", "version": "1.24.3"},
                {"name": "scipy", "version": "1.11.1"},
                {"name": "matplotlib", "version": "3.7.1"},
            ],
        },
        reproducibility={
            "score": reproducibility_score,
            "score_method": "presence_checklist_v1",
            "random_seed": parameters.get("random_seed"),
            "versions": {tool["name"]: tool["version"] for tool in tools},
            "checksums": {
                "dataset": datasets[0].get("checksum"),
                "code": None,
            },
            "container_info": container_info,
            "is_reproducible": reproducibility_score >= 0.8,
        },
        # Legacy compatibility
        parameters={
            "smoothing": 6,
            "threshold": 0.001,
        },
        environment={
            "fsl_version": "6.0.5",
            "nilearn_version": "0.10.0",
        },
        citations=[{"title": "FSL", "doi": "10.1016/j.neuroimage.2011.09.015"}],
        reproducibility_score=reproducibility_score,
    )
    dumped = run_card.model_dump(mode="json", exclude_none=True)
    dumped.setdefault("run_id", job_id)
    return dumped

@evidence_router.get("/jobs/{job_id}/runcard")
async def get_run_card(job_id: str) -> Dict[str, Any]:
    """
    Get comprehensive run card for a job.

    The run card contains complete execution metadata including:
    - Execution timing and steps
    - Input datasets and parameters
    - Output artifacts and metrics
    - Tool provenance and citations
    - Reproducibility information

    Resolution order:
    1. Pre-generated run_card on Job object
    2. Persisted run card from filesystem
    3. Generate via EnhancedJobManager
    4. Mock fallback (if ENABLE_MOCK_FALLBACK=true)
    """
    job = await get_job_safe(job_id)

    if job is None:
        # Try persisted run card before falling back to mock
        persisted = get_persisted_run_card(job_id)
        if persisted:
            logger.debug(f"Loaded persisted run card for job {job_id}")
            return persisted

        if ENABLE_MOCK_FALLBACK:
            logger.debug(f"Job {job_id} not found, returning mock run card")
            return generate_comprehensive_run_card(job_id)
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Try to get pre-generated run card from job
    if hasattr(job, 'run_card') and job.run_card:
        logger.debug(f"Returning pre-generated run card for job {job_id}")
        if hasattr(job.run_card, 'model_dump'):
            return job.run_card.model_dump()
        return job.run_card

    # Try persisted run card from filesystem
    persisted = get_persisted_run_card(job_id)
    if persisted:
        logger.debug(f"Loaded persisted run card for job {job_id}")
        return persisted

    # Try to generate run card via EnhancedJobManager
    EnhancedJobManager = _get_enhanced_job_manager()
    if EnhancedJobManager:
        try:
            run_card = await EnhancedJobManager.generate_run_card(job_id)
            if run_card:
                logger.debug(f"Generated run card for job {job_id} via EnhancedJobManager")
                if hasattr(run_card, 'model_dump'):
                    return run_card.model_dump()
                return run_card
        except Exception as e:
            logger.warning(f"Failed to generate run card for {job_id}: {e}")

    # Fall back to mock run card generation
    if ENABLE_MOCK_FALLBACK:
        logger.debug(f"Falling back to mock run card for job {job_id}")
        return generate_comprehensive_run_card(job_id)

    raise HTTPException(status_code=500, detail=f"Could not generate run card for job {job_id}")


@evidence_router.get("/jobs/{job_id}/artifacts")
async def get_artifacts(job_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get artifacts for a job.

    Returns all output artifacts from the job execution including:
    - NIfTI brain images
    - Statistical maps
    - Visualization plots
    - CSV/JSON data files

    Falls back to mock artifacts if job not found and ENABLE_MOCK_FALLBACK=true.
    """
    job = await get_job_safe(job_id)

    if job is None:
        if ENABLE_MOCK_FALLBACK:
            logger.debug(f"Job {job_id} not found, returning mock artifacts")
            return {"artifacts": _mock_artifacts(job_id)}
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Get real artifacts from job
    artifacts = []
    job_artifacts = job.artifacts if hasattr(job, 'artifacts') else []

    for artifact in job_artifacts:
        artifact_dict = {}

        # Handle both Pydantic models and dicts
        if hasattr(artifact, 'model_dump'):
            artifact_dict = artifact.model_dump()
        elif isinstance(artifact, dict):
            artifact_dict = artifact
        else:
            # Try to extract common fields
            artifact_dict = {
                "id": getattr(artifact, 'id', f"artifact_{job_artifacts.index(artifact)}"),
                "name": getattr(artifact, 'name', 'Unknown'),
                "type": getattr(artifact, 'type', 'unknown'),
                "size": getattr(artifact, 'size', 0),
                "url": getattr(artifact, 'url', ''),
                "checksum": getattr(artifact, 'checksum', None),
                "created_at": getattr(artifact, 'created_at', datetime.now()).isoformat() if hasattr(artifact, 'created_at') else datetime.now().isoformat(),
            }

        artifacts.append(artifact_dict)

    # If no artifacts and fallback enabled, return mock
    if not artifacts and ENABLE_MOCK_FALLBACK:
        logger.debug(f"Job {job_id} has no artifacts, returning mock")
        return {"artifacts": _mock_artifacts(job_id)}

    return {"artifacts": artifacts}


@evidence_router.post("/jobs/{job_id}/artifacts/{artifact_id}/annotate")
async def add_annotation(
    job_id: str,
    artifact_id: str,
    annotation: Dict[str, str]
) -> Dict[str, bool]:
    """Add annotation to an artifact"""
    # Process annotation
    return {"success": True}


def generate_pdf_run_card(run_card_data: Dict[str, Any], job_id: str) -> str:
    """Generate PDF Run Card using reportlab"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
    except ImportError:
        # Fallback if reportlab not available
        raise HTTPException(
            status_code=500, 
            detail="PDF generation not available - reportlab package required"
        )
    
    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    
    # Create PDF document
    doc = SimpleDocTemplate(temp_file.name, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=colors.darkblue
    )
    story.append(Paragraph(f"Run Card: {run_card_data['title']}", title_style))
    story.append(Spacer(1, 20))
    
    # Description
    story.append(Paragraph(f"<b>Description:</b> {run_card_data['description']}", styles['Normal']))
    story.append(Spacer(1, 12))
    
    # Metadata table
    metadata = [
        ["Run ID", run_card_data['id']],
        ["Timestamp", run_card_data['timestamp']],
        ["Duration", f"{run_card_data['execution']['duration_seconds']:.1f}s"],
        ["Reproducibility Score", f"{run_card_data.get('reproducibility_score', 0):.0%}"]
    ]
    
    t = Table(metadata, colWidths=[2*inch, 4*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    
    # Datasets
    story.append(Paragraph("<b>Datasets Used</b>", styles['Heading2']))
    for dataset in run_card_data['inputs']['datasets']:
        story.append(Paragraph(
            f"• {dataset['name']} ({dataset['source']}) - {dataset.get('n_subjects', 'N/A')} subjects",
            styles['Normal']
        ))
    story.append(Spacer(1, 12))
    
    # Tools
    story.append(Paragraph("<b>Analysis Tools</b>", styles['Heading2']))
    for tool in run_card_data['provenance']['tools']:
        story.append(Paragraph(
            f"• {tool['name']} v{tool['version']}",
            styles['Normal']
        ))
    story.append(Spacer(1, 12))
    
    # Parameters
    story.append(Paragraph("<b>Analysis Parameters</b>", styles['Heading2']))
    for key, value in run_card_data['inputs']['parameters'].items():
        story.append(Paragraph(f"• {key}: {value}", styles['Normal']))
    story.append(Spacer(1, 12))
    
    # Outputs
    story.append(Paragraph("<b>Generated Artifacts</b>", styles['Heading2']))
    for artifact in run_card_data['outputs']['artifacts']:
        size_mb = artifact['size_bytes'] / (1024*1024)
        story.append(Paragraph(
            f"• {artifact['name']} ({size_mb:.1f} MB) - {artifact.get('description', 'No description')}",
            styles['Normal']
        ))
    story.append(Spacer(1, 12))
    
    # Citations
    story.append(Paragraph("<b>Citations</b>", styles['Heading2']))
    for citation in run_card_data['provenance']['citations']:
        authors_str = ", ".join(citation['authors']) if citation['authors'] else "Unknown"
        story.append(Paragraph(
            f"• {authors_str} ({citation.get('year', 'N/A')}). {citation['title']}. DOI: {citation.get('doi', 'N/A')}",
            styles['Normal']
        ))
    story.append(Spacer(1, 12))
    
    # Reproducibility info
    story.append(Paragraph("<b>Reproducibility Information</b>", styles['Heading2']))
    repro = run_card_data['reproducibility']
    story.append(Paragraph(f"• Random Seed: {repro.get('random_seed', 'Not set')}", styles['Normal']))
    story.append(Paragraph(f"• Container Image: {repro.get('container_info', {}).get('image', 'Not available')}", styles['Normal']))
    
    # Environment
    env = run_card_data['execution']['environment']
    story.append(Paragraph(f"• Platform: {env.get('platform', 'Unknown')}", styles['Normal']))
    story.append(Paragraph(f"• Memory: {env.get('memory_gb', 'Unknown')} GB", styles['Normal']))
    
    # Build PDF
    doc.build(story)
    temp_file.close()
    
    return temp_file.name

# Configurable run cards directory
RUN_CARDS_DIR = Path(
    os.getenv("RUN_CARDS_DIR") or get_data_root() / "run_cards"
).expanduser()


def store_run_card(job_id: str, run_card_data: Dict[str, Any], format: str) -> str:
    """
    Store Run Card to filesystem.

    Uses configurable directory via RUN_CARDS_DIR environment variable.
    Default: <repo>/data/run_cards/

    Args:
        job_id: The job identifier
        run_card_data: The run card data to store
        format: Output format (json, yaml)

    Returns:
        Path to the stored file
    """
    # Create run cards directory (use configured path)
    run_cards_dir = RUN_CARDS_DIR
    run_cards_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"run_card_{job_id}_{timestamp}.{format}"
    file_path = run_cards_dir / filename

    # Store the file
    if format == "json":
        with open(file_path, 'w') as f:
            json.dump(run_card_data, f, indent=2, default=str)
    elif format == "yaml":
        import yaml
        with open(file_path, 'w') as f:
            yaml.dump(run_card_data, f, default_flow_style=False)

    logger.info(f"Stored run card for job {job_id} at {file_path}")
    return str(file_path)


def get_persisted_run_card(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Try to load a persisted run card from filesystem.

    Supports both the new timestamped pattern (run_card_{job_id}_*.json)
    and the legacy single-file pattern ({job_id}.json). Returns the most
    recently modified match.

    Args:
        job_id: The job identifier

    Returns:
        Run card data dict if found, None otherwise
    """
    run_cards_dir = RUN_CARDS_DIR
    if not run_cards_dir.exists():
        return None

    candidates: List[Path] = []

    # New pattern (preferred): run_card_{job_id}_*.json
    candidates.extend(run_cards_dir.glob(f"run_card_{job_id}_*.json"))

    # Legacy single-file pattern: {job_id}.json
    legacy = run_cards_dir / f"{job_id}.json"
    if legacy.exists():
        candidates.append(legacy)

    if not candidates:
        return None

    # Pick most recently modified file
    most_recent = max(candidates, key=lambda p: p.stat().st_mtime)

    try:
        with open(most_recent, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load persisted run card {most_recent}: {e}")
        return None

@evidence_router.get("/jobs/{job_id}/runcard/export")
async def export_run_card(
    job_id: str,
    format: str = "json",
    includeArtifacts: bool = True,
    includeProvenance: bool = True,
    includeCitations: bool = True,
    includeEnvironment: bool = True,
    generateQR: bool = False
) -> StreamingResponse:
    """Export run card in specified format with options"""
    run_card_data = await get_run_card(job_id)
    
    # Apply export options
    if not includeArtifacts:
        run_card_data["outputs"]["artifacts"] = []
    if not includeProvenance:
        run_card_data["provenance"] = {"tools": [], "citations": [], "dependencies": []}
    if not includeCitations:
        run_card_data["provenance"]["citations"] = []
        run_card_data["citations"] = []
    if not includeEnvironment:
        run_card_data["execution"]["environment"] = {}
    
    try:
        if format == "json":
            content = json.dumps(run_card_data, indent=2, default=str)
            media_type = "application/json"
            filename = f"run_card_{job_id}.json"
            
        elif format == "yaml":
            import yaml
            content = yaml.safe_dump(run_card_data, default_flow_style=False)
            media_type = "text/yaml"
            filename = f"run_card_{job_id}.yaml"
            
        elif format == "pdf":
            pdf_path = generate_pdf_run_card(run_card_data, job_id)

            # Store the run card data as well
            store_run_card(job_id, run_card_data, "json")

            with open(pdf_path, "rb") as handle:
                pdf_bytes = handle.read()

            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=run_card_{job_id}.pdf",
                    "Cache-Control": "no-cache",
                },
            )
            
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
        
        # Store the run card
        stored_path = store_run_card(job_id, run_card_data, format)
        
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Stored-Path": stored_path
        }
        if format == "yaml":
            headers["Content-Type"] = "text/yaml"

        return Response(
            content=content,
            media_type=media_type,
            headers=headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to export run card: {str(e)}"
        )

# Share Models
class ShareFormat(str, Enum):
    JSON = "json"


class ShareRequest(BaseModel):
    jobId: str
    format: ShareFormat = ShareFormat.JSON
    expires_in_hours: int = Field(default=24, ge=1, le=168)  # Max 1 week

class ShareResponse(BaseModel):
    share_id: str
    share_url: str
    expires_at: datetime

@evidence_router.post("/share")
async def create_share_link(request: ShareRequest) -> ShareResponse:
    """Create a shareable link for a Run Card"""
    share_id = f"share_{hashlib.md5(f'{request.jobId}_{datetime.now()}'.encode()).hexdigest()[:8]}"
    
    # Store share metadata (in real implementation, this would go to database)
    share_data = {
        "job_id": request.jobId,
        "format": request.format.value,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(hours=request.expires_in_hours)).isoformat()
    }
    
    # Store to filesystem (mock implementation)
    shares_dir = Path(os.environ.get("BR_SHARES_DIR", "/app/data/shares"))
    shares_dir.mkdir(parents=True, exist_ok=True)
    
    with open(shares_dir / f"{share_id}.json", 'w') as f:
        json.dump(share_data, f, indent=2)
    
    share_url = f"https://brain-researcher.ai/share/{share_id}"
    
    return ShareResponse(
        share_id=share_id,
        share_url=share_url,
        expires_at=datetime.now() + timedelta(hours=request.expires_in_hours)
    )

@evidence_router.get("/share/{share_id}")
async def get_shared_run_card(share_id: str):
    """Get Run Card from share link"""
    shares_dir = Path(os.environ.get("BR_SHARES_DIR", "/app/data/shares"))
    share_file = shares_dir / f"{share_id}.json"
    
    if not share_file.exists():
        raise HTTPException(status_code=404, detail="Share link not found")
    
    with open(share_file, 'r') as f:
        share_data = json.load(f)
    
    # Check if expired
    expires_at = datetime.fromisoformat(share_data['expires_at'])
    if datetime.now() > expires_at:
        raise HTTPException(status_code=410, detail="Share link has expired")
    
    # Get the run card
    job_id = share_data['job_id']
    run_card_data = await get_run_card(job_id)
    
    return {
        "run_card": run_card_data,
        "share_info": {
            "created_at": share_data['created_at'],
            "expires_at": share_data['expires_at']
        }
    }

# Dataset Endpoints
@dataset_router.get("/")
async def search_datasets(
    q: Optional[str] = None,
    sources: Optional[str] = None,
    modalities: Optional[str] = None,
    tasks: Optional[str] = None,
    n_subjects_min: Optional[int] = None,
    n_subjects_max: Optional[int] = None,
    quality_score_min: Optional[float] = None,
    page: int = 1,
    limit: int = 20,
    sort: str = "name",
    order: str = "asc"
) -> DatasetSearchResult:
    """Search datasets with filters"""
    # Mock dataset search
    datasets = [
        Dataset(
            id="ds000114",
            name="Motor Task Dataset",
            source="OpenNeuro",
            modality=["T1w", "bold"],
            n_subjects=10,
            tasks=["motor"],
            quality_score=8.5,
            size_gb=15.2
        ),
        Dataset(
            id="hcp_1200",
            name="Human Connectome Project",
            source="HCP",
            modality=["T1w", "T2w", "bold", "dwi"],
            n_subjects=1200,
            tasks=["motor", "wm", "language"],
            quality_score=9.8,
            size_gb=2400
        )
    ]
    
    # Apply filters
    if sources:
        source_list = sources.split(",")
        datasets = [d for d in datasets if d.source in source_list]
    
    if n_subjects_min:
        datasets = [d for d in datasets if d.n_subjects >= n_subjects_min]
    
    if n_subjects_max:
        datasets = [d for d in datasets if d.n_subjects <= n_subjects_max]
    
    # Calculate facets
    facets = {
        "sources": [
            {"value": "OpenNeuro", "count": 1},
            {"value": "HCP", "count": 1}
        ],
        "modalities": [
            {"value": "bold", "count": 2},
            {"value": "T1w", "count": 2}
        ]
    }
    
    return DatasetSearchResult(
        datasets=datasets,
        total_count=len(datasets),
        page=page,
        page_size=limit,
        facets=facets
    )


@dataset_router.get("/{dataset_id}")
async def get_dataset(dataset_id: str) -> Dataset:
    """Get dataset details"""
    if dataset_id == "ds000114":
        return Dataset(
            id="ds000114",
            name="Motor Task Dataset",
            source="OpenNeuro",
            modality=["T1w", "bold"],
            n_subjects=10,
            n_sessions=2,
            tasks=["motor"],
            quality_score=8.5,
            size_gb=15.2,
            bids_version="1.6.0"
        )
    else:
        raise HTTPException(status_code=404, detail="Dataset not found")


@dataset_router.get("/{dataset_id}/statistics")
async def get_dataset_statistics(dataset_id: str) -> Dict[str, Any]:
    """Get dataset statistics"""
    return {
        "total_subjects": 10,
        "total_sessions": 20,
        "total_size_gb": 15.2,
        "file_types": [
            {"type": "nii.gz", "count": 240},
            {"type": "json", "count": 50}
        ],
        "scan_types": [
            {"type": "T1w", "count": 10},
            {"type": "bold", "count": 200}
        ],
        "average_quality_score": 8.5
    }


@dataset_router.get("/{dataset_id}/preview")
async def get_dataset_preview(dataset_id: str) -> Dict[str, Any]:
    """Get dataset preview"""
    return {
        "sample_subjects": ["sub-01", "sub-02", "sub-03"],
        "sample_files": [
            "sub-01/anat/sub-01_T1w.nii.gz",
            "sub-01/func/sub-01_task-motor_bold.nii.gz"
        ],
        "directory_structure": {
            "sub-01": {
                "anat": ["T1w.nii.gz"],
                "func": ["task-motor_bold.nii.gz"]
            }
        }
    }


@dataset_router.get("/{dataset_id}/related")
async def get_related_datasets(
    dataset_id: str,
    limit: int = 5
) -> Dict[str, List[Dataset]]:
    """Get related datasets"""
    related = [
        Dataset(
            id="ds000115",
            name="Similar Motor Task",
            source="OpenNeuro",
            modality=["T1w", "bold"],
            n_subjects=15,
            tasks=["motor"],
            quality_score=8.0
        )
    ]
    
    return {"datasets": related[:limit]}


@dataset_router.get("/{dataset_id}/quality")
async def check_dataset_quality(dataset_id: str) -> Dict[str, Any]:
    """Check dataset quality"""
    return {
        "bids_validation": {
            "valid": True,
            "warnings": 2,
            "errors": 0
        },
        "completeness": {
            "missing_files": [],
            "missing_metadata": ["participants.json"]
        },
        "consistency": {
            "naming_convention": "consistent",
            "file_format": "valid"
        },
        "score": 8.5
    }


@dataset_router.get("/{dataset_id}/citations")
async def get_dataset_citations(dataset_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Get dataset citations"""
    citations = [
        {
            "id": "cite_1",
            "title": "Motor Task Dataset",
            "authors": ["Smith, J.", "Doe, A."],
            "year": 2021,
            "doi": "10.18112/openneuro.ds000114.v1.0.1",
            "type": "dataset"
        }
    ]
    
    return {"citations": citations}


@dataset_router.get("/{dataset_id}/download")
async def download_dataset(
    dataset_id: str,
    format: str = "bids"
) -> StreamingResponse:
    """Download dataset"""
    # Mock download - in reality would stream from storage
    content = f"Dataset {dataset_id} in {format} format"
    
    return StreamingResponse(
        iter([content.encode()]),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=dataset_{dataset_id}.tar.gz"
        }
    )


# Helper functions
async def process_chat_message(
    thread_id: str,
    message_id: str,
    request: ChatRequest
):
    """Process chat message in background"""
    # Simulate processing
    await asyncio.sleep(1)
    # Would integrate with LangGraph agent here
    pass


# Export routers
__all__ = ['chat_router', 'evidence_router', 'dataset_router']
