from __future__ import annotations

from types import SimpleNamespace

from brain_researcher.services.agent import tool_candidate_service as service


class DummyRetriever:
    def __init__(self):
        self.called_with = None

    def retrieve_tools(self, **kwargs):
        self.called_with = kwargs
        return []


def test_generate_tool_candidates_wraps_preflight(monkeypatch):
    ctx = {}

    def fake_ensure_tool_candidates(query, ctx_arg, **kwargs):
        ctx_arg["tool_candidate_diagnostics"] = {
            "candidate_count": 1,
            "candidate_generation_latency_ms": 12.5,
            "retrieval_path": "fresh",
        }
        return [{"tool_id": "foo.bar", "source": "br_kg"}]

    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_candidate_service.preflight.ensure_tool_candidates",
        fake_ensure_tool_candidates,
    )

    bundle = service.generate_tool_candidates(
        "test query",
        ctx=ctx,
        tool_retriever=DummyRetriever(),
        registry=SimpleNamespace(),
    )

    assert bundle.tool_candidates == [{"tool_id": "foo.bar", "source": "br_kg"}]
    assert bundle.tool_candidate_diagnostics["candidate_count"] == 1
    assert bundle.tool_candidate_diagnostics["retrieval_path"] == "fresh"
    assert ctx["tool_candidate_diagnostics"] == bundle.tool_candidate_diagnostics
