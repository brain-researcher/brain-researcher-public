from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver

import brain_researcher.services.agent.brain_researcher_graph as brg


class DummyApp:
    def __init__(self):
        self.last_config = None

    def invoke(self, initial_state, config):
        self.last_config = config
        return {"synthesis": {"summary": "ok"}}


class RecordingSaver(MemorySaver):
    """MemorySaver that records resume configs and exposes a fake latest checkpoint."""

    def __init__(self, thread_id: str, checkpoint_id: str):
        super().__init__()
        self.last_get_config = None
        self.storage = {thread_id: {"": {checkpoint_id: (None, None, None)}}}
        self._latest_id = checkpoint_id

    def get_tuple(self, config):  # type: ignore[override]
        self.last_get_config = config
        return SimpleNamespace(config={"configurable": {"checkpoint_id": self._latest_id}})


def test_brainresearcher_graph_resume_and_checkpoint(monkeypatch):
    """Ensure resume_checkpoint_id is passed through and checkpoint_id is surfaced."""
    thread_id = "t-checkpoint"
    resume_id = "resume-123"
    latest_ckpt = "ckpt-latest"

    saver = RecordingSaver(thread_id=thread_id, checkpoint_id=latest_ckpt)
    graph = brg.BrainResearcherGraph()

    # Replace compiled app with a dummy that captures config
    dummy_app = DummyApp()
    graph.app = dummy_app
    graph.checkpointer = saver

    result = graph.run(
        "hello",
        thread_id=thread_id,
        resume_checkpoint_id=resume_id,
    )

    # Resume config should carry the checkpoint id
    assert dummy_app.last_config is not None
    assert dummy_app.last_config["configurable"].get("checkpoint_id") == resume_id

    # After execution, the runner should expose the latest checkpoint id.
    assert result.get("checkpoint_id") == latest_ckpt
    assert "last_checkpoint_id" not in result
