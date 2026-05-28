"""
Integration tests for P2.5 Deterministic Result Cache.

Tests cache hit/miss scenarios, race condition prevention,
state protection, and end-to-end worker integration.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Import orchestrator components
from brain_researcher.services.orchestrator import main_enhanced
from brain_researcher.services.orchestrator.main_enhanced import app
from brain_researcher.services.orchestrator.sqlite_cache_store import SqliteCacheStore
from brain_researcher.services.orchestrator.cache_store import MemoryCacheStore
from brain_researcher.services.orchestrator.worker import JobWorker


@pytest.fixture
def tmp_test_db(tmp_path):
    """Create temporary test database."""
    db_path = tmp_path / "test_cache.db"
    return db_path


@pytest.fixture
async def cache_store_sqlite(tmp_test_db):
    """Create SQLite cache store for testing."""
    # Initialize job store first to create schema (including run_cache table)
    from brain_researcher.services.orchestrator.sqlite_job_store import SqliteJobStore
    job_store = SqliteJobStore(db_path=tmp_test_db)
    await job_store.initialize()

    # Now create cache store
    store = SqliteCacheStore(db_path=tmp_test_db)
    await store.initialize()
    return store


@pytest.fixture
async def cache_store_memory():
    """Create memory cache store for testing."""
    store = MemoryCacheStore()
    await store.initialize()
    return store


@pytest.fixture
def test_client_with_cache(tmp_path):
    """Create test client with cache enabled."""
    env_overrides = {
        "BR_CACHE_ENABLED": "true",
        "BR_CACHE_STORE": "memory",
        "BR_CACHE_MODE": "fast",
        "BR_PLANNER_MODE": "disabled",
        "BR_QUEUE_BACKEND": "memory",
        "BR_PREFLIGHT_MODE": "WARN",
    }
    cache_db = tmp_path / "test_cache.db"
    env_overrides["BR_CACHE_DB_PATH"] = str(cache_db)

    for key, value in env_overrides.items():
        os.environ[key] = value

    with TestClient(app) as client:
        store = MemoryCacheStore()
        asyncio.run(store.initialize())
        main_enhanced.cache_store = store
        app.state.cache_store = store
        asyncio.run(store.clear_all())
        yield client
        store = getattr(main_enhanced, "cache_store", None)
        if store is None:
            store = getattr(main_enhanced.app.state, "cache_store", None)
        if store:
            asyncio.run(store.clear_all())

    for key in env_overrides:
        os.environ.pop(key, None)
    main_enhanced.cache_store = None


def _demo_run_payload():
    """Canonical demo payload reused across cache flow tests."""
    return {
        "prompt": "Run demo connectivity analysis",
        "pipeline": "demo",
        "demo_mode": True,
        "timeout_seconds": 60,
        "parameters": {
            "demo_id": "motor_glm",
            "tool": "demo.pipeline",
            "tool_version": "1.0.0",
            "container_image": "/bin/echo",
        },
    }


async def _get_or_init_cache_store():
    store = getattr(main_enhanced, "cache_store", None) or getattr(main_enhanced.app.state, "cache_store", None)
    if store is None:
        store = MemoryCacheStore()
        await store.initialize()
        main_enhanced.cache_store = store
        main_enhanced.app.state.cache_store = store
    return store


class TestCacheMiss:
    """Test cache miss scenarios."""

    @pytest.mark.asyncio
    async def test_cache_miss_creates_pending_entry(self, cache_store_memory):
        """When cache miss occurs, pending entry should be created."""
        cache_key = "sha256:test_miss_key_001"
        run_id = "run_001"

        # Verify cache miss
        entry = await cache_store_memory.lookup(cache_key)
        assert entry is None

        # Create pending entry (simulates orchestrator behavior)
        await cache_store_memory.create_and_mark_pending(
            cache_key=cache_key,
            run_id=run_id,
            meta={"tool": "test.tool", "params": {"x": 1}},
            tool_version="test.tool:1.0.0",
        )

        # Verify pending entry exists
        entry = await cache_store_memory.lookup(cache_key)
        assert entry is not None
        assert entry.cache_key == cache_key
        assert entry.run_id == run_id
        assert entry.state == "pending"


class TestCacheHit:
    """Test cache hit scenarios."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self, cache_store_memory):
        """When cache hit occurs, completed entry should be returned."""
        cache_key = "sha256:test_hit_key_001"
        run_id = "run_hit_001"
        run_dir = "/tmp/run_hit_001"

        # Create pending entry
        await cache_store_memory.create_and_mark_pending(
            cache_key=cache_key,
            run_id=run_id,
            meta={"tool": "test.tool"},
        )

        # Mark as completed (simulates worker)
        success = await cache_store_memory.mark_completed(
            cache_key=cache_key,
            run_id=run_id,
            run_dir=run_dir,
            size_bytes=1024,
        )
        assert success is True

        # Lookup should return completed entry
        entry = await cache_store_memory.lookup(cache_key)
        assert entry is not None
        assert entry.state == "completed"
        assert entry.run_dir == run_dir
        assert entry.size_bytes == 1024

    @pytest.mark.asyncio
    async def test_cache_hit_updates_access_time(self, cache_store_memory):
        """Cache lookups should update last_accessed_at."""
        cache_key = "sha256:test_access_key_001"
        run_id = "run_access_001"

        # Create and complete entry
        await cache_store_memory.create_and_mark_pending(
            cache_key=cache_key,
            run_id=run_id,
            meta={},
        )
        await cache_store_memory.mark_completed(
            cache_key=cache_key,
            run_id=run_id,
            run_dir="/tmp/test",
        )

        # First lookup
        entry1 = await cache_store_memory.lookup(cache_key)
        first_access = entry1.last_accessed_at

        # Wait long enough to ensure different timestamp (1 second for integer timestamps)
        await asyncio.sleep(1.1)

        # Second lookup
        entry2 = await cache_store_memory.lookup(cache_key)
        second_access = entry2.last_accessed_at

        # Access time should have increased
        assert second_access > first_access


