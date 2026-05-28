"""Tests for the /run SSE streaming path."""

import json
from typing import List, Dict

from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import main_enhanced


def _collect_events(response) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    buffer: Dict[str, str] = {}

    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if line == "":
            if buffer:
                events.append(buffer)
                buffer = {}
            if len(events) >= 4:  # accepted + 3 stub events
                break
            continue
        if line.startswith("event:"):
            buffer["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            buffer["data"] = line.split(":", 1)[1].strip()
    return events


def test_run_endpoint_streams_events(monkeypatch):
    async def fake_generator(job_id: str):
        yield {"event": "step_started", "data": json.dumps({"step_id": "s1"})}
        yield {"event": "step_completed", "data": json.dumps({"step_id": "s1"})}
        yield {"event": "plan_completed", "data": json.dumps({"plan_id": "plan-demo"})}

    monkeypatch.setattr(main_enhanced, "_job_event_generator", fake_generator)

    client = TestClient(main_enhanced.app)

    payload = {"prompt": "stream test"}
    headers = {"Accept": "text/event-stream"}

    with client.stream("POST", "/run?stream=1", json=payload, headers=headers) as response:
        assert response.status_code == 200
        events = _collect_events(response)

    assert events, "Expected streaming events"
    assert events[0]["event"] == "accepted"
    accepted_payload = json.loads(events[0]["data"])
    assert accepted_payload.get("job_id")

    names = [evt["event"] for evt in events[1:]]
    assert names == ["step_started", "step_completed", "plan_completed"]
