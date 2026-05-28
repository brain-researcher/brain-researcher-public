from __future__ import annotations

from brain_researcher.services.mcp import server as srv


def test_retired_tool_surface_metadata() -> None:
    assert srv._mcp_surface_metadata("tribe_predict") == {}
    assert srv._mcp_surface_metadata("asl_quant_review") == {}


def test_retired_tool_functions_are_removed_from_mcp_entrypoint() -> None:
    assert not hasattr(srv, "tribe_predict")
    assert not hasattr(srv, "asl_quant_review")


def test_retired_tools_are_not_exposed_via_mcp_surface() -> None:
    reg = srv._get_registry()
    reg.get_all_toolspecs(force_reload=True)
    reg.get_exposed_toolspecs(force_reload=True)

    public_names = {
        tool.name for tool in srv._run_async_sync(srv.mcp._tool_manager.list_tools())
    }
    search_resp = srv.tool_search(
        "TRIBE video audio text ASL quantification review",
        limit=50,
        exposed_only=True,
    )

    assert search_resp["ok"] is True
    search_names = {tool["name"] for tool in search_resp["tools"]}

    assert srv._MCP_RETIRED_PUBLIC_TOOL_NAMES.isdisjoint(public_names)
    assert srv._MCP_RETIRED_PUBLIC_TOOL_NAMES.isdisjoint(search_names)

    for tool_name in srv._MCP_RETIRED_PUBLIC_TOOL_NAMES:
        detail_resp = srv.tool_get(tool_name)
        execute_resp = srv.tool_execute(tool_name, params={}, preview=True)

        assert detail_resp["ok"] is False
        assert detail_resp["error"] == "tool_removed"
        assert execute_resp["ok"] is False
        assert execute_resp["error"] == "tool_removed"
