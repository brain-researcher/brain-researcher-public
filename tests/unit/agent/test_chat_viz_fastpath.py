"""Regression test: chat viz fast-path should bypass LLM and return preview.

This exercises ChatOrchestrator.handle_chat when ctx contains a stat_map. The
planner fast-path should build a single viz_stat_maps step, execute it, and
return immediately without calling the router (no LLM summary). We monkeypatch
_execute_pipeline_steps to avoid touching real Nilearn and just return a
successful preview result.
"""

from types import SimpleNamespace

import pytest

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.tools.result import ToolResult


class DummyRouter:
    """Router that must never be called in this fast-path."""

    def route_chat(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("router should not be invoked for viz fast-path")


@pytest.fixture
def orchestrator(monkeypatch):
    """ChatOrchestrator with pipeline executor stubbed out."""

    orch = ChatOrchestrator(router=DummyRouter())

    async def fake_execute_pipeline_steps(steps, ctx, preview=True):
        # Simulate a successful preview result from viz_stat_maps
        return [
            {
                "step_id": steps[0].step_id,
                "tool": steps[0].tool_name,
                "status": "success",
                "data": {
                    "shape": [8, 8, 8],
                    "affine": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                    "preview_only": True,
                },
                "error": None,
            }
        ]

    monkeypatch.setattr(orch, "_execute_pipeline_steps", fake_execute_pipeline_steps)
    return orch


def test_chat_viz_fastpath_bypasses_llm(orchestrator):
    """When stat_map is provided, orchestrator should return preview without LLM."""

    ctx = {
        "stat_map": "/tmp/fake_stat.nii.gz",
        "display_mode": "ortho",
        "preview": True,
        "use_planning_engine": True,
    }

    ctx["thread_id"] = "t-fast-viz"

    reply = orchestrator.handle_chat(
        "visualize this stat map",
        history=[],
        ctx=ctx,
    )

    # No LLM summary: answer is the preview marker
    assert reply.answer.startswith("Preview only")

    # Pipeline metadata present
    assert reply.metadata.get("type") == "pipeline"
    assert reply.metadata.get("mode") == "preview"

    # Tool call contains the viz result and no errors
    assert reply.tool_calls, "expected tool_calls in reply"
    tc = reply.tool_calls[0]
    assert isinstance(tc, dict)
    assert tc["results"][0]["status"] == "success"
    assert tc["results"][0]["data"]["preview_only"] is True
