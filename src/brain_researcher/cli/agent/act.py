from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from brain_researcher.services.agent.router import LLMRouter, infer_provider
from brain_researcher.services.agent.llm_budget_manager import (
    get_shared_llm_budget_manager,
)
from brain_researcher.services.agent.managed_credential_pool import (
    get_shared_managed_pool,
)
from brain_researcher.services.agent import telemetry
from brain_researcher.services.telemetry.job_kind import JobKind
from brain_researcher.services.telemetry.metrics_kind_resolver import resolve_job_kind
from brain_researcher.cli.metrics import record_cli_command_metric
from brain_researcher.services.tools.base import ToolResult

_ROUTER = LLMRouter(
    budget_manager=get_shared_llm_budget_manager(),
    managed_pool=get_shared_managed_pool(),
)
logger = logging.getLogger(__name__)


def _json_safe(obj: Any) -> Any:
    """Best-effort JSON-safe conversion (stringifies unknown types)."""
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return obj


def _score_tools_by_query(tools, query: str) -> List:
    raw = (query or "").lower()
    q = raw.split()
    dataset_intent = any(
        word in raw for word in ("dataset", "datasets", "dandiset", "openneuro")
    )
    scored = []
    for tool in tools:
        name = tool.get_tool_name().lower()
        desc = (getattr(tool, "get_tool_description")() or "").lower()
        score = 0
        if dataset_intent and any(
            keyword in name for keyword in ("dandi", "openneuro", "dataset")
        ):
            score += 15
        if dataset_intent and any(
            keyword in desc for keyword in ("dataset", "openneuro", "dandi")
        ):
            score += 10
        if any(w in name for w in q):
            score += 10
        if any(w in desc for w in q):
            score += 5
        scored.append((score, tool))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored]


def _build_tool_prompt(query: str, tool_specs_json: str) -> str:
    return f"""You are a neuroimaging assistant with access to specialized tools.

User Query: {query}

Available Tools (with full parameter schemas):
{tool_specs_json}

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

If no tool is needed: {{"tool": "none", "params": {{}}, "reasoning": "explanation"}}
"""


def _resolve_job_kind_from_selection(selection: Dict[str, Any] | None) -> str:
    """Map CLI selections onto the shared JobKind taxonomy."""
    if not selection:
        return JobKind.OTHER.value

    metadata = selection.get("metadata") or {}
    params: Dict[str, Any] = {}

    metadata_params = metadata.get("parameters")
    if isinstance(metadata_params, dict):
        params.update(metadata_params)
    selection_params = selection.get("params")
    if isinstance(selection_params, dict):
        params.update(selection_params)

    tool_name = selection.get("tool")
    if tool_name and "tool" not in params:
        params["tool"] = tool_name

    resolver_metadata: Dict[str, Any] = {}
    if params:
        resolver_metadata["parameters"] = params

    pipeline_value = selection.get("pipeline") or metadata.get("pipeline")
    if pipeline_value:
        resolver_metadata["pipeline"] = pipeline_value

    if not resolver_metadata:
        return JobKind.OTHER.value

    try:
        return resolve_job_kind(metadata=resolver_metadata)
    except Exception:
        return JobKind.OTHER.value


