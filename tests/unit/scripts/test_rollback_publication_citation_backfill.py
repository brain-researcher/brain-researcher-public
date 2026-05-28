from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.tools.etl import rollback_publication_citation_backfill as script


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


def test_main_dry_run_writes_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    session = RecordingSession(
        [
            {"targeted_edges": 4, "targeted_sources": 2, "targeted_targets": 3},
            [
                {"publication_element_id": "4:stub:1"},
                {"publication_element_id": "4:stub:2"},
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
            "publication_citation_backfill_v1",
            "--dry-run",
            "--prune-orphan-publications",
            "--output-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["targeted_edges"] == 4
    assert payload["prunable_publications"] == 2
    assert payload["filter"]["relationship_type"] == "CITES"
    stdout = capsys.readouterr().out
    assert "Rollback dry-run" in stdout


def test_prune_query_scopes_to_method_tag() -> None:
    session = RecordingSession([{"prunable_publications": 1}])

    count = script._count_prunable_publications(
        session,
        method_tag="publication_citation_backfill_v2",
        publication_element_ids=["4:stub:1"],
    )

    assert count == 1
    query = session.calls[0]["query"]
    assert "p.method_tag = $method_tag" in query
    assert "type(other) = 'CITES' AND other.method_tag = $method_tag" in query
