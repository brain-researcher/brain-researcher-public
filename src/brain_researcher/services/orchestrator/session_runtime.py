"""User-facing remote session wrapper over the monitor runtime."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .monitor_runtime import (
    ChatBridge,
    CreateMonitorRequest,
    CreateSlackBridgeRequest,
    DeliveryTarget,
    MonitorActionRequest,
    MonitoredExecution,
    MonitorEventRecord,
    MonitorRuntime,
    MonitorSourceType,
    MonitorStatus,
)


class SessionKind(str, Enum):
    CODING_SESSION = "coding_session"
    MCP_RUN = "mcp_run"


class RemoteSession(BaseModel):
    id: str
    kind: SessionKind
    session_ref: str
    display_name: str
    thread_id: str | None = None
    status: MonitorStatus
    summary: str | None = None
    last_event_at: datetime | None = None
    control_capabilities: list[str] = Field(default_factory=list)
    delivery_targets: list[DeliveryTarget] = Field(default_factory=list)
    chat_bindings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CreateSessionRequest(BaseModel):
    kind: SessionKind
    session_ref: str = Field(..., min_length=1, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=200)
    thread_id: str | None = None
    slack_channel_id: str | None = Field(default=None, min_length=1, max_length=128)
    slack_thread_ts: str | None = Field(default=None, max_length=64)
    mirror_chat: bool = True
    cluster_profile: str | None = None
    delivery_targets: list[DeliveryTarget] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionActionRequest(BaseModel):
    tail: int = Field(default=200, ge=1, le=2000)
    stream: str = "both"
    grep: str | None = None
    reason: str | None = None
    force: bool = False


def _kind_to_source_type(kind: SessionKind) -> MonitorSourceType:
    if kind == SessionKind.CODING_SESSION:
        return MonitorSourceType.CODING_SESSION
    return MonitorSourceType.MCP_RUN


def _source_type_to_kind(source_type: MonitorSourceType | str) -> SessionKind | None:
    token = (
        source_type.value
        if isinstance(source_type, MonitorSourceType)
        else str(source_type)
    )
    if token == MonitorSourceType.CODING_SESSION.value:
        return SessionKind.CODING_SESSION
    if token == MonitorSourceType.MCP_RUN.value:
        return SessionKind.MCP_RUN
    return None


class SessionRuntime:
    """Thin session facade backed by the persistent monitor runtime."""

    def __init__(self, app: Any | None, monitor_runtime: MonitorRuntime):
        self._app = app
        self._monitor_runtime = monitor_runtime

    async def create_session(
        self,
        owner_user_id: str,
        request: CreateSessionRequest,
    ) -> RemoteSession:
        thread_id = request.thread_id
        if request.kind == SessionKind.CODING_SESSION and not thread_id:
            session_ref = request.session_ref.strip()
            if session_ref.startswith("thread_") or session_ref == "default":
                thread_id = session_ref

        monitor = await self._monitor_runtime.create_monitor(
            owner_user_id,
            CreateMonitorRequest(
                source_type=_kind_to_source_type(request.kind),
                source_ref=request.session_ref,
                display_name=request.display_name,
                thread_id=thread_id,
                cluster_profile=request.cluster_profile,
                delivery_targets=request.delivery_targets,
                metadata=request.metadata,
            ),
        )
        if request.slack_channel_id:
            await self._monitor_runtime.create_slack_bridge(
                monitor.id,
                CreateSlackBridgeRequest(
                    channel_id=request.slack_channel_id,
                    thread_ts=request.slack_thread_ts,
                    mirror_chat=request.mirror_chat,
                ),
            )
            monitor = await self._monitor_runtime.get_monitor(monitor.id) or monitor
        return self._session_from_monitor(monitor)

    async def list_sessions(
        self,
        *,
        owner_user_id: str,
        kind: SessionKind | None = None,
        thread_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RemoteSession]:
        if kind is not None:
            monitors = await self._monitor_runtime.list_monitors(
                owner_user_id=owner_user_id,
                thread_id=thread_id,
                source_type=_kind_to_source_type(kind).value,
                limit=limit,
                offset=offset,
            )
        else:
            monitors = await self._monitor_runtime.list_monitors(
                owner_user_id=owner_user_id,
                thread_id=thread_id,
                limit=max(limit + offset, 200),
                offset=0,
            )
        items = [
            self._session_from_monitor(monitor)
            for monitor in monitors
            if _source_type_to_kind(monitor.source_type) is not None
        ]
        if kind is None:
            items = items[offset : offset + limit]
        return items

    async def get_session(self, session_id: str) -> RemoteSession | None:
        monitor = await self._monitor_runtime.get_monitor(session_id)
        if monitor is None:
            return None
        if _source_type_to_kind(monitor.source_type) is None:
            return None
        return self._session_from_monitor(monitor)

    async def list_session_events(
        self,
        session_id: str,
        *,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> list[MonitorEventRecord]:
        return await self._monitor_runtime.list_monitor_events(
            session_id, after_event_id=after_event_id, limit=limit
        )

    async def perform_action(
        self,
        session_id: str,
        action: str,
        request: SessionActionRequest | None = None,
    ) -> dict[str, Any]:
        payload = request or SessionActionRequest()
        runtime_result = await self._monitor_runtime.perform_action(
            session_id,
            "tail_logs" if action == "logs" else action,
            MonitorActionRequest(
                tail=payload.tail,
                stream=payload.stream,
                grep=payload.grep,
                reason=payload.reason,
                force=payload.force,
            ),
        )
        if isinstance(runtime_result.get("monitor"), dict):
            monitor = MonitoredExecution.model_validate(runtime_result["monitor"])
            runtime_result["session"] = self._session_from_monitor(monitor).model_dump(
                mode="json"
            )
            runtime_result.pop("monitor", None)
        return runtime_result

    async def create_slack_bridge(
        self, session_id: str, request: CreateSlackBridgeRequest
    ) -> ChatBridge:
        return await self._monitor_runtime.create_slack_bridge(session_id, request)

    def _session_from_monitor(self, monitor: MonitoredExecution) -> RemoteSession:
        kind = _source_type_to_kind(monitor.source_type)
        if kind is None:
            raise ValueError(f"Unsupported session source type: {monitor.source_type}")
        summary = (
            (monitor.metadata or {}).get("session_summary")
            or (monitor.metadata or {}).get("summary")
            or monitor.status_reason
        )
        return RemoteSession(
            id=monitor.id,
            kind=kind,
            session_ref=monitor.source_ref,
            display_name=monitor.display_name,
            thread_id=monitor.thread_id,
            status=monitor.status,
            summary=str(summary) if summary else None,
            last_event_at=monitor.last_seen_at,
            control_capabilities=list(monitor.control_capabilities),
            delivery_targets=list(monitor.delivery_targets),
            chat_bindings=list(monitor.chat_bindings),
            metadata=dict(monitor.metadata or {}),
            created_at=monitor.created_at,
            updated_at=monitor.updated_at,
        )
