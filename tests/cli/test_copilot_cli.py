import json

from typer.testing import CliRunner


def _parse_json_output(text: str) -> dict:
    # Extract JSON-ish block from Rich output
    start = text.find("{")
    end = text.rfind("}")
    assert start != -1 and end != -1
    return json.loads(text[start : end + 1])


def test_cli_copilot_suggest():
    from brain_researcher.cli.main import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["copilot", "suggest", "glm motor task", "-m", '{"repetition_time":2.0}'],
        prog_name="brain-researcher",
    )
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    assert "suggestions" in data


def test_cli_copilot_autocomplete():
    from brain_researcher.cli.main import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["copilot", "autocomplete", "spm-glm", "-m", '{"repetition_time":2.0}'],
        prog_name="brain-researcher",
    )
    assert result.exit_code == 0
    data = _parse_json_output(result.output)
    completed = data.get("completed", {})
    assert completed.get("TR") == 2.0 or completed.get("tr") == 2.0
