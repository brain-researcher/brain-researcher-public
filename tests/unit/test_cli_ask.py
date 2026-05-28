from typer.testing import CliRunner

from brain_researcher.cli.main import app


runner = CliRunner()


def test_ask_gemini_json(monkeypatch):
    # Monkeypatch fallback to avoid real subprocess
    from brain_researcher.cli.compat import gemini_compat

    def fake_run_simple_chat(prompt, model=None):
        return "ok", {
            "provider": "google",
            "model": "gemini-3.1-flash-lite-preview",
            "route": "primary",
            "fallback_reason": None,
            "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(gemini_compat, "run_simple_chat", fake_run_simple_chat)

    res = runner.invoke(
        app,
        ["ask", "-m", "gemini-3.1-flash-lite-preview", "-p", "hi", "--json"],
    )
    assert res.exit_code == 0
    assert '"provider": "google"' in res.stdout
    assert '"model": "gemini-3.1-flash-lite-preview"' in res.stdout
    assert '"text": "ok"' in res.stdout


def test_chat_prompt_flag_plain(monkeypatch):
    from brain_researcher.cli.compat import gemini_compat

    def fake_run_simple_chat(prompt, model=None):
        return "plain", {
            "provider": "google",
            "model": "gemini-3-flash-preview",
            "route": "fallback",
            "fallback_reason": "quota_exhausted",
            "usage": {},
        }

    monkeypatch.setattr(gemini_compat, "run_simple_chat", fake_run_simple_chat)

    res = runner.invoke(app, ["ask", "-p", "hi there"])
    assert res.exit_code == 0
    assert "gemini-3-flash-preview route=fallback" in res.stdout
    assert "plain" in res.stdout
