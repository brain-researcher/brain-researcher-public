"""Coding SSE stream overflow behavior tests."""

from __future__ import annotations

from typing import Dict, Any

import pytest


def test_coding_stream_emits_overflow_error(monkeypatch):
    """Ensure overflow triggers coding_event_queue_full and result still arrives."""

    from brain_researcher.services.agent import ui_api

    # Force tiny queue to trigger overflow quickly
    monkeypatch.setattr(ui_api, "CODING_EVENT_QUEUE_SIZE", 1)

    # Stub orchestrator that blasts events and finishes
    class StubOrchestrator:
        def __init__(self, emit):
            self._emit = emit

        def run_task(self, instruction, ctx, thread_id, user_id):
            for i in range(ui_api.CODING_EVENT_QUEUE_SIZE + 5):
                self._emit("plan", {"i": i})
            self._emit("result", {"status": "success", "answer": "done"})

            class R:
                status = "success"
                answer = "done"
                patches = []
                files_touched = []
                iterations = 1
                test_status = None
                metadata: Dict[str, Any] = {}

            return R()

    def fake_get_code_orchestrator(event_callback=None):
        return StubOrchestrator(event_callback)

    monkeypatch.setattr(
        "brain_researcher.services.agent.ui_api.get_code_orchestrator",
        fake_get_code_orchestrator,
        raising=False,
    )

    gen = ui_api._stream_coding_response(
        user_content="test",
        thread_id="t1",
        user_id="u1",
        ctx={},
        history=[],
    )

    chunks = []
    for chunk in gen:
        chunks.append(chunk)
        if "event: stream_end" in chunk:
            break
    has_result = any("event: result" in c for c in chunks)
    has_overflow = any("coding_event_queue_full" in c for c in chunks)

    assert has_result, "result event should be delivered even under overflow"
    assert has_overflow, "overflow should emit coding_event_queue_full error"
