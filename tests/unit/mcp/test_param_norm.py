from __future__ import annotations

import asyncio
import json

from brain_researcher.services.mcp.param_norm import (
    as_str_list,
    coerce_enum,
    enum_str,
    resolve_enum_or_error,
)


def test_coerce_enum_normalizes_and_never_raises():
    aliases = {"out": "out", "outgoing": "out", "in": "in", "both": "both"}
    assert coerce_enum("OUT", aliases, "both") == "out"
    assert coerce_enum("outgoing", aliases, "both") == "out"
    assert coerce_enum("nonsense", aliases, "both") == "both"  # unknown -> default
    assert coerce_enum("", aliases, "both") == "both"
    assert coerce_enum(None, aliases, "both") == "both"


def test_resolve_enum_or_error_lists_allowed_when_unmappable():
    aliases = {"guide": "guide", "command": "command", "cmd": "command"}
    val, err = resolve_enum_or_error("cmd", aliases, field="action")
    assert (val, err) == ("command", None)
    val, err = resolve_enum_or_error("bogus", aliases, field="action")
    assert val is None
    assert err["error"] == "invalid_arguments"
    assert err["allowed"] == ["command", "guide"]
    assert "action must be one of" in err["message"]
    # with a default, unknown coerces instead of erroring
    val, err = resolve_enum_or_error("bogus", aliases, field="action", default="guide")
    assert (val, err) == ("guide", None)


def test_as_str_list_accepts_scalar_or_list():
    assert as_str_list(None) == []
    assert as_str_list("single") == ["single"]
    assert as_str_list("a, b\nc; d") == ["a", "b", "c", "d"]
    assert as_str_list(["x", " y ", ""]) == ["x", "y"]
    assert as_str_list(("p", "q")) == ["p", "q"]
    assert as_str_list(123) == ["123"]


def test_enum_str_advertises_enum_but_is_permissive_under_pep563():
    from mcp.server.fastmcp import FastMCP

    m = FastMCP("param-norm-test")

    @m.tool()
    def sample(
        direction: enum_str(("out", "in", "both"), "traversal direction") = "both",
    ) -> dict:
        return {"direction": direction}

    async def go():
        tools = await m.list_tools()
        schema = next(t.inputSchema for t in tools if t.name == "sample")
        assert schema["properties"]["direction"]["enum"] == ["out", "in", "both"]
        # advertised, but NOT enforced server-side -> a synonym still reaches the fn
        res = await m.call_tool("sample", {"direction": "outgoing"})
        return res

    asyncio.run(go())


def _find_enum(prop: dict) -> list | None:
    """Return the enum for a param, unwrapping Optional (anyOf) branches."""
    if not isinstance(prop, dict):
        return None
    if prop.get("enum"):
        return prop["enum"]
    for sub in prop.get("anyOf", []) or []:
        found = _find_enum(sub)
        if found:
            return found
    return None


def test_hardened_categorical_params_advertise_enums_on_live_surface():
    """Contract guard: the categorical params hardened to the param_norm contract
    must advertise their enum in the live MCP schema. This catches the PEP-563
    regression where Annotated[str, Field(...)] metadata can silently drop.
    """
    from brain_researcher.services.mcp import server as srv

    # Use the high-level server list_tools() -> MCP wire Tool objects (.inputSchema),
    # not _tool_manager.list_tools() which returns internal Tool objects (.parameters).
    tools = srv._run_async_sync(srv.mcp.list_tools())
    props_by_tool = {t.name: (t.inputSchema or {}).get("properties", {}) for t in tools}

    expected = {
        "slurm_submit": ["action", "cluster_profile", "template_kind", "stream"],
        "deepxiv": ["action", "search_mode"],
        "memory_write": ["card_type"],
        "plan_create": ["allowlist_mode"],
        "grounding_gate_evidence_basis": ["alignment_mode", "partial_action"],
        "get_execution_recipe": ["target_runtime"],
        "kg_neighbors": ["direction"],
        "kg_multihop_qa": ["mode"],
        "kg_detect_topology_shifts": ["mode"],
        "kg_hypothesis_candidate_cards": [
            "candidate_lane_mode",
            "frontier_mode",
            "taste_mode",
            "controller_mode",
        ],
        "kg_hypothesis_workflow": ["strategy", "candidate_lane_mode"],
    }
    problems = []
    for tool, fields in expected.items():
        props = props_by_tool.get(tool)
        if props is None:
            problems.append(f"{tool}: tool missing from surface")
            continue
        for field in fields:
            if not _find_enum(props.get(field, {})):
                problems.append(f"{tool}.{field}: enum not advertised")
    assert not problems, "; ".join(problems)
