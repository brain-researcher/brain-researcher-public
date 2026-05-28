from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import claude_agent_sdk
from mcp.types import CallToolRequest, CallToolRequestParams

from brain_researcher.integrations.notebook_intelligence.runtime_patches import (
    apply_notebook_intelligence_runtime_patches,
)


class _FakeTool:
    def __init__(self):
        self.handler = None


class _FakeResponse:
    def __init__(self, result):
        self._result = result
        self.calls: list[tuple[str, dict]] = []

    async def run_ui_command(self, command: str, args: dict | None = None):
        self.calls.append((command, args or {}))
        return self._result


def _install_fake_claude_module(monkeypatch, tmp_path: Path, *, result):
    fake_tool = _FakeTool()
    fake_rename_tool = _FakeTool()
    fake_open_file_tool = _FakeTool()
    fake_response = _FakeResponse(result)
    root_dir = tmp_path / "workspace"
    root_dir.mkdir()

    fake_module = ModuleType("notebook_intelligence.claude")
    fake_module.create_new_notebook = fake_tool
    fake_module.rename_notebook = fake_rename_tool
    fake_module.open_file_in_jupyter_ui = fake_open_file_tool
    fake_module.get_current_response = lambda: fake_response
    fake_module.get_jupyter_root_dir = lambda: str(root_dir)
    fake_module.tool_text_response = lambda text: {
        "content": [{"type": "text", "text": text}]
    }
    fake_package = ModuleType("notebook_intelligence")
    fake_package.__path__ = []  # type: ignore[attr-defined]
    fake_package.claude = fake_module

    monkeypatch.setattr(
        "brain_researcher.integrations.notebook_intelligence.runtime_patches.logger",
        SimpleNamespace(info=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(sys.modules, "notebook_intelligence", fake_package)
    monkeypatch.setitem(sys.modules, "notebook_intelligence.claude", fake_module)
    return fake_module, fake_response, root_dir


def test_patch_preserves_serializable_notebook_path(monkeypatch, tmp_path: Path):
    fake_module, fake_response, _root_dir = _install_fake_claude_module(
        monkeypatch,
        tmp_path,
        result={"path": "Untitled.ipynb"},
    )

    apply_notebook_intelligence_runtime_patches()

    result = asyncio.run(fake_module.create_new_notebook.handler({}))

    assert result["content"][0]["text"] == "Created new notebook at Untitled.ipynb"
    assert fake_response.calls == [
        ("notebook-intelligence:create-new-notebook-from-py", {"code": ""})
    ]


def test_patch_converts_placeholder_rename_result_to_success(monkeypatch, tmp_path: Path):
    fake_module, fake_response, root_dir = _install_fake_claude_module(
        monkeypatch,
        tmp_path,
        result="Could not serialize the result",
    )

    original_run_ui_command = fake_module.get_current_response().run_ui_command

    async def _run_ui_command_and_create_file(command: str, args: dict | None = None):
        result = await original_run_ui_command(command, args)
        (root_dir / "renamed.ipynb").write_text("{}", encoding="utf-8")
        return result

    fake_module.get_current_response().run_ui_command = _run_ui_command_and_create_file

    apply_notebook_intelligence_runtime_patches()

    result = asyncio.run(
        fake_module.rename_notebook.handler({"new_name": "renamed.ipynb"})
    )

    assert result["content"][0]["text"] == "Renamed notebook to renamed.ipynb"
    assert fake_response.calls == [
        ("notebook-intelligence:rename-notebook", {"newName": "renamed.ipynb"})
    ]


def test_patch_recovers_notebook_path_when_ui_result_is_not_serializable(
    monkeypatch,
    tmp_path: Path,
):
    fake_module, _fake_response, root_dir = _install_fake_claude_module(
        monkeypatch,
        tmp_path,
        result="Could not serialize the result",
    )

    original_run_ui_command = fake_module.get_current_response().run_ui_command

    async def _run_ui_command_and_create_file(command: str, args: dict | None = None):
        result = await original_run_ui_command(command, args)
        (root_dir / "Untitled.ipynb").write_text("{}", encoding="utf-8")
        return result

    fake_module.get_current_response().run_ui_command = _run_ui_command_and_create_file

    apply_notebook_intelligence_runtime_patches()

    result = asyncio.run(fake_module.create_new_notebook.handler({}))

    assert result["content"][0]["text"] == "Created new notebook at Untitled.ipynb"


def test_patch_fixes_sdk_mcp_call_tool_result_shape(monkeypatch, tmp_path: Path):
    original_factory = claude_agent_sdk.create_sdk_mcp_server
    fake_module, _fake_response, _root_dir = _install_fake_claude_module(
        monkeypatch,
        tmp_path,
        result={"path": "Untitled.ipynb"},
    )
    fake_module.create_sdk_mcp_server = original_factory

    try:
        apply_notebook_intelligence_runtime_patches()

        @claude_agent_sdk.tool("hello", "Return hello", {})
        async def hello(args):
            return {"content": [{"type": "text", "text": "hello"}]}

        config = claude_agent_sdk.create_sdk_mcp_server("test-nbi", tools=[hello])
        handler = config["instance"].request_handlers[CallToolRequest]
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="hello", arguments={}),
        )

        result = asyncio.run(handler(req))

        assert result.root.isError is False
        assert result.root.content[0].text == "hello"
    finally:
        claude_agent_sdk.create_sdk_mcp_server = original_factory


def test_patch_converts_sdk_tool_is_error_to_mcp_error(monkeypatch, tmp_path: Path):
    original_factory = claude_agent_sdk.create_sdk_mcp_server
    fake_module, _fake_response, _root_dir = _install_fake_claude_module(
        monkeypatch,
        tmp_path,
        result={"path": "Untitled.ipynb"},
    )
    fake_module.create_sdk_mcp_server = original_factory

    try:
        apply_notebook_intelligence_runtime_patches()

        @claude_agent_sdk.tool("boom", "Return an error", {})
        async def boom(args):
            return {
                "content": [{"type": "text", "text": "boom failed"}],
                "is_error": True,
            }

        config = claude_agent_sdk.create_sdk_mcp_server("test-nbi", tools=[boom])
        handler = config["instance"].request_handlers[CallToolRequest]
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="boom", arguments={}),
        )

        result = asyncio.run(handler(req))

        assert result.root.isError is True
        assert result.root.content[0].text == "boom failed"
    finally:
        claude_agent_sdk.create_sdk_mcp_server = original_factory


def test_patch_converts_placeholder_open_file_result_to_success(
    monkeypatch,
    tmp_path: Path,
):
    fake_module, fake_response, _root_dir = _install_fake_claude_module(
        monkeypatch,
        tmp_path,
        result="Could not serialize the result",
    )

    apply_notebook_intelligence_runtime_patches()

    result = asyncio.run(
        fake_module.open_file_in_jupyter_ui.handler(
            {"file_path": "analysis/br_http_validation.ipynb"}
        )
    )

    assert result["content"][0]["text"] == (
        "Opened file in Jupyter UI: analysis/br_http_validation.ipynb"
    )
    assert fake_response.calls == [
        ("docmanager:open", {"path": "analysis/br_http_validation.ipynb"})
    ]
