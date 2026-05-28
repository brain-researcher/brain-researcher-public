"""Unit tests for benchmark_importer — mapping, hashing, upsert logic."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator.benchmark_importer import (
    ImportSummary,
    _compute_hash,
    _map_to_task_spec,
    fetch_tasks_from_url,
    import_tasks,
    import_tasks_from_file,
    load_tasks_from_file,
)


@pytest.fixture()
def db():
    """In-memory SQLite with benchmark tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
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
    yield conn
    conn.close()


# ---- Mapping tests --------------------------------------------------------


class TestMapToTaskSpec:
    def test_instruction_key(self):
        spec = _map_to_task_spec(
            {"task_id": "t1", "instruction": "Do something", "category": "shell"},
        )
        assert spec.task_id == "t1"
        assert spec.inputs == {"instruction": "Do something"}

    def test_prompt_key(self):
        spec = _map_to_task_spec({"id": "t2", "prompt": "Run ls"})
        assert spec.task_id == "t2"
        assert spec.inputs == {"prompt": "Run ls"}

    def test_expected_output_single(self):
        spec = _map_to_task_spec(
            {"task_id": "t3", "expected_output": "hello", "input": "echo hello"},
        )
        assert len(spec.expected_outputs) == 1
        assert spec.expected_outputs[0]["kind"] == "expected_artifact"
        assert spec.expected_outputs[0]["id"] == "out_primary"
        assert spec.expected_outputs[0]["value"] == "hello"

    def test_oracle_mapping(self):
        spec = _map_to_task_spec(
            {"task_id": "t4", "oracle": {"script": "check.py"}, "prompt": "x"},
        )
        assert spec.expected_outputs[0]["kind"] == "gt_solution"
        assert spec.expected_outputs[0]["visibility"] == "authenticated"
        assert spec.expected_outputs[0]["content"]["script"] == "check.py"

    def test_tags_from_labels(self):
        spec = _map_to_task_spec({"task_id": "t5", "labels": ["a", "b"]})
        assert spec.tags == ["a", "b"]

    def test_metadata_populated(self):
        spec = _map_to_task_spec(
            {"task_id": "t6", "category": "web", "difficulty": "hard"},
        )
        assert spec.metadata is not None
        assert spec.metadata["category"] == "web"
        assert spec.metadata["difficulty"] == "hard"

    def test_fairness_audit_metadata_is_preserved(self):
        spec = _map_to_task_spec(
            {
                "task_id": "t6b",
                "instruction": "predict held-out behavior",
                "target_population": "adult human participants",
                "sampling_frame": "multi-site cohort",
                "audit_group_keys": ["site", "sex"],
                "fairness_audit": {
                    "group_audit": {
                        "resolved_group_keys": ["site", "sex"],
                    }
                },
            }
        )
        assert spec.metadata is not None
        assert spec.metadata["target_population"] == "adult human participants"
        assert spec.metadata["sampling_frame"] == "multi-site cohort"
        assert spec.metadata["audit_group_keys"] == ["site", "sex"]
        assert spec.metadata["fairness_audit"]["group_audit"]["resolved_group_keys"] == [
            "site",
            "sex",
        ]

    def test_scoring_string_wrapped(self):
        spec = _map_to_task_spec({"task_id": "t7", "scoring": "exact_match"})
        assert spec.scoring == {"method": "exact_match"}

    def test_inputs_dict_passthrough(self):
        spec = _map_to_task_spec({"task_id": "t8", "inputs": {"a": 1, "b": 2}})
        assert spec.inputs == {"a": 1, "b": 2}

    def test_answer_as_expected_output(self):
        spec = _map_to_task_spec({"task_id": "t9", "answer": "42"})
        assert spec.expected_outputs[0]["kind"] == "gt_solution"
        assert spec.expected_outputs[0]["content"] == "42"
        assert spec.expected_outputs[0]["format"] == "text"

    def test_expected_outputs_explicit_gt_keeps_kind(self):
        spec = _map_to_task_spec(
            {
                "task_id": "t10",
                "expected_outputs": [
                    {"kind": "gt_solution", "content": {"score": 1.0}},
                    {"path": "outputs/summary.json"},
                ],
            }
        )
        assert spec.expected_outputs[0]["kind"] == "gt_solution"
        assert spec.expected_outputs[0]["visibility"] == "authenticated"
        assert spec.expected_outputs[0]["id"] == "gt_primary"
        assert spec.expected_outputs[1]["kind"] == "expected_artifact"
        assert spec.expected_outputs[1]["id"] == "out_2"

    def test_expected_outputs_gt_keys_are_normalized(self):
        spec = _map_to_task_spec(
            {
                "task_id": "t11",
                "expected_outputs": [
                    {"oracle": {"checker": "check.py"}},
                ],
            }
        )
        assert spec.expected_outputs[0]["kind"] == "gt_solution"
        assert spec.expected_outputs[0]["content"] == {"checker": "check.py"}
        assert "oracle" not in spec.expected_outputs[0]


