from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_idea_mining_failure_taxonomy_pack as module


def test_build_idea_mining_failure_taxonomy_pack_materializes_expected_artifacts(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    exit_code = module.main(["--output-dir", str(output_dir)])
    assert exit_code == 0

    taxonomy = json.loads(
        (output_dir / "idea_mining_failure_taxonomy_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert taxonomy["schema_version"] == "idea-mining-failure-taxonomy-v1"
    assert taxonomy["cascade_rule"] == ["SC-1", "TA-1", "TD-1", "LV-1"]
    assert [row["taxonomy_id"] for row in taxonomy["layers"]] == [
        "SC-1",
        "TA-1",
        "TD-1",
        "LV-1",
    ]
    assert all(
        not ref.startswith("/")
        for row in taxonomy["layers"]
        for ref in row["code_refs"]
    )

    probes = [
        json.loads(line)
        for line in (
            output_dir / "idea_mining_failure_regression_probes_v1.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["probe_id"] for row in probes] == ["IMR-01", "IMR-02"]
    assert all(row["allow_zero_card"] is True for row in probes)
    assert probes[0]["label"] == "dmn_aging_probe"
    assert probes[1]["label"] == "visual_decoding_region_probe"
    assert any(
        role["role"] == "population_comparator"
        for role in probes[0]["query_role_terms_required"]
    )
    assert any(
        role["role"] == "region_scope"
        for role in probes[1]["query_role_terms_required"]
    )

    manifest = json.loads(
        (output_dir / "idea_mining_failure_regression_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["pack_id"] == "idea_mining_failure_regression_pack_v1_20260316"
    assert manifest["intended_surface"] == "workflow_hypothesis_candidate_cards"
    assert "template_family_rejection" in manifest["checks"]
    assert manifest["taxonomy_json"] == "idea_mining_failure_taxonomy_v1.json"
    assert manifest["probes_jsonl"] == "idea_mining_failure_regression_probes_v1.jsonl"

    summary = json.loads(
        (output_dir / "idea_mining_failure_regression_summary_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["taxonomy_layers_total"] == 4
    assert summary["probe_rows_total"] == 2
