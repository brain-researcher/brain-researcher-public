"""UI-facing API Blueprint for the Agent service.

Thin wrappers over existing chat/act/tool logic so the web UI can talk to
`/api/*` without mutating Flask request objects or depending on orchestrator
routes. Keep business logic in existing functions; this module just adapts
payloads and avoids circular imports by importing lazily inside handlers.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import uuid
import threading
import time
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import requests as req_lib
from flask import (
    Blueprint,
    Response,
    jsonify,
    request,
    send_file,
    stream_with_context,
    current_app,
)

logger = logging.getLogger(__name__)

KG_MULTIHOP_LEGACY_OUTPUTS_WARNING = "deprecation:kg_multihop_qa:data.outputs"


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (no external dependency)
# ---------------------------------------------------------------------------
_rate_limit_cache: Dict[str, List[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()


def check_rate_limit(key: str, max_requests: int = 10, window_sec: int = 60) -> bool:
    """Simple in-memory rate limiter. Returns True if request allowed."""
    now = time.time()
    with _rate_limit_lock:
        # Clean old entries
        _rate_limit_cache[key] = [
            t for t in _rate_limit_cache[key] if now - t < window_sec
        ]
        if len(_rate_limit_cache[key]) >= max_requests:
            return False
        _rate_limit_cache[key].append(now)
        return True


def api_error(
    code: str, detail: str, status: int = 500, retry_after: int | None = None
):
    """Return standardized error response.

    Format: {"error": code, "detail": message, "retry_after": seconds|null}

    Args:
        code: Short error code (e.g., 'auth_required', 'not_found', 'rate_limited')
        detail: Human-readable message
        status: HTTP status code
        retry_after: Seconds until retry allowed (for 429 responses)
    """
    body: dict = {"error": code, "detail": detail}
    if retry_after is not None:
        body["retry_after"] = retry_after
    return jsonify(body), status


ui_api = Blueprint("ui_api", __name__)


# Job service (JobStore-backed for run persistence)
def _get_job_service():
    from brain_researcher.services.agent.job_service import get_job_service

    return get_job_service()


# Thread store (Redis-backed with fakeredis fallback)
def _get_thread_store():
    from brain_researcher.services.agent.thread_store import get_thread_store

    return get_thread_store()


def _json() -> Dict[str, Any]:
    """Safe JSON extractor."""
    return request.get_json(silent=True) or {}


from brain_researcher.services.agent.kg_multihop_preview import (  # noqa: F401
    _normalize_tool_name,
    _is_kg_multihop_qa_tool_call,
    _extract_kg_multihop_arguments,
    _extract_kg_multihop_payload,
    _multihop_node_label,
    _format_multihop_path_preview,
    _build_kg_multihop_result_preview,
    _attach_kg_multihop_previews,
)


def _check_thread_access(
    thread_id: str, user_id: str, tenant_id: str = "default"
) -> bool:
    """Check if user has access to thread (owner or public)."""
    store = _get_thread_store()
    return store.check_access(thread_id, user_id, tenant_id=tenant_id)


def _add_message(
    thread_id: str,
    role: str,
    content: str,
    user_id: str | None = None,
    tenant_id: str = "default",
    **extra: Any,
) -> Dict[str, Any]:
    store = _get_thread_store()
    message_id = extra.pop("id", None) or str(uuid.uuid4())

    message = store.add_message(
        thread_id=thread_id,
        message_id=message_id,
        role=role,
        content=content,
        user_id=user_id,
        tenant_id=tenant_id,
        **extra,
    )
    return message.to_dict()


def _normalize_checkpoint_ctx_ingress(
    ctx_value: Any, payload: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Normalize legacy checkpoint request fields into canonical ctx.resume_checkpoint_id."""
    merged = dict(ctx_value) if isinstance(ctx_value, dict) else {}
    source = payload if isinstance(payload, dict) else {}

    resume_checkpoint_id = (
        source.get("resume_checkpoint_id")
        or source.get("resumeCheckpointId")
        or source.get("checkpoint_id")
        or source.get("checkpointId")
        or merged.get("resume_checkpoint_id")
        or merged.get("resumeCheckpointId")
        or merged.get("checkpoint_id")
        or merged.get("checkpointId")
    )

    if resume_checkpoint_id:
        merged["resume_checkpoint_id"] = str(resume_checkpoint_id)
    merged.pop("resumeCheckpointId", None)
    merged.pop("checkpoint_id", None)
    merged.pop("checkpointId", None)
    return merged


def _normalize_checkpoint_metadata(metadata: Any) -> Dict[str, Any]:
    """Normalize checkpoint metadata to canonical metadata.checkpoint_id."""
    normalized = dict(metadata) if isinstance(metadata, dict) else {}
    checkpoint_id = (
        normalized.get("checkpoint_id")
        or normalized.get("checkpointId")
        or normalized.get("last_checkpoint_id")
        or normalized.get("lastCheckpointId")
    )
    normalized.pop("last_checkpoint_id", None)
    normalized.pop("lastCheckpointId", None)
    normalized.pop("checkpointId", None)
    if checkpoint_id:
        normalized["checkpoint_id"] = str(checkpoint_id)
    return normalized


from brain_researcher.services.agent.query_context_helpers import (  # noqa: F401,E402
    _truncate_text,
    _normalize_history_messages,
    _resolve_history_from_payload_or_thread,
    _resolve_history_from_payload_or_thread_with_source,
    _extract_plan_context,
    _extract_repair_context,
    _format_plan_context_lines,
    _repair_examples_block,
    _augment_query_with_context,
)


from brain_researcher.services.agent.clarification_helpers import (  # noqa: F401,E402
    _is_generic_clarification_decision,
    _clarification_key,
    _pending_question_text,
    _normalize_resolution_reply,
    _match_resolution_choice,
    _queue_generic_clarifications,
    _query_has_dataset_or_subject_reference,
    _legacy_info_gap_questions,
    _clarification_anchor_from_history,
    _build_effective_clarified_user_content,
    _build_legacy_clarification_result,
    _maybe_legacy_clarification_result,
)

# ---------------------------------------------------------------------------
# Health & config
# ---------------------------------------------------------------------------


@ui_api.get("/health")
def api_health():
    return {"status": "ok"}


def _planner_catalog_health() -> Dict[str, Any]:
    """Load and report the effective planner catalog mode."""

    from brain_researcher.services.agent.planner import catalog_loader

    catalog_loader.get_capability_index()
    return catalog_loader.get_catalog_status()


@ui_api.get("/health/full")
def api_health_full():
    """
    Aggregated health for UI/status page.

    Contracts:
    - Always returns 200 with status field; individual component errors captured in detail.
    - Downstream outages are reflected in `status` = degraded/down.
    """
    started = time.perf_counter()
    components: List[Dict[str, Any]] = []
    overall_status = "ok"

    def _record(
        name: str,
        status: str,
        latency_ms: Optional[float],
        detail: Optional[str] = None,
    ):
        nonlocal overall_status
        components.append(
            {
                "name": name,
                "status": status,
                "latency_ms": latency_ms,
                **({"detail": detail} if detail else {}),
            }
        )
        if status == "down":
            overall_status = "down"
        elif status == "degraded" and overall_status != "down":
            overall_status = "degraded"

    # Agent (self)
    _record("agent", "ok", 0.0)

    # Planner catalog mode/status. This makes catalog failures and legacy fallback
    # visible without changing planner behavior.
    planner_catalog: Dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        planner_catalog = _planner_catalog_health()
        latency = (time.perf_counter() - t0) * 1000
        raw_status = str(planner_catalog.get("status") or "unknown").lower()
        if raw_status == "ok":
            component_status = "ok"
            detail = None
        else:
            component_status = "degraded"
            detail = str(planner_catalog.get("reason") or raw_status)
        _record("planner_catalog", component_status, latency, detail)
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000
        planner_catalog = {
            "status": "down",
            "planner_mode": "unknown",
            "loaded": False,
            "tool_count": 0,
            "bad_rows": 0,
            "source": None,
            "reason": f"error={exc}",
        }
        _record("planner_catalog", "down", latency, f"error={exc}")

    # BR-KG
    br_kg_url = os.getenv("BR_KG_API_URL")
    if not br_kg_url:
        try:
            from brain_researcher.services.agent.config import resolve_br_kg_url

            br_kg_url = resolve_br_kg_url()
        except Exception as exc:  # pragma: no cover - fallback path
            _record("br_kg", "degraded", None, f"unresolved: {exc}")
            br_kg_url = None

    if br_kg_url:
        t0 = time.perf_counter()
        try:
            resp = req_lib.get(f"{br_kg_url}/health", timeout=1.5)
            latency = (time.perf_counter() - t0) * 1000
            if resp.ok:
                _record("br_kg", "ok", latency)
            else:
                _record("br_kg", "degraded", latency, f"status={resp.status_code}")
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            _record("br_kg", "down", latency, f"error={exc}")

    # Neo4j stats (from BR-KG /health/stats)
    neo4j_stats: Dict[str, Any] = {}
    if br_kg_url:
        t0 = time.perf_counter()
        try:
            stats_resp = req_lib.get(f"{br_kg_url}/health/stats", timeout=2.0)
            latency = (time.perf_counter() - t0) * 1000
            if stats_resp.ok:
                neo4j_stats = stats_resp.json()
                _record("neo4j", "ok", latency)
            else:
                _record(
                    "neo4j", "degraded", latency, f"status={stats_resp.status_code}"
                )
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            _record("neo4j", "down", latency, f"error={exc}")

    # Job queue stats (JobStore)
    queue_stats: Dict[str, Any] = {}
    try:
        queue_stats = _get_job_service().get_queue_stats()
    except Exception as exc:  # pragma: no cover
        _record("job_store", "degraded", None, f"queue_stats_failed: {exc}")
    else:
        # Oldest age or depth indicates if queue is backing up
        depth = queue_stats.get("queued", 0) or queue_stats.get("queue_depth", 0)
        oldest_age = queue_stats.get("oldest_pending_age_sec", 0)
        status = "ok"
        detail = None
        if (depth and depth > 100) or (oldest_age and oldest_age > 300):
            status = "degraded"
            detail = f"depth={depth}, oldest_age_s={oldest_age}"
        _record("job_store", status, None, detail)

    # Build metadata
    git_sha = os.getenv("GIT_SHA")
    if not git_sha:
        try:
            git_sha = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode("utf-8")
                .strip()
            )
        except Exception:
            git_sha = None

    payload = {
        "status": overall_status,
        "services": components,
        "planner_catalog": planner_catalog,
        "queue": queue_stats,
        "neo4j": neo4j_stats,
        "env": os.getenv("APP_ENV") or os.getenv("ENV") or "dev",
        "build_git_sha": git_sha,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "timestamp": int(time.time()),
    }
    return jsonify(payload)


@ui_api.get("/config/ui")
def api_config_ui():
    return {
        "modes": ["default", "code", "kg_qa"],
        "tool_mode_default": "auto",
    }


# ---------------------------------------------------------------------------
# Auth stubs (minimal, non-email flows)
# ---------------------------------------------------------------------------


