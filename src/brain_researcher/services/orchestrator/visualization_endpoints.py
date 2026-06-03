"""
Visualization endpoints for Knowledge Graph, Pipeline, and Result Gallery
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio
import json
import logging
from enum import Enum

from .job_adapter import JobAdapter
from .job_state import jobs_db as core_jobs_db
from .pipeline_graph import build_job_graph_snapshot


# Knowledge Graph Models
class NodeType(str, Enum):
    PAPER = "paper"
    DATASET = "dataset"
    TOOL = "tool"
    CONCEPT = "concept"
    RESEARCHER = "researcher"

class EdgeType(str, Enum):
    CITES = "cites"
    USES = "uses"
    PRODUCES = "produces"
    RELATED_TO = "related_to"

class GraphNode(BaseModel):
    id: str
    label: str
    type: NodeType
    properties: Optional[Dict[str, Any]] = None
    x: Optional[float] = None
    y: Optional[float] = None

class GraphEdge(BaseModel):
    source: str
    target: str
    type: EdgeType
    weight: Optional[float] = 1.0

class KnowledgeGraphData(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    stats: Optional[Dict[str, Any]] = None


# Pipeline Visualization Models
class StepType(str, Enum):
    INPUT = "input"
    PROCESS = "process"
    ANALYSIS = "analysis"
    OUTPUT = "output"

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class PipelineStep(BaseModel):
    id: str
    name: str
    type: StepType
    status: StepStatus
    progress: Optional[float] = 0
    duration: Optional[int] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    parameters: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

class PipelineConnection(BaseModel):
    from_step: str = Field(..., alias="from")
    to_step: str = Field(..., alias="to")
    label: Optional[str] = None
    data_type: Optional[str] = None

class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class PipelineData(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    steps: List[PipelineStep]
    connections: List[PipelineConnection]
    status: PipelineStatus
    progress: float
    total_duration: Optional[int] = None


# Result Gallery Models
class ResultType(str, Enum):
    IMAGE = "image"
    PLOT = "plot"
    TABLE = "table"
    DOCUMENT = "document"
    MODEL = "model"

class ResultMetadata(BaseModel):
    created_at: datetime
    created_by: Optional[str] = None
    tags: Optional[List[str]] = None
    size: Optional[int] = None
    dimensions: Optional[Dict[str, int]] = None
    format: Optional[str] = None
    pipeline: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None

class ResultItem(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    type: ResultType
    thumbnail: Optional[str] = None
    full_size_url: Optional[str] = None
    metadata: ResultMetadata
    download_url: Optional[str] = None
    share_url: Optional[str] = None

class GalleryFilter(BaseModel):
    types: Optional[List[ResultType]] = None
    tags: Optional[List[str]] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    created_by: Optional[str] = None


# Create routers
kg_router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])
pipeline_router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
gallery_router = APIRouter(prefix="/api/gallery", tags=["gallery"])

logger = logging.getLogger(__name__)


def _get_job_store() -> Optional[Any]:
    """Fetch the orchestrator job store regardless of mounting context."""
    try:
        from brain_researcher.services.orchestrator.main_enhanced import app as orchestrator_app

        return getattr(orchestrator_app.state, "job_store", None)
    except Exception:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None
    return None


def _serialize_datetime(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        return value
    return None


async def _resolve_job_by_id(job_id: str) -> Optional[Any]:
    job_store = _get_job_store()
    if job_store:
        try:
            record = await job_store.get(job_id)
            if record:
                return JobAdapter.from_record(record)
        except Exception as exc:
            logger.debug("JobStore.get failed for %s: %s", job_id, exc)

    job = core_jobs_db.get(job_id)
    if job:
        return job
    return None


def _extract_pipeline_id_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    params = payload.get("parameters") or {}
    metadata = payload.get("metadata") or {}
    builder = metadata.get("builder_pipeline") or payload.get("builder_pipeline") or {}
    return (
        payload.get("pipeline_id")
        or params.get("pipeline_id")
        or metadata.get("pipeline_id")
        or builder.get("pipeline_id")
    )


async def _resolve_latest_job_for_pipeline(pipeline_id: str) -> Optional[Any]:
    job_store = _get_job_store()
    if job_store:
        try:
            all_jobs = await job_store.list_all()
            matches = []
            for record in all_jobs:
                try:
                    payload = json.loads(record.payload_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                pipeline_from_payload = _extract_pipeline_id_from_payload(payload)
                if pipeline_from_payload == pipeline_id:
                    matches.append(record)

            if matches:
                matches.sort(key=lambda r: r.created_at or 0, reverse=True)
                record = matches[0]
                return JobAdapter.from_record(record)
        except Exception as exc:
            logger.debug("Failed to resolve latest pipeline job: %s", exc)

    matches = []
    for job in core_jobs_db.values():
        metadata = getattr(job, "metadata", {}) or {}
        pipeline_from_job = _extract_pipeline_id_from_payload(metadata)
        if pipeline_from_job == pipeline_id:
            matches.append(job)

    if matches:
        def _sort_key(job: Any):
            created_at = getattr(job, "created_at", None)
            if created_at:
                return created_at
            timing = getattr(job, "timing", None)
            return getattr(timing, "start_time", None) or datetime.min

        matches.sort(key=_sort_key, reverse=True)
        return matches[0]

    return None


def _pipeline_status_from_nodes(nodes: Dict[str, Dict[str, Any]]) -> str:
    statuses = [str(node.get("status", "pending")).lower() for node in nodes.values()]
    if not statuses:
        return "idle"
    if any(status == "running" for status in statuses):
        return "running"
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "paused" for status in statuses):
        return "paused"
    if all(status == "completed" for status in statuses):
        return "completed"
    return "idle"


def _pipeline_progress_from_nodes(nodes: Dict[str, Dict[str, Any]]) -> float:
    if not nodes:
        return 0.0
    completed = sum(1 for node in nodes.values() if str(node.get("status", "")).lower() == "completed")
    return round((completed / len(nodes)) * 100, 2)


def _snapshot_to_pipeline_payload(snapshot: Dict[str, Any], pipeline_id: str, name: Optional[str] = None) -> Dict[str, Any]:
    nodes: Dict[str, Dict[str, Any]] = {}
    for node in snapshot.get("nodes", []) or []:
        node_id = node.get("id")
        if not node_id:
            continue
        timing = node.get("timing") or {}
        resources = node.get("resources") or {}
        meta = node.get("meta") or {}

        mapped_resources = None
        if resources:
            mapped_resources = {
                "cpu": resources.get("cpu_pct") or resources.get("cpu") or resources.get("cpu_usage"),
                "memory": resources.get("memory_gb") or resources.get("memory") or resources.get("memory_usage"),
                "gpu": resources.get("gpu_pct") or resources.get("gpu") or resources.get("gpu_usage"),
            }

        nodes[node_id] = {
            "label": node.get("label") or node_id,
            "type": node.get("type") or "process",
            "status": node.get("status") or "pending",
            "progress": node.get("progress"),
            "resources": mapped_resources,
            "error": (node.get("error") or {}).get("message"),
            "metadata": {"tool": meta.get("tool")} if meta.get("tool") else None,
        }

    edges = [
        {
            "id": edge.get("id") or f"{edge.get('source')}->{edge.get('target')}",
            "source": edge.get("source"),
            "target": edge.get("target"),
            "type": edge.get("type") or "smoothstep",
        }
        for edge in snapshot.get("edges", []) or []
        if edge.get("source") and edge.get("target")
    ]

    status = _pipeline_status_from_nodes(nodes)
    progress = _pipeline_progress_from_nodes(nodes)
    pipeline_name = name or snapshot.get("plan", {}).get("plan_id") or pipeline_id

    return {
        "id": snapshot.get("job_id") or pipeline_id,
        "name": pipeline_name,
        "status": status,
        "progress": progress,
        "nodes": nodes,
        "edges": edges,
        "timeline": [],
    }


def _snapshot_to_pipeline_data(snapshot: Dict[str, Any], pipeline_id: str, name: Optional[str] = None) -> PipelineData:
    steps: List[PipelineStep] = []
    for node in snapshot.get("nodes", []) or []:
        timing = node.get("timing") or {}
        status_value = str(node.get("status") or "pending").lower()
        if status_value == "running":
            status_enum = StepStatus.RUNNING
        elif status_value == "completed":
            status_enum = StepStatus.COMPLETED
        elif status_value == "failed":
            status_enum = StepStatus.FAILED
        elif status_value == "skipped":
            status_enum = StepStatus.SKIPPED
        else:
            status_enum = StepStatus.PENDING

        type_value = str(node.get("type") or "process").lower()
        if type_value == "input":
            type_enum = StepType.INPUT
        elif type_value == "analysis":
            type_enum = StepType.ANALYSIS
        elif type_value == "output":
            type_enum = StepType.OUTPUT
        else:
            type_enum = StepType.PROCESS

        steps.append(
            PipelineStep(
                id=node.get("id"),
                name=node.get("label") or node.get("id"),
                type=type_enum,
                status=status_enum,
                progress=node.get("progress") or 0,
                duration=timing.get("duration_ms"),
                inputs=None,
                outputs=None,
                parameters=node.get("meta") or None,
                error=(node.get("error") or {}).get("message"),
                start_time=_parse_datetime(timing.get("started_at")),
                end_time=_parse_datetime(timing.get("ended_at")),
            )
        )

    connections = [
        PipelineConnection(from_step=edge.get("source"), to_step=edge.get("target"), label=edge.get("label"))
        for edge in snapshot.get("edges", []) or []
        if edge.get("source") and edge.get("target")
    ]

    status_value = _pipeline_status_from_nodes({step.id: {"status": step.status.value} for step in steps})
    progress = _pipeline_progress_from_nodes({step.id: {"status": step.status.value} for step in steps})

    if status_value == "running":
        status_enum = PipelineStatus.RUNNING
    elif status_value == "completed":
        status_enum = PipelineStatus.COMPLETED
    elif status_value == "failed":
        status_enum = PipelineStatus.FAILED
    else:
        status_enum = PipelineStatus.IDLE

    return PipelineData(
        id=snapshot.get("job_id") or pipeline_id,
        name=name or snapshot.get("plan", {}).get("plan_id") or pipeline_id,
        description=None,
        steps=steps,
        connections=connections,
        status=status_enum,
        progress=progress,
        total_duration=None,
    )


# Knowledge Graph Endpoints
@kg_router.get("/")
async def get_knowledge_graph(
    query: Optional[str] = None,
    node_types: Optional[List[NodeType]] = Query(None),
    limit: int = 100
) -> KnowledgeGraphData:
    """Get knowledge graph data"""

    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []

    # Apply filters
    if node_types:
        nodes = [n for n in nodes if n.type in node_types]

    if query:
        nodes = [n for n in nodes if query.lower() in n.label.lower()]

    # Limit results
    nodes = nodes[:limit]

    # Calculate stats
    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "node_types": {},
        "edge_types": {}
    }

    for node in nodes:
        stats["node_types"][node.type] = stats["node_types"].get(node.type, 0) + 1

    for edge in edges:
        stats["edge_types"][edge.type] = stats["edge_types"].get(edge.type, 0) + 1

    return KnowledgeGraphData(nodes=nodes, edges=edges, stats=stats)


@kg_router.get("/node/{node_id}")
async def get_node_details(node_id: str) -> GraphNode:
    """Get detailed information about a specific node"""
    raise HTTPException(status_code=404, detail="Node not found")


@kg_router.get("/neighbors/{node_id}")
async def get_node_neighbors(
    node_id: str,
    depth: int = 1,
    edge_types: Optional[List[EdgeType]] = Query(None)
) -> KnowledgeGraphData:
    """Get neighbors of a specific node"""

    return KnowledgeGraphData(nodes=[], edges=[])


# Pipeline Visualization Endpoints
@pipeline_router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> PipelineData:
    """Get pipeline visualization data"""

    job = await _resolve_job_by_id(pipeline_id)
    if not job:
        job = await _resolve_latest_job_for_pipeline(pipeline_id)
    if not job:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    snapshot = build_job_graph_snapshot(job, job_id=getattr(job, "id", pipeline_id))
    return _snapshot_to_pipeline_data(snapshot, pipeline_id)


@pipeline_router.post("/{pipeline_id}/control")
async def control_pipeline(
    pipeline_id: str,
    action: str,
    step_id: Optional[str] = None
) -> Dict[str, Any]:
    """Control pipeline execution (pause, resume, cancel, retry)"""

    valid_actions = ["pause", "resume", "cancel", "retry"]
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")
    raise HTTPException(status_code=501, detail="Pipeline control not implemented")


@pipeline_router.get("/{pipeline_id}/status")
async def get_pipeline_status(pipeline_id: str, request: Request) -> Dict[str, Any]:
    """Get real-time pipeline status"""

    latest_execution: Optional[Dict[str, Any]] = None
    latest_job_id: Optional[str] = None
    resolved_job: Optional[Any] = None

    resolved_job = await _resolve_job_by_id(pipeline_id)
    if resolved_job:
        latest_job_id = getattr(resolved_job, "id", pipeline_id)
    else:
        resolved_job = await _resolve_latest_job_for_pipeline(pipeline_id)
        if resolved_job:
            latest_job_id = getattr(resolved_job, "id", None)

    if resolved_job:
        timing = getattr(resolved_job, "timing", None)
        created_at = _serialize_datetime(getattr(resolved_job, "created_at", None) or getattr(timing, "start_time", None))
        started_at = _serialize_datetime(getattr(resolved_job, "started_at", None) or getattr(timing, "start_time", None))
        finished_at = _serialize_datetime(getattr(resolved_job, "completed_at", None) or getattr(timing, "end_time", None))
        latest_execution = {
            "job_id": latest_job_id,
            "state": getattr(resolved_job, "status", None),
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
        }

    snapshot = build_job_graph_snapshot(resolved_job, job_id=latest_job_id or pipeline_id)
    pipeline_payload = _snapshot_to_pipeline_payload(snapshot, pipeline_id)

    response: Dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "status": pipeline_payload.get("status", "idle"),
        "progress": pipeline_payload.get("progress", 0),
        "pipeline": pipeline_payload,
    }

    if latest_job_id:
        response["job_id"] = latest_job_id
    if latest_execution:
        response["execution"] = latest_execution

    return response


# Result Gallery Endpoints
@gallery_router.get("/")
async def get_gallery_items(
    page: int = 1,
    page_size: int = 12,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    type_filter: Optional[List[ResultType]] = Query(None),
    tag_filter: Optional[List[str]] = Query(None),
    search: Optional[str] = None
) -> Dict[str, Any]:
    """Get gallery items with filtering and pagination"""

    # Mock gallery items
    items = [
        ResultItem(
            id="result_1",
            title="Statistical Map",
            description="Group-level activation map",
            type=ResultType.IMAGE,
            thumbnail="/thumbnails/stat_map.png",
            full_size_url="/images/stat_map_full.png",
            metadata=ResultMetadata(
                created_at=datetime.now(),
                created_by="user123",
                tags=["fmri", "glm", "motor"],
                size=2048000,
                dimensions={"width": 1920, "height": 1080},
                format="png"
            ),
            download_url="/download/stat_map.png",
            share_url="/share/result_1"
        ),
        ResultItem(
            id="result_2",
            title="Time Series Plot",
            description="BOLD signal time series",
            type=ResultType.PLOT,
            thumbnail="/thumbnails/timeseries.png",
            metadata=ResultMetadata(
                created_at=datetime.now(),
                tags=["timeseries", "bold"],
                size=512000
            )
        ),
        ResultItem(
            id="result_3",
            title="Results Table",
            type=ResultType.TABLE,
            metadata=ResultMetadata(
                created_at=datetime.now(),
                tags=["statistics"],
                size=102400
            )
        )
    ]

    # Apply filters
    if type_filter:
        items = [i for i in items if i.type in type_filter]

    if tag_filter:
        items = [i for i in items if any(tag in i.metadata.tags for tag in tag_filter)]

    if search:
        items = [i for i in items if search.lower() in i.title.lower() or
                 (i.description and search.lower() in i.description.lower())]

    # Calculate pagination
    total_items = len(items)
    total_pages = (total_items + page_size - 1) // page_size
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    return {
        "items": items[start_idx:end_idx],
        "total_items": total_items,
        "total_pages": total_pages,
        "current_page": page,
        "page_size": page_size
    }


@gallery_router.get("/{item_id}")
async def get_gallery_item(item_id: str) -> ResultItem:
    """Get detailed information about a gallery item"""

    if item_id == "result_1":
        return ResultItem(
            id="result_1",
            title="Statistical Map",
            description="Group-level activation map showing motor cortex activation",
            type=ResultType.IMAGE,
            thumbnail="/thumbnails/stat_map.png",
            full_size_url="/images/stat_map_full.png",
            metadata=ResultMetadata(
                created_at=datetime.now(),
                created_by="user123",
                tags=["fmri", "glm", "motor", "group-analysis"],
                size=2048000,
                dimensions={"width": 1920, "height": 1080},
                format="png",
                pipeline="pipeline_123",
                parameters={
                    "threshold": 0.001,
                    "correction": "FWE",
                    "smoothing": 6
                }
            ),
            download_url="/download/stat_map.png",
            share_url="/share/result_1"
        )

    raise HTTPException(status_code=404, detail="Gallery item not found")


@gallery_router.post("/{item_id}/share")
async def share_gallery_item(item_id: str) -> Dict[str, str]:
    """Generate a share link for a gallery item"""

    share_id = f"share_{item_id}_{datetime.now().timestamp()}"
    share_url = f"/shared/{share_id}"

    return {
        "item_id": item_id,
        "share_id": share_id,
        "share_url": share_url,
        "expires_at": (datetime.now().timestamp() + 86400 * 7)  # 7 days
    }


@gallery_router.delete("/{item_id}")
async def delete_gallery_item(item_id: str) -> Dict[str, str]:
    """Delete a gallery item"""

    return {
        "item_id": item_id,
        "status": "deleted",
        "message": "Gallery item deleted successfully"
    }


# Export routers
__all__ = ['kg_router', 'pipeline_router', 'gallery_router']
