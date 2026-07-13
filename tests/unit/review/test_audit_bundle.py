from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from brain_researcher.services.review.audit_bundle import (
    RUN_BUNDLE_SOURCE_FILENAMES,
    export_audit_bundle,
    persist_audit_bundle,
    rebuild_post_hoc,
)
from brain_researcher.services.review.bundle_builder import build_artifact_review_bundle


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_run_bundle_sources(run_dir: Path) -> None:
    for filename in RUN_BUNDLE_SOURCE_FILENAMES:
        path = run_dir / filename
        if filename.endswith(".json"):
            _write_json(path, {"source": filename})
        else:
            path.write_text('{"source":"trace.jsonl"}\n', encoding="utf-8")


@pytest.mark.unit
def test_audit_bundle_persist_live(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-123"
    commitment_hash = "pre-analysis-hash-verbatim"
    commitment = {
        "schema_version": "commitment-card-v1",
        "commitment_hash": commitment_hash,
        "claim_id": "claim-1",
    }
    claim_card = {
        "schema_version": "claim-card-v1",
        "claim_id": "claim-1",
        "status": "supported",
    }
    _write_json(run_dir / "society" / "commitment_card.json", commitment)
    _write_json(run_dir / "society" / "claim_card.json", claim_card)

    audit_dir = persist_audit_bundle(run_dir, provenance="live")

    assert audit_dir == run_dir / "audit"
    assert _read_json(audit_dir / "commitment.json") == commitment
    assert _read_json(audit_dir / "claim_card.json") == claim_card
    assert not (audit_dir / "refusal.json").exists()

    manifest = _read_json(audit_dir / "manifest.json")
    assert manifest["provenance"] == "live"
    assert manifest["status"] == "complete"
    assert manifest["commitment_hash"] == commitment_hash
    assert manifest["source_paths"]["commitment"] == "society/commitment_card.json"
    assert manifest["source_paths"]["claim_card"] == "society/claim_card.json"

    files_by_path = {entry["path"]: entry for entry in manifest["files"]}
    commitment_record = files_by_path["commitment.json"]
    assert commitment_record["sha256"] == _sha256(audit_dir / "commitment.json")
    assert commitment_record["bytes"] == (audit_dir / "commitment.json").stat().st_size


@pytest.mark.unit
def test_audit_bundle_persist_live_includes_run_bundle_sources(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-with-runtime-sources"
    _write_json(
        run_dir / "society" / "commitment_card.json",
        {"schema_version": "commitment-card-v1", "commitment_hash": "hash"},
    )
    _write_json(
        run_dir / "society" / "claim_card.json",
        {"schema_version": "claim-card-v1", "claim_id": "claim-1"},
    )
    _write_run_bundle_sources(run_dir)

    audit_dir = persist_audit_bundle(run_dir, provenance="live")

    manifest = _read_json(audit_dir / "manifest.json")
    assert manifest["source_paths"]["run_bundle"] == list(RUN_BUNDLE_SOURCE_FILENAMES)
    files_by_path = {entry["path"]: entry for entry in manifest["files"]}
    for filename in RUN_BUNDLE_SOURCE_FILENAMES:
        exported = audit_dir / filename
        assert exported.exists()
        assert exported.read_bytes() == (run_dir / filename).read_bytes()
        assert files_by_path[filename]["sha256"] == _sha256(exported)


@pytest.mark.unit
def test_audit_bundle_no_records(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty-run"
    run_dir.mkdir()

    audit_dir = persist_audit_bundle(run_dir)

    assert audit_dir == run_dir / "audit"
    manifest = _read_json(audit_dir / "manifest.json")
    assert manifest["status"] == "no_audit_records"
    assert manifest["files"] == []
    assert manifest["source_paths"] == {}
    assert not (audit_dir / "commitment.json").exists()
    assert not (audit_dir / "claim_card.json").exists()
    assert not (audit_dir / "refusal.json").exists()


@pytest.mark.unit
def test_audit_persist_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "run-disabled"
    _write_json(
        run_dir / "society" / "commitment_card.json",
        {"schema_version": "commitment-card-v1", "commitment_hash": "hash"},
    )
    monkeypatch.setenv("BR_AUDIT_PERSIST", "0")

    audit_dir = persist_audit_bundle(run_dir)

    assert audit_dir is None
    assert not (run_dir / "audit").exists()


@pytest.mark.unit
def test_bundle_builder_includes_society_cards(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-with-society"
    commitment = {
        "schema_version": "commitment-card-v1",
        "commitment_hash": "society-hash",
        "claim_id": "claim-1",
    }
    claim_card = {
        "schema_version": "claim-card-v1",
        "claim_id": "claim-1",
        "status": "supported",
    }
    _write_json(run_dir / "run.json", {"steps": []})
    _write_json(run_dir / "society" / "commitment_card.json", commitment)
    _write_json(run_dir / "society" / "claim_card.json", claim_card)
    persist_audit_bundle(run_dir)

    bundle = build_artifact_review_bundle("run-with-society", run_dir=run_dir)

    assert bundle.observed_artifacts["commitment_card"] == commitment
    assert bundle.observed_artifacts["claim_card"] == claim_card
    assert bundle.observed_artifacts["audit"]["manifest"]["status"] == "complete"


@pytest.mark.unit
def test_export_refuses_post_hoc_without_flag(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-posthoc"
    _write_json(run_dir / "REPORT.json", {"summary": "historical evidence"})
    rebuild_post_hoc(run_dir)

    response = export_audit_bundle(
        run_id="run-posthoc",
        run_dir=run_dir,
        dest_repo_path=tmp_path / "public",
        allow_post_hoc=False,
    )

    assert response["ok"] is False
    assert response["provenance"] == "post_hoc"
    assert "allow_post_hoc=True" in response["error"]
    assert not (tmp_path / "public").exists()


@pytest.mark.unit
def test_export_live_bundle_copies_readme_and_sha256(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-live"
    _write_json(
        run_dir / "society" / "commitment_card.json",
        {"schema_version": "commitment-card-v1", "commitment_hash": "hash"},
    )
    _write_json(
        run_dir / "society" / "claim_card.json",
        {"schema_version": "claim-card-v1", "claim_id": "claim-1"},
    )
    _write_run_bundle_sources(run_dir)
    persist_audit_bundle(run_dir, provenance="live")

    response = export_audit_bundle(
        run_id="run-live",
        run_dir=run_dir,
        dest_repo_path=tmp_path / "public",
    )

    dest = Path(response["dest_dir"])
    assert response["ok"] is True
    assert (dest / "manifest.json").exists()
    assert (dest / "README.md").exists()
    assert "run_bundle_get" in (dest / "README.md").read_text(encoding="utf-8")
    sha_by_path = response["sha256"]
    assert sha_by_path["manifest.json"] == _sha256(dest / "manifest.json")
    assert sha_by_path["README.md"] == _sha256(dest / "README.md")
    for filename in RUN_BUNDLE_SOURCE_FILENAMES:
        assert (dest / filename).exists()
        assert sha_by_path[filename] == _sha256(dest / filename)


@pytest.mark.unit
def test_rebuild_post_hoc_labels_and_refuses_hash(tmp_path: Path) -> None:
    run_dir = tmp_path / "historical-run"
    _write_json(run_dir / "analysis_bundle.json", {"claim": "available output"})

    audit_dir = rebuild_post_hoc(run_dir)

    manifest = _read_json(audit_dir / "manifest.json")
    claim_card = _read_json(audit_dir / "claim_card.json")
    assert manifest["provenance"] == "post_hoc"
    assert manifest["commitment_hash"] is None
    assert manifest["commitment_card_ref"] is None
    assert manifest["not_backfilled"] is True
    assert claim_card["provenance"] == "post_hoc"
    assert claim_card["commitment_card_ref"] is None
    assert claim_card["commitment_hash"] is None
    assert claim_card["not_backfilled"] is True
