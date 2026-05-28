import asyncio

import brain_researcher.services.agent.workflows as wf_mod
from types import SimpleNamespace


class FakeStateMachine:
    def __init__(self):
        self.seen = []

    async def run_async(self, prompt, thread_id=None, resume_checkpoint_id=None):
        self.seen.append((thread_id, resume_checkpoint_id))
        return {"ok": True}

    def get_last_checkpoint_id(self, thread_id: str):
        return f"last-{thread_id}" if thread_id else None


def test_workflow_returns_checkpoint(monkeypatch):
    fake_sm = FakeStateMachine()
    monkeypatch.setattr(wf_mod, "CoreStateMachine", lambda: fake_sm)
    monkeypatch.setattr(wf_mod, "metrics_collector", SimpleNamespace(start_workflow=lambda _id: SimpleNamespace(total_time=0, tools_used={}, state_transitions=[]), end_workflow=lambda *_args, **_kw: None))

    workflows = wf_mod.NeuroimagingWorkflows()
    # replace state_machine created in __init__
    workflows.state_machine = fake_sm

    result = asyncio.run(
        workflows.execute_workflow(
            wf_mod.WorkflowType.FMRI_STANDARD,
            inputs={"fmri_file": "file.nii", "t1_file": "t1.nii", "design_matrix": {}},
            thread_id="th1",
            resume_checkpoint_id="ck-resume",
        )
    )

    assert result["checkpoint_id"] == "last-th1"
    assert "last_checkpoint_id" not in result
    assert fake_sm.seen[0][1] == "ck-resume"
