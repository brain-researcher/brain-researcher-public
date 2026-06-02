"""Compatibility checks for LLM gateway follow-up relocations."""

from __future__ import annotations

import importlib


def test_gemini_fallback_legacy_agent_path_aliases_llm_gateway_module() -> None:
    legacy = importlib.import_module(
        "brain_researcher.services.agent.utils.gemini_fallback"
    )
    moved = importlib.import_module(
        "brain_researcher.services.llm_gateway.gemini_fallback"
    )

    assert legacy is moved
    assert legacy.chat_with_fallback is moved.chat_with_fallback
    assert legacy._set_router_for_testing is moved._set_router_for_testing


def test_metrics_collector_legacy_agent_path_aliases_telemetry_module() -> None:
    legacy = importlib.import_module(
        "brain_researcher.services.agent.monitoring.metrics_collector"
    )
    moved = importlib.import_module(
        "brain_researcher.services.telemetry.metrics_collector"
    )

    assert legacy is moved
    assert legacy.MetricsCollector is moved.MetricsCollector
    assert legacy.get_default_metrics_collector is moved.get_default_metrics_collector
