from __future__ import annotations

from pydantic_ai.ui.vercel_ai.response_types import (
    FinishChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolInputStartChunk,
    ToolOutputAvailableChunk,
)

from brain_researcher.services.orchestrator.marimo_ai_guardrails import (
    wrap_br_tool_name_guardrail_stream,
)


async def _collect_chunks(chunks):
    results = []
    async for chunk in wrap_br_tool_name_guardrail_stream(chunks):
        results.append(chunk)
    return results


async def _iter_chunks(chunks):
    for chunk in chunks:
        yield chunk


async def test_guardrail_allows_verified_br_call_names() -> None:
    chunks = [
        ToolInputStartChunk(
            toolCallId="tool-call-1",
            toolName="mcp_brain-researcher_search",
        ),
        ToolOutputAvailableChunk(
            toolCallId="tool-call-1",
            output={"results": [{"name": "connectivity_matrix"}]},
        ),
        TextStartChunk(id="text-1"),
        TextDeltaChunk(
            id="text-1",
            delta='```python\nresult = br.call("connectivity_matrix", {"matrix": "demo"})\n```',
        ),
        TextEndChunk(id="text-1"),
        FinishChunk(),
    ]

    wrapped = await _collect_chunks(_iter_chunks(chunks))

    text_deltas = [chunk.delta for chunk in wrapped if isinstance(chunk, TextDeltaChunk)]
    assert text_deltas == [
        '```python\nresult = br.call("connectivity_matrix", {"matrix": "demo"})\n```'
    ]


async def test_guardrail_replaces_speculative_br_call_names() -> None:
    chunks = [
        ToolInputStartChunk(
            toolCallId="tool-call-1",
            toolName="mcp_brain-researcher_search",
        ),
        ToolOutputAvailableChunk(
            toolCallId="tool-call-1",
            output={"results": [{"name": "connectivity_matrix"}]},
        ),
        TextStartChunk(id="text-1"),
        TextDeltaChunk(
            id="text-1",
            delta='```python\nresult = br.call("neuprint_get_connectivity", {"source": 1})\n```',
        ),
        TextEndChunk(id="text-1"),
        FinishChunk(),
    ]

    wrapped = await _collect_chunks(_iter_chunks(chunks))

    text_deltas = [chunk.delta for chunk in wrapped if isinstance(chunk, TextDeltaChunk)]
    assert len(text_deltas) == 1
    assert "I'm not emitting speculative code." in text_deltas[0]
    assert "Unverified tool name(s): neuprint_get_connectivity." in text_deltas[0]
    assert 'result = br.call("neuprint_get_connectivity"' not in text_deltas[0]


async def test_guardrail_allows_plain_conceptual_chat_without_tool_shape() -> None:
    chunks = [
        TextStartChunk(id="text-1"),
        TextDeltaChunk(
            id="text-1",
            delta=(
                "A plain explanation should remain plain. "
                "We can discuss the strategy without emitting code."
            ),
        ),
        TextEndChunk(id="text-1"),
        FinishChunk(),
    ]

    wrapped = await _collect_chunks(_iter_chunks(chunks))

    assert wrapped == chunks
