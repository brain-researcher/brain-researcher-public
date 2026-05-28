from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_chat_stream_writes_run_bundle(monkeypatch, tmp_path):
    from flask import Flask

    from brain_researcher.config.run_artifacts import reset_recorder_config
    from brain_researcher.services.agent.streaming import StreamEvent
    from brain_researcher.services.agent.ui_api import api_chat_stream

    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    reset_recorder_config()
    monkeypatch.setenv("BR_CHAT_ORCHESTRATOR_ENABLED", "0")

    run_id = "run_test_chat_stream_bundle"
    thread_id = "thread_test"

    class DummyStreamingChatHandler:
        def __init__(self, model_hint=None, thread_id=None, user_id=None, abort_flag=None):
            self.model_hint = model_hint
            self.thread_id = thread_id
            self.user_id = user_id
            self._accumulated = ""

        def stream_chat(self, message, *, history=None):
            self._accumulated = "hello"
            yield StreamEvent(event="token", data={"content": "hello"})
            yield StreamEvent(
                event="metadata",
                data={
                    "provider": "test",
                    "model": self.model_hint or "test-model",
                    "latency_ms": 1,
                    "total_length": len(self._accumulated),
                    "token_count": 1,
                },
            )
            yield StreamEvent(
                event="done",
                data={"thread_id": self.thread_id, "total_length": len(self._accumulated)},
            )

        def get_accumulated_text(self) -> str:
            return self._accumulated

    app = Flask(__name__)
    with app.test_request_context(
        "/api/chat/stream",
        method="POST",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "thread_id": thread_id,
            "ctx": {},
        },
        headers={"X-Run-ID": run_id},
    ):
        with (
            patch(
                "brain_researcher.services.agent.agent_auth.get_current_user",
                return_value=MagicMock(id="user", tenant_id="default"),
            ),
            patch("brain_researcher.services.agent.ui_api._check_thread_access", return_value=True),
            patch("brain_researcher.services.agent.ui_api._add_message", return_value=None),
            patch(
                "brain_researcher.services.agent.streaming.StreamingChatHandler",
                DummyStreamingChatHandler,
            ),
        ):
            resp = api_chat_stream()
            chunks = list(resp.response)
            assert chunks, "stream should yield at least one SSE chunk"
            assert resp.headers.get("X-Run-ID") == run_id

    date_str = datetime.now().strftime("%Y%m%d")
    run_dir = Path(tmp_path / "runs" / date_str / run_id)
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "trajectory.json").exists()
    assert (run_dir / "observation.json").exists()
    assert (run_dir / "analysis_bundle.json").exists()
    assert (run_dir / "provenance.json").exists()

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        event.get("event_type") == "chat.bundle_written"
        or (
            isinstance(event.get("payload"), dict)
            and event["payload"].get("raw_event_type") == "chat.bundle_written"
        )
        for event in trace_events
    )
