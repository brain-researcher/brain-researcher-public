"""
LLM-powered code tools: completion and diff generation.

Provides:
- llm.code.complete: In-editor code completion
- llm.code.diff: Goal-driven code modification with patch generation
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


def llm_code_complete(args: dict[str, Any]) -> dict[str, Any]:
    """
    Generate code completion using LLM.

    Args:
        args: {
            "path": str,              # File path for context
            "prefix": str,            # Code before cursor
            "suffix": str,            # Code after cursor
            "language": str,          # Optional language hint
            "cursor": {               # Optional cursor position
                "line": int,
                "col": int
            },
            "max_tokens": int,        # Max completion tokens (default: 128)
            "temperature": float,     # Sampling temperature (default: 0.2)
            "provider": str,          # Optional provider hint
            "model": str              # Optional model name
        }

    Returns:
        {
            "completion": str,
            "insert_at": {
                "path": str,
                "start": {"line": int, "col": int},
                "end": {"line": int, "col": int}
            },
            "usage": {...},
            "provider": str,
            "model": str
        }
    """
    from brain_researcher.services.llm_gateway.gemini_fallback import chat_with_fallback

    path = args["path"]
    prefix = args["prefix"]
    suffix = args["suffix"]
    language = args.get("language") or _infer_language(path)
    cursor = args.get("cursor", {"line": 1, "col": 0})
    args.get("max_tokens", 128)
    args.get("temperature", 0.2)
    model = (
        args.get("model")
        or os.environ.get("DEFAULT_CODING_MODEL")
        or os.environ.get("DEFAULT_LLM_MODEL")
        or "gemini-3-flash-preview"
    )

    # Build completion prompt
    prompt = f"""You are an expert code completion assistant. Complete the code at the cursor position.

File: {path}
Language: {language}

Code before cursor:
```{language}
{prefix}
```

Code after cursor:
```{language}
{suffix}
```

Provide ONLY the code completion to insert at the cursor. No explanations, no markdown formatting.
Keep it concise and contextually appropriate."""

    # Get completion from LLM
    text, provider, model_used, usage, fallback_reason = chat_with_fallback(
        prompt=prompt, initial_model=model, credential_name=args.get("credential")
    )

    # Clean up completion (remove markdown if present)
    completion = _clean_code_block(text, language)

    # Calculate insert position
    prefix_lines = prefix.split("\n")
    cursor_line = cursor.get("line", len(prefix_lines))
    cursor_col = cursor.get("col", len(prefix_lines[-1]) if prefix_lines else 0)

    return {
        "completion": completion,
        "insert_at": {
            "path": path,
            "start": {"line": cursor_line, "col": cursor_col},
            "end": {"line": cursor_line, "col": cursor_col},
        },
        "usage": usage,
        "provider": provider,
        "model": model_used,
        "fallback_reason": fallback_reason,
    }


def llm_code_diff(args: dict[str, Any]) -> dict[str, Any]:
    """
    Generate code changes as unified diffs based on a goal.

    Args:
        args: {
            "goal": str,                  # What to change
            "targets": [str],             # Target files/globs
            "context": {                  # Optional context
                "files": [
                    {"path": str, "content": str, "sha256": str}
                ]
            },
            "constraints": {
                "tests_must_pass": bool,
                "style": [str],
                "max_iters": int,
                "patch_format": str
            },
            "provider": str,
            "model": str,
            "temperature": float,
            "max_tokens": int
        }

    Returns:
        {
            "patches": [str],             # Unified diffs
            "test_report": str,           # JUnit XML (if tests run)
            "logs": [str],
            "usage": {...},
            "success": bool,
            "provider": str,
            "model": str
        }
    """
    from brain_researcher.services.llm_gateway.gemini_fallback import chat_with_fallback

    goal = args["goal"]
    targets = args["targets"]
    context = args.get("context", {})
    constraints = args.get("constraints", {})
    model = (
        args.get("model")
        or os.environ.get("DEFAULT_CODING_MODEL")
        or os.environ.get("DEFAULT_LLM_MODEL")
        or "gemini-3-flash-preview"
    )
    args.get("temperature", 0.2)
    args.get("max_tokens", 2048)

    # Read target files
    target_files = _resolve_targets(targets)
    if not target_files:
        return {
            "patches": [],
            "test_report": None,
            "logs": ["No target files found"],
            "usage": {},
            "success": False,
            "provider": "none",
            "model": "none",
        }

    # Build context from files
    context_files = context.get("files", [])
    file_context = _build_file_context(target_files, context_files)

    # Build diff generation prompt
    prompt = f"""You are an expert code refactoring assistant. Generate unified diff patches to achieve the following goal:

GOAL: {goal}

TARGET FILES:
{file_context}

