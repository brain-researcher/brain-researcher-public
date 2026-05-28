from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.memory import MemoryStore
from scripts.memory import backfill_memory_cards as backfill


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_backfill_run_id_filter_and_limit_select_expected_runs(
    tmp_path, monkeypatch, capsys
):
    run_root = tmp_path / "runs_root"
    for run_id in ("run_a", "run_b", "run_c"):
        _write_json(
            run_root / "runs" / run_id / "run.json",
            {"run_id": run_id, "status": "succeeded", "steps": []},
        )

    calls: list[str] = []

    def _fake_distill_and_store_run(run_id, *, run_dir, store):
        calls.append(run_id)
        assert run_dir == run_root / "runs" / run_id
        assert isinstance(store, MemoryStore)
        return {"episodic_written": True, "claim_count": 0, "writes": [1]}

    monkeypatch.setattr(backfill, "distill_and_store_run", _fake_distill_and_store_run)

    assert (
        backfill.main(
            [
                "--run-root",
                str(run_root),
                "--run-id",
                "run_b",
                "--run-id",
                "run_c",
                "--limit",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_run_ids"] == ["run_b", "run_c"]
    assert payload["missing_run_ids"] == []
    assert payload["candidate_count"] == 1
    assert payload["processed_count"] == 1
    assert payload["processed"][0]["run_id"] == "run_b"
    assert calls == ["run_b"]


def test_backfill_records_distill_failure_and_continues(tmp_path, monkeypatch, capsys):
    run_root = tmp_path / "runs"
    bad_run = run_root / "runs" / "bad_run"
    good_run = run_root / "runs" / "good_run"
    _write_json(
        good_run / "run.json",
        {
            "run_id": "good_run",
            "status": "succeeded",
            "steps": [],
        },
    )
    _write_json(
        bad_run / "run.json",
        {
            "run_id": "bad_run",
            "status": "succeeded",
            "steps": [],
        },
    )

    calls: list[str] = []

    def _fake_distill_and_store_run(run_id, *, run_dir, store):
        calls.append(run_id)
        assert isinstance(store, MemoryStore)
        if run_id == "bad_run":
            raise RuntimeError("boom")
        assert run_dir == good_run
        return {"episodic_written": True, "claim_count": 2, "writes": [1, 2]}

    monkeypatch.setattr(backfill, "distill_and_store_run", _fake_distill_and_store_run)

    assert backfill.main(["--run-root", str(run_root)]) == 0

    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["ok"] is True
    assert payload["processed_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["processed"][0]["run_id"] == "good_run"
    assert payload["skipped"][0]["run_id"] == "bad_run"
    assert "RuntimeError: boom" in payload["skipped"][0]["reason"]
    assert "traceback" in payload["skipped"][0]
    assert calls == ["bad_run", "good_run"]


def test_backfill_writes_claim_memory_for_real_claim_bearing_run(tmp_path, capsys):
    run_root = tmp_path / "mcp_runs"
    run_id = "run_claim_1"
    run_dir = run_root / "runs" / run_id
    _write_json(
        run_dir / "run.json",
        {
            "run_id": run_id,
            "created_at": "2026-04-04T00:00:00Z",
            "status": "succeeded",
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_id": "claim_extraction",
                    "params": {"dataset_ref": "HCP"},
                    "status": "succeeded",
                    "result_path": "outputs/claims.json",
                }
            ],
        },
    )
    _write_json(
        run_dir / "provenance.json",
        {
            "run_id": run_id,
            "route": "tool_execute",
            "request": {"dataset_ref": "HCP", "modality": "fMRI-task"},
        },
    )
    _write_json(
        run_dir / "session_snapshot.json",
        {
            "session_id": "session-claim-1",
            "goal": "Backfill explicit reward claim memories",
            "done": ["persisted extracted claims"],
            "open": ["review contradictory claim family"],
            "next_command": "compare the contradictory claim family",
        },
    )
    _write_json(
        run_dir / "outputs" / "claims.json",
        [
            {
                "run": {"run_id": "source-run-1"},
                "paper": {"id": "paper:reward"},
                "target": {"id": "region:amygdala", "type": "Region"},
                "mapping": {"canonical_id": "region:amygdala"},
                "claim": {
                    "id": "claim:reward:1",
                    "text": "Amygdala activation increases during reward anticipation.",
                    "polarity": "supports",
                    "claim_strength": 0.9,
                    "kind": "observation",
                },
                "evidence": {
                    "quote": "Amygdala activation increases during reward anticipation.",
                    "section": "abstract",
                },
                "variables": {"evidence_quality_score": 0.8},
            }
        ],
    )

    assert backfill.main(["--run-root", str(run_root), "--run-id", run_id]) == 0
    first_payload = json.loads(capsys.readouterr().out)
    assert first_payload["processed_count"] == 1
    assert first_payload["processed"][0]["run_id"] == run_id
    assert first_payload["processed"][0]["claim_count"] == 1

    store = MemoryStore(run_root=run_root)
    episodic = store.search(
        "",
        card_type="episodic_run_memory",
        filters={"source_run_id": run_id},
        limit=10,
    )
    claims = store.search(
        "reward anticipation amygdala",
        card_type="claim_memory",
        filters={"source_run_ids": "source-run-1", "target_id": "region:amygdala"},
        limit=10,
    )
    assert episodic["count"] >= 1
    assert claims["count"] >= 1
    assert claims["cards"][0]["claim_text"].startswith("Amygdala activation increases")

    assert backfill.main(["--run-root", str(run_root), "--run-id", run_id]) == 0
    second_payload = json.loads(capsys.readouterr().out)
    assert second_payload["processed_count"] == 1

    claims_after_rerun = store.search(
        "reward anticipation amygdala",
        card_type="claim_memory",
        filters={"source_run_ids": "source-run-1", "target_id": "region:amygdala"},
        limit=10,
    )
    assert claims_after_rerun["count"] == 1
