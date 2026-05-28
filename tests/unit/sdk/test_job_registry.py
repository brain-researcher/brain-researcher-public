"""Tests for brain_researcher.sdk.job_registry."""

from __future__ import annotations

import pytest

from brain_researcher.sdk import job_registry
from brain_researcher.sdk.models import JobHandle, ToolResult


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts with a fresh registry."""
    job_registry.clear()
    yield
    job_registry.clear()


class TestJobRegistry:
    def test_put_and_get(self):
        result = ToolResult(ok=True, tool_id="fsl.bet")
        job_registry.put("abc123", result)
        assert job_registry.get("abc123") is result

    def test_get_missing_returns_none(self):
        assert job_registry.get("nonexistent") is None

    def test_clear_removes_all(self):
        job_registry.put("a", ToolResult(ok=True))
        job_registry.put("b", ToolResult(ok=True))
        count = job_registry.clear()
        assert count == 2
        assert job_registry.get("a") is None

    def test_entries_returns_copy(self):
        result = ToolResult(ok=True, tool_id="test")
        job_registry.put("key", result)
        snapshot = job_registry.entries()
        assert "key" in snapshot
        # Mutating snapshot does not affect registry
        snapshot.pop("key")
        assert job_registry.get("key") is result

    def test_overwrite_existing(self):
        r1 = ToolResult(ok=False, tool_id="t1")
        r2 = ToolResult(ok=True, tool_id="t1")
        job_registry.put("same", r1)
        job_registry.put("same", r2)
        assert job_registry.get("same") is r2

    def test_stores_job_handle(self):
        handle = JobHandle(job_id="j1", tool_id="fsl.bet", status="running")
        job_registry.put("hash1", handle)
        retrieved = job_registry.get("hash1")
        assert isinstance(retrieved, JobHandle)
        assert retrieved.job_id == "j1"
