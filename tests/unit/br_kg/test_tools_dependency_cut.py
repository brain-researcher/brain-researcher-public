import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BR_KG_ROOT = REPO_ROOT / "src/brain_researcher/services/br_kg"


def _source(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text()


def _direct_services_tools_imports() -> list[tuple[str, str]]:
    imports: list[tuple[str, str]] = []
    for path in sorted(BR_KG_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("brain_researcher.services.tools"):
                        imports.append(
                            (path.relative_to(REPO_ROOT).as_posix(), alias.name)
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("brain_researcher.services.tools"):
                    imports.append((path.relative_to(REPO_ROOT).as_posix(), module))
    return imports


class FakeTool:
    TAGS = ["fmri", "glm"]

    def get_tool_name(self) -> str:
        return "fake_glm"

    def get_tool_description(self) -> str:
        return "Fake GLM tool for testing the shared registry facade."


class FakeRegistry:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.tools = {"fake_glm": FakeTool()}

    def get_tool(self, name: str):
        return self.tools.get(name)

    def get_tools_for_task(self, task_description: str, k: int = 5):
        return list(self.tools.values())[:k]


def test_br_kg_catalog_fallback_avoids_tools_registry_imports():
    query_service = _source("src/brain_researcher/services/br_kg/query_service.py")
    assert "brain_researcher.services.tools.registry" not in query_service


def test_br_kg_tools_catalog_loader_owns_catalog_helpers():
    loader = _source(
        "src/brain_researcher/services/br_kg/loader/tools_catalog_loader.py"
    )
    assert "brain_researcher.services.tools.catalog_loader" not in loader


def test_br_kg_has_no_direct_services_tools_imports():
    assert _direct_services_tools_imports() == []


def test_tool_registry_facade_preserves_legacy_lazy_load(monkeypatch):
    from brain_researcher.services.shared import tool_registry_facade as facade

    captured_modules: list[str] = []

    def import_module(module_name: str):
        captured_modules.append(module_name)
        return SimpleNamespace(ToolRegistry=FakeRegistry)

    monkeypatch.setattr(facade, "_default_tool_registry_factory", None)
    monkeypatch.setattr(facade.importlib, "import_module", import_module)

    registry = facade.get_default_tool_registry(auto_discover=False, light_mode=True)

    assert isinstance(registry, FakeRegistry)
    assert registry.kwargs == {"auto_discover": False, "light_mode": True}
    assert captured_modules == ["brain_researcher.services.tools.tool_registry"]


@pytest.mark.asyncio
async def test_tool_connector_uses_shared_tool_registry_facade(monkeypatch):
    from brain_researcher.services.br_kg.evidence.connectors.tools import ToolConnector
    from brain_researcher.services.shared import tool_registry_facade as facade

    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return FakeRegistry(**kwargs)

    monkeypatch.setattr(facade, "_default_tool_registry_factory", factory)
    ToolConnector._registry = None
    ToolConnector._registry_init_attempted = False

    try:
        connector = ToolConnector()

        assert connector.is_available is True

        items = await connector.search("glm", limit=1)
        item = await connector.get_by_id("fake_glm")
    finally:
        ToolConnector._registry = None
        ToolConnector._registry_init_attempted = False

    assert factory_calls == [{"auto_discover": True, "light_mode": True}]
    assert items[0].id == "fake_glm"
    assert items[0].metadata["tool_class"] == "FakeTool"
    assert item is not None
    assert item.id == "fake_glm"


@pytest.mark.asyncio
async def test_tool_evidence_source_uses_shared_tool_registry_facade(monkeypatch):
    from brain_researcher.services.br_kg.knowledge.sources.tool import (
        ToolEvidenceSource,
    )
    from brain_researcher.services.shared import tool_registry_facade as facade

    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return FakeRegistry(**kwargs)

    monkeypatch.setattr(facade, "_default_tool_registry_factory", factory)

    source = ToolEvidenceSource(light_mode=False)

    assert await source.is_available() is True

    items = await source.search("glm", limit=1, filters={"tags": ["fmri"]})
    item = await source.get_by_id("tool:fake_glm")

    assert factory_calls == [{"auto_discover": True, "light_mode": False}]
    assert items[0].id == "tool:fake_glm"
    assert items[0].metadata["tags"] == ["fmri", "glm"]
    assert item is not None
    assert item.id == "tool:fake_glm"
