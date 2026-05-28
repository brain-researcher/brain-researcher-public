"""Real-data smoke test for literature search synthesis workflow.

This workflow normally depends on BR-KG. To keep strict real-data gating
deterministic in CI-like environments, this test installs a local request mock
for the BR-KG `/subgraph` endpoint instead of skipping.

Marked as `realdata` so it is skipped by default in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests

from brain_researcher.services.tools.runner import execute_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_ROOT = PROJECT_ROOT / "out" / "tmp_tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))


@pytest.mark.realdata
@pytest.mark.timeout(120)
def test_workflow_literature_search_synthesis_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class _MockResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}")

        def json(self) -> dict:
            return self._payload

    def _mock_neurokg_get(url: str, params: dict | None = None, **_: object) -> _MockResponse:
        if url.endswith("/subgraph"):
            concept = str((params or {}).get("name", "concept")).strip() or "concept"
            concept_slug = concept.lower().replace(" ", "_")
            return _MockResponse(
                {
                    "nodes": [
                        {
                            "data": {
                                "id": f"pmid:mock_{concept_slug}",
                                "label": "Paper",
                                "title": f"Mock paper for {concept}",
                                "year": 2025,
                                "authors": ["Mock Author"],
                                "abstract": f"Synthetic abstract for {concept}.",
                            }
                        }
                    ],
                    "edges": [],
                }
            )
        return _MockResponse({"error": "Not Found"}, status_code=404)

    monkeypatch.setattr(
        "brain_researcher.services.tools.neurokg_tools.requests.get", _mock_neurokg_get
    )

    out_dir = tmp_path / "literature"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = execute_tool(
        "workflow_literature_search_synthesis",
        {"query": "working memory fMRI", "output_dir": str(out_dir)},
    )
    assert res.status == "success", res.error
    assert res.data and "steps" in res.data

    literature_json = out_dir / "literature.json"
    assert literature_json.exists() and literature_json.stat().st_size > 0

    payload = json.loads(literature_json.read_text(encoding="utf-8"))
    assert int(payload.get("n_papers", 0)) >= 1
