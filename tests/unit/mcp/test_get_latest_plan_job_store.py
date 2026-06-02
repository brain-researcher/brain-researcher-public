"""Focused tests for MCP get_latest_plan JobStore lookup."""

from __future__ import annotations


def test_get_latest_plan_job_store_uses_shared_registry(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.shared import job_store_registry

    fake_store = object()
    monkeypatch.setattr(job_store_registry, "_job_store_instance", fake_store)
    monkeypatch.setattr(job_store_registry, "_autoinit", None)

    assert srv._get_latest_plan_job_store() is fake_store
