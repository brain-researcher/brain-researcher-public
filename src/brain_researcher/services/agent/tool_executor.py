"""
Tool Executor for the Brain Researcher Agent.

Handles tool execution with two modes:
1. Command Generation Mode: For neuroimaging tools (returns executable commands)
2. Direct Execution Mode: For safe operations (API calls, data processing)

Integrates resource management, parameter validation, status tracking, and error handling.
"""

import asyncio
import json
import logging
import os
import shlex
import signal
import socket
import subprocess
import threading
import time
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from brain_researcher.core.contracts.loop_signals import parse_loop_signals
from brain_researcher.services.agent.error_handling import ErrorHandler
from brain_researcher.services.agent.error_taxonomy import (
    ErrorTaxonomyCategory,
    RecoveryAction,
    classify_failure,
)
from brain_researcher.services.agent.evidence_collection import (
    EvidenceCollector,
)
from brain_researcher.services.agent.execution_status import ExecutionTracker
from brain_researcher.services.agent.parameter_inference import ParameterInferenceEngine
from brain_researcher.services.agent.parameter_validation import ParameterValidator
from brain_researcher.services.agent.planner.evidence import (
    ToolEvidenceRecord,
    ToolEvidenceWriter,
)
from brain_researcher.services.agent.planner.failure_neo4j import (
    FailureKGRecord,
    Neo4jFailureWriter,
)
from brain_researcher.services.agent.resources.resource_manager import (
    Priority,
    ResourceManager,
)
from brain_researcher.services.agent.tool_execution_models import (  # noqa: F401
    _MAX_DISCOVERED_OUTPUT_FILES,
    _OUTPUT_PATH_PARAM_KEYS,
    ExecutionBackend,
    ExecutionMode,
    ToolCategory,
    ToolExecutionRequest,
    ToolExecutionResult,
    _env_flag,
)
from brain_researcher.services.agent.tool_qc import (
    ToolQCEvaluation,
    evaluate_semantic_qc,
    resolve_qc_spec,
)
from brain_researcher.services.tools.catalog_loader import resolve_runtime_tool_ids
from brain_researcher.services.tools.execution_policy import (
    ExecutionPolicyError,
    build_execution_policy_snapshot,
    enforce_allowed_paths,
    filesystem_guard,
    network_guard,
)
from brain_researcher.services.tools.executor import execute_tool
from brain_researcher.services.tools.executors.recorder_factory import (
    RecorderFactory,
    create_recorder_factory,
)
from brain_researcher.services.tools.neurodesk_tools import (
    NeurodeskTools,
)
from brain_researcher.services.tools.registry import UnifiedToolRegistry
from brain_researcher.services.tools.spec import ToolSpec, spec_from_tool
from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

try:
    from brain_researcher.services.agent.telemetry import (
        record_event as record_telemetry_event,
    )
except Exception:  # pragma: no cover - telemetry is optional

    def record_telemetry_event(*args, **kwargs):
        return None


