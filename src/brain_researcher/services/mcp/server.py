"""Brain Researcher local MCP server (stdio).

This server is intentionally "thin": it exposes a stable, deterministic tool
surface while delegating actual neuroimaging execution to existing BR code.

Design goals:
- No dependency on running Agent/BR-KG HTTP services (direct imports only).
- Stdio transport (safe default for CLI clients).
- A small policy gate: allowed filesystem roots, optional network/danger toggles.
"""

# ruff: noqa: I001

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import importlib
import inspect
import ipaddress
import json
import logging
import multiprocessing as mp
import os
import queue
import re
import shutil
import signal
import socket
import sys
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, get_args
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

try:  # pragma: no cover - optional dependency
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover - jsonschema optional
    jsonschema = None  # type: ignore

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult as _McpCallToolResult
from mcp.types import TextContent as _McpTextContent
from pydantic import Field

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.config.run_artifacts import (
    get_mcp_run_roots_for_read,
)
from brain_researcher.core.literature.deep_research import (
    deep_research_get,
    deep_research_sync,
)
from brain_researcher.core.utils.env_loader import ensure_env_loaded
from brain_researcher.services.agent.api_fee_debit import ApiFeeReservationError
from brain_researcher.services.agent.deep_research_idea_pipeline import (
    generate_deep_research_idea_cards_from_result,
)
from brain_researcher.services.agent.hypothesis_candidate_cards import (
    build_candidate_cards_from_workflow_result,
    find_candidate_cards_payload,
    find_workflow_result,
    rewrite_candidate_cards,
)
from brain_researcher.services.agent.novelty_calibration_questions import (
    build_novelty_calibration_context,
    generate_novelty_calibration_questions,
)
from brain_researcher.services.agent.repo_repair_context import (
    generate_repo_repair_context as build_repo_repair_context,
)
from brain_researcher.services.br_kg.etl.loaders.session_snapshot_loader import (
    build_session_snapshot_graph_payload,
    load_session_digests,
    validate_session_graph_payload,
)

# --- Dependency-inversion wiring (services layer DAG) -----------------------
# The review layer (LLM judgment critics) and the memory layer (run-artifact
# distillation) sit *below* the agent/review layers in the services layer
# order, so they depend on lightweight registry seams instead of importing
# upward. The MCP server is the real composition root for both call paths (it
# is the sole caller of `distill_and_store_run` and the entrypoint for the
# scientific-review tools), so it registers the concrete impls here.
from brain_researcher.services.llm_gateway.router import LLMRouter as _LLMRouter
from brain_researcher.services.mcp.api_fee import (
    api_fee_error_payload,
    call_mcp_platform_api_with_fee,
    reset_mcp_api_fee_context,
    set_mcp_api_fee_context,
)
from brain_researcher.services.mcp.execution_recipes import (
    AUTO_RECIPE_TARGETS,
    DEFAULT_CLUSTER_PROFILE,
    RECIPE_TARGETS,
    agent_execution_metadata,
    build_execution_recipe,
    default_recipe_target,
    is_first_wave_heavy_runtime_workflow,
    is_long_running_batch_analysis_workflow,
    is_recipe_first_mcp_workflow,
    recipe_card_metadata,
    resolve_recipe_metadata,
)
from brain_researcher.services.mcp.loop_primitives import (
    DEFAULT_LOOP_PROFILE_ID,
    SUPPORTED_LOOP_PROFILE_IDS,
    build_run_bundle_payload,
    build_run_scorecard,
    compare_run_scorecards,
    get_loop_profile,
)
from brain_researcher.services.mcp.param_norm import (
    as_str_list,
    coerce_enum,
    enum_str,
    resolve_enum_or_error,
)
from brain_researcher.services.mcp.research_summaries import (
    generate_bug_digest as build_bug_digest_summary,
)
from brain_researcher.services.mcp.research_summaries import (
    generate_research_trajectory_and_insights as build_research_trajectory_summary,
)
from brain_researcher.services.mcp.session_lessons import (
    OPEN_RISK_LABELS,
    SESSION_KG_NODE_LABELS,
    SESSION_KG_QUERY_EXAMPLES,
    SESSION_KG_RELATIONSHIP_TYPES,
    build_session_learning_report,
    build_session_policy_cards,
    build_session_signal_report,
    classify_session,
    extract_session_lessons,
)
from brain_researcher.services.mcp.slurm_tools import (
    CLUSTER_PROFILES as _SLURM_CLUSTER_PROFILES,
)
from brain_researcher.services.mcp.slurm_tools import (
    SCRIPT_SOURCES as _SLURM_SCRIPT_SOURCES,
)
from brain_researcher.services.mcp.slurm_tools import (
    CommandIntent as _SlurmCommandIntent,
)
from brain_researcher.services.mcp.slurm_tools import GuideAction as _SlurmGuideAction
from brain_researcher.services.mcp.slurm_tools import GuideTopic as _SlurmGuideTopic
from brain_researcher.services.mcp.slurm_tools import SlurmAction as _SlurmAction
from brain_researcher.services.mcp.slurm_tools import TemplateKind as _SlurmTemplateKind
from brain_researcher.services.memory import (  # noqa: F401  # re-exported: public server surface read by tests/callers
    MEMORY_CARD_TYPES,
    MemoryStore,
    build_verification_claim_mapping,
    distill_and_store_run,
    extract_claim_family_identity,
    normalize_claim_text,
    summarize_claim_families,
)
from brain_researcher.services.memory.leaves_review_distiller import (
    register_review_distiller as _register_review_distiller,
)
from brain_researcher.services.review.distill_review import (
    distill_review_records as _distill_review_records_impl,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    FORBIDDEN_GUIDANCE as _QSM_FORBIDDEN_GUIDANCE,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    HARD_CONSTRAINTS as _QSM_HARD_CONSTRAINTS,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    NON_DISPLACEMENT_NOTICE as _QSM_NON_DISPLACEMENT_NOTICE,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    QC_PROTOCOL as _QSM_QC_PROTOCOL,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    filter_qsm_tool_candidates,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    normalize_modality_list as _normalize_qsm_modality_list,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    qsm_retrieval_gate,
    review_qsm_implementation_payload,
)
from brain_researcher.services.review.rapidtide_critic import (
    review_rapidtide_implementation,
)
from brain_researcher.services.shared.dataset_mounts import dataset_mount_snapshots
from brain_researcher.services.shared.leaves_judgment_router import (
    register_default_judgment_router as _register_default_judgment_router,
)
from brain_researcher.services.shared.mcp_tokens import (
    compute_digest,
    isoformat_z,
    load_pepper,
    parse_iso_datetime,
    parse_token,
    redis_token_key,
    utc_now,
)
from brain_researcher.services.shared.planner.handoff import (
    build_handoff_from_plan_payload,
)
from brain_researcher.services.shared.runtime_semantic import (
    prewarm_sentence_transformer,
    semantic_matching_scope,
)
from brain_researcher.services.tools.catalog_loader import (
    is_workflow_tool_id,
    load_orchestration_workflows,
    load_workflow_catalog_ids,
)
from brain_researcher.services.tools.executor import (
    PYTHON_BACKEND_UNRESOLVABLE,
    TOOL_REGISTRY_MISCONFIGURED,
    audit_python_backend_configuration,
    execute_tool,
    resolve_runtime_tool_ids,
)
from brain_researcher.services.tools.registry import UnifiedToolRegistry
from brain_researcher.services.tools.spec import (
    Kind,
    ToolExecutionCapabilities,
    ToolSpec,
    infer_requires_runtime,
    normalize_hard_dependencies,
    normalize_implementation_level,
)
from brain_researcher.services.tools.tool_base import ToolResult

_register_default_judgment_router(lambda: _LLMRouter())
_register_review_distiller(_distill_review_records_impl)

UTC = timezone.utc

# Ensure direct module execution (`python -m ...server`) picks up repo .env
# values before module-level auth/transport constants are materialized.
ensure_env_loaded()

logger = logging.getLogger(__name__)

mcp = FastMCP("brain-researcher")

# Per-request "where did this MCP call enter from" tag. Populated by the HTTP
# entry middleware; defaults to "external" (public MCP entry) when unset, e.g.
# stdio clients or tests. Values: "internal" | "external".
# Defined in mcp/runstore.py (consumed by runstore._save_run); imported here so
# server.py code paths that set/reset the entry source keep working unchanged.
from brain_researcher.services.mcp.runstore import (  # noqa: E402
    _mcp_entry_source,
)

# Lazy-initialized derived memory store for novelty pre-filtering of hypothesis cards.
_mcp_memory_store: MemoryStore | None = None


def _cluster_internal_host_candidates() -> set[str]:
    raw = os.getenv("BR_MCP_INTERNAL_HOSTS") or os.getenv("BR_MCP_HTTP_URL") or ""
    hosts: set[str] = set()
    for part in raw.split(","):
        token = part.strip().lower()
        if not token:
            continue
        try:
            parsed = urlparse(token)
        except Exception:
            parsed = None
        if parsed is not None and parsed.netloc:
            host = parsed.hostname or ""
            if host:
                hosts.add(host.lower())
            continue
        hosts.add(token)
    return hosts


def _is_internal_mcp_request_host(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.split(":", 1)[0].strip().lower()
    if not host:
        return False
    if host.endswith(".svc.cluster.local") or host.endswith(".svc"):
        return True
    return host in _cluster_internal_host_candidates()


def _get_mcp_memory_store() -> MemoryStore | None:
    global _mcp_memory_store
    if _mcp_memory_store is not None:
        return _mcp_memory_store
    try:
        from pathlib import Path as _Path

        from brain_researcher.config.run_artifacts import (
            get_mcp_run_root,
            get_mcp_run_roots_for_read,
        )

        primary = _Path(get_mcp_run_root()).expanduser().resolve()
        readable = get_mcp_run_roots_for_read(primary)
        has_memory = any(
            (_Path(r) / "memory" / "index" / "memory.sqlite3").exists()
            or (_Path(r) / "memory" / "cards").exists()
            for r in readable
        )
        if has_memory:
            _mcp_memory_store = MemoryStore(run_root=primary)
    except Exception:
        pass
    return _mcp_memory_store


KG_MULTIHOP_LEGACY_OUTPUTS_WARNING = "deprecation:kg_multihop_qa:data.outputs"
AGENT_LOCAL_EXECUTION_WARNING = (
    "[DEPRECATED for Agents] Do NOT use for remote execution. "
    "Generate a local python script with tqdm/logging instead."
)

_INPUT_PLACEHOLDER_RE = re.compile(
    r"\$\{inputs\.([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}"
)
_PIPELINE_STEP_TOKEN_RE = re.compile(r"\$\{(steps\.[A-Za-z_][A-Za-z0-9_.-]*)\}")
_PIPELINE_STEP_SHORTHAND_RE = re.compile(
    r"\{([A-Za-z_][A-Za-z0-9_-]*)\.([A-Za-z0-9_.-]+)\}"
)
_DR_OPAQUE_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/_=-]{32,}$")
_NO_DEFAULT = object()


_REGISTRY: UnifiedToolRegistry | None = None
_REGISTRY_LOCK = threading.Lock()
_MULTIAGENT_ROUTER: Any | None = None
_MULTIAGENT_ROUTER_LOCK = threading.Lock()
_MULTIAGENT_ROUTER_FAILED = False
_PLAN_CACHE: dict[str, dict[str, Any]] = {}


def _get_registry() -> UnifiedToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = UnifiedToolRegistry()
    return _REGISTRY


_TOOLSPEC_SCHEMA_CACHE: dict[str, ToolSpec] = {}
_TOOLSPEC_SCHEMA_CACHE_LOCK = threading.Lock()


def _run_async_sync(coro):
    """Execute async monitor/state-store calls from sync MCP tools."""
    if not inspect.isawaitable(coro):
        return coro
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _get_latest_plan_cache() -> dict[str, dict[str, Any]]:
    if _PLAN_CACHE:
        return _PLAN_CACHE
    try:
        agent_web_service = importlib.import_module(
            "brain_researcher.services.agent.web_service"
        )
        agent_plan_cache = getattr(agent_web_service, "_PLAN_CACHE", None)
        if isinstance(agent_plan_cache, dict):
            return agent_plan_cache
    except Exception as exc:  # pragma: no cover - best-effort fallback
        logger.debug("get_latest_plan could not load agent plan cache: %s", exc)
    return _PLAN_CACHE


def _record_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    return {}


def _tool_result_payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        structured = value[1]
        return structured if isinstance(structured, dict) else {}
    if isinstance(value, _McpCallToolResult):
        structured = value.structuredContent
        return structured if isinstance(structured, dict) else {}
    return _record_dict(value)


def _rewrite_tool_result_content(
    content: Any,
    structured_payload: dict[str, Any],
) -> Any:
    content_items = list(content or [])
    if (
        len(content_items) == 1
        and isinstance(content_items[0], _McpTextContent)
        and content_items[0].type == "text"
    ):
        return [
            _McpTextContent(
                type="text",
                text=json.dumps(structured_payload, indent=2, ensure_ascii=False),
                annotations=content_items[0].annotations,
                meta=content_items[0].meta,
            )
        ]
    return content


def _tool_result_with_structured_payload(
    result: Any,
    structured_payload: dict[str, Any],
) -> Any:
    if isinstance(result, dict):
        return structured_payload
    if isinstance(result, tuple) and len(result) == 2:
        return (
            _rewrite_tool_result_content(result[0], structured_payload),
            structured_payload,
        )
    if not isinstance(result, _McpCallToolResult):
        return result

    return _McpCallToolResult(
        meta=result.meta,
        content=_rewrite_tool_result_content(result.content, structured_payload),
        structuredContent=structured_payload,
        isError=result.isError,
    )


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_text_value(*values: Any) -> str | None:
    for value in values:
        text = _text_value(value)
        if text:
            return text
    return None


def _parse_job_payload_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(raw, dict):
        return raw
    return {}


def _plan_payload_thread_id(plan_payload: dict[str, Any]) -> str | None:
    context = _record_dict(plan_payload.get("context"))
    return _first_text_value(
        plan_payload.get("thread_id"),
        plan_payload.get("session_id"),
        context.get("thread_id"),
        context.get("session_id"),
    )


def _job_record_plan_bundle(record: Any) -> tuple[dict[str, Any], str | None]:
    payload = _parse_job_payload_json(getattr(record, "payload_json", None))
    metadata = _record_dict(payload.get("metadata"))
    client_plan = _record_dict(metadata.get("client_plan_envelope"))
    plan_payload = _record_dict(payload.get("plan_of_record")) or _record_dict(
        metadata.get("plan_of_record")
    )
    thread_id = _first_text_value(
        metadata.get("thread_id"),
        client_plan.get("thread_id"),
        getattr(record, "session_id", None),
    )
    return plan_payload, thread_id


def _job_recency_key(record: Any) -> int:
    values = [
        getattr(record, "finished_at", None),
        getattr(record, "started_at", None),
        getattr(record, "claimed_at", None),
        getattr(record, "queued_at", None),
        getattr(record, "created_at", None),
    ]
    normalized = [int(v) for v in values if isinstance(v, int | float)]
    return max(normalized, default=0)


def _build_latest_plan_continuation_prompt(
    *,
    handoff: dict[str, Any],
    thread_id: str | None = None,
) -> str:
    normalized_thread_id = _text_value(thread_id)
    plan_id = _text_value(handoff.get("plan_id"))
    if plan_id:
        if normalized_thread_id:
            return (
                f'Continue from Brain Researcher plan {plan_id} for thread "{normalized_thread_id}". '
                f'Call get_latest_plan(thread_id="{normalized_thread_id}") to fetch '
                "the validated handoff block before you execute."
            )
        return (
            f"Continue from Brain Researcher plan {plan_id}. "
            "Call get_latest_plan() to fetch the validated handoff block before "
            "you execute."
        )
    if normalized_thread_id:
        return (
            f'Continue from my Brain Researcher plan for thread "{normalized_thread_id}". '
            f'Call get_latest_plan(thread_id="{normalized_thread_id}") to fetch '
            "the validated handoff block before you execute."
        )
    return (
        "Continue from my Brain Researcher plan. "
        "Call get_latest_plan() to fetch the latest validated handoff block before "
        "you execute."
    )


def _get_latest_plan_job_store() -> Any | None:
    try:
        from brain_researcher.services.shared.job_store_registry import (
            get_initialized_job_store,
            peek_initialized_job_store,
        )

        existing = peek_initialized_job_store()
        if existing is not None:
            return existing

        backend = str(os.getenv("BR_QUEUE_BACKEND", "memory")).strip().lower()
        if backend == "memory":
            return None

        job_store = get_initialized_job_store()
        initialize = getattr(job_store, "initialize", None)
        if callable(initialize):
            _run_async_sync(initialize())
        return job_store
    except Exception as exc:  # pragma: no cover - best-effort fallback
        logger.debug("get_latest_plan could not load JobStore: %s", exc)
        return None


def _resolve_latest_plan_payload(
    thread_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    requested_thread_id = _text_value(thread_id)

    cache_items = list(_get_latest_plan_cache().items())
    for plan_id, cached_plan in reversed(cache_items):
        if not isinstance(cached_plan, dict):
            continue
        cached_thread_id = _plan_payload_thread_id(cached_plan)
        if requested_thread_id and cached_thread_id != requested_thread_id:
            continue
        return cached_plan, {
            "source": "agent_plan_cache",
            "thread_id": cached_thread_id,
            "source_plan_id": plan_id,
        }

    job_store = _get_latest_plan_job_store()
    if job_store is None:
        return None, {"source": "none", "thread_id": requested_thread_id}

    try:
        records = _run_async_sync(job_store.list_all(limit=200, offset=0)) or []
    except TypeError:
        records = _run_async_sync(job_store.list_all()) or []
    except Exception as exc:
        logger.warning("get_latest_plan could not list JobStore records: %s", exc)
        return None, {"source": "job_store_error", "thread_id": requested_thread_id}

    sorted_records = sorted(records, key=_job_recency_key, reverse=True)
    for record in sorted_records:
        plan_payload, record_thread_id = _job_record_plan_bundle(record)
        if not plan_payload:
            continue
        if requested_thread_id and record_thread_id != requested_thread_id:
            continue
        return plan_payload, {
            "source": "job_store",
            "thread_id": record_thread_id,
            "source_job_id": getattr(record, "job_id", None),
            "job_status": getattr(record, "status", None),
        }

    return None, {"source": "none", "thread_id": requested_thread_id}


def _enrich_toolspec_schema(spec: ToolSpec) -> ToolSpec:
    """Best-effort: populate ``json_schema``/``required`` for a ToolSpec."""

    if spec.json_schema:
        return spec

    try:
        if spec.backend == "niwrap":
            from brain_researcher.services.tools.executor import (
                _resolve_niwrap_tool_name,
            )
            from brain_researcher.services.tools.niwrap.catalog import get_tool_by_name

            niwrap_id = spec.niwrap_id or f"{spec.name}.run"
            tool_def = get_tool_by_name(niwrap_id)
            if tool_def is None:
                resolved = _resolve_niwrap_tool_name(niwrap_id)
                if resolved:
                    tool_def = get_tool_by_name(resolved)
            if tool_def and isinstance(tool_def.get("input_schema"), dict):
                schema = tool_def["input_schema"]
                required = schema.get("required", []) or []
                if not isinstance(required, list):
                    required = []
                return spec.model_copy(
                    deep=True,
                    update={"json_schema": schema, "required": required},
                )

        elif spec.backend == "python" and spec.python_class:
            from brain_researcher.services.tools.executor import (
                _resolve_python_tool_instance,
            )
            from brain_researcher.services.tools.spec import spec_from_tool

            tool_obj = _resolve_python_tool_instance(spec)
            if tool_obj is not None:
                extracted = spec_from_tool(tool_obj)
                if extracted is not None:
                    updates: dict[str, Any] = {}
                    if not spec.json_schema and extracted.json_schema:
                        updates["json_schema"] = extracted.json_schema
                    if not spec.required and extracted.required:
                        updates["required"] = extracted.required
                    if (
                        spec.execution_capabilities is None
                        and extracted.execution_capabilities
                    ):
                        updates["execution_capabilities"] = (
                            extracted.execution_capabilities
                        )
                    if spec.qc_spec is None and extracted.qc_spec is not None:
                        updates["qc_spec"] = extracted.qc_spec
                    if not spec.requires_runtime and extracted.requires_runtime:
                        updates["requires_runtime"] = extracted.requires_runtime
                    if not spec.hard_dependencies and extracted.hard_dependencies:
                        updates["hard_dependencies"] = extracted.hard_dependencies
                    if updates:
                        return spec.model_copy(deep=True, update=updates)
    except Exception as exc:  # pragma: no cover - best effort enrichment
        logger.debug("toolspec schema enrichment failed for %s: %s", spec.name, exc)

    return spec


def _workflow_params_by_id() -> dict[str, dict[str, Any]]:
    """Index workflow catalog params by workflow id."""

    out: dict[str, dict[str, Any]] = {}
    for row in _load_workflow_catalog():
        if not isinstance(row, dict):
            continue
        workflow_id = str(row.get("id") or "").strip()
        params = row.get("params")
        if workflow_id and isinstance(params, dict):
            out[workflow_id] = params
    return out


def _enrich_workflow_toolspec_schema(tool_id: str, spec: ToolSpec) -> ToolSpec:
    """Inject workflow params schema/defaults for declarative workflows.

    Workflow catalog params are the source of truth for pipeline-facing input
    contracts. Always prefer them over runtime-introspected schemas, which can
    be stricter (for example requiring fields that have workflow defaults).
    """

    if not is_workflow_tool_id(tool_id):
        return spec

    params = _workflow_params_by_id().get(tool_id)
    if not isinstance(params, dict):
        return spec

    schema = params.get("schema") if isinstance(params.get("schema"), dict) else {}
    required: list[str] = []
    if isinstance(schema, dict):
        required_raw = schema.get("required", []) or []
        if isinstance(required_raw, list):
            required = [str(k).strip() for k in required_raw if str(k).strip()]

    updates: dict[str, Any] = {}
    if schema:
        updates["json_schema"] = schema
        updates["required"] = required
    defaults = params.get("defaults")
    if isinstance(defaults, dict):
        current_defaults = spec.defaults if isinstance(spec.defaults, dict) else {}
        merged_defaults = dict(defaults)
        for key, value in current_defaults.items():
            merged_defaults.setdefault(key, value)
        updates["defaults"] = merged_defaults

    if not updates:
        return spec
    return spec.model_copy(deep=True, update=updates)


def _get_toolspec_with_schema(tool_id: str) -> ToolSpec | None:
    with _TOOLSPEC_SCHEMA_CACHE_LOCK:
        cached = _TOOLSPEC_SCHEMA_CACHE.get(tool_id)
        if cached is not None:
            return cached

    reg = _get_registry()
    spec = reg.get_toolspec_by_name(tool_id)
    if spec is None:
        return None

    # Avoid mutating registry-cached ToolSpec objects.
    spec = spec.model_copy(deep=True)
    spec = _enrich_toolspec_schema(spec)
    spec = _enrich_workflow_toolspec_schema(tool_id, spec)
    with _TOOLSPEC_SCHEMA_CACHE_LOCK:
        _TOOLSPEC_SCHEMA_CACHE[tool_id] = spec
    return spec


@lru_cache(maxsize=1)
def _load_workflow_catalog() -> list[dict[str, Any]]:
    """Best-effort loader for workflow catalog metadata."""

    workflow_path = resolve_from_config("workflows", "workflow_catalog.yaml")
    if not workflow_path.exists():
        return []
    try:
        import yaml

        data = yaml.safe_load(workflow_path.read_text()) or {}
        workflows = data.get("workflows") if isinstance(data, dict) else None
        if not isinstance(workflows, list):
            return []
        normalized: list[dict[str, Any]] = []
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            workflow_id = str(workflow.get("id") or "").strip()
            if not workflow_id:
                continue
            inferred_params = _infer_workflow_input_params(workflow, workflow_id)
            params = workflow.get("params")
            normalized_params: dict[str, Any] | None = None
            if isinstance(params, dict):
                schema = params.get("schema")
                defaults = params.get("defaults")
                normalized_params = {}
                if isinstance(schema, dict):
                    normalized_params["schema"] = schema
                elif isinstance(inferred_params, dict):
                    inferred_schema = inferred_params.get("schema")
                    if isinstance(inferred_schema, dict):
                        normalized_params["schema"] = inferred_schema
                if isinstance(defaults, dict):
                    normalized_params["defaults"] = defaults
                elif isinstance(inferred_params, dict):
                    inferred_defaults = inferred_params.get("defaults")
                    if isinstance(inferred_defaults, dict):
                        normalized_params["defaults"] = inferred_defaults
                if not normalized_params:
                    normalized_params = None
            elif isinstance(inferred_params, dict):
                normalized_params = inferred_params
            resource_profile = workflow.get("resource_profile")
            row = {
                "id": workflow_id,
                "stage": workflow.get("stage"),
                "cost_tier": workflow.get("cost_tier"),
                "origin": workflow.get("origin"),
                "lifecycle": workflow.get("lifecycle"),
                "description": workflow.get("description")
                or workflow.get("impl")
                or workflow_id,
                "modalities": workflow.get("modalities") or [],
                "est_runtime": workflow.get("est_runtime")
                or (
                    resource_profile.get("est_runtime")
                    if isinstance(resource_profile, dict)
                    else None
                ),
                "params": normalized_params,
                "runtime": workflow.get("runtime"),
                "impl": workflow.get("impl"),
                "execution_story_kind": workflow.get("execution_story_kind"),
                "supported_recipe_targets": workflow.get("supported_recipe_targets"),
                "primary_target": workflow.get("primary_target"),
                "recipe_family": workflow.get("recipe_family"),
                "stable_workflow_pack": workflow.get("stable_workflow_pack"),
                "backend_options": workflow.get("backend_options"),
                "example_dataset": workflow.get("example_dataset"),
                "reference_assets": workflow.get("reference_assets"),
                "artifact_contract": workflow.get("artifact_contract"),
                "acceptance_gate": workflow.get("acceptance_gate"),
                "runbook": workflow.get("runbook"),
            }
            row.update(
                _compact_kwargs(
                    {
                        "source_repo": workflow.get("source_repo"),
                        "source_paper": workflow.get("source_paper"),
                        "tested_release": workflow.get("tested_release"),
                    }
                )
            )
            normalized.append(row)
        return normalized
    except Exception as exc:
        logger.warning("Failed to load workflow catalog: %s", exc)
        return []


def _workflow_catalog_entry(workflow_id: str) -> dict[str, Any] | None:
    target = str(workflow_id or "").strip()
    if not target:
        return None
    for row in _load_workflow_catalog():
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() == target:
            return row
    return None


def _workflow_param_schema_summary(
    params: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(params, dict):
        return None

    schema = params.get("schema") if isinstance(params.get("schema"), dict) else {}
    defaults = (
        params.get("defaults") if isinstance(params.get("defaults"), dict) else {}
    )

    required: list[str] = []
    properties: dict[str, str] = {}
    if isinstance(schema, dict):
        required_raw = schema.get("required", []) or []
        if isinstance(required_raw, list):
            required = [str(item).strip() for item in required_raw if str(item).strip()]

        props_raw = schema.get("properties", {}) or {}
        if isinstance(props_raw, dict):
            for key, value in props_raw.items():
                if not str(key).strip():
                    continue
                value_type = "any"
                if isinstance(value, dict):
                    raw_type = value.get("type")
                    if isinstance(raw_type, str) and raw_type.strip():
                        value_type = raw_type.strip()
                    elif isinstance(raw_type, list) and raw_type:
                        value_type = (
                            "|".join(
                                str(part).strip()
                                for part in raw_type
                                if str(part).strip()
                            )
                            or "any"
                        )
                properties[str(key)] = value_type

    return {
        "has_schema": bool(schema),
        "has_defaults": bool(defaults),
        "required": required,
        "properties": properties,
        "default_keys": sorted(str(k) for k in defaults.keys()),
    }


def _workflow_toolspec_card(tool_id: str, include_schema: bool = True) -> ToolSpec:
    entry = _workflow_catalog_entry(tool_id) or {}
    description = str(entry.get("description") or tool_id).strip()
    lifecycle = str(entry.get("lifecycle") or "").strip().lower()
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    schema = params.get("schema") if isinstance(params.get("schema"), dict) else {}
    defaults = (
        params.get("defaults") if isinstance(params.get("defaults"), dict) else {}
    )

    required: list[str] = []
    if isinstance(schema, dict):
        required_raw = schema.get("required", []) or []
        if isinstance(required_raw, list):
            required = [str(item).strip() for item in required_raw if str(item).strip()]

    tool_schema = schema if include_schema and isinstance(schema, dict) else {}
    tool_defaults = defaults if include_schema and isinstance(defaults, dict) else {}

    implementation_level = "production"
    if lifecycle in {"beta", "experimental", "deprecated"}:
        implementation_level = lifecycle

    tags = ["workflow", "pipeline_only"]
    if is_recipe_first_mcp_workflow(tool_id):
        tags.append("recipe_first")
    if is_first_wave_heavy_runtime_workflow(tool_id):
        tags.append("external_runtime")
    if is_long_running_batch_analysis_workflow(tool_id):
        tags.append("batch_analysis")

    return ToolSpec(
        name=tool_id,
        description=description,
        backend="python",
        kind="analysis",
        category="workflow",
        tags=tags,
        modalities=[str(m) for m in (entry.get("modalities") or []) if str(m).strip()],
        json_schema=tool_schema,
        required=required if include_schema else [],
        defaults=tool_defaults,
        implementation_level=implementation_level,
        requires_runtime="python",
        cost_hint=(
            "expensive"
            if str(entry.get("cost_tier") or "").strip().lower() == "expensive"
            else "normal"
        ),
    )


def _workflow_search_rows() -> list[dict[str, Any]]:
    """Return orchestration-eligible workflow rows with catalog-backed metadata when available."""

    allowed_ids = [str(item or "").strip() for item in load_orchestration_workflows()]
    allowed_ids = [wid for wid in allowed_ids if wid]
    if not allowed_ids:
        return []

    catalog_by_id: dict[str, dict[str, Any]] = {}
    for row in _load_workflow_catalog():
        if not isinstance(row, dict):
            continue
        workflow_id = str(row.get("id") or "").strip()
        if not workflow_id:
            continue
        catalog_by_id[workflow_id] = row

    rows: list[dict[str, Any]] = []
    for workflow_id in allowed_ids:
        entry = catalog_by_id.get(workflow_id)
        if isinstance(entry, dict):
            rows.append(dict(entry))
            continue
        rows.append(
            {
                "id": workflow_id,
                "stage": None,
                "cost_tier": None,
                "origin": "orchestration",
                "lifecycle": "active",
                "description": workflow_id,
                "modalities": [],
                "est_runtime": None,
                "params": None,
            }
        )
    return rows


_SEARCH_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_SEARCH_COMPOUND_SEPARATOR_RE = re.compile(r"[_./-]+")
_EXPLICIT_TOOL_QUERY_RE = re.compile(
    r"(?:^|\s)(?:afni|fsl|ants|spm|workbench|mrtrix3|freesurfer|nilearn|python)\.[^\s]+",
    re.IGNORECASE,
)
_SEARCH_TOKEN_SYNONYMS: dict[str, set[str]] = {
    "atlas": {"parcellation", "parcel", "schaefer"},
    "bold": {"fmri", "functional"},
    "connectivity": {"connectome", "correlation", "network", "fc"},
    "connectome": {"connectivity", "correlation", "network", "fc"},
    "default": {"dmn", "rest", "resting"},
    "dmn": {"default", "mode", "network", "rest", "resting"},
    "fmri": {"bold", "functional", "rsfmri"},
    "functional": {"fmri", "bold"},
    "mode": {"dmn", "rest", "resting"},
    "network": {"connectome", "connectivity", "dmn"},
    "parcellation": {"atlas", "parcel", "schaefer"},
    "rest": {"resting", "rsfmri"},
    "resting": {"rest", "rsfmri"},
    "state": {"rest", "resting"},
}


def _tokenize_search_query(query: str) -> list[str]:
    return [tok for tok in _SEARCH_TOKEN_RE.findall((query or "").lower()) if tok]


def _expand_search_compounds(text: str) -> str:
    return _SEARCH_COMPOUND_SEPARATOR_RE.sub(" ", str(text or "").lower())


def _normalize_phase_list(phases: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for phase in phases or []:
        candidate = str(phase or "").strip().lower()
        if (
            candidate in {"explore", "plan", "execute", "admin"}
            and candidate not in normalized
        ):
            normalized.append(candidate)
    return normalized


def _card_matches_phases(card: dict[str, Any], phases: list[str] | None) -> bool:
    normalized = _normalize_phase_list(phases)
    if not normalized:
        return True
    allowed = {
        str(value).strip().lower()
        for value in (card.get("allowed_phases") or [])
        if str(value).strip()
    }
    return bool(allowed & set(normalized))


def _normalize_tool_search_modalities(modalities: list[str] | None) -> set[str]:
    return {
        str(value).strip().lower() for value in (modalities or []) if str(value).strip()
    }


def _card_matches_modalities(
    card: dict[str, Any], modalities: list[str] | None
) -> bool:
    requested = _normalize_tool_search_modalities(modalities)
    if not requested:
        return True
    card_modalities = _normalize_tool_search_modalities(card.get("modalities") or [])
    if not card_modalities:
        return True
    return bool(card_modalities & requested)


def _tool_search_card_text(card: dict[str, Any]) -> str:
    execution_story = card.get("execution_story")
    parts = [
        str(card.get("name") or ""),
        str(card.get("description") or ""),
        str(card.get("search_hint") or ""),
        str(card.get("backend") or ""),
        str(card.get("kind") or ""),
        str(card.get("category") or ""),
        str(card.get("approval_level") or ""),
        str(card.get("execution_story_kind") or ""),
        str(card.get("primary_target") or ""),
        str(card.get("next_action") or ""),
        " ".join(str(v) for v in (card.get("modalities") or [])),
        " ".join(str(v) for v in (card.get("intents") or [])),
        " ".join(str(v) for v in (card.get("allowed_phases") or [])),
        " ".join(str(v) for v in (card.get("consumes") or [])),
        " ".join(str(v) for v in (card.get("produces") or [])),
        " ".join(str(v) for v in (card.get("supported_recipe_targets") or [])),
        " ".join(str(v) for v in (card.get("expected_artifacts") or [])),
    ]
    if isinstance(execution_story, dict):
        parts.append(str(execution_story.get("summary") or ""))
        parts.append(
            " ".join(str(v) for v in (execution_story.get("next_steps") or []))
        )
    return " ".join(parts).lower()


def _workflow_search_text(entry: dict[str, Any]) -> str:
    params = entry.get("params")
    schema = params.get("schema") if isinstance(params, dict) else {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    runtime = entry.get("runtime")
    backend_options = entry.get("backend_options")
    parts = [
        str(entry.get("id") or ""),
        str(entry.get("description") or ""),
        str(entry.get("stage") or ""),
        str(entry.get("cost_tier") or ""),
        str(entry.get("origin") or ""),
        str(entry.get("lifecycle") or ""),
        str(entry.get("execution_story_kind") or ""),
        str(entry.get("primary_target") or ""),
        str(entry.get("requires_runtime") or ""),
        str(entry.get("recipe_family") or ""),
        str(entry.get("impl") or ""),
        str(entry.get("source_repo") or ""),
        str(entry.get("source_paper") or ""),
        str(entry.get("runbook") or ""),
        " ".join(str(v) for v in (entry.get("modalities") or [])),
        " ".join(str(v) for v in (entry.get("supported_recipe_targets") or [])),
        " ".join(str(k) for k in (properties or {}).keys()),
    ]
    for spec in (properties or {}).values():
        if isinstance(spec, dict):
            parts.append(str(spec.get("description") or ""))
    if isinstance(runtime, dict):
        parts.append(str(runtime.get("kind") or ""))
        parts.append(str(runtime.get("impl") or ""))
    if isinstance(backend_options, dict):
        parts.append(str(backend_options.get("default") or ""))
        parts.append(" ".join(str(v) for v in (backend_options.get("available") or [])))
    return " ".join(parts).lower()


def _search_match_score(query: str, text: str, *, identifier: str | None = None) -> int:
    q = (query or "").strip().lower()
    corpus = (text or "").lower()
    if not q:
        return 0
    score = 0
    normalized_identifier = str(identifier or "").strip().lower()
    expanded_query = _expand_search_compounds(q)
    expanded_corpus = f"{corpus} {_expand_search_compounds(corpus)}"
    if normalized_identifier and q == normalized_identifier:
        score += 10_000
    if q in corpus or expanded_query in expanded_corpus:
        score += 500 + min(len(q), 120)

    tokens = _tokenize_search_query(q)
    if normalized_identifier:
        id_tokens = set(
            _tokenize_search_query(
                f"{normalized_identifier} {_expand_search_compounds(normalized_identifier)}"
            )
        )
    else:
        id_tokens = set()
    corpus_tokens = set(_tokenize_search_query(expanded_corpus))

    for tok in tokens:
        if tok in id_tokens:
            score += 250
        if tok in corpus_tokens:
            score += 80
        elif tok in corpus:
            score += 25

    for a, b in zip(tokens, tokens[1:], strict=False):
        phrase = f"{a} {b}"
        if phrase in expanded_corpus:
            score += 120

    expanded_tokens = set(tokens)
    for tok in tokens:
        expanded_tokens.update(_SEARCH_TOKEN_SYNONYMS.get(tok, set()))
    for tok in sorted(expanded_tokens - set(tokens)):
        if tok in corpus_tokens:
            score += 35
        elif tok in expanded_corpus:
            score += 10

    return score


def _tool_search_domain_adjustment(query: str, card: dict[str, Any]) -> int:
    q = (query or "").strip().lower()
    if not q:
        return 0

    identifier = str(card.get("name") or "").strip().lower()
    text = _tool_search_card_text(card)
    tokens = set(_tokenize_search_query(q))
    score = 0

    # Prefer canonical runtime IDs over legacy dotted execution IDs for
    # ordinary capability search. Explicit tool-ID queries already bypass this.
    if identifier.endswith(".run") and not _looks_like_explicit_tool_query(query):
        score -= 220

    is_vbm_query = (
        "vbm" in tokens
        or {"grey", "matter", "volume"} <= tokens
        or {"gray", "matter", "volume"} <= tokens
    )
    if is_vbm_query:
        if identifier == "spm12_vbm":
            score += 220
        if "voxel based morphometry" in text or "voxel-based morphometry" in text:
            score += 120

    is_motion_correction_query = {"motion", "correction"} <= tokens
    if is_motion_correction_query:
        if identifier == "realtime_fmri":
            score += 180
        if (
            "real-time motion correction" in text
            or "realtime motion correction" in text
        ):
            score += 120
        if identifier == "fmriprep_preprocessing":
            score -= 40

    is_ica_denoising_query = "ica" in tokens and any(
        tok.startswith("denois") or tok == "noise" for tok in tokens
    )
    if is_ica_denoising_query:
        if identifier == "fsl_fix":
            score += 180
        if (
            "artifact removal" in text
            or "remove noise components" in text
            or "xnoiseifier" in text
        ):
            score += 120
        if identifier == "fsl_melodic_ica":
            score -= 40

    is_brain_age_prediction_query = {"brain", "age"} <= tokens and any(
        tok.startswith("predict") for tok in tokens
    )
    if is_brain_age_prediction_query:
        if identifier in {"compute_brain_age", "workflow_brain_age_prediction"}:
            score += 220
        if "brain-age" in text or "brain age" in text:
            score += 120
        if identifier in {"brain_simulation", "workflow_brain_simulation"}:
            score -= 80

    is_searchlight_decoding_query = "searchlight" in tokens and any(
        tok.startswith("decod") for tok in tokens
    )
    if is_searchlight_decoding_query:
        if identifier == "searchlight_analysis":
            score += 220
        if "searchlight analysis" in text or "local pattern analysis" in text:
            score += 120
        if identifier == "mvpa":
            score -= 60

    return score


def _tool_search_family_routing_mode() -> str:
    override = os.environ.get("BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE")
    if override is not None and str(override).strip():
        return str(override).strip().lower()
    return os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE", "legacy").strip().lower()


def _looks_like_explicit_tool_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if ".run" in q or "@image:" in q or "@py:" in q or "@unknown" in q:
        return True
    if "\n" not in q and " " not in q:
        try:
            from brain_researcher.services.tools.catalog_loader import (
                get_toolspec_by_name,
                resolve_primary_runtime_tool_id,
            )

            if get_toolspec_by_name(q) is not None:
                return True
            canonical = resolve_primary_runtime_tool_id(q)
            if (
                canonical
                and canonical != q
                and get_toolspec_by_name(canonical) is not None
            ):
                return True
        except Exception:
            logger.debug("explicit tool query detection fallback failed", exc_info=True)
    return bool(_EXPLICIT_TOOL_QUERY_RE.search(q))


def _tool_search_family_ranked_ids(
    query: str,
    *,
    limit: int,
) -> list[str]:
    if _tool_search_family_routing_mode() != "cards":
        return []
    if not (query or "").strip():
        return []
    if _looks_like_explicit_tool_query(query):
        return []

    try:
        from brain_researcher.services.agent.tool_retriever import (
            rank_family_card_entrypoints,
        )
    except Exception as exc:
        logger.debug("tool_search family router import failed: %s", exc)
        return []

    try:
        return rank_family_card_entrypoints(
            query=query,
            max_families=3,
            limit=limit,
            path_str=os.environ.get("BR_TOOL_FAMILY_CARDS_PATH"),
        )
    except Exception as exc:
        logger.debug("tool_search family router failed: %s", exc)
        return []


@lru_cache(maxsize=4)
def _load_grandmaster_atomic_tool_metadata_cached(
    toolset_path: str, toolset_mtime_ns: int
) -> dict[str, dict[str, Any]]:
    """Load optional metadata overlays from grandmaster atomic tool entries."""

    try:
        import yaml

        raw = yaml.safe_load(Path(toolset_path).read_text()) or {}
    except Exception as exc:
        logger.debug("Failed to load grandmaster tool metadata: %s", exc)
        return {}

    entries = raw.get("atomic_tools") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return {}

    by_tool: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool_id = str(entry.get("id") or "").strip()
        if not tool_id:
            continue

        overlay: dict[str, Any] = {}
        if "implementation_level" in entry:
            overlay["implementation_level"] = entry.get("implementation_level")
        if "requires_runtime" in entry:
            overlay["requires_runtime"] = entry.get("requires_runtime")
        if "hard_dependencies" in entry:
            overlay["hard_dependencies"] = entry.get("hard_dependencies")
        if overlay:
            by_tool[tool_id] = overlay

    return by_tool


def _load_grandmaster_atomic_tool_metadata() -> dict[str, dict[str, Any]]:
    toolset_path = resolve_from_config("grandmaster", "toolset_vfinal.yaml")
    if not toolset_path.exists():
        return {}

    try:
        mtime_ns = int(toolset_path.stat().st_mtime_ns)
    except OSError:
        mtime_ns = -1

    return _load_grandmaster_atomic_tool_metadata_cached(str(toolset_path), mtime_ns)


_MCP_SURFACE_METADATA_BY_NAME: dict[str, dict[str, str]] = {
    "server_info": {
        "surface_tier": "ops",
        "capability_family": "server_ops",
    },
    "loop_profile_get": {
        "surface_tier": "ops",
        "capability_family": "server_ops",
    },
    "system_self_test": {
        "surface_tier": "ops",
        "capability_family": "server_ops",
    },
    "tool_search": {
        "surface_tier": "default",
        "capability_family": "tool_discovery",
    },
    "tool_search_structured": {
        "surface_tier": "advanced",
        "capability_family": "tool_discovery",
    },
    "tool_resolve": {
        "surface_tier": "advanced",
        "capability_family": "tool_discovery",
    },
    "tool_get": {
        "surface_tier": "default",
        "capability_family": "tool_discovery",
    },
    "workflow_search": {
        "surface_tier": "advanced",
        "capability_family": "tool_discovery",
    },
    "get_execution_recipe": {
        "surface_tier": "advanced",
        "capability_family": "execution_recipe",
    },
    "plan_preflight": {
        "surface_tier": "default",
        "capability_family": "planning",
    },
    "plan_create": {
        "surface_tier": "default",
        "capability_family": "planning",
    },
    "tool_execute": {
        "surface_tier": "ops",
        "capability_family": "tool_execution_admin",
    },
    "pipeline_plan_validate": {
        "surface_tier": "ops",
        "capability_family": "pipeline_execution",
    },
    "pipeline_plan_review": {
        "surface_tier": "ops",
        "capability_family": "pipeline_execution",
    },
    "qsm_implementation_review": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "rapidtide_implementation_review": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "report_claim_provenance_check": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "run_code_review": {
        "surface_tier": "ops",
        "capability_family": "pipeline_execution",
    },
    "run_scientific_review": {
        "surface_tier": "ops",
        "capability_family": "pipeline_execution",
    },
    "run_autoresearch_scientific_review": {
        "surface_tier": "ops",
        "capability_family": "autoresearch_review",
    },
    "request_scientific_review": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "scientific_report_generate": {
        "surface_tier": "ops",
        "capability_family": "scientific_report",
    },
    "pipeline_execute": {
        "surface_tier": "ops",
        "capability_family": "pipeline_execution",
    },
    "log_research_event": {
        "surface_tier": "advanced",
        "capability_family": "research_logging",
    },
    "write_session_snapshot": {
        "surface_tier": "advanced",
        "capability_family": "research_logging",
    },
    "request_external_scientific_review_directive": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "submit_external_scientific_review_verdict": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "research_session_digest": {
        "surface_tier": "advanced",
        "capability_family": "research_logging",
    },
    "research_log_summary": {
        "surface_tier": "advanced",
        "capability_family": "research_logging",
    },
    "session_risk_classify": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "session_lesson_extract": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "session_open_risks_query": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "session_policy_cards_generate": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "session_learning_report_generate": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "session_signal_report_generate": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "session_backfill_to_kg": {
        "surface_tier": "advanced",
        "capability_family": "session_lessons",
    },
    "memory_write": {
        "surface_tier": "advanced",
        "capability_family": "memory",
    },
    "memory_search": {
        "surface_tier": "advanced",
        "capability_family": "memory",
    },
    "memory_get": {
        "surface_tier": "advanced",
        "capability_family": "memory",
    },
    "run_get": {
        "surface_tier": "default",
        "capability_family": "run_observability",
    },
    "run_list": {
        "surface_tier": "default",
        "capability_family": "run_observability",
    },
    "run_find_latest_reviewable": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "run_request_summary": {
        "surface_tier": "default",
        "capability_family": "run_observability",
    },
    "run_bundle_get": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "run_logs": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "run_cancel": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "run_metrics": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "run_scorecard": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "run_compare": {
        "surface_tier": "advanced",
        "capability_family": "run_observability",
    },
    "get_latest_plan": {
        "surface_tier": "default",
        "capability_family": "plan_handoff",
    },
    "generate_research_trajectory_and_insights": {
        "surface_tier": "advanced",
        "capability_family": "research_synthesis",
    },
    "generate_bug_digest": {
        "surface_tier": "advanced",
        "capability_family": "research_synthesis",
    },
    "generate_repo_repair_context": {
        "surface_tier": "advanced",
        "capability_family": "research_synthesis",
    },
    "latex_report_render": {
        "surface_tier": "advanced",
        "capability_family": "report_generation",
    },
    "artifact_list": {
        "surface_tier": "advanced",
        "capability_family": "artifact_inspection",
    },
    "artifact_read_text": {
        "surface_tier": "advanced",
        "capability_family": "artifact_inspection",
    },
    "artifact_get_metadata": {
        "surface_tier": "advanced",
        "capability_family": "artifact_inspection",
    },
    "artifact_read_bytes": {
        "surface_tier": "advanced",
        "capability_family": "artifact_inspection",
    },
    "kg_search_nodes": {
        "surface_tier": "default",
        "capability_family": "kg_explore",
    },
    "kg_get_node": {
        "surface_tier": "default",
        "capability_family": "kg_explore",
    },
    "kg_neighbors": {
        "surface_tier": "default",
        "capability_family": "kg_explore",
    },
    "kg_search_datasets": {
        "surface_tier": "advanced",
        "capability_family": "kg_explore",
    },
    "dataset_get_resources": {
        "surface_tier": "default",
        "capability_family": "dataset_resolution",
    },
    "kg_related_datasets": {
        "surface_tier": "advanced",
        "capability_family": "kg_explore",
    },
    "kg_behavior_to_fmri_retrieval": {
        "surface_tier": "advanced",
        "capability_family": "kg_explore",
    },
    "kg_list_dataset_onvoc_links": {
        "surface_tier": "advanced",
        "capability_family": "kg_explore",
    },
    "kg_multihop_qa": {
        "surface_tier": "advanced",
        "capability_family": "kg_reasoning",
    },
    "kg_verify_hypothesis": {
        "surface_tier": "default",
        "capability_family": "kg_hypothesis",
    },
    "verify_hypothesis_with_kg": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_verify_sampled_hypotheses": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_sample_ood_hypothesis": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_hypothesis_workflow": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_sample_and_verify_hypotheses": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_hypothesis_candidate_cards": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "hypothesis_hot_load_research": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "hypothesis_run_start": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "hypothesis_run_get": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_hypothesis_candidate_cards_start": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "kg_hypothesis_candidate_cards_get": {
        "surface_tier": "advanced",
        "capability_family": "kg_hypothesis",
    },
    "refuted_landscape_summary": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "companion_diagnostic_suggester": {
        "surface_tier": "advanced",
        "capability_family": "scientific_review",
    },
    "kg_probe": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "kg_find_structural_leverage": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "kg_detect_contradiction_motifs": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "kg_find_contradiction_frontiers": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "kg_mine_assumption_cracks": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "kg_find_analogy_transfers": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "kg_detect_topology_shifts": {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    },
    "google_file_search": {
        "surface_tier": "advanced",
        "capability_family": "google_research",
    },
    "grounding_resolve": {
        "surface_tier": "advanced",
        "capability_family": "grounding",
    },
    "grounding_gate_evidence_basis": {
        "surface_tier": "advanced",
        "capability_family": "grounding",
    },
    "google_deep_research_start": {
        "surface_tier": "advanced",
        "capability_family": "google_research",
    },
    "google_deep_research_get": {
        "surface_tier": "advanced",
        "capability_family": "google_research",
    },
    "google_deep_research": {
        "surface_tier": "advanced",
        "capability_family": "google_research",
    },
    "deepxiv": {
        "surface_tier": "default",
        "capability_family": "literature_search",
    },
    "sherlock_guide": {
        "surface_tier": "advanced",
        "capability_family": "sherlock",
    },
    "sherlock_slurm": {
        "surface_tier": "advanced",
        "capability_family": "sherlock",
    },
    "slurm_guide": {
        "surface_tier": "advanced",
        "capability_family": "slurm",
    },
    "slurm_submit": {
        "surface_tier": "advanced",
        "capability_family": "slurm",
    },
}

_MCP_SURFACE_NAME_ALIASES: dict[str, str] = {
    "mcp.server_info": "server_info",
    "mcp.tool_search": "tool_search",
    "mcp.system_self_test": "system_self_test",
    "mcp.sherlock_guide": "sherlock_guide",
    "mcp.sherlock_slurm": "sherlock_slurm",
    "mcp.slurm_guide": "slurm_guide",
    "mcp.slurm_submit": "slurm_submit",
    "google.file_search": "google_file_search",
    "br_kg.find_structural_leverage": "kg_find_structural_leverage",
    "br_kg.detect_contradiction_motifs": "kg_detect_contradiction_motifs",
    "br_kg.sample_ood_hypothesis": "kg_sample_ood_hypothesis",
    "br_kg.detect_topology_shifts": "kg_detect_topology_shifts",
}

_MCP_COMPAT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "verify_hypothesis_with_kg",
        "kg_find_structural_leverage",
        "kg_detect_contradiction_motifs",
        "kg_find_contradiction_frontiers",
        "kg_mine_assumption_cracks",
        "kg_find_analogy_transfers",
        "kg_sample_ood_hypothesis",
        "kg_verify_sampled_hypotheses",
        "kg_sample_and_verify_hypotheses",
        "google_deep_research_get",
        "hypothesis_run_get",
        "kg_hypothesis_candidate_cards_get",
    }
)
_MCP_RETIRED_PUBLIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "asl_quant_review",
        "tribe_predict",
    }
)
_MCP_HIDDEN_TOOL_NAMES: frozenset[str] = frozenset(
    set(_MCP_COMPAT_TOOL_NAMES) | set(_MCP_RETIRED_PUBLIC_TOOL_NAMES)
)


def _is_retired_public_tool_name(tool_id: Any) -> bool:
    return str(tool_id or "").strip() in _MCP_RETIRED_PUBLIC_TOOL_NAMES


_MCP_COMPAT_ALIAS_TARGETS: dict[str, str] = {
    "verify_hypothesis_with_kg": "kg_verify_hypothesis",
    "kg_find_structural_leverage": "kg_probe",
    "kg_detect_contradiction_motifs": "kg_probe",
    "kg_find_contradiction_frontiers": "kg_probe",
    "kg_mine_assumption_cracks": "kg_probe",
    "kg_find_analogy_transfers": "kg_probe",
    "kg_sample_ood_hypothesis": "kg_hypothesis_workflow",
    "kg_verify_sampled_hypotheses": "kg_hypothesis_workflow",
    "kg_sample_and_verify_hypotheses": "kg_hypothesis_workflow",
    "google_deep_research_get": "run_get",
    "hypothesis_run_get": "run_get",
    "kg_hypothesis_candidate_cards_get": "run_get",
}
_MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION = "mcp-compat-alias-usage-v1"
_MCP_COMPAT_ALIAS_USAGE_RECENT_LIMIT = 200
_MCP_COMPAT_ALIAS_RUNTIME_PARAM_KEYS: frozenset[str] = frozenset(
    {"semantic", "enable_semantic", "semantic_matching"}
)
_MCP_COMPAT_ALIAS_USAGE_LOCK = threading.Lock()

_ORIGINAL_MCP_LIST_TOOLS = mcp._tool_manager.list_tools
_ORIGINAL_MCP_CALL_TOOL = mcp._tool_manager.call_tool
_MCP_SIMPLE_SEMANTIC_DEFAULT_TOOLS: frozenset[str] = frozenset(
    {
        "plan_preflight",
        "plan_create",
        "kg_multihop_qa",
        "kg_probe",
        "kg_find_structural_leverage",
        "kg_detect_contradiction_motifs",
        "kg_find_contradiction_frontiers",
        "kg_mine_assumption_cracks",
        "kg_find_analogy_transfers",
        "kg_verify_hypothesis",
        "verify_hypothesis_with_kg",
        "kg_hypothesis_workflow",
        "kg_sample_ood_hypothesis",
        "kg_verify_sampled_hypotheses",
        "kg_sample_and_verify_hypotheses",
        "kg_hypothesis_candidate_cards",
        "kg_hypothesis_candidate_cards_start",
    }
)
_MCP_ISOLATED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "plan_preflight",
        "plan_create",
        "kg_multihop_qa",
        "kg_probe",
        "kg_find_structural_leverage",
        "kg_detect_contradiction_motifs",
        "kg_find_contradiction_frontiers",
        "kg_mine_assumption_cracks",
        "kg_find_analogy_transfers",
        "kg_verify_hypothesis",
        "verify_hypothesis_with_kg",
        "kg_hypothesis_workflow",
        "kg_sample_ood_hypothesis",
        "kg_verify_sampled_hypotheses",
        "kg_sample_and_verify_hypotheses",
        "kg_hypothesis_candidate_cards",
    }
)
_MCP_TOOL_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("BR_MCP_TOOL_EXECUTOR_WORKERS", "4") or "4")),
    thread_name_prefix="br-mcp-tool",
)


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _resolve_tool_semantic_preference(
    tool_name: str,
    arguments: dict[str, Any],
) -> bool | None:
    for key in ("semantic", "enable_semantic", "semantic_matching"):
        explicit = _coerce_optional_bool(arguments.get(key))
        if explicit is not None:
            return explicit
    if tool_name in _MCP_SIMPLE_SEMANTIC_DEFAULT_TOOLS:
        return False
    return None


async def _invoke_mcp_tool_call(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    context: Any | None,
    convert_result: bool,
    semantic_enabled: bool | None,
    isolated: bool,
) -> Any:
    async def _run_call() -> Any:
        with semantic_matching_scope(semantic_enabled):
            return await _ORIGINAL_MCP_CALL_TOOL(
                tool_name,
                arguments,
                context=context,
                convert_result=convert_result,
            )

    if not isolated:
        return await _run_call()

    call_context = contextvars.copy_context()
    loop = asyncio.get_running_loop()

    def _runner() -> Any:
        return call_context.run(lambda: asyncio.run(_run_call()))

    return await loop.run_in_executor(_MCP_TOOL_EXECUTOR, _runner)


def _spawn_semantic_prewarm() -> None:
    if not _truthy(os.getenv("BR_MCP_SEMANTIC_PREWARM")):
        return

    def _runner() -> None:
        started_at = time.perf_counter()
        try:
            prewarm_sentence_transformer("all-MiniLM-L6-v2")

            from brain_researcher.services.agent.tool_retriever import (
                _family_card_embedding_matrix,
                _family_cards_path,
            )
            from brain_researcher.services.br_kg.utils.task_matcher import TaskMatcher

            with semantic_matching_scope(True):
                TaskMatcher(enable_semantic=True, prewarm=True)

                family_cards_path = _family_cards_path()
                if family_cards_path:
                    _family_card_embedding_matrix(
                        str(family_cards_path),
                        "all-MiniLM-L6-v2",
                    )

            logger.info(
                "MCP semantic prewarm completed elapsed_ms=%.1f",
                (time.perf_counter() - started_at) * 1000.0,
            )
        except Exception:
            logger.exception("MCP semantic prewarm failed")

    threading.Thread(
        target=_runner,
        name="mcp-semantic-prewarm",
        daemon=True,
    ).start()


def _list_public_mcp_tools():
    tools = _ORIGINAL_MCP_LIST_TOOLS()
    return [
        tool
        for tool in tools
        if str(getattr(tool, "name", "") or "") not in _MCP_HIDDEN_TOOL_NAMES
    ]


if not getattr(mcp._tool_manager, "_br_public_surface_filter_installed", False):
    mcp._tool_manager.list_tools = _list_public_mcp_tools
    mcp._tool_manager._br_public_surface_filter_installed = True


async def _call_tool_with_research_telemetry(
    name: str,
    arguments: dict[str, Any],
    context: Any | None = None,
    convert_result: bool = False,
) -> Any:
    tool_name = str(name or "").strip()
    safe_arguments = arguments if isinstance(arguments, dict) else {}
    if _is_retired_public_tool_name(tool_name):
        logger.warning("Rejected retired MCP tool call tool=%s", tool_name)
        return {
            "ok": False,
            "error": "tool_removed",
            "message": f"{tool_name} is no longer exposed by the Brain Researcher MCP server.",
        }
    semantic_enabled = _resolve_tool_semantic_preference(tool_name, safe_arguments)
    isolated = tool_name in _MCP_ISOLATED_TOOL_NAMES
    started_at = time.perf_counter()
    pre_binding = _resolve_research_binding_for_tool_call(
        tool_name, safe_arguments, None, context
    )
    logger.info(
        "MCP tool start tool=%s isolated=%s semantic=%s",
        tool_name,
        isolated,
        semantic_enabled,
    )
    _record_research_tool_trace(
        binding=pre_binding,
        event_type="tool.call.started",
        tool_name=tool_name,
        arguments=safe_arguments,
    )

    try:
        result = await _invoke_mcp_tool_call(
            tool_name=tool_name,
            arguments=safe_arguments,
            context=context,
            convert_result=convert_result,
            semantic_enabled=semantic_enabled,
            isolated=isolated,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        logger.exception(
            "MCP tool failed tool=%s isolated=%s semantic=%s elapsed_ms=%.1f",
            tool_name,
            isolated,
            semantic_enabled,
            elapsed_ms,
        )
        binding = pre_binding or _resolve_research_binding_for_tool_call(
            tool_name, safe_arguments, None, context
        )
        _record_research_tool_trace(
            binding=binding,
            event_type="tool.call.exception",
            tool_name=tool_name,
            arguments=safe_arguments,
            error=str(exc),
        )
        if isinstance(binding, dict) and tool_name not in _RESEARCH_AUTO_EXCLUDED_TOOLS:
            _append_research_auto_event(
                session_id=_first_text_value(binding.get("session_id")) or "",
                client_session_id=_first_text_value(binding.get("client_session_id")),
                source_client=_normalize_research_source_client(
                    binding.get("source_client")
                ),
                run_id=_first_text_value(binding.get("run_id")),
                subtype="tool_exception",
                tool_name=tool_name,
                details={"message": str(exc)},
            )
        raise

    binding = _resolve_research_binding_for_tool_call(
        tool_name, safe_arguments, result, context
    )
    result_payload = _tool_result_payload_dict(result)
    if isinstance(binding, dict):
        _bind_research_transport_session(
            context,
            session_id=_first_text_value(binding.get("session_id")) or "",
            client_session_id=_first_text_value(binding.get("client_session_id")),
            source_client=_normalize_research_source_client(
                binding.get("source_client")
            ),
            run_id=_first_text_value(binding.get("run_id"))
            or _first_text_value(result_payload.get("run_id")),
        )
    _record_research_tool_trace(
        binding=binding or pre_binding,
        event_type="tool.call.finished",
        tool_name=tool_name,
        arguments=safe_arguments,
        result=result,
    )

    logger.info(
        "MCP tool finish tool=%s isolated=%s semantic=%s elapsed_ms=%.1f",
        tool_name,
        isolated,
        semantic_enabled,
        (time.perf_counter() - started_at) * 1000.0,
    )
    auto_event = _record_research_auto_tool_signal(
        binding=binding,
        tool_name=tool_name,
        arguments=safe_arguments,
        result=result,
    )
    return _attach_research_logging_directive(
        result,
        tool_name=tool_name,
        binding=binding,
        auto_event=auto_event,
    )


if not getattr(mcp._tool_manager, "_br_research_call_wrapper_installed", False):
    mcp._tool_manager.call_tool = _call_tool_with_research_telemetry
    mcp._tool_manager._br_research_call_wrapper_installed = True


def _mcp_surface_metadata(tool_name: str) -> dict[str, str]:
    normalized = str(tool_name or "").strip()
    if not normalized:
        return {}
    canonical_name = _MCP_SURFACE_NAME_ALIASES.get(normalized, normalized)
    if canonical_name.startswith("mcp."):
        canonical_name = canonical_name.split(".", 1)[1]
    metadata = _MCP_SURFACE_METADATA_BY_NAME.get(canonical_name)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _toolspec_for_mcp_card(
    spec: ToolSpec, *, workflow_entry: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Serialize ToolSpec with stable transparency metadata for MCP tool cards."""

    payload = spec.model_dump()
    overlay = _load_grandmaster_atomic_tool_metadata().get(spec.name, {})

    payload["implementation_level"] = normalize_implementation_level(
        overlay.get("implementation_level", payload.get("implementation_level")),
        default="production",
    )
    payload["requires_runtime"] = infer_requires_runtime(
        overlay.get("requires_runtime", payload.get("requires_runtime")),
        backend=spec.backend,
    )
    payload["hard_dependencies"] = normalize_hard_dependencies(
        overlay.get("hard_dependencies", payload.get("hard_dependencies"))
    )
    recipe_meta = recipe_card_metadata(
        spec.name, spec=spec, workflow_entry=workflow_entry
    )
    payload.update(recipe_meta)
    tags = [str(tag).strip() for tag in (payload.get("tags") or []) if str(tag).strip()]
    if recipe_meta.get("recipe_first_workflow") and "recipe_first" not in tags:
        tags.append("recipe_first")
    if recipe_meta.get("heavy_runtime_workflow") and "external_runtime" not in tags:
        tags.append("external_runtime")
    if recipe_meta.get("batch_analysis_workflow") and "batch_analysis" not in tags:
        tags.append("batch_analysis")
    payload["tags"] = tags
    if recipe_meta.get("hosted_via_br_mcp_service"):
        payload["requires_runtime"] = "network"
    elif recipe_meta.get("primary_target"):
        payload["requires_runtime"] = recipe_meta["primary_target"]
    payload.update(_mcp_surface_metadata(spec.name))
    if _tool_prefers_local_execution(spec):
        payload["description"] = _prepend_agent_local_execution_warning(
            str(payload.get("description") or "")
        )
    return payload


def _resolve_recipe_context(
    tool_id: str,
) -> tuple[ToolSpec | None, dict[str, Any] | None]:
    workflow_entry = _workflow_catalog_entry(tool_id)
    if is_workflow_tool_id(tool_id) and _is_declared_workflow_id(tool_id):
        return _workflow_toolspec_card(tool_id, include_schema=True), workflow_entry
    spec = _get_registry().get_toolspec_by_name(tool_id)
    return spec, workflow_entry


def _recipe_suggested_command(recipe: dict[str, Any]) -> str | None:
    setup = [
        str(item).strip()
        for item in (recipe.get("setup_commands") or [])
        if str(item).strip()
    ]
    run_command = str(recipe.get("run_command") or "").strip()
    if not run_command:
        return None
    parts = setup + [run_command]
    return " && ".join(parts)


def _recipe_hint_payload(
    tool_id: str,
    params: dict[str, Any] | None = None,
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if spec is None and workflow_entry is None:
        spec, workflow_entry = _resolve_recipe_context(tool_id)

    metadata = resolve_recipe_metadata(
        tool_id, spec=spec, workflow_entry=workflow_entry
    )
    agent_guidance = agent_execution_metadata(
        metadata,
        requested_target=default_recipe_target(
            tool_id, spec=spec, workflow_entry=workflow_entry
        ),
        recipe_available=bool(metadata.get("supported_recipe_targets")),
    )
    supported_targets = metadata.get("supported_recipe_targets") or []
    if metadata.get("hosted_via_br_mcp_service"):
        return {
            "execution_recipe_available": False,
            "hosted_via_br_mcp_service": True,
            "execution_story_kind": metadata.get("execution_story_kind"),
            "execution_story": metadata.get("execution_story"),
            "supported_recipe_targets": list(supported_targets),
            **agent_guidance,
        }
    default_target = default_recipe_target(
        tool_id, spec=spec, workflow_entry=workflow_entry
    )
    if not supported_targets or not default_target:
        return agent_guidance

    hint: dict[str, Any] = {
        "execution_recipe_available": True,
        "supported_recipe_targets": list(supported_targets),
        **agent_guidance,
        "recipe_lookup": {
            "tool": "get_execution_recipe",
            "args": {
                "tool_id": tool_id,
                "params": dict(params or {}),
                "target_runtime": default_target,
            },
        },
    }
    try:
        recipe_resp = build_execution_recipe(
            tool_id,
            params=dict(params or {}),
            target_runtime=default_target,
            cluster_profile=DEFAULT_CLUSTER_PROFILE,
            spec=spec,
            workflow_entry=workflow_entry,
        )
    except Exception:
        return hint

    if recipe_resp.get("ok") is True:
        recipe = recipe_resp.get("recipe") if isinstance(recipe_resp, dict) else None
        if isinstance(recipe, dict):
            suggested = _recipe_suggested_command(recipe)
            if suggested:
                hint["suggested_command"] = suggested
    return hint


def _prepend_agent_local_execution_warning(description: str) -> str:
    description = str(description or "").strip()
    if AGENT_LOCAL_EXECUTION_WARNING in description:
        return description
    if not description:
        return AGENT_LOCAL_EXECUTION_WARNING
    return f"{AGENT_LOCAL_EXECUTION_WARNING} {description}"


def _tool_prefers_local_execution(spec: ToolSpec) -> bool:
    runtime = infer_requires_runtime(spec.requires_runtime, backend=spec.backend)
    if runtime not in {"python", "container"}:
        return False
    if (spec.kind or "").lower() == "kg":
        return False

    name = str(spec.name or "").lower()
    if any(
        token in name
        for token in (
            "client",
            "query",
            "search",
            "find",
            "list",
            "describe",
            "resolve",
        )
    ):
        return False
    return True


def _iter_workflow_input_placeholders(value: Any) -> list[tuple[str, str | None]]:
    matches: list[tuple[str, str | None]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            for match in _INPUT_PLACEHOLDER_RE.finditer(node):
                key = str(match.group(1) or "").strip()
                if not key:
                    continue
                matches.append((key, match.group(2)))
            return
        if isinstance(node, dict):
            for item in node.values():
                _walk(item)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(value)
    return matches


def _parse_placeholder_default(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?", value):
        try:
            return float(value)
        except ValueError:
            return value
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if (value.startswith("[") and value.endswith("]")) or (
        value.startswith("{") and value.endswith("}")
    ):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _infer_common_input_default(workflow_id: str, key: str) -> Any:
    if key == "output_dir":
        return f"/tmp/brain-researcher/{workflow_id}"
    if key in {"n_perm", "n_permutations"}:
        return 1000
    if key == "dry_run":
        return True
    if key == "strict":
        return False
    return _NO_DEFAULT


def _infer_schema_type(key: str, default: Any) -> str:
    if isinstance(default, bool):
        return "boolean"
    if isinstance(default, int) and not isinstance(default, bool):
        return "integer"
    if isinstance(default, float):
        return "number"
    if isinstance(default, list):
        return "array"
    if isinstance(default, dict):
        return "object"

    if key.startswith(("is_", "has_", "use_", "enable_", "allow_")) or key in {
        "dry_run",
        "strict",
        "standardize",
        "detrend",
    }:
        return "boolean"

    if key.startswith(("n_", "num_")) or key.endswith(
        ("_count", "_index", "_idx", "_k", "_splits", "_permutations", "_iters")
    ):
        return "integer"

    if key in {"t_r", "low_pass", "high_pass"} or key.endswith(
        ("_threshold", "_alpha", "_beta", "_gamma", "_ratio", "_radius", "_fwhm")
    ):
        return "number"

    if key.endswith(("_files", "_ids", "_coords", "_patterns")):
        return "array"

    return "string"


def _infer_workflow_input_params(
    workflow: dict[str, Any],
    workflow_id: str,
) -> dict[str, Any] | None:
    runtime = workflow.get("runtime")
    if not isinstance(runtime, dict):
        return None
    steps = runtime.get("steps")
    if not isinstance(steps, list):
        return None

    input_keys: set[str] = set()
    placeholder_defaults: dict[str, Any] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        for key, raw_default in _iter_workflow_input_placeholders(step.get("params")):
            input_keys.add(key)
            if key in placeholder_defaults or raw_default is None:
                continue
            placeholder_defaults[key] = _parse_placeholder_default(raw_default)

    if not input_keys:
        return None

    defaults: dict[str, Any] = {}
    for key in sorted(input_keys):
        if key in placeholder_defaults:
            defaults[key] = placeholder_defaults[key]
            continue
        heuristic = _infer_common_input_default(workflow_id, key)
        if heuristic is not _NO_DEFAULT:
            defaults[key] = heuristic

    properties: dict[str, Any] = {}
    required: list[str] = []
    for key in sorted(input_keys):
        default_value = defaults.get(key, _NO_DEFAULT)
        properties[key] = {
            "type": _infer_schema_type(
                key,
                None if default_value is _NO_DEFAULT else default_value,
            )
        }
        if key not in defaults:
            required.append(key)

    inferred: dict[str, Any] = {
        "schema": {"type": "object", "properties": properties},
    }
    if required:
        inferred["schema"]["required"] = required
    if defaults:
        inferred["defaults"] = defaults
    return inferred


def _format_jsonschema_error(err: Any) -> str:
    path = getattr(err, "absolute_path", None)
    if path:
        try:
            path_str = ".".join(str(p) for p in path)
        except Exception:
            path_str = "<path>"
    else:
        path_str = "<root>"
    msg = getattr(err, "message", None) or str(err)
    return f"{path_str}: {msg}"


def _lookup_pipeline_value(root: dict[str, Any], dotted: str) -> Any:
    cur: Any = root
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
            continue
        raise KeyError(dotted)
    return cur


def _resolve_pipeline_shorthand(
    ctx: dict[str, Any], step_id: str, field_path: str
) -> Any:
    normalized = str(field_path or "").strip(".")
    candidates = [
        f"steps.{step_id}.data.outputs.{normalized}",
        f"steps.{step_id}.data.{normalized}",
        f"steps.{step_id}.{normalized}",
    ]
    if normalized.startswith("outputs."):
        candidates.insert(0, f"steps.{step_id}.data.{normalized}")
    if normalized.startswith(("data.", "metadata.")) or normalized in {
        "status",
        "error",
    }:
        candidates.insert(0, f"steps.{step_id}.{normalized}")

    last_error: KeyError | None = None
    for candidate in candidates:
        try:
            return _lookup_pipeline_value(ctx, candidate)
        except KeyError as exc:
            last_error = exc
    raise KeyError(f"steps.{step_id}.{normalized}") from last_error


def _interpolate_pipeline_step_params(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        full_expr = re.fullmatch(r"\$\{([^}]+)\}", value)
        if full_expr and full_expr.group(1).startswith("steps."):
            return _lookup_pipeline_value(ctx, full_expr.group(1))

        full_shorthand = _PIPELINE_STEP_SHORTHAND_RE.fullmatch(value)
        if full_shorthand:
            return _resolve_pipeline_shorthand(
                ctx,
                step_id=full_shorthand.group(1),
                field_path=full_shorthand.group(2),
            )

        def _replace_step_expr(match: re.Match[str]) -> str:
            return str(_lookup_pipeline_value(ctx, match.group(1)))

        def _replace_step_shorthand(match: re.Match[str]) -> str:
            return str(
                _resolve_pipeline_shorthand(
                    ctx,
                    step_id=match.group(1),
                    field_path=match.group(2),
                )
            )

        if "${steps." in value:
            value = _PIPELINE_STEP_TOKEN_RE.sub(_replace_step_expr, value)
        if "{" in value and "}" in value:
            value = _PIPELINE_STEP_SHORTHAND_RE.sub(_replace_step_shorthand, value)
        return value
    if isinstance(value, dict):
        return {k: _interpolate_pipeline_step_params(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_pipeline_step_params(v, ctx) for v in value]
    return value


def _validate_tool_params(
    tool_id: str,
    spec: ToolSpec,
    params: dict[str, Any],
) -> list[dict[str, str]]:
    """Validate tool parameters against the ToolSpec JSON schema (best-effort)."""

    schema = spec.json_schema if isinstance(spec.json_schema, dict) else {}

    required: list[str] = []
    if isinstance(getattr(spec, "required", None), list):
        required = [str(k).strip() for k in (spec.required or []) if str(k).strip()]
    if not required and isinstance(schema, dict):
        required_raw = schema.get("required", []) or []
        if isinstance(required_raw, list):
            required = [str(k).strip() for k in required_raw if str(k).strip()]

    missing = [k for k in required if k not in params]
    if missing:
        return [
            {
                "level": "error",
                "code": "params_missing_required",
                "message": f"Missing required params for {tool_id}: {missing}",
            }
        ]

    if not schema:
        return []

    if jsonschema is None:
        return [
            {
                "level": "warn",
                "code": "schema_validation_unavailable",
                "message": "jsonschema not installed; skipped parameter validation",
            }
        ]

    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        errors = sorted(
            validator.iter_errors(params),
            key=lambda e: tuple(str(p) for p in getattr(e, "absolute_path", []) or []),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return [
            {
                "level": "warn",
                "code": "schema_validation_failed",
                "message": f"Failed to validate params for {tool_id}: {exc}",
            }
        ]

    issues: list[dict[str, str]] = []
    for err in errors[:20]:
        issues.append(
            {
                "level": "error",
                "code": "params_invalid",
                "message": f"Invalid params for {tool_id}: {_format_jsonschema_error(err)}",
            }
        )
    return issues


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return _truthy(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except Exception:
            value = default
    if min_value is not None and value < min_value:
        return min_value
    return value


def _parse_roots(raw: str | None) -> list[Path]:
    if not raw:
        return []
    roots: list[Path] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        roots.append(Path(part).expanduser().resolve())
    return roots


DEFAULT_ALLOWED_ROOTS = [
    (PROJECT_ROOT / "artifacts").resolve(),
    (PROJECT_ROOT / "data").resolve(),
    (PROJECT_ROOT / "tmp").resolve(),
]

ALLOWED_ROOTS = _parse_roots(os.getenv("BR_MCP_ALLOWED_ROOTS")) or DEFAULT_ALLOWED_ROOTS
# RUN_ROOT now lives in mcp/runstore.py (single source of truth). server.py
# reads it live via ``runstore.RUN_ROOT`` and re-exports the name through the
# module ``__getattr__`` at the bottom of this file, so external
# ``server.RUN_ROOT`` access keeps working. ``runstore.set_run_root()`` /
# ``monkeypatch.setattr(runstore, "RUN_ROOT", ...)`` is the authoritative way to
# redirect run storage.
from brain_researcher.services.mcp import runstore as _runstore  # noqa: E402

ALLOW_NETWORK = _truthy(os.getenv("BR_MCP_ALLOW_NETWORK"))
ALLOW_DANGEROUS = _truthy(os.getenv("BR_MCP_ALLOW_DANGEROUS"))
ENABLE_TOOL_EXECUTE = _truthy(os.getenv("BR_MCP_ENABLE_TOOL_EXECUTE"))
ENABLE_LATEX_COMPILE = _env_flag("BR_MCP_ENABLE_LATEX_COMPILE", False)
AGENT_MULTIAGENT_ENABLED = _env_flag("BR_AGENT_MULTIAGENT_ENABLED", False)
AGENT_CRITIC_PLAN_GATE = _env_flag("BR_AGENT_CRITIC_PLAN_GATE", False)
AGENT_CRITIC_TOOL_GATE = _env_flag("BR_AGENT_CRITIC_TOOL_GATE", False)
AGENT_RECOVERY_AGENT = _env_flag("BR_AGENT_RECOVERY_AGENT", False)
AGENT_CRITIC_FAIL_OPEN = _env_flag("BR_AGENT_CRITIC_FAIL_OPEN", True)
RM_LOGGING_ENABLED = _env_flag("BR_MCP_RM_LOGGING_ENABLED", False)
RM_LOGGING_POLICY = (
    os.getenv("BR_MCP_RM_LOGGING_POLICY") or "redact_raw_vault"
).strip() or "redact_raw_vault"
MAX_TEXT_BYTES = int(os.getenv("BR_MCP_MAX_TEXT_BYTES", "200000"))
MAX_BINARY_BYTES = int(os.getenv("BR_MCP_MAX_BINARY_BYTES", "5000000"))
STARTUP_STRICT_DEPENDENCIES = _env_flag("BR_MCP_STARTUP_STRICT_DEPENDENCIES", True)
DEPENDENCY_CHECK_TIMEOUT_S = _env_float("BR_MCP_DEPENDENCY_CHECK_TIMEOUT_S", 1.5)
AGENT_FALLBACK_ENABLED = _env_flag("BR_MCP_AGENT_FALLBACK_ENABLED", False)
AGENT_DELEGATED_EXECUTION_ENABLED = _env_flag(
    "BR_MCP_DELEGATE_EXECUTION_TO_AGENT", False
)


def _resolve_agent_api_url() -> str:
    return (
        os.getenv("BR_MCP_AGENT_API_URL")
        or os.getenv("BR_AGENT_URL")
        or os.getenv("AGENT_BASE_URL")
        or os.getenv("AGENT_URL")
        or os.getenv("AGENT_API_URL")
        or "http://localhost:8000"
    ).rstrip("/")


AGENT_API_URL = _resolve_agent_api_url()


def _parse_agent_fallback_paths(raw: str | None) -> list[str]:
    defaults = ["/tools/execute", "/tools/run"]
    if not raw:
        return defaults
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        if not value.startswith("/"):
            value = f"/{value}"
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out or defaults


AGENT_FALLBACK_PATHS = _parse_agent_fallback_paths(
    os.getenv("BR_MCP_AGENT_FALLBACK_PATHS")
)


def _parse_agent_delegation_path(raw: str | None) -> str:
    value = (raw or "/runs/execute_async").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value


AGENT_DELEGATION_PATH = _parse_agent_delegation_path(
    os.getenv("BR_MCP_AGENT_DELEGATION_PATH")
)


def _agent_fallback_endpoints() -> list[str]:
    endpoints: list[str] = []
    seen: set[str] = set()
    for path in AGENT_FALLBACK_PATHS:
        endpoint = f"{AGENT_API_URL}{path}"
        if endpoint in seen:
            continue
        seen.add(endpoint)
        endpoints.append(endpoint)
    if endpoints:
        return endpoints
    return [f"{AGENT_API_URL}/tools/execute"]


def _agent_delegation_endpoint() -> str:
    return f"{AGENT_API_URL}{AGENT_DELEGATION_PATH}"


def _agent_run_endpoint(run_id: str, suffix: str = "") -> str:
    normalized_suffix = suffix if suffix.startswith("/") or not suffix else f"/{suffix}"
    return f"{AGENT_API_URL}/runs/{run_id}{normalized_suffix}"


def _read_json_http_response(resp: Any) -> dict[str, Any]:
    raw_body = resp.read()
    if not raw_body:
        return {}
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _delegate_execution_to_agent(
    *,
    run_id: str,
    execution_type: str,
    tool_id: str | None = None,
    params: dict[str, Any] | None = None,
    work_dir: str | None = None,
    output_dir: str | None = None,
    plan: dict[str, Any] | None = None,
    origin: str = "mcp_delegation",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "execution_type": execution_type,
        "origin": origin,
    }
    if execution_type == "plan":
        payload["plan"] = plan or {}
    else:
        payload["tool_id"] = tool_id
        payload["params"] = params or {}
        if work_dir:
            payload["work_dir"] = work_dir
        if output_dir:
            payload["output_dir"] = output_dir

    req = urllib_request.Request(
        _agent_delegation_endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(
            req, timeout=max(1.0, AGENT_FALLBACK_TIMEOUT_MS / 1000.0)
        ) as resp:
            body = _read_json_http_response(resp)
            if body:
                body.setdefault("ok", True)
            return body or {"ok": False, "error": "invalid_agent_delegation_response"}
    except urllib_error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        return {
            "ok": False,
            "error": f"agent_delegation_http_{exc.code}",
            "detail": detail,
            "endpoint": _agent_delegation_endpoint(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"agent_delegation_unreachable:{type(exc).__name__}",
            "detail": str(exc),
            "endpoint": _agent_delegation_endpoint(),
        }


def _proxy_agent_run_payload(
    run_id: str,
    *,
    suffix: str = "",
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    req = urllib_request.Request(
        _agent_run_endpoint(run_id, suffix),
        data=(
            json.dumps(payload).encode("utf-8")
            if payload is not None and method != "GET"
            else None
        ),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib_request.urlopen(
            req, timeout=max(1.0, AGENT_FALLBACK_TIMEOUT_MS / 1000.0)
        ) as resp:
            body = _read_json_http_response(resp)
            if body:
                body.setdefault("ok", True)
            return body or {"ok": False, "error": "invalid_agent_run_response"}
    except urllib_error.HTTPError as exc:
        if exc.code == 404:
            return None
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        return {
            "ok": False,
            "error": f"agent_run_http_{exc.code}",
            "detail": detail,
            "endpoint": _agent_run_endpoint(run_id, suffix),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"agent_run_unreachable:{type(exc).__name__}",
            "detail": str(exc),
            "endpoint": _agent_run_endpoint(run_id, suffix),
        }


AGENT_FALLBACK_TIMEOUT_MS = _env_int(
    "BR_MCP_AGENT_FALLBACK_TIMEOUT_MS", 120000, min_value=1000
)
NEURODESK_CVMFS_CONTAINERS = (
    os.getenv("BR_NEURODESK_CVMFS_CONTAINERS")
    or "/cvmfs/neurodesk.ardc.edu.au/containers"
)
MCP_SELFTEST_ENABLED = _env_flag("BR_MCP_SELFTEST_ENABLED", True)
_MCP_SELFTEST_SCRIPT_PATH_RAW = (
    os.getenv("BR_MCP_SELFTEST_SCRIPT_PATH") or "scripts/mcp/selftest_probe.py"
).strip()
if _MCP_SELFTEST_SCRIPT_PATH_RAW:
    _mcp_selftest_script_path = Path(_MCP_SELFTEST_SCRIPT_PATH_RAW).expanduser()
    if not _mcp_selftest_script_path.is_absolute():
        _mcp_selftest_script_path = (
            PROJECT_ROOT / _MCP_SELFTEST_SCRIPT_PATH_RAW
        ).resolve()
else:
    _mcp_selftest_script_path = (
        PROJECT_ROOT / "scripts/mcp/selftest_probe.py"
    ).resolve()
MCP_SELFTEST_SCRIPT_PATH = _mcp_selftest_script_path

_LOOPBACK_POLICY_DOMAINS = ("localhost", "127.0.0.1", "::1")
_LOCAL_RUNTIME_MARKERS = {
    "local_runtime",
    "local_only",
    "loopback",
    "neo4j_local",
    "local_neo4j",
    "local_dependency",
}
_LOCAL_MCP_BRIDGE_TOOLS = {
    # In-process MCP bridge tools. These execute locally inside the current
    # Python process and should not be gated as external network calls.
    "mcp.server_info",
    "mcp.tool_search",
    "mcp.system_self_test",
    "mcp.sherlock_guide",
    "mcp.sherlock_slurm",
    # Test helpers are also local-only.
    "mcp.test_server_down",
    "mcp.test_timeout",
    "mcp.test_schema_mismatch",
}
_LOCAL_NETWORK_TOOL_DOMAIN_OVERRIDES: dict[str, tuple[str, ...]] = {
    # Neo4j pipeline lookup is intentionally local-runtime by default.
    "pipeline.search": _LOOPBACK_POLICY_DOMAINS,
    **dict.fromkeys(_LOCAL_MCP_BRIDGE_TOOLS, _LOOPBACK_POLICY_DOMAINS),
}


def _run_roots_for_read() -> list[Path]:
    return list(get_mcp_run_roots_for_read(_runstore.RUN_ROOT))


DEFAULT_REDACT_PATTERNS = (
    "token",
    "api_key",
    "authorization",
    "secret",
    "password",
    "cookie",
    "credential",
    "private_key",
)
DEFAULT_REDACT_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "session_token",
    "private_key",
    "client_secret",
    "bearer_token",
}


def _normalize_redaction_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _parse_redaction_key_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    out: set[str] = set()
    for part in raw.split(","):
        normalized = _normalize_redaction_key(part)
        if normalized:
            out.add(normalized)
    return out


REDACTION_ALLOWLIST = _parse_redaction_key_set(os.getenv("BR_MCP_REDACTION_ALLOWLIST"))
REDACTION_DENYLIST = (
    DEFAULT_REDACT_KEYS
    | _parse_redaction_key_set(os.getenv("BR_MCP_REDACTION_DENYLIST"))
) - REDACTION_ALLOWLIST
REDACTION_MASK = os.getenv("BR_MCP_REDACTION_MASK", "[REDACTED]")


def _should_redact_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = _normalize_redaction_key(key)
    if not normalized:
        return False
    if normalized in REDACTION_ALLOWLIST:
        return False
    if normalized in REDACTION_DENYLIST:
        return True
    return any(pattern in normalized for pattern in DEFAULT_REDACT_PATTERNS)


def _redact_for_logging(value: Any, *, key: str | None = None) -> Any:
    if _should_redact_key(key):
        return REDACTION_MASK
    if isinstance(value, dict):
        return {str(k): _redact_for_logging(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_for_logging(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_for_logging(item) for item in value]
    return value


def _parse_timeout(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _resolve_kg_read_timeout_s() -> float:
    configured = _parse_timeout(os.getenv("BR_MCP_KG_READ_TIMEOUT_S"))
    if configured is None:
        configured = 15.0
    # Keep query tools on a short leash so clients never sit on 120s holes.
    return max(1.0, min(float(configured), 15.0))


def _is_timeout_like_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError | FuturesTimeoutError):
        return True
    message = str(exc or "").strip().lower()
    if not message:
        return False
    return any(
        token in message
        for token in (
            "timed out",
            "timeout",
            "deadline exceeded",
            "query exceeded",
            "read timed out",
            "execution expired",
        )
    )


def _call_kg_query_with_timeout(
    fn: Any, *args: Any, timeout_s: float, **kwargs: Any
) -> Any:
    try:
        return fn(*args, timeout_s=timeout_s, **kwargs)
    except TypeError as exc:
        if "timeout_s" not in str(exc):
            raise
        return fn(*args, **kwargs)


def _normalize_execution_trace(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple):
        values = list(value)
    else:
        values = []
    trace: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in trace:
            trace.append(text)
    return trace


def _metadata_with_execution_trace(
    metadata: dict[str, Any] | None,
    *events: str,
    **extra: Any,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    trace = _normalize_execution_trace(merged.get("execution_trace"))
    for event in events:
        text = str(event or "").strip()
        if text and text not in trace:
            trace.append(text)
    if trace:
        merged["execution_trace"] = trace
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    return merged


def _call_execute_tool_executor(
    tool_id: str,
    params: dict[str, Any],
    *,
    work_dir: str,
    output_dir: str,
    preview: bool,
    allow_remap: bool,
) -> ToolResult:
    try:
        return execute_tool(
            tool_id,
            params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
            allow_remap=allow_remap,
        )
    except TypeError as exc:
        if "allow_remap" not in str(exc):
            raise
        return execute_tool(
            tool_id,
            params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
        )


def _call_preflight_tool_call(
    tool_id: str,
    params: dict[str, Any],
    *,
    allowlist: set[str] | None = None,
    step_id: str | None = None,
    allow_remap: bool,
) -> tuple[ToolSpec | None, list[dict[str, str]]]:
    try:
        return _preflight_tool_call(
            tool_id,
            params,
            allowlist=allowlist,
            step_id=step_id,
            allow_remap=allow_remap,
        )
    except TypeError as exc:
        if "allow_remap" not in str(exc):
            raise
        return _preflight_tool_call(
            tool_id,
            params,
            allowlist=allowlist,
            step_id=step_id,
        )


def _resolve_toolspec_for_preflight(
    tool_id: str, *, allow_remap: bool
) -> tuple[ToolSpec | None, dict[str, Any]]:
    resolver_info: dict[str, Any] = {
        "requested_tool_id": tool_id,
        "resolved_tool_id": tool_id,
        "remap_applied": False,
        "allow_remap": bool(allow_remap),
        "candidate_tool_ids": [],
    }

    if not allow_remap:
        return _get_toolspec_with_schema(tool_id), resolver_info

    reg = _get_registry()
    candidates = resolve_runtime_tool_ids(tool_id, include_self=True)
    resolver_info["candidate_tool_ids"] = list(candidates)
    unresolved_python_issue: tuple[ToolSpec, dict[str, Any]] | None = None
    for candidate_id in candidates:
        candidate_spec = reg.get_toolspec_by_name(candidate_id)
        if candidate_spec is None:
            continue
        candidate_spec = _enrich_toolspec_schema(candidate_spec.model_copy(deep=True))
        if str(candidate_spec.backend or "").lower() == "python":
            issue = audit_python_backend_configuration(candidate_spec)
            if issue is not None:
                if unresolved_python_issue is None:
                    unresolved_python_issue = (candidate_spec, issue)
                continue
        resolver_info["resolved_tool_id"] = candidate_id
        resolver_info["remap_applied"] = candidate_id != tool_id
        return candidate_spec, resolver_info

    if unresolved_python_issue is not None:
        spec, issue = unresolved_python_issue
        resolver_info["resolved_tool_id"] = spec.name
        resolver_info["python_issue"] = issue
    else:
        resolver_info["resolved_tool_id"] = None
    return None, resolver_info


def _build_kg_degraded_blocked_response(
    *,
    tool_name: str,
    query_time_s: float,
    degraded_reason: str,
    error: str,
) -> dict[str, Any]:
    execution_trace = ["kg_query_started"]
    if degraded_reason == "mcp_timeout":
        execution_trace.append("kg_timeout")
    execution_trace.append("kg_degraded_blocked")
    message = (
        f"{tool_name} produced a degraded result ({degraded_reason}) but degraded "
        "responses are disabled by default. Re-run with allow_degraded=True."
    )
    return {
        "ok": False,
        "error": error,
        "message": message,
        "degraded_result_available": True,
        "degraded_reason": degraded_reason,
        "query_time_s": round(max(0.0, float(query_time_s)), 3),
        "execution_trace": execution_trace,
    }


def _build_kg_timeout_degraded_response(
    *,
    tool_name: str,
    payload: dict[str, Any],
    query_time_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    warning = (
        f"{tool_name} timed out after {timeout_s:.1f}s; returning a degraded result."
    )
    return {
        "ok": True,
        **payload,
        "warnings": [warning],
        "completion_state": "degraded",
        "degraded_reason": "mcp_timeout",
        "query_time_s": round(max(0.0, float(query_time_s)), 3),
        "execution_trace": ["kg_query_started", "degraded_returned"],
    }


def _resolve_tool_timeout(spec: ToolSpec | None) -> float | None:
    if spec and spec.timeout_s:
        return float(spec.timeout_s)
    return _parse_timeout(os.getenv("BR_MCP_TOOL_TIMEOUT_S"))


def _resolve_timeout_cancel_grace() -> float:
    """Return the grace period (seconds) used after timeout terminate()."""

    return _parse_timeout(os.getenv("BR_MCP_TIMEOUT_CANCEL_GRACE_S")) or 1.0


def _resolve_timeout_kill_grace() -> float:
    """Return the grace period (seconds) used after SIGKILL fallback."""

    return _parse_timeout(os.getenv("BR_MCP_TIMEOUT_KILL_GRACE_S")) or 0.5


def _timeout_worker(
    result_channel: Any,
    *,
    tool_id: str,
    params: dict[str, Any],
    work_dir: str,
    output_dir: str,
    preview: bool,
    allow_remap: bool,
) -> None:
    """Execute a tool in an isolated worker process.

    Isolation lets the parent force-stop work on timeout instead of only
    cancelling a future that may already be running.
    """

    if os.name == "posix":
        try:
            os.setsid()
        except Exception:
            # Best-effort only; keep execution alive even if we cannot set pgid.
            pass

    try:
        # Ensure local-loopback network metadata is visible inside worker process.
        spec = _get_toolspec_with_schema(tool_id)
        if spec is not None:
            _prepare_spec_for_network_policy(spec, patch_catalog=True)
        result = _call_execute_tool_executor(
            tool_id,
            params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
            allow_remap=allow_remap,
        )
        result_channel.send({"ok": True, "result": result.model_dump()})
    except Exception as exc:  # pragma: no cover - defensive
        payload: dict[str, Any] = {
            "ok": False,
            "error": f"worker_exception:{type(exc).__name__}:{exc}",
        }
        policy_issues = getattr(exc, "issues", None)
        if isinstance(policy_issues, list):
            payload["error"] = "execution_policy_violation"
            payload["policy_issues"] = [
                issue for issue in policy_issues if isinstance(issue, dict)
            ]
        result_channel.send(payload)
    finally:
        try:
            result_channel.close()
        except Exception:
            pass


def _tool_result_from_worker_payload(
    payload: dict[str, Any], *, tool_id: str
) -> ToolResult:
    if payload.get("ok"):
        raw = payload.get("result")
        if isinstance(raw, dict):
            return ToolResult.model_validate(raw)
        return ToolResult(
            status="error",
            error="worker_result_invalid",
            data=None,
            metadata={"tool_id": tool_id},
        )
    err = str(payload.get("error") or "worker_execution_failed")
    data: dict[str, Any] | None = None
    metadata: dict[str, Any] = {"tool_id": tool_id}
    policy_issues = payload.get("policy_issues")
    if isinstance(policy_issues, list):
        normalized_policy_issues = [
            issue for issue in policy_issues if isinstance(issue, dict)
        ]
        if normalized_policy_issues:
            data = {"policy_issues": normalized_policy_issues}
            metadata["policy_issues"] = normalized_policy_issues
    return ToolResult(
        status="error",
        error=err,
        data=data,
        metadata=metadata,
    )


def _format_execution_error(result: dict[str, Any]) -> str | None:
    err_raw = result.get("error")
    if err_raw is None:
        return None
    err = str(err_raw)
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return err
    timeout_outcome = metadata.get("timeout_outcome")
    if timeout_outcome == "timed_out_stopped":
        return f"{err}; execution_stopped"
    if timeout_outcome == "timed_out_background":
        return f"{err}; execution_continues_in_background"
    return err


def _clone_jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value))
    except Exception:
        return value


def _critic_feedback_from_issues(
    issues: list[dict[str, Any]] | None,
    *,
    original_params: dict[str, Any] | None = None,
    current_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    relevant = [
        issue
        for issue in (issues or [])
        if str(issue.get("code") or "").startswith("multiagent_critic_")
    ]
    if not relevant:
        return None

    by_code = {str(issue.get("code") or ""): issue for issue in relevant}
    if "multiagent_critic_blocked" in by_code:
        issue = by_code["multiagent_critic_blocked"]
        return {
            "critic_verdict": "block",
            "critic_reason": str(
                issue.get("message") or "blocked_by_multiagent_critic"
            ),
            "revised_params": None,
            "recovery_suggestions": [
                "Revise the tool parameters before retrying execution.",
                "If the block is unexpected, inspect the multi-agent policy configuration.",
            ],
        }
    if "multiagent_critic_revise_unapplied" in by_code:
        issue = by_code["multiagent_critic_revise_unapplied"]
        return {
            "critic_verdict": "revise",
            "critic_reason": str(issue.get("message") or "critic_requested_revision"),
            "revised_params": None,
            "recovery_suggestions": [
                "Apply a manual parameter revision and re-run preflight.",
            ],
        }
    if "multiagent_critic_revised_params" in by_code:
        issue = by_code["multiagent_critic_revised_params"]
        revised_params = (
            _clone_jsonable(current_params)
            if isinstance(current_params, dict)
            else None
        )
        if isinstance(original_params, dict) and revised_params == original_params:
            revised_params = None
        return {
            "critic_verdict": "revise",
            "critic_reason": str(issue.get("message") or "critic_revised_params"),
            "revised_params": revised_params,
            "recovery_suggestions": [
                "Review the revised_params payload before execution.",
            ],
        }
    issue = by_code.get("multiagent_critic_failure", relevant[0])
    return {
        "critic_verdict": "error",
        "critic_reason": str(issue.get("message") or "critic_failed"),
        "revised_params": None,
        "recovery_suggestions": [
            "Retry with critic fail-open or inspect multi-agent router availability.",
        ],
    }


_FALLBACK_POLICY_ERROR_MARKERS = {
    "execution_policy_violation",
    "tool_not_allowlisted",
    "tool_execute_disabled",
    "network_blocked",
    "network_blocked_by_policy",
    "domain_not_allowed",
    "path_not_allowed",
    "params_invalid",
    "params_missing_required",
    "unknown_tool",
}


def _is_policy_style_error(error_text: str) -> bool:
    normalized = (error_text or "").strip().lower()
    if not normalized:
        return False
    if normalized in _FALLBACK_POLICY_ERROR_MARKERS:
        return True
    return any(marker in normalized for marker in _FALLBACK_POLICY_ERROR_MARKERS)


def _looks_like_runtime_env_failure(error_text: str) -> bool:
    normalized = (error_text or "").strip().lower()
    if not normalized:
        return False
    runtime_markers = (
        "apptainer",
        "singularity",
        "cvmfs",
        "mount path does not exist",
        "permission denied",
        "operation not permitted",
        "no such file or directory",
        "container",
        "failed to resolve python tool",
        "niwrap tool not found",
    )
    return any(marker in normalized for marker in runtime_markers)


def _should_attempt_agent_fallback(
    *,
    spec: ToolSpec | None,
    result: ToolResult,
    preview: bool,
) -> bool:
    if not AGENT_FALLBACK_ENABLED:
        return False
    if preview:
        return False
    if spec is None:
        return False
    if str(spec.backend or "").lower() != "niwrap":
        return False
    if str(result.status or "").lower() != "error":
        return False
    err = str(result.error or "")
    if _is_policy_style_error(err):
        return False
    # We follow local-then-forward for niwrap tools, but require either a clear
    # runtime signal or missing local runtime capabilities.
    runtime_missing = (
        not bool(shutil.which("apptainer") or shutil.which("singularity"))
        or not Path(NEURODESK_CVMFS_CONTAINERS).exists()
    )
    return runtime_missing or _looks_like_runtime_env_failure(err)


def _forward_tool_execute_to_agent(
    *,
    tool_id: str,
    params: dict[str, Any],
    work_dir: str,
    output_dir: str,
    preview: bool,
    fallback_reason: str,
) -> ToolResult:
    payload = {
        # Current endpoint contract (/tools/execute)
        "tool_id": tool_id,
        "params": params,
        # Backward-compat endpoint contract (/tools/run)
        "tool": tool_id,
        "args": params,
        "arguments": params,
        "work_dir": work_dir,
        "output_dir": output_dir,
        "preview": bool(preview),
        "origin": "mcp_fallback",
    }
    endpoints = _agent_fallback_endpoints()
    attempts: list[dict[str, Any]] = []

    for endpoint in endpoints:
        metadata_base = {
            "execution_mode": "agent_fallback",
            "forward_target": endpoint,
            "fallback_reason": fallback_reason,
            "attempted_endpoints": endpoints,
        }
        req = urllib_request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib_request.urlopen(
                req, timeout=max(1.0, AGENT_FALLBACK_TIMEOUT_MS / 1000.0)
            ) as resp:
                raw_body = resp.read()
                body: dict[str, Any] = {}
                if raw_body:
                    try:
                        body = json.loads(raw_body.decode("utf-8"))
                    except Exception:
                        body = {}

                result_payload = body.get("result")
                if isinstance(result_payload, dict):
                    parsed = ToolResult.model_validate(result_payload)
                else:
                    parsed = ToolResult(
                        status="error",
                        error="agent_fallback_invalid_payload",
                        data={
                            "agent_response": body,
                        },
                    )

                metadata = dict(parsed.metadata or {})
                metadata.update(metadata_base)
                if attempts:
                    metadata["attempt_errors"] = attempts
                policy_issues = body.get("policy_issues")
                if isinstance(policy_issues, list):
                    metadata["policy_issues"] = policy_issues

                # Invalid payload on this endpoint: try next endpoint if available.
                if (
                    str(parsed.error or "") == "agent_fallback_invalid_payload"
                    and endpoint != endpoints[-1]
                ):
                    attempts.append(
                        {
                            "endpoint": endpoint,
                            "error": "agent_fallback_invalid_payload",
                        }
                    )
                    continue

                return parsed.model_copy(update={"metadata": metadata})
        except urllib_error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                detail = ""
            attempts.append(
                {
                    "endpoint": endpoint,
                    "error": f"agent_fallback_http_{exc.code}",
                    "detail": detail,
                }
            )
            continue
        except Exception as exc:
            attempts.append(
                {
                    "endpoint": endpoint,
                    "error": f"agent_fallback_unreachable:{type(exc).__name__}",
                    "detail": str(exc),
                }
            )
            continue

    last = attempts[-1] if attempts else {}
    return ToolResult(
        status="error",
        error=str(last.get("error") or "agent_fallback_failed"),
        data={
            "detail": last.get("detail"),
            "attempt_errors": attempts,
        },
        metadata={
            "execution_mode": "agent_fallback",
            "forward_target": str(last.get("endpoint") or AGENT_API_URL),
            "fallback_reason": fallback_reason,
            "attempted_endpoints": endpoints,
            "attempt_errors": attempts,
        },
    )


def _extract_policy_issues_from_result(
    result: dict[str, Any],
    *,
    step_id: str | None = None,
) -> list[dict[str, Any]]:
    """Collect execution policy issues from a tool result payload."""

    out: list[dict[str, Any]] = []
    data = result.get("data")
    if isinstance(data, dict):
        issues = data.get("policy_issues")
        if isinstance(issues, list):
            out.extend([i for i in issues if isinstance(i, dict)])

    root_issues = result.get("policy_issues")
    if isinstance(root_issues, list):
        out.extend([i for i in root_issues if isinstance(i, dict)])

    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        issues = metadata.get("policy_issues")
        if isinstance(issues, list):
            out.extend([i for i in issues if isinstance(i, dict)])

    if (
        not out
        and str(result.get("error") or "").strip() == "execution_policy_violation"
    ):
        out.append(
            {
                "level": "error",
                "code": "execution_policy_violation",
                "message": "Execution blocked by policy",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in out:
        normalized = dict(issue)
        if step_id and not normalized.get("step_id"):
            normalized["step_id"] = step_id
        key = json.dumps(normalized, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


_POLICY_PREFLIGHT_CODES = {
    "dangerous_tool_blocked",
    "missing_required_secrets",
    "network_blocked",
    "network_blocked_by_policy",
    "domain_not_allowed",
    "path_not_allowed",
    "workspace_path_violation",
    "tool_not_allowlisted",
    "tool_execute_disabled",
    "execution_policy_violation",
}


def _is_policy_issue_code(code: str | None) -> bool:
    normalized = str(code or "").strip().lower()
    if not normalized:
        return False
    if normalized in _POLICY_PREFLIGHT_CODES:
        return True
    if "policy" in normalized:
        return True
    if normalized.startswith("multiagent_critic_"):
        return True
    if normalized.startswith("network_"):
        return True
    return False


def _extract_policy_issues_from_issue_list(
    issues: list[dict[str, Any]] | None,
    *,
    step_id: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(issues, list):
        return []
    out: list[dict[str, Any]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not _is_policy_issue_code(code):
            message = str(item.get("message") or "").lower()
            has_policy_key = any("policy" in str(k).lower() for k in item.keys())
            if "policy" not in message and not has_policy_key:
                continue
        normalized = dict(item)
        if step_id and not normalized.get("step_id"):
            normalized["step_id"] = step_id
        out.append(normalized)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in out:
        key = json.dumps(issue, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _policy_issues_for_step(
    policy_issues: list[dict[str, Any]],
    *,
    step_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(issue)
        for issue in policy_issues
        if isinstance(issue, dict) and str(issue.get("step_id") or "") == step_id
    ]


def _spawn_timeout_worker(
    *,
    tool_id: str,
    params: dict[str, Any],
    work_dir: str,
    output_dir: str,
    preview: bool,
    allow_remap: bool,
) -> tuple[Any, Any]:
    # Prefer fork when available so local monkeypatch-based tests stay deterministic.
    start_methods = mp.get_all_start_methods()
    if "fork" in start_methods:
        ctx = mp.get_context("fork")
    else:
        ctx = mp.get_context()
    result_reader, result_writer = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_timeout_worker,
        kwargs={
            "result_channel": result_writer,
            "tool_id": tool_id,
            "params": params,
            "work_dir": work_dir,
            "output_dir": output_dir,
            "preview": preview,
            "allow_remap": allow_remap,
        },
    )
    proc.start()
    try:
        result_writer.close()
    except Exception:
        pass
    return proc, result_reader


def _receive_timeout_worker_payload(result_channel: Any, *, timeout_s: float) -> Any:
    if hasattr(result_channel, "poll") and hasattr(result_channel, "recv"):
        if not result_channel.poll(timeout_s):
            raise queue.Empty
        return result_channel.recv()
    return result_channel.get(timeout=timeout_s)


def _close_timeout_worker_channel(result_channel: Any) -> None:
    if result_channel is None:
        return
    try:
        result_channel.close()
    except Exception:
        pass
    try:
        result_channel.join_thread()
    except Exception:
        pass


def _stop_timeout_worker(
    proc: Any,
    *,
    cancel_grace_s: float,
    kill_grace_s: float,
) -> tuple[bool, str]:
    """Best-effort stop for timeout worker and its subprocesses.

    Returns:
        stopped: True when the worker process is no longer alive.
        termination: Short code describing which signal path was used.
    """

    termination = "terminate"
    pid = getattr(proc, "pid", None)

    # First pass: graceful terminate.
    if os.name == "posix" and isinstance(pid, int):
        try:
            # Worker calls setsid(), so PID also identifies a process group.
            os.killpg(pid, signal.SIGTERM)
            termination = "terminate_pg"
        except Exception:
            try:
                proc.terminate()
                termination = "terminate"
            except Exception:
                termination = "terminate_failed"
    else:
        try:
            proc.terminate()
            termination = "terminate"
        except Exception:
            termination = "terminate_failed"

    proc.join(timeout=cancel_grace_s)

    # Second pass: hard kill if still alive.
    if proc.is_alive():
        if os.name == "posix" and isinstance(pid, int):
            try:
                os.killpg(pid, signal.SIGKILL)
                termination = "kill_pg"
            except Exception:
                try:
                    os.kill(pid, signal.SIGKILL)
                    termination = "kill"
                except Exception:
                    try:
                        proc.kill()
                        termination = "kill_method"
                    except Exception:
                        termination = "kill_failed"
        else:
            try:
                proc.kill()
                termination = "kill"
            except Exception:
                try:
                    proc.terminate()
                    termination = "kill_fallback_terminate"
                except Exception:
                    termination = "kill_failed"

        proc.join(timeout=kill_grace_s)

    return (not proc.is_alive(), termination)


def _execute_tool_with_timeout(
    *,
    tool_id: str,
    params: dict[str, Any],
    work_dir: str,
    output_dir: str,
    preview: bool,
    spec: ToolSpec | None = None,
    allow_remap: bool = False,
    allow_fallback: bool = False,
) -> ToolResult:
    if spec is not None:
        spec = _prepare_spec_for_network_policy(spec, patch_catalog=True)

    remap_allowed = bool(allow_remap) and not bool(preview)
    fallback_allowed = bool(allow_fallback) and not bool(preview)
    lookup_event = "remap_lookup" if remap_allowed else "direct_lookup"

    def _tag_local_result(local_result: ToolResult, *events: str) -> ToolResult:
        local_result.metadata = _metadata_with_execution_trace(
            local_result.metadata,
            lookup_event,
            *events,
            execution_mode=str(
                (local_result.metadata or {}).get("execution_mode") or "direct"
            ),
        )
        return local_result

    def _with_agent_fallback(local_result: ToolResult) -> ToolResult:
        local_result = _tag_local_result(local_result)
        if not fallback_allowed:
            return local_result
        if not _should_attempt_agent_fallback(
            spec=spec,
            result=local_result,
            preview=preview,
        ):
            return local_result

        fallback_reason = str(local_result.error or "local_execution_failed")
        forwarded = _forward_tool_execute_to_agent(
            tool_id=tool_id,
            params=params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
            fallback_reason=fallback_reason,
        )
        if str(forwarded.status or "").lower() == "success":
            forwarded.metadata = _metadata_with_execution_trace(
                forwarded.metadata,
                *_normalize_execution_trace(
                    (local_result.metadata or {}).get("execution_trace")
                ),
                "fallback_attempted",
                "fallback_succeeded",
                execution_mode="agent_fallback",
                fallback_reason=fallback_reason,
            )
            return forwarded

        merged_metadata = _metadata_with_execution_trace(
            local_result.metadata,
            "fallback_attempted",
            "fallback_failed",
            execution_mode="agent_fallback_failed",
            forward_target=(
                (forwarded.metadata or {}).get("forward_target")
                if isinstance(forwarded.metadata, dict)
                else f"{AGENT_API_URL}/tools/execute"
            ),
            fallback_reason=fallback_reason,
            agent_fallback_error=forwarded.error,
            agent_fallback_data=forwarded.data,
        )
        if isinstance(forwarded.metadata, dict):
            merged_metadata["agent_fallback_metadata"] = forwarded.metadata
        return local_result.model_copy(update={"metadata": merged_metadata})

    timeout_s = _resolve_tool_timeout(spec)
    if not timeout_s:
        local_result = _call_execute_tool_executor(
            tool_id,
            params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
            allow_remap=remap_allowed,
        )
        local_result = _tag_local_result(local_result, "local_execution")
        return _with_agent_fallback(local_result)

    cancel_grace_s = _resolve_timeout_cancel_grace()
    kill_grace_s = _resolve_timeout_kill_grace()
    proc = None
    result_channel = None
    try:
        proc, result_channel = _spawn_timeout_worker(
            tool_id=tool_id,
            params=params,
            work_dir=work_dir,
            output_dir=output_dir,
            preview=preview,
            allow_remap=remap_allowed,
        )
        proc.join(timeout=timeout_s)
        if proc.is_alive():
            logger.warning("Tool %s timed out after %.1fs", tool_id, timeout_s)
            stopped, termination = _stop_timeout_worker(
                proc,
                cancel_grace_s=cancel_grace_s,
                kill_grace_s=kill_grace_s,
            )
            timeout_outcome = "timed_out_stopped" if stopped else "timed_out_background"
            local_result = ToolResult(
                status="error",
                error=f"tool_timeout_after_{timeout_s}s",
                data=None,
                metadata=_metadata_with_execution_trace(
                    {"tool_id": tool_id, "timeout_s": timeout_s},
                    lookup_event,
                    "local_timeout",
                    execution_mode="direct",
                    timeout_outcome=timeout_outcome,
                    termination=termination,
                    cancel_grace_s=cancel_grace_s,
                    kill_grace_s=kill_grace_s,
                ),
            )
            return _with_agent_fallback(local_result)
        if result_channel is None:
            local_result = ToolResult(
                status="error",
                error="worker_result_missing",
                data=None,
                metadata=_metadata_with_execution_trace(
                    {"tool_id": tool_id, "timeout_s": timeout_s},
                    lookup_event,
                    "worker_result_missing",
                    execution_mode="direct",
                ),
            )
            return _with_agent_fallback(local_result)
        try:
            payload = _receive_timeout_worker_payload(result_channel, timeout_s=1.0)
        except queue.Empty:
            local_result = ToolResult(
                status="error",
                error="worker_result_missing",
                data=None,
                metadata=_metadata_with_execution_trace(
                    {"tool_id": tool_id, "timeout_s": timeout_s},
                    lookup_event,
                    "worker_result_missing",
                    execution_mode="direct",
                ),
            )
            return _with_agent_fallback(local_result)
        if isinstance(payload, dict):
            local_result = _tool_result_from_worker_payload(payload, tool_id=tool_id)
            local_result = _tag_local_result(local_result, "local_execution")
            return _with_agent_fallback(local_result)
        local_result = ToolResult(
            status="error",
            error="worker_result_invalid",
            data=None,
            metadata=_metadata_with_execution_trace(
                {"tool_id": tool_id, "timeout_s": timeout_s},
                lookup_event,
                "worker_result_invalid",
                execution_mode="direct",
            ),
        )
        return _with_agent_fallback(local_result)
    except FuturesTimeoutError:
        # Defensive compatibility branch if a nested call still surfaces this type.
        logger.warning("Tool %s timed out after %.1fs", tool_id, timeout_s)
        local_result = ToolResult(
            status="error",
            error=f"tool_timeout_after_{timeout_s}s",
            data=None,
            metadata=_metadata_with_execution_trace(
                {"tool_id": tool_id, "timeout_s": timeout_s},
                lookup_event,
                "local_timeout",
                execution_mode="direct",
            ),
        )
        return _with_agent_fallback(local_result)
    finally:
        _close_timeout_worker_channel(result_channel)
        if proc is not None and proc.is_alive():
            try:
                _stop_timeout_worker(proc, cancel_grace_s=0.1, kill_grace_s=0.1)
            except Exception:
                pass


# Network-mode auth (optional). When set, HTTP transports require
# `Authorization: Bearer <token>`.
AUTH_TOKEN = (os.getenv("BR_MCP_AUTH_TOKEN") or "").strip()
AUTH_MODE = (os.getenv("BR_MCP_AUTH_MODE") or "auto").strip().lower()
TOKEN_PEPPER_RAW = (os.getenv("BR_MCP_TOKEN_PEPPER") or "").strip()
TOKEN_PEPPER_VERSION = (
    os.getenv("BR_MCP_TOKEN_PEPPER_VERSION") or "v1"
).strip() or "v1"
AUTH_TOKENS_JSON = (os.getenv("BR_MCP_AUTH_TOKENS_JSON") or "").strip()
MCP_TOKEN_LAST_USED_INTERVAL_SECONDS = max(
    10, int(os.getenv("BR_MCP_LAST_USED_WRITE_INTERVAL_SECONDS", "300"))
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JWT_SECRET_KEY = (
    os.getenv("JWT_SECRET_KEY") or os.getenv("NEXTAUTH_SECRET") or ""
).strip()
SUPABASE_URL = (
    os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or ""
).strip()
SUPABASE_JWKS_URL = (os.getenv("SUPABASE_JWKS_URL") or "").strip()
SUPABASE_JWT_ISSUER = (os.getenv("SUPABASE_JWT_ISSUER") or "").strip()
SUPABASE_JWT_AUDIENCE = (os.getenv("SUPABASE_JWT_AUDIENCE") or "").strip()
JWKS_URL = (
    os.getenv("BR_MCP_JWKS_URL")
    or SUPABASE_JWKS_URL
    or (f"{SUPABASE_URL}/auth/v1/keys" if SUPABASE_URL else "")
).strip()
JWT_ISSUER = (
    os.getenv("BR_MCP_JWT_ISSUER")
    or SUPABASE_JWT_ISSUER
    or (f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else "")
).strip()
JWT_AUDIENCE = (os.getenv("BR_MCP_JWT_AUDIENCE") or SUPABASE_JWT_AUDIENCE or "").strip()
JWT_AUDIENCES = [a.strip() for a in JWT_AUDIENCE.split(",") if a.strip()]
JWT_ALGORITHMS_RAW = (os.getenv("BR_MCP_JWT_ALGORITHMS") or "").strip()
JWKS_CACHE_TTL_SECONDS = int(os.getenv("BR_MCP_JWKS_CACHE_TTL_SECONDS", "300"))
_AUTO_AUTH_FAIL_CLOSED_WARNED = False

# Network transport selection:
# - stdio: local CLI default
# - sse / streamable-http: run an HTTP server (uvicorn) for in-cluster usage
DEFAULT_TRANSPORT = os.getenv("BR_MCP_TRANSPORT", "stdio").strip().lower()
HOST = os.getenv("BR_MCP_HOST", "0.0.0.0").strip()
PORT = int(os.getenv("BR_MCP_PORT", "7000"))
MOUNT_PATH = os.getenv("BR_MCP_MOUNT_PATH", "/").strip() or "/"
MCP_SETUP_PATH = (
    os.getenv("BR_MCP_SETUP_PATH") or "/mcp/setup"
).strip() or "/mcp/setup"
STATELESS_HTTP = _env_flag("BR_MCP_STATELESS_HTTP", False)
SESSION_BOOTSTRAP_ENABLED = _env_flag("BR_MCP_SESSION_BOOTSTRAP_ENABLED", True)
SERIALIZE_TOOLS_CALL = _env_flag("BR_MCP_SERIALIZE_TOOLS_CALL", False)
SESSION_BOOTSTRAP_CACHE_TTL_SECONDS = max(
    60, int(os.getenv("BR_MCP_SESSION_BOOTSTRAP_CACHE_TTL_SECONDS", "900"))
)
SESSION_BOOTSTRAP_CACHE_MAX = max(
    1, int(os.getenv("BR_MCP_SESSION_BOOTSTRAP_CACHE_MAX", "4096"))
)
SESSION_BOOTSTRAP_MAX_BODY_BYTES = max(
    256, int(os.getenv("BR_MCP_SESSION_BOOTSTRAP_MAX_BODY_BYTES", "16384"))
)
SESSION_BOOTSTRAP_PRIME_TIMEOUT_SECONDS = (
    _parse_timeout(os.getenv("BR_MCP_SESSION_BOOTSTRAP_PRIME_TIMEOUT_SECONDS")) or 1.5
)

_SESSION_BOOTSTRAP_CACHE: dict[str, tuple[str, float]] = {}
_SESSION_BOOTSTRAP_LOCK = threading.Lock()
_SESSION_BOOTSTRAP_INIT_CACHE: dict[str, float] = {}
_SESSION_BOOTSTRAP_INIT_LOCK = threading.Lock()
_TOOLS_CALL_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}
_TOOLS_CALL_LOCKS_LOCK = threading.Lock()
SESSION_BOOTSTRAP_INIT_CACHE_TTL_SECONDS = max(
    60, int(os.getenv("BR_MCP_SESSION_INIT_CACHE_TTL_SECONDS", "3600"))
)


def _parse_csv_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    values: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.add(part)
    return values


def _session_bootstrap_cache_prune(now: float) -> None:
    expired_keys = [
        key
        for key, (_sid, seen_at) in _SESSION_BOOTSTRAP_CACHE.items()
        if now - seen_at > float(SESSION_BOOTSTRAP_CACHE_TTL_SECONDS)
    ]
    for key in expired_keys:
        _SESSION_BOOTSTRAP_CACHE.pop(key, None)
    if len(_SESSION_BOOTSTRAP_CACHE) <= SESSION_BOOTSTRAP_CACHE_MAX:
        return
    overflow = len(_SESSION_BOOTSTRAP_CACHE) - SESSION_BOOTSTRAP_CACHE_MAX
    oldest = sorted(_SESSION_BOOTSTRAP_CACHE.items(), key=lambda item: item[1][1])[
        :overflow
    ]
    for key, _ in oldest:
        _SESSION_BOOTSTRAP_CACHE.pop(key, None)


def _session_bootstrap_cache_get(key: str) -> str | None:
    now = time.time()
    with _SESSION_BOOTSTRAP_LOCK:
        _session_bootstrap_cache_prune(now)
        entry = _SESSION_BOOTSTRAP_CACHE.get(key)
        if not entry:
            return None
        session_id, _seen_at = entry
        _SESSION_BOOTSTRAP_CACHE[key] = (session_id, now)
        return session_id


def _session_bootstrap_cache_put(key: str, session_id: str) -> None:
    now = time.time()
    with _SESSION_BOOTSTRAP_LOCK:
        _session_bootstrap_cache_prune(now)
        _SESSION_BOOTSTRAP_CACHE[key] = (session_id, now)


def _session_bootstrap_init_prune(now: float) -> None:
    expired_sessions = [
        sid
        for sid, seen_at in _SESSION_BOOTSTRAP_INIT_CACHE.items()
        if now - seen_at > float(SESSION_BOOTSTRAP_INIT_CACHE_TTL_SECONDS)
    ]
    for sid in expired_sessions:
        _SESSION_BOOTSTRAP_INIT_CACHE.pop(sid, None)


def _session_bootstrap_init_has(session_id: str) -> bool:
    now = time.time()
    with _SESSION_BOOTSTRAP_INIT_LOCK:
        _session_bootstrap_init_prune(now)
        seen_at = _SESSION_BOOTSTRAP_INIT_CACHE.get(session_id)
        if seen_at is None:
            return False
        _SESSION_BOOTSTRAP_INIT_CACHE[session_id] = now
        return True


def _session_bootstrap_init_put(session_id: str) -> None:
    now = time.time()
    with _SESSION_BOOTSTRAP_INIT_LOCK:
        _session_bootstrap_init_prune(now)
        _SESSION_BOOTSTRAP_INIT_CACHE[session_id] = now


def _tools_call_lock_key(session_key: str) -> tuple[int, str]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return (0, session_key)
    return (id(loop), session_key)


def _get_tools_call_lock(session_key: str) -> asyncio.Lock:
    key = _tools_call_lock_key(session_key)
    with _TOOLS_CALL_LOCKS_LOCK:
        lock = _TOOLS_CALL_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _TOOLS_CALL_LOCKS[key] = lock
        return lock


TOOL_EXECUTE_ALLOWLIST = _parse_csv_set(os.getenv("BR_MCP_TOOL_EXECUTE_ALLOWLIST"))

ALLOWED_ORIGINS = _parse_csv_set(os.getenv("BR_MCP_ALLOWED_ORIGINS"))
ALLOWED_HOSTS = _parse_csv_set(os.getenv("BR_MCP_ALLOWED_HOSTS"))


def _parse_algorithms(raw: str) -> set[str]:
    if not raw:
        return set()
    values: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.add(part.upper())
    return values


JWT_ALGORITHMS = _parse_algorithms(JWT_ALGORITHMS_RAW)

_JWKS_CACHE_LOCK = threading.Lock()
_JWKS_CACHE_FETCHED_AT = 0.0
_JWKS_CACHE_KEYS_BY_KID: dict[str, dict[str, Any]] = {}


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class ApiKeyRecord:
    user_id: str
    digest: str
    enabled: bool = True
    expires_at: datetime | None = None
    pepper_version: str | None = None


def _parse_expiry(raw: str | None) -> datetime | None:
    return parse_iso_datetime(raw)


def _load_auth_tokens(raw: str) -> dict[str, ApiKeyRecord]:
    value = (raw or "").strip()
    if not value:
        return {}

    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("BR_MCP_AUTH_TOKENS_JSON must be valid JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("BR_MCP_AUTH_TOKENS_JSON must be a JSON object")

    records: dict[str, ApiKeyRecord] = {}
    for key_id, record_raw in data.items():
        kid = str(key_id).strip()
        if not kid:
            raise ValueError("BR_MCP_AUTH_TOKENS_JSON contains empty key id")
        if not isinstance(record_raw, dict):
            raise ValueError(f"record for key id {kid!r} must be an object")

        user_id = str(record_raw.get("user_id") or "").strip()
        digest = str(record_raw.get("digest") or "").strip().lower()
        enabled_raw = record_raw.get("enabled", True)
        expires_at = _parse_expiry(record_raw.get("expires_at"))
        pepper_version = str(record_raw.get("pepper_version") or "").strip() or None

        if not user_id:
            raise ValueError(f"record for key id {kid!r} has empty user_id")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(
                f"record for key id {kid!r} has invalid digest; expected 64-char hex"
            )
        if not isinstance(enabled_raw, bool):
            raise ValueError(f"record for key id {kid!r} has non-boolean enabled flag")

        records[kid] = ApiKeyRecord(
            user_id=user_id,
            digest=digest,
            enabled=enabled_raw,
            expires_at=expires_at,
            pepper_version=pepper_version,
        )
    return records


TOKEN_PEPPER = load_pepper(TOKEN_PEPPER_RAW)
AUTH_TOKENS_BY_KID = _load_auth_tokens(AUTH_TOKENS_JSON)
if AUTH_TOKENS_BY_KID and TOKEN_PEPPER is None:
    raise ValueError(
        "BR_MCP_TOKEN_PEPPER is required when BR_MCP_AUTH_TOKENS_JSON is set"
    )

_TOKEN_REDIS_CLIENT = None
_TOKEN_REDIS_LAST_CONNECT_ATTEMPT = 0.0
_TOKEN_REDIS_CONNECT_ERROR_LOGGED = False


def _to_bool(raw: Any, default: bool = True) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _token_redis_retry_interval_seconds() -> float:
    raw = os.getenv("BR_MCP_TOKEN_REDIS_RETRY_SECONDS", "5")
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 5.0


def _mark_token_redis_unavailable(exc: Exception, context: str) -> None:
    global _TOKEN_REDIS_CLIENT
    global _TOKEN_REDIS_LAST_CONNECT_ATTEMPT
    global _TOKEN_REDIS_CONNECT_ERROR_LOGGED
    _TOKEN_REDIS_CLIENT = None
    _TOKEN_REDIS_LAST_CONNECT_ATTEMPT = time.monotonic()
    _TOKEN_REDIS_CONNECT_ERROR_LOGGED = True
    logger.warning("MCP token Redis %s (%s)", context, exc)


def _get_token_redis():
    global _TOKEN_REDIS_CLIENT
    global _TOKEN_REDIS_LAST_CONNECT_ATTEMPT
    global _TOKEN_REDIS_CONNECT_ERROR_LOGGED

    if _TOKEN_REDIS_CLIENT is not None:
        return _TOKEN_REDIS_CLIENT

    now = time.monotonic()
    if now - _TOKEN_REDIS_LAST_CONNECT_ATTEMPT < _token_redis_retry_interval_seconds():
        return None
    _TOKEN_REDIS_LAST_CONNECT_ATTEMPT = now

    try:
        import redis

        client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        client.ping()
        _TOKEN_REDIS_CLIENT = client
        _TOKEN_REDIS_CONNECT_ERROR_LOGGED = False
        logger.info("MCP token Redis connected at %s", REDIS_URL)
    except Exception as exc:
        if not _TOKEN_REDIS_CONNECT_ERROR_LOGGED:
            logger.warning("MCP token Redis unavailable (%s)", exc)
            _TOKEN_REDIS_CONNECT_ERROR_LOGGED = True
        _TOKEN_REDIS_CLIENT = None
    return _TOKEN_REDIS_CLIENT


def _maybe_touch_redis_token_last_used(
    redis_client: Any,
    key_id: str,
    current_last_used: str | None,
) -> None:
    now = utc_now()
    should_write = True
    if current_last_used:
        try:
            last_dt = parse_iso_datetime(current_last_used)
        except ValueError:
            last_dt = None
        if last_dt is not None and now - last_dt < timedelta(
            seconds=MCP_TOKEN_LAST_USED_INTERVAL_SECONDS
        ):
            should_write = False
    if should_write:
        try:
            redis_client.hset(
                redis_token_key(key_id),
                mapping={"last_used_at": isoformat_z(now)},
            )
        except Exception as exc:
            _mark_token_redis_unavailable(exc, "last_used update failed")


def _verify_against_redis_token_record(
    key_id: str, secret: str
) -> tuple[str, str | None]:
    if TOKEN_PEPPER is None:
        return "skip", None

    redis_client = _get_token_redis()
    if redis_client is None:
        return "redis_unavailable", None

    try:
        record = redis_client.hgetall(redis_token_key(key_id))
    except Exception as exc:
        _mark_token_redis_unavailable(exc, "lookup failed")
        return "redis_unavailable", None

    if not record:
        return "not_found", None

    if not _to_bool(record.get("enabled"), default=True):
        return "found", None

    user_id = str(record.get("user_id") or "").strip()
    if not user_id:
        return "found", None

    try:
        expires_at = parse_iso_datetime(record.get("expires_at"))
    except ValueError:
        return "found", None
    if expires_at is not None and utc_now() >= expires_at:
        return "found", None

    pepper_version = str(record.get("pepper_version") or "").strip()
    if pepper_version and pepper_version != TOKEN_PEPPER_VERSION:
        return "found", None

    expected_digest = str(record.get("digest") or "").strip().lower()
    digest = compute_digest(TOKEN_PEPPER, secret)
    if not hmac.compare_digest(digest, expected_digest):
        return "found", None

    current_last_used = str(record.get("last_used_at") or "").strip() or None
    _maybe_touch_redis_token_last_used(redis_client, key_id, current_last_used)
    return "found", user_id


def _verify_against_static_tokens(key_id: str, secret: str) -> str | None:
    if TOKEN_PEPPER is None or not AUTH_TOKENS_BY_KID:
        return None
    record = AUTH_TOKENS_BY_KID.get(key_id)
    if record is None or not record.enabled:
        return None

    if record.expires_at is not None and utc_now() >= record.expires_at:
        return None
    if record.pepper_version and record.pepper_version != TOKEN_PEPPER_VERSION:
        return None

    digest = compute_digest(TOKEN_PEPPER, secret)
    if not hmac.compare_digest(digest, record.digest):
        return None
    return record.user_id


def _extract_bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    auth_header = auth_header.strip()
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _resolve_auth_mode() -> str:
    global _AUTO_AUTH_FAIL_CLOSED_WARNED
    mode = (AUTH_MODE or "auto").strip().lower()
    if mode in {"none", "token", "jwt", "token_or_jwt"}:
        return mode
    if mode != "auto":
        logger.warning("Unknown BR_MCP_AUTH_MODE=%r; defaulting to 'auto'", mode)

    has_token = bool(AUTH_TOKEN or TOKEN_PEPPER)
    has_jwt = bool(JWKS_URL or JWT_SECRET_KEY)
    if has_token and has_jwt:
        return "token_or_jwt"
    if has_token:
        return "token"
    if has_jwt:
        return "jwt"

    # Fail closed for HTTP transports when auth mode is auto but no provider
    # is configured. Operators can explicitly set BR_MCP_AUTH_MODE=none for
    # trusted local-only deployments.
    if not _AUTO_AUTH_FAIL_CLOSED_WARNED:
        logger.warning(
            "BR_MCP_AUTH_MODE=auto without token/jwt config now defaults to "
            "token mode (deny-by-default). Set BR_MCP_AUTH_MODE=none to "
            "allow unauthenticated access explicitly."
        )
        _AUTO_AUTH_FAIL_CLOSED_WARNED = True
    return "token"


def _is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True
    if not ALLOWED_ORIGINS:
        return True
    return origin in ALLOWED_ORIGINS


def _is_allowed_host(host: str | None) -> bool:
    if not host:
        return True
    if not ALLOWED_HOSTS:
        return True
    host = host.strip().lower()
    if host in ALLOWED_HOSTS:
        return True
    if ":" in host:
        hostname, _port = host.rsplit(":", 1)
        if hostname in ALLOWED_HOSTS:
            return True
        if f"{hostname}:*" in ALLOWED_HOSTS:
            return True
    if f"{host}:*" in ALLOWED_HOSTS:
        return True
    return False


def _fetch_jwks_keys_by_kid(jwks_url: str) -> dict[str, dict[str, Any]]:
    import urllib.request

    with urllib.request.urlopen(jwks_url, timeout=10) as resp:  # nosec B310
        body = resp.read()
    data = json.loads(body.decode("utf-8"))
    keys = data.get("keys")
    if not isinstance(keys, list):
        raise AuthError("jwks_missing_keys")

    keys_by_kid: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(keys):
        if not isinstance(item, dict):
            continue
        kid = str(item.get("kid") or "").strip() or f"__idx_{i}"
        keys_by_kid[kid] = item
    return keys_by_kid


def _get_cached_jwks_keys_by_kid(jwks_url: str) -> dict[str, dict[str, Any]]:
    global _JWKS_CACHE_FETCHED_AT, _JWKS_CACHE_KEYS_BY_KID
    now = time.time()
    with _JWKS_CACHE_LOCK:
        if _JWKS_CACHE_KEYS_BY_KID and now - _JWKS_CACHE_FETCHED_AT < max(
            1, JWKS_CACHE_TTL_SECONDS
        ):
            return _JWKS_CACHE_KEYS_BY_KID

        _JWKS_CACHE_KEYS_BY_KID = _fetch_jwks_keys_by_kid(jwks_url)
        _JWKS_CACHE_FETCHED_AT = now
        return _JWKS_CACHE_KEYS_BY_KID


def _verify_jwt(token: str) -> dict[str, Any]:
    from jose import JWTError
    from jose import jwk as jose_jwk
    from jose import jwt as jose_jwt

    try:
        header = jose_jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthError("invalid_jwt_header") from exc

    alg = str(header.get("alg") or "").upper()
    kid = str(header.get("kid") or "").strip() or None

    if not alg:
        raise AuthError("missing_jwt_alg")

    algorithms = JWT_ALGORITHMS
    if not algorithms:
        # Safe defaults:
        # - HS256 when we have a shared secret
        # - RS256 when we have a JWKS URL
        # - allow both when both are configured
        if JWKS_URL and JWT_SECRET_KEY:
            algorithms = {"HS256", "RS256"}
        elif JWKS_URL:
            algorithms = {"RS256"}
        else:
            algorithms = {"HS256"}

    if alg not in algorithms:
        raise AuthError("jwt_alg_not_allowed")

    key: str
    if alg.startswith("HS"):
        if not JWT_SECRET_KEY:
            raise AuthError("missing_jwt_secret")
        key = JWT_SECRET_KEY
    else:
        if not JWKS_URL:
            raise AuthError("missing_jwks_url")
        keys_by_kid = _get_cached_jwks_keys_by_kid(JWKS_URL)
        jwk_dict = keys_by_kid.get(kid or "")
        if jwk_dict is None:
            # Retry once after a forced refresh (kid rotation).
            with _JWKS_CACHE_LOCK:
                global _JWKS_CACHE_FETCHED_AT, _JWKS_CACHE_KEYS_BY_KID
                _JWKS_CACHE_KEYS_BY_KID = {}
                _JWKS_CACHE_FETCHED_AT = 0.0
            keys_by_kid = _get_cached_jwks_keys_by_kid(JWKS_URL)
            jwk_dict = keys_by_kid.get(kid or "")
        if jwk_dict is None:
            raise AuthError("jwks_kid_not_found")
        key_obj = jose_jwk.construct(jwk_dict, alg)
        key = key_obj.to_pem().decode("utf-8")

    audience: str | list[str] | None
    if len(JWT_AUDIENCES) > 1:
        audience = JWT_AUDIENCES
    elif len(JWT_AUDIENCES) == 1:
        audience = JWT_AUDIENCES[0]
    else:
        audience = None

    options = {
        "verify_aud": bool(JWT_AUDIENCES),
        "verify_iss": bool(JWT_ISSUER),
    }
    try:
        return jose_jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=audience,
            issuer=JWT_ISSUER or None,
            options=options,
        )
    except JWTError as exc:
        raise AuthError("invalid_jwt") from exc


def _try_verify_api_key(token: str) -> str | None:
    parsed = parse_token(token)
    if not parsed:
        logger.debug("MCP API key parse failed")
        return None
    key_id, secret = parsed
    logger.debug("MCP API key candidate key_id=%s", key_id)

    redis_status, redis_user_id = _verify_against_redis_token_record(key_id, secret)
    logger.debug(
        "MCP API key redis lookup key_id=%s status=%s user_present=%s",
        key_id,
        redis_status,
        bool(redis_user_id),
    )
    if redis_status == "found":
        # A Redis record exists for this kid; respect its decision (including revocation).
        if redis_user_id is None:
            logger.debug(
                "MCP API key rejected key_id=%s reason=redis_record_not_authorized",
                key_id,
            )
        else:
            logger.debug(
                "MCP API key accepted key_id=%s source=redis user_id=%s",
                key_id,
                redis_user_id,
            )
        return redis_user_id
    if redis_status in {"not_found", "redis_unavailable", "skip"}:
        static_user_id = _verify_against_static_tokens(key_id, secret)
        if static_user_id is None:
            logger.debug(
                "MCP API key rejected key_id=%s reason=static_lookup_failed redis_status=%s",
                key_id,
                redis_status,
            )
        else:
            logger.debug(
                "MCP API key accepted key_id=%s source=static user_id=%s redis_status=%s",
                key_id,
                static_user_id,
                redis_status,
            )
        return static_user_id
    logger.debug(
        "MCP API key rejected key_id=%s reason=unexpected_redis_status status=%s",
        key_id,
        redis_status,
    )
    return None


def _check_run_root_writable(path: Path) -> tuple[bool, str | None]:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    probe = path / f".mcp_write_probe_{uuid.uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _assert_run_root_writable(path: Path) -> None:
    ok, error = _check_run_root_writable(path)
    if ok:
        return
    raise RuntimeError(
        f"RUN_ROOT is not writable: {path}. "
        f"Set BR_MCP_RUN_ROOT to a writable location. ({error})"
    )


def _ensure_dirs() -> None:
    # Create run root early so server failures are explicit.
    _assert_run_root_writable(_runstore.RUN_ROOT)


def _is_under_any_root(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in roots:
        root_resolved = root.resolve()
        if resolved == root_resolved:
            return True
        if str(resolved).startswith(str(root_resolved) + os.sep):
            return True
    return False


def _require_allowed_path(path: Path, *, kind: str) -> Path:
    p = path.expanduser()
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    if not _is_under_any_root(p, ALLOWED_ROOTS):
        raise ValueError(
            f"{kind} path not allowed: {p}. Set BR_MCP_ALLOWED_ROOTS to permit it."
        )
    return p


_RESEARCH_SESSION_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_RESEARCH_EVENT_WRITE_LOCK = threading.Lock()
_RESEARCH_SESSION_INDEX_LOCK = threading.Lock()
_RESEARCH_TRANSPORT_BINDINGS_LOCK = threading.Lock()
_RESEARCH_DIRECTIVE_EMIT_LOCK = threading.Lock()
_RESEARCH_EVENTS_FILENAME = "research_events.jsonl"
_SESSION_SNAPSHOT_FILENAME = "session_snapshot.json"
_SESSION_TRANSCRIPT_FILENAME = "session_transcript.jsonl"
_RESEARCH_SESSION_INDEX_FILENAME = "research_session_index.json"
_RESEARCH_CONVERSATION_LOG_FILENAME = "conversation_log.jsonl"
_RESEARCH_TOOL_TRACE_FILENAME = "tool_trace.jsonl"
_RESEARCH_TRANSPORT_BINDINGS_TTL_SECONDS = 12 * 60 * 60
_RESEARCH_AUTO_HEARTBEAT_INTERVAL = 5
_RESEARCH_DIGEST_TRANSCRIPT_PREVIEW_LIMIT = 10
_RESEARCH_DIGEST_TOOL_TRACE_PREVIEW_LIMIT = 10
_RESEARCH_LOGGING_DIRECTIVE_MODE = (
    (os.getenv("BR_MCP_RESEARCH_LOGGING_DIRECTIVE_MODE") or "once").strip().lower()
)
if _RESEARCH_LOGGING_DIRECTIVE_MODE not in {"once", "always"}:
    _RESEARCH_LOGGING_DIRECTIVE_MODE = "once"
_RESEARCH_DIRECTIVE_FULL_EMITTED_SESSIONS: set[str] = set()
_RESEARCH_AUTO_EXCLUDED_TOOLS = {
    "log_research_event",
    "write_session_snapshot",
    "research_session_digest",
    "research_log_summary",
    "session_risk_classify",
    "session_lesson_extract",
    "session_open_risks_query",
    "session_policy_cards_generate",
    "session_learning_report_generate",
    "session_signal_report_generate",
    "session_backfill_to_kg",
    "memory_write",
    "memory_search",
    "memory_get",
}
_SESSION_SIGNAL_REVIEW_TOOLS = {
    "pipeline_plan_review",
    "pipeline_plan_validate",
    "run_code_review",
    "run_scientific_review",
    "request_scientific_review",
    "request_external_scientific_review_directive",
}
_SESSION_SIGNAL_ARTIFACT_TOOLS = {
    "artifact_list",
    "artifact_read_text",
    "artifact_get_metadata",
    "run_bundle_get",
}
_SESSION_TRACE_INVARIANT_RE = re.compile(
    r"\b(partial correlation|EmpiricalCovariance|FEATURE_SELECTION_OUTSIDE_CV|"
    r"HARMONIZATION_OUTSIDE_CV|STANDARDIZATION_OUTSIDE_CV|"
    r"BRAINMAP_CORRELATION_NO_SPATIAL_NULL|UNCORRECTED_WHOLEBRAIN|"
    r"QSM|dipole|inverted|direct inversion|data leakage|circularity|"
    r"silent-pass|silent pass)\b",
    re.IGNORECASE,
)
_RESEARCH_TRANSPORT_BINDINGS: dict[str, dict[str, Any]] = {}


def _sanitize_research_session_token(raw: Any) -> str:
    text = _first_text_value(raw)
    if not text:
        raise ValueError("session_id is required")
    cleaned = _RESEARCH_SESSION_ID_SAFE_RE.sub("-", text).strip(".-_")
    if not cleaned:
        raise ValueError("session_id must contain at least one alphanumeric character")
    if len(cleaned) > 80:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        prefix = cleaned[:67].rstrip(".-_")
        cleaned = f"{prefix}-{digest}" if prefix else digest
    return cleaned


def _research_session_run_id(session_id: str) -> str:
    return f"research_session_{_sanitize_research_session_token(session_id)}"


# Canonical research-log `source` values. The MCP schema advertises these as an
# enum so well-behaved clients pick from them, but the server stays permissive:
# common synonyms are coerced and anything else falls back to the default author
# ("agent") rather than raising, so weak-prompting hosts never eat
# invalid_arguments on this field.
RESEARCH_LOG_SOURCES: tuple[str, ...] = ("agent", "user")
_RESEARCH_LOG_SOURCE_ALIASES: dict[str, str] = {
    "agent": "agent",
    "assistant": "agent",
    "ai": "agent",
    "model": "agent",
    "llm": "agent",
    "bot": "agent",
    "system": "agent",
    "tool": "agent",
    "automation": "agent",
    "claude": "agent",
    "claude_code": "agent",
    "codex": "agent",
    "gpt": "agent",
    "user": "user",
    "human": "user",
    "person": "user",
    "researcher": "user",
    "operator": "user",
    "me": "user",
}


def _normalize_research_log_source(raw: Any) -> str:
    """Coerce a free-form ``source`` to a canonical ``agent``/``user`` value.

    Never raises: known synonyms map to a canonical value and anything else
    (including empty input) falls back to ``agent`` — the default author.
    """
    source = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not source:
        return "agent"
    return _RESEARCH_LOG_SOURCE_ALIASES.get(source, "agent")


def _normalize_research_source_client(raw: Any) -> str | None:
    text = _first_text_value(raw)
    if not text:
        return None
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9._]+", "_", normalized).strip("._")
    if not normalized:
        return None
    aliases = {
        "claude": "claude_code",
        "claudecode": "claude_code",
        "gemini": "gemini_cli",
        "geminicli": "gemini_cli",
    }
    return aliases.get(normalized, normalized)


# Canonical research-event `kind` values understood by the storage/session layer:
# "start" marks the beginning of a session/run, "note" is the generic catch-all.
# Advertised as an enum on the MCP schema; the server coerces synonyms and falls
# back to "note" for any other value so a missing/odd kind degrades gracefully
# instead of failing the call.
RESEARCH_EVENT_KINDS: tuple[str, ...] = ("start", "note")
_RESEARCH_EVENT_KIND_ALIASES: dict[str, str] = {
    "start": "start",
    "begin": "start",
    "began": "start",
    "begun": "start",
    "started": "start",
    "session_start": "start",
    "run_start": "start",
    "kickoff": "start",
    "kick_off": "start",
    "init": "start",
    "initialize": "start",
    "initialized": "start",
    "open": "start",
    "opened": "start",
    "note": "note",
    "event": "note",
    "log": "note",
    "info": "note",
    "update": "note",
    "progress": "note",
    "milestone": "note",
    "checkpoint": "note",
    "observation": "note",
    "finding": "note",
    "result": "note",
    "decision": "note",
    "status": "note",
    "message": "note",
    "comment": "note",
    "action": "note",
    "step": "note",
}


def _normalize_research_event_kind(raw: Any) -> str:
    """Coerce a free-form event ``kind`` to a canonical ``start``/``note`` value.

    Never raises: known synonyms map to ``start``/``note`` and any other value
    (including empty input) falls back to ``note`` — the generic bucket — so
    weak-prompting hosts never eat invalid_arguments on this field.
    """
    kind = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not kind:
        return "note"
    return _RESEARCH_EVENT_KIND_ALIASES.get(kind, "note")


def _ensure_run_layout(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("logs", "work", "artifacts"):
        (run_dir / dirname).mkdir(parents=True, exist_ok=True)


def _append_jsonl_record(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False)
    with _RESEARCH_EVENT_WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")


def _research_session_index_path() -> Path:
    return _runstore.RUN_ROOT / _RESEARCH_SESSION_INDEX_FILENAME


def _load_research_session_index() -> dict[str, Any]:
    path = _research_session_index_path()
    if not path.exists():
        return {
            "schema_version": "research-session-index-v1",
            "updated_at": None,
            "sessions": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "schema_version": "research-session-index-v1",
            "updated_at": None,
            "sessions": {},
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": "research-session-index-v1",
            "updated_at": None,
            "sessions": {},
        }
    payload.setdefault("schema_version", "research-session-index-v1")
    payload.setdefault("updated_at", None)
    payload.setdefault("sessions", {})
    return payload


def _lookup_research_session_run_id(session_id: str) -> str | None:
    with _RESEARCH_SESSION_INDEX_LOCK:
        snapshot = _load_research_session_index()
        sessions = snapshot.get("sessions")
        if not isinstance(sessions, dict):
            return None
        entry = sessions.get(session_id)
        if not isinstance(entry, dict):
            return None
        return _first_text_value(entry.get("run_id"))


def _record_research_session_run_id(
    session_id: str,
    run_id: str,
    *,
    updated_at: str,
) -> None:
    path = _research_session_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _RESEARCH_SESSION_INDEX_LOCK:
        snapshot = _load_research_session_index()
        sessions = snapshot.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        sessions[session_id] = {"run_id": run_id, "updated_at": updated_at}
        snapshot["sessions"] = sessions
        snapshot["updated_at"] = updated_at
        _atomic_write_json(path, snapshot)


def _research_trace_logger() -> Any:
    try:
        from brain_researcher.services.agent.run_bundle import (
            log_trace_event as _log_trace_event,
        )

        return _log_trace_event
    except Exception:
        return None


def _resolve_research_session_identity(
    session_id: Any,
    *,
    client_session_id: Any = None,
    source_client: Any = None,
) -> tuple[str, str | None, str | None]:
    normalized_session_id = _first_text_value(session_id)
    normalized_client_session_id = _first_text_value(client_session_id)
    normalized_source_client = _normalize_research_source_client(source_client)

    if not normalized_session_id:
        if normalized_client_session_id:
            prefix = normalized_source_client or "client"
            normalized_session_id = f"{prefix}:{normalized_client_session_id}"
        else:
            raise ValueError("session_id or client_session_id is required")

    return (
        normalized_session_id,
        normalized_client_session_id,
        normalized_source_client,
    )


def _research_transport_key(context: Any) -> str | None:
    if context is None:
        return None
    client_id = _first_text_value(getattr(context, "client_id", None))
    if client_id:
        return f"client:{client_id}"
    try:
        session = context.session
    except Exception:
        session = None
    if session is not None:
        return f"session:{id(session)}"
    return None


def _prune_research_transport_bindings_locked(now_s: float) -> None:
    stale_keys = [
        key
        for key, payload in _RESEARCH_TRANSPORT_BINDINGS.items()
        if now_s - float(payload.get("updated_at_s") or 0.0)
        > _RESEARCH_TRANSPORT_BINDINGS_TTL_SECONDS
    ]
    for key in stale_keys:
        _RESEARCH_TRANSPORT_BINDINGS.pop(key, None)


def _bind_research_transport_session(
    context: Any,
    *,
    session_id: str,
    client_session_id: str | None,
    source_client: str | None,
    run_id: str | None = None,
) -> None:
    transport_key = _research_transport_key(context)
    if not transport_key or not session_id:
        return
    now_s = time.time()
    with _RESEARCH_TRANSPORT_BINDINGS_LOCK:
        _prune_research_transport_bindings_locked(now_s)
        existing = _RESEARCH_TRANSPORT_BINDINGS.get(transport_key) or {}
        state = _record_dict(existing.get("runtime_state"))
        _RESEARCH_TRANSPORT_BINDINGS[transport_key] = {
            "session_id": session_id,
            "client_session_id": client_session_id,
            "source_client": source_client,
            "run_id": run_id,
            "updated_at_s": now_s,
            "runtime_state": state,
        }


def _lookup_research_transport_session(context: Any) -> dict[str, Any] | None:
    transport_key = _research_transport_key(context)
    if not transport_key:
        return None
    now_s = time.time()
    with _RESEARCH_TRANSPORT_BINDINGS_LOCK:
        _prune_research_transport_bindings_locked(now_s)
        payload = _RESEARCH_TRANSPORT_BINDINGS.get(transport_key)
        if not isinstance(payload, dict):
            return None
        payload["updated_at_s"] = now_s
        return dict(payload)


def _research_binding_from_run_id(run_id: Any) -> dict[str, Any] | None:
    normalized_run_id = _first_text_value(run_id)
    if not normalized_run_id:
        return None
    try:
        record, run_dir = _load_run_with_dir(normalized_run_id)
    except Exception:
        return None
    provenance = _load_run_provenance(run_dir)
    meta = _research_logging_meta(record, provenance)
    session_id = _first_text_value(meta.get("session_id"))
    if not session_id:
        return None
    return {
        "session_id": session_id,
        "client_session_id": _first_text_value(meta.get("client_session_id")),
        "source_client": _normalize_research_source_client(meta.get("source_client")),
        "run_id": record.run_id,
    }


def _resolve_research_binding_for_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None,
    result: Any,
    context: Any,
) -> dict[str, Any] | None:
    safe_arguments = arguments if isinstance(arguments, dict) else {}
    response = _tool_result_payload_dict(result)

    explicit_session_id = _first_text_value(
        safe_arguments.get("session_id"),
        response.get("session_id"),
    )
    explicit_client_session_id = _first_text_value(
        safe_arguments.get("client_session_id"),
        response.get("client_session_id"),
    )
    explicit_source_client = _normalize_research_source_client(
        safe_arguments.get("source_client") or response.get("source_client")
    )
    if explicit_session_id or explicit_client_session_id:
        (
            normalized_session_id,
            normalized_client_session_id,
            normalized_source_client,
        ) = _resolve_research_session_identity(
            explicit_session_id,
            client_session_id=explicit_client_session_id,
            source_client=explicit_source_client,
        )
        return {
            "session_id": normalized_session_id,
            "client_session_id": normalized_client_session_id,
            "source_client": normalized_source_client,
            "run_id": _first_text_value(
                safe_arguments.get("run_id"), response.get("run_id")
            ),
        }

    binding = _research_binding_from_run_id(
        _first_text_value(safe_arguments.get("run_id"), response.get("run_id"))
    )
    if isinstance(binding, dict):
        return binding

    return _lookup_research_transport_session(context)


def _research_auto_tool_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    filtered = {
        key: value
        for key, value in (arguments or {}).items()
        if key not in {"session_id", "client_session_id", "source_client"}
    }
    try:
        payload = json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        payload = str(sorted(filtered.keys()))
    return f"{tool_name}|{payload}"


def _research_result_is_error_like(result: Any) -> bool:
    result_dict = _tool_result_payload_dict(result)
    if not result_dict:
        return False
    if result_dict.get("ok") is False:
        return True
    status = _first_text_value(
        result_dict.get("status"), _record_dict(result_dict.get("data")).get("status")
    )
    if status and status.lower() in {
        "failed",
        "error",
        "cancelled",
        "canceled",
        "timeout",
    }:
        return True
    return bool(_first_text_value(result_dict.get("error")))


def _append_research_auto_event(
    *,
    session_id: str,
    client_session_id: str | None,
    source_client: str | None,
    subtype: str,
    tool_name: str,
    details: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any] | None:
    try:
        record, run_dir, managed_run = _load_or_create_research_run(
            session_id, run_id=run_id
        )
    except Exception:
        return None

    now = _utc_iso()
    research_logging, event_id = _next_research_event_metadata(
        record,
        session_id=session_id,
        client_session_id=client_session_id,
        source_client=source_client,
        source="server",
        managed_run=managed_run,
        event_kind="auto",
        event_at=now,
    )
    _save_run(record, run_dir=run_dir)

    _record_research_session_run_id(session_id, record.run_id, updated_at=now)

    event_payload = {
        "event_id": event_id,
        "kind": "auto",
        "event_type": f"research.auto.{subtype}",
        "session_id": session_id,
        "client_session_id": client_session_id,
        "source_client": source_client,
        "run_id": record.run_id,
        "source": "server",
        "tool_name": tool_name,
        "subtype": subtype,
        "details": details,
        "timestamp": now,
        "managed_run": bool(managed_run),
    }
    _append_jsonl_record(run_dir / _RESEARCH_EVENTS_FILENAME, event_payload)
    _persist_research_logging_provenance(
        run_dir=run_dir,
        record=record,
        session_id=session_id,
        client_session_id=client_session_id,
        source_client=source_client,
        source="server",
        managed_run=managed_run,
        last_write_tool="auto_research_telemetry",
        last_event_kind="auto",
        request_payload={
            "session_id": session_id,
            "client_session_id": client_session_id,
            "source_client": source_client,
            "tool_name": tool_name,
            "subtype": subtype,
        },
        updated_at=now,
    )
    _emit_trace_event(
        _research_trace_logger(),
        run_dir,
        run_id=record.run_id,
        event_type=f"research.auto.{subtype}",
        payload=event_payload,
    )
    return {
        "event_id": event_id,
        "event_type": event_payload["event_type"],
        "run_id": record.run_id,
        "session_id": session_id,
        "progress": research_logging,
    }


def _record_research_auto_tool_signal(
    *,
    binding: dict[str, Any] | None,
    tool_name: str,
    arguments: dict[str, Any] | None,
    result: Any,
) -> dict[str, Any] | None:
    if not isinstance(binding, dict):
        return None
    session_id = _first_text_value(binding.get("session_id"))
    if not session_id or tool_name in _RESEARCH_AUTO_EXCLUDED_TOOLS:
        return None

    safe_arguments = arguments if isinstance(arguments, dict) else {}
    error_like = _research_result_is_error_like(result)
    signature = _research_auto_tool_signature(tool_name, safe_arguments)
    heartbeat_due = False
    retry_due = False

    with _RESEARCH_TRANSPORT_BINDINGS_LOCK:
        now_s = time.time()
        transport_key = None
        for key, payload in _RESEARCH_TRANSPORT_BINDINGS.items():
            if _first_text_value(payload.get("session_id")) == session_id:
                transport_key = key
                break
        if transport_key is None:
            state = {}
        else:
            payload = _RESEARCH_TRANSPORT_BINDINGS.get(transport_key) or {}
            state = _record_dict(payload.get("runtime_state"))
        call_count = int(state.get("tool_call_count") or 0) + 1
        last_signature = _first_text_value(state.get("last_signature"))
        last_was_error = bool(state.get("last_was_error"))
        if call_count > 0 and call_count % _RESEARCH_AUTO_HEARTBEAT_INTERVAL == 0:
            heartbeat_due = True
        if last_signature == signature and last_was_error:
            retry_due = True
        state.update(
            {
                "tool_call_count": call_count,
                "last_signature": signature,
                "last_was_error": error_like,
                "updated_at_s": now_s,
            }
        )
        if transport_key is not None:
            payload = _RESEARCH_TRANSPORT_BINDINGS.get(transport_key) or {}
            payload["updated_at_s"] = now_s
            payload["runtime_state"] = state
            _RESEARCH_TRANSPORT_BINDINGS[transport_key] = payload

    auto_event = None
    if retry_due:
        auto_event = _append_research_auto_event(
            session_id=session_id,
            client_session_id=_first_text_value(binding.get("client_session_id")),
            source_client=_normalize_research_source_client(
                binding.get("source_client")
            ),
            run_id=_first_text_value(binding.get("run_id")),
            subtype="retry",
            tool_name=tool_name,
            details={"call_count": call_count},
        )
    elif error_like:
        result_dict = _tool_result_payload_dict(result)
        auto_event = _append_research_auto_event(
            session_id=session_id,
            client_session_id=_first_text_value(binding.get("client_session_id")),
            source_client=_normalize_research_source_client(
                binding.get("source_client")
            ),
            run_id=_first_text_value(binding.get("run_id")),
            subtype="tool_error",
            tool_name=tool_name,
            details={
                "call_count": call_count,
                "error": _first_text_value(result_dict.get("error")),
                "status": _first_text_value(result_dict.get("status")),
            },
        )
    elif heartbeat_due:
        auto_event = _append_research_auto_event(
            session_id=session_id,
            client_session_id=_first_text_value(binding.get("client_session_id")),
            source_client=_normalize_research_source_client(
                binding.get("source_client")
            ),
            run_id=_first_text_value(binding.get("run_id")),
            subtype="heartbeat",
            tool_name=tool_name,
            details={"call_count": call_count},
        )

    if auto_event is None:
        return None
    auto_event["call_count"] = call_count
    return auto_event


def _should_emit_full_research_logging_directive(
    *,
    session_id: str | None,
    is_snapshot_closeout: bool,
) -> bool:
    if _RESEARCH_LOGGING_DIRECTIVE_MODE == "always":
        return True
    if is_snapshot_closeout:
        return True
    if not session_id:
        return True
    directive_key = f"{Path(_runstore.RUN_ROOT).expanduser().resolve()}::{session_id}"
    with _RESEARCH_DIRECTIVE_EMIT_LOCK:
        if directive_key in _RESEARCH_DIRECTIVE_FULL_EMITTED_SESSIONS:
            return False
        _RESEARCH_DIRECTIVE_FULL_EMITTED_SESSIONS.add(directive_key)
        return True


def _compact_research_logging_directive(
    directive: dict[str, Any],
) -> dict[str, Any]:
    retained_actions = [
        action
        for action in (directive.get("actions") or [])
        if isinstance(action, dict)
        and action.get("type")
        in {
            "observe_server_auto_event",
            "prompt_post_session_actions",
            "review_session_snapshot_hygiene",
        }
    ]
    return {
        "protocol": directive.get("protocol"),
        "state": directive.get("state") or {},
        "actions": retained_actions,
        "directive_ref": {
            "mode": "compact_repeat",
            "full_directive_emitted_once": True,
            "refresh": (
                "Set BR_MCP_RESEARCH_LOGGING_DIRECTIVE_MODE=always to receive "
                "the full closeout instruction block on every response."
            ),
        },
    }


def _attach_research_logging_directive(
    result: Any,
    *,
    tool_name: str | None = None,
    binding: dict[str, Any] | None,
    auto_event: dict[str, Any] | None,
) -> Any:
    result_payload = _tool_result_payload_dict(result)
    if not result_payload:
        return result
    if not isinstance(binding, dict) and auto_event is None:
        return result

    session_id = _first_text_value(
        result_payload.get("session_id"),
        binding.get("session_id") if isinstance(binding, dict) else None,
    )
    client_session_id = _first_text_value(
        result_payload.get("client_session_id"),
        binding.get("client_session_id") if isinstance(binding, dict) else None,
    )
    source_client = _normalize_research_source_client(
        result_payload.get("source_client")
        or (binding.get("source_client") if isinstance(binding, dict) else None)
    )
    run_id = _first_text_value(
        result_payload.get("run_id"),
        binding.get("run_id") if isinstance(binding, dict) else None,
    )
    is_snapshot_closeout = bool(
        result_payload.get("ok") is True
        and tool_name == "write_session_snapshot"
        and isinstance(result_payload.get("snapshot"), dict)
    )

    def _snapshot_hygiene_action() -> dict[str, Any] | None:
        if not is_snapshot_closeout:
            return None
        snapshot = _record_dict(result_payload.get("snapshot"))
        digest = {
            "session_id": _first_text_value(
                result_payload.get("session_id"), snapshot.get("session_id")
            ),
            "run_id": _first_text_value(
                result_payload.get("run_id"), snapshot.get("run_id")
            ),
            "status": _first_text_value(result_payload.get("status")),
            "source_client": _first_text_value(
                result_payload.get("source_client"), snapshot.get("source_client")
            ),
            "has_snapshot": True,
            "snapshot": snapshot,
            "done_items": _coerce_non_empty_str_list(snapshot.get("done")),
            "open_items": _coerce_non_empty_str_list(snapshot.get("open")),
            "event_tags": _coerce_non_empty_str_list(snapshot.get("tags")),
        }
        classification = classify_session(digest)
        issues = [
            issue
            for issue in classification.get("hygiene_issues") or []
            if isinstance(issue, dict)
        ]
        if not issues:
            return None
        return {
            "type": "review_session_snapshot_hygiene",
            "required": False,
            "reason": "advisory_snapshot_hygiene",
            "payload": {
                "session_id": digest["session_id"],
                "run_id": digest["run_id"],
                "issue_count": len(issues),
                "issues": issues,
                "task_surfaces": classification.get("task_surfaces") or [],
                "validation_evidence_count": len(
                    classification.get("validation_evidence") or []
                ),
                "message": (
                    "Snapshot was persisted, but the closeout has hygiene warnings. "
                    "Treat these as follow-up guidance for future sessions."
                ),
            },
        }

    actions: list[dict[str, Any]] = []
    if session_id:
        transcript_context_aliases = [
            "transcript",
            "messages",
            "chat_history",
            "conversation_events",
            "conversation_messages",
            "conversation_log",
        ]
        trace_context_aliases = [
            "external_trace_events",
            "trace_events",
            "tool_trace",
            "tool_trace_events",
        ]
        actions.append(
            {
                "type": "bind_session",
                "required": False,
                "reason": "server_session_active",
                "payload": {
                    "session_id": session_id,
                    "client_session_id": client_session_id,
                    "source_client": source_client,
                },
            }
        )
        if is_snapshot_closeout:
            suggested_actions: list[dict[str, Any]] = []
            if run_id:
                suggested_actions.append(
                    {
                        "id": "generate_durable_session_summary",
                        "label": "Generate Session Summary",
                        "description": (
                            "Generate durable trajectory summary artifacts for the "
                            "completed session."
                        ),
                        "tool_name": "generate_research_trajectory_and_insights",
                        "arguments": {
                            "run_id": run_id,
                            "persist": True,
                        },
                        "expected_artifacts": [
                            "artifacts/summaries/research_trajectory_and_insights.json",
                            "artifacts/summaries/research_trajectory_and_insights.md",
                        ],
                    }
                )
            actions.append(
                {
                    "type": "prompt_post_session_actions",
                    "required": False,
                    "reason": "durable_session_summary_available",
                    "payload": {
                        "session_id": session_id,
                        "client_session_id": client_session_id,
                        "source_client": source_client,
                        "run_id": run_id,
                        "title": "Session closed",
                        "message": (
                            "Closeout is complete. Prompt the user to optionally "
                            "generate a durable session summary."
                        ),
                        "requires_user_initiation": True,
                        "suggested_actions": suggested_actions,
                    },
                }
            )
            hygiene_action = _snapshot_hygiene_action()
            if hygiene_action is not None:
                actions.append(hygiene_action)
        else:
            actions.append(
                {
                    "type": "write_snapshot_on_close",
                    "required": True,
                    "reason": "explicit_closeout_required",
                    "payload": {
                        "session_id": session_id,
                        "client_session_id": client_session_id,
                        "source_client": source_client,
                        "context_contract": {
                            "preferred_transcript_key": "transcript",
                            "preferred_trace_key": "external_trace_events",
                            "transcript_aliases": transcript_context_aliases,
                            "trace_aliases": trace_context_aliases,
                        },
                    },
                }
            )
            actions.append(
                {
                    "type": "attach_transcript_on_close",
                    "required": False,
                    "reason": "persist_client_transcript",
                    "payload": {
                        "session_id": session_id,
                        "context_aliases": transcript_context_aliases,
                        "preferred_context_key": "transcript",
                        "target_file": _SESSION_TRANSCRIPT_FILENAME,
                    },
                }
            )
            actions.append(
                {
                    "type": "attach_external_trace_on_close",
                    "required": False,
                    "reason": "persist_external_tool_trace",
                    "payload": {
                        "session_id": session_id,
                        "context_aliases": trace_context_aliases,
                        "preferred_context_key": "external_trace_events",
                        "target_file": _RESEARCH_TOOL_TRACE_FILENAME,
                    },
                }
            )
            actions.append(
                {
                    "type": "log_optional_note",
                    "required": False,
                    "reason": "rationale_not_in_trace",
                    "payload": {
                        "session_id": session_id,
                        "kind": "note",
                        "policy": "optional_enrichment_only",
                    },
                }
            )
    if isinstance(auto_event, dict):
        actions.append(
            {
                "type": "observe_server_auto_event",
                "required": False,
                "reason": "server_auto_telemetry",
                "payload": auto_event,
            }
        )

    directive = {
        "protocol": "br.research_logging.directive.v1",
        "state": {
            "session_id": session_id,
            "client_session_id": client_session_id,
            "source_client": source_client,
            "snapshot_required_on_close": bool(session_id) and not is_snapshot_closeout,
            "session_closed": is_snapshot_closeout,
            "post_close_actions_available": is_snapshot_closeout,
            "note_policy": "optional_enrichment_only",
            "server_mid_session_telemetry": True,
            "transcript_capture_supported": True,
            "external_trace_capture_supported": True,
            "preferred_transcript_context_key": "transcript",
            "preferred_trace_context_key": "external_trace_events",
        },
        "actions": actions,
    }

    enriched = dict(result_payload)
    existing_directive = enriched.get("_agent_directive", {})
    if not isinstance(existing_directive, dict):
        existing_directive = {}
    if not _should_emit_full_research_logging_directive(
        session_id=session_id,
        is_snapshot_closeout=is_snapshot_closeout,
    ):
        directive = _compact_research_logging_directive(directive)
    existing_directive["research_logging"] = directive
    enriched["_agent_directive"] = existing_directive
    return _tool_result_with_structured_payload(result, enriched)


def _build_review_handoff_directive(
    verdict_dict: dict[str, Any],
    *,
    review_type: str,
) -> dict[str, Any] | None:
    """Build an advisory review_handoff directive for the outer model.

    Returns None if the verdict is clean (no handoff needed).
    """
    # Determine whether handoff is warranted.
    findings_summary: list[str] = []

    if review_type == "scientific_review":
        if verdict_dict.get("overall_decision") == "proceed":
            return None
        correctness = verdict_dict.get("correctness") or {}
        judgment = verdict_dict.get("judgment") or {}
        completeness = verdict_dict.get("completeness") or {}
        missing_caveats = [
            str(item).strip()
            for item in (completeness.get("missing_caveats") or [])
            if str(item).strip()
        ]
        missing_checklist_items = [
            str(key).strip()
            for key, value in (completeness.get("checklist") or {}).items()
            if not value and str(key).strip()
        ]
        inner_verdict = {
            "overall_decision": verdict_dict.get("overall_decision"),
            "correctness_decision": correctness.get("decision"),
            "judgment_decision": judgment.get("decision"),
            "completeness_decision": completeness.get("decision"),
            "claim_strength": verdict_dict.get("claim_strength"),
            "report_action": verdict_dict.get("report_action"),
            "line_directive": verdict_dict.get("line_directive"),
            "required_next_actions": list(
                verdict_dict.get("required_next_actions") or []
            )[:10],
            "missing_caveats": missing_caveats[:10],
            "missing_checklist_items": missing_checklist_items[:10],
        }
        raw_findings = correctness.get("findings") or []
        reviewer_questions = list(judgment.get("reviewer_questions") or [])
        for issue in judgment.get("issues") or []:
            if isinstance(issue, str) and issue.strip():
                reviewer_questions.append(issue.strip())
        action_prompts = [
            {
                "type": "independent_second_opinion",
                "required": False,
                "reason": "inner_model_flagged_issues",
                "prompt": (
                    "The BR scientific review flagged methodological or "
                    "specification issues in this run. As an independent "
                    "reviewer with access to the user's conversation context, "
                    "assess: (1) whether the flagged scientific or "
                    "completeness issues are genuine concerns or already "
                    "acknowledged by the user, (2) whether the statistical "
                    "method matches the experimental design, and (3) whether "
                    "additional reviewer questions should be raised. Do not "
                    "assume the internal review is correct; form your own "
                    "judgment."
                ),
            },
            {
                "type": "acknowledge_or_override",
                "required": False,
                "reason": "user_may_have_context",
                "prompt": (
                    "If the user has previously acknowledged any flagged "
                    "scientific caveat or missing specification, note that "
                    "context rather than re-flagging it without qualification."
                ),
            },
        ]
    elif review_type == "code_review":
        if verdict_dict.get("decision") in ("approve", None):
            return None
        inner_verdict = {
            "decision": verdict_dict.get("decision"),
            "risk_level": verdict_dict.get("risk_level"),
        }
        raw_findings = verdict_dict.get("findings") or []
        reviewer_questions = [
            "Are the flagged QC or artifact issues genuine blockers for this run?",
            "Do the flagged outputs materially undermine the user's intended downstream use?",
        ]
        action_prompts = [
            {
                "type": "independent_second_opinion",
                "required": False,
                "reason": "inner_model_flagged_issues",
                "prompt": (
                    "The BR code review flagged artifact, QC, or execution "
                    "issues in this run. As an independent reviewer with "
                    "access to the user's conversation context, assess: (1) "
                    "whether the flagged run artifacts are genuine blockers or "
                    "acceptable trade-offs, (2) whether the reported risk "
                    "level matches the evidence, and (3) whether additional "
                    "artifact or QC questions should be raised. Do not assume "
                    "the internal review is correct; form your own judgment."
                ),
            },
            {
                "type": "acknowledge_or_override",
                "required": False,
                "reason": "user_may_have_context",
                "prompt": (
                    "If the user has already accepted a flagged artifact or QC "
                    "trade-off for this run, note that context and whether it "
                    "changes the practical severity."
                ),
            },
        ]
    else:
        return None

    # Build findings summary (max 5, truncated messages).
    for f in raw_findings[:5]:
        if isinstance(f, dict):
            rule_id = f.get("rule_id", "UNKNOWN")
            msg = str(f.get("message") or "")[:80]
            findings_summary.append(f"{rule_id}: {msg}")
    if review_type == "scientific_review" and len(findings_summary) < 5:
        completeness_details = (
            inner_verdict.get("missing_caveats")
            or inner_verdict.get("missing_checklist_items")
            or []
        )
        for detail in completeness_details[: 5 - len(findings_summary)]:
            findings_summary.append(f"COMPLETENESS: {str(detail)[:80]}")

    return {
        "protocol": "br.review_handoff.directive.v1",
        "review_type": review_type,
        "inner_verdict": inner_verdict,
        "findings_summary": findings_summary,
        "reviewer_questions": reviewer_questions[:10],
        "actions": action_prompts,
    }


_EXTERNAL_REVIEW_PROTOCOL_VERSION = "br.external_review.directive.v1"

_EXTERNAL_REVIEW_BASE_CRITERIA: dict[str, list[str]] = {
    "correctness": [
        "Confirm the statistical/analytic specification matches the declared research question.",
        "Verify the design matrix / model structure is well-posed (no rank deficiency, no collinear nuisance regressors).",
        "Check contrast definitions match the reported hypotheses and their dimensions.",
        "Verify cross-file consistency between events, confounds, and model spec (subjects/runs align).",
    ],
    "completeness": [
        "Random seed is pinned and reported.",
        "Atlas / parcellation version is declared when atlas-based features are used.",
        "Ordering of conditions / trials / factors is explicitly declared.",
        "Multiple-comparisons strategy (FWE / FDR / cluster threshold) is stated.",
        "Preprocessing provenance (motion scrubbing, confound regression, smoothing) is reported.",
    ],
    "judgment": [
        "The estimand is clearly specified (population, unit, causal vs. associational).",
        "The chosen method is defensible for that estimand, not just conventional.",
        "Known threats to validity are acknowledged (confounds, selection, measurement).",
        "Effect sizes and uncertainty are reported, not just p-values.",
    ],
    "overall": [
        "Synthesize correctness + completeness + judgment into a single overall_decision.",
        "Blocking correctness issues -> stop_with_rationale.",
        "Non-blocking structural correctness flags -> diagnose.",
        "Unsound judgment -> diagnose.",
        "Questionable judgment OR incomplete completeness -> explore_more.",
        "Otherwise -> proceed.",
    ],
}

_EXTERNAL_REVIEW_TAILORING: dict[str, dict[str, list[str]]] = {
    "fitlins_multiverse": {
        "correctness": [
            "Every multiverse branch declared in the spec has a corresponding result; no silent pruning.",
            "Per-branch design matrices use consistent contrast labels so cross-branch comparisons are meaningful.",
        ],
        "completeness": [
            "Multiverse manifest enumerates all (model, contrast, preprocessing) combinations actually run.",
            "Branch-level outputs carry their own provenance snapshot (FitLins config + BIDS filters).",
        ],
        "judgment": [
            "Cross-branch decision rule is declared up front (vote-count, specification curve, or pre-registered primary) rather than cherry-picked.",
        ],
    },
    "autoresearch": {
        "completeness": [
            "final_report.md declares the exact experiments.jsonl state it was generated from.",
            "predict.py version / git hash is reported alongside the final numeric claims.",
        ],
        "judgment": [
            "Autoresearch loop termination condition is justified (not just max-iterations).",
        ],
    },
}


def _compact_external_review_axes(
    evaluation_axes: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    compact: dict[str, dict[str, Any]] = {}
    for axis, payload in evaluation_axes.items():
        criteria = [
            str(item).strip()
            for item in (payload.get("criteria") or [])
            if str(item).strip()
        ]
        kg_criteria = [
            item
            for item in (payload.get("kg_derived_criteria") or [])
            if isinstance(item, dict)
        ]
        axis_summary: dict[str, Any] = {
            "decision_space": list(payload.get("decision_space") or []),
            "required_outputs": list(payload.get("required_outputs") or []),
            "criteria_summary": {
                "count": len(criteria),
                "preview": criteria[:2],
            },
        }
        if kg_criteria:
            axis_summary["kg_derived_criteria_summary"] = {
                "count": len(kg_criteria),
                "rule_ids": [
                    str(item.get("rule_id"))
                    for item in kg_criteria
                    if item.get("rule_id")
                ][:12],
            }
        compact[axis] = axis_summary
    return compact


def _build_external_review_directive(
    goal: str,
    hints: dict[str, Any] | None,
    *,
    directive_id: str,
    session_id: str | None,
    issued_at: str,
    include_full_rubric: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Build a stateless external-review directive payload.

    Returns (directive, tailoring_keys_applied). No artifact is read and no
    storage is touched; callers decide whether to persist.
    """

    normalized_hints: dict[str, Any] = {}
    if isinstance(hints, dict):
        for raw_key, value in hints.items():
            if isinstance(raw_key, str) and raw_key.strip():
                normalized_hints[raw_key.strip().lower()] = value

    tailored_checks: list[dict[str, Any]] = []
    applied_keys: list[str] = []
    for value in normalized_hints.values():
        if not isinstance(value, str):
            continue
        key = value.strip().lower()
        bundle = _EXTERNAL_REVIEW_TAILORING.get(key)
        if bundle is None:
            continue
        applied_keys.append(key)
        for axis, extras in bundle.items():
            tailored_checks.append(
                {"axis": axis, "hint": key, "criteria": list(extras)}
            )

    evaluation_axes = {
        "correctness": {
            "decision_space": ["pass", "flag", "block"],
            "criteria": list(_EXTERNAL_REVIEW_BASE_CRITERIA["correctness"]),
            "required_outputs": ["decision", "findings[]"],
        },
        "completeness": {
            "decision_space": ["complete", "incomplete"],
            "criteria": list(_EXTERNAL_REVIEW_BASE_CRITERIA["completeness"]),
            "required_outputs": [
                "decision",
                "checklist{}",
                "missing_caveats[]",
            ],
        },
        "judgment": {
            "decision_space": ["sound", "questionable", "unsound"],
            "criteria": list(_EXTERNAL_REVIEW_BASE_CRITERIA["judgment"]),
            "required_outputs": [
                "decision",
                "estimand_complete",
                "method_defensible",
                "issues[]",
                "reviewer_questions[]",
            ],
        },
        "overall": {
            "decision_space": [
                "proceed",
                "diagnose",
                "explore_more",
                "stop_with_rationale",
            ],
            "criteria": list(_EXTERNAL_REVIEW_BASE_CRITERIA["overall"]),
            "required_outputs": ["overall_decision", "report_action"],
        },
    }
    kg_criteria: dict[str, list[dict[str, Any]]] = {}
    try:
        from brain_researcher.services.review.kg_rule_registry import (
            DEFAULT_REGISTRY_ID,
            build_external_review_kg_criteria,
        )

        kg_criteria = build_external_review_kg_criteria(
            registry_id=DEFAULT_REGISTRY_ID,
        )
    except Exception:
        kg_criteria = {}
    if kg_criteria:
        for axis, criteria in kg_criteria.items():
            if axis in evaluation_axes:
                evaluation_axes[axis]["kg_derived_criteria"] = list(criteria)

    from brain_researcher.core.contracts.scientific_review import (
        ScientificReviewVerdict,
    )

    directive = {
        "protocol": _EXTERNAL_REVIEW_PROTOCOL_VERSION,
        "directive_id": directive_id,
        "session_id": session_id,
        "issued_at": issued_at,
        "review_type": "scientific_review",
        "goal": goal,
        "hints_applied": normalized_hints,
        "rubric_detail": "full" if include_full_rubric else "summary",
        "evaluation_axes": (
            evaluation_axes
            if include_full_rubric
            else _compact_external_review_axes(evaluation_axes)
        ),
        "verdict_schema_ref": "br.ScientificReviewVerdict.v1",
        "submission_tool": "submit_external_scientific_review_verdict",
        "tailored_checks": tailored_checks,
        "full_rubric_available": True,
        "full_rubric_request": {
            "tool": "request_external_scientific_review_directive",
            "argument": "include_full_rubric",
            "value": True,
        },
        "agent_instructions": [
            "Read the run artifacts yourself - BR has not read them.",
            "For each axis, produce the required_outputs and pick a decision from decision_space.",
            (
                "Use kg_derived_criteria under each axis when present; cite matching KG rule_id values in correctness.findings."
                if include_full_rubric
                else "Use kg_derived_criteria summaries when present; request include_full_rubric=true if you need the full rubric or JSON schema."
            ),
            "Roll up to overall_decision using the rules under the overall axis.",
            "Submit the completed verdict via submission_tool, echoing directive_id.",
        ],
    }
    if include_full_rubric:
        directive["verdict_schema"] = ScientificReviewVerdict.model_json_schema()
    if kg_criteria:
        directive["kg_rule_registry"] = {
            "registry_id": DEFAULT_REGISTRY_ID,
            "source": "BRKG",
            "criteria_count": sum(len(items) for items in kg_criteria.values()),
            "criteria_counts_by_axis": {
                axis: len(items) for axis, items in kg_criteria.items()
            },
            "rule_ids_by_axis": {
                axis: [
                    str(item.get("rule_id"))
                    for item in items
                    if isinstance(item, dict) and item.get("rule_id")
                ]
                for axis, items in kg_criteria.items()
            },
        }
    return directive, applied_keys


def _attach_review_route(
    response: dict[str, Any],
    *,
    selected: str,
    source_kind: str,
    source_value: str | None,
    target_tool: str,
) -> dict[str, Any]:
    routed = dict(response)
    routed["review_route"] = {
        "selected": selected,
        "source": {"kind": source_kind, "value": source_value},
        "target_tool": target_tool,
    }
    return routed


_REFUTED_LANDSCAPE_ALLOWED_STATUSES = {
    "refuted",
    "supported",
    "inconclusive",
}
_REFUTED_LANDSCAPE_REQUIRED_ITEM_FIELDS: tuple[str, ...] = (
    "claim",
    "direction",
    "status",
    "reason",
)


def _summarize_narrative_evidence_items(evidence: Any, *, top_k: int) -> list[str]:
    if not isinstance(evidence, list):
        return []
    summaries: list[str] = []
    for item in evidence:
        if len(summaries) >= top_k:
            break
        if isinstance(item, str):
            text = item.strip()
            if text:
                summaries.append(text)
            continue
        if not isinstance(item, dict):
            continue
        label = _first_text_value(
            item.get("label"),
            item.get("metric"),
            item.get("name"),
            item.get("type"),
        )
        value = item.get("value")
        if label and value is not None and not isinstance(value, dict | list):
            summaries.append(f"{label}={value}")
        elif label:
            summaries.append(label)
    return summaries


def _normalize_refuted_landscape_finding(
    raw: Any,
    *,
    index: int,
    top_k: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"findings[{index}] must be an object")
    claim = _first_text_value(raw.get("claim"))
    if not claim:
        raise ValueError(f"findings[{index}].claim is required")
    direction = _first_text_value(raw.get("direction"))
    if not direction:
        raise ValueError(f"findings[{index}].direction is required")
    status = _first_text_value(raw.get("status")).lower()
    if status not in _REFUTED_LANDSCAPE_ALLOWED_STATUSES:
        allowed = ", ".join(sorted(_REFUTED_LANDSCAPE_ALLOWED_STATUSES))
        raise ValueError(f"findings[{index}].status must be one of: {allowed}")
    reason = _first_text_value(raw.get("reason"))
    if not reason:
        raise ValueError(f"findings[{index}].reason is required")
    comparison = _first_text_value(raw.get("comparison"))
    caveats = _coerce_non_empty_str_list(raw.get("caveats"))[:top_k]
    tags = _coerce_non_empty_str_list(raw.get("tags"))[:top_k]
    evidence_summary = _summarize_narrative_evidence_items(
        raw.get("evidence"),
        top_k=top_k,
    )
    return {
        "claim": claim,
        "direction": direction,
        "status": status,
        "comparison": comparison,
        "reason": reason,
        "evidence_summary": evidence_summary,
        "caveats": caveats,
        "tags": tags,
    }


def _missing_refuted_landscape_required_keys(
    findings: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for index, raw in enumerate(findings):
        if not isinstance(raw, dict):
            continue
        for key in _REFUTED_LANDSCAPE_REQUIRED_ITEM_FIELDS:
            if not _first_text_value(raw.get(key)):
                missing.append(f"findings[{index}].{key}")
    return missing


def _build_refuted_landscape_paragraph(
    rows: list[dict[str, Any]],
    *,
    counts: dict[str, int],
    top_k: int,
) -> str:
    paragraph = (
        f"Across {counts['total']} tested directions, {counts['refuted']} were refuted, "
        f"{counts['supported']} were supported, and {counts['inconclusive']} remained inconclusive."
    )
    prominent_refuted = list(
        dict.fromkeys(
            row["direction"] for row in rows if row.get("status") == "refuted"
        )
    )[:top_k]
    if prominent_refuted:
        paragraph += (
            " Most prominent refuted directions: " + ", ".join(prominent_refuted) + "."
        )
    coverage_gaps = list(
        dict.fromkeys(
            caveat
            for row in rows
            if row.get("status") == "inconclusive"
            for caveat in row.get("caveats") or []
        )
    )[:top_k]
    if coverage_gaps:
        paragraph += " Remaining coverage gaps: " + "; ".join(coverage_gaps) + "."
    return paragraph


def _summarize_refuted_landscape(
    findings: list[dict[str, Any]],
    *,
    top_k: int,
) -> dict[str, Any]:
    rows = [
        _normalize_refuted_landscape_finding(raw, index=idx, top_k=top_k)
        for idx, raw in enumerate(findings)
    ]
    counts = {
        "total": len(rows),
        "refuted": sum(1 for row in rows if row["status"] == "refuted"),
        "supported": sum(1 for row in rows if row["status"] == "supported"),
        "inconclusive": sum(1 for row in rows if row["status"] == "inconclusive"),
    }
    top_refuted = list(
        dict.fromkeys(
            row["direction"] for row in rows if row.get("status") == "refuted"
        )
    )[:top_k]
    coverage_gaps = list(
        dict.fromkeys(
            caveat
            for row in rows
            if row.get("status") == "inconclusive"
            for caveat in row.get("caveats") or []
        )
    )[:top_k]
    return {
        "counts": counts,
        "refuted_landscape": {
            "paragraph": _build_refuted_landscape_paragraph(
                rows,
                counts=counts,
                top_k=top_k,
            ),
            "rows": rows,
            "top_refuted": top_refuted,
            "coverage_gaps": coverage_gaps,
        },
    }


_COMPANION_DIAGNOSTIC_TABLE_VERSION = "v1"

_COMPANION_DIAGNOSTIC_TABLE: dict[str, list[dict[str, Any]]] = {
    "reliability_ratio": [
        {
            "name": "within_class_variance_ratio",
            "rationale": (
                "A reliability ratio near 1 can reflect either faithful "
                "reconstruction or variance collapse in the generator. "
                "Comparing within-class pairwise-distance variance in "
                "generated vs real samples distinguishes the two."
            ),
            "failure_mode_guarded_against": "oversmoothing / mode collapse",
            "value_band_hint": "near 1.0",
            "implementation_hint": (
                "Per class c: ratio = var(pairwise_dist(generated_c)) / "
                "var(pairwise_dist(real_c)). Values << 1 suggest collapse."
            ),
            "tags": ["generative_fidelity", "variance_collapse"],
        },
        {
            "name": "pairwise_similarity_distribution_kl",
            "rationale": (
                "Even when first-order summaries match, the distribution of "
                "pairwise similarities can diverge; KL or 2-sample MMD "
                "exposes this without relying on class labels."
            ),
            "failure_mode_guarded_against": "distributional mismatch",
            "implementation_hint": (
                "Estimate KL between pairwise-similarity histograms of real "
                "and generated samples, or use 2-sample MMD with an RBF kernel."
            ),
            "tags": ["generative_fidelity"],
        },
    ],
    "balanced_accuracy": [
        {
            "name": "hubness_skewness",
            "rationale": (
                "kNN-style accuracy is inflated or deflated by pathological "
                "neighbor graphs; skewness of the k-occurrence distribution "
                "quantifies hub dominance independent of the task.",
            ),
            "failure_mode_guarded_against": "pathological kNN neighbor graph",
            "requires_context": {"classifier_family": "kNN"},
            "implementation_hint": (
                "Compute Nk(x) = number of times x appears as a k-nearest "
                "neighbor of other points; report skewness of Nk."
            ),
            "tags": ["knn", "hubness"],
        },
        {
            "name": "antihub_fraction",
            "rationale": (
                "Complementary to hubness: fraction of points never chosen as "
                "a neighbor. Large antihub fractions silently bias kNN "
                "balanced accuracy."
            ),
            "failure_mode_guarded_against": "pathological kNN neighbor graph",
            "requires_context": {"classifier_family": "kNN"},
            "tags": ["knn", "hubness"],
        },
        {
            "name": "non_knn_linear_baseline",
            "rationale": (
                "A linear baseline (SVM or logistic regression) that reaches "
                "similar accuracy rules out neighborhood-specific effects and "
                "exposes generic classifier-agnostic improvements."
            ),
            "failure_mode_guarded_against": "generic classifier-agnostic uplift",
            "requires_context": {"classifier_family": "kNN"},
            "tags": ["knn", "baseline", "reference"],
        },
    ],
    "hubness_skewness": [
        {
            "name": "mutual_proximity_ordering_check",
            "rationale": (
                "Implementations of Mutual Proximity can introduce an "
                "ordering inversion that makes MP look worse than the "
                "original distance; a direct ordering check isolates this "
                "implementation pitfall from the method itself."
            ),
            "failure_mode_guarded_against": "MP ordering inversion artifact",
            "implementation_hint": (
                "For a sample of point pairs, verify that the MP distance "
                "ordering preserves the empirical-CDF interpretation; flag "
                "any systematic sign flip."
            ),
            "tags": ["hubness", "mutual_proximity"],
        },
        {
            "name": "local_scaling_vs_mp_comparison",
            "rationale": (
                "Local Scaling and Mutual Proximity normalize density "
                "differently; a side-by-side comparison prevents attributing "
                "outcomes to the wrong mechanism.",
            ),
            "failure_mode_guarded_against": "mis-attributed density-normalization effect",
            "tags": ["hubness", "local_scaling", "mutual_proximity"],
        },
    ],
    "edge_correlation": [
        {
            "name": "nearest_neighbor_overlap",
            "rationale": (
                "Global edge correlation can be high while the local "
                "neighborhood structure collapses. Measuring k-NN overlap "
                "between real and generated samples prevents this blind spot."
            ),
            "failure_mode_guarded_against": "global-local fidelity decoupling",
            "implementation_hint": (
                "For each generated sample, compute Jaccard overlap between "
                "its top-k neighbors in generated space and in real space."
            ),
            "tags": ["generative_fidelity", "local_structure"],
        },
        {
            "name": "gradient_shift_sign_stability",
            "rationale": (
                "High global correlation with unstable disease-effect or "
                "gradient-shift sign across splits indicates task-specific "
                "fidelity is not actually preserved."
            ),
            "failure_mode_guarded_against": "task-specific fidelity failure",
            "tags": ["generative_fidelity", "replication"],
        },
    ],
    "gradient_shift_correlation": [
        {
            "name": "label_heterogeneity_probe",
            "rationale": (
                "Sign instability of gradient-shift metrics across train/val "
                "splits is the expected signature of pooled heterogeneous "
                "class labels, not necessarily a model failure."
            ),
            "failure_mode_guarded_against": "heterogeneous-class-pool artifact",
            "implementation_hint": (
                "Stratify class 1 by sub-label (if available) and re-check "
                "gradient-shift stability within each stratum."
            ),
            "tags": ["replication", "label_quality"],
        },
    ],
    "label_permutation_pvalue": [
        {
            "name": "paired_sign_permutation",
            "rationale": (
                "Label permutation ignores the within-subject pairing "
                "structure that the primary test exploits; a paired "
                "sign-permutation variant checks that the effect is not "
                "carried by pairing alone."
            ),
            "failure_mode_guarded_against": "pairing-driven false positive",
            "tags": ["permutation", "paired_design"],
        },
        {
            "name": "non_knn_reference_permutation",
            "rationale": (
                "Repeating the permutation under a non-kNN classifier shows "
                "whether the significance is classifier-specific or generic."
            ),
            "failure_mode_guarded_against": "classifier-specific significance",
            "requires_context": {"classifier_family": "kNN"},
            "tags": ["permutation", "reference"],
        },
    ],
}

_COMPANION_DIAGNOSTIC_ALIASES: dict[str, str] = {
    "generative_reliability_ratio": "reliability_ratio",
    "reliability": "reliability_ratio",
    "balanced_acc": "balanced_accuracy",
    "knn_balanced_accuracy": "balanced_accuracy",
    "hub_skewness": "hubness_skewness",
    "hubness_skew": "hubness_skewness",
    "global_edge_corr": "edge_correlation",
    "edge_corr": "edge_correlation",
    "disease_effect_edge_corr": "edge_correlation",
    "gradient_shift_corr": "gradient_shift_correlation",
    "label_perm_pvalue": "label_permutation_pvalue",
    "label_perm_p": "label_permutation_pvalue",
}


def _normalize_companion_metric_key(raw: Any) -> str:
    text = _first_text_value(raw)
    if not text:
        return ""
    cleaned = re.sub(r"[\s\-]+", "_", text.strip().lower())
    cleaned = re.sub(r"[^a-z0-9_]+", "_", cleaned).strip("_")
    return _COMPANION_DIAGNOSTIC_ALIASES.get(cleaned, cleaned)


def _companion_context_matches(
    companion: dict[str, Any],
    context: dict[str, Any] | None,
) -> bool:
    requirement = companion.get("requires_context")
    if not isinstance(requirement, dict):
        return True
    if not isinstance(context, dict):
        # Requirement exists but caller gave no context — still surface it,
        # but the tool marks it as applies_if_context_matches=False so the
        # agent can decide.
        return True
    for key, expected in requirement.items():
        actual = context.get(key)
        if isinstance(expected, str) and isinstance(actual, str):
            if expected.strip().lower() != actual.strip().lower():
                return False
        elif actual != expected:
            return False
    return True


def _lookup_companion_diagnostics(
    metric_name: str,
    *,
    context: dict[str, Any] | None,
    top_k: int,
) -> tuple[list[dict[str, Any]], str, bool]:
    """Return (companions, normalized_metric_key, matched).

    Companions are deep-copied so callers never mutate the module-level table.
    Each companion carries ``applies_if_context_matches`` so callers can gate
    the suggestion on their execution context without hiding the entry.
    """

    normalized_key = _normalize_companion_metric_key(metric_name)
    if not normalized_key:
        return [], "", False
    entries = _COMPANION_DIAGNOSTIC_TABLE.get(normalized_key)
    if not entries:
        return [], normalized_key, False

    companions: list[dict[str, Any]] = []
    for entry in entries[:top_k]:
        companion = {
            "name": entry.get("name"),
            "rationale": entry.get("rationale"),
            "failure_mode_guarded_against": entry.get("failure_mode_guarded_against"),
        }
        if "value_band_hint" in entry:
            companion["value_band_hint"] = entry["value_band_hint"]
        if "implementation_hint" in entry:
            companion["implementation_hint"] = entry["implementation_hint"]
        if "requires_context" in entry:
            companion["requires_context"] = dict(entry["requires_context"])
            companion["applies_if_context_matches"] = _companion_context_matches(
                entry, context
            )
        if "tags" in entry:
            companion["tags"] = list(entry["tags"])
        companions.append(companion)
    return companions, normalized_key, True


def _research_session_has_directive(
    *,
    session_id: str,
    directive_id: str,
) -> bool:
    indexed_run_id = _lookup_research_session_run_id(session_id)
    if not indexed_run_id:
        return False
    try:
        run_dir = _find_run_dir(indexed_run_id)
    except Exception:
        return False
    for event in _load_jsonl_dicts(run_dir / _RESEARCH_EVENTS_FILENAME):
        tags = event.get("tags") or []
        context = _record_dict(event.get("context"))
        if (
            isinstance(tags, list)
            and "directive_issued" in tags
            and _first_text_value(context.get("directive_id")) == directive_id
        ):
            return True
    return False


def _load_or_create_research_run(
    session_id: str,
    *,
    run_id: str | None = None,
) -> tuple[RunRecord, Path, bool]:
    normalized_session_id = _first_text_value(session_id)
    if not normalized_session_id:
        raise ValueError("session_id is required")

    requested_run_id = _first_text_value(run_id)
    created = False
    managed_run = False

    record: RunRecord | None = None
    run_dir: Path | None = None
    candidate_run_id = requested_run_id
    if candidate_run_id:
        try:
            record, run_dir = _load_run_with_dir(candidate_run_id)
        except Exception:
            record = None
            run_dir = None

    if record is None and not requested_run_id:
        indexed_run_id = _lookup_research_session_run_id(normalized_session_id)
        if indexed_run_id:
            try:
                record, run_dir = _load_run_with_dir(indexed_run_id)
                managed_run = True
            except Exception:
                record = None
                run_dir = None

    if record is None:
        target_run_id = _new_run_id()
        run_dir = _run_dir(target_run_id)
        _ensure_run_layout(run_dir)
        now = _utc_iso()
        record = RunRecord(
            run_id=target_run_id,
            created_at=now,
            status="running",
            started_at=now,
            progress={
                "current_stage": "research_logging",
                "message": "Research logging session started",
                "last_progress_at": now,
            },
            timing_policy=_default_run_timing_policy(),
        )
        _save_run(record, run_dir=run_dir)
        created = True
        managed_run = True
        _record_research_session_run_id(
            normalized_session_id,
            target_run_id,
            updated_at=now,
        )

    _ensure_run_layout(run_dir)

    progress_meta = _record_dict(_record_dict(record.progress).get("research_logging"))
    existing_session_id = _first_text_value(progress_meta.get("session_id"))
    if existing_session_id and existing_session_id != normalized_session_id:
        raise ValueError(
            f"run_id {record.run_id} is already associated with session_id "
            f"{existing_session_id!r}"
        )

    provenance = _load_json_dict(run_dir / "provenance.json")
    provenance_meta = _record_dict(provenance.get("research_logging"))
    provenance_session_id = _first_text_value(provenance_meta.get("session_id"))
    if provenance_session_id and provenance_session_id != normalized_session_id:
        raise ValueError(
            f"run_id {record.run_id} already has research_logging session_id "
            f"{provenance_session_id!r}"
        )

    managed_run = bool(
        managed_run
        or created
        or provenance_meta.get("managed_run") is True
        or _first_text_value(provenance.get("route")) == "research_logging"
    )
    return record, run_dir, managed_run


def _next_research_event_metadata(
    record: RunRecord,
    *,
    session_id: str,
    client_session_id: str | None,
    source_client: str | None,
    source: str,
    managed_run: bool,
    event_kind: str,
    event_at: str,
) -> tuple[dict[str, Any], str]:
    progress = dict(record.progress or {})
    research_logging = _record_dict(progress.get("research_logging"))
    try:
        event_count = int(research_logging.get("event_count") or 0) + 1
    except Exception:
        event_count = 1
    event_id = f"research_evt_{event_count:04d}"

    research_logging.update(
        {
            "session_id": session_id,
            "client_session_id": client_session_id,
            "source_client": source_client,
            "source": source,
            "managed_run": bool(managed_run),
            "event_count": event_count,
            "last_event_id": event_id,
            "last_event_kind": event_kind,
            "last_event_at": event_at,
            "events_path": _RESEARCH_EVENTS_FILENAME,
        }
    )
    if event_kind == "start":
        research_logging["start_count"] = (
            int(research_logging.get("start_count") or 0) + 1
        )
    elif event_kind == "note":
        research_logging["note_count"] = (
            int(research_logging.get("note_count") or 0) + 1
        )
    elif event_kind == "auto":
        research_logging["auto_count"] = (
            int(research_logging.get("auto_count") or 0) + 1
        )
    elif event_kind == "snapshot":
        research_logging["snapshot_count"] = (
            int(research_logging.get("snapshot_count") or 0) + 1
        )
        research_logging["snapshot_path"] = _SESSION_SNAPSHOT_FILENAME
    progress["research_logging"] = research_logging
    record.progress = progress
    return research_logging, event_id


def _research_logging_counter(meta: dict[str, Any], key: str) -> int:
    try:
        return int(meta.get(key) or 0)
    except Exception:
        return 0


def _load_research_session_snapshot_payload(
    record: RunRecord,
    *,
    run_dir: Path,
) -> dict[str, Any]:
    progress = _record_dict(record.progress)
    snapshot = _record_dict(progress.get("session_snapshot"))
    if snapshot:
        return snapshot
    return _load_json_dict(run_dir / _SESSION_SNAPSHOT_FILENAME)


def _research_session_is_closed(record: RunRecord, *, run_dir: Path) -> bool:
    progress = _record_dict(record.progress)
    research_logging = _record_dict(progress.get("research_logging"))
    if _first_text_value(research_logging.get("last_event_kind")) == "snapshot":
        return True
    return bool(_load_research_session_snapshot_payload(record, run_dir=run_dir))


def _research_snapshot_matches(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    if not existing:
        return False
    keys = (
        "goal",
        "next_command",
        "session_id",
        "client_session_id",
        "source_client",
        "run_id",
        "source",
    )
    for key in keys:
        if _first_text_value(existing.get(key)) != _first_text_value(
            candidate.get(key)
        ):
            return False
    return (
        _coerce_non_empty_str_list(existing.get("done"))
        == _coerce_non_empty_str_list(candidate.get("done"))
        and _coerce_non_empty_str_list(existing.get("open"))
        == _coerce_non_empty_str_list(candidate.get("open"))
        and _coerce_non_empty_str_list(existing.get("tags"))
        == _coerce_non_empty_str_list(candidate.get("tags"))
    )


def _research_context_trace_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_rows = context.get("trace_events")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("external_trace_events")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("tool_trace")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("tool_trace_events")
    if not isinstance(raw_rows, list):
        return rows
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        event_type = _first_text_value(raw_row.get("event_type"))
        if not event_type:
            continue
        payload = _record_dict(raw_row.get("payload"))
        for key in ("tool_id", "tool", "tool_call_id", "status", "state", "error"):
            value = raw_row.get(key)
            if value is not None and key not in payload:
                payload[key] = value
        rows.append(
            {
                "event_type": event_type,
                "timestamp": _first_text_value(
                    raw_row.get("timestamp"),
                    raw_row.get("created_at"),
                    raw_row.get("time"),
                ),
                "payload": payload,
                "tool_name": _first_text_value(
                    raw_row.get("tool_name"),
                    raw_row.get("tool_id"),
                    payload.get("tool_id"),
                    payload.get("tool"),
                ),
            }
        )
    return rows


def _research_context_conversation_rows(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_rows = context.get("transcript")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("messages")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("chat_history")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("conversation_events")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("conversation_messages")
    if not isinstance(raw_rows, list):
        raw_rows = context.get("conversation_log")
    if not isinstance(raw_rows, list):
        return rows
    for index, raw_row in enumerate(raw_rows, start=1):
        if isinstance(raw_row, str):
            content = _first_text_value(raw_row)
            role = "unknown"
            timestamp = None
            metadata: dict[str, Any] = {}
            message_id = None
            name = None
            turn_id = f"turn_{index}"
            kind = None
        elif isinstance(raw_row, dict):
            content = _first_text_value(
                raw_row.get("content"),
                raw_row.get("text"),
                raw_row.get("message"),
            )
            role = (
                _first_text_value(
                    raw_row.get("role"),
                    raw_row.get("source"),
                    raw_row.get("speaker"),
                )
                or "unknown"
            )
            timestamp = _first_text_value(
                raw_row.get("timestamp"),
                raw_row.get("created_at"),
                raw_row.get("time"),
            )
            message_id = _first_text_value(
                raw_row.get("message_id"),
                raw_row.get("messageId"),
                raw_row.get("id"),
            )
            name = _first_text_value(raw_row.get("name"))
            turn_id = (
                _first_text_value(raw_row.get("turn_id"))
                or message_id
                or f"turn_{index}"
            )
            kind = _first_text_value(raw_row.get("kind"), raw_row.get("type"))
            metadata = _record_dict(raw_row.get("metadata"))
            extras = {
                key: value
                for key, value in raw_row.items()
                if key
                not in {
                    "role",
                    "source",
                    "speaker",
                    "content",
                    "text",
                    "message",
                    "timestamp",
                    "created_at",
                    "time",
                    "message_id",
                    "messageId",
                    "id",
                    "name",
                    "turn_id",
                    "kind",
                    "type",
                    "metadata",
                }
                and value is not None
            }
            if extras:
                metadata = dict(metadata)
                metadata["extra"] = extras
        else:
            continue
        if not content:
            continue
        rows.append(
            {
                "message_id": message_id if isinstance(raw_row, dict) else None,
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "name": name,
                "turn_id": turn_id,
                "kind": kind,
                "metadata": metadata,
            }
        )
    return rows


def _research_context_for_event_payload(
    context: dict[str, Any],
    *,
    attached_trace_count: int = 0,
    attached_conversation_count: int = 0,
) -> dict[str, Any]:
    if not context:
        return {}
    trimmed = dict(context)
    for key in (
        "trace_events",
        "external_trace_events",
        "tool_trace",
        "tool_trace_events",
        "transcript",
        "messages",
        "chat_history",
        "conversation_events",
        "conversation_messages",
        "conversation_log",
    ):
        trimmed.pop(key, None)
    if attached_trace_count > 0:
        trimmed["attached_trace_event_count"] = attached_trace_count
    if attached_conversation_count > 0:
        trimmed["attached_conversation_message_count"] = attached_conversation_count
    return trimmed


def _append_research_conversation_rows(
    run_dir: Path,
    *,
    session_id: str,
    run_id: str,
    event_id: str,
    source_client: str | None,
    rows: list[dict[str, Any]],
    fallback_timestamp: str,
) -> int:
    conversation_path = run_dir / _RESEARCH_CONVERSATION_LOG_FILENAME
    transcript_path = run_dir / _SESSION_TRANSCRIPT_FILENAME
    existing_message_ids = {
        _first_text_value(row.get("message_id"))
        for row in _load_jsonl_dicts(conversation_path)
        if _first_text_value(row.get("message_id"))
    }
    count = 0
    for index, row in enumerate(rows, start=1):
        explicit_message_id = _first_text_value(row.get("message_id"))
        if explicit_message_id and explicit_message_id in existing_message_ids:
            continue
        payload = {
            "message_id": explicit_message_id or f"{event_id}.msg.{index:03d}",
            "event_id": event_id,
            "session_id": session_id,
            "run_id": run_id,
            "source_client": source_client,
            "timestamp": _first_text_value(row.get("timestamp")) or fallback_timestamp,
            "role": _first_text_value(row.get("role")) or "unknown",
            "content": _first_text_value(row.get("content")) or "",
            "name": _first_text_value(row.get("name")),
            "turn_id": _first_text_value(row.get("turn_id"))
            or explicit_message_id
            or f"{event_id}.turn.{index:03d}",
            "kind": _first_text_value(row.get("kind")),
            "metadata": _record_dict(row.get("metadata")),
        }
        if not payload["content"]:
            continue
        _append_jsonl_record(conversation_path, payload)
        _append_jsonl_record(transcript_path, payload)
        existing_message_ids.add(payload["message_id"])
        count += 1
    return count


def _load_research_conversation_rows(run_dir: Path) -> list[dict[str, Any]]:
    transcript_rows = _load_jsonl_dicts(run_dir / _SESSION_TRANSCRIPT_FILENAME)
    if transcript_rows:
        return transcript_rows
    return _load_jsonl_dicts(run_dir / _RESEARCH_CONVERSATION_LOG_FILENAME)


def _research_tool_trace_result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"result_type": type(result).__name__}
    summary = {
        "ok": result.get("ok"),
        "status": _first_text_value(result.get("status")),
        "error": _first_text_value(result.get("error")),
        "run_id": _first_text_value(result.get("run_id")),
        "session_id": _first_text_value(result.get("session_id")),
        "kind": _first_text_value(result.get("kind")),
    }
    data = _record_dict(result.get("data"))
    if data:
        summary["data_status"] = _first_text_value(data.get("status"))
    summary["result_keys"] = sorted(str(key) for key in result.keys())
    return {key: value for key, value in summary.items() if value not in (None, "", [])}


def _append_research_tool_trace_row(
    run_dir: Path,
    *,
    session_id: str,
    client_session_id: str | None,
    source_client: str | None,
    run_id: str,
    event_type: str,
    tool_name: str | None = None,
    timestamp: str | None = None,
    arguments: dict[str, Any] | None = None,
    result: Any = None,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
    attached_via_event_id: str | None = None,
) -> dict[str, Any]:
    safe_payload = _record_dict(payload)
    row = {
        "trace_id": f"tool_trace_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "timestamp": _first_text_value(timestamp) or _utc_iso(),
        "session_id": session_id,
        "client_session_id": client_session_id,
        "source_client": source_client,
        "run_id": run_id,
        "tool_name": _first_text_value(
            tool_name,
            safe_payload.get("tool_name"),
            safe_payload.get("tool_id"),
            safe_payload.get("tool"),
        ),
        "arguments": arguments if isinstance(arguments, dict) else {},
        "payload": safe_payload,
        "result": _research_tool_trace_result_summary(result),
        "error": _first_text_value(error),
        "attached_via_event_id": _first_text_value(attached_via_event_id),
    }
    _append_jsonl_record(run_dir / _RESEARCH_TOOL_TRACE_FILENAME, row)
    return row


def _record_research_tool_trace(
    *,
    binding: dict[str, Any] | None,
    event_type: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    result: Any = None,
    error: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(binding, dict):
        return None
    session_id = _first_text_value(binding.get("session_id"))
    if not session_id or tool_name in _RESEARCH_AUTO_EXCLUDED_TOOLS:
        return None
    try:
        record, run_dir, _managed_run = _load_or_create_research_run(
            session_id,
            run_id=_first_text_value(binding.get("run_id")),
        )
    except Exception:
        return None
    row = _append_research_tool_trace_row(
        run_dir,
        session_id=session_id,
        client_session_id=_first_text_value(binding.get("client_session_id")),
        source_client=_normalize_research_source_client(binding.get("source_client")),
        run_id=record.run_id,
        event_type=event_type,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        error=error,
        payload=payload,
    )
    trace_payload = {
        "trace_id": _first_text_value(row.get("trace_id")),
        "tool_id": tool_name,
        "tool_name": tool_name,
        "arguments": arguments if isinstance(arguments, dict) else {},
        "error": _first_text_value(error),
        "result": _research_tool_trace_result_summary(result),
    }
    if isinstance(payload, dict):
        trace_payload["payload"] = payload
    _emit_trace_event(
        _research_trace_logger(),
        run_dir,
        run_id=record.run_id,
        event_type=event_type,
        payload=trace_payload,
    )
    return row


def _research_logging_progress(record: RunRecord) -> dict[str, Any]:
    return _record_dict(_record_dict(record.progress).get("research_logging"))


def _research_session_has_start(
    record: RunRecord,
    *,
    run_dir: Path,
) -> bool:
    progress = _research_logging_progress(record)
    if _research_logging_counter(progress, "start_count") > 0:
        return True
    events = _load_jsonl_dicts(run_dir / _RESEARCH_EVENTS_FILENAME)
    return any(str(row.get("kind") or "") == "start" for row in events)


def _persist_research_logging_provenance(
    *,
    run_dir: Path,
    record: RunRecord,
    session_id: str,
    client_session_id: str | None,
    source_client: str | None,
    source: str,
    managed_run: bool,
    last_write_tool: str,
    last_event_kind: str,
    request_payload: dict[str, Any],
    updated_at: str,
) -> None:
    path = run_dir / "provenance.json"
    provenance = _load_json_dict(path)
    if not provenance:
        provenance = {
            "run_id": record.run_id,
            "mode": "mcp",
            "transport": DEFAULT_TRANSPORT,
        }
    provenance.setdefault("run_id", record.run_id)
    provenance.setdefault("mode", "mcp")
    provenance.setdefault("transport", DEFAULT_TRANSPORT)
    if managed_run:
        provenance["route"] = "research_logging"
        provenance["request"] = request_payload
    research_logging = _record_dict(provenance.get("research_logging"))
    research_logging.update(
        {
            "session_id": session_id,
            "client_session_id": client_session_id,
            "source_client": source_client,
            "source": source,
            "managed_run": bool(managed_run),
            "last_write_tool": last_write_tool,
            "last_event_kind": last_event_kind,
            "updated_at": updated_at,
            "events_path": _RESEARCH_EVENTS_FILENAME,
        }
    )
    if last_event_kind == "snapshot":
        research_logging["snapshot_path"] = _SESSION_SNAPSHOT_FILENAME
    provenance["research_logging"] = research_logging
    provenance["state"] = record.status
    if record.error:
        provenance["error"] = record.error
    _atomic_write_json(path, _redact_for_logging(provenance))


def _emit_trace_event(
    log_trace: Any,
    run_dir: Path,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if log_trace is None:
        return
    try:
        log_trace(
            run_dir,
            run_id=run_id,
            event_type=event_type,
            payload=_redact_for_logging(payload),
        )
    except Exception:
        pass


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _iso_to_epoch_ms(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        ts = ts.strip()
        if not ts:
            return None
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Run store (filesystem-backed)
# ---------------------------------------------------------------------------


# Run-store substrate now lives in mcp/runstore.py (Track B). Re-exported here
# so existing ``server.<name>`` references (in-process callers + tests) keep
# resolving; runstore owns RUN_ROOT and reads it live, so redirecting
# ``runstore.RUN_ROOT`` is observed everywhere.
from brain_researcher.services.mcp.runstore import (  # noqa: E402
    RunRecord,
    StepRecord,
    _atomic_write_json,
    _find_run_dir,
    _load_run,
    _load_run_with_dir,
    _new_run_id,
    _run_dir,
    _run_record_from_json,
    _save_run,
)


def _compat_alias_usage_path() -> Path:
    return _runstore.RUN_ROOT / "compat_alias_usage.json"


def _load_compat_alias_usage_snapshot() -> dict[str, Any]:
    path = _compat_alias_usage_path()
    if not path.exists():
        return {
            "schema_version": _MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION,
            "updated_at": None,
            "aliases": {},
            "recent_events": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "schema_version": _MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION,
            "updated_at": None,
            "aliases": {},
            "recent_events": [],
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": _MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION,
            "updated_at": None,
            "aliases": {},
            "recent_events": [],
        }
    payload.setdefault("schema_version", _MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION)
    payload.setdefault("updated_at", None)
    payload.setdefault("aliases", {})
    payload.setdefault("recent_events", [])
    return payload


def _compat_alias_usage_summary(*, top_k: int | None = None) -> dict[str, Any]:
    snapshot = _load_compat_alias_usage_snapshot()
    alias_rows: list[dict[str, Any]] = []
    aliases = snapshot.get("aliases")
    total_calls = 0
    if isinstance(aliases, dict):
        for alias_name, raw in aliases.items():
            if not isinstance(raw, dict):
                continue
            count = int(raw.get("count") or 0)
            total_calls += count
            alias_rows.append(
                {
                    "alias_name": str(alias_name),
                    "canonical_name": str(
                        raw.get("canonical_name")
                        or _MCP_COMPAT_ALIAS_TARGETS.get(str(alias_name), "")
                    ),
                    "count": count,
                    "first_used_at": raw.get("first_used_at"),
                    "last_used_at": raw.get("last_used_at"),
                    "last_param_keys": list(raw.get("last_param_keys") or []),
                }
            )
    alias_rows.sort(
        key=lambda item: (
            -int(item.get("count") or 0),
            str(item.get("alias_name") or ""),
        )
    )
    if top_k is not None:
        alias_rows = alias_rows[: max(1, int(top_k))]

    recent_events = snapshot.get("recent_events")
    if not isinstance(recent_events, list):
        recent_events = []

    return {
        "schema_version": _MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION,
        "record_path": str(_compat_alias_usage_path()),
        "updated_at": snapshot.get("updated_at"),
        "total_calls": total_calls,
        "distinct_aliases": (
            len(alias_rows)
            if top_k is None
            else len(
                [
                    raw
                    for raw in (snapshot.get("aliases") or {}).values()
                    if isinstance(raw, dict)
                ]
            )
        ),
        "aliases": alias_rows,
        "recent_events": recent_events[-10:],
    }


def _record_compat_alias_usage(
    alias_name: str,
    *,
    param_keys: list[str] | None = None,
) -> None:
    alias = str(alias_name or "").strip()
    if not alias:
        return
    canonical_name = _MCP_COMPAT_ALIAS_TARGETS.get(alias, "")
    now = _utc_iso()
    path = _compat_alias_usage_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    safe_param_keys = sorted(
        {
            str(key)
            for key in (param_keys or [])
            if str(key).strip()
            and str(key).strip() not in _MCP_COMPAT_ALIAS_RUNTIME_PARAM_KEYS
        }
    )
    event = {
        "ts": now,
        "alias_name": alias,
        "canonical_name": canonical_name,
        "param_keys": safe_param_keys,
    }

    with _MCP_COMPAT_ALIAS_USAGE_LOCK:
        snapshot = _load_compat_alias_usage_snapshot()
        aliases = snapshot.get("aliases")
        if not isinstance(aliases, dict):
            aliases = {}
            snapshot["aliases"] = aliases
        entry = aliases.get(alias)
        if not isinstance(entry, dict):
            entry = {
                "alias_name": alias,
                "canonical_name": canonical_name,
                "count": 0,
                "first_used_at": now,
                "last_used_at": now,
                "last_param_keys": safe_param_keys,
            }
            aliases[alias] = entry

        entry["canonical_name"] = canonical_name
        entry["count"] = int(entry.get("count") or 0) + 1
        entry.setdefault("first_used_at", now)
        entry["last_used_at"] = now
        entry["last_param_keys"] = safe_param_keys

        recent_events = snapshot.get("recent_events")
        if not isinstance(recent_events, list):
            recent_events = []
        recent_events.append(event)
        snapshot["recent_events"] = recent_events[
            -_MCP_COMPAT_ALIAS_USAGE_RECENT_LIMIT:
        ]
        snapshot["updated_at"] = now
        snapshot["schema_version"] = _MCP_COMPAT_ALIAS_USAGE_SCHEMA_VERSION
        try:
            _atomic_write_json(path, snapshot)
        except Exception as exc:
            logger.warning(
                "Failed to persist MCP compat alias usage telemetry: %s", exc
            )


def _return_compat_alias_response(
    alias_name: str,
    response: dict[str, Any],
    *,
    param_keys: list[str] | None = None,
) -> dict[str, Any]:
    _record_compat_alias_usage(alias_name, param_keys=param_keys)
    return response


def _background_launch_response(
    run_id: str,
    *,
    run_dir: Path,
    compat_poll_tool: str | None = None,
    data: dict[str, Any] | None = None,
    execution_trace: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "status": "queued",
        "run_dir": str(run_dir),
        "execution_mode": "background",
        "execution_trace": list(
            execution_trace or ["validated", "queued_background_run"]
        ),
        "poll_tool": "run_get",
    }
    if compat_poll_tool:
        response["compat_poll_tool"] = compat_poll_tool
    if data is not None:
        response["data"] = data
    if extra:
        response.update(extra)
    return response


_DEFAULT_RUN_HEARTBEAT_INTERVAL_SECONDS = _env_int(
    "BR_MCP_RUN_HEARTBEAT_INTERVAL_SECONDS", 30, min_value=5
)
_DEFAULT_RUN_STALL_TIMEOUT_SECONDS = _env_int(
    "BR_MCP_RUN_STALL_TIMEOUT_SECONDS",
    max(120, _DEFAULT_RUN_HEARTBEAT_INTERVAL_SECONDS * 3),
    min_value=30,
)
_DEFAULT_RUN_SOFT_TIMEOUT_SECONDS = _env_int(
    "BR_MCP_RUN_SOFT_TIMEOUT_SECONDS", 300, min_value=30
)
_DEFAULT_RUN_HARD_TIMEOUT_SECONDS = _env_int(
    "BR_MCP_RUN_HARD_TIMEOUT_SECONDS", 1800, min_value=60
)


def _default_run_timing_policy() -> dict[str, int]:
    return {
        "heartbeat_interval_seconds": _DEFAULT_RUN_HEARTBEAT_INTERVAL_SECONDS,
        "stall_timeout_seconds": _DEFAULT_RUN_STALL_TIMEOUT_SECONDS,
        "soft_timeout_seconds": _DEFAULT_RUN_SOFT_TIMEOUT_SECONDS,
        "hard_timeout_seconds": _DEFAULT_RUN_HARD_TIMEOUT_SECONDS,
    }


def _update_run_progress(
    record: RunRecord,
    *,
    stage: str | None = None,
    message: str | None = None,
    progress_pct: float | int | None = None,
    step_index: int | None = None,
    timestamp: str | None = None,
) -> None:
    now = timestamp or _utc_iso()
    payload = dict(record.progress or {})
    if stage is not None:
        payload["current_stage"] = str(stage)
    if message is not None:
        payload["message"] = str(message)
    if progress_pct is not None:
        try:
            payload["progress_pct"] = float(progress_pct)
        except Exception:
            pass
    payload["last_progress_at"] = now
    record.progress = payload
    if step_index is None or step_index < 0 or step_index >= len(record.steps):
        return
    step_payload = dict(record.steps[step_index].progress or {})
    if stage is not None:
        step_payload["current_stage"] = str(stage)
    if message is not None:
        step_payload["message"] = str(message)
    if progress_pct is not None:
        try:
            step_payload["progress_pct"] = float(progress_pct)
        except Exception:
            pass
    step_payload["last_progress_at"] = now
    record.steps[step_index].progress = step_payload


def _set_run_stage(
    run_id: str,
    *,
    stage: str,
    message: str | None = None,
    progress_pct: float | int | None = None,
    step_index: int | None = None,
    run_dir: Path | None = None,
) -> None:
    lock = _get_run_lock(run_id)
    with lock:
        record, resolved_run_dir = _load_run_with_dir(run_id)
        _update_run_progress(
            record,
            stage=stage,
            message=message,
            progress_pct=progress_pct,
            step_index=step_index,
        )
        _save_run(record, run_dir=run_dir or resolved_run_dir)


def _start_run_heartbeat(
    run_id: str,
    *,
    stage: str,
    message: str | None = None,
    progress_pct: float | int | None = None,
    step_index: int | None = None,
    run_dir: Path | None = None,
    interval_seconds: int | None = None,
) -> threading.Event:
    stop_event = threading.Event()
    interval = max(
        1,
        int(
            interval_seconds
            or _default_run_timing_policy()["heartbeat_interval_seconds"]
        ),
    )

    def _heartbeat() -> None:
        while not stop_event.wait(interval):
            try:
                lock = _get_run_lock(run_id)
                with lock:
                    record, resolved_run_dir = _load_run_with_dir(run_id)
                    current_progress = dict(record.progress or {})
                    _update_run_progress(
                        record,
                        stage=(
                            stage if not current_progress.get("current_stage") else None
                        ),
                        message=(
                            message if not current_progress.get("message") else None
                        ),
                        progress_pct=(
                            progress_pct
                            if progress_pct is not None
                            and current_progress.get("progress_pct") is None
                            else None
                        ),
                        step_index=step_index,
                    )
                    _save_run(record, run_dir=run_dir or resolved_run_dir)
            except Exception:
                return

    threading.Thread(target=_heartbeat, daemon=True).start()
    return stop_event


def _run_progress_snapshot(run_payload: dict[str, Any]) -> dict[str, Any]:
    progress = dict(run_payload.get("progress") or {})
    policy = dict(run_payload.get("timing_policy") or {})
    current_stage = progress.get("current_stage")
    message = progress.get("message")
    progress_pct = progress.get("progress_pct")
    last_progress_at = (
        progress.get("last_progress_at")
        or run_payload.get("started_at")
        or run_payload.get("created_at")
    )
    created_at = run_payload.get("created_at")
    started_at = run_payload.get("started_at") or created_at
    now_ms = _epoch_ms()
    silence_seconds = None
    last_progress_ms = _iso_to_epoch_ms(str(last_progress_at or ""))
    if last_progress_ms is not None:
        silence_seconds = max(0.0, (now_ms - last_progress_ms) / 1000.0)
    elapsed_seconds = None
    started_ms = _iso_to_epoch_ms(str(started_at or ""))
    if started_ms is not None:
        elapsed_seconds = max(0.0, (now_ms - started_ms) / 1000.0)
    stall_timeout_seconds = policy.get("stall_timeout_seconds")
    active = str(run_payload.get("status") or "") in _MCP_RUN_ACTIVE_STATUSES
    stalled = bool(
        active
        and isinstance(silence_seconds, int | float)
        and isinstance(stall_timeout_seconds, int | float)
        and silence_seconds >= float(stall_timeout_seconds)
    )
    return {
        "current_stage": current_stage,
        "message": message,
        "progress_pct": progress_pct,
        "last_progress_at": last_progress_at,
        "silence_seconds": silence_seconds,
        "elapsed_seconds": elapsed_seconds,
        "stalled": stalled,
        "timing_policy": policy,
    }


def _load_delegated_execution_marker(run_dir: Path) -> dict[str, Any] | None:
    provenance_path = run_dir / "provenance.json"
    if not provenance_path.exists():
        return None
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    marker = payload.get("delegated_execution")
    return marker if isinstance(marker, dict) else None


def _proxy_agent_run_status(run_id: str) -> dict[str, Any] | None:
    proxied = _proxy_agent_run_payload(run_id)
    if proxied is None:
        return None
    if proxied.get("ok") is not True:
        return proxied
    run_payload = {k: v for k, v in proxied.items() if k not in {"ok"}}
    normalized_status = _normalize_agent_run_status(run_payload.get("status"))
    if normalized_status:
        run_payload["status"] = normalized_status
    run_dir = run_payload.pop("run_dir", None)
    return {"ok": True, "run": run_payload, "run_dir": run_dir}


_MCP_RUN_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "review_blocked"}
_MCP_RUN_ACTIVE_STATUSES = {"queued", "running"}


def _normalize_agent_run_status(raw_status: Any) -> str | None:
    token = str(raw_status or "").strip().lower()
    if not token:
        return None
    if token in {"completed", "complete", "done", "success", "successful", "succeeded"}:
        return "succeeded"
    if token in {"failed", "failure", "error", "errored", "timeout"}:
        return "failed"
    if token in {"cancelled", "canceled", "cancelling", "canceling"}:
        return "cancelled"
    if token in {
        "running",
        "claimed",
        "active",
        "processing",
        "in_progress",
        "in-progress",
    }:
        return "running"
    if token in {
        "pending",
        "queued",
        "accepted",
        "created",
        "waiting",
        "retrying",
        "paused",
    }:
        return "queued"
    return token


def _coerce_agent_timestamp(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(value)))
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric_value = float(text)
    except ValueError:
        numeric_value = None
    if numeric_value is not None:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(numeric_value))
    try:
        parsed = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(parsed)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return text


def _agent_run_error_message(run_payload: dict[str, Any]) -> str | None:
    for key in ("error", "error_message", "detail", "message"):
        value = run_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _update_run_provenance_state(
    run_dir: Path,
    *,
    state: str,
    error: str | None = None,
) -> None:
    provenance_path = run_dir / "provenance.json"
    payload: dict[str, Any] = {}
    if provenance_path.exists():
        try:
            raw = json.loads(provenance_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}
    payload["state"] = state
    if error:
        payload["error"] = error
    else:
        payload.pop("error", None)
    _atomic_write_json(provenance_path, _redact_for_logging(payload))


def _reconcile_delegated_run_record(
    record: RunRecord,
    *,
    run_dir: Path,
    proxied_run: dict[str, Any],
) -> RunRecord:
    normalized_status = _normalize_agent_run_status(proxied_run.get("status"))
    if not normalized_status:
        return record

    started_at = _coerce_agent_timestamp(proxied_run.get("started_at"))
    finished_at = _coerce_agent_timestamp(proxied_run.get("finished_at"))
    error_message = _agent_run_error_message(proxied_run)
    if normalized_status in _MCP_RUN_TERMINAL_STATUSES and not finished_at:
        finished_at = _utc_iso()

    changed = False
    if record.status != normalized_status:
        record.status = normalized_status
        changed = True
    if started_at and record.started_at != started_at:
        record.started_at = started_at
        changed = True
    if finished_at and record.finished_at != finished_at:
        record.finished_at = finished_at
        changed = True
    if normalized_status == "failed":
        if error_message and record.error != error_message:
            record.error = error_message
            changed = True
    elif normalized_status == "cancelled":
        cancel_error = error_message or "cancelled"
        if record.error != cancel_error:
            record.error = cancel_error
            changed = True
    elif record.error is not None:
        record.error = None
        changed = True

    if record.steps:
        current = record.steps[0]
        desired_step_status = {
            "queued": "queued",
            "running": "running",
            "succeeded": "succeeded",
            "failed": "failed",
        }.get(normalized_status)
        if desired_step_status and current.status != desired_step_status:
            current.status = desired_step_status
            changed = True
        if started_at and current.started_at != started_at:
            current.started_at = started_at
            changed = True
        if (
            finished_at
            and normalized_status in {"succeeded", "failed"}
            and current.finished_at != finished_at
        ):
            current.finished_at = finished_at
            changed = True
        if normalized_status == "failed":
            if error_message and current.error != error_message:
                current.error = error_message
                changed = True
        elif normalized_status == "succeeded" and current.error is not None:
            current.error = None
            changed = True

    if changed:
        _save_run(record, run_dir=run_dir)
        _update_run_provenance_state(run_dir, state=record.status, error=record.error)
    return record


def _maybe_sync_delegated_run_record(
    run_id: str,
    record: RunRecord,
    run_dir: Path,
) -> tuple[RunRecord, dict[str, Any] | None]:
    marker = _load_delegated_execution_marker(run_dir)
    if not isinstance(marker, dict):
        return record, None
    backend = str(marker.get("backend") or "")
    if backend == "agent":
        if record.status in _MCP_RUN_TERMINAL_STATUSES:
            return record, None
        proxied = _proxy_agent_run_status(run_id)
        if proxied is None or proxied.get("ok") is not True:
            return record, proxied
        proxied_run = proxied.get("run")
        if isinstance(proxied_run, dict):
            lock = _get_run_lock(run_id)
            with lock:
                try:
                    fresh_record, fresh_run_dir = _load_run_with_dir(run_id)
                except Exception:
                    fresh_record, fresh_run_dir = record, run_dir
                record = _reconcile_delegated_run_record(
                    fresh_record,
                    run_dir=fresh_run_dir,
                    proxied_run=proxied_run,
                )
        return record, proxied
    if backend == "google_deep_research":
        interaction_id = str(marker.get("interaction_id") or "").strip()
        if not interaction_id:
            return record, {"ok": False, "error": "missing_interaction_id"}
        if (
            record.status in _MCP_RUN_TERMINAL_STATUSES
            and _load_google_deep_research_result(run_dir) is not None
        ):
            return record, None
        result = _google_deep_research_fetch(interaction_id, include_raw=False)
        if result.get("ok") is not True:
            return record, result
        data = result.get("data")
        if isinstance(data, dict):
            lock = _get_run_lock(run_id)
            with lock:
                try:
                    fresh_record, fresh_run_dir = _load_run_with_dir(run_id)
                except Exception:
                    fresh_record, fresh_run_dir = record, run_dir
                record = _reconcile_google_deep_research_run_record(
                    fresh_record,
                    run_dir=fresh_run_dir,
                    data=data,
                )
        return record, None
    return record, None


_RUN_LOCKS: dict[str, threading.Lock] = {}
_RUN_LOCKS_GUARD = threading.Lock()


def _get_run_lock(run_id: str) -> threading.Lock:
    with _RUN_LOCKS_GUARD:
        if run_id not in _RUN_LOCKS:
            _RUN_LOCKS[run_id] = threading.Lock()
        return _RUN_LOCKS[run_id]


# ---------------------------------------------------------------------------
# Plan schema
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    step_id: str | None = None
    work_dir: str | None = None
    output_dir: str | None = None


@dataclass
class Plan:
    steps: list[PlanStep]
    project_root: str | None = None
    run_tag: str | None = None


_STEP_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")
_PLAN_STEP_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _sanitize_plan_step_id(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    cleaned = _STEP_ID_SAFE_RE.sub("-", text).strip(".-_")
    return cleaned or None


def _validate_plan_step_id(raw: Any, *, field_name: str, step_index: int) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if not _PLAN_STEP_ID_RE.fullmatch(text):
        raise ValueError(
            f"plan.steps[{step_index}].{field_name} must match "
            r"^[A-Za-z_][A-Za-z0-9_-]*$"
        )
    return text


def _coerce_plan(raw: dict[str, Any]) -> Plan:
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError("plan.steps must be a non-empty list")
    steps: list[PlanStep] = []
    seen_step_ids: set[str] = set()
    for i, item in enumerate(steps_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"plan.steps[{i}] must be an object")
        tool = item.get("tool") or item.get("tool_id") or item.get("name")
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError(f"plan.steps[{i}].tool is required")
        params = item.get("params") or item.get("parameters") or {}
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError(f"plan.steps[{i}].params must be an object")
        step_id = _validate_plan_step_id(
            item.get("step_id"), field_name="step_id", step_index=i
        )
        if step_id is None:
            step_id = _validate_plan_step_id(
                item.get("id"), field_name="id", step_index=i
            )
        if step_id is None:
            step_id = _sanitize_plan_step_id(item.get("name"))
        if step_id:
            if step_id in seen_step_ids:
                raise ValueError(f"plan.steps[{i}] has duplicate step_id '{step_id}'")
            seen_step_ids.add(step_id)
        steps.append(
            PlanStep(
                tool=tool.strip(),
                params=params,
                step_id=step_id,
                work_dir=item.get("work_dir"),
                output_dir=item.get("output_dir"),
            )
        )
    project_root = raw.get("project_root")
    if project_root is not None and (
        not isinstance(project_root, str) or not project_root.strip()
    ):
        raise ValueError("plan.project_root must be a non-empty string when provided")

    run_tag = raw.get("run_tag")
    if run_tag is not None and (not isinstance(run_tag, str) or not run_tag.strip()):
        raise ValueError("plan.run_tag must be a non-empty string when provided")

    return Plan(
        steps=steps,
        project_root=project_root.strip() if isinstance(project_root, str) else None,
        run_tag=run_tag.strip() if isinstance(run_tag, str) else None,
    )


_RUN_TAG_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_WORKSPACE_LAYOUT_DIRS = [
    "00_manifest",
    "01_inputs",
    "02_cache",
    "03_work",
    "04_artifacts",
    "05_reports",
    "06_logs",
    "07_figures",
    "08_exports",
]


def _normalize_run_tag(raw: str | None, fallback: str) -> str:
    text = (raw or "").strip()
    if not text:
        return fallback
    cleaned = _RUN_TAG_SAFE_RE.sub("-", text).strip(".-_")
    if not cleaned:
        return fallback
    return cleaned[:96]


def _resolve_plan_workspace(
    plan: Plan,
    *,
    run_id: str,
) -> tuple[Path | None, str | None, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []

    if not plan.project_root:
        if plan.run_tag:
            issues.append(
                {
                    "level": "warn",
                    "code": "run_tag_ignored",
                    "message": (
                        "plan.run_tag is ignored unless plan.project_root is provided."
                    ),
                }
            )
        return None, None, issues

    try:
        project_root = _require_allowed_path(
            Path(plan.project_root), kind="project_root"
        )
    except ValueError as exc:
        issues.append(
            {
                "level": "error",
                "code": "path_not_allowed",
                "message": str(exc),
            }
        )
        return None, None, issues

    run_tag = _normalize_run_tag(plan.run_tag, run_id)
    workspace = project_root / "runs" / run_tag
    try:
        workspace = _require_allowed_path(workspace, kind="run_workspace")
    except ValueError as exc:
        issues.append(
            {
                "level": "error",
                "code": "path_not_allowed",
                "message": str(exc),
            }
        )
        return None, run_tag, issues

    return workspace, run_tag, issues


def _ensure_workspace_layout(run_workspace: Path) -> None:
    for rel in _WORKSPACE_LAYOUT_DIRS:
        (run_workspace / rel).mkdir(parents=True, exist_ok=True)


def _normalize_policy_host(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if not value:
        return None
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if value.endswith("."):
        value = value[:-1]
    return value or None


def _extract_domain_host(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    host: str | None = None
    if "://" in text:
        try:
            host = urlparse(text).hostname
        except Exception:
            host = None
    if host is None:
        host = text
    return _normalize_policy_host(host)


def _is_loopback_host(host: str | None) -> bool:
    normalized = _normalize_policy_host(host)
    if not normalized:
        return False
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _normalized_marker(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _resolve_local_loopback_domains(spec: ToolSpec) -> tuple[str, ...] | None:
    caps = spec.execution_capabilities
    if caps is not None and caps.allowed_domains:
        domains = [_extract_domain_host(d) for d in caps.allowed_domains]
        normalized_domains = [d for d in domains if d]
        if normalized_domains:
            if all(_is_loopback_host(d) for d in normalized_domains):
                return tuple(sorted(set(normalized_domains)))
            # Explicit non-loopback domains remain externally gated.
            return None

    tags = {
        _normalized_marker(tag) for tag in (spec.tags or []) if _normalized_marker(tag)
    }
    deps = {
        _normalized_marker(dep)
        for dep in (spec.hard_dependencies or [])
        if _normalized_marker(dep)
    }
    if tags & _LOCAL_RUNTIME_MARKERS or deps & _LOCAL_RUNTIME_MARKERS:
        return _LOOPBACK_POLICY_DOMAINS

    side_effects = {
        _normalized_marker(effect)
        for effect in (spec.side_effects or [])
        if _normalized_marker(effect)
    }
    if side_effects & _LOCAL_RUNTIME_MARKERS:
        return _LOOPBACK_POLICY_DOMAINS

    override = _LOCAL_NETWORK_TOOL_DOMAIN_OVERRIDES.get((spec.name or "").strip())
    if override:
        return tuple(sorted({_normalize_policy_host(d) or d for d in override}))
    return None


def _spec_with_local_loopback_caps(
    spec: ToolSpec,
    domains: tuple[str, ...],
) -> ToolSpec:
    cleaned_domains = [
        d for d in (_normalize_policy_host(d) for d in domains) if d is not None
    ]
    if not cleaned_domains:
        return spec

    caps = spec.execution_capabilities
    if caps is None:
        updated_caps = ToolExecutionCapabilities(
            needs_network=True,
            allowed_domains=sorted(set(cleaned_domains)),
        )
        return spec.model_copy(
            deep=True,
            update={"execution_capabilities": updated_caps},
        )

    merged_domains = sorted(
        {
            *cleaned_domains,
            *[
                d
                for d in (
                    _normalize_policy_host(v) for v in (caps.allowed_domains or [])
                )
                if d is not None
            ],
        }
    )
    if caps.needs_network is True and merged_domains == sorted(
        set(caps.allowed_domains or [])
    ):
        return spec
    updated_caps = caps.model_copy(
        deep=True,
        update={
            "needs_network": True,
            "allowed_domains": merged_domains,
        },
    )
    return spec.model_copy(
        deep=True,
        update={"execution_capabilities": updated_caps},
    )


def _patch_catalog_local_loopback_caps(tool_id: str, domains: tuple[str, ...]) -> None:
    try:
        from brain_researcher.services.tools import catalog_loader

        catalog = catalog_loader.load_tools_catalog()
        entry = catalog.get(tool_id)
        if not isinstance(entry, dict):
            return
        caps = entry.get("execution_capabilities")
        if not isinstance(caps, dict):
            caps = {}
        existing_domains = caps.get("allowed_domains")
        normalized_existing: list[str] = []
        if isinstance(existing_domains, list):
            normalized_existing = [
                d
                for d in (_normalize_policy_host(v) for v in existing_domains)
                if d is not None
            ]
        merged_domains = sorted(
            {
                *normalized_existing,
                *[
                    d
                    for d in (_normalize_policy_host(v) for v in domains)
                    if d is not None
                ],
            }
        )
        caps["needs_network"] = True
        caps["allowed_domains"] = merged_domains
        entry["execution_capabilities"] = caps
    except Exception as exc:
        logger.debug(
            "Failed to patch local loopback execution_capabilities for %s: %s",
            tool_id,
            exc,
        )


def _prepare_spec_for_network_policy(
    spec: ToolSpec,
    *,
    patch_catalog: bool,
) -> ToolSpec:
    from brain_researcher.services.tools.execution_policy import (
        prepare_spec_for_network_policy,
    )

    return prepare_spec_for_network_policy(spec, patch_catalog=patch_catalog)


def _policy_check_tool(spec: ToolSpec) -> list[dict[str, str]]:
    from brain_researcher.services.tools.execution_policy import policy_check_tool

    return policy_check_tool(
        spec,
        allow_network=ALLOW_NETWORK,
        allow_dangerous=ALLOW_DANGEROUS,
    )


def _tool_requires_network(spec: ToolSpec) -> bool:
    caps = spec.execution_capabilities
    if caps is not None:
        if caps.needs_network is True:
            return True
        if caps.needs_network is False:
            return False
        if caps.allowed_domains:
            return True

    # Local OpenNeuro catalog tools are mount/catalog readers and can run in
    # network-restricted environments.
    if (spec.name or "").lower() in {
        "openneuro.search",
        "openneuro.get_dataset",
        "openneuro.get_dataset_summary",
    }:
        return False

    if spec.backend == "external_api":
        return True

    side_effects = {s.lower() for s in (spec.side_effects or [])}
    if side_effects & {"network", "http", "https", "web"}:
        return True

    tags = {t.lower() for t in (spec.tags or [])}
    if tags & {"net", "http", "external_net", "download", "web", "url", "pubmed"}:
        return True
    if tags & {"google", "gemini", "openneuro", "neurostore"}:
        return True

    name = (spec.name or "").lower()
    return any(
        token in name
        for token in (
            "openneuro",
            "neurostore",
            "pubmed",
            "download",
            "http",
            "google",
            "gemini",
        )
    )


def _tool_allowed_by_allowlist(tool_id: str, allowlist: set[str]) -> bool:
    if not allowlist:
        return False
    if "*" in allowlist:
        return True
    if tool_id in allowlist:
        return True
    for item in allowlist:
        if item.endswith("*") and tool_id.startswith(item[:-1]):
            return True
    return False


def _mcp_guardrails_snapshot() -> dict[str, Any]:
    return {
        "allow_network": bool(ALLOW_NETWORK),
        "allow_dangerous": bool(ALLOW_DANGEROUS),
        "enable_tool_execute": bool(ENABLE_TOOL_EXECUTE),
        "enable_latex_compile": bool(ENABLE_LATEX_COMPILE),
        "selftest_enabled": bool(MCP_SELFTEST_ENABLED),
        "selftest_script_path": str(MCP_SELFTEST_SCRIPT_PATH),
        "agent_fallback_enabled": bool(AGENT_FALLBACK_ENABLED),
        "agent_delegation_enabled": bool(AGENT_DELEGATED_EXECUTION_ENABLED),
        "agent_fallback_timeout_ms": int(AGENT_FALLBACK_TIMEOUT_MS),
        "agent_api_url": AGENT_API_URL,
        "tool_execute_allowlist": sorted(TOOL_EXECUTE_ALLOWLIST),
        "agent_multiagent_enabled": bool(AGENT_MULTIAGENT_ENABLED),
        "agent_critic_plan_gate": bool(AGENT_CRITIC_PLAN_GATE),
        "agent_critic_tool_gate": bool(AGENT_CRITIC_TOOL_GATE),
        "agent_recovery_agent": bool(AGENT_RECOVERY_AGENT),
        "agent_critic_fail_open": bool(AGENT_CRITIC_FAIL_OPEN),
        "rm_logging_enabled": bool(RM_LOGGING_ENABLED),
        "rm_logging_policy": RM_LOGGING_POLICY,
        "allowed_roots": [str(p) for p in ALLOWED_ROOTS],
        "run_root": str(_runstore.RUN_ROOT),
        "run_roots_read": [str(p) for p in _run_roots_for_read()],
        "transport": DEFAULT_TRANSPORT,
        "jsonschema_available": bool(jsonschema is not None),
    }


def _local_runtime_status_snapshot() -> dict[str, Any]:
    apptainer_binary = shutil.which("apptainer") or shutil.which("singularity")
    bids_validator_binary = shutil.which("bids-validator")
    cvmfs_root = Path(NEURODESK_CVMFS_CONTAINERS)
    return {
        "apptainer_binary": apptainer_binary,
        "apptainer_available": bool(apptainer_binary),
        "bids_validator_binary": bids_validator_binary,
        "bids_validator_available": bool(bids_validator_binary),
        "cvmfs_containers_path": str(cvmfs_root),
        "cvmfs_containers_exists": cvmfs_root.exists(),
        "cvmfs_containers_readable": (
            os.access(cvmfs_root, os.R_OK) if cvmfs_root.exists() else False
        ),
    }


def _is_loopback_host(host: str | None) -> bool:
    raw = str(host or "").strip().lower()
    if not raw:
        return False
    if raw in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(raw).is_loopback
    except Exception:
        return False


def _parse_host_port_from_uri(uri: str | None) -> tuple[str | None, int | None]:
    raw = str(uri or "").strip()
    if not raw:
        return None, None
    parsed = urlparse(raw)
    host = parsed.hostname
    port = parsed.port
    if port is None:
        scheme = (parsed.scheme or "").lower()
        if scheme in {"bolt", "neo4j"}:
            port = 7687
        elif scheme in {"http"}:
            port = 7474
        elif scheme in {"https"}:
            port = 7473
    return host, port


def _probe_tcp_endpoint(
    host: str | None, port: int | None, *, timeout_s: float
) -> dict[str, Any]:
    if not host or not isinstance(port, int) or port <= 0:
        return {
            "reachable": False,
            "error": "invalid_endpoint",
            "host": host,
            "port": port,
        }
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "reachable": True,
                "host": host,
                "port": port,
                "latency_ms": latency_ms,
            }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "reachable": False,
            "host": host,
            "port": port,
            "latency_ms": latency_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _dependency_status_snapshot() -> dict[str, Any]:
    neo4j_uri = (os.getenv("NEO4J_URI") or "").strip()
    neo4j_password = (os.getenv("NEO4J_PASSWORD") or "").strip()
    neo4j_database = (os.getenv("NEO4J_DATABASE") or "").strip()
    neo4j_host, neo4j_port = _parse_host_port_from_uri(neo4j_uri)
    neo4j_configured = bool(neo4j_uri and neo4j_password)
    neo4j_probe: dict[str, Any]
    if neo4j_configured:
        if not ALLOW_NETWORK and not _is_loopback_host(neo4j_host):
            neo4j_probe = {
                "reachable": False,
                "host": neo4j_host,
                "port": neo4j_port,
                "error": "network_blocked_by_policy",
            }
        else:
            neo4j_probe = _probe_tcp_endpoint(
                neo4j_host,
                neo4j_port,
                timeout_s=DEPENDENCY_CHECK_TIMEOUT_S,
            )
    else:
        neo4j_probe = {
            "reachable": False,
            "host": neo4j_host,
            "port": neo4j_port,
            "error": "not_configured",
        }

    dataset_mounts = dataset_mount_snapshots()
    openneuro_mount = dataset_mounts["openneuro_mount"]
    public_s3_mount = dataset_mounts["public_s3_mount"]
    run_root_writable, run_root_error = _check_run_root_writable(_runstore.RUN_ROOT)
    local_runtime = _local_runtime_status_snapshot()
    agent_host, agent_port = _parse_host_port_from_uri(AGENT_API_URL)
    if AGENT_FALLBACK_ENABLED:
        if not ALLOW_NETWORK and not _is_loopback_host(agent_host):
            agent_probe: dict[str, Any] = {
                "reachable": False,
                "host": agent_host,
                "port": agent_port,
                "error": "network_blocked_by_policy",
            }
        else:
            agent_probe = _probe_tcp_endpoint(
                agent_host,
                agent_port,
                timeout_s=DEPENDENCY_CHECK_TIMEOUT_S,
            )
    else:
        agent_probe = {
            "reachable": False,
            "host": agent_host,
            "port": agent_port,
            "error": "fallback_disabled",
        }

    return {
        "run_root": {
            "path": str(_runstore.RUN_ROOT),
            "writable": bool(run_root_writable),
            "error": run_root_error,
        },
        "neo4j": {
            "configured": neo4j_configured,
            "uri": neo4j_uri or None,
            "database": neo4j_database or None,
            "active_check": neo4j_probe,
        },
        "network_policy": {"allow_network": bool(ALLOW_NETWORK)},
        "local_runtime": local_runtime,
        "agent_fallback": {
            "enabled": bool(AGENT_FALLBACK_ENABLED),
            "agent_api_url": AGENT_API_URL,
            "timeout_ms": int(AGENT_FALLBACK_TIMEOUT_MS),
            "active_check": agent_probe,
        },
        "openneuro_mount": openneuro_mount,
        "dataset_mounts": dataset_mounts,
        "public_s3_mount": public_s3_mount,
    }


def _startup_hard_health_checks() -> dict[str, Any]:
    """Run fail-fast startup checks for local storage + configured dependencies."""

    _assert_run_root_writable(_runstore.RUN_ROOT)
    status = _dependency_status_snapshot()

    run_root_status = status.get("run_root") if isinstance(status, dict) else None
    if isinstance(run_root_status, dict) and not run_root_status.get("writable", False):
        raise RuntimeError(
            f"RUN_ROOT is not writable: {_runstore.RUN_ROOT} "
            f"({run_root_status.get('error') or 'unknown_error'})"
        )

    neo4j_status = status.get("neo4j") if isinstance(status, dict) else None
    active_check = (
        neo4j_status.get("active_check") if isinstance(neo4j_status, dict) else None
    )
    neo4j_configured = bool(
        isinstance(neo4j_status, dict) and neo4j_status.get("configured")
    )
    neo4j_reachable = bool(
        isinstance(active_check, dict) and active_check.get("reachable")
    )

    if STARTUP_STRICT_DEPENDENCIES and neo4j_configured and not neo4j_reachable:
        err = active_check.get("error") if isinstance(active_check, dict) else "unknown"
        raise RuntimeError(
            "Configured Neo4j dependency failed active startup check. "
            f"(uri={neo4j_status.get('uri') if isinstance(neo4j_status, dict) else None}, error={err})"
        )

    return status


def _selftest_probe_card(
    probe_id: str,
    *,
    status: str,
    summary: str,
    latency_ms: int,
    data: dict[str, Any] | None = None,
    error: str | None = None,
    policy_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": probe_id,
        "status": status,
        "ok": status == "pass",
        "summary": summary,
        "latency_ms": int(max(0, latency_ms)),
    }
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    if policy_issues:
        payload["policy_issues"] = policy_issues
    return payload


def _selftest_json_from_stdout(
    raw_stdout: str,
) -> tuple[dict[str, Any] | None, str | None]:
    text = (raw_stdout or "").strip()
    if not text:
        return None, "empty_stdout"
    candidates = [line.strip() for line in text.splitlines() if line.strip()]
    if text not in candidates:
        candidates.append(text)
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed, None
        return None, "stdout_json_not_object"
    return None, "stdout_not_json"


def _selftest_extract_script_probe_payload(
    response: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    if not isinstance(response, dict):
        return None, "invalid_tool_execute_response", []
    if not response.get("ok"):
        error = str(response.get("error") or "tool_execute_failed")
        policy_issues = list(response.get("policy_issues") or [])
        return None, error, policy_issues

    result = response.get("result")
    if not isinstance(result, dict):
        return None, "tool_result_missing", []
    data = result.get("data")
    if not isinstance(data, dict):
        return None, "tool_result_data_missing", []
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        return None, "tool_result_outputs_missing", []
    stdout = outputs.get("stdout")
    if not isinstance(stdout, str):
        return None, "tool_result_stdout_missing", []
    payload, parse_error = _selftest_json_from_stdout(stdout)
    if parse_error:
        return None, parse_error, []
    return payload, None, []


def _selftest_run_local_probe(probe: str) -> dict[str, Any]:
    script_path = MCP_SELFTEST_SCRIPT_PATH.expanduser().resolve()
    if not script_path.exists():
        return {
            "ok": False,
            "error": f"selftest_script_not_found:{script_path}",
            "policy_issues": [],
            "script_path": str(script_path),
        }

    response = tool_execute(
        "run_local_script",
        params={"script": str(script_path), "args": ["--probe", probe]},
    )
    payload, error, policy_issues = _selftest_extract_script_probe_payload(response)
    if error:
        return {
            "ok": False,
            "error": error,
            "policy_issues": policy_issues,
            "script_path": str(script_path),
            "run_id": response.get("run_id") if isinstance(response, dict) else None,
            "run_dir": response.get("run_dir") if isinstance(response, dict) else None,
        }
    assert payload is not None  # Narrowed by parse success.
    probe_ok = bool(payload.get("ok", True))
    if not probe_ok:
        error_msg = str(
            payload.get("error") or payload.get("reason") or "probe_reported_failure"
        )
    else:
        error_msg = None
    return {
        "ok": probe_ok,
        "error": error_msg,
        "policy_issues": policy_issues,
        "payload": payload,
        "script_path": str(script_path),
        "run_id": response.get("run_id") if isinstance(response, dict) else None,
        "run_dir": response.get("run_dir") if isinstance(response, dict) else None,
    }


def _selftest_inventory_cards(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tool_id = str(item.get("name") or item.get("id") or "").strip()
        if not tool_id:
            continue
        inventory.append(
            {
                "tool_id": tool_id,
                "backend": item.get("backend"),
                "kind": item.get("kind"),
                "implementation_level": item.get("implementation_level"),
            }
        )
    return inventory


_ROUTING_INVARIANT_MEEG_SENSOR_CONNECTIVITY_PROBE_ID = (
    "routing_invariant_meeg_sensor_connectivity"
)
_ROUTING_INVARIANT_MEEG_PLAN_PREFLIGHT_PROBE_ID = (
    "routing_invariant_meeg_plan_preflight"
)
_MEEG_SENSOR_CONNECTIVITY_QUERY = "M/EEG sensor-space PLI WPLI PLV connectivity epochs"
_MEEG_SENSOR_CONNECTIVITY_TOOL_ID = "connectivity_measures"
_MEEG_PLAN_PREFLIGHT_QUERY = "MEG connectivity analysis for sensor time series"
_MEEG_PLAN_PREFLIGHT_TOOL_ID = "mne_connectivity"
_FMRI_ONLY_CONNECTIVITY_TOOL_IDS = {
    "connectivity_matrix",
    "compute_connectivity",
    "nilearn_connectivity_matrix",
    "seed_based_fc",
}


def _selftest_tool_id_list(tools: list[Any]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(
            tool.get("name") or tool.get("id") or tool.get("canonical_tool_id") or ""
        ).strip()
        if name:
            names.append(name)
    return names


def _selftest_tool_modalities(tool: Any) -> list[str]:
    if not isinstance(tool, dict):
        return []
    raw = tool.get("modalities")
    if raw is None:
        raw = tool.get("modality")
    if isinstance(raw, str):
        raw_values: list[Any] = [raw]
    elif isinstance(raw, list):
        raw_values = raw
    else:
        raw_values = []
    modalities: list[str] = []
    for item in raw_values:
        value = str(item or "").strip().lower()
        if value:
            modalities.append(value)
    return modalities


def _selftest_preflight_recipe_tool_ids(preflight: Any) -> list[str]:
    if not isinstance(preflight, dict):
        return []
    tool_ids: list[str] = []
    for call in preflight.get("recommended_next_calls") or []:
        if (
            not isinstance(call, dict)
            or call.get("tool_name") != "get_execution_recipe"
        ):
            continue
        arguments = call.get("arguments")
        if not isinstance(arguments, dict):
            continue
        tool_id = str(arguments.get("tool_id") or "").strip()
        if tool_id:
            tool_ids.append(tool_id)
    return tool_ids


def _selftest_meeg_sensor_connectivity_routing_probe() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        meg_search = tool_search(
            query=_MEEG_SENSOR_CONNECTIVITY_QUERY,
            limit=8,
            offset=0,
            modalities=["meg"],
            kind=None,
            exposed_only=True,
            include_workflows=True,
            include_total=True,
        )
        fmri_search = tool_search(
            query=_MEEG_SENSOR_CONNECTIVITY_QUERY,
            limit=12,
            offset=0,
            modalities=["fmri"],
            kind=None,
            exposed_only=True,
            include_workflows=True,
            include_total=True,
        )
    except Exception as exc:
        return _selftest_probe_card(
            _ROUTING_INVARIANT_MEEG_SENSOR_CONNECTIVITY_PROBE_ID,
            status="fail",
            summary="M/EEG sensor connectivity routing invariant raised exception",
            latency_ms=int((time.perf_counter() - started) * 1000),
            data={
                "query": _MEEG_SENSOR_CONNECTIVITY_QUERY,
                "expected_tool": _MEEG_SENSOR_CONNECTIVITY_TOOL_ID,
            },
            error=f"{type(exc).__name__}: {exc}",
        )

    meg_ok = bool(isinstance(meg_search, dict) and meg_search.get("ok"))
    fmri_ok = bool(isinstance(fmri_search, dict) and fmri_search.get("ok"))
    meg_tools = (
        list(meg_search.get("tools") or []) if isinstance(meg_search, dict) else []
    )
    fmri_tools = (
        list(fmri_search.get("tools") or []) if isinstance(fmri_search, dict) else []
    )
    meg_names = _selftest_tool_id_list(meg_tools)
    fmri_names = _selftest_tool_id_list(fmri_tools)
    meg_top_modalities = _selftest_tool_modalities(meg_tools[0] if meg_tools else None)

    data = {
        "query": _MEEG_SENSOR_CONNECTIVITY_QUERY,
        "expected_tool": _MEEG_SENSOR_CONNECTIVITY_TOOL_ID,
        "meg_top": meg_names[:5],
        "fmri_top": fmri_names[:5],
        "meg_top_modalities": meg_top_modalities,
    }

    failures: list[str] = []
    if not meg_ok:
        error = meg_search.get("error") if isinstance(meg_search, dict) else "unknown"
        failures.append(f"meg_search_failed:{error}")
    if not fmri_ok:
        error = fmri_search.get("error") if isinstance(fmri_search, dict) else "unknown"
        failures.append(f"fmri_search_failed:{error}")
    if not meg_names:
        failures.append("meg_search_returned_no_tools")
    elif meg_names[0] != _MEEG_SENSOR_CONNECTIVITY_TOOL_ID:
        failures.append("meg_top_not_connectivity_measures")
    if meg_names and not {"meg", "eeg"}.issubset(set(meg_top_modalities)):
        failures.append("meg_top_missing_meg_eeg_modalities")
    if _MEEG_SENSOR_CONNECTIVITY_TOOL_ID in fmri_names:
        failures.append("connectivity_measures_leaked_into_fmri_results")

    if failures:
        return _selftest_probe_card(
            _ROUTING_INVARIANT_MEEG_SENSOR_CONNECTIVITY_PROBE_ID,
            status="fail",
            summary="M/EEG sensor connectivity routing invariant failed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            data=data,
            error="; ".join(failures),
        )

    return _selftest_probe_card(
        _ROUTING_INVARIANT_MEEG_SENSOR_CONNECTIVITY_PROBE_ID,
        status="pass",
        summary=(
            "M/EEG sensor connectivity routes to connectivity_measures "
            "and is excluded from fMRI-filtered search"
        ),
        latency_ms=int((time.perf_counter() - started) * 1000),
        data=data,
    )


def _selftest_meeg_plan_preflight_routing_probe() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        preflight_fn = globals().get("plan_preflight")
        if preflight_fn is None:
            from brain_researcher.services.mcp.routers import plan as plan_router

            preflight_fn = plan_router.plan_preflight
        preflight = preflight_fn(
            _MEEG_PLAN_PREFLIGHT_QUERY,
            domain="neuroimaging",
            modality=["meg"],
            selection_mode=True,
        )
    except Exception as exc:
        return _selftest_probe_card(
            _ROUTING_INVARIANT_MEEG_PLAN_PREFLIGHT_PROBE_ID,
            status="fail",
            summary="M/EEG plan_preflight routing invariant raised exception",
            latency_ms=int((time.perf_counter() - started) * 1000),
            data={
                "query": _MEEG_PLAN_PREFLIGHT_QUERY,
                "expected_tool": _MEEG_PLAN_PREFLIGHT_TOOL_ID,
            },
            error=f"{type(exc).__name__}: {exc}",
        )

    ok = bool(isinstance(preflight, dict) and preflight.get("ok"))
    recipe_tool_ids = _selftest_preflight_recipe_tool_ids(preflight)
    selected_tool_id = recipe_tool_ids[0] if recipe_tool_ids else ""
    data = {
        "query": _MEEG_PLAN_PREFLIGHT_QUERY,
        "expected_tool": _MEEG_PLAN_PREFLIGHT_TOOL_ID,
        "selected_tool_id": selected_tool_id,
        "recipe_tool_ids": recipe_tool_ids[:5],
    }

    failures: list[str] = []
    if not ok:
        error = preflight.get("error") if isinstance(preflight, dict) else "unknown"
        failures.append(f"plan_preflight_failed:{error}")
    if not selected_tool_id:
        failures.append("plan_preflight_returned_no_recipe_tool")
    elif selected_tool_id != _MEEG_PLAN_PREFLIGHT_TOOL_ID:
        failures.append(f"plan_preflight_top_not_mne_connectivity:{selected_tool_id}")
    if selected_tool_id in _FMRI_ONLY_CONNECTIVITY_TOOL_IDS:
        failures.append(f"plan_preflight_selected_fmri_only_tool:{selected_tool_id}")

    if failures:
        return _selftest_probe_card(
            _ROUTING_INVARIANT_MEEG_PLAN_PREFLIGHT_PROBE_ID,
            status="fail",
            summary="M/EEG plan_preflight routing invariant failed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            data=data,
            error="; ".join(failures),
        )

    return _selftest_probe_card(
        _ROUTING_INVARIANT_MEEG_PLAN_PREFLIGHT_PROBE_ID,
        status="pass",
        summary="M/EEG plan_preflight routes to mne_connectivity",
        latency_ms=int((time.perf_counter() - started) * 1000),
        data=data,
    )


def _selftest_recommendations(probes: list[dict[str, Any]]) -> list[str]:
    recommendations: list[str] = []
    seen: set[str] = set()
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        status = str(probe.get("status") or "").strip().lower()
        if status == "pass":
            continue
        probe_id = str(probe.get("id") or "").strip().lower()
        message = ""
        if probe_id == "server_info_probe":
            message = "Check MCP transport/auth wiring and verify server_info returns ok=true."
        elif probe_id == "tool_search_probe":
            message = "Check tool registry initialization and workflow catalog loading."
        elif probe_id == "kg_probe":
            message = "Verify Neo4j connectivity (NEO4J_URI/NEO4J_PASSWORD) and network policy."
        elif probe_id == "script_probe":
            message = (
                "Enable BR_MCP_ENABLE_TOOL_EXECUTE=1 and allowlist run_local_script."
            )
        elif probe_id == "container_probe":
            message = "Install apptainer/singularity and mount CVMFS containers path."
        elif probe_id == "inventory_probe":
            message = (
                "Check tool_search workflow discoverability and relevance ranking."
            )
        elif probe_id == _ROUTING_INVARIANT_MEEG_SENSOR_CONNECTIVITY_PROBE_ID:
            message = (
                "Check connectivity_measures exposure/metadata and modality-filtered "
                "tool_search routing for M/EEG vs fMRI connectivity."
            )
        elif probe_id == _ROUTING_INVARIANT_MEEG_PLAN_PREFLIGHT_PROBE_ID:
            message = (
                "Check plan_preflight M/EEG connectivity routing and ensure the "
                "hardcoded connectivity fallback cannot select fMRI-only tools."
            )
        if message and message not in seen:
            recommendations.append(message)
            seen.add(message)
    return recommendations


def _annotate_structured_resolver_metadata(
    payload: dict[str, Any], *, force_fallback: bool
) -> None:
    source = str(payload.get("source") or "").strip().lower()
    if source == "catalog_fallback":
        payload.setdefault("resolver_mode", "catalog_fallback")
        if force_fallback:
            payload.setdefault("fallback_reason", "force_fallback")
        return
    if source:
        payload.setdefault("resolver_mode", source)


def _canonicalize_structured_tool_entry(entry: dict[str, Any] | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    raw_tool_id = str(entry.get("tool_id") or "").strip()
    if not raw_tool_id:
        return None
    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_primary_runtime_tool_id,
        )

        canonical_tool_id = resolve_primary_runtime_tool_id(raw_tool_id) or raw_tool_id
    except Exception:
        canonical_tool_id = raw_tool_id

    if canonical_tool_id != raw_tool_id:
        entry.setdefault("raw_tool_id", raw_tool_id)
        entry["tool_id"] = canonical_tool_id
    entry["canonical_tool_id"] = canonical_tool_id
    return canonical_tool_id


def _structured_tool_entry_is_retired(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    tool_id = _canonicalize_structured_tool_entry(entry) or entry.get("tool_id")
    return _is_retired_public_tool_name(tool_id)


def _filter_retired_structured_tool_entries(payload: dict[str, Any]) -> None:
    removed: list[str] = []
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        kept: list[Any] = []
        for candidate in candidates:
            if isinstance(candidate, dict) and _structured_tool_entry_is_retired(
                candidate
            ):
                removed.append(str(candidate.get("tool_id") or "").strip())
                continue
            kept.append(candidate)
        payload["candidates"] = kept

    recommendation = payload.get("recommendation")
    if isinstance(recommendation, dict) and _structured_tool_entry_is_retired(
        recommendation
    ):
        removed.append(str(recommendation.get("tool_id") or "").strip())
        kept_candidates = payload.get("candidates")
        payload["recommendation"] = (
            kept_candidates[0]
            if isinstance(kept_candidates, list) and kept_candidates
            else None
        )

    filtered = sorted({name for name in removed if name})
    if filtered:
        payload["retired_tools_filtered"] = filtered


def _merge_structured_candidate_lists(
    existing: list[str] | None, incoming: list[str] | None, *, limit: int = 8
) -> list[str]:
    merged: list[str] = []
    for value in (existing or []) + (incoming or []):
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def _structured_candidate_sort_key(
    entry: dict[str, Any],
) -> tuple[int, int, int, int, str]:
    return (
        -int(entry.get("score") or 0),
        -int(entry.get("support_count") or 1),
        -(1 if entry.get("available_runtime") else 0),
        -(1 if entry.get("available") else 0),
        str(entry.get("tool_id") or ""),
    )


def _fold_structured_candidates(
    candidates: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []

    for entry in candidates or []:
        if not isinstance(entry, dict):
            continue
        canonical_tool_id = (
            _canonicalize_structured_tool_entry(entry)
            or str(entry.get("tool_id") or "").strip()
        )
        if not canonical_tool_id:
            continue

        raw_tool_ids = _merge_structured_candidate_lists(
            list(entry.get("raw_tool_ids") or []),
            [entry.get("raw_tool_id")],
            limit=32,
        )

        existing = folded.get(canonical_tool_id)
        if existing is None:
            if raw_tool_ids:
                entry["raw_tool_ids"] = raw_tool_ids
            entry["support_count"] = 1
            folded[canonical_tool_id] = entry
            ordered.append(entry)
            continue

        existing["support_count"] = int(existing.get("support_count") or 1) + 1
        if raw_tool_ids:
            existing["raw_tool_ids"] = _merge_structured_candidate_lists(
                list(existing.get("raw_tool_ids") or []),
                raw_tool_ids,
                limit=32,
            )
        existing["matched"] = _merge_structured_candidate_lists(
            list(existing.get("matched") or []),
            list(entry.get("matched") or []),
            limit=8,
        )
        existing["score"] = max(
            int(existing.get("score") or 0), int(entry.get("score") or 0)
        )
        if entry.get("available_runtime") and not existing.get("available_runtime"):
            existing["available_runtime"] = True
            existing["availability_source"] = entry.get("availability_source")
        if entry.get("available") and not existing.get("available"):
            existing["available"] = True
            existing["availability_source"] = entry.get("availability_source")

    ordered.sort(key=_structured_candidate_sort_key)
    return ordered


def _toolspec_available(reg: UnifiedToolRegistry, tool_id: str | None) -> bool:
    if not tool_id:
        return False
    try:
        return reg.get_toolspec_by_name(tool_id) is not None
    except Exception:
        return False


def _tool_runtime_available(reg: UnifiedToolRegistry, tool_id: str | None) -> bool:
    if not tool_id:
        return False
    try:
        return bool(reg.is_tool_runtime_callable(tool_id))
    except Exception:
        return False


def _declared_workflow_ids() -> set[str]:
    ids = set(load_orchestration_workflows()) | set(load_workflow_catalog_ids())
    return {str(item).strip() for item in ids if str(item).strip()}


def _is_declared_workflow_id(tool_id: str | None) -> bool:
    tid = str(tool_id or "").strip()
    if not tid:
        return False
    return tid in _declared_workflow_ids()


def _toolspec_runtime_callable(spec: ToolSpec) -> bool:
    """Best-effort runtime callability check used for workflow discoverability."""

    try:
        return _get_registry().is_toolspec_runtime_callable(spec)
    except Exception:
        return False


def _get_multiagent_router():
    global _MULTIAGENT_ROUTER
    global _MULTIAGENT_ROUTER_FAILED
    if _MULTIAGENT_ROUTER is not None:
        return _MULTIAGENT_ROUTER
    if _MULTIAGENT_ROUTER_FAILED:
        return None
    with _MULTIAGENT_ROUTER_LOCK:
        if _MULTIAGENT_ROUTER is not None:
            return _MULTIAGENT_ROUTER
        if _MULTIAGENT_ROUTER_FAILED:
            return None
        try:
            from brain_researcher.services.agent.subagents.router import (
                MultiAgentRouter,
            )

            _MULTIAGENT_ROUTER = MultiAgentRouter.from_env()
            return _MULTIAGENT_ROUTER
        except Exception as exc:  # pragma: no cover - optional path
            logger.debug("MCP could not initialize MultiAgentRouter: %s", exc)
            _MULTIAGENT_ROUTER_FAILED = True
            return None


def _multiagent_critic_tool_issues(
    *,
    tool_id: str,
    params: dict[str, Any],
    spec: ToolSpec,
    allowlist: set[str] | None,
    step_id: str | None,
) -> list[dict[str, str]]:
    if not (AGENT_MULTIAGENT_ENABLED and AGENT_CRITIC_TOOL_GATE):
        return []

    router = _get_multiagent_router()
    if router is None:
        return []

    context: dict[str, Any] = {"no_network": not ALLOW_NETWORK}
    if allowlist is not None and allowlist:
        context["tool_allowlist"] = sorted(allowlist)

    try:
        verdict = router.review_tool_call(
            tool_name=tool_id,
            params=params,
            context=context,
            tool_metadata={"dangerous": bool(spec.dangerous)},
        )
    except Exception as exc:
        if AGENT_CRITIC_FAIL_OPEN:
            logger.warning("MCP multi-agent tool critic failed (fail-open): %s", exc)
            return []
        issue = {
            "level": "error",
            "code": "multiagent_critic_failure",
            "message": f"Multi-agent critic failed: {type(exc).__name__}",
        }
        if step_id:
            issue["step_id"] = step_id
        return [issue]

    if verdict.decision == "block":
        message = verdict.reason or "blocked_by_multiagent_critic"
        issue = {
            "level": "error",
            "code": "multiagent_critic_blocked",
            "message": f"Multi-agent critic blocked tool '{tool_id}': {message}",
        }
        if step_id:
            issue["step_id"] = step_id
        return [issue]

    if verdict.decision == "revise":
        patch = (
            verdict.suggested_patch if isinstance(verdict.suggested_patch, dict) else {}
        )
        patched = patch.get("params")
        if isinstance(patched, dict):
            params.clear()
            params.update(patched)
            issue = {
                "level": "warn",
                "code": "multiagent_critic_revised_params",
                "message": f"Multi-agent critic revised params for '{tool_id}'.",
            }
            if step_id:
                issue["step_id"] = step_id
            return [issue]
        if not AGENT_CRITIC_FAIL_OPEN:
            issue = {
                "level": "error",
                "code": "multiagent_critic_revise_unapplied",
                "message": (
                    f"Multi-agent critic requested revision for '{tool_id}' "
                    "but no deterministic patch was provided."
                ),
            }
            if step_id:
                issue["step_id"] = step_id
            return [issue]

    return []


_PATH_PARAM_SUFFIXES = (
    "_path",
    "_paths",
    "_file",
    "_files",
    "_dir",
    "_dirs",
    "_folder",
    "_folders",
    "_filename",
    "_filenames",
)
_PATH_PARAM_CORE_TOKENS = {
    "path",
    "paths",
    "file",
    "files",
    "dir",
    "dirs",
    "folder",
    "folders",
    "filename",
    "filenames",
    "filepath",
    "workdir",
    "workspace",
    "mount",
    "root",
}
_PATH_INPUT_HINT_TOKENS = {
    "input",
    "inputs",
    "src",
    "source",
    "read",
    "load",
    "dataset",
    "datasets",
    "data",
    "config",
    "reference",
    "references",
    "template",
    "templates",
    "atlas",
    "mask",
    "model",
    "weights",
    "checkpoint",
    "ckpt",
    "script",
    "image",
    "img",
}
_PATH_OUTPUT_HINT_TOKENS = {
    "out",
    "output",
    "outputs",
    "dest",
    "destination",
    "target",
    "result",
    "results",
    "artifact",
    "artifacts",
    "save",
    "write",
    "export",
    "report",
    "reports",
    "log",
    "logs",
    "stdout",
    "stderr",
    "cache",
    "tmp",
    "temp",
    "scratch",
    "work",
    "workspace",
    "staging",
}
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _split_param_key_tokens(key: str) -> list[str]:
    if not key:
        return []
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key.strip())
    parts = re.split(r"[^A-Za-z0-9]+", normalized.lower())
    return [part for part in parts if part]


def _looks_like_path_param_key(key: str) -> bool:
    lowered = key.strip().lower()
    if not lowered:
        return False
    if lowered.endswith(_PATH_PARAM_SUFFIXES):
        return True
    tokens = _split_param_key_tokens(key)
    return any(token in _PATH_PARAM_CORE_TOKENS for token in tokens)


def _classify_path_param_usage(key: str) -> str:
    tokens = _split_param_key_tokens(key)
    if any(token in _PATH_OUTPUT_HINT_TOKENS for token in tokens):
        return "output"
    if any(token in _PATH_INPUT_HINT_TOKENS for token in tokens):
        return "input"
    # Conservative fallback: most file/path-like parameters are consumed as inputs.
    return "input"


def _is_remote_uri_path_value(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered.startswith(("http://", "https://", "s3://")):
        return True
    return bool(_URI_SCHEME_RE.match(lowered))


def _is_anchored_local_path_value(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith(("~", "/", "./", "../", ".\\", "..\\")):
        return True
    if text.startswith("\\\\"):
        return True
    return bool(_WINDOWS_ABS_PATH_RE.match(text))


def _iter_path_like_string_params(
    node: Any,
    *,
    prefix: str = "",
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if isinstance(node, dict):
        for raw_key, raw_value in node.items():
            if not isinstance(raw_key, str):
                continue
            key_ref = f"{prefix}.{raw_key}" if prefix else raw_key
            if _looks_like_path_param_key(raw_key):
                if isinstance(raw_value, str):
                    out.append((key_ref, raw_key, raw_value))
                elif isinstance(raw_value, list):
                    for idx, item in enumerate(raw_value):
                        if isinstance(item, str):
                            out.append((f"{key_ref}[{idx}]", raw_key, item))
            if isinstance(raw_value, dict):
                out.extend(_iter_path_like_string_params(raw_value, prefix=key_ref))
            elif isinstance(raw_value, list):
                for idx, item in enumerate(raw_value):
                    if isinstance(item, dict):
                        out.extend(
                            _iter_path_like_string_params(
                                item, prefix=f"{key_ref}[{idx}]"
                            )
                        )
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            if isinstance(item, dict):
                nested_prefix = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                out.extend(_iter_path_like_string_params(item, prefix=nested_prefix))
    return out


def _preflight_path_param_issues(params: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()

    def _push_issue(*, code: str, message: str) -> None:
        key = f"{code}|{message}"
        if key in seen:
            return
        seen.add(key)
        issues.append({"level": "error", "code": code, "message": message})

    for key_ref, raw_key, raw_value in _iter_path_like_string_params(params):
        text = raw_value.strip()
        if not text:
            _push_issue(
                code="invalid_path_value",
                message=f"Param '{key_ref}' is empty but looks like a path parameter.",
            )
            continue
        if "\x00" in raw_value:
            _push_issue(
                code="invalid_path_value",
                message=f"Param '{key_ref}' contains an invalid null byte.",
            )
            continue
        if _is_remote_uri_path_value(text):
            # Do not treat URLs/object-store URIs as local filesystem paths.
            continue
        if not _is_anchored_local_path_value(text):
            # Leave non-anchored relative names to tool/runtime-level resolution.
            continue

        resolved: Path | None = None
        try:
            resolved = _require_allowed_path(Path(text), kind=f"param.{key_ref}")
        except ValueError as exc:
            _push_issue(
                code="path_not_allowed",
                message=f"Param '{key_ref}' rejected by path policy: {exc}",
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive
            _push_issue(
                code="invalid_path_value",
                message=(
                    f"Param '{key_ref}' path value is invalid: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
            continue

        if (
            resolved is not None
            and _classify_path_param_usage(raw_key) == "input"
            and not resolved.exists()
        ):
            _push_issue(
                code="input_not_found",
                message=f"Input path for param '{key_ref}' does not exist: {resolved}",
            )

    return issues


def _preflight_tool_call(
    tool_id: str,
    params: dict[str, Any],
    *,
    allowlist: set[str] | None = None,
    step_id: str | None = None,
    allow_remap: bool = False,
) -> tuple[ToolSpec | None, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    spec, resolver_info = _resolve_toolspec_for_preflight(
        tool_id, allow_remap=bool(allow_remap)
    )
    if spec is None:
        python_issue = resolver_info.get("python_issue")
        if isinstance(python_issue, dict):
            return None, [
                {
                    "level": "error",
                    "code": str(
                        python_issue.get("code") or TOOL_REGISTRY_MISCONFIGURED
                    ),
                    "reason_code": str(
                        python_issue.get("reason_code") or PYTHON_BACKEND_UNRESOLVABLE
                    ),
                    "message": str(
                        python_issue.get("message")
                        or "Python backend is not runtime-callable."
                    ),
                }
            ]
        issue_code = "unknown_tool"
        message = f"Unknown tool: {tool_id}"
        if is_workflow_tool_id(tool_id) and _is_declared_workflow_id(tool_id):
            issue_code = "workflow_registry_mismatch"
            message = f"Workflow '{tool_id}' is known to orchestration but missing from executable registry."
        elif resolver_info.get("candidate_tool_ids"):
            message = (
                f"Unknown tool: {tool_id}. Remap candidates were checked but no "
                "runtime-callable tool was available."
            )
        return None, [
            {
                "level": "error",
                "code": issue_code,
                "message": message,
            }
        ]
    spec = _prepare_spec_for_network_policy(spec, patch_catalog=True)

    if allowlist is not None and not _tool_allowed_by_allowlist(tool_id, allowlist):
        issues.append(
            {
                "level": "error",
                "code": "tool_not_allowlisted",
                "message": "Tool is not permitted by the active allowlist",
            }
        )

    if str(spec.backend or "").lower() == "python":
        python_issue = audit_python_backend_configuration(spec)
        if python_issue is not None:
            issues.append(
                {
                    "level": "error",
                    "code": str(
                        python_issue.get("code") or TOOL_REGISTRY_MISCONFIGURED
                    ),
                    "reason_code": str(
                        python_issue.get("reason_code") or PYTHON_BACKEND_UNRESOLVABLE
                    ),
                    "message": str(
                        python_issue.get("message")
                        or "Python backend is not runtime-callable."
                    ),
                }
            )

    issues.extend(_policy_check_tool(spec))
    issues.extend(_validate_tool_params(tool_id, spec, params))
    issues.extend(_preflight_path_param_issues(params))
    issues.extend(
        _multiagent_critic_tool_issues(
            tool_id=tool_id,
            params=params,
            spec=spec,
            allowlist=allowlist,
            step_id=step_id,
        )
    )

    if step_id:
        for item in issues:
            item.setdefault("step_id", step_id)

    return spec, issues


def _normalize_plan_for_run(
    plan: Plan, run_id: str
) -> tuple[Plan, list[dict[str, str]], Path | None, str | None]:
    issues: list[dict[str, str]] = []

    run_dir = _run_dir(run_id)
    run_workspace, run_tag, workspace_issues = _resolve_plan_workspace(
        plan, run_id=run_id
    )
    issues.extend(workspace_issues)

    if run_workspace is not None:
        work_root = run_workspace / "03_work"
        out_root = run_workspace / "04_artifacts"
    else:
        work_root = run_dir / "work"
        out_root = run_dir / "artifacts"

    normalized_steps: list[PlanStep] = []
    for idx, step in enumerate(plan.steps, start=1):
        step_id = step.step_id or f"s{idx}"
        spec, step_issues = _preflight_tool_call(
            step.tool, step.params, step_id=step_id
        )
        issues.extend(step_issues)
        if spec is None:
            continue

        step_work = step.work_dir or str(work_root / f"step-{idx:02d}-{step_id}")
        step_out = step.output_dir or str(out_root / f"step-{idx:02d}-{step_id}")

        # Enforce path sandbox on the computed directories.
        resolved_work: Path | None = None
        resolved_out: Path | None = None
        try:
            resolved_work = _require_allowed_path(Path(step_work), kind="work_dir")
            resolved_out = _require_allowed_path(Path(step_out), kind="output_dir")
        except ValueError as exc:
            issues.append(
                {
                    "level": "error",
                    "code": "path_not_allowed",
                    "message": str(exc),
                    "step_id": step_id,
                }
            )
        if run_workspace is not None:
            if resolved_work is not None and not _is_under_any_root(
                resolved_work, [run_workspace]
            ):
                issues.append(
                    {
                        "level": "error",
                        "code": "workspace_path_violation",
                        "message": (
                            "work_dir must stay under run_workspace when "
                            "plan.project_root is specified."
                        ),
                        "step_id": step_id,
                    }
                )
            if resolved_out is not None and not _is_under_any_root(
                resolved_out, [run_workspace]
            ):
                issues.append(
                    {
                        "level": "error",
                        "code": "workspace_path_violation",
                        "message": (
                            "output_dir must stay under run_workspace when "
                            "plan.project_root is specified."
                        ),
                        "step_id": step_id,
                    }
                )

        normalized_steps.append(
            PlanStep(
                tool=step.tool,
                params=step.params,
                step_id=step_id,
                work_dir=str(resolved_work or Path(step_work)),
                output_dir=str(resolved_out or Path(step_out)),
            )
        )

    return (
        Plan(
            steps=normalized_steps,
            project_root=plan.project_root,
            run_tag=run_tag,
        ),
        issues,
        run_workspace,
        run_tag,
    )


def _write_step_logs(
    run_dir: Path, *, idx: int, step_id: str, result: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    base = f"step-{idx:02d}-{step_id}"
    result_path = logs_dir / f"{base}.json"
    _atomic_write_json(result_path, result)

    stdout_path = None
    stderr_path = None
    data = result.get("data") or {}
    if isinstance(data, dict):
        if isinstance(data.get("stdout"), str) and data.get("stdout"):
            stdout_p = logs_dir / f"{base}.stdout.txt"
            stdout_p.write_text(data["stdout"])
            stdout_path = str(stdout_p.relative_to(run_dir))
        if isinstance(data.get("stderr"), str) and data.get("stderr"):
            stderr_p = logs_dir / f"{base}.stderr.txt"
            stderr_p.write_text(data["stderr"])
            stderr_path = str(stderr_p.relative_to(run_dir))

    return (
        str(result_path.relative_to(run_dir)),
        stdout_path,
        stderr_path,
    )


def _execute_run(run_id: str) -> None:
    run_dir = _run_dir(run_id)
    lock = _get_run_lock(run_id)

    preflight_issues: list[dict[str, Any]] | None = None
    try:
        issues_path = run_dir / "validation.issues.json"
        if issues_path.exists():
            raw = json.loads(issues_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("issues"), list):
                preflight_issues = [i for i in raw["issues"] if isinstance(i, dict)]
    except Exception:
        preflight_issues = None

    log_trace = None
    try:
        from brain_researcher.services.agent.run_bundle import (
            log_trace_event as _log_trace_event,
        )

        log_trace = _log_trace_event
    except Exception:
        log_trace = None

    try:
        with lock:
            record = _load_run(run_id)
            if record.status == "cancelled":
                return
            record.status = "running"
            record.started_at = _utc_iso()
            _update_run_progress(
                record,
                stage="pipeline_execute",
                message="Running pipeline execution",
                progress_pct=0.0,
            )
            _save_run(record)

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.run.started",
            payload={"route": "pipeline_execute"},
        )

        step_ctx: dict[str, Any] = {"steps": {}}
        for idx, step in enumerate(record.steps, start=1):
            heartbeat_stop: threading.Event | None = None
            with lock:
                record = _load_run(run_id)
                if record.status == "cancelled":
                    if record.finished_at is None:
                        record.finished_at = _utc_iso()
                    _save_run(record)
                    if heartbeat_stop is not None:
                        heartbeat_stop.set()
                    return
                current = record.steps[idx - 1]
                if current.status not in {"queued"}:
                    continue
                current.status = "running"
                current.started_at = _utc_iso()
                progress_pct = 0.0
                if record.steps:
                    progress_pct = ((idx - 1) / max(1, len(record.steps))) * 100.0
                _update_run_progress(
                    record,
                    stage=f"step:{step.step_id}",
                    message=f"Executing {step.tool_id}",
                    progress_pct=progress_pct,
                    step_index=idx - 1,
                )
                _save_run(record)
                if not record.dry_run:
                    heartbeat_stop = _start_run_heartbeat(
                        run_id,
                        stage=f"step:{step.step_id}",
                        message=f"Executing {step.tool_id}",
                        progress_pct=progress_pct,
                        step_index=idx - 1,
                        run_dir=run_dir,
                    )

            try:
                resolved_params = _interpolate_pipeline_step_params(
                    step.params, step_ctx
                )
                work_dir = _require_allowed_path(
                    Path(step.work_dir or ""), kind="work_dir"
                )
                out_dir = _require_allowed_path(
                    Path(step.output_dir or ""), kind="output_dir"
                )

                _emit_trace_event(
                    log_trace,
                    run_dir,
                    run_id=run_id,
                    event_type="mcp.step.started",
                    payload={
                        "step_id": step.step_id,
                        "tool_id": step.tool_id,
                        "params": resolved_params,
                    },
                )

                if record.dry_run:
                    result = {
                        "status": "success",
                        "error": None,
                        "data": {
                            "dry_run": True,
                            "would_execute": {
                                "tool_id": step.tool_id,
                                "params": resolved_params,
                                "work_dir": str(work_dir),
                                "output_dir": str(out_dir),
                            },
                        },
                        "metadata": {
                            "execution_mode": "dry_run_no_exec",
                            "tool_id": step.tool_id,
                        },
                    }
                else:
                    work_dir.mkdir(parents=True, exist_ok=True)
                    out_dir.mkdir(parents=True, exist_ok=True)

                    spec = _get_toolspec_with_schema(step.tool_id)
                    result_obj = _execute_tool_with_timeout(
                        tool_id=step.tool_id,
                        params=resolved_params,
                        work_dir=str(work_dir),
                        output_dir=str(out_dir),
                        preview=False,
                        spec=spec,
                    )
                    result = result_obj.model_dump()
            except Exception as exc:  # pragma: no cover - defensive
                result = {
                    "status": "error",
                    "error": str(exc),
                    "data": None,
                    "metadata": {},
                }

            result_path, stdout_path, stderr_path = _write_step_logs(
                run_dir, idx=idx, step_id=step.step_id, result=result
            )

            policy_issues = _extract_policy_issues_from_result(
                result, step_id=step.step_id
            )
            timeout_outcome = None
            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                timeout_outcome = metadata.get("timeout_outcome")
            _emit_trace_event(
                log_trace,
                run_dir,
                run_id=run_id,
                event_type="mcp.step.finished",
                payload={
                    "step_id": step.step_id,
                    "tool_id": step.tool_id,
                    "status": result.get("status"),
                    "error": result.get("error"),
                    "result_path": result_path,
                    "stdout_path": stdout_path,
                    "stderr_path": stderr_path,
                    "timeout_outcome": timeout_outcome,
                    "policy_issues": policy_issues,
                },
            )

            with lock:
                record = _load_run(run_id)
                current = record.steps[idx - 1]
                current.finished_at = _utc_iso()
                current.result_path = result_path
                current.stdout_path = stdout_path
                current.stderr_path = stderr_path
                current.policy_issues = policy_issues
                if record.status == "cancelled":
                    if record.finished_at is None:
                        record.finished_at = _utc_iso()
                    _save_run(record)
                    return
                if result.get("status") == "success":
                    # Dry-run is a precheck-only path: step logs are produced but no
                    # real execution happens, so keep step status as skipped.
                    current.status = "skipped" if record.dry_run else "succeeded"
                    progress_pct = (idx / max(1, len(record.steps))) * 100.0
                    _update_run_progress(
                        record,
                        stage=f"step:{step.step_id}:completed",
                        message=f"Finished {step.tool_id}",
                        progress_pct=progress_pct,
                        step_index=idx - 1,
                    )
                else:
                    formatted_error = _format_execution_error(result)
                    current.status = "failed"
                    current.error = formatted_error
                    record.status = "failed"
                    record.error = formatted_error
                    record.finished_at = _utc_iso()
                    _update_run_progress(
                        record,
                        stage=f"step:{step.step_id}:failed",
                        message=formatted_error,
                        step_index=idx - 1,
                    )
                    _save_run(record)
                    if heartbeat_stop is not None:
                        heartbeat_stop.set()
                    return
                step_ctx["steps"][step.step_id] = result
                _save_run(record)
            if heartbeat_stop is not None:
                heartbeat_stop.set()

        with lock:
            record = _load_run(run_id)
            if record.status != "cancelled":
                record.status = "succeeded"
                record.finished_at = _utc_iso()
                _update_run_progress(
                    record,
                    stage="completed",
                    message="Pipeline execution completed",
                    progress_pct=100.0,
                )
                _save_run(record)
            elif record.finished_at is None:
                record.finished_at = _utc_iso()
                _update_run_progress(
                    record,
                    stage="cancelled",
                    message="Pipeline execution cancelled",
                )
                _save_run(record)
    finally:
        try:
            record = _load_run(run_id)
        except Exception:
            record = None
        if record is not None:
            _emit_trace_event(
                log_trace,
                run_dir,
                run_id=run_id,
                event_type="mcp.run.finished",
                payload={"status": record.status, "error": record.error},
            )

        _persist_mcp_run_bundle(run_id, preflight_issues=preflight_issues)

        try:
            _run_post_execution_review_gate(run_id)
        except Exception as exc:  # pragma: no cover - gate must not crash runs
            _emit_trace_event(
                log_trace,
                run_dir,
                run_id=run_id,
                event_type="mcp.review_gate.error",
                payload={"error": repr(exc)},
            )


def _claim_mode_from_run_dir(run_dir: Path) -> str:
    """Infer confirmatory/exploratory claim mode for a completed run.

    Looks for ``review_context.claim_contract`` in the analysis bundle / run.json.
    Defaults to ``confirmatory`` so the gate stays conservative when the contract
    is missing.
    """

    candidates = [
        run_dir / "analysis_bundle.json",
        run_dir / "run.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        review_context = payload.get("review_context")
        if not isinstance(review_context, dict):
            review_context = (
                payload.get("analysis_bundle", {}).get("review_context")
                if isinstance(payload.get("analysis_bundle"), dict)
                else None
            )
        if not isinstance(review_context, dict):
            continue
        claim_contract = review_context.get("claim_contract")
        if isinstance(claim_contract, dict):
            mode = claim_contract.get("confirmatory_or_exploratory")
            if isinstance(mode, str) and mode.strip():
                return mode.strip().lower()
        mode_value = review_context.get("confirmatory_or_exploratory")
        if isinstance(mode_value, str) and mode_value.strip():
            return mode_value.strip().lower()
    return "confirmatory"


def _collect_blocking_findings(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    correctness = verdict.get("correctness") if isinstance(verdict, dict) else None
    findings = (
        correctness.get("findings")
        if isinstance(correctness, dict)
        and isinstance(correctness.get("findings"), list)
        else []
    )
    return [
        f
        for f in findings
        if isinstance(f, dict)
        and (
            str(f.get("action") or "").lower() == "block"
            or str(f.get("severity") or "").lower() in {"critical", "error"}
        )
    ]


def _collect_mandatory_block_findings(
    blocking: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Correctness findings that block regardless of claim mode.

    A ``critical`` severity correctness finding (e.g. silently-repaired
    out-of-range connectivity, CV leakage) invalidates the result itself, not
    just the strength of the claim. These block even on exploratory runs; only
    ``error``/``warn`` findings respect the exploratory downgrade.
    """

    return [
        f
        for f in blocking
        if isinstance(f, dict) and str(f.get("severity") or "").lower() == "critical"
    ]


def _collect_warning_findings(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    correctness = verdict.get("correctness") if isinstance(verdict, dict) else None
    findings = (
        correctness.get("findings")
        if isinstance(correctness, dict)
        and isinstance(correctness.get("findings"), list)
        else []
    )
    return [
        f
        for f in findings
        if isinstance(f, dict)
        and str(f.get("action") or "").lower() in {"warn", "caveat"}
        and str(f.get("severity") or "").lower() not in {"critical", "error"}
    ]


def _compact_review_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for finding in findings:
        item = {
            "rule_id": finding.get("rule_id"),
            "severity": finding.get("severity"),
            "action": finding.get("action"),
            "message": finding.get("message"),
        }
        compact.append({k: v for k, v in item.items() if v is not None})
    return compact


def _review_context_locations(
    run_dir: Path,
) -> list[tuple[Path, dict[str, Any], list[dict[str, Any]]]]:
    locations: list[tuple[Path, dict[str, Any], list[dict[str, Any]]]] = []
    for path in (run_dir / "analysis_bundle.json", run_dir / "run.json"):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        contexts: list[dict[str, Any]] = []
        review_context = payload.get("review_context")
        if isinstance(review_context, dict):
            contexts.append(review_context)
        else:
            review_context = {}
            payload["review_context"] = review_context
            contexts.append(review_context)

        analysis_bundle = payload.get("analysis_bundle")
        if isinstance(analysis_bundle, dict):
            nested_review_context = analysis_bundle.get("review_context")
            if isinstance(nested_review_context, dict):
                if not any(nested_review_context is ctx for ctx in contexts):
                    contexts.append(nested_review_context)
            elif "review_context" not in analysis_bundle:
                nested_review_context = {}
                analysis_bundle["review_context"] = nested_review_context
                contexts.append(nested_review_context)

        locations.append((path, payload, contexts))
    return locations


def _stamp_claim_contract_review_verdict(
    run_dir: Path,
    *,
    verdict: dict[str, Any],
    claim_mode: str,
    blocking: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    review_artifact_path: Path,
) -> None:
    """Persist review-gate status onto artifacts for downstream consumers."""

    mandatory = _collect_mandatory_block_findings(blocking)
    is_blocked = bool(mandatory) or (claim_mode == "confirmatory" and bool(blocking))
    report_gate_status = (
        "blocked" if is_blocked else "caveated" if blocking or warnings else "passed"
    )
    try:
        artifact_ref = str(review_artifact_path.relative_to(run_dir))
    except ValueError:
        artifact_ref = review_artifact_path.name

    stamp = {
        "confirmatory_or_exploratory": claim_mode,
        "report_allowed": not is_blocked,
        "report_gate_status": report_gate_status,
        "scientific_review_decision": verdict.get("overall_decision"),
        "scientific_review_report_action": verdict.get("report_action"),
        "claim_strength": verdict.get("claim_strength"),
        "reviewed_at": _utc_iso(),
        "review_artifact_path": artifact_ref,
        "blocking_findings": _compact_review_findings(blocking),
        "warning_findings": _compact_review_findings(warnings),
    }

    for path, payload, review_contexts in _review_context_locations(run_dir):
        for review_context in review_contexts:
            claim_contract = review_context.get("claim_contract")
            if not isinstance(claim_contract, dict):
                claim_contract = {}
                review_context["claim_contract"] = claim_contract
            claim_contract.update(stamp)
        try:
            _atomic_write_json(path, payload)
        except Exception:
            continue


def _run_post_execution_review_gate(run_id: str) -> None:
    """Synchronously invoke scientific review after pipeline execution.

    A ``critical`` severity correctness finding flips the run status to
    ``review_blocked`` regardless of claim mode (a corrupted result is invalid
    whether the claim is confirmatory or exploratory). On confirmatory runs,
    any block-action / ``error`` correctness finding also blocks. Exploratory
    runs with only non-critical findings proceed, with warnings stamped into
    ``record.progress['review_caveats']`` so the report renders them as caveats.
    """

    if os.environ.get("BR_DISABLE_EXECUTION_REVIEW_GATE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    try:
        record = _load_run(run_id)
    except Exception:
        return
    if record.status not in {"succeeded"}:
        return

    run_dir = _find_run_dir(run_id)
    verdict = run_scientific_review(run_id)
    if not isinstance(verdict, dict) or verdict.get("ok") is not True:
        return

    review_artifact_path = run_dir / "scientific_review.json"
    try:
        review_artifact_path.write_text(
            json.dumps(verdict, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass

    blocking = _collect_blocking_findings(verdict)
    warnings = _collect_warning_findings(verdict)
    claim_mode = _claim_mode_from_run_dir(run_dir)

    lock = _get_run_lock(run_id)
    with lock:
        try:
            record = _load_run(run_id)
        except Exception:
            return
        record.progress = dict(record.progress or {})
        record.progress["scientific_review_overall_decision"] = verdict.get(
            "overall_decision"
        )
        if warnings:
            record.progress["review_caveats"] = [
                {
                    "rule_id": f.get("rule_id"),
                    "severity": f.get("severity"),
                    "message": f.get("message"),
                }
                for f in warnings
            ]
        mandatory = _collect_mandatory_block_findings(blocking)
        if mandatory or (claim_mode == "confirmatory" and blocking):
            record.status = "review_blocked"
            record.error = "review_blocked_by_correctness_findings"
            record.progress["scientific_review_blocking_findings"] = [
                {
                    "rule_id": f.get("rule_id"),
                    "severity": f.get("severity"),
                    "message": f.get("message"),
                }
                for f in blocking
            ]
        _save_run(record, run_dir=run_dir)
        _stamp_claim_contract_review_verdict(
            run_dir,
            verdict=verdict,
            claim_mode=claim_mode,
            blocking=blocking,
            warnings=warnings,
            review_artifact_path=review_artifact_path,
        )


def _issues_to_violations(
    issues: list[dict[str, Any]],
    *,
    stage: str = "preflight",
) -> list[dict[str, Any]]:
    try:
        from brain_researcher.core.contracts.violation import (
            Violation,
            ViolationLocation,
        )

        created_at = _epoch_ms()
        out: list[dict[str, Any]] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            level = str(issue.get("level") or "warn").lower()
            severity = {
                "info": "info",
                "warn": "warn",
                "warning": "warn",
                "error": "error",
                "critical": "critical",
            }.get(level, "warn")
            blocking = severity in {"error", "critical"}
            step_id = issue.get("step_id")
            where = ViolationLocation(component="mcp", stage=stage, step_id=step_id)
            details = {
                k: v for k, v in issue.items() if k not in {"level", "code", "message"}
            }
            v = Violation(
                code=str(issue.get("code") or "UNKNOWN"),
                message=str(issue.get("message") or issue.get("code") or "UNKNOWN"),
                severity=severity,
                blocking=blocking,
                where=where,
                details=details,
                created_at=created_at,
            )
            out.append(v.model_dump(exclude_none=True))
        return out
    except Exception:
        return []


def _collect_run_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rel_root, role in (("artifacts", "artifact"), ("logs", "log")):
        base = run_dir / rel_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(run_dir))
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            items.append({"path": rel, "name": rel, "role": role, "size_bytes": size})
    return items


_RM_LOGGING_FILE_ALIASES = {
    "rm_pairwise_redacted_json": "rm_pairwise_redacted_json",
    "rm_pairwise_redacted_jsonl": "rm_pairwise_redacted_json",
    "pairwise_redacted": "rm_pairwise_redacted_json",
    "pairwise_redacted_path": "rm_pairwise_redacted_json",
    "rm_process_redacted_json": "rm_process_redacted_json",
    "rm_process_redacted_jsonl": "rm_process_redacted_json",
    "process_redacted": "rm_process_redacted_json",
    "process_redacted_path": "rm_process_redacted_json",
    "rm_pairwise_raw_json": "rm_pairwise_raw_json",
    "vault_pairwise_raw_json": "rm_pairwise_raw_json",
    "vault_pairwise_raw_jsonl": "rm_pairwise_raw_json",
    "pairwise_raw": "rm_pairwise_raw_json",
    "pairwise_raw_path": "rm_pairwise_raw_json",
    "pairwise_vault_raw": "rm_pairwise_raw_json",
    "rm_process_raw_json": "rm_process_raw_json",
    "vault_process_raw_json": "rm_process_raw_json",
    "vault_process_raw_jsonl": "rm_process_raw_json",
    "process_raw": "rm_process_raw_json",
    "process_raw_path": "rm_process_raw_json",
    "process_vault_raw": "rm_process_raw_json",
}


def _resolve_rm_file_key(raw_key: str, raw_path: str) -> str | None:
    key = raw_key.strip().lower().replace("-", "_")
    if key in _RM_LOGGING_FILE_ALIASES:
        return _RM_LOGGING_FILE_ALIASES[key]

    path = raw_path.strip().lower().replace("-", "_")
    if "pairwise" in key or "pairwise" in path:
        if "redact" in key or "redact" in path:
            return "rm_pairwise_redacted_json"
        if "raw" in key or "raw" in path or "vault" in key or "vault" in path:
            return "rm_pairwise_raw_json"
    if "process" in key or "process" in path:
        if "redact" in key or "redact" in path:
            return "rm_process_redacted_json"
        if "raw" in key or "raw" in path or "vault" in key or "vault" in path:
            return "rm_process_raw_json"
    return None


def _to_run_relative_path(run_dir: Path, raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(run_dir.resolve()))
    except Exception:
        return str(path.resolve())


def _extract_rm_logging_files(run_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for key in ("files", "paths", "outputs"):
        raw = payload.get(key)
        if not isinstance(raw, dict):
            continue
        for maybe_key, maybe_path in raw.items():
            if isinstance(maybe_key, str) and isinstance(maybe_path, str):
                candidates[maybe_key] = maybe_path

    for maybe_key, maybe_path in payload.items():
        if isinstance(maybe_key, str) and isinstance(maybe_path, str):
            candidates.setdefault(maybe_key, maybe_path)

    out: dict[str, str] = {}
    for raw_key, raw_path in candidates.items():
        canonical = _resolve_rm_file_key(raw_key, raw_path)
        if not canonical:
            continue
        out[canonical] = _to_run_relative_path(run_dir, raw_path)
    return out


def _resolve_rm_logging_helper(module: Any) -> tuple[str | None, Any | None]:
    candidates = (
        "generate_rm_logging_files",
        "generate_rm_logging_bundle",
        "generate_rm_logs",
        "persist_rm_logging_files",
    )
    for name in candidates:
        fn = getattr(module, name, None)
        if callable(fn):
            return name, fn
    return None, None


def _persist_mcp_run_bundle(
    run_id: str,
    *,
    preflight_issues: list[dict[str, Any]] | None = None,
    run_dir: Path | None = None,
) -> None:
    """Best-effort write trace/provenance/observation/analysis bundle for an MCP run."""
    try:
        if run_dir is None:
            record, run_dir = _load_run_with_dir(run_id)
        else:
            record = _run_record_from_json(run_dir / "run.json")
    except Exception:
        return
    provenance_path = run_dir / "provenance.json"

    try:
        provenance: dict[str, Any] = {}
        if provenance_path.exists():
            raw = json.loads(provenance_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                provenance = raw
        provenance.setdefault("run_id", run_id)
        provenance.setdefault("mode", "mcp")
        provenance.setdefault("transport", DEFAULT_TRANSPORT)
        provenance.setdefault("run_dir", str(run_dir))
        provenance.setdefault("guardrails", _mcp_guardrails_snapshot())
        provenance["state"] = record.status
        if record.error:
            provenance["error"] = record.error
    except Exception:
        provenance = {"run_id": run_id, "mode": "mcp"}

    tool_calls: list[dict[str, Any]] = []
    execution_policy_issues: list[dict[str, Any]] = []
    for step in record.steps:
        result_payload: dict[str, Any] | None = None
        if step.result_path:
            try:
                rp = (run_dir / step.result_path).resolve()
                result_payload = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:
                result_payload = None

        tool_calls.append(
            {
                "tool_call_id": step.step_id,
                "name": step.tool_id,
                "arguments": _redact_for_logging(step.params),
                "status": step.status,
                "result": _redact_for_logging(result_payload),
                "error": step.error,
                "run_dir": str(run_dir),
                "result_path": step.result_path,
                "stdout_path": step.stdout_path,
                "stderr_path": step.stderr_path,
                "work_dir": step.work_dir,
                "output_dir": step.output_dir,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
            }
        )
        if isinstance(step.policy_issues, list):
            for issue in step.policy_issues:
                if isinstance(issue, dict):
                    execution_policy_issues.append(issue)
        if isinstance(result_payload, dict):
            execution_policy_issues.extend(
                _extract_policy_issues_from_result(result_payload, step_id=step.step_id)
            )

    rm_logging: dict[str, Any] = {
        "enabled": bool(RM_LOGGING_ENABLED),
        "policy": RM_LOGGING_POLICY,
        "status": "disabled",
        "files": {},
    }
    rm_pairwise: dict[str, Any] | None = None
    rm_process: dict[str, Any] | None = None
    if RM_LOGGING_ENABLED:
        try:
            module = importlib.import_module(
                "brain_researcher.services.agent.rm_logging"
            )
            helper_name, helper_fn = _resolve_rm_logging_helper(module)
            if helper_fn is None:
                raise AttributeError(
                    "No RM logging helper found; expected one of: "
                    "generate_rm_logging_files|generate_rm_logging_bundle|"
                    "generate_rm_logs|persist_rm_logging_files"
                )
            helper_output = helper_fn(
                run_dir=run_dir,
                run_id=run_id,
                policy=RM_LOGGING_POLICY,
                provenance=_redact_for_logging(provenance),
                record=asdict(record),
                tool_calls=tool_calls,
                preflight_issues=preflight_issues or [],
            )
            rm_logging = {
                "enabled": True,
                "policy": RM_LOGGING_POLICY,
                "status": "ok",
                "helper": helper_name,
                "files": {},
            }
            if isinstance(helper_output, dict):
                rm_files = _extract_rm_logging_files(run_dir, helper_output)
                rm_logging["files"] = rm_files
                rm_pairwise_raw = helper_output.get("rm_pairwise")
                if isinstance(rm_pairwise_raw, dict):
                    rm_pairwise = dict(rm_pairwise_raw)
                rm_process_raw = helper_output.get("rm_process")
                if isinstance(rm_process_raw, dict):
                    rm_process = dict(rm_process_raw)

                # Fallback metadata when helper only returns file paths.
                if rm_pairwise is None:
                    redacted = rm_files.get("rm_pairwise_redacted_json")
                    raw = rm_files.get("rm_pairwise_raw_json")
                    if redacted or raw:
                        rm_pairwise = {
                            "policy": RM_LOGGING_POLICY,
                            "redacted_json": redacted,
                            "raw_json": raw,
                        }
                if rm_process is None:
                    redacted = rm_files.get("rm_process_redacted_json")
                    raw = rm_files.get("rm_process_raw_json")
                    if redacted or raw:
                        rm_process = {
                            "policy": RM_LOGGING_POLICY,
                            "redacted_json": redacted,
                            "raw_json": raw,
                        }
                helper_status = helper_output.get("status")
                if isinstance(helper_status, str) and helper_status.strip():
                    rm_logging["status"] = helper_status.strip().lower()
        except Exception as exc:
            rm_logging = {
                "enabled": True,
                "policy": RM_LOGGING_POLICY,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "files": {},
            }
            logger.warning("MCP RM logging failed for %s (fail-open): %s", run_id, exc)

    provenance["rm_logging"] = rm_logging
    safe_provenance = _redact_for_logging(provenance)
    try:
        _atomic_write_json(provenance_path, safe_provenance)
    except Exception:
        pass

    artifacts = _collect_run_artifacts(run_dir)
    try:
        # Also attempt to index external output directories referenced by steps.
        run_dir_resolved = run_dir.resolve()
        seen_paths: set[str] = set()
        for item in artifacts:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                seen_paths.add(item["path"])

        max_external_files = 2000
        for step in record.steps:
            raw_out = step.output_dir
            if not isinstance(raw_out, str) or not raw_out.strip():
                continue
            try:
                out_dir = Path(raw_out).expanduser()
                if not out_dir.is_absolute():
                    out_dir = (PROJECT_ROOT / out_dir).resolve()
                else:
                    out_dir = out_dir.resolve()
                if out_dir.is_relative_to(run_dir_resolved):
                    continue
            except Exception:
                continue
            if not out_dir.exists():
                continue
            for path in sorted(out_dir.rglob("*")):
                if not path.is_file():
                    continue
                abs_path = str(path.resolve())
                if abs_path in seen_paths:
                    continue
                seen_paths.add(abs_path)
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                relpath = None
                try:
                    relpath = str(path.relative_to(out_dir))
                except Exception:
                    relpath = None
                artifacts.append(
                    {
                        "path": abs_path,
                        "name": abs_path,
                        "role": "external_output",
                        "size_bytes": size,
                        "external_root": str(out_dir),
                        "relpath": relpath,
                    }
                )
                if len(seen_paths) >= max_external_files:
                    break
            if len(seen_paths) >= max_external_files:
                break

        from brain_researcher.core.artifact_checksums import (
            compute_file_sha256,
            fill_artifact_checksums,
        )

        fill_artifact_checksums(artifacts, run_dir=run_dir)
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            checksum = artifact.get("checksum")
            if isinstance(checksum, str) and checksum.startswith("sha256:"):
                continue
            raw_path = artifact.get("path") or artifact.get("name")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                continue
            hexdigest, status, reason = compute_file_sha256(candidate)
            if hexdigest:
                artifact["checksum"] = f"sha256:{hexdigest}"
            artifact["checksum_status"] = status
            if reason:
                artifact["checksum_reason"] = reason
    except Exception:
        pass

    try:
        from brain_researcher.core.contracts.run_card import RunCardV1

        route = str(safe_provenance.get("route") or "mcp")
        selected_tool = record.steps[0].tool_id if len(record.steps) == 1 else None
        run_card_model = RunCardV1(
            id=run_id,
            execution={
                "provider": "local",
                "model": None,
                "tool_mode": "mcp",
                "route": route,
                "transport": DEFAULT_TRANSPORT,
                "selected_tool": selected_tool,
                "dry_run": bool(record.dry_run),
                "usage": {},
            },
            provenance={"run_dir": str(run_dir)},
        )
        run_card_dict = run_card_model.model_dump(exclude_none=True)
    except Exception:
        run_card_model = None
        run_card_dict = {"id": run_id, "provenance": {"run_dir": str(run_dir)}}

    violations = []
    if preflight_issues:
        violations.extend(_issues_to_violations(preflight_issues, stage="preflight"))
    if execution_policy_issues:
        violations.extend(
            _issues_to_violations(execution_policy_issues, stage="execution")
        )

    try:
        from brain_researcher.services.agent.run_bundle import (
            persist_agent_analysis_bundle,
            persist_agent_observation,
            persist_agent_trajectory,
        )

        user_message = json.dumps(
            {
                "run_id": run_id,
                "route": safe_provenance.get("route"),
                "steps": len(record.steps),
            },
            ensure_ascii=False,
        )
        agent_message = json.dumps(
            {"state": record.status, "error": record.error},
            ensure_ascii=False,
        )
        persist_agent_trajectory(
            run_dir,
            session_id=run_id,
            model_name="mcp",
            user_message=user_message,
            agent_message=agent_message,
            tool_calls=tool_calls,
            started_at_iso=record.started_at or record.created_at,
            finished_at_iso=record.finished_at,
            extra={"route": safe_provenance.get("route")},
        )

        persist_agent_observation(
            run_dir,
            job_id=run_id,
            run_id=run_id,
            state=record.status,
            run_card=run_card_model or run_card_dict,
            provenance=safe_provenance,
            tool_calls=tool_calls,
            artifacts=artifacts,
            violations=violations or None,
            created_at_ms=_iso_to_epoch_ms(record.created_at),
            started_at_ms=_iso_to_epoch_ms(record.started_at),
            finished_at_ms=_iso_to_epoch_ms(record.finished_at),
            rm_pairwise=rm_pairwise,
            rm_process=rm_process,
        )
        persist_agent_analysis_bundle(
            run_dir,
            job_id=run_id,
            run_id=run_id,
            state=record.status,
            run_card=run_card_dict,
            provenance=safe_provenance,
            policy={
                "guardrails": _mcp_guardrails_snapshot(),
                "preflight_issues": _redact_for_logging(preflight_issues or []),
                "execution_policy_issues": _redact_for_logging(execution_policy_issues),
                "rm_logging": rm_logging,
            },
            rm_pairwise=rm_pairwise,
            rm_process=rm_process,
        )
        if (
            record.status in _MCP_RUN_TERMINAL_STATUSES
            or (run_dir / _SESSION_SNAPSHOT_FILENAME).exists()
        ):
            try:
                distill_and_store_run(
                    run_id,
                    run_dir=run_dir,
                    store=MemoryStore(run_root=_runstore.RUN_ROOT),
                )
            except Exception as exc:
                logger.warning(
                    "MCP memory distillation failed for %s (fail-open): %s",
                    run_id,
                    exc,
                )
    except Exception:
        logger.exception("Failed to persist MCP run bundle for %s", run_id)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


_OSS_CONTRACT_INFO_CACHE: dict[str, Any] | None = None


def _oss_contract_info() -> dict[str, Any]:
    """Read OSS contract metadata from contracts/VERSION + contracts/tools/*.json.

    Computed once and cached; safe across the server's lifetime because the
    contract files are write-once at build time, not at runtime.
    """
    global _OSS_CONTRACT_INFO_CACHE
    if _OSS_CONTRACT_INFO_CACHE is not None:
        return _OSS_CONTRACT_INFO_CACHE

    import hashlib as _hl
    import json as _json

    from brain_researcher.config.paths import get_config_root

    repo_root = get_config_root().parent
    version_path = repo_root / "contracts" / "VERSION"
    tools_dir = repo_root / "contracts" / "tools"

    contract_version = (
        version_path.read_text().strip() if version_path.exists() else "0.0.0-unset"
    )

    stable_tier: list[dict[str, Any]] = []
    deprecated: list[dict[str, Any]] = []
    if tools_dir.exists():
        for path in sorted(tools_dir.glob("*.json")):
            try:
                entry = _json.loads(path.read_text())
            except Exception:
                continue
            stability = entry.get("stability")
            if stability == "stable":
                stable_tier.append(entry)
            elif stability == "deprecated":
                deprecated.append(
                    {
                        "name": entry.get("name"),
                        "replaced_by": entry.get("deprecated_in_favor_of"),
                    }
                )

    hasher = _hl.sha256()
    for entry in sorted(stable_tier, key=lambda e: e.get("name", "")):
        hasher.update((entry.get("name") or "").encode())
        hasher.update(b"\0")
        canonical = _json.dumps(
            {
                "name": entry.get("name"),
                "input_schema": entry.get("input_schema"),
                "output_schema": entry.get("output_schema"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        hasher.update(_hl.sha256(canonical.encode()).hexdigest().encode())
        hasher.update(b"\0")

    stable_names = sorted(e.get("name") for e in stable_tier if e.get("name"))
    capability_families = {e.get("capability_family") for e in stable_tier}

    _OSS_CONTRACT_INFO_CACHE = {
        "contract_version": contract_version,
        "toolset_hash": hasher.hexdigest(),
        "stable_tools": stable_names,
        "deprecated_tools": deprecated,
        "capabilities": {
            "planning": "planning" in capability_families,
            "pipeline_execution": "pipeline_execution" in capability_families,
            "scientific_review": "scientific_review" in capability_families
            or "scientific_report" in capability_families,
            "grounding": "grounding" in capability_families,
            "run_observability": "run_observability" in capability_families,
            "tool_discovery": "tool_discovery" in capability_families,
            "execution_recipe": "execution_recipe" in capability_families,
            "server_ops": "server_ops" in capability_families,
        },
    }
    return _OSS_CONTRACT_INFO_CACHE


@mcp.tool()
def server_info() -> dict[str, Any]:
    """Return server configuration/capabilities for clients."""
    dependency_status = _dependency_status_snapshot()
    compat_alias_usage = _compat_alias_usage_summary()
    tool_registry_mode_snapshot = {
        "BR_TOOL_REGISTRY_BACKEND": os.getenv("BR_TOOL_REGISTRY_BACKEND"),
        "BR_TOOL_REGISTRY_MUTATION_MODE": os.getenv("BR_TOOL_REGISTRY_MUTATION_MODE"),
        "BR_TOOL_REGISTRY_FAIL_OPEN": os.getenv("BR_TOOL_REGISTRY_FAIL_OPEN"),
        "BR_TOOL_EXECUTE_AUTO_REMAP": os.getenv("BR_TOOL_EXECUTE_AUTO_REMAP"),
    }
    contract_info = _oss_contract_info()
    return {
        "ok": True,
        "data": {
            "name": "brain-researcher",
            "contract_version": contract_info["contract_version"],
            "toolset_hash": contract_info["toolset_hash"],
            "capabilities": contract_info["capabilities"],
            "stable_tools": contract_info["stable_tools"],
            "deprecated_tools": contract_info["deprecated_tools"],
            "run_root": str(_runstore.RUN_ROOT),
            "run_roots_read": [str(p) for p in _run_roots_for_read()],
            "allowed_roots": [str(p) for p in ALLOWED_ROOTS],
            "allow_network": bool(ALLOW_NETWORK),
            "allow_dangerous": bool(ALLOW_DANGEROUS),
            "enable_tool_execute": bool(ENABLE_TOOL_EXECUTE),
            "selftest_enabled": bool(MCP_SELFTEST_ENABLED),
            "selftest_script_path": str(MCP_SELFTEST_SCRIPT_PATH),
            "agent_fallback_enabled": bool(AGENT_FALLBACK_ENABLED),
            "agent_delegation_enabled": bool(AGENT_DELEGATED_EXECUTION_ENABLED),
            "agent_api_url": AGENT_API_URL,
            "agent_fallback_timeout_ms": int(AGENT_FALLBACK_TIMEOUT_MS),
            "tool_execute_allowlist": sorted(TOOL_EXECUTE_ALLOWLIST),
            "agent_multiagent_enabled": bool(AGENT_MULTIAGENT_ENABLED),
            "agent_critic_plan_gate": bool(AGENT_CRITIC_PLAN_GATE),
            "agent_critic_tool_gate": bool(AGENT_CRITIC_TOOL_GATE),
            "agent_recovery_agent": bool(AGENT_RECOVERY_AGENT),
            "agent_critic_fail_open": bool(AGENT_CRITIC_FAIL_OPEN),
            "rm_logging_enabled": bool(RM_LOGGING_ENABLED),
            "rm_logging_policy": RM_LOGGING_POLICY,
            "max_text_bytes": int(MAX_TEXT_BYTES),
            "max_binary_bytes": int(MAX_BINARY_BYTES),
            "default_loop_profile_id": DEFAULT_LOOP_PROFILE_ID,
            "available_loop_profiles": list(SUPPORTED_LOOP_PROFILE_IDS),
            "dependency_status": dependency_status,
            "compat_alias_usage": compat_alias_usage,
            "tool_registry_mode_snapshot": tool_registry_mode_snapshot,
        },
    }


@mcp.tool()
def loop_profile_get(profile_id: str = DEFAULT_LOOP_PROFILE_ID) -> dict[str, Any]:
    """Return a machine-readable loop profile for external agents."""
    try:
        profile = get_loop_profile(profile_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "profile": profile}


def _literal_values(literal_type: Any) -> list[str]:
    return [str(value) for value in get_args(literal_type)]


def _missing_action_params_response(
    *,
    action: str | None,
    missing: list[str],
    supported_actions: list[str],
    message: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    action_text = action or "<missing>"
    return {
        "ok": False,
        "error": "missing_required_params",
        "message": message
        or (
            f"Missing required parameter(s) for action={action_text!r}: "
            + ", ".join(missing)
        ),
        "action": action,
        "missing_required_params": missing,
        "required_params": missing,
        "supported_actions": supported_actions,
        "sources": _SLURM_SCRIPT_SOURCES,
        **extra,
    }


def _slurm_guide_required_param_error(
    *,
    action: str,
    topic: str | None,
    intent: str | None,
) -> dict[str, Any] | None:
    normalized_action = _first_text_value(action)
    supported_actions = _literal_values(_SlurmGuideAction)
    if not normalized_action:
        return _missing_action_params_response(
            action=None,
            missing=["action"],
            supported_actions=supported_actions,
        )
    if normalized_action == "guide" and not _first_text_value(topic):
        return _missing_action_params_response(
            action=normalized_action,
            missing=["topic"],
            supported_actions=supported_actions,
            supported_topics=_literal_values(_SlurmGuideTopic),
        )
    if normalized_action == "command" and not _first_text_value(intent):
        return _missing_action_params_response(
            action=normalized_action,
            missing=["intent"],
            supported_actions=supported_actions,
            supported_intents=_literal_values(_SlurmCommandIntent),
        )
    return None


def _slurm_submit_required_param_error(
    *,
    action: str,
    template_kind: str | None,
    change_request: str | None,
    script_text: str | None,
    script_path: str | None,
    job_id: str | None,
    log_path: str | None,
) -> dict[str, Any] | None:
    normalized_action = _first_text_value(action)
    supported_actions = _literal_values(_SlurmAction)
    if not normalized_action:
        return _missing_action_params_response(
            action=None,
            missing=["action"],
            supported_actions=supported_actions,
        )

    missing: list[str] = []
    extra: dict[str, Any] = {}
    if normalized_action == "render_script":
        if not _first_text_value(template_kind):
            missing.append("template_kind")
        extra["supported_templates"] = _literal_values(_SlurmTemplateKind)
    elif normalized_action == "validate_script":
        if not (_first_text_value(script_text) or _first_text_value(script_path)):
            missing.append("script_text_or_script_path")
    elif normalized_action == "patch_script":
        if not _first_text_value(change_request):
            missing.append("change_request")
        if not (_first_text_value(script_text) or _first_text_value(script_path)):
            missing.append("script_text_or_script_path")
    elif normalized_action == "inspect_job":
        if not _first_text_value(job_id):
            missing.append("job_id")
    elif normalized_action == "read_logs":
        if not (_first_text_value(job_id) or _first_text_value(log_path)):
            missing.append("job_id_or_log_path")

    if not missing:
        return None
    return _missing_action_params_response(
        action=normalized_action,
        missing=missing,
        supported_actions=supported_actions,
        **extra,
    )


@mcp.tool()
def system_self_test(
    mode: str = "quick",
    include_kg: bool = True,
    include_container: bool = True,
    include_script: bool = True,
    include_inventory: bool = True,
    inventory_limit: int = 12,
    kg_query: str = "brain",
    strict: bool = False,
) -> dict[str, Any]:
    """Run an MCP self-test suite and return probe-level status."""
    if not MCP_SELFTEST_ENABLED:
        issues = [
            {
                "level": "error",
                "code": "self_test_disabled",
                "message": "Set BR_MCP_SELFTEST_ENABLED=1 to enable system_self_test.",
            }
        ]
        return {
            "ok": False,
            "error": "self_test_disabled",
            "message": "Set BR_MCP_SELFTEST_ENABLED=1 to enable system_self_test.",
            "mode": "quick",
            "overall": "fail",
            "counts": {"pass": 0, "warn": 0, "fail": 1, "skip": 0},
            "probes": [],
            "recommendations": [
                "Enable BR_MCP_SELFTEST_ENABLED and retry the self-test.",
            ],
            "issues": issues,
            "policy_issues": issues,
        }

    mode_normalized = str(mode or "quick").strip().lower()
    if mode_normalized not in {"quick", "active"}:
        return {
            "ok": False,
            "error": "invalid_mode",
            "message": "mode must be one of: quick, active",
        }

    probes: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    limit = max(1, min(int(inventory_limit), 50))
    normalized_kg_query = str(kg_query or "brain").strip() or "brain"

    started = time.perf_counter()
    try:
        info = server_info()
        ok = bool(isinstance(info, dict) and info.get("ok"))
        status = "pass" if ok else "fail"
        probe_error = None
        if not ok:
            probe_error = str(
                info.get("error") if isinstance(info, dict) else "unknown"
            )
        summary = (
            "server_info returned ok=true" if ok else "server_info returned failure"
        )
        probes.append(
            _selftest_probe_card(
                "server_info_probe",
                status=status,
                summary=summary,
                latency_ms=int((time.perf_counter() - started) * 1000),
                data={"ok": ok},
                error=probe_error,
            )
        )
    except Exception as exc:
        probes.append(
            _selftest_probe_card(
                "server_info_probe",
                status="fail",
                summary="server_info raised exception",
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    started = time.perf_counter()
    try:
        search = tool_search(
            query="workflow",
            limit=5,
            offset=0,
            modalities=None,
            kind=None,
            exposed_only=True,
            include_workflows=True,
            include_total=True,
        )
        ok = bool(isinstance(search, dict) and search.get("ok"))
        count = int(search.get("count") or 0) if isinstance(search, dict) else 0
        status = "pass" if ok else "fail"
        probe_error = None
        if not ok:
            probe_error = str(
                search.get("error") if isinstance(search, dict) else "unknown"
            )
        summary = (
            f"tool_search returned {count} result(s)"
            if ok
            else "tool_search returned failure"
        )
        probes.append(
            _selftest_probe_card(
                "tool_search_probe",
                status=status,
                summary=summary,
                latency_ms=int((time.perf_counter() - started) * 1000),
                data={"count": count},
                error=probe_error,
            )
        )
    except Exception as exc:
        probes.append(
            _selftest_probe_card(
                "tool_search_probe",
                status="fail",
                summary="tool_search raised exception",
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    probes.append(_selftest_meeg_sensor_connectivity_routing_probe())
    probes.append(_selftest_meeg_plan_preflight_routing_probe())

    if include_inventory:
        started = time.perf_counter()
        try:
            discovery = tool_search(
                query="",
                limit=limit,
                offset=0,
                modalities=None,
                kind=None,
                exposed_only=True,
                include_workflows=True,
                include_total=False,
            )
            ok = bool(isinstance(discovery, dict) and discovery.get("ok"))
            tools = (
                list(discovery.get("tools") or [])
                if isinstance(discovery, dict)
                else []
            )
            inventory = _selftest_inventory_cards(tools)
            status = "pass" if ok else "warn"
            probe_error = None
            if not ok:
                probe_error = str(
                    discovery.get("error") if isinstance(discovery, dict) else "unknown"
                )
            summary = (
                f"inventory captured {len(inventory)} tool card(s)"
                if ok
                else "inventory lookup failed"
            )
            probes.append(
                _selftest_probe_card(
                    "inventory_probe",
                    status=status,
                    summary=summary,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    data={"count": len(inventory)},
                    error=probe_error,
                )
            )
        except Exception as exc:
            probes.append(
                _selftest_probe_card(
                    "inventory_probe",
                    status="warn",
                    summary="inventory lookup raised exception",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    if mode_normalized == "active":
        if include_kg:
            started = time.perf_counter()
            try:
                kg = kg_search_nodes(query=normalized_kg_query, limit=1)
                ok = bool(isinstance(kg, dict) and kg.get("ok"))
                item_count = (
                    len(list(kg.get("items") or [])) if isinstance(kg, dict) else 0
                )
                status = "pass" if ok else "warn"
                probe_error = None
                if not ok:
                    probe_error = str(
                        kg.get("error") if isinstance(kg, dict) else "unknown"
                    )
                summary = (
                    f"kg probe returned {item_count} node(s)"
                    if ok
                    else "kg probe failed"
                )
                probes.append(
                    _selftest_probe_card(
                        "kg_probe",
                        status=status,
                        summary=summary,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        data={"query": normalized_kg_query, "items": item_count},
                        error=probe_error,
                    )
                )
            except Exception as exc:
                probes.append(
                    _selftest_probe_card(
                        "kg_probe",
                        status="warn",
                        summary="kg probe raised exception",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        else:
            probes.append(
                _selftest_probe_card(
                    "kg_probe",
                    status="skip",
                    summary="kg probe disabled by request",
                    latency_ms=0,
                )
            )

        if include_script:
            started = time.perf_counter()
            script_probe = _selftest_run_local_probe("script")
            if script_probe.get("ok"):
                payload = (
                    dict(script_probe.get("payload"))
                    if isinstance(script_probe.get("payload"), dict)
                    else {}
                )
                probes.append(
                    _selftest_probe_card(
                        "script_probe",
                        status="pass",
                        summary="script probe executed successfully",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        data=payload,
                    )
                )
            else:
                probes.append(
                    _selftest_probe_card(
                        "script_probe",
                        status="fail",
                        summary="script probe failed",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error=str(script_probe.get("error") or "script_probe_failed"),
                        policy_issues=list(script_probe.get("policy_issues") or []),
                        data={
                            "script_path": script_probe.get("script_path"),
                            "run_id": script_probe.get("run_id"),
                        },
                    )
                )
        else:
            probes.append(
                _selftest_probe_card(
                    "script_probe",
                    status="skip",
                    summary="script probe disabled by request",
                    latency_ms=0,
                )
            )

        if include_container:
            started = time.perf_counter()
            container_probe = _selftest_run_local_probe("container")
            if container_probe.get("ok"):
                payload = (
                    dict(container_probe.get("payload"))
                    if isinstance(container_probe.get("payload"), dict)
                    else {}
                )
                probes.append(
                    _selftest_probe_card(
                        "container_probe",
                        status="pass",
                        summary="container probe passed",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        data=payload,
                    )
                )
            else:
                payload = (
                    dict(container_probe.get("payload"))
                    if isinstance(container_probe.get("payload"), dict)
                    else {}
                )
                probes.append(
                    _selftest_probe_card(
                        "container_probe",
                        status="warn",
                        summary="container probe reported unavailable runtime",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error=str(
                            container_probe.get("error")
                            or payload.get("error")
                            or "container_probe_failed"
                        ),
                        policy_issues=list(container_probe.get("policy_issues") or []),
                        data={
                            "payload": payload or None,
                            "script_path": container_probe.get("script_path"),
                            "run_id": container_probe.get("run_id"),
                        },
                    )
                )
        else:
            probes.append(
                _selftest_probe_card(
                    "container_probe",
                    status="skip",
                    summary="container probe disabled by request",
                    latency_ms=0,
                )
            )

    if strict:
        for probe in probes:
            if probe.get("status") == "warn":
                probe["status"] = "fail"
                probe["ok"] = False
                probe["strict_escalated"] = True

    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for probe in probes:
        status = str(probe.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1

    if counts["fail"] > 0:
        overall = "fail"
    elif counts["warn"] > 0:
        overall = "degraded"
    else:
        overall = "pass"

    failed_or_warned = [
        str(p.get("id") or "")
        for p in probes
        if str(p.get("status") or "").strip().lower() in {"warn", "fail"}
    ]
    detail_suffix = (
        f" affected={','.join(failed_or_warned)}" if failed_or_warned else ""
    )
    summary_text = (
        f"MCP self-test mode={mode_normalized} overall={overall} "
        f"(pass={counts['pass']} warn={counts['warn']} fail={counts['fail']} skip={counts['skip']})."
        f"{detail_suffix}"
    )

    recommendations = _selftest_recommendations(probes)
    return {
        "ok": counts["fail"] == 0,
        "mode": mode_normalized,
        "overall": overall,
        "summary_text": summary_text,
        "counts": counts,
        "probes": probes,
        "recommendations": recommendations,
        "inventory": inventory,
        "strict": bool(strict),
    }


# ---------------------------------------------------------------------------
# SLURM / Sherlock tools (slurm_guide / sherlock_guide / slurm_submit /
# sherlock_slurm) extracted to mcp/routers/slurm.py. Importing it registers
# those tools (import side effect). The _slurm_*_required_param_error
# validators stay here and are imported back by the router.
# ---------------------------------------------------------------------------
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    slurm as _slurm_router,
)


@mcp.tool()
def tool_search(
    query: str,
    limit: int = 20,
    offset: int = 0,
    modalities: list[str] | None = None,
    kind: Kind | None = None,
    phases: list[str] | None = None,
    exposed_only: bool = True,
    include_workflows: bool = True,
    include_total: bool = True,
) -> dict[str, Any]:
    """Search Brain Researcher tools by capability keywords."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    normalized_phases = _normalize_phase_list(phases)
    reg = _get_registry()
    family_ranked_ids = _tool_search_family_ranked_ids(
        query,
        limit=limit + offset,
    )
    family_ranked_ids = [
        tool_id
        for tool_id in family_ranked_ids
        if not _is_retired_public_tool_name(tool_id)
    ]
    registry_limit = limit + offset
    registry_offset = 0
    search_kwargs = {
        "goal": query,
        "modalities": modalities,
        "kind": kind,
        "limit": registry_limit,
        "offset": registry_offset,
        "exposed_only": bool(exposed_only),
        "include_workflows": bool(include_workflows),
    }
    try:
        specs, total_matches = reg.search_toolspecs(
            phases=normalized_phases or None,
            **search_kwargs,
        )
    except TypeError:
        specs, total_matches = reg.search_toolspecs(**search_kwargs)
        if normalized_phases:
            specs = [
                spec
                for spec in specs
                if _card_matches_phases(spec.model_dump(), normalized_phases)
            ]
            total_matches = len(specs)
    workflow_rows_by_id: dict[str, dict[str, Any]] = {}
    if include_workflows:
        workflow_rows_by_id = {
            str(row.get("id") or "").strip(): row
            for row in _workflow_search_rows()
            if str(row.get("id") or "").strip()
        }

    cards = [
        _toolspec_for_mcp_card(s, workflow_entry=workflow_rows_by_id.get(s.name))
        for s in specs
        if not _is_retired_public_tool_name(s.name)
    ]
    if normalized_phases:
        cards = [
            card for card in cards if _card_matches_phases(card, normalized_phases)
        ]

    exposed_specs_by_id: dict[str, Any] = {}
    if family_ranked_ids and bool(exposed_only):
        try:
            from brain_researcher.services.tools.catalog_loader import load_tool_specs

            exposed_specs_by_id = {
                str(spec.name or "").strip(): spec
                for spec in load_tool_specs(
                    exposed_only=True,
                    include_workflows=bool(include_workflows),
                    agent_visible_only=False,
                )
                if str(spec.name or "").strip()
            }
        except Exception:
            logger.debug("Failed building exposed tool_search map", exc_info=True)

    seen = {str(card.get("name") or "").strip() for card in cards}
    for tool_id in family_ranked_ids:
        if _is_retired_public_tool_name(tool_id):
            continue
        if tool_id in seen:
            continue
        workflow_row = workflow_rows_by_id.get(tool_id)
        spec = (
            exposed_specs_by_id.get(tool_id)
            if bool(exposed_only)
            else reg.get_toolspec_by_name(tool_id)
        )
        if spec is not None:
            card = _toolspec_for_mcp_card(spec, workflow_entry=workflow_row)
            if not _card_matches_modalities(card, modalities):
                continue
            if normalized_phases and not _card_matches_phases(card, normalized_phases):
                continue
            cards.append(card)
            seen.add(tool_id)
            continue
        if workflow_row is not None and include_workflows:
            card = _toolspec_for_mcp_card(
                _workflow_toolspec_card(tool_id, include_schema=True),
                workflow_entry=workflow_row,
            )
            if not _card_matches_modalities(card, modalities):
                continue
            if normalized_phases and not _card_matches_phases(card, normalized_phases):
                continue
            cards.append(card)
            seen.add(tool_id)

    q = (query or "").strip().lower()
    if include_workflows:
        normalized_modalities = {
            str(item).strip().lower()
            for item in (modalities or [])
            if str(item).strip()
        }
        requested_kind = str(getattr(kind, "value", kind) or "").strip().lower()

        for row in workflow_rows_by_id.values():
            workflow_id = str(row.get("id") or "").strip()
            if not workflow_id or workflow_id in seen:
                continue
            if requested_kind and requested_kind not in {"analysis", "workflow"}:
                continue
            if normalized_modalities:
                row_modalities = {
                    str(item).strip().lower()
                    for item in (row.get("modalities") or [])
                    if str(item).strip()
                }
                if row_modalities and not (row_modalities & normalized_modalities):
                    continue
            workflow_text = _workflow_search_text(row)
            if (
                q
                and _search_match_score(
                    query,
                    workflow_text,
                    identifier=workflow_id,
                )
                <= 0
            ):
                continue
            card = _toolspec_for_mcp_card(
                _workflow_toolspec_card(workflow_id, include_schema=True),
                workflow_entry=row,
            )
            if normalized_phases and not _card_matches_phases(card, normalized_phases):
                continue
            cards.append(card)
            seen.add(workflow_id)

    cards = [
        card for card in cards if not _is_retired_public_tool_name(card.get("name"))
    ]
    cards = [card for card in cards if _card_matches_modalities(card, modalities)]

    if q:
        family_rank = {tool_id: rank for rank, tool_id in enumerate(family_ranked_ids)}
        ranked_cards: list[tuple[int, int, dict[str, Any]]] = []
        for index, card in enumerate(cards):
            identifier = str(card.get("name") or "").strip()
            text_parts = [_tool_search_card_text(card)]
            workflow_row = workflow_rows_by_id.get(identifier)
            if workflow_row is not None:
                text_parts.append(_workflow_search_text(workflow_row))
            rerank_boost = 0
            if identifier in family_rank:
                rerank_boost = 20_000 - (family_rank[identifier] * 250)
            ranked_cards.append(
                (
                    _search_match_score(
                        query,
                        " ".join(part for part in text_parts if part),
                        identifier=identifier,
                    )
                    + _tool_search_domain_adjustment(query, card)
                    + rerank_boost,
                    index,
                    card,
                )
            )
        ranked_cards.sort(key=lambda item: (-item[0], item[1]))
        cards = [card for _score, _index, card in ranked_cards]

    cards, qsm_gate = filter_qsm_tool_candidates(
        query=query,
        modality=modalities,
        candidates=cards,
    )
    cards = cards[offset : offset + limit]

    response: dict[str, Any] = {
        "ok": True,
        "tools": cards,
        "count": len(cards),
        "limit": limit,
        "offset": offset,
        "exposed_only": bool(exposed_only),
        "include_workflows": bool(include_workflows),
        "phases": normalized_phases or None,
    }
    if qsm_gate is not None:
        response["task_type_gate"] = qsm_gate
    if include_total:
        response["total_matches"] = int(total_matches)
    return response


@mcp.tool()
def workflow_search(
    query: str = "",
    limit: int = 20,
    offset: int = 0,
    include_param_schema_summary: bool = False,
) -> dict[str, Any]:
    """Search orchestration workflows (separate from ordinary tool_search)."""

    q = (query or "").strip().lower()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    workflows = _workflow_search_rows()

    if q:
        ranked_workflows: list[tuple[int, int, dict[str, Any]]] = []
        for index, row in enumerate(workflows):
            workflow_id = str(row.get("id") or "").strip()
            score = _search_match_score(
                query,
                _workflow_search_text(row),
                identifier=workflow_id,
            )
            if score > 0:
                ranked_workflows.append((score, index, row))
        ranked_workflows.sort(key=lambda item: (-item[0], item[1]))
        workflows = [row for _score, _index, row in ranked_workflows]

    total = len(workflows)
    sliced = workflows[offset : offset + limit]
    enriched_rows: list[dict[str, Any]] = []
    for row in sliced:
        copied = dict(row)
        workflow_id = str(copied.get("id") or "").strip()
        if workflow_id:
            copied.update(
                recipe_card_metadata(
                    workflow_id,
                    workflow_entry=row if isinstance(row, dict) else None,
                )
            )
            if copied.get("primary_target"):
                copied["requires_runtime"] = copied["primary_target"]
        copied.pop("runtime", None)
        copied.pop("impl", None)
        copied.pop("recipe_family", None)
        enriched_rows.append(copied)
    sliced = enriched_rows
    if include_param_schema_summary:
        enriched: list[dict[str, Any]] = []
        for row in sliced:
            copied = dict(row)
            copied["params_summary"] = _workflow_param_schema_summary(
                row.get("params") if isinstance(row, dict) else None
            )
            enriched.append(copied)
        sliced = enriched
    return {
        "ok": True,
        "workflows": sliced,
        "count": len(sliced),
        "total_matches": total,
        "limit": limit,
        "offset": offset,
        "include_param_schema_summary": bool(include_param_schema_summary),
    }


@mcp.tool()
def tool_search_structured(
    query: str | None = None,
    primary_intents: list[str] | None = None,
    softwares: list[str] | None = None,
    exposed_only: bool = True,
    default_only: bool = True,
    k_methods: int = 8,
    k_softwares: int = 5,
    k_candidates: int = 50,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Structured tool search (method → software → version) over KG."""
    try:
        from brain_researcher.services.br_kg import query_service

        data = query_service.search_tools_structured(
            query=query,
            primary_intents=primary_intents,
            softwares=softwares,
            exposed_only=exposed_only,
            default_only=default_only,
            k_methods=k_methods,
            k_softwares=k_softwares,
            k_candidates=k_candidates,
            force_fallback=force_fallback,
        )
        if isinstance(data, dict):
            _annotate_structured_resolver_metadata(
                data, force_fallback=bool(force_fallback)
            )
            _filter_retired_structured_tool_entries(data)
        try:
            reg = _get_registry()
            candidates = data.get("candidates", []) if isinstance(data, dict) else []
            for cand in candidates:
                tid = _canonicalize_structured_tool_entry(cand) or cand.get("tool_id")
                cand["available"] = _toolspec_available(reg, tid)
                cand["available_runtime"] = _tool_runtime_available(reg, tid)
                cand["availability_source"] = "toolspec_registry"
            if isinstance(data, dict):
                data["candidates"] = _fold_structured_candidates(candidates)
            rec = data.get("recommendation") if isinstance(data, dict) else None
            if isinstance(rec, dict) and rec.get("tool_id"):
                rec_tid = _canonicalize_structured_tool_entry(rec) or rec.get("tool_id")
                rec["available"] = _toolspec_available(reg, rec_tid)
                rec["available_runtime"] = _tool_runtime_available(reg, rec_tid)
                rec["availability_source"] = "toolspec_registry"
            if isinstance(data, dict) and data.get("candidates"):
                data["recommendation"] = data["candidates"][0]
        except Exception:
            pass

        return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def tool_resolve(
    method: str | None = None,
    software: str | None = None,
    op_key: str | None = None,
    prefer_version: str | None = None,
    exposed_only: bool = True,
    default_only: bool = True,
    force_fallback: bool = False,
) -> dict[str, Any]:
    """Resolve a tool_id from method/software/op_key (optionally version-pinned)."""
    try:
        from brain_researcher.services.br_kg import query_service

        data = query_service.resolve_tool_structured(
            method=method,
            software=software,
            op_key=op_key,
            prefer_version=prefer_version,
            exposed_only=exposed_only,
            default_only=default_only,
            force_fallback=force_fallback,
        )
        if isinstance(data, dict):
            _annotate_structured_resolver_metadata(
                data, force_fallback=bool(force_fallback)
            )
            _filter_retired_structured_tool_entries(data)
            try:
                reg = _get_registry()
                rec = data.get("recommendation")
                if isinstance(rec, dict):
                    rec_tid = _canonicalize_structured_tool_entry(rec) or rec.get(
                        "tool_id"
                    )
                    rec["available"] = _toolspec_available(reg, rec_tid)
                    rec["available_runtime"] = _tool_runtime_available(reg, rec_tid)
                    rec["availability_source"] = "toolspec_registry"
            except Exception:
                pass
        return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def tool_get(tool_id: str, include_schema: bool = True) -> dict[str, Any]:
    """Get a tool spec; optionally enrich with JSON schema for parameters."""
    if _is_retired_public_tool_name(tool_id):
        return {
            "ok": False,
            "error": "tool_removed",
            "message": f"{tool_id} is no longer exposed by the Brain Researcher MCP server.",
        }

    workflow_only = is_workflow_tool_id(tool_id)
    declared_workflow = _is_declared_workflow_id(tool_id)
    reg = _get_registry()
    spec = reg.get_toolspec_by_name(tool_id)
    if spec is None:
        if workflow_only and declared_workflow:
            return {
                "ok": False,
                "error": "workflow_registry_mismatch",
                "message": (
                    f"Workflow '{tool_id}' is known but missing from executable registry. "
                    "Rebuild tool specs and ensure workflow bridge registration is loaded."
                ),
            }
        return {"ok": False, "error": f"Unknown tool: {tool_id}"}

    if include_schema:
        enriched = _get_toolspec_with_schema(tool_id)
        if enriched is not None:
            spec = enriched
        else:
            spec = spec.model_copy(deep=True)
    else:
        spec = spec.model_copy(deep=True)

    if workflow_only:
        if not declared_workflow:
            return {
                "ok": False,
                "error": f"Unknown workflow: {tool_id}",
            }
        if not _toolspec_runtime_callable(spec):
            return {
                "ok": False,
                "error": "workflow_registry_mismatch",
                "message": (
                    f"Workflow '{tool_id}' is indexed but not callable at runtime "
                    f"(python_class={spec.python_class!r})."
                ),
            }
        spec = spec.model_copy(
            deep=True,
            update={
                "description": _prepend_agent_local_execution_warning(spec.description)
            },
        )

    response: dict[str, Any] = {
        "ok": True,
        "tool": _toolspec_for_mcp_card(
            spec,
            workflow_entry=_workflow_catalog_entry(tool_id) if workflow_only else None,
        ),
    }
    if workflow_only:
        response["workflow_only"] = True
        if is_recipe_first_mcp_workflow(tool_id):
            supported_targets = [
                str(target).strip()
                for target in (response["tool"].get("supported_recipe_targets") or [])
                if str(target).strip()
            ]
            target_text = (
                ", ".join(supported_targets) if supported_targets else "python"
            )
            if is_first_wave_heavy_runtime_workflow(tool_id):
                response["message"] = (
                    f"{AGENT_LOCAL_EXECUTION_WARNING} '{tool_id}' is a heavy runtime workflow. "
                    "Treat the MCP surface as recipe-first: generate an execution recipe "
                    f"via get_execution_recipe and run it through {target_text}; reserve "
                    "pipeline_plan_validate + pipeline_execute for manual/admin approval paths."
                )
            else:
                response["message"] = (
                    f"{AGENT_LOCAL_EXECUTION_WARNING} '{tool_id}' is a long-running batch analysis workflow. "
                    "Treat the MCP surface as recipe-first: generate a python execution "
                    f"recipe via get_execution_recipe and run the generated recipe with {target_text}; reserve "
                    "pipeline_plan_validate + pipeline_execute for manual/admin approval paths."
                )
        else:
            response["message"] = (
                f"{AGENT_LOCAL_EXECUTION_WARNING} '{tool_id}' is a declarative workflow. "
                "Prefer generating an explicit execution recipe or execution story via "
                "get_execution_recipe; reserve pipeline_plan_validate + "
                "pipeline_execute for manual/admin paths."
            )
    return response


# --- Categorical-arg contract aliases (see services/mcp/param_norm.py) -------
# Each maps lowercased/underscored synonyms -> canonical AND every canonical
# value -> itself, mirroring _KG_PROBE_TYPE_ALIASES. enum_str advertises the
# allowed set in the schema; coerce_enum / resolve_enum_or_error normalize what
# the client actually sends so a lax host never eats invalid_arguments.
_RECIPE_TARGET_ENUM: tuple[str, ...] = tuple(RECIPE_TARGETS)
_CLUSTER_PROFILE_ENUM: tuple[str, ...] = tuple(sorted(_SLURM_CLUSTER_PROFILES))
_KG_NEIGHBOR_DIRECTION_ENUM: tuple[str, ...] = ("out", "in", "both")
_KG_MULTIHOP_MODE_ENUM: tuple[str, ...] = (
    "bfs",
    "dfs",
    "shortest",
    "weighted",
    "bidirectional",
    "pattern",
)
_TOPOLOGY_SHIFT_MODE_ALIASES: dict[str, str] = {
    "detect": "detect",
    "proposal": "detect",
    "propose": "detect",
    "preview": "detect",
    "dry_run": "detect",
    "apply": "apply",
    "commit": "apply",
    "write": "apply",
}
_CANDIDATE_LANE_MODE_ALIASES: dict[str, str] = {
    "broad": "broad",
    "wide": "broad",
    "recall": "broad",
    "high_recall": "broad",
    "strict": "strict",
    "narrow": "strict",
    "precise": "strict",
    "precision": "strict",
}
_FRONTIER_MODE_ALIASES: dict[str, str] = {
    "off": "off",
    "none": "off",
    "disabled": "off",
    "false": "off",
    "frontier": "frontier",
    "on": "frontier",
    "enabled": "frontier",
    "true": "frontier",
    "wow": "frontier",
}
_TASTE_MODE_ALIASES: dict[str, str] = {
    "balanced": "balanced",
    "novelty_first": "novelty_first",
    "novelty": "novelty_first",
    "evidence_first": "evidence_first",
    "evidence": "evidence_first",
}
_CONTROLLER_MODE_ALIASES: dict[str, str] = {
    "principle_v0": "principle_v0",
    "principle": "principle_v0",
    "v0": "principle_v0",
}


@mcp.tool()
def get_execution_recipe(
    tool_id: str,
    params: dict[str, Any] | None = None,
    target_runtime: (
        enum_str(_RECIPE_TARGET_ENUM, "execution recipe target runtime") | None
    ) = None,
    cluster_profile: enum_str(
        _CLUSTER_PROFILE_ENUM, "SLURM cluster profile name"
    ) = DEFAULT_CLUSTER_PROFILE,
    include_legacy_local_run: bool = False,
) -> dict[str, Any]:
    """Return a stateless execution recipe for a public MCP tool or workflow."""

    params = params or {}
    if not isinstance(params, dict):
        return {
            "ok": False,
            "requested_tool_id": tool_id,
            "resolved_tool_id": None,
            "target_runtime": target_runtime,
            "cluster_profile": cluster_profile,
            "supported_recipe_targets": [],
            "recipe_depth": "summary",
            "warnings": [],
            "unsupported_reason": "params must be an object",
            "error": "invalid_recipe_params",
        }

    requested_target = str(target_runtime or "").strip().lower()
    auto_target = requested_target in AUTO_RECIPE_TARGETS
    if requested_target and not auto_target and requested_target not in RECIPE_TARGETS:
        return {
            "ok": False,
            "requested_tool_id": tool_id,
            "resolved_tool_id": None,
            "target_runtime": requested_target,
            "cluster_profile": cluster_profile,
            "supported_recipe_targets": list(RECIPE_TARGETS),
            "recipe_depth": "summary",
            "warnings": [],
            "unsupported_reason": (
                f"target_runtime must be one of {list(RECIPE_TARGETS)}"
            ),
            "error": "unsupported_recipe_target",
        }

    spec, workflow_entry = _resolve_recipe_context(tool_id)
    metadata = resolve_recipe_metadata(
        tool_id, spec=spec, workflow_entry=workflow_entry
    )
    normalized_target = (
        ("" if auto_target else requested_target)
        or default_recipe_target(tool_id, spec=spec, workflow_entry=workflow_entry)
        or "python"
    )
    if (
        spec is None
        and workflow_entry is None
        and not metadata.get("known_recipe_subject")
    ):
        return {
            "ok": False,
            "requested_tool_id": tool_id,
            "resolved_tool_id": None,
            "target_runtime": normalized_target,
            "cluster_profile": cluster_profile,
            "supported_recipe_targets": [],
            "recipe_depth": "summary",
            "warnings": [],
            "unsupported_reason": f"Unknown tool: {tool_id}",
            "error": "unknown_tool",
        }

    recipe_resp = build_execution_recipe(
        tool_id,
        params=params,
        target_runtime=normalized_target,
        cluster_profile=cluster_profile or DEFAULT_CLUSTER_PROFILE,
        spec=spec,
        workflow_entry=workflow_entry,
        include_legacy_local_run=bool(include_legacy_local_run),
    )
    recipe_resp.setdefault("requested_tool_id", tool_id)
    recipe_resp.setdefault(
        "resolved_tool_id", spec.name if spec is not None else tool_id
    )
    return recipe_resp


_PLAN_EXECUTION_SCHEMA_VERSION = "br-plan-execution-v1"
PIPELINE_EXECUTE_CONFIRM_PHRASE = "I_UNDERSTAND_CONFIRM_BEFORE_EXECUTE"
PIPELINE_EXECUTE_ADMIN_PHRASE = "I_UNDERSTAND_ADMIN_EXECUTION_RISK"
_PIPELINE_EXECUTION_CONTRACT_ERROR_CODES = {
    "execution_contract_required",
    "execution_contract_invalid",
    "execution_contract_tool_mismatch",
}
_PIPELINE_EXECUTION_GATE_ERROR_CODES = {
    "execution_recipe_required",
    "execution_manual_review_required",
    "execution_confirmation_required",
    "execution_admin_approval_required",
}


def _normalize_query_understanding_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    try:
        dumped = asdict(value)
    except Exception:
        dumped = None
    return dumped if isinstance(dumped, dict) else {}


def _collect_dataset_refs(*sources: Any) -> list[str]:
    refs: list[str] = []

    def _add(value: Any) -> None:
        text = _text_value(value)
        if text and text not in refs:
            refs.append(text)

    for source in sources:
        mapping = _record_dict(source)
        _add(mapping.get("dataset_ref"))
        _add(mapping.get("dataset_id"))
        for key in ("resolved_datasets", "candidate_datasets", "datasets"):
            items = mapping.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                row = _record_dict(item)
                _add(
                    _first_text_value(
                        row.get("dataset_ref"),
                        row.get("dataset_id"),
                        row.get("id"),
                        row.get("openneuro_id"),
                        row.get("ref"),
                    )
                )
    return refs


def _collect_string_items(source: Any, *keys: str) -> list[str]:
    values: list[str] = []
    mapping = _record_dict(source)
    for key in keys:
        raw = mapping.get(key)
        if isinstance(raw, list):
            for item in raw:
                text = _text_value(item)
                if text and text not in values:
                    values.append(text)
    return values


def _agent_plan_payload_from_args(
    *,
    query: str,
    domain: str,
    modality: list[str] | None,
    inputs: dict[str, Any] | None,
    allowlist_mode: str | None,
    query_understanding: dict[str, Any] | None,
    include_debug: bool,
) -> dict[str, Any]:
    from brain_researcher.services.shared.planner.models import PlanRequest

    payload = {
        "pipeline": query,
        "query": query,
        "domain": domain,
        "modality": list(modality or []),
        "inputs": inputs or {},
    }
    if allowlist_mode:
        payload["allowlist_mode"] = allowlist_mode
    if query_understanding:
        payload["query_understanding"] = query_understanding
    if include_debug:
        payload["debug_selection"] = True

    normalized = PlanRequest.model_validate(payload).model_dump(mode="json")
    normalized["query"] = query
    if include_debug:
        normalized["debug_selection"] = True
    return normalized


def _call_agent_plan_contract(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from brain_researcher.services.agent.web_service import app as agent_app

    with agent_app.test_client() as client:
        response = client.post("/agent/plan", json=payload)
    body = response.get_json(silent=True)
    return int(response.status_code), body if isinstance(body, dict) else {}


def _plan_steps_payload(plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
    dag = _record_dict(plan_payload.get("dag"))
    raw_steps = dag.get("steps") or plan_payload.get("steps") or []
    return [step for step in raw_steps if isinstance(step, dict)]


def _estimate_plan_cost(step_tools: list[str]) -> str:
    order = {"cheap": 0, "normal": 1, "expensive": 2}
    selected = "cheap"
    reg = _get_registry()
    for tool_id in step_tools:
        spec = reg.get_toolspec_by_name(tool_id)
        hint = _text_value(getattr(spec, "cost_hint", None)) or "normal"
        if order.get(hint, 1) > order.get(selected, 0):
            selected = hint
    return selected


def _candidate_tool_id(candidate: Any) -> str:
    row = _record_dict(candidate)
    return _first_text_value(
        row.get("tool_id"),
        row.get("name"),
        row.get("id"),
        row.get("workflow_id"),
    )


def _normalize_preflight_modality_tokens(value: Any) -> set[str]:
    raw_values: list[Any]
    if value is None:
        raw_values = []
    elif isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, dict):
        raw_values = list(value.values())
    elif isinstance(value, list | tuple | set):
        raw_values = list(value)
    else:
        raw_values = [value]

    tokens: set[str] = set()
    for raw_value in raw_values:
        if isinstance(raw_value, list | tuple | set):
            tokens.update(_normalize_preflight_modality_tokens(raw_value))
            continue
        text = str(raw_value or "").strip().lower()
        if not text:
            continue
        parts = re.split(r"[^a-z0-9+]+", text)
        for part in parts:
            if not part:
                continue
            if part in {"m", "meeg", "m+eeg"}:
                tokens.update({"meg", "eeg"})
            elif part in {"meg", "magnetoencephalography"}:
                tokens.add("meg")
            elif part in {"eeg", "electroencephalography"}:
                tokens.add("eeg")
            elif part in {"fmri", "fmr", "bold", "func"}:
                tokens.add("fmri")
            else:
                tokens.add(part)
        if "m/eeg" in text or "m-eeg" in text:
            tokens.update({"meg", "eeg"})
    return tokens


def _explicit_preflight_modalities(route_bundle: dict[str, Any]) -> set[str]:
    modalities = _normalize_preflight_modality_tokens(route_bundle.get("modality"))
    query = str(route_bundle.get("query") or "").lower()
    if re.search(r"\bm[/+-]?eeg\b", query):
        modalities.update({"meg", "eeg"})
    if re.search(r"\bmeg\b|magnetoencephalography", query):
        modalities.add("meg")
    if re.search(r"\beeg\b|electroencephalography", query):
        modalities.add("eeg")
    if re.search(r"\bf[-\s]?mri\b|\bfmri\b|\bbold\b", query):
        modalities.add("fmri")
    return modalities


def _candidate_modalities(candidate: Any) -> set[str]:
    row = _record_dict(candidate)
    modalities: set[str] = set()
    for key in ("modalities", "modality", "supported_modalities"):
        modalities.update(_normalize_preflight_modality_tokens(row.get(key)))
    metadata = _record_dict(row.get("metadata"))
    if metadata:
        for key in ("modalities", "modality", "supported_modalities"):
            modalities.update(_normalize_preflight_modality_tokens(metadata.get(key)))
    return modalities


def _tool_modalities_for_preflight_selection(
    tool_id: str,
    tool_candidates: list[dict[str, Any]],
) -> set[str]:
    for candidate in tool_candidates:
        if _candidate_tool_id(candidate) == tool_id:
            modalities = _candidate_modalities(candidate)
            if modalities:
                return modalities
    try:
        spec = _get_registry().get_toolspec_by_name(tool_id)
    except Exception:
        spec = None
    if spec is None:
        return set()
    if isinstance(spec, dict):
        modalities: set[str] = set()
        for key in ("modalities", "modality", "supported_modalities"):
            modalities.update(_normalize_preflight_modality_tokens(spec.get(key)))
        return modalities
    modalities = set()
    for key in ("modalities", "modality", "supported_modalities"):
        modalities.update(
            _normalize_preflight_modality_tokens(getattr(spec, key, None))
        )
    return modalities


def _first_modality_matching_preflight_candidate(
    route_bundle: dict[str, Any],
    *,
    explicit_modalities: set[str],
    skipped: set[str],
) -> str:
    if not explicit_modalities:
        return ""
    for candidate in route_bundle.get("tool_candidates") or []:
        tool_id = _candidate_tool_id(candidate)
        if not tool_id or tool_id in skipped:
            continue
        modalities = _candidate_modalities(candidate)
        if not modalities:
            modalities = _tool_modalities_for_preflight_selection(
                tool_id,
                list(route_bundle.get("tool_candidates") or []),
            )
        if modalities and modalities & explicit_modalities:
            return tool_id
    return ""


def _infer_dataset_refs_from_query(query: str) -> list[str]:
    q = str(query or "").lower()
    refs: list[str] = []
    for needle, ref in (
        ("haxby", "haxby"),
        ("ds000105", "ds000105"),
        ("adhd", "adhd"),
        ("abide", "abide"),
        ("ds000114", "ds000114"),
    ):
        if needle in q and ref not in refs:
            refs.append(ref)
    return refs


def _infer_preflight_purpose(
    tool_id: str, query: str, candidate: Any | None = None
) -> str:
    candidate_row = _record_dict(candidate)
    text = " ".join(
        item
        for item in (
            tool_id,
            query,
            str(candidate_row.get("description") or ""),
            str(candidate_row.get("summary") or ""),
        )
        if item
    ).lower()
    if "bids" in text and ("valid" in text or "layout" in text):
        return "bids_validation"
    if any(token in text for token in ("fmriprep", "preprocess", "preproc")):
        return "fmri_preprocessing"
    if any(token in text for token in ("freesurfer", "recon-all", "surface")):
        return "surface_reconstruction"
    if "mriqc" in text or "quality" in text or "qc" in text:
        return "qc_reporting"
    if any(token in text for token in ("first_level", "glm", "hrf", "contrast")):
        return "first_level_glm"
    if any(token in text for token in ("connectivity", "connectome", "msdl", "atlas")):
        return "connectivity_extraction"
    if any(token in text for token in ("permutation", "permuted_ols", "palm")):
        return "permutation_inference"
    if any(token in text for token in ("tedana", "multi-echo", "multi_echo")):
        return "multi_echo_denoising"
    if any(token in text for token in ("combat", "harmoni", "site")):
        return "site_harmonization"
    if any(token in text for token in ("neurosynth", "nimare", "ale", "meta-analysis")):
        return "coordinate_meta_analysis"
    if any(token in text for token in ("dataset", "openneuro", "fetch_")):
        return "dataset_access"
    return "tool_selection"


def _infer_preflight_route_tool_ids(query: str) -> list[tuple[str, str]]:
    q = str(query or "").lower()
    routes: list[tuple[str, str]] = []

    def add(purpose: str, tool_id: str) -> None:
        route = (purpose, tool_id)
        if route not in routes:
            routes.append(route)

    if "bids" in q and ("valid" in q or "layout" in q or "structure" in q):
        add("bids_validation", "validate_bids_structure")
    if "fmriprep" in q or "preprocess" in q or "preprocessing" in q:
        add("fmri_preprocessing", "fmriprep")
    if "mriqc" in q or ("quality" in q and "report" in q):
        add("qc_reporting", "mriqc")
    if "first-level" in q or "first level" in q or "glm" in q or "hrf" in q:
        add("first_level_glm", "glm_first_level")
    if "contrast" in q and ("glm" in q or "condition" in q):
        add("contrast_estimation", "glm_first_level")
    if "connectivity" in q or "connectome" in q:
        add("connectivity_extraction", "nilearn_connectivity_matrix")
        if "confound" in q or "resting" in q or "rest" in q:
            add("confound_cleaning", "clean_confounds")
    if "svm" in q or "classifier" in q or "decode" in q or "decoding" in q:
        add("supervised_decoding", "nilearn_decoding")
    if "neurosynth" in q or "ale" in q or "meta-analysis" in q:
        add("study_search", "neurosynth_search_terms")
        add("coordinate_meta_analysis", "coordinate_meta_analysis")
    if "permutation" in q or "label-shuffle" in q or "label shuffle" in q:
        add("permutation_inference", "permutation_testing")
        add("multiple_comparison_control", "multiple_comparison_correction")
    if "combat" in q or "harmoni" in q or "site effect" in q:
        add("site_harmonization", "harmonize_data")
        add("site_effect_diagnostics", "detect_outliers")
    if "tedana" in q or "multi-echo" in q or "multi_echo" in q:
        add("multi_echo_denoising", "tedana")
        add("confound_cleaning", "clean_confounds")

    return routes


def _is_explicit_meeg_connectivity_route(
    query: str,
    modality: list[str] | None,
) -> bool:
    q = str(query or "").lower()
    if "connectivity" not in q and "connectome" not in q:
        return False
    explicit_modalities = _normalize_preflight_modality_tokens(modality)
    if re.search(r"\bm[/+-]?eeg\b", q):
        explicit_modalities.update({"meg", "eeg"})
    if re.search(r"\bmeg\b|magnetoencephalography", q):
        explicit_modalities.add("meg")
    if re.search(r"\beeg\b|electroencephalography", q):
        explicit_modalities.add("eeg")
    if re.search(r"\bf[-\s]?mri\b|\bfmri\b|\bbold\b", q):
        explicit_modalities.add("fmri")
    return (
        bool(explicit_modalities & {"meg", "eeg"}) and "fmri" not in explicit_modalities
    )


def _supplemental_meeg_connectivity_route_tool_id(
    query: str,
    modality: list[str] | None,
) -> str:
    if not _is_explicit_meeg_connectivity_route(query, modality):
        return ""
    requested_modalities = sorted(
        _normalize_preflight_modality_tokens(modality) & {"meg", "eeg"}
    )
    if not requested_modalities:
        requested_modalities = ["eeg", "meg"]
    try:
        search_result = tool_search(
            query,
            limit=8,
            modalities=requested_modalities,
            phases=["execute"],
            exposed_only=True,
            include_workflows=True,
            include_total=False,
        )
    except Exception:
        logger.debug(
            "supplemental MEG/EEG connectivity route lookup failed",
            exc_info=True,
        )
        return ""
    tools = search_result.get("tools")
    if not isinstance(tools, list):
        return ""
    for candidate in tools:
        if _candidate_tool_id(candidate) == "mne_connectivity":
            return "mne_connectivity"
    return ""


def _append_preflight_next_call(
    calls: list[dict[str, Any]],
    *,
    purpose: str,
    tool_name: str,
    arguments: dict[str, Any],
    rationale: str,
    counts_as_routing_path: bool = True,
) -> None:
    key = (purpose, tool_name, json.dumps(arguments, sort_keys=True, default=str))
    for existing in calls:
        existing_key = (
            existing.get("purpose"),
            existing.get("tool_name"),
            json.dumps(existing.get("arguments") or {}, sort_keys=True, default=str),
        )
        if existing_key == key:
            return
    calls.append(
        {
            "purpose": purpose,
            "tool_name": tool_name,
            "arguments": arguments,
            "rationale": rationale,
            "counts_as_routing_path": bool(counts_as_routing_path),
        }
    )


def _plan_preflight_recommended_next_calls(
    *,
    query: str,
    facts: dict[str, Any],
    modality: list[str] | None,
    tool_candidates: list[dict[str, Any]],
    selection_mode: bool,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    dataset_refs = [
        str(ref).strip()
        for ref in (
            list(facts.get("dataset_refs") or [])
            + _infer_dataset_refs_from_query(query)
        )
        if str(ref).strip()
    ]
    seen_refs: set[str] = set()
    for dataset_ref in dataset_refs[:3]:
        if dataset_ref in seen_refs:
            continue
        seen_refs.add(dataset_ref)
        _append_preflight_next_call(
            calls,
            purpose="dataset_access",
            tool_name="dataset_get_resources",
            arguments={"dataset_ref": dataset_ref},
            rationale="Resolve dataset resources through the BR dataset resource route.",
        )

    q = query.lower()
    if "bids" in q and ("valid" in q or "layout" in q or "structure" in q):
        params: dict[str, Any] = {
            "task": query,
            "mode": "routing_only",
            "no_download": True,
            "no_heavy_execution": True,
        }
        if seen_refs:
            params["dataset_ref"] = sorted(seen_refs)[0]
        _append_preflight_next_call(
            calls,
            purpose="bids_validation",
            tool_name="get_execution_recipe",
            arguments={
                "tool_id": "validate_bids_structure",
                "params": params,
                "target_runtime": "python",
            },
            rationale="Select the concrete BIDS validation route rather than probing for executables.",
        )

    for purpose, tool_id in _infer_preflight_route_tool_ids(query):
        route_tool_id = tool_id
        rationale = (
            "Use BR's query-derived route shortlist to commit to a concrete "
            "scientific tool."
        )
        if (
            purpose == "connectivity_extraction"
            and tool_id == "nilearn_connectivity_matrix"
        ):
            supplemental_tool_id = _supplemental_meeg_connectivity_route_tool_id(
                query,
                modality,
            )
            if supplemental_tool_id:
                route_tool_id = supplemental_tool_id
                rationale = (
                    "Use an exposed execute-capable M/EEG connectivity route "
                    "instead of the fMRI-only hardcoded connectivity fallback."
                )
        if any(
            call.get("purpose") == purpose
            and call.get("tool_name") == "get_execution_recipe"
            and _record_dict(call.get("arguments")).get("tool_id") == route_tool_id
            for call in calls
        ):
            continue
        _append_preflight_next_call(
            calls,
            purpose=purpose,
            tool_name="get_execution_recipe",
            arguments={
                "tool_id": route_tool_id,
                "params": {
                    "task": query,
                    "mode": "routing_only",
                    "no_download": True,
                    "no_heavy_execution": True,
                },
                "target_runtime": default_recipe_target(route_tool_id) or "python",
            },
            rationale=rationale,
        )

    for candidate in tool_candidates[:8]:
        tool_id = _candidate_tool_id(candidate)
        if not tool_id:
            continue
        if tool_id in {
            "tool_search",
            "tool_search_structured",
            "plan_preflight",
            "dataset_get_resources",
        }:
            continue
        _append_preflight_next_call(
            calls,
            purpose=_infer_preflight_purpose(tool_id, query, candidate),
            tool_name="get_execution_recipe",
            arguments={
                "tool_id": tool_id,
                "params": {
                    "task": query,
                    "mode": "routing_only",
                    "no_download": True,
                    "no_heavy_execution": True,
                },
                "target_runtime": default_recipe_target(tool_id) or "python",
            },
            rationale="Commit to this candidate by requesting its stateless execution recipe.",
        )

    return calls[:5] if selection_mode else calls[:8]


def _plan_preflight_route_bundle(
    *,
    query: str,
    domain: str,
    modality: list[str] | None,
    inputs: dict[str, Any] | None,
    allowlist_mode: str | None,
    selection_mode: bool,
    runtime_surface: str,
    query_understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared plan_preflight routing shortlist."""

    from brain_researcher.services.agent.tool_candidate_service import (
        generate_tool_candidates,
    )

    working_query = _text_value(query)
    normalized_modality = _normalize_qsm_modality_list(modality)
    ctx: dict[str, Any] = {"runtime_surface": runtime_surface}
    if query_understanding:
        ctx["query_understanding"] = query_understanding

    bundle = generate_tool_candidates(
        working_query,
        ctx=ctx,
        tool_retriever=None,
        registry=None,
    )
    normalized_query_understanding = _normalize_query_understanding_payload(
        bundle.query_understanding
    )
    search_result = tool_search(
        working_query,
        limit=12,
        modalities=normalized_modality,
        phases=["explore", "plan"],
        exposed_only=str(allowlist_mode or "").strip().lower() != "diagnostic",
        include_workflows=True,
        include_total=False,
    )
    qsm_gate = search_result.get("task_type_gate")
    tool_candidates = search_result.get("tools", [])
    if not isinstance(tool_candidates, list):
        tool_candidates = []
    if qsm_gate is None:
        qsm_gate = qsm_retrieval_gate(
            query=working_query,
            domain=domain,
            modality=normalized_modality,
            candidates=tool_candidates,
        )
    facts = {
        "query_understanding": normalized_query_understanding,
        "dataset_refs": _collect_dataset_refs(
            inputs or {},
            normalized_query_understanding,
            bundle.resolution_state,
        ),
        "derivatives": _collect_string_items(
            normalized_query_understanding,
            "derivatives",
            "available_derivatives",
            "existing_derivatives",
        ),
        "blockers": _collect_string_items(
            normalized_query_understanding,
            "blockers",
            "missing_inputs",
            "missing_derivatives",
            "pending_decisions",
        ),
        "data_quality_concerns": _collect_string_items(
            normalized_query_understanding,
            "data_quality_flags",
            "qc_flags",
            "quality_concerns",
        ),
        "resolution_state": bundle.resolution_state,
    }
    recommended_next_calls = _plan_preflight_recommended_next_calls(
        query=working_query,
        facts=facts,
        modality=normalized_modality,
        tool_candidates=tool_candidates,
        selection_mode=bool(selection_mode),
    )
    if qsm_gate is not None:
        # QSM guidance must be non-displacive: do not route agents into
        # generic fMRI/fieldmap tools when no QSM-specific candidate exists.
        recommended_next_calls = []

    return {
        "query": working_query,
        "domain": domain,
        "modality": normalized_modality,
        "facts": facts,
        "tool_candidates": tool_candidates,
        "recommended_next_calls": recommended_next_calls,
        "routing_diagnostics": dict(bundle.tool_candidate_diagnostics or {}),
        "task_type_gate": qsm_gate,
    }


def _select_preflight_plan_tool_id(route_bundle: dict[str, Any]) -> str:
    skipped = {
        "tool_search",
        "tool_search_structured",
        "plan_preflight",
        "dataset_get_resources",
    }
    tool_candidates = list(route_bundle.get("tool_candidates") or [])
    explicit_modalities = _explicit_preflight_modalities(route_bundle)
    for call in route_bundle.get("recommended_next_calls") or []:
        call_row = _record_dict(call)
        if call_row.get("tool_name") != "get_execution_recipe":
            continue
        tool_id = _text_value(_record_dict(call_row.get("arguments")).get("tool_id"))
        if tool_id and tool_id not in skipped:
            tool_modalities = _tool_modalities_for_preflight_selection(
                tool_id,
                tool_candidates,
            )
            if (
                explicit_modalities
                and tool_modalities
                and not (tool_modalities & explicit_modalities)
            ):
                matching_candidate = _first_modality_matching_preflight_candidate(
                    route_bundle,
                    explicit_modalities=explicit_modalities,
                    skipped=skipped,
                )
                if matching_candidate:
                    return matching_candidate
            return tool_id
    for candidate in route_bundle.get("tool_candidates") or []:
        tool_id = _candidate_tool_id(candidate)
        if tool_id and tool_id not in skipped:
            return tool_id
    return ""


_PREFLIGHT_SELECT_SKIPPED = {
    "tool_search",
    "tool_search_structured",
    "plan_preflight",
    "dataset_get_resources",
}


def _preflight_selection_trace(
    route_bundle: dict[str, Any],
    selected_tool_id: str,
    *,
    trace_limit: int = 15,
) -> dict[str, Any]:
    """Additive fallback-path routing trace (diagnostics-only; no behaviour change).

    Mirrors ``_select_preflight_plan_tool_id`` to make the selection PATH visible on
    the plan_preflight fallback path — the path where the MEG mis-route lives. The
    key signal is ``preflight_selected_via == "recommended_next_calls"`` (a keyword/
    recommendation route, ``_plan_preflight_recommended_next_calls`` /
    ``_infer_preflight_route_tool_ids``) winning over the embedding-ranked
    ``tool_candidates``, and/or ``preflight_selected_outranked_by > 0`` (the selected
    tool was not the top candidate).
    """

    candidates = route_bundle.get("tool_candidates") or []
    candidate_trace: list[dict[str, Any]] = []
    selected_rank: int | None = None
    for idx, candidate in enumerate(candidates, start=1):
        tid = _candidate_tool_id(candidate)
        is_selected = bool(tid) and tid == selected_tool_id
        if is_selected and selected_rank is None:
            selected_rank = idx
        if idx <= trace_limit:
            candidate_trace.append(
                {"rank": idx, "tool_id": tid, "selected": is_selected}
            )

    # Replicate the selector's first-choice: the first non-skipped get_execution_recipe
    # in recommended_next_calls. If that equals the selection, it won over candidates.
    recommended_pick: str | None = None
    for call in route_bundle.get("recommended_next_calls") or []:
        call_row = _record_dict(call)
        if call_row.get("tool_name") != "get_execution_recipe":
            continue
        tid = _text_value(_record_dict(call_row.get("arguments")).get("tool_id"))
        if tid and tid not in _PREFLIGHT_SELECT_SKIPPED:
            recommended_pick = tid
            break

    if recommended_pick is not None and recommended_pick == selected_tool_id:
        selected_via = "recommended_next_calls"
    elif selected_rank == 1:
        selected_via = "candidate_top"
    elif selected_rank is not None:
        selected_via = "candidate_lower"
    else:
        selected_via = "none"

    if selected_rank is None:
        outranked_by: int | None = None
    else:
        outranked_by = selected_rank - 1
    return {
        "preflight_candidate_trace": candidate_trace,
        "preflight_selected_rank": selected_rank,
        "preflight_selected_via": selected_via,
        "preflight_selected_outranked_by": outranked_by,
        "preflight_recommended_pick": recommended_pick,
    }


def _plan_create_candidate_rows(
    tool_candidates: list[dict[str, Any]],
    *,
    selected_tool_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected_row: dict[str, Any] | None = None
    seen: set[str] = set()

    for candidate in tool_candidates:
        if not isinstance(candidate, dict):
            continue
        tool_id = _candidate_tool_id(candidate)
        if not tool_id or tool_id in seen:
            continue
        seen.add(tool_id)
        row = dict(candidate)
        row["tool_id"] = tool_id
        row.setdefault("source", row.get("source") or "plan_preflight")
        if tool_id == selected_tool_id:
            selected_row = row
        else:
            rows.append(row)

    if selected_row is None:
        selected_row = {
            "tool_id": selected_tool_id,
            "source": "plan_preflight_route",
        }
    return [selected_row] + rows


def _plan_step_runtime_kind(tool_id: str) -> str:
    try:
        spec = _get_registry().get_toolspec_by_name(tool_id)
    except Exception:
        spec = None
    runtime = _first_text_value(
        getattr(spec, "runtime_kind", None),
        getattr(spec, "backend", None),
        default_recipe_target(tool_id, spec=spec),
    )
    runtime = runtime.lower()
    if runtime == "python":
        return "python"
    if runtime in {"api", "mcp", "external_api"}:
        return "api"
    return "container"


def _without_no_suitable_tool_warnings(warnings: Any) -> list[str]:
    cleaned: list[str] = []
    for warning in warnings or []:
        text = _text_value(warning)
        if not text or text.startswith("No suitable tools found for query:"):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _apply_plan_preflight_fallback(
    plan_payload: dict[str, Any],
    *,
    query: str,
    domain: str,
    modality: list[str] | None,
    inputs: dict[str, Any] | None,
    allowlist_mode: str | None,
    query_understanding: dict[str, Any] | None,
) -> dict[str, Any]:
    if _plan_steps_payload(plan_payload):
        return plan_payload

    route_bundle = _plan_preflight_route_bundle(
        query=query,
        domain=domain,
        modality=modality,
        inputs=inputs,
        allowlist_mode=allowlist_mode,
        selection_mode=False,
        runtime_surface="plan_create",
        query_understanding=query_understanding,
    )
    selected_tool_id = _select_preflight_plan_tool_id(route_bundle)
    if not selected_tool_id:
        return plan_payload

    updated = dict(plan_payload)
    candidate_rows = _plan_create_candidate_rows(
        list(route_bundle.get("tool_candidates") or []),
        selected_tool_id=selected_tool_id,
    )
    dag = _record_dict(updated.get("dag"))
    updated["dag"] = {
        **dag,
        "steps": [
            {
                "id": "001-main",
                "tool": selected_tool_id,
                "params": inputs or {},
                "runtime_kind": _plan_step_runtime_kind(selected_tool_id),
            }
        ],
        "artifacts": dag.get("artifacts") or [],
    }
    updated["pipeline"] = _text_value(updated.get("pipeline")) or query
    updated["chosen_tool"] = selected_tool_id
    updated["candidates"] = candidate_rows
    updated["resolvable"] = True
    updated["selection_reason"] = (
        "Selected from the shared plan_preflight routing shortlist after the "
        "primary plan contract returned no executable steps."
    )
    updated["warnings"] = _without_no_suitable_tool_warnings(updated.get("warnings"))

    context = _record_dict(updated.get("context"))
    context.setdefault("pipeline", query)
    context.setdefault("query", query)
    context.setdefault("domain", domain)
    context.setdefault("modality", route_bundle.get("modality") or list(modality or []))
    context.setdefault("inputs", inputs or {})
    if route_bundle.get("facts", {}).get("query_understanding") is not None:
        context["query_understanding"] = route_bundle["facts"]["query_understanding"]
    context["tool_candidates"] = route_bundle.get("tool_candidates") or []
    context["tool_candidate_diagnostics"] = (
        route_bundle.get("routing_diagnostics") or {}
    )
    updated["context"] = context

    diagnostics = _record_dict(updated.get("routing_diagnostics"))
    preflight_diagnostics = dict(route_bundle.get("routing_diagnostics") or {})
    diagnostics.update(
        {
            "surface": "plan",
            "preflight_fallback_used": True,
            "fallback_selected_tool": selected_tool_id,
            "fallback_candidate_count": len(candidate_rows),
            "preflight_candidate_count": len(route_bundle.get("tool_candidates") or []),
            "preflight_candidate_source_counts": preflight_diagnostics.get(
                "candidate_source_counts"
            )
            or {},
            "planner_candidate_count": len(candidate_rows),
            "candidate_count": len(candidate_rows),
            "routing_terminal_reason": "preflight_fallback_promoted_to_plan",
        }
    )
    diagnostics.update(_preflight_selection_trace(route_bundle, selected_tool_id))
    updated["routing_diagnostics"] = diagnostics
    return updated


def _build_display_summary(
    plan_payload: dict[str, Any],
    *,
    query: str,
) -> tuple[dict[str, Any], str]:
    handoff = build_handoff_from_plan_payload(plan_payload)
    query_understanding = _record_dict(
        (plan_payload.get("context") or {}).get("query_understanding")
    )
    dataset_refs = _collect_dataset_refs(
        handoff,
        (plan_payload.get("context") or {}).get("inputs"),
        query_understanding,
    )
    dataset_scope = ", ".join(dataset_refs) if dataset_refs else "unspecified"

    steps_payload = _plan_steps_payload(plan_payload)
    step_tools: list[str] = []
    steps_summary: list[dict[str, Any]] = []
    reg = _get_registry()
    for idx, step in enumerate(steps_payload, start=1):
        tool_id = _text_value(step.get("tool")) or f"step-{idx}"
        if tool_id not in step_tools:
            step_tools.append(tool_id)
        spec = reg.get_toolspec_by_name(tool_id)
        step_summary = {
            "index": idx,
            "id": _text_value(step.get("id")) or f"{idx:03d}",
            "tool": tool_id,
            "runtime_kind": _text_value(step.get("runtime_kind")) or "container",
            "summary": _text_value(getattr(spec, "description", None)) or tool_id,
            "param_keys": sorted((step.get("params") or {}).keys()),
        }
        steps_summary.append(step_summary)

    approval_level = _text_value(handoff.get("approval_level")) or "none"
    approval_gates: list[str] = []
    if approval_level == "admin":
        approval_gates.append("Manual admin path required before execution.")
    elif approval_level == "confirm":
        approval_gates.append("Pause for human approval before execute-phase tools.")

    risks = list(handoff.get("warnings") or [])
    if not risks and not plan_payload.get("resolvable", True):
        risks.append("Planner did not mark this plan as fully resolvable.")

    estimated_cost = _estimate_plan_cost(step_tools)
    summary = {
        "goal": query,
        "dataset_scope": dataset_scope,
        "steps": steps_summary,
        "approval_gates": approval_gates,
        "risks": risks,
        "estimated_cost": estimated_cost,
    }

    markdown_lines = [
        "### Pipeline Plan",
        f"**Goal**: {query}",
        f"**Dataset**: {dataset_scope}",
        "",
        "**Steps**:",
    ]
    if steps_summary:
        for step in steps_summary:
            param_suffix = ""
            if step["param_keys"]:
                param_suffix = f" (params: {', '.join(step['param_keys'][:6])})"
            markdown_lines.append(
                f"{step['index']}. `{step['tool']}` - {step['summary']}{param_suffix}"
            )
    else:
        markdown_lines.append("1. No executable steps were produced.")

    markdown_lines.append("")
    markdown_lines.append(f"**Estimated Cost**: {estimated_cost}")
    if approval_gates:
        markdown_lines.append("")
        markdown_lines.append("**Approval Gates**:")
        for gate in approval_gates:
            markdown_lines.append(f"- {gate}")
    if risks:
        markdown_lines.append("")
        markdown_lines.append("**Risks**:")
        for risk in risks:
            markdown_lines.append(f"- {risk}")

    return summary, "\n".join(markdown_lines).strip()


def _build_execution_envelope(plan_payload: dict[str, Any]) -> dict[str, Any]:
    handoff = build_handoff_from_plan_payload(plan_payload)
    return {
        "schema_version": _PLAN_EXECUTION_SCHEMA_VERSION,
        "plan_id": handoff.get("plan_id"),
        "version": handoff.get("version"),
        "por_token": _text_value(plan_payload.get("por_token")),
        "handoff": handoff,
        "allowed_tools": list(handoff.get("allowed_tools") or []),
        "approval_level": _text_value(handoff.get("approval_level")) or "none",
        "run_mode_hint": _text_value(handoff.get("run_mode_hint")),
    }


def _validate_pipeline_execution_contract(
    raw_plan: dict[str, Any],
    normalized: Plan,
    *,
    dry_run: bool,
) -> list[dict[str, str]]:
    if dry_run:
        return []

    execution = _record_dict(raw_plan.get("execution"))
    if not execution:
        return [
            {
                "level": "error",
                "code": "execution_contract_required",
                "message": (
                    "pipeline_execute now requires plan.execution for non-dry-run "
                    "execution. Build a validated execution envelope with plan_create() "
                    "and attach it under plan.execution before calling pipeline_execute."
                ),
            }
        ]

    schema_version = _text_value(execution.get("schema_version"))
    if schema_version != _PLAN_EXECUTION_SCHEMA_VERSION:
        return [
            {
                "level": "error",
                "code": "execution_contract_invalid",
                "message": (
                    "plan.execution.schema_version must be "
                    f"'{_PLAN_EXECUTION_SCHEMA_VERSION}' for non-dry-run execution."
                ),
            }
        ]

    allowed_tools = _coerce_non_empty_str_list(execution.get("allowed_tools"))
    if allowed_tools:
        unexpected_tools = [
            step.tool for step in normalized.steps if step.tool not in allowed_tools
        ]
        if unexpected_tools:
            unexpected = ", ".join(sorted(set(unexpected_tools)))
            return [
                {
                    "level": "error",
                    "code": "execution_contract_tool_mismatch",
                    "message": (
                        "plan.steps contains tool_ids not present in "
                        f"plan.execution.allowed_tools: {unexpected}"
                    ),
                }
            ]

    return []


def _validate_pipeline_execution_gate(
    raw_plan: dict[str, Any],
    *,
    dry_run: bool,
    approval_phrase: str | None,
) -> list[dict[str, str]]:
    if dry_run:
        return []

    execution = _record_dict(raw_plan.get("execution"))
    if not execution:
        return []

    approval_level = _text_value(execution.get("approval_level")) or "none"
    run_mode_hint = _text_value(execution.get("run_mode_hint")) or ""
    normalized_phrase = _text_value(approval_phrase)

    if run_mode_hint == "recipe_required":
        return [
            {
                "level": "error",
                "code": "execution_recipe_required",
                "message": (
                    "plan.execution.run_mode_hint=recipe_required cannot be executed "
                    "directly via pipeline_execute. Use get_execution_recipe or the "
                    "runtime-specific CLI/Slurm path instead."
                ),
            }
        ]

    if run_mode_hint == "manual_review":
        return [
            {
                "level": "error",
                "code": "execution_manual_review_required",
                "message": (
                    "plan.execution.run_mode_hint=manual_review requires a human review "
                    "step before any execute-phase call. Do not use pipeline_execute "
                    "directly for this plan."
                ),
            }
        ]

    if run_mode_hint == "admin_only" or approval_level == "admin":
        if normalized_phrase != PIPELINE_EXECUTE_ADMIN_PHRASE:
            return [
                {
                    "level": "error",
                    "code": "execution_admin_approval_required",
                    "message": (
                        "This execution envelope is admin-only. Re-run pipeline_execute "
                        f"with approval_phrase={PIPELINE_EXECUTE_ADMIN_PHRASE!r} if you "
                        "intend to perform the admin-path execution."
                    ),
                }
            ]
        return []

    if run_mode_hint == "confirm_before_execute" or approval_level == "confirm":
        if normalized_phrase not in {
            PIPELINE_EXECUTE_CONFIRM_PHRASE,
            PIPELINE_EXECUTE_ADMIN_PHRASE,
        }:
            return [
                {
                    "level": "error",
                    "code": "execution_confirmation_required",
                    "message": (
                        "This execution envelope requires explicit confirmation. Re-run "
                        f"pipeline_execute with approval_phrase={PIPELINE_EXECUTE_CONFIRM_PHRASE!r} "
                        "after review."
                    ),
                }
            ]

    return []


# ---------------------------------------------------------------------------
# Planning tools (plan_preflight / plan_create / get_latest_plan) extracted to
# mcp/routers/plan.py. Importing it registers those tools (import side effect).
# The planning helpers they call stay here and are imported back by the router.
# ---------------------------------------------------------------------------
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    plan as _plan_router,
)


@mcp.tool()
def tool_execute(
    tool_id: str,
    params: dict[str, Any] | None = None,
    work_dir: str | None = None,
    output_dir: str | None = None,
    preview: bool = False,
    allow_remap: bool = False,
    allow_fallback: bool = False,
) -> dict[str, Any]:
    """[DEPRECATED for Agents] Execute a single tool (manual/admin path only)."""
    preview_requested = bool(preview)
    remap_requested = bool(allow_remap) and not preview_requested
    fallback_requested = bool(allow_fallback) and not preview_requested

    def _response_with_execution(
        *,
        ok: bool,
        execution_trace: list[str],
        resolved_tool_id: str | None = tool_id,
        remap_applied: bool = False,
        execution_mode: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        response = {
            "ok": ok,
            "requested_tool_id": tool_id,
            "resolved_tool_id": resolved_tool_id,
            "remap_applied": bool(remap_applied),
            "allow_remap": remap_requested,
            "allow_fallback": fallback_requested,
            "execution_trace": list(execution_trace),
        }
        if execution_mode is not None:
            response["execution_mode"] = execution_mode
        response.update(extra)
        return response

    if _is_retired_public_tool_name(tool_id):
        return _response_with_execution(
            ok=False,
            execution_trace=["retired_tool_blocked"],
            resolved_tool_id=None,
            error="tool_removed",
            message=f"{tool_id} is no longer exposed by the Brain Researcher MCP server.",
        )

    if is_workflow_tool_id(tool_id) and _is_declared_workflow_id(tool_id):
        resp = _response_with_execution(
            ok=False,
            execution_trace=["workflow_blocked"],
            resolved_tool_id=None,
            error="workflow_requires_pipeline_execute",
            message=(
                f"'{tool_id}' is a workflow. Use pipeline_plan_validate + pipeline_execute "
                "instead of tool_execute."
            ),
        )
        resp.update(
            _recipe_hint_payload(
                tool_id,
                params if isinstance(params, dict) else None,
                workflow_entry=_workflow_catalog_entry(tool_id),
            )
        )
        return resp
    if not ENABLE_TOOL_EXECUTE:
        issues = [
            {
                "level": "error",
                "code": "tool_execute_disabled",
                "message": "Set BR_MCP_ENABLE_TOOL_EXECUTE=1 to enable tool_execute.",
            }
        ]
        resp = _response_with_execution(
            ok=False,
            execution_trace=["tool_execute_disabled"],
            resolved_tool_id=None,
            error="tool_execute_disabled",
            message="Set BR_MCP_ENABLE_TOOL_EXECUTE=1 to enable tool_execute.",
            issues=issues,
            policy_issues=issues,
        )
        resp.update(
            _recipe_hint_payload(
                tool_id,
                params if isinstance(params, dict) else None,
            )
        )
        return resp
    if not _tool_allowed_by_allowlist(tool_id, TOOL_EXECUTE_ALLOWLIST):
        issues = [
            {
                "level": "error",
                "code": "tool_not_allowlisted",
                "message": (
                    "tool_execute is allowlisted; set BR_MCP_TOOL_EXECUTE_ALLOWLIST='*' "
                    "or a comma-separated list of tool IDs/prefixes."
                ),
            }
        ]
        resp = _response_with_execution(
            ok=False,
            execution_trace=["allowlist_blocked"],
            resolved_tool_id=None,
            error="tool_not_allowlisted",
            message=(
                "tool_execute is allowlisted; set BR_MCP_TOOL_EXECUTE_ALLOWLIST='*' "
                "or a comma-separated list of tool IDs/prefixes."
            ),
            issues=issues,
            policy_issues=issues,
        )
        resp.update(
            _recipe_hint_payload(
                tool_id,
                params if isinstance(params, dict) else None,
            )
        )
        return resp
    params = params or {}
    if not isinstance(params, dict):
        return _response_with_execution(
            ok=False,
            execution_trace=["params_invalid"],
            resolved_tool_id=None,
            error="params must be an object",
        )

    run_id = _new_run_id()
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    log_trace = None
    try:
        from brain_researcher.services.agent.run_bundle import (
            log_trace_event as _log_trace_event,
        )

        log_trace = _log_trace_event
    except Exception:
        log_trace = None

    provenance = {
        "run_id": run_id,
        "mode": "mcp",
        "route": "tool_execute",
        "transport": DEFAULT_TRANSPORT,
        "guardrails": _mcp_guardrails_snapshot(),
        "request": {
            "tool_id": tool_id,
            "params": params,
            "preview": preview_requested,
            "allow_remap": remap_requested,
            "allow_fallback": fallback_requested,
            "work_dir": work_dir,
            "output_dir": output_dir,
        },
    }
    _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))

    record = RunRecord(
        run_id=run_id,
        created_at=_utc_iso(),
        status="queued",
        dry_run=preview_requested,
        progress={
            "current_stage": "queued",
            "message": f"Queued {tool_id} for execution",
            "last_progress_at": _utc_iso(),
        },
        timing_policy=_default_run_timing_policy(),
        steps=[
            StepRecord(
                step_id="s1",
                tool_id=tool_id,
                params=params,
                status="queued",
                work_dir=None,
                output_dir=None,
                progress={
                    "current_stage": "queued",
                    "message": f"Queued {tool_id} for execution",
                    "last_progress_at": _utc_iso(),
                },
            )
        ],
    )
    _save_run(record)

    _emit_trace_event(
        log_trace,
        run_dir,
        run_id=run_id,
        event_type="mcp.tool_execute.queued",
        payload={"tool_id": tool_id},
    )

    original_params = _clone_jsonable(params) if isinstance(params, dict) else None
    spec, issues = _call_preflight_tool_call(
        tool_id,
        params,
        allowlist=TOOL_EXECUTE_ALLOWLIST,
        step_id="s1",
        allow_remap=remap_requested,
    )
    critic_feedback = _critic_feedback_from_issues(
        issues,
        original_params=original_params,
        current_params=params,
    )
    resolved_tool_id = spec.name if spec is not None else tool_id
    remap_applied = resolved_tool_id != tool_id
    preflight_policy_issues = _extract_policy_issues_from_issue_list(
        issues, step_id="s1"
    )
    blocking = [i for i in issues if i.get("level") == "error"]
    if blocking:
        codes = {str(i.get("code") or "") for i in blocking}
        if "unknown_tool" in codes:
            err = "unknown_tool"
        elif TOOL_REGISTRY_MISCONFIGURED in codes:
            err = TOOL_REGISTRY_MISCONFIGURED
        elif codes & {"params_invalid", "params_missing_required"}:
            err = "params_invalid"
        else:
            err = "policy_rejected"

        lock = _get_run_lock(run_id)
        with lock:
            record = _load_run(run_id)
            record.status = "failed"
            record.error = err
            record.finished_at = _utc_iso()
            record.steps[0].status = "failed"
            record.steps[0].error = err
            record.steps[0].policy_issues = preflight_policy_issues
            _save_run(record)

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.preflight_rejected",
            payload={"tool_id": tool_id, "error": err, "issues": issues},
        )

        _persist_mcp_run_bundle(run_id, preflight_issues=issues)
        resp = _response_with_execution(
            ok=False,
            execution_trace=["preflight_failed"],
            resolved_tool_id=resolved_tool_id if spec is not None else None,
            remap_applied=remap_applied,
            error=err,
            issues=issues,
            run_id=run_id,
            run_dir=str(run_dir),
        )
        if preflight_policy_issues:
            resp["policy_issues"] = preflight_policy_issues
        if critic_feedback:
            resp.update(critic_feedback)
        if err not in {"unknown_tool", TOOL_REGISTRY_MISCONFIGURED, "params_invalid"}:
            resp.update(
                _recipe_hint_payload(
                    resolved_tool_id,
                    params,
                    spec=spec,
                    workflow_entry=(
                        _workflow_catalog_entry(resolved_tool_id)
                        if is_workflow_tool_id(resolved_tool_id)
                        else None
                    ),
                )
            )
        return resp

    resolved_workflow_entry = (
        _workflow_catalog_entry(resolved_tool_id)
        if is_workflow_tool_id(resolved_tool_id)
        else None
    )
    recipe_meta = resolve_recipe_metadata(
        resolved_tool_id,
        spec=spec,
        workflow_entry=resolved_workflow_entry,
    )
    # Keep local MCP bridge tools usable through tool_execute even though their
    # discovery cards are exposed as hosted/control-plane tools.
    if recipe_meta.get("hosted_via_br_mcp_service") and (
        resolved_tool_id not in _LOCAL_MCP_BRIDGE_TOOLS
    ):
        hosted_issue = {
            "level": "error",
            "code": "hosted_tool_local_execution_disabled",
            "message": (
                f"'{resolved_tool_id}' is hosted by default. Use the deployed "
                "Brain Researcher MCP service directly instead of tool_execute."
            ),
            "step_id": "s1",
        }
        issues = [*issues, hosted_issue]

        lock = _get_run_lock(run_id)
        with lock:
            record = _load_run(run_id)
            record.status = "failed"
            record.error = "hosted_execution_required"
            record.finished_at = _utc_iso()
            record.steps[0].status = "failed"
            record.steps[0].error = "hosted_execution_required"
            record.steps[0].policy_issues = []
            _save_run(record)

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.hosted_rejected",
            payload={
                "tool_id": tool_id,
                "resolved_tool_id": resolved_tool_id,
                "issues": issues,
            },
        )

        _persist_mcp_run_bundle(run_id, preflight_issues=issues)
        resp = _response_with_execution(
            ok=False,
            execution_trace=["preflight_passed", "hosted_execution_required"],
            resolved_tool_id=resolved_tool_id,
            remap_applied=remap_applied,
            error="hosted_execution_required",
            message=(
                f"'{resolved_tool_id}' is hosted by default. Call it through the "
                "deployed Brain Researcher MCP service instead of tool_execute."
            ),
            issues=issues,
            run_id=run_id,
            run_dir=str(run_dir),
        )
        resp["execution_story_kind"] = recipe_meta.get("execution_story_kind")
        resp["execution_story"] = recipe_meta.get("execution_story")
        resp.update(
            _recipe_hint_payload(
                resolved_tool_id,
                params,
                spec=spec,
                workflow_entry=resolved_workflow_entry,
            )
        )
        if critic_feedback:
            resp.update(critic_feedback)
        return resp

    if recipe_meta.get("execution_story_kind") == "binary_backed_atomic":
        runtime_issue = {
            "level": "error",
            "code": "binary_execution_recipe_required",
            "message": (
                f"'{resolved_tool_id}' requires runtime-specific binaries. "
                "Use get_execution_recipe and run it via Neurodesk, container, or Slurm "
                "instead of tool_execute."
            ),
            "step_id": "s1",
        }
        issues = [*issues, runtime_issue]

        lock = _get_run_lock(run_id)
        with lock:
            record = _load_run(run_id)
            record.status = "failed"
            record.error = "binary_execution_recipe_required"
            record.finished_at = _utc_iso()
            record.steps[0].status = "failed"
            record.steps[0].error = "binary_execution_recipe_required"
            record.steps[0].policy_issues = []
            _save_run(record)

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.binary_runtime_rejected",
            payload={
                "tool_id": tool_id,
                "resolved_tool_id": resolved_tool_id,
                "issues": issues,
            },
        )

        _persist_mcp_run_bundle(run_id, preflight_issues=issues)
        resp = _response_with_execution(
            ok=False,
            execution_trace=["preflight_passed", "binary_execution_recipe_required"],
            resolved_tool_id=resolved_tool_id,
            remap_applied=remap_applied,
            error="binary_execution_recipe_required",
            message=(
                f"'{resolved_tool_id}' requires runtime-specific binaries. "
                "Call get_execution_recipe and execute the generated Neurodesk, "
                "container, or Slurm recipe instead of tool_execute."
            ),
            issues=issues,
            run_id=run_id,
            run_dir=str(run_dir),
        )
        resp["execution_story_kind"] = recipe_meta.get("execution_story_kind")
        resp["execution_story"] = recipe_meta.get("execution_story")
        resp.update(
            _recipe_hint_payload(
                resolved_tool_id,
                params,
                spec=spec,
                workflow_entry=resolved_workflow_entry,
            )
        )
        if critic_feedback:
            resp.update(critic_feedback)
        return resp

    if AGENT_DELEGATED_EXECUTION_ENABLED and not preview_requested:
        delegated_work_dir = None
        delegated_output_dir = None
        try:
            if work_dir:
                delegated_work_dir = str(
                    _require_allowed_path(Path(work_dir), kind="work_dir")
                )
            if output_dir:
                delegated_output_dir = str(
                    _require_allowed_path(Path(output_dir), kind="output_dir")
                )
        except ValueError as exc:
            path_issue = {
                "level": "error",
                "code": "path_not_allowed",
                "message": str(exc),
                "step_id": "s1",
            }
            issues = [*issues, path_issue]
            policy_issues = _extract_policy_issues_from_issue_list(issues, step_id="s1")
            lock = _get_run_lock(run_id)
            with lock:
                record = _load_run(run_id)
                record.status = "failed"
                record.error = str(exc)
                record.finished_at = _utc_iso()
                record.steps[0].status = "failed"
                record.steps[0].error = str(exc)
                record.steps[0].policy_issues = policy_issues
                _save_run(record)
            _persist_mcp_run_bundle(run_id, preflight_issues=issues)
            resp = _response_with_execution(
                ok=False,
                execution_trace=["preflight_passed", "path_rejected"],
                resolved_tool_id=resolved_tool_id,
                remap_applied=remap_applied,
                error=str(exc),
                issues=issues,
                run_id=run_id,
                run_dir=str(run_dir),
            )
            if policy_issues:
                resp["policy_issues"] = policy_issues
            if critic_feedback:
                resp.update(critic_feedback)
            return resp

        provenance["delegated_execution"] = {
            "backend": "agent",
            "endpoint": _agent_delegation_endpoint(),
            "execution_type": "tool",
            "delegated_at": _utc_iso(),
        }
        provenance["request"]["work_dir"] = delegated_work_dir
        provenance["request"]["output_dir"] = delegated_output_dir
        _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))
        delegated = _delegate_execution_to_agent(
            run_id=run_id,
            execution_type="tool",
            tool_id=resolved_tool_id,
            params=params,
            work_dir=delegated_work_dir,
            output_dir=delegated_output_dir,
        )
        if delegated.get("ok") is not True:
            delegated_error = str(delegated.get("error") or "agent_delegation_failed")
            lock = _get_run_lock(run_id)
            with lock:
                record = _load_run(run_id)
                record.status = "failed"
                record.error = delegated_error
                record.finished_at = _utc_iso()
                record.steps[0].status = "failed"
                record.steps[0].error = delegated_error
                _save_run(record)
            _emit_trace_event(
                log_trace,
                run_dir,
                run_id=run_id,
                event_type="mcp.tool_execute.delegation_failed",
                payload={"tool_id": resolved_tool_id, "error": delegated_error},
            )
            _persist_mcp_run_bundle(run_id, preflight_issues=issues)
            resp = _response_with_execution(
                ok=False,
                execution_trace=[
                    "preflight_passed",
                    "delegated_to_agent",
                    "delegation_failed",
                ],
                resolved_tool_id=resolved_tool_id,
                remap_applied=remap_applied,
                execution_mode="agent_delegated",
                error=delegated_error,
                run_id=run_id,
                run_dir=str(run_dir),
            )
            resp["delegated_execution"] = {
                "backend": "agent",
                "endpoint": delegated.get("endpoint") or _agent_delegation_endpoint(),
            }
            if critic_feedback:
                resp.update(critic_feedback)
            return resp

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.delegated",
            payload={
                "tool_id": resolved_tool_id,
                "endpoint": _agent_delegation_endpoint(),
            },
        )
        resp = _response_with_execution(
            ok=True,
            execution_trace=["preflight_passed", "delegated_to_agent", "queued"],
            resolved_tool_id=resolved_tool_id,
            remap_applied=remap_applied,
            execution_mode="agent_delegated",
            run_id=str(delegated.get("run_id") or run_id),
            run_dir=delegated.get("run_dir"),
            status=str(delegated.get("status") or "queued"),
        )
        resp["delegated_execution"] = {
            "backend": "agent",
            "endpoint": _agent_delegation_endpoint(),
        }
        if issues:
            resp["issues"] = issues
        if critic_feedback:
            resp.update(critic_feedback)
        return resp

    preview_degradation_issue: dict[str, Any] | None = None
    if preview_requested and spec is not None and str(spec.backend).lower() == "python":
        preview_degradation_issue = {
            "level": "warning",
            "code": "preview_not_supported_for_backend",
            "message": (
                "preview=true for backend 'python' is synthetic and non-executing; "
                "execution is skipped."
            ),
            "step_id": "s1",
        }
        issues = [*issues, preview_degradation_issue]
        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.preview_degraded",
            payload={"tool_id": tool_id, "issues": issues},
        )

    # Default directories go under the run root for consistent artifact collection.
    work_dir = work_dir or str(run_dir / "work" / "step-01-s1")
    output_dir = output_dir or str(run_dir / "artifacts" / "step-01-s1")
    try:
        wd = _require_allowed_path(Path(work_dir), kind="work_dir")
        od = _require_allowed_path(Path(output_dir), kind="output_dir")
        wd.mkdir(parents=True, exist_ok=True)
        od.mkdir(parents=True, exist_ok=True)
    except ValueError as exc:
        path_issue = {
            "level": "error",
            "code": "path_not_allowed",
            "message": str(exc),
            "step_id": "s1",
        }
        issues = [*issues, path_issue]
        path_policy_issues = _extract_policy_issues_from_issue_list(
            issues, step_id="s1"
        )
        lock = _get_run_lock(run_id)
        with lock:
            record = _load_run(run_id)
            record.status = "failed"
            record.error = str(exc)
            record.finished_at = _utc_iso()
            record.steps[0].status = "failed"
            record.steps[0].error = str(exc)
            record.steps[0].policy_issues = path_policy_issues
            _save_run(record)

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.path_rejected",
            payload={"tool_id": tool_id, "error": str(exc)},
        )

        _persist_mcp_run_bundle(run_id, preflight_issues=issues)
        resp = _response_with_execution(
            ok=False,
            execution_trace=["preflight_passed", "path_rejected"],
            resolved_tool_id=resolved_tool_id,
            remap_applied=remap_applied,
            error=str(exc),
            issues=issues,
            run_id=run_id,
            run_dir=str(run_dir),
        )
        if path_policy_issues:
            resp["policy_issues"] = path_policy_issues
        if critic_feedback:
            resp.update(critic_feedback)
        resp.update(
            _recipe_hint_payload(
                resolved_tool_id,
                params,
                spec=spec,
                workflow_entry=resolved_workflow_entry,
            )
        )
        return resp

    provenance["request"]["work_dir"] = str(wd)
    provenance["request"]["output_dir"] = str(od)
    _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))

    lock = _get_run_lock(run_id)
    with lock:
        record = _load_run(run_id)
        record.status = "running"
        record.started_at = _utc_iso()
        step = record.steps[0]
        step.status = "running"
        step.started_at = _utc_iso()
        step.work_dir = str(wd)
        step.output_dir = str(od)
        _update_run_progress(
            record,
            stage="tool_execute",
            message=f"Executing {resolved_tool_id}",
            progress_pct=0.0,
            step_index=0,
        )
        _save_run(record)

    _emit_trace_event(
        log_trace,
        run_dir,
        run_id=run_id,
        event_type="mcp.tool_execute.started",
        payload={
            "tool_id": tool_id,
            "work_dir": str(wd),
            "output_dir": str(od),
        },
    )

    if preview_degradation_issue is not None:
        warning_message = str(preview_degradation_issue.get("message") or "")
        result_obj = ToolResult(
            status="success",
            data={
                "preview": True,
                "synthetic_preview": True,
                "executed": False,
                "message": warning_message,
            },
            metadata=_metadata_with_execution_trace(
                {
                    "tool_id": tool_id,
                    "backend": "python",
                    "mode": "preview",
                    "preview_mode": "synthetic_non_executing",
                    "execution_skipped": True,
                    "warning_code": "preview_not_supported_for_backend",
                    "warnings": [warning_message],
                },
                "preview_only",
                execution_mode="preview_only",
            ),
        )
    else:
        result_obj = _execute_tool_with_timeout(
            tool_id=tool_id,
            params=params,
            work_dir=str(wd),
            output_dir=str(od),
            preview=preview_requested,
            spec=spec,
            allow_remap=remap_requested,
            allow_fallback=fallback_requested,
        )
    result = result_obj.model_dump()
    result_policy_issues = _extract_policy_issues_from_result(result, step_id="s1")
    policy_issues = _extract_policy_issues_from_issue_list(issues, step_id="s1")
    if result_policy_issues:
        policy_issues = _extract_policy_issues_from_issue_list(
            [*policy_issues, *result_policy_issues], step_id="s1"
        )

    result_path, stdout_path, stderr_path = _write_step_logs(
        run_dir, idx=1, step_id="s1", result=result
    )

    with lock:
        record = _load_run(run_id)
        step = record.steps[0]
        step.finished_at = _utc_iso()
        step.result_path = result_path
        step.stdout_path = stdout_path
        step.stderr_path = stderr_path
        step.policy_issues = policy_issues
        if result.get("status") == "success":
            step.status = "succeeded"
            record.status = "succeeded"
            record.finished_at = _utc_iso()
            _update_run_progress(
                record,
                stage="completed",
                message=f"Finished {resolved_tool_id}",
                progress_pct=100.0,
                step_index=0,
            )
        else:
            formatted_error = _format_execution_error(result)
            step.status = "failed"
            step.error = formatted_error
            record.status = "failed"
            record.error = formatted_error
            record.finished_at = _utc_iso()
            _update_run_progress(
                record,
                stage="failed",
                message=formatted_error,
                step_index=0,
            )
        _save_run(record)

    timeout_outcome = None
    metadata = result.get("metadata")
    fallback_mode = None
    fallback_reason = None
    forward_target = None
    if isinstance(metadata, dict):
        timeout_outcome = metadata.get("timeout_outcome")
        fallback_mode = metadata.get("execution_mode")
        fallback_reason = metadata.get("fallback_reason")
        forward_target = metadata.get("forward_target")
    if fallback_mode in {"agent_fallback", "agent_fallback_failed"}:
        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.tool_execute.fallback_attempted",
            payload={
                "tool_id": tool_id,
                "fallback_reason": fallback_reason,
                "forward_target": forward_target,
            },
        )
        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type=(
                "mcp.tool_execute.fallback_succeeded"
                if fallback_mode == "agent_fallback"
                else "mcp.tool_execute.fallback_failed"
            ),
            payload={
                "tool_id": tool_id,
                "fallback_reason": fallback_reason,
                "forward_target": forward_target,
                "status": record.status,
            },
        )
    _emit_trace_event(
        log_trace,
        run_dir,
        run_id=run_id,
        event_type="mcp.tool_execute.finished",
        payload={
            "tool_id": tool_id,
            "status": record.status,
            "error": record.error,
            "result_path": result_path,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "timeout_outcome": timeout_outcome,
            "policy_issues": policy_issues,
        },
    )

    _persist_mcp_run_bundle(run_id, preflight_issues=issues)
    execution_metadata = metadata if isinstance(metadata, dict) else {}
    execution_trace = _normalize_execution_trace(
        execution_metadata.get("execution_trace")
    )
    if preview_requested:
        execution_trace = ["preflight_passed", *execution_trace]
    elif not execution_trace or execution_trace[0] != "preflight_passed":
        execution_trace = ["preflight_passed", *execution_trace]
    execution_mode = str(
        execution_metadata.get("execution_mode")
        or ("preview_only" if preview_requested else "direct")
    )
    resp = _response_with_execution(
        ok=record.status == "succeeded",
        execution_trace=execution_trace,
        resolved_tool_id=(
            str(execution_metadata.get("resolved_tool_id") or resolved_tool_id)
            if (execution_metadata.get("resolved_tool_id") or resolved_tool_id)
            else None
        ),
        remap_applied=bool(execution_metadata.get("remap_applied", remap_applied)),
        execution_mode=execution_mode,
        run_id=run_id,
        run_dir=str(run_dir),
        result=result,
        work_dir=str(wd),
        output_dir=str(od),
    )
    execution_pack = execution_metadata.get("execution_pack")
    if isinstance(execution_pack, dict) and execution_pack:
        resp["execution_pack"] = _clone_jsonable(execution_pack)
    combined_issues = list(issues or [])
    if policy_issues:
        combined_issues = [
            *combined_issues,
            *[
                item
                for item in policy_issues
                if not any(item == existing for existing in combined_issues)
            ],
        ]
        resp["policy_issues"] = policy_issues
    if combined_issues:
        resp["issues"] = combined_issues
    if critic_feedback:
        resp.update(critic_feedback)
    if record.status != "succeeded":
        resp["error"] = record.error or "tool_failed"
        resp.update(
            _recipe_hint_payload(
                resolved_tool_id,
                params,
                spec=spec,
                workflow_entry=resolved_workflow_entry,
            )
        )
    if preview_degradation_issue is not None:
        resp["warnings"] = [str(preview_degradation_issue.get("message") or "")]
    return resp


# ---------------------------------------------------------------------------
# Pipeline plan validation/review tools (pipeline_plan_validate /
# pipeline_plan_review) extracted to mcp/routers/pipeline.py. Importing it
# registers those tools (import side effect). pipeline_execute stays here
# (run-orchestration; moves with the run-store substrate). Helpers stay here
# and are imported back by the router.
# ---------------------------------------------------------------------------
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    pipeline as _pipeline_router,
)


@mcp.tool()
def qsm_implementation_review(
    code: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Audit generated QSM code for direct-inversion and local-field dataflow hazards.

    This tool is intentionally non-displacive: it returns hard constraints,
    findings, and QC checks, not a replacement QSM reconstruction recipe.
    """
    if not _text_value(code):
        return {"ok": False, "error": "code_required"}
    try:
        verdict = review_qsm_implementation_payload(code, filename=filename)
        payload = verdict.model_dump()
        payload["domain_invariant_review"] = {
            "task_type": "qsm_reconstruction",
            "advice_mode": "audit_only",
            "hard_constraints": _QSM_HARD_CONSTRAINTS,
            "non_displacement_notice": _QSM_NON_DISPLACEMENT_NOTICE,
            "qc_protocol": _QSM_QC_PROTOCOL,
            "forbidden_guidance": _QSM_FORBIDDEN_GUIDANCE,
        }
        return {"ok": True, **payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def rapidtide_implementation_review(
    task_profile: str,
    method_contract: dict[str, Any],
    subject_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit a rapidtide sLFO time-lag analysis against the canonical method.

    Checks a declared ``method_contract`` (and optional numeric
    ``subject_summaries``) for methodological errors that make the output
    invalid even when it looks plausible: a static zero-lag regression instead
    of a cross-correlation lag search, a lag-search window that clips real
    delays, missing probe-regressor refinement, or a filter band outside the
    sLFO range. Non-displacive: returns canonical-method findings, not a
    replacement reconstruction recipe.
    """
    if not _text_value(task_profile):
        return {"ok": False, "error": "task_profile_required"}
    if not isinstance(method_contract, dict):
        return {"ok": False, "error": "method_contract_must_be_object"}
    try:
        verdict = review_rapidtide_implementation(
            task_profile=task_profile,
            method_contract=method_contract,
            subject_summaries=subject_summaries,
        )
        return {"ok": True, **verdict.model_dump()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def report_claim_provenance_check(
    run_id: str,
    claims: list[dict[str, Any]],
    require_claim_provenance: bool = False,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Check report claims are traceable to artifacts/code that actually ran.

    Report-code traceability: builds a provenance index from the run (file
    manifest path+checksum and plan steps) and validates each claim's
    ``artifact_path`` / ``artifact_sha256`` / ``code_ref`` against it. A claim
    fails when it lacks provenance, cites an artifact the run never produced,
    has a checksum that does not match, or names a code ref absent from the
    plan. Returns the unsupported claim ids, a report-ready 'Claims missing
    provenance' section, and (when blocking) a synthetic critical/block
    correctness finding callers can fold into a report verdict. Unsupported
    claims block under ``require_claim_provenance`` or a confirmatory claim mode;
    exploratory runs surface them as a caveat only. This guards against a report
    describing the intended analysis rather than the one that actually ran.
    """
    if not _text_value(run_id):
        return {"ok": False, "error": "run_id_required"}
    if not isinstance(claims, list) or not claims:
        return {"ok": False, "error": "claims_required"}
    try:
        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )
        from brain_researcher.services.review.claim_provenance import (
            build_claim_provenance_gate,
            build_run_provenance_index,
        )

        bundle = build_artifact_review_bundle(run_id, workflow_id=workflow_id)
        index = build_run_provenance_index(bundle)
        try:
            claim_mode = _claim_mode_from_run_dir(_find_run_dir(run_id))
        except Exception:
            claim_mode = "confirmatory"
        gate = build_claim_provenance_gate(
            claims,
            index,
            claim_mode=claim_mode,
            require_claim_provenance=require_claim_provenance,
        )
        if gate is None:
            return {
                "ok": True,
                "checked": 0,
                "unsupported_ids": [],
                "blocked": False,
                "claim_mode": claim_mode,
            }
        return {"ok": True, **gate}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def run_code_review(
    run_id: str,
    workflow_id: str | None = None,
    force_recompute: bool = False,
    use_kg: bool = False,
) -> dict[str, Any]:
    """Post-execution domain review of a completed run.

    Checks execution artifacts against neuroimaging domain rules:
    mean framewise displacement, scrubbing rate, GLM model fit (R²),
    effect size sanity, QC flag rates, artifact completeness, and step success rate.

    Results are cached in code_review_verdict.json inside the run directory.
    Use force_recompute=True to re-evaluate.

    Returns a CodeReviewVerdict with decision, risk_level, and per-finding details.
    """
    try:
        from brain_researcher.services.review.distill_review import (
            distill_review_records,
        )

        mem = distill_review_records(
            run_id,
            workflow_id=workflow_id,
            force_recompute=force_recompute,
        )
        if mem.verdict is None:
            return {
                "ok": False,
                "run_id": run_id,
                "error": "; ".join(mem.warnings)
                or "could not build artifact review bundle",
            }
        verdict_dict = mem.verdict.model_dump()
        result = {"ok": True, "run_id": run_id, **verdict_dict}
        handoff = _build_review_handoff_directive(
            verdict_dict, review_type="code_review"
        )
        if handoff is not None:
            result["_agent_directive"] = {"review_handoff": handoff}
        return result
    except Exception as exc:
        return {"ok": False, "run_id": run_id, "error": str(exc)}


@mcp.tool()
def run_scientific_review(
    run_id: str,
    workflow_id: str | None = None,
    use_judgment_critic: bool = True,
    force_recompute: bool = False,
) -> dict[str, Any]:
    """Three-verdict scientific review: correctness + completeness + judgment.

    Phase 3a (deterministic, no LLM): correctness checks (design matrix rank,
    cross-file consistency, contrast dimensions) + completeness checklist
    (seed pinned, atlas versioned, ordering declared).

    Phase 3b (use_judgment_critic=True): adds LLM-based scientific judgment
    (estimand completeness, method defensibility, reviewer questions).

    Returns a ScientificReviewVerdict with overall_decision:
    proceed | diagnose | explore_more | stop_with_rationale
    """
    try:
        from brain_researcher.services.review.distill_review import (
            distill_scientific_review_records,
        )

        verdict = distill_scientific_review_records(
            run_id,
            workflow_id=workflow_id,
            use_judgment_critic=use_judgment_critic,
            force_recompute=force_recompute,
        )
        verdict_dict = verdict.model_dump()
        result = {"ok": True, **verdict_dict}
        handoff = _build_review_handoff_directive(
            verdict_dict, review_type="scientific_review"
        )
        if handoff is not None:
            result["_agent_directive"] = {"review_handoff": handoff}
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def run_autoresearch_scientific_review(
    autoresearch_dir: str,
    logs_dir: str | None = None,
    task_id: str = "liu_component_v1",
    use_judgment_critic: bool = True,
    force_recompute: bool = False,
) -> dict[str, Any]:
    """Scientific review for autoresearch loop artifacts.

    Reviews an autoresearch workspace containing `experiments.jsonl`,
    `predict.py`, and `outputs/final_report.md`, using an autoresearch-specific
    bundle adapter plus an optional LLM judgment critic.

    Returns a ScientificReviewVerdict with extra autoresearch fields such as
    `claim_strength`, `report_action`, `required_next_actions`,
    `validation_status`, and `line_directive`.
    """
    try:
        from brain_researcher.services.review.autoresearch_scientific_review import (
            distill_autoresearch_scientific_review,
        )

        verdict = distill_autoresearch_scientific_review(
            autoresearch_dir,
            logs_dir=logs_dir,
            task_id=task_id,
            use_judgment_critic=use_judgment_critic,
            force_recompute=force_recompute,
        )
        verdict_dict = verdict.model_dump()
        result = {
            "ok": True,
            "autoresearch_dir": autoresearch_dir,
            "logs_dir": logs_dir,
            "task_id": task_id,
            **verdict_dict,
        }
        handoff = _build_review_handoff_directive(
            verdict_dict, review_type="scientific_review"
        )
        if handoff is not None:
            result["_agent_directive"] = {"review_handoff": handoff}
        return result
    except Exception as exc:
        return {
            "ok": False,
            "autoresearch_dir": autoresearch_dir,
            "logs_dir": logs_dir,
            "task_id": task_id,
            "error": str(exc),
        }


@mcp.tool()
def request_scientific_review(
    goal: str | None = None,
    run_id: str | None = None,
    autoresearch_dir: str | None = None,
    hints: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    logs_dir: str | None = None,
    task_id: str = "liu_component_v1",
    use_judgment_critic: bool = True,
    force_recompute: bool = False,
    session_id: str | None = None,
    source_client: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Route scientific review requests to the correct existing review surface.

    ``run_id`` executes the normal BR run review, ``autoresearch_dir`` executes
    the autoresearch review, and requests without either source return the
    external-agent directive plus KG-selected criteria. The router does not add a
    new verdict schema or protocol.
    """

    normalized_run_id = _first_text_value(run_id)
    normalized_autoresearch_dir = _first_text_value(autoresearch_dir)
    if normalized_run_id and normalized_autoresearch_dir:
        return {
            "ok": False,
            "error": "ambiguous_review_source",
            "message": "Provide exactly one of run_id or autoresearch_dir, not both.",
        }

    if normalized_run_id:
        response = run_scientific_review(
            normalized_run_id,
            workflow_id=workflow_id,
            use_judgment_critic=use_judgment_critic,
            force_recompute=force_recompute,
        )
        return _attach_review_route(
            response,
            selected="run_scientific_review",
            source_kind="run_id",
            source_value=normalized_run_id,
            target_tool="run_scientific_review",
        )

    if normalized_autoresearch_dir:
        response = run_autoresearch_scientific_review(
            normalized_autoresearch_dir,
            logs_dir=logs_dir,
            task_id=task_id,
            use_judgment_critic=use_judgment_critic,
            force_recompute=force_recompute,
        )
        return _attach_review_route(
            response,
            selected="run_autoresearch_scientific_review",
            source_kind="autoresearch_dir",
            source_value=normalized_autoresearch_dir,
            target_tool="run_autoresearch_scientific_review",
        )

    goal_text = _first_text_value(goal)
    if not goal_text:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": "goal is required when no run_id or autoresearch_dir is supplied",
        }
    response = request_external_scientific_review_directive(
        goal=goal_text,
        hints=hints,
        session_id=session_id,
        source_client=source_client,
        client_session_id=client_session_id,
    )
    return _attach_review_route(
        response,
        selected="external_directive",
        source_kind="external",
        source_value=None,
        target_tool="request_external_scientific_review_directive",
    )


def _format_scientific_report_list(items: Any, *, empty: str = "None reported.") -> str:
    values = _coerce_non_empty_str_list(items)
    if not values:
        return empty
    return "\n".join(f"- {value}" for value in values)


def _format_scientific_report_findings(findings: Any) -> str:
    if not isinstance(findings, list) or not findings:
        return "None reported."

    rows: list[str] = []
    for finding in findings[:20]:
        item = _record_dict(finding)
        rule_id = _first_text_value(item.get("rule_id")) or "unknown_rule"
        severity = _first_text_value(item.get("severity")) or "unknown"
        action = _first_text_value(item.get("action")) or "unknown"
        message = _first_text_value(item.get("message")) or "No message."
        rows.append(f"- {rule_id} [{severity}/{action}]: {message}")
        suggested_fix = _first_text_value(item.get("suggested_fix"))
        if suggested_fix:
            rows.append(f"  Suggested fix: {suggested_fix}")
    if len(findings) > 20:
        rows.append(f"- Truncated: {len(findings) - 20} additional findings omitted.")
    return "\n".join(rows)


_SCIENTIFIC_REPORT_BLOCKED_FINDING_SECTION = (
    "Analysis blocked by scientific review finding"
)


def _scientific_report_blocking_correctness_findings(
    verdict: dict[str, Any],
) -> list[dict[str, Any]]:
    correctness = _record_dict(verdict.get("correctness"))
    findings = correctness.get("findings")
    if not isinstance(findings, list):
        return []

    blocking: list[dict[str, Any]] = []
    for finding in findings:
        item = _record_dict(finding)
        severity = (_first_text_value(item.get("severity")) or "").strip().lower()
        action = (_first_text_value(item.get("action")) or "").strip().lower()
        if severity in {"critical", "error"} or action == "block":
            blocking.append(item)
    return blocking


def _scientific_report_conclusion_from_verdict(verdict: dict[str, Any]) -> str:
    overall = _first_text_value(verdict.get("overall_decision")) or "unknown"
    report_action = _first_text_value(verdict.get("report_action")) or "not specified"
    claim_strength = _first_text_value(verdict.get("claim_strength")) or "not specified"
    rationale = _first_text_value(verdict.get("rationale")) or "No rationale provided."
    next_actions = _coerce_non_empty_str_list(verdict.get("required_next_actions"))
    blocking_findings = _scientific_report_blocking_correctness_findings(verdict)

    if blocking_findings:
        opening = (
            "Analysis blocked by scientific review finding. Do not interpret this "
            "report as final scientific conclusions until the blocking correctness "
            "finding is resolved."
        )
    elif overall == "proceed":
        opening = (
            "The reviewed materials satisfy the current Brain Researcher scientific "
            "review checks for report generation."
        )
    elif overall == "stop_with_rationale":
        opening = (
            "The reviewed materials should not be presented as a final scientific "
            "conclusion until the blocking review rationale is addressed."
        )
    elif overall == "diagnose":
        opening = (
            "The reviewed materials require diagnosis before their conclusions are "
            "treated as scientifically stable."
        )
    elif overall == "explore_more":
        opening = (
            "The reviewed materials support a provisional report, but the conclusion "
            "should remain caveated until the review gaps are resolved."
        )
    else:
        opening = (
            "The scientific review returned an unrecognized decision; treat this "
            "report as a review draft rather than a final conclusion."
        )

    lines = [
        opening,
        f"Overall decision: {overall}",
        f"Report action: {report_action}",
        f"Recommended claim strength: {claim_strength}",
        f"Rationale: {rationale}",
    ]
    if blocking_findings:
        lines.extend(["", "Blocking correctness findings:"])
        lines.append(_format_scientific_report_findings(blocking_findings))
    if next_actions:
        lines.extend(["", "Required before stronger claims:"])
        lines.extend(f"- {action}" for action in next_actions[:10])
    return "\n".join(lines)


def _scientific_report_is_blocked(verdict: dict[str, Any]) -> bool:
    judgment = _record_dict(verdict.get("judgment"))
    overall = (_first_text_value(verdict.get("overall_decision")) or "").lower()
    report_action = (_first_text_value(verdict.get("report_action")) or "").lower()
    judgment_decision = (_first_text_value(judgment.get("decision")) or "").lower()
    return (
        overall == "stop_with_rationale"
        or report_action == "revise_report"
        or judgment_decision == "unsound"
        or bool(_scientific_report_blocking_correctness_findings(verdict))
    )


def _scientific_report_mode(verdict: dict[str, Any]) -> str:
    if _scientific_report_is_blocked(verdict):
        return "review_blocked_draft"
    if verdict.get("overall_decision") == "proceed":
        return "final_report"
    return "review_caveated_draft"


def _scientific_report_sections_from_verdict(
    verdict: dict[str, Any],
    *,
    source_label: str,
) -> dict[str, str]:
    correctness = _record_dict(verdict.get("correctness"))
    judgment = _record_dict(verdict.get("judgment"))
    completeness = _record_dict(verdict.get("completeness"))
    checklist = completeness.get("checklist")
    if not isinstance(checklist, dict):
        checklist = {}

    missing_checklist = [
        str(key)
        for key, value in sorted(checklist.items(), key=lambda item: str(item[0]))
        if value is False
    ]
    passed_checklist = [
        str(key)
        for key, value in sorted(checklist.items(), key=lambda item: str(item[0]))
        if value is True
    ]

    validation_status = verdict.get("validation_status")
    if isinstance(validation_status, dict) and validation_status:
        validation_lines = "\n".join(
            f"- {key}: {value}"
            for key, value in sorted(
                validation_status.items(), key=lambda item: str(item[0])
            )
        )
    else:
        validation_lines = "None reported."

    sections: dict[str, str] = {}
    blocking_findings = _scientific_report_blocking_correctness_findings(verdict)
    if blocking_findings:
        sections[_SCIENTIFIC_REPORT_BLOCKED_FINDING_SECTION] = "\n".join(
            [
                "Analysis blocked by scientific review finding.",
                (
                    "Do not interpret this report as final scientific conclusions "
                    "until the blocking correctness finding is resolved."
                ),
                "",
                "Blocking correctness findings:",
                _format_scientific_report_findings(blocking_findings),
            ]
        )

    sections.update(
        {
            "Executive Summary": "\n".join(
                [
                    f"Source: {source_label}",
                    f"Review scope: {_first_text_value(verdict.get('review_scope')) or 'unknown'}",
                    f"Overall decision: {_first_text_value(verdict.get('overall_decision')) or 'unknown'}",
                    f"Report action: {_first_text_value(verdict.get('report_action')) or 'not specified'}",
                    f"Claim strength: {_first_text_value(verdict.get('claim_strength')) or 'not specified'}",
                    f"Rationale: {_first_text_value(verdict.get('rationale')) or 'No rationale provided.'}",
                ]
            ),
            "Correctness Review": "\n".join(
                [
                    f"Decision: {_first_text_value(correctness.get('decision')) or 'unknown'}",
                    "",
                    "Findings:",
                    _format_scientific_report_findings(correctness.get("findings")),
                ]
            ),
            "Scientific Judgment": "\n".join(
                [
                    f"Decision: {_first_text_value(judgment.get('decision')) or 'unknown'}",
                    f"Estimand complete: {bool(judgment.get('estimand_complete', False))}",
                    f"Method defensible: {bool(judgment.get('method_defensible', False))}",
                    f"Judgment status: {_first_text_value(judgment.get('judgment_status')) or 'unknown'}",
                    "",
                    "Issues:",
                    _format_scientific_report_list(judgment.get("issues")),
                    "",
                    "Reviewer questions:",
                    _format_scientific_report_list(judgment.get("reviewer_questions")),
                ]
            ),
            "Completeness Review": "\n".join(
                [
                    f"Decision: {_first_text_value(completeness.get('decision')) or 'unknown'}",
                    "",
                    "Missing checklist items:",
                    _format_scientific_report_list(missing_checklist),
                    "",
                    "Passed checklist items:",
                    _format_scientific_report_list(passed_checklist),
                    "",
                    "Missing caveats:",
                    _format_scientific_report_list(completeness.get("missing_caveats")),
                ]
            ),
            "Required Next Actions": _format_scientific_report_list(
                verdict.get("required_next_actions")
            ),
            "Validation Status": validation_lines,
            "Consolidated Conclusion": _scientific_report_conclusion_from_verdict(
                verdict
            ),
        }
    )
    return sections


def _merge_scientific_report_sections(
    analysis_sections: dict[str, str],
    review_sections: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    sections: dict[str, str] = {}
    warnings: list[str] = []
    review_names = set(review_sections)
    if _SCIENTIFIC_REPORT_BLOCKED_FINDING_SECTION in review_sections:
        sections[_SCIENTIFIC_REPORT_BLOCKED_FINDING_SECTION] = review_sections[
            _SCIENTIFIC_REPORT_BLOCKED_FINDING_SECTION
        ]

    for name, content in analysis_sections.items():
        output_name = name
        if output_name in review_names:
            output_name = f"Analysis - {name}"
            warnings.append(
                f"Renamed analysis section {name!r} to {output_name!r} to avoid "
                "overwriting a generated review section."
            )
        suffix = 2
        base_name = output_name
        while output_name in sections or output_name in review_names:
            output_name = f"{base_name} ({suffix})"
            suffix += 1
        sections[output_name] = content

    for name, content in review_sections.items():
        if name not in sections:
            sections[name] = content
    return sections, warnings


def _scientific_report_markdown_from_sections(
    *,
    title: str,
    authors: str,
    subtitle: str = "",
    institution: str = "",
    date: str = "",
    sections: dict[str, str],
    source: dict[str, Any] | None = None,
    consolidation: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = [f"# {title.strip() or 'Scientific Report Draft'}", ""]
    if subtitle:
        lines.extend([f"## {subtitle}", ""])
    metadata = []
    if authors:
        metadata.append(f"Authors: {authors}")
    if institution:
        metadata.append(f"Institution: {institution}")
    if date:
        metadata.append(f"Date: {date}")
    if source:
        source_kind = source.get("kind")
        source_value = source.get("value")
        metadata.append(f"BR source: {source_kind}={source_value}")
    if consolidation:
        mode = consolidation.get("mode")
        claim_strength = consolidation.get("claim_strength")
        report_action = consolidation.get("report_action")
        if mode:
            metadata.append(f"Report mode: {mode}")
        if report_action:
            metadata.append(f"Report action: {report_action}")
        if claim_strength:
            metadata.append(f"Claim strength: {claim_strength}")
    if metadata:
        lines.extend(metadata)
        lines.append("")

    for name, content in sections.items():
        lines.extend([f"## {name}", "", str(content or "").rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _report_artifact_descriptor(
    *,
    run_id: str,
    run_dir: str,
    relpath: str,
    kind: str,
    media_type: str,
) -> dict[str, Any]:
    path = Path(run_dir) / relpath if run_dir else None
    read_tool = (
        "artifact_read_bytes"
        if media_type == "application/pdf"
        else "artifact_read_text"
    )
    read_arguments: dict[str, Any] = {"run_id": run_id, "relpath": relpath}
    if media_type == "application/pdf":
        read_arguments["max_bytes"] = MAX_BINARY_BYTES
    else:
        read_arguments["max_bytes"] = MAX_TEXT_BYTES
    descriptor: dict[str, Any] = {
        "kind": kind,
        "run_id": run_id,
        "relpath": relpath,
        "media_type": media_type,
        "read_tool": read_tool,
        "read_arguments": read_arguments,
    }
    if path is not None:
        descriptor["absolute_path"] = str(path)
    return descriptor


def _normalize_report_revision_source_artifacts(
    artifacts: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(artifacts, list):
        return normalized
    for idx, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            value = _first_text_value(artifact)
            if value:
                normalized.append(
                    {
                        "label": f"user_artifact_{idx + 1}",
                        "role": "user_supplied_context",
                        "path": value,
                    }
                )
            continue
        label = (
            _first_text_value(artifact.get("label"))
            or _first_text_value(artifact.get("name"))
            or _first_text_value(artifact.get("title"))
            or f"user_artifact_{idx + 1}"
        )
        item: dict[str, Any] = {
            "label": label,
            "role": _first_text_value(artifact.get("role")) or "user_supplied_context",
        }
        for key in ("path", "relpath", "absolute_path", "description", "media_type"):
            value = _first_text_value(artifact.get(key))
            if value:
                item[key] = value
        normalized.append(item)
    return normalized


def _normalize_report_local_workspace_context(
    local_workspace: str | None,
    local_workspace_manifest: dict[str, Any] | None,
) -> dict[str, Any] | None:
    manifest = _record_dict(local_workspace_manifest)
    path = _first_text_value(
        local_workspace,
        manifest.get("local_workspace"),
        manifest.get("workspace"),
        manifest.get("workspace_path"),
        manifest.get("path"),
    )
    if not path and not manifest:
        return None

    context: dict[str, Any] = {
        "access_mode": "client_local_workspace",
        "server_readable": False,
        "usage": (
            "The coding agent should read this workspace from its local filesystem, "
            "then revise the returned TeX/style/template bundle locally."
        ),
    }
    if path:
        context["path"] = path

    artifact_groups = (
        "source_files",
        "figures",
        "tables",
        "logs",
        "scripts",
        "citations",
        "data_files",
    )
    for key in artifact_groups:
        raw_items = manifest.get(key)
        if raw_items is None:
            continue
        if isinstance(raw_items, list):
            normalized = _normalize_report_revision_source_artifacts(raw_items)
        else:
            normalized = _normalize_report_revision_source_artifacts([raw_items])
        if normalized:
            context[key] = normalized

    for key in ("notes", "compile_command", "preferred_output_dir"):
        value = _first_text_value(manifest.get(key))
        if value:
            context[key] = value

    required_revision = _coerce_non_empty_str_list(manifest.get("required_revision"))
    if required_revision:
        context["required_revision"] = required_revision

    context["boundary"] = (
        "This local workspace is a handoff pointer, not proof that the deployed "
        "MCP server can read the path. Server-side review only covers run_id or "
        "autoresearch_dir sources that are readable in the server runtime."
    )
    return context


def _scientific_report_source_context_artifacts(
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    source_kind = _first_text_value(source.get("kind"))
    source_value = _first_text_value(source.get("value"))
    if not source_kind or not source_value:
        return []

    if source_kind == "autoresearch_dir":
        base = Path(source_value)
        candidates = [
            (
                "experiments_ledger",
                "experiments.jsonl",
                "experiment ledger; source of tested actions and scores",
            ),
            (
                "line_state",
                "line_state.json",
                "autoresearch line state and claim strength",
            ),
            (
                "final_report",
                "outputs/final_report.md",
                "line-authored final report; preserve its scientific detail",
            ),
            (
                "predict_source",
                "predict.py",
                "prediction implementation used by the line",
            ),
            ("run_source", "run.py", "line execution harness"),
            (
                "review_verdict",
                "outputs/autoresearch_scientific_review_verdict.json",
                "persisted scientific-review verdict",
            ),
            (
                "review_bundle",
                "outputs/autoresearch_scientific_review_bundle.json",
                "persisted scientific-review evidence bundle",
            ),
        ]
    elif source_kind == "run_id":
        try:
            base = _find_run_dir(source_value)
        except Exception:
            return []
        candidates = [
            ("run_record", "run.json", "BR run record"),
            ("provenance", "provenance.json", "BR run provenance"),
            ("analysis_bundle", "analysis_bundle.json", "analysis evidence bundle"),
            ("source_summary", "source_summary.json", "source summary for review"),
            (
                "review_verdict",
                "artifacts/review/scientific_review_verdict.json",
                "persisted scientific-review verdict",
            ),
        ]
    else:
        return []

    context: list[dict[str, Any]] = []
    for label, relpath, description in candidates:
        path = base / relpath
        if not path.exists() or not path.is_file():
            continue
        context.append(
            {
                "label": label,
                "role": "source_context",
                "relpath": relpath,
                "absolute_path": str(path),
                "description": description,
            }
        )
    return context


def _build_scientific_report_revision_handoff(
    *,
    render: dict[str, Any],
    source: dict[str, Any],
    consolidation: dict[str, Any],
    compile_pdf_requested: bool,
    revision_instructions: list[str] | None = None,
    revision_source_artifacts: list[dict[str, Any]] | None = None,
    local_workspace_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    report_run_id = _first_text_value(render.get("run_id"))
    run_dir = _first_text_value(render.get("run_dir")) or ""
    artifacts = render.get("artifacts")
    if not report_run_id or not isinstance(artifacts, dict):
        return None

    draft_artifacts: dict[str, dict[str, Any]] = {}
    artifact_specs = {
        "markdown": ("markdown", "text/markdown"),
        "tex": ("latex", "text/x-tex"),
        "style": ("latex_style", "text/x-tex"),
        "template": ("latex_template", "text/plain"),
        "pdf": ("pdf", "application/pdf"),
        "metadata": ("metadata", "application/json"),
        "bibliography": ("bibliography", "text/x-bibtex"),
        "handoff": ("handoff_manifest", "application/json"),
    }
    for artifact_key, (kind, media_type) in artifact_specs.items():
        relpath = _first_text_value(artifacts.get(artifact_key))
        if relpath:
            draft_artifacts[artifact_key] = _report_artifact_descriptor(
                run_id=report_run_id,
                run_dir=run_dir,
                relpath=relpath,
                kind=kind,
                media_type=media_type,
            )

    if not draft_artifacts:
        return None

    retrieval_plan = [
        {
            "artifact": key,
            "tool": descriptor["read_tool"],
            "arguments": descriptor["read_arguments"],
        }
        for key, descriptor in draft_artifacts.items()
    ]

    source_context_artifacts = _scientific_report_source_context_artifacts(source)
    user_source_artifacts = _normalize_report_revision_source_artifacts(
        revision_source_artifacts
    )
    instructions = _coerce_non_empty_str_list(revision_instructions)

    return {
        "protocol": "br.report_revision_handoff.directive.v1",
        "version": 1,
        "purpose": "source_preserving_scientific_report_revision",
        "source": source,
        "report_run_id": report_run_id,
        "run_dir": run_dir or None,
        "compile_pdf_requested": bool(compile_pdf_requested),
        "draft_artifacts": draft_artifacts,
        "source_context_artifacts": source_context_artifacts,
        "user_source_artifacts": user_source_artifacts,
        "local_workspace_context": local_workspace_context,
        "revision_instructions": instructions,
        "retrieval_plan": retrieval_plan,
        "editing_contract": {
            "source_of_truth": [
                "Use the draft TeX as the formatting/PDF source of truth.",
                "Use the draft Markdown and BR sections as the semantic source of truth.",
                "Use the review verdict and consolidation fields as claim-boundary constraints.",
                "Use source_context_artifacts and user_source_artifacts as detail-restoration evidence.",
                "When local_workspace_context is present, use it as the coding-agent-only local filesystem evidence plan.",
            ],
            "must": [
                "Preserve existing BR-generated sections unless the user explicitly asks to remove or restructure them.",
                "Make surgical additions for citations, figures, script paths, experiment logs, artifact provenance, and missing caveats.",
                "Restore details from source context instead of replacing them with a shorter summary.",
                "If local_workspace_context is present, read those files locally before editing the returned TeX.",
                "Keep negative results, blockers, required next work, and claim-strength boundaries visible.",
                "Compile the revised TeX to PDF and report the exact validation command/result.",
                "Report changed files and any remaining compile or evidence gaps.",
            ],
            "must_not": [
                "Regenerate the manuscript from a short summary when source files are available.",
                "Condense away reviewer-requested details, blocked axes, limitations, or provenance.",
                "Promote claim strength or remove caveats without new line-local evidence.",
                "Treat a generated PDF as editable source when TeX is available.",
            ],
            "default_revision_mode": "preserve_source_add_details",
        },
        "recommended_coding_agent_task": (
            "Retrieve the draft Markdown, TeX, LaTeX style/template assets, PDF, "
            "metadata, and handoff manifest; "
            "inspect source_context_artifacts, user_source_artifacts, and any "
            "local_workspace_context; revise the TeX source-preservingly; add "
            "requested scientific details and figures from explicit artifacts; "
            "compile PDF; return changed files, validation results, and unresolved "
            "evidence gaps."
        ),
        "consolidation": consolidation,
    }


def _write_scientific_report_markdown_artifact(
    *,
    render: dict[str, Any],
    title: str,
    authors: str,
    subtitle: str,
    institution: str,
    date: str,
    sections: dict[str, str],
    source: dict[str, Any],
    consolidation: dict[str, Any],
) -> str | None:
    run_dir_text = _first_text_value(render.get("run_dir"))
    if not run_dir_text:
        return None
    run_dir = Path(run_dir_text)
    report_dir = run_dir / "artifacts" / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "draft_report.md"
    markdown_path.write_text(
        _scientific_report_markdown_from_sections(
            title=title,
            authors=authors,
            subtitle=subtitle,
            institution=institution,
            date=date,
            sections=sections,
            source=source,
            consolidation=consolidation,
        ),
        encoding="utf-8",
    )
    return str(markdown_path.relative_to(run_dir))


def _write_scientific_report_handoff_artifact(
    *,
    render: dict[str, Any],
    handoff: dict[str, Any],
) -> str | None:
    run_dir_text = _first_text_value(render.get("run_dir"))
    if not run_dir_text:
        return None
    run_dir = Path(run_dir_text)
    report_dir = run_dir / "artifacts" / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = report_dir / "report_revision_handoff.json"
    _atomic_write_json(handoff_path, handoff)
    return str(handoff_path.relative_to(run_dir))


def _attach_scientific_report_revision_handoff(
    response: dict[str, Any],
    *,
    render: dict[str, Any],
    title: str,
    authors: str,
    subtitle: str,
    institution: str,
    date: str,
    sections: dict[str, str],
    source: dict[str, Any],
    consolidation: dict[str, Any],
    compile_pdf: bool,
    revision_instructions: list[str] | None = None,
    revision_source_artifacts: list[dict[str, Any]] | None = None,
    local_workspace_context: dict[str, Any] | None = None,
) -> None:
    if render.get("ok") is not True:
        return
    artifacts = render.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        render["artifacts"] = artifacts

    try:
        markdown_relpath = _write_scientific_report_markdown_artifact(
            render=render,
            title=title,
            authors=authors,
            subtitle=subtitle,
            institution=institution,
            date=date,
            sections=sections,
            source=source,
            consolidation=consolidation,
        )
        if markdown_relpath:
            artifacts["markdown"] = markdown_relpath

        handoff = _build_scientific_report_revision_handoff(
            render=render,
            source=source,
            consolidation=consolidation,
            compile_pdf_requested=compile_pdf,
            revision_instructions=revision_instructions,
            revision_source_artifacts=revision_source_artifacts,
            local_workspace_context=local_workspace_context,
        )
        if handoff is None:
            return
        handoff_relpath = _write_scientific_report_handoff_artifact(
            render=render,
            handoff=handoff,
        )
        if handoff_relpath:
            artifacts["handoff"] = handoff_relpath
            handoff = (
                _build_scientific_report_revision_handoff(
                    render=render,
                    source=source,
                    consolidation=consolidation,
                    compile_pdf_requested=compile_pdf,
                    revision_instructions=revision_instructions,
                    revision_source_artifacts=revision_source_artifacts,
                    local_workspace_context=local_workspace_context,
                )
                or handoff
            )
            _write_scientific_report_handoff_artifact(render=render, handoff=handoff)

        response["report_revision_handoff"] = handoff
        directive = response.setdefault("_agent_directive", {})
        if isinstance(directive, dict):
            directive["report_revision_handoff"] = handoff
    except Exception as exc:
        warnings = response.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(f"Report revision handoff artifact creation failed: {exc}")


@mcp.tool()
def scientific_report_generate(
    run_id: str | None = None,
    autoresearch_dir: str | None = None,
    workflow_id: str | None = None,
    logs_dir: str | None = None,
    task_id: str = "liu_component_v1",
    title: str | None = None,
    authors: str = "Brain Researcher",
    analysis_sections: dict[str, str] | None = None,
    subtitle: str = "",
    institution: str = "",
    date: str = "",
    use_judgment_critic: bool = True,
    force_recompute: bool = False,
    compile_pdf: bool = False,
    halt_on_review_block: bool = False,
    revision_instructions: list[str] | None = None,
    revision_source_artifacts: list[dict[str, Any]] | None = None,
    local_workspace: str | None = None,
    local_workspace_manifest: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
    require_claim_provenance: bool = False,
) -> dict[str, Any]:
    """Draft a scientific report by reviewing one run/workspace and rendering LaTeX.

    When ``run_id`` or ``autoresearch_dir`` is supplied, the tool delegates
    review to the existing scientific-review MCP functions, converts the
    resulting verdict into conservative report sections, merges optional
    plain-text analysis sections, then calls ``latex_report_render``. When no
    source is supplied, it degrades to a plain ``latex_report_render`` call over
    the provided analysis sections and skips scientific review.

    On successful render, the tool also writes a Markdown draft and a
    ``report_revision_handoff`` manifest next to the TeX/style/template/PDF
    artifacts. The handoff is for source-preserving revision by a coding agent;
    it is not an instruction to regenerate the manuscript from a summary. Optional
    ``revision_instructions``, ``revision_source_artifacts``, ``local_workspace``,
    and ``local_workspace_manifest`` are copied into that manifest so a coding
    agent can restore details from explicit evidence. ``local_workspace`` is a
    coding-agent handoff pointer only; the deployed MCP server does not assume it
    can read that filesystem path.
    """

    normalized_run_id = _first_text_value(run_id)
    normalized_autoresearch_dir = _first_text_value(autoresearch_dir)
    if normalized_run_id and normalized_autoresearch_dir:
        return {
            "ok": False,
            "error": "ambiguous_review_source",
            "message": "Provide exactly one of run_id or autoresearch_dir, not both.",
        }

    raw_analysis_sections = analysis_sections or {
        "Analysis Summary": "No additional analysis summary supplied."
    }
    _, section_issues = _validate_latex_report_sections(raw_analysis_sections)
    blocking_section_issues = [
        issue for issue in section_issues if issue.get("level") == "error"
    ]
    if blocking_section_issues:
        source_value = normalized_run_id or normalized_autoresearch_dir
        source_kind = (
            "run_id"
            if normalized_run_id
            else "autoresearch_dir" if normalized_autoresearch_dir else "none"
        )
        return {
            "ok": False,
            "error": "analysis_sections_invalid",
            "source": {"kind": source_kind, "value": source_value},
            "issues": section_issues,
        }
    normalized_analysis_sections = {
        str(name).strip(): str(content or "")
        for name, content in raw_analysis_sections.items()
    }
    normalized_revision_instructions = _coerce_non_empty_str_list(revision_instructions)
    normalized_revision_source_artifacts = _normalize_report_revision_source_artifacts(
        revision_source_artifacts
    )
    normalized_local_workspace_context = _normalize_report_local_workspace_context(
        local_workspace,
        local_workspace_manifest,
    )

    review: dict[str, Any] | None = None
    merge_warnings: list[str] = []
    if normalized_run_id:
        review = run_scientific_review(
            normalized_run_id,
            workflow_id=workflow_id,
            use_judgment_critic=use_judgment_critic,
            force_recompute=force_recompute,
        )
        source = {"kind": "run_id", "value": normalized_run_id}
        source_label = f"run_id={normalized_run_id}"
        default_title = f"Scientific Review Report for {normalized_run_id}"
    elif normalized_autoresearch_dir:
        review = run_autoresearch_scientific_review(
            normalized_autoresearch_dir or "",
            logs_dir=logs_dir,
            task_id=task_id,
            use_judgment_critic=use_judgment_critic,
            force_recompute=force_recompute,
        )
        source = {"kind": "autoresearch_dir", "value": normalized_autoresearch_dir}
        source_label = f"autoresearch_dir={normalized_autoresearch_dir}"
        default_title = "Autoresearch Scientific Review Report"
    else:
        source = {"kind": "none", "value": None}
        default_title = "Scientific Report Draft"
        sections = normalized_analysis_sections
        consolidation = {
            "overall_decision": None,
            "report_action": "render_only",
            "claim_strength": None,
            "rationale": (
                "No run_id or autoresearch_dir was provided; rendered the supplied "
                "analysis sections without scientific review."
            ),
            "required_next_actions": [],
            "mode": "analysis_only_render",
        }
        merge_warnings = [
            "No run_id or autoresearch_dir was provided; rendered the supplied analysis sections without scientific review."
        ]
        render_title = _first_text_value(title) or default_title
        render_authors = _first_text_value(authors) or "Brain Researcher"
        render = latex_report_render(
            title=render_title,
            authors=render_authors,
            sections=sections,
            subtitle=subtitle,
            institution=institution,
            date=date,
            compile_pdf=compile_pdf,
            sections_are_latex=False,
        )
        warnings = [
            *merge_warnings,
            *_coerce_non_empty_str_list(render.get("warnings")),
        ]

        response: dict[str, Any] = {
            "ok": render.get("ok") is True,
            "source": source,
            "review": None,
            "review_skipped": True,
            "consolidation": consolidation,
            "sections": sections,
            "report_render": render,
            "compile_pdf_requested": bool(compile_pdf),
            "warnings": warnings,
        }
        _attach_scientific_report_revision_handoff(
            response,
            render=render,
            title=render_title,
            authors=render_authors,
            subtitle=subtitle,
            institution=institution,
            date=date,
            sections=sections,
            source=source,
            consolidation=consolidation,
            compile_pdf=compile_pdf,
            revision_instructions=normalized_revision_instructions,
            revision_source_artifacts=normalized_revision_source_artifacts,
            local_workspace_context=normalized_local_workspace_context,
        )
        if render.get("ok") is True:
            response["report_run_id"] = render.get("run_id")
            response["artifacts"] = render.get("artifacts", {})
        else:
            response["error"] = "render_failed"
        return response

    if review.get("ok") is not True:
        return {
            "ok": False,
            "error": "review_failed",
            "source": source,
            "review": review,
        }

    # Claim-provenance gate (run_id path only). Build a provenance index from the
    # run and validate report claims against artifacts/code that actually ran. A
    # blocking gate finding is folded into review['correctness']['findings'] BEFORE
    # sections/mode are computed so the existing blocked-draft machinery
    # (halt_on_review_block, _scientific_report_mode) reflects it. Wrapped in
    # try/except so a provenance-index failure never breaks report generation.
    claim_gate: dict[str, Any] | None = None
    claim_gate_warnings: list[str] = []
    if normalized_run_id and claims:
        try:
            from brain_researcher.services.review.bundle_builder import (
                build_artifact_review_bundle,
            )
            from brain_researcher.services.review.claim_provenance import (
                build_claim_provenance_gate,
                build_run_provenance_index,
            )

            _prov_bundle = build_artifact_review_bundle(
                normalized_run_id, workflow_id=workflow_id
            )
            _prov_index = build_run_provenance_index(_prov_bundle)
            try:
                _claim_mode = _claim_mode_from_run_dir(_find_run_dir(normalized_run_id))
            except Exception:
                _claim_mode = "confirmatory"
            claim_gate = build_claim_provenance_gate(
                claims,
                _prov_index,
                claim_mode=_claim_mode,
                require_claim_provenance=require_claim_provenance,
            )
        except Exception as exc:  # pragma: no cover - defensive
            claim_gate_warnings.append(f"claim_provenance_gate_failed: {exc}")
            claim_gate = None
        if claim_gate and claim_gate.get("finding"):
            _correctness = review.setdefault("correctness", {})
            if not isinstance(_correctness, dict):
                _correctness = {}
                review["correctness"] = _correctness
            _findings = _correctness.setdefault("findings", [])
            if not isinstance(_findings, list):
                _findings = []
                _correctness["findings"] = _findings
            _findings.append(claim_gate["finding"])

    review_sections = _scientific_report_sections_from_verdict(
        review,
        source_label=source_label,
    )
    sections, merge_warnings = _merge_scientific_report_sections(
        normalized_analysis_sections,
        review_sections,
    )
    # extend AFTER the merge, which reassigns merge_warnings (caveat fix).
    merge_warnings.extend(claim_gate_warnings)
    if claim_gate and claim_gate.get("section_text"):
        sections["Claims missing provenance"] = claim_gate["section_text"]
    consolidation = {
        "overall_decision": review.get("overall_decision"),
        "report_action": review.get("report_action"),
        "claim_strength": review.get("claim_strength"),
        "rationale": review.get("rationale"),
        "required_next_actions": review.get("required_next_actions") or [],
        "mode": _scientific_report_mode(review),
    }
    if claim_gate is not None:
        consolidation["claim_provenance"] = claim_gate
    if halt_on_review_block and _scientific_report_is_blocked(review):
        blocked_response: dict[str, Any] = {
            "ok": False,
            "error": "review_blocked_report_generation",
            "source": source,
            "review": review,
            "consolidation": consolidation,
            "sections": sections,
            "warnings": merge_warnings,
        }
        if "_agent_directive" in review:
            blocked_response["_agent_directive"] = review["_agent_directive"]
        return blocked_response

    render_title = _first_text_value(title) or default_title
    render_authors = _first_text_value(authors) or "Brain Researcher"
    render = latex_report_render(
        title=render_title,
        authors=render_authors,
        sections=sections,
        subtitle=subtitle,
        institution=institution,
        date=date,
        compile_pdf=compile_pdf,
        sections_are_latex=False,
    )
    warnings = [
        *merge_warnings,
        *_coerce_non_empty_str_list(render.get("warnings")),
    ]

    response: dict[str, Any] = {
        "ok": render.get("ok") is True,
        "source": source,
        "review": review,
        "review_skipped": False,
        "consolidation": consolidation,
        "sections": sections,
        "report_render": render,
        "compile_pdf_requested": bool(compile_pdf),
        "warnings": warnings,
    }
    if "_agent_directive" in review:
        response["_agent_directive"] = review["_agent_directive"]
    _attach_scientific_report_revision_handoff(
        response,
        render=render,
        title=render_title,
        authors=render_authors,
        subtitle=subtitle,
        institution=institution,
        date=date,
        sections=sections,
        source=source,
        consolidation=consolidation,
        compile_pdf=compile_pdf,
        revision_instructions=normalized_revision_instructions,
        revision_source_artifacts=normalized_revision_source_artifacts,
        local_workspace_context=normalized_local_workspace_context,
    )
    if render.get("ok") is True:
        response["report_run_id"] = render.get("run_id")
        response["artifacts"] = render.get("artifacts", {})
    else:
        response["error"] = "render_failed"
    return response


@mcp.tool()
def request_external_scientific_review_directive(
    goal: str,
    hints: dict[str, Any] | None = None,
    session_id: str | None = None,
    source_client: str | None = None,
    client_session_id: str | None = None,
    include_full_rubric: bool = False,
) -> dict[str, Any]:
    """Emit a stateless scientific-review directive for a non-BR (external) run.

    BR does not read any external artifacts. It returns the four-axis evaluation
    conditions (correctness / completeness / judgment / overall), the target
    verdict schema (ScientificReviewVerdict), and the submission tool that an
    external coding agent must call after performing the review itself.

    Optional ``hints`` (e.g. ``{"adapter": "fitlins_multiverse"}``) append
    adapter- or analysis-specific checks to ``tailored_checks`` without altering
    the base four-axis schema. ``session_id`` is optional only for standalone
    directive rendering. The round-trip submit path requires the directive to be
    issued with ``session_id`` or ``client_session_id`` so the verdict can be
    cross-referenced later.
    """

    try:
        goal_text = _first_text_value(goal)
        if not goal_text:
            raise ValueError("goal is required")
    except Exception as exc:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": str(exc),
        }

    normalized_session_id: str | None = None
    normalized_client_session_id: str | None = None
    normalized_source_client: str | None = None
    if session_id or client_session_id:
        try:
            (
                normalized_session_id,
                normalized_client_session_id,
                normalized_source_client,
            ) = _resolve_research_session_identity(
                session_id,
                client_session_id=client_session_id,
                source_client=source_client,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": "invalid_arguments",
                "message": str(exc),
            }

    directive_id = f"ext_review_dir_{uuid.uuid4().hex[:12]}"
    issued_at = _utc_iso()
    directive, applied_keys = _build_external_review_directive(
        goal_text,
        hints,
        directive_id=directive_id,
        session_id=normalized_session_id,
        issued_at=issued_at,
        include_full_rubric=bool(include_full_rubric),
    )

    log_result: dict[str, Any] = {}
    if normalized_session_id or normalized_client_session_id:
        log_result = log_research_event(
            kind="note",
            content=f"external_review directive issued: {goal_text[:200]}",
            session_id=normalized_session_id,
            source="agent",
            context={
                "directive_id": directive_id,
                "protocol": directive["protocol"],
                "hints_applied": directive["hints_applied"],
                "tailoring_keys": applied_keys,
                "kg_rule_registry": directive.get("kg_rule_registry"),
            },
            tags=[
                "external_review",
                "scientific_review",
                "directive_issued",
            ],
            source_client=normalized_source_client,
            client_session_id=normalized_client_session_id,
        )

    response: dict[str, Any] = {"ok": True, **directive}
    if normalized_client_session_id:
        response["client_session_id"] = normalized_client_session_id
    if normalized_source_client:
        response["source_client"] = normalized_source_client
    if normalized_session_id:
        response["agent_instructions"] = [
            *list(response.get("agent_instructions") or []),
            "When submitting the verdict, include the session binding fields returned in this directive.",
        ]
    else:
        response["round_trip_hint"] = {
            "session_binding_required": True,
            "submission_tool": "submit_external_scientific_review_verdict",
            "message": (
                "This directive was issued without session_id/client_session_id. "
                "Verdict submission requires a session binding, so issue the "
                "directive with session_id or client_session_id for the "
                "directive -> verdict round trip."
            ),
        }
        response["agent_instructions"] = [
            *list(response.get("agent_instructions") or []),
            (
                "Round-trip verdict submission requires a session_id or "
                "client_session_id; re-issue this directive with one before "
                "calling submit_external_scientific_review_verdict."
            ),
        ]
    if isinstance(log_result, dict):
        if log_result.get("ok"):
            event = log_result.get("event") or {}
            if isinstance(event, dict) and event.get("event_id"):
                response["logged_event_id"] = event["event_id"]
            if log_result.get("run_id"):
                response["logged_run_id"] = log_result["run_id"]
        elif log_result:
            warning = log_result.get("message") or log_result.get("error")
            return {
                "ok": False,
                "error": "directive_logging_failed",
                "message": warning or "failed to persist directive event",
                "session_id": normalized_session_id,
                "client_session_id": normalized_client_session_id,
                "source_client": normalized_source_client,
            }
    return response


@mcp.tool()
def submit_external_scientific_review_verdict(
    directive_id: str,
    verdict: Annotated[
        dict[str, Any],
        Field(
            description=(
                "ScientificReviewVerdict object, validated server-side against the "
                "ScientificReviewVerdict schema. Top-level 'overall_decision' must be one "
                "of: proceed, diagnose, explore_more, stop_with_rationale. (A full nested "
                "$defs schema is intentionally not advertised: FastMCP 1.26 cannot ref-count "
                "the nested decision models, and an object param cannot carry a string enum.)"
            ),
        ),
    ],
    session_id: str | None = None,
    reviewer: str | None = None,
    notes: str | None = None,
    source_client: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Accept a ScientificReviewVerdict produced by an external coding agent.

    Validates ``verdict`` against ``ScientificReviewVerdict``; on success,
    records the verdict via ``log_research_event`` and returns the normalized
    verdict plus a ``review_handoff`` directive when the overall decision is
    not ``proceed``. This is the return half of the ``request_external_
    scientific_review_directive`` -> external agent -> BR round-trip. The
    original directive must have been issued with ``session_id`` or
    ``client_session_id``, and the same binding is required here.
    """

    try:
        from brain_researcher.core.contracts.scientific_review import (
            ScientificReviewVerdict,
            roll_up_scientific_decision,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": "import_failed",
            "message": str(exc),
        }

    directive_id_text = _first_text_value(directive_id)
    if not directive_id_text:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": "directive_id is required",
        }
    if not (session_id or client_session_id):
        return {
            "ok": False,
            "error": "session_binding_required",
            "directive_id": directive_id_text,
            "message": (
                "session_id or client_session_id is required for "
                "directive-bound external review submission"
            ),
        }
    normalized_session_id: str | None = None
    normalized_client_session_id: str | None = None
    normalized_source_client: str | None = None
    (
        normalized_session_id,
        normalized_client_session_id,
        normalized_source_client,
    ) = _resolve_research_session_identity(
        session_id,
        client_session_id=client_session_id,
        source_client=source_client,
    )
    if not _research_session_has_directive(
        session_id=normalized_session_id,
        directive_id=directive_id_text,
    ):
        return {
            "ok": False,
            "error": "directive_not_found",
            "directive_id": directive_id_text,
            "message": "directive_id was not found in the supplied research session",
        }
    if not isinstance(verdict, dict):
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": "verdict must be a JSON object matching ScientificReviewVerdict",
        }

    try:
        parsed = ScientificReviewVerdict.model_validate(verdict)
    except Exception as exc:
        errors: Any
        extractor = getattr(exc, "errors", None)
        if callable(extractor):
            try:
                errors = extractor()
            except Exception:
                errors = str(exc)
        else:
            errors = str(exc)
        return {
            "ok": False,
            "error": "verdict_schema_invalid",
            "directive_id": directive_id_text,
            "schema_errors": errors,
        }

    expected_overall_decision, expected_rationale = roll_up_scientific_decision(
        parsed.correctness,
        parsed.judgment,
        parsed.completeness,
    )
    if parsed.overall_decision != expected_overall_decision:
        return {
            "ok": False,
            "error": "verdict_inconsistent",
            "directive_id": directive_id_text,
            "provided_overall_decision": parsed.overall_decision,
            "expected_overall_decision": expected_overall_decision,
            "expected_rationale": expected_rationale,
            "message": (
                "overall_decision is inconsistent with correctness/judgment/"
                "completeness verdict cards"
            ),
        }

    verdict_dict = parsed.model_dump()
    verdict_id = f"ext_review_verdict_{uuid.uuid4().hex[:12]}"
    stored_at = _utc_iso()
    reviewer_text = _first_text_value(reviewer) or "external_coding_agent"
    notes_text = _first_text_value(notes)
    kg_rule_feedback: dict[str, Any] = {}
    kg_feedback_write: dict[str, Any] = {}
    try:
        from brain_researcher.services.review.kg_rule_registry import (
            record_external_review_rule_feedback,
            summarize_external_review_rule_feedback,
        )

        kg_rule_feedback = summarize_external_review_rule_feedback(verdict_dict)
        if kg_rule_feedback.get("cited_rule_ids"):
            kg_feedback_write = record_external_review_rule_feedback(
                feedback=kg_rule_feedback,
                directive_id=directive_id_text,
                verdict_id=verdict_id,
                session_id=normalized_session_id or "",
                reviewer=reviewer_text,
                overall_decision=verdict_dict.get("overall_decision"),
            )
            kg_rule_feedback["kg_write"] = kg_feedback_write
    except Exception as exc:
        kg_rule_feedback = {
            "status": "feedback_processing_failed",
            "message": str(exc),
        }

    log_context: dict[str, Any] = {
        "directive_id": directive_id_text,
        "verdict_id": verdict_id,
        "reviewer": reviewer_text,
        "overall_decision": verdict_dict.get("overall_decision"),
        "correctness_decision": (verdict_dict.get("correctness") or {}).get("decision"),
        "judgment_decision": (verdict_dict.get("judgment") or {}).get("decision"),
        "completeness_decision": (verdict_dict.get("completeness") or {}).get(
            "decision"
        ),
        "verdict": verdict_dict,
    }
    if notes_text:
        log_context["notes"] = notes_text
    if kg_rule_feedback:
        log_context["kg_rule_feedback"] = kg_rule_feedback

    log_result: dict[str, Any] = log_research_event(
        kind="note",
        content=(
            "external_review verdict received "
            f"(overall_decision={verdict_dict.get('overall_decision')})"
        ),
        session_id=normalized_session_id,
        source="agent",
        context=log_context,
        tags=[
            "external_review",
            "scientific_review",
            "external_review_verdict",
        ],
        source_client=normalized_source_client,
        client_session_id=normalized_client_session_id,
    )

    response: dict[str, Any] = {
        "ok": True,
        "directive_id": directive_id_text,
        "verdict_id": verdict_id,
        "stored_at": stored_at,
        "reviewer": reviewer_text,
        "inner_verdict": verdict_dict,
    }
    if kg_rule_feedback:
        response["kg_rule_feedback"] = kg_rule_feedback
    if isinstance(log_result, dict):
        if log_result.get("ok"):
            event = log_result.get("event") or {}
            if isinstance(event, dict) and event.get("event_id"):
                response["logged_event_id"] = event["event_id"]
            if log_result.get("run_id"):
                response["logged_run_id"] = log_result["run_id"]
        elif log_result:
            warning = log_result.get("message") or log_result.get("error")
            return {
                "ok": False,
                "error": "verdict_logging_failed",
                "directive_id": directive_id_text,
                "message": warning or "failed to persist verdict event",
                "session_id": normalized_session_id,
                "client_session_id": normalized_client_session_id,
                "source_client": normalized_source_client,
            }

    handoff = _build_review_handoff_directive(
        verdict_dict, review_type="scientific_review"
    )
    if handoff is not None:
        response["_agent_directive"] = {"review_handoff": handoff}

    return response


@mcp.tool()
def refuted_landscape_summary(
    findings: list[dict[str, Any]],
    session_id: str | None = None,
    run_ids: list[str] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """Summarize refuted/supported/inconclusive directions from structured findings.

    ``findings`` is the evidence-bearing input in v1. Optional ``session_id`` and
    ``run_ids`` only enrich the response with session/run metadata; they do not
    alter counts or statuses. Each finding item must be an object with non-empty
    ``claim``, ``direction``, ``status``, and ``reason`` fields; ``status`` must
    be one of ``refuted``, ``supported``, or ``inconclusive``.
    """

    try:
        if not isinstance(findings, list) or not findings:
            raise ValueError("findings must be a non-empty list")
        safe_top_k = max(1, min(int(top_k), 50))
        missing_required_keys = _missing_refuted_landscape_required_keys(findings)
        if missing_required_keys:
            return {
                "ok": False,
                "error": "invalid_arguments",
                "message": (
                    "findings items are missing required keys: "
                    + ", ".join(missing_required_keys)
                ),
                "missing_required_keys": missing_required_keys,
                "required_item_fields": list(_REFUTED_LANDSCAPE_REQUIRED_ITEM_FIELDS),
            }
        summary = _summarize_refuted_landscape(findings, top_k=safe_top_k)
    except Exception as exc:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": str(exc),
        }

    enrichment: dict[str, Any] = {}
    normalized_session_id = _first_text_value(session_id)
    normalized_run_ids = _coerce_non_empty_str_list(run_ids)
    if normalized_session_id:
        digest_resp = research_session_digest(session_id=normalized_session_id)
        if digest_resp.get("ok") is not True:
            return {
                "ok": False,
                "error": digest_resp.get("error") or "research_session_not_found",
                "message": digest_resp.get("message")
                or "failed to load session digest",
                "session_id": normalized_session_id,
            }
        digest = _record_dict(digest_resp.get("digest"))
        enrichment.update(
            {
                "session_id": normalized_session_id,
                "done_items": _coerce_non_empty_str_list(digest.get("done_items")),
                "open_items": _coerce_non_empty_str_list(digest.get("open_items")),
            }
        )
        if not normalized_run_ids:
            normalized_run_ids = _coerce_non_empty_str_list(
                digest.get("run_ids")
            ) or _coerce_non_empty_str_list([digest.get("run_id")])
    if normalized_run_ids:
        enrichment["run_ids"] = list(dict.fromkeys(normalized_run_ids))

    return {
        "ok": True,
        **summary,
        "rigor_guards": [
            "Counts and statuses are derived only from caller-supplied structured findings.",
            "Session and run metadata are enrichment only and never change finding classification.",
        ],
        "enrichment": enrichment,
    }


@mcp.tool()
def companion_diagnostic_suggester(
    metric_name: str,
    observed_value: float | None = None,
    context: dict[str, Any] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """Suggest companion diagnostics for a named metric.

    Returns the companion checks that guard against known failure modes for
    ``metric_name`` (e.g. ``reliability_ratio`` -> ``within_class_variance_
    ratio`` to rule out oversmoothing). The mapping is a fixed v1 lookup
    table, not a model; unknown metrics return ``matched_known_metric: False``
    with an empty companion list so callers can log the gap.

    ``observed_value`` is never used to gate suggestions; it is echoed back
    alongside each companion's ``value_band_hint`` so the caller (or an
    external coding agent) decides whether the band actually applies.
    ``context`` (e.g. ``{"classifier_family": "kNN"}``) is compared against
    each companion's ``requires_context`` and recorded as
    ``applies_if_context_matches`` so entries are surfaced, not hidden, when
    context is absent.
    """

    try:
        safe_top_k = max(1, min(int(top_k), 50))
    except Exception as exc:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": f"top_k must be an integer: {exc}",
        }

    text = _first_text_value(metric_name)
    if not text:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": "metric_name is required",
        }

    companions, normalized_key, matched = _lookup_companion_diagnostics(
        text,
        context=context,
        top_k=safe_top_k,
    )

    response: dict[str, Any] = {
        "ok": True,
        "metric_name": text,
        "normalized_metric_key": normalized_key,
        "matched_known_metric": matched,
        "observed_value": observed_value,
        "companions": companions,
        "rigor_guards": [
            "Companion diagnostics are advisory. Running a companion is not "
            "proof of correctness; skipping one is not proof of a problem.",
            "Value-band hints are not evaluated server-side; the caller "
            "decides whether ``observed_value`` falls in the band.",
            "Coverage is a fixed v1 table; unknown metrics should be logged "
            "as gaps rather than taken as 'no companions needed'.",
        ],
        "coverage": {
            "table_version": _COMPANION_DIAGNOSTIC_TABLE_VERSION,
            "known_metrics_count": len(_COMPANION_DIAGNOSTIC_TABLE),
        },
    }
    if not matched:
        response["note"] = (
            "metric not in v1 companion table; treat as coverage gap and "
            "surface it for future inclusion"
        )
    return response


@mcp.tool()
def pipeline_execute(
    plan: dict[str, Any],
    dry_run: bool = False,
    approval_phrase: str | None = None,
) -> dict[str, Any]:
    """[DEPRECATED for Agents] Execute a validated pipeline plan (manual/admin path only)."""
    try:
        parsed = _coerce_plan(plan)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    run_id = _new_run_id()
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    log_trace = None
    try:
        from brain_researcher.services.agent.run_bundle import (
            log_trace_event as _log_trace_event,
        )

        log_trace = _log_trace_event
    except Exception:
        log_trace = None

    provenance = {
        "run_id": run_id,
        "mode": "mcp",
        "route": "pipeline_execute",
        "transport": DEFAULT_TRANSPORT,
        "guardrails": _mcp_guardrails_snapshot(),
        "request": {
            "plan": plan,
            "dry_run": bool(dry_run),
            "approval_supplied": bool(_text_value(approval_phrase)),
        },
    }
    _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))

    _emit_trace_event(
        log_trace,
        run_dir,
        run_id=run_id,
        event_type="mcp.pipeline_execute.queued",
        payload={"dry_run": bool(dry_run)},
    )

    normalized, issues, run_workspace, run_tag = _normalize_plan_for_run(parsed, run_id)
    issues = [
        *issues,
        *_validate_pipeline_execution_contract(
            plan,
            normalized,
            dry_run=bool(dry_run),
        ),
        *_validate_pipeline_execution_gate(
            plan,
            dry_run=bool(dry_run),
            approval_phrase=approval_phrase,
        ),
    ]
    policy_issues = _extract_policy_issues_from_issue_list(issues)
    run_workspace_str = str(run_workspace) if run_workspace is not None else None
    if run_workspace is not None:
        _ensure_workspace_layout(run_workspace)

    _atomic_write_json(run_dir / "validation.issues.json", {"issues": issues})
    if any(i.get("level") == "error" for i in issues):
        pipeline_gate_error_code = next(
            (
                str(i.get("code") or "")
                for i in issues
                if str(i.get("code") or "")
                in (
                    _PIPELINE_EXECUTION_CONTRACT_ERROR_CODES
                    | _PIPELINE_EXECUTION_GATE_ERROR_CODES
                )
            ),
            None,
        )
        error_code = pipeline_gate_error_code or "plan_invalid"
        failure_stage = (
            "execution_contract_rejected"
            if pipeline_gate_error_code
            else "plan_validation_failed"
        )
        failure_message = (
            "Pipeline execution gate rejected"
            if pipeline_gate_error_code
            else "Pipeline plan validation failed"
        )
        _atomic_write_json(
            run_dir / "plan.normalized.json",
            {
                "project_root": normalized.project_root,
                "run_tag": run_tag,
                "run_workspace": run_workspace_str,
                "steps": [
                    {
                        "step_id": s.step_id,
                        "tool": s.tool,
                        "params": s.params,
                        "work_dir": s.work_dir,
                        "output_dir": s.output_dir,
                    }
                    for s in normalized.steps
                ],
            },
        )

        record = RunRecord(
            run_id=run_id,
            created_at=_utc_iso(),
            status="failed",
            dry_run=bool(dry_run),
            run_workspace=run_workspace_str,
            finished_at=_utc_iso(),
            error=error_code,
            progress={
                "current_stage": failure_stage,
                "message": failure_message,
                "last_progress_at": _utc_iso(),
            },
            timing_policy=_default_run_timing_policy(),
            steps=[
                StepRecord(
                    step_id=s.step_id or f"s{idx}",
                    tool_id=s.tool,
                    params=s.params,
                    status="skipped",
                    work_dir=s.work_dir,
                    output_dir=s.output_dir,
                    error=error_code,
                    policy_issues=_policy_issues_for_step(
                        policy_issues, step_id=s.step_id or f"s{idx}"
                    ),
                    progress={
                        "current_stage": failure_stage,
                        "message": (
                            "Skipped because pipeline execution gate was rejected"
                            if pipeline_gate_error_code
                            else "Skipped because pipeline plan is invalid"
                        ),
                        "last_progress_at": _utc_iso(),
                    },
                )
                for idx, s in enumerate(normalized.steps, start=1)
            ],
        )
        _save_run(record)

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type=(
                "mcp.pipeline_execute.execution_contract_rejected"
                if pipeline_gate_error_code
                else "mcp.pipeline_execute.plan_invalid"
            ),
            payload={"issues": issues},
        )

        _persist_mcp_run_bundle(run_id, preflight_issues=issues)
        resp: dict[str, Any] = {
            "ok": False,
            "error": error_code,
            "issues": issues,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "run_workspace": run_workspace_str,
        }
        if pipeline_gate_error_code:
            gate_issue = next(
                (
                    issue
                    for issue in issues
                    if str(issue.get("code") or "") == pipeline_gate_error_code
                ),
                None,
            )
            gate_message = _text_value((gate_issue or {}).get("message"))
            if gate_message:
                resp["message"] = gate_message
        if policy_issues:
            resp["policy_issues"] = policy_issues
        return resp

    _atomic_write_json(
        run_dir / "plan.normalized.json",
        {
            "project_root": normalized.project_root,
            "run_tag": run_tag,
            "run_workspace": run_workspace_str,
            "steps": [
                {
                    "step_id": s.step_id,
                    "tool": s.tool,
                    "params": s.params,
                    "work_dir": s.work_dir,
                    "output_dir": s.output_dir,
                }
                for s in normalized.steps
            ],
        },
    )

    record = RunRecord(
        run_id=run_id,
        created_at=_utc_iso(),
        status="queued",
        dry_run=bool(dry_run),
        run_workspace=run_workspace_str,
        progress={
            "current_stage": "queued",
            "message": "Queued pipeline execution",
            "last_progress_at": _utc_iso(),
        },
        timing_policy=_default_run_timing_policy(),
        steps=[
            StepRecord(
                step_id=s.step_id or f"s{idx}",
                tool_id=s.tool,
                params=s.params,
                status="queued",
                work_dir=s.work_dir,
                output_dir=s.output_dir,
                progress={
                    "current_stage": "queued",
                    "message": f"Queued {s.tool}",
                    "last_progress_at": _utc_iso(),
                },
            )
            for idx, s in enumerate(normalized.steps, start=1)
        ],
    )
    _save_run(record)

    if AGENT_DELEGATED_EXECUTION_ENABLED and not dry_run and len(normalized.steps) == 1:
        normalized_step = normalized.steps[0]
        original_step = parsed.steps[0] if parsed.steps else None
        delegated_work_dir = (
            normalized_step.work_dir
            if original_step is not None and original_step.work_dir
            else None
        )
        delegated_output_dir = (
            normalized_step.output_dir
            if original_step is not None and original_step.output_dir
            else None
        )
        provenance["delegated_execution"] = {
            "backend": "agent",
            "endpoint": _agent_delegation_endpoint(),
            "execution_type": "tool",
            "delegated_at": _utc_iso(),
        }
        _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))
        delegated = _delegate_execution_to_agent(
            run_id=run_id,
            execution_type="tool",
            tool_id=normalized_step.tool,
            params=normalized_step.params,
            work_dir=delegated_work_dir,
            output_dir=delegated_output_dir,
            origin="mcp_pipeline_execute",
        )
        if delegated.get("ok") is not True:
            delegated_error = str(delegated.get("error") or "agent_delegation_failed")
            record.status = "failed"
            record.error = delegated_error
            record.finished_at = _utc_iso()
            record.steps[0].status = "failed"
            record.steps[0].error = delegated_error
            _save_run(record)
            _persist_mcp_run_bundle(run_id, preflight_issues=issues)
            resp: dict[str, Any] = {
                "ok": False,
                "error": delegated_error,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "run_workspace": run_workspace_str,
                "execution_trace": [
                    "preflight_passed",
                    "delegated_to_agent",
                    "delegation_failed",
                ],
                "execution_mode": "agent_delegated",
                "delegated_execution": {
                    "backend": "agent",
                    "endpoint": delegated.get("endpoint")
                    or _agent_delegation_endpoint(),
                },
            }
            if issues:
                resp["issues"] = issues
            if policy_issues:
                resp["policy_issues"] = policy_issues
            return resp

        _emit_trace_event(
            log_trace,
            run_dir,
            run_id=run_id,
            event_type="mcp.pipeline_execute.delegated",
            payload={
                "tool_id": normalized_step.tool,
                "endpoint": _agent_delegation_endpoint(),
            },
        )
        resp = {
            "ok": True,
            "run_id": str(delegated.get("run_id") or run_id),
            "status": str(delegated.get("status") or "queued"),
            "run_dir": delegated.get("run_dir"),
            "run_workspace": run_workspace_str,
            "execution_trace": ["preflight_passed", "delegated_to_agent", "queued"],
            "execution_mode": "agent_delegated",
            "delegated_execution": {
                "backend": "agent",
                "endpoint": _agent_delegation_endpoint(),
            },
        }
        if issues:
            resp["issues"] = issues
        if policy_issues:
            resp["policy_issues"] = policy_issues
        return resp

    if dry_run:
        _execute_run(run_id)
        final_status = "succeeded"
        try:
            final_status = _load_run(run_id).status
        except Exception:
            pass

        resp: dict[str, Any] = {
            "ok": True,
            "run_id": run_id,
            "status": final_status,
            "run_dir": str(run_dir),
            "run_workspace": run_workspace_str,
        }
        if issues:
            resp["issues"] = issues
        if policy_issues:
            resp["policy_issues"] = policy_issues
        return resp

    # Keep the execution worker non-daemonic so queued runs can finish
    # finalization and persist their observation/bundle artifacts before the
    # process exits.
    thread = threading.Thread(target=_execute_run, args=(run_id,), daemon=False)
    thread.start()

    resp: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "status": "queued",
        "run_dir": str(run_dir),
        "run_workspace": run_workspace_str,
    }
    if issues:
        resp["issues"] = issues
    if policy_issues:
        resp["policy_issues"] = policy_issues
    return resp


@mcp.tool()
def log_research_event(
    kind: Annotated[
        str,
        Field(
            description=(
                "Event kind. Canonical values: 'start' (a session/run begins) or "
                "'note' (any other event). Synonyms such as 'event', 'milestone', "
                "'update', or 'finding' are accepted and normalized to 'note'; any "
                "unrecognized value also falls back to 'note'."
            ),
            json_schema_extra={"enum": list(RESEARCH_EVENT_KINDS)},
        ),
    ],
    content: str,
    session_id: str | None = None,
    run_id: str | None = None,
    source: Annotated[
        str,
        Field(
            description=(
                "Event author: 'agent' (default) or 'user'. Synonyms such as "
                "'assistant'/'claude'/'codex' (→ agent) or 'human' (→ user) are "
                "accepted and normalized; unrecognized values fall back to 'agent'."
            ),
            json_schema_extra={"enum": list(RESEARCH_LOG_SOURCES)},
        ),
    ] = "agent",
    context: dict[str, Any] | None = None,
    tags: list[str] | str | None = None,
    source_client: str | None = None,
    client_session_id: str | None = None,
) -> dict[str, Any]:
    """Persist a lightweight research workflow event for later session/workflow analysis.

    `session_id` should be the canonical Brain Researcher session identifier for one
    continuous coding session. If the client only has a native thread/chat id, pass
    it via `client_session_id`; BR will derive a namespaced canonical `session_id`
    when `session_id` is omitted.
    """
    try:
        (
            normalized_session_id,
            normalized_client_session_id,
            normalized_source_client,
        ) = _resolve_research_session_identity(
            session_id,
            client_session_id=client_session_id,
            source_client=source_client,
        )
        normalized_kind = _normalize_research_event_kind(kind)
        normalized_source = _normalize_research_log_source(source)
        content_text = _first_text_value(content)
        if not content_text:
            raise ValueError("content is required")
    except Exception as exc:
        return {"ok": False, "error": "invalid_arguments", "message": str(exc)}

    safe_context = _record_dict(context)
    safe_tags = _coerce_csv_or_non_empty_str_list(tags)
    attached_trace_rows = _research_context_trace_rows(safe_context)
    attached_conversation_rows = _research_context_conversation_rows(safe_context)
    stored_context = _research_context_for_event_payload(
        safe_context,
        attached_trace_count=len(attached_trace_rows),
        attached_conversation_count=len(attached_conversation_rows),
    )

    try:
        record, run_dir, managed_run = _load_or_create_research_run(
            normalized_session_id,
            run_id=run_id,
        )
    except Exception as exc:
        return {"ok": False, "error": "run_init_failed", "message": str(exc)}

    if _research_session_is_closed(record, run_dir=run_dir):
        return {
            "ok": False,
            "error": "session_already_closed",
            "message": (
                f"session_id {normalized_session_id!r} already has a persisted "
                "snapshot; use a new session_id for additional logging"
            ),
            "run_id": record.run_id,
            "session_id": normalized_session_id,
        }

    now = _utc_iso()
    if managed_run:
        record.status = "running"
        record.finished_at = None
        if record.started_at is None:
            record.started_at = now
        _update_run_progress(
            record,
            stage="research_logging",
            message=f"Logged research {normalized_kind}",
            timestamp=now,
        )

    research_logging, event_id = _next_research_event_metadata(
        record,
        session_id=normalized_session_id,
        client_session_id=normalized_client_session_id,
        source_client=normalized_source_client,
        source=normalized_source,
        managed_run=managed_run,
        event_kind=normalized_kind,
        event_at=now,
    )
    _save_run(record, run_dir=run_dir)

    _record_research_session_run_id(
        normalized_session_id,
        record.run_id,
        updated_at=now,
    )

    event_payload = {
        "event_id": event_id,
        "kind": normalized_kind,
        "session_id": normalized_session_id,
        "client_session_id": normalized_client_session_id,
        "source_client": normalized_source_client,
        "run_id": record.run_id,
        "source": normalized_source,
        "content": content_text,
        "context": stored_context,
        "tags": safe_tags,
        "timestamp": now,
        "managed_run": bool(managed_run),
    }

    _append_jsonl_record(run_dir / _RESEARCH_EVENTS_FILENAME, event_payload)
    attached_conversation_count = _append_research_conversation_rows(
        run_dir,
        session_id=normalized_session_id,
        run_id=record.run_id,
        event_id=event_id,
        source_client=normalized_source_client,
        rows=attached_conversation_rows,
        fallback_timestamp=now,
    )
    _persist_research_logging_provenance(
        run_dir=run_dir,
        record=record,
        session_id=normalized_session_id,
        client_session_id=normalized_client_session_id,
        source_client=normalized_source_client,
        source=normalized_source,
        managed_run=managed_run,
        last_write_tool="log_research_event",
        last_event_kind=normalized_kind,
        request_payload={
            "session_id": normalized_session_id,
            "client_session_id": normalized_client_session_id,
            "source_client": normalized_source_client,
            "kind": normalized_kind,
            "source": normalized_source,
            "tags": safe_tags,
        },
        updated_at=now,
    )

    _emit_trace_event(
        _research_trace_logger(),
        run_dir,
        run_id=record.run_id,
        event_type=f"research.{normalized_kind}",
        payload=event_payload,
    )
    for trace_row in attached_trace_rows:
        _append_research_tool_trace_row(
            run_dir,
            session_id=normalized_session_id,
            client_session_id=normalized_client_session_id,
            source_client=normalized_source_client,
            run_id=record.run_id,
            event_type=str(trace_row["event_type"]),
            timestamp=_first_text_value(trace_row.get("timestamp")),
            payload=_record_dict(trace_row.get("payload")),
            attached_via_event_id=event_id,
        )
        _emit_trace_event(
            _research_trace_logger(),
            run_dir,
            run_id=record.run_id,
            event_type=str(trace_row["event_type"]),
            payload=_record_dict(trace_row.get("payload")),
        )

    response = {
        "ok": True,
        "run_id": record.run_id,
        "run_dir": str(run_dir),
        "session_id": normalized_session_id,
        "client_session_id": normalized_client_session_id,
        "source_client": normalized_source_client,
        "kind": normalized_kind,
        "managed_run": bool(managed_run),
        "status": record.status,
        "event": event_payload,
        "progress": research_logging,
        "files": {
            "research_events_jsonl": _RESEARCH_EVENTS_FILENAME,
            "trace_jsonl": "trace.jsonl",
            "session_transcript_jsonl": _SESSION_TRANSCRIPT_FILENAME,
            "conversation_log_jsonl": _RESEARCH_CONVERSATION_LOG_FILENAME,
            "tool_trace_jsonl": _RESEARCH_TOOL_TRACE_FILENAME,
        },
    }
    if attached_trace_rows:
        response["attached_trace_event_count"] = len(attached_trace_rows)
    if attached_conversation_count:
        response["attached_conversation_message_count"] = attached_conversation_count
    return response


@mcp.tool()
def write_session_snapshot(
    goal: str,
    done: list[str],
    open: list[str],
    next_command: str,
    session_id: str | None = None,
    run_id: str | None = None,
    source: Annotated[
        str,
        Field(
            description=(
                "Snapshot author: 'agent' (default) or 'user'. Synonyms such as "
                "'assistant'/'claude'/'codex' (→ agent) or 'human' (→ user) are "
                "accepted and normalized; unrecognized values fall back to 'agent'."
            ),
            json_schema_extra={"enum": list(RESEARCH_LOG_SOURCES)},
        ),
    ] = "agent",
    tags: list[str] | str | None = None,
    source_client: str | None = None,
    client_session_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a structured end-of-session snapshot for later resume/coaching workflows.

    Use one snapshot per continuous coding session. If the client only exposes a
    native thread/chat id, pass it via `client_session_id`; BR will derive a
    canonical `session_id` when `session_id` is omitted.
    """
    try:
        (
            normalized_session_id,
            normalized_client_session_id,
            normalized_source_client,
        ) = _resolve_research_session_identity(
            session_id,
            client_session_id=client_session_id,
            source_client=source_client,
        )
        normalized_source = _normalize_research_log_source(source)
        goal_text = _first_text_value(goal)
        if not goal_text:
            raise ValueError("goal is required")
        next_command_text = _first_text_value(next_command)
        if not next_command_text:
            raise ValueError("next_command is required")
    except Exception as exc:
        return {"ok": False, "error": "invalid_arguments", "message": str(exc)}

    safe_done = _coerce_non_empty_str_list(done)
    safe_open = _coerce_non_empty_str_list(open)
    safe_tags = _coerce_csv_or_non_empty_str_list(tags)
    safe_context = _record_dict(context)
    attached_trace_rows = _research_context_trace_rows(safe_context)
    attached_conversation_rows = _research_context_conversation_rows(safe_context)

    try:
        record, run_dir, managed_run = _load_or_create_research_run(
            normalized_session_id,
            run_id=run_id,
        )
    except Exception as exc:
        return {"ok": False, "error": "run_init_failed", "message": str(exc)}

    now = _utc_iso()
    existing_snapshot = _load_research_session_snapshot_payload(record, run_dir=run_dir)
    snapshot_payload = {
        "goal": goal_text,
        "done": safe_done,
        "open": safe_open,
        "next_command": next_command_text,
        "session_id": normalized_session_id,
        "client_session_id": normalized_client_session_id,
        "source_client": normalized_source_client,
        "run_id": record.run_id,
        "source": normalized_source,
        "tags": safe_tags,
        "updated_at": now,
    }

    if existing_snapshot:
        if _research_snapshot_matches(existing_snapshot, snapshot_payload):
            progress = _research_logging_progress(record)
            if not progress.get("snapshot_count"):
                progress["snapshot_count"] = 1
            progress.setdefault("snapshot_path", _SESSION_SNAPSHOT_FILENAME)
            merged_progress = dict(record.progress or {})
            merged_progress["research_logging"] = progress
            merged_progress["session_snapshot"] = existing_snapshot
            record.progress = merged_progress
            if managed_run:
                if record.started_at is None:
                    record.started_at = now
                record.status = "succeeded"
                if record.finished_at is None:
                    record.finished_at = now
                _update_run_progress(
                    record,
                    stage="completed",
                    message="Research session snapshot already up to date",
                    progress_pct=100.0,
                    timestamp=now,
                )
            _save_run(record, run_dir=run_dir)
            _persist_research_logging_provenance(
                run_dir=run_dir,
                record=record,
                session_id=normalized_session_id,
                client_session_id=normalized_client_session_id,
                source_client=normalized_source_client,
                source=normalized_source,
                managed_run=managed_run,
                last_write_tool="write_session_snapshot",
                last_event_kind="snapshot",
                request_payload={
                    "session_id": normalized_session_id,
                    "client_session_id": normalized_client_session_id,
                    "source_client": normalized_source_client,
                    "source": normalized_source,
                    "tags": safe_tags,
                    "has_snapshot": True,
                    "idempotent": True,
                },
                updated_at=now,
            )
            _persist_mcp_run_bundle(record.run_id, run_dir=run_dir)
            return {
                "ok": True,
                "run_id": record.run_id,
                "run_dir": str(run_dir),
                "session_id": normalized_session_id,
                "client_session_id": normalized_client_session_id,
                "source_client": normalized_source_client,
                "kind": "end",
                "managed_run": bool(managed_run),
                "status": record.status,
                "snapshot": existing_snapshot,
                "progress": progress,
                "idempotent": True,
                "files": {
                    "research_events_jsonl": _RESEARCH_EVENTS_FILENAME,
                    "session_snapshot_json": _SESSION_SNAPSHOT_FILENAME,
                    "trace_jsonl": "trace.jsonl",
                    "session_transcript_jsonl": _SESSION_TRANSCRIPT_FILENAME,
                    "conversation_log_jsonl": _RESEARCH_CONVERSATION_LOG_FILENAME,
                    "tool_trace_jsonl": _RESEARCH_TOOL_TRACE_FILENAME,
                },
            }
        return {
            "ok": False,
            "error": "session_already_closed",
            "message": (
                f"session_id {normalized_session_id!r} already has a persisted "
                "snapshot with different contents; use a new session_id"
            ),
            "run_id": record.run_id,
            "session_id": normalized_session_id,
            "snapshot": existing_snapshot,
        }

    if not _research_session_has_start(record, run_dir=run_dir):
        existing_progress = _research_logging_progress(record)
        if (
            managed_run
            and _research_logging_counter(existing_progress, "event_count") > 0
        ):
            return {
                "ok": False,
                "error": "session_not_started",
                "message": (
                    "write_session_snapshot cannot auto-start a session after "
                    "non-start research events already exist; log a start event first"
                ),
                "run_id": record.run_id,
                "session_id": normalized_session_id,
            }
        auto_start_content = "Auto-started research session on first snapshot write."
        if managed_run:
            if record.started_at is None:
                record.started_at = now
            record.status = "running"
            record.finished_at = None
            _update_run_progress(
                record,
                stage="research_logging",
                message="Auto-started research session on first snapshot write",
                timestamp=now,
            )
        _, start_event_id = _next_research_event_metadata(
            record,
            session_id=normalized_session_id,
            client_session_id=normalized_client_session_id,
            source_client=normalized_source_client,
            source=normalized_source,
            managed_run=managed_run,
            event_kind="start",
            event_at=now,
        )
        start_event_payload = {
            "event_id": start_event_id,
            "kind": "start",
            "session_id": normalized_session_id,
            "client_session_id": normalized_client_session_id,
            "source_client": normalized_source_client,
            "run_id": record.run_id,
            "source": normalized_source,
            "content": auto_start_content,
            "context": {},
            "tags": safe_tags,
            "timestamp": now,
            "managed_run": bool(managed_run),
        }
        _append_jsonl_record(run_dir / _RESEARCH_EVENTS_FILENAME, start_event_payload)
        _emit_trace_event(
            _research_trace_logger(),
            run_dir,
            run_id=record.run_id,
            event_type="research.start",
            payload=start_event_payload,
        )

    if managed_run:
        if record.started_at is None:
            record.started_at = now
        record.status = "succeeded"
        record.finished_at = now
        _update_run_progress(
            record,
            stage="completed",
            message="Research session snapshot written",
            progress_pct=100.0,
            timestamp=now,
        )

    research_logging, event_id = _next_research_event_metadata(
        record,
        session_id=normalized_session_id,
        client_session_id=normalized_client_session_id,
        source_client=normalized_source_client,
        source=normalized_source,
        managed_run=managed_run,
        event_kind="snapshot",
        event_at=now,
    )
    progress = dict(record.progress or {})
    progress["session_snapshot"] = snapshot_payload
    record.progress = progress
    _save_run(record, run_dir=run_dir)

    _record_research_session_run_id(
        normalized_session_id,
        record.run_id,
        updated_at=now,
    )

    _atomic_write_json(run_dir / _SESSION_SNAPSHOT_FILENAME, snapshot_payload)

    end_event_payload = {
        "event_id": event_id,
        "kind": "end",
        "event_type": "research.snapshot",
        "session_id": normalized_session_id,
        "client_session_id": normalized_client_session_id,
        "source_client": normalized_source_client,
        "run_id": record.run_id,
        "source": normalized_source,
        "tags": safe_tags,
        "timestamp": now,
        "managed_run": bool(managed_run),
        "snapshot": snapshot_payload,
    }
    _append_jsonl_record(run_dir / _RESEARCH_EVENTS_FILENAME, end_event_payload)
    attached_conversation_count = _append_research_conversation_rows(
        run_dir,
        session_id=normalized_session_id,
        run_id=record.run_id,
        event_id=event_id,
        source_client=normalized_source_client,
        rows=attached_conversation_rows,
        fallback_timestamp=now,
    )
    _persist_research_logging_provenance(
        run_dir=run_dir,
        record=record,
        session_id=normalized_session_id,
        client_session_id=normalized_client_session_id,
        source_client=normalized_source_client,
        source=normalized_source,
        managed_run=managed_run,
        last_write_tool="write_session_snapshot",
        last_event_kind="snapshot",
        request_payload={
            "session_id": normalized_session_id,
            "client_session_id": normalized_client_session_id,
            "source_client": normalized_source_client,
            "source": normalized_source,
            "tags": safe_tags,
            "has_snapshot": True,
            "attached_trace_event_count": len(attached_trace_rows),
            "attached_conversation_message_count": attached_conversation_count,
        },
        updated_at=now,
    )

    _emit_trace_event(
        _research_trace_logger(),
        run_dir,
        run_id=record.run_id,
        event_type="research.snapshot",
        payload={
            "event_id": event_id,
            "session_id": normalized_session_id,
            "client_session_id": normalized_client_session_id,
            "source_client": normalized_source_client,
            "run_id": record.run_id,
            "source": normalized_source,
            "tags": safe_tags,
            "managed_run": bool(managed_run),
            "snapshot": snapshot_payload,
        },
    )
    for trace_row in attached_trace_rows:
        _append_research_tool_trace_row(
            run_dir,
            session_id=normalized_session_id,
            client_session_id=normalized_client_session_id,
            source_client=normalized_source_client,
            run_id=record.run_id,
            event_type=str(trace_row["event_type"]),
            timestamp=_first_text_value(trace_row.get("timestamp")),
            payload=_record_dict(trace_row.get("payload")),
            attached_via_event_id=event_id,
        )
        _emit_trace_event(
            _research_trace_logger(),
            run_dir,
            run_id=record.run_id,
            event_type=str(trace_row["event_type"]),
            payload=_record_dict(trace_row.get("payload")),
        )
    _persist_mcp_run_bundle(record.run_id, run_dir=run_dir)
    response = {
        "ok": True,
        "run_id": record.run_id,
        "run_dir": str(run_dir),
        "session_id": normalized_session_id,
        "client_session_id": normalized_client_session_id,
        "source_client": normalized_source_client,
        "kind": "end",
        "managed_run": bool(managed_run),
        "status": record.status,
        "snapshot": snapshot_payload,
        "progress": research_logging,
        "files": {
            "research_events_jsonl": _RESEARCH_EVENTS_FILENAME,
            "session_snapshot_json": _SESSION_SNAPSHOT_FILENAME,
            "trace_jsonl": "trace.jsonl",
            "session_transcript_jsonl": _SESSION_TRANSCRIPT_FILENAME,
            "conversation_log_jsonl": _RESEARCH_CONVERSATION_LOG_FILENAME,
            "tool_trace_jsonl": _RESEARCH_TOOL_TRACE_FILENAME,
        },
    }
    if attached_trace_rows:
        response["attached_trace_event_count"] = len(attached_trace_rows)
    if attached_conversation_count:
        response["attached_conversation_message_count"] = attached_conversation_count
    return response


@mcp.tool()
def research_session_digest(
    run_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Return a structured digest for one research-logging session."""
    normalized_run_id = _first_text_value(run_id)
    normalized_session_id = _first_text_value(session_id)
    if not normalized_run_id and not normalized_session_id:
        return {
            "ok": False,
            "error": "missing_selector",
            "message": "Provide run_id or session_id.",
        }

    try:
        if normalized_run_id:
            record, run_dir = _load_run_with_dir(normalized_run_id)
            provenance = _load_run_provenance(run_dir)
        else:
            digests = _collect_research_session_digests(normalized_session_id or "")
            if not digests:
                return {
                    "ok": False,
                    "error": "research_session_not_found",
                    "message": f"No research session found for session_id={normalized_session_id!r}.",
                }
            digest = _merge_research_session_digests(digests)
            return {
                "ok": True,
                "run_id": digest.get("run_id"),
                "run_dir": digest.get("run_dir"),
                "session_id": digest.get("session_id"),
                "digest": digest,
            }

        digest = _build_research_session_digest(record, run_dir, provenance)
        if not isinstance(digest, dict):
            return {
                "ok": False,
                "error": "research_logging_not_found",
                "message": "Run does not contain research logging artifacts.",
            }
        if normalized_session_id and digest.get("session_id") != normalized_session_id:
            return {
                "ok": False,
                "error": "session_id_mismatch",
                "message": (
                    f"run_id {record.run_id} is associated with session_id="
                    f"{digest.get('session_id')!r}, not {normalized_session_id!r}."
                ),
            }
        return {
            "ok": True,
            "run_id": record.run_id,
            "run_dir": str(run_dir),
            "session_id": digest.get("session_id"),
            "digest": digest,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def research_log_summary(
    top_k: int = 10,
    since_days: int | None = None,
) -> dict[str, Any]:
    """Summarize persisted research-logging sessions across runs."""
    try:
        top_k = max(1, min(int(top_k), 100))
        if since_days is not None:
            since_days = max(1, min(int(since_days), 3650))
        cutoff = None
        if since_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=since_days)

        run_rows: list[dict[str, Any]] = []
        grouped_rows: dict[str, list[dict[str, Any]]] = {}
        status_counts: dict[str, int] = {}
        route_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        source_client_counts: dict[str, int] = {}
        tag_counts: dict[str, int] = {}
        open_item_counts: dict[str, int] = {}
        event_counts = {"total": 0, "start": 0, "note": 0, "auto": 0, "end": 0}
        server_signal_totals = {
            "trace_event_total": 0,
            "research_trace_events": 0,
            "non_research_trace_events": 0,
            "tool_call_started": 0,
            "tool_call_finished": 0,
            "tool_call_non_success": 0,
            "retry_like_events": 0,
            "warning_events": 0,
            "error_like_events": 0,
            "failed_steps": 0,
            "succeeded_steps": 0,
        }
        sessions_with_snapshot = 0
        managed_sessions = 0
        synthetic_sessions = 0
        attached_sessions = 0
        sessions_with_auto_events = 0
        sessions_with_non_research_trace_events = 0

        for record, run_dir, provenance in _iter_run_records_for_summary():
            digest = _build_research_session_digest(record, run_dir, provenance)
            if not isinstance(digest, dict):
                continue
            marker = _first_text_value(
                digest.get("last_event_at"), digest.get("created_at")
            )
            marker_dt = _parse_iso(marker)
            if cutoff is not None and marker_dt is not None and marker_dt < cutoff:
                continue

            run_rows.append(digest)
            session_key = _first_text_value(digest.get("session_id")) or (
                f"run:{_first_text_value(digest.get('run_id'))}"
            )
            grouped_rows.setdefault(session_key, []).append(digest)

        session_rows = [
            _merge_research_session_digests(rows)
            for rows in grouped_rows.values()
            if rows
        ]
        session_rows.sort(key=_research_session_digest_marker, reverse=True)
        duplicate_session_ids = sum(
            1 for rows in grouped_rows.values() if len(rows) > 1
        )
        duplicate_run_rows = sum(
            len(rows) for rows in grouped_rows.values() if len(rows) > 1
        )

        for digest in session_rows:
            counts = _record_dict(digest.get("event_counts"))
            event_counts["total"] += int(counts.get("total") or 0)
            event_counts["start"] += int(counts.get("start") or 0)
            event_counts["note"] += int(counts.get("note") or 0)
            event_counts["auto"] += int(counts.get("auto") or 0)
            event_counts["end"] += int(counts.get("end") or 0)

            status = _first_text_value(digest.get("status")) or "unknown"
            route = _first_text_value(digest.get("route")) or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            route_counts[route] = route_counts.get(route, 0) + 1

            if digest.get("has_snapshot"):
                sessions_with_snapshot += 1
            if digest.get("managed_run") is True:
                managed_sessions += 1
            if _research_session_logging_mode(digest) == "synthetic":
                synthetic_sessions += 1
            else:
                attached_sessions += 1
            source_client = _first_text_value(digest.get("source_client"))
            if source_client:
                source_client_counts[source_client] = (
                    source_client_counts.get(source_client, 0) + 1
                )
            if int(counts.get("auto") or 0) > 0:
                sessions_with_auto_events += 1

            for source in _coerce_non_empty_str_list(digest.get("event_sources")):
                source_counts[source] = source_counts.get(source, 0) + 1
            for tag in _coerce_non_empty_str_list(digest.get("event_tags")):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            for item in _coerce_non_empty_str_list(digest.get("open_items")):
                open_item_counts[item] = open_item_counts.get(item, 0) + 1
            signals = _record_dict(digest.get("server_derived_signals"))
            if int(signals.get("non_research_trace_events") or 0) > 0:
                sessions_with_non_research_trace_events += 1
            for key, value in signals.items():
                try:
                    server_signal_totals[key] = server_signal_totals.get(key, 0) + int(
                        value or 0
                    )
                except Exception:
                    continue

        total_sessions = len(session_rows)
        closure_rate = (
            round(sessions_with_snapshot / total_sessions, 4)
            if total_sessions > 0
            else 0.0
        )

        return {
            "ok": True,
            "top_k": top_k,
            "since_days": since_days,
            "total_sessions": total_sessions,
            "total_run_rows": len(run_rows),
            "duplicate_session_ids": duplicate_session_ids,
            "duplicate_run_rows": duplicate_run_rows,
            "sessions_with_snapshot": sessions_with_snapshot,
            "managed_sessions": managed_sessions,
            "synthetic_sessions": synthetic_sessions,
            "attached_sessions": attached_sessions,
            "sessions_with_auto_events": sessions_with_auto_events,
            "sessions_with_non_research_trace_events": (
                sessions_with_non_research_trace_events
            ),
            "closure_rate": closure_rate,
            "roots_scanned": [str(root) for root in _run_roots_for_read()],
            "event_counts": event_counts,
            "status_counts": [
                {"status": key, "count": value}
                for key, value in sorted(
                    status_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "route_counts": [
                {"route": key, "count": value}
                for key, value in sorted(
                    route_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "source_counts": [
                {"source": key, "count": value}
                for key, value in sorted(
                    source_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "source_client_counts": [
                {"source_client": key, "count": value}
                for key, value in sorted(
                    source_client_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "server_signal_totals": server_signal_totals,
            "top_tags": [
                {"tag": key, "count": value}
                for key, value in sorted(
                    tag_counts.items(), key=lambda item: (-item[1], item[0])
                )[:top_k]
            ],
            "frequent_open_items": [
                {"open_item": key, "count": value}
                for key, value in sorted(
                    open_item_counts.items(), key=lambda item: (-item[1], item[0])
                )[:top_k]
            ],
            "recent_sessions": [
                {
                    "run_id": row.get("run_id"),
                    "run_ids": row.get("run_ids"),
                    "session_id": row.get("session_id"),
                    "client_session_id": row.get("client_session_id"),
                    "source_client": row.get("source_client"),
                    "status": row.get("status"),
                    "route": row.get("route"),
                    "logging_mode": row.get("logging_mode"),
                    "managed_run": bool(row.get("managed_run")),
                    "has_snapshot": bool(row.get("has_snapshot")),
                    "event_counts": row.get("event_counts"),
                    "server_derived_signals": row.get("server_derived_signals"),
                    "done_count": int(row.get("done_count") or 0),
                    "open_count": int(row.get("open_count") or 0),
                    "last_event_at": row.get("last_event_at"),
                }
                for row in session_rows[:top_k]
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _research_session_digest_from_selector(
    *,
    run_id: str | None = None,
    session_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    normalized_run_id = _first_text_value(run_id)
    normalized_session_id = _first_text_value(session_id)
    if not normalized_run_id and not normalized_session_id:
        return None, {
            "ok": False,
            "error": "missing_selector",
            "message": "Provide run_id or session_id.",
        }
    if normalized_run_id:
        try:
            record, run_dir = _load_run_with_dir(normalized_run_id)
            digest = _build_research_session_digest(
                record,
                run_dir,
                _load_run_provenance(run_dir),
            )
        except Exception as exc:
            return None, {"ok": False, "error": str(exc)}
        if not isinstance(digest, dict):
            return None, {
                "ok": False,
                "error": "research_logging_not_found",
                "message": "Run does not contain research logging artifacts.",
            }
        if normalized_session_id and digest.get("session_id") != normalized_session_id:
            return None, {
                "ok": False,
                "error": "session_id_mismatch",
                "message": (
                    f"run_id {normalized_run_id} is associated with session_id="
                    f"{digest.get('session_id')!r}, not {normalized_session_id!r}."
                ),
            }
        return digest, None

    digests = _collect_research_session_digests(normalized_session_id or "")
    if not digests:
        return None, {
            "ok": False,
            "error": "research_session_not_found",
            "message": (
                f"No research session found for session_id="
                f"{normalized_session_id!r}."
            ),
        }
    return _merge_research_session_digests(digests), None


def _research_session_rows_for_lessons(
    *,
    since_days: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    cutoff = None
    if since_days is not None:
        since_days = max(1, min(int(since_days), 3650))
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for record, run_dir, provenance in _iter_run_records_for_summary():
        digest = _build_research_session_digest(record, run_dir, provenance)
        if not isinstance(digest, dict):
            continue
        marker_dt = _parse_iso(
            _first_text_value(digest.get("last_event_at"), digest.get("created_at"))
        )
        if cutoff is not None and marker_dt is not None and marker_dt < cutoff:
            continue
        session_key = _first_text_value(digest.get("session_id")) or (
            f"run:{_first_text_value(digest.get('run_id'))}"
        )
        grouped_rows.setdefault(session_key, []).append(digest)

    rows = [_merge_research_session_digests(items) for items in grouped_rows.values()]
    rows.sort(key=_research_session_digest_marker, reverse=True)
    return rows[: max(1, min(int(limit), 1000))]


@mcp.tool()
def session_risk_classify(
    run_id: str | None = None,
    session_id: str | None = None,
    digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify handoff risks and hygiene issues for one research session."""
    if isinstance(digest, dict) and digest:
        selected = digest
        error = None
    else:
        selected, error = _research_session_digest_from_selector(
            run_id=run_id,
            session_id=session_id,
        )
    if error is not None:
        return error
    try:
        classification = classify_session(selected or {})
        return {
            "ok": True,
            "session_id": classification.get("session_id"),
            "run_id": classification.get("run_id"),
            "classification": classification,
            "risk_labels": list(OPEN_RISK_LABELS),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def session_lesson_extract(
    run_id: str | None = None,
    session_id: str | None = None,
    digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract conservative candidate lessons from one research session."""
    if isinstance(digest, dict) and digest:
        selected = digest
        error = None
    else:
        selected, error = _research_session_digest_from_selector(
            run_id=run_id,
            session_id=session_id,
        )
    if error is not None:
        return error
    try:
        payload = extract_session_lessons(selected or {})
        return {"ok": True, **payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def session_open_risks_query(
    risk_label: str | None = None,
    risk_code: str | None = None,
    surface: str | None = None,
    since_days: int | None = 60,
    limit: int = 50,
) -> dict[str, Any]:
    """Query repeated open-risk labels and session hygiene issues."""
    try:
        normalized_label = _first_text_value(risk_label)
        normalized_code = _first_text_value(risk_code)
        normalized_surface = _first_text_value(surface)
        rows: list[dict[str, Any]] = []
        for digest in _research_session_rows_for_lessons(
            since_days=since_days,
            limit=max(limit * 5, limit),
        ):
            classification = classify_session(digest)
            surfaces = set(
                _coerce_non_empty_str_list(classification.get("task_surfaces"))
            )
            if normalized_surface and normalized_surface not in surfaces:
                continue
            for risk in classification.get("open_risks") or []:
                if not isinstance(risk, dict):
                    continue
                if normalized_label and risk.get("label") != normalized_label:
                    continue
                rows.append(
                    {
                        "kind": "open_risk",
                        "session_id": classification.get("session_id"),
                        "run_id": classification.get("run_id"),
                        "task_surfaces": list(surfaces),
                        "risk_label": risk.get("label"),
                        "text": risk.get("text"),
                    }
                )
            for issue in classification.get("hygiene_issues") or []:
                if not isinstance(issue, dict):
                    continue
                if normalized_code and issue.get("code") != normalized_code:
                    continue
                rows.append(
                    {
                        "kind": "hygiene_issue",
                        "session_id": classification.get("session_id"),
                        "run_id": classification.get("run_id"),
                        "task_surfaces": list(surfaces),
                        "risk_code": issue.get("code"),
                        "severity": issue.get("severity"),
                        "message": issue.get("message"),
                    }
                )
            if len(rows) >= max(1, min(int(limit), 500)):
                break
        return {
            "ok": True,
            "since_days": since_days,
            "risk_label": normalized_label,
            "risk_code": normalized_code,
            "surface": normalized_surface,
            "count": len(rows),
            "results": rows[: max(1, min(int(limit), 500))],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def session_policy_cards_generate(
    since_days: int | None = 60,
    limit: int = 200,
) -> dict[str, Any]:
    """Generate candidate policy cards from repeated session lessons."""
    try:
        lesson_payloads = [
            extract_session_lessons(digest)
            for digest in _research_session_rows_for_lessons(
                since_days=since_days,
                limit=limit,
            )
        ]
        cards = build_session_policy_cards(lesson_payloads)
        return {
            "ok": True,
            "since_days": since_days,
            "sessions_considered": len(lesson_payloads),
            "policy_cards": cards,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def session_learning_report_generate(
    since_days: int | None = 60,
    limit: int = 500,
    top_k: int = 10,
    min_support: int = 2,
) -> dict[str, Any]:
    """Generate a periodic agent-learning report from research sessions."""
    try:
        limit = max(1, min(int(limit), 1000))
        top_k = max(1, min(int(top_k), 50))
        min_support = max(1, min(int(min_support), 100))
        digests = _research_session_rows_for_lessons(
            since_days=since_days,
            limit=limit,
        )
        report = build_session_learning_report(
            digests,
            top_k=top_k,
            min_support=min_support,
        )
        return {
            "ok": True,
            "since_days": since_days,
            "limit": limit,
            "top_k": top_k,
            "min_support": min_support,
            **report,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _post_snapshot_activity_for_digest(digest: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = _record_dict(digest.get("snapshot"))
    snapshot_at_text = _first_text_value(snapshot.get("updated_at"))
    snapshot_at = _parse_iso(snapshot_at_text)
    run_dir_text = _first_text_value(digest.get("run_dir"))
    if snapshot_at is None or not run_dir_text:
        return None

    run_dir = Path(run_dir_text)
    tool_events: list[dict[str, Any]] = []
    auto_events: list[dict[str, Any]] = []
    tool_counts: dict[str, int] = {}
    review_tools: list[str] = []
    artifact_tools: list[str] = []
    invariant_terms: list[str] = []
    error_count = 0
    latest_post_at: str | None = None

    def remember_timestamp(timestamp: str | None) -> None:
        nonlocal latest_post_at
        if not timestamp:
            return
        if latest_post_at is None or timestamp > latest_post_at:
            latest_post_at = timestamp

    for row in _load_jsonl_dicts(run_dir / _RESEARCH_TOOL_TRACE_FILENAME):
        timestamp = _first_text_value(row.get("timestamp"))
        timestamp_dt = _parse_iso(timestamp)
        if timestamp_dt is None or timestamp_dt <= snapshot_at:
            continue
        tool_name = _first_text_value(row.get("tool_name")) or "unknown"
        event_type = _first_text_value(row.get("event_type")) or "unknown"
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        if tool_name in _SESSION_SIGNAL_REVIEW_TOOLS and tool_name not in review_tools:
            review_tools.append(tool_name)
        if (
            tool_name in _SESSION_SIGNAL_ARTIFACT_TOOLS
            and tool_name not in artifact_tools
        ):
            artifact_tools.append(tool_name)
        if _first_text_value(row.get("error")):
            error_count += 1
        serialized = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        for match in _SESSION_TRACE_INVARIANT_RE.finditer(serialized):
            term = match.group(0)
            if term not in invariant_terms:
                invariant_terms.append(term)
        tool_events.append(
            {
                "timestamp": timestamp,
                "event_type": event_type,
                "tool_name": tool_name,
                "has_error": bool(_first_text_value(row.get("error"))),
            }
        )
        remember_timestamp(timestamp)

    for row in _load_jsonl_dicts(run_dir / _RESEARCH_EVENTS_FILENAME):
        timestamp = _first_text_value(row.get("timestamp"))
        timestamp_dt = _parse_iso(timestamp)
        if timestamp_dt is None or timestamp_dt <= snapshot_at:
            continue
        event_type = _first_text_value(row.get("event_type"), row.get("kind"))
        if not str(event_type or "").startswith("research.auto"):
            continue
        details = _record_dict(row.get("details"))
        tool_name = _first_text_value(row.get("tool_name"), details.get("tool_name"))
        subtype = _first_text_value(row.get("subtype"), details.get("subtype"))
        if "error" in str(event_type or "") or "error" in str(subtype or ""):
            error_count += 1
        auto_events.append(
            {
                "timestamp": timestamp,
                "event_type": event_type,
                "tool_name": tool_name,
                "subtype": subtype,
            }
        )
        remember_timestamp(timestamp)

    event_count = len(tool_events) + len(auto_events)
    if event_count == 0:
        return None
    open_items = _coerce_non_empty_str_list(digest.get("open_items"))
    return {
        "session_id": digest.get("session_id"),
        "run_id": digest.get("run_id"),
        "snapshot_at": snapshot_at_text,
        "latest_post_snapshot_at": latest_post_at,
        "snapshot_open_empty": not bool(open_items),
        "open_count": len(open_items),
        "event_count": event_count,
        "tool_trace_event_count": len(tool_events),
        "auto_event_count": len(auto_events),
        "tool_name_counts": [
            {"tool_name": key, "count": value}
            for key, value in sorted(
                tool_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "review_tool_names": review_tools,
        "artifact_inspection_tool_names": artifact_tools,
        "trace_only_invariant_terms": invariant_terms,
        "error_count": error_count,
        "task_surfaces": classify_session(digest).get("task_surfaces", []),
    }


@mcp.tool()
def session_signal_report_generate(
    since_days: int | None = 60,
    limit: int = 500,
    top_k: int = 10,
    min_support: int = 2,
) -> dict[str, Any]:
    """Generate read-only session signals for silent-fail and loop closure mining."""
    try:
        limit = max(1, min(int(limit), 1000))
        top_k = max(1, min(int(top_k), 50))
        min_support = max(1, min(int(min_support), 100))
        digests = _research_session_rows_for_lessons(
            since_days=since_days,
            limit=limit,
        )
        post_snapshot_activity = [
            row
            for digest in digests
            if (row := _post_snapshot_activity_for_digest(digest)) is not None
        ]
        report = build_session_signal_report(
            digests,
            post_snapshot_activity=post_snapshot_activity,
            top_k=top_k,
            min_support=min_support,
        )
        return {
            "ok": True,
            "since_days": since_days,
            "limit": limit,
            "top_k": top_k,
            "min_support": min_support,
            **report,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _write_session_digests_to_kg(digests: list[dict[str, Any]]) -> dict[str, Any]:
    from brain_researcher.services.br_kg.db.bootstrap import get_db
    from brain_researcher.services.br_kg.db.schema import setup_schema

    db = get_db(preload_cache=False)
    setup_schema(db)
    return load_session_digests(db, digests)


@mcp.tool()
def session_backfill_to_kg(
    run_id: str | None = None,
    session_id: str | None = None,
    since_days: int | None = None,
    limit: int = 100,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build or write KG rows for research sessions.

    With dry_run=True, returns normalized AgentSession, TaskSurface,
    ValidationEvidence, OpenRisk, Outcome, Lesson, and NextAction rows plus
    relationship rows. With dry_run=False, applies the rows to the configured
    Neo4j-backed BR-KG after setting up schema constraints/indexes.
    """
    try:
        if _first_text_value(run_id) or _first_text_value(session_id):
            digest, error = _research_session_digest_from_selector(
                run_id=run_id,
                session_id=session_id,
            )
            if error is not None:
                return error
            digests = [digest or {}]
        else:
            digests = _research_session_rows_for_lessons(
                since_days=since_days,
                limit=limit,
            )
        graph = build_session_snapshot_graph_payload(digests)
        endpoint_errors = validate_session_graph_payload(graph)
        if endpoint_errors:
            return {
                "ok": False,
                "error": "invalid_session_graph_payload",
                "endpoint_errors": endpoint_errors,
                "dry_run": bool(dry_run),
            }
        if not dry_run:
            result = _write_session_digests_to_kg(digests)
            result.update(
                {
                    "dry_run": False,
                    "kg_write_supported": True,
                    "sessions_considered": len(digests),
                }
            )
            return result
        return {
            "ok": True,
            "dry_run": True,
            "kg_write_supported": True,
            "sessions_considered": len(digests),
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "schema": {
                "node_labels": list(SESSION_KG_NODE_LABELS),
                "relationship_types": list(SESSION_KG_RELATIONSHIP_TYPES),
            },
            "query_examples": list(SESSION_KG_QUERY_EXAMPLES),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _strip_key_from_payload(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _strip_key_from_payload(item_value, key)
            for item_key, item_value in value.items()
            if item_key != key
        }
    if isinstance(value, list):
        return [_strip_key_from_payload(item, key) for item in value]
    return value


_MEMORY_RESPONSE_TRUNCATION_MARKER = "...[truncated]"
_MEMORY_SEARCH_DEFAULT_LIMIT = 5
_MEMORY_SEARCH_TEXT_LIMIT = 1600


def _truncate_memory_response_text(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        keep_chars = max(0, max_chars - len(_MEMORY_RESPONSE_TRUNCATION_MARKER))
        return value[:keep_chars] + _MEMORY_RESPONSE_TRUNCATION_MARKER
    if isinstance(value, dict):
        return {
            key: _truncate_memory_response_text(item, max_chars=max_chars)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _truncate_memory_response_text(item, max_chars=max_chars) for item in value
        ]
    return value


def _memory_response_without_embeddings(
    response: dict[str, Any],
    *,
    include_embedding_vector: bool,
) -> dict[str, Any]:
    payload = dict(response)
    if include_embedding_vector:
        return payload
    return _strip_key_from_payload(payload, "embedding_vector")


def _slim_memory_search_response(
    response: dict[str, Any],
    *,
    include_full_cards: bool,
    include_embedding_vector: bool,
    max_card_text_chars: int,
) -> dict[str, Any]:
    payload = _memory_response_without_embeddings(
        response,
        include_embedding_vector=include_embedding_vector,
    )
    if include_full_cards:
        return payload
    text_limit = max(1, min(int(max_card_text_chars), 20000))
    if isinstance(payload.get("cards"), list):
        payload["cards"] = [
            _truncate_memory_response_text(card, max_chars=text_limit)
            for card in payload["cards"]
        ]
    if isinstance(payload.get("hits"), list):
        slim_hits: list[Any] = []
        for hit in payload["hits"]:
            if not isinstance(hit, dict):
                slim_hits.append(hit)
                continue
            slim_hit = dict(hit)
            if isinstance(slim_hit.get("record"), dict):
                slim_hit["record"] = _truncate_memory_response_text(
                    slim_hit["record"],
                    max_chars=text_limit,
                )
            slim_hits.append(slim_hit)
        payload["hits"] = slim_hits
    payload["cards_truncated"] = True
    payload["truncation_marker"] = _MEMORY_RESPONSE_TRUNCATION_MARKER
    payload["max_card_text_chars"] = text_limit
    return payload


# ---------------------------------------------------------------------------
# Derived-memory tools (memory_write / memory_search / memory_get)
# Extracted to mcp/routers/memory.py. Importing it registers those tools on
# the shared FastMCP instance (import side effect).
# ---------------------------------------------------------------------------
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    memory as _memory_router,
)


@mcp.tool()
def run_get(run_id: str) -> dict[str, Any]:
    """Get run status and step records."""
    try:
        record, run_dir = _load_run_with_dir(run_id)
        record, proxied = _maybe_sync_delegated_run_record(run_id, record, run_dir)
        if proxied is not None and proxied.get("ok") is not True:
            return proxied
    except Exception as exc:
        proxied = _proxy_agent_run_status(run_id)
        if proxied is not None:
            if proxied.get("ok") is True and isinstance(proxied.get("run"), dict):
                proxied["progress"] = _run_progress_snapshot(proxied["run"])
            return proxied
        return {"ok": False, "error": f"run not found: {exc}"}
    run_payload = asdict(record)
    response = {
        "ok": True,
        "run_id": run_payload.get("run_id") or run_id,
        "status": run_payload.get("status"),
        "done": str(run_payload.get("status") or "") in _MCP_RUN_TERMINAL_STATUSES,
        "run": run_payload,
        "run_dir": str(run_dir),
        "progress": _run_progress_snapshot(run_payload),
    }
    return _augment_run_get_with_specialized_payload(response, run_dir=run_dir)


def _load_bundle_and_scorecard(
    run_id: str,
    *,
    profile_id: str = DEFAULT_LOOP_PROFILE_ID,
) -> tuple[dict[str, Any], dict[str, Any], list[str], Path]:
    record, run_dir = _load_run_with_dir(run_id)
    record_dict = asdict(record)
    bundle_payload, bundle_warnings = build_run_bundle_payload(
        run_id,
        record=record_dict,
        run_dir=run_dir,
    )
    metrics_resp = run_metrics(run_id)
    warnings = list(bundle_warnings)
    metrics = {}
    if metrics_resp.get("ok") is True and isinstance(metrics_resp.get("metrics"), dict):
        metrics = metrics_resp["metrics"]
    else:
        warnings.append("run_metrics unavailable for scorecard generation")
    scorecard = build_run_scorecard(
        run_id,
        profile_id=profile_id,
        record=record_dict,
        run_dir=run_dir,
        metrics=metrics,
        bundle_payload=bundle_payload,
        bundle_warnings=warnings,
    )
    return bundle_payload, scorecard, warnings, run_dir


_NULL_SECTION_SENTINEL = object()


def _drop_all_null_sections(value: Any, *, path: str = "$") -> tuple[Any, list[str]]:
    if value is None:
        return _NULL_SECTION_SENTINEL, []
    if isinstance(value, dict):
        omitted: list[str] = []
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            child_path = f"{path}.{key}"
            child, child_omitted = _drop_all_null_sections(item, path=child_path)
            omitted.extend(child_omitted)
            if child is _NULL_SECTION_SENTINEL:
                if isinstance(item, dict | list):
                    omitted.append(child_path)
                continue
            cleaned[key] = child
        if not cleaned:
            return _NULL_SECTION_SENTINEL, omitted
        return cleaned, omitted
    if isinstance(value, list):
        omitted: list[str] = []
        cleaned_items: list[Any] = []
        for index, item in enumerate(value):
            child, child_omitted = _drop_all_null_sections(
                item,
                path=f"{path}[{index}]",
            )
            omitted.extend(child_omitted)
            if child is _NULL_SECTION_SENTINEL:
                if isinstance(item, dict | list):
                    omitted.append(f"{path}[{index}]")
                continue
            cleaned_items.append(child)
        if not cleaned_items:
            return _NULL_SECTION_SENTINEL, omitted
        return cleaned_items, omitted
    return value, []


def _slim_run_bundle_response(
    response: dict[str, Any],
    *,
    verbose: bool,
) -> dict[str, Any]:
    payload = dict(response)
    payload["verbose"] = bool(verbose)
    if verbose:
        return payload
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        return payload
    slim_bundle, omitted = _drop_all_null_sections(bundle)
    payload["bundle"] = {} if slim_bundle is _NULL_SECTION_SENTINEL else slim_bundle
    if omitted:
        payload["omitted_null_sections"] = sorted(dict.fromkeys(omitted))
    return payload


@mcp.tool()
def run_bundle_get(run_id: str, verbose: bool = False) -> dict[str, Any]:
    """Return a normalized observation bundle for a persisted run."""
    try:
        run_dir = _find_run_dir(run_id)
        marker = _load_delegated_execution_marker(run_dir)
        if isinstance(marker, dict) and str(marker.get("backend") or "") == "agent":
            proxied = _proxy_agent_run_payload(run_id, suffix="/bundle")
            if proxied is not None:
                return _slim_run_bundle_response(proxied, verbose=bool(verbose))
        bundle_payload, _, warnings, run_dir = _load_bundle_and_scorecard(run_id)
    except Exception as exc:
        proxied = _proxy_agent_run_payload(run_id, suffix="/bundle")
        if proxied is not None:
            return _slim_run_bundle_response(proxied, verbose=bool(verbose))
        return {"ok": False, "error": f"run not found: {exc}"}
    return _slim_run_bundle_response(
        {
            "ok": True,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "bundle": bundle_payload,
            "warnings": warnings,
        },
        verbose=bool(verbose),
    )


@mcp.tool()
def run_scorecard(
    run_id: str, profile_id: str = DEFAULT_LOOP_PROFILE_ID
) -> dict[str, Any]:
    """Return a normalized scorecard for a persisted run."""
    try:
        _ = get_loop_profile(profile_id)
        run_dir = _find_run_dir(run_id)
        marker = _load_delegated_execution_marker(run_dir)
        if isinstance(marker, dict) and str(marker.get("backend") or "") == "agent":
            proxied = _proxy_agent_run_payload(
                run_id, suffix=f"/scorecard?profile_id={profile_id}"
            )
            if proxied is not None:
                return proxied
        _, scorecard, warnings, run_dir = _load_bundle_and_scorecard(
            run_id, profile_id=profile_id
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        proxied = _proxy_agent_run_payload(
            run_id, suffix=f"/scorecard?profile_id={profile_id}"
        )
        if proxied is not None:
            return proxied
        return {"ok": False, "error": f"run not found: {exc}"}
    return {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "profile_id": profile_id,
        "scorecard": scorecard,
        "warnings": warnings,
    }


@mcp.tool()
def run_compare(
    baseline_run_id: str,
    candidate_run_id: str,
    profile_id: str = DEFAULT_LOOP_PROFILE_ID,
    metric_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Compare two runs using the normalized MCP scorecard profile."""
    try:
        _ = get_loop_profile(profile_id)
        _, baseline_scorecard, baseline_warnings, _ = _load_bundle_and_scorecard(
            baseline_run_id, profile_id=profile_id
        )
        _, candidate_scorecard, candidate_warnings, _ = _load_bundle_and_scorecard(
            candidate_run_id, profile_id=profile_id
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"run not found: {exc}"}

    comparison = compare_run_scorecards(
        baseline_scorecard,
        candidate_scorecard,
        metric_keys=metric_keys,
    )
    warnings = []
    warnings.extend(baseline_warnings)
    warnings.extend(candidate_warnings)
    warnings.extend(comparison.get("warnings") or [])
    return {
        "ok": True,
        "profile_id": profile_id,
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_run_id,
        "metric_keys": list(metric_keys or []),
        "decision_hint": comparison.get("decision_hint"),
        "comparison": comparison,
        "baseline_scorecard": baseline_scorecard,
        "candidate_scorecard": candidate_scorecard,
        "warnings": sorted({str(w) for w in warnings if str(w).strip()}),
    }


@mcp.tool()
def generate_research_trajectory_and_insights(
    run_id: str | None = None,
    candidate_id: str | None = None,
    agent_log_paths: list[str] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Summarize one run/candidate trajectory and persist the result as BR artifacts."""
    try:
        return build_research_trajectory_summary(
            run_id=run_id,
            candidate_id=candidate_id,
            agent_log_paths=agent_log_paths,
            persist=bool(persist),
            run_root=_runstore.RUN_ROOT,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def generate_bug_digest(
    run_id: str | None = None,
    candidate_id: str | None = None,
    bug_query: str | None = None,
    agent_log_paths: list[str] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Summarize the dominant bug/root-cause state for one run/candidate anchor."""
    try:
        return build_bug_digest_summary(
            run_id=run_id,
            candidate_id=candidate_id,
            bug_query=bug_query,
            agent_log_paths=agent_log_paths,
            persist=bool(persist),
            run_root=_runstore.RUN_ROOT,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def generate_repo_repair_context(
    top_n: int = 8,
    persist: bool = True,
) -> dict[str, Any]:
    """Build an agent-readable repo repair context artifact from autoresearch state."""
    try:
        return build_repo_repair_context(
            top_n=max(1, min(int(top_n), 50)),
            persist=bool(persist),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def run_list(limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    """List recent runs stored under RUN_ROOT (plus read aliases)."""
    try:
        limit = max(1, min(int(limit), 200))
        run_ids_seen: set[str] = set()
        primary_run_ids: list[str] = []
        alias_run_ids: list[str] = []
        primary_root = _runstore.RUN_ROOT.expanduser().resolve()
        for root in _run_roots_for_read():
            runs_dir = root / "runs"
            if not runs_dir.exists():
                continue
            bucket = (
                primary_run_ids
                if root.expanduser().resolve() == primary_root
                else alias_run_ids
            )
            for p in runs_dir.iterdir():
                if not p.is_dir() or p.name in run_ids_seen:
                    continue
                run_ids_seen.add(p.name)
                bucket.append(p.name)
        primary_run_ids.sort(reverse=True)
        alias_run_ids.sort(reverse=True)
        run_ids = primary_run_ids + alias_run_ids
        if cursor:
            try:
                idx = run_ids.index(cursor)
                run_ids = run_ids[idx + 1 :]
            except ValueError:
                # Unknown cursor; return from the top.
                pass

        selected = run_ids[:limit]
        next_cursor = selected[-1] if len(selected) == limit else None

        runs = []
        for run_id in selected:
            try:
                rec, run_dir = _load_run_with_dir(run_id)
                rec, proxied = _maybe_sync_delegated_run_record(run_id, rec, run_dir)
                if proxied is not None and proxied.get("ok") is not True:
                    logger.debug(
                        "delegated run_list sync failed for %s: %s",
                        run_id,
                        proxied.get("error"),
                    )
                runs.append(
                    {
                        "run_id": rec.run_id,
                        "created_at": rec.created_at,
                        "status": rec.status,
                        "dry_run": bool(rec.dry_run),
                        "source": rec.source or "external",
                    }
                )
            except Exception:
                runs.append(
                    {"run_id": run_id, "status": "unknown", "source": "external"}
                )

        return {"ok": True, "runs": runs, "next_cursor": next_cursor}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def run_logs(run_id: str) -> dict[str, Any]:
    """List log files under a run directory."""
    try:
        run_dir = _find_run_dir(run_id)
        marker = _load_delegated_execution_marker(run_dir)
        if isinstance(marker, dict) and str(marker.get("backend") or "") == "agent":
            proxied = _proxy_agent_run_payload(run_id, suffix="/logs")
            if proxied is not None:
                if proxied.get("ok") is True:
                    return {"ok": True, "items": proxied.get("logs") or []}
                return proxied
        logs_dir = run_dir / "logs"
        if not logs_dir.exists():
            return {"ok": True, "items": []}
        items = []
        for p in sorted(logs_dir.rglob("*")):
            if p.is_dir():
                continue
            rel = str(p.relative_to(run_dir))
            items.append({"relpath": rel, "size_bytes": p.stat().st_size})
        return {"ok": True, "items": items}
    except Exception as exc:
        proxied = _proxy_agent_run_payload(run_id, suffix="/logs")
        if proxied is not None:
            if proxied.get("ok") is True:
                return {"ok": True, "items": proxied.get("logs") or []}
            return proxied
        return {"ok": False, "error": str(exc)}


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_run_provenance(run_dir: Path) -> dict[str, Any]:
    return _load_json_dict(run_dir / "provenance.json")


def _load_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return []
    return rows


def _research_logging_meta(
    record: RunRecord,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    provenance_meta = _record_dict(provenance.get("research_logging"))
    progress_meta = _record_dict(_record_dict(record.progress).get("research_logging"))
    merged = dict(provenance_meta)
    merged.update(progress_meta)
    return merged


def _trace_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _record_dict(row.get("payload"))
    if _first_text_value(row.get("event_type")) == "unknown":
        raw_payload = _record_dict(payload.get("raw_payload"))
        if raw_payload:
            return raw_payload
    return payload


def _trace_row_event_type(row: dict[str, Any]) -> str:
    event_type = _first_text_value(row.get("event_type"))
    if event_type == "unknown":
        payload = _record_dict(row.get("payload"))
        return _first_text_value(payload.get("raw_event_type"), "unknown") or "unknown"
    return event_type or "unknown"


def _build_server_derived_signals(
    record: RunRecord,
    run_dir: Path,
) -> dict[str, int]:
    trace_rows = _load_jsonl_dicts(run_dir / "trace.jsonl")

    research_trace_events = 0
    non_research_trace_events = 0
    tool_call_started = 0
    tool_call_finished = 0
    tool_call_non_success = 0
    retry_like_events = 0
    warning_events = 0
    error_like_events = 0

    for row in trace_rows:
        event_type = _trace_row_event_type(row)
        payload = _trace_row_payload(row)
        lowered = event_type.lower()

        if lowered.startswith("research."):
            research_trace_events += 1
        else:
            non_research_trace_events += 1

        if lowered in {"tool.call.started", "tool.started", "tool_started"}:
            tool_call_started += 1
        elif lowered in {
            "tool.call.finished",
            "tool.finished",
            "tool.completed",
            "tool_completed",
        }:
            tool_call_finished += 1
            status = _first_text_value(payload.get("status"), payload.get("state"))
            if status and status.lower() not in {
                "ok",
                "success",
                "successful",
                "succeeded",
            }:
                tool_call_non_success += 1

        if lowered == "warning" or lowered in {"tool.blocked"}:
            warning_events += 1
        if (
            lowered == "error"
            or lowered.endswith(".failed")
            or lowered == "step_failed"
        ):
            error_like_events += 1
        if "retry" in lowered:
            retry_like_events += 1
            continue
        status = _first_text_value(payload.get("status"))
        if status and status.lower() == "retrying":
            retry_like_events += 1

    failed_steps = sum(1 for step in record.steps if str(step.status or "") == "failed")
    successful_steps = sum(
        1 for step in record.steps if str(step.status or "") == "succeeded"
    )

    return {
        "trace_event_total": len(trace_rows),
        "research_trace_events": research_trace_events,
        "non_research_trace_events": non_research_trace_events,
        "tool_call_started": tool_call_started,
        "tool_call_finished": tool_call_finished,
        "tool_call_non_success": tool_call_non_success,
        "retry_like_events": retry_like_events,
        "warning_events": warning_events,
        "error_like_events": error_like_events,
        "failed_steps": failed_steps,
        "succeeded_steps": successful_steps,
    }


def _build_research_session_digest(
    record: RunRecord,
    run_dir: Path,
    provenance: dict[str, Any],
) -> dict[str, Any] | None:
    meta = _research_logging_meta(record, provenance)
    session_id = _first_text_value(meta.get("session_id"))
    events = _load_jsonl_dicts(run_dir / _RESEARCH_EVENTS_FILENAME)
    snapshot = _load_json_dict(run_dir / _SESSION_SNAPSHOT_FILENAME)
    conversation_rows = _load_research_conversation_rows(run_dir)
    tool_trace_rows = _load_jsonl_dicts(run_dir / _RESEARCH_TOOL_TRACE_FILENAME)
    if not session_id and not events and not snapshot:
        return None

    start_events = [row for row in events if str(row.get("kind") or "") == "start"]
    note_events = [row for row in events if str(row.get("kind") or "") == "note"]
    auto_events = [row for row in events if str(row.get("kind") or "") == "auto"]
    end_events = [
        row
        for row in events
        if str(row.get("kind") or "") == "end"
        or str(row.get("event_type") or "") == "research.snapshot"
    ]
    source_client = _first_text_value(
        meta.get("source_client"),
        snapshot.get("source_client"),
        events[-1].get("source_client") if events else None,
    )
    client_session_id = _first_text_value(
        meta.get("client_session_id"),
        snapshot.get("client_session_id"),
        events[-1].get("client_session_id") if events else None,
    )
    last_source = _first_text_value(
        meta.get("source"),
        snapshot.get("source"),
        events[-1].get("source") if events else None,
    )
    route = (
        _first_text_value(
            provenance.get("route"),
            _record_dict(provenance.get("request")).get("route"),
        )
        or "unknown"
    )
    event_count = int(meta.get("event_count") or len(events))
    start_count = int(meta.get("start_count") or len(start_events))
    note_count = int(meta.get("note_count") or len(note_events))
    auto_count = int(meta.get("auto_count") or len(auto_events))
    end_count = int(
        meta.get("snapshot_count") or len(end_events) or (1 if snapshot else 0)
    )

    event_tags: list[str] = []
    event_sources: list[str] = []
    for row in events:
        event_tags.extend(_coerce_non_empty_str_list(row.get("tags")))
        source = _first_text_value(row.get("source"))
        if source:
            event_sources.append(source)
    if snapshot:
        event_tags.extend(_coerce_non_empty_str_list(snapshot.get("tags")))

    done_items = _coerce_non_empty_str_list(snapshot.get("done"))
    open_items = _coerce_non_empty_str_list(snapshot.get("open"))
    notes = [
        {
            "event_id": _first_text_value(row.get("event_id")),
            "timestamp": _first_text_value(row.get("timestamp")),
            "source": _first_text_value(row.get("source")),
            "content": _first_text_value(row.get("content")),
            "tags": _coerce_non_empty_str_list(row.get("tags")),
            "context": _record_dict(row.get("context")),
        }
        for row in note_events
    ]
    auto_event_rows = [
        {
            "event_id": _first_text_value(row.get("event_id")),
            "event_type": _first_text_value(row.get("event_type")),
            "timestamp": _first_text_value(row.get("timestamp")),
            "tool_name": _first_text_value(row.get("tool_name")),
            "subtype": _first_text_value(row.get("subtype")),
            "details": _record_dict(row.get("details")),
        }
        for row in auto_events
    ]
    recent_events = [
        {
            "event_id": _first_text_value(row.get("event_id")),
            "kind": _first_text_value(row.get("kind"), row.get("event_type")),
            "timestamp": _first_text_value(row.get("timestamp")),
            "source": _first_text_value(row.get("source")),
            "tags": _coerce_non_empty_str_list(row.get("tags")),
            "content": _first_text_value(row.get("content")),
            "has_snapshot": isinstance(row.get("snapshot"), dict),
        }
        for row in events[-10:]
    ]
    conversation_preview = [
        {
            "message_id": _first_text_value(row.get("message_id")),
            "timestamp": _first_text_value(row.get("timestamp")),
            "role": _first_text_value(row.get("role")),
            "content": _first_text_value(row.get("content")),
            "metadata": _record_dict(row.get("metadata")),
        }
        for row in conversation_rows[-_RESEARCH_DIGEST_TRANSCRIPT_PREVIEW_LIMIT:]
    ]
    tool_trace_preview = [
        {
            "trace_id": _first_text_value(row.get("trace_id")),
            "timestamp": _first_text_value(row.get("timestamp")),
            "event_type": _first_text_value(row.get("event_type")),
            "tool_name": _first_text_value(row.get("tool_name")),
            "error": _first_text_value(row.get("error")),
            "result": _record_dict(row.get("result")),
        }
        for row in tool_trace_rows[-_RESEARCH_DIGEST_TOOL_TRACE_PREVIEW_LIMIT:]
    ]
    server_derived_signals = _build_server_derived_signals(record, run_dir)

    return {
        "run_id": record.run_id,
        "run_dir": str(run_dir),
        "session_id": session_id,
        "client_session_id": client_session_id,
        "source_client": source_client,
        "route": route,
        "logging_mode": "synthetic" if route == "research_logging" else "attached",
        "status": record.status,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "managed_run": bool(meta.get("managed_run")),
        "source": last_source,
        "last_event_at": _first_text_value(
            meta.get("last_event_at"),
            events[-1].get("timestamp") if events else None,
        ),
        "has_snapshot": bool(snapshot),
        "snapshot": snapshot or None,
        "event_counts": {
            "total": event_count,
            "start": start_count,
            "note": note_count,
            "auto": auto_count,
            "end": end_count,
        },
        "done_count": len(done_items),
        "open_count": len(open_items),
        "transcript_message_count": len(conversation_rows),
        "tool_trace_event_count": len(tool_trace_rows),
        "done_items": done_items,
        "open_items": open_items,
        "event_tags": event_tags,
        "event_sources": event_sources,
        "notes": notes,
        "auto_events": auto_event_rows,
        "recent_events": recent_events,
        "conversation_preview": conversation_preview,
        "tool_trace_preview": tool_trace_preview,
        "server_derived_signals": server_derived_signals,
        "files": {
            "research_events_jsonl": _RESEARCH_EVENTS_FILENAME,
            "session_snapshot_json": _SESSION_SNAPSHOT_FILENAME,
            "trace_jsonl": "trace.jsonl",
            "session_transcript_jsonl": _SESSION_TRANSCRIPT_FILENAME,
            "conversation_log_jsonl": _RESEARCH_CONVERSATION_LOG_FILENAME,
            "tool_trace_jsonl": _RESEARCH_TOOL_TRACE_FILENAME,
        },
    }


def _research_session_digest_marker(digest: dict[str, Any]) -> tuple[str, str]:
    return (
        _first_text_value(digest.get("last_event_at"), digest.get("created_at")) or "",
        _first_text_value(digest.get("run_id")) or "",
    )


def _research_session_logging_mode(digest: dict[str, Any]) -> str:
    routes = [
        route
        for route in _coerce_non_empty_str_list(digest.get("routes"))
        if route.strip()
    ]
    if not routes:
        route = _first_text_value(digest.get("route"))
        if route:
            routes = [route]
    if routes and all(route == "research_logging" for route in routes):
        return "synthetic"
    return "attached"


def _merge_research_session_digests(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    ordered = sorted(rows, key=_research_session_digest_marker)
    latest = ordered[-1]
    latest_snapshot_row = next(
        (row for row in reversed(ordered) if row.get("has_snapshot")),
        latest,
    )

    merged_event_counts = {"total": 0, "start": 0, "note": 0, "auto": 0, "end": 0}
    merged_server_signals = {
        "trace_event_total": 0,
        "research_trace_events": 0,
        "non_research_trace_events": 0,
        "tool_call_started": 0,
        "tool_call_finished": 0,
        "tool_call_non_success": 0,
        "retry_like_events": 0,
        "warning_events": 0,
        "error_like_events": 0,
        "failed_steps": 0,
        "succeeded_steps": 0,
    }
    event_tags: list[str] = []
    event_sources: list[str] = []
    notes: list[dict[str, Any]] = []
    auto_events: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []
    conversation_preview: list[dict[str, Any]] = []
    tool_trace_preview: list[dict[str, Any]] = []
    routes: list[str] = []
    run_ids: list[str] = []
    transcript_message_count = 0
    tool_trace_event_count = 0

    for row in ordered:
        run_id = _first_text_value(row.get("run_id"))
        if run_id:
            run_ids.append(run_id)
        route = _first_text_value(row.get("route"))
        if route:
            routes.append(route)
        counts = _record_dict(row.get("event_counts"))
        for key in merged_event_counts:
            try:
                merged_event_counts[key] += int(counts.get(key) or 0)
            except Exception:
                continue
        for key, value in _record_dict(row.get("server_derived_signals")).items():
            try:
                merged_server_signals[key] = merged_server_signals.get(key, 0) + int(
                    value or 0
                )
            except Exception:
                continue
        event_tags.extend(_coerce_non_empty_str_list(row.get("event_tags")))
        event_sources.extend(_coerce_non_empty_str_list(row.get("event_sources")))
        notes.extend(item for item in row.get("notes", []) if isinstance(item, dict))
        auto_events.extend(
            item for item in row.get("auto_events", []) if isinstance(item, dict)
        )
        recent_events.extend(
            item for item in row.get("recent_events", []) if isinstance(item, dict)
        )
        conversation_preview.extend(
            item
            for item in row.get("conversation_preview", [])
            if isinstance(item, dict)
        )
        tool_trace_preview.extend(
            item for item in row.get("tool_trace_preview", []) if isinstance(item, dict)
        )
        try:
            transcript_message_count += int(row.get("transcript_message_count") or 0)
        except Exception:
            pass
        try:
            tool_trace_event_count += int(row.get("tool_trace_event_count") or 0)
        except Exception:
            pass

    notes.sort(
        key=lambda item: (
            _first_text_value(item.get("timestamp")) or "",
            _first_text_value(item.get("event_id")) or "",
        )
    )
    auto_events.sort(
        key=lambda item: (
            _first_text_value(item.get("timestamp")) or "",
            _first_text_value(item.get("event_id")) or "",
        )
    )
    recent_events.sort(
        key=lambda item: (
            _first_text_value(item.get("timestamp")) or "",
            _first_text_value(item.get("event_id")) or "",
        )
    )
    conversation_preview.sort(
        key=lambda item: (
            _first_text_value(item.get("timestamp")) or "",
            _first_text_value(item.get("message_id")) or "",
        )
    )
    tool_trace_preview.sort(
        key=lambda item: (
            _first_text_value(item.get("timestamp")) or "",
            _first_text_value(item.get("trace_id")) or "",
        )
    )

    merged = dict(latest)
    merged["run_ids"] = run_ids
    unique_routes = list(dict.fromkeys(route for route in routes if route))
    if len(unique_routes) > 1:
        merged["routes"] = unique_routes
    merged["logging_mode"] = _research_session_logging_mode(
        {"route": latest.get("route"), "routes": unique_routes}
    )
    merged["managed_run"] = any(row.get("managed_run") for row in ordered)
    merged["has_snapshot"] = any(row.get("has_snapshot") for row in ordered)
    merged["snapshot"] = latest_snapshot_row.get("snapshot")
    merged["done_items"] = _coerce_non_empty_str_list(
        latest_snapshot_row.get("done_items")
    )
    merged["open_items"] = _coerce_non_empty_str_list(
        latest_snapshot_row.get("open_items")
    )
    merged["done_count"] = len(merged["done_items"])
    merged["open_count"] = len(merged["open_items"])
    merged["event_counts"] = merged_event_counts
    merged["event_tags"] = event_tags
    merged["event_sources"] = event_sources
    merged["notes"] = notes
    merged["auto_events"] = auto_events
    merged["recent_events"] = recent_events[-10:]
    merged["transcript_message_count"] = transcript_message_count
    merged["tool_trace_event_count"] = tool_trace_event_count
    merged["conversation_preview"] = conversation_preview[
        -_RESEARCH_DIGEST_TRANSCRIPT_PREVIEW_LIMIT:
    ]
    merged["tool_trace_preview"] = tool_trace_preview[
        -_RESEARCH_DIGEST_TOOL_TRACE_PREVIEW_LIMIT:
    ]
    merged["server_derived_signals"] = merged_server_signals
    return merged


def _collect_research_session_digests(session_id: str) -> list[dict[str, Any]]:
    normalized_session_id = _first_text_value(session_id)
    if not normalized_session_id:
        return []

    matches: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()

    indexed_run_id = _lookup_research_session_run_id(normalized_session_id)
    if indexed_run_id:
        try:
            record, run_dir = _load_run_with_dir(indexed_run_id)
            provenance = _load_run_provenance(run_dir)
            digest = _build_research_session_digest(record, run_dir, provenance)
            if (
                isinstance(digest, dict)
                and digest.get("session_id") == normalized_session_id
            ):
                matches.append(digest)
                seen_run_ids.add(record.run_id)
        except Exception:
            pass

    for record, run_dir, provenance in _iter_run_records_for_summary():
        if record.run_id in seen_run_ids:
            continue
        digest = _build_research_session_digest(record, run_dir, provenance)
        if (
            isinstance(digest, dict)
            and digest.get("session_id") == normalized_session_id
        ):
            matches.append(digest)
            seen_run_ids.add(record.run_id)

    matches.sort(key=_research_session_digest_marker)
    return matches


def _find_research_run_by_session_id(
    session_id: str,
) -> tuple[RunRecord, Path, dict[str, Any]] | None:
    normalized_session_id = _first_text_value(session_id)
    if not normalized_session_id:
        return None

    matches = _collect_research_session_digests(normalized_session_id)
    if not matches:
        return None
    latest = matches[-1]
    try:
        record, run_dir = _load_run_with_dir(
            _first_text_value(latest.get("run_id")) or ""
        )
    except Exception:
        return None
    return record, run_dir, _load_run_provenance(run_dir)


def _request_type_entries(
    record: RunRecord,
    provenance: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    route = (
        _first_text_value(
            provenance.get("route"),
            _record_dict(provenance.get("request")).get("route"),
        )
        or "unknown"
    )
    request = _record_dict(provenance.get("request"))
    entries: list[tuple[str, str, dict[str, Any]]] = []

    tool_id = _first_text_value(
        request.get("tool_id"),
        request.get("requested_tool_id"),
        request.get("tool_name"),
    )
    if tool_id:
        params = request.get("params")
        entries.append((route, tool_id, params if isinstance(params, dict) else {}))

    plan = _record_dict(request.get("plan"))
    plan_steps = plan.get("steps")
    if isinstance(plan_steps, list):
        for step in plan_steps:
            if not isinstance(step, dict):
                continue
            tool = _first_text_value(step.get("tool"), step.get("tool_id"))
            if not tool:
                continue
            params = step.get("params")
            entries.append((route, tool, params if isinstance(params, dict) else {}))

    if entries:
        return entries

    for step in record.steps:
        tool = _first_text_value(step.tool_id)
        if not tool:
            continue
        entries.append(
            (route, tool, step.params if isinstance(step.params, dict) else {})
        )
    return entries


def _iter_run_records_for_summary() -> list[tuple[RunRecord, Path, dict[str, Any]]]:
    records: list[tuple[RunRecord, Path, dict[str, Any]]] = []
    run_ids_seen: set[str] = set()
    for root in _run_roots_for_read():
        runs_dir = root / "runs"
        if not runs_dir.exists():
            continue
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir() or run_dir.name in run_ids_seen:
                continue
            run_ids_seen.add(run_dir.name)
            try:
                record = _run_record_from_json(run_dir / "run.json")
            except Exception:
                continue
            record, proxied = _maybe_sync_delegated_run_record(
                record.run_id, record, run_dir
            )
            if proxied is not None and proxied.get("ok") is not True:
                logger.debug(
                    "delegated summary sync failed for %s: %s",
                    record.run_id,
                    proxied.get("error"),
                )
            records.append((record, run_dir, _load_run_provenance(run_dir)))
    records.sort(key=lambda item: item[0].created_at or item[0].run_id, reverse=True)
    return records


_REVIEWABLE_RUN_SIGNAL_FILES = (
    "analysis_bundle.json",
    "source_summary.json",
    "extraction_report.json",
    "scientific_review_verdict.json",
    "research_episode.json",
    "option_set.json",
    "evidence_gate.json",
    "commitment.json",
    "claim_report.json",
    "claim_update.json",
)
_REVIEWABLE_RUN_OBSERVED_KEYS = frozenset(
    {
        "analysis_bundle",
        "source_summary",
        "extraction_report",
        "review_contract",
        "review_context",
        "research_episode",
        "option_set",
        "evidence_gate",
        "commitment",
        "claim_report",
        "claim_update",
    }
)
_REVIEWABLE_RUN_HOUSEKEEPING_TOOLS = frozenset(
    {
        "log_research_event",
        "write_session_snapshot",
        "research_session_digest",
        "research_log_summary",
        "session_risk_classify",
        "session_lesson_extract",
        "session_open_risks_query",
        "session_policy_cards_generate",
        "session_learning_report_generate",
        "session_signal_report_generate",
        "session_backfill_to_kg",
        "latex_report_render",
        "scientific_report_generate",
        "request_scientific_review",
        "request_external_scientific_review_directive",
        "submit_external_scientific_review_verdict",
        "run_scientific_review",
        "run_autoresearch_scientific_review",
        "run_code_review",
    }
)


def _reviewable_run_signal_files(run_dir: Path) -> list[str]:
    return [
        relpath
        for relpath in _REVIEWABLE_RUN_SIGNAL_FILES
        if (run_dir / relpath).exists()
    ]


def _reviewable_run_route(provenance: dict[str, Any]) -> str:
    return (
        _first_text_value(
            provenance.get("route"),
            _record_dict(provenance.get("request")).get("route"),
        )
        or "unknown"
    )


def _reviewable_run_tool_ids(
    record: RunRecord,
    provenance: dict[str, Any],
) -> list[str]:
    tool_ids: list[str] = []
    seen: set[str] = set()
    for _route, tool_id, _params in _request_type_entries(record, provenance):
        normalized = _first_text_value(tool_id)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tool_ids.append(normalized)
    return tool_ids


def _probe_reviewable_run(
    record: RunRecord,
    run_dir: Path,
    provenance: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    route = _reviewable_run_route(provenance)
    tool_ids = _reviewable_run_tool_ids(record, provenance)
    signal_files = _reviewable_run_signal_files(run_dir)
    run_payload = _load_json_dict(run_dir / "run.json")
    inline_review_contract = _record_dict(run_payload.get("review_contract"))
    inline_review_context = _record_dict(run_payload.get("review_context"))

    if (
        route == "research_logging"
        and not signal_files
        and not inline_review_contract
        and not inline_review_context
    ):
        return None, "research_logging_only"

    housekeeping_only = (
        bool(tool_ids) and set(tool_ids) <= _REVIEWABLE_RUN_HOUSEKEEPING_TOOLS
    )
    if (
        housekeeping_only
        and not signal_files
        and not inline_review_contract
        and not inline_review_context
    ):
        return None, "housekeeping_only"

    # Keep discovery conservative and cheap: only probe runs that already expose
    # at least one review-oriented signal on disk or inline in run.json.
    if not signal_files and not inline_review_contract and not inline_review_context:
        return None, "missing_fast_review_signals"

    try:
        from brain_researcher.services.review.bundle_builder import (
            build_artifact_review_bundle,
        )
        from brain_researcher.services.review.checks.completeness import (
            build_completeness_checklist,
        )

        bundle = build_artifact_review_bundle(record.run_id, run_dir=run_dir)
        checklist = build_completeness_checklist(bundle)
    except Exception as exc:
        return None, f"bundle_unavailable:{type(exc).__name__}"

    observed_artifacts = (
        dict(bundle.observed_artifacts)
        if isinstance(getattr(bundle, "observed_artifacts", None), dict)
        else {}
    )
    observed_keys = [
        key
        for key in sorted(_REVIEWABLE_RUN_OBSERVED_KEYS)
        if key in observed_artifacts
    ]
    review_contract = _record_dict(observed_artifacts.get("review_contract"))
    if not review_contract:
        review_contract = inline_review_contract
    review_context = _record_dict(getattr(bundle, "review_context", {}))
    if not review_context:
        review_context = inline_review_context
    if not review_context:
        review_context = _record_dict(observed_artifacts.get("review_context"))

    if not (signal_files or observed_keys or review_contract or review_context):
        return None, "no_reviewable_bundle_signals"

    missing_checks = [key for key, passed in checklist.items() if not passed]
    contract_mode = _first_text_value(review_contract.get("contract_mode"))
    scientific_review_profile = _first_text_value(
        review_contract.get("scientific_review_profile"),
        review_context.get("scientific_review_profile"),
        _record_dict(getattr(bundle, "stats_metrics", {})).get(
            "artifact_scientific_review_profile"
        ),
    )

    reasons: list[str] = []
    if signal_files:
        reasons.append("review artifacts present: " + ", ".join(signal_files[:4]))
    if observed_keys:
        reasons.append("bundle signals: " + ", ".join(observed_keys[:4]))
    if contract_mode:
        reasons.append(f"review contract: {contract_mode}")
    if scientific_review_profile:
        reasons.append(f"profile: {scientific_review_profile}")
    if checklist:
        reasons.append(
            f"declared completeness checks: {len(checklist) - len(missing_checks)}/{len(checklist)}"
        )
    if not reasons:
        reasons.append("bundle builds with scientific review context")

    return (
        {
            "run_id": record.run_id,
            "created_at": record.created_at,
            "status": record.status,
            "route": route,
            "steps_total": len(record.steps),
            "tool_ids": tool_ids,
            "signal_files": signal_files,
            "observed_review_artifacts": observed_keys,
            "review_contract_mode": contract_mode,
            "scientific_review_profile": scientific_review_profile,
            "review_context_keys": sorted(review_context.keys())[:12],
            "completeness_preview": {
                "declared_checks_total": len(checklist),
                "declared_checks_missing": missing_checks[:10],
            },
            "selection_reasons": reasons,
            "next_step": f"Pass run_id={record.run_id} to scientific_report_generate.",
        },
        None,
    )


@mcp.tool()
def run_find_latest_reviewable(
    limit: int = 50,
    max_candidates: int = 5,
    include_non_succeeded: bool = False,
) -> dict[str, Any]:
    """Find recent runs that look suitable for scientific review/report generation.

    This helper searches recent persisted runs, skips obvious housekeeping/report
    runs, and returns the newest candidates that expose review-oriented artifacts
    such as ``analysis_bundle.json`` or ``source_summary.json``. The selected
    ``run_id`` can then be passed to ``scientific_report_generate``.
    """

    try:
        limit = max(1, min(int(limit), 200))
        max_candidates = max(1, min(int(max_candidates), 20))
    except Exception as exc:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": str(exc),
        }

    candidates: list[dict[str, Any]] = []
    skipped_preview: list[dict[str, Any]] = []
    inspected_runs = 0

    for record, run_dir, provenance in _iter_run_records_for_summary():
        if inspected_runs >= limit:
            break
        inspected_runs += 1

        if not include_non_succeeded and str(record.status or "") != "succeeded":
            if len(skipped_preview) < 10:
                skipped_preview.append(
                    {
                        "run_id": record.run_id,
                        "status": record.status,
                        "reason": "status_not_succeeded",
                    }
                )
            continue

        candidate, skip_reason = _probe_reviewable_run(record, run_dir, provenance)
        if candidate is None:
            if len(skipped_preview) < 10:
                skipped_preview.append(
                    {
                        "run_id": record.run_id,
                        "status": record.status,
                        "reason": skip_reason or "not_reviewable",
                    }
                )
            continue

        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break

    selected = candidates[0] if candidates else None
    if selected is None:
        message = (
            "No reviewable runs were found in the inspected window. Provide a run_id "
            "manually, or call scientific_report_generate without a source to render "
            "analysis sections only."
        )
    else:
        message = (
            f"Selected {selected['run_id']} as the newest reviewable run. Pass this "
            "run_id to scientific_report_generate."
        )

    return {
        "ok": True,
        "selected_run_id": (
            selected.get("run_id") if isinstance(selected, dict) else None
        ),
        "selected": selected,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "inspected_runs": inspected_runs,
        "limit": limit,
        "max_candidates": max_candidates,
        "include_non_succeeded": bool(include_non_succeeded),
        "skipped_preview": skipped_preview,
        "message": message,
    }


@mcp.tool()
def run_request_summary(
    top_k: int = 10,
    since_days: int | None = None,
) -> dict[str, Any]:
    """Summarize historical MCP request types from persisted run artifacts."""
    try:
        top_k = max(1, min(int(top_k), 100))
        if since_days is not None:
            since_days = max(1, min(int(since_days), 3650))
        cutoff = None
        if since_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=since_days)

        route_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        request_type_counts: dict[str, int] = {}
        request_routes: dict[str, set[str]] = {}
        request_examples: dict[str, list[dict[str, Any]]] = {}
        total_runs = 0
        skipped_runs = 0

        for record, _run_dir, provenance in _iter_run_records_for_summary():
            created_at = _parse_iso(record.created_at)
            if cutoff is not None and created_at is not None and created_at < cutoff:
                continue

            total_runs += 1
            route = (
                _first_text_value(
                    provenance.get("route"),
                    _record_dict(provenance.get("request")).get("route"),
                )
                or "unknown"
            )
            status = (
                _first_text_value(record.status, provenance.get("state")) or "unknown"
            )
            route_counts[route] = route_counts.get(route, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1

            entries = _request_type_entries(record, provenance)
            if not entries:
                skipped_runs += 1
                continue

            for entry_route, request_type, params in entries:
                request_type_counts[request_type] = (
                    request_type_counts.get(request_type, 0) + 1
                )
                request_routes.setdefault(request_type, set()).add(entry_route)
                examples = request_examples.setdefault(request_type, [])
                if len(examples) >= 3:
                    continue
                examples.append(
                    {
                        "run_id": record.run_id,
                        "route": entry_route,
                        "status": status,
                        "created_at": record.created_at,
                        "param_keys": sorted(
                            str(key) for key in params.keys() if str(key).strip()
                        ),
                    }
                )

        request_rows = [
            {
                "request_type": request_type,
                "count": count,
                "routes": sorted(request_routes.get(request_type, set())),
                "examples": request_examples.get(request_type, []),
            }
            for request_type, count in sorted(
                request_type_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:top_k]
        ]
        compat_alias_usage = _compat_alias_usage_summary(top_k=top_k)

        return {
            "ok": True,
            "top_k": top_k,
            "since_days": since_days,
            "total_runs": total_runs,
            "runs_without_request_type": skipped_runs,
            "roots_scanned": [str(root) for root in _run_roots_for_read()],
            "route_counts": [
                {"route": route, "count": count}
                for route, count in sorted(
                    route_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "status_counts": [
                {"status": status, "count": count}
                for status, count in sorted(
                    status_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "request_type_counts": request_rows,
            "compat_alias_usage": compat_alias_usage,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def run_cancel(run_id: str, reason: str | None = None) -> dict[str, Any]:
    """Request cancellation of a run (best-effort)."""
    lock = _get_run_lock(run_id)
    with lock:
        try:
            record, run_dir = _load_run_with_dir(run_id)
            marker = _load_delegated_execution_marker(run_dir)
            if isinstance(marker, dict) and str(marker.get("backend") or "") == "agent":
                proxied = _proxy_agent_run_payload(
                    run_id,
                    suffix="/cancel",
                    method="POST",
                    payload={"reason": reason},
                )
                if proxied is not None:
                    return proxied
        except Exception as exc:
            proxied = _proxy_agent_run_payload(
                run_id,
                suffix="/cancel",
                method="POST",
                payload={"reason": reason},
            )
            if proxied is not None:
                return proxied
            return {"ok": False, "error": f"run not found: {exc}"}

        if record.status in {"succeeded", "failed", "cancelled"}:
            return {
                "ok": True,
                "run_id": record.run_id,
                "status": record.status,
                "message": "run already finished",
            }

        record.status = "cancelled"
        record.error = reason or "cancelled"
        record.finished_at = _utc_iso()
        for step in record.steps:
            if step.status == "queued":
                step.status = "skipped"
        _update_run_progress(
            record,
            stage="cancelled",
            message=reason or "Run cancelled",
        )
        _save_run(record, run_dir=run_dir)

    log_trace = None
    try:
        from brain_researcher.services.agent.run_bundle import (
            log_trace_event as _log_trace_event,
        )

        log_trace = _log_trace_event
    except Exception:
        log_trace = None

    _emit_trace_event(
        log_trace,
        run_dir,
        run_id=run_id,
        event_type="mcp.run.cancelled",
        payload={"reason": reason or "cancelled"},
    )

    _persist_mcp_run_bundle(run_id, run_dir=run_dir)
    return {"ok": True, "run_id": record.run_id, "status": record.status}


@mcp.tool()
def run_metrics(run_id: str) -> dict[str, Any]:
    """Return timing/cost metrics for a run and its steps."""
    try:
        record, run_dir = _load_run_with_dir(run_id)
        marker = _load_delegated_execution_marker(run_dir)
        if isinstance(marker, dict) and str(marker.get("backend") or "") == "agent":
            proxied = _proxy_agent_run_payload(run_id, suffix="/metrics")
            if proxied is not None:
                return proxied
    except Exception as exc:
        proxied = _proxy_agent_run_payload(run_id, suffix="/metrics")
        if proxied is not None:
            return proxied
        return {"ok": False, "error": f"run not found: {exc}"}
    totals = {
        "steps": len(record.steps),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "execution_time_s_sum": 0.0,
        "tokens_sum": 0,
        "cost_usd_sum": 0.0,
    }
    steps_out = []

    for step in record.steps:
        st = _parse_iso(step.started_at)
        ft = _parse_iso(step.finished_at)
        duration_s = (ft - st).total_seconds() if st and ft else None

        result_payload: dict[str, Any] = {}
        if step.result_path:
            try:
                result_path = (run_dir / step.result_path).resolve()
                result_payload = json.loads(result_path.read_text())
            except Exception:
                result_payload = {}

        data = result_payload.get("data") if isinstance(result_payload, dict) else {}
        metadata = (
            result_payload.get("metadata") if isinstance(result_payload, dict) else {}
        )
        if not isinstance(data, dict):
            data = {}
        if not isinstance(metadata, dict):
            metadata = {}

        execution_time = None
        for key in (
            "execution_time",
            "execution_time_s",
            "execution_time_seconds",
            "runtime_s",
        ):
            if key in data:
                execution_time = data.get(key)
                break
            if key in metadata:
                execution_time = metadata.get(key)
                break

        tokens = None
        for key in ("tokens", "total_tokens"):
            if key in metadata:
                tokens = metadata.get(key)
                break
        if tokens is None:
            input_tokens = metadata.get("input_tokens")
            output_tokens = metadata.get("output_tokens")
            if isinstance(input_tokens, int | float) or isinstance(
                output_tokens, int | float
            ):
                tokens = (input_tokens or 0) + (output_tokens or 0)

        cost_usd = metadata.get("cost_usd") or metadata.get("estimated_usd")

        if step.status == "succeeded":
            totals["succeeded"] += 1
        elif step.status == "failed":
            totals["failed"] += 1
        elif step.status == "skipped":
            totals["skipped"] += 1

        if isinstance(execution_time, int | float):
            totals["execution_time_s_sum"] += float(execution_time)
        if isinstance(tokens, int | float):
            totals["tokens_sum"] += int(tokens)
        if isinstance(cost_usd, int | float):
            totals["cost_usd_sum"] += float(cost_usd)

        steps_out.append(
            {
                "step_id": step.step_id,
                "tool_id": step.tool_id,
                "status": step.status,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
                "duration_s": duration_s,
                "execution_time_s": execution_time,
                "tokens": tokens,
                "cost_usd": cost_usd,
                "error": step.error,
            }
        )

    run_started = _parse_iso(record.started_at)
    run_finished = _parse_iso(record.finished_at)
    run_duration_s = (
        (run_finished - run_started).total_seconds()
        if run_started and run_finished
        else None
    )

    metrics = {
        "run_id": record.run_id,
        "status": record.status,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_s": run_duration_s,
        "totals": totals,
        "steps": steps_out,
    }
    return {"ok": True, "metrics": metrics}


_LATEX_TEXT_ESCAPES: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_LATEX_REPORT_GENERATED_NOTE = (
    "This report was generated automatically by Brain Researcher. "
    "Review all methods, outputs, and interpretations before using it for "
    "scientific, clinical, operational, or publication decisions."
)


def _latex_escape_text(value: Any) -> str:
    return "".join(_LATEX_TEXT_ESCAPES.get(ch, ch) for ch in str(value or ""))


def _validate_latex_report_sections(
    sections: dict[str, str],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    if not isinstance(sections, dict) or not sections:
        return {}, [
            {
                "level": "error",
                "code": "sections_required",
                "message": "sections must be a non-empty object mapping names to report content.",
            }
        ]

    if len(sections) > 50:
        return {}, [
            {
                "level": "error",
                "code": "too_many_sections",
                "message": "latex_report_render accepts at most 50 sections.",
            }
        ]

    total_bytes = 0
    normalized: dict[str, str] = {}
    for raw_name, raw_content in sections.items():
        name = _latex_escape_text(raw_name).strip()
        if not name:
            issues.append(
                {
                    "level": "error",
                    "code": "section_name_required",
                    "message": "section names must be non-empty strings.",
                }
            )
            continue
        content = str(raw_content or "")
        total_bytes += len(content.encode("utf-8", errors="replace"))
        if total_bytes > MAX_TEXT_BYTES:
            return {}, [
                {
                    "level": "error",
                    "code": "content_too_large",
                    "message": f"section content exceeds BR_MCP_MAX_TEXT_BYTES={MAX_TEXT_BYTES}.",
                }
            ]
        normalized[name] = content

    return normalized, issues


_LATEX_REPORT_PRESETS: dict[str, tuple[str, ...]] = {
    "freeform": (),
    "imrad": (
        "Abstract",
        "Introduction",
        "Methods",
        "Results",
        "Discussion",
        "Limitations",
        "Data And Code Availability",
        "References",
    ),
    "case_report": (
        "Abstract",
        "Introduction",
        "Case Study",
        "Methods",
        "Results",
        "Discussion",
        "Limitations",
        "Execution Pack",
        "References",
    ),
    "methods_report": (
        "Abstract",
        "Introduction",
        "Methods",
        "Validation",
        "Execution Pack",
        "Limitations",
        "References",
    ),
    "review_response": (
        "Response Overview",
        "Reviewer Comments",
        "Changes Made",
        "Validation",
        "References",
    ),
    "supplement": (
        "Supplementary Methods",
        "Supplementary Results",
        "Supplementary Figures",
        "Supplementary Tables",
        "References",
    ),
}


def _normalize_latex_report_template_preset(template_preset: str) -> str:
    preset = str(template_preset or "freeform").strip().lower().replace("-", "_")
    return preset if preset in _LATEX_REPORT_PRESETS else ""


def _latex_report_preset_checklist(
    template_preset: str,
    sections: dict[str, str],
) -> str:
    expected = _LATEX_REPORT_PRESETS.get(template_preset, ())
    if not expected:
        return ""
    lines = [r"\begin{reportingchecklist}[Template Preset Completeness]"]
    for name in expected:
        status = (
            r"\claimsupported supplied"
            if name in sections
            else r"\claimmissing missing"
        )
        lines.append(rf"\checklistitem{{{name}}}{{{status}}}")
    lines.append(r"\end{reportingchecklist}")
    return "\n".join(lines)


def _apply_latex_report_template_preset(
    sections: dict[str, str],
    template_preset: str,
) -> dict[str, str]:
    expected = _LATEX_REPORT_PRESETS.get(template_preset, ())
    if not expected:
        return sections

    ordered: dict[str, str] = {}
    for name in expected:
        if name in sections:
            ordered[name] = sections[name]
    for name, content in sections.items():
        if name not in ordered:
            ordered[name] = content

    checklist = _latex_report_preset_checklist(template_preset, sections)
    if checklist:
        section_name = "Template Completeness"
        if section_name in ordered:
            ordered[section_name] = ordered[section_name] + "\n" + checklist
        else:
            ordered[section_name] = checklist
    return ordered


def _validate_latex_bibliography_style(style: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", style or ""))


def _latex_report_execution_pack(
    *,
    template_preset: str,
    output_path: Path,
    created_at: str,
    compile_pdf: bool,
    sections_are_latex: bool,
    bibliography_written: bool,
) -> str:
    compile_requested = "yes" if compile_pdf else "no"
    raw_latex = "yes" if sections_are_latex else "no"
    bib_status = "written" if bibliography_written else "not supplied"
    return (
        r"\begin{executionpack}[MCP Render Execution Pack]"
        "\n"
        rf"\textbf{{Route.}} \texttt{{latex\_report\_render}}\par\medskip"
        "\n"
        rf"\textbf{{Created at.}} {_latex_escape_text(created_at)}\par\medskip"
        "\n"
        rf"\textbf{{Template preset.}} \texttt{{{_latex_escape_text(template_preset)}}}\par\medskip"
        "\n"
        rf"\textbf{{Raw LaTeX sections.}} {_latex_escape_text(raw_latex)}\par\medskip"
        "\n"
        rf"\textbf{{PDF compile requested.}} {_latex_escape_text(compile_requested)}\par\medskip"
        "\n"
        rf"\textbf{{Bibliography artifact.}} {_latex_escape_text(bib_status)}\par\medskip"
        "\n"
        rf"\artifactentry{{Renderer}}{{src/brain_researcher/services/tools/report_tools.py}}{{bundled}}"
        "\n"
        rf"\artifactentry{{Template}}{{src/brain_researcher/assets/latex/report_template.tex.j2}}{{bundled}}"
        "\n"
        rf"\artifactentry{{Style}}{{src/brain_researcher/assets/latex/scientific_report.sty}}{{bundled}}"
        "\n"
        rf"\artifactentry{{Output TeX}}{{{output_path}}}{{render target}}"
        "\n"
        r"\end{executionpack}"
    )


@mcp.tool()
def latex_report_render(
    title: str,
    authors: str,
    sections: dict[str, str],
    subtitle: str = "",
    institution: str = "",
    date: str = "",
    compile_pdf: bool = False,
    sections_are_latex: bool = False,
    template_preset: str = "freeform",
    front_matter_latex: str = "",
    back_matter_latex: str = "",
    bibliography_bibtex: str = "",
    bibliography_style: str = "plainnat",
    include_execution_pack: bool = False,
) -> dict[str, Any]:
    """Render structured content into the bundled Brain Researcher LaTeX report template.

    ``template_preset`` may be one of ``freeform``, ``imrad``, ``case_report``,
    ``methods_report``, ``review_response``, or ``supplement``. Non-freeform
    presets reorder supplied sections and add a preset-completeness checklist;
    they do not invent missing scientific content.
    """

    title_text = str(title or "").strip()
    authors_text = str(authors or "").strip()
    if not title_text:
        return {"ok": False, "error": "title_required"}
    if not authors_text:
        return {"ok": False, "error": "authors_required"}
    preset_key = _normalize_latex_report_template_preset(template_preset)
    if not preset_key:
        return {
            "ok": False,
            "error": "invalid_template_preset",
            "allowed_presets": sorted(_LATEX_REPORT_PRESETS),
        }
    bib_style = str(bibliography_style or "plainnat").strip() or "plainnat"
    if not _validate_latex_bibliography_style(bib_style):
        return {"ok": False, "error": "invalid_bibliography_style"}
    bibtex_text = str(bibliography_bibtex or "")
    if len(bibtex_text.encode("utf-8", errors="replace")) > MAX_TEXT_BYTES:
        return {"ok": False, "error": "bibliography_too_large"}

    normalized_sections, issues = _validate_latex_report_sections(sections)
    blocking = [issue for issue in issues if issue.get("level") == "error"]
    if blocking:
        return {"ok": False, "error": blocking[0]["code"], "issues": issues}
    render_sections = (
        normalized_sections
        if sections_are_latex
        else {
            name: _latex_escape_text(content)
            for name, content in normalized_sections.items()
        }
    )
    render_sections = _apply_latex_report_template_preset(render_sections, preset_key)

    _ensure_dirs()
    run_id = _new_run_id()
    run_dir = _run_dir(run_id)
    report_dir = run_dir / "artifacts" / "report"
    logs_dir = run_dir / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    created_at = _utc_iso()
    output_path = report_dir / "report.tex"
    record = RunRecord(
        run_id=run_id,
        created_at=created_at,
        status="running",
        run_workspace=str(run_dir),
        started_at=created_at,
        timing_policy=_default_run_timing_policy(),
        progress={
            "current_stage": "rendering",
            "message": "Rendering LaTeX report",
            "last_progress_at": created_at,
        },
        steps=[
            StepRecord(
                step_id="latex-report",
                tool_id="latex_report_render",
                params={
                    "title": title_text,
                    "authors": authors_text,
                    "section_count": len(normalized_sections),
                    "compile_pdf": bool(compile_pdf),
                    "sections_are_latex": bool(sections_are_latex),
                    "template_preset": preset_key,
                    "front_matter_latex": bool(front_matter_latex),
                    "back_matter_latex": bool(back_matter_latex),
                    "bibliography_bibtex": bool(bibtex_text),
                    "include_execution_pack": bool(include_execution_pack),
                },
                status="running",
                started_at=created_at,
                output_dir=str(report_dir),
                progress={
                    "current_stage": "rendering",
                    "message": "Rendering LaTeX report",
                    "last_progress_at": created_at,
                },
            )
        ],
    )
    _save_run(record)
    _atomic_write_json(
        run_dir / "provenance.json",
        _redact_for_logging(
            {
                "run_id": run_id,
                "mode": "mcp",
                "route": "latex_report_render",
                "transport": DEFAULT_TRANSPORT,
                "guardrails": _mcp_guardrails_snapshot(),
                "request": {
                    "title": title_text,
                    "authors": authors_text,
                    "section_count": len(normalized_sections),
                    "compile_pdf": bool(compile_pdf),
                    "sections_are_latex": bool(sections_are_latex),
                    "template_preset": preset_key,
                    "front_matter_latex": bool(front_matter_latex),
                    "back_matter_latex": bool(back_matter_latex),
                    "bibliography_bibtex": bool(bibtex_text),
                    "include_execution_pack": bool(include_execution_pack),
                },
            }
        ),
    )

    from brain_researcher.services.tools.report_tools import (
        compile_report_pdf,
        render_report_tex,
    )

    bibliography_path: Path | None = None
    if bibtex_text:
        bibliography_path = report_dir / "references.bib"
        bibliography_path.write_text(bibtex_text, encoding="utf-8")

    back_matter_parts = [str(back_matter_latex or "").strip()]
    if bibliography_path is not None:
        back_matter_parts.append(
            "\n".join(
                [
                    r"\reportappendix{References}",
                    rf"\reportbibliography{{{bib_style}}}{{references}}",
                ]
            )
        )
    combined_back_matter = "\n\n".join(part for part in back_matter_parts if part)

    if include_execution_pack:
        section_name = "Execution Pack"
        execution_pack = _latex_report_execution_pack(
            template_preset=preset_key,
            output_path=output_path,
            created_at=created_at,
            compile_pdf=bool(compile_pdf),
            sections_are_latex=bool(sections_are_latex),
            bibliography_written=bibliography_path is not None,
        )
        render_sections[section_name] = (
            render_sections.get(section_name, "") + "\n" + execution_pack
            if section_name in render_sections
            else execution_pack
        )

    generated_note = f"{_LATEX_REPORT_GENERATED_NOTE} Generated at {created_at}."
    render_result = render_report_tex(
        title=_latex_escape_text(title_text),
        subtitle=_latex_escape_text(subtitle),
        authors=_latex_escape_text(authors_text),
        institution=_latex_escape_text(institution),
        date=_latex_escape_text(date) if str(date or "").strip() else "",
        sections=render_sections,
        output_path=str(output_path),
        generated_note=_latex_escape_text(generated_note),
        front_matter=str(front_matter_latex or ""),
        back_matter=combined_back_matter,
    )

    compile_result: dict[str, Any] | None = None
    compile_status = "not_requested"
    warnings: list[str] = []
    if compile_pdf:
        if not ENABLE_LATEX_COMPILE:
            compile_status = "disabled"
            warnings.append(
                "PDF compilation skipped because BR_MCP_ENABLE_LATEX_COMPILE is not enabled."
            )
        elif render_result.get("status") == "success":
            compile_result = compile_report_pdf(
                tex_path=str(output_path),
                output_dir=str(report_dir),
            )
            compile_status = str(compile_result.get("status") or "error")

    artifacts: dict[str, str] = {}
    render_outputs = (
        render_result.get("outputs")
        if isinstance(render_result.get("outputs"), dict)
        else {}
    )
    if output_path.exists():
        artifacts["tex"] = str(output_path.relative_to(run_dir))
    for artifact_key, output_key in (
        ("style", "style_path"),
        ("template", "template_path"),
    ):
        asset_path = render_outputs.get(output_key)
        if asset_path and Path(str(asset_path)).exists():
            asset = Path(str(asset_path)).resolve()
            try:
                artifacts[artifact_key] = str(asset.relative_to(run_dir))
            except ValueError:
                # Keep generated artifacts portable; bundled source paths are
                # reported separately in template_assets below.
                pass
    if bibliography_path is not None and bibliography_path.exists():
        artifacts["bibliography"] = str(bibliography_path.relative_to(run_dir))
    metadata_path = report_dir / "report_metadata.json"
    if compile_result and isinstance(compile_result.get("outputs"), dict):
        pdf_path = compile_result["outputs"].get("pdf_path")
        if pdf_path and Path(str(pdf_path)).exists():
            artifacts["pdf"] = str(Path(str(pdf_path)).relative_to(run_dir))

    ok = render_result.get("status") == "success" and compile_status != "error"
    error = None
    if render_result.get("status") != "success":
        error = str(render_result.get("error") or "render_failed")
    elif compile_status == "error":
        error = str((compile_result or {}).get("error") or "compile_failed")

    template_assets = {
        "tex_template_source": "src/brain_researcher/assets/latex/report_template.tex.j2",
        "style_source": "src/brain_researcher/assets/latex/scientific_report.sty",
        "tex_template_artifact": artifacts.get("template"),
        "style_artifact": artifacts.get("style"),
    }
    result_payload: dict[str, Any] = {
        "ok": ok,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "artifacts": artifacts,
        "template_assets": template_assets,
        "generated_note": _LATEX_REPORT_GENERATED_NOTE,
        "sections_are_latex": bool(sections_are_latex),
        "template_preset": preset_key,
        "front_matter_latex": bool(front_matter_latex),
        "back_matter_latex": bool(back_matter_latex),
        "bibliography_bibtex": bool(bibtex_text),
        "bibliography_style": bib_style,
        "include_execution_pack": bool(include_execution_pack),
        "compile_pdf": {
            "requested": bool(compile_pdf),
            "enabled": bool(ENABLE_LATEX_COMPILE),
            "status": compile_status,
        },
        "render_result": render_result,
        "warnings": warnings,
    }
    if compile_result is not None:
        result_payload["compile_result"] = compile_result
    if error:
        result_payload["error"] = error

    _atomic_write_json(
        metadata_path,
        {
            "run_id": run_id,
            "created_at": created_at,
            "title": title_text,
            "authors": authors_text,
            "section_count": len(normalized_sections),
            "sections_are_latex": bool(sections_are_latex),
            "template_preset": preset_key,
            "front_matter_latex": bool(front_matter_latex),
            "back_matter_latex": bool(back_matter_latex),
            "bibliography_bibtex": bool(bibtex_text),
            "bibliography_style": bib_style,
            "include_execution_pack": bool(include_execution_pack),
            "generated_note": _LATEX_REPORT_GENERATED_NOTE,
            "compile_pdf": result_payload["compile_pdf"],
            "artifacts": artifacts,
            "template_assets": template_assets,
            "warnings": warnings,
            "ok": ok,
            "error": error,
        },
    )
    artifacts["metadata"] = str(metadata_path.relative_to(run_dir))
    result_payload["artifacts"] = artifacts
    _atomic_write_json(logs_dir / "latex_report_render.json", result_payload)

    finished_at = _utc_iso()
    record.status = "succeeded" if ok else "failed"
    record.finished_at = finished_at
    record.error = error
    record.progress = {
        "current_stage": "completed" if ok else "failed",
        "message": "Rendered LaTeX report" if ok else str(error),
        "last_progress_at": finished_at,
        "progress_pct": 100.0 if ok else 0.0,
    }
    step = record.steps[0]
    step.status = "succeeded" if ok else "failed"
    step.finished_at = finished_at
    step.error = error
    step.result_path = str((logs_dir / "latex_report_render.json").relative_to(run_dir))
    _save_run(record)
    return result_payload


# ---------------------------------------------------------------------------
# Run artifact access (artifact_list / read_text / get_metadata / read_bytes)
# Extracted to mcp/routers/artifacts.py. Importing it registers those tools
# on the shared FastMCP instance (import side effect).
# ---------------------------------------------------------------------------
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    artifacts as _artifacts_router,
)


@mcp.tool()
def kg_search_nodes(
    query: str,
    node_types: list[str] | None = None,
    limit: int = 20,
    allow_degraded: bool = False,
) -> dict[str, Any]:
    """Search BR-KG nodes (direct Neo4j via query_service; read-only)."""
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    try:
        from brain_researcher.services.br_kg import query_service

        items = _call_kg_query_with_timeout(
            query_service.search_nodes,
            query,
            node_types=node_types,
            limit=int(limit),
            timeout_s=timeout_s,
        )
        return {
            "ok": True,
            "items": [
                {
                    "kg_id": it.kg_id,
                    "element_id": it.element_id,
                    "label": it.label,
                    "node_type": it.node_type,
                    "score": it.score,
                }
                for it in items
            ],
        }
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_search_nodes",
                    payload={"items": []},
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_search_nodes",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


def _kg_id_variants(raw_id: str) -> list[str]:
    value = (raw_id or "").strip()
    if not value:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str | None) -> None:
        if not candidate:
            return
        normalized = candidate.strip()
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        variants.append(normalized)

    compact = re.sub(r"\s+", "", value)
    _add(value)
    _add(value.lower())
    _add(compact)
    _add(compact.lower())

    pmid_match = re.match(r"^\s*(?:pmid[:\s]*)?([0-9]{5,9})\s*$", value, re.IGNORECASE)
    if pmid_match:
        pmid = pmid_match.group(1)
        _add(pmid)
        _add(f"pmid:{pmid}")

    doi_match = re.match(
        r"^\s*(?:doi[:\s]*)?(10\.[0-9]{4,9}/\S+)\s*$",
        value,
        re.IGNORECASE,
    )
    if doi_match:
        doi = re.sub(r"\s+", "", doi_match.group(1)).lower().strip(".,;:)]}")
        if doi:
            _add(doi)
            _add(f"doi:{doi}")

    return variants


@mcp.tool()
def kg_get_node(kg_id: str, allow_degraded: bool = False) -> dict[str, Any]:
    """Fetch a single KG node with trimmed properties + neighbor IDs."""
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    try:
        from brain_researcher.services.br_kg import query_service

        node = None
        for candidate in _kg_id_variants(kg_id):
            node = _call_kg_query_with_timeout(
                query_service.node_details,
                candidate,
                timeout_s=timeout_s,
            )
            if node is not None:
                break
        if node is None:
            return {"ok": False, "error": f"node not found: {kg_id}"}
        return {
            "ok": True,
            "node": {
                "kg_id": node.kg_id,
                "element_id": node.element_id,
                "label": node.label,
                "node_type": node.node_type,
                "score": node.score,
                "properties": node.properties,
            },
        }
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_get_node",
                    payload={"node": None},
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_get_node",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_neighbors(
    kg_id: str,
    relation_types: list[str] | None = None,
    direction: enum_str(_KG_NEIGHBOR_DIRECTION_ENUM, "traversal direction") = "both",
    limit: int = 25,
    allow_degraded: bool = False,
) -> dict[str, Any]:
    """List neighbors for a KG node with relation metadata."""
    relation_types = as_str_list(relation_types) or None
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    try:
        from brain_researcher.services.br_kg import query_service

        items = _call_kg_query_with_timeout(
            query_service.neighbors,
            kg_id,
            relation_types=relation_types,
            direction=direction,
            limit=int(limit),
            timeout_s=timeout_s,
        )
        return {"ok": True, "items": items}
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_neighbors",
                    payload={"items": []},
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_neighbors",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_search_datasets(
    text: str | None = None,
    task_ids: list[str] | None = None,
    modality: str | None = None,
    min_subjects: int | None = None,
    species: str | None = None,
    limit: int = 20,
    allow_degraded: bool = False,
) -> dict[str, Any]:
    """Search BR-KG dataset subgraph (direct Neo4j; read-only)."""
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    try:
        from brain_researcher.services.br_kg import query_service

        datasets = _call_kg_query_with_timeout(
            query_service.search_datasets,
            text=text,
            task_ids=task_ids,
            modality=modality,
            min_subjects=min_subjects,
            species=species,
            limit=int(limit),
            timeout_s=timeout_s,
        )
        return {
            "ok": True,
            "items": [
                {
                    "dataset_id": d.dataset_id,
                    "title": d.title,
                    "tasks": d.tasks,
                    "modalities": d.modalities,
                    "n_subjects": d.n_subjects,
                    "species": d.species,
                    "kg_id": d.kg_id,
                }
                for d in datasets
            ],
        }
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_search_datasets",
                    payload={"items": []},
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_search_datasets",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def dataset_get_resources(
    dataset_ref: str,
    dataset_version: str | None = None,
) -> dict[str, Any]:
    """Resolve lightweight dataset resources (local path/BIDS path, derivatives, URLs)."""
    try:
        from brain_researcher.services.br_kg import query_service

        resources = query_service.dataset_resources(
            dataset_ref,
            dataset_version=dataset_version,
        )
        if resources is None:
            return {"ok": False, "error": f"dataset not found: {dataset_ref}"}
        return {"ok": True, "resources": asdict(resources)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _resource_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=False)


def _resource_type_hint(schema: dict[str, Any]) -> str | None:
    value = schema.get("type")
    if isinstance(value, str) and value:
        return value
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        hints = [
            str(item.get("type")).strip()
            for item in any_of
            if isinstance(item, dict) and str(item.get("type") or "").strip()
        ]
        if hints:
            unique: list[str] = []
            for hint in hints:
                if hint not in unique:
                    unique.append(hint)
            return "|".join(unique)
    return None


def _summarize_schema_properties(
    schema: dict[str, Any] | None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = {
        str(name).strip()
        for name in (schema.get("required") or [])
        if str(name).strip()
    }
    summary: list[dict[str, Any]] = []
    for name, raw_prop in properties.items():
        if len(summary) >= limit:
            break
        prop = raw_prop if isinstance(raw_prop, dict) else {}
        entry: dict[str, Any] = {
            "name": str(name),
            "required": str(name) in required,
        }
        type_hint = _resource_type_hint(prop)
        if type_hint:
            entry["type"] = type_hint
        description = str(prop.get("description") or "").strip()
        if description:
            entry["description"] = description
        if "default" in prop:
            entry["default"] = prop.get("default")
        summary.append(entry)
    return summary


def _strip_agent_local_warning(description: str) -> str:
    text = str(description or "").strip()
    prefix = str(AGENT_LOCAL_EXECUTION_WARNING or "").strip()
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :].strip()
    return text


def _tool_resource_payload(tool_id: str) -> dict[str, Any]:
    response = tool_get(tool_id, include_schema=True)
    if response.get("ok") is not True:
        return {
            "ok": False,
            "resource_kind": "tool",
            "tool_id": tool_id,
            "error": response.get("error") or "unknown_tool",
            "message": response.get("message"),
        }

    tool = response.get("tool") if isinstance(response.get("tool"), dict) else {}
    schema = (
        tool.get("json_schema") if isinstance(tool.get("json_schema"), dict) else {}
    )
    resolved_name = str(tool.get("name") or tool_id).strip() or tool_id
    summary = _strip_agent_local_warning(str(tool.get("description") or ""))
    workflow_only = bool(response.get("workflow_only"))
    example_br_usage = {
        "discover": f'br.search("{resolved_name}")',
        "recipe": f'br.recipe("{tool_id}", {{"...": "..."}})',
    }
    if not workflow_only:
        example_br_usage["execute"] = f'br.execute("{tool_id}", {{"...": "..."}})'
    return {
        "ok": True,
        "resource_kind": "tool",
        "tool_id": tool_id,
        "name": resolved_name,
        "summary": summary,
        "backend": tool.get("backend"),
        "requires_runtime": tool.get("requires_runtime"),
        "execution_story_kind": tool.get("execution_story_kind"),
        "supported_recipe_targets": tool.get("supported_recipe_targets") or [],
        "execution_recipe_available": bool(tool.get("execution_recipe_available")),
        "workflow_only": workflow_only,
        "important_params": _summarize_schema_properties(schema),
        "example_br_usage": example_br_usage,
        "notes": [response.get("message")] if response.get("message") else [],
    }


def _dataset_resource_payload(dataset_ref: str) -> dict[str, Any]:
    response = dataset_get_resources(dataset_ref)
    if response.get("ok") is not True:
        return {
            "ok": False,
            "resource_kind": "dataset",
            "dataset_ref": dataset_ref,
            "error": response.get("error") or "dataset_not_found",
        }

    resources = (
        response.get("resources") if isinstance(response.get("resources"), dict) else {}
    )
    metadata = (
        resources.get("dataset_metadata")
        if isinstance(resources.get("dataset_metadata"), dict)
        else {}
    )
    readiness = (
        resources.get("readiness")
        if isinstance(resources.get("readiness"), dict)
        else {}
    )
    remote_urls = (
        resources.get("remote_urls")
        if isinstance(resources.get("remote_urls"), dict)
        else {}
    )
    return {
        "ok": True,
        "resource_kind": "dataset",
        "dataset_ref": dataset_ref,
        "resolved_dataset_id": resources.get("resolved_dataset_id"),
        "display_name": resources.get("display_name") or resources.get("dataset_name"),
        "source_repo": resources.get("source_repo"),
        "modalities": metadata.get("modalities") or [],
        "tasks": metadata.get("tasks") or [],
        "local_path": resources.get("local_path"),
        "bids_path": resources.get("bids_path"),
        "available_derivatives": resources.get("available_derivatives") or [],
        "remote_urls": remote_urls,
        "readiness": {
            "status": readiness.get("status"),
            "reason": readiness.get("reason"),
            "note": readiness.get("note"),
        },
        "example_br_usage": {
            "recipe": 'br.recipe("workflow_preprocessing_qc", {"bids_dir": "<bids_path>", "output_dir": "<output_dir>"})',
            "execute": 'br.execute("extract_timeseries", {"img": "<bold.nii.gz>", "atlas": "<atlas.nii.gz>"})',
        },
    }


def _workflow_resource_payload(workflow_id: str) -> dict[str, Any]:
    workflow = next(
        (
            dict(row)
            for row in _workflow_search_rows()
            if isinstance(row, dict) and str(row.get("id") or "").strip() == workflow_id
        ),
        None,
    )
    if workflow is None:
        return {
            "ok": False,
            "resource_kind": "workflow",
            "workflow_id": workflow_id,
            "error": f"Unknown workflow: {workflow_id}",
        }

    workflow.update(recipe_card_metadata(workflow_id, workflow_entry=workflow))
    workflow["params_summary"] = _workflow_param_schema_summary(workflow.get("params"))
    workflow.pop("runtime", None)
    workflow.pop("impl", None)
    workflow.pop("recipe_family", None)
    return {
        "ok": True,
        "resource_kind": "workflow",
        "workflow_id": workflow_id,
        "summary": workflow.get("description"),
        "stage": workflow.get("stage"),
        "modalities": workflow.get("modalities") or [],
        "primary_target": workflow.get("primary_target"),
        "supported_recipe_targets": workflow.get("supported_recipe_targets") or [],
        "params_summary": workflow.get("params_summary") or {},
        "example_br_usage": {
            "recipe": f'br.recipe("{workflow_id}", {{"...": "..."}})',
        },
    }


@mcp.resource(
    "tool://{tool_id}",
    name="tool_resource",
    title="BR tool resource",
    description="Concise Brain Researcher tool context for external coding agents.",
    mime_type="application/json",
)
def tool_resource(tool_id: str) -> str:
    return _resource_json_text(_tool_resource_payload(tool_id))


@mcp.resource(
    "dataset://{dataset_ref}",
    name="dataset_resource",
    title="BR dataset resource",
    description="Concise Brain Researcher dataset context for external coding agents.",
    mime_type="application/json",
)
def dataset_resource(dataset_ref: str) -> str:
    return _resource_json_text(_dataset_resource_payload(dataset_ref))


@mcp.resource(
    "workflow://{workflow_id}",
    name="workflow_resource",
    title="BR workflow resource",
    description="Concise Brain Researcher workflow context for external coding agents.",
    mime_type="application/json",
)
def workflow_resource(workflow_id: str) -> str:
    return _resource_json_text(_workflow_resource_payload(workflow_id))


@mcp.tool()
def kg_related_datasets(
    kg_id: str, limit: int = 10, allow_degraded: bool = False
) -> dict[str, Any]:
    """List datasets connected to a KG node (best-effort)."""
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    try:
        from brain_researcher.services.br_kg import query_service

        items = _call_kg_query_with_timeout(
            query_service.related_datasets,
            kg_id,
            limit=int(limit),
            timeout_s=timeout_s,
        )
        return {
            "ok": True,
            "items": [
                {
                    "dataset_id": d.dataset_id,
                    "title": d.title,
                    "tasks": d.tasks,
                    "modalities": d.modalities,
                    "n_subjects": d.n_subjects,
                    "species": d.species,
                    "kg_id": d.kg_id,
                }
                for d in items
            ],
        }
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_related_datasets",
                    payload={"items": []},
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_related_datasets",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_behavior_to_fmri_retrieval(
    seed_id: str | None = None,
    label: str | None = None,
    name: str | None = None,
    limit: int = 12,
    max_maps: int = 20,
    max_paths: int = 20,
    max_regions_per_map: int = 8,
    max_behavior_neighbors: int = 4,
    min_behavior_similarity: float = 0.0,
    allow_degraded: bool = False,
) -> dict[str, Any]:
    """Retrieve task-fMRI evidence for a behavior seed such as a Psych-101 task or experiment."""
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    try:
        from brain_researcher.services.br_kg import query_service

        result = _call_kg_query_with_timeout(
            query_service.behavior_to_fmri_retrieval,
            seed_id=seed_id,
            label=label,
            name=name,
            limit=int(limit),
            max_maps=int(max_maps),
            max_paths=int(max_paths),
            max_regions_per_map=int(max_regions_per_map),
            max_behavior_neighbors=int(max_behavior_neighbors),
            min_behavior_similarity=float(min_behavior_similarity),
            timeout_s=timeout_s,
        )
        if isinstance(result, dict) and result.get("error"):
            return {"ok": False, **result}
        return {"ok": True, **(result if isinstance(result, dict) else {"items": []})}
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_behavior_to_fmri_retrieval",
                    payload={"items": [], "seed_tasks": [], "summary": {}},
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_behavior_to_fmri_retrieval",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_list_dataset_onvoc_links(
    onvoc_id: str | None = None,
    page: int = 1,
    page_size: int = 100,
    allow_degraded: bool = False,
) -> dict[str, Any]:
    """List direct Dataset->ONVOC links in stable pages (direct Neo4j; read-only)."""
    timeout_s = _resolve_kg_read_timeout_s()
    started_at = time.perf_counter()
    page_num = max(1, int(page))
    per_page = max(1, min(int(page_size), 500))
    try:
        from brain_researcher.services.br_kg import query_service

        result = _call_kg_query_with_timeout(
            query_service.list_dataset_onvoc_links,
            onvoc_id=onvoc_id,
            page=page_num,
            page_size=per_page,
            timeout_s=timeout_s,
        )
        items = result.get("items", []) if isinstance(result, dict) else []
        return {
            "ok": True,
            "items": [asdict(item) for item in items],
            "page": int(result.get("page", page_num)),
            "page_size": int(result.get("page_size", per_page)),
            "total": int(result.get("total", 0)),
            "has_more": bool(result.get("has_more", False)),
        }
    except Exception as exc:
        if _is_timeout_like_exception(exc):
            query_time_s = time.perf_counter() - started_at
            if allow_degraded:
                return _build_kg_timeout_degraded_response(
                    tool_name="kg_list_dataset_onvoc_links",
                    payload={
                        "items": [],
                        "page": page_num,
                        "page_size": per_page,
                        "total": 0,
                        "has_more": False,
                    },
                    query_time_s=query_time_s,
                    timeout_s=timeout_s,
                )
            return _build_kg_degraded_blocked_response(
                tool_name="kg_list_dataset_onvoc_links",
                query_time_s=query_time_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )
        return {"ok": False, "error": str(exc)}


def _kg_seed_suggestions_for_question(question: str) -> list[dict[str, str]]:
    q = str(question or "").strip().lower()
    if not q:
        return []
    tokens = set(_tokenize_search_query(q))
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(query: str, reason: str) -> None:
        key = query.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        suggestions.append({"query": query, "reason": reason})

    if "default mode" in q or "dmn" in tokens or {"default", "mode"} <= tokens:
        _add(
            "default mode network",
            "Use the canonical network name as the seed entity.",
        )
    if "resting-state" in q or "resting" in tokens or "rsfmri" in tokens:
        _add(
            "resting-state fMRI",
            "Start from the acquisition/analysis family instead of the full question.",
        )
    if "fmri" in tokens or "bold" in tokens:
        _add("fMRI", "Use the modality as a broad seed.")
    if any(tok.startswith("connect") for tok in tokens):
        _add(
            "connectome",
            "Map connectivity wording to the KG connectome concept.",
        )
    if "atlas" in tokens or any(tok.startswith("parcell") for tok in tokens):
        _add(
            "atlas-based signal extraction",
            "Use the analysis primitive as a seed for workflow discovery.",
        )
    if "workflow" in tokens and any(tok.startswith("connect") for tok in tokens):
        _add(
            "workflow_rest_connectome_e2e",
            "Use the canonical workflow id when the question is workflow-oriented.",
        )

    return suggestions[:6]


@mcp.tool()
def kg_multihop_qa(
    question: str,
    max_hops: int = 3,
    mode: enum_str(
        _KG_MULTIHOP_MODE_ENUM, "traversal mode (aliases like breadth_first accepted)"
    ) = "breadth_first",
    max_results: int = 50,
    allowed_edge_types: list[str] | None = None,
    return_subgraph: bool = False,
    allow_degraded: bool = False,
    semantic: bool = False,
) -> dict[str, Any]:
    """Answer KG questions via multi-hop traversal (summary-first MCP payload)."""

    def _resolve_kg_multihop_timeout_s() -> float:
        configured = _parse_timeout(os.getenv("BR_MCP_KG_MULTIHOP_TIMEOUT_S"))
        if configured is None:
            configured = _parse_timeout(os.getenv("BR_KG_MULTIHOP_TOOL_BUDGET_S"))
        if configured is None:
            configured = _parse_timeout(os.getenv("BR_MCP_TOOL_TIMEOUT_S"))
        if configured is None:
            configured = 45.0
        # Keep a hard cap below common 120s client timeouts.
        return max(1.0, min(float(configured), 110.0))

    def _normalize_completion_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(summary or {})
        degraded = bool(normalized.get("degraded"))
        completion_state = str(normalized.get("completion_state") or "").strip().lower()
        if completion_state not in {"complete", "partial", "degraded"}:
            completion_state = "degraded" if degraded else "complete"
        if degraded and completion_state != "degraded":
            completion_state = "degraded"
        if completion_state == "degraded" and not degraded:
            normalized["degraded"] = True
            degraded = True
        if completion_state == "degraded":
            degraded_stage = str(normalized.get("degraded_stage") or "").strip()
            if not degraded_stage:
                degraded_reason = str(normalized.get("degraded_reason") or "").strip()
                if ":" in degraded_reason:
                    degraded_stage = degraded_reason.split(":", 1)[1].strip()
                elif degraded_reason:
                    degraded_stage = degraded_reason
            if degraded_stage:
                normalized["degraded_stage"] = degraded_stage
        normalized["completion_state"] = completion_state
        if "degraded" not in normalized:
            normalized["degraded"] = bool(degraded)
        return normalized

    def _build_degraded_timeout_result(timeout_s: float) -> dict[str, Any]:
        max_hops_i = int(max_hops) if isinstance(max_hops, int | float) else 3
        if max_hops_i < 1:
            max_hops_i = 1
        warning = (
            f"kg_multihop_qa timed out after {timeout_s:.1f}s; "
            "returning degraded response with empty traversal results"
        )
        result: dict[str, Any] = {
            "summary": {
                "question": question,
                "max_hops": max_hops_i,
                "hops_used": 0,
                "n_seed_entities": 0,
                "n_paths": 0,
                "n_nodes_traversed": 0,
                "n_edges_traversed": 0,
                "query_time_s": round(float(timeout_s), 3),
                "reasoning_method": "kg_multi_hop_traversal",
                "mode": str(mode),
                "degraded": True,
                "degraded_reason": "mcp_timeout",
                "completion_state": "degraded",
                "degraded_stage": "mcp_timeout",
                "runtime_budget_s": round(float(timeout_s), 3),
            },
            "answer": (
                "Timed out while running multi-hop traversal; "
                "returned degraded empty result."
            ),
            "seed_entities": [],
            "top_paths": [],
            "warnings": [warning],
        }
        seed_suggestions = _kg_seed_suggestions_for_question(question)
        if seed_suggestions:
            result["seed_suggestions"] = seed_suggestions
        if return_subgraph:
            result["subgraph"] = {"nodes": [], "edges": []}
        return result

    try:
        from brain_researcher.services.tools.kg_multihop_qa_tool import KGMultihopQATool

        timeout_s = _resolve_kg_multihop_timeout_s()
        result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

        def _runner() -> None:
            try:
                with semantic_matching_scope(semantic):
                    raw_result = KGMultihopQATool().run(
                        question=question,
                        max_hops=max_hops,
                        mode=mode,
                        max_results=max_results,
                        allowed_edge_types=allowed_edge_types,
                        return_subgraph=return_subgraph,
                        semantic=semantic,
                    )
                result_queue.put({"ok": True, "raw": raw_result})
            except Exception as exc:  # pragma: no cover - defensive
                result_queue.put({"ok": False, "error": str(exc)})

        worker = threading.Thread(
            target=_runner,
            name="kg_multihop_qa_runner",
            daemon=True,
        )
        worker.start()

        try:
            payload = result_queue.get(timeout=timeout_s)
        except queue.Empty:
            if allow_degraded:
                degraded_result = _build_degraded_timeout_result(timeout_s)
                degraded_summary = degraded_result.get("summary", {})
                return {
                    "ok": True,
                    "result": degraded_result,
                    "warnings": list(degraded_result.get("warnings") or []),
                    "completion_state": degraded_summary.get("completion_state"),
                    "degraded_reason": degraded_summary.get("degraded_reason"),
                    "execution_trace": [
                        "kg_query_started",
                        "kg_timeout",
                        "degraded_returned",
                    ],
                }
            return _build_kg_degraded_blocked_response(
                tool_name="kg_multihop_qa",
                query_time_s=timeout_s,
                degraded_reason="mcp_timeout",
                error="kg_query_timeout",
            )

        if not payload.get("ok"):
            error_message = str(payload.get("error") or "kg_multihop_qa_failed")
            response: dict[str, Any] = {
                "ok": False,
                "error": error_message,
            }
            seed_suggestions = _kg_seed_suggestions_for_question(question)
            if seed_suggestions and "seed" in error_message.lower():
                response["seed_suggestions"] = seed_suggestions
            return response

        raw = payload.get("raw")
        if not isinstance(raw, dict):
            return {"ok": False, "error": "invalid_tool_response"}

        if raw.get("status") != "success":
            error_message = str(raw.get("error") or "kg_multihop_qa_failed")
            response = {
                "ok": False,
                "error": error_message,
            }
            seed_suggestions = _kg_seed_suggestions_for_question(question)
            if seed_suggestions and "seed" in error_message.lower():
                response["seed_suggestions"] = seed_suggestions
            return response

        data = raw.get("data")
        if not isinstance(data, dict):
            data = {}
        legacy_outputs = data.get("outputs")
        if not isinstance(legacy_outputs, dict):
            legacy_outputs = {}
        legacy_outputs_consumed = False

        def _coalesce(key: str, expected_type: type | tuple[type, ...]) -> Any:
            nonlocal legacy_outputs_consumed
            top_level_value = data.get(key)
            if isinstance(top_level_value, expected_type):
                return top_level_value
            legacy_value = legacy_outputs.get(key)
            if isinstance(legacy_value, expected_type):
                legacy_outputs_consumed = True
                return legacy_value
            return None

        summary = _coalesce("summary", dict)
        if not isinstance(summary, dict):
            summary = {}
        summary = _normalize_completion_summary(summary)

        seed_entities = _coalesce("seed_entities", list)
        if not isinstance(seed_entities, list):
            seed_entities = []

        paths = _coalesce("paths", list)
        if not isinstance(paths, list):
            paths = _coalesce("top_paths", list)
        if not isinstance(paths, list):
            paths = []

        warnings = _coalesce("warnings", list)
        if not isinstance(warnings, list):
            warnings = []
        warning_messages = [str(w) for w in warnings]

        answer_value = data.get("answer")
        if answer_value is None and "answer" in legacy_outputs:
            legacy_outputs_consumed = True
            answer_value = legacy_outputs.get("answer")

        if (
            legacy_outputs_consumed
            and KG_MULTIHOP_LEGACY_OUTPUTS_WARNING not in warning_messages
        ):
            warning_messages.append(KG_MULTIHOP_LEGACY_OUTPUTS_WARNING)

        result: dict[str, Any] = {
            "summary": summary,
            "answer": str(answer_value or ""),
            "seed_entities": seed_entities,
            "top_paths": paths[:3],
            "warnings": warning_messages,
        }
        seed_suggestions = _kg_seed_suggestions_for_question(question)
        if seed_suggestions and not seed_entities:
            result["seed_suggestions"] = seed_suggestions

        if return_subgraph:
            subgraph = _coalesce("subgraph", dict)
            if not isinstance(subgraph, dict):
                subgraph = {"nodes": [], "edges": []}
            result["subgraph"] = subgraph

        if summary.get("degraded"):
            degraded_reason = str(summary.get("degraded_reason") or "degraded")
            if not allow_degraded:
                return _build_kg_degraded_blocked_response(
                    tool_name="kg_multihop_qa",
                    query_time_s=float(summary.get("query_time_s") or 0.0),
                    degraded_reason=degraded_reason,
                    error=(
                        "kg_query_timeout"
                        if degraded_reason == "mcp_timeout"
                        else "kg_query_degraded"
                    ),
                )
            return {
                "ok": True,
                "result": result,
                "warnings": warning_messages,
                "completion_state": summary.get("completion_state"),
                "degraded_reason": degraded_reason,
                "execution_trace": ["kg_query_started", "degraded_returned"],
            }

        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_verify_hypothesis(
    hypothesis: str,
    entity_hints: list[str] | None = None,
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    strictness: str = "high_recall",
    min_evidence_score: float | None = None,
    include_subgraph: bool = True,
    include_path_details: bool = True,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: enum_str(
        ("broad", "strict"), "candidate recall lane"
    ) = "broad",
    rerank_candidate_cap: int = 50,
    hypothesis_budget_seconds: float = 60.0,
    semantic: bool = False,
) -> dict[str, Any]:
    """Verify a hypothesis with KG evidence and highlight supporting/conflicting findings."""
    with semantic_matching_scope(semantic):
        if not str(hypothesis or "").strip():
            return {"ok": False, "error": "hypothesis is required"}

        try:
            from brain_researcher.services.br_kg import query_service

            prior_claim_context = _compact_claim_memory_context(
                hypothesis,
                entity_hints=entity_hints,
                allowed_node_types=allowed_node_types,
                limit=3,
            )
            result = query_service.verify_hypothesis(
                hypothesis=hypothesis,
                entity_hints=entity_hints,
                allowed_node_types=allowed_node_types,
                max_evidence=max_evidence,
                max_paths=max_paths,
                strictness=strictness,
                min_evidence_score=min_evidence_score,
                include_subgraph=include_subgraph,
                include_path_details=include_path_details,
                confidence_scoring_version=confidence_scoring_version,
                candidate_lane_mode=candidate_lane_mode,
                rerank_candidate_cap=rerank_candidate_cap,
                hypothesis_budget_seconds=hypothesis_budget_seconds,
            )
            if not isinstance(result, dict):
                return {"ok": False, "error": "invalid_tool_response"}
            derived_memory = (
                dict(result.get("derived_memory"))
                if isinstance(result.get("derived_memory"), dict)
                else {}
            )
            existing_claim_memory = (
                dict(derived_memory.get("claim_memory"))
                if isinstance(derived_memory.get("claim_memory"), dict)
                else {}
            )
            merged_claim_memory = dict(prior_claim_context)
            merged_claim_memory.update(existing_claim_memory)
            derived_memory["claim_memory"] = merged_claim_memory
            persistence = _persist_verified_claim_memory(
                hypothesis=hypothesis,
                result=result,
                claim_memory_context=merged_claim_memory,
                entity_hints=entity_hints,
                allowed_node_types=allowed_node_types,
                strictness=strictness,
                confidence_scoring_version=confidence_scoring_version,
                candidate_lane_mode=candidate_lane_mode,
            )
            if persistence:
                derived_memory["claim_memory"] = {
                    **merged_claim_memory,
                    "persistence": persistence,
                }
                if not persistence.get("ok", True):
                    warnings = list(result.get("warnings") or [])
                    warnings.append("claim_memory_persist_failed")
                    result["warnings"] = warnings
            result["derived_memory"] = derived_memory
            return {"ok": True, "result": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


@mcp.tool()
def verify_hypothesis_with_kg(
    hypothesis: str,
    entity_hints: list[str] | None = None,
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    strictness: str = "high_recall",
    min_evidence_score: float | None = None,
    include_subgraph: bool = True,
    include_path_details: bool = True,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: str = "broad",
    rerank_candidate_cap: int = 50,
    hypothesis_budget_seconds: float = 60.0,
    semantic: bool = False,
) -> dict[str, Any]:
    """Alias of `kg_verify_hypothesis` with hypothesis-first naming."""
    param_keys = sorted(locals().keys())
    return _return_compat_alias_response(
        "verify_hypothesis_with_kg",
        kg_verify_hypothesis(
            hypothesis=hypothesis,
            entity_hints=entity_hints,
            allowed_node_types=allowed_node_types,
            max_evidence=max_evidence,
            max_paths=max_paths,
            strictness=strictness,
            min_evidence_score=min_evidence_score,
            include_subgraph=include_subgraph,
            include_path_details=include_path_details,
            confidence_scoring_version=confidence_scoring_version,
            candidate_lane_mode=candidate_lane_mode,
            rerank_candidate_cap=rerank_candidate_cap,
            hypothesis_budget_seconds=hypothesis_budget_seconds,
            semantic=semantic,
        ),
        param_keys=param_keys,
    )


def _kg_result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if result is None:
        return {}
    return {"value": result}


def _coerce_non_empty_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _coerce_csv_or_non_empty_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        if not any(sep in value for sep in (",", "\n", ";")):
            return _coerce_non_empty_str_list([value])
        return _coerce_non_empty_str_list(re.split(r"[\n,;]+", value))
    return _coerce_non_empty_str_list(value)


def _compact_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


def _compact_claim_memory_context(
    hypothesis: str,
    *,
    entity_hints: list[str] | None = None,
    allowed_node_types: list[str] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    query_parts = [str(hypothesis or "").strip()]
    for values in (entity_hints, allowed_node_types):
        if not values:
            continue
        query_parts.extend(str(value).strip() for value in values if str(value).strip())
    search_query = " ".join(part for part in query_parts if part)
    safe_limit = max(1, min(int(limit), 5))
    filters = {"status": "active"}

    try:
        search_resp = MemoryStore(run_root=_runstore.RUN_ROOT).search(
            search_query,
            card_type="claim_memory",
            filters=filters,
            limit=safe_limit,
        )
        if not isinstance(search_resp, dict) or not search_resp.get("ok"):
            error_message = "memory_search_failed"
            if isinstance(search_resp, dict):
                error_message = str(
                    search_resp.get("error")
                    or search_resp.get("message")
                    or error_message
                )
            return {
                "ok": False,
                "query": search_query,
                "card_type": "claim_memory",
                "filters": filters,
                "count": 0,
                "cards": [],
                "error": error_message,
            }

        cards: list[dict[str, Any]] = []
        for raw_card in list(search_resp.get("cards") or [])[:safe_limit]:
            if not isinstance(raw_card, dict):
                continue
            family_identity = extract_claim_family_identity(raw_card)
            related_claims: list[dict[str, Any]] = []
            for raw_link in list(raw_card.get("related_claims") or [])[:3]:
                if not isinstance(raw_link, dict):
                    continue
                related_claims.append(
                    {
                        "claim_id": str(raw_link.get("claim_id") or "").strip(),
                        "relation": str(raw_link.get("relation") or "").strip(),
                        "note": str(raw_link.get("note") or "").strip() or None,
                    }
                )

            compact_card: dict[str, Any] = {
                "card_id": raw_card.get("card_id"),
                "claim_text": raw_card.get("claim_text"),
                "claim_type": raw_card.get("claim_type"),
                "claim_polarity": raw_card.get("claim_polarity"),
                "confidence": raw_card.get("confidence"),
                "status": raw_card.get("status"),
                "target_ids": list(raw_card.get("target_ids") or [])[:5],
                "analytic_conditions": list(raw_card.get("analytic_conditions") or [])[
                    :5
                ],
                "source_run_ids": list(raw_card.get("source_run_ids") or [])[:3],
                "stable_key": str(raw_card.get("stable_key") or "").strip() or None,
                "canonical_claim_id": str(
                    family_identity.get("canonical_claim_id") or ""
                ).strip()
                or None,
                "canonical_target_id": str(
                    family_identity.get("canonical_target_id") or ""
                ).strip()
                or None,
            }
            if related_claims:
                compact_card["related_claims"] = related_claims
            cards.append(compact_card)

        claim_family_summary = summarize_claim_families(cards)
        return {
            "ok": True,
            "query": search_query,
            "card_type": "claim_memory",
            "filters": filters,
            "count": len(cards),
            "cards": cards,
            "claim_family_summary": claim_family_summary,
        }
    except Exception as exc:
        logger.warning("Claim memory retrieval failed in kg_verify_hypothesis: %s", exc)
        return {
            "ok": False,
            "query": search_query,
            "card_type": "claim_memory",
            "filters": filters,
            "count": 0,
            "cards": [],
            "error": str(exc),
        }


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _verification_claim_polarity(verdict: Any) -> str | None:
    key = str(verdict or "").strip().lower()
    if key == "supported":
        return "supports"
    if key == "conflicting":
        return "refutes"
    return None


_PERSISTABLE_CLAIM_RELATIONS = {
    "supports",
    "contradicts",
    "conditions",
    "refines",
    "supersedes",
}


def _verification_claim_confidence_bucket(value: Any) -> str:
    try:
        numeric = float(value)
    except Exception:
        return "preliminary"
    if numeric >= 0.8:
        return "strong"
    if numeric >= 0.55:
        return "moderate"
    return "preliminary"


def _verification_claim_analytic_conditions(
    result: dict[str, Any],
    *,
    strictness: str,
    confidence_scoring_version: str,
    candidate_lane_mode: str,
    allowed_node_types: list[str] | None,
) -> list[str]:
    return _coerce_non_empty_str_list(
        [
            f"strictness:{strictness}",
            f"candidate_lane_mode:{candidate_lane_mode}",
            f"confidence_scoring_version:{confidence_scoring_version}",
            f"evidence_mode:{result.get('evidence_mode')}",
            f"evidence_source_scope:{result.get('evidence_source_scope')}",
            *[
                f"allowed_node_type:{item}"
                for item in _coerce_non_empty_str_list(allowed_node_types)
            ],
        ]
    )


def _verification_claim_mapping(
    result: dict[str, Any],
    *,
    hypothesis: str,
) -> dict[str, Any]:
    normalized_claim = (
        dict(result.get("normalized_claim"))
        if isinstance(result.get("normalized_claim"), dict)
        else {}
    )
    claim_polarity = _verification_claim_polarity(result.get("verdict")) or "supports"
    mapping = build_verification_claim_mapping(
        hypothesis=hypothesis,
        normalized_claim=normalized_claim,
        verdict=claim_polarity,
    )
    return {
        "canonical_claim_id": mapping.get("canonical_claim_id"),
        "canonical_target_id": mapping.get("canonical_target_id"),
        "canonical_claim_text": mapping.get("canonical_claim_text")
        or normalize_claim_text(hypothesis),
        "target_ids": _coerce_non_empty_str_list(mapping.get("target_ids")),
        "target_type": mapping.get("target_type"),
        "claim_polarity": claim_polarity,
        "predicate": mapping.get("predicate"),
        "stable_key": mapping.get("stable_key"),
        "domain": mapping.get("domain"),
        "tags": _coerce_non_empty_str_list(mapping.get("tags")),
    }


def _verification_claim_evidence_refs(
    evidence_items: Any,
    *,
    source_run_id: str,
    canonical_claim_id: str,
    canonical_target_id: str,
    claim_text: str,
    confidence: Any,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, raw_item in enumerate(list(evidence_items or [])[:3]):
        if not isinstance(raw_item, dict):
            continue
        publication = (
            dict(raw_item.get("publication"))
            if isinstance(raw_item.get("publication"), dict)
            else {}
        )
        claim_block = (
            dict(raw_item.get("claim"))
            if isinstance(raw_item.get("claim"), dict)
            else {}
        )
        refs.append(
            {
                "run_id": source_run_id,
                "claim_id": canonical_claim_id,
                "paper_id": _normalize_optional_text(publication.get("kg_id")),
                "target_id": canonical_target_id,
                "metric": (
                    "evidence_score"
                    if isinstance(raw_item.get("score"), int | float)
                    else None
                ),
                "value": (
                    float(raw_item.get("score"))
                    if isinstance(raw_item.get("score"), int | float)
                    else None
                ),
                "confidence": _verification_claim_confidence_bucket(
                    raw_item.get("score") or confidence
                ),
                "source_ref": _normalize_optional_text(raw_item.get("evidence_id"))
                or f"kg_verify_hypothesis:evidence:{index}",
                "description": _normalize_optional_text(raw_item.get("description"))
                or _normalize_optional_text(raw_item.get("summary"))
                or _normalize_optional_text(raw_item.get("snippet"))
                or _normalize_optional_text(raw_item.get("preview"))
                or _normalize_optional_text(raw_item.get("text"))
                or _normalize_optional_text(claim_block.get("label"))
                or _normalize_optional_text(publication.get("label"))
                or claim_text,
            }
        )
    if refs:
        return refs
    return [
        {
            "run_id": source_run_id,
            "claim_id": canonical_claim_id,
            "target_id": canonical_target_id,
            "confidence": _verification_claim_confidence_bucket(confidence),
            "source_ref": "kg_verify_hypothesis",
            "description": claim_text,
        }
    ]


def _build_verified_claim_memory_payload(
    *,
    hypothesis: str,
    result: dict[str, Any],
    claim_memory_context: dict[str, Any],
    entity_hints: list[str] | None,
    allowed_node_types: list[str] | None,
    strictness: str,
    confidence_scoring_version: str,
    candidate_lane_mode: str,
) -> tuple[dict[str, Any] | None, str | None]:
    relation_summary = (
        dict(claim_memory_context.get("relation_summary"))
        if isinstance(claim_memory_context.get("relation_summary"), dict)
        else {}
    )
    relation = str(relation_summary.get("relation") or "").strip().lower()
    if relation not in _PERSISTABLE_CLAIM_RELATIONS:
        return None, "nonpersistable_relation"

    verdict = str(result.get("verdict") or "").strip().lower()
    claim_polarity = _verification_claim_polarity(verdict)
    if claim_polarity is None:
        return None, "non_directional_verdict"

    mapping = _verification_claim_mapping(result, hypothesis=hypothesis)
    claim_text = _normalize_optional_text(mapping.get("canonical_claim_text"))
    if not claim_text:
        return None, "missing_claim_text"

    source_run_id = (
        "verify_claim_"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    payload = {
        "source_run_ids": [source_run_id],
        "claim_text": claim_text,
        "claim_type": "verification",
        "claim_polarity": mapping.get("claim_polarity") or claim_polarity,
        "domain": mapping.get("domain") or mapping.get("target_type"),
        "target_ids": list(mapping.get("target_ids") or []),
        "analytic_conditions": _verification_claim_analytic_conditions(
            result,
            strictness=strictness,
            confidence_scoring_version=confidence_scoring_version,
            candidate_lane_mode=candidate_lane_mode,
            allowed_node_types=allowed_node_types,
        ),
        "supporting_evidence": (
            _verification_claim_evidence_refs(
                result.get("supporting_evidence"),
                source_run_id=source_run_id,
                canonical_claim_id=str(mapping.get("canonical_claim_id") or ""),
                canonical_target_id=str(mapping.get("canonical_target_id") or ""),
                claim_text=claim_text,
                confidence=result.get("confidence"),
            )
            if verdict == "supported"
            else []
        ),
        "conflicting_evidence": (
            _verification_claim_evidence_refs(
                result.get("conflicting_evidence"),
                source_run_id=source_run_id,
                canonical_claim_id=str(mapping.get("canonical_claim_id") or ""),
                canonical_target_id=str(mapping.get("canonical_target_id") or ""),
                claim_text=claim_text,
                confidence=result.get("confidence"),
            )
            if verdict == "conflicting"
            else []
        ),
        "confidence": _verification_claim_confidence_bucket(result.get("confidence")),
        "tags": _coerce_non_empty_str_list(
            [
                "kg_verify_hypothesis",
                f"relation:{relation}",
                f"verdict:{verdict}",
                f"canonical_claim_id:{mapping.get('canonical_claim_id')}",
                f"canonical_target_id:{mapping.get('canonical_target_id')}",
                *(list(mapping.get("tags") or [])[:6]),
                *(_coerce_non_empty_str_list(entity_hints)[:3]),
            ]
        ),
        "stable_key": mapping.get("stable_key"),
        "_skip_relation_derivation": True,
    }
    return payload, None


def _persist_verified_claim_memory(
    *,
    hypothesis: str,
    result: dict[str, Any],
    claim_memory_context: dict[str, Any],
    entity_hints: list[str] | None,
    allowed_node_types: list[str] | None,
    strictness: str,
    confidence_scoring_version: str,
    candidate_lane_mode: str,
) -> dict[str, Any]:
    payload, skip_reason = _build_verified_claim_memory_payload(
        hypothesis=hypothesis,
        result=result,
        claim_memory_context=claim_memory_context,
        entity_hints=entity_hints,
        allowed_node_types=allowed_node_types,
        strictness=strictness,
        confidence_scoring_version=confidence_scoring_version,
        candidate_lane_mode=candidate_lane_mode,
    )
    if payload is None:
        return {"ok": True, "persisted": False, "reason": skip_reason or "skipped"}

    try:
        write_resp = MemoryStore(run_root=_runstore.RUN_ROOT).write(
            "claim_memory", payload
        )
        card_id = (
            str(write_resp.get("card_id") or "").strip()
            if isinstance(write_resp, dict)
            else ""
        )
        relation_summary = (
            dict(claim_memory_context.get("relation_summary"))
            if isinstance(claim_memory_context.get("relation_summary"), dict)
            else {}
        )
        relation = str(relation_summary.get("relation") or "").strip().lower()
        relation_note = _normalize_optional_text(relation_summary.get("reason"))
        source_run_ids = list(payload.get("source_run_ids") or [])
        source_run_id = source_run_ids[0] if source_run_ids else None
        persisted_relation_events: list[dict[str, Any]] = []
        if card_id and relation in _PERSISTABLE_CLAIM_RELATIONS:
            for raw_card in list(claim_memory_context.get("cards") or []):
                if not isinstance(raw_card, dict):
                    continue
                rhs_claim_id = str(raw_card.get("card_id") or "").strip()
                if not rhs_claim_id or rhs_claim_id == card_id:
                    continue
                event_resp = MemoryStore(run_root=_runstore.RUN_ROOT).write(
                    "claim_relation_event",
                    {
                        "triggering_run_id": source_run_id,
                        "lhs_claim_id": card_id,
                        "rhs_claim_id": rhs_claim_id,
                        "relation_type": relation,
                        "note": relation_note,
                        "evidence_refs": [
                            {
                                "run_id": source_run_id,
                                "claim_id": card_id,
                                "confidence": _verification_claim_confidence_bucket(
                                    result.get("confidence")
                                ),
                                "source_ref": "kg_verify_hypothesis",
                                "description": payload.get("claim_text"),
                            }
                        ],
                    },
                )
                if isinstance(event_resp, dict):
                    persisted_relation_events.append(
                        dict(event_resp.get("card"))
                        if isinstance(event_resp.get("card"), dict)
                        else dict(event_resp.get("record") or {})
                    )
        return {
            "ok": bool(isinstance(write_resp, dict) and write_resp.get("ok")),
            "persisted": True,
            "card_id": (
                write_resp.get("card_id") if isinstance(write_resp, dict) else None
            ),
            "stable_key": (
                write_resp.get("stable_key") if isinstance(write_resp, dict) else None
            ),
            "canonical_claim_id": next(
                (
                    str(tag).split(":", 1)[1]
                    for tag in list(payload.get("tags") or [])
                    if str(tag).startswith("canonical_claim_id:")
                ),
                None,
            ),
            "canonical_target_id": next(
                (
                    str(tag).split(":", 1)[1]
                    for tag in list(payload.get("tags") or [])
                    if str(tag).startswith("canonical_target_id:")
                ),
                None,
            ),
            "relation_event_count": len(persisted_relation_events),
            "relation_types": sorted(
                {
                    str(item.get("relation_type") or "").strip()
                    for item in persisted_relation_events
                    if isinstance(item, dict)
                    and str(item.get("relation_type") or "").strip()
                }
            ),
        }
    except Exception as exc:
        logger.warning(
            "Claim memory persistence failed in kg_verify_hypothesis: %s", exc
        )
        return {
            "ok": False,
            "persisted": False,
            "error": str(exc),
        }


def _tool_result_payload(result: ToolResult) -> dict[str, Any]:
    payload = getattr(result, "data", None)
    if isinstance(payload, dict):
        return payload
    if payload is None:
        return {}
    return {"value": payload}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


_GAP_TYPE_RANKS: dict[str, int] = {
    "evidence": 0,
    "method": 1,
    "data": 2,
    "ontology": 3,
}
_GROUNDING_STATUS_RANKS: dict[str, int] = {"grounded": 0, "degraded": 1}
_VERDICT_RANKS: dict[str, int] = {
    "supported": 0,
    "uncertain": 1,
    "mixed": 2,
    "insufficient_evidence": 3,
    "conflicting": 4,
}
_QUALITY_BUCKET_RANKS: dict[str, int] = {
    "actual_idea_like": 0,
    "template_only": 1,
    "off_target": 2,
}
_REWRITE_STATUS_RANKS: dict[str, int] = {
    "rewritten": 0,
    "needs_rewrite": 1,
    "rejected": 2,
}


def _sort_rank(value: Any, ranks: dict[str, int]) -> tuple[int, str]:
    key = str(value or "").strip().lower()
    if key in ranks:
        return ranks[key], key
    return len(ranks), key


def _claim_memory_priority_rank_for_candidate_card(card: dict[str, Any]) -> int:
    priority_ranks = {
        "conflict_resolution": 0,
        "conditioning_resolution": 1,
        "conditioning_sensitive": 2,
        "background": 3,
        "unknown": 4,
        "low": 5,
        "conflict_risk": 6,
        "none": 7,
    }
    explicit_priority = str(card.get("claim_memory_priority") or "").strip().lower()
    explicit_rank = priority_ranks.get(explicit_priority, priority_ranks["none"])

    profile = card.get("claim_memory_profile")
    if not isinstance(profile, dict):
        provenance = card.get("provenance")
        if isinstance(provenance, dict):
            maybe_profile = provenance.get("claim_memory_profile")
            if isinstance(maybe_profile, dict):
                profile = maybe_profile
    if not isinstance(profile, dict):
        return explicit_rank
    profile_priority = str(profile.get("priority") or "").strip().lower()
    if profile_priority in priority_ranks:
        profile_rank = priority_ranks[profile_priority]
    else:
        try:
            n_conflicting = int(profile.get("n_conflicting") or 0)
            n_conditioning = int(profile.get("n_conditioning") or 0)
            n_supporting = int(profile.get("n_supporting") or 0)
        except Exception:
            return explicit_rank
        if n_conflicting > 0:
            profile_rank = priority_ranks["conflict_resolution"]
        elif n_conditioning > 0:
            profile_rank = priority_ranks["conditioning_sensitive"]
        elif n_supporting > 0:
            profile_rank = priority_ranks["background"]
        else:
            profile_rank = priority_ranks["none"]
    return min(explicit_rank, profile_rank)


def _candidate_card_rerank_key(
    card: dict[str, Any], idx: int
) -> tuple[int, int, int, int, int, int, str]:
    claim_memory_rank = _claim_memory_priority_rank_for_candidate_card(card)
    grounding_rank, grounding_key = _sort_rank(
        card.get("grounding_status"), _GROUNDING_STATUS_RANKS
    )
    gap_rank, gap_key = _sort_rank(card.get("gap_type"), _GAP_TYPE_RANKS)
    verdict = _sort_rank(
        (card.get("kg_verification") or {}).get("verdict"), _VERDICT_RANKS
    )
    quality_rank, quality_key = _sort_rank(
        card.get("quality_bucket"), _QUALITY_BUCKET_RANKS
    )
    rewrite_rank, rewrite_key = _sort_rank(
        card.get("rewrite_status"), _REWRITE_STATUS_RANKS
    )

    # Keep the rerank conservative: grounded and more actionable gaps come first,
    # but stable input order is preserved as the final tiebreaker.
    return (
        claim_memory_rank,
        grounding_rank,
        gap_rank,
        verdict[0],
        quality_rank,
        rewrite_rank,
        (
            f"{grounding_key}:{claim_memory_rank}:{gap_key}:"
            f"{quality_key}:{rewrite_key}:{idx:04d}"
        ),
    )


def _rerank_candidate_cards_for_mcp(
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked = sorted(
        enumerate(cards),
        key=lambda item: _candidate_card_rerank_key(item[1], item[0]),
    )
    return [dict(card) for _, card in ranked]


def _normalize_candidate_cards_for_mcp(
    raw_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw_card in enumerate(raw_cards, start=1):
        card = dict(raw_card)
        title = str(
            card.get("title") or card.get("label") or f"Candidate {idx}"
        ).strip()
        hypothesis = str(
            card.get("hypothesis") or card.get("summary") or card.get("statement") or ""
        ).strip()
        card_id = str(card.get("card_id") or card.get("id") or f"cand_{idx:02d}")
        card.update(
            {
                "card_id": card_id,
                "title": title,
                "hypothesis": hypothesis,
                "raw_hypothesis": str(card.get("raw_hypothesis") or "").strip(),
                "idea": str(card.get("idea") or "").strip(),
                "mechanism": str(card.get("mechanism") or "").strip(),
                "testable_hypothesis": str(
                    card.get("testable_hypothesis") or ""
                ).strip(),
                "rewrite_status": str(card.get("rewrite_status") or "").strip(),
                "quality_bucket": str(card.get("quality_bucket") or "").strip(),
                "rejection_reason": str(card.get("rejection_reason") or "").strip(),
                "gap_type": str(card.get("gap_type") or "").strip(),
                "gap_specification": str(card.get("gap_specification") or "").strip(),
                "gap_actionable": _coerce_bool(card.get("gap_actionable")),
                "semantic_fidelity_flags": list(
                    card.get("semantic_fidelity_flags") or []
                ),
                "taste_axis": str(card.get("taste_axis") or "").strip()
                or "unspecified",
                "minimal_discriminating_test": str(
                    card.get("minimal_discriminating_test") or ""
                ).strip(),
                "falsifier_hint": str(card.get("falsifier_hint") or "").strip(),
                "novelty_signal": str(card.get("novelty_signal") or "").strip(),
                "claim_memory_priority": str(
                    card.get("claim_memory_priority") or ""
                ).strip(),
                "claim_memory_reason": str(
                    card.get("claim_memory_reason") or ""
                ).strip(),
                "claim_memory_profile": dict(card.get("claim_memory_profile") or {}),
                "claim_memory_summary": str(
                    card.get("claim_memory_summary") or ""
                ).strip(),
                "claim_memory_resolution_hint": str(
                    card.get("claim_memory_resolution_hint") or ""
                ).strip(),
                "contradiction_probe": str(
                    card.get("contradiction_probe") or ""
                ).strip(),
                "topology_shift_probe": str(
                    card.get("topology_shift_probe") or ""
                ).strip(),
                "anomaly_flags": card.get("anomaly_flags", []),
                "supporting_paper_titles": list(
                    card.get("supporting_paper_titles") or []
                ),
                "evidence_source_scope": str(
                    card.get("evidence_source_scope") or ""
                ).strip(),
                "provenance": card.get("provenance", {}),
            }
        )
        provenance = card.get("provenance")
        claim_family_summary = dict(card.get("claim_family_summary") or {})
        if not claim_family_summary and isinstance(provenance, dict):
            claim_family_summary = dict(provenance.get("claim_family_summary") or {})
        card["claim_family_summary"] = claim_family_summary
        if isinstance(provenance, dict):
            sampled = provenance.get("sampled_hypothesis_verification")
            if isinstance(sampled, dict):
                sampled = {
                    **sampled,
                    "gap_type": card["gap_type"],
                    "gap_specification": card["gap_specification"],
                    "gap_actionable": card["gap_actionable"],
                }
                card["provenance"] = {
                    **provenance,
                    "sampled_hypothesis_verification": sampled,
                }
        normalized.append(card)
    return _rerank_candidate_cards_for_mcp(normalized)


def _rewrite_raw_workflow_candidate_cards_for_mcp(
    raw_cards: list[dict[str, Any]],
    *,
    query: str,
) -> list[dict[str, Any]]:
    """Re-evaluate weak raw workflow cards with the agent rewrite/filter path.

    Strong workflow cards are preserved as-is so we do not lose verified gap
    metadata, but cards that already look weak/template-like are sanitized and
    sent back through the agent-side rewrite logic instead of being accepted at
    face value.
    """

    rewritten_cards: list[dict[str, Any]] = []
    blocked_fields = {
        "idea",
        "mechanism",
        "prediction",
        "independent_variable",
        "dependent_variable",
        "predicted_direction",
        "testable_hypothesis",
        "quality_bucket",
        "rewrite_status",
        "rejection_reason",
        "gap_type",
        "gap_specification",
        "gap_actionable",
        "semantic_fidelity_flags",
        "minimal_discriminating_test",
        "falsifier_hint",
    }
    for raw_card in raw_cards:
        card = dict(raw_card)
        if _is_weak_baseline_candidate_card(card):
            for field_name in blocked_fields:
                card.pop(field_name, None)
            rewritten_cards.extend(rewrite_candidate_cards([card], query=query))
            continue
        rewritten_cards.append(card)
    return rewritten_cards


def _extract_candidate_cards_from_workflow_payload(
    payload: dict[str, Any],
    *,
    query: str,
    top_n: int,
) -> list[dict[str, Any]]:
    raw_cards = find_candidate_cards_payload(payload)
    if raw_cards:
        rewritten = _rewrite_raw_workflow_candidate_cards_for_mcp(
            raw_cards,
            query=query,
        )
        return _normalize_candidate_cards_for_mcp(rewritten[:top_n])

    workflow_result = find_workflow_result(payload)
    if workflow_result is None:
        return []

    generated = build_candidate_cards_from_workflow_result(
        workflow_result,
        query=query,
        top_n=top_n,
        memory_store=_get_mcp_memory_store(),
    )
    return _normalize_candidate_cards_for_mcp(generated)


def _extract_resolved_anchor_bundle_from_workflow_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    workflow_result = find_workflow_result(payload)
    if not isinstance(workflow_result, dict):
        return []

    steps = workflow_result.get("steps")
    if not isinstance(steps, dict):
        return []

    for step_id in ("leverage", "principle_state_init", "ood_sampling", "verify"):
        step_payload = steps.get(step_id)
        if not isinstance(step_payload, dict):
            continue
        data_payload = step_payload.get("data")
        if not isinstance(data_payload, dict):
            continue
        bundle = data_payload.get("resolved_anchor_bundle")
        if isinstance(bundle, list) and bundle:
            return [dict(item) for item in bundle if isinstance(item, dict)]
    return []


def _compact_deep_research_payload(result: dict[str, Any]) -> dict[str, Any]:
    report = result.get("result")
    if not isinstance(report, dict):
        report = _deep_research_result_payload(result)
    compact_report: dict[str, Any] | None = None
    if isinstance(report, dict):
        compact_report = {
            "status": report.get("status"),
            "status_reason": report.get("status_reason"),
            "summary": report.get("summary"),
            "synthesis_full_text": report.get("synthesis_full_text")
            or report.get("summary")
            or report.get("text"),
            "documents": list(report.get("documents") or [])[:10],
            "quality": report.get("quality"),
            "metadata": report.get("metadata"),
            "search_trails": report.get("search_trails"),
        }

    payload: dict[str, Any] = {
        "requested": True,
        "status": result.get("status"),
        "idempotency_key": result.get("idempotency_key"),
    }
    if compact_report is not None:
        payload["report"] = compact_report
    for key in ("error", "message", "error_type", "status_code"):
        if result.get(key) is not None:
            payload[key] = result.get(key)
    return payload


def _deep_research_result_payload(
    result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    payload = result.get("result")
    if isinstance(payload, dict):
        return dict(payload)

    data = result.get("data")
    if not isinstance(data, dict):
        return None

    normalized = dict(data)
    documents = normalized.get("documents")
    if not isinstance(documents, list):
        normalized["documents"] = [
            {
                "doc_id": f"doc_{idx + 1}",
                "title": item.get("title"),
                "url": item.get("url"),
                "raw_url": item.get("url"),
                "publisher": None,
                "published_at": None,
                "snippets": [],
            }
            for idx, item in enumerate(normalized.get("sources") or [])
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        ]

    if not normalized.get("synthesis_full_text"):
        normalized["synthesis_full_text"] = (
            normalized.get("summary") or normalized.get("text") or ""
        )

    if "raw" not in normalized:
        normalized["raw"] = (
            normalized.get("raw_response") or normalized.get("response") or {}
        )

    metadata = normalized.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    interaction_id = str(normalized.get("interaction_id") or "").strip()
    if interaction_id and not metadata.get("interaction_id"):
        metadata["interaction_id"] = interaction_id
    if metadata:
        normalized["metadata"] = metadata

    return normalized


def _build_deep_research_idea_cards_payload(
    *,
    deep_research_result: dict[str, Any] | None,
    query: str,
    top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    if not isinstance(deep_research_result, dict):
        return [], None, None
    try:
        payload = generate_deep_research_idea_cards_from_result(
            deep_research_result=deep_research_result,
            query=query,
            top_n=top_n,
        )
    except Exception as exc:
        return [], None, str(exc)

    raw_cards = payload.get("candidate_cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        return [], payload, None
    return _normalize_candidate_cards_for_mcp(list(raw_cards[:top_n])), payload, None


def _inject_deep_research_into_candidate_cards(
    cards: list[dict[str, Any]],
    *,
    deep_research_payload: dict[str, Any] | None,
) -> None:
    if not isinstance(deep_research_payload, dict):
        return

    def _clean_supporting_titles(raw_titles: Any) -> list[str]:
        if not isinstance(raw_titles, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in raw_titles:
            text = str(raw or "").strip()
            lowered = text.lower()
            if not text:
                continue
            if lowered in {"node", "article", "document", "untitled"}:
                continue
            if lowered.startswith(("url:", "http://", "https://", "doi:", "pmid:")):
                continue
            if lowered.startswith(
                (
                    "404",
                    "403",
                    "access denied",
                    "error",
                    "just a moment",
                    "page not found",
                    "this page could not be found",
                    "deep research source ",
                )
            ):
                continue
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    def _card_specific_support(card: dict[str, Any]) -> tuple[list[str], bool]:
        provenance = card.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        titles = _clean_supporting_titles(
            card.get("supporting_paper_titles")
            or provenance.get("supporting_paper_titles")
        )
        supporting_ids = provenance.get("supporting_paper_ids")
        support_count = len(supporting_ids) if isinstance(supporting_ids, list) else 0
        evidence_scope = str(
            card.get("evidence_source_scope")
            or (card.get("kg_verification") or {}).get("evidence_source_scope")
            or ""
        ).strip()
        has_support = (
            bool(titles) or support_count >= 2 or evidence_scope == "cross_source"
        )
        return titles, has_support

    report = deep_research_payload.get("report")
    report_summary = ""
    report_status = ""
    if isinstance(report, dict):
        report_summary = str(report.get("summary") or "").strip()
        report_status = str(report.get("status") or "").strip()

    idempotency_key = str(deep_research_payload.get("idempotency_key") or "").strip()
    error_text = str(
        deep_research_payload.get("error") or deep_research_payload.get("message") or ""
    ).strip()

    grounded = bool(report_summary)
    for card in cards:
        supporting_titles, has_card_specific_support = _card_specific_support(card)
        if supporting_titles:
            card["supporting_paper_titles"] = supporting_titles
        if grounded and has_card_specific_support:
            card["grounding_status"] = "grounded"
            card["grounding_basis"] = "card_specific_evidence"
            card["evidence_summary"] = report_summary
            if report_status:
                card["deep_research_status"] = report_status
        else:
            card["grounding_status"] = "degraded"
            if grounded:
                card["grounding_basis"] = "report_only"
                card["evidence_summary"] = report_summary
            if report_status:
                card["deep_research_status"] = report_status
            if error_text:
                card["deep_research_error"] = error_text
        if idempotency_key:
            card["deep_research_idempotency_key"] = idempotency_key


def _is_weak_baseline_candidate_card(card: dict[str, Any]) -> bool:
    if not isinstance(card, dict):
        return False

    quality_bucket = str(card.get("quality_bucket") or "").strip().lower()
    if quality_bucket == "template_only":
        return True

    rewrite_status = str(card.get("rewrite_status") or "").strip().lower()
    if rewrite_status == "needs_rewrite":
        return True

    kg_verification = card.get("kg_verification") or {}
    verdict = str(kg_verification.get("verdict") or "").strip().lower()
    if verdict in {"insufficient_evidence", "uncertain", "mixed", "conflicting"}:
        return True

    confidence = kg_verification.get("confidence")
    try:
        if confidence is not None and float(confidence) < 0.10:
            return True
    except (TypeError, ValueError):
        pass

    summary = kg_verification.get("summary") or {}
    try:
        n_supporting = int(summary.get("n_supporting") or 0) + int(
            summary.get("n_external_literature_supporting") or 0
        )
        n_conflicting = int(summary.get("n_conflicting") or 0)
    except (TypeError, ValueError):
        n_supporting = 0
        n_conflicting = 0
    return (
        n_conflicting >= 3
        and n_conflicting > n_supporting
        and n_conflicting >= max(3, n_supporting * 2)
    )


def _should_promote_deep_research_candidate_cards(
    existing_cards: list[dict[str, Any]],
) -> bool:
    if not existing_cards:
        return True
    return all(_is_weak_baseline_candidate_card(card) for card in existing_cards)


_KG_PROBE_TYPE_ALIASES: dict[str, str] = {
    "structural_leverage": "structural_leverage",
    "find_structural_leverage": "structural_leverage",
    "kg_find_structural_leverage": "structural_leverage",
    "contradiction_motifs": "contradiction_motifs",
    "detect_contradiction_motifs": "contradiction_motifs",
    "kg_detect_contradiction_motifs": "contradiction_motifs",
    "contradiction_frontiers": "contradiction_frontiers",
    "find_contradiction_frontiers": "contradiction_frontiers",
    "kg_find_contradiction_frontiers": "contradiction_frontiers",
    "assumption_cracks": "assumption_cracks",
    "mine_assumption_cracks": "assumption_cracks",
    "kg_mine_assumption_cracks": "assumption_cracks",
    "analogy_transfers": "analogy_transfers",
    "find_analogy_transfers": "analogy_transfers",
    "kg_find_analogy_transfers": "analogy_transfers",
}
KgProbeType = Literal[
    "structural_leverage",
    "contradiction_motifs",
    "contradiction_frontiers",
    "assumption_cracks",
    "analogy_transfers",
]
_KG_PROBE_SUPPORTED_TYPES: tuple[str, ...] = get_args(KgProbeType)


def _normalize_kg_probe_type(probe_type: str | None) -> str:
    return _KG_PROBE_TYPE_ALIASES.get(str(probe_type or "").strip().lower(), "")


def _parse_positive_int(
    value: Any, *, field_name: str
) -> tuple[int | None, dict[str, Any] | None]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, {"ok": False, "error": f"{field_name} must be an integer"}
    if parsed < 1:
        return None, {"ok": False, "error": f"{field_name} must be >= 1"}
    return parsed, None


def _parse_optional_positive_int(
    value: Any, *, field_name: str
) -> tuple[int | None, dict[str, Any] | None]:
    if value is None:
        return None, None
    return _parse_positive_int(value, field_name=field_name)


def _append_result_warning(payload: dict[str, Any], message: str) -> None:
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        warnings.append(message)
    else:
        payload["warnings"] = [message]


def _resolve_seed_kg_ids(
    seed_kg_ids: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
) -> list[str]:
    normalized_seed_ids = _coerce_non_empty_str_list(seed_kg_ids)
    if not normalized_seed_ids:
        normalized_seed_ids = _coerce_non_empty_str_list(start_kg_ids)
    if not normalized_seed_ids and kg_id:
        normalized_seed_ids = _coerce_non_empty_str_list([kg_id])
    return normalized_seed_ids


def _normalize_hypothesis_workflow_taste_mode(
    strategy: str | None,
    *,
    default_mode: str,
) -> str:
    strategy_mode = str(strategy or default_mode).strip().lower()
    return {
        "frontier": "novelty_first",
        "novelty_first": "novelty_first",
        "balanced": "balanced",
        "evidence_first": "evidence_first",
    }.get(strategy_mode, default_mode)


def _run_kg_probe(
    *,
    probe_type: str,
    query: str | None = None,
    hypothesis: str | None = None,
    claim: str | None = None,
    entity_hints: list[str] | None = None,
    seed_kg_ids: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    max_results: int = 10,
    top_k: int | None = None,
    max_hops: int = 2,
    allowed_edge_types: list[str] | None = None,
    query_required_error: str = "query is required",
    query_or_entity_required_error: str = "query or entity_hints is required",
    seed_required_error: str = "seed_kg_ids is required",
) -> dict[str, Any]:
    normalized_type = _normalize_kg_probe_type(probe_type)
    if not normalized_type:
        supported = ", ".join(_KG_PROBE_SUPPORTED_TYPES)
        return {
            "ok": False,
            "error": f"unsupported probe_type: {probe_type!r}. Supported values: {supported}",
        }

    normalized_query = str(query or hypothesis or claim or "").strip()
    normalized_entity_hints = _coerce_non_empty_str_list(entity_hints)

    try:
        from brain_researcher.services.br_kg import query_service

        if normalized_type == "structural_leverage":
            normalized_seed_ids = _coerce_non_empty_str_list(start_kg_ids)
            if not normalized_seed_ids:
                normalized_seed_ids = _coerce_non_empty_str_list(seed_kg_ids)
            if not normalized_seed_ids and kg_id:
                normalized_seed_ids = _coerce_non_empty_str_list([kg_id])
            if not normalized_seed_ids:
                return {"ok": False, "error": seed_required_error}

            max_hops_i, error_resp = _parse_positive_int(
                max_hops, field_name="max_hops"
            )
            if error_resp:
                return error_resp

            result_limit_raw = top_k if top_k is not None else max_results
            result_limit_i, error_resp = _parse_positive_int(
                result_limit_raw,
                field_name="top_k" if top_k is not None else "max_results",
            )
            if error_resp:
                return error_resp

            call_kwargs = _compact_kwargs(
                {
                    "seed_kg_ids": normalized_seed_ids,
                    "limit": result_limit_i,
                    "relation_types": allowed_edge_types,
                }
            )
            result = query_service.find_structural_leverage(**call_kwargs)
            payload = _kg_result_payload(result)
            if max_hops_i != 2:
                _append_result_warning(
                    payload, "max_hops is currently informational for this endpoint"
                )
            return {"ok": True, "result": payload}

        if normalized_type == "contradiction_motifs":
            if not normalized_query:
                return {"ok": False, "error": query_required_error}
            max_results_i, error_resp = _parse_positive_int(
                max_results, field_name="max_results"
            )
            if error_resp:
                return error_resp
            result = query_service.detect_contradiction_motifs(
                **_compact_kwargs(
                    {
                        "hypothesis": normalized_query,
                        "seed_kg_ids": normalized_entity_hints,
                        "max_evidence": max_results_i,
                    }
                )
            )
            return {"ok": True, "result": _kg_result_payload(result)}

        if not normalized_query and not normalized_entity_hints:
            return {"ok": False, "error": query_or_entity_required_error}

        max_results_i, error_resp = _parse_positive_int(
            max_results, field_name="max_results"
        )
        if error_resp:
            return error_resp

        if normalized_type == "contradiction_frontiers":
            result = query_service.find_contradiction_frontiers(
                query=normalized_query or None,
                seed_kg_ids=normalized_entity_hints,
                relation_types=allowed_edge_types,
                limit=max_results_i,
                max_evidence=max_results_i,
            )
            return {"ok": True, "result": _kg_result_payload(result)}

        if normalized_type == "assumption_cracks":
            result = query_service.mine_assumption_cracks(
                query=normalized_query or None,
                seed_kg_ids=normalized_entity_hints,
                limit=max_results_i,
            )
            return {"ok": True, "result": _kg_result_payload(result)}

        result = query_service.find_analogy_transfers(
            query=normalized_query or None,
            seed_kg_ids=normalized_entity_hints,
            relation_types=allowed_edge_types,
            limit=max_results_i,
        )
        return {"ok": True, "result": _kg_result_payload(result)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_probe(
    probe_type: KgProbeType,
    query: str | None = None,
    entity_hints: list[str] | None = None,
    seed_kg_ids: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    max_results: int = 10,
    top_k: int | None = None,
    max_hops: int = 2,
    allowed_edge_types: list[str] | None = None,
    hypothesis: str | None = None,
    claim: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Probe KG structure for leverage, contradictions, assumption cracks, or analogy transfers."""

    with semantic_matching_scope(semantic):
        return _run_kg_probe(
            probe_type=probe_type,
            query=query,
            hypothesis=hypothesis,
            claim=claim,
            entity_hints=entity_hints,
            seed_kg_ids=seed_kg_ids,
            start_kg_ids=start_kg_ids,
            kg_id=kg_id,
            max_results=max_results,
            top_k=top_k,
            max_hops=max_hops,
            allowed_edge_types=allowed_edge_types,
        )


@mcp.tool()
def kg_find_structural_leverage(
    start_kg_ids: list[str] | None = None,
    max_hops: int = 2,
    top_k: int = 20,
    allowed_edge_types: list[str] | None = None,
    seed_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_probe` for structural leverage queries."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_find_structural_leverage",
            _run_kg_probe(
                probe_type="structural_leverage",
                start_kg_ids=start_kg_ids,
                max_hops=max_hops,
                top_k=top_k,
                allowed_edge_types=allowed_edge_types,
                seed_kg_ids=seed_kg_ids,
                kg_id=kg_id,
                seed_required_error="start_kg_ids is required",
            ),
            param_keys=param_keys,
        )


@mcp.tool()
def kg_detect_contradiction_motifs(
    hypothesis: str | None = None,
    entity_hints: list[str] | None = None,
    max_results: int = 25,
    claim: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_probe` for contradiction motif queries."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_detect_contradiction_motifs",
            _run_kg_probe(
                probe_type="contradiction_motifs",
                hypothesis=hypothesis,
                claim=claim,
                entity_hints=entity_hints,
                max_results=max_results,
                query_required_error="hypothesis is required",
            ),
            param_keys=param_keys,
        )


@mcp.tool()
def kg_find_contradiction_frontiers(
    hypothesis: str | None = None,
    entity_hints: list[str] | None = None,
    max_results: int = 10,
    claim: str | None = None,
    allowed_edge_types: list[str] | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_probe` for contradiction frontier queries."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_find_contradiction_frontiers",
            _run_kg_probe(
                probe_type="contradiction_frontiers",
                hypothesis=hypothesis,
                claim=claim,
                entity_hints=entity_hints,
                max_results=max_results,
                allowed_edge_types=allowed_edge_types,
                query_or_entity_required_error="hypothesis or entity_hints is required",
            ),
            param_keys=param_keys,
        )


@mcp.tool()
def kg_mine_assumption_cracks(
    hypothesis: str | None = None,
    entity_hints: list[str] | None = None,
    max_results: int = 10,
    claim: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_probe` for assumption-crack queries."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_mine_assumption_cracks",
            _run_kg_probe(
                probe_type="assumption_cracks",
                hypothesis=hypothesis,
                claim=claim,
                entity_hints=entity_hints,
                max_results=max_results,
                query_or_entity_required_error="hypothesis or entity_hints is required",
            ),
            param_keys=param_keys,
        )


@mcp.tool()
def kg_find_analogy_transfers(
    hypothesis: str | None = None,
    entity_hints: list[str] | None = None,
    max_results: int = 10,
    claim: str | None = None,
    allowed_edge_types: list[str] | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_probe` for analogy-transfer queries."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_find_analogy_transfers",
            _run_kg_probe(
                probe_type="analogy_transfers",
                hypothesis=hypothesis,
                claim=claim,
                entity_hints=entity_hints,
                max_results=max_results,
                allowed_edge_types=allowed_edge_types,
                query_or_entity_required_error="hypothesis or entity_hints is required",
            ),
            param_keys=param_keys,
        )


@mcp.tool()
def kg_sample_ood_hypothesis(
    seed_kg_ids: list[str] | None = None,
    n_samples: int = 5,
    max_hops: int = 2,
    strategy: str = "frontier",
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_hypothesis_workflow` for OOD sampling."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_sample_ood_hypothesis",
            _run_kg_hypothesis_workflow(
                operation="sample",
                seed_kg_ids=seed_kg_ids,
                n_samples=n_samples,
                max_hops=max_hops,
                strategy=strategy,
                start_kg_ids=start_kg_ids,
                kg_id=kg_id,
                seed_required_error="seed_kg_ids is required",
            ),
            param_keys=param_keys,
        )


_KG_HYPOTHESIS_WORKFLOW_OPERATION_ALIASES: dict[str, str] = {
    "sample": "sample",
    "sample_ood": "sample",
    "sample_ood_hypothesis": "sample",
    "kg_sample_ood_hypothesis": "sample",
    "verify_candidates": "verify_candidates",
    "verify_sampled": "verify_candidates",
    "verify_sampled_hypotheses": "verify_candidates",
    "kg_verify_sampled_hypotheses": "verify_candidates",
    "sample_and_verify": "sample_and_verify",
    "sample_and_verify_hypotheses": "sample_and_verify",
    "kg_sample_and_verify_hypotheses": "sample_and_verify",
}
_KG_HYPOTHESIS_WORKFLOW_OPERATIONS: tuple[str, ...] = (
    "sample",
    "verify_candidates",
    "sample_and_verify",
)


def _normalize_kg_hypothesis_workflow_operation(operation: str | None) -> str:
    return _KG_HYPOTHESIS_WORKFLOW_OPERATION_ALIASES.get(
        str(operation or "").strip().lower(), ""
    )


def _run_kg_hypothesis_workflow(
    *,
    operation: str,
    query: str | None = None,
    sampled_hypotheses: list[dict[str, Any]] | None = None,
    seed_kg_ids: list[str] | None = None,
    n_samples: int = 5,
    verify_top_k: int | None = None,
    max_hops: int = 2,
    strategy: str | None = None,
    strictness: str = "high_recall",
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    min_evidence_score: float | None = None,
    include_subgraph: bool = False,
    include_path_details: bool = False,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: str = "broad",
    use_external_literature: bool = False,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    seed_required_error: str = "seed_kg_ids is required",
    sampled_required_error: str = "sampled_hypotheses is required",
) -> dict[str, Any]:
    normalized_operation = _normalize_kg_hypothesis_workflow_operation(operation)
    if not normalized_operation:
        supported = ", ".join(_KG_HYPOTHESIS_WORKFLOW_OPERATIONS)
        return {
            "ok": False,
            "error": (
                f"unsupported operation: {operation!r}. Supported values: {supported}"
            ),
        }

    normalized_query = str(query or "").strip() or None
    normalized_seed_ids = _resolve_seed_kg_ids(
        seed_kg_ids=seed_kg_ids,
        start_kg_ids=start_kg_ids,
        kg_id=kg_id,
    )

    verify_top_k_i, error_resp = _parse_optional_positive_int(
        verify_top_k, field_name="verify_top_k"
    )
    if error_resp:
        return error_resp

    try:
        from brain_researcher.services.br_kg import query_service

        if normalized_operation == "sample":
            if not normalized_seed_ids:
                return {"ok": False, "error": seed_required_error}
            n_samples_i, error_resp = _parse_positive_int(
                n_samples, field_name="n_samples"
            )
            if error_resp:
                return error_resp
            max_hops_i, error_resp = _parse_positive_int(
                max_hops, field_name="max_hops"
            )
            if error_resp:
                return error_resp

            taste_mode = _normalize_hypothesis_workflow_taste_mode(
                strategy, default_mode="novelty_first"
            )
            result = query_service.sample_ood_hypothesis(
                **_compact_kwargs(
                    {
                        "seed_kg_ids": normalized_seed_ids,
                        "limit": n_samples_i,
                        "taste": {"mode": taste_mode},
                    }
                )
            )
            payload = _kg_result_payload(result)
            if max_hops_i != 2:
                _append_result_warning(
                    payload, "max_hops is currently informational for this endpoint"
                )
            return {"ok": True, "result": payload}

        if normalized_operation == "verify_candidates":
            if not isinstance(sampled_hypotheses, list) or not sampled_hypotheses:
                return {"ok": False, "error": sampled_required_error}
            result = query_service.verify_sampled_hypotheses(
                **_compact_kwargs(
                    {
                        "sampled_hypotheses": sampled_hypotheses,
                        "query": normalized_query,
                        "seed_kg_ids": normalized_seed_ids,
                        "verify_top_k": verify_top_k_i,
                        "strictness": strictness,
                        "allowed_node_types": allowed_node_types,
                        "max_evidence": max_evidence,
                        "max_paths": max_paths,
                        "min_evidence_score": min_evidence_score,
                        "include_subgraph": include_subgraph,
                        "include_path_details": include_path_details,
                        "confidence_scoring_version": confidence_scoring_version,
                        "candidate_lane_mode": candidate_lane_mode,
                        "use_external_literature": use_external_literature,
                        "external_literature_top_k": external_literature_top_k,
                        "external_literature_recency_days": external_literature_recency_days,
                        "external_literature_exclude_domains": external_literature_exclude_domains,
                    }
                )
            )
            return {"ok": True, "result": _kg_result_payload(result)}

        if not normalized_seed_ids:
            return {"ok": False, "error": seed_required_error}
        n_samples_i, error_resp = _parse_positive_int(n_samples, field_name="n_samples")
        if error_resp:
            return error_resp
        max_hops_i, error_resp = _parse_positive_int(max_hops, field_name="max_hops")
        if error_resp:
            return error_resp

        taste_mode = _normalize_hypothesis_workflow_taste_mode(
            strategy, default_mode="balanced"
        )
        result = query_service.sample_and_verify_hypotheses(
            **_compact_kwargs(
                {
                    "seed_kg_ids": normalized_seed_ids,
                    "query": normalized_query,
                    "sample_limit": n_samples_i,
                    "verify_top_k": verify_top_k_i,
                    "taste": {"mode": taste_mode},
                    "strictness": strictness,
                    "allowed_node_types": allowed_node_types,
                    "max_evidence": max_evidence,
                    "max_paths": max_paths,
                    "min_evidence_score": min_evidence_score,
                    "include_subgraph": include_subgraph,
                    "include_path_details": include_path_details,
                    "confidence_scoring_version": confidence_scoring_version,
                    "candidate_lane_mode": candidate_lane_mode,
                    "use_external_literature": use_external_literature,
                    "external_literature_top_k": external_literature_top_k,
                    "external_literature_recency_days": external_literature_recency_days,
                    "external_literature_exclude_domains": external_literature_exclude_domains,
                }
            )
        )
        payload = _kg_result_payload(result)
        if max_hops_i != 2:
            _append_result_warning(
                payload, "max_hops is currently informational for this endpoint"
            )
        return {"ok": True, "result": payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def kg_hypothesis_workflow(
    operation: str,
    query: str | None = None,
    sampled_hypotheses: list[dict[str, Any]] | None = None,
    seed_kg_ids: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    n_samples: int = 5,
    verify_top_k: int | None = None,
    max_hops: int = 2,
    strategy: (
        enum_str(
            ("frontier", "novelty_first", "balanced", "evidence_first"),
            "hypothesis sampling/ranking strategy",
        )
        | None
    ) = None,
    strictness: str = "high_recall",
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    min_evidence_score: float | None = None,
    include_subgraph: bool = False,
    include_path_details: bool = False,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: enum_str(
        ("broad", "strict"), "candidate recall lane"
    ) = "broad",
    use_external_literature: bool = False,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: list[str] | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Run KG hypothesis workflows for sampling, candidate verification, or combined sample+verify flows."""

    with semantic_matching_scope(semantic):
        return _run_kg_hypothesis_workflow(
            operation=operation,
            query=query,
            sampled_hypotheses=sampled_hypotheses,
            seed_kg_ids=seed_kg_ids,
            start_kg_ids=start_kg_ids,
            kg_id=kg_id,
            n_samples=n_samples,
            verify_top_k=verify_top_k,
            max_hops=max_hops,
            strategy=strategy,
            strictness=strictness,
            allowed_node_types=allowed_node_types,
            max_evidence=max_evidence,
            max_paths=max_paths,
            min_evidence_score=min_evidence_score,
            include_subgraph=include_subgraph,
            include_path_details=include_path_details,
            confidence_scoring_version=confidence_scoring_version,
            candidate_lane_mode=candidate_lane_mode,
            use_external_literature=use_external_literature,
            external_literature_top_k=external_literature_top_k,
            external_literature_recency_days=external_literature_recency_days,
            external_literature_exclude_domains=external_literature_exclude_domains,
        )


@mcp.tool()
def kg_verify_sampled_hypotheses(
    sampled_hypotheses: list[dict[str, Any]] | None = None,
    query: str | None = None,
    seed_kg_ids: list[str] | None = None,
    verify_top_k: int | None = None,
    strictness: str = "high_recall",
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    min_evidence_score: float | None = None,
    include_subgraph: bool = False,
    include_path_details: bool = False,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: str = "broad",
    use_external_literature: bool = False,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_hypothesis_workflow` for candidate verification."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_verify_sampled_hypotheses",
            _run_kg_hypothesis_workflow(
                operation="verify_candidates",
                sampled_hypotheses=sampled_hypotheses,
                query=query,
                seed_kg_ids=seed_kg_ids,
                verify_top_k=verify_top_k,
                strictness=strictness,
                allowed_node_types=allowed_node_types,
                max_evidence=max_evidence,
                max_paths=max_paths,
                min_evidence_score=min_evidence_score,
                include_subgraph=include_subgraph,
                include_path_details=include_path_details,
                confidence_scoring_version=confidence_scoring_version,
                candidate_lane_mode=candidate_lane_mode,
                use_external_literature=use_external_literature,
                external_literature_top_k=external_literature_top_k,
                external_literature_recency_days=external_literature_recency_days,
                external_literature_exclude_domains=external_literature_exclude_domains,
                start_kg_ids=start_kg_ids,
                kg_id=kg_id,
                sampled_required_error="sampled_hypotheses is required",
            ),
            param_keys=param_keys,
        )


@mcp.tool()
def kg_sample_and_verify_hypotheses(
    query: str | None = None,
    seed_kg_ids: list[str] | None = None,
    n_samples: int = 5,
    verify_top_k: int | None = None,
    max_hops: int = 2,
    strategy: str = "balanced",
    strictness: str = "high_recall",
    allowed_node_types: list[str] | None = None,
    max_evidence: int = 60,
    max_paths: int = 60,
    min_evidence_score: float | None = None,
    include_subgraph: bool = False,
    include_path_details: bool = False,
    confidence_scoring_version: str = "v2",
    candidate_lane_mode: str = "broad",
    use_external_literature: bool = False,
    external_literature_top_k: int = 5,
    external_literature_recency_days: int = 365,
    external_literature_exclude_domains: list[str] | None = None,
    start_kg_ids: list[str] | None = None,
    kg_id: str | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Compatibility alias of `kg_hypothesis_workflow` for sample+verify flows."""
    param_keys = sorted(locals().keys())
    with semantic_matching_scope(semantic):
        return _return_compat_alias_response(
            "kg_sample_and_verify_hypotheses",
            _run_kg_hypothesis_workflow(
                operation="sample_and_verify",
                query=query,
                seed_kg_ids=seed_kg_ids,
                n_samples=n_samples,
                verify_top_k=verify_top_k,
                max_hops=max_hops,
                strategy=strategy,
                strictness=strictness,
                allowed_node_types=allowed_node_types,
                max_evidence=max_evidence,
                max_paths=max_paths,
                min_evidence_score=min_evidence_score,
                include_subgraph=include_subgraph,
                include_path_details=include_path_details,
                confidence_scoring_version=confidence_scoring_version,
                candidate_lane_mode=candidate_lane_mode,
                use_external_literature=use_external_literature,
                external_literature_top_k=external_literature_top_k,
                external_literature_recency_days=external_literature_recency_days,
                external_literature_exclude_domains=external_literature_exclude_domains,
                start_kg_ids=start_kg_ids,
                kg_id=kg_id,
                seed_required_error="seed_kg_ids is required",
            ),
            param_keys=param_keys,
        )


def _execute_candidate_cards_core(
    workflow_params: dict[str, Any],
    with_deep_research: bool,
    deep_research_interaction_id: str | None,
    normalized_query: str,
    top_n_i: int,
    top_k_i: int,
    recency_days_i: int,
    exclude_domains: list[str] | None,
    *,
    progress_callback: Callable[[str, str, float], None] | None = None,
) -> dict[str, Any]:
    """Execute the candidate cards workflow core logic.

    Parameters
    ----------
    progress_callback:
        Optional ``(stage, message, pct)`` callable invoked at each major
        transition for observability.
    """

    def _notify(stage: str, message: str, pct: float) -> None:
        if progress_callback is not None:
            progress_callback(stage, message, pct)

    _notify("workflow_start", "Starting hypothesis candidate cards workflow", 0.0)
    normalized_interaction_id = str(deep_research_interaction_id or "").strip() or None
    outer_deep_research_enabled = bool(with_deep_research or normalized_interaction_id)
    workflow_public_params = dict(workflow_params)
    if outer_deep_research_enabled:
        workflow_public_params["verify_use_external_literature"] = False
    workflow_execution_params = dict(workflow_public_params)

    def _workflow_step_progress(event: dict[str, Any]) -> None:
        step_id = str(event.get("step_id") or "").strip()
        tool_name = str(event.get("tool_name") or "").strip() or step_id
        status = str(event.get("status") or "").strip().lower()
        total_steps = max(int(event.get("total_steps") or 0), 1)
        step_index = max(int(event.get("step_index") or 0), 0)
        if status == "running":
            pct = min(29.5, ((step_index + 0.5) / total_steps) * 30.0)
            _notify(
                f"workflow_step:{step_id}",
                f"Executing {tool_name}",
                pct,
            )
        elif status == "completed":
            pct = min(29.8, ((step_index + 1.0) / total_steps) * 30.0)
            _notify(
                f"workflow_step:{step_id}:completed",
                f"Completed {tool_name}",
                pct,
            )
        elif status == "failed":
            pct = min(29.8, ((step_index + 1.0) / total_steps) * 30.0)
            _notify(
                f"workflow_step:{step_id}:failed",
                str(event.get("error") or f"Failed {tool_name}"),
                pct,
            )

    if progress_callback is not None:
        workflow_execution_params["_progress_callback"] = _workflow_step_progress

    workflow_result = execute_tool(
        "workflow_hypothesis_candidate_cards",
        workflow_execution_params,
    )

    _notify("workflow_done", "Workflow execution completed", 30.0)

    workflow_status = str(getattr(workflow_result, "status", "error") or "error")
    if workflow_status != "success":
        raise RuntimeError(
            str(getattr(workflow_result, "error", None) or workflow_status)
        )

    workflow_payload = _tool_result_payload(workflow_result)
    candidate_cards = _extract_candidate_cards_from_workflow_payload(
        workflow_payload,
        query=normalized_query,
        top_n=top_n_i,
    )
    resolved_anchor_bundle = _extract_resolved_anchor_bundle_from_workflow_payload(
        workflow_payload
    )

    warnings: list[str] = []
    if not candidate_cards:
        warnings.append("no_candidate_cards")

    deep_research_payload: dict[str, Any] | None = None
    deep_research_idea_cards_payload: dict[str, Any] | None = None
    deep_research_idea_cards_used = False
    idea_cards_error: str | None = None
    if outer_deep_research_enabled:
        _notify("deep_research_start", "Starting deep research", 35.0)
        if normalized_interaction_id:
            raw_research = deep_research_get(interaction_id=normalized_interaction_id)
        else:
            raw_research = deep_research_sync(
                {
                    "query": normalized_query,
                    "recency_days": recency_days_i,
                    "top_k": top_k_i,
                    "exclude_domains": _coerce_non_empty_str_list(exclude_domains),
                }
            )
        _notify("deep_research_done", "Deep research completed", 60.0)
        deep_research_payload = _compact_deep_research_payload(raw_research)
        deep_research_result = _deep_research_result_payload(raw_research)

        _notify("idea_cards_start", "Building idea cards", 65.0)
        deep_research_cards, deep_research_idea_cards_payload, idea_cards_error = (
            _build_deep_research_idea_cards_payload(
                deep_research_result=deep_research_result,
                query=normalized_query,
                top_n=top_n_i,
            )
        )
        _notify("idea_cards_done", "Idea cards built", 80.0)
        if deep_research_cards and _should_promote_deep_research_candidate_cards(
            candidate_cards
        ):
            candidate_cards = deep_research_cards
            deep_research_idea_cards_used = True
    if candidate_cards:
        _inject_deep_research_into_candidate_cards(
            candidate_cards,
            deep_research_payload=deep_research_payload,
        )
        candidate_cards = _rerank_candidate_cards_for_mcp(candidate_cards)
        if (
            deep_research_payload is not None
            and str(deep_research_payload.get("status") or "").strip() == "error"
        ):
            warnings.append("deep_research_error")
        if idea_cards_error:
            warnings.append("deep_research_idea_cards_error")
            if deep_research_payload is not None:
                deep_research_payload["idea_cards_error"] = idea_cards_error
        elif deep_research_idea_cards_payload and deep_research_payload is not None:
            deep_research_payload["idea_cards"] = {
                "status": "ok",
                "used_as_primary": deep_research_idea_cards_used,
                "summary": deep_research_idea_cards_payload.get("summary"),
                "artifacts": deep_research_idea_cards_payload.get("artifacts"),
                "ephemeral_weighted_subgraph": deep_research_idea_cards_payload.get(
                    "ephemeral_weighted_subgraph"
                ),
            }

    grounded_cards = sum(
        1 for card in candidate_cards if card.get("grounding_status") == "grounded"
    )
    degraded_cards = sum(
        1 for card in candidate_cards if card.get("grounding_status") == "degraded"
    )

    result: dict[str, Any] = {
        "query": normalized_query,
        "workflow": {
            "workflow_id": "workflow_hypothesis_candidate_cards",
            "status": workflow_status,
            "params": workflow_public_params,
            "result": workflow_payload,
        },
        "resolved_anchor_bundle": resolved_anchor_bundle,
        "candidate_cards": candidate_cards,
        "summary": {
            "n_candidate_cards": len(candidate_cards),
            "n_grounded_cards": grounded_cards,
            "n_degraded_cards": degraded_cards,
            "candidate_lane_mode": workflow_params["candidate_lane_mode"],
            "deep_research_requested": bool(
                with_deep_research or normalized_interaction_id
            ),
            "deep_research_idea_cards_used": deep_research_idea_cards_used,
            "quality_bucket_counts": _count_card_nested_field(
                candidate_cards, "quality_bucket"
            ),
            "rewrite_status_counts": _count_card_nested_field(
                candidate_cards, "rewrite_status"
            ),
            "gap_type_counts": _count_card_nested_field(candidate_cards, "gap_type"),
        },
    }
    novelty_calibration = generate_novelty_calibration_questions(
        build_novelty_calibration_context(
            query=normalized_query,
            candidate_cards=candidate_cards,
            summary=result["summary"],
        )
    )
    result["novelty_calibration_questions"] = novelty_calibration[
        "novelty_calibration_questions"
    ]
    result["novelty_calibration_meta"] = novelty_calibration["novelty_calibration_meta"]
    if deep_research_idea_cards_payload and isinstance(
        deep_research_idea_cards_payload.get("ephemeral_weighted_subgraph"), dict
    ):
        result["ephemeral_weighted_subgraph"] = deep_research_idea_cards_payload.get(
            "ephemeral_weighted_subgraph"
        )
    if deep_research_payload is not None:
        result["deep_research"] = deep_research_payload
    if warnings:
        result["warnings"] = warnings

    _notify("completed", "Candidate cards generation completed", 100.0)

    return result


@mcp.tool()
def kg_hypothesis_candidate_cards(
    query: str,
    seed_kg_ids: list[str] | None = None,
    relation_types: list[str] | None = None,
    top_n: int = 5,
    top_k: int = 20,
    taste_mode: enum_str(
        ("balanced", "novelty_first", "evidence_first"), "ranking taste"
    ) = "balanced",
    controller_mode: enum_str(("principle_v0",), "controller policy") = "principle_v0",
    candidate_lane_mode: enum_str(
        ("broad", "strict"), "candidate recall lane"
    ) = "broad",
    frontier_mode: enum_str(("off", "frontier"), "frontier rewrite mode") = "off",
    with_deep_research: bool = True,
    deep_research_interaction_id: str | None = None,
    recency_days: int = 365,
    exclude_domains: list[str] | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Generate hypothesis candidate cards synchronously (use kg_hypothesis_candidate_cards_start for long-running queries)."""
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {"ok": False, "error": "query is required"}

    try:
        top_n_i = int(top_n)
    except (TypeError, ValueError):
        return {"ok": False, "error": "top_n must be an integer"}
    if top_n_i < 1:
        return {"ok": False, "error": "top_n must be >= 1"}

    try:
        top_k_i = int(top_k)
    except (TypeError, ValueError):
        return {"ok": False, "error": "top_k must be an integer"}
    if top_k_i < 1:
        return {"ok": False, "error": "top_k must be >= 1"}

    try:
        recency_days_i = int(recency_days)
    except (TypeError, ValueError):
        return {"ok": False, "error": "recency_days must be an integer"}
    if recency_days_i < 0:
        return {"ok": False, "error": "recency_days must be >= 0"}

    frontier_mode_norm = coerce_enum(frontier_mode, _FRONTIER_MODE_ALIASES, "off")
    workflow_params = _compact_kwargs(
        {
            "query": normalized_query,
            "seed_kg_ids": _coerce_non_empty_str_list(seed_kg_ids),
            "relation_types": _coerce_non_empty_str_list(relation_types),
            "top_k": top_k_i,
            "n_samples": top_n_i,
            "taste_mode": coerce_enum(taste_mode, _TASTE_MODE_ALIASES, "balanced"),
            "controller_mode": coerce_enum(
                controller_mode, _CONTROLLER_MODE_ALIASES, "principle_v0"
            ),
            "candidate_lane_mode": coerce_enum(
                candidate_lane_mode, _CANDIDATE_LANE_MODE_ALIASES, "broad"
            ),
            "frontier_mode": (
                frontier_mode_norm if frontier_mode_norm != "off" else None
            ),
            "use_external_literature": bool(with_deep_research),
            "external_literature_top_k": min(top_k_i, 5),
            "external_literature_recency_days": recency_days_i,
            "external_literature_exclude_domains": _coerce_non_empty_str_list(
                exclude_domains
            ),
        }
    )

    try:
        with semantic_matching_scope(semantic):
            result = _execute_candidate_cards_core(
                workflow_params=workflow_params,
                with_deep_research=with_deep_research,
                deep_research_interaction_id=deep_research_interaction_id,
                normalized_query=normalized_query,
                top_n_i=top_n_i,
                top_k_i=top_k_i,
                recency_days_i=recency_days_i,
                exclude_domains=exclude_domains,
            )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "result": result}


def _count_card_nested_field(cards: list[dict[str, Any]], *path: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        current: Any = card
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, str):
            normalized = current.strip()
            if normalized:
                counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def _top_anchor_labels(
    anchor_bundle: list[dict[str, Any]], limit: int = 5
) -> list[str]:
    labels: list[str] = []
    for row in anchor_bundle:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row.get("kg_id") or "").strip()
        if not label or label in labels:
            continue
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _build_hot_load_next_actions(
    *,
    candidate_cards: list[dict[str, Any]],
    resolved_anchor_bundle: list[dict[str, Any]],
    summary: dict[str, Any],
    deep_research_payload: dict[str, Any] | None,
    candidate_lane_mode: str,
) -> list[str]:
    actions: list[str] = []
    grounded_count = int(summary.get("n_grounded_cards") or 0)
    degraded_count = int(summary.get("n_degraded_cards") or 0)
    deep_status = str((deep_research_payload or {}).get("status") or "").strip().lower()

    if not resolved_anchor_bundle:
        actions.append(
            "Refine the query with task, modality, or population constraints."
        )
    if not candidate_cards:
        actions.append("Retry with a narrower query or provide manual seed_kg_ids.")
    if grounded_count > 0:
        actions.append(
            "Inspect grounded candidate cards first and choose one minimal test."
        )
    elif candidate_cards:
        actions.append(
            "Treat returned cards as hypothesis leads, not verified conclusions."
        )
    if deep_status == "error":
        actions.append(
            "Deep research degraded; retry with a narrower query or fewer domains."
        )
    if degraded_count > 0:
        actions.append(
            "Review degraded cards for missing evidence before promoting any idea."
        )
    if candidate_lane_mode == "broad":
        actions.append(
            "Re-run with candidate_lane_mode=strict to compare benchmark-only evidence."
        )

    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped[:4]


def _normalize_hypothesis_hot_load_request(
    query: str,
    max_cards: int = 5,
    depth: str = "deep",
    candidate_lane_mode: str = "broad",
    frontier_mode: str = "off",
    seed_kg_ids: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {"ok": False, "error": "query is required"}

    try:
        max_cards_i = int(max_cards)
    except (TypeError, ValueError):
        return {"ok": False, "error": "max_cards must be an integer"}
    if max_cards_i < 1:
        return {"ok": False, "error": "max_cards must be >= 1"}

    depth_mode = str(depth or "deep").strip().lower() or "deep"
    if depth_mode not in {"shallow", "balanced", "deep"}:
        return {"ok": False, "error": "depth must be one of: shallow, balanced, deep"}

    profile = {
        "shallow": {
            "top_k": 12,
            "with_deep_research": False,
            "recency_days": 180,
        },
        "balanced": {
            "top_k": 20,
            "with_deep_research": True,
            "recency_days": 365,
        },
        "deep": {
            "top_k": 30,
            "with_deep_research": True,
            "recency_days": 730,
        },
    }[depth_mode]

    frontier_mode_norm = coerce_enum(frontier_mode, _FRONTIER_MODE_ALIASES, "off")
    return {
        "ok": True,
        "request": _compact_kwargs(
            {
                "query": normalized_query,
                "max_cards": max_cards_i,
                "depth": depth_mode,
                "candidate_lane_mode": coerce_enum(
                    candidate_lane_mode, _CANDIDATE_LANE_MODE_ALIASES, "broad"
                ),
                "frontier_mode": (
                    frontier_mode_norm if frontier_mode_norm != "off" else None
                ),
                "seed_kg_ids": _coerce_non_empty_str_list(seed_kg_ids),
                "exclude_domains": _coerce_non_empty_str_list(exclude_domains),
                "profile": {
                    "top_k": int(profile["top_k"]),
                    "with_deep_research": bool(profile["with_deep_research"]),
                    "recency_days": int(profile["recency_days"]),
                },
            }
        ),
    }


def _execute_hypothesis_hot_load_request(request: dict[str, Any]) -> dict[str, Any]:
    normalized_query = str(request.get("query") or "").strip()
    max_cards_i = int(request.get("max_cards") or 5)
    depth_mode = str(request.get("depth") or "deep").strip().lower() or "deep"
    candidate_lane_mode = (
        str(request.get("candidate_lane_mode") or "broad").strip() or "broad"
    )
    frontier_mode = str(request.get("frontier_mode") or "off").strip().lower() or "off"
    seed_kg_ids = _coerce_non_empty_str_list(request.get("seed_kg_ids"))
    exclude_domains = _coerce_non_empty_str_list(request.get("exclude_domains"))
    profile = dict(request.get("profile") or {})

    base = kg_hypothesis_candidate_cards(
        **_compact_kwargs(
            {
                "query": normalized_query,
                "seed_kg_ids": seed_kg_ids,
                "top_n": max_cards_i,
                "top_k": int(profile["top_k"]),
                "taste_mode": "balanced",
                "controller_mode": "principle_v0",
                "candidate_lane_mode": candidate_lane_mode,
                "frontier_mode": frontier_mode if frontier_mode != "off" else None,
                "with_deep_research": bool(profile["with_deep_research"]),
                "recency_days": int(profile["recency_days"]),
                "exclude_domains": exclude_domains,
            }
        )
    )
    if not base.get("ok"):
        return base

    payload = dict(base.get("result") or {})
    candidate_cards = list(payload.get("candidate_cards") or [])
    resolved_anchor_bundle = list(payload.get("resolved_anchor_bundle") or [])
    base_summary = dict(payload.get("summary") or {})
    deep_research_payload = (
        dict(payload.get("deep_research") or {})
        if isinstance(payload.get("deep_research"), dict)
        else None
    )

    enriched_summary = {
        **base_summary,
        "depth": depth_mode,
        "top_anchor_labels": _top_anchor_labels(resolved_anchor_bundle),
        "n_resolved_anchors": len(resolved_anchor_bundle),
        "verdict_counts": _count_card_nested_field(
            candidate_cards, "kg_verification", "verdict"
        ),
        "evidence_source_scope_counts": _count_card_nested_field(
            candidate_cards, "kg_verification", "evidence_source_scope"
        ),
        "gap_type_counts": _count_card_nested_field(candidate_cards, "gap_type"),
        "deep_research_status": (
            str((deep_research_payload or {}).get("status") or "").strip() or None
        ),
    }

    research_profile = {
        "top_k": int(profile["top_k"]),
        "deep_research_requested": bool(profile["with_deep_research"]),
        "recency_days": int(profile["recency_days"]),
        "candidate_lane_mode": str(candidate_lane_mode or "broad").strip() or "broad",
    }
    if frontier_mode != "off":
        research_profile["frontier_mode"] = frontier_mode

    result = {
        "query": normalized_query,
        "status": "completed",
        "mode": "sync",
        "depth": depth_mode,
        "research_profile": research_profile,
        "resolved_anchor_bundle": resolved_anchor_bundle,
        "candidate_cards": candidate_cards,
        "summary": enriched_summary,
        "next_actions": _build_hot_load_next_actions(
            candidate_cards=candidate_cards,
            resolved_anchor_bundle=resolved_anchor_bundle,
            summary=base_summary,
            deep_research_payload=deep_research_payload,
            candidate_lane_mode=str(candidate_lane_mode or "broad").strip() or "broad",
        ),
        "workflow": payload.get("workflow"),
    }
    if deep_research_payload is not None:
        result["deep_research"] = deep_research_payload
    if payload.get("warnings"):
        result["warnings"] = list(payload.get("warnings") or [])

    return {"ok": True, "result": result}


@mcp.tool()
def hypothesis_hot_load_research(
    query: str,
    max_cards: int = 5,
    depth: str = "deep",
    candidate_lane_mode: enum_str(
        ("broad", "strict"), "candidate recall lane"
    ) = "broad",
    frontier_mode: enum_str(("off", "frontier"), "frontier rewrite mode") = "off",
    seed_kg_ids: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full hot-load hypothesis research path behind one MCP tool."""
    normalized = _normalize_hypothesis_hot_load_request(
        query=query,
        max_cards=max_cards,
        depth=depth,
        candidate_lane_mode=candidate_lane_mode,
        frontier_mode=frontier_mode,
        seed_kg_ids=seed_kg_ids,
        exclude_domains=exclude_domains,
    )
    if not normalized.get("ok"):
        return normalized
    return _execute_hypothesis_hot_load_request(dict(normalized.get("request") or {}))


_HYPOTHESIS_RUN_RESULT_RELPATH = "artifacts/hypothesis_hot_load.result.json"


def _load_hypothesis_run_result(run_dir: Path, relpath: str) -> dict[str, Any] | None:
    target = run_dir / relpath
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _run_result_relpath_from_payload(
    run_payload: dict[str, Any],
    *,
    default_relpath: str | None = None,
) -> str | None:
    step_records = list(run_payload.get("steps") or [])
    relpath = str(default_relpath or "").strip() or None
    if step_records and isinstance(step_records[0], dict):
        step_relpath = str(step_records[0].get("result_path") or "").strip()
        if step_relpath:
            relpath = step_relpath
    return relpath


def _augment_run_get_with_specialized_payload(
    response: dict[str, Any],
    *,
    run_dir: Path,
) -> dict[str, Any]:
    run_payload = response.get("run")
    if not isinstance(run_payload, dict):
        return response

    step_records = list(run_payload.get("steps") or [])
    first_step = (
        step_records[0] if step_records and isinstance(step_records[0], dict) else {}
    )
    tool_id = str(first_step.get("tool_id") or "").strip()

    result_relpath = _run_result_relpath_from_payload(run_payload)
    result_payload: dict[str, Any] | None = None
    if result_relpath:
        result_payload = _load_hypothesis_run_result(run_dir, result_relpath)

    if result_payload is not None:
        response["result"] = result_payload
        if tool_id == "google_deep_research_start":
            response["data"] = result_payload
            interaction_id = str(result_payload.get("interaction_id") or "").strip()
            if interaction_id:
                response["interaction_id"] = interaction_id
        if isinstance(result_payload.get("summary"), dict):
            response["summary"] = result_payload["summary"]
        if result_payload.get("warnings"):
            response["warnings"] = list(result_payload.get("warnings") or [])
        if isinstance(result_payload.get("novelty_calibration_questions"), list):
            response["novelty_calibration_questions"] = list(
                result_payload.get("novelty_calibration_questions") or []
            )
        if isinstance(result_payload.get("novelty_calibration_meta"), dict):
            response["novelty_calibration_meta"] = dict(
                result_payload.get("novelty_calibration_meta") or {}
            )
        if isinstance(result_payload.get("_stage_timings"), list):
            response["stage_timings"] = result_payload["_stage_timings"]

    if (
        str(run_payload.get("status") or "") == "failed"
        and "stage_timings" not in response
        and tool_id == "kg_hypothesis_candidate_cards"
    ):
        error_artifact = run_dir / "artifacts" / "candidate_cards_error.json"
        if error_artifact.exists():
            try:
                err_data = json.loads(error_artifact.read_text(encoding="utf-8"))
                if isinstance(err_data.get("_stage_timings"), list):
                    response["stage_timings"] = err_data["_stage_timings"]
            except Exception:
                pass

    return response


def _execute_hypothesis_run(run_id: str, request: dict[str, Any]) -> None:
    run_dir = _run_dir(run_id)
    result_relpath = _HYPOTHESIS_RUN_RESULT_RELPATH
    lock = _get_run_lock(run_id)
    heartbeat_stop: threading.Event | None = None

    with lock:
        record, run_dir = _load_run_with_dir(run_id)
        if record.status == "cancelled":
            return
        started_at = _utc_iso()
        record.status = "running"
        record.started_at = started_at
        if record.steps:
            step = record.steps[0]
            step.status = "running"
            step.started_at = started_at
        _update_run_progress(
            record,
            stage="hypothesis_hot_load",
            message="Running hot-load hypothesis research",
            progress_pct=0.0,
            step_index=0 if record.steps else None,
            timestamp=started_at,
        )
        _save_run(record, run_dir=run_dir)
        _update_run_provenance_state(run_dir, state=record.status)
        heartbeat_stop = _start_run_heartbeat(
            run_id,
            stage="hypothesis_hot_load",
            message="Running hot-load hypothesis research",
            progress_pct=0.0,
            step_index=0 if record.steps else None,
            run_dir=run_dir,
        )

    try:
        response = _execute_hypothesis_hot_load_request(request)
        if response.get("ok") is not True:
            raise RuntimeError(str(response.get("error") or "hypothesis_run_failed"))
        result_payload = dict(response.get("result") or {})
        _atomic_write_json(run_dir / result_relpath, result_payload)

        with lock:
            record, run_dir = _load_run_with_dir(run_id)
            if record.status == "cancelled":
                return
            finished_at = _utc_iso()
            record.status = "succeeded"
            record.finished_at = finished_at
            record.error = None
            if record.steps:
                step = record.steps[0]
                step.status = "succeeded"
                step.finished_at = finished_at
                step.result_path = result_relpath
                step.error = None
            _update_run_progress(
                record,
                stage="completed",
                message="Hot-load hypothesis research completed",
                progress_pct=100.0,
                step_index=0 if record.steps else None,
                timestamp=finished_at,
            )
            _save_run(record, run_dir=run_dir)
            _update_run_provenance_state(run_dir, state=record.status)
    except Exception as exc:
        error_message = str(exc)
        with lock:
            record, run_dir = _load_run_with_dir(run_id)
            if record.status == "cancelled":
                return
            finished_at = _utc_iso()
            record.status = "failed"
            record.finished_at = finished_at
            record.error = error_message
            if record.steps:
                step = record.steps[0]
                step.status = "failed"
                step.finished_at = finished_at
                step.error = error_message
            _update_run_progress(
                record,
                stage="failed",
                message=error_message,
                step_index=0 if record.steps else None,
                timestamp=finished_at,
            )
            _save_run(record, run_dir=run_dir)
            _update_run_provenance_state(
                run_dir, state=record.status, error=record.error
            )
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()


@mcp.tool()
def hypothesis_run_start(
    query: str,
    max_cards: int = 5,
    depth: str = "deep",
    candidate_lane_mode: enum_str(
        ("broad", "strict"), "candidate recall lane"
    ) = "broad",
    frontier_mode: enum_str(("off", "frontier"), "frontier rewrite mode") = "off",
    seed_kg_ids: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Start a background hot-load hypothesis run and return a pollable run_id."""
    normalized = _normalize_hypothesis_hot_load_request(
        query=query,
        max_cards=max_cards,
        depth=depth,
        candidate_lane_mode=candidate_lane_mode,
        frontier_mode=frontier_mode,
        seed_kg_ids=seed_kg_ids,
        exclude_domains=exclude_domains,
    )
    if not normalized.get("ok"):
        return normalized

    request = dict(normalized.get("request") or {})
    run_id = _new_run_id()
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    provenance = {
        "run_id": run_id,
        "mode": "mcp",
        "route": "hypothesis_run_start",
        "request": request,
    }
    _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))

    record = RunRecord(
        run_id=run_id,
        created_at=_utc_iso(),
        status="queued",
        dry_run=False,
        progress={
            "current_stage": "queued",
            "message": "Queued hot-load hypothesis research",
            "last_progress_at": _utc_iso(),
        },
        timing_policy=_default_run_timing_policy(),
        steps=[
            StepRecord(
                step_id="hypothesis_hot_load",
                tool_id="hypothesis_hot_load_research",
                params=request,
                status="queued",
                progress={
                    "current_stage": "queued",
                    "message": "Queued hot-load hypothesis research",
                    "last_progress_at": _utc_iso(),
                },
            )
        ],
    )
    _save_run(record, run_dir=run_dir)

    thread = threading.Thread(
        target=_execute_hypothesis_run,
        args=(run_id, request),
        daemon=False,
    )
    thread.start()

    return _background_launch_response(
        run_id=run_id,
        run_dir=run_dir,
        compat_poll_tool="hypothesis_run_get",
    )


@mcp.tool()
def hypothesis_run_get(run_id: str) -> dict[str, Any]:
    """Fetch background hot-load hypothesis run status and final payload when available."""
    param_keys = sorted(locals().keys())
    response = dict(run_get(run_id))
    if response.get("ok") is not True:
        return _return_compat_alias_response(
            "hypothesis_run_get",
            response,
            param_keys=param_keys,
        )

    run_payload = response.get("run")
    status = str((run_payload or {}).get("status") or "")
    response.update(
        {
            "run_id": str((run_payload or {}).get("run_id") or run_id),
            "status": status,
            "done": status in _MCP_RUN_TERMINAL_STATUSES,
            "execution_mode": "background",
        }
    )
    return _return_compat_alias_response(
        "hypothesis_run_get",
        response,
        param_keys=param_keys,
    )


# ---------------------------------------------------------------------------
# Candidate cards async start/get
# ---------------------------------------------------------------------------

_CANDIDATE_CARDS_RUN_RESULT_RELPATH = "artifacts/candidate_cards_result.json"


def _execute_candidate_cards_run(run_id: str, params: dict[str, Any]) -> None:
    """Background worker for async candidate cards generation."""
    run_dir = _run_dir(run_id)
    result_relpath = _CANDIDATE_CARDS_RUN_RESULT_RELPATH
    lock = _get_run_lock(run_id)
    heartbeat_stop: threading.Event | None = None
    t0 = time.monotonic()
    stage_timings: list[dict[str, Any]] = []

    def _on_progress(stage: str, message: str, pct: float) -> None:
        now = _utc_iso()
        stage_timings.append(
            {
                "stage": stage,
                "started_at": now,
                "elapsed_s": round(time.monotonic() - t0, 2),
            }
        )
        with lock:
            try:
                record, rd = _load_run_with_dir(run_id)
            except Exception:
                return
            if record.status == "cancelled":
                return
            _update_run_progress(
                record,
                stage=stage,
                message=message,
                progress_pct=pct,
                step_index=0 if record.steps else None,
                timestamp=now,
            )
            _save_run(record, run_dir=rd)

    with lock:
        record, run_dir = _load_run_with_dir(run_id)
        if record.status == "cancelled":
            return
        started_at = _utc_iso()
        record.status = "running"
        record.started_at = started_at
        if record.steps:
            step = record.steps[0]
            step.status = "running"
            step.started_at = started_at
        _update_run_progress(
            record,
            stage="candidate_cards",
            message="Running candidate cards generation",
            progress_pct=0.0,
            step_index=0 if record.steps else None,
            timestamp=started_at,
        )
        _save_run(record, run_dir=run_dir)
        _update_run_provenance_state(run_dir, state=record.status)
        heartbeat_stop = _start_run_heartbeat(
            run_id,
            stage="candidate_cards",
            message="Running candidate cards generation",
            progress_pct=0.0,
            step_index=0 if record.steps else None,
            run_dir=run_dir,
        )

    try:
        with semantic_matching_scope(_coerce_optional_bool(params.get("semantic"))):
            result = _execute_candidate_cards_core(
                workflow_params=params["workflow_params"],
                with_deep_research=params["with_deep_research"],
                deep_research_interaction_id=params.get("deep_research_interaction_id"),
                normalized_query=params["normalized_query"],
                top_n_i=params["top_n_i"],
                top_k_i=params["top_k_i"],
                recency_days_i=params["recency_days_i"],
                exclude_domains=params.get("exclude_domains"),
                progress_callback=_on_progress,
            )
        result["_stage_timings"] = stage_timings
        _atomic_write_json(run_dir / result_relpath, result)

        with lock:
            record, run_dir = _load_run_with_dir(run_id)
            if record.status == "cancelled":
                return
            finished_at = _utc_iso()
            record.status = "succeeded"
            record.finished_at = finished_at
            record.error = None
            if record.steps:
                step = record.steps[0]
                step.status = "succeeded"
                step.finished_at = finished_at
                step.result_path = result_relpath
                step.error = None
            _update_run_progress(
                record,
                stage="completed",
                message="Candidate cards generation completed",
                progress_pct=100.0,
                step_index=0 if record.steps else None,
                timestamp=finished_at,
            )
            _save_run(record, run_dir=run_dir)
            _update_run_provenance_state(run_dir, state=record.status)
    except Exception as exc:
        error_message = str(exc)
        _atomic_write_json(
            run_dir / "artifacts" / "candidate_cards_error.json",
            {"error": error_message, "_stage_timings": stage_timings},
        )
        with lock:
            record, run_dir = _load_run_with_dir(run_id)
            if record.status == "cancelled":
                return
            finished_at = _utc_iso()
            record.status = "failed"
            record.finished_at = finished_at
            record.error = error_message
            if record.steps:
                step = record.steps[0]
                step.status = "failed"
                step.finished_at = finished_at
                step.error = error_message
            _update_run_progress(
                record,
                stage="failed",
                message=error_message,
                step_index=0 if record.steps else None,
                timestamp=finished_at,
            )
            _save_run(record, run_dir=run_dir)
            _update_run_provenance_state(
                run_dir, state=record.status, error=record.error
            )
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()


@mcp.tool()
def kg_hypothesis_candidate_cards_start(
    query: str,
    seed_kg_ids: list[str] | None = None,
    relation_types: list[str] | None = None,
    top_n: int = 5,
    top_k: int = 20,
    taste_mode: enum_str(
        ("balanced", "novelty_first", "evidence_first"), "ranking taste"
    ) = "balanced",
    controller_mode: enum_str(("principle_v0",), "controller policy") = "principle_v0",
    candidate_lane_mode: enum_str(
        ("broad", "strict"), "candidate recall lane"
    ) = "broad",
    with_deep_research: bool = True,
    deep_research_interaction_id: str | None = None,
    recency_days: int = 365,
    exclude_domains: list[str] | None = None,
    semantic: bool = False,
) -> dict[str, Any]:
    """Start a background candidate cards generation run and return a pollable run_id."""
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {"ok": False, "error": "query is required"}

    try:
        top_n_i = int(top_n)
    except (TypeError, ValueError):
        return {"ok": False, "error": "top_n must be an integer"}
    if top_n_i < 1:
        return {"ok": False, "error": "top_n must be >= 1"}

    try:
        top_k_i = int(top_k)
    except (TypeError, ValueError):
        return {"ok": False, "error": "top_k must be an integer"}
    if top_k_i < 1:
        return {"ok": False, "error": "top_k must be >= 1"}

    try:
        recency_days_i = int(recency_days)
    except (TypeError, ValueError):
        return {"ok": False, "error": "recency_days must be an integer"}
    if recency_days_i < 0:
        return {"ok": False, "error": "recency_days must be >= 0"}

    workflow_params = _compact_kwargs(
        {
            "query": normalized_query,
            "seed_kg_ids": _coerce_non_empty_str_list(seed_kg_ids),
            "relation_types": _coerce_non_empty_str_list(relation_types),
            "top_k": top_k_i,
            "n_samples": top_n_i,
            "taste_mode": coerce_enum(taste_mode, _TASTE_MODE_ALIASES, "balanced"),
            "controller_mode": coerce_enum(
                controller_mode, _CONTROLLER_MODE_ALIASES, "principle_v0"
            ),
            "candidate_lane_mode": coerce_enum(
                candidate_lane_mode, _CANDIDATE_LANE_MODE_ALIASES, "broad"
            ),
            "use_external_literature": bool(with_deep_research),
            "external_literature_top_k": min(top_k_i, 5),
            "external_literature_recency_days": recency_days_i,
            "external_literature_exclude_domains": _coerce_non_empty_str_list(
                exclude_domains
            ),
        }
    )

    run_id = _new_run_id()
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "work").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    provenance = {
        "run_id": run_id,
        "mode": "mcp",
        "route": "kg_hypothesis_candidate_cards_start",
        "request": {
            "query": normalized_query,
            "top_n": top_n_i,
            "top_k": top_k_i,
            "with_deep_research": with_deep_research,
            "recency_days": recency_days_i,
        },
    }
    _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))

    record = RunRecord(
        run_id=run_id,
        created_at=_utc_iso(),
        status="queued",
        dry_run=False,
        progress={
            "current_stage": "queued",
            "message": "Queued candidate cards generation",
            "last_progress_at": _utc_iso(),
        },
        timing_policy=_default_run_timing_policy(),
        steps=[
            StepRecord(
                step_id="candidate_cards",
                tool_id="kg_hypothesis_candidate_cards",
                params={
                    "query": normalized_query,
                    "top_n": top_n_i,
                    "top_k": top_k_i,
                    "with_deep_research": with_deep_research,
                },
                status="queued",
                progress={
                    "current_stage": "queued",
                    "message": "Queued candidate cards generation",
                    "last_progress_at": _utc_iso(),
                },
            )
        ],
    )
    _save_run(record, run_dir=run_dir)

    core_params: dict[str, Any] = {
        "workflow_params": workflow_params,
        "with_deep_research": with_deep_research,
        "deep_research_interaction_id": deep_research_interaction_id,
        "normalized_query": normalized_query,
        "top_n_i": top_n_i,
        "top_k_i": top_k_i,
        "recency_days_i": recency_days_i,
        "exclude_domains": exclude_domains,
        "semantic": semantic,
    }

    thread = threading.Thread(
        target=_execute_candidate_cards_run,
        args=(run_id, core_params),
        daemon=False,
    )
    thread.start()

    return _background_launch_response(
        run_id=run_id,
        run_dir=run_dir,
        compat_poll_tool="kg_hypothesis_candidate_cards_get",
    )


@mcp.tool()
def kg_hypothesis_candidate_cards_get(run_id: str) -> dict[str, Any]:
    """Fetch background candidate cards run status, progress, and final payload when available."""
    param_keys = sorted(locals().keys())
    response = dict(run_get(run_id))
    if response.get("ok") is not True:
        return _return_compat_alias_response(
            "kg_hypothesis_candidate_cards_get",
            response,
            param_keys=param_keys,
        )

    run_payload = response.get("run")
    status = str((run_payload or {}).get("status") or "")
    response.update(
        {
            "run_id": str((run_payload or {}).get("run_id") or run_id),
            "status": status,
            "done": status in _MCP_RUN_TERMINAL_STATUSES,
            "execution_mode": "background",
        }
    )
    return _return_compat_alias_response(
        "kg_hypothesis_candidate_cards_get",
        response,
        param_keys=param_keys,
    )


@mcp.tool()
def kg_detect_topology_shifts(
    mode: enum_str(("detect", "apply"), "detect proposals or apply them") = "detect",
    baseline_ref: str | None = None,
    current_ref: str | None = None,
    scope: str | None = None,
    approval_phrase: str | None = None,
) -> dict[str, Any]:
    """Detect or apply topology-shift updates across graph snapshots."""
    normalized_mode, mode_err = resolve_enum_or_error(
        mode, _TOPOLOGY_SHIFT_MODE_ALIASES, field="mode"
    )
    if mode_err is not None:
        return {**mode_err, "error": "mode must be one of: detect, apply"}

    if normalized_mode == "apply":
        topology_write_enabled = _truthy(os.getenv("BR_KG_TOPOLOGY_WRITE_ENABLED"))
        allow_dangerous = _truthy(os.getenv("BR_MCP_ALLOW_DANGEROUS"))
        approval_ok = approval_phrase == "I_UNDERSTAND_WRITE_RISK"
        if not (topology_write_enabled and allow_dangerous and approval_ok):
            return {"ok": False, "error": "policy_rejected"}

    try:
        from brain_researcher.services.br_kg import query_service

        query_mode = "apply" if normalized_mode == "apply" else "proposal"
        update_reason: str | None = None
        if baseline_ref or current_ref or scope:
            update_reason = (
                f"baseline={baseline_ref or 'na'};"
                f"current={current_ref or 'na'};"
                f"scope={scope or 'na'}"
            )

        result = query_service.detect_topology_shifts(
            **_compact_kwargs(
                {
                    "mode": query_mode,
                    "update_reason": update_reason,
                }
            )
        )
        return {"ok": True, "result": _kg_result_payload(result)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _grounding_kg_lookup(kg_id: str) -> dict[str, Any] | None:
    from brain_researcher.services.br_kg import query_service

    node = query_service.node_details(kg_id, include_neighbors=True)
    if node is None:
        return None
    node_payload = node.model_dump() if hasattr(node, "model_dump") else dict(node)
    props = dict(node_payload.get("properties") or {})
    label = str(node_payload.get("label") or kg_id)
    node_type = str(node_payload.get("node_type") or "Node")
    return {
        "support_text": f"{node_type} {label}",
        "provenance": {
            "resolver": "br_kg.node_details",
            "kg_id": node_payload.get("kg_id") or kg_id,
            "properties": props,
        },
    }


def _grounding_session_lookup(
    card_ref: str, *, run_root: Any = None
) -> dict[str, Any] | None:
    from brain_researcher.services.memory.store import MemoryStore

    store = MemoryStore(run_root=run_root) if run_root is not None else MemoryStore()
    result = store.get(card_ref)
    if not result.get("ok"):
        search_result = store.search(card_ref, limit=5)
        for card in search_result.get("cards") or []:
            if not isinstance(card, dict):
                continue
            if card_ref in {
                str(card.get("card_id") or ""),
                str(card.get("stable_key") or ""),
            }:
                result = {"ok": True, "card": card}
                break
    if not result.get("ok") or not isinstance(result.get("card"), dict):
        return None
    card = dict(result["card"])
    support_text = (
        card.get("claim_text")
        or card.get("output_summary")
        or card.get("task_description")
        or card.get("embedding_text")
        or card_ref
    )
    return {
        "support_text": str(support_text),
        "provenance": {
            "resolver": "memory_store",
            "card_id": card.get("card_id"),
            "stable_key": card.get("stable_key"),
            "created_at": card.get("created_at"),
            "card_type": card.get("card_type"),
        },
    }


# ---------------------------------------------------------------------------
# Grounding + Google File Search tools (google_file_search / grounding_resolve
# / grounding_gate_evidence_basis) extracted to mcp/routers/grounding.py.
# Importing it registers those tools (import side effect). The
# _grounding_kg_lookup / _grounding_session_lookup resolvers stay here (other
# in-server callers) and are imported back by the router.
# ---------------------------------------------------------------------------
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    grounding as _grounding_router,
)

_DR_COMPLETED_STATUSES = {
    "completed",
    "complete",
    "done",
    "finished",
    "succeeded",
    "success",
    "ok",
    "ready",
}
_DR_TERMINAL_ERROR_STATUSES = {
    "failed",
    "error",
    "cancelled",
    "canceled",
    "expired",
    "rejected",
}
_DR_SUMMARY_MAX_CHARS = 4000
_GOOGLE_DEEP_RESEARCH_RESULT_RELPATH = "artifacts/google_deep_research.result.json"


def _dr_normalize_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-]+", "_", text)


def _dr_extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    response_obj = getattr(exc, "response", None) or getattr(exc, "http_response", None)
    if response_obj is None:
        return None
    for attr in ("status_code", "status", "code"):
        value = getattr(response_obj, attr, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _dr_exception_payload(exc: Exception) -> dict[str, Any]:
    status_code = _dr_extract_status_code(exc)
    message = str(exc)
    lowered = message.lower()
    retryable = bool(
        status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        or any(
            token in lowered
            for token in (
                "timeout",
                "timed out",
                "temporarily unavailable",
                "connection",
                "rate limit",
                "unavailable",
                "econnreset",
            )
        )
    )
    payload: dict[str, Any] = {
        "error": message,
        "error_type": exc.__class__.__name__,
        "retryable": retryable,
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return payload


def _dr_collect_urls(payload: Any) -> set[str]:
    urls: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            for matched in re.findall(r"https?://[^\s\)\]\}<>]+", node):
                urls.add(matched.strip())
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("url", "uri", "href", "link", "source"):
            value = node.get(key)
            if isinstance(value, str) and value.strip().startswith(
                ("http://", "https://")
            ):
                urls.add(value.strip())
        for value in node.values():
            _walk(value)

    _walk(payload)
    return urls


def _dr_read_field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _dr_extract_text_from_candidates(value: Any) -> str:
    candidates = _dr_read_field(value, "candidates")
    if not isinstance(candidates, list | tuple):
        return ""

    chunks: list[str] = []
    for candidate in candidates:
        content = _dr_read_field(candidate, "content")
        parts = _dr_read_field(content, "parts")
        if not isinstance(parts, list | tuple):
            continue
        part_texts: list[str] = []
        for part in parts:
            text = _dr_read_field(part, "text")
            if isinstance(text, str) and text.strip():
                part_texts.append(text.strip())
        if part_texts:
            chunks.append("\n".join(part_texts))
    return "\n\n".join(chunks).strip()


def _dr_is_opaque_token_like(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return False
    if any(char.isspace() for char in text):
        return False
    if len(text) < 40 or not _DR_OPAQUE_TOKEN_RE.match(text):
        return False
    if "." not in text and "/" not in text:
        return True
    return text.count("_") + text.count("-") >= 2 and len(text) >= 56


def _dr_collect_preferred_text_candidates(
    payload: Any, candidates: list[str], *, accept_raw_strings: bool = False
) -> None:
    if payload is None:
        return
    if isinstance(payload, str):
        if accept_raw_strings:
            candidates.append(payload)
        return
    if isinstance(payload, list):
        for item in payload:
            _dr_collect_preferred_text_candidates(
                item, candidates, accept_raw_strings=accept_raw_strings
            )
        return
    if not isinstance(payload, dict):
        return

    prioritized_keys = (
        "outputs",
        "text",
        "output_text",
        "summary",
        "content",
        "output",
        "message",
    )
    for key in prioritized_keys:
        value = payload.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict | list):
            _dr_collect_preferred_text_candidates(
                value, candidates, accept_raw_strings=True
            )

    for key, value in payload.items():
        if key in prioritized_keys:
            continue
        if isinstance(value, dict | list):
            _dr_collect_preferred_text_candidates(
                value, candidates, accept_raw_strings=False
            )


def _dr_extract_text(payload: Any) -> str:
    candidate_text = _dr_extract_text_from_candidates(payload)
    if candidate_text and not _dr_is_opaque_token_like(candidate_text):
        return candidate_text

    candidates: list[str] = []
    _dr_collect_preferred_text_candidates(payload, candidates)

    fallback = ""
    for candidate in candidates:
        normalized = str(candidate).strip()
        if not normalized:
            continue
        if not fallback:
            fallback = normalized
        if _dr_is_opaque_token_like(normalized):
            continue
        return normalized

    if fallback and not _dr_is_opaque_token_like(fallback):
        return fallback
    return ""


def _dr_json_safe(value: Any) -> Any:
    """Convert nested provider payloads to JSON-safe primitives."""
    if value is None or isinstance(value, int | float | bool):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8", "replace")
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, dict):
        return {
            str(_dr_json_safe(key)): _dr_json_safe(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [_dr_json_safe(inner) for inner in value]
    if hasattr(value, "model_dump"):
        try:
            return _dr_json_safe(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _dr_json_safe(value.dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _dr_json_safe(vars(value))
        except Exception:
            pass
    return str(value).encode("utf-8", "replace").decode("utf-8", "replace")


def _dr_normalize_summary_text(
    text: Any, *, max_chars: int | None = _DR_SUMMARY_MAX_CHARS
) -> str:
    if not isinstance(text, str):
        return ""
    safe_text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    normalized_lines = [
        re.sub(r"\s+", " ", line).strip() for line in safe_text.splitlines()
    ]
    normalized = "\n".join(line for line in normalized_lines if line).strip()
    if max_chars is None or len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _dr_extract_sources(payload: Any) -> list[dict[str, Any]]:
    safe_payload = _dr_json_safe(payload)
    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def _add_source(url_value: Any, title_value: Any = None) -> None:
        if not isinstance(url_value, str):
            return
        url = url_value.strip()
        if not url.startswith(("http://", "https://")) or url in seen_urls:
            return
        seen_urls.add(url)
        title = (
            title_value.strip()
            if isinstance(title_value, str) and title_value.strip()
            else None
        )
        sources.append({"url": url, "title": title})

    def _walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                _walk(item)
            return
        if not isinstance(value, dict):
            return

        _add_source(
            value.get("uri")
            or value.get("url")
            or value.get("link")
            or value.get("href")
            or value.get("source"),
            value.get("title") or value.get("name") or value.get("label"),
        )

        grounding = value.get("grounding_metadata") or value.get("groundingMetadata")
        if isinstance(grounding, dict):
            chunks = grounding.get("grounding_chunks") or grounding.get(
                "groundingChunks"
            )
            if isinstance(chunks, list):
                for chunk in chunks:
                    if not isinstance(chunk, dict):
                        continue
                    _add_source(
                        chunk.get("uri")
                        or chunk.get("url")
                        or chunk.get("link")
                        or chunk.get("href"),
                        chunk.get("title") or chunk.get("name") or chunk.get("label"),
                    )
                    web = chunk.get("web")
                    if isinstance(web, dict):
                        _add_source(
                            web.get("uri") or web.get("url"),
                            web.get("title") or web.get("name"),
                        )
                    retrieved_context = chunk.get("retrieved_context") or chunk.get(
                        "retrievedContext"
                    )
                    if isinstance(retrieved_context, dict):
                        _add_source(
                            retrieved_context.get("uri")
                            or retrieved_context.get("url")
                            or retrieved_context.get("link")
                            or retrieved_context.get("href"),
                            retrieved_context.get("title")
                            or retrieved_context.get("name")
                            or retrieved_context.get("label"),
                        )

        for item in value.values():
            _walk(item)

    _walk(safe_payload)
    return sources


def _dr_build_normalized_payload(
    *,
    status: Any,
    raw_payload: Any,
    summary_text: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    safe_payload = _dr_json_safe(raw_payload)
    raw_text = (
        summary_text
        if isinstance(summary_text, str)
        else _dr_extract_text(safe_payload)
    )
    normalized_full_text = _dr_normalize_summary_text(raw_text, max_chars=None)
    summary = _dr_normalize_summary_text(normalized_full_text)
    sources = _dr_extract_sources(safe_payload)
    diagnostics = _dr_build_interaction_diagnostics(status, safe_payload)
    diagnostics["summary_chars"] = len(summary)
    diagnostics["summary_truncated"] = len(normalized_full_text) > len(summary)
    diagnostics["source_count"] = len(sources)
    diagnostics["raw_included"] = include_raw

    payload: dict[str, Any] = {
        "summary": summary,
        "synthesis_full_text": normalized_full_text,
        "sources": sources,
        "diagnostics": diagnostics,
        "text": normalized_full_text,
        "documents": [
            {"doc_id": f"src_{idx + 1}", "title": item.get("title"), "url": item["url"]}
            for idx, item in enumerate(sources)
        ],
    }
    if include_raw:
        payload["raw_response"] = safe_payload
        payload["response"] = safe_payload
    return payload


def _google_deep_research_fetch(
    interaction_id: str, *, include_raw: bool = False
) -> dict[str, Any]:
    if not ALLOW_NETWORK:
        return {
            "ok": False,
            "error": "network_blocked",
            "message": "Set BR_MCP_ALLOW_NETWORK=1 to enable Google APIs.",
        }

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "missing_api_key",
            "message": "Set GOOGLE_API_KEY or GEMINI_API_KEY to use google_deep_research_get.",
        }

    try:
        from google import genai
    except ImportError as exc:
        return {"ok": False, **_dr_exception_payload(exc)}

    client = genai.Client(api_key=api_key)
    if not hasattr(client, "interactions"):
        return {
            "ok": False,
            "error": "interactions_not_supported",
            "message": "google-genai SDK missing Interactions API; upgrade google-genai >= 1.55.0.",
        }

    try:
        try:
            interaction = client.interactions.get(interaction_id)
        except TypeError:
            interaction = client.interactions.get(name=interaction_id)
        interaction_id_out = getattr(interaction, "id", None) or getattr(
            interaction, "name", None
        )
        status = getattr(interaction, "status", None) or getattr(
            interaction, "state", None
        )
        response = (
            interaction.model_dump()
            if hasattr(interaction, "model_dump")
            else {"raw": str(interaction)}
        )
        normalized = _dr_build_normalized_payload(
            status=status,
            raw_payload=response,
            include_raw=include_raw,
        )
        return {
            "ok": True,
            "data": {
                "interaction_id": interaction_id_out or interaction_id,
                "status": status,
                **normalized,
            },
        }
    except Exception as exc:
        return {"ok": False, **_dr_exception_payload(exc)}


def _google_deep_research_run_status(data: dict[str, Any]) -> str:
    diagnostics = data.get("diagnostics")
    if isinstance(diagnostics, dict):
        normalized = _normalize_agent_run_status(diagnostics.get("status_normalized"))
        if normalized:
            return normalized
    normalized = _normalize_agent_run_status(data.get("status"))
    return normalized or "running"


def _google_deep_research_progress_message(data: dict[str, Any]) -> str:
    diagnostics = data.get("diagnostics")
    status_normalized = ""
    if isinstance(diagnostics, dict):
        status_normalized = str(diagnostics.get("status_normalized") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if summary:
        return summary[:160]
    if status_normalized:
        return f"Deep Research provider status: {status_normalized}"
    status_text = str(data.get("status") or "").strip()
    if status_text:
        return f"Deep Research provider status: {status_text}"
    return "Deep Research provider accepted request"


def _persist_google_deep_research_result(
    run_dir: Path, payload: dict[str, Any]
) -> None:
    _atomic_write_json(run_dir / _GOOGLE_DEEP_RESEARCH_RESULT_RELPATH, payload)


def _load_google_deep_research_result(run_dir: Path) -> dict[str, Any] | None:
    target = run_dir / _GOOGLE_DEEP_RESEARCH_RESULT_RELPATH
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _reconcile_google_deep_research_run_record(
    record: RunRecord,
    *,
    run_dir: Path,
    data: dict[str, Any],
) -> RunRecord:
    normalized_status = _google_deep_research_run_status(data)
    now = _utc_iso()
    changed = False
    if record.status != normalized_status:
        record.status = normalized_status
        changed = True
    if record.started_at is None:
        record.started_at = now
        changed = True
    if normalized_status in _MCP_RUN_TERMINAL_STATUSES and record.finished_at != now:
        record.finished_at = now
        changed = True
    if normalized_status == "failed":
        new_error = str(
            data.get("summary") or data.get("text") or "google_deep_research_failed"
        )
        if record.error != new_error:
            record.error = new_error
            changed = True
    elif normalized_status == "cancelled":
        cancel_error = str(data.get("summary") or "cancelled")
        if record.error != cancel_error:
            record.error = cancel_error
            changed = True
    elif record.error is not None:
        record.error = None
        changed = True

    progress_pct = 100.0 if normalized_status in _MCP_RUN_TERMINAL_STATUSES else None
    _update_run_progress(
        record,
        stage="google_deep_research",
        message=_google_deep_research_progress_message(data),
        progress_pct=progress_pct,
        step_index=0 if record.steps else None,
        timestamp=now,
    )

    if record.steps:
        current = record.steps[0]
        desired_step_status = {
            "queued": "queued",
            "running": "running",
            "succeeded": "succeeded",
            "failed": "failed",
            "cancelled": "skipped",
        }.get(normalized_status)
        if desired_step_status and current.status != desired_step_status:
            current.status = desired_step_status
            changed = True
        if current.started_at is None:
            current.started_at = now
            changed = True
        if (
            normalized_status in _MCP_RUN_TERMINAL_STATUSES
            and current.finished_at != now
        ):
            current.finished_at = now
            changed = True
        if normalized_status == "failed":
            new_error = str(record.error or "google_deep_research_failed")
            if current.error != new_error:
                current.error = new_error
                changed = True
        elif normalized_status == "cancelled":
            new_error = str(record.error or "cancelled")
            if current.error != new_error:
                current.error = new_error
                changed = True
        elif current.error is not None:
            current.error = None
            changed = True
        if (
            normalized_status in _MCP_RUN_TERMINAL_STATUSES
            and current.result_path != _GOOGLE_DEEP_RESEARCH_RESULT_RELPATH
        ):
            current.result_path = _GOOGLE_DEEP_RESEARCH_RESULT_RELPATH
            changed = True

    if normalized_status in _MCP_RUN_TERMINAL_STATUSES:
        _persist_google_deep_research_result(run_dir, data)
    if changed:
        _save_run(record, run_dir=run_dir)
        _update_run_provenance_state(run_dir, state=record.status, error=record.error)
    return record


def _dr_build_interaction_diagnostics(status: Any, payload: Any) -> dict[str, Any]:
    status_normalized = _dr_normalize_status(status)
    urls = _dr_collect_urls(payload)
    text = _dr_extract_text(payload)
    terminal_error = status_normalized in _DR_TERMINAL_ERROR_STATUSES
    terminal = terminal_error or status_normalized in _DR_COMPLETED_STATUSES
    return {
        "status_normalized": status_normalized or "unknown",
        "terminal": terminal,
        "terminal_error": terminal_error,
        "extractable_text": bool(text),
        "source_count": len(urls),
    }


@mcp.tool()
def google_deep_research_start(
    input: str | None = None,
    agent: str = "deep-research-pro-preview-12-2025",
    file_search_store_names: list[str] | None = None,
    store_names: list[str] | None = None,
    previous_interaction_id: str | None = None,
    query: str | None = None,
    scientific_mode: bool | None = None,
) -> dict[str, Any]:
    """Start a Deep Research task via Gemini Interactions API (background)."""
    if not ALLOW_NETWORK:
        return {
            "ok": False,
            "error": "network_blocked",
            "message": "Set BR_MCP_ALLOW_NETWORK=1 to enable Google APIs.",
        }

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "missing_api_key",
            "message": "Set GOOGLE_API_KEY or GEMINI_API_KEY to use google_deep_research_start.",
        }

    prompt = input or query
    if not prompt:
        return {"ok": False, "error": "missing_input", "message": "Provide input text."}
    use_scientific_mode = _resolve_google_deep_research_scientific_mode(
        prompt, scientific_mode
    )
    provider_input = _build_google_deep_research_background_input(
        prompt, scientific_mode=use_scientific_mode
    )

    def _normalize_store_name(name: str) -> str:
        if not name:
            return name
        return (
            name if name.startswith("fileSearchStores/") else f"fileSearchStores/{name}"
        )

    stores = file_search_store_names or store_names or []
    if isinstance(stores, str):
        stores = [stores]
    if not stores:
        multi = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
        if multi:
            stores = [s.strip() for s in multi.split(",") if s.strip()]
        else:
            single_store = (
                os.environ.get("FILE_SEARCH_STORE")
                or os.environ.get("BR_FILE_SEARCH_STORE")
                or os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE")
                or os.environ.get("GOOGLE_FILE_SEARCH_STORE")
            )
            stores = [single_store] if single_store else []
    stores = [_normalize_store_name(s) for s in stores if s]
    tools: list[dict[str, Any]] = [{"type": "google_search"}]
    if stores:
        tools.append({"type": "file_search", "file_search_store_names": stores})

    try:
        from google import genai
    except ImportError as exc:
        return {"ok": False, **_dr_exception_payload(exc)}

    client = genai.Client(api_key=api_key)
    if not hasattr(client, "interactions"):
        return {
            "ok": False,
            "error": "interactions_not_supported",
            "message": "google-genai SDK missing Interactions API; upgrade google-genai >= 1.55.0.",
        }

    payload = {
        "input": provider_input,
        "agent": agent,
        "background": True,
        "tools": tools,
    }
    if previous_interaction_id:
        payload["previous_interaction_id"] = previous_interaction_id

    try:
        interaction = call_mcp_platform_api_with_fee(
            lambda: client.interactions.create(**payload),
            provider="google",
            model=agent,
            call_prefix="google_deep_research_start",
            estimated_cost_usd=_env_float(
                "BR_MCP_GOOGLE_DEEP_RESEARCH_START_RESERVE_USD", 0.05
            ),
        )
        interaction_id = getattr(interaction, "id", None) or getattr(
            interaction, "name", None
        )
        status = getattr(interaction, "status", None) or getattr(
            interaction, "state", None
        )
        response = (
            interaction.model_dump()
            if hasattr(interaction, "model_dump")
            else {"raw": str(interaction)}
        )
        run_id = _new_run_id()
        run_dir = _run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "work").mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        now = _utc_iso()
        provenance = {
            "run_id": run_id,
            "mode": "mcp",
            "route": "google_deep_research_start",
            "transport": DEFAULT_TRANSPORT,
            "request": {
                "input": prompt,
                "provider_input": provider_input,
                "agent": agent,
                "file_search_store_names": stores,
                "previous_interaction_id": previous_interaction_id,
                "scientific_mode": use_scientific_mode,
            },
            "delegated_execution": {
                "backend": "google_deep_research",
                "provider": "google_genai_interactions",
                "interaction_id": interaction_id,
                "delegated_at": now,
            },
            "state": "queued",
        }
        _atomic_write_json(run_dir / "provenance.json", _redact_for_logging(provenance))
        record = RunRecord(
            run_id=run_id,
            created_at=now,
            status="queued",
            progress={
                "current_stage": "google_deep_research",
                "message": (
                    "Deep Research provider accepted request"
                    + (f" ({status})" if status else "")
                ),
                "last_progress_at": now,
            },
            timing_policy=_default_run_timing_policy(),
            steps=[
                StepRecord(
                    step_id="google_deep_research",
                    tool_id="google_deep_research_start",
                    params={
                        "input": prompt,
                        "provider_input": provider_input,
                        "agent": agent,
                        "file_search_store_names": stores,
                        "previous_interaction_id": previous_interaction_id,
                        "scientific_mode": use_scientific_mode,
                    },
                    status="queued",
                    progress={
                        "current_stage": "google_deep_research",
                        "message": (
                            "Deep Research provider accepted request"
                            + (f" ({status})" if status else "")
                        ),
                        "last_progress_at": now,
                    },
                )
            ],
        )
        _save_run(record, run_dir=run_dir)
        return _background_launch_response(
            run_id=run_id,
            run_dir=run_dir,
            compat_poll_tool="google_deep_research_get",
            execution_trace=(
                [
                    "validated",
                    "scientific_mode_enabled",
                    "provider_request_accepted",
                    "queued_background_run",
                ]
                if use_scientific_mode
                else [
                    "validated",
                    "provider_request_accepted",
                    "queued_background_run",
                ]
            ),
            extra={
                "interaction_id": interaction_id,
                "scientific_mode": use_scientific_mode,
                "data": {
                    "interaction_id": interaction_id,
                    "status": status,
                    "scientific_mode": use_scientific_mode,
                    "response": response,
                },
            },
        )
    except ApiFeeReservationError as exc:
        return api_fee_error_payload(exc)
    except Exception as exc:
        return {"ok": False, **_dr_exception_payload(exc)}


@mcp.tool()
def google_deep_research_get(
    interaction_id: str, include_raw: bool = False
) -> dict[str, Any]:
    """Fetch a Deep Research task result via Gemini Interactions API."""
    param_keys = sorted(locals().keys())
    try:
        record, run_dir = _load_run_with_dir(interaction_id)
        marker = _load_delegated_execution_marker(run_dir)
    except Exception:
        record, run_dir, marker = None, None, None

    if (
        record is not None
        and run_dir is not None
        and isinstance(marker, dict)
        and str(marker.get("backend") or "") == "google_deep_research"
    ):
        sync_error = None
        record, proxied = _maybe_sync_delegated_run_record(
            interaction_id, record, run_dir
        )
        if proxied is not None and proxied.get("ok") is not True:
            sync_error = proxied
        result_payload = _load_google_deep_research_result(run_dir)
        if result_payload is None:
            provider_interaction_id = str(marker.get("interaction_id") or "").strip()
            if provider_interaction_id:
                fetched = _google_deep_research_fetch(
                    provider_interaction_id,
                    include_raw=include_raw,
                )
                if fetched.get("ok") is True and isinstance(fetched.get("data"), dict):
                    result_payload = fetched["data"]
                    if record.status in _MCP_RUN_TERMINAL_STATUSES:
                        _persist_google_deep_research_result(run_dir, result_payload)
                elif sync_error is None:
                    sync_error = fetched
        if sync_error is not None and result_payload is None:
            return sync_error
        run_payload = asdict(record)
        provenance = _load_run_provenance(run_dir)
        request_meta = (
            provenance.get("request") if isinstance(provenance, dict) else None
        )
        scientific_mode = False
        if isinstance(request_meta, dict):
            scientific_mode = bool(request_meta.get("scientific_mode"))
        response: dict[str, Any] = {
            "ok": True,
            "run_id": run_payload.get("run_id") or interaction_id,
            "status": run_payload.get("status"),
            "done": str(run_payload.get("status") or "") in _MCP_RUN_TERMINAL_STATUSES,
            "run": run_payload,
            "run_dir": str(run_dir),
            "execution_mode": "background",
            "scientific_mode": scientific_mode,
            "progress": _run_progress_snapshot(run_payload),
        }
        if result_payload is not None:
            response["data"] = {**result_payload, "scientific_mode": scientific_mode}
        return _return_compat_alias_response(
            "google_deep_research_get",
            response,
            param_keys=param_keys,
        )

    return _return_compat_alias_response(
        "google_deep_research_get",
        _google_deep_research_fetch(interaction_id, include_raw=include_raw),
        param_keys=param_keys,
    )


_DEEP_RESEARCH_SCIENTIFIC_HINTS = (
    "paper",
    "papers",
    "study",
    "studies",
    "journal",
    "doi",
    "pmid",
    "pmcid",
    "pubmed",
    "clinical trial",
    "meta-analysis",
    "systematic review",
    "preprint",
    "arxiv",
    "biorxiv",
    "medrxiv",
    "neuroimaging",
    "fmri",
    "mri",
    "eeg",
    "dataset",
    "datasets",
    "biomarker",
)
_DEEP_RESEARCH_SCIENTIFIC_EXCLUDE_DOMAINS = (
    "researchgate.net",
    "sciencedaily.com",
    "eurekalert.org",
    "medicalxpress.com",
    "news-medical.net",
    "phys.org",
)
_DEEP_RESEARCH_PRIMARY_SOURCE_GUIDANCE = (
    "Prefer PubMed, PMC, journal publisher pages, official preprints, datasets, "
    "and other first-party research artifacts. Avoid press releases, "
    "ResearchGate mirrors, news summaries, and blog posts unless no primary "
    "source exists. Explicitly say when evidence comes from secondary coverage "
    "only."
)
_DEEP_RESEARCH_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
_DEEP_RESEARCH_PMCID_RE = re.compile(r"\bPMC\d+\b", re.IGNORECASE)
_DEEP_RESEARCH_PMID_REF_RE = re.compile(r"(?:pmid[:\s]*|pubmed/)(\d+)", re.IGNORECASE)
_DEEP_RESEARCH_ELSEVIER_PII_RE = re.compile(
    r"\bS\d{4}-\d{4}\(\d{2}\)\d{5}-\d\b", re.IGNORECASE
)


def _normalize_deep_research_doi(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _DEEP_RESEARCH_DOI_RE.search(text)
    if not match:
        return ""
    return match.group(1).lower().rstrip(".,;:)]}")


def _normalize_deep_research_pmcid(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _DEEP_RESEARCH_PMCID_RE.search(text)
    return match.group(0).upper() if match else ""


def _normalize_deep_research_pmid(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return text
    match = _DEEP_RESEARCH_PMID_REF_RE.search(text)
    return match.group(1) if match else ""


def _normalize_deep_research_pii(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^pii:\s*", "", text, flags=re.IGNORECASE)
    match = _DEEP_RESEARCH_ELSEVIER_PII_RE.search(text)
    return match.group(0).upper() if match else ""


def _looks_like_scientific_query(query: str) -> bool:
    normalized = " ".join(str(query or "").lower().split())
    if not normalized:
        return False
    if _DEEP_RESEARCH_DOI_RE.search(normalized):
        return True
    if _DEEP_RESEARCH_PMCID_RE.search(normalized):
        return True
    if _DEEP_RESEARCH_PMID_REF_RE.search(normalized):
        return True
    return any(hint in normalized for hint in _DEEP_RESEARCH_SCIENTIFIC_HINTS)


def _resolve_google_deep_research_scientific_mode(
    query: str, scientific_mode: bool | None
) -> bool:
    if scientific_mode is not None:
        return bool(scientific_mode)
    return _looks_like_scientific_query(query)


def _merge_domain_excludes(
    exclude_domains: list[str] | None, extra_domains: tuple[str, ...]
) -> list[str] | None:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in [*(exclude_domains or []), *extra_domains]:
        domain = str(raw or "").strip().lower()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        merged.append(domain)
    return merged or None


def _build_google_deep_research_background_input(
    prompt: str, *, scientific_mode: bool
) -> str:
    normalized_prompt = str(prompt or "").strip()
    if not scientific_mode:
        return normalized_prompt
    return (
        "Scientific research mode.\n"
        "Constraints:\n"
        f"- {_DEEP_RESEARCH_PRIMARY_SOURCE_GUIDANCE}\n"
        "- If a paper is not available in PMC, prefer PubMed or the publisher page "
        "over secondary summaries.\n"
        "- Flag any claim that could only be grounded in secondary coverage.\n\n"
        f"Task:\n{normalized_prompt}"
    ).strip()


@mcp.tool()
def google_deep_research(
    query: str,
    model: str = "gemini-3-flash-preview",
    max_output_tokens: int = 2048,
    temperature: float = 0.2,
    recency_days: int | None = None,
    exclude_domains: list[str] | None = None,
    scientific_mode: bool | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Deep research via Gemini + Google Search tool (first-class MCP tool)."""
    if not ALLOW_NETWORK:
        return {
            "ok": False,
            "error": "network_blocked",
            "message": "Set BR_MCP_ALLOW_NETWORK=1 to enable Google Search grounding.",
        }

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "missing_api_key",
            "message": "Set GOOGLE_API_KEY or GEMINI_API_KEY to use google_deep_research.",
        }

    recency_hint = ""
    if recency_days is not None and int(recency_days) > 0:
        recency_hint = f"Prefer sources from the last {int(recency_days)} days.\n"

    use_scientific_mode = _resolve_google_deep_research_scientific_mode(
        query, scientific_mode
    )
    effective_exclude_domains = exclude_domains
    system_instruction = (
        "You are a careful research assistant. Use Google Search to ground claims. "
        "Cite sources with URLs. If uncertain, say so."
    )
    if use_scientific_mode:
        effective_exclude_domains = _merge_domain_excludes(
            exclude_domains, _DEEP_RESEARCH_SCIENTIFIC_EXCLUDE_DOMAINS
        )
        system_instruction = (
            "You are a careful scientific research assistant. Use Google Search to "
            "ground claims in primary sources whenever possible. "
            f"{_DEEP_RESEARCH_PRIMARY_SOURCE_GUIDANCE} Cite sources with URLs. "
            "If uncertain, say so."
        )

    prompt = (
        f"{recency_hint}"
        f"Task: {query}\n\n"
        "Deliverables:\n"
        "1) Executive summary (5-10 bullets)\n"
        "2) Detailed findings with inline citations (URLs)\n"
        "3) Source list (URLs) at the end\n"
    )
    if use_scientific_mode:
        prompt += (
            "4) Briefly flag any claim that could only be supported by secondary "
            "coverage or where no primary paper/page was found\n"
        )

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        google_search = genai.types.GoogleSearch(
            exclude_domains=effective_exclude_domains
        )
        tools = [genai.types.Tool(google_search=google_search)]

        config = genai.types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            response_modalities=["text"],
            max_output_tokens=int(max_output_tokens),
            temperature=float(temperature),
        )
        resp = call_mcp_platform_api_with_fee(
            lambda: client.models.generate_content(
                model=model, contents=prompt, config=config
            ),
            provider="google",
            model=model,
            call_prefix="google_deep_research",
            estimated_cost_usd=_env_float(
                "BR_MCP_GOOGLE_DEEP_RESEARCH_RESERVE_USD", 0.05
            ),
        )
        raw_response: Any
        if hasattr(resp, "model_dump"):
            raw_response = resp.model_dump()
        else:
            raw_response = {}
        if not isinstance(raw_response, dict):
            raw_response = {"response": raw_response}
        response_candidates = _dr_read_field(resp, "candidates")
        if response_candidates is not None and "candidates" not in raw_response:
            raw_response["candidates"] = _dr_json_safe(response_candidates)
        response_text = _dr_read_field(resp, "text")
        if response_text is not None and "text" not in raw_response:
            raw_response["text"] = _dr_json_safe(response_text)
        if not raw_response:
            raw_response = {"raw": str(resp)}

        text_candidates = [
            _dr_extract_text_from_candidates(resp),
            _dr_extract_text_from_candidates(raw_response),
            getattr(resp, "text", None),
            _dr_extract_text(raw_response),
        ]
        normalized_text = max(
            (
                candidate.strip()
                for candidate in text_candidates
                if isinstance(candidate, str) and candidate.strip()
            ),
            key=len,
            default="",
        )

        payload = _dr_build_normalized_payload(
            status="completed",
            raw_payload=raw_response,
            summary_text=normalized_text,
            include_raw=include_raw,
        )
        if not normalized_text:
            return {
                "ok": False,
                "error": "empty_response",
                "message": "google_deep_research returned empty text.",
                "data": payload,
            }
        return {"ok": True, "data": payload}
    except ApiFeeReservationError as exc:
        return api_fee_error_payload(exc)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# DeepXiv: structured arXiv / PMC paper access
# ---------------------------------------------------------------------------

from mcp.types import Tool as _MCPTool  # noqa: E402,I001
from mcp.types import ToolAnnotations as _ToolAnnotations  # noqa: E402

# Extracted to mcp/routers/deepxiv.py. Importing it registers the `deepxiv`
# @mcp.tool() on the shared FastMCP instance (import side effect).
from brain_researcher.services.mcp.routers import (  # noqa: E402,F401
    deepxiv as _deepxiv_router,
)

# ---------------------------------------------------------------------------
# CC (Claude Code) integration: annotations + searchHint injection
# ---------------------------------------------------------------------------
# Re-registers the FastMCP list_tools handler to add two fields that CC reads:
#
#   annotations.readOnlyHint / destructiveHint
#     → CC permission model: read-only tools auto-approve, destructive prompt user
#
#   _meta['anthropic/searchHint']
#     → CC ToolSearchTool scoring: boosts correct tool to +4 points vs desc-only +2
#       Without it, "fMRI preprocessing" might not surface `pipeline_execute`.
#
# The underlying @mcp.tool() decorators are unchanged.  Only the ListTools
# wire response is enriched.  Other MCP clients (Codex, Cursor) ignore these
# fields gracefully since they're optional per spec.
#
# Update _BR_CC_TOOL_META when new @mcp.tool() functions are added.
# ---------------------------------------------------------------------------


# (tool_name, readOnlyHint, destructiveHint, searchHint)
# destructiveHint is ignored (None) when readOnlyHint=True per MCP spec.
_BR_CC_TOOL_META: list[tuple[str, bool, bool | None, str]] = [
    # --- Server ops ---
    ("server_info", True, None, "server configuration metadata capabilities run_root"),
    ("loop_profile_get", True, None, "loop profile configuration parameters"),
    ("system_self_test", True, None, "system self test health check diagnostics"),
    # --- Tool discovery ---
    (
        "tool_search",
        True,
        None,
        "search find neuroimaging tools fMRIPrep FSL AFNI preprocessing",
    ),
    (
        "tool_search_structured",
        True,
        None,
        "structured search neuroimaging tools query",
    ),
    ("workflow_search", True, None, "search workflow pipeline templates"),
    ("tool_resolve", True, None, "resolve tool name alias lookup"),
    ("tool_get", True, None, "get tool details spec recipe parameters"),
    (
        "get_execution_recipe",
        True,
        None,
        "execution recipe local Python script generate",
    ),
    ("get_latest_plan", True, None, "latest pipeline plan retrieve"),
    # --- Planning ---
    (
        "plan_preflight",
        True,
        None,
        "plan preflight dataset check BIDS readiness blockers subjects",
    ),
    ("plan_create", False, False, "create pipeline plan analysis design steps"),
    ("pipeline_plan_validate", False, False, "validate pipeline plan parameters check"),
    (
        "pipeline_plan_review",
        False,
        False,
        "review pipeline plan domain validation neuroimaging check",
    ),
    (
        "qsm_implementation_review",
        True,
        None,
        "audit QSM code local field dataflow dipole inversion total field",
    ),
    (
        "rapidtide_implementation_review",
        True,
        None,
        "audit rapidtide sLFO lag delay cross-correlation refinement canonical method",
    ),
    (
        "report_claim_provenance_check",
        True,
        None,
        "report claim traceability provenance artifact hash code ref what actually ran",
    ),
    (
        "run_code_review",
        False,
        False,
        "post-execution artifact review FD effect size QC completeness",
    ),
    (
        "run_scientific_review",
        False,
        False,
        "scientific review correctness completeness judgment verdict",
    ),
    (
        "run_autoresearch_scientific_review",
        False,
        False,
        "autoresearch scientific review loop final report experiments ledger validation claim strength",
    ),
    (
        "request_scientific_review",
        False,
        False,
        "route scientific review run_id autoresearch_dir external directive KG criteria",
    ),
    (
        "scientific_report_generate",
        False,
        False,
        "scientific report generate review verdict latex sections pdf",
    ),
    # --- Execution ---
    ("tool_execute", False, True, "execute run tool neuroimaging pipeline step"),
    (
        "pipeline_execute",
        False,
        True,
        "execute run fMRIPrep QSIPrep FitLins preprocessing pipeline",
    ),
    ("run_cancel", False, True, "cancel abort stop running job pipeline"),
    # --- Run management ---
    ("run_get", True, None, "get run status results outputs"),
    ("run_list", True, None, "list runs history completed"),
    (
        "run_find_latest_reviewable",
        True,
        None,
        "find latest reviewable run scientific report source candidate",
    ),
    ("run_logs", True, None, "get run logs output stderr"),
    ("run_bundle_get", True, None, "get run bundle outputs artifacts files"),
    ("run_metrics", True, None, "run metrics performance statistics"),
    ("run_scorecard", True, None, "run scorecard quality assessment"),
    ("run_compare", True, None, "compare runs diff results"),
    ("run_request_summary", True, None, "run request summary description"),
    # --- Artifacts ---
    ("latex_report_render", False, False, "latex report render template tex pdf"),
    ("artifact_list", True, None, "list artifacts outputs files results"),
    ("artifact_get_metadata", True, None, "artifact metadata file info"),
    ("artifact_read_text", True, None, "read artifact text file content"),
    ("artifact_read_bytes", True, None, "read artifact binary bytes"),
    # --- Knowledge Graph ---
    (
        "kg_search_nodes",
        True,
        None,
        "search BR-KG knowledge graph concepts methods neuroscience",
    ),
    ("kg_get_node", True, None, "get knowledge graph node details"),
    ("kg_neighbors", True, None, "knowledge graph neighbors related concepts"),
    ("kg_probe", True, None, "probe knowledge graph structured query"),
    ("kg_multihop_qa", True, None, "multi-hop knowledge graph question answering"),
    ("dataset_get_resources", True, None, "get dataset resources files structure BIDS"),
    (
        "kg_related_datasets",
        True,
        None,
        "related neuroimaging datasets knowledge graph",
    ),
    ("kg_search_datasets", True, None, "search datasets OpenNeuro BIDS neuroimaging"),
    ("kg_verify_hypothesis", True, None, "verify hypothesis evidence knowledge graph"),
    (
        "verify_hypothesis_with_kg",
        True,
        None,
        "verify hypothesis knowledge graph evidence",
    ),
    (
        "kg_behavior_to_fmri_retrieval",
        True,
        None,
        "behavior fMRI BOLD signal retrieval mapping",
    ),
    ("kg_list_dataset_onvoc_links", True, None, "dataset ontology vocabulary links"),
    (
        "kg_find_structural_leverage",
        True,
        None,
        "structural leverage knowledge graph analysis",
    ),
    (
        "kg_detect_contradiction_motifs",
        True,
        None,
        "contradiction motifs detection knowledge graph",
    ),
    (
        "kg_find_contradiction_frontiers",
        True,
        None,
        "contradiction frontiers knowledge graph",
    ),
    (
        "kg_mine_assumption_cracks",
        True,
        None,
        "assumption cracks gaps mining knowledge graph",
    ),
    ("kg_find_analogy_transfers", True, None, "analogy transfer knowledge graph"),
    ("kg_sample_ood_hypothesis", True, None, "out-of-distribution hypothesis sampling"),
    ("kg_hypothesis_workflow", True, None, "hypothesis workflow generation pipeline"),
    (
        "kg_hypothesis_candidate_cards",
        True,
        None,
        "hypothesis candidate cards generation",
    ),
    (
        "kg_hypothesis_candidate_cards_start",
        True,
        None,
        "start hypothesis candidate cards async",
    ),
    (
        "kg_hypothesis_candidate_cards_get",
        True,
        None,
        "get hypothesis candidate cards result",
    ),
    ("kg_verify_sampled_hypotheses", True, None, "verify sampled hypotheses batch"),
    ("kg_sample_and_verify_hypotheses", True, None, "sample and verify hypotheses"),
    ("kg_detect_topology_shifts", True, None, "detect topology shifts knowledge graph"),
    # --- Research / logging ---
    ("log_research_event", False, False, "log research event tracking annotation"),
    ("write_session_snapshot", False, False, "write session snapshot memory context"),
    ("research_session_digest", True, None, "research session digest summary"),
    ("research_log_summary", True, None, "research log summary history"),
    ("session_risk_classify", True, None, "classify session handoff risks"),
    ("session_lesson_extract", True, None, "extract session lessons"),
    ("session_open_risks_query", True, None, "query open session risks"),
    (
        "session_policy_cards_generate",
        True,
        None,
        "generate session policy card candidates",
    ),
    (
        "session_learning_report_generate",
        True,
        None,
        "generate periodic session learning report",
    ),
    (
        "session_signal_report_generate",
        True,
        None,
        "generate session silent-fail signal report",
    ),
    ("session_backfill_to_kg", True, None, "dry run session graph backfill rows"),
    ("memory_write", False, False, "write derived memory card episodic claim relation"),
    (
        "memory_search",
        True,
        None,
        "search derived memory cards episodic claim relation",
    ),
    ("memory_get", True, None, "get derived memory card by id"),
    (
        "generate_research_trajectory_and_insights",
        True,
        None,
        "research trajectory insights generation",
    ),
    ("generate_bug_digest", True, None, "bug digest error analysis"),
    ("generate_repo_repair_context", True, None, "repo repair context generation"),
    # --- Hypothesis / ideation ---
    ("hypothesis_run_start", False, False, "start hypothesis research run pipeline"),
    ("hypothesis_run_get", True, None, "get hypothesis run status results"),
    (
        "hypothesis_hot_load_research",
        True,
        None,
        "hot load research hypothesis context",
    ),
    # --- Sherlock debugging ---
    ("sherlock_guide", True, None, "sherlock debugging guide analysis recommendations"),
    ("sherlock_slurm", True, None, "sherlock slurm cluster HPC job debugging"),
    # --- Google research ---
    ("google_file_search", True, None, "google file search papers literature"),
    (
        "grounding_resolve",
        True,
        None,
        "resolve evidence reference anchor doi pmid doc kg session provenance support",
    ),
    (
        "grounding_gate_evidence_basis",
        True,
        None,
        "gate evidence_basis references anchors downgrade unresolved malformed citation",
    ),
    (
        "google_deep_research_start",
        False,
        False,
        "start async deep research literature review",
    ),
    ("google_deep_research_get", True, None, "get deep research result synthesis"),
    (
        "google_deep_research",
        False,
        False,
        "deep research synthesis literature review scientific primary sources pubmed pmc doi",
    ),
    (
        "deepxiv",
        True,
        None,
        "arXiv PMC paper search read literature trending preprint pmcid pmid doi pii",
    ),
]

_BR_CC_META_LOOKUP: dict[str, tuple[bool, bool | None, str]] = {
    name: (ro, dest, hint) for name, ro, dest, hint in _BR_CC_TOOL_META
}


@mcp._mcp_server.list_tools()
async def _list_tools_with_cc_hints() -> list[_MCPTool]:
    """list_tools override: enriches tool definitions for CC ToolSearchTool."""
    tools = mcp._tool_manager.list_tools()
    result: list[_MCPTool] = []
    for info in tools:
        meta_row = _BR_CC_META_LOOKUP.get(info.name)
        if meta_row:
            ro, dest, hint = meta_row
            annotations = _ToolAnnotations(
                readOnlyHint=ro,
                destructiveHint=(dest if not ro else None),
            )
            mcp_tool = _MCPTool(
                name=info.name,
                title=info.title,
                description=info.description,
                inputSchema=info.parameters,
                outputSchema=info.output_schema,
                annotations=annotations,
            ).model_copy(update={"meta": {"anthropic/searchHint": hint}})
        else:
            mcp_tool = _MCPTool(
                name=info.name,
                title=info.title,
                description=info.description,
                inputSchema=info.parameters,
                outputSchema=info.output_schema,
                annotations=info.annotations,
            )
        result.append(mcp_tool)
    return result


def build_http_app(inner_app) -> Any:
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import (
        JSONResponse,
        PlainTextResponse,
        RedirectResponse,
        Response,
    )
    from starlette.routing import Mount, Route

    class _McpSessionBootstrapMiddleware:
        def __init__(self, app):
            self.app = app

        @staticmethod
        def _response_content_type(message: dict[str, Any] | None) -> str:
            if not isinstance(message, dict):
                return ""
            for k, v in list(message.get("headers") or []):
                if not (
                    isinstance(k, bytes | bytearray)
                    and isinstance(v, bytes | bytearray)
                ):
                    continue
                if k.decode("latin-1").lower() == "content-type":
                    return v.decode("latin-1").strip().lower()
            return ""

        @staticmethod
        def _cache_key(scope: dict[str, Any], headers: dict[str, str]) -> str:
            state = scope.get("state")
            user_id = ""
            if isinstance(state, dict):
                user_id = str(state.get("user_id") or "")
            auth_token = _extract_bearer_token(headers.get("authorization")) or ""
            auth_digest = (
                hashlib.sha256(auth_token.encode("utf-8")).hexdigest()[:16]
                if auth_token
                else ""
            )
            host = (headers.get("host") or "").strip().lower()
            path = str(scope.get("path") or "").strip().lower()
            client_addr = ""
            client = scope.get("client")
            if isinstance(client, tuple) and client:
                client_addr = str(client[0] or "").strip().lower()
            # Keep key stable across GET/POST preflight + RPC calls.
            # Do not include origin/user-agent, which may differ per request.
            return f"{user_id}|{auth_digest}|{host}|{client_addr}|{path}"

        @staticmethod
        def _clone_scope_with_headers(
            scope: dict[str, Any], extra_headers: list[tuple[bytes, bytes]]
        ) -> dict[str, Any]:
            cloned = dict(scope)
            override_names = {
                k.decode("latin-1").lower()
                for k, _ in extra_headers
                if isinstance(k, bytes | bytearray)
            }
            headers = [
                (k, v)
                for (k, v) in list(scope.get("headers") or [])
                if not (
                    isinstance(k, bytes | bytearray)
                    and k.decode("latin-1").lower() in override_names
                )
            ]
            headers.extend(extra_headers)
            cloned["headers"] = headers
            return cloned

        @staticmethod
        def _clone_scope_without_headers(
            scope: dict[str, Any], remove_header_names: set[str]
        ) -> dict[str, Any]:
            normalized = {name.strip().lower() for name in remove_header_names if name}
            cloned = dict(scope)
            headers = [
                (k, v)
                for (k, v) in list(scope.get("headers") or [])
                if not (
                    isinstance(k, bytes | bytearray)
                    and k.decode("latin-1").lower() in normalized
                )
            ]
            cloned["headers"] = headers
            return cloned

        @staticmethod
        def _replay_receive(body: bytes):
            sent = False

            async def _receive() -> dict[str, Any]:
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.request", "body": b"", "more_body": False}

            return _receive

        async def _prime_session_via_get(
            self, scope: dict[str, Any], cache_key: str
        ) -> str | None:
            preflight_scope = dict(scope)
            preflight_scope["method"] = "GET"
            preflight_scope["headers"] = [
                (k, v)
                for (k, v) in list(scope.get("headers") or [])
                if isinstance(k, bytes | bytearray)
                and k.decode("latin-1").lower()
                not in {"mcp-session-id", "content-type", "content-length"}
            ]

            seeded_session: str | None = None

            async def _capture_send(message: dict[str, Any]) -> None:
                nonlocal seeded_session
                if message.get("type") != "http.response.start":
                    return
                for k, v in list(message.get("headers") or []):
                    if not (
                        isinstance(k, bytes | bytearray)
                        and isinstance(v, bytes | bytearray)
                    ):
                        continue
                    if k.decode("latin-1").lower() != "mcp-session-id":
                        continue
                    sid = v.decode("latin-1").strip()
                    if sid:
                        seeded_session = sid
                    break

            try:
                await asyncio.wait_for(
                    self.app(preflight_scope, self._replay_receive(b""), _capture_send),
                    timeout=SESSION_BOOTSTRAP_PRIME_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "mcp_bootstrap prime_session_get timeout_s=%.2f key=%s",
                    SESSION_BOOTSTRAP_PRIME_TIMEOUT_SECONDS,
                    cache_key,
                )
                return None
            if seeded_session:
                _session_bootstrap_cache_put(cache_key, seeded_session)
            return seeded_session

        async def _ensure_initialized_session(
            self, scope: dict[str, Any], session_id: str
        ) -> None:
            if not session_id or _session_bootstrap_init_has(session_id):
                return
            logger.info(
                "mcp_bootstrap ensure_initialized start session_id=%s", session_id
            )

            stripped = self._clone_scope_without_headers(
                scope, {"mcp-session-id", "content-type", "content-length"}
            )
            init_scope = self._clone_scope_with_headers(
                stripped,
                extra_headers=[
                    (b"mcp-session-id", session_id.encode("utf-8")),
                    (b"content-type", b"application/json"),
                ],
            )
            init_scope["method"] = "POST"

            init_payload = {
                "jsonrpc": "2.0",
                "id": "bootstrap-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "brain-researcher-mcp-bootstrap",
                        "version": "1.0",
                    },
                },
            }
            init_status = 0

            async def _capture_init(message: dict[str, Any]) -> None:
                nonlocal init_status
                if message.get("type") == "http.response.start":
                    init_status = int(message.get("status") or 0)

            await self.app(
                init_scope,
                self._replay_receive(json.dumps(init_payload).encode("utf-8")),
                _capture_init,
            )
            logger.info(
                "mcp_bootstrap ensure_initialized initialize_status=%s session_id=%s",
                init_status,
                session_id,
            )
            if init_status != 200:
                logger.warning(
                    "mcp_bootstrap initialize failed status=%s session_id=%s",
                    init_status,
                    session_id,
                )
                return

            notif_payload = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
            await self.app(
                init_scope,
                self._replay_receive(json.dumps(notif_payload).encode("utf-8")),
                _capture_init,
            )
            logger.info(
                "mcp_bootstrap ensure_initialized notification_status=%s session_id=%s",
                init_status,
                session_id,
            )
            _session_bootstrap_init_put(session_id)

        def _build_send_with_cache_for_request(
            self,
            *,
            send,
            cache_key: str,
            fallback_session_id: str | None = None,
        ):
            async def _send_with_cache(message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.start":
                    resp_headers = list(message.get("headers") or [])
                    response_session: str | None = None
                    has_session = False
                    for k, v in resp_headers:
                        if isinstance(k, bytes | bytearray) and isinstance(
                            v, bytes | bytearray
                        ):
                            if k.decode("latin-1").lower() == "mcp-session-id":
                                has_session = True
                                sid = v.decode("latin-1").strip()
                                if sid:
                                    response_session = sid
                                break
                    if response_session:
                        _session_bootstrap_cache_put(cache_key, response_session)
                    elif fallback_session_id and not has_session:
                        resp_headers.append(
                            (b"mcp-session-id", fallback_session_id.encode("utf-8"))
                        )
                        message = dict(message)
                        message["headers"] = resp_headers
                await send(message)

            return _send_with_cache

        async def _dispatch_inner(
            self,
            *,
            scope: dict[str, Any],
            body: bytes,
            send,
            cache_key: str,
            fallback_session_id: str | None = None,
            enforce_json_response: bool = False,
            serialize_key: str | None = None,
        ) -> None:
            send_with_cache = self._build_send_with_cache_for_request(
                send=send,
                cache_key=cache_key,
                fallback_session_id=fallback_session_id,
            )

            async def _invoke() -> None:
                if not enforce_json_response:
                    await self.app(scope, self._replay_receive(body), send_with_cache)
                    return

                captured: list[dict[str, Any]] = []

                async def _capture(message: dict[str, Any]) -> None:
                    captured.append(message)

                await self.app(scope, self._replay_receive(body), _capture)
                start_message = next(
                    (
                        message
                        for message in captured
                        if message.get("type") == "http.response.start"
                    ),
                    None,
                )
                content_type = self._response_content_type(start_message)
                if content_type and not (
                    content_type.startswith("application/json")
                    or content_type.startswith("text/event-stream")
                ):
                    response = JSONResponse(
                        {
                            "ok": False,
                            "error": "unexpected_response_content_type",
                            "content_type": content_type,
                        },
                        status_code=502,
                    )
                    await response(scope, self._replay_receive(b""), send_with_cache)
                    return

                for message in captured:
                    await send_with_cache(message)

            if serialize_key and SERIALIZE_TOOLS_CALL:
                async with _get_tools_call_lock(serialize_key):
                    await _invoke()
                return
            await _invoke()

        async def __call__(self, scope, receive, send):
            if not SESSION_BOOTSTRAP_ENABLED:
                await self.app(scope, receive, send)
                return
            if STATELESS_HTTP:
                await self.app(scope, receive, send)
                return
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return
            if str(scope.get("path") or "") == "/healthz":
                await self.app(scope, receive, send)
                return

            http_method = str(scope.get("method") or "").upper()
            raw_headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
            headers: dict[str, str] = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in raw_headers
                if isinstance(k, bytes | bytearray) and isinstance(v, bytes | bytearray)
            }

            cache_key = self._cache_key(scope, headers)

            explicit_session = (headers.get("mcp-session-id") or "").strip()

            # Some clients do GET /mcp first to establish transport/session.
            if http_method == "GET":
                if explicit_session:
                    _session_bootstrap_cache_put(cache_key, explicit_session)
                await self.app(
                    scope,
                    receive,
                    self._build_send_with_cache_for_request(
                        send=send,
                        cache_key=cache_key,
                    ),
                )
                return

            if http_method != "POST":
                await self.app(scope, receive, send)
                return

            # Streamable MCP JSON-RPC uses small JSON POST payloads.
            content_type = (headers.get("content-type") or "").lower()
            if "application/json" not in content_type:
                await self.app(scope, receive, send)
                return

            body_chunks: list[bytes] = []
            total_body_bytes = 0
            while True:
                message = await receive()
                if message.get("type") != "http.request":
                    break
                chunk = message.get("body", b"")
                if isinstance(chunk, bytearray):
                    chunk = bytes(chunk)
                elif not isinstance(chunk, bytes):
                    chunk = b""
                if chunk:
                    total_body_bytes += len(chunk)
                    if total_body_bytes > SESSION_BOOTSTRAP_MAX_BODY_BYTES:
                        response = JSONResponse(
                            {
                                "ok": False,
                                "error": "payload_too_large",
                                "max_body_bytes": SESSION_BOOTSTRAP_MAX_BODY_BYTES,
                            },
                            status_code=413,
                        )
                        await response(scope, receive, send)
                        return
                    body_chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            body = b"".join(body_chunks)
            rpc_method = ""
            try:
                payload = json.loads(body.decode("utf-8"))
                if isinstance(payload, dict):
                    rpc_method = str(payload.get("method") or "")
                elif (
                    isinstance(payload, list)
                    and payload
                    and isinstance(payload[0], dict)
                ):
                    rpc_method = str(payload[0].get("method") or "")
            except Exception:
                rpc_method = ""

            cached_session = _session_bootstrap_cache_get(cache_key)
            if not cached_session:
                cached_session = await self._prime_session_via_get(scope, cache_key)

            if explicit_session:
                # Some clients keep a stale session id across server restarts.
                # For initialize, drop stale explicit ids (or replace with cached)
                # so Streamable HTTP can create a fresh transport session.
                logger.info(
                    "mcp_bootstrap explicit_session rpc_method=%s cache_hit=%s",
                    rpc_method or "<none>",
                    bool(cached_session),
                )
                if rpc_method == "initialize" or (
                    not rpc_method and not cached_session
                ):
                    if cached_session:
                        _session_bootstrap_cache_put(cache_key, cached_session)
                        patched_scope = self._clone_scope_with_headers(
                            scope,
                            extra_headers=[
                                (b"mcp-session-id", cached_session.encode("utf-8"))
                            ],
                        )
                        await self._dispatch_inner(
                            scope=patched_scope,
                            body=body,
                            send=send,
                            cache_key=cache_key,
                            enforce_json_response=True,
                        )
                        return
                    stripped_scope = self._clone_scope_without_headers(
                        scope, {"mcp-session-id"}
                    )
                    await self._dispatch_inner(
                        scope=stripped_scope,
                        body=body,
                        send=send,
                        cache_key=cache_key,
                        enforce_json_response=True,
                    )
                    return

                session_for_request = (
                    cached_session
                    if cached_session and cached_session != explicit_session
                    else explicit_session
                )
                _session_bootstrap_cache_put(cache_key, session_for_request)
                if session_for_request != explicit_session:
                    if rpc_method == "tools/call":
                        await self._ensure_initialized_session(
                            scope, session_for_request
                        )
                    patched_scope = self._clone_scope_with_headers(
                        scope,
                        extra_headers=[
                            (b"mcp-session-id", session_for_request.encode("utf-8"))
                        ],
                    )
                    await self._dispatch_inner(
                        scope=patched_scope,
                        body=body,
                        send=send,
                        cache_key=cache_key,
                        enforce_json_response=True,
                        serialize_key=(
                            session_for_request if rpc_method == "tools/call" else None
                        ),
                    )
                    return
                if rpc_method == "tools/call":
                    await self._ensure_initialized_session(scope, session_for_request)
                await self._dispatch_inner(
                    scope=scope,
                    body=body,
                    send=send,
                    cache_key=cache_key,
                    enforce_json_response=True,
                    serialize_key=(
                        session_for_request if rpc_method == "tools/call" else None
                    ),
                )
                return

            session_id = cached_session
            logger.info(
                "mcp_bootstrap inferred_session rpc_method=%s cache_hit=%s",
                rpc_method or "<none>",
                bool(session_id),
            )

            if not session_id:
                await self._dispatch_inner(
                    scope=scope,
                    body=body,
                    send=send,
                    cache_key=cache_key,
                    enforce_json_response=True,
                )
                return

            if rpc_method == "tools/call":
                await self._ensure_initialized_session(scope, session_id)
            patched_scope = self._clone_scope_with_headers(
                scope, extra_headers=[(b"mcp-session-id", session_id.encode("utf-8"))]
            )
            await self._dispatch_inner(
                scope=patched_scope,
                body=body,
                send=send,
                cache_key=cache_key,
                fallback_session_id=session_id,
                enforce_json_response=True,
                serialize_key=session_id if rpc_method == "tools/call" else None,
            )

    def _workspace_id_from_jwt(payload: dict[str, Any] | None) -> str:
        if not isinstance(payload, dict):
            return "default"
        for key in ("tenant_id", "workspace_id", "org_id"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return "default"

    async def _call_next_with_api_fee_context(
        request: Request,
        call_next,
        *,
        user_id: str | None,
        workspace_id: str | None = None,
    ):
        request_id = (
            request.headers.get("x-request-id")
            or request.headers.get("x-correlation-id")
            or request.headers.get("mcp-session-id")
        )
        token = set_mcp_api_fee_context(
            user_id=user_id,
            workspace_id=workspace_id,
            request_id=request_id,
        )
        try:
            return await call_next(request)
        finally:
            reset_mcp_api_fee_context(token)

    class _McpEntrySourceMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            host = request.headers.get("host")
            source = "internal" if _is_internal_mcp_request_host(host) else "external"
            ctx_token = _mcp_entry_source.set(source)
            try:
                return await call_next(request)
            finally:
                _mcp_entry_source.reset(ctx_token)

    def _is_browser_mcp_setup_request(request: Request) -> bool:
        request_method = request.method.upper()
        if request_method not in {"GET", "HEAD"}:
            return False
        if _extract_bearer_token(request.headers.get("authorization")):
            return False

        mount_path = "/" + MOUNT_PATH.strip("/") if MOUNT_PATH.strip("/") else ""
        if not mount_path:
            return False
        request_path = request.url.path.rstrip("/") or "/"
        if request_path != mount_path.rstrip("/"):
            return False

        accept = (request.headers.get("accept") or "").lower()
        fetch_dest = (request.headers.get("sec-fetch-dest") or "").lower()
        wants_protocol_response = any(
            media_type in accept
            for media_type in (
                "application/json",
                "application/json-rpc",
                "text/event-stream",
            )
        )
        if wants_protocol_response:
            return False
        return (
            request_method == "HEAD"
            or "text/html" in accept
            or "application/xhtml+xml" in accept
            or "*/*" in accept
            or not accept
            or fetch_dest == "document"
        )

    class _BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            # Always allow health checks without auth.
            if request.url.path == "/healthz":
                return await call_next(request)

            origin = (request.headers.get("origin") or "").strip() or None
            if not _is_allowed_origin(origin):
                return JSONResponse(
                    {"ok": False, "error": "origin_not_allowed"},
                    status_code=403,
                )

            host = (request.headers.get("host") or "").strip() or None
            if not _is_allowed_host(host):
                return JSONResponse(
                    {"ok": False, "error": "host_not_allowed"},
                    status_code=421,
                )

            if _is_browser_mcp_setup_request(request):
                return RedirectResponse(MCP_SETUP_PATH, status_code=302)

            mode = _resolve_auth_mode()
            if mode == "none":
                return await call_next(request)

            token = _extract_bearer_token(request.headers.get("authorization"))
            if not token:
                return JSONResponse(
                    {"ok": False, "error": "missing_bearer_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if (
                mode in {"token", "token_or_jwt"}
                and AUTH_TOKEN
                and hmac.compare_digest(token, AUTH_TOKEN)
            ):
                request.state.user_id = "__break_glass__"
                logger.info(
                    "auth ok user=%s path=%s",
                    request.state.user_id,
                    request.url.path,
                )
                return await call_next(request)

            if mode in {"token", "token_or_jwt"}:
                user_id = _try_verify_api_key(token)
                if user_id is not None:
                    request.state.user_id = user_id
                    logger.info(
                        "auth ok user=%s path=%s",
                        request.state.user_id,
                        request.url.path,
                    )
                    return await _call_next_with_api_fee_context(
                        request,
                        call_next,
                        user_id=request.state.user_id,
                        workspace_id="default",
                    )

            if mode in {"jwt", "token_or_jwt"}:
                try:
                    request.state.jwt = _verify_jwt(token)
                except AuthError:
                    return JSONResponse(
                        {"ok": False, "error": "invalid_token"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                request.state.user_id = str(request.state.jwt.get("sub") or "__jwt__")
                logger.info(
                    "auth ok user=%s path=%s",
                    request.state.user_id,
                    request.url.path,
                )
                return await _call_next_with_api_fee_context(
                    request,
                    call_next,
                    user_id=request.state.user_id,
                    workspace_id=_workspace_id_from_jwt(request.state.jwt),
                )

            return JSONResponse(
                {"ok": False, "error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def _healthz(_: Request) -> Response:
        return PlainTextResponse("ok")

    async def _resolve_reference_http(request: Request) -> Response:
        ref = str(request.query_params.get("ref") or "").strip()
        if not ref:
            return JSONResponse(
                {"ok": False, "error": "ref query parameter is required"},
                status_code=400,
            )
        try:
            from brain_researcher.core.grounding_references import resolve_reference

            return JSONResponse(
                {
                    "ok": True,
                    "result": resolve_reference(
                        ref,
                        kg_lookup=_grounding_kg_lookup,
                        session_lookup=lambda card_ref: _grounding_session_lookup(
                            card_ref,
                            run_root=_runstore.RUN_ROOT,
                        ),
                        run_root=_runstore.RUN_ROOT,
                    ),
                }
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    resolve_routes = [
        Route("/resolve", endpoint=_resolve_reference_http, methods=["GET"])
    ]
    normalized_mount_path = "/" + MOUNT_PATH.strip("/") if MOUNT_PATH.strip("/") else ""
    if normalized_mount_path:
        resolve_routes.append(
            Route(
                f"{normalized_mount_path}/resolve",
                endpoint=_resolve_reference_http,
                methods=["GET"],
            )
        )

    # Prefer mutating the inner Starlette app in-place so its lifespan (startup/shutdown)
    # remains active (some MCP transports require it).
    if isinstance(inner_app, Starlette) or hasattr(inner_app, "router"):
        app: Any = inner_app
        try:
            app.add_middleware(_McpSessionBootstrapMiddleware)
            app.add_middleware(_BearerAuthMiddleware)
            app.add_middleware(_McpEntrySourceMiddleware)
        except Exception:
            # Fall back to outer mounting when middleware injection isn't supported.
            return Starlette(
                routes=[
                    Route("/healthz", endpoint=_healthz, methods=["GET"]),
                    *resolve_routes,
                    Mount("/", app=inner_app),
                ],
                middleware=[
                    Middleware(_McpEntrySourceMiddleware),
                    Middleware(_BearerAuthMiddleware),
                    Middleware(_McpSessionBootstrapMiddleware),
                ],
            )

        # Ensure /healthz is not shadowed by any catch-all route.
        try:
            app.router.routes.insert(
                0, Route("/healthz", endpoint=_healthz, methods=["GET"])
            )
            for route in reversed(resolve_routes):
                app.router.routes.insert(1, route)
        except Exception:
            # Conservative fallback.
            return Starlette(
                routes=[
                    Route("/healthz", endpoint=_healthz, methods=["GET"]),
                    *resolve_routes,
                    Mount("/", app=inner_app),
                ],
                middleware=[
                    Middleware(_McpEntrySourceMiddleware),
                    Middleware(_BearerAuthMiddleware),
                    Middleware(_McpSessionBootstrapMiddleware),
                ],
            )

        return app

    # Fallback: wrap as mounted sub-app.
    return Starlette(
        routes=[
            Route("/healthz", endpoint=_healthz, methods=["GET"]),
            *resolve_routes,
            Mount("/", app=inner_app),
        ],
        middleware=[
            Middleware(_BearerAuthMiddleware),
            Middleware(_McpSessionBootstrapMiddleware),
        ],
    )


def main() -> None:
    # Keep logs on stderr; stdout is reserved for MCP JSON-RPC.
    logging.basicConfig(
        level=os.getenv("BR_MCP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    _ensure_dirs()
    dependency_status = _startup_hard_health_checks()
    logger.info(
        "MCP startup health checks passed (run_root=%s writable=%s neo4j_configured=%s neo4j_reachable=%s strict=%s)",
        (
            dependency_status.get("run_root", {}).get("path")
            if isinstance(dependency_status, dict)
            else str(_runstore.RUN_ROOT)
        ),
        (
            dependency_status.get("run_root", {}).get("writable")
            if isinstance(dependency_status, dict)
            else True
        ),
        (
            dependency_status.get("neo4j", {}).get("configured")
            if isinstance(dependency_status, dict)
            else False
        ),
        (
            dependency_status.get("neo4j", {}).get("active_check", {}).get("reachable")
            if isinstance(dependency_status, dict)
            else False
        ),
        STARTUP_STRICT_DEPENDENCIES,
    )
    _spawn_semantic_prewarm()

    transport = DEFAULT_TRANSPORT
    if transport in {"stdio", ""}:
        mcp.run(transport="stdio")
        return

    if transport not in {"sse", "streamable-http"}:
        raise ValueError(
            f"Unsupported BR_MCP_TRANSPORT={transport!r}; expected stdio|sse|streamable-http"
        )

    # HTTP transports: build an ASGI app and run uvicorn ourselves so we can
    # enforce auth and provide a /healthz endpoint.
    import uvicorn

    # Configure host/port/mount path for the underlying MCP Starlette app.
    mcp.settings.host = HOST
    mcp.settings.port = PORT
    mcp.settings.mount_path = MOUNT_PATH
    mcp.settings.stateless_http = STATELESS_HTTP

    # FastMCP auto-enables DNS rebinding protection when initialized with a localhost
    # bind host (127.0.0.1/localhost). Since we construct `mcp` at import time, it
    # may default to localhost even in production and then reject ingress Host
    # headers (421 Invalid Host header). Override transport security settings here.
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        if ALLOWED_HOSTS or ALLOWED_ORIGINS:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=sorted(ALLOWED_HOSTS),
                allowed_origins=sorted(ALLOWED_ORIGINS),
            )
        else:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
    except Exception:
        logger.exception("Failed to configure MCP transport security settings")

    if transport == "sse":
        inner = mcp.sse_app(mount_path=MOUNT_PATH)
    else:
        inner = mcp.streamable_http_app()

    app = build_http_app(inner)

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level=os.getenv("BR_MCP_LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    # `python -m brain_researcher.services.mcp.server` executes this file under the
    # name ``__main__``. The per-domain router modules (mcp/routers/*.py) do
    # ``from brain_researcher.services.mcp.server import mcp`` at import time, which
    # — because this module is registered in sys.modules as ``__main__`` and not yet
    # under its canonical dotted name — triggers a SECOND import of this file under
    # the canonical name, creating a SECOND FastMCP ``mcp`` instance. The router
    # ``@mcp.tool()`` decorations register onto that canonical instance, so the 20
    # router-hosted tools (artifacts/deepxiv/grounding/memory/pipeline/plan/slurm,
    # incl. google_file_search + grounding_resolve + grounding_gate_evidence_basis)
    # are absent from the ``__main__`` instance that ``main()`` would otherwise serve
    # over HTTP (87 registered vs 67 served).
    #
    # Delegate to the canonical module's ``main()`` so the served ``mcp`` is the one
    # the routers populated. Falls back to the local ``main()`` if the canonical
    # module is unavailable (e.g. run directly by path outside the package).
    import importlib

    try:
        _canonical = importlib.import_module("brain_researcher.services.mcp.server")
    except Exception:
        _canonical = None

    if _canonical is not None and _canonical is not sys.modules.get(__name__):
        _canonical.main()
    else:
        main()


# ---------------------------------------------------------------------------
# Lazy re-export of router-hosted tool callables (BLOCKER 1 fix)
#
# The 20 tool functions were extracted into mcp/routers/*.py; server.py imports
# those modules above purely for the @mcp.tool() registration side effect, so the
# callables are no longer attributes of *this* module. In-process callers still
# reach them as ``mcp_server.<name>`` (chat_orchestrator.pipeline_plan_validate,
# registry.sherlock_guide / sherlock_slurm) and the unit suite asserts they are
# attributes of ``services.mcp.server``.
#
# Resolved lazily via module ``__getattr__`` (PEP 562) rather than eager
# ``from ...routers.X import <tool>`` re-imports: routers do ``from ...server
# import <helpers>`` at their top, so an eager re-import deadlocks with a
# partial-init circular ImportError whenever a router is imported *before* server.
# Deferring to first attribute access sidesteps the cycle. Binds names only; no
# @mcp.tool() re-decoration, so no tool is registered twice.
# ---------------------------------------------------------------------------
_ROUTER_TOOL_EXPORTS: dict[str, str] = {
    "artifact_get_metadata": "artifacts",
    "artifact_list": "artifacts",
    "artifact_read_bytes": "artifacts",
    "artifact_read_text": "artifacts",
    "deepxiv": "deepxiv",
    "google_file_search": "grounding",
    "grounding_gate_evidence_basis": "grounding",
    "grounding_resolve": "grounding",
    "memory_get": "memory",
    "memory_search": "memory",
    "memory_write": "memory",
    "pipeline_plan_review": "pipeline",
    "pipeline_plan_validate": "pipeline",
    "get_latest_plan": "plan",
    "plan_create": "plan",
    "plan_preflight": "plan",
    "sherlock_guide": "slurm",
    "sherlock_slurm": "slurm",
    "slurm_guide": "slurm",
    "slurm_submit": "slurm",
}


def __getattr__(name: str) -> Any:
    """Resolve router-hosted tool callables + live RUN_ROOT on access (PEP 562)."""
    if name == "RUN_ROOT":
        # RUN_ROOT is owned by runstore; resolve live so server.RUN_ROOT reflects
        # runstore.set_run_root() / monkeypatch.setattr(runstore, "RUN_ROOT", ...).
        # Not cached in globals() — must stay live.
        return _runstore.RUN_ROOT
    router_name = _ROUTER_TOOL_EXPORTS.get(name)
    if router_name is not None:
        import importlib

        router = importlib.import_module(
            f"brain_researcher.services.mcp.routers.{router_name}"
        )
        value = getattr(router, name)
        globals()[name] = value  # cache so subsequent lookups skip __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *_ROUTER_TOOL_EXPORTS])
