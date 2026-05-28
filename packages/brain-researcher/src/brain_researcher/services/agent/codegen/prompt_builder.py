"""Prompt builder for the coding agent.

The builder consumes a :class:`CodegenContext` and produces a single prompt
string tailored either for an initial generation ("fresh") or a repair cycle
after an observed error ("repair").
"""

from __future__ import annotations

from typing import Literal

from brain_researcher.services.agent.codegen.constitution import (
    format_codegen_constitution_for_prompt,
)
from brain_researcher.services.agent.codegen.context import CodegenContext

MARIMO_FORMAT_GUIDE = """\
The target file is a **Marimo notebook** (.py).  Follow these rules exactly:

1. The file starts with `import marimo` and `app = marimo.App()`.
2. Each cell is a function decorated with `@app.cell`.
3. Cell dependencies are declared via function parameters:
   `def _(df):` means this cell depends on a cell that returns `df`.
4. Cells return values that downstream cells consume.  Use `return (x, y)` tuples.
5. Use `import brain_researcher.sdk as br` for all tool calls.
   Use only `br.search()`, `br.execute()`, `br.recipe()`, `br.display.*`.
6. Use `mo.md("# Title")` for markdown, `mo.stop(cond, msg)` for guards.
7. Never use mutable global state between cells — Marimo enforces isolation.
8. The file ends with `if __name__ == "__main__": app.run()`.
9. Emit the entire file or a unified diff — both are accepted.
"""


def _format_section(title: str, body: str) -> str:
    if not body:
        return ""
    return f"## {title}\n{body.strip()}\n\n"


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n... (truncated)"


def build_prompt(context: CodegenContext, mode: Literal["fresh", "repair"] = "fresh") -> str:
    """Compose the LLM prompt for code generation/repair.

    Args:
        context: Aggregated codegen context.
        mode: "fresh" for first attempt, "repair" when providing an error trace.
    """

    sections = []

    sections.append(_format_section("User Request", context.instruction))
    sections.append(
        _format_section("Constitution", format_codegen_constitution_for_prompt())
    )

    if context.code_context:
        sections.append(_format_section("Current Code Context", _truncate(context.code_context, 4000)))

    if context.plan_steps:
        plan_lines = [f"- Step {s.get('step_number', i+1)}: {s.get('description','')}" for i, s in enumerate(context.plan_steps)]
        sections.append(_format_section("Plan", "\n".join(plan_lines)))

    snippets: list[str] = []
    if context.files:
        for fs in context.files[:5]:
            header = f"### {fs.path}"
            loc = ""
            if fs.start_line is not None:
                loc = f" (lines {fs.start_line}-{fs.end_line or '...'})"
            snippets.append(f"{header}{loc}\n```\n{_truncate(fs.snippet, 2000)}\n```\n")
    elif context.file_snippets:
        for path, snippet in list(context.file_snippets.items())[:5]:
            snippets.append(f"### {path}\n```\n{_truncate(snippet, 2000)}\n```\n")
    if snippets:
        sections.append(_format_section("Relevant Files", "\n".join(snippets)))

    if context.datasets:
        sections.append(_format_section("Datasets", "\n".join(context.datasets)))
    if context.kg_info:
        sections.append(_format_section("Knowledge Graph", _truncate(context.kg_info, 2000)))

    if context.tool_outputs:
        formatted = []
        for out in context.tool_outputs:
            name = out.get("name", "tool")
            summary = _truncate(out.get("summary", ""), 1000)
            formatted.append(f"- {name}: {summary}")
        sections.append(_format_section("Previous Tool Outputs", "\n".join(formatted)))

    if mode == "repair" and (context.error_trace or context.prior_errors):
        error_text = context.error_trace or ""
        if context.prior_errors:
            joined = "\n".join(f"- {e}" for e in context.prior_errors[-3:])
            error_text = f"{error_text}\n{joined}".strip()
        sections.append(_format_section("Last Error", _truncate(error_text, 2000)))

    constraints = context.constraints or {}
    constraint_lines = []
    if constraints.get("style"):
        constraint_lines.append(f"- Follow style: {constraints['style']}")
    if constraints.get("tests_must_pass"):
        constraint_lines.append("- All referenced tests must pass")
    if constraints.get("max_iters"):
        constraint_lines.append(f"- Max iterations remaining: {constraints['max_iters']}")
    if context.test_command:
        constraint_lines.append(f"- Preferred test command: {context.test_command}")
    constraint_lines.append("- Return concise code with minimal commentary")

    if constraints.get("output_format") == "marimo":
        sections.append(_format_section(
            "Marimo Notebook Format",
            MARIMO_FORMAT_GUIDE,
        ))

    sections.append(_format_section("Constraints", "\n".join(constraint_lines)))

    guidance = (
        "You are a coding assistant. Propose minimal changes to satisfy the request. "
        "Use fenced code blocks or unified diff if edits are needed. If nothing should change, say so clearly."
    )

    prompt = guidance + "\n\n" + "".join(sections)

    return prompt
