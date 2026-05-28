"""Human-friendly rendering of CodegenResult for chat/CLI surfaces."""

from __future__ import annotations

from typing import List

from brain_researcher.services.agent.codegen.context import CodegenResult


def _header(status: str) -> str:
    if status == "success":
        return "✅ Coding succeeded"
    if status == "failed":
        return "❌ Coding failed"
    return f"⚠️ Status: {status}"


def render_result_for_chat(result: CodegenResult) -> str:
    lines: List[str] = [_header(result.status)]
    lines.append(f"- Iterations: {result.iterations}")
    if result.files_touched:
        lines.append(f"- Files: {', '.join(result.files_touched)}")
    if result.exec_result:
        if result.exec_result.exit_code is not None:
            lines.append(f"- Test exit code: {result.exec_result.exit_code}")
        if result.exec_result.stderr:
            lines.append(f"- Stderr: {_truncate(result.exec_result.stderr, 400)}")
    if result.errors:
        lines.append(f"- Error: {_truncate(str(result.errors), 400)}")
    if result.patches:
        lines.append(f"- Patches: {len(result.patches)} (review before applying)")
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "... (truncated)"


__all__ = ["render_result_for_chat"]