class TestRaceConditionPrevention:
    """Test that race conditions are prevented."""

    @pytest.mark.asyncio
    async def test_concurrent_create_and_mark_pending_atomic(self, cache_store_sqlite):
        """Concurrent create_and_mark_pending calls should be atomic."""
        cache_key = "sha256:test_race_key_001"

        async def create_and_mark_pending_task(run_id: str):
            """Create pending entry and return whether it was created."""
            try:
                await cache_store_sqlite.create_and_mark_pending(
                    cache_key=cache_key,
                    run_id=run_id,
                    meta={"tool": "test"},
                )
                return run_id
            except Exception:
                return None

        # Launch 5 concurrent create_and_mark_pending calls
        tasks = [
            create_and_mark_pending_task(f"run_{i:03d}")
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        # Exactly one should succeed (first one wins)
        # Others should silently fail due to INSERT OR IGNORE
        entry = await cache_store_sqlite.lookup(cache_key)
        assert entry is not None
        assert entry.state == "pending"

        # Entry should have run_id from first successful insert
        assert entry.run_id in results

    @pytest.mark.asyncio
    async def test_pending_state_blocks_concurrent_execution(self, cache_store_memory):
        """Pending state should signal that computation is in progress."""
        cache_key = "sha256:test_block_key_001"

        # Create pending entry
        await cache_store_memory.create_and_mark_pending(
            cache_key=cache_key,
            run_id="run_001",
            meta={},
        )

        # Lookup should return pending
        entry = await cache_store_memory.lookup(cache_key)
        assert entry is not None
        assert entry.state == "pending"

        # Orchestrator should detect pending and return 409
        # (This is tested in test_client tests below)


class TestStateProtection:
    """Test that state transitions are protected."""

    @pytest.mark.asyncio
    async def test_completed_cannot_be_overwritten_by_failed(self, cache_store_memory):
        """Completed entries cannot be downgraded to failed."""
        cache_key = "sha256:test_protect_key_001"

        # Create and complete entry
        await cache_store_memory.create_and_mark_pending(
            cache_key=cache_key,
            run_id="run_001",
            meta={},
        )
        await cache_store_memory.mark_completed(
            cache_key=cache_key,
            run_id="run_001",
            run_dir="/tmp/test",
            size_bytes=2048,
        )

        # Verify completed
        entry = await cache_store_memory.lookup(cache_key)
        assert entry.state == "completed"
        assert entry.size_bytes == 2048

        # Attempt to mark as failed (should fail)
        success = await cache_store_memory.mark_failed(
            cache_key=cache_key,
            run_id="run_001",
            error="Simulated error",
        )
        assert success is False

        # State should still be completed
        entry = await cache_store_memory.lookup(cache_key)
        assert entry.state == "completed"
        assert entry.size_bytes == 2048

    @pytest.mark.asyncio
    async def test_failed_cannot_be_overwritten_by_completed(self, cache_store_sqlite):
        """Failed entries cannot be upgraded to completed."""
        cache_key = "sha256:test_failed_key_001"

        # Create and fail entry
        await cache_store_sqlite.create_and_mark_pending(
            cache_key=cache_key,
            run_id="run_001",
            meta={},
        )
        await cache_store_sqlite.mark_failed(
            cache_key=cache_key,
            run_id="run_001",
            error="Test error",
        )

        # Verify failed
        entry = await cache_store_sqlite.lookup(cache_key)
        assert entry.state == "failed"

        # Attempt to mark as completed (should fail)
        success = await cache_store_sqlite.mark_completed(
            cache_key=cache_key,
            run_id="run_001",
            run_dir="/tmp/test",
        )
        assert success is False

        # State should still be failed
        entry = await cache_store_sqlite.lookup(cache_key)
        assert entry.state == "failed"


class TestCacheAPIEndpoints:
    """Test cache API endpoints."""

    def test_cache_stats_endpoint(self, test_client_with_cache):
        """GET /api/cache/stats returns statistics."""
        response = test_client_with_cache.get("/api/cache/stats")
        assert response.status_code == 200

        stats = response.json()
        assert "total_entries" in stats
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "hit_rate" in stats

    def test_cache_resolve_by_key(self, test_client_with_cache):
        """GET /api/cache/resolve?key=... resolves cache entry."""
        # First, create a cache entry through the API
        # (This would normally happen via create_run endpoint)
        from brain_researcher.services.orchestrator import main_enhanced
        cache_store = main_enhanced.cache_store

        cache_key = "sha256:test_resolve_key"
        asyncio.run(cache_store.create_and_mark_pending(
            cache_key=cache_key,
            run_id="run_resolve_001",
            meta={"tool": "test.tool"},
        ))
        asyncio.run(cache_store.mark_completed(
            cache_key=cache_key,
            run_id="run_resolve_001",
            run_dir="/tmp/run_resolve_001",
            size_bytes=512,
        ))

        # Resolve via API
        response = test_client_with_cache.get(
            "/api/cache/resolve",
            params={"key": cache_key}
        )
        assert response.status_code == 200

        entry = response.json()
        assert entry["cache_key"] == cache_key
        assert entry["run_id"] == "run_resolve_001"
        assert entry["state"] == "completed"

    def test_cache_resolve_accepts_key_alias(self, test_client_with_cache):
        """GET /api/runs/resolve works with ?key="""
        from brain_researcher.services.orchestrator import main_enhanced
        cache_store = main_enhanced.cache_store

        cache_key = "sha256:resolve_alias"
        asyncio.run(cache_store.create_and_mark_pending(cache_key=cache_key, run_id="run_alias", meta={}))
        asyncio.run(cache_store.mark_completed(cache_key, "run_alias", "/tmp/run_alias"))

        response = test_client_with_cache.get(f"/api/runs/resolve?key={cache_key}")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "run_alias"
        assert data["cache_key"] == cache_key

    def test_cache_resolve_by_params(self, test_client_with_cache):
        """POST /api/cache/resolve computes key and checks cache."""
        response = test_client_with_cache.post(
            "/api/cache/resolve",
            json={
                "tool": "fsl.bet",
                "tool_version": "6.0.7",
                "parameters": {"input": "/tmp/input.nii", "output": "/tmp/output.nii"},
                "container_image": "/cvmfs/fsl.simg",
            }
        )
        assert response.status_code == 200

        result = response.json()
        assert "cache_key" in result
        assert result["cache_key"].startswith("sha256:")
        assert "found" in result
        # Should be miss since we didn't create this entry
        assert result["found"] is False


class TestRunResolverEndpoint:
    """Tests for GET /api/runs/resolve."""

    def test_run_resolver_returns_completed_entry(self, test_client_with_cache):
        store = getattr(main_enhanced, "cache_store", None)
        assert store is not None, "Cache store not initialized"

        cache_key = "sha256:test_run_resolve_http"
        run_id = "job_demo_resolve_http"

        asyncio.run(store.clear_all())
        asyncio.run(store.create_and_mark_pending(
            cache_key=cache_key,
            run_id=run_id,
            meta={"tool": "demo.tool"},
            tool_version="demo.tool:1.0.0",
            git_sha="deadbeef",
        ))
        asyncio.run(store.mark_completed(
            cache_key=cache_key,
            run_id=run_id,
            run_dir="/tmp/demo_resolve_http",
            size_bytes=256,
        ))

        resp = test_client_with_cache.get(f"/api/runs/resolve?cache_key={cache_key}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["cache_key"] == cache_key

    def test_run_resolver_404(self, test_client_with_cache):
        resp = test_client_with_cache.get("/api/runs/resolve?cache_key=sha256:missing")
        assert resp.status_code == 404

    def test_run_resolver_missing_key_returns_400(self, test_client_with_cache):
        resp = test_client_with_cache.get("/api/runs/resolve")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "cache_key or key is required"

    def test_run_resolver_pending_entry_returns_404(self, test_client_with_cache):
        from brain_researcher.services.orchestrator import main_enhanced

        cache_store = main_enhanced.cache_store
        cache_key = "sha256:test_run_resolve_pending"
        asyncio.run(
            cache_store.create_and_mark_pending(
                cache_key=cache_key,
                run_id="job_pending_resolve",
                meta={"tool": "demo"},
                tool_version="1.0.0",
            )
        )

        resp = test_client_with_cache.get(f"/api/runs/resolve?cache_key={cache_key}")
        assert resp.status_code == 404

    def test_cache_clear_endpoint(self, test_client_with_cache):
        """DELETE /api/cache clears cache entries."""
        # Add some entries first
        from brain_researcher.services.orchestrator import main_enhanced
        cache_store = main_enhanced.cache_store

        for i in range(3):
            asyncio.run(cache_store.create_and_mark_pending(
                cache_key=f"sha256:test_clear_{i}",
                run_id=f"run_{i}",
                meta={},
            ))

        # Clear all
        response = test_client_with_cache.delete("/api/cache")
        assert response.status_code == 200

        result = response.json()
        assert result["deleted"] >= 3
        assert result["filter"] == "all"

    def test_cache_gc_endpoint(self, test_client_with_cache):
        """POST /api/cache/gc runs LRU eviction."""
        response = test_client_with_cache.post(
            "/api/cache/gc",
            params={"max_entries": 1000}
        )
        assert response.status_code == 200

        result = response.json()
        assert "evicted" in result
        assert "max_entries" in result


class TestEndToEndCacheFlow:
    """Test end-to-end cache flow with create_run endpoint."""

    def test_cache_miss_creates_job_and_pending_entry(self, test_client_with_cache):
        """First request creates job and pending cache entry."""
        store = getattr(main_enhanced, "cache_store", None)
        assert store is not None, "Cache store not initialized"
        asyncio.run(store.clear_all())

        response = test_client_with_cache.post("/run", json=_demo_run_payload())
        assert response.status_code == 200
        data = response.json()
        assert data["cached"] is False
        assert data["cache_key"]

        entry = asyncio.run(store.lookup(data["cache_key"]))
        assert entry is not None
        assert entry.state == "pending"
        assert entry.run_id == data["job_id"]

    def test_cache_hit_returns_cached_result(self, test_client_with_cache):
        """Second request with same params returns cached result."""
        store = getattr(main_enhanced, "cache_store", None)
        assert store is not None
        asyncio.run(store.clear_all())

        first = test_client_with_cache.post("/run", json=_demo_run_payload())
        assert first.status_code == 200
        first_data = first.json()

        assert first_data["cache_key"]
        assert first_data["cached"] is False

        completed = asyncio.run(store.mark_completed(
            cache_key=first_data["cache_key"],
            run_id=first_data["job_id"],
            run_dir="/tmp/cache_hit_run",
            size_bytes=1024,
        ))
        assert completed is True

        second = test_client_with_cache.post("/run", json=_demo_run_payload())
        assert second.status_code == 200
        second_data = second.json()
        assert second_data["cached"] is True
        assert second_data["job_id"] == first_data["job_id"]
        assert second_data["cache_key"] == first_data["cache_key"]

    def test_cache_pending_returns_409(self, test_client_with_cache):
        """Request while computation pending returns 409."""
        store = getattr(main_enhanced, "cache_store", None)
        assert store is not None
        asyncio.run(store.clear_all())

        first = test_client_with_cache.post("/run", json=_demo_run_payload())
        assert first.status_code == 200
        first_data = first.json()

        second = test_client_with_cache.post("/run", json=_demo_run_payload())
        assert second.status_code == 409
        body = second.json()
        assert body["error"] == "computation_in_progress"
        assert "cache_key" in body
        assert body["run_id"] == first_data["job_id"]

    def test_job_detail_and_steps_reflect_cache_metadata(self, test_client_with_cache):
        """/jobs/{id} and /api/jobs/{id}/steps expose cache metadata persisted via JobStore."""
        response = test_client_with_cache.post("/run", json=_demo_run_payload())
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        job_store = getattr(app.state, "job_store", None)
        if job_store is None:
            pytest.skip("job_store not initialized for cache metadata test")

        job_record = asyncio.run(job_store.get(job_id))
        assert job_record is not None
        payload = json.loads(job_record.payload_json)
        metadata = payload.setdefault("metadata", {})
        cache_key = metadata.get("cache_key") or "sha256:test_meta"
        metadata["cache_key"] = cache_key
        payload["metadata"] = metadata
        job_record.payload_json = json.dumps(payload)
        asyncio.run(job_store.update_state(job_id, job_record.state, payload_json=job_record.payload_json))

        worker = JobWorker(job_store, worker_id="test-cache-meta")
        asyncio.run(
            worker._annotate_cache_metadata(
                job_id,
                cache_key,
                hit=True,
                run_dir="/tmp/cache-meta",
                metadata=metadata,
                payload=payload,
                job_record=job_record,
            )
        )

        job_detail = test_client_with_cache.get(f"/jobs/{job_id}")
        assert job_detail.status_code == 200
        job_payload = job_detail.json()
        assert job_payload["metadata"]["cache"]["hit"] is True
        assert job_payload["metadata"]["cache"]["key"] == cache_key
        assert job_payload["cache_metadata"]["cache_hit"] is True
        assert job_payload["cache_metadata"]["cache_key"] == cache_key

        steps = test_client_with_cache.get(f"/api/jobs/{job_id}/steps")
        assert steps.status_code == 200
        assert steps.json()["cache_hit"] is True


class TestRunFastPath:
    """Tests covering deterministic /run cache fast-path behavior."""

    @pytest.mark.asyncio
    async def test_run_fastpath_miss_then_hit(self, async_client_with_cache, tmp_path):
        store = await _get_or_init_cache_store()
        await store.clear_all()

        payload = _demo_run_payload()
        first = await async_client_with_cache.post("/run", json=payload)
        assert first.status_code in (200, 201)
        first_data = first.json()

        store = await _get_or_init_cache_store()

        run_dir = tmp_path / "fastpath_hit"
        run_dir.mkdir()
        artifact = run_dir / "result.txt"
        artifact.write_text("done")
        size_bytes = artifact.stat().st_size

        await store.mark_completed(
            cache_key=first_data["cache_key"],
            run_id=first_data["job_id"],
            run_dir=str(run_dir),
            size_bytes=size_bytes,
        )

        second = await async_client_with_cache.post("/run", json=payload)
        assert second.status_code == 200
        second_data = second.json()
        assert second_data["cached"] is True
        assert second_data["job_id"] == first_data["job_id"]
        assert second_data["cache_key"] == first_data["cache_key"]

    @pytest.mark.asyncio
    async def test_run_concurrent_reserve_returns_409(self, async_client_with_cache):
        store = await _get_or_init_cache_store()
        await store.clear_all()

        payload = _demo_run_payload()

        async def submit():
            return await async_client_with_cache.post("/run", json=payload)

        resp_one, resp_two = await asyncio.gather(submit(), submit())
        statuses = sorted([resp_one.status_code, resp_two.status_code])
        assert statuses[0] in (200, 201)
        assert statuses[1] == 409

        conflict = resp_one if resp_one.status_code == 409 else resp_two
        body = conflict.json()
        assert body["error"] == "computation_in_progress"
        assert "cache_key" in body

    @pytest.mark.asyncio
    async def test_run_writes_cache_and_resolve_reports_size(self, async_client_with_cache, tmp_path):
        store = await _get_or_init_cache_store()
        await store.clear_all()

        payload = _demo_run_payload()
        response = await async_client_with_cache.post("/run", json=payload)
        assert response.status_code in (200, 201)
        run_info = response.json()

        store = await _get_or_init_cache_store()

        run_dir = tmp_path / run_info["job_id"]
        run_dir.mkdir()
        artifact = run_dir / "result.txt"
        artifact.write_text("cached output")
        size_bytes = artifact.stat().st_size

        await store.mark_completed(
            cache_key=run_info["cache_key"],
            run_id=run_info["job_id"],
            run_dir=str(run_dir),
            size_bytes=size_bytes,
        )

        resolver = await async_client_with_cache.get(
            f"/api/runs/resolve?cache_key={run_info['cache_key']}"
        )
        assert resolver.status_code == 200
        resolver_data = resolver.json()
        assert resolver_data["run_id"] == run_info["job_id"]
        assert resolver_data["state"] == "completed"
        assert resolver_data["size_bytes"] >= size_bytes


@pytest.fixture
async def async_client_with_cache(tmp_path):
    """Async client variant that enables cache + memory JobStore."""
    env_overrides = {
        "BR_CACHE_ENABLED": "true",
        "BR_CACHE_STORE": "memory",
        "BR_CACHE_MODE": "fast",
        "BR_PLANNER_MODE": "disabled",
        "BR_QUEUE_BACKEND": "memory",
        "BR_PREFLIGHT_MODE": "WARN",
    }
    cache_db = tmp_path / "async_cache.db"
    env_overrides["BR_CACHE_DB_PATH"] = str(cache_db)

    for key, value in env_overrides.items():
        os.environ[key] = value

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        store = MemoryCacheStore()
        await store.initialize()
        main_enhanced.cache_store = store
        app.state.cache_store = store
        await store.clear_all()
        yield client
        store = getattr(main_enhanced, "cache_store", None)
        if store:
            await store.clear_all()

    for key in env_overrides:
        os.environ.pop(key, None)
    main_enhanced.cache_store = None


@pytest.mark.asyncio
async def test_worker_marks_cache_and_resolver_handles_hit(async_client_with_cache, monkeypatch, tmp_path):
    """Ensure worker finalization marks cache entries and resolver reports hits."""
    from types import SimpleNamespace
    from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
    from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
    from brain_researcher.services.orchestrator.worker import JobWorker

    cache_store = MemoryCacheStore()
    await cache_store.initialize()
    main_enhanced.cache_store = cache_store
    original_app_cache = getattr(app.state, "cache_store", None)
    app.state.cache_store = cache_store

    job_store = MemoryJobStore()
    original_job_store = getattr(app.state, "job_store", None)
    app.state.job_store = job_store

    cache_key = "sha256:worker_hit_key"
    payload = {
        "metadata": {
            "cache_key": cache_key,
            "parameters": {"tool": "glm.pipeline"},
        }
    }
    job = JobRecord(
        job_id="job_worker_cache_hit",
        kind="tool",
        payload_json=json.dumps(payload),
        state=JobState.QUEUED,
        priority=5,
        gpu_req=0,
    )
    await job_store.enqueue(job)
    await cache_store.create_and_mark_pending(
        cache_key=cache_key,
        run_id=job.job_id,
        meta={"tool": "glm.pipeline"},
        tool_version="glm.pipeline:1.0.0",
        git_sha="deadbeef",
    )

    # Ensure legacy in-memory job cache sees metadata updates.
    main_enhanced.jobs_db[job.job_id] = SimpleNamespace(metadata={})

    worker = JobWorker(
        job_store,
        worker_id="worker-cache-hit",
        heartbeat_interval=0.05,
    )

    async def fake_execute_job(self, job_record):
        await asyncio.sleep(0.05)
        await self._finalize_job(
            job_record.job_id,
            exit_code=0,
            run_id=f"run_{job_record.job_id}",
            run_dir=str(tmp_path / "worker_run"),
            provenance_path=None,
        )

    monkeypatch.setattr(JobWorker, "_execute_job", fake_execute_job, raising=False)

    worker_task = asyncio.create_task(worker.start())
    try:
        await asyncio.sleep(0.2)
        await worker.stop()
        await worker_task

        entry = await cache_store.lookup(cache_key)
        assert entry is not None
        assert entry.state == "completed"

        resolver_resp = await async_client_with_cache.get(f"/api/runs/resolve?cache_key={cache_key}")
        assert resolver_resp.status_code == 200
        resolver_data = resolver_resp.json()
        assert resolver_data["run_id"] == job.job_id
    finally:
        main_enhanced.jobs_db.pop(job.job_id, None)
        app.state.cache_store = original_app_cache
        app.state.job_store = original_job_store
        main_enhanced.cache_store = original_app_cache


class TestCacheLRUEviction:
    """Test LRU eviction logic."""

    @pytest.mark.asyncio
    async def test_gc_lru_evicts_oldest_entries(self, cache_store_memory):
        """gc_lru should evict oldest entries based on last_accessed_at."""
        # Create 5 entries
        for i in range(5):
            cache_key = f"sha256:evict_key_{i:03d}"
            await cache_store_memory.create_and_mark_pending(
                cache_key=cache_key,
                run_id=f"run_{i}",
                meta={},
            )
            await cache_store_memory.mark_completed(
                cache_key=cache_key,
                run_id=f"run_{i}",
                run_dir=f"/tmp/run_{i}",
            )
            # Small delay to ensure different access times
            await asyncio.sleep(0.01)

        # Access some entries to update their last_accessed_at
        await cache_store_memory.lookup("sha256:evict_key_003")
        await cache_store_memory.lookup("sha256:evict_key_004")

        # Run GC to keep only 2 entries
        evicted = await cache_store_memory.gc_lru(max_entries=2)
        assert evicted == 3

        # Verify that the 2 most recently accessed remain
        entry_3 = await cache_store_memory.lookup("sha256:evict_key_003")
        entry_4 = await cache_store_memory.lookup("sha256:evict_key_004")
        assert entry_3 is not None
        assert entry_4 is not None

        # Older entries should be gone
        entry_0 = await cache_store_memory.lookup("sha256:evict_key_000")
        assert entry_0 is None


class TestCacheInvalidation:
    """Test cache invalidation by tool version and git SHA."""

    @pytest.mark.asyncio
    async def test_clear_by_tool_version(self, cache_store_sqlite):
        """clear_by_tool should remove entries for specific tool."""
        # Create entries for different tools
        for tool in ["fsl.bet:6.0.7", "fsl.flirt:6.0.7", "ants.reg:2.3.0"]:
            for i in range(2):
                cache_key = f"sha256:{tool}_{i}"
                await cache_store_sqlite.create_and_mark_pending(
                    cache_key=cache_key,
                    run_id=f"run_{tool}_{i}",
                    meta={},
                    tool_version=tool,
                )

        # Clear all fsl.bet entries
        deleted = await cache_store_sqlite.clear_by_tool("fsl.bet:6.0.7")
        assert deleted == 2

        # Verify others remain
        stats = await cache_store_sqlite.get_stats()
        assert stats.total_entries == 4  # 2 flirt + 2 ants

    @pytest.mark.asyncio
    async def test_clear_by_git_sha(self, cache_store_sqlite):
        """clear_by_git should remove entries for specific commit."""
        git_sha_old = "abc123def456"
        git_sha_new = "xyz789uvw012"

        # Create entries with different git SHAs
        for sha in [git_sha_old, git_sha_new]:
            for i in range(3):
                cache_key = f"sha256:{sha}_{i}"
                await cache_store_sqlite.create_and_mark_pending(
                    cache_key=cache_key,
                    run_id=f"run_{sha}_{i}",
                    meta={},
                    git_sha=sha,
                )

        # Clear entries for old SHA
        deleted = await cache_store_sqlite.clear_by_git(git_sha_old)
        assert deleted == 3

        # Verify new SHA entries remain
        stats = await cache_store_sqlite.get_stats()
        assert stats.total_entries == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
