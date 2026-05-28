from __future__ import annotations

from brain_researcher.services.agent import preflight


class DummyRetriever:
    def __init__(self):
        self.called_with = None

    def retrieve_tools(self, **kwargs):
        self.called_with = kwargs
        return []


def test_ensure_tool_candidates_respects_disable_gfs_flag():
    retriever = DummyRetriever()
    ctx = {"disable_gfs": True}

    preflight.ensure_tool_candidates("test query", ctx, tool_retriever=retriever)

    assert retriever.called_with is not None
    assert retriever.called_with.get("filters", {}).get("disable_gfs") is True


def test_ensure_tool_candidates_default_no_filters():
    retriever = DummyRetriever()
    ctx = {}

    preflight.ensure_tool_candidates("test query", ctx, tool_retriever=retriever)

    assert retriever.called_with is not None
    assert retriever.called_with.get("filters") in (None, {})


def test_ensure_tool_candidates_skips_default_retriever_on_plan_surfaces(monkeypatch):
    import brain_researcher.services.agent.tool_retriever as tool_retriever

    def _unexpected_init():
        raise AssertionError("ToolRetriever should not initialize on plan surfaces")

    monkeypatch.delenv("BR_USE_TOOL_RETRIEVER", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(tool_retriever, "ToolRetriever", _unexpected_init)

    for runtime_surface in ("plan", "plan_preflight"):
        ctx = {"runtime_surface": runtime_surface}
        candidates = preflight.ensure_tool_candidates(
            "test query",
            ctx,
            tool_retriever=None,
        )

        assert candidates == []
        diagnostics = ctx.get("tool_candidate_diagnostics") or {}
        assert diagnostics.get("retrieval_path") == "surface_default_disabled"
