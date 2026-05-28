from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.tools.etl import backfill_openneuro_dataset_publications as script


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


def _write_candidate_pack(tmp_path: Path) -> Path:
    payload = {
        "dataset_reports": [
            {
                "dataset_kg_id": "ds:openneuro:ds006661",
                "dataset_id": "ds:openneuro:ds006661",
                "source_repo_id": "ds006661",
                "aliases": ["Rapid decoding dataset"],
                "openneuro_dois": ["10.18112/openneuro.ds006661.v1.0.2"],
                "candidates": [
                    {
                        "title": "Rapid decoding of neural information representation from ultra-fast functional magnetic resonance imaging signals",
                        "doi": "10.1101/2025.07.21.665938",
                        "pmid": "",
                        "pmcid": "",
                        "journal": "bioRxiv",
                        "year": 2025,
                        "url": "https://example.org/ds006661-paper",
                        "score": 0.99,
                        "match_reasons": ["exact_title_match"],
                        "search_strategies": ["exact_title_match"],
                        "evidence": [{"url": "https://example.org/ds006661-paper"}],
                    },
                    {
                        "title": "Weak candidate",
                        "doi": "",
                        "score": 0.2,
                    },
                ],
            },
            {
                "dataset_kg_id": "ds:openneuro:ds001293",
                "dataset_id": "ds:openneuro:ds001293",
                "source_repo_id": "ds001293",
                "aliases": ["7T orientation decoding"],
                "openneuro_dois": ["10.18112/openneuro.ds001293.v1.0.0"],
                "candidates": [
                    {
                        "title": "Title only candidate",
                        "url": "https://example.org/title-only",
                        "score": 0.93,
                        "match_reasons": ["related_analysis"],
                        "search_strategies": ["related_analysis"],
                    }
                ],
            },
        ]
    }
    path = tmp_path / "candidate_pack.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_select_candidate_rows_filters_and_shapes_rows(tmp_path: Path) -> None:
    pack_path = _write_candidate_pack(tmp_path)
    reports = script._load_candidate_reports(pack_path)

    rows, stats = script._select_candidate_rows(
        reports,
        dataset_filters=set(),
        min_score=0.75,
        max_candidates_per_dataset=1,
        allow_title_only=False,
        candidate_pack_path=pack_path,
        method_tag="openneuro_backfill_v1",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["dataset_kg_id"] == "ds:openneuro:ds006661"
    assert row["publication_id"] == "10.1101/2025.07.21.665938"
    assert "ds006661" in row["publication_aliases"]
    assert "doi:10.1101/2025.07.21.665938" in row["publication_aliases"]
    assert row["dataset_lookup_terms"] == [
        "ds:openneuro:ds006661",
        "ds006661",
        "10.18112/openneuro.ds006661.v1.0.2",
    ]
    assert "openneuro" not in row["dataset_lookup_terms"]
    assert row["applied_from_pack"] == str(pack_path.resolve())
    assert stats["dataset_reports_selected"] == 2
    assert stats["candidates_selected"] == 1
    assert stats["skipped_missing_identifier"] == 1


def test_main_dry_run_writes_selection_only_report(
    tmp_path: Path, capsys
) -> None:
    pack_path = _write_candidate_pack(tmp_path)
    report_path = tmp_path / "backfill_report.json"

    exit_code = script.main(
        [
            "--candidate-pack",
            str(pack_path),
            "--dry-run",
            "--output-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["selection"]["candidates_selected"] == 1
    assert payload["graph"]["stats_skipped"] is True
    stdout = json.loads(capsys.readouterr().out.strip())
    assert stdout["ok"] is True
    assert stdout["selection"]["candidates_selected"] == 1


def test_main_apply_uses_method_tag_scoped_cited_by_edges(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    pack_path = _write_candidate_pack(tmp_path)
    session = RecordingSession(
        [
            {"total": 1},
            {"deleted": 1},
            {"selected_rows": 1, "matched_rows": 1, "matched_datasets": 1},
            {
                "matched_rows": 1,
                "matched_datasets": 1,
                "created_publications": 1,
                "created_edges": 1,
            },
            {"cleaned": 1},
            {"cleaned": 1},
        ]
    )
    monkeypatch.setattr(
        script.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: FakeDriver(session),
    )

    report_path = tmp_path / "backfill_apply_report.json"
    exit_code = script.main(
        [
            "--candidate-pack",
            str(pack_path),
            "--neo4j-password",
            "test-password",
            "--neo4j-database",
            "neo4j",
            "--method-tag",
            "openneuro_backfill_v2",
            "--prune-method-tag-first",
            "--output-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["graph"]["deleted_existing_edges"] == 1
    assert payload["graph"]["created_publications"] == 1
    assert payload["graph"]["created_edges"] == 1
    assert payload["graph"]["cleanup"]["cleaned_publication_flags"] == 1
    assert payload["graph"]["cleanup"]["cleaned_edge_flags"] == 1

    queries = [call["query"] for call in session.calls]
    assert any(
        "MERGE (d)-[r:CITED_BY {method_tag: row.method_tag}]->(p)" in query
        for query in queries
    )
    assert any("p.method_tag = row.method_tag" in query for query in queries)
    stdout = json.loads(capsys.readouterr().out.strip())
    assert stdout["graph"]["created_edges"] == 1
