from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from brain_researcher.cli.main import app

runner = CliRunner()


def test_sessions_attach_invokes_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request_json(method, path, *, json_body=None, params=None, timeout=30.0):
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        return {
            "session": {
                "id": "mon_demo123",
                "kind": "mcp_run",
                "status": "running",
                "display_name": "Demo Run",
                "session_ref": "run_demo",
                "thread_id": "thread_demo123",
                "summary": "Fit model",
            }
        }

    monkeypatch.setattr(
        "brain_researcher.cli.commands.sessions_commands._request_json",
        fake_request_json,
    )

    result = runner.invoke(
        app,
        [
            "sessions",
            "attach",
            "mcp_run",
            "run_demo",
            "--display-name",
            "Demo Run",
            "--slack-channel",
            "C123",
        ],
    )

    assert result.exit_code == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/sessions/attach"
    assert captured["json_body"] == {
        "kind": "mcp_run",
        "session_ref": "run_demo",
        "display_name": "Demo Run",
        "mirror_chat": True,
        "slack_channel_id": "C123",
    }
    assert "Attached session" in result.stdout
    assert "mon_demo123" in result.stdout


def test_sessions_slack_manifest_renders_public_urls(
    tmp_path: Path, monkeypatch
) -> None:
    template_path = tmp_path / "manifest.yaml"
    template_path.write_text(
        "events: __PUBLIC_BASE_URL__/api/integrations/slack/events\n"
        "interactions: __PUBLIC_BASE_URL__/api/integrations/slack/interactions\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "brain_researcher.cli.commands.sessions_commands._MANIFEST_TEMPLATE_PATH",
        template_path,
    )

    result = runner.invoke(
        app,
        [
            "sessions",
            "slack-manifest",
            "--public-base-url",
            "https://demo.ngrok-free.app",
        ],
    )

    assert result.exit_code == 0
    assert "https://demo.ngrok-free.app/api/integrations/slack/events" in result.stdout
    assert (
        "https://demo.ngrok-free.app/api/integrations/slack/interactions"
        in result.stdout
    )
