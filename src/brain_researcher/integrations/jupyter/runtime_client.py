"""Helpers for executing code against a stateful Jupyter Server session."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import websockets

UTC = timezone.utc


def _normalize_base_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Jupyter base URL is required")
    return value.rstrip("/")


def _build_http_url(base_url: str, path: str) -> str:
    parsed = urlsplit(_normalize_base_url(base_url))
    full_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    return urlunsplit((parsed.scheme, parsed.netloc, full_path, "", ""))


def _build_ws_url(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    query: dict[str, str] | None = None,
) -> str:
    parsed = urlsplit(_normalize_base_url(base_url))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    full_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    query_items = dict(query or {})
    if token:
        query_items.setdefault("token", token)
    return urlunsplit(
        (
            scheme,
            parsed.netloc,
            full_path,
            urlencode(query_items),
            "",
        )
    )


def _auth_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"token {token}"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class JupyterRuntimeTarget:
    base_url: str
    token: str | None = None
    kernel_name: str = "python3"
    session_name: str = "Brain Researcher Studio"
    session_path: str = "studio/session"
    session_type: str = "console"
    working_directory: str | None = None

    @property
    def normalized_base_url(self) -> str:
        return _normalize_base_url(self.base_url)


@dataclass(frozen=True)
class JupyterRuntimeHandle:
    session_id: str
    kernel_id: str
    kernel_name: str


@dataclass(frozen=True)
class JupyterExecutionResult:
    status: str
    execution_count: int | None
    stdout: str
    stderr: str
    outputs: list[dict[str, Any]]
    summary: str
    error_name: str | None = None
    error_value: str | None = None


def _wrap_python_code(
    code: str,
    *,
    working_directory: str | None,
    env: dict[str, str] | None,
) -> str:
    prologue: list[str] = []
    if working_directory or env:
        prologue.append("import os")
    if working_directory:
        prologue.append(f"os.makedirs({working_directory!r}, exist_ok=True)")
        prologue.append(f"os.chdir({working_directory!r})")
    for key, value in sorted((env or {}).items()):
        prologue.append(f"os.environ[{key!r}] = {value!r}")
    if not prologue:
        return code
    return "\n".join([*prologue, "", code])


async def get_session(
    target: JupyterRuntimeTarget,
    session_id: str,
    *,
    timeout_seconds: int | None = None,
) -> dict[str, Any] | None:
    timeout = float(timeout_seconds or 30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            _build_http_url(target.normalized_base_url, f"/api/sessions/{session_id}"),
            headers=_auth_headers(target.token),
        )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def list_sessions(
    target: JupyterRuntimeTarget,
    *,
    timeout_seconds: int | None = None,
) -> list[dict[str, Any]]:
    timeout = float(timeout_seconds or 30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            _build_http_url(target.normalized_base_url, "/api/sessions"),
            headers=_auth_headers(target.token),
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def create_session(
    target: JupyterRuntimeTarget,
    *,
    timeout_seconds: int | None = None,
) -> JupyterRuntimeHandle:
    timeout = float(timeout_seconds or 30)
    payload = {
        "kernel": {"name": target.kernel_name},
        "name": target.session_name,
        "path": target.session_path,
        "type": target.session_type,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _build_http_url(target.normalized_base_url, "/api/sessions"),
            headers={
                "Content-Type": "application/json",
                **_auth_headers(target.token),
            },
            json=payload,
        )
    response.raise_for_status()
    data = response.json()
    kernel = dict(data.get("kernel") or {})
    return JupyterRuntimeHandle(
        session_id=str(data["id"]),
        kernel_id=str(kernel["id"]),
        kernel_name=str(kernel.get("name") or target.kernel_name),
    )


async def ensure_session(
    target: JupyterRuntimeTarget,
    *,
    existing_session_id: str | None,
    timeout_seconds: int | None = None,
) -> JupyterRuntimeHandle:
    if existing_session_id:
        existing = await get_session(
            target,
            existing_session_id,
            timeout_seconds=timeout_seconds,
        )
        if existing is not None:
            kernel = dict(existing.get("kernel") or {})
            kernel_id = str(kernel.get("id") or "").strip()
            if kernel_id:
                return JupyterRuntimeHandle(
                    session_id=str(existing["id"]),
                    kernel_id=kernel_id,
                    kernel_name=str(kernel.get("name") or target.kernel_name),
                )
    existing_sessions = await list_sessions(target, timeout_seconds=timeout_seconds)
    for item in existing_sessions:
        if item.get("path") != target.session_path and item.get("name") != target.session_name:
            continue
        kernel = dict(item.get("kernel") or {})
        kernel_id = str(kernel.get("id") or "").strip()
        if not kernel_id:
            continue
        return JupyterRuntimeHandle(
            session_id=str(item["id"]),
            kernel_id=kernel_id,
            kernel_name=str(kernel.get("name") or target.kernel_name),
        )
    return await create_session(target, timeout_seconds=timeout_seconds)


async def interrupt_kernel(
    target: JupyterRuntimeTarget,
    *,
    kernel_id: str,
    timeout_seconds: int | None = None,
) -> None:
    timeout = float(timeout_seconds or 15)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _build_http_url(
                target.normalized_base_url,
                f"/api/kernels/{kernel_id}/interrupt",
            ),
            headers=_auth_headers(target.token),
        )
    response.raise_for_status()


def _execution_summary(status: str, error_value: str | None) -> str:
    if status == "ok":
        return "Execution completed on the bound Jupyter kernel"
    return error_value or "Execution failed on the bound Jupyter kernel"


async def execute_python_code(
    target: JupyterRuntimeTarget,
    *,
    handle: JupyterRuntimeHandle,
    code: str,
    working_directory: str | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
) -> JupyterExecutionResult:
    timeout = float(timeout_seconds or 60)
    ws_url = _build_ws_url(
        target.normalized_base_url,
        f"/api/kernels/{handle.kernel_id}/channels",
        token=target.token,
        query={"session_id": handle.session_id},
    )
    client_session_id = uuid.uuid4().hex
    msg_id = f"msg_{uuid.uuid4().hex}"
    message = {
        "channel": "shell",
        "header": {
            "msg_id": msg_id,
            "msg_type": "execute_request",
            "session": client_session_id,
            "username": "brain-researcher",
            "date": _now_iso(),
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "content": {
            "code": _wrap_python_code(
                code,
                working_directory=working_directory or target.working_directory,
                env=env or {},
            ),
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": True,
        },
    }
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    outputs: list[dict[str, Any]] = []
    status = "ok"
    error_name: str | None = None
    error_value: str | None = None
    execution_count: int | None = None
    execute_reply_seen = False
    idle_seen = False

    async with websockets.connect(
        ws_url,
        additional_headers=_auth_headers(target.token),
        open_timeout=timeout,
        close_timeout=min(timeout, 10.0),
    ) as websocket:
        await websocket.send(json.dumps(message))
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(raw)
            parent_header = dict(payload.get("parent_header") or {})
            if parent_header.get("msg_id") != msg_id:
                continue
            header = dict(payload.get("header") or {})
            msg_type = str(payload.get("msg_type") or header.get("msg_type") or "")
            content = dict(payload.get("content") or {})
            if msg_type == "status":
                if content.get("execution_state") == "idle":
                    idle_seen = True
                    if execute_reply_seen:
                        break
            elif msg_type == "execute_input":
                execution_count = content.get("execution_count")
            elif msg_type == "execute_reply":
                execute_reply_seen = True
                execution_count = content.get("execution_count") or execution_count
                if content.get("status") == "error":
                    status = "error"
                    error_name = content.get("ename")
                    error_value = content.get("evalue")
                if idle_seen:
                    break
            elif msg_type == "stream":
                text = str(content.get("text") or "")
                if content.get("name") == "stderr":
                    stderr_parts.append(text)
                else:
                    stdout_parts.append(text)
            elif msg_type in {"display_data", "execute_result"}:
                outputs.append(
                    {
                        "type": msg_type,
                        "data": content.get("data") or {},
                        "metadata": content.get("metadata") or {},
                        "execution_count": content.get("execution_count"),
                    }
                )
            elif msg_type == "error":
                status = "error"
                error_name = content.get("ename")
                error_value = content.get("evalue")
                traceback_text = "\n".join(content.get("traceback") or [])
                if traceback_text:
                    stderr_parts.append(traceback_text)

    return JupyterExecutionResult(
        status=status,
        execution_count=execution_count,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        outputs=outputs,
        summary=_execution_summary(status, error_value),
        error_name=error_name,
        error_value=error_value,
    )
