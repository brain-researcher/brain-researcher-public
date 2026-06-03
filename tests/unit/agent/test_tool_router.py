import pytest
from types import SimpleNamespace

from brain_researcher.services.agent.tool_router import (
    ToolFamily,
    RoutingView,
    ToolRouter,
)


class FakeRuntimeTool:
    def __init__(self, tool_id, name, description, tags=None, dangerous=False):
        self._id = tool_id
        self._name = name
        self._description = description
        self._tags = tags or []
        self._dangerous = dangerous

    # Chat router uses spec_from_tool(tool) which calls these methods
    def get_tool_name(self):
        return self._name

    def get_tool_description(self):
        return self._description

    def get_args_schema(self):
        # minimal schema
        return SimpleNamespace(model_json_schema=lambda: {})

    # metadata consumed by spec_from_tool
    CATEGORY = None
    ARG_SYNONYMS = {}
    EXAMPLES = []
    SAFETY = []
    TAGS = []
    dangerous = False


class FakeRuntimeRegistry:
    def __init__(self, tools):
        self._tools = tools

    def get_all_tools(self):
        return self._tools


def make_family_br_kg_client():
    return ToolFamily(
        id="br_kg.client",
        description="Client for BR-KG",
        op_param="op",
        ops={
            "search_datasets": "br_kg.search_datasets",
            "search_tasks": "br_kg.search_tasks",
        },
    )


def test_family_folding_and_leaf_remaining():
    t1 = FakeRuntimeTool(
        "br_kg.search_datasets",
        "br_kg.search_datasets",
        "search datasets",
        ["br_kg"],
    )
    t2 = FakeRuntimeTool(
        "br_kg.search_tasks", "br_kg.search_tasks", "search tasks", ["br_kg"]
    )
    t3 = FakeRuntimeTool("other.tool", "other.tool", "something else", ["other"])

    registry = FakeRuntimeRegistry([t1, t2, t3])
    families = {"br_kg.client": make_family_br_kg_client()}

    view = RoutingView(registry, families=families)
    views = view.all_tools()

    assert len(views) == 2  # 1 family + 1 remaining leaf
    by_id = {v.runtime_id: v for v in views}
    assert "br_kg.client" in by_id
    assert "other.tool" in by_id
    fam_view = by_id["br_kg.client"]
    assert fam_view.family_id == "br_kg.client"
    assert set(fam_view.family_ops) == {"search_datasets", "search_tasks"}


def test_family_view_inherits_danger_from_members():
    dangerous_leaf = FakeRuntimeTool(
        "neurodesk_command",
        "neurodesk_command",
        "heavy execution",
        ["family"],
    )
    other_leaf = FakeRuntimeTool(
        "family.search",
        "family.search",
        "safe search",
        ["family"],
    )
    registry = FakeRuntimeRegistry([dangerous_leaf, other_leaf])
    families = {
        "family.client": ToolFamily(
            id="family.client",
            description="Family view",
            op_param="op",
            ops={"exec": "neurodesk_command", "search": "family.search"},
        )
    }

    view = RoutingView(registry, families=families)
    by_id = {tool.runtime_id: tool for tool in view.all_tools()}

    assert by_id["family.client"].dangerous is True


def test_chat_whitelist_and_dangerous_filter(monkeypatch):
    safe = SimpleNamespace(
        runtime_id="safe.tool",
        name="safe.tool",
        description="safe",
        tags=["chat_safe"],
        dangerous=False,
        family_id=None,
        family_ops=None,
        selection_stub=lambda: "safe",
    )
    dangerous = SimpleNamespace(
        runtime_id="danger.tool",
        name="danger.tool",
        description="danger",
        tags=["chat_safe"],
        dangerous=True,
        family_id=None,
        family_ops=None,
        selection_stub=lambda: "danger",
    )
    non_whitelisted = SimpleNamespace(
        runtime_id="other.tool",
        name="other.tool",
        description="no",
        tags=["chat_safe"],
        dangerous=False,
        family_id=None,
        family_ops=None,
        selection_stub=lambda: "other",
    )

    class DummyReg:
        pass

    router = ToolRouter(core_registry=DummyReg(), chat_whitelist={"safe.tool"})
    router.view = SimpleNamespace(all_tools=lambda: [safe, dangerous, non_whitelisted])

    candidates = router.get_candidates("whatever", history=[], ctx={"chat_mode": True})
    ids = [c.runtime_id for c in candidates]
    assert ids == ["safe.tool"]


def test_explicit_empty_whitelist_is_fail_closed():
    safe = SimpleNamespace(
        runtime_id="safe.tool",
        name="safe.tool",
        description="safe",
        tags=["chat_safe"],
        dangerous=False,
        family_id=None,
        family_ops=None,
        selection_stub=lambda: "safe",
    )

    class DummyReg:
        pass

    router = ToolRouter(core_registry=DummyReg(), chat_whitelist=set())
    router.view = SimpleNamespace(all_tools=lambda: [safe])

    candidates = router.get_candidates("whatever", history=[], ctx={"chat_mode": True})
    assert candidates == []
