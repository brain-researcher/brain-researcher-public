from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.neurokg.etl.adapters.virtual_brain_adapter import VirtualBrainAdapter


def _write_report(sim_dir: Path, sim_id: str, task_id: str) -> None:
    structure = {
        "simulation": {
            "id": sim_id,
            "model": "wilson_cowan",
            "seeded_task_id": task_id,
            "metrics": {"fc_pearson": 0.5},
        },
        "region_activity": [{"region_id": "region:0", "mean_activity": 0.8}],
    }
    (sim_dir / "report.json").write_text(json.dumps(structure), encoding="utf-8")


def test_virtual_brain_adapter_fetches_latest(tmp_path: Path) -> None:
    sim_id = "sim:schaefer100:test"
    sim_folder = tmp_path / sim_id.replace(":", "_")
    sim_folder.mkdir(parents=True, exist_ok=True)
    _write_report(sim_folder, sim_id, "task:n-back")

    adapter = VirtualBrainAdapter(cache_dir=str(tmp_path))
    payload = adapter.fetch(latest=True)
    assert payload
    assert payload[0]["simulation"]["id"] == sim_id


def test_virtual_brain_adapter_fetches_specific_simulation(tmp_path: Path) -> None:
    sim_id = "sim:schaefer100:target"
    sim_folder = tmp_path / sim_id.replace(":", "_")
    sim_folder.mkdir(parents=True, exist_ok=True)
    _write_report(sim_folder, sim_id, "task:n-back")

    adapter = VirtualBrainAdapter(cache_dir=str(tmp_path))
    payload = adapter.fetch(simulation_ids=[sim_id])
    assert len(payload) == 1
    assert payload[0]["simulation"]["seeded_task_id"] == "task:n-back"
