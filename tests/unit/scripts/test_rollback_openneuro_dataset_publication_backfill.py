from __future__ import annotations

import json
from typing import Any

from scripts.tools.etl import rollback_openneuro_dataset_publication_backfill as script


class FakeResult(list):
    def single(self):
        return self[0] if self else None


class RecordingSession:
    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def run(self, query: str, params: dict[str, Any] | None = None):
        self.calls.append({"query": query, "params": params or {}})
        response = self._responses.pop(0) if self._responses else None
        if isinstance(response, list):
            return FakeResult(response)
        if response is None:
            return FakeResult([])
        return FakeResult([response])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    def __init__(self, session: RecordingSession):
        self._session = session

    def session(self, database: str | None = None):
        assert database in {None, "neo4j"}
        return self._session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_main_dry_run_writes_json_report(tmp_path, monkeypatch, capsys) -> None:
    session = RecordingSession(
        [
            {
                "targeted_edges": 4,
                "targeted_datasets": 2,
                "targeted_publications": 3,
            },
            [
                {"publication_element_id": "pub-1"},
                {"publication_element_id": "pub-2"},
                {"publication_element_id": "pub-3"},
            ],
            {"prunable_publications": 2},
        ]
    )
    monkeypatch.setattr(
        script.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: FakeDriver(session),
    )

    report_path = tmp_path / "rollback_report.json"
    exit_code = script.main(
        [
            "--neo4j-password",
            "test-password",
            "--neo4j-database",
            "neo4j",
            "--method-tag",
            "openneuro_pub_backfill_v1",
            "--dry-run",
            "--prune-orphan-publications",
            "--output-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["filter"]["method_tag"] == "openneuro_pub_backfill_v1"
    assert report["targeted_edges"] == 4
    assert report["targeted_datasets"] == 2
    assert report["targeted_publications"] == 3
    assert report["prunable_publications"] == 2
    assert report["deleted_edges"] == 0
    assert report["deleted_publications"] == 0
    assert len(session.calls) == 3
    assert "Rollback dry-run" in capsys.readouterr().out


def test_main_apply_deletes_edges_and_prunes_publications(
    tmp_path, monkeypatch, capsys
) -> None:
    session = RecordingSession(
        [
            {
                "targeted_edges": 5,
                "targeted_datasets": 3,
                "targeted_publications": 4,
            },
            [
                {"publication_element_id": "pub-1"},
                {"publication_element_id": "pub-2"},
            ],
            {"prunable_publications": 2},
            {"deleted_edges": 5},
            {"deleted_publications": 2},
        ]
    )
    monkeypatch.setattr(
        script.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: FakeDriver(session),
    )

    report_path = tmp_path / "rollback_report_apply.json"
    exit_code = script.main(
        [
            "--neo4j-password",
            "test-password",
            "--neo4j-database",
            "neo4j",
            "--method-tag",
            "openneuro_pub_backfill_v2",
            "--prune-orphan-publications",
            "--output-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is False
    assert report["deleted_edges"] == 5
    assert report["deleted_publications"] == 2
    assert len(session.calls) == 5
    assert "Rollback done" in capsys.readouterr().out


def test_count_prunable_publications_requires_safe_orphan_condition() -> None:
    session = RecordingSession([{"prunable_publications": 1}])

    count = script._count_prunable_publications(
        session,
        method_tag="openneuro_pub_backfill_v3",
        publication_element_ids=["pub-1"],
    )

    assert count == 1
    assert session.calls
    query = session.calls[0]["query"]
    params = session.calls[0]["params"]
    assert "p.method_tag = $method_tag" in query
    assert "NOT EXISTS" in query
    assert "type(other) = 'CITED_BY' AND other.method_tag = $method_tag" in query
    assert params["publication_element_ids"] == ["pub-1"]
