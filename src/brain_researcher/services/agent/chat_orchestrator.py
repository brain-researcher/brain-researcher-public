"""Chat orchestrator with tool selection scaffolding."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.agent.advanced_error_recovery import (
    AdvancedErrorRecoverySystem,
)
from brain_researcher.services.agent.checkpoint_manager import (
    CheckpointManager,
    ExecutionState,
)
from brain_researcher.services.agent.code_orchestrator import (
    CodeResult,
    get_code_orchestrator,
)
from brain_researcher.services.agent.codegen.context import (
    CodegenResult,
    ExecutionResult,
)
from brain_researcher.services.agent.codegen.fs_context import (
    GeminiCliFsClient,
    build_fs_context_for_task_sync,
)
from brain_researcher.services.agent.codegen.render import render_result_for_chat
from brain_researcher.services.agent.memory import ConversationMemory
from brain_researcher.services.agent.monitoring.metrics_collector import (
    get_default_metrics_collector,
)
from brain_researcher.services.agent.planning import (
    PlanningEngine,
    QueryIntent,
    WorkflowStep,
)
from brain_researcher.services.agent.resolution_memory import (
    add_pending_decision,
    clear_pending_decisions,
    get_generic_clarification_state,
    get_overrides,
    get_pending_decisions,
    pop_pending_decision,
    record_generic_clarification_answer,
    set_override,
)
from brain_researcher.services.agent.router import LLMRouter
from brain_researcher.services.agent.tool_candidate_service import (
    generate_tool_candidates,
)
from brain_researcher.services.agent.tool_executor import (
    ToolExecutionRequest,
)
from brain_researcher.services.agent.tool_router import (
    RoutingToolView,
    ToolFamily,
    ToolRouter,
    load_chat_tools_whitelist,
    load_tool_families,
)
from brain_researcher.services.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from brain_researcher.services.agent.knowledge import (
        EvidenceAggregator,
        EvidenceBundle,
        KnowledgeMemoryStore,
        KnowledgePlanner,
    )

logger = logging.getLogger(__name__)

_CODE_AGENT_TOOL_ID = "code_agent"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _candidate_rank(tools: list[RoutingToolView], runtime_id: str | None) -> int | None:
    if not runtime_id:
        return None
    for idx, tool in enumerate(tools, start=1):
        if tool.runtime_id == runtime_id:
            return idx
    return None


@dataclass
class ChatReply:
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] | None = None


@dataclass
class ToolPlan:
    tool: str
    params: dict[str, Any]
    reasoning: str
    is_family: bool = False
    op: str | None = None
    leaf_runtime_id: str | None = None


class ChatOrchestrator:
    """Selects a tool (or no_tool), executes, then summarizes."""

    def __init__(
        self,
        router: LLMRouter,
        tool_executor: Any | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_router: ToolRouter | None = None,
        memory: ConversationMemory | None = None,
        error_recovery: AdvancedErrorRecoverySystem | None = None,
        max_recovery_attempts: int = 2,
        knowledge_aggregator: EvidenceAggregator | None = None,
        knowledge_planner: KnowledgePlanner | None = None,
        enable_knowledge_layer: bool = True,
    ) -> None:
        self.router = router
        self.tool_executor = tool_executor
        self.registry = tool_registry or ToolRegistry.from_env(auto_discover=True)
        self.families: dict[str, ToolFamily] = load_tool_families()
        # Keep router in sync with the shared registry + family config so
        # chat-safe filtering works as expected.
        self.tool_router = tool_router or ToolRouter(
            core_registry=self.registry,
            families=self.families,
            chat_whitelist=load_chat_tools_whitelist(),
        )
        self.memory = memory or ConversationMemory()
        # Allow explicit False to disable recovery in constrained environments/tests
        if error_recovery is False:
            self.error_recovery = None
        else:
            self.error_recovery = error_recovery or AdvancedErrorRecoverySystem(
                tool_registry=self.registry
            )
        self.max_recovery_attempts = max_recovery_attempts
        # Default to in-memory checkpoints to avoid Redis dependency during dev/test
        self.checkpoints = CheckpointManager(storage_backend="memory")
        # Track K+ knowledge layer for evidence-aware tool selection and planning
        self._knowledge_aggregator = knowledge_aggregator
        self._knowledge_planner = knowledge_planner
        self._enable_knowledge_layer = enable_knowledge_layer

        # Shared knowledge memory (per account) for personalization/debugging
        if enable_knowledge_layer:
            try:
                from brain_researcher.services.agent.knowledge import (
                    KnowledgeMemoryStore,
                )

                self._knowledge_memory_store: KnowledgeMemoryStore | None = (
                    KnowledgeMemoryStore()
                )
            except Exception:  # pragma: no cover - optional dependency failure
                self._knowledge_memory_store = None
        else:
            self._knowledge_memory_store = None

        self._metrics = get_default_metrics_collector()
        self._pending_patches: dict[str, dict[str, Any]] = {}

        # Load chat tool schemas (examples) for selection prompt enrichment
        schemas_path = resolve_from_config("catalog", "chat_tool_schemas.yaml")
        try:
            self.chat_schemas = (
                yaml.safe_load(schemas_path.read_text()).get("schemas", {})
                if schemas_path.exists()
                else {}
            )
        except Exception:
            self.chat_schemas = {}

        self._fs_client = GeminiCliFsClient()
        self._preflight_parser = None
        self._tool_retriever = None
        self._workflow_index = self._load_workflow_index()
        self._multiagent_router = None
        self._multiagent_router_failed = False

    def _get_preflight_parser(self):
        if self._preflight_parser is not None:
            return self._preflight_parser

        use_llm = os.getenv("BR_PREFLIGHT_USE_LLM", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        llm = None
        if use_llm:
            try:
                from brain_researcher.services.agent.llm import get_llm

                llm = get_llm()
            except Exception as exc:
                logger.debug("Preflight LLM unavailable: %s", exc)
                llm = None

        try:
            from brain_researcher.services.agent.domain_knowledge import (
                get_domain_knowledge,
            )
            from brain_researcher.services.agent.query_understanding import (
                create_advanced_parser,
            )

            self._preflight_parser = create_advanced_parser(
                domain_knowledge=get_domain_knowledge(),
                llm=llm,
            )
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Preflight parser unavailable: %s", exc)
            self._preflight_parser = None

        return self._preflight_parser

    def _get_tool_retriever(self):
        if self._tool_retriever is not None:
            return self._tool_retriever

        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("BR_USE_TOOL_RETRIEVER") is None
        ):
            return None

        use_retriever = os.getenv("BR_USE_TOOL_RETRIEVER", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not use_retriever:
            return None

        try:
            from brain_researcher.services.agent.tool_retriever import ToolRetriever

            self._tool_retriever = ToolRetriever()
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("ToolRetriever unavailable: %s", exc)
            self._tool_retriever = None

        return self._tool_retriever

    def handle_chat(
        self,
        user_msg: str,
        history: list[Any] | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> ChatReply:
        history = history or []
        ctx = ctx or {}
        ctx = self._restore_checkpoint_context(ctx)
        thread_id = str(ctx.get("thread_id", "default"))

        # Quick path: user confirming patch apply from prior run
        if self._should_apply_patches(user_msg, thread_id):
            return self._apply_pending_patches(thread_id, ctx)

        self._apply_resolution_decision_reply(user_msg, ctx, thread_id)

        # Global flag to disable tools (LLM-only), but keep capability choice separate
        llm_only_fallback = os.environ.get("LLM_ONLY_FALLBACK", "").lower() in {
            "1",
            "true",
            "yes",
        }

        selftest_mode = self._detect_mcp_selftest_mode(user_msg, ctx)
        if selftest_mode:
            selftest_reply = self._handle_mcp_selftest(
                user_msg=user_msg,
                ctx=ctx,
                thread_id=thread_id,
                mode=selftest_mode,
            )
            if selftest_reply is not None:
                return selftest_reply

        # If explicitly coding (or heuristically) handle coding first to avoid neuro prompt bleed-through
        is_coding = self._is_coding_query(user_msg, ctx)
        if is_coding:
            coding_reply = self._handle_coding_chat(user_msg, history, ctx, thread_id)
            if coding_reply is not None:
                return coding_reply

        # If tools are globally disabled (fallback) and not coding, answer directly with general LLM
        if llm_only_fallback and not is_coding:
            return self._general_llm_reply(user_msg, history, ctx, thread_id)

        # Persist user message into lightweight memory for future context reuse.
        try:
            self.memory.append(thread_id, "user", user_msg, {"kind": "query"})
        except Exception as exc:  # pragma: no cover - best effort only
            logger.debug("memory append failed: %s", exc)

        # Preflight: query understanding + KG tool candidates (best-effort)
        preflight_candidate_latency_ms: float | None = None
        preflight_candidate_diagnostics: dict[str, Any] = {}
        try:
            tool_candidate_bundle = generate_tool_candidates(
                user_msg,
                ctx=ctx,
                parser=self._get_preflight_parser(),
                tool_retriever=self._get_tool_retriever(),
                registry=self.registry,
            )
            ctx = tool_candidate_bundle.ctx
            preflight_candidate_diagnostics = dict(
                tool_candidate_bundle.tool_candidate_diagnostics or {}
            )
            preflight_candidate_latency_ms = preflight_candidate_diagnostics.get(
                "candidate_generation_latency_ms"
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Preflight enrichment failed: %s", exc)

        # Track K+: Gather knowledge evidence before tool selection
        knowledge_evidence = self._gather_knowledge_evidence(user_msg, ctx)
        if knowledge_evidence:
            ctx = {**ctx, "knowledge_evidence": knowledge_evidence}

        structured_ctx = self._build_structured_context(
            user_msg, history, ctx, thread_id
        )

        pending_decisions = get_pending_decisions(ctx)
        if pending_decisions:
            first = pending_decisions[0]
            question = self._pending_question_text(first)
            checkpoint_id = self._record_checkpoint(
                thread_id,
                ToolPlan(
                    tool="no_tool",
                    params={},
                    reasoning="resolution_pending_decision",
                ),
                history,
                ctx,
            )
            reply = ChatReply(
                answer=question,
                tool_calls=[],
                metadata={
                    "type": "clarification",
                    "questions": [question],
                    "pending_decision": first,
                    "checkpoint_id": checkpoint_id,
                },
            )
            self.memory.append(
                thread_id,
                "assistant",
                reply.answer,
                {"type": "clarification"},
            )
            return reply

        # Clarify early if query understanding reported ambiguities.
        qur = ctx.get("query_understanding") if isinstance(ctx, dict) else None
        ambiguities: list[str] = list(getattr(qur, "ambiguities", []) or [])
        if ambiguities:
            self._queue_generic_clarifications(
                ctx,
                ambiguities[:3],
                source="query_understanding",
            )
            pending_decisions = get_pending_decisions(ctx)
            if pending_decisions:
                first = pending_decisions[0]
                question = self._pending_question_text(first)
                reply = ChatReply(
                    answer=question,
                    tool_calls=[],
                    metadata={
                        "type": "clarification",
                        "questions": [question],
                        "pending_decision": first,
                    },
                )
                self.memory.append(
                    thread_id,
                    "assistant",
                    reply.answer,
                    {"type": "clarification"},
                )
                return reply

        # ===== Workflow/Pipeline-first branch for imaging queries =====
        use_planning = ctx.get("use_planning_engine", False) if ctx else False
        detected_domain = self._detect_imaging_domain(user_msg)
        matched_workflow = self._match_declared_workflow(user_msg)
        if matched_workflow:
            use_planning = True
            ctx = {**ctx, "preferred_workflow_id": matched_workflow}

        logger.debug(
            "[pipeline] branch check use_planning=%s detected_domain=%s workflow=%s ctx_keys=%s thread_id=%s",
            use_planning,
            detected_domain,
            matched_workflow,
            list(ctx.keys()) if ctx else None,
            thread_id,
        )

        if use_planning or detected_domain:
            pipeline_result = self._try_pipeline_execution(
                user_msg, detected_domain, ctx or {}, thread_id
            )
            if pipeline_result is not None:
                logger.info(
                    "[pipeline] succeeded for query='%s' domain=%s workflow=%s thread_id=%s",
                    user_msg,
                    detected_domain,
                    matched_workflow,
                    thread_id,
                )
                return pipeline_result
            else:
                logger.info(
                    "[pipeline] fallback to single-tool for query='%s' domain=%s thread_id=%s",
                    user_msg,
                    detected_domain,
                    thread_id,
                )
        # ===== END: Pipeline-first branch =====

        # ===== END: Pipeline-first branch =====

        tool_routing_t0 = time.perf_counter()
        router_candidate_t0 = time.perf_counter()
        tools = self.tool_router.get_candidates(user_msg, history, ctx)
        router_candidate_latency_ms = (
            time.perf_counter() - router_candidate_t0
        ) * 1000.0

        # Serialize candidates for telemetry/UI (limit to top 10)
        candidates_data = [
            {
                "id": t.runtime_id,
                "name": t.name,
                "description": t.description,
                "tags": t.tags,
                "dangerous": t.dangerous,
                "is_family": t.is_family(),
            }
            for t in tools[:10]
        ]

        selection_t0 = time.perf_counter()
        plan_dict = self._select_tool(user_msg, history, tools, structured_ctx)
        selection_latency_ms = (time.perf_counter() - selection_t0) * 1000.0
        selected_surface_tool = str(plan_dict.get("tool") or "no_tool")
        family_attempted = selected_surface_tool in self.families
        plan = self._enrich_plan(plan_dict)
        plan = self._maybe_enrich_coding_plan(plan, user_msg, ctx)
        selected_tool_rank = _candidate_rank(
            tools,
            None if selected_surface_tool == "no_tool" else selected_surface_tool,
        )
        preflight_diagnostics = preflight_candidate_diagnostics or (
            dict(ctx.get("tool_candidate_diagnostics") or {})
            if isinstance(ctx, dict)
            else {}
        )
        effective_preflight_latency_ms = preflight_diagnostics.get(
            "candidate_generation_latency_ms"
        )
        if effective_preflight_latency_ms is None:
            effective_preflight_latency_ms = preflight_candidate_latency_ms
        candidate_generation_latency_ms = float(
            effective_preflight_latency_ms or 0.0
        ) + float(router_candidate_latency_ms)
        total_routing_latency_ms = (time.perf_counter() - tool_routing_t0) * 1000.0
        family_expand_success = (
            True if plan.is_family else False if family_attempted else None
        )
        routing_metadata = {
            "surface": "chat",
            "candidate_count": len(tools),
            "selected_tool_rank": selected_tool_rank,
            "selected_tool_in_top_5": (
                selected_tool_rank is not None and selected_tool_rank <= 5
            ),
            "selected_tool_in_top_10": (
                selected_tool_rank is not None and selected_tool_rank <= 10
            ),
            "family_selected": plan.is_family,
            "family_expand_success": family_expand_success,
            "candidate_generation_latency_ms": round(
                candidate_generation_latency_ms, 3
            ),
            "selection_latency_ms": round(selection_latency_ms, 3),
            "routing_latency_ms": round(total_routing_latency_ms, 3),
            "preflight_candidate_generation_latency_ms": None
            if effective_preflight_latency_ms is None
            else round(float(effective_preflight_latency_ms), 3),
            "router_candidate_generation_latency_ms": round(
                router_candidate_latency_ms, 3
            ),
        }
        if preflight_diagnostics:
            routing_metadata["preflight"] = preflight_diagnostics
        plan_verdict = None
        plan, plan_verdict = self._apply_multiagent_plan_gate(
            plan=plan,
            user_msg=user_msg,
            structured_ctx=structured_ctx,
            ctx=ctx,
            tools=tools,
        )
        if plan_verdict:
            ctx = {**ctx, "critic_plan_verdict": plan_verdict}

        clarification = self._maybe_clarify(user_msg, plan, ctx, structured_ctx)
        if clarification:
            self.memory.append(
                thread_id,
                "assistant",
                clarification.answer,
                {"type": "clarification"},
            )
            return clarification

        if plan.tool == "no_tool":
            result = self.router.route_chat(user_msg)
            meta_obj = getattr(result, "metadata", None)
            metadata = meta_obj.__dict__ if meta_obj is not None else None
            if plan_verdict:
                metadata = metadata or {}
                metadata["critic_plan_verdict"] = plan_verdict
            reply = ChatReply(answer=result.text, tool_calls=[], metadata=metadata)
            if candidates_data:
                reply.metadata = reply.metadata or {}
                reply.metadata["tool_candidates"] = candidates_data
            reply.metadata = reply.metadata or {}
            reply.metadata["tool_routing"] = routing_metadata
            self._metrics.record_tool_routing(
                surface="chat",
                candidate_count=len(tools),
                selected_rank=selected_tool_rank,
                candidate_generation_latency_ms=candidate_generation_latency_ms,
                selection_latency_ms=selection_latency_ms,
                routing_latency_ms=total_routing_latency_ms,
                family_expand_success=family_expand_success,
                top_k_hits={
                    5: bool(selected_tool_rank is not None and selected_tool_rank <= 5),
                    10: bool(
                        selected_tool_rank is not None and selected_tool_rank <= 10
                    ),
                },
            )
            self.memory.append(thread_id, "assistant", result.text, {"type": "direct"})
            return reply

        checkpoint_id = self._record_checkpoint(thread_id, plan, history, ctx)
        ctx = {**ctx, "checkpoint_id": checkpoint_id}

        tool_result = self._execute_tool(plan, ctx)
        if tool_result.get("status") not in {"ok", "success", "completed"}:
            tool_result = self._recover_from_error(
                plan,
                tool_result,
                user_msg,
                ctx,
                history,
            )
            if tool_result.get("clarification_needed"):
                clar_text = (
                    tool_result.get("question") or "I need more info to proceed."
                )
                reply = ChatReply(
                    answer=clar_text,
                    tool_calls=[{"plan": plan.__dict__, "result": tool_result}],
                    metadata={"type": "clarification", "checkpoint_id": checkpoint_id},
                )
                self.memory.append(
                    thread_id,
                    "assistant",
                    clar_text,
                    {"type": "clarification"},
                )
                return reply

        reply = self._build_final_reply(
            user_msg, plan, tool_result, structured_ctx, thread_id, ctx
        )

        if candidates_data:
            reply.metadata = reply.metadata or {}
            reply.metadata["tool_candidates"] = candidates_data
        if plan_verdict:
            reply.metadata = reply.metadata or {}
            reply.metadata["critic_plan_verdict"] = plan_verdict
        reply.metadata = reply.metadata or {}
        reply.metadata["tool_routing"] = routing_metadata
        self._metrics.record_tool_routing(
            surface="chat",
            candidate_count=len(tools),
            selected_rank=selected_tool_rank,
            candidate_generation_latency_ms=candidate_generation_latency_ms,
            selection_latency_ms=selection_latency_ms,
            routing_latency_ms=total_routing_latency_ms,
            family_expand_success=family_expand_success,
            top_k_hits={
                5: bool(selected_tool_rank is not None and selected_tool_rank <= 5),
                10: bool(selected_tool_rank is not None and selected_tool_rank <= 10),
            },
        )

        return reply

    # internals
    def _select_tool(
        self,
        user_msg: str,
        history: list[Any],
        tools: list[RoutingToolView],
        structured_ctx: str,
    ) -> dict[str, Any]:
        if not tools:
            return {"tool": "no_tool", "params": {}, "reasoning": "no candidates"}

        prompt = self._build_selection_prompt(user_msg, history, tools, structured_ctx)
        try:
            selection = self.router.route_chat(prompt)
            raw = selection.text if hasattr(selection, "text") else str(selection)
            plan = self._parse_plan(raw, tools)
            return plan
        except Exception:
            return {"tool": "no_tool", "params": {}, "reasoning": "fallback"}

    def _build_selection_prompt(
        self,
        user_msg: str,
        history: list[Any],
        tools: list[RoutingToolView],
        structured_ctx: str,
    ) -> str:
        tool_lines = []
        for tool in tools:
            stub = tool.selection_stub()
            schema = self.chat_schemas.get(tool.runtime_id) or self.chat_schemas.get(
                tool.name
            )
            if schema and schema.get("examples"):
                try:
                    example_json = json.dumps(schema["examples"][0], ensure_ascii=False)
                except Exception:
                    example_json = None
                if example_json:
                    stub = stub + f" example={example_json}"
            tool_lines.append(stub)

        history_txt = []
        for h in history[-4:]:
            if isinstance(h, dict):
                u = h.get("user") or h.get("User") or ""
                a = h.get("assistant") or h.get("Assistant") or ""
                history_txt.append(f"User: {u}\nAssistant: {a}")
            else:
                history_txt.append(str(h))

        return (
            "You are the Brain Researcher chat assistant.\n"
            "You can either answer directly, or call exactly one tool from the list.\n"
            "Prefer `no_tool` when general reasoning suffices.\n"
            "You may use recent context to fill missing parameters, but DO NOT invent dataset IDs or file paths.\n"
            "Tools:\n"
            + "\n".join(tool_lines)
            + '\nPseudo-tool no_tool: {"reason": "why no external tool is needed"}\n'
            + (
                "Conversation history:\n" + "\n".join(history_txt) + "\n"
                if history_txt
                else ""
            )
            + (structured_ctx + "\n" if structured_ctx else "")
            + "Current user question: "
            + user_msg
            + '\nRespond ONLY with JSON: {"tool": "<name or no_tool>", "params": {...}, "reasoning": "..."}'
        )

    def _execute_tool(self, plan: ToolPlan, ctx: dict[str, Any]) -> dict[str, Any]:
        tool_name = plan.leaf_runtime_id or plan.tool
        params = plan.params or {}
        if plan.tool == "no_tool":
            return {"status": "skipped"}
        if self.tool_executor is None:
            return {"status": "not_configured", "tool": tool_name, "params": params}

        runtime_tool = self.registry.get_runtime_tool(tool_name)
        if runtime_tool is None:
            return {"status": "not_found", "tool": tool_name, "params": params}

        # strip op param for family tools
        if plan.is_family and plan.op:
            fam = self.families.get(plan.tool)
            if fam:
                params = {k: v for k, v in params.items() if k != fam.op_param}

        # Prefer ToolExecutor.execute API if available
        if hasattr(self.tool_executor, "execute"):
            try:
                req = ToolExecutionRequest(
                    tool_name=tool_name,
                    parameters=params,
                    context=ctx,
                )
                exec_result = self.tool_executor.execute(req)
                return {
                    "status": exec_result.status,
                    "result": getattr(exec_result, "result", None)
                    or getattr(exec_result, "data", None),
                    "error": exec_result.error,
                    "metadata": exec_result.metadata,
                }
            except Exception as exc:
                return {"status": "error", "error": str(exc)}

        # Fallback: look for a run() method (legacy)
        try:
            result = self.tool_executor.run(tool_name, params)
            return {"status": "ok", "result": result}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _build_summary_prompt(
        self,
        user_msg: str,
        plan: ToolPlan,
        tool_result: dict[str, Any],
        structured_ctx: str,
    ) -> str:
        return (
            "User question: " + user_msg + "\n"
            "Invoked tool: "
            + (plan.tool or "")
            + ", params: "
            + json.dumps(plan.params or {})
            + "\n"
            "Tool return: "
            + json.dumps(tool_result)
            + "\n"
            + (structured_ctx + "\n" if structured_ctx else "")
            + "Please answer the user concisely in English, including key results."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_plan(self, raw: str, tools: list[RoutingToolView]) -> dict[str, Any]:
        plan = json.loads(raw)
        if not isinstance(plan, dict):
            raise ValueError("selection not a dict")
        plan.setdefault("tool", "no_tool")
        plan.setdefault("params", {})

        allowed = {t.runtime_id for t in tools}
        if plan["tool"] not in allowed and plan["tool"] != "no_tool":
            plan["reasoning"] = f"tool {plan['tool']} not in candidates; fallback"
            plan["tool"] = "no_tool"
        return plan

    def _enrich_plan(self, plan_dict: dict[str, Any]) -> ToolPlan:
        tool = plan_dict.get("tool", "no_tool")
        params = plan_dict.get("params", {}) or {}
        reasoning = plan_dict.get("reasoning", "")

        # no_tool straight through
        if tool == "no_tool":
            return ToolPlan(tool="no_tool", params=params, reasoning=reasoning)

        # family?
        fam = self.families.get(tool)
        if fam:
            op_val = params.get(fam.op_param)
            if op_val not in fam.ops:
                return ToolPlan(tool="no_tool", params={}, reasoning="invalid_op")
            leaf_id = fam.ops[op_val]
            return ToolPlan(
                tool=tool,
                params=params,
                reasoning=reasoning,
                is_family=True,
                op=op_val,
                leaf_runtime_id=leaf_id,
            )

        # normal leaf
        return ToolPlan(
            tool=tool, params=params, reasoning=reasoning, leaf_runtime_id=tool
        )

    def _maybe_enrich_coding_plan(
        self, plan: ToolPlan, user_msg: str, ctx: dict[str, Any]
    ) -> ToolPlan:
        """If the selected tool is code_agent, prefetch FS snippets and set defaults."""

        if (
            plan.leaf_runtime_id != _CODE_AGENT_TOOL_ID
            and plan.tool != _CODE_AGENT_TOOL_ID
        ):
            return plan

        params = dict(plan.params or {})
        params.setdefault("instruction", user_msg)

        repo_root = params.get("repo_root") or ctx.get("repo_root") or "."

        # Prefer caller-provided fs_client (for tests) else shared CLI client
        fs_client = ctx.get("fs_client", self._fs_client)

        try:
            snippets = build_fs_context_for_task_sync(
                query=user_msg,
                repo_root=repo_root,
                fs_client=fs_client,
            )
            if snippets:
                params["prefetched_files"] = [s.__dict__ for s in snippets]
                params.setdefault("auto_fs_context", False)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("chat orchestrator FS prefetch failed: %s", exc)

        plan.params = params
        return plan

    def _get_multiagent_router(self):
        if self._multiagent_router_failed:
            return None
        if self._multiagent_router is not None:
            return self._multiagent_router
        try:
            from brain_researcher.services.agent.subagents.router import (
                MultiAgentRouter,
            )

            self._multiagent_router = MultiAgentRouter.from_env()
            return self._multiagent_router
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Multi-agent router unavailable: %s", exc)
            self._multiagent_router_failed = True
            return None

    def _apply_multiagent_plan_gate(
        self,
        *,
        plan: ToolPlan,
        user_msg: str,
        structured_ctx: str,
        ctx: dict[str, Any],
        tools: list[RoutingToolView],
    ) -> tuple[ToolPlan, dict[str, Any] | None]:
        router = self._get_multiagent_router()
        if router is None or not (
            _env_flag("BR_AGENT_MULTIAGENT_ENABLED", False)
            and _env_flag("BR_AGENT_CRITIC_PLAN_GATE", False)
        ):
            return plan, None

        payload = {
            "tool": plan.tool,
            "leaf_runtime_id": plan.leaf_runtime_id,
            "params": plan.params,
            "reasoning": plan.reasoning,
            "is_family": plan.is_family,
            "op": plan.op,
        }
        candidates = [
            {
                "id": view.runtime_id,
                "name": view.name,
                "dangerous": view.dangerous,
            }
            for view in tools
        ]
        verdict = router.review_plan(
            plan=payload,
            user_msg=user_msg,
            structured_ctx=structured_ctx,
            context=ctx,
            tool_candidates=candidates,
        )
        verdict_dict = verdict.to_dict()
        if verdict.decision == "approve":
            return plan, verdict_dict

        if verdict.decision == "block":
            blocked = ToolPlan(
                tool="no_tool",
                params={},
                reasoning=f"critic_block:{verdict.reason or 'blocked'}",
            )
            return blocked, verdict_dict

        patch = verdict.suggested_patch or {}
        revised = ToolPlan(
            tool=plan.tool,
            params=dict(plan.params or {}),
            reasoning=plan.reasoning,
            is_family=plan.is_family,
            op=plan.op,
            leaf_runtime_id=plan.leaf_runtime_id,
        )
        if isinstance(patch.get("params"), dict):
            revised.params = dict(patch["params"])
        if patch.get("tool") == "no_tool":
            revised = ToolPlan(
                tool="no_tool",
                params={},
                reasoning=f"critic_revise:{verdict.reason or 'revise'}",
            )
        return revised, verdict_dict

    # ------------------------------------------------------------------
    # Patch apply helpers
    # ------------------------------------------------------------------

    def _should_apply_patches(self, user_msg: str, thread_id: str) -> bool:
        if thread_id not in self._pending_patches:
            return False
        lowered = user_msg.strip().lower()
        return lowered in {"apply", "apply patches", "yes apply", "apply now"}

    def _apply_pending_patches(self, thread_id: str, ctx: dict[str, Any]) -> ChatReply:
        pending = self._pending_patches.pop(thread_id, None)
        if not pending:
            return ChatReply(answer="No pending patches to apply.")

        try:
            from brain_researcher.services.agent.codegen.workspace import (
                apply_patches_to_repo,
            )

            logs = apply_patches_to_repo(pending["patches"], Path(pending["repo_root"]))
            answer = "Patches applied to repo.\n" + "\n".join(logs)
        except Exception as exc:  # pragma: no cover
            answer = f"Failed to apply patches: {exc}"

        self.memory.append(thread_id, "assistant", answer, {"type": "patch_apply"})
        return ChatReply(answer=answer, tool_calls=[], metadata={"kind": "patch_apply"})

    def _restore_checkpoint_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        checkpoint_id = ctx.get("resume_checkpoint_id") or ctx.get("checkpoint_id")
        if not checkpoint_id:
            return ctx

        try:
            state = self.checkpoints.restore_from_checkpoint(str(checkpoint_id))
        except Exception as exc:  # pragma: no cover - best effort only
            logger.debug("checkpoint restore failed: %s", exc)
            return ctx

        restored_ctx = {}
        variables = getattr(state, "variables", None)
        if isinstance(variables, dict):
            candidate = variables.get("ctx")
            if isinstance(candidate, dict):
                restored_ctx = dict(candidate)

        merged = dict(restored_ctx)
        merged.update(ctx)
        if getattr(state, "execution_id", None):
            merged.setdefault("thread_id", str(state.execution_id))
        merged["checkpoint_id"] = str(checkpoint_id)
        return merged

    @staticmethod
    def _is_generic_clarification_decision(decision: dict[str, Any]) -> bool:
        return str(decision.get("kind") or "").strip() == "generic_clarification"

    @staticmethod
    def _clarification_key(question: str, source: str) -> str:
        return f"{source}:{question.strip()}"

    def _queue_generic_clarifications(
        self,
        ctx: dict[str, Any],
        questions: list[str],
        *,
        source: str,
    ) -> None:
        state = get_generic_clarification_state(ctx)
        answered_keys = {
            str(item).strip()
            for item in (state.get("answered_keys") or [])
            if str(item).strip()
        }
        pending_keys = {
            str(item.get("clarification_key") or "").strip()
            for item in get_pending_decisions(ctx)
            if isinstance(item, dict) and self._is_generic_clarification_decision(item)
        }

        for raw_question in questions:
            question = str(raw_question or "").strip()
            if not question:
                continue
            clarification_key = self._clarification_key(question, source)
            if clarification_key in answered_keys or clarification_key in pending_keys:
                continue
            add_pending_decision(
                ctx,
                {
                    "kind": "generic_clarification",
                    "source": source,
                    "clarification_key": clarification_key,
                    "question": question,
                },
            )
            pending_keys.add(clarification_key)

    @staticmethod
    def _pending_question_text(decision: dict[str, Any]) -> str:
        return str(
            decision.get("question")
            or "I need a quick clarification before proceeding."
        )

    @staticmethod
    def _normalize_resolution_reply(user_msg: str) -> str:
        return " ".join((user_msg or "").strip().lower().replace("_", " ").split())

    def _match_resolution_choice(
        self,
        user_msg: str,
        decision: dict[str, Any],
    ) -> str | None:
        normalized = self._normalize_resolution_reply(user_msg)
        if not normalized:
            return None

        options = [
            str(option).strip() for option in (decision.get("options") or []) if option
        ]
        normalized_options = {
            self._normalize_resolution_reply(option): option for option in options
        }
        if normalized in normalized_options:
            return normalized_options[normalized]

        if normalized in {"default", "recommended", "use recommended"}:
            recommended = decision.get("recommended_choice")
            return str(recommended) if recommended else None

        if any(phrase in normalized for phrase in ("local nilearn", "use nilearn")):
            return "local_nilearn"
        if any(
            phrase in normalized
            for phrase in ("search more", "keep searching", "search again")
        ):
            return "search_more"

        return None

    def _apply_resolution_decision_reply(
        self,
        user_msg: str,
        ctx: dict[str, Any],
        thread_id: str,
    ) -> dict[str, str] | None:
        pending_decisions = get_pending_decisions(ctx)
        if not pending_decisions:
            return None

        first = pending_decisions[0]
        if self._is_generic_clarification_decision(first):
            consumed = pop_pending_decision(ctx) or first
            record_generic_clarification_answer(ctx, consumed, user_msg)
            clarification_payload = {
                "clarification_key": str(
                    consumed.get("clarification_key") or ""
                ).strip(),
                "question": str(consumed.get("question") or "").strip(),
                "answer": str(user_msg or "").strip(),
            }
            ctx["generic_clarification_applied"] = clarification_payload
            return clarification_payload

        capability_intent = str(first.get("capability_intent") or "").strip()
        if not capability_intent:
            return None

        choice = self._match_resolution_choice(user_msg, first)
        if not choice:
            return None

        if choice == "search_more":
            clear_pending_decisions(ctx, capability_intent)
            ctx["_resolution_force_capability_lookup"] = capability_intent
        else:
            set_override(ctx, capability_intent, choice)

        decision_payload = {
            "capability_intent": capability_intent,
            "choice": choice,
        }
        ctx["resolution_decision_applied"] = decision_payload

        try:
            self.memory.append(
                thread_id,
                "assistant",
                f"Resolution choice applied: {capability_intent} -> {choice}",
                {"type": "resolution_choice", **decision_payload},
            )
        except Exception as exc:  # pragma: no cover - best effort only
            logger.debug("resolution decision memory append failed: %s", exc)

        return decision_payload

    def _build_final_reply(
        self,
        user_msg: str,
        plan: ToolPlan,
        tool_result: dict[str, Any],
        structured_ctx: str,
        thread_id: str,
        ctx: dict[str, Any],
    ) -> ChatReply:
        # Special-case code agent: render structured result without another LLM hop
        if (
            plan.tool == _CODE_AGENT_TOOL_ID
            or plan.leaf_runtime_id == _CODE_AGENT_TOOL_ID
        ):
            res_body = tool_result.get("result") or tool_result.get("data") or {}
            if res_body.get("summary"):
                rendered = res_body["summary"]
            else:
                rendered = render_result_for_chat(
                    CodegenResult(
                        status=res_body.get("status", "unknown"),
                        iterations=res_body.get("iterations", 1),
                        response_text=res_body.get("response", ""),
                        patches=res_body.get("patches") or [],
                        files_touched=res_body.get("files_touched") or [],
                        exec_result=ExecutionResult(
                            success=(
                                res_body.get("exec_stdout") is not None
                                and not res_body.get("exec_stderr")
                            ),
                            stdout=res_body.get("exec_stdout") or "",
                            stderr=res_body.get("exec_stderr") or "",
                            exit_code=None,
                        )
                        if res_body.get("exec_stdout") is not None
                        or res_body.get("exec_stderr") is not None
                        else None,
                        errors=tool_result.get("error"),
                        provider=res_body.get("provider"),
                        model=res_body.get("model"),
                        usage=res_body.get("usage") or {},
                        fallback_reason=res_body.get("fallback_reason"),
                    )
                )
            reply = ChatReply(
                answer=rendered,
                tool_calls=[{"plan": plan.__dict__, "result": tool_result}],
                metadata={
                    "type": "tool_summary",
                    "tool": plan.tool,
                    "checkpoint_id": ctx.get("checkpoint_id"),
                },
            )
            # Cache patches for optional apply
            if res_body.get("requires_confirmation") and res_body.get("patches"):
                self._pending_patches[thread_id] = {
                    "patches": res_body["patches"],
                    "repo_root": ctx.get("repo_root") or os.getcwd(),
                }
                reply.answer += "\n\nPatch ready. Reply with 'apply patches' to write to repo (destructive)."
            self.memory.append(
                thread_id,
                "assistant",
                reply.answer,
                {"type": "tool_summary", "tool": plan.tool},
            )
            return reply

        # Default path: use LLM summarizer
        summary_prompt = self._build_summary_prompt(
            user_msg, plan, tool_result, structured_ctx
        )
        result = self.router.route_chat(summary_prompt)
        meta_obj = getattr(result, "metadata", None)
        metadata = meta_obj.__dict__ if meta_obj is not None else None
        reply = ChatReply(
            answer=result.text,
            tool_calls=[{"plan": plan.__dict__, "result": tool_result}],
            metadata=metadata,
        )
        if ctx.get("checkpoint_id"):
            reply.metadata = reply.metadata or {}
            reply.metadata.setdefault("checkpoint_id", ctx.get("checkpoint_id"))
        self.memory.append(
            thread_id,
            "assistant",
            result.text,
            {"type": "tool_summary", "tool": plan.tool},
        )
        return reply

    # ------------------------------------------------------------------
    # Context, clarification, recovery
    # ------------------------------------------------------------------

    def _build_structured_context(
        self, user_msg: str, history: list[Any], ctx: dict[str, Any], thread_id: str
    ) -> str:
        lines: list[str] = []
        generic_clarification_state = get_generic_clarification_state(ctx)
        answered_keys = {
            str(item).strip()
            for item in (generic_clarification_state.get("answered_keys") or [])
            if str(item).strip()
        }
        if ctx.get("query_understanding"):
            qur = ctx["query_understanding"]
            lines.append("# Structured query context")
            if getattr(qur, "resolved_datasets", None):
                ds_labels = [
                    getattr(ds, "dataset_id", "") for ds in qur.resolved_datasets
                ]
                lines.append(f"datasets: {', '.join(ds_labels)}")
            if getattr(qur, "kg_nodes", None):
                lines.append(f"kg_nodes: {len(qur.kg_nodes)} candidates")
            if getattr(qur, "ambiguities", None):
                unresolved_ambiguities = [
                    ambiguity
                    for ambiguity in list(getattr(qur, "ambiguities", []) or [])
                    if self._clarification_key(str(ambiguity), "query_understanding")
                    not in answered_keys
                ]
                if unresolved_ambiguities:
                    lines.append(
                        "ambiguities: " + "; ".join(unresolved_ambiguities[:3])
                    )

        # Track K+: Include knowledge evidence context
        knowledge_evidence = ctx.get("knowledge_evidence")
        if knowledge_evidence:
            lines.append("# Knowledge evidence")
            lines.append(f"confidence: {knowledge_evidence.confidence:.2f}")
            lines.append(f"total_items: {len(knowledge_evidence.items)}")
            # Summarize top evidence items
            top_items = knowledge_evidence.get_top_items(5)
            for item in top_items:
                lines.append(f"  [{item.source_type.value}] {item.label[:50]}")

        if ctx.get("pipeline_state"):
            lines.append("# Pipeline state")
            lines.append(json.dumps(ctx["pipeline_state"], default=str)[:500])
        resolution_choice = ctx.get("resolution_decision_applied")
        if isinstance(resolution_choice, dict):
            lines.append("# Resolution decision")
            lines.append(json.dumps(resolution_choice, default=str))
        resolution_overrides = get_overrides(ctx)
        if resolution_overrides:
            lines.append("# Resolution overrides")
            lines.append(json.dumps(resolution_overrides, sort_keys=True))
        clarification_answers = [
            item
            for item in (generic_clarification_state.get("answers") or [])
            if isinstance(item, dict)
        ]
        if clarification_answers:
            lines.append("# Clarification answers")
            for item in clarification_answers[-3:]:
                question = str(item.get("question") or "").strip()
                answer = str(item.get("answer") or "").strip()
                if question or answer:
                    lines.append(f"Q: {question or 'clarification'}")
                    lines.append(f"A: {answer or '(empty)'}")
        memory_snippet = self.memory.render_recent(thread_id, limit=4)
        if memory_snippet:
            lines.append(memory_snippet)
        recent_decisions = []
        for h in reversed(history[-3:]):
            if isinstance(h, dict) and "tool_calls" in h:
                recent_decisions.append(str(h))
        if recent_decisions:
            lines.append("# Recent decisions")
            lines.extend(recent_decisions)
        if not lines:
            return ""
        return "\n".join(lines)

    async def _gather_knowledge_evidence_async(
        self, user_msg: str, ctx: dict[str, Any], timeout_s: float = 0.6
    ) -> EvidenceBundle | None:
        """Async helper to gather knowledge evidence with a tight timeout.

        Uses only fast sources for chat responsiveness.
        """

        if not self._enable_knowledge_layer:
            return None

        if self._knowledge_aggregator is None:
            from brain_researcher.services.agent.knowledge import EvidenceAggregator

            account_id = None
            if isinstance(ctx, dict):
                account_id = ctx.get("user_id") or ctx.get("account_id")

            self._knowledge_aggregator = EvidenceAggregator(
                use_shared_cache=True,
                account_id=account_id or "test-account",
                memory_store=self._knowledge_memory_store,
            )
        else:
            # Update account id on the shared aggregator to avoid cross-user cache bleed
            if isinstance(ctx, dict):
                account_id = (
                    ctx.get("user_id") or ctx.get("account_id") or "test-account"
                )
                self._knowledge_aggregator._account_id = account_id  # type: ignore[attr-defined]

        try:
            dataset_hints = []
            if isinstance(ctx, dict):
                qur = ctx.get("query_understanding")
                if qur is not None:
                    resolved = getattr(qur, "resolved_datasets", None) or (
                        qur.get("resolved_datasets") if isinstance(qur, dict) else []
                    )
                    candidates = getattr(qur, "candidate_datasets", None) or (
                        qur.get("candidate_datasets") if isinstance(qur, dict) else []
                    )
                    dataset_hints = [*resolved, *candidates]

            return await asyncio.wait_for(
                self._knowledge_aggregator.gather_evidence(
                    query=user_msg,
                    limit=10,
                    timeout=timeout_s,
                    dataset_hints=dataset_hints,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.debug("knowledge gathering timed out after %.1fs", timeout_s)
            return None
        except Exception as exc:
            logger.debug("knowledge gathering failed: %s", exc)
            return None
        finally:
            try:
                if self._knowledge_aggregator:
                    account_id = (
                        ctx.get("user_id") or ctx.get("account_id")
                        if isinstance(ctx, dict)
                        else None
                    )
                    self._knowledge_aggregator.export_metrics(
                        self._metrics, account_id=account_id
                    )

                    # Also push to global monitoring integration for Prometheus export
                    try:
                        from brain_researcher.services.agent.monitoring_integration import (
                            get_monitoring_integration,
                        )

                        mi = get_monitoring_integration()
                        m = self._knowledge_aggregator.get_metrics()
                        mi.metrics_collector.record_knowledge_cache_metrics(
                            l1_hits=m.get("l1_hits", 0),
                            l1_misses=m.get("l1_misses", 0),
                            shared_hits=m.get("shared_hits", 0),
                            shared_sets=m.get("shared_sets", 0),
                            account_id=account_id or "unknown",
                        )
                    except Exception:
                        logger.debug("global monitoring export failed", exc_info=True)
            except Exception:
                logger.debug("knowledge metrics export failed", exc_info=True)

    def _gather_knowledge_evidence(
        self, user_msg: str, ctx: dict[str, Any]
    ) -> EvidenceBundle | None:
        """Sync wrapper for async evidence gather with safeguards."""

        if not self._enable_knowledge_layer:
            return None

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    self._gather_knowledge_evidence_async(user_msg, ctx), loop
                )
                return fut.result(timeout=0.7)  # Slightly above inner timeout
            else:
                return loop.run_until_complete(
                    self._gather_knowledge_evidence_async(user_msg, ctx)
                )
        except Exception as exc:
            logger.debug("knowledge gathering wrapper failed: %s", exc)
            return None

    def _maybe_clarify(
        self, user_msg: str, plan: ToolPlan, ctx: dict[str, Any], structured_ctx: str
    ) -> ChatReply | None:
        pending_decisions = get_pending_decisions(ctx)
        if pending_decisions:
            first = pending_decisions[0]
            question = self._pending_question_text(first)
            return ChatReply(
                answer=question,
                tool_calls=[],
                metadata={
                    "type": "clarification",
                    "questions": [question],
                    "pending_decision": first,
                },
            )

        qur = ctx.get("query_understanding") if isinstance(ctx, dict) else None
        ambiguities: list[str] = list(getattr(qur, "ambiguities", []) or [])
        if ambiguities:
            self._queue_generic_clarifications(
                ctx,
                ambiguities[:3],
                source="query_understanding",
            )
        info_gap = self._detect_insufficient_info(plan, structured_ctx, ctx)
        if info_gap:
            self._queue_generic_clarifications(
                ctx,
                [info_gap],
                source="info_gap",
            )
        pending_decisions = get_pending_decisions(ctx)
        if pending_decisions:
            first = pending_decisions[0]
            question = self._pending_question_text(first)
            return ChatReply(
                answer=question,
                tool_calls=[],
                metadata={
                    "type": "clarification",
                    "questions": [question],
                    "pending_decision": first,
                },
            )
        if not ambiguities and not info_gap:
            return None
        return None

    @staticmethod
    def _detect_insufficient_info(
        plan: ToolPlan,
        structured_ctx: str,
        ctx: dict[str, Any] | None = None,
    ) -> str | None:
        clarification_state = get_generic_clarification_state(ctx)
        answered_keys = {
            str(item).strip()
            for item in (clarification_state.get("answered_keys") or [])
            if str(item).strip()
        }
        if plan.tool == "no_tool" and "info" in (plan.reasoning or "").lower():
            question = "What dataset or subject should I operate on?"
            if f"info_gap:{question}" not in answered_keys:
                return question
            return None
        if "dataset" not in (structured_ctx or "") and plan.tool != "no_tool":
            question = "Which dataset ID or path should this tool use?"
            if f"info_gap:{question}" not in answered_keys:
                return question
            return None
        return None

    def _record_checkpoint(
        self, thread_id: str, plan: ToolPlan, history: list[Any], ctx: dict[str, Any]
    ) -> str | None:
        try:
            state = ExecutionState(
                execution_id=thread_id,
                current_step=len(history),
                completed_steps=[],
                step_results={},
                variables={"plan": plan.__dict__, "ctx": ctx},
                timestamp=time.time(),
                metadata={"kind": "chat_orchestrator"},
            )
            return self.checkpoints.create_checkpoint(state)
        except Exception as exc:  # pragma: no cover - checkpointing is best effort
            logger.debug("checkpoint create failed: %s", exc)
            return None

    def _recover_from_error(
        self,
        plan: ToolPlan,
        tool_result: dict[str, Any],
        user_msg: str,
        ctx: dict[str, Any],
        history: list[Any],
    ) -> dict[str, Any]:
        if not self.error_recovery:
            return tool_result

        exec_ctx = {
            "tool_name": plan.leaf_runtime_id or plan.tool,
            "parameters": plan.params,
            "history": history,
            "original_query": user_msg,
            "checkpoint_id": ctx.get("checkpoint_id"),
            "reason": tool_result.get("error") or tool_result.get("status"),
        }

        recovery_result = asyncio.run(
            self.error_recovery.handle_error_with_recovery(
                error=Exception(str(tool_result)),
                execution_context=exec_ctx,
                recovery_options={"max_attempts": self.max_recovery_attempts},
            )
        )

        if recovery_result.get("clarification_needed"):
            return recovery_result

        if recovery_result.get("success"):
            result_payload = recovery_result.get("result") or recovery_result
            return {
                "status": "recovered",
                "result": result_payload,
                "recovery_actions": recovery_result.get("actions_taken"),
            }

        return tool_result

    # ------------------------------------------------------------------
    # MCP self-test quick path
    # ------------------------------------------------------------------

    def _detect_mcp_selftest_mode(self, query: str, ctx: dict[str, Any]) -> str | None:
        if not _env_flag("BR_AGENT_MCP_SELFTEST_AUTOROUTE", True):
            return None
        explicit_mode = str(ctx.get("mcp_selftest_mode") or "").strip().lower()
        if explicit_mode in {"quick", "active"}:
            return explicit_mode
        if bool(ctx.get("mcp_selftest")):
            return "active"

        q = (query or "").strip().lower()
        if not q:
            return None

        if "mcp" not in q:
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

    def _handle_mcp_selftest(
        self,
        *,
        user_msg: str,
        ctx: dict[str, Any],
        thread_id: str,
        mode: str,
    ) -> ChatReply | None:
        try:
            from brain_researcher.services.shared.mcp_runtime_bridge import (
                MCPRuntimeUnavailable,
                call_mcp_tool,
            )

            include_kg = bool(ctx.get("mcp_selftest_include_kg", True))
            include_container = bool(ctx.get("mcp_selftest_include_container", True))
            include_script = bool(ctx.get("mcp_selftest_include_script", True))
            include_inventory = bool(ctx.get("mcp_selftest_include_inventory", True))
            inventory_limit = int(ctx.get("mcp_selftest_inventory_limit", 12))
            strict = bool(ctx.get("mcp_selftest_strict", False))
            kg_query = str(ctx.get("mcp_selftest_kg_query") or "brain")

            payload = call_mcp_tool(
                "system_self_test",
                mode=mode,
                include_kg=include_kg,
                include_container=include_container,
                include_script=include_script,
                include_inventory=include_inventory,
                inventory_limit=inventory_limit,
                kg_query=kg_query,
                strict=strict,
            )
        except MCPRuntimeUnavailable as exc:
            logger.warning("MCP self-test provider unavailable: %s", exc)
            return None
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

        summary_text = str(payload.get("summary_text") or "MCP self-test completed.")
        recommendations = payload.get("recommendations") or []
        if isinstance(recommendations, list) and recommendations:
            summary_text += "\nRecommendations:\n" + "\n".join(
                f"- {str(item)}" for item in recommendations[:3]
            )

        reply = ChatReply(
            answer=summary_text,
            tool_calls=[
                {
                    "plan": {
                        "tool": "mcp.system_self_test",
                        "params": {
                            "mode": mode,
                            "include_kg": include_kg,
                            "include_container": include_container,
                            "include_script": include_script,
                            "include_inventory": include_inventory,
                            "inventory_limit": inventory_limit,
                            "kg_query": kg_query,
                            "strict": strict,
                        },
                        "reasoning": "detected mcp self-test intent",
                    },
                    "result": payload,
                }
            ],
            metadata={
                "type": "mcp_selftest",
                "mode": mode,
                "overall": payload.get("overall"),
                "ok": payload.get("ok"),
                "counts": payload.get("counts"),
            },
        )
        self.memory.append(
            thread_id,
            "assistant",
            reply.answer,
            {
                "type": "mcp_selftest",
                "mode": mode,
                "overall": payload.get("overall"),
            },
        )
        return reply

    # ------------------------------------------------------------------
    # Coding-first helpers (gemini_cli + coder fallback)
    # ------------------------------------------------------------------

    def _is_coding_query(self, query: str, ctx: dict[str, Any]) -> bool:
        """Heuristic or explicit flag for coding tasks."""
        if ctx.get("tools", {}).get("mode") == "coding":
            return True
        q = query.lower()
        coding_keywords = [
            ".py",
            "python",
            "bash",
            "shell",
            "script",
            "code",
            "function",
            "class",
            "refactor",
            "test",
            "pytest",
            "json schema",
            "regex",
            # repo-edit hints
            "patch",
            "diff",
            "git",
            "apply patch",
            "modify",
            "fix lint",
        ]
        return any(k in q for k in coding_keywords)

    def _llm_coder_fallback(
        self, user_msg: str, ctx: dict[str, Any] | None = None
    ) -> ChatReply:
        """Pure LLM coding response without tools."""
        ctx = ctx or {}
        if isinstance(ctx.get("repair_context"), dict):
            coder_system = (
                "You are a neuroimaging repair assistant inside Studio. You have no external tools. "
                "The user is repairing a failed validation run. Prefer a brief diagnosis, the smallest in-Studio fix, "
                "and a re-validation recommendation. Do not imply that you already executed anything. "
                "If the prompt asks for a fenced json block, follow that contract exactly. "
                "Only suggest external IDE handoff when the issue requires environment, dependency, or external code changes."
            )
        else:
            coder_system = (
                "You are a coding assistant. You have no external tools. "
                "Prefer runnable local code, patch suggestions, and shell commands the user can run locally. "
                "Do not imply that you already executed anything. "
                "Return runnable code first (in fenced code blocks), then a brief explanation."
            )
        # Route with an explicit system prefix; reuse router but avoid tool schemas.
        result = self.router.route_chat(
            f"{coder_system}\n\nUser: {user_msg}",
            task_type="code",
        )
        return ChatReply(
            answer=result.text, tool_calls=[], metadata={"type": "coding_llm"}
        )

    def _general_llm_reply(
        self,
        user_msg: str,
        history: list[Any],
        ctx: dict[str, Any],
        thread_id: str,
    ) -> ChatReply:
        """LLM-only reply with tools disabled (fallback/general mode)."""
        system_prompt = (
            "You are a helpful assistant. You have no external tools. "
            "Answer concisely and helpfully."
        )
        prompt = f"{system_prompt}\n\nUser: {user_msg}"
        result = self.router.route_chat(prompt)
        self.memory.append(thread_id, "assistant", result.text, {"type": "direct"})
        return ChatReply(
            answer=result.text, tool_calls=[], metadata={"type": "llm_only"}
        )

    def _handle_coding_chat(
        self,
        user_msg: str,
        history: list[Any],
        ctx: dict[str, Any],
        thread_id: str,
    ) -> ChatReply | None:
        """Coding branch.

        Strategy:
        1) explain_only always uses the pure LLM coding path.
        2) Local-first is the default for coding requests, including repo-edit prompts.
        3) CodeOrchestrator is only used when the caller explicitly opts in.
        """

        force_agent = bool(ctx.get("force_code_agent"))
        explain_only = bool(ctx.get("explain_only"))

        if explain_only:
            return self._llm_coder_fallback(user_msg, ctx)

        if self._should_use_code_agent_escape_hatch(ctx):
            return self._delegate_to_code_orchestrator(user_msg, ctx, thread_id)

        if force_agent:
            logger.info(
                "Ignoring force_code_agent request because the BR_ENABLE_CODE_AGENT_TOOL "
                "escape hatch is not enabled"
            )

        return self._llm_coder_fallback(user_msg, ctx)

    @staticmethod
    def _should_use_code_agent_escape_hatch(ctx: dict[str, Any] | None) -> bool:
        """Return True only for the explicit feature-flagged code-agent escape hatch.

        This is the sole coding-mode path that bypasses the normal local-first
        planner/allowlist tool surfaces. It requires both a caller opt-in
        (``force_code_agent``) and a service-level feature flag
        (``BR_ENABLE_CODE_AGENT_TOOL``).
        """

        if not isinstance(ctx, dict):
            return False
        if bool(ctx.get("explain_only")):
            return False
        if not bool(ctx.get("force_code_agent")):
            return False
        return _env_flag("BR_ENABLE_CODE_AGENT_TOOL", default=False)

    def _delegate_to_code_orchestrator(
        self,
        user_msg: str,
        ctx: dict[str, Any],
        thread_id: str,
    ) -> ChatReply:
        """Delegate coding request to dedicated CodeOrchestrator.

        This is an explicit opt-in escape hatch. It completely bypasses the
        general tool routing and uses the CodeOrchestrator's minimal tool
        registry and inner loop.
        """
        # Record checkpoint for logging/recovery
        plan = ToolPlan(
            tool=_CODE_AGENT_TOOL_ID,
            params={"instruction": user_msg},
            reasoning="coding request via CodeOrchestrator",
            leaf_runtime_id=_CODE_AGENT_TOOL_ID,
        )
        checkpoint_id = self._record_checkpoint(thread_id, plan, [], ctx)
        ctx = {**ctx, "checkpoint_id": checkpoint_id}

        try:
            # Get the shared CodeOrchestrator instance
            code_orchestrator = get_code_orchestrator()

            # Run the coding task
            result: CodeResult = code_orchestrator.run_task(
                instruction=user_msg,
                ctx=ctx,
                thread_id=thread_id,
                user_id=ctx.get("user_id"),
            )

            # Build reply from CodeResult
            reply = ChatReply(
                answer=result.answer,
                tool_calls=[
                    {
                        "plan": plan.__dict__,
                        "result": {
                            "status": result.status,
                            "patches": result.patches,
                            "files_touched": result.files_touched,
                            "iterations": result.iterations,
                            "test_status": result.test_status,
                            "requires_confirmation": result.requires_confirmation,
                        },
                    }
                ],
                metadata={
                    "type": "coding_tool",
                    "tool": _CODE_AGENT_TOOL_ID,
                    "status": result.status,
                    "checkpoint_id": checkpoint_id,
                    **result.metadata,
                },
            )

            # Persist to memory
            self.memory.append(
                thread_id, "assistant", reply.answer, {"type": "coding_tool"}
            )
            return reply

        except Exception as e:
            logger.warning("CodeOrchestrator failed, fallback to LLM: %s", e)
            return self._llm_coder_fallback(user_msg, ctx)

    @staticmethod
    def _looks_like_repo_edit(text: str) -> bool:
        q = text.lower()
        keywords = [
            "apply patch",
            "diff",
            "git",
            "repo",
            "tests/",
            "test/",
            ".py",
            "refactor",
            "rename",
            "modify",
            "fix lint",
        ]
        return any(k in q for k in keywords)

    # ------------------------------------------------------------------
    # Pipeline-first helpers (Phase 6)
    # ------------------------------------------------------------------

    def _load_workflow_index(self) -> dict[str, dict[str, Any]]:
        """Load orchestration workflows for workflow-first matching."""

        try:
            from brain_researcher.services.tools.catalog_loader import (
                load_orchestration_workflows,
            )

            allowed = set(load_orchestration_workflows())
        except Exception:
            allowed = set()

        workflow_path = resolve_from_config("workflows", "workflow_catalog.yaml")
        if not workflow_path.exists():
            return {}

        try:
            data = yaml.safe_load(workflow_path.read_text()) or {}
        except Exception as exc:
            logger.debug(
                "Failed to load workflow catalog for workflow-first routing: %s", exc
            )
            return {}

        workflows = data.get("workflows") if isinstance(data, dict) else None
        if not isinstance(workflows, list):
            return {}

        index: dict[str, dict[str, Any]] = {}
        for entry in workflows:
            if not isinstance(entry, dict):
                continue
            workflow_id = str(entry.get("id") or "").strip()
            if not workflow_id:
                continue
            if allowed and workflow_id not in allowed:
                continue
            text_parts = [
                workflow_id,
                str(entry.get("description") or ""),
                str(entry.get("impl") or ""),
                str(entry.get("stage") or ""),
                " ".join(str(m) for m in (entry.get("modalities") or [])),
            ]
            text = " ".join(text_parts).lower()
            tokens = {t for t in re.split(r"[^a-z0-9]+", text) if len(t) >= 3}
            index[workflow_id] = {
                "id": workflow_id,
                "description": str(
                    entry.get("description") or entry.get("impl") or workflow_id
                ),
                "tokens": tokens,
            }
        return index

    def _match_declared_workflow(self, query: str) -> str | None:
        """Return workflow ID when the query clearly asks for a known workflow."""

        if not self._workflow_index:
            return None
        q = (query or "").strip().lower()
        if not q:
            return None

        # Exact ID mention wins immediately.
        for workflow_id in self._workflow_index.keys():
            if workflow_id.lower() in q:
                return workflow_id

        action_cues = {
            "run",
            "execute",
            "workflow",
            "pipeline",
            "preprocess",
            "glm",
            "connectome",
            "decoding",
            "qc",
        }
        q_tokens = {t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 3}
        if not (q_tokens & action_cues):
            return None

        # Lightweight lexical match over workflow descriptions.
        best_id: str | None = None
        best_score = 0
        for workflow_id, payload in self._workflow_index.items():
            tokens = payload.get("tokens") or set()
            if not tokens:
                continue
            score = len(q_tokens & set(tokens))
            if score > best_score:
                best_score = score
                best_id = workflow_id
        return best_id if best_score >= 2 else None

    def _detect_imaging_domain(self, query: str) -> str | None:
        """Detect imaging domain from query text for pipeline routing."""
        q = query.lower()

        # Avoid pipeline-first for purely explanatory questions.
        explanation_cues = [
            "explain",
            "what is",
            "what's",
            "define",
            "definition",
            "overview",
            "introduction",
            "summary",
            "summarize",
            "describe",
            "tell me about",
            "difference between",
            "compare",
        ]
        action_cues = [
            "run",
            "execute",
            "preprocess",
            "process",
            "analyze",
            "analysis",
            "fit",
            "estimate",
            "compute",
            "apply",
            "build",
            "pipeline",
            "workflow",
            "register",
            "normalize",
            "segment",
            "extract",
        ]
        if any(cue in q for cue in explanation_cues) and not any(
            cue in q for cue in action_cues
        ):
            return None

        # Modality detection
        if any(k in q for k in ["fmri", "bold", "functional"]):
            return "fmri"
        if any(k in q for k in ["dmri", "diffusion", "dti", "tractography"]):
            return "dmri"
        if any(k in q for k in ["t1", "t2", "structural", "smri"]):
            return "smri"

        # General imaging keywords / registration synonyms
        imaging_keywords = [
            "preprocess",
            "pipeline",
            "workflow",
            "registration",
            "register",
            "normalize",
            "standard space",
            "mni",
            "warp",
            "skull",
            "strip",
            "brain extraction",
            "bet",
            "ica",
            "fix",
            "denois",
            "glm",
            "first level",
            "cluster",
            "clustsim",
        ]
        if any(k in q for k in imaging_keywords):
            return "imaging"

        return None

    async def _execute_pipeline_steps(
        self,
        steps: list[WorkflowStep],
        ctx: dict[str, Any],
        preview: bool = True,
    ) -> list[dict[str, Any]]:
        """Execute pipeline steps (preview mode by default for safety)."""
        from brain_researcher.services.tools.executor import execute_tool

        work_dir = ctx.get("work_dir")
        output_dir = ctx.get("output_dir")

        results = []
        for step in steps:
            result = execute_tool(
                step.tool_name,
                step.tool_args or {},
                work_dir=work_dir,
                output_dir=output_dir,
                preview=preview,
            )
            results.append(
                {
                    "step_id": step.step_id,
                    "tool": step.tool_name,
                    "status": result.status,
                    "data": result.data if result.status == "success" else None,
                    "error": result.error,
                }
            )

            # Stop on error unless in preview mode
            if not preview and result.status != "success":
                break

        return results

    def _build_pipeline_summary_prompt(
        self,
        user_msg: str,
        steps: list[WorkflowStep],
        step_results: list[dict[str, Any]],
    ) -> str:
        """Build LLM prompt to summarize pipeline execution."""
        steps_desc = "\n".join(
            [f"- {s.step_id}: {s.tool_name} ({s.description})" for s in steps]
        )

        results_desc = "\n".join(
            [
                f"- {r['step_id']}: {r['status']}"
                + (f" - {r.get('error', '')}" if r.get("error") else "")
                for r in step_results
            ]
        )

        return f"""User request: {user_msg}

