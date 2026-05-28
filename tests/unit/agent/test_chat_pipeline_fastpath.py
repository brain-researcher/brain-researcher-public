"""Regression: pipeline preview fast-path should bypass LLM and return steps/results.

This mirrors the viz fast-path test, but exercises the imaging pipeline branch
with planning enabled. We stub PlanningEngine.generate_plan to return a simple
two-step T1→MNI plan (BET → FNIRT) and stub _execute_pipeline_steps to return
preview results. The router must not be invoked and the reply should carry
pipeline metadata and success tool results.
"""

from types import SimpleNamespace

import pytest

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator, WorkflowStep


class DummyRouter:
    """Router that must not be called in the fast-path."""

    def route_chat(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("router should not be invoked for pipeline fast-path")


@pytest.fixture
def orchestrator(monkeypatch):
    """ChatOrchestrator with planner & executor patched for fast-path preview."""

    orch = ChatOrchestrator(router=DummyRouter(), enable_knowledge_layer=False)

    # Stub planner to return a deterministic T1->MNI plan
    async def fake_generate_plan(self, query, intent, context):
        steps = [
            WorkflowStep(
                step_id="step_bet",
                step_number=1,
                description="Brain extraction",
                tool_name="fsl.bet",
                tool_args={"input": context.get("t1w_image", "t1.nii.gz")},
            ),
            WorkflowStep(
                step_id="step_fnirt",
                step_number=2,
                description="Nonlinear registration to MNI",
                tool_name="fsl.fnirt",
                tool_args={
                    "in_file": context.get("t1w_image", "t1.nii.gz"),
                    "ref_file": "MNI152_T1_2mm.nii.gz",
                },
            ),
        ]
        return SimpleNamespace(steps=steps)

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.PlanningEngine.generate_plan",
        fake_generate_plan,
    )

    async def fake_execute_pipeline_steps(steps, ctx, preview=True):
        return [
            {
                "step_id": steps[0].step_id,
                "tool": steps[0].tool_name,
                "status": "success",
                "data": {"preview_only": True, "cmd": "bet <input> <out>"},
                "error": None,
            },
            {
                "step_id": steps[1].step_id,
                "tool": steps[1].tool_name,
                "status": "success",
                "data": {"preview_only": True, "cmd": "fnirt <in> <ref>"},
                "error": None,
            },
        ]

    monkeypatch.setattr(orch, "_execute_pipeline_steps", fake_execute_pipeline_steps)
    return orch


def test_chat_pipeline_preview_fastpath(orchestrator):
    """T1->MNI pipeline with preview should return steps/results and skip LLM."""

    ctx = {
        "use_planning_engine": True,
        "pipeline_preview": True,
        "preview": True,
        "t1w_image": "/tmp/fake_t1.nii.gz",
        "thread_id": "t-pipeline",
    }

    reply = orchestrator.handle_chat(
        "preprocess my T1 to MNI",
        history=[],
        ctx=ctx,
    )

    assert reply.metadata.get("type") == "pipeline"
    assert reply.metadata.get("mode") == "preview"

    assert reply.tool_calls, "expected tool_calls"
    tc = reply.tool_calls[0]
    assert len(tc["pipeline_steps"]) == 2
    assert tc["pipeline_steps"][0]["tool_name"] == "fsl.bet"
    assert tc["pipeline_steps"][1]["tool_name"] == "fsl.fnirt"

    # Both steps succeeded with preview data
    results = tc["results"]
    assert all(r["status"] == "success" for r in results)
    assert all(r["data"]["preview_only"] is True for r in results)

