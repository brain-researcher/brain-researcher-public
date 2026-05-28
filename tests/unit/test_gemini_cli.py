import json
from types import SimpleNamespace

import pytest

from brain_researcher.services.agent.utils import gemini_cli


class DummyProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_parse_full_json():
    out = json.dumps({"text": "hello", "usage": {"total_tokens": 10}})
    parsed = gemini_cli.parse_gemini_response(out)
    assert parsed["text"] == "hello"
    assert parsed["usage"]["total_tokens"] == 10


def test_parse_line_by_line_json():
    out = "noise\n{" + '"text":"hi"' + "}\nmore"
    parsed = gemini_cli.parse_gemini_response(out)
    assert parsed["text"] == "hi"


def test_parse_plain_text_fallback():
    out = "This is plain text output from gemini"
    parsed = gemini_cli.parse_gemini_response(out)
    assert "text" in parsed and len(parsed["text"]) > 0
    assert parsed.get("warning") == "fallback_parse"


def test_parse_plain_text_fallback_preserves_newlines():
    out = "```python\nprint('a')\nprint('b')\n```"
    parsed = gemini_cli.parse_gemini_response(out)
    assert parsed["text"] == out
    assert "\n" in parsed["text"]


def test_parse_regex_text_value_unescapes_newlines():
    out = '{"text":"```python\\nprint(\\"hi\\")\\n```"}'
    parsed = gemini_cli.parse_gemini_response(out)
    assert parsed["text"] == '```python\nprint("hi")\n```'


def test_is_logged_in_success(monkeypatch):
    def fake_run(args, capture_output, text, timeout, shell):
        assert args[-1] == "whoami"
        return DummyProc(returncode=0, stdout="user@example.com")

    monkeypatch.setattr(gemini_cli, "get_gemini_executable", lambda: "/usr/bin/gemini")
    monkeypatch.setattr(gemini_cli.subprocess, "run", fake_run)

    assert gemini_cli.is_logged_in() is True


def test_check_gemini_version(monkeypatch):
    def fake_run(args, capture_output, text, timeout, shell):
        return DummyProc(stdout="gemini version 1.2.5")

    monkeypatch.setattr(gemini_cli, "get_gemini_executable", lambda: "/usr/bin/gemini")
    monkeypatch.setattr(gemini_cli.subprocess, "run", fake_run)

    v = gemini_cli.check_gemini_version()
    assert v == "1.2.5"


def test_execute_chat_happy_path(monkeypatch):
    def fake_run(args, capture_output, text, timeout, shell):
        # first element is executable path when we call subprocess.run([exe] + args)
        assert args[0].endswith("gemini") or args[0].endswith("gemini.exe")
        return DummyProc(
            stdout=json.dumps({"text": "ok", "usage": {"total_tokens": 3}})
        )

    monkeypatch.setattr(gemini_cli, "get_gemini_executable", lambda: "/usr/bin/gemini")
    monkeypatch.setattr(gemini_cli.subprocess, "run", fake_run)

    res = gemini_cli.execute_chat("hi", model="gemini-3.1-flash-lite-preview")
    assert res.text == "ok"
    assert res.usage["total_tokens"] == 3


def test_execute_chat_quota_error(monkeypatch):
    def fake_run(args, capture_output, text, timeout, shell):
        return DummyProc(returncode=1, stderr="Quota exceeded for today")

    monkeypatch.setattr(gemini_cli, "get_gemini_executable", lambda: "/usr/bin/gemini")
    monkeypatch.setattr(gemini_cli.subprocess, "run", fake_run)

    with pytest.raises(gemini_cli.GeminiQuotaError):
        gemini_cli.execute_chat("hi", model="gemini-3.1-flash-lite-preview")
