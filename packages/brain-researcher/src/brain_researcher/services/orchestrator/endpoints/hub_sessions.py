"""FastAPI endpoints for hosted Marimo hub sessions."""

from __future__ import annotations

import logging
import random
import string
from functools import lru_cache
from typing import Any
from uuid import uuid4

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from brain_researcher.config.paths import get_config_root
from brain_researcher.services.orchestrator.taskbeacon_handoff import (
    default_taskbeacon_target_path,
    normalize_taskbeacon_ref,
    normalize_taskbeacon_repo,
)

from ..studio_session_runtime import (
    CreateStudioSessionRequest,
    HubWorkspaceHandoffRequest,
    StudioRuntimeKind,
    StudioRuntimeProfile,
    StudioRuntimeSession,
    StudioSession,
    StudioSessionActionRequest,
    StudioSessionRuntime,
)

router = APIRouter(prefix="/api/hub/sessions", tags=["hub-sessions"])
logger = logging.getLogger(__name__)


class CreateHubSessionRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    runtime_profile_id: StudioRuntimeProfile = StudioRuntimeProfile.STANDARD
    attach_if_exists: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    target_path: str | None = Field(default=None, max_length=2000)
    notebook_path: str | None = Field(default=None, max_length=2000)
    open_artifact_id: str | None = Field(default=None, max_length=200)
    initial_focus: str | None = Field(default=None, max_length=100)
    materialize_notebook_if_needed: bool = False
    open_clean_workspace: bool = False
    taskbeacon_repo: str | None = Field(default=None, max_length=500)
    taskbeacon_ref: str | None = Field(default=None, max_length=200)


class HubSessionEnvelope(BaseModel):
    session: dict[str, Any]
    runtime: dict[str, Any]
    handoff: dict[str, Any]


class HubSessionActionEnvelope(BaseModel):
    action: str
    session: dict[str, Any]
    runtime: dict[str, Any] | None = None


class HubWorkspaceHandoffEnvelope(BaseModel):
    handoff: dict[str, Any]


class HubResourceItem(BaseModel):
    uri: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None
    type: str = Field(..., pattern="^(tool|dataset|workflow|kg)$")
    data: dict[str, Any] = Field(default_factory=dict)
    details: str | None = None


class HubSessionResourcesEnvelope(BaseModel):
    resources: list[HubResourceItem]


_BROWSER_SCRUBBED_RUNTIME_METADATA_KEYS: frozenset[str] = frozenset(
    {"marimo_runtime_token"}
)


def _runtime_from_request(request: Request) -> StudioSessionRuntime:
    runtime = getattr(request.app.state, "studio_session_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="Hub session runtime is not available"
        )
    return runtime


def _runtime_envelope_for_browser(runtime: StudioRuntimeSession) -> dict[str, Any]:
    """Serialize a runtime session for browser response, stripping secrets."""
    payload = runtime.model_dump(mode="json")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        scrubbed = {
            key: value
            for key, value in metadata.items()
            if key not in _BROWSER_SCRUBBED_RUNTIME_METADATA_KEYS
        }
        payload["metadata"] = scrubbed
    return payload


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


async def _get_hub_runtime_or_404(
    runtime: StudioSessionRuntime,
    session: StudioSession,
) -> StudioRuntimeSession:
    bound = await runtime.get_runtime_session(session.runtime_session_id)
    if bound is None or bound.kind != StudioRuntimeKind.MARIMO:
        raise HTTPException(status_code=404, detail="Hub session not found")
    return bound


def _handoff_request_from_create(
    payload: CreateHubSessionRequest,
    *,
    target_path: str | None = None,
) -> HubWorkspaceHandoffRequest:
    return HubWorkspaceHandoffRequest(
        target_path=target_path if target_path is not None else payload.target_path,
        notebook_path=payload.notebook_path,
        open_artifact_id=payload.open_artifact_id,
        initial_focus=payload.initial_focus,
        materialize_notebook_if_needed=payload.materialize_notebook_if_needed,
        open_clean_workspace=payload.open_clean_workspace,
    )


