from __future__ import annotations

from pathlib import Path


def test_root_neurokg_stage_bakes_spacy_model() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM base AS neurokg" in dockerfile
    assert "RUN python -m spacy download en_core_web_sm" in dockerfile
