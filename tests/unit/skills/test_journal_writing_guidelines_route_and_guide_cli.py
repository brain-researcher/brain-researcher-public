from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "journal-writing-guidelines" / "scripts" / "route_and_guide.py"


def test_route_and_guide_cli_returns_linked_outputs() -> None:
    idea = (
        "We propose a cross-subject fMRI alignment and denoising pipeline with strong baselines, "
        "ablation studies, motion confound controls, and open-source BIDS-compatible release."
    )

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--idea",
        idea,
        "--section",
        "abstract",
        "--top-k",
        "5",
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)

    assert payload["top_journal_id"]
    assert payload["top_journal"]
    assert payload["fit_summary"]

    assert payload["idea_fit_result"]["top_journal"]["journal_id"] == payload["top_journal_id"]
    assert payload["writing_guide_result"]["journal_id"] == payload["top_journal_id"]
    assert payload["figure_plan_result"]["journal_id"] == payload["top_journal_id"]

    assert "core_message" in payload["writing_guide_snapshot"]
    assert "narrative_goals" in payload["writing_guide_snapshot"]
    assert "figure_strategy" in payload["writing_guide_snapshot"]
    assert isinstance(payload["first_actions"], list)
    assert len(payload["first_actions"]) >= 1
