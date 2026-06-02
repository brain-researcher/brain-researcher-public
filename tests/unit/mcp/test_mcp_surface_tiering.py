from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.mcp import server as srv
from brain_researcher.services.tools.spec import ToolSpec


def test_mcp_surface_metadata_normalizes_runtime_aliases():
    assert srv._mcp_surface_metadata("mcp.sherlock_guide") == {
        "surface_tier": "advanced",
        "capability_family": "sherlock",
    }
    assert srv._mcp_surface_metadata("google.file_search") == {
        "surface_tier": "advanced",
        "capability_family": "google_research",
    }
    assert srv._mcp_surface_metadata("br_kg.find_structural_leverage") == {
        "surface_tier": "advanced",
        "capability_family": "kg_probe",
    }


def test_toolspec_for_mcp_card_includes_surface_metadata():
    sherlock_spec = ToolSpec(
        name="mcp.sherlock_slurm",
        description="Render Sherlock scripts.",
        backend="python",
    )
    sherlock_card = srv._toolspec_for_mcp_card(sherlock_spec)
    assert sherlock_card["surface_tier"] == "advanced"
    assert sherlock_card["capability_family"] == "sherlock"

    search_spec = ToolSpec(
        name="mcp.tool_search",
        description="Search tool cards.",
        backend="python",
    )
    search_card = srv._toolspec_for_mcp_card(search_spec)
    assert search_card["surface_tier"] == "default"
    assert search_card["capability_family"] == "tool_discovery"


def test_docs_schema_includes_surface_tiering_fields():
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "mcp_tools.schema.json"
    doc = json.loads(doc_path.read_text())

    assert doc["schema_version"] == "2026-03-17"
    allowed_tiers = {"default", "advanced", "ops"}

    for tool in doc.get("tools", []):
        assert tool["surface_tier"] in allowed_tiers
        assert tool["tier"] == tool["surface_tier"]
        assert isinstance(tool["capability_family"], str)
        assert tool["capability_family"].strip()

    by_name = {tool["name"]: tool for tool in doc["tools"]}
    assert by_name["server_info"]["surface_tier"] == "ops"
    assert by_name["server_info"]["capability_family"] == "server_ops"
    assert by_name["pipeline_execute"]["surface_tier"] == "ops"
    assert by_name["run_cancel"]["surface_tier"] == "advanced"
    assert by_name["kg_neighbors"]["surface_tier"] == "default"
    assert by_name["kg_probe"]["surface_tier"] == "advanced"
    assert by_name["kg_hypothesis_workflow"]["surface_tier"] == "advanced"
    assert by_name["tool_search_structured"]["surface_tier"] == "advanced"
    assert "asl_quant_review" not in by_name
    assert "tribe_predict" not in by_name


def test_public_runtime_surface_has_metadata():
    runtime_names = {
        tool.name for tool in srv._run_async_sync(srv.mcp._tool_manager.list_tools())
    }

    assert runtime_names <= set(srv._MCP_SURFACE_METADATA_BY_NAME)


def test_docs_schema_matches_public_runtime_tool_surface():
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "mcp_tools.schema.json"
    doc = json.loads(doc_path.read_text())
    doc_names = {tool["name"] for tool in doc.get("tools", [])}
    runtime_names = {
        tool.name for tool in srv._run_async_sync(srv.mcp._tool_manager.list_tools())
    }

    assert doc_names == runtime_names
    assert not any(name.startswith("br_kg.") for name in doc_names)


def test_compatibility_aliases_are_hidden_from_public_tool_list():
    public_names = {
        tool.name for tool in srv._run_async_sync(srv.mcp._tool_manager.list_tools())
    }
    all_names = set(getattr(srv.mcp._tool_manager, "_tools", {}).keys())

    assert srv._MCP_COMPAT_TOOL_NAMES <= all_names
    assert srv._MCP_COMPAT_TOOL_NAMES.isdisjoint(public_names)
    assert srv._MCP_RETIRED_PUBLIC_TOOL_NAMES.isdisjoint(public_names)
    assert "kg_probe" in public_names
    assert "kg_hypothesis_workflow" in public_names