def _normalize_taskbeacon_seed(
    project_id: str,
    repo: str | None,
    ref: str | None,
    target_path: str | None,
) -> tuple[str | None, str | None, str | None]:
    normalized_repo = normalize_taskbeacon_repo(repo)
    normalized_ref = normalize_taskbeacon_ref(ref)
    resolved_target_path = target_path
    if normalized_repo and not resolved_target_path:
        resolved_target_path = default_taskbeacon_target_path(
            project_id, normalized_repo
        )
    return normalized_repo, normalized_ref, resolved_target_path


def _trim_resource_text(value: Any, *, limit: int = 220) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _resource_details(*parts: str | None) -> str | None:
    normalized = [
        part.strip() for part in parts if isinstance(part, str) and part.strip()
    ]
    if not normalized:
        return None
    return "\n".join(normalized)


def _build_tool_resource_items() -> list[HubResourceItem]:
    from brain_researcher.services.tools.catalog_loader import load_tool_specs

    items: list[HubResourceItem] = []
    try:
        specs = load_tool_specs(
            exposed_only=True,
            include_workflows=False,
            agent_visible_only=False,
        )
    except Exception as exc:
        logger.warning("Failed to load tool resource manifest: %s", exc)
        return items

    for spec in specs:
        description = _trim_resource_text(spec.description)
        metadata = ", ".join(
            part
            for part in (
                f"backend={spec.backend}" if spec.backend else "",
                f"kind={spec.kind}" if spec.kind else "",
                f"category={spec.category}" if spec.category else "",
                f"cost={spec.cost_hint}" if spec.cost_hint else "",
            )
            if part
        )
        modality_text = ", ".join(spec.modalities[:4]) or None
        details = _resource_details(
            description,
            metadata,
            f"modalities={modality_text}" if modality_text else None,
        )
        items.append(
            HubResourceItem(
                uri=f"tool://{spec.name}",
                name=spec.name,
                description=description,
                type="tool",
                data={
                    "tool_id": spec.name,
                    "backend": spec.backend,
                    "kind": spec.kind,
                    "category": spec.category,
                    "cost_hint": spec.cost_hint,
                    "modalities": list(spec.modalities or []),
                    "intents": list(spec.intents or []),
                    "requires_runtime": spec.requires_runtime,
                },
                details=details,
            )
        )
    return sorted(items, key=lambda item: item.name.lower())


def _load_workflow_catalog_rows() -> list[dict[str, Any]]:
    workflow_path = get_config_root() / "workflows" / "workflow_catalog.yaml"
    if not workflow_path.exists():
        return []
    try:
        payload = yaml.safe_load(workflow_path.read_text()) or {}
    except Exception as exc:
        logger.warning("Failed to load workflow resource manifest: %s", exc)
        return []

    workflow_defs = payload.get("workflows") if isinstance(payload, dict) else None
    if not isinstance(workflow_defs, list):
        return []
    return [row for row in workflow_defs if isinstance(row, dict)]


def _build_workflow_resource_items() -> list[HubResourceItem]:
    items: list[HubResourceItem] = []
    for row in _load_workflow_catalog_rows():
        workflow_id = str(row.get("id") or "").strip()
        if not workflow_id:
            continue
        description = _trim_resource_text(row.get("description"))
        metadata = ", ".join(
            part
            for part in (
                f"stage={row.get('stage')}" if row.get("stage") else "",
                f"origin={row.get('origin')}" if row.get("origin") else "",
                f"cost={row.get('cost_tier')}" if row.get("cost_tier") else "",
                f"lifecycle={row.get('lifecycle')}" if row.get("lifecycle") else "",
            )
            if part
        )
        modality_text = ", ".join(
            str(item) for item in (row.get("modalities") or [])[:4]
        )
        details = _resource_details(
            description,
            metadata,
            f"modalities={modality_text}" if modality_text else None,
        )
        items.append(
            HubResourceItem(
                uri=f"workflow://{workflow_id}",
                name=workflow_id,
                description=description,
                type="workflow",
                data={
                    "workflow_id": workflow_id,
                    "stage": row.get("stage"),
                    "origin": row.get("origin"),
                    "cost_tier": row.get("cost_tier"),
                    "lifecycle": row.get("lifecycle"),
                    "modalities": list(row.get("modalities") or []),
                    "tested_release": row.get("tested_release"),
                },
                details=details,
            )
        )
    return sorted(items, key=lambda item: item.name.lower())


