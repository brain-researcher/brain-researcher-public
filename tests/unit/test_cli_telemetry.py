from pathlib import Path

from brain_researcher.services.agent.router import LLMChatResult, LLMRouteMetadata
from brain_researcher.cli.compat import gemini_compat


def test_run_simple_chat_records_event(monkeypatch):
    events = []

    def fake_record_event(payload, event_type="chat"):
        events.append(payload)
        return Path("/dev/null")

    class DummyRouter:
        @staticmethod
        def route_chat(prompt, model_hint=None, **kwargs):
            metadata = LLMRouteMetadata(
                provider="google",
                model="gemini-3.1-flash-lite-preview",
                route="primary",
                transport="cli",
                usage={"total_tokens": 5},
            )
            metadata.latency_ms = 7
            return LLMChatResult(text="hi there", metadata=metadata)

    monkeypatch.setattr(gemini_compat.telemetry, "record_event", fake_record_event)
    monkeypatch.setattr(gemini_compat, "_ROUTER", DummyRouter())

    text, meta = gemini_compat.run_simple_chat(
        "hello world", model="gemini-3.1-flash-lite-preview"
    )
    assert text == "hi there"
    assert meta["provider"] == "google"
    assert "run_id" in meta
    assert events
    assert events[0]["run_id"] == meta["run_id"]
    assert events[0]["channel"] == "cli"