Pipeline execution (preview mode):

Steps planned:
{steps_desc}

Results:
{results_desc}

Summarize the pipeline plan for the user. Explain what each step does and whether it would succeed.
If preview mode, explain that the user can run with `--execute` to actually perform the analysis."""

    def _build_pipeline_fallback_reply(
        self,
        user_msg: str,
        reason: str,
    ) -> ChatReply:
        """
        Build a graceful fallback ChatReply when pipeline execution cannot proceed
        (e.g., KG/Neo4j down or no pipeline match). Uses LLM to give a manual
        checklist so the user still gets actionable guidance.
        """
        try:
            prompt = (
                "Our pipeline planner / knowledge graph is temporarily unavailable "
                f"(reason: {reason}).\n"
                f"User request: {user_msg}\n\n"
                "Provide a concise, actionable checklist (3-6 steps) the user can follow. "
                "Focus on the key processing stages, mention required inputs, and note that "
                "execution was not run."
            )
            summary = self.router.route_chat(prompt)
            text = summary.text
        except Exception:
            text = (
                "Pipeline planner is unavailable right now. "
                "Suggested manual steps: brain extraction → registration/normalization → QC. "
                "Execution was not run."
            )

        return ChatReply(
            answer=text,
            tool_calls=[],
            metadata={
                "type": "pipeline_fallback",
                "mode": "llm_only",
                "reason": reason,
            },
        )

    def _try_pipeline_execution(
        self,
        user_msg: str,
        domain: str | None,
        ctx: dict[str, Any],
        thread_id: str,
    ) -> ChatReply | None:
        """Attempt pipeline-first execution. Returns None if no pipeline matches."""
        try:
            preferred_workflow = str(
                (ctx or {}).get("preferred_workflow_id") or ""
            ).strip()
            if preferred_workflow:
                preview = bool(ctx.get("pipeline_preview", True))
                params = (
                    ctx.get("workflow_params")
                    if isinstance(ctx.get("workflow_params"), dict)
                    else {}
                )
                plan = {
                    "steps": [
                        {
                            "step_id": "s1",
                            "tool": preferred_workflow,
                            "params": params,
                        }
                    ]
                }

                from brain_researcher.services.shared.mcp_runtime_bridge import (
                    call_mcp_tool,
                )

                validated = call_mcp_tool("pipeline_plan_validate", plan=plan)
                if not validated.get("ok"):
                    return self._build_pipeline_fallback_reply(
                        user_msg,
                        f"workflow_plan_invalid:{preferred_workflow}",
                    )
                submitted = call_mcp_tool(
                    "pipeline_execute",
                    plan=plan,
                    dry_run=preview,
                )
                if not submitted.get("ok"):
                    return self._build_pipeline_fallback_reply(
                        user_msg,
                        f"workflow_submit_failed:{preferred_workflow}",
                    )
                run_id = str(submitted.get("run_id") or "")
                mode = "preview" if preview else "execute"
                answer = (
                    f"Matched workflow `{preferred_workflow}` and submitted a {mode} run"
                    + (f" (`{run_id}`)." if run_id else ".")
                )
                reply = ChatReply(
                    answer=answer,
                    tool_calls=[
                        {
                            "workflow_id": preferred_workflow,
                            "plan": plan,
                            "submission": submitted,
                        }
                    ],
                    metadata={
                        "type": "workflow_pipeline",
                        "workflow_id": preferred_workflow,
                        "mode": mode,
                        "run_id": run_id,
                    },
                )
                self.memory.append(
                    thread_id,
                    "assistant",
                    reply.answer,
                    {"type": "workflow_pipeline", "workflow_id": preferred_workflow},
                )
                return reply

            # ------------------------------------------------------------------
            # Orchestrator-level viz fast-path: if stat_map is provided in ctx,
            # build a single-step plan and return preview without LLM summary.
            # ------------------------------------------------------------------
            stat_map = (ctx or {}).get("stat_map") or (ctx or {}).get("stat_map_path")
            if stat_map:
                display_mode = (ctx or {}).get("display_mode", "ortho")
                preview_flag = ctx.get("pipeline_preview", True)

                steps = [
                    WorkflowStep(
                        step_id="step_1",
                        step_number=1,
                        description="Visualize statistical map",
                        tool_name="viz_stat_maps",
                        tool_args={
                            "stat_map": stat_map,
                            "display_mode": display_mode,
                            "preview": True,
                        },
                    )
                ]

                step_results = asyncio.run(
                    self._execute_pipeline_steps(
                        steps,
                        ctx,
                        preview=preview_flag,
                    )
                )

                reply = ChatReply(
                    answer="Preview only (no LLM summary)",
                    tool_calls=[
                        {
                            "pipeline_steps": [s.__dict__ for s in steps],
                            "results": step_results,
                        }
                    ],
                    metadata={
                        "type": "pipeline",
                        "mode": "preview" if preview_flag else "execute",
                    },
                )
                self.memory.append(
                    thread_id, "assistant", reply.answer, {"type": "pipeline"}
                )
                return reply

            preview = ctx.get("pipeline_preview", True)
            ctx.get("work_dir")
            ctx.get("output_dir")

            # Construct intent for planning engine (public API)
            intent = QueryIntent(
                primary_intent="analyze",
                domain=domain or "imaging",
                entities={"query": user_msg},
            )

            # Use a real LLM-backed planner; the chat router is not an LLM instance.
            planner = PlanningEngine()

            # Public plan generation (includes heuristics + parameter inference)
            plan = asyncio.run(
                planner.generate_plan(
                    query=user_msg,
                    intent=intent,
                    context=ctx,
                )
            )

            if not plan or not plan.steps:
                return self._build_pipeline_fallback_reply(
                    user_msg, "no pipeline steps found"
                )

            logger.info(
                "Pipeline branch triggered",
                extra={
                    "thread_id": thread_id,
                    "domain": intent.domain,
                    "query": user_msg,
                    "steps": [s.tool_name for s in plan.steps],
                },
            )

            # Execute (preview by default)
            step_results = asyncio.run(
                self._execute_pipeline_steps(
                    plan.steps,
                    ctx,
                    preview=preview,
                )
            )

            # Short-circuit: if preview/skip_summary requested, return tool results directly
            skip_summary = bool(
                ctx.get("preview")
                or ctx.get("skip_summary")
                or os.getenv("CHAT_SKIP_SUMMARY", "0") in {"1", "true", "True"}
            )

            if skip_summary:
                summary_text = "Preview only (no LLM summary)"
            else:
                # Summarize with LLM; fall back to deterministic summary on failure
                try:
                    summary_prompt = self._build_pipeline_summary_prompt(
                        user_msg, plan.steps, step_results
                    )
                    summary = self.router.route_chat(summary_prompt)
                    summary_text = summary.text
                except Exception as summary_exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Pipeline summary via LLM failed; returning deterministic summary",
                        exc_info=summary_exc,
                    )
                    steps_desc = ", ".join([s.tool_name for s in plan.steps])
                    summary_text = (
                        "Planned pipeline steps (preview): "
                        f"{steps_desc}. "
                        "Execution was in preview mode; no container was run."
                    )

            # Build reply
            reply = ChatReply(
                answer=summary_text,
                tool_calls=[
                    {
                        "pipeline_steps": [s.__dict__ for s in plan.steps],
                        "results": step_results,
                    }
                ],
                metadata={
                    "type": "pipeline",
                    "mode": "preview" if preview else "execute",
                },
            )

            self.memory.append(
                thread_id, "assistant", summary_text, {"type": "pipeline"}
            )
            return reply

        except Exception as e:
            logger.warning(f"Pipeline execution failed, providing LLM fallback: {e}")
            return self._build_pipeline_fallback_reply(user_msg, f"pipeline error: {e}")
