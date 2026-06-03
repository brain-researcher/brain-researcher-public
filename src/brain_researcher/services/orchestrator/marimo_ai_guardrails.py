"""Runtime guardrails for hosted marimo AI responses."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.ui.vercel_ai.response_types import (
    BaseChunk,
    FinishChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolInputAvailableChunk,
    ToolInputStartChunk,
    ToolOutputAvailableChunk,
)

_BR_CALL_PATTERN = re.compile(
    r"""br\.call\(\s*(?P<quote>['"])(?P<tool_name>[^'"]+)(?P=quote)"""
)
_BR_MCP_PREFIX = "mcp_brain-researcher_"
_BR_NAME_FIELDS = frozenset({"name", "tool_name", "toolName"})
_BR_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


def _extract_referenced_br_call_names(text: str) -> list[str]:
    seen: list[str] = []
    for match in _BR_CALL_PATTERN.finditer(text):
        tool_name = match.group("tool_name")
        if tool_name not in seen:
            seen.append(tool_name)
    return seen


def _has_speculative_br_call(text: str) -> bool:
    return _BR_CALL_PATTERN.search(text) is not None


def _collect_br_named_values(value: Any) -> set[str]:
    names: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in _BR_NAME_FIELDS and isinstance(child, str):
                    if _BR_TOOL_NAME_PATTERN.fullmatch(child):
                        names.add(child)
                visit(child)
            return
        if isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return names


def _collect_verified_br_tool_names(
    tool_call_names: dict[str, str],
    tool_outputs: list[tuple[str, Any]],
) -> set[str]:
    verified: set[str] = set()

    for tool_name in tool_call_names.values():
        if tool_name.startswith(_BR_MCP_PREFIX):
            verified.add(tool_name[len(_BR_MCP_PREFIX) :])

    for source_tool_name, output in tool_outputs:
        if not source_tool_name.startswith(_BR_MCP_PREFIX):
            continue
        verified.update(_collect_br_named_values(output))

    return verified


def _build_speculative_br_call_reply(
    unverified_names: list[str], verified_names: set[str]
) -> str:
    lines = [
        "I couldn't verify the exact Brain Researcher tool name for that "
        "`br.call(...)` example from this session's tool evidence, so I'm not "
        "emitting speculative code.",
        f"Unverified tool name(s): {', '.join(unverified_names)}.",
    ]

    if verified_names:
        sample = ", ".join(sorted(verified_names)[:8])
        lines.append(
            f"Verified Brain Researcher tool names seen in this run: {sample}."
        )
    else:
        lines.append("No exact Brain Researcher tool name was verified in this run.")

    lines.append(
        "Next step: use a tool name returned by `br.search(...)` or another "
        "Brain Researcher tool output in this session, or ask one concise "
        "clarifying question if no exact match is available."
    )
    return "\n\n".join(lines)


def _replacement_text_for_speculative_br_calls(
    text: str,
    tool_call_names: dict[str, str],
    tool_outputs: list[tuple[str, Any]],
) -> str | None:
    if not _has_speculative_br_call(text):
        return None

    referenced_names = _extract_referenced_br_call_names(text)
    if not referenced_names:
        return None

    verified_names = _collect_verified_br_tool_names(tool_call_names, tool_outputs)
    unverified_names = [name for name in referenced_names if name not in verified_names]
    if not unverified_names:
        return None

    return _build_speculative_br_call_reply(unverified_names, verified_names)


async def _emit_buffered_text(
    buffered_text_chunks: list[BaseChunk],
    replacement_text: str | None,
) -> AsyncIterator[BaseChunk]:
    if replacement_text is None:
        for chunk in buffered_text_chunks:
            yield chunk
        return

    text_chunk_id = next(
        (
            getattr(chunk, "id", None)
            for chunk in buffered_text_chunks
            if getattr(chunk, "id", None)
        ),
        f"br_guardrail_{uuid.uuid4().hex}",
    )
    yield TextStartChunk(id=text_chunk_id)
    yield TextDeltaChunk(id=text_chunk_id, delta=replacement_text)
    yield TextEndChunk(id=text_chunk_id)


async def wrap_br_tool_name_guardrail_stream(
    stream: AsyncIterator[BaseChunk],
) -> AsyncIterator[BaseChunk]:
    """Delay assistant text until validation can reject speculative BR tool names."""

    buffered_text_chunks: list[BaseChunk] = []
    text_parts: list[str] = []
    tool_call_names: dict[str, str] = {}
    tool_outputs: list[tuple[str, Any]] = []

    async for chunk in stream:
        if isinstance(chunk, ToolInputStartChunk | ToolInputAvailableChunk):
            tool_call_names[chunk.tool_call_id] = chunk.tool_name
            yield chunk
            continue

        if isinstance(chunk, ToolOutputAvailableChunk):
            source_tool_name = tool_call_names.get(chunk.tool_call_id, "")
            tool_outputs.append((source_tool_name, chunk.output))
            yield chunk
            continue

        if isinstance(chunk, TextStartChunk | TextDeltaChunk | TextEndChunk):
            buffered_text_chunks.append(chunk)
            if isinstance(chunk, TextDeltaChunk):
                text_parts.append(chunk.delta)
            continue

        if isinstance(chunk, FinishChunk):
            replacement_text = _replacement_text_for_speculative_br_calls(
                "".join(text_parts),
                tool_call_names,
                tool_outputs,
            )
            async for text_chunk in _emit_buffered_text(
                buffered_text_chunks, replacement_text
            ):
                yield text_chunk
            buffered_text_chunks.clear()
            text_parts.clear()
            yield chunk
            continue

        yield chunk

    if buffered_text_chunks:
        replacement_text = _replacement_text_for_speculative_br_calls(
            "".join(text_parts),
            tool_call_names,
            tool_outputs,
        )
        async for text_chunk in _emit_buffered_text(
            buffered_text_chunks, replacement_text
        ):
            yield text_chunk
