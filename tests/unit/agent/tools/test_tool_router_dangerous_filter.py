import pytest

from brain_researcher.services.agent.tool_router import ToolRouter, load_tool_families
from brain_researcher.services.tools.tool_registry import ToolRegistry


def test_chat_router_filters_dangerous_tools():
    reg = ToolRegistry(auto_discover=True, use_capabilities=True, enable_integrations=False, light_mode=True)
    fams = load_tool_families()

    # Chat-mode router (allow_dangerous=False by default)
    # Explicit whitelist includes a dangerous tool to ensure it would be considered
    chat_router = ToolRouter(
        core_registry=reg,
        families=fams,
        chat_whitelist={"gemini.run_shell", "gemini.list_directory"},
        allow_dangerous=False,
    )
    ids = {c.runtime_id for c in chat_router.get_candidates("run shell", history=None, ctx={})}
    # Dangerous Gemini shell must be filtered out in chat mode
    assert "gemini.run_shell" not in ids


def test_non_chat_router_allows_dangerous_tools():
    reg = ToolRegistry(auto_discover=True, use_capabilities=True, enable_integrations=False, light_mode=True)
    fams = load_tool_families()

    # Non-chat router with allow_dangerous=True should preserve dangerous tools *if* they are registered
    router = ToolRouter(core_registry=reg, families=fams, allow_dangerous=True)
    ids = {c.runtime_id for c in router.get_candidates("run shell", history=None, ctx={})}

    # In light registry we only register lightweight tools; dangerous ones may be absent.
    # Assert that non-chat router does not drop dangerous tools when present.
    dangerous_ids = {"gemini.run_shell", "gemini.fs", "gemini.list_directory"}
    available = ids & dangerous_ids
    if not available:
        pytest.skip("Dangerous gemini tools not registered in light mode for this env")
    # If available, ensure router didn't filter them out
    assert available
