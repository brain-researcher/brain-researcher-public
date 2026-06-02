#!/usr/bin/env python3
"""
Web service for the BR-KG LangGraph Agent.

This provides an HTTP API interface for the research assistant.
"""

import asyncio
import concurrent.futures
import contextvars
import hashlib
import importlib
import inspect
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from enum import Enum
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:  # optional Neo4j dependency for run/plan info
    from neo4j import GraphDatabase as _Neo4jDriver
except Exception:  # pragma: no cover - optional
    _Neo4jDriver = None

import yaml
from flask import Flask, Response, g, jsonify, request, stream_with_context
from flask_cors import CORS
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, Field, ValidationError

from brain_researcher.services.agent import telemetry
from brain_researcher.services.agent.agent_factory import (
    DEFAULT_CODING_MODEL,
    get_llm_agent,
    reset_llm_agent_cache,
)
from brain_researcher.services.agent.api_fee_debit import (
    ApiFeeDebitIdentity,
    ApiFeeDebitResult,
    ApiFeeReservationError,
    call_with_platform_api_fee_reservation,
    record_usage_and_debit_platform_api_fee,
)
from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.agent.cost_calculator import calculate_cost
from brain_researcher.services.agent.llm_budget_manager import (
    get_shared_llm_budget_manager,
)
from brain_researcher.services.agent.logging.token_counter import TokenCounter
from brain_researcher.services.agent.managed_credential_pool import (
    get_shared_managed_pool,
)
from brain_researcher.services.agent.monitoring.metrics_collector import (
    get_default_metrics_collector,
)
from brain_researcher.services.agent.router import (
    LLMChatResult,
    LLMRouteMetadata,
    LLMRouter,
    infer_provider,
)
from brain_researcher.services.agent.usage_aggregator import UsageTracker
from brain_researcher.services.shared.api_version import set_api_version
from brain_researcher.services.shared.log_scrubber import scrub_text
from brain_researcher.services.shared.trace_headers import (
    get_request_id,
    get_trace_id,
    set_trace_headers,
)

try:
    from brain_researcher.services.agent.monitoring_integration import (
        get_monitoring_integration as _get_monitoring_integration,
    )
except Exception:  # pragma: no cover - optional dependency
    _get_monitoring_integration = None
from brain_researcher.config.paths import resolve_from_config
from brain_researcher.core.contracts import Violation

# Modality plan builders were carved into plan_builders.py. Re-exported so the
# agent_plan_contract route (which calls _build_plan_for_request /
# _build_plan_routing_diagnostics) and the tests that patch/call them resolve.
# plan_builders imports planner.models (not web_service) at load → cycle-free.
from brain_researcher.services.agent.plan_builders import (  # noqa: F401,I001
    _build_connectivity_plan_eeg,
    _build_connectivity_plan_fmri,
    _build_connectivity_plan_ieeg,
    _build_demo_plan,
    _build_dmri_connectome_plan,
    _build_kg_ingest_validate_plan,
    _build_meta_termmap_plan,
    _build_pet_suvr_plan,
    _build_plan_for_request,
    _build_plan_routing_diagnostics,
    _build_smri_morphometry_plan,
)

# Plan execution + streaming engine was carved into plan_execution.py. Re-exported
# so the routes that delegate to it (agent_run_plan_contract et al) resolve.
# plan_execution imports nothing from web_service at load → cycle-free.
from brain_researcher.services.agent.plan_execution import (  # noqa: F401,I001
    _execute_plan_with_streaming,
    _proxy_plan_stream,
    _stream_stub_plan_events,
    _submit_plan_job,
)
from brain_researcher.services.agent.planner.catalog_loader import (
    get_tool_by_id,
)
from brain_researcher.services.agent.planner.models import (
    ArtifactSpec,
    ConstraintSpec,
    Plan,
    PlanDAG,
    PlanRequest,
    StepSpec,
)
from brain_researcher.services.agent.tool_candidate_service import (
    generate_tool_candidates,
)

# Tool-context retrieval helpers were carved into tool_context.py (cache state
# moved with them). Re-exported so the routes that delegate to them (simple_chat,
# agent_plan_contract, agent_studio_plan) + _filter_fallback_tools + tests resolve.
from brain_researcher.services.agent.tool_context import (  # noqa: F401,I001
    _build_context_for_query,
    _get_contract_tool_retriever,
    _get_fallback_tool_registry,
    _get_relevant_tool_context,
    _get_relevant_tool_context_legacy,
    _get_required_params,
)
from brain_researcher.services.shared.chat_scenarios import get_chat_scenario
from brain_researcher.services.shared.planner.handoff import (
    build_handoff_from_plan_payload,
)
from brain_researcher.services.shared.settings import get_settings
from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)

ORCHESTRATOR_BASE_URL = (
    os.getenv("BR_ORCHESTRATOR_URL")
    or os.getenv("ORCHESTRATOR_BASE_URL")
    or os.getenv("ORCHESTRATOR_URL")
    or os.getenv("ORCHESTRATOR_API_URL")
    or "http://localhost:3001"
)

# Lightweight in-process metrics collector (no external backend required)
_metrics = get_default_metrics_collector()

# ---------------------------------------------------------------------------
# Lightweight output-mode and complexity classification for core-agent path
# ---------------------------------------------------------------------------


class OutputMode(str, Enum):
    CODE = "code"
    PIPELINE = "pipeline"
    NATURAL = "natural"
    AUTO = "auto"


class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


_CODE_PATTERNS = [
    r"(?:write|generate|create)\s+(?:python|code|script)",
    r"code\s+(?:snippet|example)",
]
_PIPELINE_PATTERNS = [
    r"(?:create|build|design)\s+(?:a\s+)?pipeline",
    r"(?:workflow|processing)\s+(?:for|to)",
]
# Use raw strings so \b is treated as word boundary, not a literal backslash.
_MULTI_STEP_INDICATORS = [
    r"\band\s+then\b",
    r"\bthen\b",
    r"\bfollowed\s+by\b",
    r"\bafter\s+that\b",
    r"\bfirst\s*,.*\bthen\b",
]


def classify_output_mode(query: str) -> OutputMode:
    q = query.lower()
    for p in _CODE_PATTERNS:
        if re.search(p, q):
            return OutputMode.CODE
    for p in _PIPELINE_PATTERNS:
        if re.search(p, q):
            return OutputMode.PIPELINE
    return OutputMode.NATURAL


def assess_complexity(query: str) -> QueryComplexity:
    q = query.lower()
    multi = sum(1 for p in _MULTI_STEP_INDICATORS if re.search(p, q))
    word_count = len(query.split())
    # Loosen thresholds so single “then” or moderate length triggers planning.
    if multi >= 2 or word_count > 50:
        return QueryComplexity.COMPLEX
    if multi >= 1 or word_count > 25:
        return QueryComplexity.MODERATE
    return QueryComplexity.SIMPLE


# Load environment variables from repository .env file (if available)
try:
    from brain_researcher.core.utils import ensure_env_loaded

    loaded_env = ensure_env_loaded()
    if loaded_env:
        # Avoid polluting stdout for CLI machine-readable outputs (e.g., `br act --json`).
        sys.stderr.write(f"Loaded environment from {loaded_env}\n")
except Exception:
    loaded_env = None

# Paper utils and RAG imports - moved to functions to avoid circular deps

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _is_agent_metrics_enabled() -> bool:
    return os.getenv("BR_METRICS_ENABLED", "true").lower() in {"1", "true", "yes"}


_AGENT_METRICS_ENABLED = _is_agent_metrics_enabled()

# Tool context cache for performance optimization
# Shared LLM router for chat/act endpoints with budget enforcement
_BUDGET_MANAGER = get_shared_llm_budget_manager()
_MANAGED_POOL = get_shared_managed_pool()
_LLM_ROUTER = LLMRouter(budget_manager=_BUDGET_MANAGER, managed_pool=_MANAGED_POOL)
_USAGE_TRACKER = UsageTracker()
_API_FEE_DEBIT_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("api_fee_debit_context", default=None)
)
_CHAT_TOOL_REGISTRY = None
_CHAT_TOOL_ROUTER = None
_CHAT_TOOL_EXECUTOR = None
_ACT_LLM_TOOL_REGISTRY_CACHE: dict[str, Any] = {}
_ACT_LLM_TOOL_REGISTRY_CACHE_LOCK = threading.Lock()
# Lazy singleton orchestrator; only used if feature flag is enabled
_CHAT_ORCHESTRATOR: ChatOrchestrator | None = None


class _ApiFeeDebitingRouter:
    """Per-request service-layer billing wrapper around the shared LLM router."""

    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    def route_chat(self, *args: Any, **kwargs: Any) -> LLMChatResult:
        context = _API_FEE_DEBIT_CONTEXT.get() or {}
        return _route_chat_result_with_api_fee_debit(
            self._router,
            args=args,
            kwargs=kwargs,
            context=context,
        )


_BILLING_LLM_ROUTER = _ApiFeeDebitingRouter(_LLM_ROUTER)


def _first_present_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _request_header_value(*names: str) -> str | None:
    for name in names:
        value = request.headers.get(name)
        if value:
            return str(value).strip()
    return None


def _payload_value(payload: dict[str, Any] | None, *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value).strip() or None
    return None


def _trust_proxy_identity_headers() -> bool:
    return os.getenv("BR_TRUST_PROXY_IDENTITY_HEADERS", "0").lower() in {
        "1",
        "true",
        "yes",
    }


def _extract_api_fee_debit_identity(
    payload: dict[str, Any] | None = None,
) -> ApiFeeDebitIdentity | None:
    """Extract explicit wallet identity from authenticated service context."""

    header_user_id = _request_header_value("X-User-Id", "X-User-ID", "X-Account-Id")
    header_workspace_id = _request_header_value(
        "X-Workspace-Id", "X-Workspace-ID", "X-Org-Id"
    )

    try:
        from brain_researcher.services.agent.agent_auth import optional_auth

        current_user = optional_auth(request)
    except Exception:
        current_user = None

    if current_user is not None:
        tenant_id = getattr(current_user, "tenant_id", None)
        user_id = _first_present_text(getattr(current_user, "id", None))
        workspace_id = _first_present_text(
            tenant_id if tenant_id and tenant_id != "default" else None,
            header_workspace_id,
        )
    elif _trust_proxy_identity_headers():
        user_id = _first_present_text(header_user_id)
        workspace_id = _first_present_text(header_workspace_id)
    else:
        return None

    if not user_id or not workspace_id:
        return None
    return ApiFeeDebitIdentity(workspace_id=workspace_id, user_id=user_id)


def _extract_llm_budget_id(payload: dict[str, Any] | None = None) -> str | None:
    ctx = payload.get("ctx") if isinstance(payload, dict) else None
    if not isinstance(ctx, dict):
        ctx = {}
    return _first_present_text(
        _request_header_value("X-LLM-Budget-Id", "X-Budget-Id"),
        _payload_value(payload, "llm_budget_id", "budget_id"),
        _payload_value(ctx, "llm_budget_id", "budget_id"),
    )


def _build_api_fee_debit_context(
    payload: dict[str, Any] | None,
    *,
    call_prefix: str,
    fallback_run_id: str | None = None,
) -> dict[str, Any]:
    run_id = _first_present_text(
        fallback_run_id,
        getattr(g, "run_id", None),
        getattr(g, "client_run_id", None),
        getattr(g, "request_id", None),
    )
    return {
        "identity": _extract_api_fee_debit_identity(payload),
        "budget_id": _extract_llm_budget_id(payload),
        "call_prefix": call_prefix,
        "run_id": run_id,
        "counter": 0,
    }