# ---- Hashing tests --------------------------------------------------------


def test_compute_hash_deterministic():
    h1 = _compute_hash('{"a":1}')
    h2 = _compute_hash('{"a":1}')
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_hash_different_for_different_content():
    h1 = _compute_hash('{"a":1}')
    h2 = _compute_hash('{"a":2}')
    assert h1 != h2


# ---- Upsert tests ---------------------------------------------------------


class TestImportTasks:
    def test_insert_new_tasks(self, db):
        raw = [
            {"task_id": "t1", "instruction": "hello", "tags": ["a"]},
            {"task_id": "t2", "prompt": "world"},
        ]
        summary = import_tasks(db, "ds1", "1.0", raw)
        db.commit()

        assert summary.added == 2
        assert summary.updated == 0
        assert summary.skipped == 0

        rows = db.execute("SELECT * FROM benchmark_tasks").fetchall()
        assert len(rows) == 2

        gov = db.execute("SELECT * FROM benchmark_task_governance").fetchall()
        assert len(gov) == 2
        assert gov[0]["status"] == "imported"

        tags = db.execute("SELECT * FROM benchmark_task_tags WHERE task_id='t1'").fetchall()
        assert [r["tag"] for r in tags] == ["a"]

    def test_idempotent_skip(self, db):
        raw = [{"task_id": "t1", "instruction": "hello"}]
        import_tasks(db, "ds1", "1.0", raw)
        db.commit()

        summary2 = import_tasks(db, "ds1", "1.0", raw)
        db.commit()

        assert summary2.skipped == 1
        assert summary2.added == 0

    def test_content_change_updates(self, db):
        raw = [{"task_id": "t1", "instruction": "hello"}]
        import_tasks(db, "ds1", "1.0", raw)
        db.commit()

        raw_updated = [{"task_id": "t1", "instruction": "hello world"}]
        summary = import_tasks(db, "ds1", "1.1", raw_updated)
        db.commit()

        assert summary.updated == 1
        assert summary.skipped == 0

        row = db.execute(
            "SELECT task_spec_json FROM benchmark_tasks WHERE task_id='t1'"
        ).fetchone()
        spec = json.loads(row["task_spec_json"])
        assert spec["inputs"]["instruction"] == "hello world"

    def test_governance_preserved_on_update(self, db):
        raw = [{"task_id": "t1", "instruction": "hello", "category": "shell"}]
        import_tasks(db, "ds1", "1.0", raw)
        db.commit()

        # Manually change governance
        db.execute(
            "UPDATE benchmark_task_governance SET status='validated' WHERE task_id='t1'"
        )
        db.commit()

        raw_updated = [{"task_id": "t1", "instruction": "changed", "category": "web"}]
        import_tasks(db, "ds1", "1.1", raw_updated, overwrite_governance=False)
        db.commit()

        gov = db.execute(
            "SELECT status FROM benchmark_task_governance WHERE task_id='t1'"
        ).fetchone()
        assert gov["status"] == "validated"

    def test_governance_overwritten_when_requested(self, db):
        raw = [{"task_id": "t1", "instruction": "hello", "category": "shell"}]
        import_tasks(db, "ds1", "1.0", raw)
        db.commit()

        db.execute(
            "UPDATE benchmark_task_governance SET status='validated' WHERE task_id='t1'"
        )
        db.commit()

        raw_updated = [{"task_id": "t1", "instruction": "changed", "category": "web"}]
        import_tasks(db, "ds1", "1.1", raw_updated, overwrite_governance=True)
        db.commit()

        gov = db.execute(
            "SELECT status, category FROM benchmark_task_governance WHERE task_id='t1'"
        ).fetchone()
        assert gov["status"] == "imported"
        assert gov["category"] == "web"

    def test_dataset_row_created(self, db):
        import_tasks(db, "myds", "2.0", [{"task_id": "t1", "instruction": "x"}])
        db.commit()

        ds = db.execute(
            "SELECT * FROM benchmark_datasets WHERE dataset_id='myds'"
        ).fetchone()
        assert ds is not None
        assert ds["version"] == "2.0"

    def test_empty_task_id_is_rejected(self, db):
        raw = [
            {"task_id": "t1", "instruction": "good"},
            {},  # Maps to empty task_id -> should fail validation
        ]
        summary = import_tasks(db, "ds", "1.0", raw)
        db.commit()

        assert summary.added == 1
        assert summary.failed == 1
        rows = db.execute("SELECT task_id FROM benchmark_tasks ORDER BY task_id").fetchall()
        assert [r["task_id"] for r in rows] == ["t1"]

    def test_import_job_recorded(self, db):
        # import_tasks itself does NOT write import_jobs — that's in endpoints
        # Just verify the table exists
        count = db.execute("SELECT COUNT(*) FROM benchmark_import_jobs").fetchone()[0]
        assert count == 0


