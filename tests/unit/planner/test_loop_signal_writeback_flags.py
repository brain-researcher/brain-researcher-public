from __future__ import annotations

from brain_researcher.services.agent.planner.loop_signal_neo4j import (
    enabled_signal_types,
    is_loop_signal_writeback_enabled,
)


def test_loop_signal_flags_default_disabled(monkeypatch):
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_ALL", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_CONDITION_TAG", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_SENSITIVITY_FINDING", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_DESIGN_CONSTRAINT", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_HYPOTHESIS_DELTA", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_USER_FEEDBACK", raising=False)

    assert enabled_signal_types() == set()
    assert is_loop_signal_writeback_enabled("condition_tag") is False


def test_loop_signal_flags_per_signal_type(monkeypatch):
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_ALL", raising=False)
    monkeypatch.setenv("BR_LOOP_SIGNAL_WRITEBACK_CONDITION_TAG", "1")
    monkeypatch.setenv("BR_LOOP_SIGNAL_WRITEBACK_SENSITIVITY_FINDING", "true")
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_DESIGN_CONSTRAINT", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_HYPOTHESIS_DELTA", raising=False)
    monkeypatch.delenv("BR_LOOP_SIGNAL_WRITEBACK_USER_FEEDBACK", raising=False)

    enabled = enabled_signal_types()
    assert "condition_tag" in enabled
    assert "sensitivity_finding" in enabled
    assert "design_constraint" not in enabled
    assert is_loop_signal_writeback_enabled("condition_tag") is True
    assert is_loop_signal_writeback_enabled("user_feedback") is False


def test_loop_signal_all_flag_enables_everything(monkeypatch):
    monkeypatch.setenv("BR_LOOP_SIGNAL_WRITEBACK_ALL", "yes")
    enabled = enabled_signal_types()
    assert "condition_tag" in enabled
    assert "sensitivity_finding" in enabled
    assert "design_constraint" in enabled
    assert "hypothesis_delta" in enabled
    assert "user_feedback" in enabled

