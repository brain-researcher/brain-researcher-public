from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain_researcher.services.mcp import runstore


def _configure_run_root(monkeypatch, tmp_path: Path):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    srv._ensure_dirs()
    return srv


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _write_run_fixture(
    root: Path,
    run_id: str,
    *,
    files: dict[str, object] | None = None,
) -> Path:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": "2026-05-29T00:00:00Z",
                "status": "succeeded",
                "dry_run": False,
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    for relpath, content in (files or {}).items():
        path = run_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict | list):
            path.write_text(json.dumps(content), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
    return run_dir


def test_memory_tools_slim_defaults_strip_embeddings_and_truncate_search(
    tmp_path,
    monkeypatch,
):
    srv = _configure_run_root(monkeypatch, tmp_path)
    long_summary = "Produced detailed memory card body. " * 120

    first_card_id = None
    for index in range(7):
        resp = srv.memory_write(
            "episodic_run_memory",
            {
                "source_run_id": f"run_memory_slim_{index}",
                "task_description": f"Memory payload slimming run {index}",
                "task_type": "analysis",
                "status": "success",
                "output_summary": long_summary,
                "tags": ["payload-slim"],
            },
        )
        assert resp["ok"] is True
        assert not _contains_key(resp, "embedding_vector")
        first_card_id = first_card_id or resp["card_id"]

    search = srv.memory_search(query="", card_type="episodic_run_memory")

    assert search["ok"] is True
    assert search["count"] == 5
    assert len(search["cards"]) == 5
    assert not _contains_key(search, "embedding_vector")
    assert search["truncation_marker"] == "...[truncated]"
    assert any("...[truncated]" in card["output_summary"] for card in search["cards"])

    full_search = srv.memory_search(
        query="",
        card_type="episodic_run_memory",
        limit=1,
        include_full_cards=True,
    )
    assert full_search["ok"] is True
    assert "...[truncated]" not in full_search["cards"][0]["output_summary"]

    get_resp = srv.memory_get(first_card_id or "")
    assert get_resp["ok"] is True
    assert not _contains_key(get_resp, "embedding_vector")

    get_with_embedding = srv.memory_get(
        first_card_id or "",
        include_embedding_vector=True,
    )
    assert get_with_embedding["ok"] is True
    assert _contains_key(get_with_embedding, "embedding_vector")


def test_execution_recipe_defaults_to_compact_local_run_alias():
    from brain_researcher.services.mcp import server as srv

    resp = srv.get_execution_recipe(
        "workflow_rest_connectome_e2e",
        params={"img": "/data/bold.nii.gz", "output_dir": "/data/out"},
        target_runtime="python",
    )

    assert resp["ok"] is True
    assert resp["run_pack"]["commands"][-1] == "python run_pack.py"
    assert resp["local_run"] == {
        "alias_for": "run_pack",
        "ref": "#/run_pack",
        "deprecated": True,
        "message": (
            "local_run is a compact backwards-compatible alias. Use run_pack, "
            "or call get_execution_recipe(..., include_legacy_local_run=True) "
            "for the legacy duplicated payload."
        ),
    }
    assert resp["local_run_alias"] is True
    assert len(json.dumps(resp["local_run"])) < len(json.dumps(resp["run_pack"]))

    legacy = srv.get_execution_recipe(
        "workflow_rest_connectome_e2e",
        params={"img": "/data/bold.nii.gz", "output_dir": "/data/out"},
        target_runtime="python",
        include_legacy_local_run=True,
    )
    assert legacy["ok"] is True
    assert legacy["local_run"] == legacy["run_pack"]
    assert legacy["local_run_alias"] is False


def test_run_bundle_get_omits_all_null_sections_by_default(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)
    run_id = "br_payload_slim_bundle"
    _write_run_fixture(
        tmp_path,
        run_id,
        files={
            "analysis_bundle.json": {
                "schema_version": "analysis-bundle-v1",
                "review_context": {
                    "design_model": {
                        "estimator": None,
                        "contrast": None,
                    },
                    "statistical_inference": {
                        "threshold": None,
                        "correction": None,
                    },
                    "claim_contract": {
                        "primary_claim": "Connectivity changed after QC.",
                    },
                },
            },
            "observation.json": {"schema_version": "observation-v1"},
        },
    )

    slim = srv.run_bundle_get(run_id)
    full = srv.run_bundle_get(run_id, verbose=True)

    assert slim["ok"] is True
    assert slim["verbose"] is False
    slim_context = slim["bundle"]["analysis_bundle"]["review_context"]
    assert "design_model" not in slim_context
    assert "statistical_inference" not in slim_context
    assert slim_context["claim_contract"]["primary_claim"] == (
        "Connectivity changed after QC."
    )
    assert (
        "$.analysis_bundle.review_context.design_model" in slim["omitted_null_sections"]
    )

    assert full["ok"] is True
    assert full["verbose"] is True
    full_context = full["bundle"]["analysis_bundle"]["review_context"]
    assert full_context["design_model"]["estimator"] is None
    assert full_context["statistical_inference"]["threshold"] is None
