"""Dedicated CodeOrchestrator for coding tasks.

This orchestrator owns the coding flow completely, bypassing the general
tool router. It uses a minimal tool registry and emits granular SSE events
for plan/patch/test progress.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.codegen.context import CodegenContext, FileSnippet
from brain_researcher.services.agent.codegen.fs_context import (
    GeminiCliFsClient,
    build_fs_context_for_task_sync,
)
from brain_researcher.services.agent.codegen.loop import CodegenLoop
from brain_researcher.services.agent.codegen.render import render_result_for_chat
from brain_researcher.services.agent.llm_budget_manager import (
    get_shared_llm_budget_manager,
)
from brain_researcher.services.agent.managed_credential_pool import (
    get_shared_managed_pool,
)
from brain_researcher.services.agent.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class CodeResult:
    """Structured result from coding orchestration."""

    status: str  # "success" | "failed" | "error"
    answer: str  # Human-readable summary
    patches: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    iterations: int = 0
    test_status: str | None = None  # "passed" | "failed" | "not_run"
    exec_stdout: str | None = None
    exec_stderr: str | None = None
    requires_confirmation: bool = False
    apply_logs: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CodeOrchestrator:
    """Dedicated coding subsystem - bypasses general tool routing.

    Key responsibilities:
    1. Accept coding requests from ChatOrchestrator
    2. Use minimal code tool registry (6 tools max)
    3. Delegate to CodegenLoop for plan→patch→test→repair cycle
    4. Emit SSE events for granular progress (plan/patch/test/done)
    5. Return structured CodeResult
    """

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        max_iters: int = 3,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self._router = llm_router or LLMRouter(
            budget_manager=get_shared_llm_budget_manager(),
            managed_pool=get_shared_managed_pool(),
        )
        self._max_iters = int(os.environ.get("BR_CODE_AGENT_MAX_ITERS", str(max_iters)))
        self._emit = event_callback or self._noop_emit
        # Pass event_callback to CodegenLoop for real-time SSE events
        self._code_loop = CodegenLoop(
            self._router,
            max_iters=self._max_iters,
            event_callback=self._emit,
        )
        self._fs_client = GeminiCliFsClient()

    @staticmethod
    def _noop_emit(event: str, data: dict[str, Any]) -> None:
        """No-op event emitter when no callback is provided."""
        pass

    def _get_model(self, ctx: dict[str, Any]) -> str:
        """Resolve model hint for coding tasks."""
        tools_cfg = ctx.get("tools", {}) or {}
        return (
            tools_cfg.get("model_hint")
            or ctx.get("model_hint")
            or os.environ.get("CODE_AGENT_MODEL")
            or os.environ.get("CODE_AGENT_MODEL_HINT")
            or os.environ.get("DEFAULT_CODING_MODEL")
            or os.environ.get("DEFAULT_LLM_MODEL")
            or "gemini-3-flash-preview"
        )

    def run_task(
        self,
        instruction: str,
        ctx: dict[str, Any],
        thread_id: str = "default",
        user_id: str | None = None,
    ) -> CodeResult:
        """Main entry point for coding tasks.

        Args:
            instruction: The coding instruction/request from user
            ctx: Context dict with repo_root, file_paths, apply, dry_run, etc.
            thread_id: Thread identifier for state tracking
            user_id: Optional user identifier

        Returns:
            CodeResult with status, answer, patches, and metadata
        """
        try:
            # Check if coding agent is enabled
            if os.environ.get("BR_CODE_AGENT_ENABLED", "true").lower() != "true":
                return CodeResult(
                    status="error",
                    answer="Coding agent disabled by BR_CODE_AGENT_ENABLED",
                    metadata={"error": "disabled"},
                )

            # Emit plan event
            self._emit(
                "plan",
                {
                    "instruction": instruction,
                    "thread_id": thread_id,
                    "phase": "starting",
                },
            )

            # Resolve parameters
            model_hint = self._get_model(ctx)
            tools_cfg = ctx.get("tools", {}) or {}
            repo_root = ctx.get("repo_root") or os.getcwd()
            file_paths = ctx.get("file_paths") or tools_cfg.get("file_paths")
            apply = ctx.get("apply", False)
            dry_run = ctx.get("dry_run", True)
            max_iters = ctx.get("max_iters", self._max_iters)

            # Build file context
            file_snippets = self._build_file_context(instruction, ctx)

            # Build CodegenContext
            codegen_ctx = CodegenContext(
                user_query=instruction,
                instruction=instruction,
                code_context=ctx.get("code_context"),
                plan_steps=None,
                pipeline_context=None,
                datasets=None,
                kg_info=None,
                tool_outputs=None,
                file_paths=file_paths,
                files=file_snippets,
                file_snippets=None,
                constraints={"max_iters": max_iters, "tests_must_pass": True},
                test_command=ctx.get("test_command"),
                model_hint=model_hint,
                repo_root=repo_root,
                budget_id=ctx.get("budget_id"),
                credential_name=ctx.get("credential_name"),
            )

            # Update loop max_iters
            self._code_loop.max_iters = max_iters

            # Run the codegen loop (emits plan/patch/test events internally)
            loop_result = self._code_loop.run(codegen_ctx)

            # Handle patch application
            apply_logs = None
            if apply and loop_result.status == "success" and loop_result.patches:
                apply_logs = self._apply_patches(
                    loop_result.patches, repo_root, dry_run
                )

            # Build summary
            summary = render_result_for_chat(loop_result)

            # Emit done event
            self._emit(
                "done",
                {
                    "status": loop_result.status,
                    "iterations": loop_result.iterations,
                    "files_touched": loop_result.files_touched,
                },
            )

            return CodeResult(
                status=loop_result.status,
                answer=summary,
                patches=loop_result.patches,
                files_touched=loop_result.files_touched,
                iterations=loop_result.iterations,
                test_status=self._exec_status(loop_result.exec_result),
                exec_stdout=(
                    loop_result.exec_result.stdout if loop_result.exec_result else None
                ),
                exec_stderr=(
                    loop_result.exec_result.stderr if loop_result.exec_result else None
                ),
                requires_confirmation=bool(loop_result.patches) and not apply,
                apply_logs=apply_logs,
                metadata={
                    "provider": loop_result.provider,
                    "model": loop_result.model,
                    "usage": loop_result.usage,
                    "fallback_reason": loop_result.fallback_reason,
                    "thread_id": thread_id,
                    "user_id": user_id,
                },
            )

        except Exception as exc:
            logger.exception("CodeOrchestrator.run_task failed: %s", exc)
            self._emit("error", {"error": str(exc)})
            return CodeResult(
                status="error",
                answer=f"Coding task failed: {exc}",
                metadata={"error": str(exc)},
            )

    def _build_file_context(
        self,
        instruction: str,
        ctx: dict[str, Any],
    ) -> list[FileSnippet] | None:
        """Build file context for the coding task."""
        tools_cfg = ctx.get("tools", {}) or {}

        # Check for prefetched files first
        prefetched = ctx.get("prefetched_files") or tools_cfg.get("prefetched_files")
        if prefetched:
            try:
                return [
                    fs if isinstance(fs, FileSnippet) else FileSnippet(**fs)
                    for fs in prefetched
                ]
            except Exception as exc:
                logger.warning("Invalid prefetched_files: %s", exc)

        # Auto-fetch context if enabled
        auto_fs = ctx.get("auto_fs_context", True)
        file_paths = ctx.get("file_paths") or tools_cfg.get("file_paths")

        if auto_fs and not file_paths:
            try:
                repo_root = ctx.get("repo_root") or os.getcwd()
                max_files = ctx.get("max_fs_files", 5)
                max_chars = ctx.get("max_fs_chars", 4000)

                return build_fs_context_for_task_sync(
                    query=instruction,
                    repo_root=repo_root,
                    fs_client=self._fs_client,
                    max_files=max_files,
                    max_chars_per_file=max_chars,
                )
            except Exception as exc:
                logger.warning("FS context enrichment failed: %s", exc)

        return None

    def _apply_patches(
        self,
        patches: list[str],
        repo_root: str,
        dry_run: bool,
    ) -> list[str]:
        """Apply patches to the repository."""
        if dry_run:
            return ["dry-run: patches not applied"]

        try:
            from brain_researcher.services.agent.codegen.workspace import (
                apply_patches_to_repo,
            )

            return apply_patches_to_repo(patches, Path(repo_root))
        except Exception as exc:
            logger.error("Failed to apply patches: %s", exc)
            return [f"error: {exc}"]

    @staticmethod
    def _exec_status(exec_result) -> str | None:
        """Convert execution result to status string."""
        if exec_result is None:
            return None
        if exec_result.success:
            return "passed"
        if exec_result.exit_code is None:
            return "not_run"
        return "failed"


# NOTE: Coding tasks are per-request; using fresh instances avoids
# cross-request callback leakage. Keep a simple helper for callers.
def get_code_orchestrator(
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> CodeOrchestrator:
    """Return a new CodeOrchestrator wired to the given callback."""

    return CodeOrchestrator(event_callback=event_callback)


__all__ = ["CodeOrchestrator", "CodeResult", "get_code_orchestrator"]
