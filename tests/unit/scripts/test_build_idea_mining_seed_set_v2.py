from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_idea_mining_seed_set_v2 as module


def test_build_idea_mining_seed_set_v2_materializes_seed_and_replay_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    exit_code = module.main(["--output-dir", str(output_dir)])
    assert exit_code == 0

    seed_rows = [
        json.loads(line)
        for line in (output_dir / "idea_mining_seed_set_v2.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(seed_rows) == len(module.SEED_ROWS)
    assert any(row["seed_id"] == "concept:amyloid" for row in seed_rows)
    assert any(row["seed_id"] == "task:response_inhibition" for row in seed_rows)
    assert any(row["seed_id"] == "concept:reward_learning" for row in seed_rows)
    assert not any(row["seed_id"] == "concept:working_memory" for row in seed_rows)

    replay_rows = [
        json.loads(line)
        for line in (output_dir / "idea_mining_replay_pack_v2_examples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(replay_rows) == len(module.SEED_ROWS) * 2
    assert {row["candidate_lane_mode"] for row in replay_rows} == {"broad", "strict"}

    summary = json.loads(
        (output_dir / "idea_mining_seed_set_v2_summary.json").read_text(encoding="utf-8")
    )
    assert summary["candidate_sensitive_total"] == 5
    assert summary["control_total"] == 3

    manifest = json.loads(
        (output_dir / "idea_mining_replay_pack_v2_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["replay_pack_id"] == "idea_mining_replay_pack_v2_20260314"
