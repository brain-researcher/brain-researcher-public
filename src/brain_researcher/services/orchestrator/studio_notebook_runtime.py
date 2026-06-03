"""Hosted Studio notebook runtime.

This runtime owns the notebook document resource for hosted Studio. The
canonical source of truth is a standard ``.ipynb`` file stored under the
project workspace. Lightweight notebook metadata is mirrored in SQLite so the
control plane can find and reopen the document quickly.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import nbformat
from nbformat import v4 as nbf
from pydantic import AliasChoices, BaseModel, Field

from .state_store import resolve_state_db_path
from .studio_execution_runtime import (
    StudioExecution,
    StudioExecutionBackend,
    StudioExecutionKind,
    StudioExecutionRequest,
    StudioExecutionResult,
    StudioExecutionRuntime,
    StudioExecutionStatus,
)
from .studio_session_runtime import (
    StudioRuntimeSession,
    StudioSession,
    StudioSessionRuntime,
    resolve_runtime_absolute_working_directory,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _deserialize_datetime(value: str | None) -> datetime:
    if not value:
        return _utc_now()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _default_studio_db_path() -> Path:
    return Path(resolve_state_db_path())


def _cell_id() -> str:
    return f"cell_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"


def _normalize_source(value: str | list[str] | None) -> str:
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value or "")


def _normalize_notebook_title(path: str, explicit_title: str | None = None) -> str:
    candidate = (explicit_title or "").strip()
    if candidate:
        return candidate
    return Path(path).stem.replace("_", " ").strip() or "Studio notebook"


def _summarize_command(value: str | None, *, max_lines: int = 3, max_chars: int = 240) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    preview = " | ".join(lines[:max_lines])
    if len(lines) > max_lines:
        preview = f"{preview} | ..."
    if len(preview) > max_chars:
        preview = f"{preview[: max_chars - 3]}..."
    return preview


class StudioNotebookCellType(str, Enum):
    CODE = "code"
    MARKDOWN = "markdown"


class StudioNotebookCellStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StudioNotebookOutput(BaseModel):
    output_type: str = Field(..., min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    text: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    ename: str | None = Field(default=None, max_length=200)
    evalue: str | None = None
    traceback: list[str] = Field(default_factory=list)
    execution_count: int | None = None


class StudioNotebookCell(BaseModel):
    id: str = Field(..., min_length=1, max_length=200)
    type: StudioNotebookCellType = Field(
        ...,
        validation_alias=AliasChoices("type", "cell_type"),
        serialization_alias="cell_type",
    )
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    outputs: list[StudioNotebookOutput] = Field(default_factory=list)
    execution_count: int | None = None
    status: StudioNotebookCellStatus = StudioNotebookCellStatus.IDLE


class StudioNotebook(BaseModel):
    id: str = Field(..., pattern=r"^nb_[A-Za-z0-9]+$")
    session_id: str = Field(..., pattern=r"^studio_[A-Za-z0-9]+$")
    runtime_session_id: str = Field(..., pattern=r"^rt_[A-Za-z0-9]+$")
    project_id: str = Field(..., min_length=1, max_length=200)
    owner_user_id: str = Field(..., min_length=1, max_length=200)
    path: str = Field(..., min_length=1, max_length=2000)
    title: str = Field(..., min_length=1, max_length=300)
    kernel_name: str = Field(default="python3", min_length=1, max_length=100)
    format: str = Field(default="ipynb", min_length=1, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    cells: list[StudioNotebookCell] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_saved_at: datetime = Field(default_factory=_utc_now)
    revision: int = Field(default=1, ge=1)


class StudioNotebookCellInput(BaseModel):
    id: str | None = Field(default=None, max_length=200)
    type: StudioNotebookCellType = Field(
        ...,
        validation_alias=AliasChoices("type", "cell_type"),
        serialization_alias="cell_type",
    )
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    outputs: list[StudioNotebookOutput] = Field(default_factory=list)
    execution_count: int | None = None
    status: StudioNotebookCellStatus | None = None


class OpenOrCreateStudioNotebookRequest(BaseModel):
    path: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    create_if_missing: bool = True


class UpdateStudioNotebookRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    metadata: dict[str, Any] | None = None
    cells: list[StudioNotebookCellInput] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class StudioNotebookOperationType(str, Enum):
    APPEND = "append"
    UPDATE_CELL = "update_cell"
    DELETE_CELL = "delete_cell"
    MOVE_CELL = "move_cell"
    REPLACE_CELL = "replace_cell"
    APPLY_OUTPUTS = "apply_outputs"
    EDIT = "edit"
    EDIT_AND_MOVE = "edit_and_move"


class StudioNotebookOperation(BaseModel):
    type: StudioNotebookOperationType
    cell_id: str | None = Field(default=None, max_length=200)
    before_cell_id: str | None = Field(default=None, max_length=200)
    after_cell_id: str | None = Field(default=None, max_length=200)
    cell: StudioNotebookCellInput | None = None
    source: str | None = None
    outputs: list[StudioNotebookOutput] | None = None
    execution_count: int | None = None
    status: StudioNotebookCellStatus | None = None
    metadata: dict[str, Any] | None = None


class StudioNotebookOpsRequest(BaseModel):
    operations: list[StudioNotebookOperation] = Field(default_factory=list)
    expected_revision: int | None = Field(default=None, ge=1)


class StudioNotebookExecuteCellRequest(BaseModel):
    working_directory: str | None = Field(default=None, max_length=2000)
    timeout_seconds: int | None = Field(default=None, ge=1)
    env: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioNotebookDocumentInput(BaseModel):
    notebook_path: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    kernel_name: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    cells: list[StudioNotebookCellInput] = Field(default_factory=list)


class StudioNotebookPatchRequest(BaseModel):
    notebook: StudioNotebook | None = None
    title: str | None = Field(default=None, max_length=300)
    metadata: dict[str, Any] | None = None
    cells: list[StudioNotebookCellInput] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class StudioNotebookOperationRequest(BaseModel):
    op: StudioNotebookOperationType
    cell_id: str | None = Field(default=None, max_length=200)
    cell: StudioNotebookCellInput | None = None
    source: str | None = None
    after_cell_id: str | None = Field(default=None, max_length=200)
    before_cell_id: str | None = Field(default=None, max_length=200)
    outputs: list[StudioNotebookOutput] | None = None
    execution_count: int | None = None
    status: StudioNotebookCellStatus | None = None
    metadata: dict[str, Any] | None = None


class StudioNotebookExecutionRequest(StudioNotebookExecuteCellRequest):
    notebook_path: str | None = Field(default=None, max_length=2000)
    runtime_profile_id: str | None = Field(default=None, max_length=100)


class StudioNotebookCellExecution(BaseModel):
    cell_id: str
    execution: StudioExecution
    notebook: StudioNotebook


class StudioNotebookRuntime:
    """SQLite-backed Studio notebook facade with ``.ipynb`` persistence."""

    def __init__(
        self,
        *,
        studio_session_runtime: StudioSessionRuntime,
        studio_execution_runtime: StudioExecutionRuntime | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self._studio_session_runtime = studio_session_runtime
        self._studio_execution_runtime = studio_execution_runtime
        self._db_path = Path(
            db_path
            or getattr(studio_session_runtime, "_db_path", None)
            or _default_studio_db_path()
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = int(
            os.getenv("BR_SQLITE_BUSY_TIMEOUT_MS", "5000")
        )
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=self._busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS studio_notebooks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE,
                runtime_session_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                path TEXT NOT NULL,
                title TEXT NOT NULL,
                kernel_name TEXT NOT NULL,
                format TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_saved_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_notebooks_owner_project_updated "
            "ON studio_notebooks(owner_user_id, project_id, updated_at DESC)"
        )

    async def get_notebook(
        self,
        owner_user_id: str,
        session_id: str,
    ) -> StudioNotebook | None:
        session, runtime = await self._resolve_session_and_runtime(owner_user_id, session_id)
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM studio_notebooks WHERE session_id = ?",
                    (session.id,),
                ).fetchone()
                if row is not None:
                    notebook = self._hydrate_notebook_from_row(
                        self._row_to_notebook(row),
                        runtime,
                    )
                    self._upsert_notebook_locked(conn, notebook)
                    return notebook
        notebook_path = self._resolve_notebook_workspace_path(
            session,
            runtime,
            raw_path=None,
        )
        absolute_path = self._resolve_absolute_notebook_path(runtime, notebook_path)
        if not absolute_path.exists():
            return None
        notebook = self._load_notebook_from_path(
            session=session,
            runtime=runtime,
            notebook_id=f"nb_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}",
            notebook_path=notebook_path,
            absolute_path=absolute_path,
            created_at=_utc_now(),
            revision=1,
        )
        with self._lock:
            with self._connect() as conn:
                self._upsert_notebook_locked(conn, notebook)
        return notebook

    async def open_or_create_notebook(
        self,
        owner_user_id: str,
        session_id: str,
        request: OpenOrCreateStudioNotebookRequest | StudioNotebookDocumentInput | None = None,
    ) -> StudioNotebook:
        payload, initial_cells, metadata_updates = self._normalize_open_request(request)
        session, runtime = await self._resolve_session_and_runtime(owner_user_id, session_id)
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM studio_notebooks WHERE session_id = ?",
                    (session.id,),
                ).fetchone()
                existing = self._row_to_notebook(row) if row is not None else None

                notebook_path = self._resolve_notebook_workspace_path(
                    session,
                    runtime,
                    raw_path=payload.path or (existing.path if existing else None),
                )
                absolute_path = self._resolve_absolute_notebook_path(runtime, notebook_path)

                if absolute_path.exists():
                    notebook = self._load_notebook_from_path(
                        session=session,
                        runtime=runtime,
                        notebook_id=existing.id if existing else self._new_notebook_id(),
                        notebook_path=notebook_path,
                        absolute_path=absolute_path,
                        created_at=existing.created_at if existing else _utc_now(),
                        revision=existing.revision if existing else 1,
                        title_override=payload.title or (existing.title if existing else None),
                    )
                else:
                    if not payload.create_if_missing:
                        raise FileNotFoundError(notebook_path)
                    notebook = self._build_default_notebook(
                        session=session,
                        runtime=runtime,
                        notebook_id=existing.id if existing else self._new_notebook_id(),
                        notebook_path=notebook_path,
                        title=payload.title or (existing.title if existing else None),
                        created_at=existing.created_at if existing else _utc_now(),
                        revision=(existing.revision if existing else 0) + 1,
                    )
                if initial_cells is not None:
                    notebook = notebook.model_copy(update={"cells": initial_cells})
                if metadata_updates:
                    notebook = notebook.model_copy(
                        update={
                            "metadata": {
                                **dict(notebook.metadata or {}),
                                **metadata_updates,
                            }
                        }
                    )
                self._write_notebook_file(notebook, runtime)

                self._upsert_notebook_locked(conn, notebook)
                return notebook

    async def update_notebook(
        self,
        owner_user_id: str,
        session_id: str,
        request: UpdateStudioNotebookRequest,
    ) -> StudioNotebook:
        notebook = await self.open_or_create_notebook(owner_user_id, session_id)
        if request.expected_revision is not None and notebook.revision != request.expected_revision:
            raise ValueError("Notebook revision conflict")
        updated = notebook.model_copy(
            update={
                "title": request.title or notebook.title,
                "metadata": (
                    {**notebook.metadata, **request.metadata}
                    if request.metadata
                    else notebook.metadata
                ),
                "cells": (
                    [self._input_to_cell(cell) for cell in request.cells]
                    if request.cells is not None
                    else notebook.cells
                ),
                "updated_at": _utc_now(),
                "last_saved_at": _utc_now(),
                "revision": notebook.revision + 1,
            }
        )
        session, runtime = await self._resolve_session_and_runtime(owner_user_id, session_id)
        self._write_notebook_file(updated, runtime)
        with self._lock:
            with self._connect() as conn:
                self._upsert_notebook_locked(conn, updated)
        return updated

    async def patch_notebook(
        self,
        owner_user_id: str,
        session_id: str,
        request: StudioNotebookPatchRequest,
    ) -> StudioNotebook:
        if request.notebook is not None:
            payload = UpdateStudioNotebookRequest(
                title=request.notebook.title,
                metadata=request.notebook.metadata,
                cells=[
                    StudioNotebookCellInput.model_validate(cell.model_dump(mode="python"))
                    for cell in request.notebook.cells
                ],
                expected_revision=request.expected_revision or request.notebook.revision,
            )
        else:
            payload = UpdateStudioNotebookRequest(
                title=request.title,
                metadata=request.metadata,
                cells=request.cells,
                expected_revision=request.expected_revision,
            )
        return await self.update_notebook(owner_user_id, session_id, payload)

    async def apply_operations(
        self,
        owner_user_id: str,
        session_id: str,
        request: StudioNotebookOpsRequest,
    ) -> StudioNotebook:
        notebook = await self.open_or_create_notebook(owner_user_id, session_id)
        if request.expected_revision is not None and notebook.revision != request.expected_revision:
            raise ValueError("Notebook revision conflict")
        cells = [cell.model_copy(deep=True) for cell in notebook.cells]
        for operation in request.operations:
            cells = self._apply_operation(cells, operation)
        updated = notebook.model_copy(
            update={
                "cells": cells,
                "updated_at": _utc_now(),
                "last_saved_at": _utc_now(),
                "revision": notebook.revision + 1,
            }
        )
        _, runtime = await self._resolve_session_and_runtime(owner_user_id, session_id)
        self._write_notebook_file(updated, runtime)
        with self._lock:
            with self._connect() as conn:
                self._upsert_notebook_locked(conn, updated)
        return updated

    async def apply_operation(
        self,
        owner_user_id: str,
        session_id: str,
        request: StudioNotebookOperationRequest,
    ) -> StudioNotebook:
        return await self.apply_operations(
            owner_user_id,
            session_id,
            StudioNotebookOpsRequest(
                operations=[
                    StudioNotebookOperation(
                        type=request.op,
                        cell_id=request.cell_id,
                        before_cell_id=request.before_cell_id,
                        after_cell_id=request.after_cell_id,
                        cell=request.cell,
                        source=request.source,
                        outputs=request.outputs,
                        execution_count=request.execution_count,
                        status=request.status,
                        metadata=request.metadata,
                    )
                ]
            ),
        )

    async def execute_cell(
        self,
        owner_user_id: str,
        session_id: str,
        cell_id: str,
        request: StudioNotebookExecuteCellRequest | StudioNotebookExecutionRequest | None = None,
    ) -> StudioNotebookCellExecution:
        payload = request or StudioNotebookExecuteCellRequest()
        notebook = await self.open_or_create_notebook(owner_user_id, session_id)
        target_cell = next((cell for cell in notebook.cells if cell.id == cell_id), None)
        if target_cell is None:
            raise KeyError(cell_id)
        if target_cell.type != StudioNotebookCellType.CODE:
            raise ValueError("Only code cells can be executed")
        session, runtime = await self._resolve_session_and_runtime(owner_user_id, session_id)
        execution = await self._run_cell_execution(
            owner_user_id=owner_user_id,
            session=session,
            runtime=runtime,
            notebook=notebook,
            cell=target_cell,
            request=payload,
        )
        patched = self._apply_cell_execution_result(notebook, cell_id, execution)
        self._write_notebook_file(patched, runtime)
        with self._lock:
            with self._connect() as conn:
                self._upsert_notebook_locked(conn, patched)
        return StudioNotebookCellExecution(
            cell_id=cell_id,
            execution=execution,
            notebook=patched,
        )

    async def _run_cell_execution(
        self,
        *,
        owner_user_id: str,
        session: StudioSession,
        runtime: StudioRuntimeSession,
        notebook: StudioNotebook,
        cell: StudioNotebookCell,
        request: StudioNotebookExecuteCellRequest,
    ) -> StudioExecution:
        execution_runtime = self._studio_execution_runtime
        if execution_runtime is None:
            raise RuntimeError("Studio execution runtime is not available")
        notebook_dir = self._resolve_notebook_working_directory(runtime, notebook.path)
        execution = await execution_runtime.create_execution(
            owner_user_id,
            session.id,
            StudioExecutionRequest(
                kind=StudioExecutionKind.CODE,
                language="python",
                code=cell.source,
                runtime_backend=StudioExecutionBackend.JUPYTER_KERNEL,
                runtime_profile_id=session.runtime_profile_id,
                working_directory=request.working_directory or notebook_dir,
                timeout_seconds=request.timeout_seconds or 120,
                env=request.env,
                dry_run=False,
                metadata={
                    **request.metadata,
                    "source": "studio_notebook_cell",
                    "cell_id": cell.id,
                    "notebook_path": notebook.path,
                },
            ),
        )
        terminal = {
            StudioExecutionStatus.SUCCEEDED,
            StudioExecutionStatus.FAILED,
            StudioExecutionStatus.CANCELED,
        }
        deadline = time.monotonic() + float(request.timeout_seconds or 120)
        current = execution
        while current.status not in terminal and time.monotonic() < deadline:
            await __import__("asyncio").sleep(0.1)
            hydrated = await execution_runtime.get_execution(
                owner_user_id,
                session.id,
                current.id,
            )
            if hydrated is None:
                break
            current = hydrated
        return current

    def _resolve_notebook_working_directory(
        self,
        runtime: StudioRuntimeSession,
        notebook_path: str,
    ) -> str | None:
        notebook_dir = str(Path(notebook_path).parent).strip("/")
        workspace_root = str(runtime.metadata.get("workspace_relative_root") or "").strip("/")
        if workspace_root and notebook_dir.startswith(f"{workspace_root}/"):
            trimmed = notebook_dir[len(workspace_root) + 1 :]
            return trimmed or None
        if notebook_dir == workspace_root:
            return None
        return notebook_dir or None

    def _normalize_open_request(
        self,
        request: OpenOrCreateStudioNotebookRequest | StudioNotebookDocumentInput | None,
    ) -> tuple[
        OpenOrCreateStudioNotebookRequest,
        list[StudioNotebookCell] | None,
        dict[str, Any],
    ]:
        if request is None:
            return OpenOrCreateStudioNotebookRequest(), None, {}
        if isinstance(request, OpenOrCreateStudioNotebookRequest):
            return request, None, {}
        cells = (
            [self._input_to_cell(cell) for cell in request.cells]
            if request.cells
            else None
        )
        return (
            OpenOrCreateStudioNotebookRequest(
                path=request.notebook_path,
                title=request.title,
                create_if_missing=True,
            ),
            cells,
            dict(request.metadata or {}),
        )

    async def _resolve_session_and_runtime(
        self,
        owner_user_id: str,
        session_id: str,
    ) -> tuple[StudioSession, StudioRuntimeSession]:
        session = await self._studio_session_runtime.get_session(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            raise KeyError(session_id)
        runtime = await self._studio_session_runtime.get_runtime_session(
            session.runtime_session_id
        )
        if runtime is None:
            raise RuntimeError("Studio runtime session is not available")
        return session, runtime

    def _resolve_notebook_workspace_path(
        self,
        session: StudioSession,
        runtime: StudioRuntimeSession,
        *,
        raw_path: str | None,
    ) -> str:
        raw_candidate = raw_path or f"notebooks/studio/{session.id}.ipynb"
        resolver = self._studio_session_runtime._resolve_workspace_tree_path
        workspace_path = resolver(raw_candidate, runtime, project_id=session.project_id)
        if not workspace_path or not workspace_path.endswith(".ipynb"):
            raise ValueError("Studio notebook path must resolve to an .ipynb file")
        return workspace_path

    def _resolve_absolute_notebook_path(
        self,
        runtime: StudioRuntimeSession,
        notebook_path: str,
    ) -> Path:
        workspace_root = str(runtime.metadata.get("workspace_relative_root") or "").strip("/")
        absolute_root = str(
            resolve_runtime_absolute_working_directory(runtime) or ""
        ).strip()
        if not absolute_root:
            raise RuntimeError("Studio runtime does not expose a project working directory")
        relative = notebook_path
        if workspace_root and notebook_path.startswith(f"{workspace_root}/"):
            relative = notebook_path[len(workspace_root) + 1 :]
        elif workspace_root and notebook_path == workspace_root:
            relative = Path(notebook_path).name
        return Path(absolute_root) / relative

    def _build_default_notebook(
        self,
        *,
        session: StudioSession,
        runtime: StudioRuntimeSession,
        notebook_id: str,
        notebook_path: str,
        title: str | None,
        created_at: datetime,
        revision: int,
    ) -> StudioNotebook:
        resolved_title = _normalize_notebook_title(notebook_path, title)
        heading_cell = StudioNotebookCell(
            id=_cell_id(),
            type=StudioNotebookCellType.MARKDOWN,
            source=f"# {resolved_title}\n\nCreated from Brain Researcher Studio.",
            metadata={},
        )
        code_cell = StudioNotebookCell(
            id=_cell_id(),
            type=StudioNotebookCellType.CODE,
            source="",
            metadata={},
        )
        now = _utc_now()
        return StudioNotebook(
            id=notebook_id,
            session_id=session.id,
            runtime_session_id=runtime.id,
            project_id=session.project_id,
            owner_user_id=session.owner_user_id,
            path=notebook_path,
            title=resolved_title,
            kernel_name=runtime.jupyter_kernel_name or "python3",
            metadata={
                "brain_researcher": {
                    "session_id": session.id,
                    "runtime_session_id": runtime.id,
                    "surface_origin": "studio",
                }
            },
            cells=[heading_cell, code_cell],
            created_at=created_at,
            updated_at=now,
            last_saved_at=now,
            revision=max(revision, 1),
        )

    def _load_notebook_from_path(
        self,
        *,
        session: StudioSession,
        runtime: StudioRuntimeSession,
        notebook_id: str,
        notebook_path: str,
        absolute_path: Path,
        created_at: datetime,
        revision: int,
        title_override: str | None = None,
    ) -> StudioNotebook:
        notebook_node = nbformat.read(absolute_path, as_version=4)
        metadata = dict(notebook_node.get("metadata") or {})
        kernelspec = dict(metadata.get("kernelspec") or {})
        kernel_name = str(
            kernelspec.get("name") or runtime.jupyter_kernel_name or "python3"
        )
        cells = [self._nb_cell_to_model(cell) for cell in notebook_node.cells]
        stat = absolute_path.stat()
        last_saved = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        updated_at = _utc_now()
        title = _normalize_notebook_title(notebook_path, title_override)
        return StudioNotebook(
            id=notebook_id,
            session_id=session.id,
            runtime_session_id=runtime.id,
            project_id=session.project_id,
            owner_user_id=session.owner_user_id,
            path=notebook_path,
            title=title,
            kernel_name=kernel_name,
            metadata=metadata,
            cells=cells,
            created_at=created_at,
            updated_at=updated_at,
            last_saved_at=last_saved,
            revision=max(revision, 1),
        )

    def _write_notebook_file(
        self,
        notebook: StudioNotebook,
        runtime: StudioRuntimeSession,
    ) -> None:
        absolute_path = self._resolve_absolute_notebook_path(runtime, notebook.path)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        notebook_node = nbf.new_notebook(
            cells=[self._model_cell_to_nb(cell) for cell in notebook.cells],
            metadata={
                **dict(notebook.metadata or {}),
                "kernelspec": {
                    **dict((notebook.metadata or {}).get("kernelspec") or {}),
                    "name": notebook.kernel_name,
                    "display_name": notebook.kernel_name,
                    "language": "python",
                },
            },
        )
        nbformat.write(notebook_node, absolute_path)

    def _nb_cell_to_model(self, cell: Any) -> StudioNotebookCell:
        metadata = dict(cell.get("metadata") or {})
        br_meta = dict(metadata.get("brain_researcher") or {})
        status = str(br_meta.get("status") or StudioNotebookCellStatus.IDLE.value)
        cell_id = str(cell.get("id") or _cell_id())
        outputs = []
        for output in cell.get("outputs") or []:
            output_type = str(output.get("output_type") or "")
            outputs.append(
                StudioNotebookOutput(
                    output_type=output_type,
                    name=output.get("name"),
                    text=_normalize_source(output.get("text")),
                    data=dict(output.get("data") or {}),
                    metadata=dict(output.get("metadata") or {}),
                    ename=output.get("ename"),
                    evalue=output.get("evalue"),
                    traceback=list(output.get("traceback") or []),
                    execution_count=output.get("execution_count"),
                )
            )
        return StudioNotebookCell(
            id=cell_id,
            type=StudioNotebookCellType.CODE
            if cell.get("cell_type") == "code"
            else StudioNotebookCellType.MARKDOWN,
            source=_normalize_source(cell.get("source")),
            metadata=metadata,
            outputs=outputs,
            execution_count=cell.get("execution_count"),
            status=StudioNotebookCellStatus(status),
        )

    def _model_cell_to_nb(self, cell: StudioNotebookCell) -> dict[str, Any]:
        metadata = dict(cell.metadata or {})
        br_meta = dict(metadata.get("brain_researcher") or {})
        br_meta["status"] = cell.status.value
        metadata["brain_researcher"] = br_meta
        if cell.type == StudioNotebookCellType.MARKDOWN:
            notebook_cell = nbf.new_markdown_cell(source=cell.source, metadata=metadata)
        else:
            notebook_cell = nbf.new_code_cell(
                source=cell.source,
                metadata=metadata,
                execution_count=cell.execution_count,
                outputs=[self._model_output_to_nb(output) for output in cell.outputs],
            )
        notebook_cell["id"] = cell.id
        return notebook_cell

    def _model_output_to_nb(self, output: StudioNotebookOutput) -> dict[str, Any]:
        payload: dict[str, Any] = {"output_type": output.output_type}
        if output.output_type == "stream":
            payload["name"] = output.name or "stdout"
            payload["text"] = output.text or ""
        elif output.output_type == "error":
            payload["ename"] = output.ename or "Error"
            payload["evalue"] = output.evalue or ""
            payload["traceback"] = list(output.traceback or [])
        else:
            payload["data"] = dict(output.data or {})
            payload["metadata"] = dict(output.metadata or {})
            if output.execution_count is not None:
                payload["execution_count"] = output.execution_count
        return nbf.new_output(**payload)

    def _row_to_notebook(self, row: sqlite3.Row) -> StudioNotebook:
        return StudioNotebook.model_validate(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "runtime_session_id": row["runtime_session_id"],
                "project_id": row["project_id"],
                "owner_user_id": row["owner_user_id"],
                "path": row["path"],
                "title": row["title"],
                "kernel_name": row["kernel_name"],
                "format": row["format"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "cells": [],
                "revision": row["revision"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_saved_at": row["last_saved_at"],
            }
        )

    def _upsert_notebook_locked(self, conn: sqlite3.Connection, notebook: StudioNotebook) -> None:
        payload = {
            "id": notebook.id,
            "session_id": notebook.session_id,
            "runtime_session_id": notebook.runtime_session_id,
            "project_id": notebook.project_id,
            "owner_user_id": notebook.owner_user_id,
            "path": notebook.path,
            "title": notebook.title,
            "kernel_name": notebook.kernel_name,
            "format": notebook.format,
            "metadata_json": json.dumps(
                notebook.metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "revision": notebook.revision,
            "created_at": _serialize_datetime(notebook.created_at),
            "updated_at": _serialize_datetime(notebook.updated_at),
            "last_saved_at": _serialize_datetime(notebook.last_saved_at),
        }
        conn.execute(
            """
            INSERT INTO studio_notebooks (
                id,
                session_id,
                runtime_session_id,
                project_id,
                owner_user_id,
                path,
                title,
                kernel_name,
                format,
                metadata_json,
                revision,
                created_at,
                updated_at,
                last_saved_at
            ) VALUES (
                :id,
                :session_id,
                :runtime_session_id,
                :project_id,
                :owner_user_id,
                :path,
                :title,
                :kernel_name,
                :format,
                :metadata_json,
                :revision,
                :created_at,
                :updated_at,
                :last_saved_at
            )
            ON CONFLICT(session_id) DO UPDATE SET
                runtime_session_id = excluded.runtime_session_id,
                project_id = excluded.project_id,
                owner_user_id = excluded.owner_user_id,
                path = excluded.path,
                title = excluded.title,
                kernel_name = excluded.kernel_name,
                format = excluded.format,
                metadata_json = excluded.metadata_json,
                revision = excluded.revision,
                updated_at = excluded.updated_at,
                last_saved_at = excluded.last_saved_at
            """,
            payload,
        )
        conn.commit()

    def _hydrate_notebook_from_row(
        self,
        notebook: StudioNotebook,
        runtime: StudioRuntimeSession,
    ) -> StudioNotebook:
        absolute_path = self._resolve_absolute_notebook_path(runtime, notebook.path)
        if not absolute_path.exists():
            return notebook.model_copy(update={"cells": []})
        return self._load_notebook_from_path(
            session=StudioSession.model_validate(
                {
                    "id": notebook.session_id,
                    "project_id": notebook.project_id,
                    "owner_user_id": notebook.owner_user_id,
                    "display_name": notebook.title,
                    "runtime_profile_id": runtime.runtime_profile_id,
                    "runtime_session_id": notebook.runtime_session_id,
                    "assistant_session_id": "ast_missing",
                    "status": "ready",
                    "metadata": {},
                }
            ),
            runtime=runtime,
            notebook_id=notebook.id,
            notebook_path=notebook.path,
            absolute_path=absolute_path,
            created_at=notebook.created_at,
            revision=notebook.revision,
            title_override=notebook.title,
        )

    def _new_notebook_id(self) -> str:
        return f"nb_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"

    def _input_to_cell(self, value: StudioNotebookCellInput) -> StudioNotebookCell:
        return StudioNotebookCell(
            id=value.id or _cell_id(),
            type=value.type,
            source=value.source,
            metadata=dict(value.metadata or {}),
            outputs=list(value.outputs or []),
            execution_count=value.execution_count,
            status=value.status or StudioNotebookCellStatus.IDLE,
        )

    def _apply_operation(
        self,
        cells: list[StudioNotebookCell],
        operation: StudioNotebookOperation,
    ) -> list[StudioNotebookCell]:
        next_cells = [cell.model_copy(deep=True) for cell in cells]

        def _index_for(cell_id: str) -> int:
            for index, candidate in enumerate(next_cells):
                if candidate.id == cell_id:
                    return index
            raise KeyError(cell_id)

        if operation.type == StudioNotebookOperationType.APPEND:
            if operation.cell is None:
                raise ValueError("append requires a cell payload")
            next_cells.append(self._input_to_cell(operation.cell))
            return next_cells

        if operation.type in {
            StudioNotebookOperationType.UPDATE_CELL,
            StudioNotebookOperationType.EDIT,
        }:
            if not operation.cell_id:
                raise ValueError("update_cell requires cell_id")
            idx = _index_for(operation.cell_id)
            current = next_cells[idx]
            metadata = dict(current.metadata)
            if operation.metadata:
                metadata.update(operation.metadata)
            next_cells[idx] = current.model_copy(
                update={
                    "source": operation.source if operation.source is not None else current.source,
                    "metadata": metadata,
                }
            )
            return next_cells

        if operation.type == StudioNotebookOperationType.DELETE_CELL:
            if not operation.cell_id:
                raise ValueError("delete_cell requires cell_id")
            idx = _index_for(operation.cell_id)
            next_cells.pop(idx)
            return next_cells

        if operation.type == StudioNotebookOperationType.MOVE_CELL:
            if not operation.cell_id:
                raise ValueError("move_cell requires cell_id")
            idx = _index_for(operation.cell_id)
            cell = next_cells.pop(idx)
            target_index = len(next_cells)
            if operation.before_cell_id:
                target_index = _index_for(operation.before_cell_id)
            elif operation.after_cell_id:
                target_index = _index_for(operation.after_cell_id) + 1
            next_cells.insert(target_index, cell)
            return next_cells

        if operation.type in {
            StudioNotebookOperationType.REPLACE_CELL,
            StudioNotebookOperationType.EDIT_AND_MOVE,
        }:
            if not operation.cell_id or operation.cell is None:
                raise ValueError("replace_cell requires cell_id and cell payload")
            idx = _index_for(operation.cell_id)
            replacement = self._input_to_cell(operation.cell)
            if operation.type == StudioNotebookOperationType.EDIT_AND_MOVE:
                next_cells.pop(idx)
                insert_at = len(next_cells)
                if operation.before_cell_id:
                    insert_at = _index_for(operation.before_cell_id)
                elif operation.after_cell_id:
                    insert_at = _index_for(operation.after_cell_id) + 1
                next_cells.insert(insert_at, replacement)
            else:
                next_cells[idx] = replacement
            return next_cells

        if operation.type == StudioNotebookOperationType.APPLY_OUTPUTS:
            if not operation.cell_id:
                raise ValueError("apply_outputs requires cell_id")
            idx = _index_for(operation.cell_id)
            current = next_cells[idx]
            next_cells[idx] = current.model_copy(
                update={
                    "outputs": list(operation.outputs or []),
                    "execution_count": operation.execution_count,
                    "status": operation.status or current.status,
                }
            )
            return next_cells

        raise ValueError(f"Unsupported notebook op: {operation.type}")

    def _apply_cell_execution_result(
        self,
        notebook: StudioNotebook,
        cell_id: str,
        execution: StudioExecution,
    ) -> StudioNotebook:
        execution_outputs = self._execution_result_to_outputs(execution)
        cells: list[StudioNotebookCell] = []
        for cell in notebook.cells:
            if cell.id != cell_id:
                cells.append(cell)
                continue
            status = (
                StudioNotebookCellStatus.SUCCEEDED
                if execution.status == StudioExecutionStatus.SUCCEEDED
                else StudioNotebookCellStatus.FAILED
            )
            execution_count = (
                execution.result.artifacts[0].get("execution_count")
                if execution.result and execution.result.artifacts
                else None
            )
            if not isinstance(execution_count, int):
                execution_count = None
            cells.append(
                cell.model_copy(
                    update={
                        "outputs": execution_outputs,
                        "execution_count": execution_count,
                        "status": status,
                    }
                )
            )
        now = _utc_now()
        return notebook.model_copy(
            update={
                "cells": cells,
                "updated_at": now,
                "last_saved_at": now,
                "revision": notebook.revision + 1,
            }
        )

    def _execution_result_to_outputs(
        self,
        execution: StudioExecution,
    ) -> list[StudioNotebookOutput]:
        result = execution.result
        if result is None:
            return []
        outputs: list[StudioNotebookOutput] = []
        if result.stdout:
            outputs.append(
                StudioNotebookOutput(
                    output_type="stream",
                    name="stdout",
                    text=result.stdout,
                )
            )
        for artifact in result.artifacts:
            artifact_type = str(artifact.get("type") or artifact.get("output_type") or "")
            if artifact_type in {"execute_result", "display_data"}:
                outputs.append(
                    StudioNotebookOutput(
                        output_type=artifact_type,
                        data=dict(artifact.get("data") or {}),
                        metadata=dict(artifact.get("metadata") or {}),
                        execution_count=artifact.get("execution_count"),
                    )
                )
        if execution.status == StudioExecutionStatus.FAILED:
            error_output = self._build_failed_execution_output(execution, result)
            if error_output is not None:
                outputs.append(error_output)
        elif result.stderr:
            outputs.append(
                StudioNotebookOutput(
                    output_type="stream",
                    name="stderr",
                    text=result.stderr,
                )
            )
        return outputs

    def _build_failed_execution_output(
        self,
        execution: StudioExecution,
        result: StudioExecutionResult,
    ) -> StudioNotebookOutput | None:
        metadata = dict(execution.metadata or {})
        backend_mode = str(metadata.get("backend_mode") or "").strip()
        backend_error = str(metadata.get("backend_error") or "").strip()
        error_name = str(
            metadata.get("backend_jupyter_error_name")
            or metadata.get("backend_error_name")
            or "ExecutionError"
        )
        primary_message = (
            backend_error
            or str(
                metadata.get("backend_jupyter_error_value")
                or result.stderr
                or result.summary
                or ""
            ).strip()
        )
        if not primary_message:
            primary_message = "Execution failed"

        traceback_lines: list[str] = []

        def _append_unique(text: str | None) -> None:
            cleaned = str(text or "").strip()
            if not cleaned:
                return
            for line in cleaned.splitlines():
                normalized = line.strip()
                if normalized and normalized not in traceback_lines:
                    traceback_lines.append(normalized)

        _append_unique(result.stderr)
        _append_unique(result.summary if result.summary != primary_message else None)
        _append_unique(backend_error if backend_error != primary_message else None)

        resolved_working_directory = str(
            metadata.get("resolved_working_directory") or execution.working_directory or ""
        ).strip()
        if resolved_working_directory:
            _append_unique(f"Working directory: {resolved_working_directory}")
        if backend_mode:
            _append_unique(f"Backend: {backend_mode}")
        submitted_command = str(metadata.get("submitted_command") or "").strip()
        if submitted_command and backend_mode == "tool_executor_direct":
            command_preview = _summarize_command(submitted_command)
            if command_preview:
                _append_unique(f"Command: {command_preview}")
        if not traceback_lines and primary_message:
            traceback_lines.append(primary_message)

        return StudioNotebookOutput(
            output_type="error",
            ename=error_name,
            evalue=primary_message,
            traceback=traceback_lines,
        )
