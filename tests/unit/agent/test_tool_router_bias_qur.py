from brain_researcher.services.agent.tool_router import RoutingToolView, ToolRouter
from brain_researcher.services.tools.tool_registry import ToolRegistry


class DummySpec(RoutingToolView):
    def __init__(self, runtime_id: str, tags=None):
        super().__init__(
            runtime_id=runtime_id,
            name=runtime_id,
            description=runtime_id,
            tags=tags or [],
        )


def test_router_bias_dataset(monkeypatch):
    # minimal router with two tools
    registry = ToolRegistry(auto_discover=False)
    router = ToolRouter(core_registry=registry, chat_whitelist=None)

    specs = [
        DummySpec("generic", tags=["generic"]),
        DummySpec("datasets.list_resources", tags=["dataset_catalog"]),
    ]
    monkeypatch.setattr(router.view, "all_tools", lambda: specs)

    qur = {"resolved_datasets": ["ds000001"]}
    ranked = router.get_candidates("run ds000001", ctx={"query_understanding": qur})

    assert ranked[0].runtime_id == "datasets.list_resources"


def test_router_no_bias_without_qur(monkeypatch):
    registry = ToolRegistry(auto_discover=False)
    router = ToolRouter(core_registry=registry, chat_whitelist=None)

    specs = [
        DummySpec("generic", tags=["generic"]),
        DummySpec("datasets.list_resources", tags=["dataset_catalog"]),
    ]
    monkeypatch.setattr(router.view, "all_tools", lambda: specs)

    ranked = router.get_candidates("generic task", ctx={})
    # ordering should remain as returned when scores tie (bias absent)
    assert ranked[0].runtime_id in {"generic", "datasets.list_resources"}


def test_router_prefers_dataset_inventory_for_exploratory_dataset_queries(monkeypatch):
    registry = ToolRegistry(auto_discover=False)
    router = ToolRouter(core_registry=registry, chat_whitelist=None)

    specs = [
        DummySpec("resolve_dataset_asset", tags=["dataset", "safe"]),
        DummySpec(
            "list_dataset_assets",
            tags=["dataset_catalog", "inventory", "derivative"],
        ),
    ]
    monkeypatch.setattr(router.view, "all_tools", lambda: specs)

    qur = {"resolved_datasets": ["ds000114"]}
    ranked = router.get_candidates(
        "what files and derivatives are available in ds000114",
        ctx={"query_understanding": qur},
    )

    assert ranked[0].runtime_id == "list_dataset_assets"


def test_router_prefers_list_dataset_assets_for_exploratory_dataset_asset_query(
    monkeypatch,
):
    registry = ToolRegistry(auto_discover=False)
    router = ToolRouter(core_registry=registry, chat_whitelist=None)

    specs = [
        DummySpec("resolve_dataset_asset", tags=["dataset"]),
        DummySpec("list_dataset_assets", tags=["dataset"]),
        DummySpec("generic", tags=["generic"]),
    ]
    monkeypatch.setattr(router.view, "all_tools", lambda: specs)

    qur = {"resolved_datasets": ["ds000114"]}
    ranked = router.get_candidates(
        "list available dataset assets and derivatives for ds000114",
        ctx={"query_understanding": qur},
    )

    assert ranked[0].runtime_id == "list_dataset_assets"


def test_router_does_not_force_browse_for_concrete_dataset_resolve_query(monkeypatch):
    registry = ToolRegistry(auto_discover=False)
    router = ToolRouter(core_registry=registry, chat_whitelist=None)

    specs = [
        DummySpec("resolve_dataset_asset", tags=["dataset"]),
        DummySpec("list_dataset_assets", tags=["dataset"]),
    ]
    monkeypatch.setattr(router.view, "all_tools", lambda: specs)

    qur = {"resolved_datasets": ["ds000114"]}
    ranked = router.get_candidates(
        "resolve the exact confounds path for ds000114",
        ctx={"query_understanding": qur},
    )

    assert ranked[0].runtime_id == "resolve_dataset_asset"