def _act_in_process_core(
    query: str,
    *,
    model: Optional[str] = None,
    tool_mode: str = "auto",
    tools_whitelist: Optional[List[str]] = None,
    budget_ms: int = 90_000,
    preview: bool = False,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute tool-enabled flow locally (same logic as /act, no HTTP).

    Returns a dict including selection and (if run) tool result/artifacts.
    """
    from brain_researcher.services.agent.agents.neuro_agent import NeuroAgent
    from brain_researcher.services.tools.spec import (
        spec_from_tool,
        ToolSpecRegistry,
        compress_schema,
    )
    from brain_researcher.services.tools.args_resolver import ArgsResolver
    from brain_researcher.services.agent.tool_executor import BudgetedToolExecutor

    # Initialize agent and registry
    agent = NeuroAgent()
    registry = agent.tool_registry

    # Choose model
    model_name = model or os.environ.get("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")

    # Select candidate tools
    tools = registry.get_all_tools()
    if tools_whitelist:
        allow = {t.lower() for t in tools_whitelist}
        tools = [t for t in tools if t.get_tool_name().lower() in allow]
    if progress_callback:
        progress_callback(
            {"stage": "tool_selection", "message": "Discovering relevant tools..."}
        )

    ranked = _score_tools_by_query(tools, query)[:8]

    # Build specs and compressed schemas
    spec_registry = ToolSpecRegistry()
    tool_infos = []
    for tool in ranked:
        spec = spec_from_tool(tool)
        if not spec:
            continue
        spec_registry.register(spec)
        compressed = compress_schema(spec.json_schema, max_properties=8)
        tool_infos.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": compressed.get("properties", {}),
                "required": spec.required[:5],
                "examples": [
                    {"query": ex.user_query, "params": ex.params}
                    for ex in spec.examples[:2]
                ],
            }
        )

    prompt = _build_tool_prompt(query, json.dumps(tool_infos, indent=2))

    if progress_callback:
        progress_callback(
            {"stage": "tool_selection", "message": "Analyzing query with LLM..."}
        )

    # Helper: deterministic local selection (used for preview and as fallback)
    def _local_select_tool() -> Tuple[str, Dict[str, Any], str]:
        try:
            from brain_researcher.services.orchestrator.nl2tool import select_tool

            decision = select_tool(query)
            resolved = decision.resolved_tool or decision.tool or "none"
            params = decision.parameters or {}
            if resolved != "none":
                return resolved, params, "nl_router"
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("nl2tool select failed for preview: %s", exc)

        # Hard rule: download + OpenNeuro dsID -> openneuro_download (preview only)
        q = (query or "").lower()
        m = re.search(r"(ds\\d{6})", q)
        if m and "download" in q:
            dsid = m.group(1)
            work_root = os.getenv("OPENNEURO_WORK_ROOT", "/app/data/openneuro_work")
            os.makedirs(work_root, exist_ok=True)
            return (
                "openneuro_download",
                {
                    "dataset_id": dsid,
                    "output_dir": os.path.join(work_root, dsid),
                    "execute": False,
                },
                "local_rule_openneuro_download",
            )

        # Prefer spec-based search for precision
        candidates: List[Tuple[int, Any]] = []
        if tool_infos:
            # Build simple scores by keyword presence
            for info in tool_infos:
                score = 0
                name = info.get("name", "").lower()
                desc = (info.get("description") or "").lower()
                if "glm" in q and ("glm" in name or "glm" in desc):
                    score += 20
                if name in q:
                    score += 10
                for word in q.split():
                    if word and word in desc:
                        score += 1
                candidates.append((score, info))
            candidates.sort(key=lambda x: x[0], reverse=True)
            if candidates and candidates[0][0] > 0:
                info = candidates[0][1]
                return info.get("name", "none"), {}, "local_preview_match"
        # Fallback to naive ranking from registry
        if ranked:
            return ranked[0].get_tool_name(), {}, "local_rank_match"
        return "none", {}, "no_match"

    # Tool selection via LLM (skipped for preview)
    selection_text: str
    provider = "unknown"
    route = "primary"
    fallback_reason = None
    usage: Dict[str, Any] = {}
    transport = "none"
    credential_used: Optional[str] = None
    bill_to: Optional[str] = None

    if preview:
        # For preview, avoid LLM dependency and use deterministic local selection
        chosen_tool, chosen_params, reason = _local_select_tool()
        parsed = {"tool": chosen_tool, "params": chosen_params, "reasoning": reason}
    else:
        router_result = _ROUTER.route_chat(prompt, model_hint=model_name)
        selection_text = router_result.text
        metadata = router_result.metadata
        provider = metadata.provider
        model_name = metadata.model
        route = metadata.route
        fallback_reason = metadata.fallback_reason
        usage = metadata.usage or {}
        transport = metadata.transport
        credential_used = metadata.credential
        bill_to = metadata.bill_to

        # Parse JSON from selection
        try:
            m = re.search(r"\{[\s\S]*\}", selection_text)
            parsed = json.loads(m.group(0)) if m else {"tool": "none", "params": {}}
        except Exception as e:
            parsed = {"tool": "none", "params": {}, "error": f"parse_error: {e}"}

        # Router-level hard rule: download + OpenNeuro dsID -> openneuro_download (preview only)
        q = (query or "").lower()
        m = re.search(r"(ds\\d{6})", q)
        if m and "download" in q:
            forced_tool = parsed.get("tool", "").lower()
            if forced_tool in ("agent", "code_agent", "none"):
                dsid = m.group(1)
                # For downloads we default to a working dir (not the mount root).
                work_root = os.getenv("OPENNEURO_WORK_ROOT", "/app/data/openneuro_work")
                os.makedirs(work_root, exist_ok=True)
                parsed = {
                    "tool": "openneuro_download",
                    "params": {
                        "dataset_id": dsid,
                        "output_dir": os.path.join(work_root, dsid),
                        "execute": False,
                    },
                    "reasoning": "router_rule_openneuro_download",
                }

        # If LLM failed to select, fallback to local deterministic selection
        if (parsed.get("tool") or "none").strip() == "none":
            lt, lp, lr = _local_select_tool()
            parsed = {"tool": lt, "params": lp, "reasoning": f"fallback:{lr}"}

    chosen_tool = (parsed.get("tool") or "none").strip()
    chosen_params = parsed.get("params") or {}

    # Alias placeholder 'agent' to the actual generic agent tool
    if chosen_tool == "agent":
        chosen_tool = "code_agent"
        # Pass the original user prompt to the generic agent tool if no params provided
        if not chosen_params and prompt:
            chosen_params = {"prompt": prompt}

    # Align parameter naming for code_agent
    if chosen_tool == "code_agent":
        if "instruction" not in chosen_params and "prompt" in chosen_params:
            chosen_params["instruction"] = chosen_params.pop("prompt")

    result: Dict[str, Any] = {
        "selection": {
            "tool": chosen_tool,
            "params": chosen_params,
            "reasoning": parsed.get("reasoning"),
        },
        "execution": {
            "provider": provider,
            "model": model_name,
            "route": route,
            "fallback_reason": fallback_reason,
            "usage": usage,
            "transport": transport,
            "credential": credential_used,
            "bill_to": bill_to,
        },
    }

    if chosen_tool == "none":
        return result

    tool = registry.get_tool(chosen_tool)
    if not tool:
        err = f"tool_not_found: {chosen_tool}"
        result["error"] = err
        # Also surface a tool_result block so downstream UI doesn't assume a missing output
        result["tool_result"] = {
            "status": "error",
            "error": err,
            "data": None,
            "metadata": {"tool": chosen_tool},
        }
        return result

    # Preview mode: do not execute
    if preview:
        # Optional rough estimate hook
        est = getattr(tool, "ESTIMATED_RUNTIME", None) or getattr(
            tool, "estimated_runtime", None
        )
        result["preview"] = {"estimated_runtime": est or "unknown"}
        return result

    # Resolve params and execute
    resolver = ArgsResolver(context={"working_dir": os.getcwd()})
    resolved = resolver.resolve_synonyms(chosen_params)
    # Additional inference can be added here (BIDS metadata, defaults, etc.)

    # Test/CI escape hatch: allow bypassing the real executor (which may depend on
    # Redis or heavy registries) by setting BR_ACT_BYPASS_EXECUTOR=1. This keeps
    # the CLI surface stable while making unit tests deterministic.
    if os.environ.get("BR_ACT_BYPASS_EXECUTOR"):

        class _BypassResult:
            status = "success"
            data = resolved
            error = None
            metadata = {"bypassed": True}

        tool_result = _BypassResult()
        if progress_callback:
            progress_callback(
                {"stage": "execution", "message": f"Bypassed {chosen_tool} execution"}
            )
    else:
        with BudgetedToolExecutor(
            global_budget_ms=budget_ms, use_subprocess=False
        ) as execu:
            if progress_callback:
                progress_callback(
                    {"stage": "execution", "message": f"Running {chosen_tool}..."}
                )
            tool_result = execu.execute_with_timeout(tool, resolved, timeout_ms=None)

    # Attach tool result
    def _flatten(obj: Any) -> Any:
        if isinstance(obj, ToolResult):
            return obj.model_dump()
        if isinstance(obj, dict):
            return {k: _flatten(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_flatten(v) for v in obj]
        return obj

    data_payload = getattr(tool_result, "data", None)
    data_payload = _flatten(data_payload)
    data_payload = _json_safe(data_payload)
    result["tool_result"] = {
        "status": getattr(tool_result, "status", None),
        "data": data_payload,
        "error": getattr(tool_result, "error", None),
        "metadata": getattr(tool_result, "metadata", None),
    }
    if progress_callback:
        status = result["tool_result"].get("status")
        progress_callback(
            {"stage": "done", "message": f"{chosen_tool} {status or 'completed'}."}
        )
    return result


def act_in_process(
    query: str,
    *,
    model: Optional[str] = None,
    tool_mode: str = "auto",
    tools_whitelist: Optional[List[str]] = None,
    budget_ms: int = 90_000,
    preview: bool = False,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """Telemetry-wrapped entrypoint mirroring the /act HTTP endpoint."""

    run_id = telemetry.new_run_id()
    request_type = "act_preview" if preview else "act"
    error_info: Optional[Exception] = None
    result: Optional[Dict[str, Any]] = None

    act_span = telemetry.start_span(
        "agent.act",
        {
            "channel": "cli",
            "request_type": request_type,
            "run_id": run_id,
            "tool_mode": tool_mode,
        },
    )
    try:
        result = _act_in_process_core(
            query,
            model=model,
            tool_mode=tool_mode,
            tools_whitelist=tools_whitelist,
            budget_ms=budget_ms,
            preview=preview,
            progress_callback=progress_callback,
        )
        if result is not None:
            result["run_id"] = run_id
        return result
    except Exception as exc:
        error_info = exc
        raise
    finally:
        execution = (result or {}).get("execution", {})
        selection = (result or {}).get("selection", {})
        job_kind = _resolve_job_kind_from_selection(selection)
        tool_result_meta = (result or {}).get("tool_result")
        if tool_result_meta is None:
            tool_status_value = (
                "skipped" if request_type == "act_preview" else "unknown"
            )
        else:
            tool_status_value = tool_result_meta.get("status") or (
                "error" if tool_result_meta.get("error") else "success"
            )

        provider_value = execution.get("provider") or infer_provider(model)
        model_value = execution.get("model") or model

        act_span_record = act_span.finish(
            status="error" if error_info else "ok",
            provider=provider_value,
            model=model_value,
            selected_tool=selection.get("tool"),
            tool_status=tool_status_value,
        )
        spans = [act_span_record]
        execution_meta = execution
        event_payload = {
            "run_id": run_id,
            "channel": "cli",
            "request_type": request_type,
            "prompt_hash": telemetry.prompt_hash(query),
            "prompt_length": len(query or ""),
            "latency_ms": int(round(act_span_record["duration_ms"])),
            "job_kind": job_kind,
            "llm": {
                "provider": provider_value,
                "model": model_value,
                "requested_model": model,
                "route": execution_meta.get("route"),
                "transport": execution_meta.get("transport"),
                "credential": execution_meta.get("credential"),
                "bill_to": execution_meta.get("bill_to"),
                "usage": execution_meta.get("usage") or {},
                "fallback_reason": execution_meta.get("fallback_reason"),
            },
            "tooling": {
                "selected_tool": selection.get("tool"),
                "tool_route": tool_mode,
                "result_status": tool_status_value,
                "job_kind": job_kind,
            },
            "selection": selection,
            "spans": spans,
            "error": {
                "message": str(error_info),
                "type": type(error_info).__name__,
            }
            if error_info
            else None,
        }
        try:
            telemetry.record_event(event_payload, event_type="act")
        except Exception:
            pass
        cli_status = (
            "success" if not error_info and tool_status_value != "error" else "error"
        )
        try:
            record_cli_command_metric(
                "agent_act",
                duration_ms=act_span_record["duration_ms"],
                status=cli_status,
                job_kind=job_kind,
            )
        except Exception:
            pass


logger = logging.getLogger(__name__)
