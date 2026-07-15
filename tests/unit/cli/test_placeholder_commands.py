from typer.testing import CliRunner

from brain_researcher.cli.main import app


def test_analyze_placeholder_fails_closed() -> None:
    result = CliRunner().invoke(app, ["analyze", "contrast"])

    assert result.exit_code == 2
    assert "does not execute" in result.output


def test_ingest_placeholder_fails_closed() -> None:
    result = CliRunner().invoke(app, ["ingest", "openneuro", "ds000001"])

    assert result.exit_code == 2
    assert "does not ingest" in result.output


def test_root_help_marks_placeholders_as_preview_only() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Preview-only placeholder; does not execute" in result.output
    assert "Preview-only placeholder; does not ingest" in result.output
