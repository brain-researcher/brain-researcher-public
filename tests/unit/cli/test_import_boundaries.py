from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import typer
from typer.testing import CliRunner

from brain_researcher.cli import lazy
from brain_researcher.cli.main import app

runner = CliRunner()


def test_root_help_keeps_optional_runtime_modules_out_of_process() -> None:
    script = textwrap.dedent(
        """
        import sys
        from typer.testing import CliRunner
        from brain_researcher.cli.main import app

        result = CliRunner().invoke(app, ["--help"])
        assert result.exit_code == 0, result.output
        forbidden = (
            "mcp",
            "nibabel",
            "nilearn",
            "brain_researcher.services.agent",
            "brain_researcher.services.tools",
            "brain_researcher.cli.commands.agent_commands",
            "brain_researcher.cli.commands.br_kg_ingest",
        )
        leaked = sorted(
            name
            for name in sys.modules
            if any(name == item or name.startswith(item + ".") for item in forbidden)
        )
        assert not leaked, leaked
        """
    )
    env = os.environ.copy()
    env["BRAIN_RESEARCHER_SKIP_DOTENV"] = "1"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_root_help_lists_lazy_commands_without_importing_them(monkeypatch) -> None:
    def fail_import(_module_name: str):
        raise AssertionError("root help imported a lazy command module")

    monkeypatch.setattr(lazy.importlib, "import_module", fail_import)

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command_name in ("agent", "br-kg", "codegen", "notebook", "tools"):
        assert command_name in result.output


def test_root_version_does_not_import_lazy_commands(monkeypatch) -> None:
    def fail_import(_module_name: str):
        raise AssertionError("root version imported a lazy command module")

    monkeypatch.setattr(lazy.importlib, "import_module", fail_import)

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "Brain Researcher v" in result.output


def test_lazy_command_explains_missing_optional_profile(monkeypatch) -> None:
    def missing_dependency(_module_name: str):
        raise ModuleNotFoundError("No module named 'rapidfuzz'", name="rapidfuzz")

    monkeypatch.setattr(lazy.importlib, "import_module", missing_dependency)

    result = runner.invoke(app, ["br-kg", "--help"])

    assert result.exit_code == 2
    assert "optional 'br-kg' profile" in result.output
    assert "pip install '.[br-kg]'" in result.output
    assert "missing module 'rapidfuzz'" in result.output


def test_lazy_command_checks_profile_before_import(monkeypatch) -> None:
    monkeypatch.setattr(lazy.importlib.util, "find_spec", lambda _name: None)

    def fail_import(_module_name: str):
        raise AssertionError("optional command imported before its profile probe")

    monkeypatch.setattr(lazy.importlib, "import_module", fail_import)

    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 2
    assert "optional 'agent' profile" in result.output
    assert "missing module 'langgraph'" in result.output


def test_query_command_declares_br_kg_profile(monkeypatch) -> None:
    monkeypatch.setattr(lazy.importlib.util, "find_spec", lambda _name: None)

    result = runner.invoke(app, ["query", "--help"])

    assert result.exit_code == 2
    assert "optional 'br-kg' profile" in result.output
    assert "missing module 'nibabel'" in result.output


def test_lazy_command_does_not_mask_internal_import_bug(monkeypatch) -> None:
    error = ModuleNotFoundError(
        "No module named 'brain_researcher.broken'",
        name="brain_researcher.broken",
    )

    def internal_import_bug(_module_name: str):
        raise error

    monkeypatch.setattr(lazy.importlib, "import_module", internal_import_bug)

    result = runner.invoke(app, ["br-kg", "--help"])

    assert result.exit_code == 1
    assert result.exception is error


def test_lazy_command_forwards_to_real_typer_group() -> None:
    result = runner.invoke(app, ["cache", "--help"])

    assert result.exit_code == 0
    assert "status" in result.output
    assert "clear" in result.output


def test_lazy_command_preserves_nested_exit_code(monkeypatch) -> None:
    nested = typer.Typer()

    @nested.command()
    def fail() -> None:
        raise typer.Exit(7)

    monkeypatch.setattr(
        lazy.importlib,
        "import_module",
        lambda _module_name: SimpleNamespace(app=nested),
    )

    result = runner.invoke(app, ["cache", "fail"])

    assert result.exit_code == 7