def _build_dataset_resource_items() -> list[HubResourceItem]:
    from brain_researcher.core.datasets.catalog import load_catalog

    items: list[HubResourceItem] = []
    try:
        rows = load_catalog()
    except Exception as exc:
        logger.warning("Failed to load dataset resource manifest: %s", exc)
        return items

    for record in rows:
        description = _trim_resource_text(record.description)
        metadata = ", ".join(
            part
            for part in (
                f"repo={record.source_repo}" if record.source_repo else "",
                f"subjects={record.subjects_count}" if record.subjects_count else "",
                "derivatives=yes" if record.has_derivatives else "",
            )
            if part
        )
        modality_text = ", ".join(
            str(item) for item in list(record.modalities or [])[:4]
        )
        task_text = ", ".join(str(item) for item in list(record.tasks or [])[:4])
        details = _resource_details(
            description,
            metadata,
            f"modalities={modality_text}" if modality_text else None,
            f"tasks={task_text}" if task_text else None,
        )
        items.append(
            HubResourceItem(
                uri=f"dataset://{record.dataset_id}",
                name=record.name,
                description=description,
                type="dataset",
                data={
                    "dataset_id": record.dataset_id,
                    "short_name": record.short_name,
                    "source_repo": record.source_repo,
                    "source_repo_id": record.source_repo_id,
                    "subjects_count": record.subjects_count,
                    "modalities": list(record.modalities or []),
                    "tasks": list(record.tasks or []),
                    "species": list(record.species or []),
                    "has_derivatives": record.has_derivatives,
                    "primary_url": str(record.primary_url),
                },
                details=details,
            )
        )
    return sorted(items, key=lambda item: item.name.lower())


_KG_RESOURCE_SEED_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    ("Task:n-back", "n-back", "Task", "Working memory task"),
    ("Task:stroop", "Stroop", "Task", "Conflict monitoring task"),
    ("Task:go-no-go", "go/no-go", "Task", "Response inhibition task"),
    ("Task:resting-state", "resting state", "Task", "Task-free fMRI condition"),
    (
        "Concept:working-memory",
        "working memory",
        "Concept",
        "Executive function concept",
    ),
    ("Concept:attention", "attention", "Concept", "Attention and salience concept"),
    ("Concept:emotion", "emotion", "Concept", "Affective processing concept"),
    ("Concept:language", "language", "Concept", "Language processing concept"),
    ("Concept:reward", "reward", "Concept", "Reward valuation concept"),
    (
        "Concept:default-mode-network",
        "default mode network",
        "Concept",
        "Resting-state network concept",
    ),
    (
        "BrainRegion:hippocampus",
        "hippocampus",
        "BrainRegion",
        "Medial temporal lobe region",
    ),
    ("BrainRegion:amygdala", "amygdala", "BrainRegion", "Limbic brain region"),
    (
        "BrainRegion:prefrontal-cortex",
        "prefrontal cortex",
        "BrainRegion",
        "Frontal association cortex",
    ),
    (
        "BrainRegion:visual-cortex",
        "visual cortex",
        "BrainRegion",
        "Occipital visual region",
    ),
    ("BrainRegion:motor-cortex", "motor cortex", "BrainRegion", "Primary motor region"),
    ("Disorder:depression", "depression", "Disorder", "Mood disorder"),
    ("Disorder:schizophrenia", "schizophrenia", "Disorder", "Psychotic disorder"),
    ("Disorder:autism", "autism", "Disorder", "Neurodevelopmental disorder"),
    ("Modality:fMRI", "fMRI", "Modality", "Functional MRI modality"),
)


