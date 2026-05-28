from types import SimpleNamespace

import pytest

import brain_researcher.services.agent.enhanced_integration as ei


class _DummyEvidenceCollector:
    def __init__(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_process_query_surfaces_canonical_checkpoint_id(monkeypatch):
    fake_state_machine = SimpleNamespace(
        tool_registry=None,
        get_last_checkpoint_id=lambda _thread_id: "ckpt-final",
    )

    monkeypatch.setattr(ei, "EnhancedToolRegistry", lambda: SimpleNamespace())
    monkeypatch.setattr(ei, "RunRecorder", lambda base_path: SimpleNamespace())
    monkeypatch.setattr(ei, "EnhancedEvidenceCollector", _DummyEvidenceCollector)

    orchestrator = ei.EnhancedAgentOrchestrator(
        base_state_machine=fake_state_machine,
        enable_workflow_composition=False,
        enable_error_recovery=False,
    )

    async def _planning(*_args, **_kwargs):
        return {"plan": "ok"}

    async def _execution(*_args, **_kwargs):
        return {"execution": "ok"}

    async def _review(*_args, **_kwargs):
        return {"review": "ok"}

    async def _response(*_args, **_kwargs):
        return {"success": True}

    monkeypatch.setattr(orchestrator, "_enhanced_planning_phase", _planning)
    monkeypatch.setattr(orchestrator, "_enhanced_execution_phase", _execution)
    monkeypatch.setattr(orchestrator, "_enhanced_review_phase", _review)
    monkeypatch.setattr(orchestrator, "_generate_comprehensive_response", _response)
    monkeypatch.setattr(orchestrator, "_update_performance_metrics", lambda *_a, **_k: None)
    monkeypatch.setattr(orchestrator, "_archive_session", lambda *_a, **_k: None)

    result = await orchestrator.process_query("hello", thread_id="thread-1")

    assert result["checkpoint_id"] == "ckpt-final"
    assert "last_checkpoint_id" not in result
