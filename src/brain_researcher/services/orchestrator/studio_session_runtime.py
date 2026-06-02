"""Hosted Studio session gateway runtime.

This runtime owns lightweight Studio session records and workspace handoff
construction. It is intentionally separate from raw execution and monitor
runtime behavior.

Contracts memorialized here
---------------------------

- Runtime reuse is keyed by ``(owner_user_id, project_id, runtime_profile_id,
  runtime_kind)`` and only considers active session bindings. A stopped session
  is never "reopened" in place.
- Closing a Jupyter-backed Studio session stops the session row but leaves the
  runtime row intact; a later ``create_or_attach_session`` call provisions a
  fresh session binding rather than reusing a stopped session record.
- Closing a Marimo-backed hosted session tears down the runtime target via the
  configured ``MarimoRuntimeProvisioner`` and marks the runtime row stopped.
- Stale Marimo runtimes that fail live-check reconciliation are marked stopped
  together with every bound session and best-effort cleaned up through the same
  provisioner destroy path.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from posixpath import normpath
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import BaseModel, Field

from .cleanup_reasons import CleanupReason
from .marimo_runtime_provisioner import (
    MarimoRuntimeProvisioner,
    MarimoRuntimeSpec,
    MarimoRuntimeTarget,
    build_marimo_runtime_provisioner_from_env,
)
from .state_store import resolve_state_db_path

logger = logging.getLogger(__name__)


def _offloaded(method):
    """Run a synchronous StudioSessionRuntime method on a worker thread.

    The runtime's public methods hold a process-wide ``threading.Lock`` and do
    blocking work (SQLite + synchronous kubernetes-client calls). Executing that
    directly on the asyncio event loop stalls the loop, which under provisioning
    bursts starves the liveness/readiness probes and the whole request path (the
    orchestrator is intentionally single-replica: SQLite + in-process locks).

    Wrapping each method in ``asyncio.to_thread`` keeps the event loop free while
    the blocking body runs in a thread; the ``threading.Lock`` still serializes
    the bodies across those threads exactly as before. The wrapped callable
    remains an awaitable coroutine function, so callers are unchanged.
    """

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, functools.partial(method, self, *args, **kwargs)
        )

    return wrapper


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _default_workspace_url() -> str:
    return (
        _normalize_optional_text(os.getenv("BR_PUBLIC_WORKSPACE_URL"))
        or _normalize_optional_text(os.getenv("NEXT_PUBLIC_WORKSPACE_URL"))
        or "https://hub.brain-researcher.com"
    ).rstrip("/")


def _append_marimo_access_token(
    public_url: str | None, token: str | None
) -> str | None:
    """Attach the per-pod marimo access token to the iframe handoff URL.

    Marimo gates both the editor HTML and the kernel websocket behind its
    ``--token-password-file`` auth (``validate_auth`` in
    ``marimo/_server/api/auth.py``). The browser iframe must therefore present
    the token on its first GET so marimo sets the signed ``session_<port>``
    cookie and serves the editor; marimo then strips ``access_token`` from the
    served URL itself. The token must equal the pod's ``auth_token``, so we
    reuse the per-pod runtime token rather than minting a separate one.

    This is the one intentional browser-facing use of the runtime token (same
    origin, lax cookie). All other surfaces must keep scrubbing it.
    """
    normalized_url = _normalize_optional_text(public_url)
    normalized_token = _normalize_optional_text(token)
    if normalized_url is None or normalized_token is None:
        return normalized_url
    separator = "&" if "?" in normalized_url else "?"
    return f"{normalized_url}{separator}{urlencode({'access_token': normalized_token})}"


def _default_marimo_base_url(workspace_base_url: str) -> str:
    explicit = _normalize_optional_text(
        os.getenv("BR_PUBLIC_HUB_URL") or os.getenv("NEXT_PUBLIC_HUB_URL")
    )
    if explicit:
        return explicit.rstrip("/")
    normalized = workspace_base_url.rstrip("/")
    if normalized == "https://hub.brain-researcher.com":
        return "https://brain-researcher.com/hub"
    return normalized if normalized.endswith("/hub") else f"{normalized}/hub"


def _default_marimo_port() -> int:
    raw = _normalize_optional_text(os.getenv("BR_MARIMO_PORT"))
    if raw is None:
        return 2718
    try:
        return int(raw)
    except ValueError:
        return 2718


def _studio_runtime_live_check_enabled() -> bool:
    value = _normalize_optional_text(os.getenv("BR_STUDIO_RUNTIME_LIVE_CHECK_ENABLED"))
    return bool(value and value.lower() in {"1", "true", "yes", "on"})


def _default_studio_runtime_namespace() -> str:
    return (
        _normalize_optional_text(os.getenv("BR_STUDIO_RUNTIME_NAMESPACE"))
        or _normalize_optional_text(os.getenv("POD_NAMESPACE"))
        or "brain-researcher-core"
    )


def _default_studio_jupyter_base_url_template() -> str | None:
    return _normalize_optional_text(os.getenv("BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE"))


def _studio_prefers_local_backend() -> bool:
    return os.getenv("BR_DEV_MODE", "").lower() in {"1", "true", "yes", "on"}


def _default_studio_jupyter_base_url(workspace_base_url: str) -> str | None:
    explicit = _normalize_optional_text(
        os.getenv("BR_STUDIO_JUPYTER_BASE_URL") or os.getenv("BR_JUPYTER_BASE_URL")
    )
    if explicit:
        return explicit
    if (
        _studio_prefers_local_backend()
        and not _default_studio_jupyter_base_url_template()
    ):
        return None
    return _normalize_optional_text(
        os.getenv("BR_PUBLIC_WORKSPACE_URL") or workspace_base_url
    )


def _default_studio_jupyter_token() -> str | None:
    return _normalize_optional_text(
        os.getenv("BR_STUDIO_JUPYTER_TOKEN") or os.getenv("BR_JUPYTER_TOKEN")
    )


def _default_studio_jupyter_kernel_name() -> str:
    return (
        _normalize_optional_text(os.getenv("BR_STUDIO_JUPYTER_KERNEL_NAME"))
        or "python3"
    )


def _path_is_writable_or_creatable(path: Path) -> bool:
    try:
        candidate = path.expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / f".br_write_probe_{secrets.token_hex(4)}"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _default_local_studio_workdir_root() -> str:
    override = _normalize_optional_text(os.getenv("BR_STUDIO_LOCAL_WORKDIR_ROOT"))
    if override:
        return override.rstrip("/")
    return str(Path(resolve_state_db_path()).resolve().parent / "studio-workspaces")


def _default_studio_workdir_root() -> str:
    configured = _normalize_optional_text(os.getenv("BR_STUDIO_JUPYTER_WORKDIR_ROOT"))
    if configured:
        return configured.rstrip("/")
    default_root = Path("/home/jovyan/work/projects")
    if _path_is_writable_or_creatable(default_root):
        return default_root.as_posix().rstrip("/")
    fallback_root = Path(_default_local_studio_workdir_root())
    _path_is_writable_or_creatable(fallback_root)
    return fallback_root.as_posix().rstrip("/")


def _default_marimo_workdir_root() -> str:
    configured = _normalize_optional_text(os.getenv("BR_STUDIO_MARIMO_WORKDIR_ROOT"))
    if configured:
        return configured.rstrip("/")
    default_root = Path("/home/br_user/work/projects")
    if _path_is_writable_or_creatable(default_root):
        return default_root.as_posix().rstrip("/")
    fallback_root = Path(_default_local_studio_workdir_root())
    _path_is_writable_or_creatable(fallback_root)
    return fallback_root.as_posix().rstrip("/")


def _default_studio_db_path() -> Path:
    override = _normalize_optional_text(os.getenv("BR_STUDIO_SESSION_DB"))
    return Path(override or resolve_state_db_path())


def _default_jupyter_base_url() -> str | None:
    return _normalize_optional_text(
        os.getenv("BR_STUDIO_JUPYTER_BASE_URL") or os.getenv("BR_JUPYTER_BASE_URL")
    )


def _default_jupyter_token() -> str | None:
    return _normalize_optional_text(
        os.getenv("BR_STUDIO_JUPYTER_TOKEN") or os.getenv("BR_JUPYTER_TOKEN")
    )


def _default_project_root_template() -> str:
    template = _normalize_optional_text(os.getenv("BR_STUDIO_PROJECT_ROOT_TEMPLATE"))
    return template or "projects/{project_id}"


def _default_jupyter_kernel_name() -> str:
    return (
        _normalize_optional_text(os.getenv("BR_STUDIO_JUPYTER_KERNEL_NAME"))
        or "python3"
    )


def resolve_runtime_absolute_working_directory(
    runtime: StudioRuntimeSession,
) -> str | None:
    configured = _normalize_optional_text(
        str(runtime.metadata.get("absolute_working_directory") or "")
    ) or _normalize_optional_text(runtime.working_directory)
    if configured:
        candidate = Path(configured)
        if _path_is_writable_or_creatable(candidate):
            return candidate.expanduser().resolve().as_posix()
    default_root = (
        _default_marimo_workdir_root()
        if runtime.kind == StudioRuntimeKind.MARIMO
        else _default_studio_workdir_root()
    )
    fallback_root = Path(default_root) / runtime.project_id
    if _path_is_writable_or_creatable(fallback_root):
        return fallback_root.expanduser().resolve().as_posix()
    if configured:
        return Path(configured).expanduser().as_posix()
    return None


def _normalize_runtime_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    normalized = normpath(value)
    if normalized in {"", ".", "/"}:
        return ""
    return normalized.lstrip("/")


def _runtime_pod_name(runtime_session_id: str) -> str:
    return f"br-marimo-{runtime_session_id}".replace("_", "-").lower()


class _TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def _build_runtime_template_context(
    *,
    owner_user_id: str,
    project_id: str,
    runtime_session_id: str,
    metadata: dict[str, Any],
) -> dict[str, str]:
    jupyter_user_name = str(
        metadata.get("jupyter_user_name")
        or metadata.get("jupyter_username")
        or owner_user_id
    ).strip()
    workspace_relative_root = str(metadata.get("workspace_relative_root") or "").strip()
    absolute_working_directory = str(
        metadata.get("absolute_working_directory") or ""
    ).strip()
    raw_values = {
        "owner_user_id": owner_user_id,
        "project_id": project_id,
        "runtime_session_id": runtime_session_id,
        "jupyter_user_name": jupyter_user_name,
        "workspace_relative_root": workspace_relative_root,
        "absolute_working_directory": absolute_working_directory,
    }
    context = _TemplateContext(
        {key: value for key, value in raw_values.items() if value}
    )
    for key, value in raw_values.items():
        if value:
            context[f"{key}_url"] = quote(value, safe="")
    return context


def _render_runtime_template(
    template: str | None,
    *,
    owner_user_id: str,
    project_id: str,
    runtime_session_id: str,
    metadata: dict[str, Any],
) -> str | None:
    normalized_template = _normalize_optional_text(template)
    if normalized_template is None:
        return None
    context = _build_runtime_template_context(
        owner_user_id=owner_user_id,
        project_id=project_id,
        runtime_session_id=runtime_session_id,
        metadata=metadata,
    )
    try:
        rendered = normalized_template.format_map(context)
    except Exception:
        return normalized_template
    return _normalize_optional_text(rendered)


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _deserialize_datetime(value: str | None) -> datetime:
    if not value:
        return _utc_now()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class StudioSessionStatus(str, Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    BUSY = "busy"
    IDLE = "idle"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    EXPIRED = "expired"


class StudioRuntimeProfile(str, Enum):
    STANDARD = "standard"
    HIGH_MEM = "high_mem"
    GPU = "gpu"


class StudioRuntimeKind(str, Enum):
    JUPYTER = "jupyter"
    MARIMO = "marimo"


_ATTACHABLE_SESSION_STATUSES = {
    StudioSessionStatus.READY,
    StudioSessionStatus.BUSY,
    StudioSessionStatus.IDLE,
    StudioSessionStatus.DEGRADED,
}

# Runtimes eligible for REUSE on attach. Includes PROVISIONING so a still-coming-up
# runtime is reused (the handoff polls until ready) instead of minting a duplicate
# pod. Session READY-promotion still uses the stricter _ATTACHABLE_SESSION_STATUSES,
# so a reused provisioning session correctly stays "provisioning" until it is ready.
_REUSABLE_RUNTIME_STATUSES = _ATTACHABLE_SESSION_STATUSES | {
    StudioSessionStatus.PROVISIONING,
}


class StudioSession(BaseModel):
    id: str = Field(..., pattern=r"^studio_[A-Za-z0-9]+$")
    project_id: str = Field(..., min_length=1, max_length=200)
    owner_user_id: str = Field(..., min_length=1, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    runtime_profile_id: StudioRuntimeProfile = StudioRuntimeProfile.STANDARD
    runtime_session_id: str = Field(..., pattern=r"^rt_[A-Za-z0-9]+$")
    assistant_session_id: str = Field(..., pattern=r"^ast_[A-Za-z0-9]+$")
    status: StudioSessionStatus = StudioSessionStatus.READY
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_activity_at: datetime = Field(default_factory=_utc_now)


class StudioRuntimeSession(BaseModel):
    id: str = Field(..., pattern=r"^rt_[A-Za-z0-9]+$")
    project_id: str = Field(..., min_length=1, max_length=200)
    owner_user_id: str = Field(..., min_length=1, max_length=200)
    runtime_profile_id: StudioRuntimeProfile = StudioRuntimeProfile.STANDARD
    kind: StudioRuntimeKind = StudioRuntimeKind.JUPYTER
    status: StudioSessionStatus = StudioSessionStatus.READY
    jupyter_base_url: str | None = None
    jupyter_token: str | None = None
    jupyter_session_id: str | None = None
    jupyter_kernel_id: str | None = None
    jupyter_kernel_name: str = Field(default="python3", min_length=1, max_length=100)
    marimo_base_url: str | None = None
    marimo_port: int = 2718
    working_directory: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_activity_at: datetime = Field(default_factory=_utc_now)


class CreateStudioSessionRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    runtime_profile_id: StudioRuntimeProfile = StudioRuntimeProfile.STANDARD
    runtime_kind: StudioRuntimeKind = StudioRuntimeKind.JUPYTER
    attach_if_exists: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class StudioSessionActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class WorkspaceHandoffRequest(BaseModel):
    runtime_profile_id: StudioRuntimeProfile | None = None
    target_path: str | None = Field(default=None, max_length=2000)
    notebook_path: str | None = Field(default=None, max_length=2000)
    open_artifact_id: str | None = Field(default=None, max_length=200)
    initial_focus: str | None = Field(default=None, max_length=100)
    materialize_notebook_if_needed: bool = False
    open_clean_workspace: bool = False


class WorkspaceLaunchMode(str, Enum):
    REUSE_ACTIVE_RUNTIME = "reuse_active_runtime"
    PROVISION_NEW_RUNTIME = "provision_new_runtime"


class WorkspaceHandoff(BaseModel):
    project_id: str
    runtime_session_id: str | None = None
    runtime_profile_id: StudioRuntimeProfile
    launch_mode: WorkspaceLaunchMode
    workspace_url: str
    target_path: str | None = None
    notebook_path: str | None = None
    open_artifact_id: str | None = None
    initial_focus: str | None = None
    materialize_notebook_if_needed: bool = False


class HubWorkspaceHandoffRequest(WorkspaceHandoffRequest):
    """Launch request for the hosted Marimo /hub gateway."""


class HubWorkspaceHandoff(WorkspaceHandoff):
    session_id: str = Field(..., pattern=r"^studio_[A-Za-z0-9]+$")
    runtime_kind: StudioRuntimeKind = StudioRuntimeKind.MARIMO
    runtime_status: StudioSessionStatus
    hub_base_url: str
    runtime_target_url: str | None = None
    runtime_websocket_url: str | None = None
    runtime_connection_mode: str | None = None
    runtime_target_ready: bool | None = None
    runtime_target_reason: str | None = None


class StudioSessionRuntime:
    """SQLite-backed Studio session facade for the hosted web control plane."""

    def __init__(
        self,
        *,
        workspace_base_url: str | None = None,
        db_path: str | Path | None = None,
        marimo_runtime_provisioner: MarimoRuntimeProvisioner | None = None,
    ) -> None:
        self._workspace_base_url = (
            workspace_base_url or _default_workspace_url()
        ).rstrip("/")
        self._db_path = Path(db_path or _default_studio_db_path())
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = int(os.getenv("BR_SQLITE_BUSY_TIMEOUT_MS", "5000"))
        self._runtime_live_check_enabled = _studio_runtime_live_check_enabled()
        self._runtime_namespace = _default_studio_runtime_namespace()
        self._runtime_core_api: Any | None = None
        self._runtime_api_exception_type: type[Exception] = Exception
        self._runtime_client_ready: bool | None = None
        self._lock = threading.Lock()
        # Dedicated thread pool for the @_offloaded methods. The bodies block on
        # self._lock inside their worker thread; running them on a DEDICATED pool
        # (not the shared asyncio.to_thread default executor) keeps a create
        # burst's lock-waiters from head-of-line-blocking unrelated offloaded
        # work (analysis bundle saves, tool execution, worker run_in_executor).
        try:
            _executor_workers = int(
                os.getenv("BR_STUDIO_RUNTIME_EXECUTOR_WORKERS", "16")
            )
        except (TypeError, ValueError):
            _executor_workers = 16
        self._executor = ThreadPoolExecutor(
            max_workers=max(2, _executor_workers),
            thread_name_prefix="studio-runtime",
        )
        self._marimo_runtime_provisioner = (
            marimo_runtime_provisioner or build_marimo_runtime_provisioner_from_env()
        )

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
            CREATE TABLE IF NOT EXISTS studio_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                runtime_profile_id TEXT NOT NULL,
                runtime_session_id TEXT NOT NULL,
                assistant_session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_sessions_owner_project_profile_status_updated "
            "ON studio_sessions(owner_user_id, project_id, runtime_profile_id, status, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_sessions_owner_updated "
            "ON studio_sessions(owner_user_id, updated_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS studio_runtime_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                runtime_profile_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                jupyter_base_url TEXT,
                jupyter_token TEXT,
                jupyter_session_id TEXT,
                jupyter_kernel_id TEXT,
                jupyter_kernel_name TEXT NOT NULL,
                marimo_base_url TEXT,
                marimo_port INTEGER NOT NULL DEFAULT 2718,
                working_directory TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_runtime_sessions_owner_project_profile_status_updated "
            "ON studio_runtime_sessions(owner_user_id, project_id, runtime_profile_id, status, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_runtime_sessions_owner_updated "
            "ON studio_runtime_sessions(owner_user_id, updated_at DESC)"
        )
        self._ensure_runtime_session_columns(conn)

    def _ensure_runtime_session_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(studio_runtime_sessions)").fetchall()
        existing: set[str] = {
            str(row["name"]) if isinstance(row, sqlite3.Row) else str(row[1])
            for row in columns
        }
        required = {
            "marimo_base_url": "marimo_base_url TEXT",
            "marimo_port": "marimo_port INTEGER NOT NULL DEFAULT 2718",
        }
        for name, definition in required.items():
            if name in existing:
                continue
            conn.execute(f"ALTER TABLE studio_runtime_sessions ADD COLUMN {definition}")
        conn.commit()

    def _row_to_session(self, row: sqlite3.Row) -> StudioSession:
        return StudioSession.model_validate(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "owner_user_id": row["owner_user_id"],
                "display_name": row["display_name"],
                "runtime_profile_id": row["runtime_profile_id"],
                "runtime_session_id": row["runtime_session_id"],
                "assistant_session_id": row["assistant_session_id"],
                "status": row["status"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_activity_at": row["last_activity_at"],
            }
        )

    def _session_row_payload(self, session: StudioSession) -> dict[str, Any]:
        return {
            "id": session.id,
            "project_id": session.project_id,
            "owner_user_id": session.owner_user_id,
            "display_name": session.display_name,
            "runtime_profile_id": session.runtime_profile_id.value,
            "runtime_session_id": session.runtime_session_id,
            "assistant_session_id": session.assistant_session_id,
            "status": session.status.value,
            "metadata_json": json.dumps(
                session.metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "created_at": _serialize_datetime(session.created_at),
            "updated_at": _serialize_datetime(session.updated_at),
            "last_activity_at": _serialize_datetime(session.last_activity_at),
        }

    def _row_to_runtime_session(self, row: sqlite3.Row) -> StudioRuntimeSession:
        return StudioRuntimeSession.model_validate(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "owner_user_id": row["owner_user_id"],
                "runtime_profile_id": row["runtime_profile_id"],
                "kind": row["kind"],
                "status": row["status"],
                "jupyter_base_url": row["jupyter_base_url"],
                "jupyter_token": row["jupyter_token"],
                "jupyter_session_id": row["jupyter_session_id"],
                "jupyter_kernel_id": row["jupyter_kernel_id"],
                "jupyter_kernel_name": row["jupyter_kernel_name"],
                "marimo_base_url": row["marimo_base_url"],
                "marimo_port": row["marimo_port"],
                "working_directory": row["working_directory"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_activity_at": row["last_activity_at"],
            }
        )

    def _runtime_row_payload(self, runtime: StudioRuntimeSession) -> dict[str, Any]:
        return {
            "id": runtime.id,
            "project_id": runtime.project_id,
            "owner_user_id": runtime.owner_user_id,
            "runtime_profile_id": runtime.runtime_profile_id.value,
            "kind": runtime.kind.value,
            "status": runtime.status.value,
            "jupyter_base_url": runtime.jupyter_base_url,
            "jupyter_token": runtime.jupyter_token,
            "jupyter_session_id": runtime.jupyter_session_id,
            "jupyter_kernel_id": runtime.jupyter_kernel_id,
            "jupyter_kernel_name": runtime.jupyter_kernel_name,
            "marimo_base_url": runtime.marimo_base_url,
            "marimo_port": runtime.marimo_port,
            "working_directory": runtime.working_directory,
            "metadata_json": json.dumps(
                runtime.metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "created_at": _serialize_datetime(runtime.created_at),
            "updated_at": _serialize_datetime(runtime.updated_at),
            "last_activity_at": _serialize_datetime(runtime.last_activity_at),
        }

    def _upsert_session_locked(
        self, conn: sqlite3.Connection, session: StudioSession
    ) -> None:
        payload = self._session_row_payload(session)
        conn.execute(
            """
            INSERT INTO studio_sessions (
                id,
                project_id,
                owner_user_id,
                display_name,
                runtime_profile_id,
                runtime_session_id,
                assistant_session_id,
                status,
                metadata_json,
                created_at,
                updated_at,
                last_activity_at
            ) VALUES (
                :id,
                :project_id,
                :owner_user_id,
                :display_name,
                :runtime_profile_id,
                :runtime_session_id,
                :assistant_session_id,
                :status,
                :metadata_json,
                :created_at,
                :updated_at,
                :last_activity_at
            )
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                owner_user_id = excluded.owner_user_id,
                display_name = excluded.display_name,
                runtime_profile_id = excluded.runtime_profile_id,
                runtime_session_id = excluded.runtime_session_id,
                assistant_session_id = excluded.assistant_session_id,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_activity_at = excluded.last_activity_at
            """,
            payload,
        )

    def _upsert_runtime_session_locked(
        self, conn: sqlite3.Connection, runtime: StudioRuntimeSession
    ) -> None:
        payload = self._runtime_row_payload(runtime)
        conn.execute(
            """
            INSERT INTO studio_runtime_sessions (
                id,
                project_id,
                owner_user_id,
                runtime_profile_id,
                kind,
                status,
                jupyter_base_url,
                jupyter_token,
                jupyter_session_id,
                jupyter_kernel_id,
                jupyter_kernel_name,
                marimo_base_url,
                marimo_port,
                working_directory,
                metadata_json,
                created_at,
                updated_at,
                last_activity_at
            ) VALUES (
                :id,
                :project_id,
                :owner_user_id,
                :runtime_profile_id,
                :kind,
                :status,
                :jupyter_base_url,
                :jupyter_token,
                :jupyter_session_id,
                :jupyter_kernel_id,
                :jupyter_kernel_name,
                :marimo_base_url,
                :marimo_port,
                :working_directory,
                :metadata_json,
                :created_at,
                :updated_at,
                :last_activity_at
            )
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                owner_user_id = excluded.owner_user_id,
                runtime_profile_id = excluded.runtime_profile_id,
                kind = excluded.kind,
                status = excluded.status,
                jupyter_base_url = excluded.jupyter_base_url,
                jupyter_token = excluded.jupyter_token,
                jupyter_session_id = excluded.jupyter_session_id,
                jupyter_kernel_id = excluded.jupyter_kernel_id,
                jupyter_kernel_name = excluded.jupyter_kernel_name,
                marimo_base_url = excluded.marimo_base_url,
                marimo_port = excluded.marimo_port,
                working_directory = excluded.working_directory,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_activity_at = excluded.last_activity_at
            """,
            payload,
        )

    @_offloaded
    def create_or_attach_session(
        self,
        owner_user_id: str,
        request: CreateStudioSessionRequest,
    ) -> StudioSession:
        with self._lock:
            with self._connect() as conn:
                if request.attach_if_exists:
                    existing_binding = self._find_attachable_locked(
                        conn,
                        owner_user_id=owner_user_id,
                        project_id=request.project_id,
                        runtime_profile_id=request.runtime_profile_id,
                        runtime_kind=request.runtime_kind,
                    )
                    if existing_binding is not None:
                        existing, runtime = existing_binding
                        runtime = runtime.model_copy(
                            update={
                                "last_activity_at": _utc_now(),
                                "updated_at": _utc_now(),
                            }
                        )
                        self._upsert_runtime_session_locked(conn, runtime)
                        if runtime.kind == StudioRuntimeKind.MARIMO:
                            runtime = self._reconcile_marimo_runtime_locked(
                                conn, runtime
                            )
                        touched = self._touch_locked(
                            conn,
                            existing.model_copy(
                                update={
                                    "runtime_session_id": runtime.id,
                                    "status": (
                                        StudioSessionStatus.READY
                                        if runtime.status
                                        in _ATTACHABLE_SESSION_STATUSES
                                        else runtime.status
                                    ),
                                    "metadata": self._merge_runtime_metadata(
                                        existing.metadata,
                                        runtime,
                                    ),
                                }
                            ),
                            metadata=request.metadata,
                        )
                        self._upsert_session_locked(conn, touched)
                        return touched

                now = _utc_now()
                runtime = self._provision_runtime_session_locked(
                    conn,
                    owner_user_id=owner_user_id,
                    request=request,
                )
                session = StudioSession(
                    id=f"studio_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}",
                    project_id=request.project_id,
                    owner_user_id=owner_user_id,
                    display_name=request.display_name,
                    runtime_profile_id=request.runtime_profile_id,
                    runtime_session_id=runtime.id,
                    assistant_session_id=f"ast_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}",
                    status=(
                        StudioSessionStatus.READY
                        if runtime.status in _ATTACHABLE_SESSION_STATUSES
                        else runtime.status
                    ),
                    metadata=self._merge_runtime_metadata(
                        dict(request.metadata or {}),
                        runtime,
                    ),
                    created_at=now,
                    updated_at=now,
                    last_activity_at=now,
                )
                self._upsert_session_locked(conn, session)
                return session

    @_offloaded
    def list_sessions(
        self,
        *,
        owner_user_id: str,
        project_id: str | None = None,
        runtime_profile_id: StudioRuntimeProfile | None = None,
        status: StudioSessionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StudioSession]:
        # Lock-free read: SQLite WAL gives readers a consistent snapshot even
        # while a writer holds the runtime lock, so reads stay responsive under
        # provisioning bursts instead of queuing behind writes.
        with self._connect() as conn:
            clauses = ["owner_user_id = ?"]
            params: list[Any] = [owner_user_id]
            if project_id is not None:
                clauses.append("project_id = ?")
                params.append(project_id)
            if runtime_profile_id is not None:
                clauses.append("runtime_profile_id = ?")
                params.append(runtime_profile_id.value)
            if status is not None:
                clauses.append("status = ?")
                params.append(status.value)
            params.extend([limit, offset])
            query = (
                "SELECT * FROM studio_sessions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?"
            )
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_session(row) for row in rows]

    @_offloaded
    def get_session(self, session_id: str) -> StudioSession | None:
        # Lock-free read (WAL snapshot); see list_sessions.
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM studio_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return self._row_to_session(row) if row is not None else None

    @_offloaded
    def get_runtime_session(
        self, runtime_session_id: str
    ) -> StudioRuntimeSession | None:
        # Lock-free read (WAL snapshot); see list_sessions.
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM studio_runtime_sessions WHERE id = ?",
                (runtime_session_id,),
            ).fetchone()
            return self._row_to_runtime_session(row) if row is not None else None

    @_offloaded
    def get_runtime_token(self, br_session_id: str) -> str | None:
        """Return the per-pod marimo runtime token for a BR session.

        Used server-side (e.g. the ``Marimo-Server-Token`` header for cell
        injection). The only browser-facing exposure is the one-time
        ``access_token`` query param on the iframe handoff URL built in
        ``build_hub_handoff`` (see ``_append_marimo_access_token``); the raw
        token must stay scrubbed from every other browser payload.
        """
        # Lock-free read (WAL snapshot); see list_sessions.
        with self._connect() as conn:
            session = self._get_session_locked(conn, br_session_id)
            if session is None:
                return None
            runtime = self._get_runtime_session_locked(conn, session.runtime_session_id)
            if runtime is None:
                return None
            token = runtime.metadata.get("marimo_runtime_token")
            if isinstance(token, str) and token.strip():
                return token.strip()
            return None

    @_offloaded
    def get_runtime_skew_token(self, br_session_id: str) -> str | None:
        """Return the per-pod marimo skew-protection token for a BR session.

        Sent server-side as the ``Marimo-Server-Token`` header for cell
        injection. Unlike the auth token this value is client-visible by design
        (marimo serves it to the frontend), so it is safe to expose but useless
        without also passing the auth ``access_token``.
        """
        # Lock-free read (WAL snapshot); see list_sessions.
        with self._connect() as conn:
            session = self._get_session_locked(conn, br_session_id)
            if session is None:
                return None
            runtime = self._get_runtime_session_locked(conn, session.runtime_session_id)
            if runtime is None:
                return None
            token = runtime.metadata.get("marimo_skew_token")
            if isinstance(token, str) and token.strip():
                return token.strip()
            return None

    @_offloaded
    def get_marimo_runtime_target(
        self, br_session_id: str
    ) -> tuple[StudioRuntimeSession, MarimoRuntimeTarget] | None:
        """Return runtime session + marimo target for a BR session, or None."""
        with self._lock:
            with self._connect() as conn:
                session = self._get_session_locked(conn, br_session_id)
                if session is None:
                    return None
                runtime = self._get_runtime_session_locked(
                    conn, session.runtime_session_id
                )
                if runtime is None or runtime.kind != StudioRuntimeKind.MARIMO:
                    return None
                target = self._marimo_runtime_target_from_runtime(runtime)
                if target is None:
                    return None
                # The stored target.ready reflects the pod phase at the last
                # reconcile; a pod that was Pending then became Running would still
                # read not-ready. Re-reconcile (re-reads the pod) so callers such as
                # server-side cell injection stop seeing a stale "pending" 503 once
                # the runtime is actually up.
                if not target.ready and runtime.status not in {
                    StudioSessionStatus.STOPPING,
                    StudioSessionStatus.STOPPED,
                    StudioSessionStatus.FAILED,
                    StudioSessionStatus.EXPIRED,
                }:
                    try:
                        runtime = self._reconcile_marimo_runtime_locked(conn, runtime)
                        refreshed = self._marimo_runtime_target_from_runtime(runtime)
                        if refreshed is not None:
                            target = refreshed
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning(
                            "Marimo runtime readiness refresh failed for %s: %s",
                            runtime.id,
                            exc,
                        )
                return runtime, target

    @_offloaded
    def update_runtime_session(
        self,
        runtime_session_id: str,
        *,
        status: StudioSessionStatus | None = None,
        jupyter_session_id: str | None = None,
        jupyter_kernel_id: str | None = None,
        working_directory: str | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> StudioRuntimeSession:
        with self._lock:
            with self._connect() as conn:
                runtime = self._get_runtime_session_locked(conn, runtime_session_id)
                if runtime is None:
                    raise KeyError(runtime_session_id)
                merged_metadata = dict(runtime.metadata)
                if metadata_updates:
                    merged_metadata.update(metadata_updates)
                now = _utc_now()
                updated = runtime.model_copy(
                    update={
                        "status": status or runtime.status,
                        "jupyter_session_id": (
                            jupyter_session_id
                            if jupyter_session_id is not None
                            else runtime.jupyter_session_id
                        ),
                        "jupyter_kernel_id": (
                            jupyter_kernel_id
                            if jupyter_kernel_id is not None
                            else runtime.jupyter_kernel_id
                        ),
                        "working_directory": (
                            working_directory
                            if working_directory is not None
                            else runtime.working_directory
                        ),
                        "metadata": merged_metadata,
                        "updated_at": now,
                        "last_activity_at": now,
                    }
                )
                self._upsert_runtime_session_locked(conn, updated)
                return updated

    @_offloaded
    def perform_action(
        self,
        owner_user_id: str,
        session_id: str,
        action: str,
        request: StudioSessionActionRequest | None = None,
    ) -> dict[str, Any]:
        payload = request or StudioSessionActionRequest()
        with self._lock:
            with self._connect() as conn:
                session = self._get_session_locked(conn, session_id)
                if session is None or session.owner_user_id != owner_user_id:
                    raise KeyError(session_id)
                runtime = self._get_runtime_session_locked(
                    conn, session.runtime_session_id
                )

                if action == "touch":
                    updated = self._touch_locked(conn, session)
                elif action == "close":
                    now = _utc_now()
                    if runtime is not None and runtime.kind == StudioRuntimeKind.MARIMO:
                        self._destroy_marimo_runtime_target_best_effort(runtime)
                        stopped_runtime = runtime.model_copy(
                            update={
                                "status": StudioSessionStatus.STOPPED,
                                "updated_at": now,
                                "last_activity_at": now,
                            }
                        )
                        self._upsert_runtime_session_locked(conn, stopped_runtime)
                    updated = session.model_copy(
                        update={
                            "status": StudioSessionStatus.STOPPED,
                            "updated_at": now,
                            "last_activity_at": now,
                            "metadata": {
                                **dict(session.metadata),
                                "close_reason": payload.reason,
                            },
                        }
                    )
                else:
                    raise ValueError(action)

                self._upsert_session_locked(conn, updated)
                return {"action": action, "session": updated.model_dump(mode="json")}

    @_offloaded
    def build_workspace_handoff(
        self,
        owner_user_id: str,
        session_id: str,
        request: WorkspaceHandoffRequest,
    ) -> WorkspaceHandoff:
        with self._lock:
            with self._connect() as conn:
                session = self._get_session_locked(conn, session_id)
                if session is None or session.owner_user_id != owner_user_id:
                    raise KeyError(session_id)
                runtime = self._resolve_session_runtime_locked(conn, session)
                if runtime is None:
                    refreshed_session = self._get_session_locked(conn, session_id)
                    if refreshed_session is not None:
                        session = refreshed_session

        runtime_profile_id = request.runtime_profile_id or session.runtime_profile_id
        launch_mode = (
            WorkspaceLaunchMode.PROVISION_NEW_RUNTIME
            if request.open_clean_workspace
            or runtime is None
            or runtime.status not in _ATTACHABLE_SESSION_STATUSES
            else WorkspaceLaunchMode.REUSE_ACTIVE_RUNTIME
        )
        metadata = dict(runtime.metadata if runtime is not None else session.metadata)
        default_target_path = _normalize_optional_text(
            str(metadata.get("taskbeacon_target_path") or "")
        )
        requested_target_path = request.target_path or (
            default_target_path if not request.notebook_path else None
        )
        resolved_notebook_path = (
            self._resolve_workspace_tree_path(
                request.notebook_path,
                runtime,
                project_id=session.project_id,
            )
            if request.notebook_path
            else None
        )
        resolved_target_path = (
            self._resolve_workspace_tree_path(
                requested_target_path,
                runtime,
                project_id=session.project_id,
            )
            if requested_target_path
            else None
        )
        workspace_base_url = self._resolve_workspace_launch_base_url(
            session=session,
            runtime=runtime,
        )
        workspace_url = self._build_workspace_url(
            workspace_base_url=workspace_base_url,
            notebook_path=resolved_notebook_path,
            target_path=resolved_target_path,
        )
        return WorkspaceHandoff(
            project_id=session.project_id,
            runtime_session_id=(
                None
                if launch_mode == WorkspaceLaunchMode.PROVISION_NEW_RUNTIME
                else session.runtime_session_id
            ),
            runtime_profile_id=runtime_profile_id,
            launch_mode=launch_mode,
            workspace_url=workspace_url,
            target_path=resolved_target_path,
            notebook_path=resolved_notebook_path,
            open_artifact_id=request.open_artifact_id,
            initial_focus=request.initial_focus,
            materialize_notebook_if_needed=request.materialize_notebook_if_needed,
        )

    @_offloaded
    def build_hub_handoff(
        self,
        owner_user_id: str,
        session_id: str,
        request: HubWorkspaceHandoffRequest,
    ) -> HubWorkspaceHandoff:
        with self._lock:
            with self._connect() as conn:
                session = self._get_session_locked(conn, session_id)
                if session is None or session.owner_user_id != owner_user_id:
                    raise KeyError(session_id)
                runtime = self._get_runtime_session_locked(
                    conn, session.runtime_session_id
                )
                if runtime is None:
                    self._mark_session_stopped_locked(
                        conn,
                        session,
                        reason=CleanupReason.RUNTIME_RECORD_MISSING.value,
                    )
                elif runtime.kind != StudioRuntimeKind.MARIMO:
                    raise KeyError(session_id)
                elif runtime.status in {
                    StudioSessionStatus.STOPPING,
                    StudioSessionStatus.STOPPED,
                    StudioSessionStatus.FAILED,
                    StudioSessionStatus.EXPIRED,
                }:
                    runtime = None
                elif runtime.status in _ATTACHABLE_SESSION_STATUSES:
                    live = self._runtime_backing_pod_is_live(runtime)
                    if live is False:
                        self._mark_runtime_and_bound_sessions_stopped_locked(
                            conn,
                            runtime,
                            reason=CleanupReason.POD_GONE.value,
                        )
                        runtime = None
                    else:
                        runtime = self._reconcile_marimo_runtime_locked(conn, runtime)
                        session = self._touch_locked(
                            conn,
                            session.model_copy(
                                update={
                                    "runtime_session_id": runtime.id,
                                    "status": self._session_status_for_runtime(runtime),
                                    "metadata": self._merge_runtime_metadata(
                                        session.metadata,
                                        runtime,
                                    ),
                                }
                            ),
                        )
                else:
                    runtime = self._reconcile_marimo_runtime_locked(conn, runtime)
                    session = self._touch_locked(
                        conn,
                        session.model_copy(
                            update={
                                "runtime_session_id": runtime.id,
                                "status": self._session_status_for_runtime(runtime),
                                "metadata": self._merge_runtime_metadata(
                                    session.metadata,
                                    runtime,
                                ),
                            }
                        ),
                    )

                refreshed_session = self._get_session_locked(conn, session_id)
                if refreshed_session is not None:
                    session = refreshed_session

        runtime_profile_id = request.runtime_profile_id or session.runtime_profile_id
        launch_mode = (
            WorkspaceLaunchMode.PROVISION_NEW_RUNTIME
            if request.open_clean_workspace
            or runtime is None
            or runtime.status not in _ATTACHABLE_SESSION_STATUSES
            else WorkspaceLaunchMode.REUSE_ACTIVE_RUNTIME
        )
        metadata = dict(runtime.metadata if runtime is not None else session.metadata)
        default_target_path = _normalize_optional_text(
            str(metadata.get("taskbeacon_target_path") or "")
        )
        requested_target_path = request.target_path or (
            default_target_path if not request.notebook_path else None
        )
        resolved_notebook_path = (
            self._resolve_workspace_tree_path(
                request.notebook_path,
                runtime,
                project_id=session.project_id,
            )
            if request.notebook_path
            else None
        )
        resolved_target_path = (
            self._resolve_workspace_tree_path(
                requested_target_path,
                runtime,
                project_id=session.project_id,
            )
            if requested_target_path
            else None
        )
        hub_base_url = self._resolve_hub_launch_base_url(
            session=session, runtime=runtime
        )
        workspace_url = self._build_hub_workspace_url(
            hub_base_url=hub_base_url,
            session_id=session.id,
            notebook_path=resolved_notebook_path,
            target_path=resolved_target_path,
            open_artifact_id=request.open_artifact_id,
            initial_focus=request.initial_focus,
            materialize_notebook_if_needed=request.materialize_notebook_if_needed,
            open_clean_workspace=request.open_clean_workspace,
        )
        target = (
            self._marimo_runtime_target_from_runtime(runtime)
            if runtime is not None
            else None
        )
        runtime_access_token = (
            _normalize_optional_text(
                str((runtime.metadata or {}).get("marimo_runtime_token") or "")
            )
            if runtime is not None
            else None
        )
        runtime_target_url = (
            _append_marimo_access_token(target.public_url, runtime_access_token)
            if target is not None
            else None
        )
        return HubWorkspaceHandoff(
            session_id=session.id,
            project_id=session.project_id,
            runtime_session_id=(
                None
                if launch_mode == WorkspaceLaunchMode.PROVISION_NEW_RUNTIME
                else session.runtime_session_id
            ),
            runtime_profile_id=runtime_profile_id,
            runtime_kind=(
                runtime.kind if runtime is not None else StudioRuntimeKind.MARIMO
            ),
            runtime_status=(
                runtime.status if runtime is not None else StudioSessionStatus.STOPPED
            ),
            hub_base_url=hub_base_url,
            launch_mode=launch_mode,
            workspace_url=workspace_url,
            target_path=resolved_target_path,
            notebook_path=resolved_notebook_path,
            open_artifact_id=request.open_artifact_id,
            initial_focus=request.initial_focus,
            materialize_notebook_if_needed=request.materialize_notebook_if_needed,
            runtime_target_url=runtime_target_url,
            runtime_websocket_url=target.websocket_url if target is not None else None,
            runtime_connection_mode=(
                target.connection_mode if target is not None else None
            ),
            runtime_target_ready=target.ready if target is not None else None,
            runtime_target_reason=target.status_reason if target is not None else None,
        )

    def _find_attachable_locked(
        self,
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        project_id: str,
        runtime_profile_id: StudioRuntimeProfile,
        runtime_kind: StudioRuntimeKind,
    ) -> tuple[StudioSession, StudioRuntimeSession] | None:
        rows = conn.execute(
            """
            SELECT s.* FROM studio_sessions AS s
            JOIN studio_runtime_sessions AS r ON s.runtime_session_id = r.id
            WHERE s.owner_user_id = ?
              AND s.project_id = ?
              AND s.runtime_profile_id = ?
              AND r.kind = ?
              AND s.status IN (?, ?, ?, ?, ?)
            ORDER BY s.updated_at DESC, s.created_at DESC
            """,
            (
                owner_user_id,
                project_id,
                runtime_profile_id.value,
                runtime_kind.value,
                StudioSessionStatus.READY.value,
                StudioSessionStatus.BUSY.value,
                StudioSessionStatus.IDLE.value,
                StudioSessionStatus.DEGRADED.value,
                # Reuse a still-provisioning runtime instead of minting a new pod
                # (the handoff polls until ready); avoids runtime churn on attach.
                StudioSessionStatus.PROVISIONING.value,
            ),
        ).fetchall()
        for row in rows:
            session = self._row_to_session(row)
            runtime = self._resolve_session_runtime_locked(conn, session)
            if runtime is not None and runtime.kind == runtime_kind:
                return session, runtime
        return None

    def _find_attachable_runtime_locked(
        self,
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        project_id: str,
        runtime_profile_id: StudioRuntimeProfile,
        runtime_kind: StudioRuntimeKind,
    ) -> StudioRuntimeSession | None:
        rows = conn.execute(
            """
            SELECT * FROM studio_runtime_sessions
            WHERE owner_user_id = ?
              AND project_id = ?
              AND runtime_profile_id = ?
              AND kind = ?
              AND status IN (?, ?, ?, ?, ?)
            ORDER BY updated_at DESC, created_at DESC
            """,
            (
                owner_user_id,
                project_id,
                runtime_profile_id.value,
                runtime_kind.value,
                StudioSessionStatus.READY.value,
                StudioSessionStatus.BUSY.value,
                StudioSessionStatus.IDLE.value,
                StudioSessionStatus.DEGRADED.value,
                # See _find_attachable_locked: reuse provisioning runtimes too.
                StudioSessionStatus.PROVISIONING.value,
            ),
        ).fetchall()
        for row in rows:
            runtime = self._resolve_attachable_runtime_locked(
                conn,
                self._row_to_runtime_session(row),
            )
            if runtime is not None and runtime.kind == runtime_kind:
                return runtime
        return None

    def _touch_locked(
        self,
        conn: sqlite3.Connection,
        session: StudioSession,
        metadata: dict[str, Any] | None = None,
    ) -> StudioSession:
        now = _utc_now()
        merged_metadata = dict(session.metadata)
        if metadata:
            merged_metadata.update(metadata)
        updated = session.model_copy(
            update={
                "updated_at": now,
                "last_activity_at": now,
                "metadata": merged_metadata,
            }
        )
        self._upsert_session_locked(conn, updated)
        return updated

    def _get_runtime_session_locked(
        self, conn: sqlite3.Connection, runtime_session_id: str
    ) -> StudioRuntimeSession | None:
        row = conn.execute(
            "SELECT * FROM studio_runtime_sessions WHERE id = ?",
            (runtime_session_id,),
        ).fetchone()
        return self._row_to_runtime_session(row) if row is not None else None

    @staticmethod
    def _session_status_for_runtime(
        runtime: StudioRuntimeSession,
    ) -> StudioSessionStatus:
        return (
            StudioSessionStatus.READY
            if runtime.status in _ATTACHABLE_SESSION_STATUSES
            else runtime.status
        )

    @staticmethod
    def _marimo_runtime_target_from_runtime(
        runtime: StudioRuntimeSession,
    ) -> MarimoRuntimeTarget | None:
        raw = runtime.metadata.get("marimo_runtime_target")
        if not isinstance(raw, dict):
            return None
        try:
            return MarimoRuntimeTarget.model_validate(raw)
        except Exception:
            return None

    def _marimo_runtime_spec(self, runtime: StudioRuntimeSession) -> MarimoRuntimeSpec:
        workspace_relative_root = _normalize_runtime_path(
            str(runtime.metadata.get("workspace_relative_root") or "")
        ) or _normalize_runtime_path(
            _default_project_root_template().format(project_id=runtime.project_id)
        )
        absolute_working_directory = (
            resolve_runtime_absolute_working_directory(runtime)
            or runtime.working_directory
            or workspace_relative_root
        )
        return MarimoRuntimeSpec(
            owner_user_id=runtime.owner_user_id,
            project_id=runtime.project_id,
            runtime_session_id=runtime.id,
            runtime_profile_id=runtime.runtime_profile_id.value,
            marimo_port=runtime.marimo_port,
            workspace_relative_root=workspace_relative_root,
            absolute_working_directory=absolute_working_directory,
            taskbeacon_repo=_normalize_optional_text(
                str(runtime.metadata.get("taskbeacon_repo") or "")
            ),
            taskbeacon_ref=_normalize_optional_text(
                str(runtime.metadata.get("taskbeacon_ref") or "")
            ),
            taskbeacon_target_path=_normalize_optional_text(
                str(runtime.metadata.get("taskbeacon_target_path") or "")
            ),
            skew_protection_token=_normalize_optional_text(
                str(runtime.metadata.get("marimo_skew_token") or "")
            ),
        )

    def _reconcile_marimo_runtime_locked(
        self,
        conn: sqlite3.Connection,
        runtime: StudioRuntimeSession,
    ) -> StudioRuntimeSession:
        if runtime.kind != StudioRuntimeKind.MARIMO:
            return runtime
        # Ensure a stable, per-pod skew-protection token exists before building the
        # spec so it is both injected into the pod env (pinning marimo's skew token)
        # and persisted for server-side cell injection. Distinct from the auth token
        # because marimo serves the skew token to the browser.
        if not _normalize_optional_text(
            str(runtime.metadata.get("marimo_skew_token") or "")
        ):
            runtime = runtime.model_copy(
                update={
                    "metadata": {
                        **runtime.metadata,
                        "marimo_skew_token": secrets.token_urlsafe(16),
                    }
                }
            )
        spec = self._marimo_runtime_spec(runtime)
        target = self._marimo_runtime_provisioner.ensure_target(spec)
        existing_token = _normalize_optional_text(
            str(runtime.metadata.get("marimo_runtime_token") or "")
        )
        runtime_token: str | None = existing_token
        try:
            runtime_token = self._marimo_runtime_provisioner.ensure_runtime_token(
                spec, target, existing_token=existing_token
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to ensure marimo runtime token for %s: %s", runtime.id, exc
            )
        metadata = dict(runtime.metadata)
        metadata["workspace_relative_root"] = spec.workspace_relative_root
        metadata["absolute_working_directory"] = spec.absolute_working_directory
        metadata["marimo_runtime_target"] = target.model_dump(mode="json")
        if runtime_token is not None:
            metadata["marimo_runtime_token"] = runtime_token
        status = runtime.status
        if runtime.status not in {
            StudioSessionStatus.STOPPING,
            StudioSessionStatus.STOPPED,
            StudioSessionStatus.FAILED,
            StudioSessionStatus.EXPIRED,
        }:
            status = (
                StudioSessionStatus.READY
                if target.ready
                else StudioSessionStatus.PROVISIONING
            )
        updated = runtime.model_copy(
            update={
                "status": status,
                "working_directory": spec.workspace_relative_root,
                "metadata": metadata,
                "updated_at": _utc_now(),
                "last_activity_at": _utc_now(),
            }
        )
        self._upsert_runtime_session_locked(conn, updated)
        return updated

    def _ensure_runtime_binding_locked(
        self,
        conn: sqlite3.Connection,
        session: StudioSession,
        *,
        request: CreateStudioSessionRequest,
    ) -> StudioRuntimeSession:
        existing = self._resolve_attachable_runtime_locked(
            conn,
            self._get_runtime_session_locked(conn, session.runtime_session_id),
            bound_session=session,
        )
        if existing is not None and existing.kind == request.runtime_kind:
            touched = existing.model_copy(
                update={
                    "last_activity_at": _utc_now(),
                    "updated_at": _utc_now(),
                }
            )
            self._upsert_runtime_session_locked(conn, touched)
            return (
                self._reconcile_marimo_runtime_locked(conn, touched)
                if touched.kind == StudioRuntimeKind.MARIMO
                else touched
            )
        attachable = self._find_attachable_runtime_locked(
            conn,
            owner_user_id=session.owner_user_id,
            project_id=session.project_id,
            runtime_profile_id=session.runtime_profile_id,
            runtime_kind=request.runtime_kind,
        )
        if attachable is not None:
            touched = attachable.model_copy(
                update={
                    "last_activity_at": _utc_now(),
                    "updated_at": _utc_now(),
                }
            )
            self._upsert_runtime_session_locked(conn, touched)
            return (
                self._reconcile_marimo_runtime_locked(conn, touched)
                if touched.kind == StudioRuntimeKind.MARIMO
                else touched
            )
        runtime = self._provision_runtime_session_locked(
            conn,
            owner_user_id=session.owner_user_id,
            request=request,
        )
        return runtime

    def _resolve_session_runtime_locked(
        self,
        conn: sqlite3.Connection,
        session: StudioSession,
    ) -> StudioRuntimeSession | None:
        runtime = self._get_runtime_session_locked(conn, session.runtime_session_id)
        if runtime is None:
            self._mark_session_stopped_locked(
                conn,
                session,
                reason=CleanupReason.RUNTIME_RECORD_MISSING.value,
            )
            return None
        return self._resolve_attachable_runtime_locked(
            conn,
            runtime,
            bound_session=session,
        )

    def _resolve_attachable_runtime_locked(
        self,
        conn: sqlite3.Connection,
        runtime: StudioRuntimeSession | None,
        *,
        bound_session: StudioSession | None = None,
    ) -> StudioRuntimeSession | None:
        if runtime is None:
            return None
        if runtime.status not in _REUSABLE_RUNTIME_STATUSES:
            return None
        live = self._runtime_backing_pod_is_live(runtime)
        if live is False:
            self._mark_runtime_and_bound_sessions_stopped_locked(
                conn,
                runtime,
                reason=CleanupReason.POD_GONE.value,
            )
            return None
        return runtime

    def _mark_session_stopped_locked(
        self,
        conn: sqlite3.Connection,
        session: StudioSession,
        *,
        reason: str,
    ) -> StudioSession:
        now = _utc_now()
        metadata = dict(session.metadata)
        metadata.update(
            {
                "cleanup_reason": reason,
                "cleanup_detected_at": _serialize_datetime(now),
                "cleanup_detected_by": "studio_session_runtime",
            }
        )
        updated = session.model_copy(
            update={
                "status": StudioSessionStatus.STOPPED,
                "metadata": metadata,
                "updated_at": now,
                "last_activity_at": now,
            }
        )
        self._upsert_session_locked(conn, updated)
        return updated

    def _sync_bound_sessions_locked(
        self,
        conn: sqlite3.Connection,
        runtime: StudioRuntimeSession,
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM studio_sessions WHERE runtime_session_id = ?",
            (runtime.id,),
        ).fetchall()
        for row in rows:
            session = self._row_to_session(row)
            updated = session.model_copy(
                update={
                    "status": self._session_status_for_runtime(runtime),
                    "metadata": self._merge_runtime_metadata(
                        dict(session.metadata),
                        runtime,
                    ),
                    "updated_at": _utc_now(),
                    "last_activity_at": _utc_now(),
                }
            )
            self._upsert_session_locked(conn, updated)

    def _destroy_marimo_runtime_target_best_effort(
        self,
        runtime: StudioRuntimeSession,
    ) -> None:
        if runtime.kind != StudioRuntimeKind.MARIMO:
            return
        target = self._marimo_runtime_target_from_runtime(runtime)
        if target is None:
            return
        try:
            self._marimo_runtime_provisioner.destroy_target(target)
        except Exception as exc:  # pragma: no cover - defensive logging only
            logger.warning(
                "Failed to destroy Marimo runtime target for %s: %s", runtime.id, exc
            )

    def _mark_runtime_and_bound_sessions_stopped_locked(
        self,
        conn: sqlite3.Connection,
        runtime: StudioRuntimeSession,
        *,
        reason: str,
    ) -> None:
        now = _utc_now()
        cleanup_metadata = {
            "cleanup_reason": reason,
            "cleanup_detected_at": _serialize_datetime(now),
            "cleanup_detected_by": "studio_session_runtime",
        }
        self._destroy_marimo_runtime_target_best_effort(runtime)
        stopped_runtime = runtime.model_copy(
            update={
                "status": StudioSessionStatus.STOPPED,
                "metadata": {
                    **dict(runtime.metadata),
                    **cleanup_metadata,
                },
                "updated_at": now,
                "last_activity_at": now,
            }
        )
        self._upsert_runtime_session_locked(conn, stopped_runtime)
        rows = conn.execute(
            "SELECT * FROM studio_sessions WHERE runtime_session_id = ?",
            (runtime.id,),
        ).fetchall()
        for row in rows:
            session = self._row_to_session(row)
            stopped_session = session.model_copy(
                update={
                    "status": StudioSessionStatus.STOPPED,
                    "metadata": self._merge_runtime_metadata(
                        {
                            **dict(session.metadata),
                            **cleanup_metadata,
                        },
                        stopped_runtime,
                    ),
                    "updated_at": now,
                    "last_activity_at": now,
                }
            )
            self._upsert_session_locked(conn, stopped_session)

    @_offloaded
    def reconcile_runtime_sessions_once(self) -> dict[str, int]:
        summary = {
            "scanned": 0,
            "refreshed": 0,
            "stopped": 0,
            "still_provisioning": 0,
        }
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM studio_runtime_sessions
                    WHERE kind = ?
                      AND status IN (?, ?, ?, ?, ?)
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (
                        StudioRuntimeKind.MARIMO.value,
                        StudioSessionStatus.PROVISIONING.value,
                        StudioSessionStatus.READY.value,
                        StudioSessionStatus.BUSY.value,
                        StudioSessionStatus.IDLE.value,
                        StudioSessionStatus.DEGRADED.value,
                    ),
                ).fetchall()
                for row in rows:
                    runtime = self._row_to_runtime_session(row)
                    summary["scanned"] += 1
                    if runtime.status in _ATTACHABLE_SESSION_STATUSES:
                        live = self._runtime_backing_pod_is_live(runtime)
                        if live is False:
                            self._mark_runtime_and_bound_sessions_stopped_locked(
                                conn,
                                runtime,
                                reason=CleanupReason.POD_GONE.value,
                            )
                            summary["stopped"] += 1
                            continue

                    refreshed = self._reconcile_marimo_runtime_locked(conn, runtime)
                    self._sync_bound_sessions_locked(conn, refreshed)
                    if refreshed.status == StudioSessionStatus.PROVISIONING:
                        summary["still_provisioning"] += 1
                    else:
                        summary["refreshed"] += 1
        return summary

    def _runtime_backing_pod_is_live(
        self,
        runtime: StudioRuntimeSession,
    ) -> bool | None:
        if (
            not self._runtime_live_check_enabled
            or runtime.kind != StudioRuntimeKind.MARIMO
        ):
            return None
        core_api = self._load_runtime_core_api()
        if core_api is None:
            return None
        try:
            pod = core_api.read_namespaced_pod(
                name=_runtime_pod_name(runtime.id),
                namespace=self._runtime_namespace,
            )
        except self._runtime_api_exception_type as exc:
            status = getattr(exc, "status", None)
            if status == 404:
                return False
            if status in {401, 403}:
                logger.warning(
                    "Studio runtime live check disabled: service account cannot read pods in %s",
                    self._runtime_namespace,
                )
                self._runtime_client_ready = False
                self._runtime_core_api = None
                return None
            logger.warning(
                "Studio runtime live check failed for %s: %s", runtime.id, exc
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive logging only
            logger.warning(
                "Studio runtime live check errored for %s: %s", runtime.id, exc
            )
            return None
        if getattr(pod.metadata, "deletion_timestamp", None) is not None:
            return False
        conditions = {
            condition.type: condition.status
            for condition in (getattr(pod.status, "conditions", None) or [])
        }
        return (
            getattr(pod.status, "phase", None) == "Running"
            and conditions.get("Ready") == "True"
        )

    def _load_runtime_core_api(self) -> Any | None:
        if not self._runtime_live_check_enabled:
            return None
        if self._runtime_core_api is not None:
            return self._runtime_core_api
        if self._runtime_client_ready is False:
            return None
        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config
            from kubernetes.client.rest import ApiException
        except ImportError:
            logger.warning(
                "Studio runtime live check disabled: kubernetes client is not installed"
            )
            self._runtime_client_ready = False
            return None
        try:
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            self._runtime_core_api = k8s_client.CoreV1Api()
            self._runtime_api_exception_type = ApiException
            self._runtime_client_ready = True
            return self._runtime_core_api
        except Exception as exc:
            logger.warning(
                "Studio runtime live check disabled: could not initialize Kubernetes client: %s",
                exc,
            )
            self._runtime_client_ready = False
            return None

    def _provision_runtime_session_locked(
        self,
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        request: CreateStudioSessionRequest,
        runtime_session_id: str | None = None,
    ) -> StudioRuntimeSession:
        metadata = dict(request.metadata or {})
        runtime_id = runtime_session_id or (
            f"rt_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"
        )
        workspace_relative_root = metadata.get("workspace_relative_root")
        if (
            not isinstance(workspace_relative_root, str)
            or not workspace_relative_root.strip()
        ):
            workspace_relative_root = _default_project_root_template().format(
                project_id=request.project_id
            )
        workspace_relative_root = _normalize_runtime_path(workspace_relative_root)
        project_root = metadata.get("jupyter_working_directory") or metadata.get(
            "working_directory"
        )
        if not isinstance(project_root, str) or not project_root.strip():
            project_root = workspace_relative_root
        absolute_project_root = metadata.get("absolute_working_directory")
        runtime_kind = request.runtime_kind
        if (
            not isinstance(absolute_project_root, str)
            or not absolute_project_root.strip()
        ):
            default_workdir_root = (
                _default_marimo_workdir_root()
                if runtime_kind == StudioRuntimeKind.MARIMO
                else _default_studio_workdir_root()
            )
            absolute_project_root = f"{default_workdir_root}/{request.project_id}"
        now = _utc_now()
        if runtime_kind == StudioRuntimeKind.MARIMO:
            marimo_base_url = metadata.get("marimo_base_url")
            if not isinstance(marimo_base_url, str) or not marimo_base_url.strip():
                marimo_base_url = _default_marimo_base_url(self._workspace_base_url)
            marimo_port = metadata.get("marimo_port")
            if isinstance(marimo_port, bool):
                marimo_port = _default_marimo_port()
            elif not isinstance(marimo_port, int):
                try:
                    marimo_port = int(str(marimo_port).strip())
                except (TypeError, ValueError):
                    marimo_port = _default_marimo_port()
            runtime = StudioRuntimeSession(
                id=runtime_id,
                project_id=request.project_id,
                owner_user_id=owner_user_id,
                runtime_profile_id=request.runtime_profile_id,
                kind=StudioRuntimeKind.MARIMO,
                status=(
                    StudioSessionStatus.READY
                    if marimo_base_url
                    else StudioSessionStatus.DEGRADED
                ),
                marimo_base_url=marimo_base_url,
                marimo_port=marimo_port,
                working_directory=project_root,
                metadata={
                    **metadata,
                    "runtime_kind": StudioRuntimeKind.MARIMO.value,
                    "surface_origin": "hub",
                    "workspace_relative_root": workspace_relative_root,
                    "absolute_working_directory": absolute_project_root,
                },
                created_at=now,
                updated_at=now,
                last_activity_at=now,
            )
            self._upsert_runtime_session_locked(conn, runtime)
            return self._reconcile_marimo_runtime_locked(conn, runtime)

        jupyter_base_url = metadata.get("jupyter_base_url")
        if not isinstance(jupyter_base_url, str) or not jupyter_base_url.strip():
            jupyter_base_url = _render_runtime_template(
                _default_studio_jupyter_base_url_template(),
                owner_user_id=owner_user_id,
                project_id=request.project_id,
                runtime_session_id=runtime_id,
                metadata={
                    **metadata,
                    "workspace_relative_root": workspace_relative_root,
                    "absolute_working_directory": absolute_project_root,
                },
            ) or _default_studio_jupyter_base_url(self._workspace_base_url)
        jupyter_token = metadata.get("jupyter_token")
        if not isinstance(jupyter_token, str) or not jupyter_token.strip():
            jupyter_token = _default_studio_jupyter_token()
        jupyter_kernel_name = metadata.get("jupyter_kernel_name")
        if not isinstance(jupyter_kernel_name, str) or not jupyter_kernel_name.strip():
            jupyter_kernel_name = _default_studio_jupyter_kernel_name()
        session_path = metadata.get("jupyter_session_path")
        if not isinstance(session_path, str) or not session_path.strip():
            session_path = f"projects/{request.project_id}/.studio/{runtime_id}"
        runtime = StudioRuntimeSession(
            id=runtime_id,
            project_id=request.project_id,
            owner_user_id=owner_user_id,
            runtime_profile_id=request.runtime_profile_id,
            kind=StudioRuntimeKind.JUPYTER,
            status=(
                StudioSessionStatus.READY
                if jupyter_base_url
                else StudioSessionStatus.DEGRADED
            ),
            jupyter_base_url=jupyter_base_url,
            jupyter_token=jupyter_token,
            jupyter_kernel_name=jupyter_kernel_name,
            working_directory=project_root,
            metadata={
                **metadata,
                "runtime_kind": StudioRuntimeKind.JUPYTER.value,
                "surface_origin": "studio",
                "jupyter_session_path": session_path,
                "workspace_relative_root": workspace_relative_root,
                "absolute_working_directory": absolute_project_root,
            },
            created_at=now,
            updated_at=now,
            last_activity_at=now,
        )
        self._upsert_runtime_session_locked(conn, runtime)
        return runtime

    def _get_session_locked(
        self, conn: sqlite3.Connection, session_id: str
    ) -> StudioSession | None:
        row = conn.execute(
            "SELECT * FROM studio_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return self._row_to_session(row) if row is not None else None

    @staticmethod
    def _merge_runtime_metadata(
        metadata: dict[str, Any], runtime: StudioRuntimeSession
    ) -> dict[str, Any]:
        merged = dict(metadata)
        merged["runtime_binding"] = {
            "runtime_session_id": runtime.id,
            "runtime_kind": runtime.kind.value,
            "status": runtime.status.value,
            "working_directory": runtime.working_directory,
            "jupyter_session_path": runtime.metadata.get("jupyter_session_path"),
            "workspace_relative_root": runtime.metadata.get("workspace_relative_root"),
            "jupyter_session_id": runtime.jupyter_session_id,
            "jupyter_kernel_id": runtime.jupyter_kernel_id,
            "marimo_base_url": runtime.marimo_base_url,
            "marimo_port": runtime.marimo_port,
            "marimo_runtime_target": runtime.metadata.get("marimo_runtime_target"),
        }
        return merged

    def _resolve_workspace_tree_path(
        self,
        raw_path: str | None,
        runtime: StudioRuntimeSession | None,
        *,
        project_id: str,
    ) -> str | None:
        normalized = _normalize_runtime_path(raw_path or "")
        workspace_root = ""
        if runtime is not None:
            workspace_root = _normalize_runtime_path(
                str(runtime.metadata.get("workspace_relative_root") or "")
            )
        if not workspace_root:
            workspace_root = _normalize_runtime_path(
                _default_project_root_template().format(project_id=project_id)
            )
        if not normalized:
            return workspace_root or None
        if not workspace_root:
            return normalized
        if normalized == workspace_root or normalized.startswith(f"{workspace_root}/"):
            return normalized
        return f"{workspace_root}/{normalized}"

    def _resolve_workspace_launch_base_url(
        self,
        *,
        session: StudioSession,
        runtime: StudioRuntimeSession | None,
    ) -> str:
        runtime_base_url = _normalize_optional_text(
            runtime.jupyter_base_url if runtime is not None else None
        )
        if runtime_base_url:
            return runtime_base_url.rstrip("/")

        rendered = _render_runtime_template(
            _default_studio_jupyter_base_url_template(),
            owner_user_id=session.owner_user_id,
            project_id=session.project_id,
            runtime_session_id=session.runtime_session_id,
            metadata=dict(
                runtime.metadata if runtime is not None else session.metadata
            ),
        )
        if rendered:
            return rendered.rstrip("/")

        return self._workspace_base_url

    def _resolve_hub_launch_base_url(
        self,
        *,
        session: StudioSession,
        runtime: StudioRuntimeSession | None,
    ) -> str:
        runtime_base_url = _normalize_optional_text(
            runtime.marimo_base_url if runtime is not None else None
        )
        if runtime_base_url:
            return runtime_base_url.rstrip("/")

        metadata = dict(runtime.metadata if runtime is not None else session.metadata)
        rendered = _render_runtime_template(
            _normalize_optional_text(os.getenv("BR_PUBLIC_HUB_URL_TEMPLATE")),
            owner_user_id=session.owner_user_id,
            project_id=session.project_id,
            runtime_session_id=session.runtime_session_id,
            metadata=metadata,
        )
        if rendered:
            return rendered.rstrip("/")

        return _default_marimo_base_url(self._workspace_base_url)

    def _build_workspace_url(
        self,
        *,
        workspace_base_url: str,
        notebook_path: str | None,
        target_path: str | None,
    ) -> str:
        path = notebook_path or target_path
        if not path:
            return f"{workspace_base_url}/lab"
        encoded = quote(path.lstrip("/"), safe="/")
        return f"{workspace_base_url}/lab/tree/{encoded}"

    def _build_hub_workspace_url(
        self,
        *,
        hub_base_url: str,
        session_id: str,
        notebook_path: str | None,
        target_path: str | None,
        open_artifact_id: str | None,
        initial_focus: str | None,
        materialize_notebook_if_needed: bool,
        open_clean_workspace: bool,
    ) -> str:
        params: dict[str, str] = {"session_id": session_id}
        path = notebook_path or target_path
        if path:
            params["path"] = path
        if open_artifact_id:
            params["artifact_id"] = open_artifact_id
        if initial_focus:
            params["focus"] = initial_focus
        if materialize_notebook_if_needed:
            params["materialize_notebook_if_needed"] = "1"
        if open_clean_workspace:
            params["open_clean_workspace"] = "1"
        return f"{hub_base_url}?{urlencode(params)}"
