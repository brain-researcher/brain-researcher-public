from __future__ import annotations

from brain_researcher.services.orchestrator.nl2tool import select_tool
from brain_researcher.services.orchestrator.models import PipelineType


def test_code_profile_forces_coding_rule():
    d = select_tool(
        "open the main orchestrator file and show first lines",
        profile="code",
    )
    assert d.profile == "code"
    # Alias for coding rule
    assert d.tool == "code"
    # Resolved concrete tool should be one of the fs tools (from fallback or MCP)
    assert d.resolved_tool in {"fs.read", "fs.apply_patch"}
    # Metadata carries profile
    md = d.to_metadata()
    assert md.get("profile") == "code"


def test_coding_keywords_trigger_without_profile():
    d = select_tool("please read src file and print first 20 lines")
    assert d.tool in {"code", "agent"}
    # If coding rule matched, resolved_tool will be present
    if d.tool == "code":
        assert d.resolved_tool in {"fs.read", "fs.apply_patch"}
