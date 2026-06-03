"""FastAPI endpoints for the hosted Studio notebook gateway."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ..studio_notebook_runtime import (
    StudioNotebookDocumentInput,
    StudioNotebookExecutionRequest,
    StudioNotebookOperationRequest,
    StudioNotebookOpsRequest,
    StudioNotebookPatchRequest,
    StudioNotebookRuntime,
)

router = APIRouter(
    prefix="/api/studio/sessions/{session_id}/notebook",
    tags=["studio-notebooks"],
)


def _runtime_from_request(request: Request) -> StudioNotebookRuntime:
    runtime = getattr(request.app.state, "studio_notebook_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503, detail="Studio notebook runtime is not available"
        )
    return runtime


async def _resolve_request_user(request: Request):
    from ..auth_endpoints import _resolve_authenticated_user

    return await _resolve_authenticated_user(request)


@router.get("")
async def get_studio_notebook(request: Request, session_id: str) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    notebook = await runtime.get_notebook(user.id, session_id)
    if notebook is None:
        raise HTTPException(status_code=404, detail="Studio notebook not found")
    return {"notebook": notebook.model_dump(mode="json", by_alias=True)}


@router.post("/open-or-create")
async def open_or_create_studio_notebook(
    request: Request,
    session_id: str,
    payload: StudioNotebookDocumentInput | None = None,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        notebook = await runtime.open_or_create_notebook(user.id, session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"notebook": notebook.model_dump(mode="json", by_alias=True)}


@router.patch("")
async def patch_studio_notebook(
    request: Request,
    session_id: str,
    payload: StudioNotebookPatchRequest,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        notebook = await runtime.patch_notebook(user.id, session_id, payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Studio notebook not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"notebook": notebook.model_dump(mode="json", by_alias=True)}


@router.post("/ops")
async def apply_studio_notebook_operation(
    request: Request,
    session_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        if "ops" in payload or "operations" in payload:
            operations = payload.get("operations")
            if operations is None:
                operations = payload.get("ops")
            ops_request = StudioNotebookOpsRequest.model_validate(
                {
                    "operations": operations or [],
                    "expected_revision": payload.get("expected_revision"),
                }
            )
            notebook = await runtime.apply_operations(user.id, session_id, ops_request)
            return {
                "operations": [
                    operation.model_dump(mode="json", by_alias=True)
                    for operation in ops_request.operations
                ],
                "notebook": notebook.model_dump(mode="json", by_alias=True),
            }
        single_request = StudioNotebookOperationRequest.model_validate(payload)
        notebook = await runtime.apply_operation(user.id, session_id, single_request)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Studio notebook not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "operation": single_request.op,
        "notebook": notebook.model_dump(mode="json", by_alias=True),
    }


@router.post("/cells/{cell_id}/execute")
async def execute_studio_notebook_cell(
    request: Request,
    session_id: str,
    cell_id: str,
    payload: StudioNotebookExecutionRequest | None = None,
) -> dict[str, Any]:
    runtime = _runtime_from_request(request)
    user, _ = await _resolve_request_user(request)
    try:
        execution = await runtime.execute_cell(user.id, session_id, cell_id, payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Studio notebook not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "cell_id": cell_id,
        "execution": execution.execution.model_dump(mode="json"),
        "notebook": execution.notebook.model_dump(mode="json", by_alias=True),
    }