@ui_api.post("/auth/signup")
def api_auth_signup():
    """User signup stub - returns success without persistence.

    For real signups, users should use OAuth providers (Google, GitHub).
    This endpoint exists to prevent UI errors when signup form is submitted.
    """
    data = _json()
    email = data.get("email")
    if not email:
        return jsonify({"error": "email_required", "detail": "Email is required"}), 400

    # Stub: return success without creating user
    # Real implementation would require user store + email verification
    logger.info(f"Signup stub called for email: {email}")
    return jsonify(
        {
            "message": "Signup request received. Please use OAuth login (Google/GitHub) for full account creation.",
            "status": "stub",
            "email": email,
        }
    ), 200


@ui_api.post("/auth/reset-password")
def api_auth_reset_password():
    """Password reset stub - returns success without sending email.

    For real password reset, implement email service + token flow.
    """
    data = _json()
    email = data.get("email")
    if not email:
        return jsonify({"error": "email_required", "detail": "Email is required"}), 400

    # Stub: return success without sending email
    logger.info(f"Password reset stub called for email: {email}")
    return jsonify(
        {
            "message": "If an account exists, a reset email would be sent.",
            "status": "stub",
        }
    ), 200


@ui_api.post("/auth/exchange")
def api_auth_exchange():
    """Exchange a PAT for a short-lived JWT (CLI/MCP usage)."""
    from brain_researcher.services.agent.agent_auth import (
        AuthError,
        is_pat_token,
        issue_pat_jwt,
        pat_subject_from_token,
    )

    data = _json()
    auth = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or ""
    )
    token = None
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    token = token or data.get("token") or data.get("pat")

    if not token:
        return (
            jsonify(
                {
                    "error": "missing_pat",
                    "detail": "Provide PAT via Authorization header or body",
                }
            ),
            400,
        )

    if not is_pat_token(token):
        return jsonify({"error": "invalid_pat", "detail": "PAT not recognized"}), 401

    ttl_default = int(os.getenv("BR_PAT_JWT_TTL_SECONDS", "3600"))
    ttl_seconds = int(data.get("ttl_seconds") or ttl_default)
    ttl_seconds = max(300, min(ttl_seconds, 86400))

    subject = data.get("subject") or pat_subject_from_token(token)

    try:
        jwt_token = issue_pat_jwt(subject=subject, ttl_seconds=ttl_seconds)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 500

    return jsonify(
        {
            "access_token": jwt_token,
            "token_type": "bearer",
            "expires_in": ttl_seconds,
            "subject": subject,
        }
    )


# ---------------------------------------------------------------------------
# Chat & threads
# ---------------------------------------------------------------------------