CONSTRAINTS:
- Output format: unified diff (--- a/path +++ b/path @@ ... @@)
- Be precise and minimal - only change what's necessary
- Preserve existing code style and formatting
- Do NOT include explanatory text, only the diff patches
{_format_constraints(constraints)}

Generate the unified diff patches now:"""

    # Get diff from LLM
    text, provider, model_used, usage, fallback_reason = chat_with_fallback(
        prompt=prompt, initial_model=model, credential_name=args.get("credential")
    )

    # Extract unified diffs from response
    patches = _extract_unified_diffs(text)

    # Optionally run tests if constraints specify
    test_report = None
    logs = []
    success = len(patches) > 0

    if constraints.get("tests_must_pass") and patches:
        # Note: Actual test running would be done via fs.apply_patch + tests.run
        # This is a placeholder
        logs.append(
            "Note: tests_must_pass constraint requires manual application via fs.apply_patch + tests.run"
        )

    return {
        "patches": patches,
        "test_report": test_report,
        "logs": logs,
        "usage": usage,
        "success": success,
        "provider": provider,
        "model": model_used,
        "fallback_reason": fallback_reason,
    }


# ============================================================================
# Helper Functions
# ============================================================================


def _infer_language(path: str) -> str:
    """Infer programming language from file extension."""
    ext = Path(path).suffix.lower()
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".java": "java",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
        ".sh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
    }
    return lang_map.get(ext, "text")


def _clean_code_block(text: str, language: str) -> str:
    """Remove markdown code block formatting if present."""
    # Remove markdown code blocks
    pattern = rf"```{language}?\s*\n?(.*?)\n?```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _resolve_targets(targets: list[str]) -> list[Path]:
    """Resolve file paths from glob patterns."""
    import glob

    resolved = []
    for target in targets:
        if "*" in target or "?" in target:
            # Glob pattern
            matches = glob.glob(target, recursive=True)
            resolved.extend([Path(m) for m in matches if Path(m).is_file()])
        else:
            # Direct path
            p = Path(target)
            if p.is_file():
                resolved.append(p)

    return resolved


def _build_file_context(
    target_files: list[Path], context_files: list[dict[str, Any]]
) -> str:
    """Build file context string for prompt."""
    lines = []

    # Add target files
    for path in target_files[:5]:  # Limit to avoid token overflow
        try:
            content = path.read_text()
            lines.append(f"File: {path}")
            lines.append("```")
            lines.append(content[:2000])  # Limit content length
            if len(content) > 2000:
                lines.append(f"... (truncated, {len(content)} total chars)")
            lines.append("```")
            lines.append("")
        except Exception as e:
            lines.append(f"File: {path} (error reading: {e})")
            lines.append("")

    # Add context files if provided
    for ctx_file in context_files[:3]:
        lines.append(f"Context: {ctx_file.get('path')}")
        lines.append("```")
        lines.append(ctx_file.get("content", "")[:1000])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _format_constraints(constraints: dict[str, Any]) -> str:
    """Format constraints for prompt."""
    lines = []
    if constraints.get("style"):
        lines.append(f"- Follow style guidelines: {', '.join(constraints['style'])}")
    if constraints.get("max_iters"):
        lines.append(f"- Maximum {constraints['max_iters']} refinement iterations")
    return "\n".join(lines)


def _extract_unified_diffs(text: str) -> list[str]:
    """Extract unified diff blocks from text."""
    # Pattern for unified diff: starts with --- a/path, ends before next --- or end
    diff_pattern = r"(---\s+a/.*?(?=---\s+a/|\Z))"
    matches = re.findall(diff_pattern, text, re.DOTALL)

    # Clean up each diff
    diffs = []
    for match in matches:
        diff = match.strip()
        if diff and ("+++" in diff or "@@ " in diff):
            diffs.append(diff)

    return diffs


LLM_CODE_COMPLETE_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}
LLM_CODE_COMPLETE_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {"completion": {"type": "string"}},
}
LLM_CODE_DIFF_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "context": {"type": "string"},
    },
    "required": ["goal"],
}
LLM_CODE_DIFF_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {"diff": {"type": "string"}},
}


def get_llm_code_tools() -> list[dict[str, Any]]:
    """Get LLM code tool definitions for registration (MCP schemas inlined)."""

    return [
        {
            "name": "llm.code.complete",
            "description": "Generate code completion using LLM (Gemini/GPT)",
            "input_schema": LLM_CODE_COMPLETE_INPUT,
            "output_schema": LLM_CODE_COMPLETE_OUTPUT,
            "handler": llm_code_complete,
            "tags": ["llm", "code", "completion"],
        },
        {
            "name": "llm.code.diff",
            "description": "Generate code changes as unified diffs based on goals",
            "input_schema": LLM_CODE_DIFF_INPUT,
            "output_schema": LLM_CODE_DIFF_OUTPUT,
            "handler": llm_code_diff,
            "tags": ["llm", "code", "diff", "refactor"],
        },
    ]
