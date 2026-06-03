"""Chat interface bridging Marimo notebooks to the BR coding agent.

``br.chat(message)`` sends a natural-language request to the
``CodeOrchestrator``, which generates or modifies the current notebook file.
The orchestrator is called in-process (no HTTP round-trip needed when running
inside ``br notebook open``).

For remote setups (Marimo running separately from the agent), this module
also supports an HTTP fallback via ``BR_AGENT_URL``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    """Result of a ``br.chat()`` call."""

    message: str
    patches: list[str]
    files_touched: list[str]
    status: str  # "success" | "failed" | "error"
    metadata: dict[str, Any]


def _extract_notebook_code(patches: list[str]) -> str | None:
    """Extract Python source from the first patch that looks like a complete file."""
    for patch in patches:
        # Strip leading/trailing whitespace and fencing artifacts
        code = patch.strip()
        if code.startswith("```"):
            # Remove fenced code block markers
            lines = code.split("\n")
            lines = lines[1:]  # drop ```python or ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)
        lines = code.splitlines()
        if lines and lines[0].strip().lower() in {"python", "py"}:
            code = "\n".join(lines[1:])
        if "marimo" in code or "@app.cell" in code:
            return code
    return None


def _looks_like_marimo(code: str) -> bool:
    """Quick heuristic: does *code* look like a valid Marimo notebook?"""
    return "import marimo" in code and "@app.cell" in code


def _coerce_marimo_codegen_result(
    result: Any,
    notebook_path: str | None,
    apply: bool,
) -> bool:
    """Normalize full-file Marimo outputs that were misclassified as failed patches."""
    if not (
        getattr(result, "patches", None)
        and getattr(result, "status", None) == "failed"
        and "garbage" in (getattr(result, "answer", "") or "").lower()
    ):
        return False

    code = _extract_notebook_code(result.patches)
    if not (code and _looks_like_marimo(code)):
        return False

    if apply and notebook_path:
        Path(notebook_path).write_text(code)
        result.answer = f"Notebook written to {notebook_path}"
        result.files_touched = [notebook_path]
    else:
        target = notebook_path or "Marimo notebook"
        result.answer = f"Generated Marimo notebook preview for {target}"
        result.files_touched = []

    result.status = "success"
    return True


def _preferred_credential_name(
    model_hint: str | None, credential_name: str | None
) -> str | None:
    if credential_name:
        return credential_name
    model_name = (model_hint or os.environ.get("DEFAULT_CODING_MODEL") or "").lower()
    if "gemini" in model_name and os.environ.get("GEMINI_API_KEY"):
        return "env_gemini"
    if ("gpt" in model_name or "openai" in model_name) and os.environ.get(
        "OPENAI_API_KEY"
    ):
        return "env_openai"
    return None


def chat(
    message: str,
    *,
    notebook_path: str | None = None,
    apply: bool = True,
    model_hint: str | None = None,
    credential_name: str | None = None,
) -> ChatResponse:
    """Send a natural-language request to the BR coding agent.

    Args:
        message: User request, e.g. "Add a cell that runs fMRIPrep".
        notebook_path: Path to the target Marimo .py file.  If ``None``,
            auto-detected from ``BR_NOTEBOOK_PATH`` or the first ``.py``
            in the current directory that imports ``marimo``.
        apply: Whether to write patches to disk (default ``True``).
        model_hint: Override the coding model.
        credential_name: Optional explicit credential selection (e.g. ``env_gemini``).

    Returns:
        A ``ChatResponse`` with the agent's answer and any patches applied.
    """
    notebook_path = notebook_path or os.environ.get("BR_NOTEBOOK_PATH")

    agent_url = os.environ.get("BR_AGENT_URL")
    if agent_url:
        return _chat_remote(
            message, notebook_path, apply, model_hint, credential_name, agent_url
        )
    return _chat_local(message, notebook_path, apply, model_hint, credential_name)


def _chat_local(
    message: str,
    notebook_path: str | None,
    apply: bool,
    model_hint: str | None,
    credential_name: str | None,
) -> ChatResponse:
    """In-process call to ``CodeOrchestrator``."""
    try:
        from brain_researcher.services.agent.code_orchestrator import (
            CodeOrchestrator,
            CodeResult,
        )
    except ImportError as exc:
        return ChatResponse(
            message=f"CodeOrchestrator not available: {exc}",
            patches=[],
            files_touched=[],
            status="error",
            metadata={"error": str(exc)},
        )

    ctx: dict[str, Any] = {
        "apply": apply,
        "dry_run": not apply,
        "constraints": {"output_format": "marimo"},
    }
    preferred_credential = _preferred_credential_name(model_hint, credential_name)
    if notebook_path:
        ctx["file_paths"] = [notebook_path]
        ctx["repo_root"] = str(Path(notebook_path).parent)
    if model_hint:
        ctx["model_hint"] = model_hint
    if preferred_credential:
        ctx["credential_name"] = preferred_credential

    orch = CodeOrchestrator()
    result: CodeResult = orch.run_task(instruction=message, ctx=ctx)

    # CodegenLoop may report "failed" when the LLM returns a complete file
    # instead of a unified diff (patch -p0 rejects it as "garbage").
    # In that case the generated code is still valid — normalize it here.
    _coerce_marimo_codegen_result(result, notebook_path, apply)

    return ChatResponse(
        message=result.answer,
        patches=result.patches,
        files_touched=result.files_touched,
        status=result.status,
        metadata=result.metadata,
    )


def _chat_remote(
    message: str,
    notebook_path: str | None,
    apply: bool,
    model_hint: str | None,
    credential_name: str | None,
    agent_url: str,
) -> ChatResponse:
    """HTTP call to a remote agent service."""
    import urllib.request

    payload = {
        "prompt": message,
        "ctx": {
            "apply": apply,
            "dry_run": not apply,
            "constraints": {"output_format": "marimo"},
        },
    }
    if notebook_path:
        payload["ctx"]["file_paths"] = [notebook_path]
    if model_hint:
        payload["ctx"]["model_hint"] = model_hint
    preferred_credential = _preferred_credential_name(model_hint, credential_name)
    if preferred_credential:
        payload["ctx"]["credential_name"] = preferred_credential

    url = f"{agent_url.rstrip('/')}/act_llm"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return ChatResponse(
            message=data.get("answer", ""),
            patches=data.get("patches", []),
            files_touched=data.get("files_touched", []),
            status=data.get("status", "success"),
            metadata=data,
        )
    except Exception as exc:
        logger.error("Remote agent call failed: %s", exc)
        return ChatResponse(
            message=f"Remote agent error: {exc}",
            patches=[],
            files_touched=[],
            status="error",
            metadata={"error": str(exc), "url": url},
        )
