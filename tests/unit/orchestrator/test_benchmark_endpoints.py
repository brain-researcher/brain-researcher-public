"""Unit tests for benchmark_endpoints — API contract and query logic."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.benchmark_endpoints import router, _ensure_tables


@pytest.fixture()
def db_path(tmp_path):
    """Create temp SQLite DB with schema."""
    p = tmp_path / "test_bench.sqlite"
    conn = sqlite3.connect(str(p))
    schema = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "brain_researcher"
        / "services"
        / "orchestrator"
        / "sqlite_schema"
        / "schema.sql"
    )
    conn.executescript(schema.read_text())
    conn.close()
    return p


@pytest.fixture()
def client(db_path, monkeypatch):
    """TestClient with benchmark router, patched DB path."""
    import brain_researcher.services.orchestrator.benchmark_endpoints as mod
    monkeypatch.setattr(mod, "_DB_PATH", db_path)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed_tasks(db_path: Path, dataset_id: str = "ds1", count: int = 3):
    """Seed benchmark tables with sample data."""
    conn = sqlite3.connect(str(db_path))
    now = int(time.time())

    conn.execute(
        """INSERT OR IGNORE INTO benchmark_datasets
           (dataset_id, version, name, source_type, source_ref_json, imported_at, updated_at)
           VALUES (?, '1.0', ?, 'registry', '{}', ?, ?)""",
        (dataset_id, dataset_id, now, now),
    )

    for i in range(count):
        tid = f"task-{i}"
        spec = json.dumps({"schema_version": "task-spec-v1", "task_id": tid, "inputs": {"prompt": f"do {i}"}})
        conn.execute(
            """INSERT INTO benchmark_tasks
               (dataset_id, task_id, content_hash, task_spec_json,
                source_category, source_difficulty, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (dataset_id, tid, f"hash{i}", spec, "shell", "easy", now, now),
        )
        conn.execute(
            """INSERT INTO benchmark_task_governance
               (dataset_id, task_id, status, category, updated_at)
               VALUES (?, ?, 'imported', 'shell', ?)""",
            (dataset_id, tid, now),
        )
        if i == 0:
            conn.execute(
                "INSERT INTO benchmark_task_tags (dataset_id, task_id, tag) VALUES (?, ?, 'linux')",
                (dataset_id, tid),
            )
    conn.commit()
    conn.close()


# ---- GET /api/benchmarks/datasets ----------------------------------------

