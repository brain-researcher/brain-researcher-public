"""Smoke test to ensure declarative workflow catalog is runnable in light mode."""

from __future__ import annotations

from pathlib import Path
import yaml

from brain_researcher.services.tools.tool_registry import ToolRegistry


def _load_catalog() -> list[dict]:
    repo_root = Path(__file__).resolve().parents[3]
    catalog_path = repo_root / "configs" / "workflows" / "workflow_catalog.yaml"
    data = yaml.safe_load(catalog_path.read_text()) or {}
    return data.get("workflows") or []


def test_workflow_steps_have_registered_tools(monkeypatch):
    # Force lightweight discovery and enable Grandmaster YAML surface
    monkeypatch.setenv("TOOL_DISCOVERY_MODE", "light")
    monkeypatch.setenv("BR_GRANDMASTER_ENABLE", "1")
    monkeypatch.setenv("BR_GRANDMASTER_STUBS", "1")

    registry = ToolRegistry(auto_discover=True, light_mode=True)
    available = set(registry.tools.keys())

    missing: dict[str, list[str]] = {}
    for wf in _load_catalog():
        wf_id = wf.get("id", "<unknown>")
        runtime = wf.get("runtime") or {}
        for step in runtime.get("steps") or []:
            tool_id = step.get("tool")
            if tool_id and tool_id not in available:
                missing.setdefault(wf_id, []).append(tool_id)

    assert not missing, f"Missing tools in catalog: {missing}"
