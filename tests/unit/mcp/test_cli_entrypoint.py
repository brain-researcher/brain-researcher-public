from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain_researcher.services.mcp import cli


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_do_not_import_server(flag, monkeypatch, capsys) -> None:
    def fail_import(_module_name: str):
        raise AssertionError("lightweight flag imported the MCP server")

    monkeypatch.setattr(cli.importlib, "import_module", fail_import)

    with pytest.raises(SystemExit) as exc_info:
        cli.main([flag])

    assert exc_info.value.code == 0
    assert "brain-researcher-mcp" in capsys.readouterr().out


def test_start_explains_missing_mcp_runtime(monkeypatch, capsys) -> None:
    def missing_dependency(_module_name: str):
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    monkeypatch.setattr(cli.importlib, "import_module", missing_dependency)

    with pytest.raises(SystemExit) as exc_info:
        cli.main([])

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "MCP runtime dependency 'mcp' is not installed" in stderr
    assert "pip install '.[mcp]'" in stderr


def test_start_does_not_mask_internal_server_import_bug(monkeypatch) -> None:
    error = ModuleNotFoundError(
        "No module named 'brain_researcher.services.mcp.broken'",
        name="brain_researcher.services.mcp.broken",
    )

    def internal_import_bug(_module_name: str):
        raise error

    monkeypatch.setattr(cli.importlib, "import_module", internal_import_bug)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        cli.main([])

    assert exc_info.value is error


def test_start_imports_and_calls_server_on_demand(monkeypatch) -> None:
    calls: list[str] = []
    module = SimpleNamespace(main=lambda: calls.append("started"))
    monkeypatch.setattr(cli.importlib, "import_module", lambda _name: module)

    cli.main([])

    assert calls == ["started"]
