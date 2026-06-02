from types import SimpleNamespace

from brain_researcher.services.agent.planner.unified_planner import UnifiedPlanner


class _StubRetriever:
    def __init__(self, tools):
        self._tools = tools

    def select_families_by_query(self, query, llm=None, max_families=3):
        return ["connectivity"]

    def retrieve_tools(self, query, family_ids=None, top_k=20):
        return self._tools[:top_k]


def _kg_tool(tool_id: str, score: float):
    return SimpleNamespace(id=tool_id, score=score)


def _force_kg_only(monkeypatch):
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.unified_planner.select_tools",
        lambda **kwargs: [],
    )
    monkeypatch.setenv("BR_PLANNER_USE_CAPABILITY_PRIOR", "0")
    monkeypatch.setenv("BR_PLANNER_USE_EVIDENCE_PRIOR", "0")


def test_kg_only_fallback_skips_off_modality_fmri_tool_for_meg(monkeypatch):
    _force_kg_only(monkeypatch)
    planner = UnifiedPlanner(
        tool_retriever=_StubRetriever(
            [
                _kg_tool("nilearn_connectivity_matrix", 1.0),
                _kg_tool("mne_connectivity", 0.9),
            ]
        )
    )

    result = planner.plan(
        query="estimate source-space connectivity from MEG epochs",
        modality="meg",
        max_candidates=5,
    )

    assert result.chosen_tool_id == "mne_connectivity"
    assert [row["tool_id"] for row in result.candidates] == ["mne_connectivity"]
    assert "kg_modality_gate=meg" in result.constraints_applied
    assert any(
        item.startswith("kg_modality_rejected=nilearn_connectivity_matrix")
        for item in result.constraints_applied
    )


def test_kg_only_fallback_fails_closed_when_all_candidates_are_off_modality(
    monkeypatch,
):
    _force_kg_only(monkeypatch)
    planner = UnifiedPlanner(
        tool_retriever=_StubRetriever(
            [
                _kg_tool("nilearn_connectivity_matrix", 1.0),
                _kg_tool("compute_connectivity", 0.9),
            ]
        )
    )

    result = planner.plan(
        query="estimate source-space connectivity from MEG epochs",
        modality="meg",
        max_candidates=5,
    )

    assert result.chosen_tool_id is None
    assert result.candidates == []
    assert result.routing_diagnostics["selected_tool_id"] is None
    assert any(
        item.startswith("kg_modality_rejected=nilearn_connectivity_matrix")
        for item in result.constraints_applied
    )
