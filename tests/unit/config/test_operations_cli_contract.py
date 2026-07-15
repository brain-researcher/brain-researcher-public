from pathlib import Path

import click
from typer.main import get_command

from brain_researcher.cli.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_operations_root_command_table_matches_runtime_help() -> None:
    operations = (REPO_ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    table = operations.split("<!-- root-cli-commands:start -->", maxsplit=1)[1]
    table = table.split("<!-- root-cli-commands:end -->", maxsplit=1)[0]
    documented = [
        line.split("`", maxsplit=2)[1]
        for line in table.splitlines()
        if line.startswith("| `")
    ]

    command = get_command(app)
    context = click.Context(command)
    assert documented == command.list_commands(context)


def test_operations_defines_every_documented_status() -> None:
    operations = (REPO_ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    for status in (
        "active",
        "experimental",
        "private-input-required",
        "preview-only",
    ):
        assert f"- `{status}`:" in operations
