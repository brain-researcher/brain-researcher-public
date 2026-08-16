"""Golden checks for the public HCP workflow-search replay pack."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "reproducibility" / "hcp_workflow_search"


def test_hcp_workflow_search_replay_preserves_recorded_accounting(tmp_path: Path) -> None:
    output = tmp_path / "figure5.svg"
    completed = subprocess.run(
        [
            sys.executable,
            str(PACK / "scripts" / "replay_and_validate.py"),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)

    assert report["scope"] == "derived_artifact_replay_only"
    assert report["search"] == {"parent": 116, "completed": 104, "incomplete": 12}
    assert report["search_headline"] == {
        "initial_maximum_r": 0.37263729808107476,
        "expanded_scored": 84,
        "expanded_above_initial_maximum": 27,
        "expanded_maximum_r": 0.48710921135174756,
    }
    assert report["cohort_ledger"] == {
        "eligible_hcp_cohort_n": 326,
        "search": {"row_count": 245, "family_count": 244},
        "matched_comparison": {"row_count": 244, "family_count": 243},
        "separate_internal_holdout_row_count": 81,
    }
    assert report["selection"] == {
        "automatic_champion_selected": False,
        "analysis_frozen_before_matched_comparison": True,
    }
    assert report["cognition"] == {
        "directional_wins": "10/10",
        "median_delta_r": 0.09827205188739016,
        "conditional_one_sided_p": 0.006,
    }
    assert report["transfer"] == {
        "directional_wins": "37/40",
        "weak_fwer_status": "unsupported",
    }
    assert report["all_outcomes"] == {"directional_wins": "47/50"}
    assert report["positive_median_selected_r2"] == ["Cognition", "Tobacco Use"]
    assert output.exists()
    assert "<svg" in output.read_text(encoding="utf-8")


def test_hcp_workflow_search_uses_stage_level_public_provenance() -> None:
    summary = json.loads((PACK / "data" / "study_summary.json").read_text(encoding="utf-8"))
    closure = summary["producer_closure"]

    assert closure["historical_producing_code"] == {
        "publicly_resolvable": False,
        "shipped_in_public_pack": False,
        "stages": [
            "MVE100 expansion",
            "12-slot recovery",
            "R2 Cognition paired inference",
            "R3 transfer",
        ],
        "status": "recovered_in_private_history",
    }
    assert "historical_code_refs" not in closure
    assert "commit" not in json.dumps(closure)
    assert "branch" not in json.dumps(closure)

    reference_surfaces = [
        PACK / "README.md",
        PACK / "provenance_card.md",
        PACK / "data" / "study_summary.json",
        PACK / "scripts" / "replay_and_validate.py",
    ]
    for path in reference_surfaces:
        text = path.read_text(encoding="utf-8")
        assert "codex/" not in text
        assert re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", text) is None

    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    manifest_provenance = "\n".join(manifest["source"]["provenance"])
    assert "codex/" not in manifest_provenance
    assert re.search(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", manifest_provenance) is None
