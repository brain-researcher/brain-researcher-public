#!/usr/bin/env python3
"""Reusable CLI for calling Brain Researcher MCP tools over HTTP JSON-RPC."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

DEFAULT_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_CLIENT_NAME = "call_http_tool"
DEFAULT_CLIENT_VERSION = "0.1.0"
DEFAULT_USER_AGENT = os.environ.get("BR_MCP_HTTP_USER_AGENT", "curl/8.7.1")
DEFAULT_TIMEOUT_S = float(os.environ.get("BR_MCP_HTTP_TIMEOUT_S", "20"))
DEFAULT_POLL_TIMEOUT_S = float(os.environ.get("BR_MCP_POLL_TIMEOUT_S", "300"))
DEFAULT_POLL_INTERVAL_S = float(os.environ.get("BR_MCP_POLL_INTERVAL_S", "2"))
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
TRACE_TEXT_TAIL_CHARS = 2000

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_RESOLVER = REPO_ROOT / "scripts" / "mcp" / "resolve_br_mcp_token.sh"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


def default_mcp_url() -> str:
    if os.environ.get("BR_MCP_HTTP_URL"):
        return str(os.environ["BR_MCP_HTTP_URL"])
    host = os.environ.get("BR_MCP_HOST", "127.0.0.1")
    port = os.environ.get("BR_MCP_PORT", "7000")
    mount_path = os.environ.get("BR_MCP_MOUNT_PATH", "/mcp")
    return f"http://{host}:{port}{mount_path}"


def resolve_mcp_token(explicit_token: str | None = None) -> str | None:
    token = str(explicit_token or os.environ.get("BR_MCP_TOKEN") or "").strip()
    if token:
        return token
    if not TOKEN_RESOLVER.exists():
        return None
    proc = subprocess.run(
        ["bash", str(TOKEN_RESOLVER)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    resolved = proc.stdout.strip()
    return resolved or None


def load_json_value(raw: str | None, *, default: Any) -> Any:
    if raw is None:
        return default
    text: str
    if raw == "-":
        text = sys.stdin.read()
    elif raw.startswith("@"):
        text = Path(raw[1:]).read_text(encoding="utf-8")
    else:
        text = raw
    if not text.strip():
        return default
    return json.loads(text)


def load_json_object(raw: str | None, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = load_json_value(raw, default=default or {})
    if not isinstance(loaded, dict):
        raise ValueError("JSON value must decode to an object")
    return loaded


def extract_first_sse_json(body_text: str) -> dict[str, Any] | None:
    for raw_line in body_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            decoded = json.loads(payload)
        except Exception:
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def write_json_output(payload: Any, *, output_path: str | None, compact: bool) -> None:
    text = json.dumps(
        payload,
        indent=None if compact else 2,
        sort_keys=True,
        default=str,
    )
    if not compact:
        text += "\n"
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if compact:
        sys.stdout.write("\n")


def emit_poll_progress(message: str, *, quiet: bool) -> None:
    if quiet:
        return
    print(message, file=sys.stderr, flush=True)


def find_run_id(value: Any) -> str | None:
    if isinstance(value, dict):
        run_id = value.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
        for child in value.values():
            resolved = find_run_id(child)
            if resolved:
                return resolved
        return None
    if isinstance(value, list):
        for child in value:
            resolved = find_run_id(child)
            if resolved:
                return resolved
    return None


def open_url(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate_text(value: Any, *, max_chars: int = TRACE_TEXT_TAIL_CHARS) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _extract_remote_command(cmd: list[str]) -> str | None:
    try:
        idx = cmd.index("--command")
    except ValueError:
        return None
    if idx + 1 >= len(cmd):
        return None
    remote = str(cmd[idx + 1] or "").strip()
    return remote or None


def infer_external_tool_name(cmd: list[str]) -> str:
    if not cmd:
        return "shell"
    base = Path(str(cmd[0])).name or "shell"
    if base != "gcloud":
        return base
    remote = (_extract_remote_command(cmd) or "").lower()
    if "kubectl" in remote:
        return "kubectl"
    if "docker" in remote:
        return "docker"
    return "gcloud"


def build_external_trace_rows(
    cmd: list[str],
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    returncode: int | None = None,
    stdout: Any = "",
    stderr: Any = "",
    timeout_s: float | None = None,
    timed_out: bool = False,
    error: str | None = None,
    duration_s: float | None = None,
) -> list[dict[str, Any]]:
    tool_name = infer_external_tool_name(cmd)
    command_str = shlex.join(str(part) for part in cmd)
    remote_command = _extract_remote_command(cmd)
    started = started_at or utc_now_iso()
    finished = finished_at or utc_now_iso()

    start_payload: dict[str, Any] = {
        "tool_name": tool_name,
        "command": [str(part) for part in cmd],
        "command_str": command_str,
    }
    if remote_command:
        start_payload["remote_command"] = remote_command

    finish_payload = dict(start_payload)
    if duration_s is not None:
        finish_payload["duration_s"] = round(float(duration_s), 3)
    if timeout_s is not None:
        finish_payload["timeout_s"] = float(timeout_s)
    if returncode is not None:
        finish_payload["returncode"] = int(returncode)
    if stdout:
        finish_payload["stdout_tail"] = _truncate_text(stdout)
    if stderr:
        finish_payload["stderr_tail"] = _truncate_text(stderr)
    if error:
        finish_payload["error"] = str(error)

    if timed_out:
        status = "timeout"
    elif returncode == 0:
        status = "success"
    else:
        status = "error"

    return [
        {
            "event_type": "tool.call.started",
            "tool_id": tool_name,
            "tool_name": tool_name,
            "timestamp": started,
            "payload": start_payload,
        },
        {
            "event_type": "tool.call.finished",
            "tool_id": tool_name,
            "tool_name": tool_name,
            "timestamp": finished,
            "status": status,
            "payload": {
                **finish_payload,
                "status": status,
            },
        },
    ]


class SupportsMCPToolCalls(Protocol):
    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        prime: bool = True,
        initialize: bool = True,
    ) -> dict[str, Any]: ...


class ResearchLoggingSession:
    """Best-effort client-side buffer for transcript rows and external trace rows."""

    def __init__(
        self,
        client: SupportsMCPToolCalls | None = None,
        *,
        source_client: str,
        session_id: str | None = None,
        client_session_id: str | None = None,
        source: str = "agent",
        prime: bool = True,
        initialize: bool = True,
    ) -> None:
        self.client = client
        self.source_client = source_client
        self.session_id = session_id
        self.client_session_id = client_session_id
        self.source = source
        self.prime = prime
        self.initialize = initialize
        self.transcript_context_key = "transcript"
        self.trace_context_key = "external_trace_events"
        self.transcript_rows: list[dict[str, Any]] = []
        self.trace_rows: list[dict[str, Any]] = []
        self.pending_post_session_payload: dict[str, Any] | None = None
        self.pending_post_session_question: str | None = None
        self.started = False

    @staticmethod
    def _response_payload(response: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {}
        payload = response.get("payload")
        if isinstance(payload, dict):
            return payload
        return response

    @staticmethod
    def _research_logging_directive(payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        directive = payload.get("_agent_directive", {}).get("research_logging", {})
        return directive if isinstance(directive, dict) else {}

    @staticmethod
    def _render_post_session_question(payload: dict[str, Any] | None) -> str | None:
        if not isinstance(payload, dict):
            return None
        suggested = payload.get("suggested_actions")
        if not isinstance(suggested, list):
            return None
        first_action = next((item for item in suggested if isinstance(item, dict)), None)
        if not isinstance(first_action, dict):
            return None
        tool_name = str(first_action.get("tool_name") or "").strip()
        if tool_name == "generate_research_trajectory_and_insights":
            return "Session closed. Do you want me to generate a durable session summary now?"
        label = str(first_action.get("label") or "").strip()
        if label:
            return f"Session closed. Do you want me to {label.lower()} now?"
        return "Session closed. Do you want me to run the suggested follow-up action now?"

    @staticmethod
    def _coerce_confirmation(value: bool | str) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"y", "yes", "ok", "okay", "sure", "go", "run", "do it"}:
            return True
        if normalized in {"n", "no", "skip", "later", "not now"}:
            return False
        return None

    def bind_client(self, client: SupportsMCPToolCalls) -> None:
        self.client = client

    def clear_pending_post_session_actions(self) -> None:
        self.pending_post_session_payload = None
        self.pending_post_session_question = None

    def pending_post_session_actions(self) -> list[dict[str, Any]]:
        payload = self.pending_post_session_payload
        if not isinstance(payload, dict):
            return []
        actions = payload.get("suggested_actions")
        if not isinstance(actions, list):
            return []
        return [dict(item) for item in actions if isinstance(item, dict)]

    def build_follow_up_question(self) -> str | None:
        return self.pending_post_session_question

    def observe_directive_payload(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        directive = self._research_logging_directive(payload)
        if not isinstance(directive, dict):
            return
        state = directive.get("state")
        if isinstance(state, dict):
            session_id = state.get("session_id")
            if isinstance(session_id, str) and session_id.strip():
                self.session_id = session_id.strip()
            preferred_transcript_key = state.get("preferred_transcript_context_key")
            if isinstance(preferred_transcript_key, str) and preferred_transcript_key.strip():
                self.transcript_context_key = preferred_transcript_key.strip()
            preferred_trace_key = state.get("preferred_trace_context_key")
            if isinstance(preferred_trace_key, str) and preferred_trace_key.strip():
                self.trace_context_key = preferred_trace_key.strip()
        actions = directive.get("actions")
        if not isinstance(actions, list):
            return
        prompt_payload = None
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "prompt_post_session_actions":
                continue
            candidate_payload = action.get("payload")
            if isinstance(candidate_payload, dict):
                prompt_payload = dict(candidate_payload)
                break
        if prompt_payload is not None:
            self.pending_post_session_payload = prompt_payload
            self.pending_post_session_question = self._render_post_session_question(
                prompt_payload
            )

    def record_message(
        self,
        *,
        role: str,
        content: str,
        timestamp: str | None = None,
        metadata: dict[str, Any] | None = None,
        name: str | None = None,
        kind: str | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": timestamp or utc_now_iso(),
        }
        if metadata:
            row["metadata"] = metadata
        if name:
            row["name"] = name
        if kind:
            row["kind"] = kind
        self.transcript_rows.append(row)

    def record_progress(self, message: str, **metadata: Any) -> None:
        row_metadata = metadata or None
        self.record_message(
            role="assistant",
            content=message,
            metadata=row_metadata,
            name=self.source_client,
            kind="progress",
        )

    def record_external_trace_rows(self, rows: list[dict[str, Any]]) -> None:
        self.trace_rows.extend(dict(row) for row in rows if isinstance(row, dict))

    def record_external_command(
        self,
        cmd: list[str],
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        returncode: int | None = None,
        stdout: Any = "",
        stderr: Any = "",
        timeout_s: float | None = None,
        timed_out: bool = False,
        error: str | None = None,
        duration_s: float | None = None,
    ) -> None:
        self.record_external_trace_rows(
            build_external_trace_rows(
                cmd,
                started_at=started_at,
                finished_at=finished_at,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                timeout_s=timeout_s,
                timed_out=timed_out,
                error=error,
                duration_s=duration_s,
            )
        )

    def start(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "error": "client_not_bound"}
        response = self.client.call_tool(
            "log_research_event",
            {
                "kind": "start",
                "content": content,
                "session_id": self.session_id,
                "client_session_id": self.client_session_id,
                "source_client": self.source_client,
                "source": self.source,
                "tags": tags or [],
                "context": context or {},
            },
            prime=self.prime,
            initialize=self.initialize,
        )
        payload = self._response_payload(response)
        self.observe_directive_payload(payload)
        self.started = bool(payload.get("ok"))
        return payload

    def close(
        self,
        *,
        goal: str,
        done: list[str],
        open_items: list[str],
        next_command: str,
        tags: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.client is None:
            return {"ok": False, "error": "client_not_bound"}
        merged_context = dict(context or {})
        if self.transcript_rows and self.transcript_context_key not in merged_context:
            merged_context[self.transcript_context_key] = list(self.transcript_rows)
        if self.trace_rows and self.trace_context_key not in merged_context:
            merged_context[self.trace_context_key] = list(self.trace_rows)
        response = self.client.call_tool(
            "write_session_snapshot",
            {
                "goal": goal,
                "done": done,
                "open": open_items,
                "next_command": next_command,
                "session_id": self.session_id,
                "client_session_id": self.client_session_id,
                "source_client": self.source_client,
                "source": self.source,
                "tags": tags or [],
                "context": merged_context,
            },
            prime=self.prime,
            initialize=self.initialize,
        )
        payload = self._response_payload(response)
        self.observe_directive_payload(payload)
        question = self.build_follow_up_question()
        if question:
            enriched_payload = dict(payload)
            enriched_payload["follow_up_question"] = question
            enriched_payload["post_session_actions"] = self.pending_post_session_actions()
            return enriched_payload
        return payload

    def confirm_post_session_actions(
        self,
        confirmation: bool | str,
        *,
        action_id: str | None = None,
    ) -> dict[str, Any]:
        decision = self._coerce_confirmation(confirmation)
        if decision is None:
            return {
                "ok": False,
                "error": "ambiguous_confirmation",
                "message": "Confirmation must clearly accept or decline the follow-up action.",
                "follow_up_question": self.pending_post_session_question,
            }
        if not decision:
            question = self.pending_post_session_question
            self.clear_pending_post_session_actions()
            return {
                "ok": True,
                "skipped": True,
                "reason": "user_declined",
                "follow_up_question": question,
            }
        if self.client is None:
            return {"ok": False, "error": "client_not_bound"}
        actions = self.pending_post_session_actions()
        if not actions:
            return {"ok": False, "error": "no_pending_post_session_actions"}
        selected_action = None
        if action_id:
            selected_action = next(
                (
                    item
                    for item in actions
                    if str(item.get("id") or "").strip() == action_id
                ),
                None,
            )
            if selected_action is None:
                return {
                    "ok": False,
                    "error": "unknown_post_session_action",
                    "message": f"No pending post-session action matched action_id={action_id!r}.",
                }
        else:
            selected_action = actions[0]
        tool_name = str(selected_action.get("tool_name") or "").strip()
        arguments = selected_action.get("arguments")
        if not tool_name:
            return {"ok": False, "error": "invalid_post_session_action"}
        self.clear_pending_post_session_actions()
        response = self.client.call_tool(
            tool_name,
            arguments if isinstance(arguments, dict) else {},
            prime=self.prime,
            initialize=self.initialize,
        )
        payload = self._response_payload(response)
        self.observe_directive_payload(payload)
        return payload


def run_subprocess_with_trace(
    cmd: list[str],
    *,
    timeout_s: float,
    check: bool = False,
    logger: ResearchLoggingSession | None = None,
) -> subprocess.CompletedProcess[str]:
    started_at = utc_now_iso()
    started_monotonic = time.time()
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        if logger is not None:
            logger.record_external_command(
                cmd,
                started_at=started_at,
                finished_at=utc_now_iso(),
                stdout=exc.stdout,
                stderr=exc.stderr,
                timeout_s=timeout_s,
                timed_out=True,
                error=str(exc),
                duration_s=time.time() - started_monotonic,
            )
        raise
    except Exception as exc:
        if logger is not None:
            logger.record_external_command(
                cmd,
                started_at=started_at,
                finished_at=utc_now_iso(),
                timeout_s=timeout_s,
                error=str(exc),
                duration_s=time.time() - started_monotonic,
            )
        raise

    if logger is not None:
        logger.record_external_command(
            cmd,
            started_at=started_at,
            finished_at=utc_now_iso(),
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            timeout_s=timeout_s,
            duration_s=time.time() - started_monotonic,
        )
    if check and proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"command failed: {' '.join(cmd)}")
    return proc


class HttpMCPClient:
    """Minimal stdlib-only MCP streamable HTTP client."""

    def __init__(
        self,
        *,
        url: str,
        token: str | None,
        timeout_s: float,
        session_id: str | None = None,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        client_name: str = DEFAULT_CLIENT_NAME,
        client_version: str = DEFAULT_CLIENT_VERSION,
        opener: Callable[[urllib.request.Request, float], Any] | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout_s = timeout_s
        self.session_id = session_id
        self.protocol_version = protocol_version
        self.client_name = client_name
        self.client_version = client_version
        self._opener = opener or open_url
        self._initialize_done = False
        self._rpc_counter = 0

    def _next_id(self) -> str:
        self._rpc_counter += 1
        return f"http-call-{self._rpc_counter}"

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    def _update_session_id(self, headers: dict[str, Any] | None) -> None:
        if not headers:
            return
        for key, value in headers.items():
            if str(key).lower() == "mcp-session-id" and value:
                self.session_id = str(value)
                return

    def _request(
        self,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, dict[str, Any], str]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        headers = self._base_headers()
        headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self.url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener(request, self.timeout_s) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = int(getattr(response, "status", response.getcode()))
                response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            status = int(exc.code)
            response_headers = dict((exc.headers or {}).items())
        self._update_session_id(response_headers)
        return status, response_headers, raw

    @staticmethod
    def _parse_rpc_body(
        *,
        status_code: int,
        headers: dict[str, Any],
        body: str,
    ) -> dict[str, Any]:
        content_type = str(headers.get("Content-Type", ""))
        if "text/event-stream" in content_type or body.lstrip().startswith(("data:", "event:")):
            parsed = extract_first_sse_json(body)
            if parsed is None:
                return {
                    "ok": False,
                    "error": "invalid_sse_response",
                    "http_status": status_code,
                    "body": body[:2000],
                }
            return parsed
        try:
            loaded = json.loads(body)
        except Exception:
            return {
                "ok": False,
                "error": "invalid_json_response",
                "http_status": status_code,
                "body": body[:2000],
            }
        if isinstance(loaded, dict):
            return loaded
        return {
            "ok": False,
            "error": "unexpected_json_response_type",
            "http_status": status_code,
            "body": body[:2000],
        }

    @staticmethod
    def extract_tools_call_payload(result_obj: Any) -> dict[str, Any]:
        if isinstance(result_obj, dict):
            structured = result_obj.get("structuredContent")
            if isinstance(structured, dict):
                return structured
            content = result_obj.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if not isinstance(text, str):
                        continue
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
            return result_obj
        return {"ok": True, "result": result_obj}

    def prime_session(self) -> dict[str, Any]:
        request = urllib.request.Request(
            self.url,
            headers=self._base_headers(),
            method="GET",
        )
        try:
            with self._opener(request, self.timeout_s) as response:
                status = int(getattr(response, "status", response.getcode()))
                response_headers = dict(response.headers.items())
                body = ""
        except Exception as exc:
            return {
                "ok": False,
                "url": self.url,
                "error": str(exc),
                "session_id": self.session_id,
            }
        self._update_session_id(response_headers)
        ok = status in {200, 204, 406}
        result = {
            "ok": ok,
            "url": self.url,
            "http_status": status,
            "session_id": self.session_id,
        }
        if not ok:
            result["body"] = body[:1000]
        elif body.strip():
            result["body"] = body[:1000]
        return result

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        status, headers, body = self._request(method="POST", payload=payload)
        envelope = self._parse_rpc_body(status_code=status, headers=headers, body=body)
        ok = status == 200 and isinstance(envelope, dict) and "error" not in envelope
        return {
            "ok": ok,
            "method": method,
            "params": params or {},
            "http_status": status,
            "session_id": self.session_id,
            "envelope": envelope,
        }

    def initialize(self, *, prime: bool = True) -> dict[str, Any]:
        primed = None
        if prime:
            primed = self.prime_session()
        response = self.rpc(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_name,
                    "version": self.client_version,
                },
            },
        )
        response["primed"] = primed
        if response.get("ok"):
            self._initialize_done = True
        return response

    def initialize_once(self, *, prime: bool = True) -> dict[str, Any] | None:
        if self._initialize_done:
            return None
        return self.initialize(prime=prime)

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        prime: bool = True,
        initialize: bool = True,
    ) -> dict[str, Any]:
        primed = None
        initialize_result = None
        if initialize:
            initialize_result = self.initialize_once(prime=prime)
            if isinstance(initialize_result, dict):
                primed = initialize_result.get("primed")
        elif prime:
            primed = self.prime_session()
        response = self.rpc(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )
        payload = None
        if response.get("ok"):
            payload = self.extract_tools_call_payload(
                response.get("envelope", {}).get("result")
            )
        response.update(
            {
                "tool_name": tool_name,
                "arguments": arguments or {},
                "primed": primed,
                "payload": payload,
                "initialized": initialize_result,
            }
        )
        return response


def poll_run_get(
    client: HttpMCPClient,
    run_id: str,
    *,
    timeout_s: float,
    interval_s: float,
    heartbeat_s: float,
    quiet: bool,
    prime: bool = True,
    initialize: bool = True,
) -> dict[str, Any]:
    started = time.time()
    deadline = started + timeout_s
    last_status: str | None = None
    last_heartbeat = 0.0
    attempts = 0
    last_response: dict[str, Any] | None = None
    while time.time() < deadline:
        attempts += 1
        last_response = client.call_tool(
            "run_get",
            {"run_id": run_id},
            prime=prime if attempts == 1 else False,
            initialize=initialize,
        )
        payload = last_response.get("payload")
        run = payload.get("run") if isinstance(payload, dict) else None
        status = str(run.get("status") or "") if isinstance(run, dict) else ""
        now = time.time()
        if status != last_status or now - last_heartbeat >= heartbeat_s:
            emit_poll_progress(
                f"[poll] run_id={run_id} status={status or 'unknown'} elapsed_s={round(now - started, 1)} attempt={attempts}",
                quiet=quiet,
            )
            last_status = status
            last_heartbeat = now
        if (
            last_response.get("ok")
            and isinstance(payload, dict)
            and status in TERMINAL_RUN_STATUSES
        ):
            return {
                "ok": status == "succeeded",
                "run_id": run_id,
                "status": status,
                "attempts": attempts,
                "elapsed_s": round(now - started, 3),
                "response": last_response,
                "payload": payload,
            }
        time.sleep(interval_s)
    return {
        "ok": False,
        "error": "poll_timeout",
        "run_id": run_id,
        "attempts": attempts,
        "elapsed_s": round(time.time() - started, 3),
        "last_response": last_response,
    }


def build_client_from_args(args: argparse.Namespace) -> HttpMCPClient:
    token = resolve_mcp_token(getattr(args, "token", None))
    return HttpMCPClient(
        url=args.url,
        token=token,
        timeout_s=float(args.timeout_s),
        session_id=getattr(args, "session_id", None),
        protocol_version=args.protocol_version,
        client_name=args.client_name,
        client_version=args.client_version,
    )


def handle_prime(args: argparse.Namespace) -> tuple[int, Any]:
    client = build_client_from_args(args)
    result = client.prime_session()
    return (0 if result.get("ok") else 1), result


def handle_initialize(args: argparse.Namespace) -> tuple[int, Any]:
    client = build_client_from_args(args)
    result = client.initialize(prime=not args.no_prime)
    return (0 if result.get("ok") else 1), result


def handle_rpc(args: argparse.Namespace) -> tuple[int, Any]:
    client = build_client_from_args(args)
    params = load_json_object(args.params, default={})
    primed = None
    initialized = None
    if args.prime:
        primed = client.prime_session()
    if args.initialize_first:
        initialized = client.initialize(prime=False)
    result = client.rpc(args.method, params)
    result["primed"] = primed
    result["initialized"] = initialized
    return (0 if result.get("ok") else 1), result


def handle_call(args: argparse.Namespace) -> tuple[int, Any]:
    client = build_client_from_args(args)
    arguments = load_json_object(args.args, default={})
    result = client.call_tool(
        args.tool_name,
        arguments,
        prime=not args.no_prime,
        initialize=not args.no_initialize,
    )

    poll_result = None
    if args.poll_run:
        run_id = args.run_id or find_run_id(result.get("payload"))
        if not run_id:
            result["poll_error"] = "poll requested but no run_id was provided or returned"
            if args.result_only:
                return 1, {"ok": False, "error": result["poll_error"], "call": result}
            return 1, result
        poll_result = poll_run_get(
            client,
            run_id,
            timeout_s=float(args.poll_timeout_s),
            interval_s=float(args.poll_interval_s),
            heartbeat_s=float(args.poll_heartbeat_s),
            quiet=bool(args.quiet_poll),
            prime=False,
            initialize=not args.no_initialize,
        )
        result["poll"] = poll_result

    if args.result_only:
        if poll_result is not None:
            return (0 if poll_result.get("ok") else 1), poll_result.get("payload") or poll_result
        payload = result.get("payload")
        if payload is None:
            return (0 if result.get("ok") else 1), result
        return (0 if result.get("ok") else 1), payload

    exit_code = 0 if result.get("ok") else 1
    if poll_result is not None and not poll_result.get("ok"):
        exit_code = 1
    return exit_code, result


def handle_poll_run(args: argparse.Namespace) -> tuple[int, Any]:
    client = build_client_from_args(args)
    if not args.no_initialize:
        client.initialize_once(prime=not args.no_prime)
    elif not args.no_prime:
        client.prime_session()
    result = poll_run_get(
        client,
        args.run_id,
        timeout_s=float(args.poll_timeout_s),
        interval_s=float(args.poll_interval_s),
        heartbeat_s=float(args.poll_heartbeat_s),
        quiet=bool(args.quiet_poll),
        prime=False,
        initialize=False,
    )
    return (0 if result.get("ok") else 1), result


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default=default_mcp_url(), help="MCP HTTP endpoint.")
    common.add_argument("--token", default=None, help="Bearer token. Defaults to BR_MCP_TOKEN or resolver script.")
    common.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="HTTP request timeout in seconds.",
    )
    common.add_argument(
        "--session-id",
        default=None,
        help="Optional existing mcp-session-id to reuse.",
    )
    common.add_argument(
        "--protocol-version",
        default=DEFAULT_PROTOCOL_VERSION,
        help="MCP protocol version used during initialize.",
    )
    common.add_argument(
        "--client-name",
        default=DEFAULT_CLIENT_NAME,
        help="clientInfo.name used during initialize.",
    )
    common.add_argument(
        "--client-version",
        default=DEFAULT_CLIENT_VERSION,
        help="clientInfo.version used during initialize.",
    )
    common.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path.",
    )
    common.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact one-line JSON instead of pretty JSON.",
    )

    parser = argparse.ArgumentParser(
        description="Call Brain Researcher MCP tools over HTTP JSON-RPC.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "prime",
        parents=[common],
        help="Prime an HTTP MCP session with a GET request.",
    )

    initialize = subparsers.add_parser(
        "initialize",
        parents=[common],
        help="Send initialize after optional session priming.",
    )
    initialize.add_argument(
        "--no-prime",
        action="store_true",
        help="Skip the initial session-prime GET before initialize.",
    )

    rpc = subparsers.add_parser(
        "rpc",
        parents=[common],
        help="Send a raw JSON-RPC method with JSON params.",
    )
    rpc.add_argument("method", help="JSON-RPC method name, for example tools/list.")
    rpc.add_argument(
        "--params",
        default="{}",
        help="Inline JSON, @file, or - for stdin.",
    )
    rpc.add_argument(
        "--prime",
        action="store_true",
        help="Prime the session before sending the RPC method.",
    )
    rpc.add_argument(
        "--initialize-first",
        action="store_true",
        help="Send initialize before the requested RPC method.",
    )

    call = subparsers.add_parser(
        "call",
        parents=[common],
        help="Call tools/call with JSON arguments.",
    )
    call.add_argument("tool_name", help="Tool name for tools/call.")
    call.add_argument(
        "--args",
        default="{}",
        help="Inline JSON, @file, or - for stdin.",
    )
    call.add_argument(
        "--no-prime",
        action="store_true",
        help="Skip the initial session-prime GET.",
    )
    call.add_argument(
        "--no-initialize",
        action="store_true",
        help="Skip automatic initialize before tools/call.",
    )
    call.add_argument(
        "--poll-run",
        action="store_true",
        help="After the tool call, poll run_get until a terminal run status.",
    )
    call.add_argument(
        "--run-id",
        default=None,
        help="Explicit run_id to poll instead of discovering one from the tool payload.",
    )
    call.add_argument(
        "--poll-timeout-s",
        type=float,
        default=DEFAULT_POLL_TIMEOUT_S,
        help="Maximum polling time in seconds.",
    )
    call.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help="Polling interval in seconds.",
    )
    call.add_argument(
        "--poll-heartbeat-s",
        type=float,
        default=5.0,
        help="Minimum interval between repeated progress lines to stderr.",
    )
    call.add_argument(
        "--quiet-poll",
        action="store_true",
        help="Suppress polling progress lines on stderr.",
    )
    call.add_argument(
        "--result-only",
        action="store_true",
        help="Print the extracted tool payload, or the final poll payload when polling.",
    )

    poll_run = subparsers.add_parser(
        "poll-run",
        parents=[common],
        help="Poll the run_get tool for an existing run_id.",
    )
    poll_run.add_argument("run_id", help="Run identifier returned by a previous call.")
    poll_run.add_argument(
        "--no-prime",
        action="store_true",
        help="Skip the initial session-prime GET.",
    )
    poll_run.add_argument(
        "--no-initialize",
        action="store_true",
        help="Skip automatic initialize before polling run_get.",
    )
    poll_run.add_argument(
        "--poll-timeout-s",
        type=float,
        default=DEFAULT_POLL_TIMEOUT_S,
        help="Maximum polling time in seconds.",
    )
    poll_run.add_argument(
        "--poll-interval-s",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help="Polling interval in seconds.",
    )
    poll_run.add_argument(
        "--poll-heartbeat-s",
        type=float,
        default=5.0,
        help="Minimum interval between repeated progress lines to stderr.",
    )
    poll_run.add_argument(
        "--quiet-poll",
        action="store_true",
        help="Suppress polling progress lines on stderr.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prime":
            exit_code, payload = handle_prime(args)
        elif args.command == "initialize":
            exit_code, payload = handle_initialize(args)
        elif args.command == "rpc":
            exit_code, payload = handle_rpc(args)
        elif args.command == "call":
            exit_code, payload = handle_call(args)
        elif args.command == "poll-run":
            exit_code, payload = handle_poll_run(args)
        else:  # pragma: no cover - argparse enforces the set
            raise ValueError(f"unsupported command: {args.command}")
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "command": args.command}
        write_json_output(payload, output_path=args.output, compact=args.compact)
        return 1
    write_json_output(payload, output_path=args.output, compact=args.compact)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
