import json
from types import SimpleNamespace

import pytest

from brain_researcher.services.tools import gemini_cli_tools as gct
from brain_researcher.services.tools.tool_registry import ToolRegistry


class DummyCompleted:
    def __init__(self, stdout: str = "{}", stderr: str = "", returncode: int = 0):
        self.stdout = stdout.encode("utf-8")
        self.stderr = stderr.encode("utf-8")
        self.returncode = returncode


def test_list_directory_parses_json(monkeypatch):
    calls = []

    def fake_run(args, input=None, stdout=None, stderr=None, check=None, timeout=None):
        calls.append(args)
        return DummyCompleted(stdout=json.dumps({"files": ["a.txt", "b.txt"]}))

    monkeypatch.setattr(gct.subprocess, "run", fake_run)

    tool = gct.GeminiListDirectory()
    result = tool._run(path=".")

    assert result.status == "success"
    assert result.data == {"files": ["a.txt", "b.txt"]}
    assert calls[0][0:2] == ["gemini", "list"]


def test_registry_registers_gemini_tools(monkeypatch):
    # Avoid slow discovery; keep light mode and stub heavy parts if needed
    reg = ToolRegistry(auto_discover=True, use_capabilities=True, enable_integrations=False, light_mode=True)
    gemini_tools = [t for t in reg.get_all_tools() if t.get_tool_name().startswith("gemini.")]
    assert len(gemini_tools) >= 5  # list/read/search + web_fetch/google_search at least
