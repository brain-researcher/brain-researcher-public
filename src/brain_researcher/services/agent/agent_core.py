"""Core agent functions that can be called from any context (Flask, CLI, etc).

These functions take dicts as input and return dicts as output, without any
Flask-specific dependencies like request, g, or jsonify.
"""

from __future__ import annotations

import json as json_module
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _prune_tool_registry_by_allowlist(
    tool_registry: Any, allowlist: list[str] | None
) -> None:
    """Prune a registry in-place to the runtime allowlist."""

    if allowlist is None:
        return

    allowset = {tool_id for tool_id in allowlist if tool_id}
    tools_dict = getattr(tool_registry, "tools", {})
    descriptions = getattr(tool_registry, "tool_descriptions", {})
    removed = 0
    for tool_id in list(tools_dict.keys()):
        if tool_id.startswith("mcp.test_"):
            continue
        if tool_id in allowset:
            continue
        tools_dict.pop(tool_id, None)
        descriptions.pop(tool_id, None)
        removed += 1

    if removed:
        logger.info("Pruned %d tool(s) from simple_chat_core runtime registry", removed)


def simple_chat_core(
    message: str,
    *,
    thread_id: str | None = None,
    history: list | None = None,
    ctx: dict | None = None,
    env_override: dict | None = None,
) -> Dict[str, Any]:
    """
    Core chat function without Flask dependencies.

    Returns:
        Dict with 'text', 'metadata', and optionally 'tool_calls' keys.
    """
    from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator

    # Prefer the agent-owned router, but keep the older agent alias if present.
    try:
        from brain_researcher.services.agent.llm_router import (  # legacy location
            LLMRouter,
        )
    except ModuleNotFoundError:
        from brain_researcher.services.agent.router import LLMRouter

    history = history or []
    ctx = ctx or {}
    extra_env = dict(env_override or {})

    # Pluck orchestration-specific fields from env override
    thread_id = extra_env.pop("thread_id", thread_id)
    history = extra_env.pop("history", history)
    ctx_extra = extra_env.pop("ctx", None) or {}
    ctx.update(ctx_extra)
    if thread_id:
        ctx.setdefault("thread_id", thread_id)
    ctx.setdefault("history_len", len(history))

    # Check if orchestrator mode is enabled
    if os.getenv("BR_CHAT_ORCHESTRATOR_ENABLED", "0").lower() in {"1", "true", "yes"}:
        from brain_researcher.services.agent.advanced_error_recovery import (
            create_error_recovery_system,
        )
        from brain_researcher.services.agent.memory import ConversationMemory
        from brain_researcher.services.agent.planner.evidence_neo4j import (
            get_default_evidence_store,
        )
        from brain_researcher.services.agent.planner.failure_neo4j import (
            get_default_failure_writer,
        )
        from brain_researcher.services.agent.tool_allowlist_loader import (
            resolve_runtime_tool_allowlist,
        )
        from brain_researcher.services.agent.tool_executor import ToolExecutor
        from brain_researcher.services.agent.tool_router import (
            ToolRouter,
            load_tool_families,
        )
        from brain_researcher.services.shared.settings import get_settings
        from brain_researcher.services.tools.tool_registry import ToolRegistry

        tool_registry = ToolRegistry(
            auto_discover=True, use_capabilities=True, enable_integrations=False
        )
        runtime_allowlist = resolve_runtime_tool_allowlist(
            get_settings().tool_allowlist
        )
        _prune_tool_registry_by_allowlist(tool_registry, runtime_allowlist)
        tool_router = ToolRouter(
            core_registry=tool_registry,
            families=load_tool_families(),
            chat_whitelist=runtime_allowlist,
        )
        tool_executor = ToolExecutor(
            tool_registry=tool_registry,
            safe_mode=True,
            evidence_writer=get_default_evidence_store(),
            failure_writer=get_default_failure_writer(),
        )
        memory = ConversationMemory()
        error_recovery = create_error_recovery_system(tool_registry)

        llm_router = LLMRouter()
        orchestrator = ChatOrchestrator(
            router=llm_router,
            tool_executor=tool_executor,
            tool_registry=tool_registry,
            tool_router=tool_router,
            memory=memory,
            error_recovery=error_recovery,
        )
        reply = orchestrator.handle_chat(message, history=history, ctx=ctx)
        return {
            "text": reply.answer,
            "tool_calls": reply.tool_calls,
            "metadata": reply.metadata or {},
        }

    # Apply environment overrides if provided
    original_env = {}
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

    try:
        model_name = os.environ.get("DEFAULT_LLM_MODEL", "unknown")
        use_gemini_cli = os.environ.get("USE_GEMINI_CLI", "true").lower() == "true"

        text: str
        provider = "unknown"
        model_used = model_name
        route = "primary"
        usage = {}
        fallback_reason = None

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
                    prompt=message, initial_model=model_name
                )
                route = "primary" if model_used == model_name else "fallback"
            else:
                from brain_researcher.services.agent.llm import get_llm

                llm = get_llm()
                response = llm.invoke(message)
                text = (
                    response.content if hasattr(response, "content") else str(response)
                )
                provider = "configured"
                route = "default"
        else:
            from brain_researcher.services.agent.llm import get_llm

            llm = get_llm()
            response = llm.invoke(message)
            text = response.content if hasattr(response, "content") else str(response)
            provider = "configured"
            route = "default"

        return {
            "text": text,
            "metadata": {
                "provider": provider,
                "model": model_used,
                "route": route,
                "usage": usage,
                "fallback_reason": fallback_reason,
            },
        }

    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def agent_act_core(
    payload: Dict[str, Any],
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    llm_router: Any | None = None,
) -> Dict[str, Any]:
    """
    Core agent action function without Flask dependencies.

    Args:
        payload: Dict containing:
            - query: The user query (required)
            - session_id: Optional session identifier
            - tool_mode: 'auto', 'off', or 'force' (default: 'auto')
            - tools_whitelist: List of allowed tools
            - budget_ms: Execution budget in milliseconds (default: 90000)
        trace_id: Optional trace ID for logging
        run_id: Optional run ID for telemetry
        llm_router: Optional router used for the planning LLM call.

    Returns:
        Dict with 'message', 'tool_calls', 'artifacts', 'runCard', 'session_id' keys.
        On error, returns dict with 'error' key.
    """
    query = payload.get("query")
    session_id = payload.get("session_id")
    tool_mode = payload.get("tool_mode", "auto")
    tools_whitelist = payload.get("tools_whitelist", [])
    if "budget_ms" in payload:
        budget_ms = payload.get("budget_ms")
    else:
        from brain_researcher.services.shared.retry_timeout import load_timeout_config

        budget_ms = load_timeout_config().tool_execution_budget_ms
    messages = payload.get("messages") or []

    if not query:
        return {"error": "Missing query parameter", "code": "INVALID_PARAMETER"}

    trace_id = trace_id or str(uuid.uuid4())[:8]
    run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"

    def _build_run_card_v1(
        *, execution: dict[str, Any], provenance: dict[str, Any] | None
    ):
        from datetime import datetime, timezone

        from brain_researcher.core.contracts.ids import IdsV1
        from brain_researcher.core.contracts.run_card import RunCardV1

        ids = IdsV1(
            analysis_id=run_id,
            run_id=run_id,
            job_id=run_id,
            trace_id=trace_id,
            session_id=session_id,
        )
        card = RunCardV1(
            id=run_id,
            timestamp=datetime.now(tz=timezone.utc),
            ids=ids,
            execution=execution,
            provenance=provenance,
        )
        dumped = card.model_dump(mode="json", exclude_none=True)
        # Back-compat: UI/tests still look for runCard.run_id.
        dumped.setdefault("run_id", run_id)
        return dumped

    # ------------------------------------------------------------------
    # LLM-only fallback: skip tool discovery/execution entirely
    # Triggered when tool discovery is disabled or explicitly requested.
    # ------------------------------------------------------------------
    fallback_flag = os.getenv("LLM_ONLY_FALLBACK", "0").lower() in {"1", "true", "yes"}
    discovery_disabled = os.getenv("DISABLE_TOOL_DISCOVERY", "0").lower() in {
        "1",
        "true",
        "yes",
    }
    if fallback_flag or discovery_disabled:
        logger.info(
            f"[{trace_id}] LLM-only fallback enabled (discovery_disabled={discovery_disabled})"
        )
        try:
            model_name = os.environ.get("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
            provider = "openai"

            # Detect Gemini models and use Google AI client
            if model_name.startswith("gemini"):
                import google.generativeai as genai

                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
                    "GOOGLE_API_KEY"
                )
                if not api_key:
                    raise ValueError(
                        "GEMINI_API_KEY or GOOGLE_API_KEY required for Gemini models"
                    )

                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(query)
                response_text = response.text
                provider = "google"
            else:
                # Use OpenAI client for non-Gemini models
                from openai import OpenAI

                client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": query}],
                )
                response_text = completion.choices[0].message.content

            return {
                "message": {"role": "assistant", "content": response_text},
                "tool_calls": [],
                "artifacts": [],
                "runCard": _build_run_card_v1(
                    execution={
                        "provider": provider,
                        "model": model_name,
                        "latency_ms": None,
                        "tool_mode": "none",
                        "route": "llm_only_direct",
                        "transport": "api",
                        "usage": {},
                        "selected_tool": None,
                    },
                    provenance={"tool_calls": []},
                ),
                "session_id": session_id,
            }
        except Exception as exc:
            logger.exception(f"[{trace_id}] LLM-only fallback failed: {exc}")
            return {"error": f"Fallback chat failed: {exc}", "code": "INTERNAL_ERROR"}

    # Heavy imports are deferred until after the fallback to keep tests hermetic
    from brain_researcher.services.agent import telemetry
    from brain_researcher.services.agent.router import LLMRouter

    # Budgeted executor lives under agent.tool_executor (compat wrapper)
    from brain_researcher.services.agent.tool_executor import BudgetedToolExecutor
    from brain_researcher.services.agent.web_service import (
        _config,
        get_agent,
        infer_provider,
    )
    from brain_researcher.services.tools.spec import (
        ToolSpecRegistry,
        compress_schema,
        spec_from_tool,
    )

    try:
        from brain_researcher.services.tools.args_resolver import ArgsResolver
    except ModuleNotFoundError:
        ArgsResolver = None
        logger.warning("ArgsResolver module not found; falling back to raw parameters")
    from pydantic import ValidationError

    # If run_id was generated above, keep it; otherwise use telemetry for full path
    run_id = run_id or telemetry.new_run_id()

    demo_mode = _config.get("DEMO_MODE", False)

    from brain_researcher.config.run_artifacts import (
        build_run_dir,
        get_recorder_config,
    )
    from brain_researcher.services.agent.guardrails import (
        GuardrailsSnapshotV1,
        GuardrailsV1,
    )
    from brain_researcher.services.agent.run_bundle import (
        log_trace_event,
        persist_agent_analysis_bundle,
        persist_agent_observation,
        persist_agent_trajectory,
    )

    run_dir = build_run_dir(get_recorder_config().root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    guardrails_snapshot = GuardrailsSnapshotV1(
        frozen=bool(payload.get("frozen", False)),
        no_network=bool(payload.get("no_network", False)),
        budget_ms=budget_ms,
        tool_allowlist=tools_whitelist or None,
        policy_id=os.getenv("BR_POLICY_ID"),
    )
    guardrails = GuardrailsV1(guardrails_snapshot)
    violations: list[dict[str, Any]] = []

    # Defaults to keep finally blocks robust.
    model_hint = os.environ.get("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
    provider = "unknown"
    route = "direct"
    transport = "sdk"
    credential_used = None
    bill_to = None
    fallback_reason = None
    usage: dict[str, Any] = {}

    spans: List[Dict[str, Any]] = []
    plan_metadata = None
    selected_tool_name: Optional[str] = None
    tool_invocation_count = 0
    tool_result_status = "skipped"
    telemetry_tool_calls: List[Dict[str, Any]] = []
    tool_calls = []
    artifacts = []
    tool_executor = None
    error_info: Optional[Exception] = None
    response_text: str | None = None
    model_name: str | None = None
    started_at_ms = int(time.time() * 1000)
    finished_at_ms: int | None = None

    act_span = telemetry.start_span(
        "agent.act",
        {
            "channel": "api",
            "request_type": "act",
            "session_id": session_id,
            "tool_mode": tool_mode,
        },
    )
    trace_payload_base: dict[str, Any] = {
        "job_id": run_id,
        "run_id": run_id,
        "analysis_id": run_id,
        "trace_id": trace_id,
    }
    if session_id:
        trace_payload_base["session_id"] = session_id

    try:
        log_trace_event(
            run_dir,
            run_id=run_id,
            event_type="act.started",
            payload={
                **trace_payload_base,
                "tool_mode": tool_mode,
                "budget_ms": budget_ms,
                "guardrails": guardrails_snapshot.model_dump(exclude_none=True),
            },
        )
        start_time = time.time()
        logger.info(
            f"[{trace_id}] Processing query with tools: {query[:100]}... (mode: {tool_mode})"
        )

        if llm_router is None:
            llm_router = LLMRouter()
        model_hint = os.environ.get("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
        provider = infer_provider(model_hint)
        model_name = model_hint

        if tool_mode == "off":
            chat_span = telemetry.start_span(
                "agent.chat",
                {"channel": "api", "run_id": run_id, "session_id": session_id},
            )
            try:
                chat_result = llm_router.route_chat(query, model_hint=model_hint)
            except Exception as chat_exc:
                spans.append(chat_span.finish(status="error", error=str(chat_exc)))
                raise

            plan_metadata = chat_result.metadata
            spans.append(
                chat_span.finish(
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

            response_text = chat_result.text
            usage = plan_metadata.usage or {}
            provider = plan_metadata.provider or provider
            model_name = plan_metadata.model or model_hint
            route = plan_metadata.route
            transport = plan_metadata.transport
            credential_used = plan_metadata.credential
            bill_to = plan_metadata.bill_to
            fallback_reason = plan_metadata.fallback_reason
            latency_ms = plan_metadata.latency_ms
            if latency_ms is None:
                latency_ms = int((time.time() - start_time) * 1000)
            finished_at_ms = int(time.time() * 1000)

            result = {
                "message": {"role": "assistant", "content": response_text},
                "tool_calls": [],
                "artifacts": [],
                "runCard": _build_run_card_v1(
                    execution={
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
                        "selected_tool": None,
                        "api_fee_debit": getattr(plan_metadata, "api_fee_debit", None),
                    },
                    provenance={
                        "run_dir": str(run_dir),
                        "trace_jsonl": str(run_dir / "trace.jsonl"),
                        "trajectory_json": str(run_dir / "trajectory.json"),
                        "observation_json": str(run_dir / "observation.json"),
                        "analysis_bundle_json": str(run_dir / "analysis_bundle.json"),
                        "tool_calls": [],
                    },
                ),
                "session_id": session_id,
            }
            return result

        agent = get_agent()
        tool_registry = agent.tool_registry
        tool_executor = BudgetedToolExecutor(
            global_budget_ms=budget_ms,
            use_subprocess=False,
            tool_registry=tool_registry,
            safe_mode=True,
        )
        spec_registry = ToolSpecRegistry()
        resolver = (
            ArgsResolver(context={"working_dir": os.getcwd()}) if ArgsResolver else None
        )

        all_tools = agent.tool_registry.get_all_tools()
        query_lower = query.lower()

        # Score and select tools
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

        parsed = None
        if tool_mode == "force" and tools_whitelist and len(tools_whitelist) == 1:
            parsed = {
                "tool": tools_whitelist[0],
                "params": payload.get("tool_params", {}) or {},
                "reasoning": "forced_tool_selection",
            }
            selection_text = json_module.dumps(parsed)
            usage = {}
            route = "forced"
            transport = "direct"
            credential_used = None
            bill_to = None
            fallback_reason = "forced_tool_selection"
            model_name = model_hint
        else:
            # Plan phase
            plan_span = telemetry.start_span(
                "agent.plan",
                {"channel": "api", "run_id": run_id, "session_id": session_id},
            )
            try:
                plan_result = llm_router.route_chat(tool_prompt, model_hint=model_hint)
            except Exception as plan_exc:
                spans.append(plan_span.finish(status="error", error=str(plan_exc)))
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

            # Parse LLM response
            try:
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

        # Tool execution phase
        tool_choice = (parsed.get("tool") or "").strip().lower()
        if (
            tool_mode != "off"
            and tool_choice
            and tool_choice not in {"error", "none", "null"}
        ):
            tool_name = parsed["tool"]
            tool_params = parsed.get("params", {})
            tool_call_id = f"call_{uuid.uuid4().hex[:10]}"
            selected_tool_name = tool_name

            from brain_researcher.services.agent.tool_mapper import get_tool_mapper

            mapper = get_tool_mapper(agent.tool_registry)
            mapped_name, match_type = mapper.map_tool_name(
                tool_name,
                whitelist=tools_whitelist if tools_whitelist else None,
                trace_id=trace_id,
            )

            if mapped_name:
                tool = agent.tool_registry.get_tool(mapped_name)
                if match_type != "exact":
                    logger.info(
                        f"[{trace_id}] Tool remapped via {match_type}: {tool_name} -> {mapped_name}"
                    )
            else:
                tool = None

            tool_id_for_policy = mapped_name or tool_name
            preflight = guardrails.check_tool_call(
                tool_id_for_policy, step_id=tool_call_id
            )
            if not preflight.allowed:
                blocked = [
                    v.model_dump(exclude_none=True) for v in preflight.violations
                ]
                violations.extend(blocked)
                tool_calls.append(
                    {
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "tool": mapped_name,
                        "arguments": tool_params,
                        "status": "blocked",
                        "error": "Blocked by guardrails",
                        "violations": blocked,
                    }
                )
                telemetry_tool_calls.append(
                    {
                        "name": tool_id_for_policy,
                        "status": "blocked",
                        "match_type": "guardrails",
                    }
                )
                tool_result_status = "blocked"
                log_trace_event(
                    run_dir,
                    run_id=run_id,
                    event_type="tool.blocked",
                    payload={
                        **trace_payload_base,
                        "tool_call_id": tool_call_id,
                        "tool_id": tool_id_for_policy,
                        "violations": blocked,
                    },
                )
            elif tool:
                tool_span = telemetry.start_span(
                    f"agent.tool.{tool_id_for_policy}",
                    {
                        "tool_name": tool_id_for_policy,
                        "run_id": run_id,
                        "session_id": session_id,
                    },
                )
                try:
                    tool_spec = spec_registry.get(mapped_name) if mapped_name else None
                    if tool_spec and ArgsResolver and resolver is not None:
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
                            f"[{trace_id}] Parameters resolved via ArgsResolver"
                        )
                    else:
                        from brain_researcher.services.tools.arg_adapter import (
                            ToolArgumentAdapter,
                        )

                        adapted_args = ToolArgumentAdapter.adapt(
                            tool_id_for_policy,
                            tool_params,
                            demo=demo_mode,
                            trace_id=trace_id,
                        )
                        logger.info(
                            f"[{trace_id}] Parameters adapted via legacy adapter"
                        )

                    logger.info(
                        f"[{trace_id}] Executing tool: {tool_id_for_policy} with processed args"
                    )

                    log_trace_event(
                        run_dir,
                        run_id=run_id,
                        event_type="tool.started",
                        payload={
                            **trace_payload_base,
                            "tool_call_id": tool_call_id,
                            "tool_id": tool_id_for_policy,
                        },
                    )

                    exec_context: Dict[str, Any] = {
                        "job_id": run_id,
                        "thread_id": session_id or run_id,
                        "parent_run_id": run_id,
                        "step_id": tool_call_id,
                        "tool_call_id": tool_call_id,
                    }
                    # Keep non-happy-path tests fast and deterministic.
                    if tool_id_for_policy.startswith("mcp.test_"):
                        exec_context.update(
                            {"retry_on_failure": False, "max_retries": 0}
                        )

                    tool_result = tool_executor.execute_with_timeout(
                        tool=tool,
                        args=adapted_args,
                        timeout_ms=None,
                        trace_id=trace_id,
                        context=exec_context,
                    )
                    tool_invocation_count += 1
                except ValidationError as val_err:
                    logger.error(f"[{trace_id}] Validation error: {val_err}")
                    from brain_researcher.services.tools.tool_base import ToolResult

                    tool_result = ToolResult(
                        status="error", error=f"VALIDATION_ERROR: {str(val_err)}"
                    )

                tool_summary = tool_result.model_dump()
                tool_status = "success" if tool_result.status == "success" else "error"
                tool_result_status = tool_status
                spans.append(
                    tool_span.finish(
                        status=tool_status, exit_code=tool_summary.get("exit_code")
                    )
                )
                telemetry_tool_calls.append(
                    {
                        "name": tool_id_for_policy,
                        "status": tool_status,
                        "match_type": match_type,
                    }
                )
                tool_md = tool_summary.get("metadata") or {}
                tool_calls.append(
                    {
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "tool": tool_id_for_policy,
                        "arguments": tool_params,
                        "status": "ok" if tool_result.status == "success" else "error",
                        "result": tool_summary.get("data"),
                        "error": tool_summary.get("error"),
                        "error_category": tool_md.get("error_category"),
                        "is_retryable": tool_md.get("is_retryable"),
                        "recovery_strategy": tool_md.get("recovery_strategy"),
                        "recovery_suggestions": tool_md.get("recovery_suggestions")
                        or [],
                        "run_dir": tool_md.get("run_dir"),
                        "provenance_path": tool_md.get("provenance_path"),
                        "execution_id": tool_md.get("execution_id"),
                    }
                )
                log_trace_event(
                    run_dir,
                    run_id=run_id,
                    event_type="tool.finished",
                    payload={
                        **trace_payload_base,
                        "tool_call_id": tool_call_id,
                        "tool_id": tool_id_for_policy,
                        "status": tool_status,
                        "run_dir": tool_md.get("run_dir"),
                        "provenance_path": tool_md.get("provenance_path"),
                    },
                )
                if tool_result.data:
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
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "arguments": tool_params,
                        "status": "error",
                        "error": f"Tool {tool_id_for_policy} not found in registry",
                    }
                )
                telemetry_tool_calls.append(
                    {
                        "name": tool_id_for_policy,
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

        if tool_calls:
            first_call = tool_calls[0]
            if first_call.get("status") == "ok":
                response_text = f"{parsed.get('reasoning', 'Analysis completed')}. Tool '{first_call['name']}' executed successfully."
                # If tool returned data, surface a short summary
                if first_call.get("result"):
                    response_text += (
                        "\nResult: "
                        + json_module.dumps(first_call["result"], ensure_ascii=False)[
                            :800
                        ]
                    )
            else:
                # surface tool error directly to user
                err = first_call.get("error") or "Tool execution failed"
                response_text = f"Tool '{first_call['name']}' failed: {err}"
                if first_call.get("error_category"):
                    response_text += f"\nError category: {first_call['error_category']}"
                suggestions = first_call.get("recovery_suggestions") or []
                if suggestions:
                    response_text += "\nSuggested next steps:\n- " + "\n- ".join(
                        suggestions[:5]
                    )
        else:
            response_text = parsed.get("reasoning", selection_text)

        finished_at_ms = int(time.time() * 1000)

        result = {
            "message": {"role": "assistant", "content": response_text},
            "tool_calls": tool_calls,
            "artifacts": artifacts,
            "runCard": _build_run_card_v1(
                execution={
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
                    "api_fee_debit": (
                        getattr(plan_metadata, "api_fee_debit", None)
                        if plan_metadata
                        else None
                    ),
                },
                provenance={
                    "run_dir": str(run_dir),
                    "trace_jsonl": str(run_dir / "trace.jsonl"),
                    "trajectory_json": str(run_dir / "trajectory.json"),
                    "observation_json": str(run_dir / "observation.json"),
                    "analysis_bundle_json": str(run_dir / "analysis_bundle.json"),
                    "tool_calls": tool_calls,
                },
            ),
            "session_id": session_id,
        }

    except Exception as exc:
        error_info = exc
        logger.exception(f"[{trace_id}] Error in agent_act_core: {exc}")
        error_code = (
            "INSUFFICIENT_API_CREDITS"
            if type(exc).__name__ == "ApiFeeReservationError"
            else "INTERNAL_ERROR"
        )
        try:
            log_trace_event(
                run_dir,
                run_id=run_id,
                event_type="act.failed",
                payload={
                    **trace_payload_base,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
        except Exception:
            pass
        result = {
            "error": f"Failed to execute action: {str(exc)}",
            "code": error_code,
        }

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
            status="error" if error_info else "ok", **act_attrs
        )
        spans.insert(0, act_span_record)

        event_payload = {
            "run_id": run_id,
            "channel": "api",
            "request_type": "act",
            "session_id": session_id,
            "latency_ms": int(round(act_span_record.get("duration_ms", 0))),
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
                "api_fee_debit": (
                    getattr(plan_metadata, "api_fee_debit", None)
                    if plan_metadata
                    else None
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
                {"message": str(error_info), "type": type(error_info).__name__}
                if error_info
                else None
            ),
        }
        try:
            telemetry.record_event(event_payload, event_type="act")
        except Exception:
            logger.exception("[agent_act_core] Failed to record telemetry event")

        finished_at_ms = finished_at_ms or int(time.time() * 1000)
        state = "failed" if error_info else "succeeded"

        # Best-effort: write closed-loop bundle artifacts for replay/benchmark.
        try:
            provenance = {
                "run_id": run_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "tool_mode": tool_mode,
                "guardrails": guardrails_snapshot.model_dump(exclude_none=True),
                "llm": {
                    "provider": plan_metadata.provider if plan_metadata else provider,
                    "model": plan_metadata.model if plan_metadata else model_name,
                    "route": plan_metadata.route if plan_metadata else "direct",
                    "transport": plan_metadata.transport if plan_metadata else "sdk",
                },
            }
            (run_dir / "provenance.json").write_text(
                json_module.dumps(provenance, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            persist_agent_trajectory(
                run_dir,
                session_id=session_id or run_id,
                model_name=model_name or "unknown",
                user_message=query,
                agent_message=(result.get("message") or {}).get("content") or "",
                tool_calls=list(result.get("tool_calls") or []),
                extra={"trace_id": trace_id},
            )
            persist_agent_observation(
                run_dir,
                job_id=run_id,
                run_id=run_id,
                state=state,
                run_card=result.get("runCard") if isinstance(result, dict) else None,
                provenance=provenance,
                tool_calls=list(result.get("tool_calls") or []),
                artifacts=list(result.get("artifacts") or []),
                violations=violations or None,
                created_at_ms=started_at_ms,
                started_at_ms=started_at_ms,
                finished_at_ms=finished_at_ms,
            )
            persist_agent_analysis_bundle(
                run_dir,
                job_id=run_id,
                run_id=run_id,
                state=state,
                run_card=result.get("runCard") if isinstance(result, dict) else None,
                provenance=provenance,
                policy={
                    "guardrails": guardrails_snapshot.model_dump(exclude_none=True)
                },
            )
            log_trace_event(
                run_dir,
                run_id=run_id,
                event_type="act.bundle_written",
                payload={**trace_payload_base, "state": state},
            )
        except Exception:
            logger.exception("[agent_act_core] Failed to persist run bundle")

        if tool_executor is not None:
            tool_executor.shutdown()

    return result
