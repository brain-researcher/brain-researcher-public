from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import run_claim_snapshot_v4_b2_conflict_hotload as module


def test_run_claim_snapshot_v4_b2_conflict_hotload_orchestrates_pipeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def _fake_expansion(argv: list[str]) -> int:
        calls.append(("expansion", list(argv)))
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "claim_snapshot_v4_b2_conflict_expansion_pack.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )
        (out_dir / "claim_snapshot_v4_b2_conflict_expansion_summary.json").write_text(
            "{}\n", encoding="utf-8"
        )
        return 0

    def _fake_task(argv: list[str]) -> int:
        calls.append(("task", list(argv)))
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (
            out_dir / "claim_snapshot_v4_b2_task_manifest.json"
        ).write_text(json.dumps({"artifacts": {"examples_jsonl": str(out_dir / "examples.jsonl")}}), encoding="utf-8")
        (out_dir / "claim_snapshot_v4_b2_task_summary.json").write_text("{}\n", encoding="utf-8")
        return 0

    def _fake_split(argv: list[str]) -> int:
        calls.append(("split", list(argv)))
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "claim_snapshot_v4_b2_split_manifest.json").write_text("{}\n", encoding="utf-8")
        (out_dir / "claim_snapshot_v4_b2_split_summary.json").write_text("{}\n", encoding="utf-8")
        return 0

    def _fake_baseline(argv: list[str]) -> int:
        calls.append(("baseline", list(argv)))
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "claim_snapshot_v4_b2_baseline_eval_summary.json").write_text(
            "{}\n", encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(module.expansion, "main", _fake_expansion)
    monkeypatch.setattr(module.task_builder, "main", _fake_task)
    monkeypatch.setattr(module.split_builder, "main", _fake_split)
    monkeypatch.setattr(module.baseline, "main", _fake_baseline)
    exclude_pack = tmp_path / "exclude.jsonl"
    exclude_pack.write_text("{}\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--target-id",
            "concept:attention",
            "--target-id",
            "concept:working_memory",
            "--run-label",
            "hotload_demo",
            "--eval-root",
            str(tmp_path / "eval"),
            "--exclude-pack-jsonl",
            str(exclude_pack),
        ]
    )
    assert exit_code == 0
    assert [name for name, _ in calls] == ["expansion", "task", "split", "baseline"]
    expansion_args = calls[0][1]
    assert "--exclude-pack-jsonl" in expansion_args
    assert expansion_args[expansion_args.index("--exclude-pack-jsonl") + 1] == str(
        exclude_pack.resolve()
    )
    run_summary = json.loads(
        (tmp_path / "eval" / "claim_snapshot_v4_b2_hotload" / "hotload_demo" / "run_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert run_summary["target_ids"] == ["concept:attention", "concept:working_memory"]
