"""LLM Router and Coding Agent tool wrappers.

These expose the existing LLMRouter / Gemini CLI cascade as planner-visible
tools without duplicating provider logic. They lean on
``chat_with_fallback`` which already uses a shared ``LLMRouter`` instance and
handles multi-credential routing (Gemini first, then fallbacks).
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

import os

from brain_researcher.services.agent.router import LLMRouter
from brain_researcher.services.agent.codegen.context import (
    CodegenContext,
    FileSnippet,
    ExecutionResult,
)
from brain_researcher.services.agent.codegen.fs_context import (
    GeminiCliFsClient,
    build_fs_context_for_task_sync,
)
from brain_researcher.services.agent.codegen.loop import CodegenLoop
from brain_researcher.services.agent.codegen.render import render_result_for_chat
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult
from brain_researcher.services.agent.llm_budget_manager import (
    get_shared_llm_budget_manager,
)
from brain_researcher.services.agent.managed_credential_pool import (
    get_shared_managed_pool,
)


class LLMRouterChatArgs(BaseModel):
    """Inputs for generic LLM chat/summarization."""

    prompt: str = Field(..., description="Main prompt for the LLM")
    context: Optional[str] = Field(
        None, description="Optional additional context or history"
    )
    task_type: Optional[str] = Field(
        "chat", description="Task type hint (chat, summary, code, etc.)"
    )
    model_hint: Optional[str] = Field(None, description="Preferred model/provider hint")


class CodingAgentArgs(BaseModel):
    """Inputs for coding-agent mode."""

    instruction: str = Field(..., description="High-level coding instruction")
    code_context: Optional[str] = Field(None, description="Code snippet or error text")
    file_paths: Optional[List[str]] = Field(
        None, description="List of relevant file paths (for context only)"
    )
    model_hint: Optional[str] = Field(None, description="Preferred model/provider hint")
    gemini_only: bool = Field(
        False,
        description="Force Gemini-only routing and disable GPT/OpenAI fallback for this run",
    )
    repo_root: Optional[str] = Field(None, description="Repository root for FS search")
    auto_fs_context: bool = Field(
        True, description="Auto fetch code context via FS search"
    )
    max_fs_files: int = Field(5, description="Maximum files to include from FS search")
    max_fs_chars: int = Field(
        4000, description="Max chars per file snippet from FS search"
    )
    prefetched_files: Optional[List[dict]] = Field(
        None, description="Prefetched file snippets (bypass internal FS search)"
    )
    apply: bool = Field(
        False, description="Apply patches to repo after successful loop"
    )
    dry_run: bool = Field(
        False, description="If applying, preview only without writing"
    )
    max_iters: int = Field(3, description="Maximum codegen iterations")


class LLMRouterChatTool(NeuroToolWrapper):
    """Route a prompt through the shared LLMRouter (Gemini-first cascade)."""

    def __init__(self):
        super().__init__()
        self._router = LLMRouter(
            budget_manager=get_shared_llm_budget_manager(),
            managed_pool=get_shared_managed_pool(),
        )
        max_iters = int(os.environ.get("BR_CODE_AGENT_MAX_ITERS", "3"))
        self._code_loop = CodegenLoop(self._router, max_iters=max_iters)

    def get_tool_name(self) -> str:
        return "ai.llm.router.chat"

    def get_tool_description(self) -> str:
        return (
            "Use the LLMRouter to handle chat/summarization with multi-credential "
            "fallback (Gemini CLI preferred)."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return LLMRouterChatArgs

    def _run(
        self,
        prompt: str,
        context: Optional[str] = None,
        task_type: str = "chat",
        model_hint: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            composed = prompt if not context else f"{prompt}\n\n{context}"
            result = self._router.route_chat(
                prompt=composed,
                model_hint=(
                    model_hint
                    or os.environ.get("DEFAULT_LLM_MODEL")
                    or "gemini-3-flash-preview"
                ),
                credential_name=None,
            )

            metadata = result.metadata

            return ToolResult(
                status="success",
                data={
                    "response": result.text,
                    "usage": metadata.usage,
                    "provider": metadata.provider,
                    "model": metadata.model,
                    "fallback_reason": metadata.fallback_reason,
                    "bill_to": metadata.bill_to,
                    "estimated_cost": metadata.estimated_cost,
                    "budget_remaining": metadata.budget_remaining,
                    "quota_remaining": metadata.quota_remaining,
                    "route": metadata.route,
                    "transport": metadata.transport,
                    "latency_ms": metadata.latency_ms,
                },
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("LLMRouterChatTool failed: %s", exc)
            return ToolResult(status="error", error=str(exc))


class CodingAgentTool(NeuroToolWrapper):
    """Coding-focused LLM agent using the shared router."""

    def __init__(self):
        super().__init__()
        self._router = LLMRouter(
            budget_manager=get_shared_llm_budget_manager(),
            managed_pool=get_shared_managed_pool(),
        )
        max_iters = int(os.environ.get("BR_CODE_AGENT_MAX_ITERS", "3"))
        self._code_loop = CodegenLoop(self._router, max_iters=max_iters)
        self._fs_client = GeminiCliFsClient()
        # Hint execution backend so ToolExecutor routes to Python wrapper instead of ToolSpec
        self.execution_backend = "python"

    def get_tool_name(self) -> str:
        return "code_agent"

    def get_tool_description(self) -> str:
        return (
            "LLM-based coding assistant to refactor code, fix bugs, or write tests "
            "via the LLMRouter in code mode."
        )

    def get_args_schema(self) -> type[BaseModel]:
        return CodingAgentArgs

    def _run(
        self,
        instruction: str,
        code_context: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        model_hint: Optional[str] = None,
        gemini_only: bool = False,
        repo_root: Optional[str] = None,
        auto_fs_context: bool = True,
        max_fs_files: int = 5,
        max_fs_chars: int = 4000,
        prefetched_files: Optional[List[dict]] = None,
        apply: bool = False,
        dry_run: bool = False,
        max_iters: int = 3,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            if os.environ.get("BR_CODE_AGENT_ENABLED", "true").lower() != "true":
                return ToolResult(
                    status="error",
                    error="Coding agent disabled by BR_CODE_AGENT_ENABLED",
                )

            env_gemini_only = (
                os.environ.get("BR_CODE_AGENT_GEMINI_ONLY", "false").lower() == "true"
            )
            gemini_only = bool(gemini_only or env_gemini_only)

            # Resolve model hint: prefer explicit arg, then coding env overrides, then chat default.
            model_hint = (
                model_hint
                or os.environ.get("DEFAULT_CODING_MODEL")
                or os.environ.get("CODE_AGENT_MODEL_HINT")
                or os.environ.get("DEFAULT_LLM_MODEL")
            )
            provider_lock: Optional[str] = None
            if gemini_only:
                provider_lock = "gemini"
                if not model_hint or "gemini" not in model_hint.lower():
                    model_hint = (
                        os.environ.get("CODE_AGENT_GEMINI_MODEL")
                        or os.environ.get("DEFAULT_CODING_MODEL")
                        or "gemini-3-flash-preview"
                    )

            # Optional FS-assisted context
            file_snippets = None
            if prefetched_files:
                try:
                    file_snippets = [
                        fs if isinstance(fs, FileSnippet) else FileSnippet(**fs)
                        for fs in prefetched_files
                    ]
                    auto_fs_context = False
                except Exception as exc:  # pragma: no cover
                    self.logger.warning("Invalid prefetched_files: %s", exc)

            if auto_fs_context and not file_paths and not file_snippets:
                try:
                    file_snippets = build_fs_context_for_task_sync(
                        query=instruction,
                        repo_root=repo_root or os.getcwd(),
                        fs_client=kwargs.get("fs_client", self._fs_client),
                        max_files=max_fs_files,
                        max_chars_per_file=max_fs_chars,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.warning("FS context enrichment failed: %s", exc)

            context = CodegenContext(
                user_query=instruction,
                instruction=instruction,
                code_context=code_context,
                plan_steps=None,
                pipeline_context=None,
                datasets=None,
                kg_info=None,
                tool_outputs=None,
                file_paths=file_paths,
                files=file_snippets,
                file_snippets=None,
                constraints={"max_iters": max_iters},
                test_command=kwargs.get("test_command"),
                model_hint=model_hint,
                provider_lock=provider_lock,
                repo_root=repo_root or os.getcwd(),
                budget_id=kwargs.get("budget_id"),
                credential_name=kwargs.get("credential_name"),
            )

            # allow per-call override
            self._code_loop.max_iters = max_iters
            loop_result = self._code_loop.run(context)

            apply_logs = None
            if apply and loop_result.status == "success" and loop_result.patches:
                try:
                    if not dry_run:
                        from brain_researcher.services.agent.codegen.workspace import (
                            apply_patches_to_repo,
                        )

                        apply_logs = apply_patches_to_repo(
                            loop_result.patches, Path(context.repo_root or os.getcwd())
                        )
                    else:
                        apply_logs = ["dry-run: patches not applied"]
                except Exception as exc:  # pylint: disable=broad-except
                    return ToolResult(
                        status="error",
                        error=f"Failed to apply patches: {exc}",
                        data={"patches": loop_result.patches},
                    )

            return ToolResult(
                status="success" if loop_result.status == "success" else "error",
                data={
                    "response": loop_result.response_text,
                    "patches": loop_result.patches,
                    "files_touched": loop_result.files_touched,
                    "files_changed": [
                        {"path": p, "change_summary": ""}
                        for p in loop_result.files_touched
                    ],
                    "status": loop_result.status,
                    "iterations": loop_result.iterations,
                    "exec_stdout": loop_result.exec_result.stdout
                    if loop_result.exec_result
                    else None,
                    "exec_stderr": loop_result.exec_result.stderr
                    if loop_result.exec_result
                    else None,
                    "test_status": _exec_status(loop_result.exec_result),
                    "provider": loop_result.provider,
                    "model": loop_result.model,
                    "usage": loop_result.usage,
                    "fallback_reason": loop_result.fallback_reason,
                    "requires_confirmation": bool(loop_result.patches) and not apply,
                    "apply_logs": apply_logs,
                    "summary": render_result_for_chat(loop_result),
                },
                error=loop_result.errors,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("CodingAgentTool failed: %s", exc)
            return ToolResult(status="error", error=str(exc))


__all__ = ["LLMRouterChatTool", "CodingAgentTool"]


def _exec_status(exec_result: ExecutionResult | None) -> str | None:
    if exec_result is None:
        return None
    if exec_result.success:
        return "passed"
    if exec_result.exit_code is None:
        return "not_run"
    return "failed"
