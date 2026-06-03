"""Persistent execution monitors and chat bridge runtime."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import signal
import subprocess
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from brain_researcher.services.mcp.slurm_tools import (
    sherlock_job_inspect,
    sherlock_job_logs,
)

from .job_state import jobs_db, messages_db, threads_db
from .models import (
    Message,
    Notification,
    NotificationPriority,
    NotificationType,
    Thread,
)
from .state_store import get_state_store

logger = logging.getLogger(__name__)

_MONITOR_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_DEFAULT_POLL_SECONDS = int(os.getenv("BR_MONITOR_POLL_SECONDS", "15"))
_SLACK_ROOT_KEY = "root"


class MonitorSourceType(str, Enum):
    BR_JOB = "br_job"
    SLURM_JOB = "slurm_job"
    LOCAL_PROCESS = "local_process"
    CODING_SESSION = "coding_session"
    MCP_RUN = "mcp_run"


class MonitorStatus(str, Enum):
    UNKNOWN = "unknown"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryTarget(BaseModel):
    platform: Literal["slack", "discord", "in_app"]
    bridge_id: str | None = None
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class MonitoredExecution(BaseModel):
    id: str = Field(..., pattern=r"^mon_[A-Za-z0-9]+$")
    owner_user_id: str
    thread_id: str | None = None
    source_type: MonitorSourceType
    source_ref: str
    display_name: str = Field(..., min_length=1, max_length=200)
    status: MonitorStatus = MonitorStatus.UNKNOWN
    status_reason: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=100.0)
    log_sources: dict[str, Any] = Field(default_factory=dict)
    control_capabilities: list[str] = Field(default_factory=list)
    delivery_targets: list[DeliveryTarget] = Field(default_factory=list)
    chat_bindings: list[str] = Field(default_factory=list)
    audit_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MonitorEventRecord(BaseModel):
    event_id: int
    event_type: str
    created_at: int
    payload: dict[str, Any]


class CreateMonitorRequest(BaseModel):
    source_type: MonitorSourceType
    source_ref: str
    display_name: str = Field(..., min_length=1, max_length=200)
    thread_id: str | None = None
    cluster_profile: str | None = None
    log_paths: list[str] = Field(default_factory=list)
    delivery_targets: list[DeliveryTarget] = Field(default_factory=list)
    control_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MonitorActionRequest(BaseModel):
    tail: int = Field(default=200, ge=1, le=2000)
    stream: Literal["stdout", "stderr", "both"] = "both"
    grep: str | None = None
    reason: str | None = None
    force: bool = False


class CreateSlackBridgeRequest(BaseModel):
    channel_id: str = Field(..., min_length=1, max_length=128)
    thread_ts: str | None = None
    initial_message: str | None = Field(default=None, max_length=2000)
    post_root_message: bool = True
    mirror_chat: bool = True


class CreateDiscordBridgeRequest(BaseModel):
    webhook_url: str = Field(..., min_length=10, max_length=2000)
    channel_id: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class ChatBridge(BaseModel):
    id: str = Field(..., pattern=r"^bridge_[A-Za-z0-9]+$")
    thread_id: str
    platform: Literal["slack", "discord"]
    bridge_key: str
    monitor_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


def _utc_now() -> datetime:
    return datetime.utcnow()


def _tail_lines(text: str, tail: int) -> str:
    lines = text.splitlines()
    if tail <= 0:
        return text
    return "\n".join(lines[-tail:])


def _summarize_text(text: str, limit: int = 180) -> str:
    summary = " ".join(str(text or "").split())
    if len(summary) <= limit:
        return summary
    return summary[: max(0, limit - 3)].rstrip() + "..."


def _normalize_thread_id(thread_id: str) -> str:
    if thread_id.startswith("thread_"):
        return thread_id
    return f"thread_{thread_id}"


def _slack_bridge_key(channel_id: str, thread_ts: str | None) -> str:
    return f"channel:{channel_id}:thread:{thread_ts or _SLACK_ROOT_KEY}"


def _discord_bridge_key(channel_id: str | None, webhook_url: str) -> str:
    digest = hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()[:16]
    channel_part = channel_id or "webhook"
    return f"channel:{channel_part}:webhook:{digest}"


def _parse_progress(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return float(int(raw))
    if isinstance(raw, int | float):
        return max(0.0, min(float(raw), 100.0))
    if isinstance(raw, dict):
        return _parse_progress(raw.get("percentage"))
    return None


def _normalize_monitor_status(raw: Any) -> MonitorStatus:
    token = str(raw or "").strip().lower()
    if token in {"queued", "pending", "pd", "configuring"}:
        return MonitorStatus.QUEUED
    if token in {"running", "claimed", "retrying", "cg", "completing"}:
        return MonitorStatus.RUNNING
    if token in {"completed", "complete", "succeeded", "cd"}:
        return MonitorStatus.COMPLETED
    if token in {"failed", "f", "timeout", "timed_out", "oom", "out_of_memory"}:
        return MonitorStatus.FAILED
    if token in {"cancelled", "canceled", "ca"}:
        return MonitorStatus.CANCELLED
    return MonitorStatus.UNKNOWN


def _status_is_terminal(status: MonitorStatus | str) -> bool:
    return str(status) in _MONITOR_TERMINAL_STATUSES


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _slack_signing_secret() -> str | None:
    return os.getenv("BR_MONITOR_SLACK_SIGNING_SECRET") or os.getenv(
        "SLACK_SIGNING_SECRET"
    )


def _slack_bot_token() -> str | None:
    return os.getenv("BR_MONITOR_SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN")


def _discord_public_key() -> str | None:
    return os.getenv("BR_MONITOR_DISCORD_PUBLIC_KEY") or os.getenv(
        "DISCORD_PUBLIC_KEY"
    )


def _strip_slack_mentions(text: str) -> str:
    return re.sub(r"<@[A-Z0-9]+>", "", text or "").strip()


def _decode_discord_hex_key(value: str) -> bytes:
    return bytes.fromhex(value.strip())


class MonitorRuntime:
    """Owns persistent monitor refresh and external chat bridge dispatch."""

    def __init__(self, app: Any | None = None, poll_seconds: int = _DEFAULT_POLL_SECONDS):
        self._app = app
        self._poll_seconds = max(5, int(poll_seconds))
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.refresh_all_monitors()
            except Exception:
                logger.exception("Monitor refresh loop failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_seconds
                )
            except asyncio.TimeoutError:
                continue

    async def refresh_all_monitors(self) -> list[MonitoredExecution]:
        store = await get_state_store()
        if store is None:
            return []
        refreshed: list[MonitoredExecution] = []
        for raw in await store.list_monitors(limit=500):
            monitor = MonitoredExecution.model_validate(raw)
            refreshed.append(await self.refresh_monitor(monitor))
        return refreshed

    async def create_monitor(
        self, owner_user_id: str, request: CreateMonitorRequest
    ) -> MonitoredExecution:
        store = await self._require_store()
        thread_id = await self._ensure_thread_record(
            owner_user_id=owner_user_id,
            title=request.display_name,
            metadata={
                "monitor_source_type": request.source_type.value,
                "monitor_source_ref": request.source_ref,
            },
            preferred_thread_id=request.thread_id,
        )
        now = _utc_now()
        monitor = MonitoredExecution(
            id=f"mon_{uuid.uuid4().hex[:12]}",
            owner_user_id=owner_user_id,
            thread_id=thread_id,
            source_type=request.source_type,
            source_ref=str(request.source_ref),
            display_name=request.display_name,
            status=MonitorStatus.UNKNOWN,
            log_sources=self._initial_log_sources(request),
            control_capabilities=self._control_capabilities(request.source_type),
            delivery_targets=request.delivery_targets,
            audit_policy=request.control_policy,
            metadata={
                **request.metadata,
                **(
                    {"cluster_profile": request.cluster_profile}
                    if request.cluster_profile
                    else {}
                ),
            },
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        await store.upsert_monitor(monitor.model_dump(mode="json"))
        await self._append_monitor_event(
            monitor,
            "monitor.created",
            {
                "display_name": monitor.display_name,
                "source_type": monitor.source_type.value,
                "source_ref": monitor.source_ref,
            },
        )
        return await self.refresh_monitor(monitor, emit_transition=False)

    async def list_monitors(
        self,
        *,
        owner_user_id: str | None = None,
        thread_id: str | None = None,
        source_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MonitoredExecution]:
        store = await self._require_store()
        items = await store.list_monitors(
            owner_user_id=owner_user_id,
            thread_id=thread_id,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )
        return [MonitoredExecution.model_validate(item) for item in items]

    async def get_monitor(self, monitor_id: str) -> MonitoredExecution | None:
        store = await self._require_store()
        raw = await store.get_monitor(monitor_id)
        if raw is None:
            return None
        return MonitoredExecution.model_validate(raw)

    async def list_monitor_events(
        self, monitor_id: str, *, after_event_id: int = 0, limit: int = 200
    ) -> list[MonitorEventRecord]:
        store = await self._require_store()
        rows = await store.list_monitor_events(
            monitor_id=monitor_id,
            after_event_id=after_event_id,
            limit=limit,
        )
        return [MonitorEventRecord.model_validate(row) for row in rows]

    async def create_slack_bridge(
        self, monitor_id: str, request: CreateSlackBridgeRequest
    ) -> ChatBridge:
        monitor = await self._require_monitor(monitor_id)
        thread_ts = request.thread_ts
        if not thread_ts and request.post_root_message:
            initial_message = (
                request.initial_message
                or f"Monitoring `{monitor.display_name}` from Brain Researcher."
            )
            thread_ts = await self._post_slack_message(
                channel_id=request.channel_id,
                text=initial_message,
                thread_ts=None,
            )

        bridge = ChatBridge(
            id=f"bridge_{uuid.uuid4().hex[:12]}",
            thread_id=str(monitor.thread_id),
            platform="slack",
            bridge_key=_slack_bridge_key(request.channel_id, thread_ts),
            monitor_id=monitor.id,
            config={
                "channel_id": request.channel_id,
                "thread_ts": thread_ts,
                "mirror_chat": request.mirror_chat,
            },
            metadata={},
        )
        await self._persist_bridge(bridge)
        updated_monitor = await self._attach_bridge_to_monitor(monitor, bridge)
        await self._append_monitor_event(
            updated_monitor,
            "bridge.created",
            {"platform": "slack", "bridge_id": bridge.id},
        )
        return bridge

    async def create_discord_bridge(
        self, monitor_id: str, request: CreateDiscordBridgeRequest
    ) -> ChatBridge:
        monitor = await self._require_monitor(monitor_id)
        bridge = ChatBridge(
            id=f"bridge_{uuid.uuid4().hex[:12]}",
            thread_id=str(monitor.thread_id),
            platform="discord",
            bridge_key=_discord_bridge_key(request.channel_id, request.webhook_url),
            monitor_id=monitor.id,
            config={
                "webhook_url": request.webhook_url,
                "channel_id": request.channel_id,
                "display_name": request.display_name or "Brain Researcher",
            },
            metadata={},
        )
        await self._persist_bridge(bridge)
        updated_monitor = await self._attach_bridge_to_monitor(monitor, bridge)
        await self._append_monitor_event(
            updated_monitor,
            "bridge.created",
            {"platform": "discord", "bridge_id": bridge.id},
        )
        return bridge

    async def refresh_monitor(
        self,
        monitor: MonitoredExecution,
        *,
        emit_transition: bool = True,
    ) -> MonitoredExecution:
        store = await self._require_store()
        now = _utc_now()
        snapshot = await self._probe_monitor(monitor)
        previous_status = monitor.status
        updated = monitor.model_copy(
            update={
                "status": snapshot["status"],
                "status_reason": snapshot.get("status_reason"),
                "progress": snapshot.get("progress"),
                "log_sources": snapshot.get("log_sources", monitor.log_sources),
                "control_capabilities": snapshot.get(
                    "control_capabilities", monitor.control_capabilities
                ),
                "metadata": {**monitor.metadata, **snapshot.get("metadata", {})},
                "last_seen_at": now,
                "updated_at": now,
            }
        )
        await store.upsert_monitor(updated.model_dump(mode="json"))
        if emit_transition and previous_status != updated.status:
            payload = {
                "from_status": previous_status.value,
                "to_status": updated.status.value,
                "reason": updated.status_reason,
                "progress": updated.progress,
            }
            await self._append_monitor_event(updated, "monitor.status_changed", payload)
            await self._send_status_notifications(updated, previous_status)
        return updated

    async def perform_action(
        self,
        monitor_id: str,
        action: str,
        request: MonitorActionRequest | None = None,
    ) -> dict[str, Any]:
        request = request or MonitorActionRequest()
        monitor = await self._require_monitor(monitor_id)
        action_token = action.strip().lower()

        if action_token == "status":
            refreshed = await self.refresh_monitor(monitor)
            return {"ok": True, "monitor": refreshed.model_dump(mode="json")}

        if action_token == "tail_logs":
            logs = await self._tail_logs(monitor, request=request)
            return {"ok": True, "monitor_id": monitor.id, "logs": logs}

        if action_token == "cancel":
            result = await self._cancel_monitor(monitor, request=request)
            refreshed = await self.refresh_monitor(await self._require_monitor(monitor_id))
            return {
                "ok": True,
                "monitor": refreshed.model_dump(mode="json"),
                "result": result,
            }

        if action_token == "retry":
            result = await self._retry_monitor(monitor)
            refreshed = await self.refresh_monitor(await self._require_monitor(monitor_id))
            return {
                "ok": True,
                "monitor": refreshed.model_dump(mode="json"),
                "result": result,
            }

        if action_token == "ack":
            refreshed = await self._ack_monitor(monitor)
            return {"ok": True, "monitor": refreshed.model_dump(mode="json")}

        raise HTTPException(status_code=400, detail=f"Unsupported monitor action: {action}")

    async def mirror_thread_message_outbound(self, message: Message) -> None:
        if not message.thread_id:
            return
        store = await get_state_store()
        if store is None:
            return
        bridges = await store.list_chat_bridges(thread_id=message.thread_id, platform="slack")
        if not bridges:
            return
        for raw in bridges:
            bridge = ChatBridge.model_validate(raw)
            if message.metadata.get("bridge_source") == bridge.id:
                continue
            if not bridge.config.get("mirror_chat", True):
                continue
            try:
                role_label = "Assistant" if message.role == "assistant" else "User"
                await self._post_slack_message(
                    channel_id=bridge.config["channel_id"],
                    text=f"*{role_label}:*\n{message.content}",
                    thread_ts=bridge.config.get("thread_ts"),
                )
            except Exception:
                logger.exception("Failed to mirror thread %s to Slack", message.thread_id)

    async def handle_slack_events(self, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        self._verify_slack_request(body, headers)
        payload = json.loads(body.decode("utf-8"))
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        if payload.get("type") != "event_callback":
            return {"ok": True}

        event = payload.get("event") or {}
        if event.get("subtype") == "bot_message":
            return {"ok": True}

        event_type = event.get("type")
        if event_type not in {"app_mention", "message"}:
            return {"ok": True}

        channel_id = str(event.get("channel") or "").strip()
        thread_ts = str(event.get("thread_ts") or event.get("ts") or "").strip()
        if not channel_id:
            return {"ok": True}

        bridge = await self._resolve_slack_bridge(channel_id=channel_id, thread_ts=thread_ts)
        if bridge is None:
            return {"ok": True}

        text = _strip_slack_mentions(str(event.get("text") or ""))
        if not text:
            return {"ok": True}

        monitor_id = bridge.monitor_id
        handled = False
        if monitor_id:
            handled = await self._handle_chat_command(
                platform="slack",
                bridge=bridge,
                text=text,
            )
        if handled:
            return {"ok": True}

        if bridge.thread_id:
            await self._enqueue_chat_message_via_app(
                thread_id=bridge.thread_id,
                content=text,
                metadata={
                    "bridge_source": bridge.id,
                    "bridge_platform": "slack",
                    "external_user": event.get("user"),
                },
            )
        return {"ok": True}

    async def handle_slack_interaction(
        self, raw_body: bytes, headers: dict[str, str]
    ) -> dict[str, Any]:
        self._verify_slack_request(raw_body, headers)
        form_payload = raw_body.decode("utf-8")
        if form_payload.lstrip().startswith("{"):
            payload = json.loads(form_payload)
            payload_text = payload.get("payload")
        else:
            from urllib.parse import parse_qs

            payload_text = (parse_qs(form_payload, keep_blank_values=True).get("payload") or [None])[0]
        if payload_text is None:
            raise HTTPException(status_code=400, detail="Missing Slack interaction payload")
        payload = json.loads(payload_text)
        actions = payload.get("actions") or []
        if not actions:
            return {"text": "No action payload found."}
        action = actions[0]
        try:
            value = json.loads(action.get("value") or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid Slack action payload") from exc
        result = await self.perform_action(
            str(value.get("monitor_id") or ""),
            str(value.get("action") or ""),
            MonitorActionRequest.model_validate(value.get("params") or {}),
        )
        return {"text": self._format_action_result(result)}

    async def handle_discord_interaction(
        self, body: bytes, headers: dict[str, str]
    ) -> dict[str, Any]:
        self._verify_discord_request(body, headers)
        payload = json.loads(body.decode("utf-8"))
        interaction_type = int(payload.get("type") or 0)
        if interaction_type == 1:
            return {"type": 1}
        if interaction_type != 2:
            return {"type": 4, "data": {"content": "Unsupported interaction."}}

        data = payload.get("data") or {}
        name = str(data.get("name") or "").strip().lower()
        options = {
            str(item.get("name")): item.get("value")
            for item in (data.get("options") or [])
            if isinstance(item, dict)
        }
        monitor_id = str(options.get("monitor_id") or "").strip()
        tail = int(options.get("tail") or 200)

        if not monitor_id:
            return {"type": 4, "data": {"content": "monitor_id is required."}}

        action_map = {
            "monitor-status": ("status", MonitorActionRequest()),
            "monitor-logs": ("tail_logs", MonitorActionRequest(tail=tail)),
            "monitor-cancel": ("cancel", MonitorActionRequest()),
            "monitor-ack": ("ack", MonitorActionRequest()),
        }
        mapped = action_map.get(name)
        if mapped is None:
            return {"type": 4, "data": {"content": f"Unsupported command: {name}"}}
        result = await self.perform_action(monitor_id, mapped[0], mapped[1])
        return {"type": 4, "data": {"content": self._format_action_result(result)}}

    async def _require_store(self):
        store = await get_state_store()
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Monitor registry requires the persistent state store.",
            )
        return store

    async def _require_monitor(self, monitor_id: str) -> MonitoredExecution:
        monitor = await self.get_monitor(monitor_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor not found")
        return monitor

    async def _persist_bridge(self, bridge: ChatBridge) -> None:
        store = await self._require_store()
        await store.upsert_chat_bridge(bridge.model_dump(mode="json"))

    async def _append_monitor_event(
        self, monitor: MonitoredExecution, event_type: str, payload: dict[str, Any]
    ) -> int:
        store = await self._require_store()
        return await store.append_monitor_event(
            monitor_id=monitor.id,
            event_type=event_type,
            event={
                "monitor_id": monitor.id,
                "thread_id": monitor.thread_id,
                **payload,
            },
        )

    async def _attach_bridge_to_monitor(
        self, monitor: MonitoredExecution, bridge: ChatBridge
    ) -> MonitoredExecution:
        delivery_targets = list(monitor.delivery_targets)
        delivery_targets.append(
            DeliveryTarget(platform=bridge.platform, bridge_id=bridge.id, enabled=True)
        )
        chat_bindings = list(monitor.chat_bindings)
        if bridge.id not in chat_bindings:
            chat_bindings.append(bridge.id)
        updated = monitor.model_copy(
            update={
                "chat_bindings": chat_bindings,
                "delivery_targets": delivery_targets,
                "updated_at": _utc_now(),
            }
        )
        store = await self._require_store()
        await store.upsert_monitor(updated.model_dump(mode="json"))
        return updated

    async def _ensure_thread_record(
        self,
        *,
        owner_user_id: str,
        title: str,
        metadata: dict[str, Any],
        preferred_thread_id: str | None = None,
    ) -> str:
        store = await self._require_store()
        thread_id = (
            _normalize_thread_id(preferred_thread_id)
            if preferred_thread_id
            else f"thread_{uuid.uuid4().hex[:12]}"
        )
        if thread_id in threads_db:
            return thread_id
        stored_thread = await store.get_thread(thread_id)
        if stored_thread is not None:
            threads_db[thread_id] = Thread.model_validate(stored_thread)
            messages_db.setdefault(thread_id, [])
            return thread_id

        now = _utc_now()
        thread = Thread(
            thread_id=thread_id,
            title=title,
            created_at=now,
            updated_at=now,
            context={},
            metadata={"owner_user_id": owner_user_id, **metadata},
            scenario_id=None,
        )
        threads_db[thread_id] = thread
        messages_db.setdefault(thread_id, [])
        await store.upsert_thread(thread_id=thread_id, thread=thread.model_dump(mode="json"))
        return thread_id

    async def _load_thread_messages(self, thread_ref: str, limit: int = 100) -> list[Message]:
        if not thread_ref:
            return []
        thread_id = _normalize_thread_id(thread_ref)
        in_memory = messages_db.get(thread_id) or []
        if in_memory:
            return list(in_memory[-limit:])
        store = await get_state_store()
        if store is None:
            return []
        rows = await store.list_messages(thread_id=thread_id, limit=limit)
        messages = [Message.model_validate(row) for row in rows]
        if messages:
            messages_db[thread_id] = list(messages)
        return messages

    async def _resolve_coding_session_delegate(
        self, monitor: MonitoredExecution
    ) -> MonitoredExecution | None:
        source_ref = str(monitor.source_ref or "").strip()
        if source_ref and (source_ref.startswith("job_") or source_ref in jobs_db):
            return monitor.model_copy(
                update={
                    "source_type": MonitorSourceType.BR_JOB,
                    "source_ref": source_ref,
                    "control_capabilities": self._control_capabilities(MonitorSourceType.BR_JOB),
                }
            )
        if source_ref and not source_ref.startswith("thread_") and source_ref != monitor.thread_id:
            run_monitor = monitor.model_copy(
                update={
                    "source_type": MonitorSourceType.MCP_RUN,
                    "source_ref": source_ref,
                    "control_capabilities": self._control_capabilities(MonitorSourceType.MCP_RUN),
                }
            )
            run_snapshot = await self._probe_mcp_run(run_monitor)
            if str(run_snapshot.get("status_reason") or "").strip() not in {
                "run_not_found",
                "",
            } or run_snapshot.get("status") != MonitorStatus.UNKNOWN:
                return run_monitor

        thread_ref = monitor.thread_id or source_ref
        messages = await self._load_thread_messages(thread_ref)
        for message in reversed(messages):
            for candidate in (
                message.job_id,
                (message.metadata or {}).get("job_id"),
                (message.metadata or {}).get("plan_job_id"),
            ):
                if candidate:
                    return monitor.model_copy(
                        update={
                            "source_type": MonitorSourceType.BR_JOB,
                            "source_ref": str(candidate),
                            "control_capabilities": self._control_capabilities(MonitorSourceType.BR_JOB),
                        }
                    )
            candidate = (message.metadata or {}).get("run_id")
            if candidate:
                run_monitor = monitor.model_copy(
                    update={
                        "source_type": MonitorSourceType.MCP_RUN,
                        "source_ref": str(candidate),
                        "control_capabilities": self._control_capabilities(MonitorSourceType.MCP_RUN),
                    }
                )
                run_snapshot = await self._probe_mcp_run(run_monitor)
                if str(run_snapshot.get("status_reason") or "").strip() != "run_not_found":
                    return run_monitor
        return None

    def _discover_run_log_sources(self, run_dir: Path) -> dict[str, Any]:
        log_sources: dict[str, Any] = {"run_dir": str(run_dir)}
        log_paths: list[str] = []
        logs_dir = run_dir / "logs"
        if logs_dir.exists():
            log_paths.extend(str(path) for path in sorted(logs_dir.rglob("*")) if path.is_file())
        for candidate_name in ("stdout.txt", "stderr.txt"):
            candidate = run_dir / candidate_name
            if candidate.exists():
                log_paths.append(str(candidate))
        if not log_paths:
            return log_sources
        ordered_paths = list(dict.fromkeys(log_paths))
        log_sources["paths"] = ordered_paths
        for path_str in ordered_paths:
            name = Path(path_str).name.lower()
            if "stdout" in name and "stdout" not in log_sources:
                log_sources["stdout"] = path_str
            elif "stderr" in name and "stderr" not in log_sources:
                log_sources["stderr"] = path_str
        if "stdout" not in log_sources:
            log_sources["stdout"] = ordered_paths[0]
        if "stderr" not in log_sources and len(ordered_paths) > 1:
            log_sources["stderr"] = ordered_paths[1]
        return log_sources

    def _initial_log_sources(self, request: CreateMonitorRequest) -> dict[str, Any]:
        log_sources: dict[str, Any] = {}
        if request.log_paths:
            log_sources["paths"] = list(request.log_paths)
            if len(request.log_paths) >= 1:
                log_sources["stdout"] = request.log_paths[0]
            if len(request.log_paths) >= 2:
                log_sources["stderr"] = request.log_paths[1]
        return log_sources

    def _control_capabilities(self, source_type: MonitorSourceType) -> list[str]:
        if source_type == MonitorSourceType.BR_JOB:
            return ["status", "tail_logs", "cancel", "retry", "ack"]
        if source_type == MonitorSourceType.SLURM_JOB:
            return ["status", "tail_logs", "cancel", "ack"]
        if source_type == MonitorSourceType.LOCAL_PROCESS:
            return ["status", "tail_logs", "cancel", "ack"]
        if source_type == MonitorSourceType.CODING_SESSION:
            return ["status", "tail_logs", "cancel", "ack"]
        if source_type == MonitorSourceType.MCP_RUN:
            return ["status", "tail_logs", "cancel", "ack"]
        return ["status"]

    async def _probe_monitor(self, monitor: MonitoredExecution) -> dict[str, Any]:
        if monitor.source_type == MonitorSourceType.BR_JOB:
            return await self._probe_br_job(monitor)
        if monitor.source_type == MonitorSourceType.SLURM_JOB:
            return await self._probe_slurm_job(monitor)
        if monitor.source_type == MonitorSourceType.LOCAL_PROCESS:
            return await self._probe_local_process(monitor)
        if monitor.source_type == MonitorSourceType.CODING_SESSION:
            return await self._probe_coding_session(monitor)
        if monitor.source_type == MonitorSourceType.MCP_RUN:
            return await self._probe_mcp_run(monitor)
        return {"status": MonitorStatus.UNKNOWN, "status_reason": "unsupported_source"}

    async def _probe_br_job(self, monitor: MonitoredExecution) -> dict[str, Any]:
        source_ref = monitor.source_ref
        job = jobs_db.get(source_ref)
        job_adapter = getattr(self._app.state, "job_adapter", None) if self._app else None
        if job is None and job_adapter is not None:
            try:
                job = await job_adapter.get_job(source_ref)
            except Exception:
                logger.debug("JobAdapter lookup failed for %s", source_ref, exc_info=True)

        if job is None:
            return {
                "status": monitor.status if _status_is_terminal(monitor.status) else MonitorStatus.UNKNOWN,
                "status_reason": "job_not_found",
                "progress": monitor.progress,
                "log_sources": monitor.log_sources,
                "control_capabilities": self._control_capabilities(monitor.source_type),
            }

        run_dir = getattr(job, "run_dir", None)
        log_sources = dict(monitor.log_sources)
        if run_dir:
            run_path = Path(str(run_dir))
            stdout_path = run_path / "stdout.txt"
            stderr_path = run_path / "stderr.txt"
            if stdout_path.exists():
                log_sources["stdout"] = str(stdout_path)
            if stderr_path.exists():
                log_sources["stderr"] = str(stderr_path)
            log_sources["run_dir"] = str(run_path)

        status_reason = (
            getattr(job, "error", None)
            or getattr(job, "cancellation_reason", None)
            or getattr(job, "status_message", None)
        )
        return {
            "status": _normalize_monitor_status(getattr(job, "status", None)),
            "status_reason": status_reason,
            "progress": _parse_progress(getattr(job, "progress", None)),
            "log_sources": log_sources,
            "control_capabilities": self._control_capabilities(monitor.source_type),
            "metadata": {
                "job_id": source_ref,
                "pipeline": (getattr(job, "metadata", {}) or {}).get("pipeline"),
                "session_summary": _summarize_text(
                    status_reason or f"Job {getattr(job, 'status', 'unknown')}"
                ),
            },
        }

    async def _probe_slurm_job(self, monitor: MonitoredExecution) -> dict[str, Any]:
        inspect = sherlock_job_inspect(job_id=monitor.source_ref)
        squeue = inspect.get("squeue") or {}
        sacct_rows = inspect.get("sacct") or []
        sacct_state = ""
        if sacct_rows:
            sacct_state = str(sacct_rows[0].get("State") or "")
        status_token = squeue.get("state") or sacct_state
        reason = squeue.get("reason") or squeue.get("node_or_reason")
        log_sources = dict(monitor.log_sources)
        if inspect.get("log_paths"):
            log_sources.update(inspect["log_paths"])
        return {
            "status": _normalize_monitor_status(status_token),
            "status_reason": reason or status_token or "slurm_status_unknown",
            "progress": None,
            "log_sources": log_sources,
            "control_capabilities": self._control_capabilities(monitor.source_type),
            "metadata": {
                "slurm": {
                    "squeue": squeue,
                    "sacct": sacct_rows[:2],
                    "warnings": inspect.get("warnings") or [],
                }
            },
        }

    async def _probe_local_process(self, monitor: MonitoredExecution) -> dict[str, Any]:
        try:
            pid = int(str(monitor.source_ref))
        except ValueError:
            return {
                "status": MonitorStatus.FAILED,
                "status_reason": "invalid_pid",
                "progress": monitor.progress,
                "log_sources": monitor.log_sources,
                "control_capabilities": self._control_capabilities(monitor.source_type),
            }

        alive = _pid_is_alive(pid)
        status = MonitorStatus.RUNNING if alive else MonitorStatus.COMPLETED
        if not alive and monitor.metadata.get("cancel_requested_at"):
            status = MonitorStatus.CANCELLED
        return {
            "status": status,
            "status_reason": "pid_alive" if alive else "process_exited",
            "progress": monitor.progress,
            "log_sources": monitor.log_sources,
            "control_capabilities": self._control_capabilities(monitor.source_type),
            "metadata": {"pid": pid},
        }

    async def _probe_mcp_run(self, monitor: MonitoredExecution) -> dict[str, Any]:
        try:
            from brain_researcher.services.mcp import server as mcp_server
        except Exception as exc:
            logger.debug(
                "MCP server import failed while probing %s", monitor.source_ref, exc_info=True
            )
            return {
                "status": monitor.status
                if _status_is_terminal(monitor.status)
                else MonitorStatus.UNKNOWN,
                "status_reason": f"mcp_server_unavailable:{exc}",
                "progress": monitor.progress,
                "log_sources": monitor.log_sources,
                "control_capabilities": self._control_capabilities(monitor.source_type),
            }

        run_payload = mcp_server.run_get(monitor.source_ref)
        if run_payload.get("ok") is not True:
            return {
                "status": monitor.status
                if _status_is_terminal(monitor.status)
                else MonitorStatus.UNKNOWN,
                "status_reason": "run_not_found",
                "progress": monitor.progress,
                "log_sources": monitor.log_sources,
                "control_capabilities": self._control_capabilities(monitor.source_type),
                "metadata": {
                    "run_id": monitor.source_ref,
                    "run_error": str(run_payload.get("error") or "run_not_found"),
                },
            }

        run = run_payload.get("run") or {}
        metrics_payload = mcp_server.run_metrics(monitor.source_ref)
        metrics = metrics_payload.get("metrics") if metrics_payload.get("ok") else {}
        run_dir_raw = run_payload.get("run_dir")
        log_sources = dict(monitor.log_sources)
        if isinstance(run_dir_raw, str) and run_dir_raw.strip():
            log_sources.update(self._discover_run_log_sources(Path(run_dir_raw)))

        steps = run.get("steps") or []
        step_statuses = [str((step or {}).get("status") or "").strip().lower() for step in steps]
        completed_steps = sum(
            1
            for status in step_statuses
            if status in {"succeeded", "failed", "skipped", "cancelled"}
        )
        progress = (
            round((completed_steps / len(step_statuses)) * 100.0, 2)
            if step_statuses
            else monitor.progress
        )
        active_step = next(
            (
                step
                for step in steps
                if str((step or {}).get("status") or "").strip().lower()
                in {"running", "claimed", "retrying"}
            ),
            None,
        )
        failed_step = next(
            (
                step
                for step in reversed(steps)
                if str((step or {}).get("status") or "").strip().lower() == "failed"
            ),
            None,
        )
        session_summary = ""
        if isinstance(active_step, dict):
            session_summary = _summarize_text(
                active_step.get("title") or active_step.get("step_id") or "MCP run in progress."
            )
        elif isinstance(failed_step, dict):
            session_summary = _summarize_text(
                failed_step.get("error")
                or failed_step.get("title")
                or failed_step.get("step_id")
                or "MCP run failed."
            )
        elif step_statuses:
            session_summary = f"{completed_steps}/{len(step_statuses)} steps complete."
        else:
            session_summary = f"MCP run {run.get('status') or 'unknown'}."

        status_reason = (
            run.get("error")
            or (active_step or {}).get("title")
            or (failed_step or {}).get("error")
            or run.get("status")
        )
        capabilities = self._control_capabilities(monitor.source_type)
        if _normalize_monitor_status(run.get("status")) in {
            MonitorStatus.COMPLETED,
            MonitorStatus.FAILED,
            MonitorStatus.CANCELLED,
        }:
            capabilities = [cap for cap in capabilities if cap != "cancel"]

        return {
            "status": _normalize_monitor_status(run.get("status")),
            "status_reason": _summarize_text(status_reason) if status_reason else None,
            "progress": progress,
            "log_sources": log_sources,
            "control_capabilities": capabilities,
            "metadata": {
                "run_id": monitor.source_ref,
                "run_dir": run_dir_raw,
                "run_status": run.get("status"),
                "active_step": (active_step or {}).get("title")
                or (active_step or {}).get("step_id"),
                "metrics": metrics,
                "session_summary": session_summary,
            },
        }

    async def _probe_coding_session(self, monitor: MonitoredExecution) -> dict[str, Any]:
        delegate = await self._resolve_coding_session_delegate(monitor)
        if delegate is not None:
            snapshot = await self._probe_monitor(delegate)
            thread_ref = monitor.thread_id or monitor.source_ref
            messages = await self._load_thread_messages(thread_ref)
            latest_message = messages[-1] if messages else None
            summary = snapshot.get("metadata", {}).get("session_summary") or (
                _summarize_text(latest_message.content) if latest_message else None
            )
            metadata = {
                **snapshot.get("metadata", {}),
                "thread_id": _normalize_thread_id(thread_ref),
            }
            if summary:
                metadata["session_summary"] = summary
            return {
                **snapshot,
                "metadata": metadata,
            }

        thread_ref = monitor.thread_id or monitor.source_ref
        messages = await self._load_thread_messages(thread_ref)
        latest_message = messages[-1] if messages else None
        latest_assistant = next(
            (message for message in reversed(messages) if message.role == "assistant"), None
        )
        latest_user = next(
            (message for message in reversed(messages) if message.role == "user"), None
        )
        latest_role = latest_message.role if latest_message else None
        session_summary = None
        if latest_assistant is not None:
            session_summary = _summarize_text(latest_assistant.content)
        elif latest_user is not None:
            session_summary = _summarize_text(latest_user.content)

        if latest_role == "user":
            status = MonitorStatus.RUNNING
            status_reason = "awaiting_reply"
        elif latest_role == "assistant":
            status = MonitorStatus.COMPLETED
            status_reason = "idle"
        elif messages:
            status = MonitorStatus.UNKNOWN
            status_reason = "session_has_messages"
        else:
            status = MonitorStatus.UNKNOWN
            status_reason = "session_not_started"

        return {
            "status": status,
            "status_reason": status_reason,
            "progress": None,
            "log_sources": monitor.log_sources,
            "control_capabilities": ["status", "ack"],
            "metadata": {
                "thread_id": _normalize_thread_id(thread_ref),
                "latest_role": latest_role,
                "last_message_at": latest_message.timestamp.isoformat()
                if latest_message
                else None,
                "session_summary": session_summary,
                "message_count": len(messages),
            },
        }

    async def _tail_logs(
        self, monitor: MonitoredExecution, *, request: MonitorActionRequest
    ) -> dict[str, Any]:
        if monitor.source_type == MonitorSourceType.SLURM_JOB:
            result = sherlock_job_logs(
                job_id=monitor.source_ref,
                stream=request.stream,
                tail=request.tail,
                grep=request.grep,
            )
            return {
                "stdout": result.get("stdout_text"),
                "stderr": result.get("stderr_text"),
                "log_sources": result.get("log_paths") or {},
            }

        if monitor.source_type == MonitorSourceType.BR_JOB:
            store = getattr(self._app.state, "job_store", None) if self._app else None
            text_by_stream: dict[str, str] = {}
            if store is not None and hasattr(store, "iter_logs"):
                chunks = await store.iter_logs(job_id=monitor.source_ref, start_offset=0, stream=None)
                grouped: dict[str, list[str]] = {"stdout": [], "stderr": []}
                for chunk in chunks:
                    if chunk.stream in grouped:
                        grouped[chunk.stream].append(
                            chunk.data.decode("utf-8", errors="replace")
                        )
                for stream_name, parts in grouped.items():
                    if parts:
                        text_by_stream[stream_name] = _tail_lines("".join(parts), request.tail)
            if not text_by_stream:
                text_by_stream = self._tail_file_logs(
                    monitor.log_sources,
                    tail=request.tail,
                    stream=request.stream,
                    grep=request.grep,
                )
            return {
                "stdout": text_by_stream.get("stdout"),
                "stderr": text_by_stream.get("stderr"),
                "log_sources": monitor.log_sources,
            }

        if monitor.source_type == MonitorSourceType.MCP_RUN:
            refreshed = await self.refresh_monitor(monitor, emit_transition=False)
            text_by_stream = self._tail_file_logs(
                refreshed.log_sources,
                tail=request.tail,
                stream=request.stream,
                grep=request.grep,
            )
            return {
                "stdout": text_by_stream.get("stdout"),
                "stderr": text_by_stream.get("stderr"),
                "log_sources": refreshed.log_sources,
            }

        if monitor.source_type == MonitorSourceType.CODING_SESSION:
            delegate = await self._resolve_coding_session_delegate(monitor)
            if delegate is None:
                return {"stdout": None, "stderr": None, "log_sources": monitor.log_sources}
            return await self._tail_logs(delegate, request=request)

        return {
            "stdout": self._tail_file_logs(
                monitor.log_sources,
                tail=request.tail,
                stream=request.stream,
                grep=request.grep,
            ).get("stdout"),
            "stderr": self._tail_file_logs(
                monitor.log_sources,
                tail=request.tail,
                stream=request.stream,
                grep=request.grep,
            ).get("stderr"),
            "log_sources": monitor.log_sources,
        }

    def _tail_file_logs(
        self,
        log_sources: dict[str, Any],
        *,
        tail: int,
        stream: Literal["stdout", "stderr", "both"],
        grep: str | None,
    ) -> dict[str, str]:
        def _read(path_str: str) -> str:
            path = Path(path_str).expanduser()
            if not path.exists():
                return ""
            text = path.read_text(encoding="utf-8", errors="replace")
            if grep:
                text = "\n".join(
                    line for line in text.splitlines() if grep.lower() in line.lower()
                )
            return _tail_lines(text, tail)

        result: dict[str, str] = {}
        if stream in {"stdout", "both"} and log_sources.get("stdout"):
            result["stdout"] = _read(str(log_sources["stdout"]))
        if stream in {"stderr", "both"} and log_sources.get("stderr"):
            result["stderr"] = _read(str(log_sources["stderr"]))
        if not result and log_sources.get("paths"):
            paths = list(log_sources.get("paths") or [])
            if paths:
                result["stdout"] = _read(str(paths[0]))
            if len(paths) > 1:
                result["stderr"] = _read(str(paths[1]))
        return result

    async def _cancel_monitor(
        self, monitor: MonitoredExecution, *, request: MonitorActionRequest
    ) -> dict[str, Any]:
        if "cancel" not in monitor.control_capabilities:
            raise HTTPException(status_code=400, detail="Cancel is not supported for this monitor")

        if monitor.source_type == MonitorSourceType.BR_JOB:
            if self._app is None:
                raise HTTPException(status_code=503, detail="BR job cancellation requires the orchestrator app runtime")
            payload = await self._call_app_post(
                f"/api/jobs/{monitor.source_ref}/cancel",
                params={"reason": request.reason or "Monitor requested cancellation"},
            )
            await self._append_monitor_event(
                monitor,
                "monitor.cancel_requested",
                {"action": "cancel", "result": payload},
            )
            return payload

        if monitor.source_type == MonitorSourceType.SLURM_JOB:
            cmd = ["scancel", monitor.source_ref]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or "scancel failed")
            await self._append_monitor_event(
                monitor,
                "monitor.cancel_requested",
                {"action": "cancel", "command": cmd},
            )
            return {"command": cmd, "stdout": proc.stdout.strip()}

        if monitor.source_type == MonitorSourceType.MCP_RUN:
            from brain_researcher.services.mcp import server as mcp_server

            payload = mcp_server.run_cancel(
                monitor.source_ref,
                reason=request.reason or "Session requested cancellation",
            )
            if payload.get("ok") is not True:
                raise HTTPException(
                    status_code=400,
                    detail=str(payload.get("error") or "run_cancel failed"),
                )
            await self._append_monitor_event(
                monitor,
                "monitor.cancel_requested",
                {"action": "cancel", "result": payload},
            )
            return payload

        if monitor.source_type == MonitorSourceType.CODING_SESSION:
            delegate = await self._resolve_coding_session_delegate(monitor)
            if delegate is None or "cancel" not in delegate.control_capabilities:
                raise HTTPException(
                    status_code=400,
                    detail="Cancel is not supported for this coding session",
                )
            if delegate.source_type == MonitorSourceType.BR_JOB:
                if self._app is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Coding session cancellation requires the orchestrator app runtime",
                    )
                payload = await self._call_app_post(
                    f"/api/jobs/{delegate.source_ref}/cancel",
                    params={"reason": request.reason or "Session requested cancellation"},
                )
            elif delegate.source_type == MonitorSourceType.MCP_RUN:
                from brain_researcher.services.mcp import server as mcp_server

                payload = mcp_server.run_cancel(
                    delegate.source_ref,
                    reason=request.reason or "Session requested cancellation",
                )
                if payload.get("ok") is not True:
                    raise HTTPException(
                        status_code=400,
                        detail=str(payload.get("error") or "run_cancel failed"),
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported coding session cancellation target",
                )
            await self._append_monitor_event(
                monitor,
                "monitor.cancel_requested",
                {
                    "action": "cancel",
                    "delegate_source_type": delegate.source_type.value,
                    "delegate_source_ref": delegate.source_ref,
                    "result": payload,
                },
            )
            return payload

        pid = int(monitor.source_ref)
        sig = signal.SIGKILL if request.force else signal.SIGTERM
        os.kill(pid, sig)
        updated = monitor.model_copy(
            update={
                "metadata": {
                    **monitor.metadata,
                    "cancel_requested_at": _utc_now().isoformat(),
                    "cancel_signal": sig.value,
                }
            }
        )
        store = await self._require_store()
        await store.upsert_monitor(updated.model_dump(mode="json"))
        await self._append_monitor_event(
            updated,
            "monitor.cancel_requested",
            {"action": "cancel", "signal": sig.value, "pid": pid},
        )
        return {"pid": pid, "signal": sig.value}

    async def _retry_monitor(self, monitor: MonitoredExecution) -> dict[str, Any]:
        if "retry" not in monitor.control_capabilities:
            raise HTTPException(status_code=400, detail="Retry is not supported for this monitor")
        if monitor.source_type != MonitorSourceType.BR_JOB or self._app is None:
            raise HTTPException(status_code=400, detail="Retry is only supported for Brain Researcher jobs")
        payload = await self._call_app_post(f"/api/jobs/{monitor.source_ref}/retry")
        await self._append_monitor_event(
            monitor, "monitor.retry_requested", {"action": "retry", "result": payload}
        )
        return payload

    async def _ack_monitor(self, monitor: MonitoredExecution) -> MonitoredExecution:
        updated = monitor.model_copy(
            update={
                "metadata": {
                    **monitor.metadata,
                    "acknowledged_at": _utc_now().isoformat(),
                },
                "updated_at": _utc_now(),
            }
        )
        store = await self._require_store()
        await store.upsert_monitor(updated.model_dump(mode="json"))
        await self._append_monitor_event(updated, "monitor.acknowledged", {})
        return updated

    async def _send_status_notifications(
        self,
        monitor: MonitoredExecution,
        previous_status: MonitorStatus,
    ) -> None:
        title = f"{monitor.display_name}: {monitor.status.value}"
        if previous_status == MonitorStatus.UNKNOWN:
            body = f"{monitor.display_name} is now {monitor.status.value}."
        else:
            body = (
                f"{monitor.display_name} changed from {previous_status.value} "
                f"to {monitor.status.value}."
            )

        await self._create_in_app_notification(monitor, title=title, body=body)
        if not monitor.thread_id:
            return
        store = await get_state_store()
        if store is None:
            return
        for raw in await store.list_chat_bridges(thread_id=monitor.thread_id):
            bridge = ChatBridge.model_validate(raw)
            try:
                if bridge.platform == "slack":
                    await self._post_slack_message(
                        channel_id=bridge.config["channel_id"],
                        text=body,
                        thread_ts=bridge.config.get("thread_ts"),
                    )
                elif bridge.platform == "discord":
                    await self._post_discord_webhook(
                        webhook_url=bridge.config["webhook_url"],
                        text=body,
                        username=bridge.config.get("display_name") or "Brain Researcher",
                    )
            except Exception:
                logger.exception(
                    "Failed to send %s notification for monitor %s",
                    bridge.platform,
                    monitor.id,
                )

    async def _create_in_app_notification(
        self, monitor: MonitoredExecution, *, title: str, body: str
    ) -> None:
        store = await get_state_store()
        if store is None:
            return
        notif_type = (
            NotificationType.JOB_FAILED
            if monitor.status == MonitorStatus.FAILED
            else NotificationType.JOB_COMPLETE
            if monitor.status in {MonitorStatus.COMPLETED, MonitorStatus.CANCELLED}
            else NotificationType.SYSTEM_ALERT
        )
        priority = (
            NotificationPriority.HIGH
            if monitor.status in {MonitorStatus.FAILED, MonitorStatus.CANCELLED}
            else NotificationPriority.NORMAL
        )
        notification = Notification(
            id=f"notif_{uuid.uuid4().hex[:12]}",
            user_id=monitor.owner_user_id,
            type=notif_type,
            priority=priority,
            title=title,
            message=body,
            data={"monitor_id": monitor.id, "thread_id": monitor.thread_id},
            action_url=f"/chat?thread={monitor.thread_id}" if monitor.thread_id else None,
            action_text="Open thread" if monitor.thread_id else None,
        )
        await store.upsert_notification(notification.model_dump(mode="json"))

    async def _resolve_slack_bridge(
        self, *, channel_id: str, thread_ts: str
    ) -> ChatBridge | None:
        store = await get_state_store()
        if store is None:
            return None
        for candidate in (
            _slack_bridge_key(channel_id, thread_ts),
            _slack_bridge_key(channel_id, None),
        ):
            raw = await store.get_chat_bridge_by_external(
                platform="slack", bridge_key=candidate
            )
            if raw is not None:
                return ChatBridge.model_validate(raw)
        return None

    async def _handle_chat_command(
        self, *, platform: str, bridge: ChatBridge, text: str
    ) -> bool:
        if not bridge.monitor_id:
            return False
        parts = text.strip().split()
        if not parts:
            return False
        verb = parts[0].lower()
        if verb not in {"status", "logs", "cancel", "retry", "ack"}:
            return False

        action = "tail_logs" if verb == "logs" else verb
        tail = 200
        if verb == "logs" and len(parts) > 1:
            try:
                tail = max(1, min(int(parts[1]), 2000))
            except ValueError:
                tail = 200
        result = await self.perform_action(
            bridge.monitor_id,
            action,
            MonitorActionRequest(tail=tail),
        )
        text_payload = self._format_action_result(result)
        if platform == "slack":
            await self._post_slack_message(
                channel_id=bridge.config["channel_id"],
                text=text_payload,
                thread_ts=bridge.config.get("thread_ts"),
            )
        return True

    def _format_action_result(self, result: dict[str, Any]) -> str:
        if "logs" in result:
            stdout = (result["logs"].get("stdout") or "").strip()
            stderr = (result["logs"].get("stderr") or "").strip()
            parts: list[str] = []
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            return "\n\n".join(parts) or "No logs available."
        monitor_payload = result.get("monitor")
        if isinstance(monitor_payload, dict):
            status = monitor_payload.get("status")
            name = monitor_payload.get("display_name") or monitor_payload.get("id")
            reason = monitor_payload.get("status_reason")
            if reason:
                return f"{name}: {status} ({reason})"
            return f"{name}: {status}"
        return json.dumps(result, indent=2, default=str)

    async def _enqueue_chat_message_via_app(
        self, *, thread_id: str, content: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        if self._app is None:
            raise HTTPException(status_code=503, detail="Chat mirroring requires the orchestrator app runtime")
        return await self._call_app_post(
            f"/threads/{thread_id}/messages",
            json_body={"content": content, "attachments": [], "metadata": metadata},
        )

    async def _call_app_post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._app is None:
            raise HTTPException(status_code=503, detail="App runtime not available")
        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://monitor-runtime"
        ) as client:
            response = await client.post(path, json=json_body, params=params)
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return {"text": response.text}

    def _verify_slack_request(self, body: bytes, headers: dict[str, str]) -> None:
        secret = _slack_signing_secret()
        if not secret:
            return
        timestamp = headers.get("x-slack-request-timestamp") or headers.get(
            "X-Slack-Request-Timestamp"
        )
        signature = headers.get("x-slack-signature") or headers.get("X-Slack-Signature")
        if not timestamp or not signature:
            raise HTTPException(status_code=401, detail="Missing Slack signature headers")
        base = f"v0:{timestamp}:".encode() + body
        expected = "v0=" + hmac.new(
            secret.encode("utf-8"), base, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    def _verify_discord_request(self, body: bytes, headers: dict[str, str]) -> None:
        public_key = _discord_public_key()
        if not public_key:
            return
        signature = headers.get("x-signature-ed25519") or headers.get(
            "X-Signature-Ed25519"
        )
        timestamp = headers.get("x-signature-timestamp") or headers.get(
            "X-Signature-Timestamp"
        )
        if not signature or not timestamp:
            raise HTTPException(status_code=401, detail="Missing Discord signature headers")
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
        except Exception as exc:  # pragma: no cover - optional dependency
            raise HTTPException(
                status_code=503,
                detail="cryptography is required for Discord signature verification",
            ) from exc

        verifier = Ed25519PublicKey.from_public_bytes(
            _decode_discord_hex_key(public_key)
        )
        try:
            verifier.verify(bytes.fromhex(signature), timestamp.encode("utf-8") + body)
        except InvalidSignature as exc:
            raise HTTPException(status_code=401, detail="Invalid Discord signature") from exc

    async def _post_slack_message(
        self, *, channel_id: str, text: str, thread_ts: str | None
    ) -> str | None:
        token = _slack_bot_token()
        if not token:
            raise HTTPException(status_code=503, detail="Slack bot token is not configured")
        payload: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        data = response.json()
        if response.status_code >= 400 or not data.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=f"Slack API error: {data.get('error') or response.text}",
            )
        return data.get("ts")

    async def _post_discord_webhook(
        self, *, webhook_url: str, text: str, username: str
    ) -> None:
        payload = {"content": text, "username": username}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(webhook_url, json=payload)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Discord webhook delivery failed")
