"""
Unit tests for cache store backends (P2.5).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator.cache_store import MemoryCacheStore
from brain_researcher.services.orchestrator.sqlite_cache_store import SqliteCacheStore

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/brain_researcher/services/orchestrator/sqlite_schema/schema.sql"
)


def _apply_schema(db_path: Path) -> None:
    """Apply orchestrator schema (includes run_cache table)."""

    sql = SCHEMA_PATH.read_text()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(sql)


@pytest.mark.asyncio
async def test_memory_cache_store_lifecycle(tmp_path):
    store = MemoryCacheStore()
    await store.initialize()

    cache_key = "sha256:demo"
    meta = {"tool": "demo", "params": {"alpha": 1}}

    reserved = await store.create_and_mark_pending(cache_key, "job1", meta, tool_version="1.0")
    assert reserved

    # Second reservation while pending should fail.
    assert not await store.create_and_mark_pending(cache_key, "job2", meta)

    entry = await store.lookup(cache_key)
    assert entry is not None
    assert entry.state == "pending"

    assert await store.mark_completed(cache_key, "job1", "/tmp/run_demo", size_bytes=42)

    entry_after = await store.lookup(cache_key)
    assert entry_after.state == "completed"
    assert entry_after.run_dir == "/tmp/run_demo"

    stats = await store.get_stats()
    assert stats.completed_entries == 1
    assert stats.hit_count >= 2  # lookup called twice


@pytest.mark.asyncio
async def test_sqlite_cache_store_pending_and_complete(tmp_path):
    db_path = tmp_path / "cache.db"
    _apply_schema(db_path)

    store = SqliteCacheStore(db_path)
    await store.initialize()

    cache_key = "sha256:f00"
    meta = {"tool": "demo", "params": {"beta": 2}}

    assert await store.create_and_mark_pending(cache_key, "jobA", meta, tool_version="2.0", git_sha="abc123")
    assert not await store.create_and_mark_pending(cache_key, "jobB", meta), "pending entries should be exclusive"

    entry = await store.lookup(cache_key)
    assert entry is not None
    assert entry.state == "pending"
    assert entry.run_id == "jobA"

    assert await store.mark_completed(cache_key, "jobA", "/tmp/runA", size_bytes=1024)

    entry_done = await store.lookup(cache_key)
    assert entry_done.state == "completed"
    assert entry_done.run_dir == "/tmp/runA"

    stats = await store.get_stats()
    assert stats.completed_entries == 1
    assert stats.pending_entries == 0


@pytest.mark.asyncio
async def test_sqlite_cache_store_mark_failed(tmp_path):
    db_path = tmp_path / "cache.db"
    _apply_schema(db_path)

    store = SqliteCacheStore(db_path)
    await store.initialize()

    cache_key = "sha256:fail"
    meta = {"tool": "demo", "params": {"gamma": 3}}
    await store.create_and_mark_pending(cache_key, "jobFail", meta)

    assert await store.mark_failed(cache_key, "jobFail", "network outage")

    entry = await store.lookup(cache_key)
    assert entry is not None
    assert entry.state == "failed"
    assert json.loads(entry.meta_json)["error"] == "network outage"