def _build_kg_resource_items() -> list[HubResourceItem]:
    items: list[HubResourceItem] = []

    for kg_id, label, node_type, description in _KG_RESOURCE_SEED_ITEMS:
        items.append(
            HubResourceItem(
                uri=f"kg://{kg_id}",
                name=label,
                description=_trim_resource_text(description, limit=120),
                type="kg",
                data={
                    "kg_id": kg_id,
                    "label": label,
                    "node_type": node_type,
                },
                details=_resource_details(
                    f"type={node_type}" if node_type else None,
                    f"kg_id={kg_id}",
                ),
            )
        )

    return sorted(items, key=lambda item: item.name.lower())


@lru_cache(maxsize=1)
def _hub_session_resource_manifest() -> tuple[HubResourceItem, ...]:
    resources = [
        *_build_tool_resource_items(),
        *_build_workflow_resource_items(),
        *_build_dataset_resource_items(),
        *_build_kg_resource_items(),
    ]
    return tuple(resources)


@router.post("")
async def create_or_attach_hub_session(
    request: Request,
    payload: CreateHubSessionRequest,
) -> HubSessionEnvelope:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        taskbeacon_repo, taskbeacon_ref, target_path = _normalize_taskbeacon_seed(
            payload.project_id,
            payload.taskbeacon_repo,
            payload.taskbeacon_ref,
            payload.target_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session_metadata = {**payload.metadata, "surface_origin": "hub"}
    if taskbeacon_repo is not None:
        session_metadata.update(
            {
                "taskbeacon_repo": taskbeacon_repo,
                "taskbeacon_target_path": target_path,
            }
        )
        if taskbeacon_ref is not None:
            session_metadata["taskbeacon_ref"] = taskbeacon_ref
    session = await runtime.create_or_attach_session(
        user.id,
        CreateStudioSessionRequest(
            project_id=payload.project_id,
            display_name=payload.display_name,
            runtime_profile_id=payload.runtime_profile_id,
            runtime_kind=StudioRuntimeKind.MARIMO,
            attach_if_exists=(
                False if taskbeacon_repo is not None else payload.attach_if_exists
            ),
            metadata=session_metadata,
        ),
    )
    handoff = await runtime.build_hub_handoff(
        user.id,
        session.id,
        _handoff_request_from_create(payload, target_path=target_path),
    )
    refreshed_session = await runtime.get_session(session.id)
    if refreshed_session is None:
        raise HTTPException(status_code=404, detail="Hub session not found")
    bound = await _get_hub_runtime_or_404(runtime, refreshed_session)
    return HubSessionEnvelope(
        session=refreshed_session.model_dump(mode="json"),
        runtime=_runtime_envelope_for_browser(bound),
        handoff=handoff.model_dump(mode="json"),
    )


@router.get("/{session_id}")
async def get_hub_session(request: Request, session_id: str) -> HubSessionEnvelope:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Hub session not found")
    handoff = await runtime.build_hub_handoff(
        user.id, session.id, HubWorkspaceHandoffRequest()
    )
    refreshed_session = await runtime.get_session(session.id)
    if refreshed_session is None:
        raise HTTPException(status_code=404, detail="Hub session not found")
    bound = await _get_hub_runtime_or_404(runtime, refreshed_session)
    return HubSessionEnvelope(
        session=refreshed_session.model_dump(mode="json"),
        runtime=_runtime_envelope_for_browser(bound),
        handoff=handoff.model_dump(mode="json"),
    )


@router.get("/{session_id}/resources")
async def get_hub_session_resources(
    request: Request,
    session_id: str,
) -> HubSessionResourcesEnvelope:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Hub session not found")
    await _get_hub_runtime_or_404(runtime, session)
    return HubSessionResourcesEnvelope(resources=list(_hub_session_resource_manifest()))


@router.post("/{session_id}/handoff")
async def create_hub_workspace_handoff(
    request: Request,
    session_id: str,
    payload: HubWorkspaceHandoffRequest,
) -> HubWorkspaceHandoffEnvelope:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Hub session not found")
    handoff = await runtime.build_hub_handoff(user.id, session.id, payload)
    return HubWorkspaceHandoffEnvelope(handoff=handoff.model_dump(mode="json"))


class CreateCellRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=100_000)