class ToolExecutor:
    """
    Comprehensive tool executor with command generation and direct execution.

    Features:
    - Command generation for neuroimaging tools (safety-first)
    - Direct execution for safe operations
    - Auto-detection of tool category and execution mode
    - Resource-aware execution with allocation
    - Parameter validation and inference
    - Execution status tracking
    - Error handling with retry logic
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        resource_manager: ResourceManager | None = None,
        parameter_validator: ParameterValidator | None = None,
        parameter_inference: ParameterInferenceEngine | None = None,
        error_handler: ErrorHandler | None = None,
        neurodesk_tools: NeurodeskTools | None = None,
        max_workers: int = 4,
        default_timeout: float = 300.0,
        enable_caching: bool = True,
        safe_mode: bool = True,  # Prevent direct execution of dangerous commands
        evidence_collector: EvidenceCollector | None = None,
        recorder_factory: RecorderFactory | None = None,
        bg_loop_name: str = "ToolExecutor-AsyncLoop",
        evidence_writer: ToolEvidenceWriter | None = None,
        failure_writer: Neo4jFailureWriter | None = None,
    ):
        """
        Initialize the tool executor.

        Args:
            tool_registry: Registry of available tools
            resource_manager: Resource allocation manager
            parameter_validator: Parameter validation system
            parameter_inference: Parameter inference engine
            error_handler: Error handling system
            neurodesk_tools: Neurodesk tool generators
            max_workers: Maximum concurrent executions
            default_timeout: Default execution timeout
            enable_caching: Enable result caching
            safe_mode: Prevent direct execution of potentially dangerous commands
            evidence_collector: Evidence collection system
            recorder_factory: Factory for creating run recorders (for provenance tracking)
        """
        self.tool_registry = tool_registry or ToolRegistry.from_env(auto_discover=True)
        self.resource_manager = resource_manager or ResourceManager()
        self.parameter_validator = parameter_validator or ParameterValidator()
        self.parameter_inference = parameter_inference or ParameterInferenceEngine()
        self.error_handler = error_handler or ErrorHandler()
        self.neurodesk_tools = neurodesk_tools or NeurodeskTools()
        self.recorder_factory = recorder_factory or create_recorder_factory()
        self.evidence_writer = evidence_writer
        self.failure_writer = failure_writer

        self.max_workers = max_workers
        self.default_timeout = default_timeout
        self.enable_caching = enable_caching
        self.safe_mode = safe_mode
        self.evidence_collector = evidence_collector
        self._bg_loop_name = bg_loop_name
        self._multiagent_router = None
        self._multiagent_router_failed = False

        # Execution tracking
        self.active_executions: dict[str, ExecutionTracker] = {}
        self.execution_history: list[ToolExecutionResult] = []
        self.execution_cache: dict[str, ToolExecutionResult] = {}

        # Process tracking for cancellation support (per-execution-id)
        self._running_processes: dict[str, subprocess.Popen] = {}
        self._cancelled_executions: set[str] = set()

        self._process_lock = threading.Lock()

        # Thread pool for background execution
        self.executor_pool = ThreadPoolExecutor(max_workers=max_workers)

        # Dedicated background event loop for async operations (log persistence, etc.)
        self._bg_loop = None
        self._bg_loop_thread = None
        self._bg_loop_ready = threading.Event()
        self._bg_loop_stop = threading.Event()  # Signal to stop the loop
        self._start_background_loop()

        # Register Neurodesk tools with registry
        self._register_neurodesk_tools()

        logger.info(
            "ToolExecutor initialized (workers=%s, safe_mode=%s, bg_loop=running)",
            max_workers,
            safe_mode,
        )

    def _emit_tool_call_failed(
        self,
        request: ToolExecutionRequest,
        exec_result: ToolExecutionResult,
    ) -> None:
        if exec_result.status == "success":
            return

        context = request.context or {}
        error_message = exec_result.error
        if not error_message and isinstance(exec_result.result, dict):
            error_message = exec_result.result.get("error")
        error_category = (
            exec_result.error_category
            or (exec_result.metadata or {}).get("error_taxonomy", {}).get("category")
            or "unknown"
        )
        payload = {
            "job_id": context.get("job_id"),
            "thread_id": context.get("thread_id"),
            "execution_id": exec_result.execution_id,
            "tool_name": exec_result.tool_name,
            "status": exec_result.status,
            "error_message": error_message,
            "error_category": error_category,
            "is_retryable": exec_result.is_retryable,
            "recovery_strategy": exec_result.recovery_strategy,
            "retry_count": exec_result.retries,
            "mode": request.mode.value if request.mode else None,
            "category": request.category.value if request.category else None,
            "runtime_kind": request.runtime_kind or context.get("runtime_kind"),
        }
        record_telemetry_event(payload, event_type="tool_call_failed")

        # Writeback to KG (Failure)
        if self.failure_writer:
            try:
                rec = FailureKGRecord(
                    failure_id=f"fail_{exec_result.execution_id}",
                    plan_id=context.get("job_id") or exec_result.execution_id,
                    step_id=context.get("step_id"),
                    tool_id=exec_result.tool_name,
                    tool_version_id=None,  # TODO: version logic
                    error_category=error_category,
                    recovery_action=exec_result.recovery_strategy,
                    is_retryable=exec_result.is_retryable,
                    error_message=error_message,
                    attempt=exec_result.retries + 1,
                    # We can populate more fields if context has them
                    task_family=context.get("task_family"),
                    dataset_id=context.get("dataset_id"),
                    loop_signals=tuple(
                        parse_loop_signals(context.get("loop_signals") or [])
                    ),
                )
                # Fire and forget / async preferred but sync for now (writer is usually fast or has internal queuing)
                # For safety, wrap in try/except or use background loop if writer supports it.
                # Here we call directly as failure_neo4j writer is sync but has timeouts.
                self.failure_writer.write([rec])
            except Exception as e:
                logger.warning("Failed to write failure to KG: %s", e)

    def _emit_step_retry(
        self,
        request: ToolExecutionRequest,
        *,
        attempt: int,
        max_retries: int,
        error_message: str | None = None,
    ) -> None:
        context = request.context or {}
        error_category = None
        if error_message:
            try:
                taxonomy = classify_failure(
                    status="error",
                    error_message=error_message,
                    exception=None,
                    returncode=None,
                    stderr=None,
                )
                error_category = taxonomy.category.value
            except Exception:
                error_category = None

        payload = {
            "job_id": context.get("job_id"),
            "thread_id": context.get("thread_id"),
            "execution_id": request.execution_id,
            "tool_name": request.tool_name,
            "retry_attempt": attempt,
            "max_retries": max_retries,
            "error_message": error_message,
            "error_category": error_category,
            "mode": request.mode.value if request.mode else None,
            "category": request.category.value if request.category else None,
            "runtime_kind": request.runtime_kind or context.get("runtime_kind"),
        }
        record_telemetry_event(payload, event_type="step_retry")

    @staticmethod
    def _extract_step_metadata(
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(context, dict):
            return None
        metadata = context.get("step_metadata") or context.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        return None

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
        except Exception as exc:  # pragma: no cover - optional path
            logger.debug("Failed to initialize multi-agent router: %s", exc)
            self._multiagent_router_failed = True
            return None

    def _apply_multiagent_tool_gate(
        self,
        request: ToolExecutionRequest,
        *,
        tool: BRKGToolWrapper | None,
    ) -> ToolExecutionResult | None:
        if not (
            _env_flag("BR_AGENT_MULTIAGENT_ENABLED", False)
            and _env_flag("BR_AGENT_CRITIC_TOOL_GATE", False)
        ):
            return None

        router = self._get_multiagent_router()
        if router is None:
            return None

        tool_metadata: dict[str, Any] = {}
        if tool is not None:
            dangerous = getattr(tool, "dangerous", None)
            if dangerous is not None:
                tool_metadata["dangerous"] = bool(dangerous)

        verdict = router.review_tool_call(
            tool_name=request.tool_name,
            params=request.parameters,
            context=request.context if isinstance(request.context, dict) else {},
            tool_metadata=tool_metadata or None,
        )
        if verdict.decision == "approve":
            return None

        if verdict.decision == "revise":
            patch = verdict.suggested_patch or {}
            patched_params = patch.get("params")
            if isinstance(patched_params, dict):
                request.parameters = dict(patched_params)
            return None

        return ToolExecutionResult(
            execution_id=request.execution_id or "",
            tool_name=request.tool_name,
            status="error",
            error="blocked_by_multiagent_critic",
            metadata={
                "policy": "multiagent_critic",
                "multiagent_verdict": verdict.to_dict(),
            },
        )

    def _recovery_policy_for_failure(
        self,
        request: ToolExecutionRequest,
        *,
        error_message: str | None,
        stderr: str | None = None,
        returncode: int | None = None,
        status: str = "error",
        exception: BaseException | None = None,
    ):
        from brain_researcher.services.agent.recovery_policy import policy_for_taxonomy

        taxonomy = classify_failure(
            status=status,
            error_message=error_message,
            exception=exception,
            returncode=returncode,
            stderr=stderr,
        )
        policy = policy_for_taxonomy(
            taxonomy,
            step_metadata=self._extract_step_metadata(request.context),
        )
        return taxonomy, policy

    @staticmethod
    def _should_retry_for_policy(
        request: ToolExecutionRequest,
        *,
        retry_count: int,
        taxonomy,
        policy,
    ) -> bool:
        if not request.retry_on_failure or retry_count >= request.max_retries:
            return False
        action = getattr(policy, "action", None)
        if action in {RecoveryAction.ASK_USER, RecoveryAction.ABORT}:
            return False

        # Pragmatic default: allow a single retry for generic tool failures even if the
        # taxonomy classifies the error as non-retryable. Many wrappers surface transient
        # errors as plain exceptions/strings that are hard to categorize deterministically.
        if (
            getattr(taxonomy, "category", None) == ErrorTaxonomyCategory.TOOL
            and retry_count == 0
        ):
            return True

        if not getattr(taxonomy, "is_retryable", False):
            return False
        if not getattr(policy, "allow_retry", False):
            return False
        return True

    def _execute_with_policy_retry(
        self,
        request: ToolExecutionRequest,
        executor_fn: Callable[[ToolExecutionRequest], ToolExecutionResult],
    ) -> ToolExecutionResult:
        from brain_researcher.services.agent.recovery_policy import (
            select_recovery_decision,
        )

        retry_count = 0
        failed_tools: set[str] = set()
        current_request = request
        while True:
            exec_result = executor_fn(current_request)
            exec_result = self._attach_failure_taxonomy(current_request, exec_result)
            if exec_result.status == "success":
                qc_evaluation = self._evaluate_semantic_qc(
                    current_request,
                    exec_result,
                    attempt_index=retry_count,
                )
                exec_result = self._attach_semantic_qc_metadata(
                    exec_result, qc_evaluation
                )
                if qc_evaluation.status != "fail":
                    return exec_result

                failed_tools.add(current_request.tool_name)
                decision = qc_evaluation.retry_decision
                error_msg = self._semantic_qc_error_message(qc_evaluation)

                if (
                    decision is not None
                    and decision.adjusted_params
                    and decision.adjusted_params != current_request.parameters
                ):
                    if retry_count >= current_request.max_retries:
                        return self._attach_failure_taxonomy(
                            current_request,
                            self._semantic_qc_failure_result(
                                exec_result, qc_evaluation
                            ),
                        )
                    self._emit_step_retry(
                        current_request,
                        attempt=retry_count + 1,
                        max_retries=current_request.max_retries,
                        error_message=error_msg,
                    )
                    current_request = replace(
                        current_request,
                        parameters=decision.adjusted_params,
                    )
                    retry_count += 1
                    continue

                if (
                    decision is not None
                    and decision.fallback_tool
                    and decision.fallback_tool not in failed_tools
                ):
                    if retry_count >= current_request.max_retries:
                        return self._attach_failure_taxonomy(
                            current_request,
                            self._semantic_qc_failure_result(
                                exec_result, qc_evaluation
                            ),
                        )
                    self._emit_step_retry(
                        current_request,
                        attempt=retry_count + 1,
                        max_retries=current_request.max_retries,
                        error_message=error_msg,
                    )
                    current_request = replace(
                        current_request,
                        tool_name=decision.fallback_tool,
                        parameters=decision.adjusted_params
                        or current_request.parameters,
                    )
                    retry_count += 1
                    continue

                return self._attach_failure_taxonomy(
                    current_request,
                    self._semantic_qc_failure_result(exec_result, qc_evaluation),
                )

            payload = exec_result.result if isinstance(exec_result.result, dict) else {}
            error_msg = exec_result.error or payload.get("error")
            stderr = payload.get("stderr")
            returncode = payload.get("returncode")

            # Success writeback
            if exec_result.status == "success" and self.evidence_writer:
                try:
                    context = current_request.context or {}
                    latency_ms = (
                        int(exec_result.execution_time * 1000)
                        if exec_result.execution_time
                        else 0
                    )
                    rec = ToolEvidenceRecord(
                        tool_id=current_request.tool_name,
                        tool_version=None,
                        task_family=context.get("task_family") or "unknown",
                        outcome="success",
                        latency_ms=latency_ms,
                        run_id=context.get("job_id"),
                        dataset_id=context.get("dataset_id"),
                    )
                    self.evidence_writer.write([rec])
                except Exception as e:
                    logger.warning("Failed to write success evidence to KG: %s", e)

            taxonomy, policy = self._recovery_policy_for_failure(
                current_request,
                error_message=error_msg,
                stderr=stderr,
                returncode=returncode,
                status=exec_result.status or "error",
            )
            failed_tools.add(current_request.tool_name)

            context = (
                current_request.context
                if isinstance(current_request.context, dict)
                else {}
            )
            plan_candidates = context.get("plan_candidates") or context.get(
                "tool_candidates"
            )
            step_idx = context.get("step_idx")
            if step_idx is None and plan_candidates:
                step_idx = 0
            decision = select_recovery_decision(
                taxonomy=taxonomy,
                tool_id=current_request.tool_name,
                step_metadata=self._extract_step_metadata(context),
                step_idx=step_idx,
                plan_candidates=(
                    plan_candidates if isinstance(plan_candidates, list) else None
                ),
                query=context.get("query")
                or context.get("user_query")
                or context.get("prompt"),
                router=None,
                failed_tools=failed_tools,
                params=current_request.parameters,
            )

            if (
                decision.adjusted_params
                and decision.adjusted_params != current_request.parameters
            ):
                if retry_count >= current_request.max_retries:
                    return exec_result
                self._emit_step_retry(
                    current_request,
                    attempt=retry_count + 1,
                    max_retries=current_request.max_retries,
                    error_message=error_msg,
                )
                current_request = replace(
                    current_request,
                    parameters=decision.adjusted_params,
                )
                retry_count += 1
                continue

            if decision.fallback_tools:
                fallback_tool = decision.fallback_tools[0]
                if retry_count >= current_request.max_retries:
                    return exec_result
                self._emit_step_retry(
                    current_request,
                    attempt=retry_count + 1,
                    max_retries=current_request.max_retries,
                    error_message=error_msg,
                )
                current_request = replace(
                    current_request,
                    tool_name=fallback_tool,
                    parameters=decision.adjusted_params or current_request.parameters,
                )
                retry_count += 1
                continue

            if not self._should_retry_for_policy(
                current_request,
                retry_count=retry_count,
                taxonomy=taxonomy,
                policy=policy,
            ):
                return exec_result

            self._emit_step_retry(
                current_request,
                attempt=retry_count + 1,
                max_retries=current_request.max_retries,
                error_message=error_msg,
            )
            time.sleep(2**retry_count)
            retry_count += 1

    def _resolve_toolspec_for_request(
        self,
        request: ToolExecutionRequest,
    ) -> ToolSpec | None:
        spec = None
        try:
            spec = UnifiedToolRegistry().get_toolspec_by_name(request.tool_name)
        except Exception:
            spec = None
        if spec is not None:
            return spec
        try:
            tool = self._get_tool(request.tool_name)
        except Exception:
            tool = None
        if tool is None:
            return None
        template_spec = getattr(tool, "TOOL_SPEC", None)
        if isinstance(template_spec, ToolSpec):
            return template_spec
        return spec_from_tool(tool)

    def _evaluate_semantic_qc(
        self,
        request: ToolExecutionRequest,
        exec_result: ToolExecutionResult,
        *,
        attempt_index: int,
    ) -> ToolQCEvaluation:
        spec = self._resolve_toolspec_for_request(request)
        step_metadata = self._extract_step_metadata(request.context)
        payload = exec_result.result if isinstance(exec_result.result, dict) else {}
        return evaluate_semantic_qc(
            tool_name=request.tool_name,
            parameters=request.parameters,
            payload=payload,
            qc_spec=resolve_qc_spec(spec, step_metadata),
            attempt_index=attempt_index,
            context=request.context,
        )

    def _request_has_semantic_qc(self, request: ToolExecutionRequest) -> bool:
        spec = self._resolve_toolspec_for_request(request)
        qc_spec = resolve_qc_spec(spec, self._extract_step_metadata(request.context))
        return qc_spec is not None and qc_spec.enabled

    @staticmethod
    def _attach_semantic_qc_metadata(
        exec_result: ToolExecutionResult,
        qc_evaluation: ToolQCEvaluation,
    ) -> ToolExecutionResult:
        metadata = dict(exec_result.metadata or {})
        metadata["semantic_qc"] = qc_evaluation.to_metadata()
        return replace(exec_result, metadata=metadata)

    @staticmethod
    def _semantic_qc_error_message(qc_evaluation: ToolQCEvaluation) -> str:
        if qc_evaluation.judge_result is None:
            return "semantic QC failed"
        failure_modes = ",".join(qc_evaluation.judge_result.failure_modes or [])
        summary = qc_evaluation.judge_result.summary or "semantic QC failed"
        if failure_modes:
            return f"{summary} [{failure_modes}]"
        return summary

    @staticmethod
    def _semantic_qc_failure_result(
        exec_result: ToolExecutionResult,
        qc_evaluation: ToolQCEvaluation,
    ) -> ToolExecutionResult:
        error_message = ToolExecutor._semantic_qc_error_message(qc_evaluation)
        return replace(
            exec_result,
            status="error",
            error="semantic_qc_failed",
            metadata={
                **(exec_result.metadata or {}),
                "semantic_qc": qc_evaluation.to_metadata(),
                "semantic_qc_error": error_message,
            },
        )

    def _build_provenance_metadata(
        self, recorder, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Construct provenance-aware metadata payloads.

        Ensures every ToolExecutionResult includes recorder-derived identifiers
        so downstream components (worker, APIs) can persist provenance even
        when execution fails.
        """
        run_dir_path = Path(recorder.run_dir)
        metadata: dict[str, Any] = {
            "run_id": recorder.run_id,
            "run_dir": str(run_dir_path),
            "provenance_path": str(run_dir_path / "provenance.json"),
        }
        if extra:
            metadata.update(extra)
        return metadata

    @staticmethod
    def _schema_field_names(schema: Any) -> set[str]:
        if schema is None:
            return set()
        model_fields = getattr(schema, "model_fields", None)
        if isinstance(model_fields, dict):
            return {str(name) for name in model_fields.keys()}
        legacy_fields = getattr(schema, "__fields__", None)
        if isinstance(legacy_fields, dict):
            return {str(name) for name in legacy_fields.keys()}
        return set()

    def _normalize_output_path_parameters(
        self,
        parameters: dict[str, Any],
        *,
        base_dir: Path,
        schema_fields: set[str] | None = None,
        context_output_dir: str | None = None,
    ) -> dict[str, Any]:
        normalized = dict(parameters)
        fields = schema_fields or set()

        # If the tool exposes output_dir and caller omitted it, anchor it under run_dir.
        if "output_dir" in fields:
            output_dir_value = normalized.get("output_dir")
            if not isinstance(output_dir_value, str) or not output_dir_value.strip():
                if isinstance(context_output_dir, str) and context_output_dir.strip():
                    output_dir_path = Path(context_output_dir.strip())
                    if not output_dir_path.is_absolute():
                        output_dir_path = (base_dir / output_dir_path).resolve()
                else:
                    output_dir_path = (base_dir / "outputs").resolve()
                normalized["output_dir"] = str(output_dir_path)

        for key in _OUTPUT_PATH_PARAM_KEYS:
            value = normalized.get(key)
            if not isinstance(value, str):
                continue
            raw = value.strip()
            if not raw:
                continue
            if "://" in raw:
                continue
            path_candidate = Path(raw)
            if path_candidate.is_absolute():
                normalized[key] = str(path_candidate)
                continue
            normalized[key] = str((base_dir / path_candidate).resolve())

        return normalized

    def _discover_output_files_from_payload(
        self,
        payload: dict[str, Any],
        *,
        base_dirs: list[Path] | None = None,
    ) -> list[str]:
        nodes: list[Any] = []

        def _append_node(node: Any) -> None:
            if node is not None:
                nodes.append(node)

        _append_node(payload.get("outputs"))
        _append_node(payload.get("artifacts"))
        _append_node(payload.get("artifact"))

        data = payload.get("data")
        if isinstance(data, dict):
            _append_node(data.get("outputs"))
            _append_node(data.get("artifacts"))
            _append_node(data.get("artifact"))
            _append_node(data.get("steps"))

        result = payload.get("result")
        if isinstance(result, dict):
            _append_node(result.get("outputs"))
            _append_node(result.get("artifacts"))
            _append_node(result.get("artifact"))
            _append_node(result.get("steps"))

        discovered: list[str] = []
        seen: set[str] = set()
        search_roots: list[Path] = []
        for base_dir in base_dirs or []:
            try:
                search_roots.append(Path(base_dir).expanduser().resolve())
            except Exception:
                continue
        search_roots.append(Path.cwd())

        def _walk(node: Any, *, depth: int) -> None:
            if depth > 8 or len(discovered) >= _MAX_DISCOVERED_OUTPUT_FILES:
                return
            if isinstance(node, str):
                text = node.strip()
                if not text or "://" in text:
                    return
                raw_candidate = Path(text).expanduser()
                candidates: list[Path] = []
                if raw_candidate.is_absolute():
                    candidates.append(raw_candidate.resolve())
                else:
                    for root in search_roots:
                        candidates.append((root / raw_candidate).resolve())
                for candidate in candidates:
                    try:
                        if not candidate.is_file():
                            continue
                    except OSError:
                        continue
                    path_text = str(candidate)
                    if path_text in seen:
                        return
                    seen.add(path_text)
                    discovered.append(path_text)
                    return
                return
            if isinstance(node, dict):
                for value in node.values():
                    _walk(value, depth=depth + 1)
                return
            if isinstance(node, list | tuple | set):
                for value in node:
                    _walk(value, depth=depth + 1)

        for node in nodes:
            _walk(node, depth=0)

        return discovered

    def _register_neurodesk_tools(self):
        """Register Neurodesk tools with the tool registry."""
        for tool in self.neurodesk_tools.get_all_tools():
            self.tool_registry.register_tool(tool)
        logger.info("Registered Neurodesk tools with registry")

    def _build_multi_step_commands(
        self,
        base_command: str | None,
        execution_plan: dict[str, Any],
    ) -> tuple[str, str] | None:
        """Construct combined command and script for multi-step execution plans."""
        if not base_command or not isinstance(base_command, str):
            return None

        executable = execution_plan.get("executable")
        steps = execution_plan.get("steps") or []

        if not executable or not steps:
            return None

        prefix_before, separator, _ = base_command.partition(executable)
        if not separator:
            return None

        prefix = (prefix_before + executable).strip()
        step_commands: list[str] = []

        for step in steps:
            args = step.get("args") if isinstance(step, dict) else None
            if not isinstance(args, list | tuple):
                logger.debug("Skipping malformed execution plan step: %s", step)
                continue

            arg_parts = [str(arg) for arg in args]
            step_command = " ".join([prefix] + arg_parts).strip()
            if step_command:
                step_commands.append(step_command)

        if not step_commands:
            return None

        combined_command = " && ".join(step_commands)
        script_lines = ["#!/bin/bash", "set -euo pipefail", *step_commands]
        script = "\n".join(script_lines)
        return combined_command, script

    def _start_background_loop(self):
        """
        Start dedicated event loop in background thread for async operations.

        This loop handles log persistence and other async operations without
        blocking the main thread or creating/destroying loops repeatedly.
        """
        stop_event = self._bg_loop_stop
        ready_event = self._bg_loop_ready
        loop_name = self._bg_loop_name
        self_ref = weakref.ref(self)

        def run_loop():
            """Background thread target: create and run event loop."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            owner = self_ref()
            if owner is not None:
                owner._bg_loop = loop
            # Drop strong reference to owner so the thread doesn't keep the executor alive.
            owner = None
            ready_event.set()  # Signal that loop is ready

            logger.debug("Background event loop started")

            # Run loop with periodic stop checks
            iteration = 0
            while not stop_event.is_set():
                if self_ref() is None:
                    logger.debug("Background loop owner released; stopping loop")
                    break
                iteration += 1
                # Run loop briefly to process pending callbacks
                loop.call_later(0.05, loop.stop)
                loop.run_forever()
                if iteration % 10 == 0:
                    logger.debug(
                        "Background loop iteration %s, stop=%s",
                        iteration,
                        stop_event.is_set(),
                    )

            logger.debug("Background event loop stopped")
            try:
                loop.close()
            except Exception:
                pass

        # Start thread
        self._bg_loop_thread = threading.Thread(
            target=run_loop,
            daemon=True,  # Daemon thread won't prevent process exit
            name=loop_name,
        )
        self._bg_loop_thread.start()

        # Wait for loop to be ready (with timeout for safety)
        if not self._bg_loop_ready.wait(timeout=5.0):
            raise RuntimeError("Background event loop failed to start within 5 seconds")

        logger.debug("Background loop thread started successfully")

    def cancel(self, execution_id: str, reason: str = "Cancelled by user") -> bool:
        """
        Cancel a specific execution by killing its process group.

        Sends SIGKILL to the process group to ensure all child processes
        are terminated. This is a hard kill that cannot be caught.

        Args:
            execution_id: ID of the execution to cancel
            reason: Reason for cancellation (for logging)

        Returns:
            True if process was found and killed, False otherwise
        """
        with self._process_lock:
            self._cancelled_executions.add(execution_id)
            proc = self._running_processes.get(execution_id)

            if proc and proc.poll() is None:
                try:
                    # Kill the entire process group
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                    logger.info(
                        f"Killed execution {execution_id} (pgid={pgid}) with SIGKILL: {reason}"
                    )
                    return True
                except ProcessLookupError:
                    logger.debug(
                        f"Process for execution {execution_id} already terminated"
                    )
                except Exception as e:
                    logger.error(
                        f"Error killing process for execution {execution_id}: {e}"
                    )
            else:
                logger.warning(f"No running process found for execution {execution_id}")

        return False

    def is_cancelled(self, execution_id: str) -> bool:
        """Check if a specific execution was cancelled."""
        return execution_id in self._cancelled_executions

    def _async_append_log(
        self, job_store: Any, job_id: str, stream: str, data: bytes, offset: int
    ) -> None:
        """
        Submit log append to background event loop (non-blocking, fire-and-forget).

        Uses the dedicated background loop instead of creating new loops repeatedly.
        This is much more efficient and avoids event loop lifecycle issues.

        Args:
            job_store: JobStore instance
            job_id: Job identifier
            stream: Stream name ('stdout' or 'stderr')
            data: Log data bytes
            offset: Byte offset in stream
        """
        if self._bg_loop is None or not self._bg_loop.is_running():
            logger.warning("Background loop not available, skipping log append")
            return

        try:
            # Schedule coroutine on background loop (non-blocking, fire-and-forget)
            asyncio.run_coroutine_threadsafe(
                job_store.append_log(job_id, stream, data, offset), self._bg_loop
            )
        except Exception as e:
            logger.debug(f"Failed to schedule log append: {e}")

    async def _stream_process_output(
        self,
        proc: subprocess.Popen,
        execution_id: str,
        job_store: Any,
        job_id: str,
        timeout: float | None = None,
    ) -> tuple[str, str, int]:
        """
        Stream stdout/stderr from process with incremental log persistence.

        Now fully async to avoid blocking. Runs on background event loop.

        Args:
            proc: Running subprocess.Popen instance
            execution_id: Execution identifier
            job_store: JobStore instance for log persistence
            job_id: Job identifier for log association
            timeout: Optional timeout in seconds

        Returns:
            Tuple of (stdout_text, stderr_text, returncode)
        """
        stdout_chunks = []
        stderr_chunks = []
        stdout_offset = 0
        stderr_offset = 0

        # Make stdout/stderr non-blocking
        import fcntl

        if proc.stdout:
            fd_stdout = proc.stdout.fileno()
            fl = fcntl.fcntl(fd_stdout, fcntl.F_GETFL)
            fcntl.fcntl(fd_stdout, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        if proc.stderr:
            fd_stderr = proc.stderr.fileno()
            fl = fcntl.fcntl(fd_stderr, fcntl.F_GETFL)
            fcntl.fcntl(fd_stderr, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        start_time = time.time()
        poll_interval = 0.01  # Poll every 10ms for higher throughput
        chunk_size = 65536  # 64KB chunks to reduce overhead

        async def _drain_stream(
            fd: int, stream_name: str, offset: int, chunks: list[bytes]
        ) -> int:
            """Read all currently available data from a non-blocking fd."""
            while True:
                try:
                    chunk = os.read(fd, chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    try:
                        await job_store.append_log(job_id, stream_name, chunk, offset)
                    except Exception as e:
                        logger.warning(f"Failed to persist {stream_name} chunk: {e}")
                    offset += len(chunk)
                except (BlockingIOError, OSError):
                    break
            return offset

        while True:
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                raise subprocess.TimeoutExpired(proc.args, timeout)

            # Check if process finished
            returncode = proc.poll()

            # Drain available data from stdout/stderr
            if proc.stdout:
                stdout_offset = await _drain_stream(
                    fd_stdout, "stdout", stdout_offset, stdout_chunks
                )
            if proc.stderr:
                stderr_offset = await _drain_stream(
                    fd_stderr, "stderr", stderr_offset, stderr_chunks
                )

            # If process finished and no more data, exit
            if returncode is not None:
                # Final read to catch any remaining output (non-blocking sleep)
                await asyncio.sleep(0.1)

                # Final drain for both streams
                if proc.stdout:
                    stdout_offset = await _drain_stream(
                        fd_stdout, "stdout", stdout_offset, stdout_chunks
                    )
                if proc.stderr:
                    stderr_offset = await _drain_stream(
                        fd_stderr, "stderr", stderr_offset, stderr_chunks
                    )

                break

            # Check for cancellation
            if self.is_cancelled(execution_id):
                logger.info(f"Execution {execution_id} cancelled during streaming")
                # Kill process group
                with self._process_lock:
                    if proc.poll() is None:
                        try:
                            pgid = os.getpgid(proc.pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            pass
                proc.wait()
                returncode = -1
                break

            # Non-blocking sleep to avoid busy-waiting
            await asyncio.sleep(poll_interval)

        # Decode accumulated output
        stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        return stdout_text, stderr_text, returncode

    def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """
        Execute a tool based on its category and mode.

        Args:
            request: Tool execution request

        Returns:
            Execution result with command or direct execution output
        """
        # Optional MCP policy gate (internal-only execution gate)
        if os.getenv("BR_MCP_EXECUTION_GATE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            if request.tool_name == "shell_command":
                return ToolExecutionResult(
                    execution_id=request.execution_id or "",
                    tool_name=request.tool_name,
                    status="error",
                    error="mcp_gate_blocks_shell_execution",
                    metadata={"policy": "mcp_gate"},
                )
            try:
                from brain_researcher.services.tools.execution_policy import (
                    policy_check_tool,
                )
                from brain_researcher.services.tools.registry import (
                    UnifiedToolRegistry,
                )

                spec = UnifiedToolRegistry().get_toolspec_by_name(request.tool_name)
                if spec is None:
                    return ToolExecutionResult(
                        execution_id=request.execution_id or "",
                        tool_name=request.tool_name,
                        status="error",
                        error=f"unknown_tool:{request.tool_name}",
                        metadata={"policy": "mcp_gate"},
                    )
                issues = policy_check_tool(
                    spec,
                    allow_network=os.getenv("BR_MCP_ALLOW_NETWORK", "").strip().lower()
                    in {"1", "true", "yes", "on"},
                    allow_dangerous=os.getenv("BR_MCP_ALLOW_DANGEROUS", "")
                    .strip()
                    .lower()
                    in {"1", "true", "yes", "on"},
                )
                if any(i.get("level") == "error" for i in issues):
                    return ToolExecutionResult(
                        execution_id=request.execution_id or "",
                        tool_name=request.tool_name,
                        status="error",
                        error="policy_rejected",
                        metadata={"policy": "mcp_gate", "issues": issues},
                    )
                if request.timeout is None and spec.timeout_s:
                    request.timeout = float(spec.timeout_s)
            except Exception as exc:  # pragma: no cover - best effort gate
                logger.debug("MCP gate check skipped: %s", exc)

        # Get tool early to check execution_backend attribute
        try:
            tool = self._get_tool(request.tool_name)
        except ValueError:
            # Tool not found, will fail later - use default backend detection
            tool = None

        backend = self._determine_backend(request, tool)
        logger.info(
            f"Executing tool {request.tool_name} "
            f"(mode={request.mode.value}, category={request.category.value}, backend={backend.value})"
        )

        gate_result = self._apply_multiagent_tool_gate(request, tool=tool)
        if gate_result is not None:
            gate_result = self._attach_failure_taxonomy(request, gate_result)
            self._emit_tool_call_failed(request, gate_result)
            return gate_result

        # Check cache if enabled
        if self.enable_caching and not self._request_has_semantic_qc(request):
            cache_key = self._get_cache_key(request)
            if cache_key in self.execution_cache:
                logger.info("Returning cached result")
                cached = self.execution_cache[cache_key]
                cached.metadata["from_cache"] = True
                # Record evidence even on cache hit
                self._record_tool_evidence(
                    tool_name=request.tool_name,
                    parameters=request.parameters,
                    command=cached.command,
                    execution_time=0.0,
                    success=cached.status == "success",
                    result=cached.result,
                )
                return self._attach_failure_taxonomy(request, cached)

        # Safety check for direct execution
        if request.mode == ExecutionMode.DIRECT_EXECUTION and self.safe_mode:
            if request.category == ToolCategory.NEUROIMAGING:
                logger.warning(
                    f"Blocking direct execution of neuroimaging tool {request.tool_name} "
                    f"in safe mode. Switching to command generation."
                )
                request.mode = ExecutionMode.COMMAND_GENERATION

        # Route based on backend/mode
        if backend == ExecutionBackend.PYTHON:
            exec_result = self._execute_with_policy_retry(request, self._execute_python)
            self._emit_tool_call_failed(request, exec_result)
            return exec_result

        # Ensure API backend uses API_CALL mode
        if backend == ExecutionBackend.API:
            request.mode = ExecutionMode.API_CALL

        if request.mode == ExecutionMode.COMMAND_GENERATION:
            exec_result = self._execute_with_policy_retry(
                request, self._execute_command_generation
            )
            self._emit_tool_call_failed(request, exec_result)
            return exec_result
        if request.mode == ExecutionMode.DIRECT_EXECUTION:
            exec_result = self._execute_with_policy_retry(request, self._execute_direct)
            self._emit_tool_call_failed(request, exec_result)
            return exec_result
        if request.mode == ExecutionMode.API_CALL:
            exec_result = self._execute_with_policy_retry(
                request, self._execute_api_call
            )
            self._emit_tool_call_failed(request, exec_result)
            return exec_result
        if request.mode == ExecutionMode.BATCH:
            exec_result = self._execute_with_policy_retry(request, self._execute_batch)
            self._emit_tool_call_failed(request, exec_result)
            return exec_result

    def run_tool(
        self,
        tool_name: str,
        _execution_context: dict[str, Any] | None = None,
        **parameters,
    ) -> dict[str, Any]:
        """Compatibility shim for DAGExecutor: execute a tool and return a payload dict."""
        request = ToolExecutionRequest(
            tool_name=tool_name,
            parameters=parameters,
            context=_execution_context or {},
            runtime_kind="python",
        )
        exec_result = self.execute(request)
        payload = exec_result.result
        if isinstance(payload, ToolResult):
            return payload.model_dump()
        if isinstance(payload, dict):
            return payload
        return {
            "status": exec_result.status,
            "data": payload,
            "error": exec_result.error,
        }
        exec_result = self._execute_command_generation(request)
        exec_result = self._attach_failure_taxonomy(request, exec_result)
        self._emit_tool_call_failed(request, exec_result)
        return exec_result

    def _attach_failure_taxonomy(
        self,
        request: ToolExecutionRequest,
        exec_result: ToolExecutionResult,
        *,
        exception: BaseException | None = None,
    ) -> ToolExecutionResult:
        """Attach durable failure taxonomy + recovery hints to an execution result.

        This is intentionally best-effort; it should never raise.
        """

        if exec_result.status == "success":
            return exec_result

        try:
            returncode: int | None = None
            stderr: str | None = None
            error_message: str | None = exec_result.error

            payload = exec_result.result
            if isinstance(payload, dict):
                returncode = payload.get("returncode")
                stderr = payload.get("stderr")
                error_message = error_message or payload.get("error")
            else:
                # ToolResult (pydantic) or other object
                if hasattr(payload, "error"):
                    try:
                        error_message = error_message or payload.error
                    except Exception:
                        pass
                if hasattr(payload, "metadata"):
                    try:
                        md = payload.metadata or {}
                        if isinstance(md, dict):
                            stderr = (
                                stderr or md.get("stderr") or md.get("stderr_snippet")
                            )
                            returncode = returncode or md.get("returncode")
                    except Exception:
                        pass

            taxonomy = classify_failure(
                status=exec_result.status,
                error_message=error_message,
                exception=exception,
                returncode=returncode,
                stderr=stderr,
            )

            exec_result.error_category = taxonomy.category.value
            exec_result.is_retryable = taxonomy.is_retryable
            exec_result.recovery_strategy = taxonomy.recovery_action.value
            exec_result.recovery_suggestions = list(taxonomy.recovery_suggestions)

            # Also embed into metadata for compatibility (durable serialized form).
            exec_result.metadata.setdefault("error_taxonomy", taxonomy.to_dict())
            exec_result.metadata.setdefault("tool_category", request.category.value)
            exec_result.metadata.setdefault("execution_mode", request.mode.value)
        except Exception as exc:  # pragma: no cover - safety net
            logger.debug("Failed to attach failure taxonomy: %s", exc)

        return exec_result

    def _determine_backend(
        self, request: ToolExecutionRequest, tool: BRKGToolWrapper | None = None
    ) -> ExecutionBackend:
        """Resolve execution backend from request/runtime hints and tool attributes.

        Priority order:
        1. request.runtime_kind (highest priority - explicit override)
        2. tool.execution_backend attribute (tool-level hint)
        3. request.category/mode (API detection)
        4. CONTAINER (default)
        """

        # NEW: Check request runtime hint first (highest priority)
        runtime = request.runtime_kind or request.context.get("runtime_kind")
        if runtime:
            runtime_normalized = str(runtime).strip().lower()
            runtime_aliases = {
                "mcp": "api",
                "external_api": "api",
                "niwrap": "container",
            }
            runtime_normalized = runtime_aliases.get(
                runtime_normalized, runtime_normalized
            )
            try:
                return ExecutionBackend(runtime_normalized)
            except ValueError:
                logger.debug(
                    "Unknown runtime kind %s for %s",
                    runtime_normalized,
                    request.tool_name,
                )

        # NEW: Check tool execution_backend attribute
        if tool and hasattr(tool, "execution_backend") and tool.execution_backend:
            try:
                return ExecutionBackend(tool.execution_backend)
            except ValueError:
                logger.debug(
                    "Unknown execution_backend %s for tool %s",
                    tool.execution_backend,
                    request.tool_name,
                )

        # EXISTING: Keep existing logic for API category detection
        if (
            request.mode == ExecutionMode.API_CALL
            or request.category == ToolCategory.API_SERVICE
        ):
            return ExecutionBackend.API

        # EXISTING: Keep existing container default
        return ExecutionBackend.CONTAINER

    def _execute_python(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Execute a tool by invoking its Python wrapper in-process."""

        start_time = time.time()
        tracker = ExecutionTracker(execution_id=request.execution_id)
        self.active_executions[request.execution_id] = tracker

        parent_run_id = request.context.get("parent_run_id")
        step_id = request.context.get("step_id") or request.context.get("tool_call_id")
        recorder = self.recorder_factory.create_recorder(
            run_id=request.execution_id,
            resolver_mode="python_execution",
            parent_run_id=parent_run_id,
            step_id=step_id,
        )

        try:
            with recorder:
                tracker.start_execution()
                tracker.metadata = {
                    "tool": request.tool_name,
                    "mode": "python_execution",
                    "total_steps": 3,
                }

                tracker.start_step()
                tool = self._get_tool(request.tool_name)
                tracker.complete_step()

                tracker.start_step()
                parameters = self._infer_parameters(
                    tool, dict(request.parameters), request.context
                )
                tracker.complete_step()

                validation = self._validate_parameters(tool.get_tool_name(), parameters)
                recorder.add_extra(validation=validation)

                tracker.start_step()
                # Enforce required parameters before execution
                try:
                    schema = tool.get_args_schema()
                    required_params = []
                    if hasattr(schema, "__fields__"):
                        required_params = [
                            name
                            for name, field in schema.__fields__.items()
                            if field.is_required()
                        ]
                    missing_required = [
                        name for name in required_params if parameters.get(name) is None
                    ]
                    if missing_required:
                        status = "error"
                        payload = {
                            "status": status,
                            "error": (
                                "Missing required parameters: "
                                + ", ".join(missing_required)
                            ),
                            "missing": missing_required,
                        }
                        tracker.complete_step()
                        exec_result = ToolExecutionResult(
                            execution_id=request.execution_id,
                            tool_name=request.tool_name,
                            status=status,
                            result=payload,
                            execution_time=time.time() - start_time,
                            metadata=self._build_provenance_metadata(
                                recorder,
                                {
                                    "mode": "parameter_validation",
                                    "validation": validation,
                                    "tool_data": payload,
                                },
                            ),
                        )
                        self._record_tool_evidence(
                            tool_name=request.tool_name,
                            parameters=parameters,
                            command=None,
                            execution_time=exec_result.execution_time,
                            success=False,
                            result=payload,
                        )
                        return exec_result
                except Exception as e:
                    logger.debug(f"Required param check skipped: {e}")

                # Prefer calling the wrapper's Python implementation directly when available;
                # fall back to unified execute_tool (ToolSpec) for legacy specs.
                if hasattr(tool, "_run"):
                    spec = None
                    try:
                        spec = UnifiedToolRegistry().get_toolspec_by_name(
                            request.tool_name
                        )
                    except Exception:
                        spec = None
                    if spec is None:
                        spec = spec_from_tool(tool)

                    # Parameter aliasing / hard guard for known mismatches
                    if request.tool_name == "code_agent":
                        if "instruction" not in parameters and "prompt" in parameters:
                            parameters["instruction"] = parameters.pop("prompt")

                    schema_fields = self._schema_field_names(tool.get_args_schema())
                    execution_base_dir = Path(
                        str(request.context.get("work_dir") or recorder.run_dir)
                    )
                    normalized_parameters = self._normalize_output_path_parameters(
                        parameters,
                        base_dir=execution_base_dir,
                        schema_fields=schema_fields,
                        context_output_dir=(
                            request.context.get("output_dir")
                            if isinstance(request.context.get("output_dir"), str)
                            else None
                        ),
                    )
                    try:
                        work_dir = (
                            normalized_parameters.get("work_dir")
                            or parameters.get("work_dir")
                            or request.context.get("work_dir")
                        )
                        output_dir = (
                            normalized_parameters.get("output_dir")
                            or parameters.get("output_dir")
                            or request.context.get("output_dir")
                        )
                        if spec is None:
                            tool_desc = request.tool_name
                            try:
                                tool_desc = tool.get_tool_description()
                            except Exception:
                                tool_desc = request.tool_name
                            spec = ToolSpec(
                                name=request.tool_name, description=str(tool_desc)
                            )

                        timeout_s = request.timeout or self.default_timeout
                        recorder.add_extra(
                            execution_policy=build_execution_policy_snapshot(
                                spec,
                                work_dir=work_dir,
                                output_dir=output_dir,
                                timeout_s=timeout_s,
                            )
                        )

                        def _run_under_guards(call_params: dict[str, Any]):
                            with filesystem_guard(
                                spec,
                                work_dir=work_dir,
                                output_dir=output_dir,
                            ):
                                with network_guard(spec):
                                    return tool._run(**call_params)

                        def _run_with_timeout(call_params: dict[str, Any]):
                            exec_pool = ThreadPoolExecutor(max_workers=1)
                            future = exec_pool.submit(_run_under_guards, call_params)
                            try:
                                return future.result(timeout=timeout_s)
                            finally:
                                exec_pool.shutdown(wait=False, cancel_futures=True)

                        enforce_allowed_paths(
                            spec,
                            normalized_parameters,
                            work_dir=work_dir,
                            output_dir=output_dir,
                        )
                        try:
                            tool_result = _run_with_timeout(normalized_parameters)
                        except socket.gaierror as exc:
                            msg = str(exc)
                            if "network_blocked_by_policy" in msg:
                                raise ExecutionPolicyError(
                                    [
                                        {
                                            "level": "error",
                                            "code": "network_blocked_by_policy",
                                            "message": "Network access blocked by policy",
                                        }
                                    ]
                                ) from exc
                            if "domain_not_allowed:" in msg:
                                domain = msg.split("domain_not_allowed:", 1)[1]
                                raise ExecutionPolicyError(
                                    [
                                        {
                                            "level": "error",
                                            "code": "domain_not_allowed",
                                            "message": f"Domain is not allowed: {domain}",
                                            "domain": domain,
                                        }
                                    ]
                                ) from exc
                            raise
                    except TypeError:
                        # Some tools expect context-like kwargs; merge conservatively
                        merged_params = {**normalized_parameters, **request.context}
                        try:
                            enforce_allowed_paths(
                                spec,
                                merged_params,
                                work_dir=work_dir,
                                output_dir=output_dir,
                            )
                            try:
                                tool_result = _run_with_timeout(merged_params)
                            except socket.gaierror as exc:
                                msg = str(exc)
                                if "network_blocked_by_policy" in msg:
                                    raise ExecutionPolicyError(
                                        [
                                            {
                                                "level": "error",
                                                "code": "network_blocked_by_policy",
                                                "message": "Network access blocked by policy",
                                            }
                                        ]
                                    ) from exc
                                if "domain_not_allowed:" in msg:
                                    domain = msg.split("domain_not_allowed:", 1)[1]
                                    raise ExecutionPolicyError(
                                        [
                                            {
                                                "level": "error",
                                                "code": "domain_not_allowed",
                                                "message": f"Domain is not allowed: {domain}",
                                                "domain": domain,
                                            }
                                        ]
                                    ) from exc
                                raise
                        except ExecutionPolicyError as exc:
                            status = "error"
                            payload = {
                                "status": status,
                                "error": "execution_policy_violation",
                                "policy_issues": exc.issues,
                            }
                            tracker.complete_step()
                            exec_result = ToolExecutionResult(
                                execution_id=request.execution_id,
                                tool_name=request.tool_name,
                                status=status,
                                result=payload,
                                execution_time=time.time() - start_time,
                                metadata=self._build_provenance_metadata(
                                    recorder,
                                    {
                                        "mode": "execution_policy",
                                        "validation": validation,
                                        "tool_data": payload,
                                    },
                                ),
                            )
                            self._record_tool_evidence(
                                tool_name=request.tool_name,
                                parameters=merged_params,
                                command=None,
                                execution_time=exec_result.execution_time,
                                success=False,
                                result=payload,
                            )
                            return exec_result
                        except TimeoutError:
                            status = "timeout"
                            payload = {
                                "status": status,
                                "error": "execution_timeout",
                                "timeout_s": timeout_s,
                            }
                            tracker.complete_step()
                            exec_result = ToolExecutionResult(
                                execution_id=request.execution_id,
                                tool_name=request.tool_name,
                                status=status,
                                result=payload,
                                execution_time=time.time() - start_time,
                                metadata=self._build_provenance_metadata(
                                    recorder,
                                    {
                                        "mode": "execution_timeout",
                                        "validation": validation,
                                        "tool_data": payload,
                                    },
                                ),
                            )
                            self._record_tool_evidence(
                                tool_name=request.tool_name,
                                parameters=merged_params,
                                command=None,
                                execution_time=exec_result.execution_time,
                                success=False,
                                result=payload,
                            )
                            return exec_result
                    except ExecutionPolicyError as exc:
                        status = "error"
                        payload = {
                            "status": status,
                            "error": "execution_policy_violation",
                            "policy_issues": exc.issues,
                        }
                        tracker.complete_step()
                        exec_result = ToolExecutionResult(
                            execution_id=request.execution_id,
                            tool_name=request.tool_name,
                            status=status,
                            result=payload,
                            execution_time=time.time() - start_time,
                            metadata=self._build_provenance_metadata(
                                recorder,
                                {
                                    "mode": "execution_policy",
                                    "validation": validation,
                                    "tool_data": payload,
                                },
                            ),
                        )
                        self._record_tool_evidence(
                            tool_name=request.tool_name,
                            parameters=normalized_parameters,
                            command=None,
                            execution_time=exec_result.execution_time,
                            success=False,
                            result=payload,
                        )
                        return exec_result
                    except TimeoutError:
                        status = "timeout"
                        payload = {
                            "status": status,
                            "error": "execution_timeout",
                            "timeout_s": timeout_s,
                        }
                        tracker.complete_step()
                        exec_result = ToolExecutionResult(
                            execution_id=request.execution_id,
                            tool_name=request.tool_name,
                            status=status,
                            result=payload,
                            execution_time=time.time() - start_time,
                            metadata=self._build_provenance_metadata(
                                recorder,
                                {
                                    "mode": "execution_timeout",
                                    "validation": validation,
                                    "tool_data": payload,
                                },
                            ),
                        )
                        self._record_tool_evidence(
                            tool_name=request.tool_name,
                            parameters=normalized_parameters,
                            command=None,
                            execution_time=exec_result.execution_time,
                            success=False,
                            result=payload,
                        )
                        return exec_result
                    # Normalize to ToolResult-like payload; ensure JSON-safe
                    if isinstance(tool_result, ToolResult):
                        payload = tool_result.model_dump()
                        status = tool_result.status
                    else:
                        payload = tool_result or {}
                        status = payload.get("status", "success")
                    payload = json.loads(json.dumps(payload, default=str))
                else:
                    execution_base_dir = Path(
                        str(request.context.get("work_dir") or recorder.run_dir)
                    )
                    normalized_parameters = self._normalize_output_path_parameters(
                        parameters,
                        base_dir=execution_base_dir,
                        schema_fields=set(),
                        context_output_dir=(
                            request.context.get("output_dir")
                            if isinstance(request.context.get("output_dir"), str)
                            else None
                        ),
                    )
                    tool_result = execute_tool(
                        request.tool_name,
                        normalized_parameters,
                        work_dir=request.context.get("work_dir")
                        or str(execution_base_dir),
                        output_dir=(
                            request.context.get("output_dir")
                            or normalized_parameters.get("output_dir")
                            or str((execution_base_dir / "outputs").resolve())
                        ),
                    )
                    if isinstance(tool_result, ToolResult):
                        payload = tool_result.model_dump()
                        status = tool_result.status
                    else:
                        payload = tool_result or {}
                        status = payload.get("status", "success")
                    parameters = normalized_parameters
                tracker.complete_step()

                recorder.add_extra(outputs=payload.get("outputs"))
                discovered_outputs = self._discover_output_files_from_payload(
                    payload,
                    base_dirs=[execution_base_dir],
                )
                if discovered_outputs:
                    recorder.set_outputs(discovered_outputs)
                    recorder.add_extra(output_files=discovered_outputs)

                exec_result = ToolExecutionResult(
                    execution_id=request.execution_id,
                    tool_name=request.tool_name,
                    status=status,
                    result=payload,
                    execution_time=time.time() - start_time,
                    metadata=self._build_provenance_metadata(
                        recorder,
                        {
                            "mode": "python_execution",
                            "validation": validation,
                            "tool_data": payload,
                        },
                    ),
                )

                self._record_tool_evidence(
                    tool_name=request.tool_name,
                    parameters=parameters,
                    command=None,
                    execution_time=exec_result.execution_time,
                    success=status == "success",
                    result=payload,
                )

                # Cache python executions when enabled
                if self.enable_caching:
                    cache_key = self._get_cache_key(request)
                    self.execution_cache[cache_key] = exec_result

                return exec_result

        except Exception as exc:
            logger.exception("Python tool %s failed", request.tool_name)
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error=str(exc),
                execution_time=time.time() - start_time,
                result={"error": str(exc)},
            )

        finally:
            tracker.complete_execution()
            self.active_executions.pop(request.execution_id, None)

    def _execute_command_generation(
        self, request: ToolExecutionRequest
    ) -> ToolExecutionResult:
        """Generate executable command for the tool."""
        start_time = time.time()
        tracker = ExecutionTracker(execution_id=request.execution_id)
        self.active_executions[request.execution_id] = tracker

        # Create run recorder for provenance tracking
        parent_run_id = request.context.get("parent_run_id")
        step_id = request.context.get("step_id") or request.context.get("tool_call_id")
        recorder = self.recorder_factory.create_recorder(
            run_id=request.execution_id,
            resolver_mode="command_generation",
            parent_run_id=parent_run_id,
            step_id=step_id,
        )

        try:
            # Start tracking
            tracker.start_execution()
            tracker.metadata = {
                "tool": request.tool_name,
                "mode": "command_generation",
                "total_steps": 4,
            }

            # Step 1: Get tool
            tracker.start_step()
            try:
                tool = self._get_tool(request.tool_name)
            except ValueError:
                tool = None
            tracker.complete_step()

            # Step 2: Infer parameters
            tracker.start_step()
            if tool is not None:
                inferred_params = self._infer_parameters(
                    tool, request.parameters, request.context
                )
            else:
                inferred_params = dict(request.parameters)
            tracker.complete_step()

            # Step 3: Validate parameters
            tracker.start_step()
            validation_result = (
                self._validate_parameters(request.tool_name, inferred_params)
                if tool is not None
                else {"valid": True}
            )
            if not validation_result.get("valid", True):
                logger.warning(f"Parameter validation warnings: {validation_result}")
            tracker.complete_step()

            # Step 4: Generate command
            tracker.start_step()

            # Set recorder metadata
            extra_metadata = {
                "tool_name": request.tool_name,
                "execution_mode": "command_generation",
                "tool_category": request.category.value,
                "parameters": inferred_params,
            }

            # Add preflight report from job metadata if available (P0.2)
            if "job_store" in request.context and "job_id" in request.context:
                try:
                    job_store = request.context["job_store"]
                    job_id = request.context["job_id"]
                    # Retrieve job from store (synchronous for compatibility)
                    import asyncio

                    try:
                        running_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        running_loop = None
                    if running_loop and running_loop.is_running():
                        logger.debug(
                            "Skipping preflight report retrieval: event loop already running"
                        )
                    else:
                        loop = asyncio.get_event_loop()
                        job_record = loop.run_until_complete(job_store.get(job_id))
                        if job_record and hasattr(job_record, "metadata"):
                            if "preflight_report" in job_record.metadata:
                                extra_metadata["preflight_report"] = (
                                    job_record.metadata["preflight_report"]
                                )
                except Exception as e:
                    logger.warning(
                        f"Failed to retrieve preflight report from job metadata: {e}"
                    )

            recorder.add_extra(**extra_metadata)

            # Execute tool to get command wrapped in recorder
            with recorder:
                result = tool.run(**inferred_params)

                if result.get("status") == "success":
                    command = result.get("data", {}).get("command")
                    instructions = result.get("data", {}).get("instructions", "")

                    execution_plan = request.parameters.get("execution_plan")
                    if execution_plan and execution_plan.get("steps"):
                        multi_step = self._build_multi_step_commands(
                            base_command=command,
                            execution_plan=execution_plan,
                        )
                        if multi_step:
                            command, script = multi_step
                            result.setdefault("data", {})["command"] = command
                            result["data"]["script"] = script
                            result["data"]["multi_step"] = True
                            result["data"]["steps"] = execution_plan.get("steps")
                        else:
                            logger.warning(
                                "Failed to construct multi-step script for execution plan",
                                extra={"execution_plan": execution_plan},
                            )

                    # Record the generated command
                    if isinstance(command, str):
                        command_tokens = shlex.split(command)
                    elif isinstance(command, list | tuple):
                        command_tokens = list(command)
                    else:
                        command_tokens = [str(command)]
                    recorder.set_command(command_tokens)

                    # No stdout/stderr since we didn't execute anything
                    recorder.capture_output(b"", b"")

            tracker.complete_step()
            tracker.complete_execution()

            if result.get("status") == "success":
                command = result.get("data", {}).get("command")
                instructions = result.get("data", {}).get("instructions", "")

                exec_result = ToolExecutionResult(
                    execution_id=request.execution_id,
                    tool_name=request.tool_name,
                    status="success",
                    command=command,
                    result=result,
                    execution_time=time.time() - start_time,
                    metadata=self._build_provenance_metadata(
                        recorder,
                        {
                            "mode": "command_generation",
                            "instructions": instructions,
                            "tool_data": result.get("data", {}),
                        },
                    ),
                )

                # Cache result
                if self.enable_caching:
                    cache_key = self._get_cache_key(request)
                    self.execution_cache[cache_key] = exec_result
                # Record evidence
                self._record_tool_evidence(
                    tool_name=request.tool_name,
                    parameters=inferred_params,
                    command=command,
                    execution_time=exec_result.execution_time,
                    success=True,
                    result=result,
                )

                return exec_result
            else:
                raise ValueError(f"Command generation failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Command generation failed: {str(e)}")
            tracker.complete_execution(error=str(e))

            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error=str(e),
                execution_time=time.time() - start_time,
                metadata=self._build_provenance_metadata(
                    recorder,
                    {"mode": "command_generation"},
                ),
            )
        finally:
            del self.active_executions[request.execution_id]

    def _execute_api_call(
        self, request: ToolExecutionRequest, retry_count: int = 0
    ) -> ToolExecutionResult:
        """Execute tool as API call (safe operations)."""
        start_time = time.time()
        tracker = ExecutionTracker(execution_id=request.execution_id)
        self.active_executions[request.execution_id] = tracker

        parent_run_id = request.context.get("parent_run_id")
        step_id = request.context.get("step_id") or request.context.get("tool_call_id")
        recorder = self.recorder_factory.create_recorder(
            run_id=request.execution_id,
            resolver_mode="api_call",
            parent_run_id=parent_run_id,
            step_id=step_id,
        )

        try:
            with recorder:
                # Start tracking
                tracker.start_execution()
                tracker.metadata = {
                    "tool": request.tool_name,
                    "mode": "api_call",
                    "total_steps": 5,
                }

                # Step 1: Get tool
                tracker.start_step()
                tool = self._get_tool(request.tool_name)
                tracker.complete_step()

                # Step 2: Infer parameters
                tracker.start_step()
                inferred_params = self._infer_parameters(
                    tool, request.parameters, request.context
                )
                execution_base_dir = Path(
                    str(request.context.get("work_dir") or recorder.run_dir)
                )
                schema_fields = (
                    self._schema_field_names(tool.get_args_schema())
                    if tool is not None
                    else set()
                )
                inferred_params = self._normalize_output_path_parameters(
                    inferred_params,
                    base_dir=execution_base_dir,
                    schema_fields=schema_fields,
                    context_output_dir=(
                        request.context.get("output_dir")
                        if isinstance(request.context.get("output_dir"), str)
                        else None
                    ),
                )
                tracker.complete_step()

                # Step 3: Validate parameters
                tracker.start_step()
                validation_result = self._validate_parameters(
                    request.tool_name, inferred_params
                )
                recorder.add_extra(validation=validation_result)
                if not validation_result.get("valid", True):
                    logger.warning(f"Validation warnings: {validation_result}")
                tracker.complete_step()

                # Step 4: Allocate resources
                tracker.start_step()
                allocation_id = self._allocate_resources(
                    request.tool_name, request.priority, request.execution_id
                )
                tracker.complete_step()

                try:
                    # Step 5: Execute tool
                    tracker.start_step()

                    timeout = request.timeout or self.default_timeout

                    if tool is not None:
                        tool_result = self._execute_with_timeout(
                            tool, inferred_params, timeout
                        )
                    else:
                        tool_result = execute_tool(
                            request.tool_name,
                            inferred_params,
                            work_dir=request.context.get("work_dir")
                            or str(execution_base_dir),
                            output_dir=(
                                request.context.get("output_dir")
                                or inferred_params.get("output_dir")
                                or str((execution_base_dir / "outputs").resolve())
                            ),
                        )

                    if isinstance(tool_result, ToolResult):
                        result = tool_result.model_dump()
                        success = tool_result.status == "success"
                    elif isinstance(tool_result, dict):
                        result = tool_result
                        success = result.get("status") == "success"
                    else:
                        result = tool_result or {}
                        success = (
                            isinstance(result, dict)
                            and result.get("status", "success") == "success"
                        )

                    if not success:
                        logger.info(
                            "API tool %s returned error payload: %s",
                            request.tool_name,
                            result.get("error") if isinstance(result, dict) else result,
                        )

                    tracker.complete_step()
                    tracker.complete_execution()

                    recorder.add_extra(
                        outputs=(
                            result.get("outputs") if isinstance(result, dict) else None
                        )
                    )
                    if isinstance(result, dict):
                        discovered_outputs = self._discover_output_files_from_payload(
                            result,
                            base_dirs=[execution_base_dir],
                        )
                        if discovered_outputs:
                            recorder.set_outputs(discovered_outputs)
                            recorder.add_extra(output_files=discovered_outputs)
                    exec_result = ToolExecutionResult(
                        execution_id=request.execution_id,
                        tool_name=request.tool_name,
                        status="success" if success else "error",
                        result=(
                            result if isinstance(result, dict) else {"result": result}
                        ),
                        error=(
                            None
                            if success
                            else (
                                result.get("error")
                                if isinstance(result, dict)
                                else str(result)
                            )
                        ),
                        execution_time=time.time() - start_time,
                        resource_usage=self._get_resource_usage(request.execution_id),
                        metadata=self._build_provenance_metadata(
                            recorder,
                            {
                                "mode": "api_call",
                                "validation": validation_result,
                                "tool_data": result,
                            },
                        ),
                    )
                    # Record evidence
                    self._record_tool_evidence(
                        tool_name=request.tool_name,
                        parameters=inferred_params,
                        command=None,
                        execution_time=exec_result.execution_time,
                        success=success,
                        result=result,
                    )
                    return exec_result

                finally:
                    # Release resources
                    if allocation_id:
                        self.resource_manager.release_resources(request.execution_id)

        except Exception as e:
            logger.error(f"API call execution failed: {str(e)}")
            tracker.complete_execution(error=str(e))

            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error=str(e),
                execution_time=time.time() - start_time,
                retries=retry_count,
            )
        finally:
            if request.execution_id in self.active_executions:
                del self.active_executions[request.execution_id]

    def _execute_direct(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """
        Direct execution via subprocess (use with caution).
        Only for trusted, safe commands.
        """
        if self.safe_mode and request.category == ToolCategory.NEUROIMAGING:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error="Direct execution of neuroimaging tools blocked in safe mode",
            )

        start_time = time.time()

        # Create run recorder for provenance tracking
        parent_run_id = request.context.get("parent_run_id")
        step_id = request.context.get("step_id") or request.context.get("tool_call_id")
        recorder = self.recorder_factory.create_recorder(
            run_id=request.execution_id,
            resolver_mode="direct_execution",
            parent_run_id=parent_run_id,
            step_id=step_id,
        )

        try:
            # Build command from parameters
            command = request.parameters.get("command")
            if not command:
                raise ValueError("No command specified for direct execution")

            # Safety check - block potentially dangerous commands
            dangerous_patterns = ["rm -rf", "dd if=", "mkfs", "format", ":(){:|:&};:"]
            if any(pattern in command for pattern in dangerous_patterns):
                raise ValueError(f"Blocked potentially dangerous command: {command}")

            # Set recorder metadata before execution
            command_tokens = command.split() if isinstance(command, str) else command
            recorder.set_command(command_tokens)

            extra_metadata = {
                "tool_name": request.tool_name,
                "execution_mode": "direct_execution",
                "tool_category": request.category.value,
                "parameters": request.parameters,
            }

            # Add preflight report from job metadata if available (P0.2)
            if "job_store" in request.context and "job_id" in request.context:
                try:
                    job_store = request.context["job_store"]
                    job_id = request.context["job_id"]
                    # Retrieve job from store (synchronous for compatibility)
                    import asyncio

                    try:
                        running_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        running_loop = None
                    if running_loop and running_loop.is_running():
                        logger.debug(
                            "Skipping preflight report retrieval: event loop already running"
                        )
                    else:
                        loop = asyncio.get_event_loop()
                        job_record = loop.run_until_complete(job_store.get(job_id))
                        if job_record and hasattr(job_record, "metadata"):
                            if "preflight_report" in job_record.metadata:
                                extra_metadata["preflight_report"] = (
                                    job_record.metadata["preflight_report"]
                                )
                except Exception as e:
                    logger.warning(
                        f"Failed to retrieve preflight report from job metadata: {e}"
                    )

            recorder.add_extra(**extra_metadata)

            # Execute command with timeout wrapped in recorder context
            timeout = request.timeout or self.default_timeout

            logger.info(f"Executing command: {command}")

            # Check if already cancelled before starting
            if self.is_cancelled(request.execution_id):
                logger.info(
                    f"Execution {request.execution_id} cancelled before starting"
                )
                return ToolExecutionResult(
                    execution_id=request.execution_id,
                    tool_name=request.tool_name,
                    status="cancelled",
                    error="Execution cancelled before starting",
                    execution_time=time.time() - start_time,
                )

            # Track cancellation status outside recorder context
            was_cancelled = False

            with recorder:
                # Check if streaming is enabled via context
                job_store = request.context.get("job_store")
                job_id = request.context.get("job_id")
                enable_streaming = job_store is not None and job_id is not None

                # Use Popen for process group support and hard kills
                # Note: When streaming, we need binary mode (text=False) for proper offset tracking
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=not enable_streaming,  # Binary mode if streaming
                    start_new_session=True,  # Create new process group
                )

                # Track the process by execution_id
                with self._process_lock:
                    self._running_processes[request.execution_id] = proc

                try:
                    if enable_streaming:
                        # Stream output with incremental log persistence (async on background loop)
                        logger.debug(
                            f"Streaming output for execution {request.execution_id} to job {job_id}"
                        )

                        # Run async streaming in background loop
                        future = asyncio.run_coroutine_threadsafe(
                            self._stream_process_output(
                                proc=proc,
                                execution_id=request.execution_id,
                                job_store=job_store,
                                job_id=job_id,
                                timeout=timeout,
                            ),
                            self._bg_loop,
                        )

                        try:
                            stdout, stderr, returncode = future.result()
                        except Exception as e:
                            logger.error(f"Streaming failed: {e}")
                            raise
                    else:
                        # Traditional approach: wait for process to complete
                        stdout, stderr = proc.communicate(timeout=timeout)
                        returncode = proc.returncode

                except subprocess.TimeoutExpired:
                    # Timeout - kill the process group
                    logger.warning(
                        f"Command timed out after {timeout}s, killing process group"
                    )
                    with self._process_lock:
                        if proc.poll() is None:
                            try:
                                pgid = os.getpgid(proc.pid)
                                os.killpg(pgid, signal.SIGKILL)
                            except (ProcessLookupError, OSError):
                                pass
                    stdout, stderr = proc.communicate()
                    returncode = -1
                    raise subprocess.TimeoutExpired(command, timeout) from None

                finally:
                    # Check cancellation before cleanup
                    was_cancelled = request.execution_id in self._cancelled_executions

                    # Clean up process tracking and cancellation set
                    with self._process_lock:
                        self._running_processes.pop(request.execution_id, None)
                        self._cancelled_executions.discard(request.execution_id)

                # Handle cancellation
                if was_cancelled:
                    logger.info(f"Execution {request.execution_id} was cancelled")
                    returncode = -1
                    stderr = (stderr or "") + "\n[Cancelled by user]"

                # Capture output for provenance
                # Handle both string and bytes output
                stdout_bytes = (
                    stdout.encode()
                    if isinstance(stdout, str)
                    else (stdout if stdout else b"")
                )
                stderr_bytes = (
                    stderr.encode()
                    if isinstance(stderr, str)
                    else (stderr if stderr else b"")
                )
                recorder.capture_output(stdout=stdout_bytes, stderr=stderr_bytes)

            # Determine status
            if was_cancelled:
                status = "cancelled"
            elif returncode == 0:
                status = "success"
            else:
                status = "error"

            exec_result = ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status=status,
                result={"stdout": stdout, "stderr": stderr, "returncode": returncode},
                execution_time=time.time() - start_time,
                metadata=self._build_provenance_metadata(
                    recorder,
                    {"mode": "direct_execution"},
                ),
            )
            # Record evidence
            self._record_tool_evidence(
                tool_name=request.tool_name,
                parameters=request.parameters,
                command=command,
                execution_time=exec_result.execution_time,
                success=(status == "success"),
                result=exec_result.result,
            )
            return exec_result

        except subprocess.TimeoutExpired:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="timeout",
                error=f"Command timed out after {timeout} seconds",
                execution_time=timeout,
                metadata=self._build_provenance_metadata(
                    recorder,
                    {"mode": "direct_execution"},
                ),
            )
        except Exception as e:
            return ToolExecutionResult(
                execution_id=request.execution_id,
                tool_name=request.tool_name,
                status="error",
                error=str(e),
                execution_time=time.time() - start_time,
                metadata=self._build_provenance_metadata(
                    recorder,
                    {"mode": "direct_execution"},
                ),
            )

    def _execute_batch(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Execute batch of tools."""
        batch_params = request.parameters.get("batch", [])
        results = []

        for params in batch_params:
            single_request = ToolExecutionRequest(
                tool_name=request.tool_name,
                parameters=params,
                priority=request.priority,
                execution_id=f"{request.execution_id}_batch_{len(results)}",
                retry_on_failure=request.retry_on_failure,
            )
            result = self.execute(single_request)
            results.append(result)

        successful = sum(1 for r in results if r.status == "success")

        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status="success" if successful == len(results) else "partial",
            metadata={
                "mode": "batch",
                "batch_size": len(results),
                "successful": successful,
                "failed": len(results) - successful,
                "results": results,
            },
        )

    def _get_tool(self, tool_name: str) -> BRKGToolWrapper:
        """Get tool from registry or neurodesk tools."""
        for resolved in resolve_runtime_tool_ids(tool_name, include_self=True):
            tool = self.tool_registry.get_tool(resolved)
            if tool:
                return tool

        # Try neurodesk tools
        tool = self.neurodesk_tools.get_tool_by_name(tool_name)
        if tool:
            return tool

        raise ValueError(f"Tool '{tool_name}' not found")

    def _infer_parameters(
        self,
        tool: BRKGToolWrapper,
        parameters: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Infer missing parameters."""
        try:
            # Get tool schema
            schema = tool.get_args_schema()
            if not schema:
                return parameters

            required_params = []
            if hasattr(schema, "__fields__"):
                required_params = [
                    name
                    for name, field in schema.__fields__.items()
                    if field.is_required()
                ]

            # Check for missing required parameters
            missing = set(required_params) - set(parameters.keys())

            if missing:
                logger.info(f"Inferring {len(missing)} missing parameters")

                # Try inference
                if context.get("file_paths"):
                    inferred = self.parameter_inference.infer_from_bids(
                        context["file_paths"][0], tool.get_tool_name()
                    )
                    for key, value in inferred.parameters.items():
                        if key in missing:
                            parameters[key] = value

                if context.get("query"):
                    inferred = self.parameter_inference.infer_from_context(
                        context["query"], context.get("file_paths")
                    )
                    for key, value in inferred.parameters.items():
                        if key in missing:
                            parameters[key] = value

            return parameters

        except Exception as e:
            logger.warning(f"Parameter inference failed: {str(e)}")
            return parameters

    def _validate_parameters(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate parameters."""
        try:
            return self.parameter_validator.validate_parameters(tool_name, parameters)
        except Exception as e:
            logger.warning(f"Parameter validation error: {str(e)}")
            return {"valid": True, "warnings": [str(e)]}

    def _allocate_resources(
        self, tool_name: str, priority: Priority, execution_id: str = None
    ) -> str | None:
        """Allocate resources for tool."""
        try:
            # Generate execution_id if not provided
            if not execution_id:
                execution_id = f"exec_{uuid4().hex[:8]}"

            allocation = self.resource_manager.request_resources(
                tool_name=tool_name, execution_id=execution_id, priority=priority
            )
            if allocation is None:
                return None
            if isinstance(allocation, str):
                return allocation
            return getattr(allocation, "allocation_id", None)

        except Exception as e:
            logger.warning(f"Resource allocation failed: {str(e)}")
            return None

    def _execute_with_timeout(
        self, tool: BRKGToolWrapper, parameters: dict[str, Any], timeout: float
    ) -> ToolResult | dict[str, Any]:
        """Execute tool with timeout."""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tool.run, **parameters)
            try:
                result = future.result(timeout=timeout)
                return result
            except TimeoutError:
                logger.error(f"Tool execution timed out after {timeout}s")
                return {
                    "status": "error",
                    "error": f"Execution timed out after {timeout} seconds",
                }
            except Exception as e:
                logger.error(f"Tool execution failed: {str(e)}")
                return {"status": "error", "error": str(e)}

    def _get_resource_usage(self, execution_id: str | None) -> dict[str, Any]:
        """Get resource usage for allocation keyed by execution id."""
        if not execution_id or not self.resource_manager:
            return {}

        try:
            alloc_id = self.resource_manager.execution_to_allocation.get(execution_id)
            if not alloc_id:
                return {}
            allocation = self.resource_manager.allocations.get(alloc_id)
            if allocation:
                return {
                    "cpu_cores": allocation.cpu_cores,
                    "memory_gb": allocation.memory_gb,
                    "gpu_count": allocation.gpu_count,
                    "allocated_at": allocation.allocated_at.isoformat(),
                }
        except Exception as e:
            logger.warning(f"Failed to get resource usage: {str(e)}")

        return {}

    def _get_cache_key(self, request: ToolExecutionRequest) -> str:
        """Generate cache key for request."""
        import hashlib

        key_data = {
            "tool": request.tool_name,
            "params": request.parameters,
            "mode": request.mode.value if request.mode else None,
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _record_tool_evidence(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        command: str | None,
        execution_time: float,
        success: bool,
        result: ToolResult | dict[str, Any] | None = None,
    ) -> None:
        """Record tool execution evidence if a collector is configured."""
        if not self.evidence_collector:
            return
        # Try to extract version from result data/metadata if present
        version = None
        try:
            if isinstance(result, dict):
                version = (
                    result.get("metadata", {})
                    and result.get("metadata", {}).get("version")
                ) or (result.get("data", {}) and result.get("data", {}).get("version"))
            else:
                # ToolResult-like object
                version = getattr(result, "metadata", {}) and result.metadata.get(
                    "version"
                )
        except Exception:
            version = None
        try:
            self.evidence_collector.collect_tool_execution(
                tool_name=tool_name,
                version=version,
                command=command,
                parameters=parameters,
                execution_time=execution_time,
                success=success,
            )
        except Exception as e:
            logger.warning(f"Failed to record evidence for {tool_name}: {e}")

        # Capture output artifacts (e.g., multiverse convergence outputs)
        try:
            data = None
            if isinstance(result, dict):
                data = (
                    result.get("data") if isinstance(result.get("data"), dict) else None
                )
            elif result is not None and hasattr(result, "data"):
                data = result.data
            if isinstance(data, dict):
                outputs = data.get("outputs")
                if outputs:
                    self.evidence_collector.collect_output_files(tool_name, outputs)
                artifact = data.get("artifact")
                if isinstance(artifact, dict):
                    self.evidence_collector.collect_output_files(tool_name, [artifact])
                # Capture provenance or other direct file paths
                extra_paths = {
                    key: data.get(key)
                    for key in (
                        "provenance_path",
                        "design_matrix_path",
                        "residuals_path",
                    )
                    if data.get(key)
                }
                if extra_paths:
                    self.evidence_collector.collect_output_files(tool_name, extra_paths)
        except Exception as e:
            logger.warning(f"Failed to record output artifacts for {tool_name}: {e}")

    def get_execution_status(self, execution_id: str) -> dict[str, Any] | None:
        """Get status of an execution."""
        if execution_id in self.active_executions:
            tracker = self.active_executions[execution_id]
            return tracker.get_status()

        # Check history
        for result in self.execution_history:
            if result and result.execution_id == execution_id:
                return {
                    "execution_id": execution_id,
                    "status": result.status,
                    "completed": True,
                    "execution_time": result.execution_time,
                }

        return None

    def shutdown(self):
        """Shutdown the executor and cleanup resources."""
        logger.info("Shutting down ToolExecutor...")

        # Signal background loop to stop
        self._bg_loop_stop.set()
        logger.debug("Signaled background loop to stop")

        # Wake up the loop to process stop signal
        if self._bg_loop:
            try:
                self._bg_loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass  # Loop might already be stopped

        # Wait for loop thread to finish
        if self._bg_loop_thread and self._bg_loop_thread.is_alive():
            self._bg_loop_thread.join(timeout=2.0)
            if self._bg_loop_thread.is_alive():
                logger.warning(
                    "Background loop thread did not terminate cleanly within 2 seconds"
                )
            else:
                logger.debug("Background loop thread terminated")

        # Close the loop if it exists and is not closed
        if self._bg_loop and not self._bg_loop.is_closed():
            self._bg_loop.close()
            logger.debug("Background loop closed")

        # Cancel active executions
        for exec_id in list(self.active_executions.keys()):
            tracker = self.active_executions[exec_id]
            tracker.cancel_execution()

        # Shutdown thread pool
        self.executor_pool.shutdown(wait=True, cancel_futures=False)
        logger.debug("Executor pool shutdown complete")

        logger.info("ToolExecutor shutdown complete")


# ---------------------------------------------------------------------------
# Compatibility wrapper used by agent_core / web_service
# ---------------------------------------------------------------------------


class BudgetedToolExecutor(ToolExecutor):
    """Thin wrapper that adds a global budget API expected by agent_core.

    Older code imports ``BudgetedToolExecutor`` and calls
    ``execute_with_timeout(tool, args, timeout_ms, trace_id)``. This class
    adapts that call to the newer ``ToolExecutor`` implementation.
    """

    def __init__(
        self,
        global_budget_ms: int | None = None,
        use_subprocess: bool = False,
        **kwargs,
    ):
        # ``use_subprocess`` kept for signature compatibility (unused here)
        super().__init__(**kwargs)
        if global_budget_ms is None:
            from brain_researcher.services.shared.retry_timeout import (
                load_timeout_config,
            )

            global_budget_ms = load_timeout_config().tool_execution_budget_ms
        self.global_budget_ms = global_budget_ms
        self.use_subprocess = use_subprocess

    def execute_with_timeout(
        self,
        tool: BRKGToolWrapper,
        args: dict[str, Any],
        timeout_ms: int | None = None,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
    ):
        """Execute a tool with an optional timeout (milliseconds).

        Returns a ``ToolResult`` to match legacy expectations.
        """
        from brain_researcher.services.tools.tool_base import ToolResult

        timeout_s = (timeout_ms or self.global_budget_ms) / 1000.0
        effective_context = context or {}
        request = ToolExecutionRequest(
            tool_name=tool.get_tool_name(),
            parameters=args,
            timeout=timeout_s,
            context=effective_context,
            retry_on_failure=bool(effective_context.get("retry_on_failure", True)),
            max_retries=int(effective_context.get("max_retries", 3)),
        )

        try:
            exec_result = self.execute(request)
            # exec_result is ToolExecutionResult; adapt to ToolResult
            payload = exec_result.result or {}
            from brain_researcher.services.tools.tool_base import ToolResult as TR

            if isinstance(payload, TR):
                payload = payload.model_dump()
            elif not isinstance(payload, dict):
                payload = {"result": payload}
            error_message = exec_result.error
            if not error_message and isinstance(payload, dict):
                error_message = payload.get("error")
            metadata: dict[str, Any] = dict(exec_result.metadata or {})
            metadata.update(
                {
                    "execution_id": exec_result.execution_id,
                    "trace_id": trace_id,
                }
            )

            if exec_result.status != "success":
                from brain_researcher.services.agent.error_taxonomy import (
                    classify_failure,
                )

                returncode = None
                stderr = None
                if isinstance(payload, dict):
                    returncode = payload.get("returncode")
                    stderr = payload.get("stderr")

                taxonomy = classify_failure(
                    status=exec_result.status,
                    error_message=error_message,
                    exception=None,
                    returncode=returncode,
                    stderr=stderr,
                )

                metadata["error_category"] = (
                    exec_result.error_category
                    or (exec_result.metadata or {})
                    .get("error_taxonomy", {})
                    .get("category")
                    or taxonomy.category.value
                )
                metadata["is_retryable"] = (
                    exec_result.is_retryable
                    if exec_result.is_retryable is not None
                    else taxonomy.is_retryable
                )
                metadata["recovery_strategy"] = (
                    exec_result.recovery_strategy or taxonomy.recovery_action.value
                )
                metadata["recovery_suggestions"] = list(
                    exec_result.recovery_suggestions or []
                ) or list(taxonomy.recovery_suggestions)
                metadata["error_taxonomy"] = (exec_result.metadata or {}).get(
                    "error_taxonomy"
                ) or taxonomy.to_dict()

            return ToolResult(
                status=exec_result.status,
                data=payload if exec_result.status == "success" else None,
                error=error_message,
                metadata=metadata,
            )
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("BudgetedToolExecutor failed: %s", exc)
            return ToolResult(status="error", error=str(exc))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False
