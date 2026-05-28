from __future__ import annotations

import json
from pathlib import Path

from scripts.neurometabench_v1 import refresh_layer_b_episode_records as refresh


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_refresh_repairs_stale_failed_br_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    episode_dir = run_dir / "episodes" / "cond" / "layer_b_1"
    _write_json(episode_dir / "command.json", {"command": ["agent", "prompt"]})
    record = {
        "condition_id": "cond",
        "runner": "opencode",
        "model_target": "model",
        "br_mode": "with_br_mcp",
        "status": "failed_br_required_gate",
        "error": "old tracer missed anchor",
        "meta_pmids": ["1"],
        "producer_output_dir": str(run_dir / "producer" / "cond"),
        "episode_dir": str(episode_dir),
    }
    _write_jsonl(run_dir / "episode_records.jsonl", [record])

    def fake_finalize(**kwargs):
        assert kwargs["require_br_effective_use"] is True
        assert kwargs["command"] == ["agent", "prompt"]
        return {"all_br_required_pass": True, "all_preflight_pass": True, "cases": []}

    monkeypatch.setattr(refresh, "finalize_layer_b_episode", fake_finalize)

    summary = refresh.refresh_run(
        run_dir=run_dir,
        require_br_effective_use=True,
        repo_root=tmp_path,
    )

    refreshed = json.loads((episode_dir / "record.json").read_text(encoding="utf-8"))
    assert summary["n_repaired_failed_br_required_gate"] == 1
    assert refreshed["status"] == "succeeded"
    assert refreshed["posthoc_status_repair"] == "failed_br_required_gate_to_succeeded"
    assert "error" not in refreshed
    assert (run_dir / "episode_records.jsonl.pre_layer_b_refresh").exists()


def test_refresh_does_not_require_br_for_without_br_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    episode_dir = run_dir / "episodes" / "cond" / "layer_b_1"
    _write_json(episode_dir / "command.json", {"command": ["agent", "prompt"]})
    record = {
        "condition_id": "cond",
        "runner": "opencode",
        "model_target": "model",
        "br_mode": "without_br",
        "status": "succeeded",
        "meta_pmids": ["1"],
        "producer_output_dir": str(run_dir / "producer" / "cond"),
        "episode_dir": str(episode_dir),
    }
    _write_jsonl(run_dir / "episode_records.jsonl", [record])

    def fake_finalize(**kwargs):
        assert kwargs["require_br_effective_use"] is False
        return {"all_br_required_pass": False, "all_preflight_pass": True, "cases": []}

    monkeypatch.setattr(refresh, "finalize_layer_b_episode", fake_finalize)

    refresh.refresh_run(
        run_dir=run_dir,
        require_br_effective_use=True,
        repo_root=tmp_path,
    )

    refreshed = json.loads((episode_dir / "record.json").read_text(encoding="utf-8"))
    assert refreshed["status"] == "succeeded"


def test_refresh_fails_succeeded_br_required_row_without_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    episode_dir = run_dir / "episodes" / "cond" / "layer_b_1"
    _write_json(episode_dir / "command.json", {"command": ["agent", "prompt"]})
    record = {
        "condition_id": "cond",
        "runner": "opencode",
        "model_target": "model",
        "br_mode": "with_br_required",
        "status": "succeeded",
        "meta_pmids": ["1"],
        "producer_output_dir": str(run_dir / "producer" / "cond"),
        "episode_dir": str(episode_dir),
    }
    _write_jsonl(run_dir / "episode_records.jsonl", [record])

    monkeypatch.setattr(
        refresh,
        "finalize_layer_b_episode",
        lambda **_: {"all_br_required_pass": False, "all_preflight_pass": True, "cases": []},
    )

    refresh.refresh_run(run_dir=run_dir, repo_root=tmp_path)

    refreshed = json.loads((episode_dir / "record.json").read_text(encoding="utf-8"))
    assert refreshed["status"] == "failed_br_required_gate"
    assert refreshed["error"] == "BR-required condition did not produce an effective BR anchor"


def test_refresh_skips_records_without_producer_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    record = {
        "condition_id": "cond",
        "runner": "opencode",
        "model_target": "model",
        "br_mode": "with_br_required",
        "status": "succeeded",
        "meta_pmids": ["1"],
    }
    _write_jsonl(run_dir / "episode_records.jsonl", [record])

    def fail_finalize(**_: object) -> dict[str, object]:
        raise AssertionError("rows without producer_output_dir should be skipped")

    monkeypatch.setattr(refresh, "finalize_layer_b_episode", fail_finalize)

    summary = refresh.refresh_run(run_dir=run_dir, repo_root=tmp_path)

    assert summary["n_changed"] == 0


def test_refresh_dry_run_does_not_call_finalizer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    _write_jsonl(
        run_dir / "episode_records.jsonl",
        [
            {
                "condition_id": "cond",
                "runner": "opencode",
                "model_target": "model",
                "br_mode": "with_br_required",
                "status": "succeeded",
                "meta_pmids": ["1"],
                "producer_output_dir": str(run_dir / "producer" / "cond"),
            }
        ],
    )

    def fail_finalize(**_: object) -> dict[str, object]:
        raise AssertionError("dry-run must not mutate artifacts through finalizer")

    monkeypatch.setattr(refresh, "finalize_layer_b_episode", fail_finalize)

    summary = refresh.refresh_run(run_dir=run_dir, repo_root=tmp_path, dry_run=True)

    assert summary["dry_run"] is True
    assert summary["n_refreshable"] == 1
    assert not (run_dir / "episode_records.jsonl.pre_layer_b_refresh").exists()