class CreateCellResponse(BaseModel):
    cell_id: str
    runtime_session_id: str


_CELL_INJECT_TIMEOUT_SECONDS = 15.0


def _generate_external_cell_id() -> str:
    """Marimo external cell id: UUID4 (36 chars) + 4 ASCII letters = 40 chars."""
    suffix = "".join(random.choices(string.ascii_letters, k=4))
    return f"{uuid4()}{suffix}"


def _resolve_marimo_internal_base_url(target: Any) -> str | None:
    """Pick the cluster-internal marimo URL the orchestrator should call."""
    internal = getattr(target, "internal_url", None)
    if isinstance(internal, str) and internal.strip():
        return internal.strip().rstrip("/")
    public = getattr(target, "public_url", None)
    if isinstance(public, str) and public.strip():
        return public.strip().rstrip("/")
    return None


@router.post("/{session_id}/cells")
async def append_marimo_cell(
    request: Request,
    session_id: str,
    payload: CreateCellRequest,
) -> CreateCellResponse:
    """Append a cell to the marimo notebook bound to this BR hub session.

    Proxies a single ``CreateCell`` change to marimo's
    ``POST /api/document/transaction`` upstream API. Authenticates with the
    per-pod runtime token persisted on the runtime DB row.
    """
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Hub session not found")
    bound = await _get_hub_runtime_or_404(runtime, session)
    resolved = await runtime.get_marimo_runtime_target(session_id)
    if resolved is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "marimo-runtime-not-ready", "reason": "no_target"},
        )
    runtime_session, target = resolved
    if not target.ready:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "marimo-runtime-not-ready",
                "reason": target.status_reason or "runtime_not_ready",
            },
        )
    base_url = _resolve_marimo_internal_base_url(target)
    if base_url is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "marimo-runtime-not-ready", "reason": "no_marimo_url"},
        )
    token = await runtime.get_runtime_token(session_id)

    cell_id = _generate_external_cell_id()
    transaction_body = {
        "changes": [
            {
                "type": "create-cell",
                "cellId": cell_id,
                "code": payload.code,
                "name": "_",
                "config": {},
            }
        ]
    }
    headers = {
        "content-type": "application/json",
        "Marimo-Session-Id": runtime_session.id,
    }
    if token:
        headers["Marimo-Server-Token"] = token

    try:
        async with httpx.AsyncClient(timeout=_CELL_INJECT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/api/document/transaction",
                json=transaction_body,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "Marimo cell append network error for session=%s runtime=%s url=%s: %s",
            session_id,
            runtime_session.id,
            base_url,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "network-error", "reason": str(exc)},
        ) from exc

    if response.status_code == 401 or response.status_code == 403:
        raise HTTPException(
            status_code=503,
            detail={"error": "marimo-auth-failed", "reason": "token_rejected"},
        )
    if response.status_code == 404:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "marimo-session-not-found",
                "reason": "session_id_unknown",
            },
        )
    if response.status_code >= 500:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "marimo-runtime-not-ready",
                "reason": f"upstream_{response.status_code}",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "error": "marimo-upstream-rejected",
                "reason": response.text[:200],
            },
        )

    return CreateCellResponse(cell_id=cell_id, runtime_session_id=bound.id)


@router.delete("/{session_id}")
async def delete_hub_session(
    request: Request,
    session_id: str,
) -> HubSessionActionEnvelope:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    session = await runtime.get_session(session_id)
    if session is None or session.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Hub session not found")
    bound = await _get_hub_runtime_or_404(runtime, session)
    result = await runtime.perform_action(
        user.id,
        session_id,
        "close",
        StudioSessionActionRequest(reason="hub_session_deleted"),
    )
    return HubSessionActionEnvelope(
        action=result["action"],
        session=result["session"],
        runtime=_runtime_envelope_for_browser(bound),
    )