class TestFileImports:
    @pytest.mark.parametrize(
        ("payload", "expected_ids"),
        [
            ([{"task_id": "list_1"}, {"task_id": "list_2"}], ["list_1", "list_2"]),
            ({"task_id": "single_1"}, ["single_1"]),
            ({"benchmark_tasks": [{"task_id": "psy_1"}, {"task_id": "psy_2"}]}, ["psy_1", "psy_2"]),
            ({"tasks": [{"task_id": "tasks_1"}]}, ["tasks_1"]),
            ({"data": [{"task_id": "data_1"}]}, ["data_1"]),
            ({"items": [{"task_id": "items_1"}]}, ["items_1"]),
        ],
    )
    def test_load_tasks_from_file_normalizes_manifest_shapes(
        self, tmp_path, payload, expected_ids
    ):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        tasks = load_tasks_from_file(manifest)

        assert [task["task_id"] for task in tasks] == expected_ids

    def test_import_tasks_from_file_uses_benchmark_tasks_manifest(self, db, tmp_path):
        manifest = tmp_path / "psych_101.json"
        manifest.write_text(
            json.dumps(
                {
                    "benchmark_tasks": [
                        {"task_id": "p1", "instruction": "Solve one"},
                        {"task_id": "p2", "instruction": "Solve two"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        summary = import_tasks_from_file(db, "psych101", "1.0", manifest)
        db.commit()

        assert summary.added == 2
        rows = db.execute(
            "SELECT task_id FROM benchmark_tasks ORDER BY task_id"
        ).fetchall()
        assert [row["task_id"] for row in rows] == ["p1", "p2"]


class TestImportSummary:
    def test_to_dict(self):
        s = ImportSummary()
        s.added = 3
        s.skipped = 1
        d = s.to_dict()
        assert d["added"] == 3
        assert d["skipped"] == 1
        assert d["errors"] == []


def test_fetch_tasks_from_url_rejects_tbench_html(monkeypatch):
    class DummyResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("not json")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.benchmark_importer.httpx.AsyncClient",
        DummyClient,
    )

    with pytest.raises(ValueError, match="Terminal-Bench URL is an HTML page"):
        asyncio.run(fetch_tasks_from_url("https://www.tbench.ai/registry/terminal-bench/2.0"))
