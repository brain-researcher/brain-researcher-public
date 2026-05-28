from __future__ import annotations

from brain_researcher.services.agent import preflight


class _StubRegistry:
    def __init__(self, tool_names: list[str]):
        self._tools = {name: object() for name in tool_names}

    def get_tool(self, name):
        return self._tools.get(name)


def test_canonicalize_tool_id_prefers_runtime_name():
    registry = _StubRegistry(["fsl_bet", "searchlight_analysis"])

    assert preflight._canonicalize_tool_id("fsl.bet.run", registry) == "fsl_bet"
    assert (
        preflight._canonicalize_tool_id("python.searchlight_fmri.run", registry)
        == "searchlight_analysis"
    )


def test_ensure_tool_candidates_canonicalizes_ids_without_registry():
    class _StubRetriever:
        def retrieve_tools(self, query, family_ids=None, top_k=10, filters=None):
            return [
                {"id": "python.fetch_atlas.run", "score": 0.9, "source": "neurokg"},
                {"id": "fsl.bet.run", "score": 0.8, "source": "neurokg"},
            ]

    ctx: dict[str, object] = {}
    candidates = preflight.ensure_tool_candidates(
        "test query",
        ctx,
        tool_retriever=_StubRetriever(),
        registry=None,
    )

    assert candidates == [
        {
            "tool_id": "fetch_atlas",
            "tool_id_raw": "python.fetch_atlas.run",
            "score": 0.9,
            "source": "neurokg",
            "available": None,
            "registry_available": None,
            "catalog_available": True,
            "rank": 1,
        },
        {
            "tool_id": "fsl_bet",
            "tool_id_raw": "fsl.bet.run",
            "score": 0.8,
            "source": "neurokg",
            "available": None,
            "registry_available": None,
            "catalog_available": True,
            "rank": 2,
        },
    ]
    assert ctx["tool_candidates"] == candidates
