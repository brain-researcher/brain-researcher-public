import importlib
import os

from brain_researcher.services.shared import settings as settings_module


def _reload_settings(env: dict[str, str]):
    for key in [
        "BR_PLANNER_MODE",
        "AGENT_TOOL_ALLOWLIST",
        "BR_ENABLE_CODE_AGENT_TOOL",
        "BR_SANDBOX_ENABLED",
        "BR_DAG_MAX_CONCURRENCY",
    ]:
        if key in env:
            os.environ[key] = env[key]
        elif key in os.environ:
            del os.environ[key]
    importlib.reload(settings_module)
    # clear lru cache
    settings_module.get_settings.cache_clear()  # type: ignore[attr-defined]
    return settings_module.get_settings()


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("BR_PLANNER_MODE", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)
    monkeypatch.delenv("BR_SANDBOX_ENABLED", raising=False)
    monkeypatch.delenv("BR_DAG_MAX_CONCURRENCY", raising=False)

    importlib.reload(settings_module)
    settings_module.get_settings.cache_clear()  # type: ignore[attr-defined]

    settings = settings_module.get_settings()

    assert settings.planner_mode == "advisor"
    assert settings.tool_allowlist is None
    assert settings.enable_code_agent_tool is False
    assert settings.sandbox_enabled is True
    assert settings.dag_max_concurrency == 1
    assert settings.allow_all_tools is True
    assert settings.is_tool_allowed("code_agent") is False


def test_settings_parsing_custom_values(monkeypatch):
    monkeypatch.setenv("BR_PLANNER_MODE", "autorun")
    monkeypatch.setenv(
        "AGENT_TOOL_ALLOWLIST", "fsl.bet,nilearn_connectivity,code_agent"
    )
    monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")
    monkeypatch.setenv("BR_SANDBOX_ENABLED", "false")
    monkeypatch.setenv("BR_DAG_MAX_CONCURRENCY", "4")

    importlib.reload(settings_module)
    settings_module.get_settings.cache_clear()  # type: ignore[attr-defined]

    settings = settings_module.get_settings()

    assert settings.planner_mode == "autorun"
    assert settings.tool_allowlist == [
        "fsl.bet",
        "nilearn_connectivity",
        "code_agent",
    ]
    assert settings.enable_code_agent_tool is True
    assert settings.sandbox_enabled is False
    assert settings.dag_max_concurrency == 4
    assert settings.is_tool_allowed("fsl.bet") is True
    assert settings.is_tool_allowed("unknown") is False
    assert settings.is_tool_allowed("code_agent") is True


def test_disabled_mode_preserved(monkeypatch):
    monkeypatch.setenv("BR_PLANNER_MODE", "disabled")
    importlib.reload(settings_module)
    settings_module.get_settings.cache_clear()  # type: ignore[attr-defined]

    settings = settings_module.get_settings()
    assert settings.planner_mode == "disabled"
