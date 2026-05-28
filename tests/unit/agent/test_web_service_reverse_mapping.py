from __future__ import annotations

from brain_researcher.services.agent import web_service as ws


def test_resolve_tool_signature_prefers_canonical_runtime_id(monkeypatch):
    class Tool:
        def __init__(self, consumes, produces):
            self.consumes = consumes
            self.produces = produces

    tools = {
        "fsl_bet": Tool(["input_brain"], ["bet_mask"]),
        "fsl.bet.run": Tool(["legacy_input"], ["legacy_output"]),
    }

    monkeypatch.setattr(ws, "get_tool_by_id", lambda tool_id: tools.get(tool_id))
    monkeypatch.setattr(
        "brain_researcher.services.tools.catalog_loader.resolve_catalog_tool_ids",
        lambda tool_id, include_self=False: ["fsl.bet.run"] if tool_id == "fsl_bet" else [],
    )

    consumes, produces = ws._resolve_tool_signature("fsl.bet.run")

    assert consumes == {"input_brain"}
    assert produces == {"bet_mask"}