def _next_api_fee_idempotency_key(
    metadata: Any,
    *,
    context: dict[str, Any],
) -> str | None:
    if getattr(metadata, "allocation_id", None):
        return None
    run_id = context.get("run_id")
    if not run_id:
        return None
    context["counter"] = int(context.get("counter") or 0) + 1
    return (
        f"llm-api-fee:{run_id}:{context.get('call_prefix') or 'llm'}:"
        f"{context['counter']}"
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _api_fee_precall_reservation_enabled() -> bool:
    return os.getenv("BR_PLATFORM_API_FEE_PRECALL_RESERVATION", "1").lower() not in {
        "0",
        "false",
        "no",
    }


def _provider_for_preflight(model: str, provider_lock: str | None = None) -> str:
    provider = (provider_lock or "").strip().lower() or infer_provider(model)
    if provider == "gemini":
        provider = "google"
    return provider or "unknown"


def _route_chat_prompt_from_args(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    if args:
        return str(args[0] or "")
    return str(kwargs.get("prompt") or kwargs.get("message") or "")


def _build_api_fee_preflight_metadata(
    *,
    prompt: str,
    kwargs: dict[str, Any],
    context: dict[str, Any],
) -> LLMRouteMetadata:
    budget_id = str(context.get("budget_id") or "").strip()
    model = (
        _first_present_text(
            kwargs.get("model_hint"),
            kwargs.get("model"),
            os.getenv("DEFAULT_LLM_MODEL"),
            "unknown",
        )
        or "unknown"
    )
    provider = _provider_for_preflight(model, kwargs.get("provider_lock"))
    token_provider = (
        provider if provider in {"openai", "anthropic", "google"} else "default"
    )
    prompt_tokens = max(1, TokenCounter.estimate_tokens(prompt, token_provider))
    completion_tokens = max(
        1, _env_int("BR_PLATFORM_API_FEE_RESERVE_OUTPUT_TOKENS", 4096)
    )
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    bill_to = f"managed:{budget_id}" if budget_id else "managed"
    cost = calculate_cost(provider, model, usage, bill_to=bill_to)
    reserve_cost = float(cost.get("total_cost") or 0.0)
    if not cost.get("pricing_available"):
        reserve_cost = _env_float("BR_PLATFORM_API_FEE_UNPRICED_RESERVE_USD", 0.05)
    reserve_cost = max(
        reserve_cost,
        _env_float("BR_PLATFORM_API_FEE_MIN_RESERVE_USD", 0.001),
    )
    return LLMRouteMetadata(
        provider=provider,
        model=model,
        route="preflight",
        transport="preflight",
        usage=usage,
        credential="managed_preflight",
        bill_to=bill_to,
        estimated_cost=reserve_cost,
        budget_id=budget_id or None,
    )


def _should_reserve_api_fee_before_route(context: dict[str, Any]) -> bool:
    if not _api_fee_precall_reservation_enabled():
        return False
    return bool(context.get("budget_id"))


def _route_chat_result_with_api_fee_debit(
    router: Any,
    *,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> LLMChatResult:
    debit_context = context or {}
    call_kwargs = dict(kwargs)
    if debit_context.get("budget_id") and not call_kwargs.get("budget_id"):
        call_kwargs["budget_id"] = debit_context["budget_id"]

    if _should_reserve_api_fee_before_route(debit_context):
        preflight_metadata = _build_api_fee_preflight_metadata(
            prompt=_route_chat_prompt_from_args(args, call_kwargs),
            kwargs=call_kwargs,
            context=debit_context,
        )
        idempotency_key = _next_api_fee_idempotency_key(
            preflight_metadata,
            context=debit_context,
        )
        return call_with_platform_api_fee_reservation(
            preflight_metadata,
            lambda: router.route_chat(*args, **call_kwargs),
            identity=debit_context.get("identity"),
            idempotency_key=idempotency_key,
            usage_tracker=_USAGE_TRACKER,
        )

    result = router.route_chat(*args, **call_kwargs)
    _record_llm_api_fee_debit_from_context(result, context=debit_context)
    return result


def _record_llm_api_fee_debit_from_context(
    result: LLMChatResult,
    *,
    context: dict[str, Any] | None = None,
) -> ApiFeeDebitResult:
    debit_context = context or _API_FEE_DEBIT_CONTEXT.get() or {}
    metadata = result.metadata
    debit_result = record_usage_and_debit_platform_api_fee(
        metadata,
        identity=debit_context.get("identity"),
        idempotency_key=_next_api_fee_idempotency_key(
            metadata,
            context=debit_context,
        ),
        usage_tracker=_USAGE_TRACKER,
    )
    metadata.api_fee_debit = debit_result.__dict__
    return debit_result


def _route_chat_with_api_fee_debit(
    prompt: str,
    *,
    payload: dict[str, Any] | None,
    call_prefix: str,
    fallback_run_id: str | None = None,
    **kwargs: Any,
) -> LLMChatResult:
    context = _build_api_fee_debit_context(
        payload,
        call_prefix=call_prefix,
        fallback_run_id=fallback_run_id,
    )
    return _route_chat_result_with_api_fee_debit(
        _LLM_ROUTER,
        args=(prompt,),
        kwargs=kwargs,
        context=context,
    )


# Failure logging observability + rate-limited warnings
_FAILURE_WRITE_WARN_LOCK = threading.Lock()
try:
    _FAILURE_WRITE_WARN_LIMIT = int(os.getenv("BR_FAILURE_WRITE_WARN_LIMIT", "10000"))
except ValueError:
    _FAILURE_WRITE_WARN_LIMIT = 10000
_failure_write_warned: dict[str, dict[str, float]] = {
    "plan_memory": {},
    "kg": {},
}

_KG_WRITE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.getenv("BR_KG_FAILURE_WRITE_WORKERS", "2"))
)
try:
    _KG_WRITE_MAX_INFLIGHT = int(os.getenv("BR_KG_FAILURE_WRITE_MAX_INFLIGHT", "4"))
except ValueError:
    _KG_WRITE_MAX_INFLIGHT = 4
_KG_WRITE_MAX_INFLIGHT = max(1, _KG_WRITE_MAX_INFLIGHT)
_KG_WRITE_SEMAPHORE = threading.Semaphore(_KG_WRITE_MAX_INFLIGHT)


def _warn_failure_once(category: str, plan_id: str, message: str) -> None:
    if not plan_id:
        logger.warning(message)
        return
    with _FAILURE_WRITE_WARN_LOCK:
        warned = _failure_write_warned.setdefault(category, {})
        if plan_id in warned:
            return
        warned[plan_id] = time.time()
        if len(warned) > _FAILURE_WRITE_WARN_LIMIT:
            oldest = min(warned.items(), key=lambda item: item[1])[0]
            warned.pop(oldest, None)
    logger.warning(message)


def _kg_write_timeout_seconds() -> float:
    raw = os.getenv("BR_KG_FAILURE_WRITE_TIMEOUT_S", "1.5")
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 1.5
    return max(timeout, 0.1)


def _kg_write_with_release(writer, record) -> None:
    try:
        writer.write([record])
    finally:
        _KG_WRITE_SEMAPHORE.release()


@lru_cache(maxsize=1)
def _get_agent_monitoring_for_metrics():
    if not _AGENT_METRICS_ENABLED or _get_monitoring_integration is None:
        return None
    try:
        return _get_monitoring_integration()
    except Exception as exc:  # pragma: no cover - optional logging
        logger.debug("Monitoring integration unavailable: %s", exc)
        return None


def _fallback_response(query: str) -> str:
    """Return a canned assistant reply when no provider credentials are available."""
    query_lower = (query or "").lower()
    if "glm" in query_lower:
        return (
            "I can't reach the LLM providers right now, but for GLM analyses you'll want to "
            "build a design matrix with task regressors, estimate beta weights, and inspect "
            "statistical maps for activation. Let me know if you need the detailed steps."
        )
    if "preprocess" in query_lower:
        return (
            "Preprocessing typically covers motion correction, slice-timing (for fMRI), "
            "spatial normalization to a template, and optional smoothing. When the LLM "
            "service is back I can draft a full pipeline for you."
        )
    return (
        "The hosted LLM providers are temporarily unavailable, so I'm falling back to a "
        "built-in response. Ask about analyses, preprocessing, or datasets and I can share "
        "reference guidance while we wait for credentials."
    )


# --------------------------------------------------------------------------
# TTL cache utilities (used by multiple endpoints)
# Place before first use to avoid NameError during import.
# --------------------------------------------------------------------------
_cache = {}
_cache_lock = threading.Lock()
_tool_import_lock = threading.Lock()
_tool_modules_loaded = False


def ttl_cache(seconds=300):
    """TTL cache decorator for expensive operations."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f.__name__
            with _cache_lock:
                if key in _cache:
                    result, timestamp = _cache[key]
                    if time.time() - timestamp < seconds:
                        logger.debug(f"Cache hit for {key}")
                        return result
                result = f(*args, **kwargs)
                _cache[key] = (result, time.time())
                return result

        return wrapper

    return decorator


def _ensure_tool_modules_loaded() -> None:
    """Import every tool module so registry discovery sees their classes."""

    global _tool_modules_loaded
    if _tool_modules_loaded:
        return

    with _tool_import_lock:
        if _tool_modules_loaded:
            return

        try:
            from brain_researcher.services.agent import tools as tools_pkg

            module_names = list(getattr(tools_pkg, "__all__", []))
            if not module_names:
                pkg_path = Path(tools_pkg.__file__).parent
                module_names = [
                    path.stem
                    for path in pkg_path.glob("*.py")
                    if not path.name.startswith("_")
                ]

            loaded = 0
            for short_name in sorted(module_names):
                module_path = f"{tools_pkg.__name__}.{short_name}"
                try:
                    importlib.import_module(module_path)
                except Exception as exc:  # pragma: no cover - best effort logging
                    logger.debug("Skipping tool module %s: %s", module_path, exc)
                    continue
                loaded += 1

            _tool_modules_loaded = True
            logger.info("Imported %d agent tool modules", loaded)
        except Exception as exc:  # pragma: no cover - environment specific
            logger.warning("Unable to preload tool modules: %s", exc)


def _infer_family_id(package: str) -> str:
    """Map a capability package prefix to a ToolFamily id used in BR-KG."""
    pkg = (package or "").lower()
    if pkg.startswith("fsl"):
        return "fsl"
    if pkg.startswith("afni"):
        return "afni"
    if pkg.startswith("mrtrix"):
        return "mrtrix3"
    if pkg.startswith("workbench"):
        return "workbench"
    if pkg.startswith("ants"):
        return "ants"
    if pkg.startswith("freesurfer"):
        return "freesurfer"
    if pkg.startswith("bidsapp"):
        return "bidsapps"
    return "niwrap_generic"


def _tool_summary(tool) -> dict[str, Any]:
    """Return a compact, JSON-ready summary of a ToolCapability."""
    is_niwrap = tool.runtime_kind == "container" and bool(
        getattr(tool, "entrypoint", None)
    )
    return {
        "id": tool.id,
        "runtime_kind": tool.runtime_kind,
        "package": tool.package,
        "entrypoint": getattr(tool, "entrypoint", None),
        "is_niwrap": is_niwrap,
        "is_promoted": _is_promoted_tool(tool),
        "source": getattr(tool, "source", None),
    }
    # NOTE: consider exposing selection reasons in planner responses if needed.


@lru_cache(maxsize=1)
def _load_promoted_spec():
    path = resolve_from_config("kg_promoted_niwrap.yaml")
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return data.get("promoted", []) or []
    except Exception:
        return []


def _is_promoted_tool(tool) -> bool:
    if not getattr(tool, "entrypoint", None):
        return False
    pkg = (tool.package or "").lower()
    ep = (tool.entrypoint or "").lower()
    tid = tool.id.lower()
    for spec in _load_promoted_spec():
        spkg = (spec.get("package") or "").lower()
        sep = (spec.get("entrypoint") or "").lower()
        sid = (spec.get("id") or "").lower()
        if sid and tid == sid:
            return True
        if spkg and sep and pkg == spkg and ep == sep:
            return True
        if spkg and not sep and pkg == spkg:
            return True
    return False


def _filter_registry_by_allowlist(registry) -> None:
    """Drop registry entries that violate the runtime allowlist."""
    # Prefer the merged env/chat_tools allowlist so we always bound the tool universe.
    try:
        allowlist = _env_tool_allowlist()
        settings = _agent_settings()
    except Exception:  # pragma: no cover - fallback if settings unavailable
        return

    # If an explicit allowlist (env or YAML) is present, apply it even if
    # Settings.tool_allowlist was None (which would otherwise imply allow_all).
    if not allowlist:
        if settings.allow_all_tools:
            return
        return

    allowset = set(allowlist)
    removed: list[str] = []
    tools_dict = getattr(registry, "tools", {})
    for tool_name in list(tools_dict.keys()):
        # Always retain safe E2E-only MCP tools. They are excluded from normal
        # candidate selection and only used when explicitly forced/whitelisted.
        if tool_name.startswith("mcp.test_"):
            continue
        if tool_name in allowset:
            continue
        tools_dict.pop(tool_name, None)
        if hasattr(registry, "tool_descriptions"):
            registry.tool_descriptions.pop(tool_name, None)
        removed.append(tool_name)

    if removed:
        logger.info(
            "Agent tool registry pruned %d tool(s) via AGENT_TOOL_ALLOWLIST",
            len(removed),
        )


# ============================================================================
# Planner allowlist helpers
# ============================================================================


def _agent_settings():
    """Return cached shared settings (hot reloadable via get_settings cache)."""

    return get_settings()


def _env_tool_allowlist() -> list[str] | None:
    """Resolve runtime allowlist with optional chat-tools merge.

    Default behavior merges AGENT_TOOL_ALLOWLIST with configs/catalog/chat_tools.yaml
    so newly curated chat tools are not accidentally pruned by stale env lists.
    Set AGENT_TOOL_ALLOWLIST_STRICT=1 to keep env allowlist strictly as-is.
    """

    try:
        from brain_researcher.services.agent.tool_allowlist_loader import (
            resolve_runtime_tool_allowlist,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to load chat_tools allowlist: %s", exc)
        return _agent_settings().tool_allowlist

    return resolve_runtime_tool_allowlist(_agent_settings().tool_allowlist)


def _canonical_runtime_tool_id(tool_id: str | None) -> str | None:
    normalized = str(tool_id or "").strip()
    if not normalized:
        return None
    return resolve_primary_runtime_tool_id(normalized) or normalized


def _expand_plan_surface_tool_ids(tool_ids: list[str] | None) -> list[str]:
    """Normalize plan-surface allowlists onto canonical runtime tool IDs."""

    if not tool_ids:
        return []

    try:
        from brain_researcher.services.agent.tool_allowlist_loader import (
            expand_plan_tool_ids,
        )
    except Exception:
        return [str(tool_id).strip() for tool_id in tool_ids if str(tool_id).strip()]
    return expand_plan_tool_ids(list(tool_ids))


def _normalize_allowlist_mode(allowlist_mode: str | None) -> str:
    mode = str(allowlist_mode or "").strip().lower()
    return "diagnostic" if mode == "diagnostic" else "curated"


_PLAN_SURFACE_EXTRA_ALLOWLIST: set[str] = {
    "connectivity_measures",
    "coreg_register",
    "demo_passthrough",
    "dmri_fit_model",
    "dmri_parcellate_connectome",
    "dmri_resolve_dwi_triplet",
    "eeg_preprocess",
    "epoch_events",
    "extract_timeseries",
    "fetch_atlas",
    "ieeg_connectivity",
    "ieeg_electrode_localize",
    "ieeg_epoch_features",
    "ieeg_preprocess",
    "kg_ingest",
    "kg_multihop_qa",
    "kg_shacl_validate",
    "list_dataset_assets",
    "meta_align",
    "meta_brainmap",
    "meta_combine",
    "nilearn_connectivity_matrix",
    "parcellation_fetch",
    "pet_coreg",
    "pet_parcellate",
    "pet_suvr",
    "resolve_bids",
    "resolve_montage",
    "resolve_space",
    "smri_parcellation_stats",
    "smri_recon",
    "smri_surface_export",
    "timefreq_tfr",
}


def _plan_surface_tool_allowlist(
    allowlist_mode: str | None,
) -> list[str] | None:
    """Resolve the allowlist used by /agent/plan and /agent/run_plan."""

    try:
        from brain_researcher.services.agent.tool_allowlist_loader import (
            expand_plan_tool_ids,
            resolve_plan_tool_allowlist,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to load plan allowlist helper: %s", exc)
        return _env_tool_allowlist()

    resolved = resolve_plan_tool_allowlist(
        _agent_settings().tool_allowlist,
        allowlist_mode=_normalize_allowlist_mode(allowlist_mode),
    )
    return expand_plan_tool_ids(
        list(resolved or []) + sorted(_PLAN_SURFACE_EXTRA_ALLOWLIST)
    )


def _effective_tool_allowset() -> set[str] | None:
    """Return the merged runtime allowlist as a set, if any."""

    allowlist = _env_tool_allowlist()
    if allowlist is None:
        return None
    return {tool_id for tool_id in allowlist if tool_id}


def _is_tool_allowed_by_runtime_policy(tool_id: str | None) -> bool:
    """Check tool access against the merged env/chat local-first policy."""

    allowset = _effective_tool_allowset()
    if allowset is None:
        return True
    return bool(tool_id) and tool_id in allowset


def _allowlist_violation_response(
    message: str,
    *,
    disallowed: list[str] | None = None,
    requested: list[str] | None = None,
    plan_id: str | None = None,
    denied_tool_id: str | None = None,
    denied_family: str | None = None,
    denial_stage: str | None = None,
    denial_reason_code: str | None = None,
):
    """Consistent error payload for allowlist violations."""

    denied_tool_id = denied_tool_id or next(
        (tool for tool in (disallowed or []) if tool),
        None,
    )
    denied_family = denied_family or _infer_tool_family(denied_tool_id)
    body: dict[str, Any] = {
        "error": "tool_not_allowed",
        "message": message,
    }
    if disallowed:
        body["disallowed_tools"] = sorted(disallowed)
    if requested:
        body["requested_tools"] = sorted({tool for tool in requested if tool})
    if plan_id:
        body["plan_id"] = plan_id
    if denied_tool_id:
        body["denied_tool_id"] = denied_tool_id
    if denied_family:
        body["denied_family"] = denied_family
    if denial_stage:
        body["denial_stage"] = denial_stage
    if denial_reason_code:
        body["denial_reason_code"] = denial_reason_code
    runtime_allowlist = _env_tool_allowlist()
    if runtime_allowlist:
        body["allowed_tools"] = sorted(runtime_allowlist)
    return jsonify(body), 403


def _apply_agent_allowlist(plan_request: PlanRequest) -> tuple[Response, int] | None:
    """Merge the environment tool allowlist into the incoming plan request."""

    plan_request.allowlist_mode = _normalize_allowlist_mode(
        getattr(plan_request, "allowlist_mode", None)
    )
    env_allowlist = _expand_plan_surface_tool_ids(
        _plan_surface_tool_allowlist(plan_request.allowlist_mode)
    )
    if not env_allowlist:
        return None

    env_allowset = set(env_allowlist)
    constraint = plan_request.constraints or ConstraintSpec()
    if constraint.tool_allowlist:
        requested_tools = list(constraint.tool_allowlist)
        normalized_requested = _expand_plan_surface_tool_ids(requested_tools)
        filtered = [tool for tool in normalized_requested if tool in env_allowset]
        if not filtered:
            return _allowlist_violation_response(
                "Requested tools are not permitted by the environment allowlist",
                requested=requested_tools,
                denied_tool_id=next(iter(requested_tools or []), None),
                denial_stage="request_constraints",
                denial_reason_code="requested_tools_not_permitted",
            )
        constraint.tool_allowlist = filtered
    else:
        constraint.tool_allowlist = list(env_allowlist)

    plan_request.constraints = constraint
    return None


def _collect_disallowed_tools_from_plan(plan: Plan) -> list[str]:
    """Return tools from the plan DAG that violate the env allowlist."""

    allowset = _plan_surface_allowset(getattr(plan, "allowlist_mode", None))
    if allowset is None:
        return []
    return sorted(
        {
            step.tool
            for step in plan.dag.steps
            if step.tool and step.tool not in allowset
        }
    )


def _collect_disallowed_tools_from_payload(plan_payload: dict[str, Any]) -> list[str]:
    """Same as above but operates on the cached JSON payload."""

    allowlist_mode = (
        (plan_payload or {}).get("allowlist_mode")
        if isinstance(plan_payload, dict)
        else None
    )
    allowset = _plan_surface_allowset(allowlist_mode)
    if allowset is None:
        return []

    dag = plan_payload.get("dag", {}) if isinstance(plan_payload, dict) else {}
    step_defs = dag.get("steps") or []
    if not step_defs and isinstance(plan_payload, dict):
        step_defs = plan_payload.get("steps", [])
    disallowed: set[str] = set()
    for raw in step_defs or []:
        tool_name = raw.get("tool") if isinstance(raw, dict) else None
        if tool_name and tool_name not in allowset:
            disallowed.add(tool_name)
    return sorted(disallowed)


def _plan_surface_allowset(allowlist_mode: str | None) -> set[str] | None:
    allowlist = _plan_surface_tool_allowlist(allowlist_mode)
    if allowlist is None:
        return None
    return {tool_id for tool_id in allowlist if tool_id}


def _studio_plan_allowlist_mode(payload: dict[str, Any]) -> str:
    """Resolve the allowlist mode for Studio planner requests."""

    if not isinstance(payload, dict):
        return ""
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        raw_mode = metadata.get("allowlist_mode")
        if raw_mode:
            return _normalize_allowlist_mode(str(raw_mode))
    return _normalize_allowlist_mode(payload.get("allowlist_mode"))


def _studio_plan_allowed_tool_id(tool_id: Any, allowset: set[str] | None) -> str | None:
    """Return the canonical Studio-planner tool id if allowed by policy."""

    canonical_tool_id = _canonical_runtime_tool_id(tool_id)
    if not canonical_tool_id:
        return None
    if allowset is not None and canonical_tool_id not in allowset:
        return None
    return canonical_tool_id


def _studio_plan_filter_candidates(
    tool_candidates: list[dict[str, Any]],
    allowset: set[str] | None,
) -> list[dict[str, Any]]:
    """Drop disallowed candidates and canonicalize the remaining tool ids."""

    filtered: list[dict[str, Any]] = []
    for cand in tool_candidates:
        if not isinstance(cand, dict):
            continue
        canonical_tool_id = _studio_plan_allowed_tool_id(
            cand.get("tool_id") or cand.get("id") or cand.get("tool"),
            allowset,
        )
        if not canonical_tool_id:
            continue
        filtered.append(
            {
                "tool_id": canonical_tool_id,
                "source": cand.get("source"),
                "score": cand.get("score"),
                "description": cand.get("description") or cand.get("name"),
            }
        )
    return filtered


def _studio_plan_normalize_ops(
    raw_ops: list[dict[str, Any]],
    allowset: set[str] | None,
    *,
    plan_id: str,
) -> tuple[list[dict[str, Any]], tuple[Response, int] | None]:
    """Canonicalize op tool ids and reject any disallowed tool references."""

    normalized_ops: list[dict[str, Any]] = []
    for op in raw_ops:
        if not isinstance(op, dict):
            continue
        op_copy = dict(op)
        metadata = op_copy.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        raw_tool_id = op_copy.get("tool_id") or metadata.get("tool_id")
        if raw_tool_id:
            canonical_tool_id = _studio_plan_allowed_tool_id(raw_tool_id, allowset)
            if not canonical_tool_id:
                return (
                    [],
                    _allowlist_violation_response(
                        "Studio plan references tools outside the environment allowlist",
                        disallowed=[str(raw_tool_id)],
                        plan_id=plan_id,
                        denied_tool_id=str(raw_tool_id),
                        denial_stage="studio_plan_postprocessing",
                        denial_reason_code="studio_plan_contains_disallowed_tools",
                    ),
                )
            metadata["tool_id"] = canonical_tool_id
            op_copy["tool_id"] = canonical_tool_id
            op_copy["metadata"] = metadata
        normalized_ops.append(op_copy)
    return normalized_ops, None


class PlanAllowlistError(ValueError):
    """Raised when attempting to run a plan containing disallowed tools."""

    def __init__(self, disallowed: list[str], plan_id: str | None = None):
        message = "Plan references tools outside the environment allowlist"
        super().__init__(message)
        self.disallowed = disallowed
        self.plan_id = plan_id


def _absolute_orchestrator_url(path: str) -> str:
    base = ORCHESTRATOR_BASE_URL.rstrip("/")
    if not path:
        return base
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base + "/", path.lstrip("/"))


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# Cache of plan_id -> serialized DAG so /agent/run_plan can replay the plan
_PLAN_CACHE: dict[str, dict[str, Any]] = globals().get("_PLAN_CACHE", {})


def _get_neo4j_driver():
    """Best-effort Neo4j driver for read-only run/plan lookup."""
    if _Neo4jDriver is None:
        return None
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    pwd = os.getenv("NEO4J_PASSWORD")
    if not uri or not pwd:
        return None
    try:
        return _Neo4jDriver(uri, auth=(user or "neo4j", pwd))
    except Exception:
        return None


def _strict_plan_validation_enabled() -> bool:
    """Return True if strict plan tool validation is enabled via env var."""
    return os.getenv("BR_STRICT_PLAN_TOOL_VALIDATION", "false").lower() in {
        "1",
        "true",
        "yes",
    }


# ============================================================================
# Planner contract helpers (H0A stub)
def _extract_keywords(name: str, description: str, category: str) -> list:
    """Extract keywords from tool name, description, and category."""
    import re

    text = f"{name} {description} {category}".lower()
    # Remove common stop words and extract meaningful terms
    keywords = re.findall(
        r"\b(?:fmri|mri|eeg|meg|neuroimaging|analysis|preprocessing|"
        r"registration|segmentation|connectivity|glm|statistical|"
        r"nilearn|fsl|ants|freesurfer|bids|pipeline|visualization|"
        r"diffusion|tractography|bold|dwi|t1w|t2w|func|anat|"
        r"tool|tools|list|available|show|help|what)\b",
        text,
    )
    return list(set(keywords))


# ============================================================================
# Planner contract helpers (H0A stub)
# ============================================================================

_STUB_PIPELINE = "connectivity"
_STUB_MODALITY = "fmri"
_STUB_PLAN_STEPS = (
    "fetch_atlas",
    "extract_timeseries",
    "nilearn_connectivity_matrix",
)

# Best-effort fallback tool mapping for stubbed multi-step pipelines.
# Kept intentionally empty until compatible alternatives exist in the catalog.
_FALLBACK_TOOL_MAP: dict[str, list[str]] = {}


def _act_llm_registry_surface_ids(registry) -> tuple[str, ...]:
    """Return the effective /act_llm tool ids after local-first pruning."""

    tool_ids = sorted(getattr(registry, "tools", {}).keys())
    allowset = _effective_tool_allowset()
    if allowset is None:
        return tuple(tool_ids)
    return tuple(tool_id for tool_id in tool_ids if tool_id in allowset)


def _act_llm_registry_cache_key(registry) -> str:
    """Stable cache key for the filtered /act_llm registry surface."""

    surface_ids = _act_llm_registry_surface_ids(registry)
    digest = hashlib.sha256("\n".join(surface_ids).encode("utf-8")).hexdigest()[:16]
    return f"surface:{len(surface_ids)}:{digest}"


def _clone_registry_surface(source_registry, tool_ids: tuple[str, ...]):
    """Create a lightweight ToolRegistry snapshot for the requested tool ids."""

    from brain_researcher.services.tools.tool_registry import ToolRegistry

    registry = ToolRegistry(
        auto_discover=False,
        use_capabilities=getattr(source_registry, "use_capabilities", True),
        enable_integrations=False,
        light_mode=getattr(source_registry, "light_mode", False),
        source_backend=getattr(source_registry, "source_backend", None),
    )

    registry.tools = {}
    registry.tool_descriptions = {}
    source_descriptions = getattr(source_registry, "tool_descriptions", {})
    for tool_id in tool_ids:
        tool = source_registry.get_tool(tool_id)
        if tool is None:
            continue
        registry.tools[tool_id] = tool
        description = source_descriptions.get(tool_id)
        if description is None:
            try:
                description = tool.get_tool_description()
            except Exception:  # pragma: no cover - defensive
                description = ""
        registry.tool_descriptions[tool_id] = description
    return registry


def _get_act_llm_tool_registry():
    """Return a cached filtered ToolRegistry snapshot for /act_llm."""

    source_registry = get_agent().tool_registry
    cache_key = _act_llm_registry_cache_key(source_registry)
    with _ACT_LLM_TOOL_REGISTRY_CACHE_LOCK:
        cached_registry = _ACT_LLM_TOOL_REGISTRY_CACHE.get(cache_key)
        if cached_registry is not None:
            return cached_registry, cache_key

        filtered_registry = _clone_registry_surface(
            source_registry, _act_llm_registry_surface_ids(source_registry)
        )
        _ACT_LLM_TOOL_REGISTRY_CACHE[cache_key] = filtered_registry
        return filtered_registry, cache_key


def reset_act_llm_cache() -> None:
    """Clear /act_llm registry snapshots and shared agent-factory caches."""

    with _ACT_LLM_TOOL_REGISTRY_CACHE_LOCK:
        _ACT_LLM_TOOL_REGISTRY_CACHE.clear()
    reset_llm_agent_cache()


def _get_cached_act_llm_agent(*, tool_mode: str, coding_bias: bool):
    """Resolve the cached /act_llm agent bound to the filtered registry surface."""

    tool_registry, tool_registry_cache_key = _get_act_llm_tool_registry()
    return get_llm_agent(
        tool_mode=tool_mode,
        coding_bias=coding_bias,
        tool_registry=tool_registry,
        tool_registry_cache_key=tool_registry_cache_key,
    )


def _normalize_act_llm_model_name(model_name: Any) -> str | None:
    """Normalize runtime model identifiers from provider-specific clients."""

    normalized = str(model_name or "").strip()
    if not normalized:
        return None
    if normalized.startswith("models/"):
        normalized = normalized.split("/", 1)[1]
    return normalized or None


def _resolve_act_llm_execution_metadata(
    agent_llm: Any, *, coding_mode: bool
) -> tuple[str, str]:
    """Return provider/model metadata from the bound runtime agent."""

    llm = getattr(agent_llm, "llm", None)
    model_name = None
    for attr_name in ("model_name", "model", "model_id", "model_name_or_path"):
        model_name = _normalize_act_llm_model_name(getattr(llm, attr_name, None))
        if model_name:
            break

    if not model_name:
        model_name = (
            os.getenv("DEFAULT_CODING_MODEL", DEFAULT_CODING_MODEL)
            if coding_mode
            else os.getenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
        )

    provider = "unknown"
    model_lower = model_name.lower()
    if "deepseek" in model_lower:
        provider = "deepseek"
    elif "gemini" in model_lower:
        provider = "gemini"
    elif "claude" in model_lower:
        provider = "anthropic"
    elif "gpt" in model_lower:
        provider = "openai"
    else:
        provider_family_fn = getattr(agent_llm, "_llm_provider_family", None)
        if callable(provider_family_fn):
            try:
                provider_family = str(provider_family_fn() or "").strip().lower()
            except Exception:
                provider_family = ""
            if provider_family in {"gemini", "anthropic", "openai"}:
                provider = provider_family

    return provider, model_name


def _resolve_tool_signature(
    tool_id: str,
) -> tuple[set[str] | None, set[str] | None]:
    """Return (consumes, produces) resource sets for a tool_id if known."""
    canonical_tool_id = _canonical_runtime_tool_id(tool_id) or tool_id
    raw_tool_id = str(tool_id or "").strip()
    checked: list[str] = []
    for candidate in (canonical_tool_id, raw_tool_id):
        if candidate and candidate not in checked:
            checked.append(candidate)

    tool = None
    for candidate in checked:
        try:
            tool = get_tool_by_id(candidate)
        except Exception:
            tool = None
        if tool is not None:
            break

    if tool is None:
        return None, None

    consumes = set(getattr(tool, "consumes", []) or [])
    produces = set(getattr(tool, "produces", []) or [])
    return consumes, produces


def _filter_fallback_tools(
    step: StepSpec,
    fallback_tools: list[str],
    *,
    strict: bool = False,
) -> list[str]:
    """Filter fallback tools to those with compatible inputs/outputs."""
    if not fallback_tools:
        return []

    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_runtime_tool_ids,
        )
    except Exception:
        resolve_runtime_tool_ids = None  # type: ignore

    step_consumes = set((step.consumes or {}).values())
    step_produces = set((step.produces or {}).values())
    available_params = set((step.consumes or {}).keys()) | set(
        (step.params or {}).keys()
    )

    filtered: list[str] = []
    for tool_id in fallback_tools:
        raw_tool_id = str(tool_id or "").strip()
        canonical_tool_id = _canonical_runtime_tool_id(raw_tool_id) or raw_tool_id
        runtime_candidates: list[str] = []
        for candidate in (canonical_tool_id, raw_tool_id):
            if candidate and candidate not in runtime_candidates:
                runtime_candidates.append(candidate)
        if resolve_runtime_tool_ids and raw_tool_id:
            for candidate in resolve_runtime_tool_ids(raw_tool_id, include_self=False):
                if candidate and candidate not in runtime_candidates:
                    runtime_candidates.append(candidate)
        if not runtime_candidates:
            runtime_candidates = [canonical_tool_id]

        consumes, produces = _resolve_tool_signature(canonical_tool_id)
        if strict and (consumes is None or produces is None):
            continue
        if (
            consumes is not None
            and step_consumes
            and not consumes.issubset(step_consumes)
        ):
            if strict:
                continue
        if (
            produces is not None
            and step_produces
            and not step_produces.issubset(produces)
        ):
            if strict:
                continue

        chosen = None
        for runtime_name in runtime_candidates:
            required = _get_required_params(runtime_name)
            if required is not None and not required.issubset(available_params):
                continue
            chosen = runtime_name
            break

        if chosen:
            filtered.append(chosen)
        elif not strict:
            # Keep explicit fallback hints when we cannot validate
            filtered.append(runtime_candidates[0])

    # Deduplicate while preserving order
    seen = set()
    return [t for t in filtered if not (t in seen or seen.add(t))]


def _resolve_runtime_tool_instance(tool_id: str | None):
    """Resolve a plan/catalog/runtime tool id to a live runtime tool instance."""

    normalized = _canonical_runtime_tool_id(tool_id)
    if not normalized:
        return None, None

    agent = get_agent()

    raw_tool_id = str(tool_id or "").strip()
    candidates: list[str] = []
    for candidate in (normalized, raw_tool_id):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_runtime_tool_ids,
        )
    except Exception:
        resolve_runtime_tool_ids = None  # type: ignore

    if resolve_runtime_tool_ids and raw_tool_id:
        for candidate in resolve_runtime_tool_ids(raw_tool_id, include_self=False):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    seen: set[str] = set()
    for candidate in candidates:
        candidate_id = str(candidate or "").strip()
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        tool = agent.tool_registry.get_tool(candidate_id)
        if tool is not None:
            return candidate_id, tool

    return None, None


def _load_stub_steps() -> dict[str, StepSpec]:
    """Build deterministic stub steps using the shared models."""

    atlas_step = StepSpec(
        id="s1",
        tool="fetch_atlas",
        consumes={"atlas_name": "atlas_name"},
        produces={"atlas_path": "atlas_path"},
        params={},
        runtime_kind="python",  # Use dedicated field instead of metadata
    )
    ts_step = StepSpec(
        id="s2",
        tool="extract_timeseries",
        consumes={"img": "fmri_img", "atlas": "atlas_path"},
        produces={"timeseries": "timeseries"},
        params={"detrend": True},
        runtime_kind="python",  # Use dedicated field instead of metadata
    )
    conn_step = StepSpec(
        id="s3",
        tool="nilearn_connectivity_matrix",
        consumes={"timeseries": "timeseries"},
        produces={"connectivity_matrix": "connectivity_matrix"},
        params={"method": "correlation", "kind": "correlation"},
        runtime_kind="python",  # Use dedicated field instead of metadata
    )
    return {step.id: step for step in (atlas_step, ts_step, conn_step)}


def _plan_context_from_request(
    plan_request: PlanRequest,
    *,
    query: str | None = None,
    tool_candidates: list[dict[str, Any]] | None = None,
    tool_candidate_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "pipeline": plan_request.pipeline,
        "domain": plan_request.domain,
        "modality": plan_request.modality,
        "inputs": plan_request.inputs,
        "constraints": (
            plan_request.constraints.model_dump(mode="json")
            if plan_request.constraints
            else None
        ),
    }
    if query:
        context["query"] = query
    if plan_request.query_understanding:
        context["query_understanding"] = plan_request.query_understanding
    if tool_candidates:
        context["tool_candidates"] = tool_candidates
    if tool_candidate_diagnostics:
        context["tool_candidate_diagnostics"] = tool_candidate_diagnostics
    return context


def _attach_plan_handoff(plan_payload: dict[str, Any]) -> dict[str, Any]:
    plan_payload["handoff"] = build_handoff_from_plan_payload(plan_payload)
    return plan_payload


def _register_plan(plan: Plan, context: dict[str, Any] | None = None) -> None:
    """Store the plan DAG for later SSE replay."""

    if not plan.chosen_tool and plan.dag.steps:
        plan.chosen_tool = plan.dag.steps[0].tool
    # Attach fallback tool list to the first step when candidates exist.
    if plan.dag.steps and isinstance(plan.candidates, list):
        primary = plan.chosen_tool or plan.dag.steps[0].tool
        primary = _canonical_runtime_tool_id(primary) or primary
        fallback_tools = []
        for cand in plan.candidates:
            cand_tool = _canonical_runtime_tool_id(
                cand.get("tool_id") or cand.get("tool")
            )
            if cand_tool and cand_tool != primary and cand_tool not in fallback_tools:
                fallback_tools.append(cand_tool)
        fallback_tools = _filter_fallback_tools(
            plan.dag.steps[0], fallback_tools, strict=True
        )
        if fallback_tools:
            step_meta = plan.dag.steps[0].metadata or {}
            existing = step_meta.get("fallback_tools") or []
            merged = []
            for tool_id in list(existing) + fallback_tools:
                if tool_id not in merged:
                    merged.append(tool_id)
            if merged:
                step_meta["fallback_tools"] = merged[:3]
            plan.dag.steps[0].metadata = step_meta

    # Attach best-effort fallback tool hints for stubbed pipelines.
    for step in plan.dag.steps:
        if step.tool:
            step.tool = _canonical_runtime_tool_id(step.tool) or step.tool
        if not step.tool:
            continue
        if step.metadata and step.metadata.get("fallback_tools"):
            filtered = _filter_fallback_tools(
                step, list(step.metadata.get("fallback_tools") or []), strict=True
            )
            step_meta = step.metadata or {}
            if filtered:
                step_meta["fallback_tools"] = filtered
            else:
                step_meta.pop("fallback_tools", None)
            step.metadata = step_meta
            continue
        fallback_tools = _FALLBACK_TOOL_MAP.get(step.tool, [])
        if fallback_tools:
            filtered = _filter_fallback_tools(step, fallback_tools, strict=True)
            if filtered:
                step.metadata = {**(step.metadata or {}), "fallback_tools": filtered}

    if plan.chosen_tool:
        plan.chosen_tool = (
            _canonical_runtime_tool_id(plan.chosen_tool) or plan.chosen_tool
        )
    payload = plan.model_dump(mode="json")
    if context:
        payload["context"] = context
    _attach_plan_handoff(payload)
    _annotate_plan_payload_tool_families(payload)

    _PLAN_CACHE[plan.plan_id] = payload

    if len(_PLAN_CACHE) > 32:
        # Drop the oldest cached plan
        oldest_plan_id = next(iter(_PLAN_CACHE))
        if oldest_plan_id != plan.plan_id:
            _PLAN_CACHE.pop(oldest_plan_id, None)


def _annotate_step_tool_family(step: dict[str, Any]) -> None:
    if not isinstance(step, dict):
        return
    tool_id = step.get("tool") or step.get("tool_id")
    if not tool_id:
        return
    metadata = step.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    if metadata.get("tool_family") or metadata.get("family"):
        return
    family = _infer_tool_family(tool_id)
    if family:
        metadata["tool_family"] = family
        step["metadata"] = metadata


def _annotate_plan_payload_tool_families(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    collections: list[list[dict[str, Any]]] = []
    steps = payload.get("steps")
    if isinstance(steps, list):
        collections.append(steps)
    dag = payload.get("dag")
    dag_steps = dag.get("steps") if isinstance(dag, dict) else None
    if isinstance(dag_steps, list) and dag_steps not in collections:
        collections.append(dag_steps)
    for step_list in collections:
        for step in step_list:
            _annotate_step_tool_family(step)


def _maybe_add_resolvers(
    steps: list[StepSpec],
    artifacts: list[ArtifactSpec],
    inputs: dict[str, str],
    requires_bids: bool = False,
    requires_space: bool = False,
    bids_output_name: str = "resolved_path",
) -> None:
    """
    Augment step list with BIDS or space resolvers if needed.

    Args:
        steps: Step list to modify in-place (prepends resolver steps)
        artifacts: Artifact list to modify in-place
        inputs: Input dictionary to check
        requires_bids: If True, prepend resolve_bids step
        requires_space: If True, prepend resolve_space step
    """
    subject_value = inputs.get("subject_id") or inputs.get("subject")
    if subject_value:
        inputs.setdefault("subject_id", subject_value)

    has_exact_asset_path = any(
        inputs.get(key)
        for key in (
            "t1w_image",
            "pet_image",
            "dwi_image",
            "resolved_path",
            "parcellation_labels",
            "reference_map",
        )
    )

    if inputs.get("dataset_ref") and not has_exact_asset_path:
        browse_step = StepSpec(
            id="browse_dataset_assets_s0",
            tool="list_dataset_assets",
            consumes={"dataset_ref": "dataset_ref"},
            produces={"asset_inventory_json": "report_json"},
            params={
                key: inputs.get(key)
                for key in (
                    "subject_id",
                    "session_id",
                    "task",
                    "run",
                    "datatype",
                    "suffix",
                    "space",
                    "derivative_kind",
                    "contrast",
                    "statistic",
                    "node",
                )
                if inputs.get(key)
            },
        )
        steps.insert(0, browse_step)
        artifacts.insert(
            0,
            ArtifactSpec(
                name="dataset_asset_inventory",
                rtype="report_json",
                description="Targeted dataset asset inventory for browse-before-resolve planning.",
            ),
        )

    if requires_bids and inputs.get("bids_root") and inputs.get("subject_id"):
        # Add resolve_bids as first step
        bids_step = StepSpec(
            id="resolve_s0",
            tool="resolve_bids",
            consumes={"bids_root": "bids_root", "subject_id": "subject_id"},
            produces={bids_output_name: bids_output_name},
            params={
                "datatype": inputs.get("datatype", "anat"),
                "suffix": inputs.get("suffix", "T1w"),
            },
        )
        steps.insert(0, bids_step)
        artifacts.insert(
            0,
            ArtifactSpec(
                name=bids_output_name,
                rtype="volume_3d",
                description="BIDS-resolved anatomical image",
            ),
        )

    if requires_space:
        space_name = inputs.get("space_name", "MNI152NLin2009cAsym")
        template_name = f"{space_name}_template"
        mask_name = f"{space_name}_mask"
        space_step = StepSpec(
            id=f"resolve_space_{space_name.lower()}",
            tool="resolve_space",
            consumes={},
            produces={
                "template_volume": template_name,
                "brain_mask": mask_name,
            },
            params={
                "space_name": space_name,
                "resolution": inputs.get("resolution", "2mm"),
            },
        )
        steps.insert(0, space_step)
        artifacts.insert(
            0,
            ArtifactSpec(
                name=template_name,
                rtype="volume_3d",
                description=f"{space_name} template",
            ),
        )
        artifacts.insert(
            1,
            ArtifactSpec(
                name=mask_name,
                rtype="mask_path",
                description=f"{space_name} brain mask",
            ),
        )


def _ensure_space(
    steps: list[StepSpec],
    artifacts: list[ArtifactSpec],
    inputs: dict[str, str],
    target_space: str,
    insert_at: int = 0,
) -> str:
    """
    Ensure a spatial template is available in the plan.

    Args:
        steps: Step list to modify
        artifacts: Artifact list to modify
        inputs: Input parameters
        target_space: Required space (e.g., "MNI152NLin2009cAsym")
        insert_at: Position to insert the resolver step

    Returns:
        Artifact name for the template volume
    """
    space_artifact = f"{target_space}_template"

    # Check if template already exists
    if space_artifact not in [a.name for a in artifacts]:
        space_step = StepSpec(
            id=f"space_{target_space.lower()}",
            tool="resolve_space",
            consumes={},
            produces={
                "template_volume": space_artifact,
                "brain_mask": f"{space_artifact}_mask",
            },
            params={
                "space_name": target_space,
                "resolution": inputs.get("resolution", "2mm"),
            },
        )
        steps.insert(insert_at, space_step)
        artifacts.append(
            ArtifactSpec(
                name=space_artifact,
                rtype="volume_3d",
                description=f"{target_space} template",
            )
        )
        artifacts.append(
            ArtifactSpec(
                name=f"{space_artifact}_mask",
                rtype="mask_path",
                description=f"{target_space} mask",
            )
        )

    return space_artifact


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _is_retryable_error(error: Exception) -> bool:
    """Determine if error is transient and retryable.

    PR-4: Helper for retry logic (Phase 3).
    """
    retryable_types = (TimeoutError, ConnectionError, OSError)
    if isinstance(error, retryable_types):
        return True

    # Check error message for retryable patterns
    error_str = str(error).lower()
    retryable_patterns = [
        "timeout",
        "connection",
        "temporary",
        "unavailable",
        "resource temporarily",
        "try again",
    ]
    return any(pattern in error_str for pattern in retryable_patterns)


# Legacy stub function (kept for backward compatibility)
# Initialize Flask app
app = Flask(__name__)

# The /agent/* routes were carved into agent_routes.py; register() wires them onto
# the Flask app each import (robust to per-test app reimport). agent_routes imports
# nothing from web_service at module load → cycle-free.
from brain_researcher.services.agent.agent_routes import (  # noqa: E402
    register as _register_agent_routes,
)

_register_agent_routes(app)

# The /api/* usage/budget/cli routes were carved into api_routes.py.
from brain_researcher.services.agent.api_routes import (  # noqa: E402
    register as _register_api_routes,
)

_register_api_routes(app)

# NOTE: The Web UI (Next.js) runs on :3000 and, in dev, calls the agent directly
# on :8000 with `credentials: 'include'`. For browsers to accept cross-origin
# credentialed requests, the server must:
#   1) set Access-Control-Allow-Credentials: true, and
#   2) echo an explicit origin (not "*").
# Keep this permissive for localhost development while remaining configurable.
_default_origins = ["http://127.0.0.1:3000", "http://localhost:3000"]
_origins_env = os.getenv("BR_UI_ORIGINS")
_origins = (
    [o.strip() for o in _origins_env.split(",") if o.strip()]
    if _origins_env
    else _default_origins
)
CORS(app, supports_credentials=True, origins=_origins)

# UI-facing API blueprint (thin wrappers for web UI)
from brain_researcher.services.agent.ui_api import ui_api  # noqa: E402

app.register_blueprint(ui_api, url_prefix="/api")

# Log module path to detect if using archived version
logger.info(
    "Agent web service loaded from: %s", inspect.getfile(inspect.currentframe())
)

# Initialize configuration at startup
from brain_researcher.services.agent.config import get_config  # noqa: E402

_config = get_config()
logger.info(f"Agent configuration loaded: {_config}")

from brain_researcher.services.agent.job_service import (  # noqa: E402
    maybe_initialize_job_service_for_startup,
)

maybe_initialize_job_service_for_startup()

# Set BR-KG URL if resolved
if _config.get("BR_KG_API_URL"):
    os.environ["BR_KG_API_URL"] = _config["BR_KG_API_URL"]

# ============================================================================
# Tool Context Helper
# ============================================================================


@ttl_cache(
    seconds=300
)  # Cache for 5 minutes (legacy helper; prefer the newer version above)
# ============================================================================
# Middleware for trace ID propagation
# ============================================================================


# ============================================================================
# Planner contract endpoints
# ============================================================================


@app.route("/agent/plan", methods=["POST"])
def agent_plan_contract():
    """
    Contract-first planner endpoint using catalog-driven selection.

    P0-1: Now uses choose_tool_catalog() to return Plan with selection reasoning
    (intent, candidates, chosen_tool, selection_reason).
    """
    start_time = time.perf_counter()
    _metrics.increment("planner_requests_total")
    try:
        payload = request.get_json(force=True) or {}
    except Exception as exc:  # pragma: no cover - handled by validation below
        logger.warning("Invalid JSON payload for /agent/plan: %s", exc)
        _metrics.increment("planner_errors_total")
        _metrics.record(
            "planner_request_duration_ms", (time.perf_counter() - start_time) * 1000
        )
        return jsonify({"error": "invalid_json"}), 400

    debug_selection = False
    debug_param = (
        payload.get("debug_selection") if isinstance(payload, dict) else None
    ) or request.args.get("debug_selection")
    if isinstance(debug_param, str):
        debug_selection = debug_param.lower() in {"1", "true", "yes", "y", "on"}
    elif debug_param is not None:
        debug_selection = bool(debug_param)

    requested_mode = payload.get("mode") if isinstance(payload, dict) else None
    if requested_mode not in (None, "catalog"):
        _metrics.increment("planner_errors_total")
        _metrics.record(
            "planner_request_duration_ms", (time.perf_counter() - start_time) * 1000
        )
        return (
            jsonify(
                {
                    "error": "invalid_mode",
                    "message": (
                        f"Invalid planner mode '{requested_mode}'. "
                        "Active planner runtime only supports 'catalog'."
                    ),
                }
            ),
            422,
        )

    try:
        plan_request = PlanRequest.model_validate(payload)
    except ValidationError as exc:
        _metrics.increment("planner_errors_total")
        _metrics.record(
            "planner_request_duration_ms", (time.perf_counter() - start_time) * 1000
        )
        return (
            jsonify({"error": "invalid_plan_request", "details": exc.errors()}),
            422,
        )

    plan_request.allowlist_mode = _normalize_allowlist_mode(
        getattr(plan_request, "allowlist_mode", None)
    )
    allowlist_error = _apply_agent_allowlist(plan_request)
    if allowlist_error is not None:
        return allowlist_error

    preflight_query = None
    if isinstance(payload, dict):
        preflight_query = payload.get("query") or payload.get("user_query")
    if not preflight_query:
        preflight_query = plan_request.pipeline

    preflight_tool_candidates: list[dict[str, Any]] = []
    preflight_tool_candidate_diagnostics: dict[str, Any] = {}
    resolution_state: dict[str, Any] = {}
    try:
        from brain_researcher.services.agent.query_models import QueryUnderstandingModel

        preflight_ctx: dict[str, Any] = {}
        if plan_request.query_understanding:
            preflight_ctx["query_understanding"] = plan_request.query_understanding
        if isinstance(payload, dict):
            for key in ("thread_id", "session_id", "runtime_surface", "run_id"):
                value = payload.get(key)
                if value:
                    preflight_ctx[key] = value
        preflight_ctx.setdefault("runtime_surface", "plan")

        tool_candidate_bundle = generate_tool_candidates(
            preflight_query,
            ctx=preflight_ctx,
            tool_retriever=_get_contract_tool_retriever(),
            registry=None,
        )
        preflight_ctx = tool_candidate_bundle.ctx
        qur = tool_candidate_bundle.query_understanding
        if plan_request.query_understanding is None and qur is not None:
            if isinstance(qur, dict):
                plan_request.query_understanding = qur
            else:
                plan_request.query_understanding = (
                    QueryUnderstandingModel.from_dataclass(qur).model_dump()
                )

        preflight_tool_candidates = list(tool_candidate_bundle.tool_candidates or [])
        preflight_tool_candidate_diagnostics = dict(
            tool_candidate_bundle.tool_candidate_diagnostics or {}
        )
        resolution_state = dict(tool_candidate_bundle.resolution_state or {})
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Planner preflight failed: %s", exc)

    # Active planner runtime is catalog-only; ignore BR_PLANNER_SOURCE legacy override.
    planner_mode = plan_request.mode or "catalog"

    try:
        plan = None
        plan_allowset = _plan_surface_allowset(plan_request.allowlist_mode)
        include_local_first = plan_request.allowlist_mode == "diagnostic"

        if planner_mode == "catalog":
            logger.info(
                "Using unified planner for '%s' (catalog mode)", plan_request.pipeline
            )

            # Preserve deterministic multi-step plans for known pipeline stubs.
            # (These remain useful for demos and unit tests.)
            try:
                plan = _build_plan_for_request(plan_request)
                plan.mode = "catalog"
                plan.allowlist_mode = plan_request.allowlist_mode
            except ValueError:
                plan = None

            if plan is None:
                from brain_researcher.services.agent.planner.unified_planner import (
                    get_default_unified_planner,
                )

                planner = get_default_unified_planner(
                    tool_retriever=_get_contract_tool_retriever()
                )
                modality = plan_request.modality[0] if plan_request.modality else None
                dataset_id = None
                task_family_hint = None
                if plan_request.query_understanding:
                    try:
                        from brain_researcher.services.agent.planner.kg_utils import (
                            extract_dataset_from_context,
                            extract_task_family,
                            normalize_dataset_id,
                        )

                        dataset_id = normalize_dataset_id(
                            extract_dataset_from_context(
                                {
                                    "query_understanding": plan_request.query_understanding
                                }
                            )
                        )
                        task_family_hint = extract_task_family(
                            {"query_understanding": plan_request.query_understanding},
                            plan_request.pipeline,
                        )
                    except Exception:
                        dataset_id = None
                        task_family_hint = None
                result = planner.plan(
                    query=plan_request.pipeline,
                    modality=modality,
                    query_understanding=plan_request.query_understanding,
                    dataset_id=dataset_id,
                    task_family_hint=task_family_hint,
                    max_candidates=5,
                    allowed_tool_ids=plan_allowset,
                    include_local_first=include_local_first,
                    allowlist_mode=plan_request.allowlist_mode,
                )

                if not result.candidates:
                    # Backward-compatible fallback path (preserve existing behaviors)
                    from brain_researcher.services.agent.planner import (
                        choose_tool_catalog,
                        choose_tool_intent_router,
                    )

                    intent_mask_reasons: list[Violation] = []
                    plan = choose_tool_intent_router(
                        plan_request,
                        max_candidates=5,
                        return_debug=debug_selection,
                        tool_retriever=_get_contract_tool_retriever(),
                        mask_reasons_out=intent_mask_reasons,
                        allowed_tool_ids=plan_allowset,
                    )
                    if plan is None:
                        plan = choose_tool_catalog(
                            request=plan_request,
                            max_candidates=5,
                            require_preflight_pass=True,
                            allowed_tool_ids=plan_allowset,
                            include_local_first=include_local_first,
                        )
                    if intent_mask_reasons:
                        existing = list(getattr(plan, "mask_reasons", None) or [])
                        plan.mask_reasons = existing + intent_mask_reasons
                    plan.allowlist_mode = plan_request.allowlist_mode
                    plan.mode = "catalog"
                else:
                    chosen_tool = result.chosen_tool_id or result.candidates[0].get(
                        "tool_id"
                    )
                    chosen_tool = str(chosen_tool) if chosen_tool else None

                    if not chosen_tool:
                        behavior_policy_info = None
                        for r in result.selection_reasons or []:
                            if (
                                isinstance(r, dict)
                                and r.get("code") == "behavior_policy_options"
                            ):
                                behavior_policy_info = r
                                break
                        selection_reasons_param = (
                            result.selection_reasons if debug_selection else []
                        )
                        if (
                            behavior_policy_info
                            and behavior_policy_info not in selection_reasons_param
                        ):
                            selection_reasons_param = (
                                selection_reasons_param or []
                            ) + [behavior_policy_info]

                        plan = Plan(
                            plan_id=str(uuid.uuid4()),
                            domain=plan_request.domain,
                            modality=plan_request.modality,
                            resolvable=False,
                            dag=PlanDAG(steps=[], artifacts=[]),
                            warnings=[
                                f"No suitable tools found for query: {plan_request.pipeline}"
                            ],
                            intent=result.intent,
                            predicted_capabilities=result.predicted_capabilities,
                            predicted_intents=result.predicted_intents,
                            capability_prediction=result.capability_prediction,
                            cross_stage_context=result.cross_stage_context,
                            loop_signals=result.loop_signals,
                            candidates=result.candidates or [],
                            selection_reasons=selection_reasons_param or None,
                            mask_reasons=result.mask_reasons,
                            timestamp=int(time.time()),
                            mode="catalog",
                            allowlist_mode=plan_request.allowlist_mode,
                            routing_diagnostics=result.routing_diagnostics,
                        )
                    else:
                        tool_cap = get_tool_by_id(chosen_tool)
                        runtime_kind = (
                            getattr(tool_cap, "runtime_kind", None) or "container"
                        )
                        runtime_kind = str(runtime_kind).strip().lower()
                        if runtime_kind in {"mcp", "external_api"}:
                            runtime_kind = "api"
                        if runtime_kind not in {"container", "python", "api"}:
                            runtime_kind = "container"

                        step = StepSpec(
                            id="001-main",
                            tool=chosen_tool,
                            params=plan_request.inputs,
                            runtime_kind=runtime_kind,  # Propagate backend type
                        )

                        top_score = float(result.scores.get(chosen_tool, 0.0))
                        chosen_name = getattr(tool_cap, "name", chosen_tool)
                        reason = (
                            f"Selected {chosen_name} (score: {top_score:.2f}). "
                            f"confidence={result.confidence_score:.2f}."
                        )

                        behavior_policy_info = None
                        for r in result.selection_reasons or []:
                            if (
                                isinstance(r, dict)
                                and r.get("code") == "behavior_policy_options"
                            ):
                                behavior_policy_info = r
                                break
                        selection_reasons_param = (
                            result.selection_reasons if debug_selection else []
                        )
                        if (
                            behavior_policy_info
                            and behavior_policy_info not in selection_reasons_param
                        ):
                            selection_reasons_param = (
                                selection_reasons_param or []
                            ) + [behavior_policy_info]
                        # Pull warnings from ConstraintSpec (preferred) or dict fallback.
                        warnings = []
                        if plan_request.constraints:
                            if hasattr(plan_request.constraints, "warnings"):
                                warnings = list(plan_request.constraints.warnings or [])
                            elif isinstance(plan_request.constraints, dict):
                                warnings = list(
                                    plan_request.constraints.get("warnings", []) or []
                                )
                        if behavior_policy_info and behavior_policy_info.get("table"):
                            warnings = list(warnings) + [
                                f"Behavior policies available:\n{behavior_policy_info.get('table')}"
                            ]

                        # Append behavior policy table into selection_reason for LLM prompts if present
                        if behavior_policy_info and behavior_policy_info.get("table"):
                            reason = f"{reason}\nBehavior policies:\n{behavior_policy_info.get('table')}"

                        # If user did not set policy_id but behavior policies are available, set default into params
                        if behavior_policy_info and behavior_policy_info.get(
                            "policies"
                        ):
                            try:
                                params = step.params or {}
                                user_policy = (
                                    plan_request.inputs.get("behavior_policy_id")
                                    if isinstance(plan_request.inputs, dict)
                                    else None
                                )
                                if user_policy:
                                    params["policy_id"] = user_policy
                                elif (
                                    "policy_id" not in params and "policy" not in params
                                ):
                                    first = behavior_policy_info["policies"][0]
                                    if isinstance(first, dict) and first.get(
                                        "policy_id"
                                    ):
                                        params["policy_id"] = first["policy_id"]
                                step.params = params
                            except Exception:
                                pass

                        plan = Plan(
                            plan_id=str(uuid.uuid4()),
                            domain=plan_request.domain,
                            modality=plan_request.modality,
                            resolvable=True,
                            dag=PlanDAG(steps=[step], artifacts=[]),
                            constraints=plan_request.constraints,
                            intent=result.intent,
                            predicted_capabilities=result.predicted_capabilities,
                            predicted_intents=result.predicted_intents,
                            capability_prediction=result.capability_prediction,
                            cross_stage_context=result.cross_stage_context,
                            loop_signals=result.loop_signals,
                            candidates=result.candidates,
                            chosen_tool=chosen_tool,
                            selection_reason=reason,
                            selection_reasons=selection_reasons_param or None,
                            mask_reasons=result.mask_reasons,
                            estimates={
                                "confidence_score": result.confidence_score,
                            },
                            warnings=warnings,
                            timestamp=int(time.time()),
                            mode="catalog",
                            allowlist_mode=plan_request.allowlist_mode,
                            routing_diagnostics=result.routing_diagnostics,
                        )

            # Short-circuit if unresolvable and strict validation enabled
            if not plan.resolvable and _strict_plan_validation_enabled():
                logger.error(
                    f"Catalog planner could not resolve plan for '{plan_request.pipeline}' "
                    f"and strict validation is enabled"
                )
                _metrics.increment("planner_errors_total")
                _metrics.record(
                    "planner_request_duration_ms",
                    (time.perf_counter() - start_time) * 1000,
                )
                return (
                    jsonify(
                        {
                            "error": "unresolvable_plan",
                            "message": f"Could not find suitable tools for: {plan_request.pipeline}",
                            "plan_id": plan.plan_id,
                            "warnings": plan.warnings,
                        }
                    ),
                    422,
                )
        else:
            # Invalid mode should have been rejected before PlanRequest validation.
            _metrics.increment("planner_errors_total")
            _metrics.record(
                "planner_request_duration_ms", (time.perf_counter() - start_time) * 1000
            )
            return (
                jsonify(
                    {
                        "error": "invalid_mode",
                        "message": (
                            f"Invalid planner mode '{planner_mode}'. "
                            "Active planner runtime only supports 'catalog'."
                        ),
                    }
                ),
                422,
            )

        strict_plan_validation = _strict_plan_validation_enabled()
        if strict_plan_validation:
            missing_tools: list[str] = []
            for step in plan.dag.steps:
                tool_id = step.tool
                if _resolve_runtime_tool_instance(tool_id)[1] is None:
                    missing_tools.append(tool_id)

            if missing_tools:
                agent = get_agent()
                registry_tools: list[str] = []
                if hasattr(agent.tool_registry, "get_all_tools"):
                    try:
                        registry_tools = [
                            tool.get_tool_name()
                            for tool in agent.tool_registry.get_all_tools()
                        ]
                    except Exception:  # pragma: no cover - defensive fallback
                        registry_tools = []
                if not registry_tools and hasattr(agent.tool_registry, "tools"):
                    registry_tools = list(agent.tool_registry.tools.keys())  # type: ignore[attr-defined]

                _metrics.increment("planner_errors_total")
                _metrics.record(
                    "planner_request_duration_ms",
                    (time.perf_counter() - start_time) * 1000,
                )
                return (
                    jsonify(
                        {
                            "error": "tools_not_available",
                            "message": "The following tools are not available in the agent runtime",
                            "missing_tools": missing_tools,
                            "available_tools": registry_tools[:20],
                            "total_available": len(registry_tools),
                        }
                    ),
                    422,
                )

        disallowed_tools = _collect_disallowed_tools_from_plan(plan)
        if disallowed_tools:
            return _allowlist_violation_response(
                "Plan references tools outside the environment allowlist",
                disallowed=disallowed_tools,
                plan_id=plan.plan_id,
                denied_tool_id=next(iter(disallowed_tools or []), None),
                denial_stage="plan_step_allowlist_check",
                denial_reason_code="plan_contains_disallowed_tools",
            )

        # PR-4 Issue #3: Validate chosen tool exists in agent registry
        if plan.resolvable and plan.chosen_tool:
            if plan_allowset is not None and plan.chosen_tool not in plan_allowset:
                return _allowlist_violation_response(
                    f"Selected tool '{plan.chosen_tool}' is not permitted by the environment",
                    disallowed=[plan.chosen_tool],
                    plan_id=plan.plan_id,
                    denied_tool_id=plan.chosen_tool,
                    denied_family=_infer_tool_family(plan.chosen_tool),
                    denial_stage="post_plan_validation",
                    denial_reason_code="selected_tool_not_permitted",
                )
            if strict_plan_validation:
                _, tool_instance = _resolve_runtime_tool_instance(plan.chosen_tool)
                if not tool_instance:
                    agent = get_agent()
                    registry_tools: list[str] = []
                    if hasattr(agent.tool_registry, "get_all_tools"):
                        try:
                            registry_tools = [
                                tool.get_tool_name()
                                for tool in agent.tool_registry.get_all_tools()
                            ]
                        except Exception:  # pragma: no cover - defensive fallback
                            registry_tools = []
                    if not registry_tools and hasattr(agent.tool_registry, "tools"):
                        registry_tools = list(agent.tool_registry.tools.keys())  # type: ignore[attr-defined]

                    return (
                        jsonify(
                            {
                                "error": "tool_not_available",
                                "message": f"Selected tool '{plan.chosen_tool}' is not available in the agent runtime",
                                "missing_tools": [plan.chosen_tool],
                                "chosen_tool": plan.chosen_tool,
                                "available_tools": registry_tools[:20],
                                "total_available": len(registry_tools),
                            }
                        ),
                        422,
                    )

        # Cache for potential /agent/run_plan call, preserving request context
        plan_payload = plan.model_dump(mode="json")
        plan_routing_diagnostics = _build_plan_routing_diagnostics(
            candidate_rows=list(plan_payload.get("candidates") or []),
            chosen_tool=plan_payload.get("chosen_tool"),
            preflight_tool_candidate_diagnostics=preflight_tool_candidate_diagnostics,
            routing_latency_ms=(
                (plan_payload.get("routing_diagnostics") or {}).get(
                    "routing_latency_ms"
                )
            ),
        )
        plan_routing_diagnostics["allowlist_mode"] = (
            plan_payload.get("allowlist_mode") or plan_request.allowlist_mode
        )
        plan_routing_diagnostics["allowlist_masking"] = plan_allowset is not None
        if plan_payload.get("routing_diagnostics"):
            plan_routing_diagnostics.update(plan_payload["routing_diagnostics"])
        plan_payload["routing_diagnostics"] = plan_routing_diagnostics
        plan_payload["context"] = _plan_context_from_request(
            plan_request,
            query=preflight_query,
            tool_candidates=preflight_tool_candidates or None,
            tool_candidate_diagnostics=preflight_tool_candidate_diagnostics or None,
        )
        if isinstance(payload, dict):
            ctx = plan_payload.get("context") or {}
            user_id = payload.get("user_id") or payload.get("account_id")
            workspace_id = payload.get("workspace_id") or payload.get("org_id")
            if user_id:
                ctx["user_id"] = user_id
            if workspace_id:
                ctx["workspace_id"] = workspace_id
            plan_payload["context"] = ctx
        _attach_plan_handoff(plan_payload)
        _annotate_plan_payload_tool_families(plan_payload)

        # TODO-2: Explicit planner state + append-only diffs (UI + analytics)
        try:
            from brain_researcher.services.agent.planner_confidence import (
                compute_confidence_summary,
            )
            from brain_researcher.services.agent.planner_state import (
                PlannerEvent,
                PlannerEventLogger,
                PlannerEventType,
            )
            from brain_researcher.services.agent.planner_trace import (
                build_planner_trace,
            )

            trace_events, trace_state = build_planner_trace(
                plan_payload,
                request_payload=plan_request.model_dump(mode="json"),
            )
            tool_candidates_ctx = (plan_payload.get("context") or {}).get(
                "tool_candidates"
            )
            if tool_candidates_ctx:
                trace_state["tool_candidates"] = tool_candidates_ctx
            tool_candidate_diagnostics_ctx = (plan_payload.get("context") or {}).get(
                "tool_candidate_diagnostics"
            )
            if tool_candidate_diagnostics_ctx:
                trace_state["tool_candidate_diagnostics"] = (
                    tool_candidate_diagnostics_ctx
                )
            query_understanding_ctx = (plan_payload.get("context") or {}).get(
                "query_understanding"
            )
            if query_understanding_ctx:
                trace_state["query_understanding"] = query_understanding_ctx
            if plan_payload.get("routing_diagnostics"):
                trace_state["routing_diagnostics"] = plan_payload["routing_diagnostics"]
            if resolution_state.get("step_statuses"):
                trace_state["step_statuses"] = resolution_state["step_statuses"]
            if resolution_state.get("pending_decisions") is not None:
                trace_state["pending_decisions"] = resolution_state["pending_decisions"]
            if resolution_state.get("resolution_cache_stats"):
                trace_state["resolution_cache_stats"] = resolution_state[
                    "resolution_cache_stats"
                ]

            resolution_events = resolution_state.get("resolution_events") or []
            event_type_map = {
                "resolution_cache_hit": PlannerEventType.RESOLUTION_CACHE_HIT,
                "resolution_cache_miss": PlannerEventType.RESOLUTION_CACHE_MISS,
                "resolution_discovery_bounded": PlannerEventType.RESOLUTION_DISCOVERY_BOUNDED,
                "resolution_decision_required": PlannerEventType.RESOLUTION_DECISION_REQUIRED,
                "resolution_decision_applied": PlannerEventType.RESOLUTION_DECISION_APPLIED,
            }
            for raw_event in resolution_events:
                if not isinstance(raw_event, dict):
                    continue
                raw_type = raw_event.get("event_type")
                planner_event_type = event_type_map.get(str(raw_type))
                if planner_event_type is None:
                    continue
                trace_events.append(
                    PlannerEvent(
                        event_type=planner_event_type,
                        payload=raw_event.get("payload") or {},
                        diff={},
                    )
                )
            plan_payload["planner_events"] = [e.to_dict() for e in trace_events]
            plan_payload["planner_state"] = trace_state

            # Confidence decomposition (step/branch/plan) + backward-compatible confidence_score
            run_summary = compute_confidence_summary(
                plan_payload,
                planner_events=plan_payload.get("planner_events"),
            )
            plan_payload["run_summary"] = run_summary
            plan_payload["plan_conf"] = run_summary.get("plan_conf")
            plan_payload["confidence_score"] = run_summary.get("plan_conf")
            # Also attach to in-memory Plan model (for downstream serialization)
            try:
                plan.planner_events = plan_payload.get("planner_events")
                plan.planner_state = plan_payload.get("planner_state")
                plan.run_summary = run_summary
                plan.plan_conf = run_summary.get("plan_conf")
                plan.confidence_score = run_summary.get("plan_conf")
            except Exception:
                pass

            # Persist append-only events to JSONL (best-effort; never fail planning)
            PlannerEventLogger(run_id=plan.plan_id).log_many(trace_events)
        except Exception as trace_exc:  # pragma: no cover - best-effort
            logger.debug("Planner trace generation/logging failed: %s", trace_exc)
        finally:
            if plan_payload.get("planner_state") is None and (
                preflight_tool_candidates
                or plan_request.query_understanding
                or resolution_state
            ):
                plan_payload["planner_state"] = {
                    "tool_candidates": preflight_tool_candidates,
                    "tool_candidate_diagnostics": preflight_tool_candidate_diagnostics,
                    "query_understanding": plan_request.query_understanding,
                    "step_statuses": resolution_state.get("step_statuses") or {},
                    "pending_decisions": resolution_state.get("pending_decisions")
                    or [],
                    "resolution_cache_stats": resolution_state.get(
                        "resolution_cache_stats"
                    )
                    or {},
                    "routing_diagnostics": plan_payload.get("routing_diagnostics")
                    or {},
                }
                try:
                    plan.planner_state = plan_payload.get("planner_state")
                except Exception:
                    pass

        # Record plan to PlanMemory (best-effort; don't fail planning).
        plan_memory = _get_plan_memory()
        if plan_memory:
            try:
                ctx = plan_payload.get("context") or {}
                user_id = (
                    ctx.get("user_id")
                    or ctx.get("account_id")
                    or os.getenv("BR_PLAN_MEMORY_DEFAULT_USER", "anonymous")
                )
                workspace_id = (
                    ctx.get("workspace_id")
                    or ctx.get("org_id")
                    or os.getenv("BR_PLAN_MEMORY_DEFAULT_WORKSPACE")
                )
                plan_memory_id = plan_memory.record_plan(
                    plan=plan_payload,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    query=preflight_query,
                )
                plan_payload["plan_memory_id"] = plan_memory_id
            except Exception as exc:  # pragma: no cover - best-effort
                logger.debug("Plan memory record failed: %s", exc)

        _PLAN_CACHE[plan.plan_id] = plan_payload

        routing_diagnostics = plan_routing_diagnostics or {}
        _metrics.record_tool_routing(
            surface="plan",
            candidate_count=routing_diagnostics.get("candidate_count"),
            selected_rank=routing_diagnostics.get("selected_tool_rank"),
            candidate_generation_latency_ms=(
                preflight_tool_candidate_diagnostics.get(
                    "candidate_generation_latency_ms"
                )
                if preflight_tool_candidate_diagnostics
                else None
            ),
            routing_latency_ms=routing_diagnostics.get("routing_latency_ms"),
            top_k_hits={
                5: bool(routing_diagnostics.get("selected_tool_in_top_5")),
                10: bool(routing_diagnostics.get("selected_tool_in_top_10")),
            },
        )

        _metrics.record(
            "planner_request_duration_ms", (time.perf_counter() - start_time) * 1000
        )
        return jsonify(plan_payload), 200

    except Exception as exc:
        logger.exception(f"Plan generation failed: {exc}")
        _metrics.increment("planner_errors_total")
        _metrics.record(
            "planner_request_duration_ms", (time.perf_counter() - start_time) * 1000
        )
        return jsonify({"error": "plan_failed", "message": str(exc)}), 500


# ============================================================================
# Nipype Export Endpoint
# ============================================================================


class NipypeExportRequest(BaseModel):
    """Request body for Nipype workflow export."""

    plan_id: str | None = Field(
        None, description="Plan ID from cache (if plan not provided)"
    )
    plan: dict[str, Any] | None = Field(
        None, description="Full Plan object (if plan_id not provided)"
    )
    options: dict[str, Any] | None = Field(
        default_factory=dict,
        description="Export options: plugin, plugin_args, output_dir, strict",
    )


# ============================================================================
# Unified Workflow Export Endpoint (Nipype + Pydra)
# ============================================================================


class WorkflowExportRequest(BaseModel):
    """Request body for unified workflow export."""

    plan_id: str | None = Field(
        None, description="Plan ID from cache (if plan not provided)"
    )
    plan: dict[str, Any] | None = Field(
        None, description="Full Plan object (if plan_id not provided)"
    )
    format: str = Field("nipype", description="Export format: nipype or pydra")
    options: dict[str, Any] | None = Field(
        default_factory=dict,
        description="Export options: plugin, plugin_args, output_dir, strict",
    )


# ---------------------------------------------------------------------------
# Neurodesk dispatch endpoints
# ---------------------------------------------------------------------------


@app.route("/neurodesk/dispatch/execute", methods=["POST"])
def neurodesk_execute_dispatch():
    """Execute a previously staged (pending_dispatch) Neurodesk artifact.

    Request body:
    {
        "artifact_id": "nd-script-abc123",
        "mode": "local" | "k8s" | "handoff"
    }

    Response (success, 200):
    {
        "mode": "k8s",
        "ref": "nd-br-01-fsl_bet-a1b2c3",
        "script_path": "/...",
        "instructions": "..."
    }
    """
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        body = {}

    artifact_id = body.get("artifact_id", "").strip()
    mode = body.get("mode", "").strip()

    if not artifact_id:
        return jsonify({"error": "missing_artifact_id"}), 400
    if mode not in ("local", "k8s", "handoff"):
        return (
            jsonify({"error": "invalid_mode", "allowed": ["local", "k8s", "handoff"]}),
            400,
        )

    try:
        from brain_researcher.services.tools.neurodesk_compiler import (
            NeurodeskDispatcher,
        )

        dispatcher = NeurodeskDispatcher(
            mode=mode,
            config={
                "namespace": os.environ.get("BR_K8S_NAMESPACE", "default"),
                "neurodesk_image": os.environ.get(
                    "BR_NEURODESK_IMAGE", "ghcr.io/neurodesk/neurodesktop:latest"
                ),
                "cvmfs_host_path": os.environ.get("BR_CVMFS_HOST_PATH", "/cvmfs"),
            },
        )
        result = dispatcher.execute_dispatch(artifact_id, mode)
        return jsonify(
            {
                "mode": result.mode,
                "ref": result.ref,
                "script_path": result.script_path,
                "instructions": result.instructions,
            }
        )
    except ValueError as exc:
        return jsonify({"error": "dispatch_error", "message": str(exc)}), 404
    except Exception as exc:
        logger.exception("neurodesk_execute_dispatch failed: %s", exc)
        return jsonify({"error": "dispatch_failed", "message": str(exc)}), 500


@app.route("/neurodesk/artifacts/<artifact_id>/complete", methods=["POST"])
def neurodesk_register_completion(artifact_id: str):
    """Register completion of a dispatched Neurodesk job.

    Called by the Neurodesk environment or user after the job finishes.

    Request body:
    {
        "output_paths": ["/out/brain.nii.gz"],
        "exit_code": 0,
        "notes": "optional free-text"
    }

    Response (success, 200):
    { "artifact_id": "...", "status": "completed", "output_paths": [...] }
    """
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        body = {}

    try:
        from brain_researcher.services.tools.neurodesk_compiler import (
            NeurodeskDispatcher,
        )

        dispatcher = NeurodeskDispatcher(mode="handoff", config={})
        record = dispatcher.register_completion(
            artifact_id,
            output_paths=body.get("output_paths") or [],
            exit_code=body.get("exit_code"),
            notes=body.get("notes"),
        )
        return jsonify(
            {
                "artifact_id": artifact_id,
                "status": record.get("status"),
                "output_paths": record.get("output_paths", []),
            }
        )
    except ValueError as exc:
        return jsonify({"error": "not_found", "message": str(exc)}), 404
    except Exception as exc:
        logger.exception("neurodesk_register_completion failed: %s", exc)
        return jsonify({"error": "registration_failed", "message": str(exc)}), 500


@app.before_request
def before_request():
    """Add trace ID to request context."""
    g.trace_id = get_trace_id(request.headers) or str(uuid.uuid4())
    g.request_id = get_request_id(request.headers) or str(uuid.uuid4())
    incoming_run_id = request.headers.get("X-Run-ID")
    if incoming_run_id:
        g.client_run_id = incoming_run_id
    logger.info(f"[{g.trace_id}] {request.method} {request.path}")


@app.after_request
def after_request(response):
    """Add trace ID to response headers."""
    if hasattr(g, "trace_id") or hasattr(g, "request_id"):
        set_trace_headers(
            response.headers,
            getattr(g, "trace_id", None),
            getattr(g, "request_id", None),
        )
    set_api_version(response.headers)
    if hasattr(g, "run_id"):
        response.headers["X-Run-ID"] = g.run_id
    elif hasattr(g, "client_run_id"):
        response.headers["X-Run-ID"] = g.client_run_id
    return response


# ============================================================================
# Unified error handling
# ============================================================================


def create_error_response(
    code: str, message: str, status_code: int = 500, retry_after: int | None = None
):
    """Create standardized error response.

    Args:
        code: Error code (e.g., 'auth_required', 'rate_limited', 'not_found')
        message: Human-readable error description
        status_code: HTTP status code
        retry_after: Optional seconds until retry is allowed (for rate limits)

    Returns:
        Tuple of (response, status_code)
    """
    trace_id = getattr(g, "trace_id", str(uuid.uuid4()))
    run_id = getattr(g, "run_id", getattr(g, "client_run_id", telemetry.new_run_id()))
    g.run_id = run_id

    body = {
        "error": code,
        "detail": scrub_text(message),
        "trace_id": trace_id,
    }
    if retry_after is not None:
        body["retry_after"] = retry_after

    return jsonify(body), status_code


def api_error(
    code: str, detail: str, status: int = 500, retry_after: int | None = None
):
    """Simple error response for API endpoints.

    Standardized format: {"error": code, "detail": message, "retry_after": seconds|null}

    Args:
        code: Short error code (e.g., 'auth_required', 'not_found')
        detail: Human-readable message
        status: HTTP status code
        retry_after: Seconds until retry allowed (for 429 responses)

    Returns:
        Tuple of (Flask Response, status code)
    """
    body = {"error": code, "detail": scrub_text(detail)}
    if retry_after is not None:
        body["retry_after"] = retry_after
    return jsonify(body), status


# Error code to HTTP status mapping
ERROR_CODE_TO_HTTP = {
    "validation_error": 400,
    "invalid_parameter": 400,
    "auth_required": 401,
    "forbidden": 403,
    "not_found": 404,
    "rate_limited": 429,
    "timeout": 504,
    "tool_error": 500,
    "upstream_error": 502,
    "internal_error": 500,
    # Legacy uppercase codes
    "VALIDATION_ERROR": 400,
    "INVALID_PARAMETER": 400,
    "NOT_FOUND": 404,
    "TIMEOUT": 504,
    "TOOL_ERROR": 500,
    "UPSTREAM_ERROR": 502,
    "RATE_LIMITED": 429,
    "INTERNAL_ERROR": 500,
}

# Global variables for lazy initialization
_agent = None
_rag_system = None
# _config is already initialized at the top - don't reset it
_tool_mapper = None
_history_manager = None
_plan_memory = None
_recovery_router = None


def get_agent():
    """Lazy initialization of NeuroAgent to avoid circular imports."""
    global _agent
    if _agent is None:
        logger.info("Initializing NeuroAgent for the first time")
        init_start = time.perf_counter()
        from brain_researcher.services.agent.agents.neuro_agent import NeuroAgent
        from brain_researcher.services.tools.tool_registry import ToolRegistry

        _ensure_tool_modules_loaded()
        if os.getenv("DISABLE_TOOL_DISCOVERY", "0").lower() in {"1", "true", "yes"}:
            logger.warning(
                "DISABLE_TOOL_DISCOVERY=1 set – initializing NeuroAgent with empty registry"
            )
            empty_registry = ToolRegistry(
                auto_discover=False, use_capabilities=False, enable_integrations=False
            )
            _agent = NeuroAgent(tool_registry=empty_registry)
        else:
            _agent = NeuroAgent()
        _filter_registry_by_allowlist(_agent.tool_registry)
        tool_count = len(_agent.tool_registry.get_all_tools())
        init_duration = time.perf_counter() - init_start
        logger.info(
            "NeuroAgent initialized in %.2fs with %d tools",
            init_duration,
            tool_count,
        )

        # Initialize tool mapper with registry
        global _tool_mapper
        from brain_researcher.services.agent.tool_mapper import get_tool_mapper

        _tool_mapper = get_tool_mapper(_agent.tool_registry)
    else:
        logger.debug("Returning cached NeuroAgent instance")
    return _agent


def _get_plan_memory():
    """Lazy init for plan memory (used for failure logging)."""
    global _plan_memory
    if _plan_memory is None:
        try:
            from brain_researcher.services.agent.plan_memory import create_plan_memory

            _plan_memory = create_plan_memory()
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("PlanMemory init failed: %s", exc)
            _plan_memory = False
    return _plan_memory if _plan_memory is not False else None


def _get_recovery_router():
    """Lazy init for recovery tool routing (best effort)."""
    global _recovery_router
    if _recovery_router is None:
        try:
            from brain_researcher.services.agent.tool_router import (
                ToolRouter,
                load_tool_families,
            )

            def _truthy(value: str | None) -> bool:
                return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}

            allow_dangerous = _truthy(os.getenv("BR_RECOVERY_ALLOW_DANGEROUS"))
            allow_internal = _truthy(os.getenv("BR_RECOVERY_ALLOW_INTERNAL"))
            allowlist = _env_tool_allowlist()
            chat_whitelist = set(allowlist) if allowlist is not None else None

            agent = get_agent()
            _recovery_router = ToolRouter(
                core_registry=agent.tool_registry,
                families=load_tool_families(),
                chat_whitelist=chat_whitelist,
                allow_dangerous=allow_dangerous,
                allow_internal=allow_internal,
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Recovery router init failed: %s", exc)
            _recovery_router = False
    return _recovery_router if _recovery_router is not False else None


@lru_cache(maxsize=1)
def _get_tool_family_lookup():
    """Build leaf-id -> family lookup, preferring alias families for recovery."""
    try:
        from brain_researcher.services.agent.tool_router import load_tool_families
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Tool family load failed: %s", exc)
        return {}, {}, {}
    families = load_tool_families()
    alias_sets: dict[str, set[str]] = {}
    for alias in ("download", "container"):
        fam = families.get(alias)
        if fam and isinstance(fam.ops, dict):
            alias_sets[alias] = set(fam.ops.values())
        else:
            alias_sets[alias] = set()
    leaf_to_family: dict[str, str] = {}
    for fam in families.values():
        ops = fam.ops if isinstance(fam.ops, dict) else {}
        for leaf_id in ops.values():
            if leaf_id and leaf_id not in leaf_to_family:
                leaf_to_family[leaf_id] = fam.id
    return families, alias_sets, leaf_to_family


def _infer_tool_family(tool_id: str | None) -> str | None:
    if not tool_id:
        return None
    families, alias_sets, leaf_to_family = _get_tool_family_lookup()
    if tool_id in families:
        return tool_id
    for alias in ("download", "container"):
        if tool_id in alias_sets.get(alias, set()):
            return alias
    if tool_id.startswith("container."):
        return "container"
    return leaf_to_family.get(tool_id)


def get_rag_system():
    """Lazy initialization of RAG system."""
    global _rag_system
    if _rag_system is None:
        from brain_researcher.core.analysis.rag_retrieval import RAGKnowledgeSystem

        _rag_system = RAGKnowledgeSystem()
    return _rag_system


def get_history():
    """Lazy initialization of history manager."""
    global _history_manager
    if _history_manager is None:
        from brain_researcher.services.agent.history import get_history_manager

        _history_manager = get_history_manager()
    return _history_manager


# (moved ttl_cache above to ensure availability before first use)


# Rate limiting decorator
def rate_limit(max_per_minute=30):
    """Simple rate limiting decorator."""

    def decorator(f):
        last_reset = {"time": time.time(), "count": 0}

        @wraps(f)
        def wrapper(*args, **kwargs):
            now = time.time()
            if now - last_reset["time"] > 60:
                last_reset["time"] = now
                last_reset["count"] = 0

            if last_reset["count"] >= max_per_minute:
                return (
                    jsonify({"error": "Rate limit exceeded. Please try again later."}),
                    429,
                )

            last_reset["count"] += 1
            return f(*args, **kwargs)

        return wrapper

    return decorator


# The /runs/* routes were carved into run_routes.py; register() wires them onto
# the app here (after rate_limit is defined, since one route is rate-limited).
from brain_researcher.services.agent.run_routes import (  # noqa: E402
    register as _register_run_routes,
)

_register_run_routes(app)

# The /tools/* routes were carved into tool_routes.py; register() wires them onto
# the app here (after rate_limit + ttl_cache are defined, since some are wrapped).
from brain_researcher.services.agent.tool_routes import (  # noqa: E402
    register as _register_tool_routes,
)

_register_tool_routes(app)


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    start_time = time.perf_counter()
    logger.debug("Health check request received")

    try:
        logger.debug("Health check: retrieving agent instance")
        agent = get_agent()
        logger.debug("Health check: agent instance ready, fetching tool registry")
        tool_count = len(agent.tool_registry.get_all_tools())
    except Exception as exc:
        duration = time.perf_counter() - start_time
        logger.exception(
            "Health check failed after %.2fs: %s",
            duration,
            exc,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "service": "br_kg-agent",
                    "detail": str(exc),
                }
            ),
            500,
        )

    duration = time.perf_counter() - start_time
    logger.debug(
        "Health check succeeded in %.2fs; tool registry count=%d",
        duration,
        tool_count,
    )
    return jsonify(
        {
            "status": "healthy",
            "service": "br_kg-agent",
            "tools_available": tool_count,
            "module_path": inspect.getfile(inspect.currentframe()),
        }
    )


@app.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """Expose Prometheus-formatted agent metrics."""
    if not _AGENT_METRICS_ENABLED:
        return Response(
            "metrics disabled\n",
            status=404,
            mimetype="text/plain; version=0.0.4",
        )
    monitoring = _get_agent_monitoring_for_metrics()
    payload = None
    try:
        if monitoring is not None:
            if hasattr(monitoring, "_metrics"):
                payload = monitoring._metrics.export_prometheus()
            elif hasattr(monitoring, "metrics_collector"):
                payload = monitoring.metrics_collector.export_prometheus()
            else:
                raise AttributeError("Monitoring integration lacks metrics collector")
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to export agent metrics: %s", exc, exc_info=True)
        payload = None
    if payload is None:
        try:
            payload = _metrics.export_prometheus()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to export fallback metrics: %s", exc, exc_info=True)
            return Response(
                "metrics unavailable\n",
                status=503,
                mimetype="text/plain; version=0.0.4",
            )
    if not payload.strip():
        try:
            if monitoring is not None:
                payload = _metrics.export_prometheus()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to export fallback metrics: %s", exc, exc_info=True)
            return Response(
                "metrics unavailable\n",
                status=503,
                mimetype="text/plain; version=0.0.4",
            )
    if not payload.strip():
        payload = "# no metrics available\n"
    return Response(payload, mimetype="text/plain; version=0.0.4")


def _mcp_selftest_autoroute_enabled() -> bool:
    raw = os.getenv("BR_AGENT_MCP_SELFTEST_AUTOROUTE")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _detect_mcp_selftest_mode_from_query(query: str) -> str | None:
    q = (query or "").strip().lower()
    if not q or "mcp" not in q:
        return None
    quick_cues = (
        "status",
        "health",
        "check",
        "diagnostic",
        "self-test",
        "self test",
        "自测",
        "检查",
        "看看",
        "有什么",
    )
    if not any(token in q for token in quick_cues):
        return None
    active_cues = (
        "full",
        "active",
        "trigger",
        "run",
        "experiment",
        "script",
        "container",
        "kg",
        "全面",
        "实验",
    )
    if any(token in q for token in active_cues):
        return "active"
    return "quick"


def _run_mcp_selftest_direct_response(query: str, ctx: dict | None = None):
    if not _mcp_selftest_autoroute_enabled():
        return None
    mode = _detect_mcp_selftest_mode_from_query(query)
    if mode is None:
        return None
    ctx = ctx or {}
    try:
        from brain_researcher.services.shared.mcp_runtime_bridge import call_mcp_tool

        payload = call_mcp_tool(
            "system_self_test",
            mode=mode,
            include_kg=bool(ctx.get("mcp_selftest_include_kg", True)),
            include_container=bool(ctx.get("mcp_selftest_include_container", True)),
            include_script=bool(ctx.get("mcp_selftest_include_script", True)),
            include_inventory=bool(ctx.get("mcp_selftest_include_inventory", True)),
            inventory_limit=int(ctx.get("mcp_selftest_inventory_limit", 12)),
            kg_query=str(ctx.get("mcp_selftest_kg_query") or "brain"),
            strict=bool(ctx.get("mcp_selftest_strict", False)),
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "mode": mode,
            "overall": "fail",
            "summary_text": f"MCP self-test execution error: {type(exc).__name__}: {exc}",
            "error": str(exc),
            "counts": {"pass": 0, "warn": 0, "fail": 1, "skip": 0},
            "probes": [],
            "recommendations": [],
        }
    return (
        jsonify(
            {
                "text": str(payload.get("summary_text") or "MCP self-test completed."),
                "metadata": {
                    "type": "mcp_selftest",
                    "mode": payload.get("mode"),
                    "overall": payload.get("overall"),
                    "ok": payload.get("ok"),
                    "counts": payload.get("counts"),
                },
                "tool_calls": [
                    {
                        "plan": {
                            "tool": "mcp.system_self_test",
                            "params": {"mode": mode},
                            "reasoning": "detected mcp self-test intent",
                        },
                        "result": payload,
                    }
                ],
            }
        ),
        200,
    )


def simple_chat_internal(
    query: str,
    env_override: dict = None,
    *,
    thread_id: str | None = None,
    history: list | None = None,
    ctx: dict | None = None,
):
    """Internal chat handler that can be called from CLI proxy."""
    original_env = {}
    try:
        history = history or []
        ctx = ctx or {}
        extra_env = dict(env_override or {})
        # Pluck orchestration-specific fields from env override so they don't
        # get written into the process environment.
        thread_id = extra_env.pop("thread_id", thread_id)
        history = extra_env.pop("history", history)
        ctx_extra = extra_env.pop("ctx", None) or {}
        ctx.update(ctx_extra)
        if thread_id:
            ctx.setdefault("thread_id", thread_id)
        ctx.setdefault("history_len", len(history))

        if os.getenv("BR_CHAT_ORCHESTRATOR_ENABLED", "0").lower() in {
            "1",
            "true",
            "yes",
        }:
            from brain_researcher.services.agent.advanced_error_recovery import (
                create_error_recovery_system,
            )
            from brain_researcher.services.agent.memory import ConversationMemory
            from brain_researcher.services.agent.tool_executor import ToolExecutor
            from brain_researcher.services.agent.tool_router import (
                ToolRouter,
                load_chat_tools_whitelist,
                load_tool_families,
            )
            from brain_researcher.services.tools.tool_registry import ToolRegistry

            global _CHAT_ORCHESTRATOR, _CHAT_TOOL_EXECUTOR, _CHAT_TOOL_REGISTRY, _CHAT_TOOL_ROUTER
            test_mode = os.getenv("PYTEST_CURRENT_TEST") is not None
            light_mode = test_mode or os.getenv("TOOL_DISCOVERY_MODE") == "light"
            use_capabilities = not test_mode
            if _CHAT_TOOL_REGISTRY is None:
                _CHAT_TOOL_REGISTRY = ToolRegistry(
                    auto_discover=True,
                    use_capabilities=use_capabilities,
                    enable_integrations=False,
                    light_mode=light_mode,
                )
                _filter_registry_by_allowlist(_CHAT_TOOL_REGISTRY)
            if _CHAT_TOOL_ROUTER is None:
                _CHAT_TOOL_ROUTER = ToolRouter(
                    core_registry=_CHAT_TOOL_REGISTRY,
                    families=load_tool_families(),
                    chat_whitelist=load_chat_tools_whitelist(),
                )
            if _CHAT_TOOL_EXECUTOR is None:
                _CHAT_TOOL_EXECUTOR = ToolExecutor(
                    tool_registry=_CHAT_TOOL_REGISTRY,
                    safe_mode=True,
                    bg_loop_name="ChatOrchestrator-AsyncLoop",
                )
            if _CHAT_ORCHESTRATOR is None:
                memory = ConversationMemory()
                error_recovery = create_error_recovery_system(_CHAT_TOOL_REGISTRY)
                enable_knowledge_layer = ctx.get("enable_knowledge_layer")
                if enable_knowledge_layer is None:
                    enable_knowledge_layer = not test_mode
                _CHAT_ORCHESTRATOR = ChatOrchestrator(
                    router=_BILLING_LLM_ROUTER,
                    tool_executor=_CHAT_TOOL_EXECUTOR,
                    tool_registry=_CHAT_TOOL_REGISTRY,
                    tool_router=_CHAT_TOOL_ROUTER,
                    memory=memory,
                    error_recovery=error_recovery,
                    enable_knowledge_layer=enable_knowledge_layer,
                )
            billing_context = _build_api_fee_debit_context(
                {"ctx": ctx},
                call_prefix="chat_orchestrator",
                fallback_run_id=thread_id,
            )
            token = _API_FEE_DEBIT_CONTEXT.set(billing_context)
            try:
                reply = _CHAT_ORCHESTRATOR.handle_chat(query, history=history, ctx=ctx)
            finally:
                _API_FEE_DEBIT_CONTEXT.reset(token)

            # Expose branch/mode in metadata for easier debugging (pipeline vs single-tool vs fallback)
            metadata = reply.metadata or {}
            # Keep prior metadata intact but add a helper field if not present
            if "branch" not in metadata and metadata.get("type"):
                metadata["branch"] = metadata["type"]

            return jsonify(
                {
                    "text": reply.answer,
                    "tool_calls": reply.tool_calls,
                    "metadata": metadata,
                }
            )

        selftest_response = _run_mcp_selftest_direct_response(query, ctx)
        if selftest_response is not None:
            return selftest_response

        # Apply environment overrides if provided
        original_env = {}
        if extra_env:
            for key, value in extra_env.items():
                if key in [
                    "OPENAI_API_KEY",
                    "GEMINI_API_KEY",
                    "DEEPSEEK_API_KEY",
                    "DEFAULT_LLM_MODEL",
                    "BR_GEMINI_CREDENTIAL_PREFERENCE",
                    "USE_GEMINI_CLI",
                ]:
                    original_env[key] = os.environ.get(key)
                    os.environ[key] = value

        # Determine model and routing
        model_name = os.environ.get("DEFAULT_LLM_MODEL", "unknown")
        use_gemini_cli = os.environ.get("USE_GEMINI_CLI", "true").lower() == "true"

        text: str
        provider = "unknown"
        model_used = model_name
        route = "primary"
        usage = {}
        fallback_reason = None

        # Execute chat logic
        if "gemini" in model_name.lower() and use_gemini_cli:
            from brain_researcher.services.agent.credential_resolver import (
                CredentialResolver,
            )

            resolver = CredentialResolver()
            cred = resolver.resolve_for_chat(model_hint=model_name)

            if cred and cred.kind == "local_gemini":
                from brain_researcher.services.agent.utils.gemini_fallback import (
                    chat_with_fallback,
                )

                text, provider, model_used, usage, fallback_reason = chat_with_fallback(
                    prompt=query, initial_model=model_name
                )
                route = "primary" if model_used == model_name else "fallback"
            else:
                from brain_researcher.services.agent.llm import get_llm

                llm = get_llm()
                response = llm.invoke(query)
                text = (
                    response.content if hasattr(response, "content") else str(response)
                )
                provider = "configured"
                route = "default"
        else:
            from brain_researcher.services.agent.llm import get_llm

            llm = get_llm()
            response = llm.invoke(query)
            text = response.content if hasattr(response, "content") else str(response)
            provider = "configured"
            route = "default"

        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        return (
            jsonify(
                {
                    "text": text,
                    "metadata": {
                        "provider": provider,
                        "model": model_used,
                        "route": route,
                        "usage": usage,
                        "fallback_reason": fallback_reason,
                    },
                }
            ),
            200,
        )

    except ApiFeeReservationError as e:
        reason = e.result.reason or str(e)
        logger.warning("Chat blocked by API-fee preflight reservation: %s", reason)
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return create_error_response(
            "INSUFFICIENT_API_CREDITS",
            f"API-fee reservation failed: {reason}",
            402,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        # Restore env on error too
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return jsonify({"error": str(e)}), 500


@app.route("/chat", methods=["POST"])
@rate_limit(max_per_minute=30)
def simple_chat():
    """
    Enhanced chat endpoint with tool context awareness (no execution).
    Provides users information about available tools without running them.
    """
    data = request.get_json(silent=True) or {}
    query = data.get("query") or data.get("message")
    session_id = data.get("session_id")
    tool_context_enabled = data.get("tool_context", True)  # Enable by default
    scenario_id = (
        data.get("scenario_id") or data.get("scenarioId") or data.get("scenarioID")
    )
    scenario_payload = (
        data.get("scenario") if isinstance(data.get("scenario"), dict) else None
    )
    if not scenario_id and scenario_payload:
        scenario_id = scenario_payload.get("id")
    scenario_config = get_chat_scenario(scenario_id)
    scenario_system_prompt = data.get("system_prompt")
    if scenario_config and not scenario_system_prompt:
        scenario_system_prompt = scenario_config.system_prompt
    allowed_tools = None
    if scenario_config and scenario_config.planner_hints:
        allowed_tools = scenario_config.planner_hints.tool_allowlist

    if not query:
        return create_error_response(
            "INVALID_PARAMETER", "Missing query or message parameter", 400
        )

    if os.getenv("BR_CHAT_ORCHESTRATOR_ENABLED", "0").lower() not in {
        "1",
        "true",
        "yes",
    }:
        selftest_response = _run_mcp_selftest_direct_response(
            query, data.get("ctx") or {}
        )
        if selftest_response is not None:
            return selftest_response

    # If orchestrator mode is enabled, allow passing thread/history for stateful flows
    if os.getenv("BR_CHAT_ORCHESTRATOR_ENABLED", "0").lower() in {"1", "true", "yes"}:
        thread_id = data.get("thread_id") or session_id or telemetry.new_run_id()
        history = data.get("history") or []
        ctx_extra = data.get("ctx") or {}
        reply_resp = simple_chat_internal(
            query,
            env_override=None,
            thread_id=thread_id,
            history=history,
            ctx=ctx_extra,
        )
        # simple_chat_internal already returns a Response
        return reply_resp

    try:
        run_id = getattr(g, "client_run_id", None) or telemetry.new_run_id()
        g.run_id = run_id
        with telemetry.span_context(
            "agent.chat",
            {
                "channel": "web",
                "request_type": "chat",
                "session_id": session_id,
                "run_id": run_id,
            },
        ) as chat_span:
            logger.info(
                f"[/chat] Processing query: {query[:100]}... (session: {session_id}, tool_context: {tool_context_enabled})"
            )

            # Get tool context if enabled and query seems tool-related
            tool_context = ""
            if tool_context_enabled:
                tool_context = _get_relevant_tool_context(
                    query, allowed_tools=allowed_tools
                )

            # Build contextualized query if tool context available
            contextualized_query = query
            if tool_context:
                contextualized_query = f"{tool_context}\n\nUser: {query}"
                logger.info(f"[/chat] Added tool context ({len(tool_context)} chars)")
            scenario_intro = ""
            if scenario_config or scenario_system_prompt:
                intro_lines = []
                if scenario_config:
                    intro_lines.append(
                        f"You are operating as the '{scenario_config.title}' scenario inside Brain Researcher."
                    )
                if scenario_system_prompt:
                    intro_lines.append(scenario_system_prompt.strip())
                scenario_intro = "\n".join([line for line in intro_lines if line])
            if scenario_intro:
                contextualized_query = f"{scenario_intro}\n\n{contextualized_query}"

            model_hint = os.environ.get("DEFAULT_LLM_MODEL", "unknown")
            try:
                router_result = _route_chat_with_api_fee_debit(
                    contextualized_query,
                    payload=data,
                    call_prefix="chat",
                    fallback_run_id=run_id,
                    model_hint=model_hint,
                )
                metadata = router_result.metadata
                api_fee_debit = getattr(metadata, "api_fee_debit", None)
                text = router_result.text
                provider = metadata.provider
                model_name = metadata.model
                route = metadata.route
                usage = metadata.usage or {}
                fallback_reason = metadata.fallback_reason
                transport = metadata.transport
                credential_used = metadata.credential
                bill_to = metadata.bill_to
            except ApiFeeReservationError as exc:
                reason = exc.result.reason or str(exc)
                logger.warning("[/chat] API-fee preflight blocked request: %s", reason)
                return create_error_response(
                    "INSUFFICIENT_API_CREDITS",
                    f"API-fee reservation failed: {reason}",
                    402,
                )
            except ValueError as exc:
                logger.warning(f"[/chat] Falling back to canned response: {exc}")
                text = _fallback_response(query)
                provider = "fallback"
                model_name = "quick-response"
                route = "fallback"
                usage = {}
                fallback_reason = str(exc)
                transport = "internal"
                credential_used = None
                bill_to = None
                api_fee_debit = None

            span_record = chat_span.finish(
                status="ok",
                provider=provider,
                model=model_name,
                route=route,
                transport=transport,
                credential=credential_used,
                bill_to=bill_to,
            )
            latency_ms = int(round(span_record["duration_ms"]))
            logger.info(
                "[/chat] Response received: %d chars in %dms "
                "(provider=%s, model=%s, transport=%s, route=%s, fallback=%s)",
                len(text),
                latency_ms,
                provider,
                model_name,
                transport,
                route,
                fallback_reason or "none",
            )

            tool_context_chars = len(tool_context) if tool_context else 0
            try:
                telemetry.record_event(
                    {
                        "run_id": run_id,
                        "channel": "web",
                        "request_type": "chat",
                        "session_id": session_id,
                        "prompt_hash": telemetry.prompt_hash(contextualized_query),
                        "prompt_length": len(contextualized_query or ""),
                        "scenario": (
                            {
                                "id": scenario_config.id,
                                "title": scenario_config.title,
                            }
                            if scenario_config
                            else None
                        ),
                        "llm": {
                            "provider": provider,
                            "model": model_name,
                            "requested_model": model_hint,
                            "route": route,
                            "transport": transport,
                            "credential": credential_used,
                            "bill_to": bill_to,
                            "usage": usage,
                            "fallback_reason": fallback_reason,
                            "latency_ms": latency_ms,
                            "api_fee_debit": api_fee_debit,
                        },
                        "tool_context": {
                            "enabled": bool(tool_context),
                            "chars": tool_context_chars,
                        },
                        "spans": [span_record],
                    },
                    event_type="chat",
                )
            except Exception:
                logger.exception("[/chat] Failed to record telemetry event")

            from datetime import datetime, timezone

            from brain_researcher.core.contracts.ids import IdsV1
            from brain_researcher.core.contracts.run_card import RunCardV1

            execution = {
                "provider": provider,
                "model": model_name,
                "latency_ms": latency_ms,
                "route": route,
                "transport": transport,
                "credential": credential_used,
                "bill_to": bill_to,
                "usage": usage,
                "fallback_reason": fallback_reason,
                "tool_context_enabled": bool(tool_context),
                "tool_context_length": tool_context_chars,
                "requested_model": model_hint,
                "api_fee_debit": api_fee_debit,
            }
            ids = IdsV1(
                analysis_id=run_id,
                run_id=run_id,
                job_id=run_id,
                request_id=getattr(g, "request_id", None),
                trace_id=getattr(g, "trace_id", None),
                session_id=session_id,
            )
            run_card = RunCardV1(
                id=run_id,
                timestamp=datetime.now(tz=timezone.utc),
                ids=ids,
                execution=execution,
            ).model_dump(mode="json", exclude_none=True)
            # Back-compat: some callers still look for runCard.run_id.
            run_card.setdefault("run_id", run_id)

            return jsonify(
                {
                    "message": {"role": "assistant", "content": text},
                    "runCard": run_card,
                    "session_id": session_id,
                }
            )

    except Exception as e:
        logger.exception(f"[{g.trace_id}][/chat] Error: {e}")
        return create_error_response(
            "INTERNAL_ERROR", f"Failed to process chat request: {str(e)}", 500
        )


@app.route("/act", methods=["POST"])
@rate_limit(max_per_minute=10)
def agent_act():
    """
    Tool-enabled endpoint for agent actions.
    Executes LLM with tool selection and execution.
    """
    data = request.get_json(silent=True) or {}
    from brain_researcher.services.agent.agent_core import agent_act_core

    run_id = getattr(g, "client_run_id", None) or telemetry.new_run_id()
    g.run_id = run_id
    billing_context = _build_api_fee_debit_context(
        data,
        call_prefix="act",
        fallback_run_id=run_id,
    )
    token = _API_FEE_DEBIT_CONTEXT.set(billing_context)
    try:
        result = agent_act_core(
            data,
            trace_id=getattr(g, "trace_id", None),
            run_id=run_id,
            llm_router=_BILLING_LLM_ROUTER,
        )
    except ApiFeeReservationError as exc:
        reason = exc.result.reason or str(exc)
        logger.warning("[/act] API-fee preflight blocked request: %s", reason)
        return create_error_response(
            "INSUFFICIENT_API_CREDITS",
            f"API-fee reservation failed: {reason}",
            402,
        )
    finally:
        _API_FEE_DEBIT_CONTEXT.reset(token)
    if isinstance(result, dict) and result.get("error"):
        code = result.get("code") or "INTERNAL_ERROR"
        if code == "INSUFFICIENT_API_CREDITS":
            status = 402
        elif code in {"INVALID_PARAMETER", "VALIDATION_ERROR"}:
            status = 400
        else:
            status = 500
        return create_error_response(code, result.get("error") or "", status)

    return jsonify(result)
    query = data.get("query")
    session_id = data.get("session_id")
    tool_mode = data.get("tool_mode", "auto")  # auto, off, force
    tools_whitelist = data.get("tools_whitelist", [])
    if "budget_ms" in data:
        budget_ms = data.get("budget_ms")
    else:
        from brain_researcher.services.shared.retry_timeout import load_timeout_config

        budget_ms = load_timeout_config().tool_execution_budget_ms

    if not query:
        return create_error_response(
            "INVALID_PARAMETER", "Missing query parameter", 400
        )

    from brain_researcher.services.agent.tool_executor import BudgetedToolExecutor

    tool_executor = BudgetedToolExecutor(
        global_budget_ms=budget_ms,
        use_subprocess=False,
    )

    demo_mode = _config.get("DEMO_MODE", False)

    run_id = getattr(g, "client_run_id", None) or telemetry.new_run_id()
    g.run_id = run_id
    spans: list[dict[str, Any]] = []
    plan_metadata = None
    selected_tool_name: str | None = None
    tool_invocation_count = 0
    tool_result_status = "skipped"
    telemetry_tool_calls: list[dict[str, Any]] = []
    tool_calls = []
    artifacts = []
    error_info: Exception | None = None
    response = None

    act_span = telemetry.start_span(
        "agent.act",
        {
            "channel": "web",
            "request_type": "act",
            "session_id": session_id,
            "tool_mode": tool_mode,
        },
    )

    try:
        import json as json_module
        import time

        start_time = time.time()
        logger.info(
            f"[/act] Processing query with tools: {query[:100]}... (mode: {tool_mode})"
        )

        agent = get_agent()

        model_hint = os.environ.get("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
        provider = infer_provider(model_hint)

        from brain_researcher.services.tools.args_resolver import ArgsResolver
        from brain_researcher.services.tools.spec import (
            ToolSpecRegistry,
            compress_schema,
            spec_from_tool,
        )

        spec_registry = ToolSpecRegistry()
        resolver = ArgsResolver(context={"working_dir": os.getcwd()})

        all_tools = agent.tool_registry.get_all_tools()
        query_lower = query.lower()

        tool_scores = []
        for tool in all_tools:
            name = tool.get_tool_name()
            desc = (
                tool.get_tool_description()
                if hasattr(tool, "get_tool_description")
                else ""
            )

            score = 0
            if any(word in name.lower() for word in query_lower.split()):
                score += 10
            if any(word in desc.lower() for word in query_lower.split()):
                score += 5
            category = getattr(tool, "CATEGORY", "")
            if category and any(
                word in category.lower() for word in query_lower.split()
            ):
                score += 7

            if score > 0 or len(tool_scores) < 8:
                tool_scores.append((score, tool))

        tool_scores.sort(key=lambda x: x[0], reverse=True)
        selected_tools = [tool for _, tool in tool_scores[:8]]

        tool_specs = []
        for tool in selected_tools:
            spec = spec_from_tool(tool)
            if spec:
                spec_registry.register(spec)
                tool_specs.append(spec)

        tools_with_schemas = []
        for spec in tool_specs:
            compressed = compress_schema(spec.json_schema, max_properties=8)
            tool_info = {
                "name": spec.name,
                "description": spec.description,
                "parameters": compressed.get("properties", {}),
                "required": spec.required[:5],
                "examples": [
                    {"query": ex.user_query, "params": ex.params}
                    for ex in spec.examples[:2]
                ],
            }
            tools_with_schemas.append(tool_info)

        tools_json = json_module.dumps(tools_with_schemas, indent=2)
        tool_prompt = f"""You are a neuroimaging assistant with access to specialized tools.

User Query: {query}

Available Tools (with full parameter schemas):
{tools_json}

Instructions:
1. Select the most appropriate tool for the query
2. Provide ALL required parameters based on the schema
3. Use parameter names exactly as shown in the schema
4. Reference examples if provided

Respond with valid JSON:
{{
    "tool": "tool_name",
    "params": {{
        "param1": "value1",
        "param2": "value2"
    }},
    "reasoning": "why this tool and these parameters"
}}

If no tool is needed: {{"tool": "none", "params": {{}}, "reasoning": "explanation"}}"""

        plan_span = telemetry.start_span(
            "agent.plan",
            {
                "channel": "web",
                "run_id": run_id,
                "session_id": session_id,
            },
        )
        try:
            plan_result = _LLM_ROUTER.route_chat(
                tool_prompt,
                model_hint=model_hint,
            )
        except Exception as plan_exc:
            spans.append(
                plan_span.finish(
                    status="error",
                    error=str(plan_exc),
                )
            )
            raise

        plan_metadata = plan_result.metadata
        spans.append(
            plan_span.finish(
                status="ok",
                provider=plan_metadata.provider,
                model=plan_metadata.model,
                route=plan_metadata.route,
                transport=plan_metadata.transport,
                credential=plan_metadata.credential,
                bill_to=plan_metadata.bill_to,
                fallback_reason=plan_metadata.fallback_reason,
            )
        )

        selection_text = plan_result.text
        usage = plan_metadata.usage or {}
        provider = plan_metadata.provider or provider
        model_name = plan_metadata.model or model_hint
        route = plan_metadata.route
        transport = plan_metadata.transport
        credential_used = plan_metadata.credential
        bill_to = plan_metadata.bill_to
        fallback_reason = plan_metadata.fallback_reason

        try:
            import re

            json_match = re.search(r"\{[\s\S]*\}", selection_text)
            if json_match:
                parsed = json_module.loads(json_match.group(0))
            else:
                parsed = {
                    "tool": "error",
                    "params": {},
                    "reasoning": "Failed to parse JSON",
                }
        except Exception as parse_exc:
            logger.warning(f"Failed to parse LLM response: {parse_exc}")
            parsed = {
                "tool": "error",
                "params": {"message": str(parse_exc)},
                "reasoning": "Parse error",
            }

        if tool_mode != "off" and parsed.get("tool") and parsed["tool"] != "error":
            tool_name = parsed["tool"]
            tool_params = parsed.get("params", {})
            selected_tool_name = tool_name

            if tools_whitelist and tool_name not in tools_whitelist:
                logger.warning(f"Tool {tool_name} not in whitelist: {tools_whitelist}")
                tool_calls.append(
                    {
                        "name": tool_name,
                        "arguments": tool_params,
                        "status": "blocked",
                        "error": "Tool not in whitelist",
                    }
                )
                telemetry_tool_calls.append(
                    {
                        "name": tool_name,
                        "status": "blocked",
                        "match_type": "whitelist",
                    }
                )
                tool_result_status = "blocked"
            else:
                from brain_researcher.services.agent.tool_mapper import get_tool_mapper

                mapper = get_tool_mapper(agent.tool_registry)

                mapped_name, match_type = mapper.map_tool_name(
                    tool_name,
                    whitelist=tools_whitelist if tools_whitelist else None,
                    trace_id=g.trace_id,
                )

                if mapped_name:
                    tool = agent.tool_registry.get_tool(mapped_name)
                    if match_type != "exact":
                        logger.info(
                            f"[{g.trace_id}] Tool remapped via {match_type}: {tool_name} -> {mapped_name}"
                        )
                else:
                    tool = None

                if tool:
                    tool_span = telemetry.start_span(
                        f"agent.tool.{mapped_name}",
                        {
                            "tool_name": mapped_name,
                            "run_id": run_id,
                            "session_id": session_id,
                        },
                    )
                    try:
                        tool_spec = spec_registry.get(mapped_name)
                        if tool_spec:
                            resolved_params = resolver.resolve_full_pipeline(
                                tool_params,
                                tool_spec,
                                schema_class=getattr(
                                    tool, "get_args_schema", lambda: None
                                )(),
                            )
                            adapted_args = (
                                resolved_params.get("params", resolved_params)
                                if isinstance(resolved_params, dict)
                                else resolved_params
                            )
                            logger.info(
                                f"[{g.trace_id}] Parameters resolved via ArgsResolver"
                            )
                        else:
                            from brain_researcher.services.tools.arg_adapter import (
                                ToolArgumentAdapter,
                            )

                            adapted_args = ToolArgumentAdapter.adapt(
                                mapped_name,
                                tool_params,
                                demo=demo_mode,
                                trace_id=g.trace_id,
                            )
                            logger.info(
                                f"[{g.trace_id}] Parameters adapted via legacy adapter"
                            )

                        logger.info(
                            f"[{g.trace_id}] Executing tool: {mapped_name} with processed args"
                        )

                        tool_result = tool_executor.execute_with_timeout(
                            tool=tool,
                            args=adapted_args,
                            timeout_ms=None,
                            trace_id=g.trace_id,
                        )
                        tool_invocation_count += 1
                    except ValidationError as val_err:
                        logger.error(f"[{g.trace_id}] Validation error: {val_err}")
                        from brain_researcher.services.tools.tool_base import (
                            ToolResult,
                        )

                        tool_result = ToolResult(
                            status="error", error=f"VALIDATION_ERROR: {str(val_err)}"
                        )
                    tool_summary = tool_result.model_dump()
                    tool_status = (
                        "success" if tool_result.status == "success" else "error"
                    )
                    tool_result_status = tool_status
                    spans.append(
                        tool_span.finish(
                            status=tool_status,
                            exit_code=tool_summary.get("exit_code"),
                        )
                    )
                    telemetry_tool_calls.append(
                        {
                            "name": mapped_name,
                            "status": tool_status,
                            "match_type": match_type,
                        }
                    )
                    tool_calls.append(
                        {
                            "name": tool_name,
                            "arguments": tool_params,
                            "status": (
                                "ok" if tool_result.status == "success" else "error"
                            ),
                            "result": (
                                tool_summary.get("data")
                                if tool_result.status == "success"
                                else None
                            ),
                            "error": (
                                tool_summary.get("error")
                                if tool_result.status == "error"
                                else None
                            ),
                        }
                    )
                    if tool_result.status == "success" and tool_result.data:
                        artifacts.append(
                            {
                                "id": f"tool_{tool_name}_{int(time.time())}",
                                "type": "tool_result",
                                "name": f"{tool_name} output",
                                "data": tool_result.data,
                            }
                        )
                else:
                    tool_calls.append(
                        {
                            "name": tool_name,
                            "arguments": tool_params,
                            "status": "error",
                            "error": f"Tool {tool_name} not found in registry",
                        }
                    )
                    telemetry_tool_calls.append(
                        {
                            "name": tool_name,
                            "status": "not_found",
                            "match_type": match_type,
                        }
                    )
                    tool_result_status = "error"
        else:
            telemetry_tool_calls.append(
                {
                    "name": parsed.get("tool", "none"),
                    "status": "skipped",
                    "match_type": None,
                }
            )

        latency_ms = int((time.time() - start_time) * 1000)

        if tool_calls and tool_calls[0].get("status") == "ok":
            response_text = f"{parsed.get('reasoning', 'Analysis completed')}. Tool '{tool_calls[0]['name']}' executed successfully."
        else:
            response_text = parsed.get("reasoning", selection_text)

        from datetime import datetime, timezone

        from brain_researcher.core.contracts.ids import IdsV1
        from brain_researcher.core.contracts.run_card import RunCardV1

        execution = {
            "provider": provider,
            "model": model_name,
            "latency_ms": latency_ms,
            "tool_mode": tool_mode,
            "route": route,
            "transport": transport,
            "credential": credential_used,
            "bill_to": bill_to,
            "usage": usage,
            "fallback_reason": fallback_reason,
            "selected_tool": selected_tool_name,
        }
        ids = IdsV1(
            analysis_id=run_id,
            run_id=run_id,
            job_id=run_id,
            request_id=getattr(g, "request_id", None),
            trace_id=getattr(g, "trace_id", None),
            session_id=session_id,
        )
        run_card = RunCardV1(
            id=run_id,
            timestamp=datetime.now(tz=timezone.utc),
            ids=ids,
            execution=execution,
            provenance={"tool_calls": tool_calls} if tool_calls else None,
        ).model_dump(mode="json", exclude_none=True)
        run_card.setdefault("run_id", run_id)

        response = jsonify(
            {
                "message": {"role": "assistant", "content": response_text},
                "tool_calls": tool_calls,
                "artifacts": artifacts,
                "runCard": run_card,
                "session_id": session_id,
            }
        )

    except Exception as exc:
        error_info = exc
        logger.exception(f"[{g.trace_id}][/act] Error: {exc}")
        response = create_error_response(
            "INTERNAL_ERROR", f"Failed to execute action: {str(exc)}", 500
        )
    finally:
        act_attrs = {
            "provider": plan_metadata.provider if plan_metadata else provider,
            "model": plan_metadata.model if plan_metadata else model_hint,
            "route": plan_metadata.route if plan_metadata else "direct",
            "transport": plan_metadata.transport if plan_metadata else "sdk",
            "tool_invocation_count": tool_invocation_count,
            "tool_status": tool_result_status,
            "tool_route": tool_mode,
        }
        if selected_tool_name:
            act_attrs["selected_tool"] = selected_tool_name
        if error_info:
            act_attrs["error"] = type(error_info).__name__

        act_span_record = act_span.finish(
            status="error" if error_info else "ok",
            **act_attrs,
        )
        spans.insert(0, act_span_record)

        event_payload = {
            "run_id": run_id,
            "channel": "web",
            "request_type": "act",
            "session_id": session_id,
            "latency_ms": int(round(act_span_record["duration_ms"])),
            "prompt_hash": telemetry.prompt_hash(query),
            "prompt_length": len(query or ""),
            "plan_prompt_hash": (
                telemetry.prompt_hash(tool_prompt)
                if "tool_prompt" in locals()
                else None
            ),
            "llm": {
                "provider": plan_metadata.provider if plan_metadata else provider,
                "model": plan_metadata.model if plan_metadata else model_hint,
                "requested_model": model_hint,
                "route": plan_metadata.route if plan_metadata else "direct",
                "transport": plan_metadata.transport if plan_metadata else "sdk",
                "credential": plan_metadata.credential if plan_metadata else None,
                "bill_to": plan_metadata.bill_to if plan_metadata else None,
                "usage": usage if plan_metadata else {},
                "fallback_reason": (
                    plan_metadata.fallback_reason if plan_metadata else None
                ),
            },
            "tooling": {
                "selected_tool": selected_tool_name,
                "tool_route": tool_mode,
                "invocations": tool_invocation_count,
                "result_status": tool_result_status,
                "calls": telemetry_tool_calls,
                "artifacts_count": len(artifacts),
            },
            "spans": spans,
            "error": (
                {
                    "message": str(error_info),
                    "type": type(error_info).__name__,
                }
                if error_info
                else None
            ),
        }
        try:
            telemetry.record_event(event_payload, event_type="act")
        except Exception:
            logger.exception("[/act] Failed to record telemetry event")

        tool_executor.shutdown()

    return response


@app.route("/act_llm", methods=["POST"])
@rate_limit(max_per_minute=10)
def agent_act_llm():
    """
    LLM-native tool-enabled endpoint using NeuroAgentLLM.
    Uses LangChain tool binding for model-native tool calling.
    """
    data = request.get_json(silent=True) or {}
    query = data.get("query")
    session_id = data.get("session_id")
    run_id = getattr(g, "client_run_id", None) or telemetry.new_run_id()
    g.run_id = run_id
    if not query:
        return create_error_response(
            "INVALID_PARAMETER", "Missing query parameter", 400
        )
    # Lightweight classification for output mode and complexity
    output_mode = classify_output_mode(query).value
    complexity = assess_complexity(query).value
    force_tools = bool(data.get("force_tools"))
    coding_mode = bool(data.get("codingMode") or data.get("coding_mode"))
    tool_mode = data.get("tool_mode")
    if not tool_mode:
        tool_mode = (
            "required"
            if force_tools
            else os.environ.get(
                "BR_TOOL_CHOICE_MODE",
                "required",
            )
        )
    # Normalize to known values
    if tool_mode not in {"auto", "required", "none"}:
        tool_mode = "required"

    try:
        import time

        start_time = time.time()
        logger.info(
            f"[/act_llm] Processing query with native tool-calling: {query[:100]}... (force_tools={force_tools})"
        )

        agent_llm = _get_cached_act_llm_agent(
            tool_mode=tool_mode,
            coding_bias=coding_mode,
        )

        # Run the graph with complexity gating
        run_context = {}
        if session_id:
            run_context["thread_id"] = session_id
        job_id = data.get("job_id")
        if job_id:
            run_context["job_id"] = job_id
        resume_checkpoint_id = (
            data.get("resume_checkpoint_id")
            or data.get("resumeCheckpointId")
            or data.get("checkpoint_id")
            or data.get("checkpointId")
        )
        if resume_checkpoint_id:
            run_context["resume_checkpoint_id"] = str(resume_checkpoint_id)
        final_state = agent_llm.run(
            query,
            complexity=complexity,
            context=run_context or None,
        )

        # Extract assistant text
        assistant_text = agent_llm.get_last_ai_message(final_state) or ""

        # Collect tool calls and results from messages
        tool_calls = []
        artifacts = []
        for msg in final_state.get("messages", []):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                # Record the decisions (arguments) the model made
                for tc in msg.tool_calls or []:
                    try:
                        if isinstance(tc, dict):
                            name = tc.get("name", "unknown")
                            args = tc.get("args", {})
                        else:
                            name = getattr(tc, "name", "unknown")
                            args = getattr(tc, "args", {})
                        tool_calls.append(
                            {
                                "name": name or "unknown",
                                "arguments": args or {},
                                "status": "called",
                            }
                        )
                    except Exception as e:
                        tool_calls.append(
                            {
                                "name": "unknown",
                                "arguments": {},
                                "status": "error",
                                "error": f"parse_error: {e}",
                            }
                        )
            elif isinstance(msg, ToolMessage):
                # Tool execution output from tool node
                name = getattr(msg, "name", "tool")
                content = getattr(msg, "content", "")
                # Attempt to parse JSON content
                parsed = None
                if isinstance(content, str):
                    try:
                        import json as _json

                        parsed = _json.loads(content)
                    except Exception:
                        parsed = {"text": content}
                elif isinstance(content, dict):
                    parsed = content
                else:
                    parsed = {"text": str(content)}

                tool_calls.append({"name": name, "result": parsed, "status": "ok"})

                # Promote substantial results to artifacts
                if isinstance(parsed, dict) and parsed.get("data"):
                    artifacts.append(
                        {
                            "id": f"tool_{name}_{int(time.time())}",
                            "type": "tool_result",
                            "name": f"{name} output",
                            "data": parsed.get("data"),
                        }
                    )

        provider, model_name = _resolve_act_llm_execution_metadata(
            agent_llm, coding_mode=coding_mode
        )

        latency_ms = int((time.time() - start_time) * 1000)

        from datetime import datetime, timezone

        from brain_researcher.core.contracts.ids import IdsV1
        from brain_researcher.core.contracts.run_card import RunCardV1

        execution = {
            "provider": provider,
            "model": model_name,
            "latency_ms": latency_ms,
            "tool_mode": tool_mode,
            "route": "act_llm",
            "transport": "langchain",
            "output_mode": output_mode,
            "complexity": complexity,
            "force_tools": force_tools,
            "coding_mode": coding_mode,
        }
        ids = IdsV1(
            analysis_id=run_id,
            run_id=run_id,
            job_id=job_id or run_id,
            request_id=getattr(g, "request_id", None),
            trace_id=getattr(g, "trace_id", None),
            session_id=session_id,
        )
        run_card = RunCardV1(
            id=job_id or run_id,
            timestamp=datetime.now(tz=timezone.utc),
            ids=ids,
            execution=execution,
            provenance={"tool_calls": tool_calls} if tool_calls else None,
        ).model_dump(mode="json", exclude_none=True)
        run_card.setdefault("run_id", run_id)

        # Build response
        return jsonify(
            {
                "message": {"role": "assistant", "content": assistant_text or "Done."},
                "tool_calls": tool_calls,
                "artifacts": artifacts,
                "output_mode": output_mode,
                "complexity": complexity,
                "codegen_kind": output_mode,
                "runCard": run_card,
                "session_id": session_id,
            }
        )

    except Exception as e:
        logger.exception(f"[{g.trace_id}][/act_llm] Error: {e}")
        return create_error_response(
            "INTERNAL_ERROR", f"Failed to execute native action: {str(e)}", 500
        )


def _extract_policy_issues_from_tool_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return out

    root_issues = payload.get("policy_issues")
    if isinstance(root_issues, list):
        out.extend([item for item in root_issues if isinstance(item, dict)])

    data = payload.get("data")
    if isinstance(data, dict):
        data_issues = data.get("policy_issues")
        if isinstance(data_issues, list):
            out.extend([item for item in data_issues if isinstance(item, dict)])

    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata_issues = metadata.get("policy_issues")
        if isinstance(metadata_issues, list):
            out.extend([item for item in metadata_issues if isinstance(item, dict)])

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in out:
        key = json.dumps(issue, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _execute_tool_request(
    *,
    tool_id: str,
    params: dict[str, Any],
    work_dir: str | None,
    output_dir: str | None,
    preview: bool,
    origin: str | None = None,
):
    if not isinstance(params, dict):
        return create_error_response(
            "INVALID_PARAMETER", "params must be an object", 400
        )
    if work_dir is not None and not isinstance(work_dir, str):
        return create_error_response(
            "INVALID_PARAMETER", "work_dir must be a string", 400
        )
    if output_dir is not None and not isinstance(output_dir, str):
        return create_error_response(
            "INVALID_PARAMETER", "output_dir must be a string", 400
        )

    if not _is_tool_allowed_by_runtime_policy(tool_id):
        requested = [tool_id]
        return _allowlist_violation_response(
            "Requested tool is not permitted by the environment allowlist",
            disallowed=requested,
            requested=requested,
            denied_tool_id=tool_id,
            denial_stage="tool_execute",
            denial_reason_code="requested_tool_not_permitted",
        )

    # Surface unknown tools early for clearer client semantics.
    _, tool_instance = _resolve_runtime_tool_instance(tool_id)
    if tool_instance is None:
        return create_error_response("NOT_FOUND", f"Tool '{tool_id}' not found", 404)

    try:
        start_time = time.time()
        from brain_researcher.services.tools.executor import (
            execute_tool as unified_execute_tool,
        )

        logger.info(
            "[/tools/execute] Executing %s (preview=%s, origin=%s)",
            tool_id,
            preview,
            origin or "direct",
        )
        result_obj = unified_execute_tool(
            tool_id,
            params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
        )
        result_payload = result_obj.model_dump()
        policy_issues = _extract_policy_issues_from_tool_payload(result_payload)
        latency_ms = int((time.time() - start_time) * 1000)

        response_payload: dict[str, Any] = {
            "status": result_payload.get("status", "error"),
            "tool_id": tool_id,
            "params": params,
            "preview": bool(preview),
            "work_dir": work_dir,
            "output_dir": output_dir,
            "origin": origin or "direct",
            "result": result_payload,
            "latency_ms": latency_ms,
        }
        if policy_issues:
            response_payload["policy_issues"] = policy_issues
        return jsonify(response_payload)
    except Exception as e:
        logger.exception(
            f"[{g.trace_id}][/tools/execute] Error executing {tool_id}: {e}"
        )
        return create_error_response(
            "TOOL_ERROR", f"Tool execution failed: {str(e)}", 500
        )


@app.route("/query", methods=["POST"])
@rate_limit(max_per_minute=30)
def process_query():
    """Process a natural language query with clustering and deduplication."""
    # Import here to avoid circular deps
    from brain_researcher.core.analysis.paper_utils import (
        cluster_papers,
        deduplicate_papers,
        rank_papers_in_cluster,
    )
    from brain_researcher.core.analysis.rag_retrieval import close_shared_session

    try:
        data = request.get_json()
        if not data or "query" not in data:
            return jsonify({"error": "Missing query parameter"}), 400

        query = data["query"]
        user_id = data.get("user_id", "anonymous")
        coordinates = data.get("coordinates")
        enable_clustering = data.get("enable_clustering", True)
        retrieval_mode = data.get(
            "retrieval_mode", "hybrid" if coordinates else "semantic"
        )
        top_k = min(data.get("top_k", 20), 100)  # Limit to 100

        print(f"Processing query: {query} for user: {user_id}")

        # Run async retrieval
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Determine which retrieval method to use
            rag_sys = get_rag_system()
            if retrieval_mode == "hybrid" and coordinates:
                results = loop.run_until_complete(
                    rag_sys.retrieve_hybrid_async(query, coordinates, top_k=top_k)
                )
            else:
                results = loop.run_until_complete(
                    rag_sys.retrieve_semantic_async(query, top_k=top_k)
                )
        finally:
            loop.run_until_complete(close_shared_session())
            loop.close()

        # Deduplicate results
        unique_results = deduplicate_papers(results)

        # Cluster if enabled and we have enough results
        if enable_clustering and len(unique_results) >= 3:
            clusters = cluster_papers(unique_results)

            # Rank papers within each cluster
            for cluster in clusters:
                cluster["papers"] = rank_papers_in_cluster(cluster["papers"])
        else:
            # Single cluster with all results
            clusters = [
                {
                    "cluster_id": 0,
                    "summary": f"All results ({len(unique_results)} papers)",
                    "papers": rank_papers_in_cluster(unique_results),
                    "size": len(unique_results),
                }
            ]

        # Save to history
        query_params = {
            "retrieval_mode": retrieval_mode,
            "coordinates": coordinates,
            "top_k": top_k,
            "enable_clustering": enable_clustering,
        }

        query_id = get_history().add_query(
            user_id=user_id,
            query_text=query,
            query_params=query_params,
            results=unique_results,
            metadata={"clustered": enable_clustering},
        )

        response = {
            "query_id": query_id,
            "query": query,
            "clusters": clusters,
            "total_results": len(unique_results),
            "deduplicated_from": len(results),
            "status": "success",
        }

        return jsonify(response)

    except Exception as e:
        print(f"Error processing query: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/feedback", methods=["POST"])
@rate_limit(max_per_minute=60)
def submit_feedback():
    """Submit feedback for a query."""
    try:
        data = request.get_json()

        # Validate required fields
        required = ["user_id", "query_id", "rating"]
        for field in required:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        user_id = data["user_id"]
        query_id = data["query_id"]
        rating = data["rating"]
        comment = data.get("comment")

        # Validate rating
        if not isinstance(rating, int) or not 1 <= rating <= 5:
            return jsonify({"error": "Rating must be an integer between 1 and 5"}), 400

        # Add feedback
        success = get_history().add_feedback(user_id, query_id, rating, comment)

        if success:
            return jsonify(
                {"status": "success", "message": "Feedback recorded successfully"}
            )
        else:
            return (
                jsonify({"error": "Failed to record feedback. Query not found."}),
                404,
            )

    except Exception as e:
        print(f"Error submitting feedback: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/history/<user_id>", methods=["GET"])
@rate_limit(max_per_minute=60)
def get_user_history(user_id):
    """Get query history for a user."""
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        # Validate limits
        limit = min(limit, 100)  # Max 100 per request

        history = get_history().get_user_history(user_id, limit=limit, offset=offset)

        return jsonify(
            {
                "user_id": user_id,
                "history": history,
                "count": len(history),
                "limit": limit,
                "offset": offset,
            }
        )

    except Exception as e:
        print(f"Error getting history: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/statistics/<user_id>", methods=["GET"])
@rate_limit(max_per_minute=60)
def get_user_statistics(user_id):
    """Get statistics for a user."""
    try:
        stats = get_history().get_user_statistics(user_id)
        stats["user_id"] = user_id

        return jsonify(stats)

    except Exception as e:
        print(f"Error getting statistics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/statistics", methods=["GET"])
@rate_limit(max_per_minute=10)
def get_global_statistics():
    """Get global statistics across all users."""
    try:
        stats = get_history().get_global_statistics()

        return jsonify(stats)

    except Exception as e:
        print(f"Error getting global statistics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/demo", methods=["GET"])
def run_demo():
    """Run a demonstration of the agent capabilities."""
    # Import here to avoid circular deps
    from brain_researcher.core.analysis.paper_utils import (
        cluster_papers,
        deduplicate_papers,
    )
    from brain_researcher.core.analysis.rag_retrieval import close_shared_session

    try:
        # Create a demo query
        demo_query = "memory consolidation in hippocampus"
        demo_coordinates = [30, -25, -20]  # Example hippocampus coordinates

        # Process the query
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            results = loop.run_until_complete(
                get_rag_system().retrieve_hybrid_async(
                    demo_query, demo_coordinates, top_k=10
                )
            )
        finally:
            loop.run_until_complete(close_shared_session())
            loop.close()

        # Deduplicate and cluster
        unique_results = deduplicate_papers(results)
        clusters = cluster_papers(unique_results) if len(unique_results) >= 3 else []

        demo_results = {
            "status": "success",
            "message": "Demo completed successfully",
            "demo_query": demo_query,
            "demo_coordinates": demo_coordinates,
            "results_count": len(results),
            "unique_results_count": len(unique_results),
            "clusters_count": len(clusters),
            "agent_tools": len(get_agent().tool_registry.get_all_tools()),
        }

        return jsonify(demo_results)

    except Exception as e:
        print(f"Error running demo: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/clear_history/<user_id>", methods=["DELETE"])
@rate_limit(max_per_minute=5)
def clear_user_history(user_id):
    """Clear history for a user (with confirmation)."""
    try:
        # Require confirmation token
        data = request.get_json() or {}
        if data.get("confirm") != "DELETE_ALL_HISTORY":
            return (
                jsonify(
                    {
                        "error": 'Confirmation required. Send {"confirm": "DELETE_ALL_HISTORY"}'
                    }
                ),
                400,
            )

        success = get_history().clear_user_history(user_id)

        if success:
            return jsonify(
                {"status": "success", "message": f"History cleared for user {user_id}"}
            )
        else:
            return jsonify({"error": "Failed to clear history"}), 500

    except Exception as e:
        print(f"Error clearing history: {e}")
        return jsonify({"error": str(e)}), 500

    # App run moved to end of file
    pass


@app.route("/metrics/knowledge", methods=["GET"])
def get_knowledge_metrics():
    """Return knowledge cache metrics (L1/shared) for debugging/monitoring."""
    # Prefer existing orchestrator if the request context set it
    orch = getattr(g, "orchestrator", None)

    # Fallback: build a lightweight orchestrator for metrics only
    if orch is None:
        try:
            orch = get_agent(
                router=_LLM_ROUTER,
                tool_registry=_CHAT_TOOL_REGISTRY,
                tool_router=_CHAT_TOOL_ROUTER,
                tool_executor=_CHAT_TOOL_EXECUTOR,
                enable_knowledge_layer=True,
            )
        except Exception:  # pragma: no cover - defensive
            orch = None

    agg = getattr(orch, "_knowledge_aggregator", None) if orch else None
    if agg is not None:
        try:
            metrics = agg.get_metrics()
            return jsonify({"status": "ok", "cache_metrics": metrics})
        except Exception as exc:  # pragma: no cover - defensive
            return jsonify({"error": str(exc)}), 500

    # Fallback: expose whatever the monitoring collector has
    monitoring = _get_agent_monitoring_for_metrics()
    if monitoring and hasattr(monitoring, "metrics_collector"):
        mc = monitoring.metrics_collector
        hits = mc.metrics.get("cache_hits_total")
        misses = mc.metrics.get("cache_misses_total")
        return jsonify(
            {
                "status": "ok",
                "cache_metrics": {
                    "cache_hits_total": hits.get_latest() if hits else 0,
                    "cache_misses_total": misses.get_latest() if misses else 0,
                },
            }
        )

    return jsonify({"status": "ok", "cache_metrics": {}})


# ---------------------------------------------------------------------------
# Orchestrator compatibility: minimal job SSE stream
# ---------------------------------------------------------------------------


def pipeline_execute():
    """Execute a pipeline (stub) and return an orchestrator-style response.

    The Web UI pipeline builder posts to:
      POST /pipeline/execute

    In the full stack this is handled by the orchestrator service. For
    single-process development (UI + agent only), provide a lightweight
    implementation that returns a job_id and a set of steps so the UI can
    immediately open the SSE stream at:
      GET /jobs/{job_id}/stream  (proxied via /api/jobs/{job_id}/events)

    This endpoint does not run real tooling; it is intended to satisfy the UI
    contract and E2E tests that verify streaming and duration rendering.
    """

    payload = request.get_json(silent=True) or {}
    pipeline_id = payload.get("pipeline_id") or payload.get("id") or "pipeline_stub"
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list):
        nodes = []

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    steps = []
    resource_snapshot: dict[str, Any] = {}
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id") or f"node_{idx + 1}"
        tool = node.get("tool") or node.get("label") or node_id
        name = node.get("label") or tool or node_id
        status = "running" if idx == 0 else "pending"

        estimated_duration_ms = 1500 + (idx * 250)
        steps.append(
            {
                "node_id": node_id,
                "order": idx,
                "name": name,
                "tool": tool,
                "status": status,
                "estimated_duration_ms": estimated_duration_ms,
                "summary": f"{tool} queued",
                "metadata": node.get("metadata") or {},
            }
        )

        resource_snapshot[node_id] = {
            "label": name,
            "status": status,
            "progress": 45 if status == "running" else 0,
            "node_type": node.get("type") or node.get("category") or None,
            "resources": {},
        }

    if not steps:
        # Minimal deterministic fallback so the UI always has at least one step.
        steps = [
            {
                "node_id": "node_1",
                "order": 0,
                "name": "Stub Step",
                "tool": "stub_tool",
                "status": "running",
                "estimated_duration_ms": 1500,
                "summary": "stub_tool queued",
                "metadata": {},
            }
        ]
        resource_snapshot = {
            "node_1": {
                "label": "Stub Step",
                "status": "running",
                "progress": 45,
                "node_type": None,
                "resources": {},
            }
        }

    total_ms = sum(
        step.get("estimated_duration_ms", 0) for step in steps if isinstance(step, dict)
    )
    estimated_duration_seconds = max(1, int(round(total_ms / 1000)))

    resp = jsonify(
        {
            "stub": True,
            "job_id": job_id,
            "pipeline_id": pipeline_id,
            "status": "running",
            "estimated_duration_seconds": estimated_duration_seconds,
            "steps": steps,
            "resource_snapshot": resource_snapshot,
            "stream_url": f"/jobs/{job_id}/stream",
        }
    )
    resp.headers["X-Stub-Endpoint"] = "1"
    return resp


def job_stream(job_id: str):
    """Stream job events as SSE for UI clients.

    The Web UI's pipeline builder expects an Orchestrator-style endpoint at:
      GET /jobs/{job_id}/stream  (proxied via /api/jobs/{job_id}/events)

    In development, the pipeline builder may generate a stub job_id client-side
    (when the UI uses the stub API). This endpoint emits a minimal sequence of
    SSE events so the UI can render step durations without requiring a separate
    orchestrator process.
    """

    def gen():
        # Initial handshake event (useful for client debug)
        yield f"event: init\ndata: {json.dumps({'job_id': job_id})}\n\n"

        # Emit at least one completed step update with a duration_ms so the UI can
        # display a "{n}ms" badge in the Execution Monitor.
        step_payload = {
            "job_id": job_id,
            "step_id": "step_1",
            "status": "completed",
            "preview": "stub step completed",
            "timing": {"duration_ms": 1234},
        }
        yield f"event: step_update\ndata: {json.dumps(step_payload)}\n\n"

        # Terminal status event so clients can stop streaming.
        yield f"event: status\ndata: {json.dumps({'job_id': job_id, 'status': 'completed'})}\n\n"

        # Explicit stream end marker (some clients look for this).
        yield "event: stream_end\ndata: {}\n\n"

    resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["X-Stub-Endpoint"] = "1"
    return resp


def print_exposed_tools():
    """Print the list of exposed tools for debugging/verification."""
    try:
        print("\n" + "=" * 60)
        print("AGENT STARTUP DIAGNOSTICS")
        print("=" * 60)

        # Ensure modules are loaded so registry is populated
        _ensure_tool_modules_loaded()

        # Get the global agent instance (lazy load)
        try:
            agent = get_agent()
            tools = agent.tool_registry.get_all_tools()

            print(f"\nExposed Tools ({len(tools)}):")
            for tool in sorted(tools, key=lambda t: t.get_tool_name()):
                name = tool.get_tool_name()
                # Try to get description safely
                desc = ""
                if hasattr(tool, "get_tool_description"):
                    desc = tool.get_tool_description()
                elif hasattr(tool, "description"):
                    desc = tool.description

                print(f"  - {name}: {desc[:80]}...")
        except Exception as e:
            print(
                f"⚠ Failed to load tools (likely no API key for external provider): {e}"
            )

        print("\n" + "=" * 60 + "\n")
    except Exception as e:
        print(f"⚠ Failed to enumerate tools: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    print(f"Starting BR-KG Agent Service on http://0.0.0.0:{port}")

    # Print tool diagnostics
    print_exposed_tools()

    print("Available endpoints:")
    print("  - POST /chat - Simple chat endpoint for LLM responses")
    print("  - POST /query - Process a query with clustering")
    print("  - POST /feedback - Submit feedback for a query")
    print("  - GET /history/<user_id> - Get user query history")
    print("  - GET /statistics/<user_id> - Get user statistics")
    print("  - GET /statistics - Get global statistics")
    print("  - GET /demo - Run a demo query")
    print("  - DELETE /clear_history/<user_id> - Clear user history")

    # Enable threading to handle concurrent requests (important for slow DeepSeek API)
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
