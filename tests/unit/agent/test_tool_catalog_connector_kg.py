import pytest

from brain_researcher.services.agent.knowledge.evidence_connector import (
    ToolCatalogConnector,
)
from brain_researcher.services.agent.knowledge.evidence_models import EvidenceSourceType


class _FakeTool:
    def __init__(self, name: str, desc: str = ""):
        self._name = name
        self._desc = desc

    def get_tool_name(self):
        return self._name

    def get_tool_description(self):
        return self._desc


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = {t.get_tool_name(): t for t in tools}

    def get_all_tools(self):
        return list(self._tools.values())

    def get_tool(self, name):
        return self._tools.get(name)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("BR_KG_TOOL_DISCOVERY", raising=False)


@pytest.mark.asyncio
async def test_tool_catalog_connector_kg_enabled_uses_kg(monkeypatch):
    # Arrange KG responses
    monkeypatch.setenv("BR_KG_TOOL_DISCOVERY", "1")
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.search_tools_structured",
        lambda **_: {
            "candidates": [
                {
                    "tool_id": "kg_tool_v1",
                    "method": "glm",
                    "software": "fsl",
                    "op_key": "feat",
                    "version": "1.0",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "brain_researcher.services.br_kg.query_service.resolve_tool_structured",
        lambda **_: {
            "recommendation": {
                "tool_id": "kg_tool_v1.run",
                "method": "glm",
                "software": "fsl",
                "op_key": "feat",
                "version": "1.0",
            }
        },
    )

    registry = _FakeRegistry(tools=[])
    connector = ToolCatalogConnector(registry=registry)

    # Act
    items = await connector.search("glm", limit=5)

    # Assert
    assert items
    item = items[0]
    assert item.source_type == EvidenceSourceType.TOOL_CATALOG
    assert item.source_id == "kg_tool_v1.run"
    assert item.metadata.get("available") is False
    assert item.metadata.get("source") == "br_kg"
    assert "resolved_to=kg_tool_v1.run" in item.metadata.get("reason", "")


@pytest.mark.asyncio
async def test_tool_catalog_connector_registry_fallback(monkeypatch):
    # Disable KG path
    monkeypatch.delenv("BR_KG_TOOL_DISCOVERY", raising=False)
    tool = _FakeTool("local_tool", "does glm")
    registry = _FakeRegistry(tools=[tool])
    connector = ToolCatalogConnector(registry=registry)

    items = await connector.search("glm", limit=5)

    assert items
    item = items[0]
    assert item.source_id == "local_tool"
    assert item.metadata["available"] is True
    assert item.metadata["source"] == "registry"