@ui_api.post("/chat")
def api_chat():
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    payload = _json()
    messages: List[Dict[str, Any]] = payload.get("messages") or []
    # Support both "tool_mode" (legacy) and "tools.mode" (new)
    tool_mode = payload.get("tool_mode", "auto")
    tools_config = payload.get("tools") or {}
    tools_whitelist = payload.get("tools_whitelist") or []
    if isinstance(tools_config, dict) and tools_config.get("mode"):
        tool_mode = tools_config["mode"]  # Override with nested format
    if isinstance(tools_config, dict):
        tools_whitelist = (
            tools_whitelist
            or tools_config.get("whitelist")
            or tools_config.get("allowlist")
            or []
        )
    thread_id = payload.get("thread_id") or payload.get("session_id")

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    if not messages:
        return jsonify({"error": "messages cannot be empty"}), 400

    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last_user or not last_user.get("content"):
        return jsonify({"error": "missing user content"}), 400

    # Store user message first; if caller didn't provide a thread, create one
    # so multiple users don't collide on the "default" thread.
    thread_id = thread_id or str(uuid.uuid4())

    # Check thread access (will create new thread if doesn't exist)
    if not _check_thread_access(thread_id, user.id, user.tenant_id):
        return jsonify(
            {"error": "forbidden", "detail": "You don't have access to this thread"}
        ), 403

    ctx_extra = _normalize_checkpoint_ctx_ingress(payload.get("ctx") or {}, payload)
    if not isinstance(ctx_extra, dict):
        ctx_extra = {}
    ctx_extra.setdefault("thread_id", thread_id)
    history = _resolve_history_from_payload_or_thread(
        thread_id=thread_id,
        payload_messages=messages,
        last_user_content=last_user["content"],
    )

    # Smoke test shortcut: skip LLM/tools when SMOKE_TEST_MODE=1
    if os.getenv("SMOKE_TEST_MODE") == "1":
        _add_message(
            thread_id,
            "user",
            last_user["content"],
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        assistant_text = "smoke-test-ok"
        _add_message(
            thread_id,
            "assistant",
            assistant_text,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        return jsonify(
            {
                "thread_id": thread_id,
                "run_id": "smoke-run",
                "text": assistant_text,
            }
        )

    effective_user_content = last_user["content"]
    effective_history = history
    clarification_result = None
    if tool_mode != "coding":
        (
            clarification_result,
            effective_user_content,
            effective_history,
        ) = _maybe_legacy_clarification_result(
            thread_id=thread_id,
            user_msg=last_user["content"],
            history=history,
            ctx=ctx_extra,
            tool_mode=tool_mode,
        )

    _add_message(
        thread_id,
        "user",
        last_user["content"],
        user_id=user.id,
        tenant_id=user.tenant_id,
    )

    if clarification_result is not None:
        result = clarification_result
        assistant_content = (
            result.get("text")
            or result.get("content")
            or (result.get("message") or {}).get("content")
        )
    else:
        # Optional: route through ChatOrchestrator (pipeline-first, tool orchestration)
        # Only enabled when BR_CHAT_ORCHESTRATOR_ENABLED is set and the caller
        # explicitly asks for planning via ctx.use_planning_engine. This keeps the
        # legacy code paths intact for existing tests and callers that don't need
        # multi-step planning.
        orchestrator_enabled = os.getenv(
            "BR_CHAT_ORCHESTRATOR_ENABLED", "0"
        ).lower() in {
            "1",
            "true",
            "yes",
        }
        if (
            orchestrator_enabled
            and ctx_extra.get("use_planning_engine")
            and os.getenv("SMOKE_TEST_MODE") != "1"
        ):
            from brain_researcher.services.agent.web_service import simple_chat_internal

            reply_resp = simple_chat_internal(
                _augment_query_with_context(
                    effective_user_content,
                    ctx=ctx_extra,
                ),
                env_override=None,
                thread_id=thread_id,
                history=effective_history,
                ctx=ctx_extra,
            )

            # simple_chat_internal already returns a Response
            # Attach KG multihop previews when tool_calls are present.
            try:
                if (
                    reply_resp is not None
                    and getattr(reply_resp, "status_code", 200) < 400
                ):
                    reply_data = reply_resp.get_json(silent=True)
                    if isinstance(reply_data, dict):
                        _attach_kg_multihop_previews(reply_data.get("tool_calls"))
                        reply_resp.set_data(json.dumps(reply_data))
            except Exception:
                logger.exception("Failed to normalize orchestrator /chat tool previews")
            return reply_resp

        # Use core functions directly (no Flask request dependency)
        from brain_researcher.services.agent.agent_core import (
            simple_chat_core,
            agent_act_core,
        )

        if tool_mode in {"none", "off", "coding"}:
            # "coding" mode is local-first. Preserve caller-provided ctx
            # (repo_root, file_paths, model_hint, etc.) so the coding branch can
            # generate local code/instructions, and only use the remote code agent
            # when force_code_agent is explicitly set.
            ctx = dict(ctx_extra) if isinstance(ctx_extra, dict) else {}
            if tool_mode == "coding":
                ctx = _with_coding_mode(ctx)
            result = simple_chat_core(
                _augment_query_with_context(effective_user_content, ctx=ctx_extra),
                thread_id=thread_id,
                history=effective_history,
                ctx=ctx,
            )
            assistant_content = result.get("text")
            # Wrap result to match agent_act_core format for consistency
            if tool_mode == "coding":
                from datetime import datetime, timezone

                from brain_researcher.core.contracts.ids import IdsV1
                from brain_researcher.core.contracts.run_card import RunCardV1
                from brain_researcher.services.agent import telemetry

                run_id = (
                    request.headers.get("X-Run-ID") or ""
                ).strip() or telemetry.new_run_id()
                tool_calls = result.get("tool_calls", [])
                execution = {
                    "tool_mode": "disabled",
                    "route": "coding_chat",
                    **(result.get("metadata", {}) or {}),
                }
                ids = IdsV1(
                    analysis_id=run_id,
                    run_id=run_id,
                    job_id=run_id,
                    session_id=thread_id,
                    user_id=user.id,
                )
                run_card = RunCardV1(
                    id=run_id,
                    timestamp=datetime.now(tz=timezone.utc),
                    ids=ids,
                    execution=execution,
                    provenance={"tool_calls": tool_calls} if tool_calls else None,
                ).model_dump(mode="json", exclude_none=True)
                run_card.setdefault("run_id", run_id)

                result = {
                    "message": {"role": "assistant", "content": assistant_content},
                    "tool_calls": tool_calls,
                    "artifacts": [],
                    "runCard": run_card,
                    "session_id": thread_id,
                    "metadata": _normalize_checkpoint_metadata(
                        result.get("metadata") or {}
                    ),
                }
        else:
            tool_params = payload.get("tool_params") or payload.get("toolParams")
            budget_ms = payload.get("budget_ms") or payload.get("budgetMs")
            contextual_query = _augment_query_with_context(
                effective_user_content,
                history=effective_history,
                ctx=ctx_extra,
            )
            act_payload = {
                "query": contextual_query,
                "session_id": thread_id,
                "tool_mode": "auto" if tool_mode == "auto" else "force",
                "tools_whitelist": tools_whitelist,
                "messages": messages,
            }
            if isinstance(ctx_extra, dict) and ctx_extra:
                act_payload["ctx"] = ctx_extra
            if isinstance(tool_params, dict) and tool_params:
                act_payload["tool_params"] = tool_params
            if budget_ms is not None:
                try:
                    act_payload["budget_ms"] = int(budget_ms)
                except Exception:
                    # Ignore invalid values; agent_act_core will apply defaults.
                    pass
            result = agent_act_core(act_payload)
            assistant_content = (
                result.get("text")
                or result.get("content")
                or (result.get("message") or {}).get("content")
            )

    if assistant_content:
        assistant_metadata = _normalize_checkpoint_metadata(
            result.get("metadata") or {}
        )
        _add_message(
            thread_id,
            "assistant",
            assistant_content,
            user_id=user.id,
            tenant_id=user.tenant_id,
            metadata=assistant_metadata or None,
        )

    # Check for error in result
    if "error" in result:
        return jsonify(result), 500

    if isinstance(result, dict) and "metadata" in result:
        result["metadata"] = _normalize_checkpoint_metadata(result.get("metadata"))

    # Normalize tool-call previews for UI (best effort; non-breaking).
    try:
        _attach_kg_multihop_previews(result.get("tool_calls"))
    except Exception:
        logger.exception("Failed to normalize /chat tool previews")

    # Ensure everything is JSON-serializable (ToolResult, Pydantic models)
    def _serialize(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return str(obj)

    # Append user-facing tool snippets (e.g., generated commands/code) to the assistant message
    try:
        snippets = []
        for tc in result.get("tool_calls", []) or []:
            name = tc.get("name") or tc.get("tool") or "tool"
            res = tc.get("result") or {}
            # Many tool results are nested as {status, data, error}
            payload = res.get("data") if isinstance(res, dict) else None
            if not payload and isinstance(res, dict):
                # Some tools wrap further
                payload = res.get("result", {}).get("data")

            # neurodesk_command → show bash command
            if name == "neurodesk_command" and isinstance(payload, dict):
                cmd = payload.get("command")
                if cmd:
                    snippets.append(
                        "Here is the Neurodesk command you can run:\n```bash\n"
                        + cmd
                        + "\n```"
                    )

            # dataset/openneuro clients → show python/bash if provided
            if name in {"openneuro.client", "datasets.client"} and isinstance(
                payload, dict
            ):
                if payload.get("command"):
                    snippets.append(
                        "Suggested shell command:\n```bash\n"
                        + payload["command"]
                        + "\n```"
                    )
                elif payload.get("example_code"):
                    snippets.append(
                        "Example Python code:\n```python\n"
                        + payload["example_code"]
                        + "\n```"
                    )

        if snippets:
            if "message" not in result:
                result["message"] = {"role": "assistant", "content": ""}
            content = result["message"].get("content") or ""
            content += "\n\n---\n\n" + "\n\n".join(snippets)
            result["message"]["content"] = content
    except Exception:
        logger.exception("Failed to append tool snippets to response")

    return current_app.response_class(
        json.dumps(result, default=_serialize),
        mimetype="application/json",
        status=200,
    )


# Maximum queue size for coding events (backpressure limit)
CODING_EVENT_QUEUE_SIZE = 100
# Heartbeat interval for SSE keep-alive (seconds)
SSE_HEARTBEAT_INTERVAL = 15


def _with_coding_mode(ctx: Dict[str, Any] | None) -> Dict[str, Any]:
    """Merge coding mode into ctx without discarding nested tool hints."""
    merged_ctx = dict(ctx or {})
    tools_cfg = merged_ctx.get("tools")
    merged_tools = dict(tools_cfg) if isinstance(tools_cfg, dict) else {}
    merged_tools["mode"] = "coding"
    merged_ctx["tools"] = merged_tools
    return merged_ctx


def _should_use_remote_code_agent(ctx: Dict[str, Any] | None) -> bool:
    """Return True only for the explicit feature-flagged code-agent escape hatch.

    Normal coding mode stays local-first. This helper gates the one intentional
    bypass that streams CodeOrchestrator events when the caller explicitly opts
    in with ``force_code_agent`` and the service enables
    ``BR_ENABLE_CODE_AGENT_TOOL``.
    """
    if not isinstance(ctx, dict):
        return False
    if bool(ctx.get("explain_only")):
        return False
    if os.getenv("BR_ENABLE_CODE_AGENT_TOOL", "0").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    return bool(ctx.get("force_code_agent"))


def _stream_coding_response(
    user_content: str,
    thread_id: str,
    user_id: str,
    ctx: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Generator[str, None, None]:
    """Stream coding task events via SSE.

    This remote execution path is only used when the caller explicitly opts in
    with ``force_code_agent`` and the service enables ``BR_ENABLE_CODE_AGENT_TOOL``.
    Uses a bounded queue with backpressure to handle slow clients.
    """
    from brain_researcher.services.agent.code_orchestrator import get_code_orchestrator
    from brain_researcher.services.agent.streaming import StreamEvent

    event_queue: queue.Queue = queue.Queue(maxsize=CODING_EVENT_QUEUE_SIZE)
    done_event = threading.Event()

    def emit_event(event: str, data: Dict[str, Any]) -> None:
        """Thread-safe event emitter with mild backpressure.

        - Result events block briefly to avoid loss.
        - Other events are best-effort; on overflow we drop oldest non-critical
          events and emit an explicit overflow error.
        """

        try:
            if event == "result":
                event_queue.put((event, data), timeout=1.0)
            else:
                event_queue.put_nowait((event, data))
        except queue.Full:
            # Drop one oldest to make room
            try:
                event_queue.get_nowait()
            except queue.Empty:
                pass

            # Emit explicit overflow notice (best effort)
            try:
                event_queue.put_nowait(("error", {"error": "coding_event_queue_full"}))
            except queue.Full:
                pass

            # Retry current event (best effort)
            try:
                event_queue.put_nowait((event, data))
            except queue.Full:
                logger.warning(
                    "Coding event queue full, dropping event after overflow: %s", event
                )

    def run_coding_task() -> None:
        """Run the coding task in background thread."""
        try:
            # Get orchestrator with our event callback
            orchestrator = get_code_orchestrator(event_callback=emit_event)

            # Preserve caller hints while forcing coding mode.
            task_ctx = _with_coding_mode(ctx)

            result = orchestrator.run_task(
                instruction=user_content,
                ctx=task_ctx,
                thread_id=thread_id,
                user_id=user_id,
            )

            # Emit final result
            emit_event(
                "result",
                {
                    "status": result.status,
                    "answer": result.answer,
                    "patches": result.patches,
                    "files_touched": result.files_touched,
                    "iterations": result.iterations,
                    "test_status": result.test_status,
                    "metadata": result.metadata,
                },
            )
        except Exception as e:
            logger.exception("Coding task failed: %s", e)
            emit_event("error", {"error": str(e)})
        finally:
            done_event.set()

    # Start background thread
    thread = threading.Thread(target=run_coding_task, daemon=True)
    thread.start()

    # Yield events with heartbeat support
    while True:
        # Exit once producer finished and queue is drained
        if done_event.is_set() and event_queue.empty():
            break
        try:
            item = event_queue.get(timeout=SSE_HEARTBEAT_INTERVAL)
            event_name, data = item
            yield StreamEvent(event=event_name, data=data).to_sse()
        except queue.Empty:
            # Send heartbeat to keep connection alive
            yield ": heartbeat\n\n"

    # Final done event
    yield StreamEvent(event="stream_end", data={}).to_sse()


@ui_api.post("/chat/stream")
def api_chat_stream():
    """
    Streaming chat endpoint - returns SSE stream of tokens.

    Request body:
        - messages: Array of chat messages
        - thread_id: Optional thread identifier
        - model: Optional model override
        - ctx: Optional context (for coding mode: tools.mode="coding")

    Streams token-by-token LLM response as SSE events.
    Coding mode is local-first by default. Only explicit ``force_code_agent``
    requests with ``BR_ENABLE_CODE_AGENT_TOOL=1`` stream plan/patch/test events
    from CodeOrchestrator.
    """
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError
    from brain_researcher.services.agent.streaming import (
        StreamingChatHandler,
        StreamEvent,
    )

    payload = _json()
    messages: List[Dict[str, Any]] = payload.get("messages") or []
    thread_id = payload.get("thread_id") or payload.get("session_id") or "default"
    model_hint = payload.get("model")
    ctx = _normalize_checkpoint_ctx_ingress(payload.get("ctx") or {}, payload)

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    if not messages:
        return jsonify({"error": "messages cannot be empty"}), 400

    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last_user or not last_user.get("content"):
        return jsonify({"error": "missing user content"}), 400

    # Check thread access
    if not _check_thread_access(thread_id, user.id, user.tenant_id):
        return jsonify(
            {"error": "forbidden", "detail": "You don't have access to this thread"}
        ), 403

    user_content = last_user["content"]
    history, history_source = _resolve_history_from_payload_or_thread_with_source(
        thread_id=thread_id,
        payload_messages=messages,
        last_user_content=user_content,
    )
    contextual_user_content = _augment_query_with_context(
        user_content, history=history, ctx=ctx
    )

    from datetime import datetime, timezone

    from brain_researcher.config.run_artifacts import (
        build_run_dir,
        get_recorder_config,
    )
    from brain_researcher.core.contracts.ids import IdsV1
    from brain_researcher.core.contracts.run_card import RunCardV1
    from brain_researcher.services.agent import telemetry
    from brain_researcher.services.agent.guardrails import GuardrailsSnapshotV1
    from brain_researcher.services.agent.run_bundle import (
        log_trace_event,
        persist_agent_analysis_bundle,
        persist_agent_observation,
        persist_agent_trajectory,
    )

    run_id = (request.headers.get("X-Run-ID") or "").strip() or telemetry.new_run_id()
    run_dir = build_run_dir(get_recorder_config().root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    def _extract_allowlist(payload: dict[str, Any]) -> list[str] | None:
        allowlist = payload.get("tools_whitelist") or payload.get("tools_allowlist")
        if allowlist is None:
            tools_cfg = payload.get("tools") or {}
            if isinstance(tools_cfg, dict):
                allowlist = tools_cfg.get("allowlist") or tools_cfg.get("whitelist")
        if not isinstance(allowlist, list):
            return None
        cleaned = [str(item).strip() for item in allowlist if str(item).strip()]
        return cleaned or None

    def _extract_budget_ms(payload: dict[str, Any]) -> int | None:
        raw = payload.get("budget_ms", payload.get("budgetMs"))
        if raw is None:
            return None
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    tool_allowlist = _extract_allowlist(payload)
    budget_ms = _extract_budget_ms(payload)
    guardrails_snapshot = GuardrailsSnapshotV1(
        frozen=bool(payload.get("frozen", False)),
        no_network=bool(payload.get("no_network", False)),
        budget_ms=budget_ms,
        tool_allowlist=tool_allowlist,
        policy_id=os.getenv("BR_POLICY_ID"),
    )

    trace_base: dict[str, Any] = {
        "job_id": run_id,
        "session_id": thread_id,
        "user_id": user.id,
        "thread_id": thread_id,
    }

    def _build_run_card_v1(
        *, execution: dict[str, Any], provenance: dict[str, Any] | None
    ):
        ids = IdsV1(
            analysis_id=run_id,
            run_id=run_id,
            job_id=run_id,
            session_id=thread_id,
            user_id=user.id,
        )
        card = RunCardV1(
            id=run_id,
            timestamp=datetime.now(tz=timezone.utc),
            ids=ids,
            execution=execution,
            provenance=provenance,
        )
        dumped = card.model_dump(mode="json", exclude_none=True)
        dumped.setdefault("run_id", run_id)
        return dumped

    def _try_log(event_type: str, payload: dict[str, Any] | None = None) -> None:
        try:
            log_trace_event(
                run_dir,
                run_id=run_id,
                event_type=event_type,
                payload={**trace_base, **(payload or {})},
            )
        except Exception:
            logger.exception("Failed to log trace event: %s", event_type)

    started_at_ms = int(time.time() * 1000)
    _try_log(
        "chat.started",
        payload={
            "model_hint": model_hint,
            "message_length": len(user_content or ""),
            "history_source": history_source,
            "history_count": len(history),
            "guardrails": guardrails_snapshot.model_dump(exclude_none=True),
        },
    )

    # Detect the explicit code-agent escape hatch. Plain coding mode falls
    # through to the normal LLM streaming path so the user gets local-first
    # guidance/code.
    is_coding_mode = ctx.get("tools", {}).get("mode") == "coding"
    use_remote_code_agent = is_coding_mode and _should_use_remote_code_agent(ctx)

    if use_remote_code_agent:
        # Explicit remote coding mode: stream plan/patch/test events
        def gen():
            accumulated_answer = None
            stream_metadata: dict[str, Any] | None = None
            tool_calls: list[dict[str, Any]] = []
            # Save user message
            _add_message(
                thread_id,
                "user",
                user_content,
                user_id=user.id,
                tenant_id=user.tenant_id,
            )

            start_payload = {
                "run_id": run_id,
                "thread_id": thread_id,
                "model": model_hint,
                "timestamp": time.time(),
            }
            _try_log("chat.start", payload={"event": "start", "data": start_payload})
            yield StreamEvent(event="start", data=start_payload).to_sse()

            # Stream coding events
            for sse_chunk in _stream_coding_response(
                contextual_user_content, thread_id, user.id, ctx, history
            ):
                try:
                    chunk_str = (
                        sse_chunk.decode("utf-8")
                        if isinstance(sse_chunk, (bytes, bytearray))
                        else str(sse_chunk)
                    )
                    event_name = None
                    data_payload = None
                    if chunk_str.startswith(":"):
                        _try_log("chat.heartbeat", payload={"raw": chunk_str.strip()})
                    else:
                        for line in chunk_str.splitlines():
                            if line.startswith("event:"):
                                event_name = line.split(":", 1)[1].strip()
                            elif line.startswith("data:"):
                                raw = line.split(":", 1)[1].strip()
                                try:
                                    data_payload = json.loads(raw)
                                except Exception:
                                    data_payload = {"raw": raw}
                        if event_name:
                            if event_name == "metadata" and isinstance(
                                data_payload, dict
                            ):
                                stream_metadata = data_payload
                            _try_log(
                                f"chat.{event_name}",
                                payload={
                                    "event": event_name,
                                    "data": data_payload or {},
                                },
                            )
                        else:
                            _try_log("chat.chunk", payload={"raw": chunk_str})
                except Exception:
                    logger.exception(
                        "Failed to parse coding SSE chunk for trace logging"
                    )

                # Track the final result for saving
                if sse_chunk.startswith("event: result"):
                    try:
                        # Parse the result to get the answer
                        lines = sse_chunk.strip().split("\n")
                        for line in lines:
                            if line.startswith("data: "):
                                data = json.loads(line[6:])
                                accumulated_answer = data.get("answer")
                                break
                    except Exception:
                        pass
                yield sse_chunk

            # Save assistant response
            if accumulated_answer:
                _add_message(
                    thread_id,
                    "assistant",
                    accumulated_answer,
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    metadata=_normalize_checkpoint_metadata(stream_metadata or {}),
                )

            finished_at_ms = int(time.time() * 1000)
            state = "succeeded" if accumulated_answer else "failed"
            try:
                provenance = {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "user_id": user.id,
                    "mode": "coding",
                    "guardrails": guardrails_snapshot.model_dump(exclude_none=True),
                    "llm": {
                        "provider": (stream_metadata or {}).get("provider"),
                        "model": (stream_metadata or {}).get("model") or model_hint,
                        "route": "coding_loop",
                        "transport": "sse",
                    },
                }
                (run_dir / "provenance.json").write_text(
                    json.dumps(provenance, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                run_card = _build_run_card_v1(
                    execution={
                        "provider": (stream_metadata or {}).get("provider")
                        or "unknown",
                        "model": (stream_metadata or {}).get("model")
                        or model_hint
                        or "unknown",
                        "latency_ms": (stream_metadata or {}).get("latency_ms"),
                        "tool_mode": "coding",
                        "route": "coding_loop",
                        "transport": "sse",
                        "usage": (stream_metadata or {}).get("usage") or {},
                        "selected_tool": None,
                    },
                    provenance={"run_dir": str(run_dir)},
                )

                persist_agent_trajectory(
                    run_dir,
                    session_id=thread_id,
                    model_name=(stream_metadata or {}).get("model")
                    or model_hint
                    or "unknown",
                    user_message=user_content,
                    agent_message=accumulated_answer or "",
                    tool_calls=tool_calls,
                )
                persist_agent_observation(
                    run_dir,
                    job_id=run_id,
                    run_id=run_id,
                    state=state,
                    run_card=run_card,
                    provenance=provenance,
                    tool_calls=tool_calls,
                    artifacts=[],
                    violations=None,
                    created_at_ms=started_at_ms,
                    started_at_ms=started_at_ms,
                    finished_at_ms=finished_at_ms,
                )
                persist_agent_analysis_bundle(
                    run_dir,
                    job_id=run_id,
                    run_id=run_id,
                    state=state,
                    run_card=run_card,
                    provenance=provenance,
                    policy={
                        "guardrails": guardrails_snapshot.model_dump(exclude_none=True)
                    },
                )
                _try_log("chat.bundle_written", payload={"state": state})
            except Exception:
                logger.exception("Failed to persist chat run bundle (coding mode)")

        resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
    else:
        # Check if Orchestrator is enabled (Planner Telemetry path)
        orchestrator_enabled = os.getenv(
            "BR_CHAT_ORCHESTRATOR_ENABLED", "0"
        ).lower() in {"1", "true", "yes"}

        if orchestrator_enabled and not is_coding_mode:

            def gen():
                stream_metadata: dict[str, Any] | None = None
                tool_calls: list[dict[str, Any]] = []
                answer = ""
                _add_message(
                    thread_id,
                    "user",
                    user_content,
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                )

                start_payload = {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "model": model_hint,
                    "timestamp": time.time(),
                }
                _try_log(
                    "chat.start", payload={"event": "start", "data": start_payload}
                )
                yield StreamEvent(event="start", data=start_payload).to_sse()

                try:
                    from brain_researcher.services.agent.web_service import (
                        simple_chat_internal,
                    )

                    # Call orchestrator (sync)
                    # We pass a copy of ctx to avoid mutation issues
                    internal_resp = simple_chat_internal(
                        contextual_user_content,
                        env_override=None,
                        thread_id=thread_id,
                        history=history,
                        ctx=dict(ctx),
                    )

                    # Unpack Flask Response (it returns a Response object with json body)
                    if not internal_resp or internal_resp.status_code != 200:
                        yield StreamEvent(
                            event="error", data={"error": "Orchestrator failed"}
                        ).to_sse()
                        return

                    result_data = internal_resp.get_json()
                    answer = result_data.get("text", "") or ""
                    metadata = result_data.get("metadata", {}) or {}
                    tool_calls = result_data.get("tool_calls", []) or []
                    _attach_kg_multihop_previews(tool_calls)
                    if isinstance(metadata, dict):
                        stream_metadata = _normalize_checkpoint_metadata(metadata)

                    # 1. Broadcast candidates / metadata
                    if stream_metadata:
                        _try_log(
                            "chat.metadata",
                            payload={"event": "metadata", "data": stream_metadata},
                        )
                        yield StreamEvent(
                            event="metadata", data=stream_metadata
                        ).to_sse()

                    # 2. Broadcast tool calls
                    if tool_calls:
                        for tc in tool_calls:
                            _try_log(
                                "chat.tool_call",
                                payload={"event": "tool_call", "data": tc},
                            )
                            yield StreamEvent(event="tool_call", data=tc).to_sse()

                    # 3. Stream the answer (simulated token stream for UI compatibility)
                    # We send it in chunks to mimic typing
                    chunk_size = 10
                    for i in range(0, len(answer), chunk_size):
                        chunk = answer[i : i + chunk_size]
                        _try_log(
                            "chat.token",
                            payload={"event": "token", "data": {"content": chunk}},
                        )
                        yield StreamEvent(
                            event="token", data={"content": chunk}
                        ).to_sse()
                        time.sleep(0.01)  # Slight artificial delay for UX

                    # 4. Done
                    _try_log(
                        "chat.done",
                        payload={
                            "event": "done",
                            "data": {
                                "thread_id": thread_id,
                                "total_length": len(answer),
                            },
                        },
                    )
                    yield StreamEvent(
                        event="done",
                        data={"thread_id": thread_id, "total_length": len(answer)},
                    ).to_sse()

                    # Save to history
                    _add_message(
                        thread_id,
                        "assistant",
                        answer,
                        user_id=user.id,
                        tenant_id=user.tenant_id,
                        metadata=_normalize_checkpoint_metadata(stream_metadata or {}),
                    )

                except Exception as ex:
                    logger.exception("Orchestrator stream failed")
                    _try_log(
                        "chat.error",
                        payload={"event": "error", "data": {"error": str(ex)}},
                    )
                    yield StreamEvent(event="error", data={"error": str(ex)}).to_sse()
                finally:
                    finished_at_ms = int(time.time() * 1000)
                    state = "failed" if not answer else "succeeded"
                    try:
                        provenance = {
                            "run_id": run_id,
                            "thread_id": thread_id,
                            "user_id": user.id,
                            "mode": "orchestrator",
                            "guardrails": guardrails_snapshot.model_dump(
                                exclude_none=True
                            ),
                            "llm": {
                                "provider": (stream_metadata or {}).get("provider"),
                                "model": (stream_metadata or {}).get("model")
                                or model_hint,
                                "route": "orchestrator",
                                "transport": "sse",
                            },
                        }
                        (run_dir / "provenance.json").write_text(
                            json.dumps(provenance, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )

                        run_card = _build_run_card_v1(
                            execution={
                                "provider": (stream_metadata or {}).get("provider")
                                or "unknown",
                                "model": (stream_metadata or {}).get("model")
                                or model_hint
                                or "unknown",
                                "latency_ms": (stream_metadata or {}).get("latency_ms"),
                                "tool_mode": "orchestrator",
                                "route": "orchestrator",
                                "transport": "sse",
                                "usage": (stream_metadata or {}).get("usage") or {},
                                "selected_tool": None,
                            },
                            provenance={"run_dir": str(run_dir)},
                        )

                        persist_agent_trajectory(
                            run_dir,
                            session_id=thread_id,
                            model_name=(stream_metadata or {}).get("model")
                            or model_hint
                            or "unknown",
                            user_message=user_content,
                            agent_message=answer,
                            tool_calls=tool_calls,
                        )
                        persist_agent_observation(
                            run_dir,
                            job_id=run_id,
                            run_id=run_id,
                            state=state,
                            run_card=run_card,
                            provenance=provenance,
                            tool_calls=tool_calls,
                            artifacts=[],
                            violations=None,
                            created_at_ms=started_at_ms,
                            started_at_ms=started_at_ms,
                            finished_at_ms=finished_at_ms,
                        )
                        persist_agent_analysis_bundle(
                            run_dir,
                            job_id=run_id,
                            run_id=run_id,
                            state=state,
                            run_card=run_card,
                            provenance=provenance,
                            policy={
                                "guardrails": guardrails_snapshot.model_dump(
                                    exclude_none=True
                                )
                            },
                        )
                        _try_log("chat.bundle_written", payload={"state": state})
                    except Exception:
                        logger.exception(
                            "Failed to persist chat run bundle (orchestrator mode)"
                        )

            resp = Response(stream_with_context(gen()), mimetype="text/event-stream")

        else:
            # Standard LLM streaming (Fallback or Default)
            def gen():
                stream_metadata: dict[str, Any] | None = None
                stream_error: str | None = None
                # Save user message
                _add_message(
                    thread_id,
                    "user",
                    user_content,
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                )

                start_payload = {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "model": model_hint,
                    "timestamp": time.time(),
                }
                _try_log(
                    "chat.start", payload={"event": "start", "data": start_payload}
                )
                yield StreamEvent(event="start", data=start_payload).to_sse()

                # Stream LLM response
                handler = StreamingChatHandler(
                    model_hint=model_hint,
                    thread_id=thread_id,
                )

                try:
                    for event in handler.stream_chat(
                        contextual_user_content, history=history
                    ):
                        # Inject run_id so clients can correlate the bundle.
                        if isinstance(event.data, dict) and "run_id" not in event.data:
                            event.data["run_id"] = run_id
                        if event.event == "metadata" and isinstance(event.data, dict):
                            stream_metadata = _normalize_checkpoint_metadata(event.data)
                        if event.event == "error" and isinstance(event.data, dict):
                            stream_error = str(event.data.get("error") or "")

                        _try_log(
                            f"chat.{event.event}",
                            payload={"event": event.event, "data": event.data},
                        )
                        yield event.to_sse()
                except Exception as exc:
                    stream_error = str(exc)
                    _try_log(
                        "chat.error",
                        payload={"event": "error", "data": {"error": stream_error}},
                    )
                    yield StreamEvent(
                        event="error", data={"error": stream_error, "run_id": run_id}
                    ).to_sse()

                # Save assistant response
                accumulated = handler.get_accumulated_text()
                if accumulated:
                    _add_message(
                        thread_id,
                        "assistant",
                        accumulated,
                        user_id=user.id,
                        tenant_id=user.tenant_id,
                        metadata=_normalize_checkpoint_metadata(stream_metadata or {}),
                    )

                finished_at_ms = int(time.time() * 1000)
                state = "failed" if stream_error else "succeeded"
                try:
                    provenance = {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "user_id": user.id,
                        "mode": "llm_stream",
                        "guardrails": guardrails_snapshot.model_dump(exclude_none=True),
                        "llm": {
                            "provider": (stream_metadata or {}).get("provider"),
                            "model": (stream_metadata or {}).get("model") or model_hint,
                            "route": "direct",
                            "transport": "sse",
                        },
                        "error": stream_error,
                    }
                    (run_dir / "provenance.json").write_text(
                        json.dumps(provenance, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    run_card = _build_run_card_v1(
                        execution={
                            "provider": (stream_metadata or {}).get("provider")
                            or "unknown",
                            "model": (stream_metadata or {}).get("model")
                            or model_hint
                            or "unknown",
                            "latency_ms": (stream_metadata or {}).get("latency_ms"),
                            "tool_mode": "none",
                            "route": "direct",
                            "transport": "sse",
                            "usage": (stream_metadata or {}).get("usage") or {},
                            "selected_tool": None,
                        },
                        provenance={"run_dir": str(run_dir)},
                    )

                    persist_agent_trajectory(
                        run_dir,
                        session_id=thread_id,
                        model_name=(stream_metadata or {}).get("model")
                        or model_hint
                        or "unknown",
                        user_message=user_content,
                        agent_message=accumulated or "",
                        tool_calls=[],
                    )
                    persist_agent_observation(
                        run_dir,
                        job_id=run_id,
                        run_id=run_id,
                        state=state,
                        run_card=run_card,
                        provenance=provenance,
                        tool_calls=[],
                        artifacts=[],
                        violations=None,
                        created_at_ms=started_at_ms,
                        started_at_ms=started_at_ms,
                        finished_at_ms=finished_at_ms,
                    )
                    persist_agent_analysis_bundle(
                        run_dir,
                        job_id=run_id,
                        run_id=run_id,
                        state=state,
                        run_card=run_card,
                        provenance=provenance,
                        policy={
                            "guardrails": guardrails_snapshot.model_dump(
                                exclude_none=True
                            )
                        },
                    )
                    _try_log("chat.bundle_written", payload={"state": state})
                except Exception:
                    logger.exception("Failed to persist chat run bundle (llm_stream)")

            resp = Response(stream_with_context(gen()), mimetype="text/event-stream")

    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["X-Run-ID"] = run_id
    return resp


@ui_api.get("/threads")
def api_threads_list():
    """List all threads owned by the current user."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    # Parse query params
    limit = min(int(request.args.get("limit", 50)), 100)  # Cap at 100
    include_messages = request.args.get("include_messages", "").lower() == "true"

    store = _get_thread_store()
    threads = store.list_user_threads(
        user.id,
        tenant_id=user.tenant_id,
        limit=limit,
        include_messages=include_messages,
    )

    return {
        "threads": threads,
        "count": len(threads),
        "user_id": user.id,
    }


@ui_api.get("/threads/<thread_id>/messages")
def api_thread_messages(thread_id: str):
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    # Check ownership
    if not _check_thread_access(thread_id, user.id, user.tenant_id):
        return jsonify(
            {"error": "forbidden", "detail": "You don't have access to this thread"}
        ), 403

    store = _get_thread_store()
    messages = store.get_messages(thread_id)
    return {
        "thread_id": thread_id,
        "messages": [m.to_dict() for m in messages],
        "count": len(messages),
    }


@ui_api.get("/threads/<thread_id>/stream")
def api_thread_stream(thread_id: str):
    """
    Stream thread messages as SSE events.

    Query params:
        - message: If provided, streams live LLM response to this message
        - model: Optional model override for live streaming

    Without message param, returns existing thread messages (snapshot mode).
    """
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    # Check ownership
    if not _check_thread_access(thread_id, user.id, user.tenant_id):
        return jsonify(
            {"error": "forbidden", "detail": "You don't have access to this thread"}
        ), 403

    # Check for live streaming mode
    new_message = request.args.get("message")
    model_hint = request.args.get("model")

    if new_message:
        # Live streaming mode - stream LLM response token by token
        from brain_researcher.services.agent.streaming import stream_thread_messages

        def gen():
            # Save user message first
            _add_message(
                thread_id,
                "user",
                new_message,
                user_id=user.id,
                tenant_id=user.tenant_id,
            )

            # Stream the LLM response
            yield from stream_thread_messages(
                thread_id=thread_id,
                user_id=user.id,
                tenant_id=user.tenant_id,
                new_message=new_message,
                model_hint=model_hint,
            )

        resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"  # Disable nginx buffering
        return resp
    else:
        # Snapshot mode - return existing messages
        def gen():
            store = _get_thread_store()
            messages = store.get_messages(thread_id)
            for msg in messages:
                yield "event: message\n"
                yield f"data: {json.dumps(msg.to_dict())}\n\n"
            yield "event: done\n"
            yield "data: {}\n\n"

        resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        return resp


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@ui_api.get("/tools")
def api_tools():
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError
    import logging

    # Optional auth check - allow unauthenticated but log for monitoring
    try:
        user = get_current_user(request)
        logging.getLogger(__name__).debug(f"/tools accessed by user: {user.id}")
    except AuthError:
        logging.getLogger(__name__).info("/tools accessed without authentication")

    from brain_researcher.services.agent import web_service as ws

    agent = ws.get_agent()
    registry = agent.tool_registry
    tools = [
        {
            "id": t.get_tool_name(),
            "name": t.get_tool_name(),
            "description": getattr(t, "description", ""),
            "family": getattr(t, "category", None),
            "tags": getattr(t, "tags", []),
        }
        for t in registry.get_all_tools()
    ]
    return {"tools": tools}


def _parse_int_param(
    name: str, default: int, *, min_value: int = 0, max_value: int = 500
) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(value, max_value))


def _tool_search_text(tool: Dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("id", "name", "description", "family"):
        value = tool.get(key)
        if value:
            parts.append(str(value))
    tags = tool.get("tags") or []
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags if t)
    return " ".join(parts).lower()


@ui_api.get("/tools/search")
def api_tools_search():
    query = (request.args.get("q") or "").strip().lower()
    limit = _parse_int_param("limit", 50, min_value=1, max_value=500)
    offset = _parse_int_param("offset", 0, min_value=0, max_value=10_000)

    tools_resp = api_tools()
    tools = tools_resp.get("tools", []) if isinstance(tools_resp, dict) else []

    if query:
        tokens = [t for t in query.split() if t]
        if tokens:
            tools = [
                tool
                for tool in tools
                if all(token in _tool_search_text(tool) for token in tokens)
            ]

    total = len(tools)
    sliced = tools[offset : offset + limit]

    return {
        "tools": sliced,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total,
    }


@ui_api.post("/tools/run")
def api_tools_run():
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    payload = _json()
    tool_name = payload.get("tool")
    args = payload.get("args")
    if args is None:
        args = payload.get("arguments") or {}
    if not tool_name:
        return jsonify({"error": "tool is required"}), 400

    from brain_researcher.services.agent import web_service as ws

    return ws._execute_tool_request(
        tool_id=str(tool_name),
        params=args,
        work_dir=payload.get("work_dir"),
        output_dir=payload.get("output_dir"),
        preview=bool(payload.get("preview", False)),
        origin="api_tools_run",
    )


# ---------------------------------------------------------------------------
# Runs / jobs (stubs for now)
# ---------------------------------------------------------------------------

_DEMO_RUN_ID_CACHE: set[str] | None = None
_DEMO_RUN_ID_CACHE_MTIME: float | None = None


def _resolve_demo_index_path() -> str | None:
    override = (
        os.getenv("BR_DEMO_INDEX_PATH")
        or os.getenv("DEMO_INDEX_PATH")
        or os.getenv("NEXT_PUBLIC_DEMO_INDEX_PATH")
    )
    if override:
        return override

    repo_root: Path | None = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            repo_root = parent
            break

    if not repo_root:
        return None

    return str(repo_root / "configs" / "demo" / "demo_index.json")


def _load_demo_run_ids() -> set[str]:
    global _DEMO_RUN_ID_CACHE, _DEMO_RUN_ID_CACHE_MTIME

    index_path = _resolve_demo_index_path()
    if not index_path:
        _DEMO_RUN_ID_CACHE = set()
        _DEMO_RUN_ID_CACHE_MTIME = None
        return _DEMO_RUN_ID_CACHE

    try:
        stat = os.stat(index_path)
    except OSError:
        _DEMO_RUN_ID_CACHE = set()
        _DEMO_RUN_ID_CACHE_MTIME = None
        return _DEMO_RUN_ID_CACHE

    if _DEMO_RUN_ID_CACHE is not None and _DEMO_RUN_ID_CACHE_MTIME == stat.st_mtime:
        return _DEMO_RUN_ID_CACHE

    try:
        with open(index_path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle) or {}
    except Exception:
        _DEMO_RUN_ID_CACHE = set()
        _DEMO_RUN_ID_CACHE_MTIME = stat.st_mtime
        return _DEMO_RUN_ID_CACHE

    demos = parsed.get("demos") if isinstance(parsed, dict) else None
    ids: set[str] = set()
    if isinstance(demos, list):
        for entry in demos:
            if not isinstance(entry, dict):
                continue
            analysis_id = entry.get("analysis_id")
            if isinstance(analysis_id, str) and analysis_id.strip():
                ids.add(analysis_id.strip())

    _DEMO_RUN_ID_CACHE = ids
    _DEMO_RUN_ID_CACHE_MTIME = stat.st_mtime
    return ids


def _is_demo_run_id(run_id: str) -> bool:
    return run_id.strip() in _load_demo_run_ids()


def _normalize_project_id(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "default"


@ui_api.get("/projects")
def api_projects_list():
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    projects = job_service.list_projects(user.id)
    return {"projects": projects, "count": len(projects)}


@ui_api.post("/projects")
def api_projects_create():
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    payload = _json()
    project_id = payload.get("project_id")
    name = payload.get("name")
    description = payload.get("description")

    if not isinstance(project_id, str) or not project_id.strip():
        return jsonify(
            {"error": "invalid_request", "detail": "project_id required"}
        ), 400
    if not isinstance(name, str) or not name.strip():
        return jsonify({"error": "invalid_request", "detail": "name required"}), 400
    if description is not None and not isinstance(description, str):
        return (
            jsonify(
                {"error": "invalid_request", "detail": "description must be a string"}
            ),
            400,
        )

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    try:
        project = job_service.create_project(
            user.id,
            project_id=project_id,
            name=name,
            description=description,
        )
    except ValueError as exc:
        message = str(exc)
        if "already exists" in message.lower():
            return jsonify({"error": "project_exists", "detail": message}), 409
        return jsonify({"error": "invalid_request", "detail": message}), 400

    return project, 201


@ui_api.get("/projects/<project_id>")
def api_projects_get(project_id: str):
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    project = job_service.get_project(user.id, project_id=project_id)
    if not project:
        return jsonify({"error": "not_found", "detail": "Project not found"}), 404
    return project


@ui_api.patch("/projects/<project_id>")
def api_projects_update(project_id: str):
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    payload = _json()
    has_name = "name" in payload
    has_description = "description" in payload

    if not has_name and not has_description:
        return (
            jsonify(
                {"error": "invalid_request", "detail": "name or description required"}
            ),
            400,
        )

    name = payload.get("name") if has_name else None
    description = payload.get("description") if has_description else None

    if has_name and (not isinstance(name, str) or not name.strip()):
        return jsonify(
            {"error": "invalid_request", "detail": "name must be non-empty"}
        ), 400
    if has_description and description is not None and not isinstance(description, str):
        return (
            jsonify(
                {"error": "invalid_request", "detail": "description must be a string"}
            ),
            400,
        )

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    try:
        project = job_service.update_project(
            user.id,
            project_id=project_id,
            name=name,
            description=description,
        )
    except ValueError as exc:
        return jsonify({"error": "invalid_request", "detail": str(exc)}), 400

    if not project:
        return jsonify({"error": "not_found", "detail": "Project not found"}), 404
    return project


@ui_api.delete("/projects/<project_id>")
def api_projects_delete(project_id: str):
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    try:
        job_service.delete_project(user.id, project_id=project_id)
    except KeyError:
        return jsonify({"error": "not_found", "detail": "Project not found"}), 404
    except ValueError as exc:
        return jsonify({"error": "invalid_request", "detail": str(exc)}), 400
    except Exception as exc:
        logger.exception("Project delete failed: %s", project_id)
        return jsonify({"error": "project_delete_failed", "detail": str(exc)}), 500

    return {"ok": True, "project_id": project_id}


@ui_api.post("/runs")
def api_runs_create():
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    payload = _json()
    plan = payload.get("plan") or {}
    thread_id = payload.get("thread_id")
    raw_project_id = payload.get("project_id")
    project_id = _normalize_project_id(raw_project_id)

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    if isinstance(raw_project_id, str) and raw_project_id.strip():
        if not job_service.project_exists(project_id=project_id, user_id=user.id):
            return (
                jsonify(
                    {
                        "error": "invalid_project",
                        "detail": f"Project '{project_id}' does not exist",
                    }
                ),
                400,
            )

    try:
        run = job_service.create_run(plan, user.id, thread_id, project_id=project_id)
    except ValueError as exc:
        return jsonify({"error": "invalid_project", "detail": str(exc)}), 400
    return run


@ui_api.get("/runs")
def api_runs_list():
    """List runs for the current user.

    Query params:
        - limit: Max number of runs to return (default 50, max 250)

    Returns:
        - runs: List of run objects
        - count: Total count returned
    """
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    raw_limit = request.args.get("limit", "50")
    project_id = request.args.get("project_id")
    try:
        limit_val = int(raw_limit)
    except ValueError:
        return jsonify({"error": "invalid_limit"}), 400

    limit = max(1, min(limit_val, 250))
    job_service = _get_job_service()
    runs = job_service.list_runs(user.id, limit=limit, project_id=project_id)
    return {"runs": runs, "count": len(runs)}


@ui_api.get("/runs/<run_id>")
def api_runs_status(run_id: str):
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    run = job_service.get_run(run_id)

    if not run:
        return jsonify({"error": "run not found"}), 404
    if run.get("user_id") and run["user_id"] != user.id and not _is_demo_run_id(run_id):
        return jsonify({"error": "forbidden"}), 403

    return run


@ui_api.get("/runs/<run_id>/stream")
def api_runs_stream(run_id: str):
    """Stream run status and logs as SSE events.

    Emits:
        - status: Current run status
        - log: Log chunks as they become available
        - done: Final status when run completes
    """
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    job_service = _get_job_service()
    run = job_service.get_run(run_id)

    if not run:
        return jsonify({"error": "run not found"}), 404
    if run.get("user_id") and run["user_id"] != user.id and not _is_demo_run_id(run_id):
        return jsonify({"error": "forbidden"}), 403

    def gen():
        nonlocal run
        # Emit initial status
        yield f"event: status\ndata: {json.dumps(run)}\n\n"

        # Stream logs while run is active
        log_offset = 0
        active_statuses = ("queued", "running", "pending", "cancelling")

        while run.get("status") in active_statuses:
            # Get new log chunks
            logs = job_service.get_logs(run_id, log_offset)
            for log in logs:
                yield f"event: log\ndata: {json.dumps(log)}\n\n"
                log_offset = max(log_offset, log["offset"] + len(log["data"]))

            # Refresh run status
            updated = job_service.get_run(run_id)
            if updated:
                run = updated
                yield f"event: status\ndata: {json.dumps(updated)}\n\n"

            if run.get("status") not in active_statuses:
                break

            time.sleep(1)  # Poll interval

        # Emit final status
        final = job_service.get_run(run_id)
        yield f"event: done\ndata: {json.dumps(final or {'run_id': run_id, 'status': 'unknown'})}\n\n"

    resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ---------------------------------------------------------------------------
# Feedback & files
# ---------------------------------------------------------------------------

from brain_researcher.services.agent.file_upload_storage import (  # noqa: F401,E402
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    MAX_RESUMABLE_FILE_SIZE,
    UPLOAD_DIR,
    _compute_upload_dir,
    _get_file_extension,
    _is_allowed_file,
    FileStorage,
    ResumableUploadStorage,
)


_resumable_storage: Optional[ResumableUploadStorage] = None
_resumable_storage_lock = threading.Lock()


def get_resumable_upload_storage() -> ResumableUploadStorage:
    global _resumable_storage
    if _resumable_storage is None:
        with _resumable_storage_lock:
            if _resumable_storage is None:
                _resumable_storage = ResumableUploadStorage()
    return _resumable_storage


# Singleton file storage
_file_storage: Optional[FileStorage] = None
_file_storage_lock = threading.Lock()


def get_file_storage() -> FileStorage:
    """Get singleton file storage instance."""
    global _file_storage
    if _file_storage is None:
        with _file_storage_lock:
            if _file_storage is None:
                _file_storage = FileStorage()
    return _file_storage


@ui_api.post("/feedback")
def api_feedback():
    payload = _json()
    return {"status": "ok", "feedback": payload}


@ui_api.post("/files/upload")
def api_files_upload():
    """
    Upload a file.

    Accepts multipart/form-data with a 'file' field.
    Returns file metadata including file_id and url.
    """
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    # Check if file is in request
    if "file" not in request.files:
        return jsonify({"error": "no_file", "detail": "No file provided"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "empty_file", "detail": "Empty file"}), 400

    # Validate extension
    if not _is_allowed_file(file.filename):
        return jsonify(
            {
                "error": "invalid_extension",
                "detail": f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            }
        ), 400

    # Read file data
    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify(
            {
                "error": "file_too_large",
                "detail": f"File exceeds max size of {MAX_FILE_SIZE // (1024 * 1024)}MB",
            }
        ), 413

    # Determine content type
    content_type = file.content_type or "application/octet-stream"

    # Save file
    storage = get_file_storage()
    metadata = storage.save(file_data, file.filename, content_type, user.id)

    return jsonify(metadata), 201


from brain_researcher.services.agent.file_upload_storage import (  # noqa: F401,E402
    _parse_content_range,
)


@ui_api.post("/files/resumable/init")
def api_files_resumable_init():
    """Initialize a resumable upload session."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    payload = _json()
    filename = payload.get("filename")
    total_size = payload.get("total_size")
    content_type = payload.get("content_type") or "application/octet-stream"

    if not isinstance(filename, str) or not filename.strip():
        return jsonify({"error": "invalid_request", "detail": "filename required"}), 400
    if not isinstance(total_size, int):
        return jsonify(
            {"error": "invalid_request", "detail": "total_size (int) required"}
        ), 400
    if total_size > MAX_RESUMABLE_FILE_SIZE:
        return jsonify(
            {
                "error": "file_too_large",
                "detail": f"total_size exceeds server max of {MAX_RESUMABLE_FILE_SIZE} bytes",
            }
        ), 413

    storage = get_resumable_upload_storage()
    try:
        meta = storage.init(
            filename=filename,
            content_type=content_type,
            total_size=total_size,
            user_id=user.id,
        )
    except ValueError as exc:
        return jsonify({"error": "invalid_request", "detail": str(exc)}), 400

    return jsonify(
        {
            "upload_id": meta["upload_id"],
            "filename": meta["filename"],
            "content_type": meta["content_type"],
            "total_size": meta["total_size"],
            "received": meta["received"],
            "status": meta["status"],
            "chunk_url": f"/api/files/resumable/{meta['upload_id']}",
            "complete_url": f"/api/files/resumable/{meta['upload_id']}/complete",
        }
    ), 201


@ui_api.get("/files/resumable/<upload_id>")
def api_files_resumable_status(upload_id: str):
    """Check resumable upload status."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    storage = get_resumable_upload_storage()
    meta = storage.get(upload_id)
    if not meta:
        return jsonify({"error": "not_found", "detail": "Upload not found"}), 404
    if meta.get("user_id") != user.id:
        return jsonify({"error": "forbidden", "detail": "Not owner"}), 403

    return jsonify(
        {
            "upload_id": meta["upload_id"],
            "filename": meta["filename"],
            "content_type": meta["content_type"],
            "total_size": meta["total_size"],
            "received": meta["received"],
            "status": meta["status"],
        }
    )


@ui_api.put("/files/resumable/<upload_id>")
def api_files_resumable_put(upload_id: str):
    """Append a chunk to a resumable upload (sequential)."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    # Prefer Content-Range.
    start: int | None = None
    total: int | None = None
    content_range = request.headers.get("Content-Range")
    if content_range:
        try:
            start, end, total = _parse_content_range(content_range)
        except ValueError as exc:
            return jsonify({"error": "invalid_content_range", "detail": str(exc)}), 400

    if start is None:
        # Fallback: X-Upload-Offset.
        try:
            start = int(request.headers.get("X-Upload-Offset", "0"))
        except ValueError:
            return jsonify(
                {"error": "invalid_offset", "detail": "X-Upload-Offset must be int"}
            ), 400
        try:
            total = (
                int(request.headers["X-Upload-Length"])
                if "X-Upload-Length" in request.headers
                else None
            )
        except ValueError:
            return jsonify(
                {"error": "invalid_total", "detail": "X-Upload-Length must be int"}
            ), 400

    data = request.get_data(cache=False) or b""
    if not data:
        return jsonify({"error": "empty_chunk", "detail": "No bytes provided"}), 400

    storage = get_resumable_upload_storage()
    try:
        meta = storage.append_chunk(
            upload_id=upload_id,
            user_id=user.id,
            start=int(start),
            data=data,
            total=total,
        )
    except KeyError:
        return jsonify({"error": "not_found", "detail": "Upload not found"}), 404
    except PermissionError:
        return jsonify({"error": "forbidden", "detail": "Not owner"}), 403
    except ValueError as exc:
        return jsonify(
            {
                "error": "invalid_chunk",
                "detail": str(exc),
                "expected_offset": storage.get(upload_id).get("received")
                if storage.get(upload_id)
                else None,
            }
        ), 409

    return jsonify(
        {
            "upload_id": meta["upload_id"],
            "received": meta["received"],
            "total_size": meta["total_size"],
            "status": meta["status"],
        }
    )


@ui_api.post("/files/resumable/<upload_id>/complete")
def api_files_resumable_complete(upload_id: str):
    """Finalize a resumable upload and register it as a normal file."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    resumable = get_resumable_upload_storage()
    storage = get_file_storage()
    try:
        metadata = resumable.complete(
            upload_id=upload_id, user_id=user.id, storage=storage
        )
    except KeyError:
        return jsonify({"error": "not_found", "detail": "Upload not found"}), 404
    except PermissionError:
        return jsonify({"error": "forbidden", "detail": "Not owner"}), 403
    except ValueError as exc:
        return jsonify({"error": "invalid_state", "detail": str(exc)}), 409

    return jsonify(metadata), 201


@ui_api.delete("/files/resumable/<upload_id>")
def api_files_resumable_abort(upload_id: str):
    """Abort a resumable upload and delete partial data."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    resumable = get_resumable_upload_storage()
    ok = resumable.abort(upload_id=upload_id, user_id=user.id)
    if not ok:
        return jsonify({"error": "not_found", "detail": "Upload not found"}), 404
    return jsonify({"status": "ok"}), 200


@ui_api.get("/files/<file_id>")
def api_files_get(file_id: str):
    """Download a file by ID."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    storage = get_file_storage()
    metadata = storage.get(file_id)

    if not metadata:
        return jsonify({"error": "not_found", "detail": "File not found"}), 404

    # Check ownership
    if metadata["user_id"] != user.id:
        return jsonify({"error": "forbidden", "detail": "Access denied"}), 403

    file_path = Path(metadata["path"])
    if not file_path.exists():
        return jsonify({"error": "not_found", "detail": "File no longer exists"}), 404

    return send_file(
        file_path,
        mimetype=metadata["content_type"],
        as_attachment=True,
        download_name=metadata["filename"],
    )


@ui_api.delete("/files/<file_id>")
def api_files_delete(file_id: str):
    """Delete a file by ID."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    storage = get_file_storage()
    if storage.delete(file_id, user.id):
        return jsonify({"status": "deleted", "file_id": file_id})
    else:
        return jsonify(
            {"error": "not_found", "detail": "File not found or access denied"}
        ), 404


@ui_api.get("/files")
def api_files_list():
    """List all files for current user."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    storage = get_file_storage()
    files = storage.list_user_files(user.id)
    return jsonify({"files": files, "count": len(files)})


# ---------------------------------------------------------------------------
# Datasets (catalog-backed)
# ---------------------------------------------------------------------------

# Lazy-loaded dataset catalog
_dataset_catalog: Optional[Any] = None
_dataset_catalog_lock = threading.Lock()


def _get_dataset_catalog():
    """Get or create the dataset catalog index."""
    global _dataset_catalog
    if _dataset_catalog is None:
        with _dataset_catalog_lock:
            if _dataset_catalog is None:
                try:
                    from brain_researcher.core.datasets.catalog import (
                        load_catalog,
                        DatasetRecord,
                    )

                    records = load_catalog()
                    _dataset_catalog = {
                        "records": records,
                        "by_id": {r.dataset_id: r for r in records},
                    }
                    logger.info(f"Loaded {len(records)} datasets from catalog")
                except FileNotFoundError:
                    logger.warning("Dataset catalog not found, using empty catalog")
                    _dataset_catalog = {"records": [], "by_id": {}}
                except Exception as e:
                    logger.error(f"Failed to load dataset catalog: {e}")
                    _dataset_catalog = {"records": [], "by_id": {}}
    return _dataset_catalog


@ui_api.post("/datasets/search")
def api_datasets_search():
    """
    Search datasets in the catalog.

    Request body:
        - query: str - Text query to search
        - modalities: List[str] - Filter by modalities (fMRI, EEG, etc.)
        - species: List[str] - Filter by species
        - access_type: str - Filter by access type (public, registration, etc.)
        - limit: int - Max results (default 50)
        - offset: int - Pagination offset (default 0)
    """
    payload = _json()
    query = payload.get("query", "").lower().strip()
    modalities = payload.get("modalities", [])
    species = payload.get("species", [])
    access_type = payload.get("access_type")
    limit = min(payload.get("limit", 50), 250)
    offset = payload.get("offset", 0)

    # Smoke test shortcut
    if os.getenv("SMOKE_TEST_MODE") == "1":
        return jsonify(
            {
                "results": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "facets": None,
            }
        )

    catalog = _get_dataset_catalog()
    records = catalog["records"]
    try:
        from brain_researcher.core.datasets.local_registry import list_local_datasets

        local_records = list_local_datasets()
    except Exception:
        local_records = []
    local_by_id = {r.dataset_id: r for r in local_records}

    # Filter records
    results = []
    for record in records:
        # Text search in search_blob
        if query:
            if query not in record.search_blob.lower():
                continue

        # Modality filter
        if modalities:
            record_mods = {str(m).lower() for m in record.modalities}
            if not any(m.lower() in record_mods for m in modalities):
                continue

        # Species filter
        if species:
            record_species = {s.lower() for s in record.species}
            if not any(s.lower() in record_species for s in species):
                continue

        # Access type filter
        if access_type:
            if str(record.access_type).lower() != access_type.lower():
                continue

        results.append(record)

    # Add local-only datasets (e.g., uploaded zips), unless filters would exclude them.
    if local_records:
        catalog_ids = {r.dataset_id for r in records}
        base_url = os.getenv("BR_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        for local in local_records:
            if local.dataset_id in catalog_ids:
                continue
            if query:
                blob = " ".join(
                    [
                        local.dataset_id,
                        local.name or "",
                        local.description or "",
                    ]
                ).lower()
                if query not in blob:
                    continue
            if modalities or species or access_type:
                # Local datasets don't have reliable modality/species/access labels yet.
                continue
            results.append(
                {
                    "dataset_id": local.dataset_id,
                    "name": local.name or local.dataset_id,
                    "short_name": None,
                    "alias": [],
                    "description": local.description,
                    "category": None,
                    "modalities": [],
                    "acquisitions": [],
                    "subjects_count": None,
                    "sessions_count": None,
                    "species": ["human"],
                    "age_range": None,
                    "disease_flags": [],
                    "center": None,
                    "principal_investigator": None,
                    "consortium": None,
                    "source_repo": "local",
                    "source_repo_id": None,
                    "primary_url": f"{base_url}/api/datasets/{local.dataset_id}",
                    "access_type": "restricted",
                    "license": "custom",
                    "approx_size_bytes": None,
                    "size_human": None,
                    "tags": [],
                    "tasks": [],
                    "modalities_notes": None,
                    "has_derivatives": False,
                    "preview_media": [],
                    "created_from": None,
                    "source_version": None,
                    "created_at": local.created_at,
                    "updated_at": local.updated_at,
                    "local": {
                        "bids_root": local.bids_root,
                        "manifest_sha256": local.manifest_sha256,
                        "validation": local.validation,
                    },
                }
            )

    # Pagination
    total = len(results)
    results = results[offset : offset + limit]

    # Convert to dict for JSON serialization
    # Use model_dump(mode='json') for Pydantic v2 to serialize HttpUrl properly
    def to_json_dict(record):
        if isinstance(record, dict):
            data = dict(record)
        elif hasattr(record, "model_dump"):
            data = record.model_dump(mode="json")
        else:
            data = record.dict()

        local = (
            local_by_id.get(data.get("dataset_id")) if isinstance(data, dict) else None
        )
        if local and "local" not in data:
            data["local"] = {
                "bids_root": local.bids_root,
                "manifest_sha256": local.manifest_sha256,
                "validation": local.validation,
            }
        return data

    return jsonify(
        {
            "results": [to_json_dict(r) for r in results],
            "total": total,
            "limit": limit,
            "offset": offset,
            "facets": _compute_facets(catalog["records"]) if not query else None,
        }
    )


def _compute_facets(records) -> Dict[str, List[Dict[str, Any]]]:
    """Compute facet counts for filtering UI."""
    from collections import Counter

    modality_counts: Counter = Counter()
    species_counts: Counter = Counter()
    access_counts: Counter = Counter()
    source_counts: Counter = Counter()

    for r in records:
        for m in r.modalities:
            modality_counts[str(m)] += 1
        for s in r.species:
            species_counts[s] += 1
        access_counts[str(r.access_type)] += 1
        source_counts[r.source_repo] += 1

    def to_facet_list(counter: Counter) -> List[Dict[str, Any]]:
        return [{"value": k, "count": v} for k, v in counter.most_common(20)]

    return {
        "modalities": to_facet_list(modality_counts),
        "species": to_facet_list(species_counts),
        "access_type": to_facet_list(access_counts),
        "source_repo": to_facet_list(source_counts),
    }


@ui_api.get("/datasets/<dataset_id>")
def api_dataset_detail(dataset_id: str):
    """Get dataset details by ID."""
    catalog = _get_dataset_catalog()
    record = catalog["by_id"].get(dataset_id)
    try:
        from brain_researcher.core.datasets.local_registry import get_local_dataset

        local = get_local_dataset(dataset_id)
    except Exception:
        local = None

    base_url = os.getenv("BR_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    if record:
        # Use model_dump(mode='json') for Pydantic v2 to serialize HttpUrl properly
        data = (
            record.model_dump(mode="json")
            if hasattr(record, "model_dump")
            else record.dict()
        )
        if local:
            data["local"] = {
                "bids_root": local.bids_root,
                "manifest_sha256": local.manifest_sha256,
                "validation": local.validation,
            }
        return jsonify(data)

    if local:
        return jsonify(
            {
                "dataset_id": local.dataset_id,
                "name": local.name or local.dataset_id,
                "description": local.description,
                "source_repo": "local",
                "primary_url": f"{base_url}/api/datasets/{local.dataset_id}",
                "access_type": "restricted",
                "license": "custom",
                "modalities": [],
                "acquisitions": [],
                "species": ["human"],
                "tasks": [],
                "has_derivatives": False,
                "created_at": local.created_at,
                "updated_at": local.updated_at,
                "local": {
                    "bids_root": local.bids_root,
                    "manifest_sha256": local.manifest_sha256,
                    "validation": local.validation,
                    "meta": local.meta,
                },
            }
        )

    return jsonify(
        {"error": "not_found", "detail": f"Dataset {dataset_id} not found"}
    ), 404


@ui_api.get("/datasets/local")
def api_datasets_local_list():
    """List datasets present in the local registry."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        _ = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    try:
        from brain_researcher.core.datasets.local_registry import list_local_datasets

        records = list_local_datasets()
    except Exception as e:
        return jsonify({"error": "local_registry_error", "detail": str(e)}), 500

    return jsonify(
        [
            {
                "dataset_id": r.dataset_id,
                "bids_root": r.bids_root,
                "source": r.source,
                "name": r.name,
                "description": r.description,
                "manifest_sha256": r.manifest_sha256,
                "validation": r.validation,
                "meta": r.meta,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in records
        ]
    )


@ui_api.post("/datasets/import")
def api_datasets_import():
    """Import an uploaded BIDS zip into `data/bids/<dataset_id>` and register it."""
    from brain_researcher.services.agent.agent_auth import get_current_user, AuthError

    try:
        user = get_current_user(request)
    except AuthError as exc:
        return jsonify({"error": exc.code, "detail": exc.detail}), 401

    payload = _json()
    file_id = payload.get("file_id")
    dataset_id = payload.get("dataset_id")
    overwrite = bool(payload.get("overwrite", False))
    delete_uploaded = bool(payload.get("delete_uploaded", True))
    validate = bool(payload.get("validate", True))
    strict = bool(payload.get("strict", True))
    manifest_mode = payload.get("manifest_mode", "secure")
    include_derivatives = bool(payload.get("include_derivatives", False))
    max_hash_mb = payload.get("max_hash_mb")

    if not isinstance(file_id, str) or not file_id.strip():
        return jsonify({"error": "invalid_request", "detail": "file_id required"}), 400
    if dataset_id is not None and (
        not isinstance(dataset_id, str) or not dataset_id.strip()
    ):
        return jsonify(
            {"error": "invalid_request", "detail": "dataset_id must be string"}
        ), 400

    storage = get_file_storage()
    meta = storage.get(file_id)
    if not meta:
        return jsonify({"error": "not_found", "detail": "Uploaded file not found"}), 404
    if meta.get("user_id") != user.id:
        return jsonify({"error": "forbidden", "detail": "Not owner"}), 403

    filename = meta.get("filename") or ""
    if _get_file_extension(filename) != "zip":
        return jsonify(
            {"error": "invalid_extension", "detail": "Only .zip is supported"}
        ), 400

    try:
        from brain_researcher.core.datasets.bids_import import import_bids_zip

        result = import_bids_zip(
            zip_path=meta["path"],
            dataset_id=dataset_id,
            dest_root=os.getenv("BR_DATA_ROOT", "data/bids"),
            overwrite=overwrite,
            validate=validate,
            strict=strict,
            manifest_mode=manifest_mode,
            include_derivatives=include_derivatives,
            max_hash_mb=int(max_hash_mb) if isinstance(max_hash_mb, int) else None,
        )
    except FileExistsError as exc:
        return jsonify({"error": "dataset_exists", "detail": str(exc)}), 409
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"error": "import_failed", "detail": str(exc)}), 400
    except Exception as exc:
        logger.exception("Dataset import failed")
        return jsonify({"error": "import_failed", "detail": str(exc)}), 500

    if delete_uploaded:
        try:
            storage.delete(file_id, user.id)
        except Exception:
            pass

    return jsonify(
        result.model_dump(mode="json")
        if hasattr(result, "model_dump")
        else result.dict()
    ), 201


# ---------------------------------------------------------------------------
# Demo proxy (forwards to Orchestrator demo endpoints)
# ---------------------------------------------------------------------------

_demo_logger = logging.getLogger(__name__ + ".demo_proxy")

# Orchestrator URL for demo endpoints
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:3001")


def _create_stub_run(demo_type: str, plan: dict) -> dict:
    """Create a stub run in JobStore for demo purposes.

    Returns API-formatted run dict that can be fetched via /api/runs/{id}.
    Falls back to simple response if JobStore unavailable.
    """
    try:
        from brain_researcher.services.agent.job_service import get_job_service

        job_service = get_job_service()
        run = job_service.create_run(
            plan=plan, user_id="demo_user", thread_id=f"demo_{demo_type}"
        )
        run["stub"] = True
        return run
    except Exception as e:
        _demo_logger.warning(f"Could not create stub run in JobStore: {e}")
        # Fallback to simple response
        return {
            "run_id": f"demo_{demo_type}_{uuid.uuid4().hex[:8]}",
            "status": "queued",
            "stub": True,
        }


@ui_api.post("/demo/glm")
def api_demo_glm():
    """Local stub for motor GLM demo when orchestrator is unavailable."""
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(f"demo:glm:{client_ip}", max_requests=10, window_sec=60):
        return api_error(
            "rate_limited",
            "Too many demo requests. Try again later.",
            429,
            retry_after=60,
        )

    plan = {
        "demo": True,
        "type": "glm",
        "dataset": "ds000001",
        "analysis": "motor_localizer",
        "description": "Motor GLM demo stub",
    }
    return jsonify(_create_stub_run("glm", plan))


@ui_api.post("/demo/connectivity")
def api_demo_connectivity():
    """Local stub for connectivity demo when orchestrator is unavailable."""
    client_ip = request.remote_addr or "unknown"
    if not check_rate_limit(f"demo:conn:{client_ip}", max_requests=10, window_sec=60):
        return api_error(
            "rate_limited",
            "Too many demo requests. Try again later.",
            429,
            retry_after=60,
        )

    plan = {
        "demo": True,
        "type": "connectivity",
        "dataset": "ds000001",
        "analysis": "functional_connectivity",
        "description": "Connectivity demo stub",
    }
    return jsonify(_create_stub_run("connectivity", plan))


def _proxy_demo_request(subpath: str, method: str = "GET"):
    """
    Proxy a demo request to Orchestrator.

    Forwards the request (headers, body, query params) to Orchestrator
    and returns the response.
    """
    # Build target URL
    target_url = f"{ORCHESTRATOR_URL}/api/demo/{subpath}"
    if request.query_string:
        target_url = f"{target_url}?{request.query_string.decode()}"

    # Forward headers (exclude hop-by-hop headers)
    headers = {
        k: v
        for k, v in request.headers
        if k.lower()
        not in ("host", "connection", "content-length", "transfer-encoding")
    }

    _demo_logger.debug(f"Proxying {method} /api/demo/{subpath} -> {target_url}")

    try:
        if method in ("POST", "PUT", "PATCH"):
            # Forward request body
            resp = req_lib.request(
                method,
                target_url,
                headers=headers,
                json=request.get_json(silent=True),
                timeout=60,
            )
        else:
            resp = req_lib.request(
                method,
                target_url,
                headers=headers,
                timeout=60,
            )

        # Check for streaming response (NIfTI renders, downloads, etc.)
        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith(
            "application/octet-stream"
        ) or content_type.startswith("image/"):
            # Stream binary content
            def generate():
                for chunk in resp.iter_content(chunk_size=8192):
                    yield chunk

            proxy_resp = Response(
                stream_with_context(generate()),
                status=resp.status_code,
                content_type=content_type,
            )
        else:
            # Return as-is for JSON/text responses
            proxy_resp = Response(
                resp.content,
                status=resp.status_code,
                content_type=content_type,
            )

        # Copy relevant response headers
        for header in ("Content-Disposition", "X-Demo-Id", "X-Artifact-Id"):
            if header in resp.headers:
                proxy_resp.headers[header] = resp.headers[header]

        return proxy_resp

    except req_lib.exceptions.Timeout:
        _demo_logger.error(f"Timeout proxying demo request to {target_url}")
        if method == "POST":
            plan = {
                "demo": True,
                "type": subpath,
                "description": f"Demo stub (timeout): {subpath}",
            }
            return jsonify(_create_stub_run(subpath, plan)), 200
        return jsonify(
            {"error": "upstream_timeout", "detail": "Demo service timed out"}
        ), 504
    except req_lib.exceptions.ConnectionError as e:
        _demo_logger.error(
            f"Connection error proxying demo request: {e} (method={method}, subpath={subpath})"
        )
        # Fallback stub to keep UX alive even if orchestrator is down
        if method == "POST":
            plan = {
                "demo": True,
                "type": subpath,
                "description": f"Demo stub (orchestrator down): {subpath}",
            }
            return jsonify(_create_stub_run(subpath, plan)), 200
        return jsonify(
            {"error": "upstream_unavailable", "detail": "Demo service unavailable"}
        ), 503
    except Exception as e:
        _demo_logger.exception(f"Error proxying demo request: {e}")
        if method == "POST":
            plan = {
                "demo": True,
                "type": subpath,
                "description": f"Demo stub (error): {subpath}",
            }
            return jsonify(_create_stub_run(subpath, plan)), 200
        return jsonify({"error": "proxy_error", "detail": str(e)}), 500


@ui_api.route("/demo/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def api_demo_proxy(subpath: str):
    """
    Catch-all proxy for demo endpoints.

    Forwards requests to Orchestrator's /api/demo/* endpoints.
    This allows UI to only know about Agent while demo functionality
    remains in Orchestrator until full migration.
    """
    # Rate limit POST requests (creating new demos)
    if request.method == "POST":
        client_ip = request.remote_addr or "unknown"
        if not check_rate_limit(
            f"demo:proxy:{client_ip}", max_requests=10, window_sec=60
        ):
            return api_error(
                "rate_limited",
                "Too many demo requests. Try again later.",
                429,
                retry_after=60,
            )

    if request.args.get("stub") == "1" and request.method == "POST":
        plan = {
            "demo": True,
            "type": subpath,
            "description": f"Demo stub (forced): {subpath}",
        }
        return jsonify(_create_stub_run(subpath, plan))
    return _proxy_demo_request(subpath, request.method)
