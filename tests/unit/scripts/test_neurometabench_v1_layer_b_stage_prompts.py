from __future__ import annotations

from pathlib import Path


PROMPT_DIR = Path("benchmarks/neurometabench/prompts/layer_b_stages")


def test_layer_b_stage_prompt_contracts_exist() -> None:
    expected = {
        "b1_asset_audit.md": [
            "stage_b1_asset_audit.json",
            "route_classification",
            "br_required_preflight",
        ],
        "b3_coordinate_normalization.md": [
            "coordinate_table.csv",
            "normalization_manifest.json",
            "study_id,analysis_id,x,y,z,space",
        ],
        "b5_reconciliation.md": [
            "included_studies.csv",
            "pmid_study_reconciliation.json",
            "br_reconciliation_anchors.json",
            "br_required_reconciliation",
        ],
    }

    for filename, required_phrases in expected.items():
        text = (PROMPT_DIR / filename).read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in text
