"""Router prompt templates for LLM-based tool selection.

This module provides prompt templates for the LLM tool router to select
appropriate tools based on user goals and context.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain_researcher.services.tools.spec import ToolSpec


ROUTER_PROMPT = """Select the best tool for the user's goal.

## User Goal
{goal}

## Context
{context}

## Available Tools
{tool_summaries}

## Instructions
1. Analyze the user's goal and available context
2. Choose the most appropriate tool from the list
3. Provide required arguments based on the context
4. Return response in JSON format

## Response Format
```json
{{
  "tool": "tool_name",
  "reasoning": "brief explanation of why this tool was chosen",
  "args": {{
    "param1": "value1",
    "param2": "value2"
  }}
}}
```

## Important Notes
- Only select tools from the provided list
- Consider the tool's modalities and intents when matching to the goal
- If the goal is ambiguous, ask for clarification before selecting a tool
- Prefer tools with matching intents over generic tools
- For exploratory dataset asset discovery, prefer list/browse tools such as
  list_dataset_assets before resolve_dataset_asset or resolve_bids
"""


ROUTER_PROMPT_MINIMAL = """Select the best tool for: {goal}

Tools:
{tool_summaries}

Return JSON: {{"tool": "name", "args": {{...}}}}
"""


def format_tool_summary(spec: "ToolSpec", verbose: bool = False) -> str:
    """Format a ToolSpec for the router prompt.

    Args:
        spec: ToolSpec to format
        verbose: If True, include more details

    Returns:
        Formatted string for prompt inclusion
    """
    parts = [f"**{spec.name}**: {spec.description[:200]}"]

    if verbose:
        if spec.modalities:
            parts.append(f"  modalities: {spec.modalities}")
        if spec.intents:
            parts.append(f"  intents: {spec.intents}")
        if spec.kind:
            parts.append(f"  kind: {spec.kind}")
        if spec.backend != "python":
            parts.append(f"  backend: {spec.backend}")
        if spec.consumes:
            parts.append(f"  consumes: {spec.consumes}")
        if spec.produces:
            parts.append(f"  produces: {spec.produces}")
    else:
        # Minimal format
        meta_parts = []
        if spec.modalities:
            meta_parts.append(f"modalities={spec.modalities}")
        if spec.intents:
            meta_parts.append(f"intents={spec.intents}")
        if meta_parts:
            parts.append(f"  [{', '.join(meta_parts)}]")

    return "\n".join(parts)


def build_router_prompt(
    goal: str,
    candidates: list["ToolSpec"],
    context: str = "",
    verbose: bool = False,
) -> str:
    """Build the full router prompt with candidates.

    Args:
        goal: User's natural language goal
        candidates: List of ToolSpec candidates to choose from
        context: Optional additional context (e.g., previous tool outputs)
        verbose: If True, include more tool details

    Returns:
        Complete prompt string ready for LLM
    """
    summaries = "\n\n".join(
        format_tool_summary(spec, verbose=verbose) for spec in candidates
    )

    return ROUTER_PROMPT.format(
        goal=goal,
        context=context or "No additional context provided.",
        tool_summaries=summaries,
    )


def build_minimal_router_prompt(goal: str, candidates: list["ToolSpec"]) -> str:
    """Build a minimal router prompt for token efficiency.

    Args:
        goal: User's natural language goal
        candidates: List of ToolSpec candidates

    Returns:
        Minimal prompt string
    """
    summaries = "\n".join(
        f"- {spec.name}: {spec.description[:100]}" for spec in candidates
    )

    return ROUTER_PROMPT_MINIMAL.format(goal=goal, tool_summaries=summaries)


__all__ = [
    "ROUTER_PROMPT",
    "ROUTER_PROMPT_MINIMAL",
    "build_router_prompt",
    "build_minimal_router_prompt",
    "format_tool_summary",
]
