"""Plan execution + streaming engine for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the large ``_execute_plan_with_streaming``
SSE engine plus the streaming/job helpers ``_proxy_plan_stream`` /
``_stream_stub_plan_events`` / ``_submit_plan_job``.

These are pure orchestration over web_service's helpers + globals; everything
they need from web_service (helpers, the ``_KG_WRITE_*`` executor/semaphore,
``_PLAN_CACHE``, ``_metrics``, ``logger``, the ``PlanAllowlistError`` class) stays
in ``web_service`` and is imported back LAZILY inside each function (read at call
time). This module imports its third-party/type deps directly, so it imports
nothing from web_service at module load → cycle-free. ``web_service`` re-exports
the functions so the routes that delegate to them (agent_run_plan_contract et al)
and ``_stream_stub_plan_events`` callers keep resolving.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from flask import Response, g, stream_with_context

from brain_researcher.services.agent.planner.catalog_loader import get_tool_by_id
from brain_researcher.services.agent.planner.models import RunPlanRequest, StepSpec


def _proxy_plan_stream(job_info: dict[str, Any]) -> Response:
    """Stream orchestrator job events back to the caller as SSE."""
    from brain_researcher.services.agent.web_service import (
        _absolute_orchestrator_url,
        _format_sse,
        logger,
    )

    stream_url = job_info.get("stream_url_abs") or _absolute_orchestrator_url(
        job_info.get("stream_url", "")
    )
    accepted_payload = {
        "job_id": job_info.get("job_id"),
        "plan_id": job_info.get("plan_id"),
        "status_url": job_info.get("status_url"),
        "stream_url": job_info.get("stream_url"),
    }

    def event_stream():
        yield _format_sse("accepted", accepted_payload)
        try:
            with requests.get(
                stream_url,
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=(5, None),
            ) as upstream:
                upstream.raise_for_status()
                for chunk in upstream.iter_lines(decode_unicode=True):
                    if chunk is None:
                        continue
                    if chunk == "":
                        yield "\n"
                    else:
                        yield chunk + "\n"
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            logger.error(
                "Failed to proxy plan SSE for %s: %s", job_info.get("job_id"), exc
            )
            yield _format_sse("agent_error", {"error": str(exc)})

    headers = {"X-Run-ID": job_info.get("job_id", "")}
    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers=headers,
    )


def _execute_plan_with_streaming(run_request: RunPlanRequest):
    """Execute plan steps with real tool execution and SSE streaming.

    PR-4: Replaces stub implementation with real execution via ToolHub.
    """
    from brain_researcher.services.agent.error_taxonomy import classify_failure
    from brain_researcher.services.agent.tool_executor import BudgetedToolExecutor
    from brain_researcher.services.agent.web_service import (
        _KG_WRITE_EXECUTOR,
        _KG_WRITE_SEMAPHORE,
        _PLAN_CACHE,
        _filter_fallback_tools,
        _format_sse,
        _get_plan_memory,
        _get_recovery_router,
        _infer_tool_family,
        _is_retryable_error,
        _kg_write_timeout_seconds,
        _kg_write_with_release,
        _metrics,
        _resolve_runtime_tool_instance,
        _warn_failure_once,
        logger,
    )
    from brain_researcher.services.tools.executors import (
        RunRecorder,
        prepare_child_summary_extra,
    )

    cached_plan = (
        run_request.plan.model_dump(mode="json")
        if run_request.plan is not None
        else _PLAN_CACHE.get(run_request.plan_id)
    )
    if not cached_plan:
        raise ValueError(
            f"Unknown plan_id {run_request.plan_id}. Must POST /agent/plan before /agent/run_plan."
        )

    dag_payload = cached_plan.get("dag") or {}
    steps_payload = cached_plan.get("steps") or dag_payload.get("steps") or []
    artifacts_payload = (
        cached_plan.get("artifacts") or dag_payload.get("artifacts") or []
    )

    steps: list[dict[str, Any]] = (
        steps_payload if isinstance(steps_payload, list) else []
    )

    artifact_lookup: dict[str, dict[str, Any]] = {}
    if isinstance(artifacts_payload, dict):
        artifact_lookup = artifacts_payload
    elif isinstance(artifacts_payload, list):
        for spec in artifacts_payload:
            if isinstance(spec, dict):
                name = spec.get("name")
                if name:
                    artifact_lookup[name] = spec

    def _produced_artifacts(step: dict[str, Any]) -> list[dict[str, Any]]:
        produced: list[dict[str, Any]] = []
        for artifact_name in (step.get("produces") or {}).values():
            spec = artifact_lookup.get(artifact_name)
            if spec:
                produced.append(spec)
        return produced

    def _collect_fallback_tools(
        step: dict[str, Any],
        tool_id: str,
        step_idx: int,
        failure_taxonomy,
        params: dict[str, Any],
        failed_tools: set[str],
    ):
        """Select fallback tools using recovery policy + routing hints."""
        from brain_researcher.services.agent.recovery_policy import (
            select_recovery_decision,
        )

        plan_candidates = (
            cached_plan.get("candidates")
            if isinstance(cached_plan.get("candidates"), list)
            else None
        )
        query_text = (
            cached_plan.get("query")
            or cached_plan.get("user_query")
            or cached_plan.get("prompt")
        )
        step_metadata = (
            dict(step.get("metadata") or {})
            if isinstance(step.get("metadata"), dict)
            else {}
        )
        if not step_metadata.get("tool_family") and not step_metadata.get("family"):
            inferred_family = _infer_tool_family(tool_id)
            if inferred_family:
                step_metadata["tool_family"] = inferred_family
        decision = select_recovery_decision(
            taxonomy=failure_taxonomy,
            tool_id=tool_id,
            step_metadata=step_metadata,
            step_idx=step_idx,
            plan_candidates=plan_candidates,
            query=query_text,
            router=_get_recovery_router(),
            failed_tools=failed_tools,
            params=params,
        )
        if decision.fallback_tools:
            try:
                step_payload = {
                    key: step.get(key)
                    for key in (
                        "id",
                        "tool",
                        "consumes",
                        "produces",
                        "params",
                        "metadata",
                        "runtime_kind",
                    )
                    if key in step
                }
                step_spec = StepSpec(**step_payload)
            except Exception:
                step_spec = None
            if step_spec:
                decision.fallback_tools = _filter_fallback_tools(
                    step_spec, list(decision.fallback_tools), strict=True
                )
        return decision

    def _generator():
        # Create parent RunRecorder for the entire plan
        parent_recorder = RunRecorder(
            run_id=run_request.plan_id,
            resolver_mode="catalog",
            parent_run_id=None,
            step_id=None,
            attempt=1,
        )

        # Initialize tool executor
        executor = BudgetedToolExecutor(
            global_budget_ms=300000,  # 5 minutes for plan execution
            use_subprocess=False,
        )
        failed_tools: set[str] = set()
        failed_steps: list[dict[str, Any]] = []

        def _record_failure_memory(
            *,
            plan_id: str,
            step_id: str,
            tool_id: str,
            taxonomy,
            error_message: str,
            attempt: int | None,
            max_attempts: int | None,
            recovered: bool | None,
            recovery_actions: list[dict[str, Any]] | None,
        ) -> None:
            from brain_researcher.core.contracts.loop_signals import parse_loop_signals
            from brain_researcher.services.agent.planner.kg_utils import (
                extract_dataset_from_context,
                extract_task_family,
                normalize_dataset_id,
                normalize_tool_id,
            )

            def _truthy(value: str | None) -> bool:
                return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}

            log_to_memory = _truthy(os.getenv("BR_PLAN_MEMORY_LOG_FAILURES", "true"))
            kg_write = _truthy(os.getenv("BR_KG_FAILURE_WRITEBACK")) or _truthy(
                os.getenv("BR_KG_WRITEBACK")
            )
            if not log_to_memory and not kg_write:
                return

            failure_id = None
            # Context used for dataset/task extraction
            ctx = (
                (cached_plan.get("context") or {})
                if isinstance(cached_plan, dict)
                else {}
            )
            dataset_id_raw = extract_dataset_from_context(ctx)
            dataset_id = normalize_dataset_id(dataset_id_raw)
            task_family = extract_task_family(
                ctx,
                cached_plan.get("pipeline") if isinstance(cached_plan, dict) else None,
            )
            tool_key = normalize_tool_id(tool_id)
            loop_signals = parse_loop_signals(
                cached_plan.get("loop_signals") if isinstance(cached_plan, dict) else []
            )
            if not loop_signals:
                loop_signals = parse_loop_signals(
                    ctx.get("loop_signals") if isinstance(ctx, dict) else []
                )

            if log_to_memory:
                plan_memory = _get_plan_memory()
                if not plan_memory:
                    _metrics.increment("plan_memory_failure_write_errors_total")
                    _warn_failure_once(
                        "plan_memory",
                        plan_id,
                        "PlanMemory unavailable; failure record not persisted for plan "
                        f"{plan_id}.",
                    )
                else:
                    try:
                        ctx = (
                            (cached_plan.get("context") or {})
                            if isinstance(cached_plan, dict)
                            else {}
                        )
                        user_id = ctx.get("user_id") or ctx.get("account_id")
                        workspace_id = ctx.get("workspace_id") or ctx.get("org_id")
                        plan_memory.ensure_plan_record(
                            plan_id=plan_id,
                            plan=cached_plan if isinstance(cached_plan, dict) else None,
                            query=ctx.get("query"),
                            user_id=user_id,
                            workspace_id=workspace_id,
                        )
                        failure_id = plan_memory.record_failure(
                            plan_id=plan_id,
                            step_id=step_id,
                            tool_id=tool_key,
                            error_category=(
                                getattr(taxonomy, "category", None).value
                                if getattr(taxonomy, "category", None)
                                else None
                            ),
                            recovery_action=(
                                getattr(taxonomy, "recovery_action", None).value
                                if getattr(taxonomy, "recovery_action", None)
                                else None
                            ),
                            is_retryable=getattr(taxonomy, "is_retryable", None),
                            error_message=error_message,
                            error_taxonomy=(
                                taxonomy.to_dict()
                                if hasattr(taxonomy, "to_dict")
                                else None
                            ),
                            recovery_actions=recovery_actions,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            recovered=recovered,
                        )
                        _metrics.increment("plan_memory_failure_writes_total")
                    except Exception as exc:  # pragma: no cover - best effort
                        _metrics.increment("plan_memory_failure_write_errors_total")
                        _warn_failure_once(
                            "plan_memory",
                            plan_id,
                            "PlanMemory failure record write failed for plan "
                            f"{plan_id}: {exc}",
                        )

            if kg_write:
                if not failure_id:
                    failure_id = f"fail_{uuid.uuid4().hex[:12]}"
                try:
                    from brain_researcher.services.agent.planner.failure_neo4j import (
                        FailureKGRecord,
                        get_default_failure_writer,
                    )
                    from brain_researcher.services.agent.planner.kg_bridge import (
                        resolve_dataset_id,
                    )

                    writer = get_default_failure_writer()
                    if not writer:
                        _metrics.increment("kg_failure_write_errors_total")
                        _metrics.increment(
                            "kg_writeback_fail_total",
                            labels={"type": "failure"},
                        )
                        _warn_failure_once(
                            "kg",
                            plan_id,
                            "KG failure writeback unavailable; skipping for plan "
                            f"{plan_id}.",
                        )
                        return
                    if not _KG_WRITE_SEMAPHORE.acquire(blocking=False):
                        _metrics.increment("kg_failure_write_errors_total")
                        _metrics.increment(
                            "kg_writeback_fail_total",
                            labels={"type": "failure"},
                        )
                        _warn_failure_once(
                            "kg",
                            plan_id,
                            "KG failure writeback skipped due to saturation for plan "
                            f"{plan_id}.",
                        )
                        return
                    resolved_ds = resolve_dataset_id(dataset_id) or dataset_id

                    record = FailureKGRecord(
                        failure_id=failure_id,
                        plan_id=plan_id,
                        step_id=step_id,
                        tool_id=tool_key,
                        tool_version_id=(
                            getattr(get_tool_by_id(tool_key), "entrypoint", None)
                            if tool_key
                            else None
                        ),
                        error_category=(
                            getattr(taxonomy, "category", None).value
                            if getattr(taxonomy, "category", None)
                            else None
                        ),
                        recovery_action=(
                            getattr(taxonomy, "recovery_action", None).value
                            if getattr(taxonomy, "recovery_action", None)
                            else None
                        ),
                        is_retryable=getattr(taxonomy, "is_retryable", None),
                        error_message=error_message,
                        error_taxonomy=(
                            taxonomy.to_dict() if hasattr(taxonomy, "to_dict") else None
                        ),
                        recovery_actions=recovery_actions,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        recovered=recovered,
                        created_at=int(time.time()),
                        dataset_id=resolved_ds,
                        task_family=task_family,
                        run_id=run_request.plan_id,
                        loop_signals=tuple(loop_signals),
                    )
                    timeout_s = _kg_write_timeout_seconds()
                    try:
                        future = _KG_WRITE_EXECUTOR.submit(
                            _kg_write_with_release, writer, record
                        )
                    except Exception as exc:
                        _KG_WRITE_SEMAPHORE.release()
                        _metrics.increment("kg_failure_write_errors_total")
                        _metrics.increment(
                            "kg_writeback_fail_total",
                            labels={"type": "failure"},
                        )
                        _warn_failure_once(
                            "kg",
                            plan_id,
                            "KG failure writeback submission failed for plan "
                            f"{plan_id}: {exc}",
                        )
                        return
                    try:
                        future.result(timeout=timeout_s)
                        _metrics.increment("kg_failure_writes_total")
                    except concurrent.futures.TimeoutError:
                        # Best-effort cancel; the task may already be running.
                        if future.cancel():
                            _KG_WRITE_SEMAPHORE.release()
                        _metrics.increment("kg_failure_write_errors_total")
                        _metrics.increment(
                            "kg_writeback_timeout_total",
                            labels={"type": "failure"},
                        )
                        _warn_failure_once(
                            "kg",
                            plan_id,
                            "KG failure writeback timed out after "
                            f"{timeout_s:.1f}s for plan {plan_id}.",
                        )
                    except Exception as exc:  # pragma: no cover - best effort
                        _metrics.increment("kg_failure_write_errors_total")
                        _metrics.increment(
                            "kg_writeback_fail_total",
                            labels={"type": "failure"},
                        )
                        _warn_failure_once(
                            "kg",
                            plan_id,
                            f"KG failure writeback failed for plan {plan_id}: {exc}",
                        )
                except Exception as exc:  # pragma: no cover - best effort
                    _metrics.increment("kg_failure_write_errors_total")
                    _metrics.increment(
                        "kg_writeback_fail_total",
                        labels={"type": "failure"},
                    )
                    _warn_failure_once(
                        "kg",
                        plan_id,
                        f"KG failure writeback setup failed for plan {plan_id}: {exc}",
                    )

        try:
            with parent_recorder:
                for step_idx, step in enumerate(steps):
                    step_id = step.get("id", f"step_{step_idx:03d}")
                    tool_id = step.get("tool")
                    params = step.get("params", {})
                    original_tool_id = tool_id
                    step_tool_family = _infer_tool_family(tool_id)
                    step_metadata = (
                        step.get("metadata") if isinstance(step, dict) else None
                    )
                    if (
                        step_tool_family
                        and isinstance(step_metadata, dict)
                        and not step_metadata.get("tool_family")
                        and not step_metadata.get("family")
                    ):
                        step_metadata["tool_family"] = step_tool_family
                        step["metadata"] = step_metadata

                    # Emit step_started
                    yield _format_sse(
                        "step_started",
                        {
                            "plan_id": run_request.plan_id,
                            "version": run_request.version,
                            "step_id": step_id,
                            "tool": tool_id,
                        },
                    )

                    # PR-4 Issue #4: Cache checking before execution
                    cache_key = None
                    try:
                        from brain_researcher.services.shared.cache_key import (
                            build_cache_key,
                        )
                        from brain_researcher.services.shared.cache_store_registry import (
                            peek_initialized_cache_store,
                        )

                        # Compute cache key
                        cache_key = build_cache_key(
                            tool=str(tool_id or "<unknown_tool>"),
                            tool_version=None,
                            canonical_params=params or {},
                            input_paths=[],  # TODO: Extract from step consumes / attachments
                            container_image="__missing_container__",
                            mode=os.getenv("BR_CACHE_MODE", "fast"),
                        )

                        # Check cache (async call in sync context)
                        cache_store = peek_initialized_cache_store()
                        if cache_store:
                            cache_entry = asyncio.run(cache_store.lookup(cache_key))
                            if cache_entry and cache_entry.state == "completed":
                                # CACHE HIT - skip execution
                                logger.info(
                                    f"Cache hit for step {step_id}, cache_key={cache_key}"
                                )

                                yield _format_sse(
                                    "step_cache_hit",
                                    {
                                        "plan_id": run_request.plan_id,
                                        "version": run_request.version,
                                        "step_id": step_id,
                                        "tool": tool_id,
                                        "cache_key": cache_key,
                                        "cached_run_dir": cache_entry.run_dir,
                                    },
                                )

                                # Skip retry loop - use cached outputs
                                retry_successful = True
                                outputs = {}  # TODO: Load from cached run_dir if needed
                                last_error = None
                                step_recorder = None

                                # Record cache hit in parent
                                parent_recorder.add_child_summary(
                                    step_id=step_id,
                                    state="succeeded",
                                    run_dir=Path(cache_entry.run_dir),
                                    extra={
                                        "cache": {
                                            "cache_key": cache_key,
                                            "cache_hit": True,
                                        },
                                        "execution_time_ms": 0,
                                        "attempt": 1,
                                        "max_attempts": 1,
                                        **(
                                            {"tool_family": step_tool_family}
                                            if step_tool_family
                                            else {}
                                        ),
                                    },
                                )

                                # Continue to next step
                                continue
                            elif cache_entry and cache_entry.state == "pending":
                                # Another worker is computing - log and proceed anyway
                                logger.info(
                                    f"Cache pending for step {step_id}, executing anyway"
                                )
                    except Exception as cache_exc:
                        # Cache check failed - log but continue with execution
                        logger.warning(
                            f"Cache check failed for step {step_id}: {cache_exc}",
                            exc_info=True,
                        )

                    # PR-4 Phase 3: Retry logic with exponential backoff
                    max_attempts = 3  # TODO: Make configurable per tool
                    retry_successful = False
                    last_error = None
                    outputs = {}
                    step_recorder = None

                    for attempt in range(1, max_attempts + 1):
                        # Create child RunRecorder for this attempt
                        step_recorder = RunRecorder(
                            run_id=f"{run_request.plan_id}_step_{step_idx}",
                            resolver_mode="catalog",
                            parent_run_id=run_request.plan_id,
                            step_id=step_id,
                            attempt=attempt,
                        )

                        # PR-4 Issue #4: Add cache metadata to recorder
                        if cache_key:
                            step_recorder.add_extra(
                                cache_key=cache_key,
                                cache_hit=False,  # This is a cache miss (we're executing)
                            )
                        if step_tool_family:
                            step_recorder.add_extra(tool_family=step_tool_family)

                        # Emit retry event if this is a retry
                        if attempt > 1:
                            yield _format_sse(
                                "step_retry_started",
                                {
                                    "plan_id": run_request.plan_id,
                                    "version": run_request.version,
                                    "step_id": step_id,
                                    "tool": tool_id,
                                    "attempt": attempt,
                                    "max_attempts": max_attempts,
                                    "reason": str(last_error),
                                },
                            )

                        try:
                            # Get tool from catalog
                            tool = get_tool_by_id(tool_id)
                            if not tool:
                                raise ValueError(f"Tool {tool_id} not found in catalog")

                            # Emit step_executing (on first attempt or retry)
                            if attempt == 1:
                                yield _format_sse(
                                    "step_executing",
                                    {
                                        "plan_id": run_request.plan_id,
                                        "version": run_request.version,
                                        "step_id": step_id,
                                        "tool": tool_id,
                                    },
                                )

                            # Execute tool with RunRecorder
                            with step_recorder:
                                # Get the actual tool instance from agent registry
                                _, tool_instance = _resolve_runtime_tool_instance(
                                    tool_id
                                )

                                # PR-4 Issue #3: Hard failure when tool not found
                                if not tool_instance:
                                    raise ValueError(
                                        f"Tool '{tool_id}' found in catalog but not registered in agent runtime. "
                                        f"This indicates a registration bug or missing tool implementation."
                                    )

                                # Execute via tool executor
                                result = executor.execute_with_timeout(
                                    tool=tool_instance,
                                    args=params,
                                    timeout_ms=None,
                                    trace_id=getattr(g, "trace_id", None),
                                )

                                if result.status == "success":
                                    payload = getattr(result, "data", None)
                                    outputs = (
                                        payload
                                        if isinstance(payload, dict)
                                        else {"result": payload}
                                    )
                                else:
                                    raise RuntimeError(
                                        result.error or "Tool execution failed"
                                    )

                            # PR-4 Issue #4: Mark cache as completed after successful execution
                            if cache_key and cache_store and step_recorder:
                                try:
                                    asyncio.run(
                                        cache_store.mark_completed(
                                            cache_key=cache_key,
                                            run_id=(
                                                step_recorder.run_id
                                                if step_recorder
                                                else run_request.plan_id
                                            ),
                                            run_dir=(
                                                str(step_recorder.run_dir)
                                                if step_recorder
                                                else ""
                                            ),
                                            size_bytes=None,  # TODO: Compute output size
                                        )
                                    )
                                    logger.info(
                                        f"Marked cache entry as completed: {cache_key}"
                                    )
                                except Exception as cache_exc:
                                    logger.warning(
                                        f"Failed to mark cache as completed: {cache_exc}"
                                    )

                            # Success - break out of retry loop
                            retry_successful = True
                            break

                        except Exception as e:
                            last_error = e
                            logger.warning(
                                f"Step {step_id} attempt {attempt} failed: {e}"
                            )

                            # Check if we should retry
                            if attempt < max_attempts and _is_retryable_error(e):
                                # Exponential backoff: 2^attempt seconds
                                backoff_seconds = 2**attempt
                                logger.info(
                                    f"Retrying step {step_id} in {backoff_seconds}s (attempt {attempt + 1}/{max_attempts})"
                                )
                                time.sleep(backoff_seconds)
                                continue
                            else:
                                # No more retries or non-retryable error
                                logger.error(
                                    f"Step {step_id} failed permanently after {attempt} attempt(s): {e}",
                                    exc_info=True,
                                )
                                break

                    # Check if we succeeded after retries
                    if retry_successful:
                        # Success - emit step_completed
                        produced_meta = _produced_artifacts(step)
                        yield _format_sse(
                            "step_completed",
                            {
                                "plan_id": run_request.plan_id,
                                "version": run_request.version,
                                "step_id": step_id,
                                "tool": tool_id,
                                "state": "succeeded",
                                "attempt": (
                                    step_recorder.attempt if step_recorder else 1
                                ),
                                "message": f"{tool_id} completed successfully",
                                "produces": produced_meta if produced_meta else outputs,
                            },
                        )

                        # Add to parent recorder with PR-4 fields
                        parent_recorder.add_child_summary(
                            step_id=step_id,
                            state="succeeded",
                            run_dir=step_recorder.run_dir,
                            extra={
                                **prepare_child_summary_extra(
                                    child_recorder=step_recorder,
                                    max_attempts=max_attempts,
                                    outputs=outputs,
                                ),
                                **(
                                    {"tool_family": step_tool_family}
                                    if step_tool_family
                                    else {}
                                ),
                            },
                        )
                    else:
                        failure_taxonomy = classify_failure(
                            status="error",
                            error_message=str(last_error),
                        )
                        initial_failure_taxonomy = failure_taxonomy
                        original_error_message = str(last_error)
                        failed_tools.add(original_tool_id)
                        decision = _collect_fallback_tools(
                            step,
                            tool_id,
                            step_idx,
                            failure_taxonomy,
                            params,
                            failed_tools,
                        )
                        fallback_tools = decision.fallback_tools
                        adjusted_params = decision.adjusted_params
                        recovery_attempts: list[dict[str, Any]] = [
                            {
                                "policy_action": decision.action.value,
                                "policy_reason": decision.reason,
                            }
                        ]
                        recovered = False

                        # Optional: retry same tool with safe parameter adjustments.
                        param_retry_flag = os.getenv(
                            "BR_RECOVERY_PARAM_RETRY", "true"
                        ).lower()
                        if adjusted_params and param_retry_flag not in {
                            "0",
                            "false",
                            "no",
                        }:
                            try:
                                from brain_researcher.services.agent.planner_state import (
                                    PlannerEvent,
                                    PlannerEventLogger,
                                    PlannerEventType,
                                )

                                PlannerEventLogger(run_id=run_request.plan_id).log(
                                    PlannerEvent(
                                        event_type=PlannerEventType.RECOVERY_TRIGGERED,
                                        payload={
                                            "reason": "param_adjustment_retry",
                                            "policy_reason": decision.reason,
                                            "tool": tool_id,
                                            "step_id": step_id,
                                            "error": str(last_error),
                                            "error_taxonomy": failure_taxonomy.to_dict(),
                                        },
                                    )
                                )
                            except Exception:
                                pass

                            yield _format_sse(
                                "step_retry_started",
                                {
                                    "plan_id": run_request.plan_id,
                                    "version": run_request.version,
                                    "step_id": step_id,
                                    "tool": tool_id,
                                    "attempt": 1,
                                    "max_attempts": 1,
                                    "reason": (
                                        f"recovery_triggered: param_adjustment_retry [{decision.reason}]"
                                    ),
                                },
                            )

                            step_recorder = RunRecorder(
                                run_id=f"{run_request.plan_id}_step_{step_idx}_param_adjusted",
                                resolver_mode="catalog",
                                parent_run_id=run_request.plan_id,
                                step_id=step_id,
                                attempt=1,
                            )
                            if step_tool_family:
                                step_recorder.add_extra(tool_family=step_tool_family)
                            try:
                                tool = get_tool_by_id(tool_id)
                                if not tool:
                                    raise ValueError(
                                        f"Tool {tool_id} not found in catalog"
                                    )

                                with step_recorder:
                                    _, tool_instance = _resolve_runtime_tool_instance(
                                        tool_id
                                    )
                                    if not tool_instance:
                                        raise ValueError(
                                            f"Tool '{tool_id}' selected for retry but not registered in agent runtime"
                                        )
                                    result = executor.execute_with_timeout(
                                        tool=tool_instance,
                                        args=adjusted_params,
                                        timeout_ms=None,
                                        trace_id=getattr(g, "trace_id", None),
                                    )
                                    if result.status != "success":
                                        raise RuntimeError(
                                            result.error
                                            or "Adjusted retry execution failed"
                                        )
                                    outputs = (
                                        result.output
                                        if isinstance(result.output, dict)
                                        else {"result": result.output}
                                    )

                                produced_meta = _produced_artifacts(step)
                                yield _format_sse(
                                    "step_completed",
                                    {
                                        "plan_id": run_request.plan_id,
                                        "version": run_request.version,
                                        "step_id": step_id,
                                        "tool": tool_id,
                                        "state": "succeeded",
                                        "attempt": 1,
                                        "message": f"{tool_id} completed successfully (param-adjusted retry)",
                                        "produces": (
                                            produced_meta if produced_meta else outputs
                                        ),
                                        "recovery": {
                                            "from_tool": original_tool_id,
                                            "to_tool": tool_id,
                                            "mode": "param_adjustment",
                                        },
                                        **(
                                            {"tool_family": step_tool_family}
                                            if step_tool_family
                                            else {}
                                        ),
                                    },
                                )

                                parent_recorder.add_child_summary(
                                    step_id=step_id,
                                    state="succeeded",
                                    run_dir=step_recorder.run_dir,
                                    extra={
                                        **prepare_child_summary_extra(
                                            child_recorder=step_recorder,
                                            max_attempts=1,
                                            outputs=outputs,
                                        ),
                                        "recovery": {
                                            "from_tool": original_tool_id,
                                            "to_tool": tool_id,
                                            "mode": "param_adjustment",
                                        },
                                    },
                                )
                                recovery_attempts.append(
                                    {
                                        "tool": tool_id,
                                        "status": "success",
                                        "mode": "param_adjustment",
                                    }
                                )
                                _record_failure_memory(
                                    plan_id=run_request.plan_id,
                                    step_id=step_id,
                                    tool_id=original_tool_id,
                                    taxonomy=initial_failure_taxonomy,
                                    error_message=original_error_message,
                                    attempt=(
                                        step_recorder.attempt
                                        if step_recorder
                                        else max_attempts
                                    ),
                                    max_attempts=max_attempts,
                                    recovered=True,
                                    recovery_actions=recovery_attempts,
                                )
                                recovered = True
                            except Exception as retry_exc:
                                last_error = retry_exc
                                failure_taxonomy = classify_failure(
                                    status="error",
                                    error_message=str(last_error),
                                )
                                recovery_attempts.append(
                                    {
                                        "tool": tool_id,
                                        "status": "failed",
                                        "mode": "param_adjustment",
                                        "error": str(retry_exc),
                                    }
                                )

                        if recovered:
                            continue

                        if fallback_tools:
                            for fb_idx, fallback_tool_id in enumerate(
                                fallback_tools, start=1
                            ):
                                # Log recovery event (append-only) for UI/analytics.
                                try:
                                    from brain_researcher.services.agent.planner_state import (
                                        PlannerEvent,
                                        PlannerEventLogger,
                                        PlannerEventType,
                                    )

                                    PlannerEventLogger(run_id=run_request.plan_id).log(
                                        PlannerEvent(
                                            event_type=PlannerEventType.RECOVERY_TRIGGERED,
                                            payload={
                                                "reason": "tool_substitute_after_failure",
                                                "policy_reason": decision.reason,
                                                "from_tool": tool_id,
                                                "to_tool": fallback_tool_id,
                                                "step_id": step_id,
                                                "error": str(last_error),
                                                "error_taxonomy": failure_taxonomy.to_dict(),
                                            },
                                            diff={
                                                "rejected_add": [f"hyp:{tool_id}"],
                                                "selected_branch_id_set": f"br:{fallback_tool_id}",
                                                "selected_tool_ids_set": [
                                                    fallback_tool_id
                                                ],
                                            },
                                        )
                                    )
                                except Exception:
                                    pass

                                # Attempt executing the fallback tool once (no retries) to keep behavior bounded.
                                yield _format_sse(
                                    "step_retry_started",
                                    {
                                        "plan_id": run_request.plan_id,
                                        "version": run_request.version,
                                        "step_id": step_id,
                                        "tool": fallback_tool_id,
                                        "attempt": 1,
                                        "max_attempts": 1,
                                        "reason": (
                                            f"recovery_triggered: substitute tool after failure "
                                            f"({tool_id} -> {fallback_tool_id}) [{decision.reason}]"
                                        ),
                                    },
                                )

                                tool_id = fallback_tool_id
                                fallback_family = _infer_tool_family(fallback_tool_id)
                                step_recorder = RunRecorder(
                                    run_id=f"{run_request.plan_id}_step_{step_idx}_fallback_{fb_idx}",
                                    resolver_mode="catalog",
                                    parent_run_id=run_request.plan_id,
                                    step_id=step_id,
                                    attempt=1,
                                )
                                if fallback_family:
                                    step_recorder.add_extra(tool_family=fallback_family)
                                try:
                                    tool = get_tool_by_id(tool_id)
                                    if not tool:
                                        raise ValueError(
                                            f"Tool {tool_id} not found in catalog"
                                        )

                                    with step_recorder:
                                        _, tool_instance = (
                                            _resolve_runtime_tool_instance(tool_id)
                                        )
                                        if not tool_instance:
                                            raise ValueError(
                                                f"Tool '{tool_id}' selected for fallback but not registered in agent runtime"
                                            )
                                        result = executor.execute_with_timeout(
                                            tool=tool_instance,
                                            args=params,
                                            timeout_ms=None,
                                            trace_id=getattr(g, "trace_id", None),
                                        )
                                        if result.status != "success":
                                            raise RuntimeError(
                                                result.error
                                                or "Fallback tool execution failed"
                                            )
                                        outputs = (
                                            result.output
                                            if isinstance(result.output, dict)
                                            else {"result": result.output}
                                        )

                                    # Success - emit step_completed and continue to next step.
                                    produced_meta = _produced_artifacts(step)
                                    yield _format_sse(
                                        "step_completed",
                                        {
                                            "plan_id": run_request.plan_id,
                                            "version": run_request.version,
                                            "step_id": step_id,
                                            "tool": tool_id,
                                            "state": "succeeded",
                                            "attempt": 1,
                                            "message": f"{tool_id} completed successfully (recovered from {original_tool_id})",
                                            "produces": (
                                                produced_meta
                                                if produced_meta
                                                else outputs
                                            ),
                                            "recovery": {
                                                "from_tool": original_tool_id,
                                                "to_tool": tool_id,
                                            },
                                        },
                                    )

                                    parent_recorder.add_child_summary(
                                        step_id=step_id,
                                        state="succeeded",
                                        run_dir=step_recorder.run_dir,
                                        extra={
                                            **prepare_child_summary_extra(
                                                child_recorder=step_recorder,
                                                max_attempts=1,
                                                outputs=outputs,
                                            ),
                                            "recovery": {
                                                "from_tool": original_tool_id,
                                                "to_tool": tool_id,
                                            },
                                            **(
                                                {"tool_family": fallback_family}
                                                if fallback_family
                                                else {}
                                            ),
                                        },
                                    )
                                    recovery_attempts.append(
                                        {
                                            "tool": fallback_tool_id,
                                            "status": "success",
                                            "recovery": {
                                                "from_tool": original_tool_id,
                                                "to_tool": tool_id,
                                            },
                                        }
                                    )
                                    _record_failure_memory(
                                        plan_id=run_request.plan_id,
                                        step_id=step_id,
                                        tool_id=original_tool_id,
                                        taxonomy=initial_failure_taxonomy,
                                        error_message=original_error_message,
                                        attempt=(
                                            step_recorder.attempt
                                            if step_recorder
                                            else max_attempts
                                        ),
                                        max_attempts=max_attempts,
                                        recovered=True,
                                        recovery_actions=recovery_attempts,
                                    )
                                    recovered = True
                                    break
                                except Exception as fallback_exc:
                                    last_error = fallback_exc
                                    failure_taxonomy = classify_failure(
                                        status="error",
                                        error_message=str(last_error),
                                    )
                                    failed_tools.add(fallback_tool_id)
                                    recovery_attempts.append(
                                        {
                                            "tool": fallback_tool_id,
                                            "status": "failed",
                                            "error": str(fallback_exc),
                                        }
                                    )

                        if recovered:
                            continue

                        # Failed after all retries (failure_taxonomy computed/updated above)
                        # PR-4 Issue #4: Mark cache as failed after permanent failure
                        if cache_key and cache_store:
                            try:
                                asyncio.run(
                                    cache_store.mark_failed(
                                        cache_key=cache_key,
                                        run_id=(
                                            step_recorder.run_id
                                            if step_recorder
                                            else run_request.plan_id
                                        ),
                                        error=str(last_error),
                                    )
                                )
                                logger.info(
                                    f"Marked cache entry as failed: {cache_key}"
                                )
                            except Exception as cache_exc:
                                logger.warning(
                                    f"Failed to mark cache as failed: {cache_exc}"
                                )

                        failure_payload = {
                            "plan_id": run_request.plan_id,
                            "version": run_request.version,
                            "step_id": step_id,
                            "tool": tool_id,
                            "state": "failed",
                            "attempt": (
                                step_recorder.attempt if step_recorder else max_attempts
                            ),
                            "max_attempts": max_attempts,
                            "error": str(last_error),
                            "retryable": False,  # Already exhausted retries
                            "error_category": failure_taxonomy.category.value,
                            "is_retryable": failure_taxonomy.is_retryable,
                            "recovery_strategy": failure_taxonomy.recovery_action.value,
                            "recovery_suggestions": failure_taxonomy.recovery_suggestions,
                            "error_taxonomy": failure_taxonomy.to_dict(),
                            "recovery": (
                                {"from_tool": original_tool_id, "to_tool": tool_id}
                                if original_tool_id != tool_id
                                else None
                            ),
                        }
                        failed_steps.append(failure_payload)
                        yield _format_sse(
                            "step_failed",
                            failure_payload,
                        )

                        _record_failure_memory(
                            plan_id=run_request.plan_id,
                            step_id=step_id,
                            tool_id=original_tool_id,
                            taxonomy=failure_taxonomy,
                            error_message=str(last_error),
                            attempt=(
                                step_recorder.attempt if step_recorder else max_attempts
                            ),
                            max_attempts=max_attempts,
                            recovered=False,
                            recovery_actions=recovery_attempts or None,
                        )

                        # Add failed step to parent recorder with PR-4 fields
                        final_family = _infer_tool_family(tool_id)
                        parent_recorder.add_child_summary(
                            step_id=step_id,
                            state="failed",
                            run_dir=step_recorder.run_dir if step_recorder else None,
                            extra=(
                                {
                                    **prepare_child_summary_extra(
                                        child_recorder=step_recorder,
                                        max_attempts=max_attempts,
                                        retry_reason=str(last_error),
                                        error=str(last_error),
                                    ),
                                    "error_taxonomy": failure_taxonomy.to_dict(),
                                    **(
                                        {"tool_family": final_family}
                                        if final_family
                                        else {}
                                    ),
                                }
                                if step_recorder
                                else {
                                    "error": str(last_error),
                                    "attempt": max_attempts,
                                    "max_attempts": max_attempts,
                                    "error_taxonomy": failure_taxonomy.to_dict(),
                                    **(
                                        {"tool_family": final_family}
                                        if final_family
                                        else {}
                                    ),
                                }
                            ),
                        )

                        # For now, continue to next step (don't fail entire plan)
                        # TODO: Add configurable failure policy
                        continue

                if failed_steps:
                    yield _format_sse(
                        "plan_failed",
                        {
                            "plan_id": run_request.plan_id,
                            "version": run_request.version,
                            "state": "failed",
                            "failed_steps": failed_steps,
                            "error": failed_steps[0].get("error"),
                        },
                    )
                else:
                    yield _format_sse(
                        "plan_completed",
                        {
                            "plan_id": run_request.plan_id,
                            "version": run_request.version,
                            "state": "completed",
                        },
                    )

        finally:
            # Keep plan in cache for potential replay/debugging
            # TODO: Add configurable cache retention policy
            pass

    return _generator()


def _stream_stub_plan_events(run_request: RunPlanRequest):
    """Generator yielding deterministic SSE events for the stub plan.

    DEPRECATED: Use _execute_plan_with_streaming for real execution.
    """
    from brain_researcher.services.agent.web_service import (
        logger,
    )

    logger.warning("Using deprecated stub plan execution")
    return _execute_plan_with_streaming(run_request)


def _submit_plan_job(
    plan_id: str,
    version: str,
    por_token: str,
    *,
    plan_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit plan execution as a job to the worker queue.

    PR-4 Phase 4 (Issue #1): Delegates plan execution to async worker pool
    instead of executing in Flask request thread.

    Args:
        plan_id: Plan identifier from _PLAN_CACHE
        version: Plan version
        por_token: Proof-of-reservation token

    Returns:
        Dict with job_id, stream_url, status_url

    Raises:
        ValueError: If plan_id not found in cache
    """
    import asyncio

    from brain_researcher.services.agent.web_service import (
        _PLAN_CACHE,
        PlanAllowlistError,
        _absolute_orchestrator_url,
        _collect_disallowed_tools_from_payload,
        logger,
    )
    from brain_researcher.services.shared.job_models import JobRecord, JobState
    from brain_researcher.services.shared.job_store_registry import (
        peek_initialized_job_store,
    )
    from brain_researcher.services.shared.job_update_bus import job_updates

    # Validate plan exists in cache
    cached_plan = plan_payload or _PLAN_CACHE.get(plan_id)
    if not cached_plan:
        raise ValueError(
            f"Plan {plan_id} not found in cache. Must POST /agent/plan first."
        )

    disallowed = _collect_disallowed_tools_from_payload(cached_plan)
    if disallowed:
        raise PlanAllowlistError(disallowed, plan_id=plan_id)

    job_store = peek_initialized_job_store()
    if job_store is None:
        raise RuntimeError("Job store is not initialized")

    # Generate job ID
    job_id = str(uuid.uuid4())

    # Create job payload
    dag_payload = cached_plan.get("dag", {})
    job_payload = {
        "type": "plan_execution",
        "plan_id": plan_id,
        "plan": cached_plan,
        "dag": dag_payload,
        "steps": dag_payload.get("steps", cached_plan.get("steps", [])),
        "artifacts": dag_payload.get("artifacts", cached_plan.get("artifacts", {})),
        "context": cached_plan.get("context"),
        "snapshot": {
            "intent": cached_plan.get("intent"),
            "predicted_capabilities": cached_plan.get("predicted_capabilities"),
            "predicted_intents": cached_plan.get("predicted_intents"),
            "capability_prediction": cached_plan.get("capability_prediction"),
            "cross_stage_context": cached_plan.get("cross_stage_context"),
            "loop_signals": cached_plan.get("loop_signals"),
            "candidates": cached_plan.get("candidates"),
            "chosen_tool": cached_plan.get("chosen_tool"),
            "selection_reason": cached_plan.get("selection_reason"),
        },
        "metadata": {
            "version": version,
            "por_token": por_token,
        },
    }

    # Create job record
    job = JobRecord(
        job_id=job_id,
        kind="plan_execution",
        state=JobState.QUEUED,
        payload_json=json.dumps(job_payload),
        created_at=int(time.time()),
    )

    # Submit to worker queue (synchronously from Flask handler)
    job_updates[job_id] = asyncio.Queue()

    async def _enqueue_job():
        await job_store.enqueue(job)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_enqueue_job())
    finally:
        loop.close()
    logger.info(f"Submitted plan {plan_id} as job {job_id} to worker queue")

    # Remove plan from cache after submission to avoid leaks
    if plan_payload is None:
        _PLAN_CACHE.pop(plan_id, None)

    # Return job info
    job_info = {
        "job_id": job_id,
        "plan_id": plan_id,
        "stream_url": f"/jobs/{job_id}/stream",
        "status_url": f"/jobs/{job_id}",
        "steps_url": f"/api/jobs/{job_id}/steps",
    }
    job_info["stream_url_abs"] = _absolute_orchestrator_url(job_info["stream_url"])
    job_info["status_url_abs"] = _absolute_orchestrator_url(job_info["status_url"])
    job_info["steps_url_abs"] = _absolute_orchestrator_url(job_info["steps_url"])
    return job_info
