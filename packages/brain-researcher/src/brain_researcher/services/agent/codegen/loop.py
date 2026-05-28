"""LangGraph-inspired iterative loop for code generation and repair.

The implementation is intentionally lightweight: we keep a simple Python loop
to avoid pulling additional dependencies while mirroring the generate→execute
→analyze→decide pattern.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, List

from brain_researcher.services.agent.codegen.context import (
    CodegenContext,
    CodegenResult,
    ExecutionResult,
)
from brain_researcher.services.agent.codegen.prompt_builder import build_prompt
from brain_researcher.services.agent.codegen.workspace import Workspace
from brain_researcher.services.agent.codegen.model_policy import (
    choose_model_for_code_task,
)
from brain_researcher.services.agent.logging.token_counter import TokenCounter


class CodegenLoop:
    def __init__(
        self,
        router,
        max_iters: int = 3,
        workspace_cls=Workspace,
        patch_char_limit: int = 40_000,
        patch_line_limit: int = 1200,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.router = router
        self.max_iters = max_iters
        self.workspace_cls = workspace_cls
        self.patch_char_limit = patch_char_limit
        self.patch_line_limit = patch_line_limit
        self._emit = event_callback or self._noop_emit

    @staticmethod
    def _noop_emit(event: str, data: Dict[str, Any]) -> None:
        """No-op event emitter when no callback is provided."""
        pass

    def run(
        self, context: CodegenContext, *, strict_json: bool = True
    ) -> CodegenResult:
        last_error: Optional[str] = None
        last_execution: Optional[ExecutionResult] = None
        response_text: str = ""
        patches: List[str] = []
        prior_errors: List[str] = context.prior_errors or []

        repo_root = Path(context.repo_root or os.getcwd())
        workspace = self.workspace_cls(repo_root=repo_root)
        files_for_ws = context.files if context.files else (context.file_paths or [])
        if files_for_ws:
            workspace.materialize_files(files_for_ws)

        for iteration in range(self.max_iters):
            mode = "repair" if last_error else "fresh"

            # Emit plan event at start of iteration
            self._emit(
                "plan",
                {
                    "iteration": iteration,
                    "max_iters": self.max_iters,
                    "mode": mode,
                    "phase": "generating",
                },
            )

            ctx = CodegenContext(
                **{
                    **context.__dict__,
                    "iteration": iteration,
                    "error_trace": last_error,
                    "prior_errors": prior_errors[-3:],
                }
            )
            prompt = build_prompt(ctx, mode=mode)

            estimated_tokens = TokenCounter.estimate_tokens(prompt, provider="google")
            # Respect explicit model hint first; otherwise fall back to policy.
            model_hint = context.model_hint or choose_model_for_code_task(
                ctx=context,
                prompt_tokens_estimate=estimated_tokens,
                strict_json=strict_json,
            )

            llm_result = self.router.route_chat(
                prompt=prompt,
                model_hint=model_hint,
                provider_lock=context.provider_lock,
                task_type="code",
                strict_json=strict_json,
                ctx_tokens=estimated_tokens,
                budget_id=context.budget_id,
                credential_name=context.credential_name,
            )

            response_text = llm_result.text
            patches = _extract_patches(response_text)

            # Emit patch events for each extracted patch
            for i, patch in enumerate(patches):
                self._emit(
                    "patch",
                    {
                        "index": i,
                        "total": len(patches),
                        "preview": patch[:300] + "..." if len(patch) > 300 else patch,
                    },
                )

            apply_error: Optional[str] = None
            for patch in patches:
                if _exceeds_limits(patch, self.patch_char_limit, self.patch_line_limit):
                    apply_error = (
                        f"Patch too large (chars>{self.patch_char_limit} or lines>{self.patch_line_limit}); "
                        "reduce scope and retry."
                    )
                    break
                try:
                    workspace.apply_patch(patch)
                except Exception as exc:
                    apply_error = str(exc)
                    break

            if apply_error:
                last_error = apply_error
                prior_errors.append(apply_error)
                self._emit(
                    "test", {"status": "skipped", "reason": "patch apply failed"}
                )
                continue

            # Emit test event before running checks
            self._emit(
                "test",
                {
                    "status": "running",
                    "command": context.test_command or "py_compile",
                },
            )

            last_execution = workspace.run_checks(test_command=context.test_command)

            # Emit test result event
            self._emit(
                "test",
                {
                    "status": "passed" if last_execution.success else "failed",
                    "stdout": (last_execution.stdout or "")[:500],
                    "stderr": (last_execution.stderr or "")[:500],
                    "exit_code": last_execution.exit_code,
                },
            )
            if last_execution.success:
                return CodegenResult(
                    status="success",
                    iterations=iteration + 1,
                    response_text=response_text,
                    patches=patches,
                    files_touched=workspace.files_touched(),
                    exec_result=last_execution,
                    errors=None,
                    provider=llm_result.metadata.provider,
                    model=llm_result.metadata.model,
                    usage=llm_result.metadata.usage,
                    fallback_reason=llm_result.metadata.fallback_reason,
                )

            last_error = last_execution.stderr or "Unknown execution failure"
            prior_errors.append(last_error)

        # Exhausted iterations
        return CodegenResult(
            status="failed",
            iterations=self.max_iters,
            response_text=response_text,
            patches=patches,
            files_touched=workspace.files_touched(),
            exec_result=last_execution,
            errors=last_error,
            provider=None,
            model=context.model_hint,
            usage={},
            fallback_reason=None,
        )


def _extract_patches(text: str) -> List[str]:
    patches: List[str] = []
    if not text:
        return patches
    fence = "```"
    start = text.find(fence)
    while start != -1:
        end = text.find(fence, start + 3)
        if end == -1:
            break
        snippet = text[start + 3 : end].strip()
        if snippet:
            patches.append(snippet)
        start = text.find(fence, end + 3)
    return patches


def _exceeds_limits(patch: str, char_limit: int, line_limit: int) -> bool:
    if len(patch) > char_limit:
        return True
    if patch.count("\n") + 1 > line_limit:
        return True
    return False