class TestListDatasets:
    def test_empty(self, client):
        resp = client.get("/api/benchmarks/datasets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["datasets"] == []
        assert data["total"] == 0

    def test_with_data(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.get("/api/benchmarks/datasets")
        assert resp.status_code == 200
        assert len(resp.json()["datasets"]) == 1

    def test_status_filter(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.get("/api/benchmarks/datasets?status=active")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = client.get("/api/benchmarks/datasets?status=deprecated")
        assert resp.json()["total"] == 0


# ---- GET /api/benchmarks/datasets/{id}/tasks ------------------------------

class TestListTasks:
    def test_list_all(self, client, db_path):
        _seed_tasks(db_path, count=5)
        resp = client.get("/api/benchmarks/datasets/ds1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["tasks"]) == 5

    def test_search_filter(self, client, db_path):
        _seed_tasks(db_path, count=3)
        resp = client.get("/api/benchmarks/datasets/ds1/tasks?q=task-1")
        data = resp.json()
        assert data["total"] == 1

    def test_status_filter(self, client, db_path):
        _seed_tasks(db_path, count=3)
        resp = client.get("/api/benchmarks/datasets/ds1/tasks?status=imported")
        assert resp.json()["total"] == 3

        resp = client.get("/api/benchmarks/datasets/ds1/tasks?status=active")
        assert resp.json()["total"] == 0

    def test_tag_filter(self, client, db_path):
        _seed_tasks(db_path, count=3)
        resp = client.get("/api/benchmarks/datasets/ds1/tasks?tag=linux")
        assert resp.json()["total"] == 1

    def test_pagination(self, client, db_path):
        _seed_tasks(db_path, count=5)
        resp = client.get("/api/benchmarks/datasets/ds1/tasks?limit=2&offset=0")
        data = resp.json()
        assert len(data["tasks"]) == 2
        assert data["total"] == 5


# ---- GET /api/benchmarks/tasks/{dataset_id}/{task_id} --------------------

class TestGetTaskDetail:
    def test_found(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.get("/api/benchmarks/tasks/ds1/task-0")
        assert resp.status_code == 200
        data = resp.json()
        assert "task_spec" in data
        assert data["task_spec"]["task_id"] == "task-0"
        assert data["governance"] is not None
        assert data["governance"]["status"] == "imported"
        assert "linux" in data["tags"]

    def test_not_found(self, client, db_path):
        resp = client.get("/api/benchmarks/tasks/ds1/nonexistent")
        assert resp.status_code == 404


# ---- PATCH /api/benchmarks/tasks/{dataset_id}/{task_id}/governance --------

class TestUpdateGovernance:
    def test_update_status(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.patch(
            "/api/benchmarks/tasks/ds1/task-0/governance",
            json={"status": "validated"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "validated"

    def test_update_multiple_fields(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.patch(
            "/api/benchmarks/tasks/ds1/task-0/governance",
            json={"status": "active", "owner": "alice", "notes": "Reviewed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["owner"] == "alice"

    def test_empty_body_rejected(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.patch(
            "/api/benchmarks/tasks/ds1/task-0/governance",
            json={},
        )
        assert resp.status_code == 400

    def test_missing_task_returns_404(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.patch(
            "/api/benchmarks/tasks/ds1/does-not-exist/governance",
            json={"status": "active"},
        )
        assert resp.status_code == 404

    def test_update_created_by_fields(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.patch(
            "/api/benchmarks/tasks/ds1/task-0/governance",
            json={
                "created_by_name": "Alice",
                "created_by_email": "alice@example.com",
                "created_by_profile": "https://example.com/alice",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_by_name"] == "Alice"
        assert data["created_by_email"] == "alice@example.com"


# ---- POST /api/benchmarks/tasks/{dataset_id}/{task_id}/validations --------

class TestAddValidation:
    def test_add_validation(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.post(
            "/api/benchmarks/tasks/ds1/task-0/validations",
            json={
                "validator": "alice",
                "type": "manual_review",
                "result": "pass",
                "notes": "Looks good",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "validated_at" in data

    def test_validation_on_nonexistent_task(self, client, db_path):
        resp = client.post(
            "/api/benchmarks/tasks/ds1/nonexistent/validations",
            json={
                "validator": "alice",
                "type": "manual_review",
                "result": "pass",
            },
        )
        assert resp.status_code == 404


# ---- GET /api/benchmarks/taxonomy ----------------------------------------

class TestTaxonomy:
    def test_empty(self, client):
        resp = client.get("/api/benchmarks/taxonomy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["statuses"] == []
        assert data["categories"] == []

    def test_with_data(self, client, db_path):
        _seed_tasks(db_path)
        resp = client.get("/api/benchmarks/taxonomy")
        data = resp.json()
        assert "imported" in data["statuses"]
        assert "shell" in data["categories"]
        assert "linux" in data["tags"]
        assert "easy" in data["difficulties"]


# ---- POST /api/benchmarks/import -----------------------------------------

class TestImportEndpoint:
    @patch(
        "brain_researcher.services.orchestrator.benchmark_endpoints.fetch_tasks_from_url",
        new_callable=AsyncMock,
    )
    def test_import_success(self, mock_fetch, client, db_path):
        mock_fetch.return_value = [
            {"task_id": "t1", "instruction": "hello", "tags": ["a"]},
            {"task_id": "t2", "prompt": "world"},
        ]
        resp = client.post(
            "/api/benchmarks/import",
            json={"url": "https://example.com/tasks.json", "dataset_id": "testds"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "succeeded"
        assert data["summary"]["added"] == 2

    @patch(
        "brain_researcher.services.orchestrator.benchmark_endpoints.fetch_tasks_from_url",
        new_callable=AsyncMock,
    )
    def test_import_idempotent(self, mock_fetch, client, db_path):
        tasks = [{"task_id": "t1", "instruction": "hello"}]
        mock_fetch.return_value = tasks

        client.post("/api/benchmarks/import", json={"url": "https://x.com/t.json", "dataset_id": "ds"})
        resp = client.post("/api/benchmarks/import", json={"url": "https://x.com/t.json", "dataset_id": "ds"})
        data = resp.json()
        assert data["summary"]["skipped"] == 1
        assert data["summary"]["added"] == 0

    @patch(
        "brain_researcher.services.orchestrator.benchmark_endpoints.fetch_tasks_from_url",
        new_callable=AsyncMock,
    )
    def test_import_fetch_failure(self, mock_fetch, client, db_path):
        mock_fetch.side_effect = Exception("Connection refused")
        resp = client.post(
            "/api/benchmarks/import",
            json={"url": "https://down.com/tasks.json"},
        )
        assert resp.status_code == 502

    @patch(
        "brain_researcher.services.orchestrator.benchmark_endpoints.fetch_tasks_from_url",
        new_callable=AsyncMock,
    )
    def test_import_tbench_html_error_returns_400(self, mock_fetch, client, db_path):
        mock_fetch.side_effect = ValueError(
            "Provided Terminal-Bench URL is an HTML page, not a JSON registry payload. "
            "Use a raw JSON endpoint for import."
        )
        resp = client.post(
            "/api/benchmarks/import",
            json={"url": "https://www.tbench.ai/registry/terminal-bench/2.0"},
        )
        assert resp.status_code == 400
        assert "HTML page" in resp.json()["detail"]


class TestDbPathResolution:
    def test_resolve_db_path_prefers_queue_db_path(self, monkeypatch):
        import brain_researcher.services.orchestrator.benchmark_endpoints as mod

        monkeypatch.setattr(mod, "_DB_PATH", None)
        monkeypatch.delenv("BR_BENCHMARK_DB_PATH", raising=False)
        monkeypatch.setenv("BR_QUEUE_DB_PATH", "/tmp/queue_a.sqlite")
        monkeypatch.setenv("BR_QUEUE_DB", "/tmp/queue_b.sqlite")

        resolved = mod._resolve_db_path()
        assert str(resolved) == "/tmp/queue_a.sqlite"

    def test_resolve_db_path_prefers_benchmark_override(self, monkeypatch):
        import brain_researcher.services.orchestrator.benchmark_endpoints as mod

        monkeypatch.setattr(mod, "_DB_PATH", None)
        monkeypatch.setenv("BR_BENCHMARK_DB_PATH", "/tmp/bench.sqlite")
        monkeypatch.setenv("BR_QUEUE_DB_PATH", "/tmp/queue.sqlite")

        resolved = mod._resolve_db_path()
        assert str(resolved) == "/tmp/bench.sqlite"
