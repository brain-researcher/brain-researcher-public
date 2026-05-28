from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.tools.etl import backfill_publication_citation_edges as script


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


class FakeLoader:
    def __init__(self, *args, **kwargs):
        del args, kwargs

    def load_records(self, *, dois):
        assert "10.1101/2025.07.21.665938" in dois
        return [
            {
                "doi": "10.1101/2025.07.21.665938",
                "title": "Rapid decoding paper",
                "citations": [
                    "10.1038/nn1444",
                    "10.1038/nn1444",
                    "https://doi.org/10.1016/j.neuroimage.2008.05.050",
                ],
            }
        ]


def test_build_citation_rows_shapes_rows() -> None:
    rows, stats = script._build_citation_rows(
        [
            {
                "publication_id": "10.1101/2025.07.21.665938",
                "doi": "10.1101/2025.07.21.665938",
                "title": "Rapid decoding paper",
                "dataset_ids": ["ds:openneuro:ds006661"],
            }
        ],
        loader=FakeLoader(),
        method_tag="publication_citation_backfill_v1",
    )

    assert len(rows) == 2
    assert rows[0]["source_publication_id"] == "10.1101/2025.07.21.665938"
    assert rows[0]["target_publication_id"] == "10.1038/nn1444"
    assert rows[0]["source_dataset_ids"] == ["ds:openneuro:ds006661"]
    assert rows[0]["source_lookup_terms"] == [
        "10.1101/2025.07.21.665938",
        "doi:10.1101/2025.07.21.665938",
    ]
    assert stats["citation_rows"] == 2
    assert stats["skipped_self_citation"] == 0


def test_main_apply_uses_method_tag_scoped_cites_edges(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    session = RecordingSession(
        [
            [
                {
                    "dataset_kg_id": "ds:openneuro:ds006661",
                    "dataset_id": "ds:openneuro:ds006661",
                    "source_repo_id": "ds006661",
                    "publication_id": "10.1101/2025.07.21.665938",
                    "doi": "10.1101/2025.07.21.665938",
                    "title": "Rapid decoding paper",
                }
            ],
            {"total": 0},
            {"selected_rows": 2, "matched_rows": 2, "matched_publications": 1},
            {
                "matched_rows": 2,
                "matched_publications": 1,
                "created_publications": 2,
                "created_edges": 2,
            },
            {"cleaned": 2},
            {"cleaned": 2},
        ]
    )
    monkeypatch.setattr(
        script.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: FakeDriver(session),
    )
    monkeypatch.setattr(script, "ScholarlyMetadataLoader", FakeLoader)

    report_path = tmp_path / "citation_backfill_report.json"
    exit_code = script.main(
        [
            "--dataset-id",
            "ds006661",
            "--neo4j-password",
            "test-password",
            "--neo4j-database",
            "neo4j",
            "--output-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["selection"]["citation_rows"] == 2
    assert payload["graph"]["created_edges"] == 2
    queries = [call["query"] for call in session.calls]
    assert any(
        "MERGE (src)-[r:CITES {method_tag: row.method_tag, target_id: row.target_publication_id}]->(dst)"
        in query
        for query in queries
    )
    stdout = json.loads(capsys.readouterr().out.strip())
    assert stdout["graph"]["created_edges"] == 2
