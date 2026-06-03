"""Unit tests for knowledge evidence connectors and KG hints."""

import os

import pytest

from brain_researcher.services.agent.knowledge.evidence_connector import (
    EvidenceAggregator,
    EvidenceConnector,
)
from brain_researcher.services.agent.knowledge.evidence_models import (
    EvidenceItem,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.evidence.tool_source import ToolEvidenceSource


class DummyConnector(EvidenceConnector):
    @property
    def source_name(self) -> str:
        return "dummy"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.KG_GRAPH

    async def search(self, query: str, limit: int = 10) -> list[EvidenceItem]:
        return []

    async def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_dataset_hints_injected_into_bundle():
    aggregator = EvidenceAggregator(connectors=[DummyConnector()], enable_cache=False)
    hints = [{"dataset_id": "ds000001", "name": "Test Dataset"}]
    bundle = await aggregator.gather_evidence(
        query="test query",
        limit=5,
        dataset_hints=hints,
    )
    ids = [
        item.source_id
        for item in bundle.items
        if item.source_type == EvidenceSourceType.DATASET_CATALOG
    ]
    assert "ds000001" in ids
    hint_item = next(item for item in bundle.items if item.source_id == "ds000001")
    assert hint_item.metadata.get("source") == "kg_hint"


def test_tool_evidence_source_kg_query(monkeypatch):
    os.environ["BR_KG_TOOL_DISCOVERY"] = "1"

    class StubRegistry:
        def get_tools_for_task(self, query: str, k: int = 10):
            return []

    def fake_search_tools_structured(*args, **kwargs):
        return {
            "candidates": [
                {
                    "tool_id": "fsl.bet",
                    "method": "bet",
                    "software": "fsl",
                    "op_key": "bet",
                    "version": "6.0.7",
                }
            ]
        }

    def fake_resolve_tool_structured(*args, **kwargs):
        return {"recommendation": {"tool_id": "fsl.bet"}}

    monkeypatch.setenv("BR_KG_TOOL_DISCOVERY", "1")
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        fake_search_tools_structured,
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.resolve_tool_structured",
        fake_resolve_tool_structured,
    )

    source = ToolEvidenceSource(registry=StubRegistry(), use_kg=True)
    results = source.query_sync(type("Q", (), {"text": "skull strip", "limit": 5}))

    assert results
    top = results[0]
    assert top.id == "fsl.bet"
    assert top.payload.get("source") == "br_kg"
