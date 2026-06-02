"""Model routing policy helpers for codegen tasks."""

from __future__ import annotations

import os

from brain_researcher.services.llm_gateway.codegen.context import CodegenContext


def choose_model_for_code_task(
    ctx: CodegenContext | None,
    prompt_tokens_estimate: int,
    strict_json: bool,
) -> str:
    """
    Heuristic model policy for code tasks.

    - If strict JSON/patch reliability is required -> prefer GPT-5.
    - If prompt is very long (>120k tokens estimate) -> prefer Gemini 3 Flash (long context).
    - Otherwise pick a balanced default (GPT-5.1 Pro).
    """

    if strict_json:
        return "gpt-5"
    if prompt_tokens_estimate and prompt_tokens_estimate > 120_000:
        return "gemini-3-flash-preview"
    return "gpt-5.1-pro"


def select_model(
    model_hint: str | None,
    *,
    task_type: str | None,
    strict_json: bool | None,
    ctx_tokens: int | None,
    ctx: CodegenContext | None = None,
) -> str | None:
    """Return a possibly adjusted model name based on policy signals."""

    if not task_type or task_type != "code":
        return model_hint

    # If caller already provided a strong hint, respect it.
    if model_hint:
        return model_hint

    env_model = (
        os.getenv("DEFAULT_CODING_MODEL")
        or os.getenv("CODE_AGENT_MODEL")
        or os.getenv("DEFAULT_LLM_MODEL")
    )
    if env_model:
        return env_model

    return choose_model_for_code_task(
        ctx=ctx, prompt_tokens_estimate=ctx_tokens or 0, strict_json=bool(strict_json)
    )
