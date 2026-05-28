"""Tests for catalog_generator (MCP → capabilities)."""

from brain_researcher.services.agent.planner import catalog_generator as gen


def test_generate_capabilities_filters_and_tags():
    tool_defs = [
        {"name": "fsl.bet.run", "entrypoint": "fsl.bet.run"},
        {"name": "unknown.tool"},
        {"name": "mne.source"},
    ]

    caps = gen.generate_capabilities(tool_defs, ["fsl", "mne"])
    ids = [c["id"] for c in caps]
    assert "fsl.bet.run" in ids
    assert "mne.source" in ids
    assert "unknown.tool" not in ids

    bet = next(c for c in caps if c["id"] == "fsl.bet.run")
    assert bet["runtime_kind"] == "container"
    assert bet["metadata"]["source"] == "mcp_auto"


def test_default_allowed_prefixes_nonempty():
    prefixes = gen.default_allowed_prefixes()
    assert "fsl" in prefixes
    assert len(prefixes) > 5

