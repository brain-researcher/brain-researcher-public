from typer.testing import CliRunner

from brain_researcher.cli.commands import notebook_commands


def test_find_builtin_template_resolves_quickstart():
    path = notebook_commands._find_template("br_quickstart")

    assert path.name == "br_quickstart.py"
    assert path.exists()
    assert path.parent == notebook_commands._TEMPLATES_DIR


def test_notebook_list_shows_builtin_templates():
    runner = CliRunner()

    result = runner.invoke(notebook_commands.app, ["list"])

    assert result.exit_code == 0
    assert "br_quickstart" in result.stdout
    assert "behavior_task_builder" in result.stdout


def test_agent_setup_prints_pairing_and_fallback_paths():
    runner = CliRunner()

    result = runner.invoke(notebook_commands.app, ["agent-setup"])

    assert result.exit_code == 0
    assert "Marimo Agent Setup" in result.stdout
    assert "npx skills add marimo-team/marimo-pair" in result.stdout
    assert "uvx marimo@latest pair prompt" in result.stdout
    assert "Config -> Pair with an agent" in result.stdout
    assert "docs/mcp.md" in result.stdout
    assert "Operations guide" in result.stdout
    assert "docs/OPERATIONS.md" in result.stdout
    assert "~/.codex/skills/marimo-pair" in result.stdout
    assert "marimo edit --watch" in result.stdout
    assert "br notebook check" in result.stdout
    assert "BR_MCP_SERVER_COMMAND=brain-researcher-mcp" in result.stdout
    assert "BR_MCP_HTTP_URL=https://${PUBLIC_HOSTNAME}/mcp" in result.stdout
    assert 'BR_MCP_AUTH_HEADER="Bearer <token>"' in result.stdout
    assert "BR_MCP_TOKEN=<token>" in result.stdout
    assert "br.call()" in result.stdout
    assert "br.execute()" in result.stdout


def test_check_invokes_marimo_check(monkeypatch):
    called = {}

    class Result:
        returncode = 0

    def fake_run(args, check=False):
        called["args"] = args
        called["check"] = check
        return Result()

    monkeypatch.setattr(notebook_commands.subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(notebook_commands.app, ["check", "br_quickstart"])

    assert result.exit_code == 0
    assert called["args"][0] == "marimo"
    assert called["args"][1] == "check"
    assert called["args"][2].endswith("br_quickstart.py")
    assert called["check"] is False
