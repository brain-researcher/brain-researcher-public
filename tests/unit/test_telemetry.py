import json
import os
import time

import pytest

from brain_researcher.services.agent import telemetry


def test_new_run_id_unique():
    run_ids = {telemetry.new_run_id() for _ in range(10)}
    assert len(run_ids) == 10
    for rid in run_ids:
        assert len(rid) == 32


def test_prompt_hash_stable():
    text = "an example prompt"
    h1 = telemetry.prompt_hash(text)
    h2 = telemetry.prompt_hash(text)
    assert h1 == h2
    assert h1 != telemetry.prompt_hash(text + "x")
    assert telemetry.prompt_hash("") == ""


def test_start_span_finish_reports_duration(monkeypatch):
    span = telemetry.start_span("agent.chat", {"run_id": "abc"})
    time.sleep(0.01)
    finished = span.finish(status="ok")
    assert finished["name"] == "agent.chat"
    assert finished["attributes"]["run_id"] == "abc"
    assert finished["attributes"]["status"] == "ok"
    assert finished["duration_ms"] >= 10


def test_record_event_writes_ndjson(tmp_path, monkeypatch):
    output_dir = tmp_path / "telemetry_out"
    monkeypatch.setenv("BRAIN_RESEARCHER_TELEMETRY_DIR", str(output_dir))
    event_path = telemetry.record_event(
        {
            "run_id": "run-123",
            "llm": {"provider": "google", "fallback_reason": None},
        },
        event_type="chat",
    )

    assert event_path.exists()
    with event_path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["event_type"] == "chat"
    assert payload["run_id"] == "run-123"
    # ensure None was pruned
    assert "fallback_reason" not in payload["llm"]

