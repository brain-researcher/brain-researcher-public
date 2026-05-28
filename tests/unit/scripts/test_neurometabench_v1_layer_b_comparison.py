from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.neurometabench_v1 import run_layer_b_comparison as module


def test_layer_b_contract_lists_diagnostic_reporting_keys() -> None:
    contract = module.layer_b_contract()

    keys = contract["diagnostic_report_keys"]
    assert "br_reconciliation_gain" in keys
    assert "identifier_coverage_delta" in keys
    assert "provenance_enrichment_delta" in keys
    assert "normalized_vs_raw_recovery" in keys
    assert "degraded_fallback_map" in keys
    assert "br_reconciliation_anchor_pass" in keys
    assert "br_reconciliation_anchors.json" in contract["br_required_case_artifacts"]
    anchor_contract = contract["br_reconciliation_anchor_contract"]
    assert (
        anchor_contract["recommended_anchor_shape"]["target_artifact"]
        == "spatial_report.md"
    )
    assert anchor_contract["recommended_anchor_shape"]["target_field"] == "study_pmid"
    assert anchor_contract["recommended_anchor_shape"]["changed_bundle"] is False
    assert "exact short value" in anchor_contract["canonical_value_rule"]
    assert "audit-only" in anchor_contract["changed_bundle_rule"]
    assert "conservative" in anchor_contract["safe_reproduction_table_write_policy"]
    assert "do not split, merge, rename" in anchor_contract["science_table_guardrail"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_nifti(path: Path) -> None:
    nib = pytest.importorskip("nibabel")
    np = pytest.importorskip("numpy")

    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.arange(27, dtype=float).reshape((3, 3, 3))
    image = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(image, str(path))


def test_layer_b_comparison_summarizes_metrics_artifacts(tmp_path: Path) -> None:
    condition_dir = tmp_path / "pure_nimare"
    case_dir = condition_dir / "layer_b_123_reward"
    map_path = case_dir / "ale_maps" / "123_z.nii.gz"
    map_path.parent.mkdir(parents=True)
    map_path.write_bytes(b"not-a-real-nifti")
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"x": "1", "y": "2", "z": "3"}, {"x": "4", "y": "5", "z": "6"}],
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "s1"}, {"study_id": "s2"}, {"study_id": "s3"}],
    )
    _write_json(case_dir / "provenance_manifest.json", {"method": {"ale_engine": "nimare"}})
    _write_json(
        case_dir / "metrics.json",
        {
            "case_id": "neurometabench:123",
            "meta_pmid": "123",
            "topic": "Reward",
            "project_key": "reward",
            "n_coordinate_rows": 2,
            "n_nimads_studies": 3,
            "ale": {
                "map_paths": {
                    "z": "/tmp/stale/layer_b_123_reward/ale_maps/123_z.nii.gz"
                }
            },
            "split_half": {
                "status": "computed",
                "z_map_metrics": {
                    "pearson_union_positive": 0.75,
                    "dice_top5_positive": 0.4,
                },
            },
            "outputs": {
                "coordinate_table": "/tmp/stale/layer_b_123_reward/coordinate_table.csv",
                "included_studies": "/tmp/stale/layer_b_123_reward/included_studies.csv",
                "provenance_manifest": (
                    "/tmp/stale/layer_b_123_reward/provenance_manifest.json"
                ),
                "metrics": "/tmp/stale/layer_b_123_reward/metrics.json",
                "ale_maps_dir": "/tmp/stale/layer_b_123_reward/ale_maps",
            },
        },
    )

    output_dir = tmp_path / "out"
    result = module.run_comparison(
        [module.ConditionInput("pure_nimare", condition_dir)],
        output_dir,
    )

    written = json.loads(
        (output_dir / "layer_b_comparison_summary.json").read_text(encoding="utf-8")
    )
    assert written == result
    condition = written["conditions"][0]
    case = condition["cases"][0]
    assert condition["status_counts"] == {"evaluable": 1, "degraded": 0, "failed": 0}
    assert case["status"] == "evaluable"
    assert case["map_generated"] is True
    assert case["n_coordinate_rows"] == 2
    assert case["n_included_studies"] == 3
    assert case["split_half_status"] == "computed"
    assert case["spatial_metrics"]["split_half_z_map"]["pearson_union_positive"] == 0.75
    assert case["required_artifacts"]["provenance_manifest"]["present"] is True
    assert case["artifact_checksums"]["coordinate_table"]
    assert case["artifact_checksums"]["ale_maps"]["123_z.nii.gz"]
    assert condition["metric_layers"]["deterministic_artifact"][
        "map_generation_rate"
    ] == 1.0
    assert condition["metric_layers"]["br_relevant_audit"][
        "mean_local_identifier_coverage"
    ] == 1.0

    md = (output_dir / "layer_b_comparison_summary.md").read_text(encoding="utf-8")
    assert "pure_nimare" in md
    assert "neurometabench:123" in md
    assert "## Metric Layers" in md
    assert "| pure_nimare | evaluable | 1 | 1 | 0 | 0 | 1 | 2 | 3 |" in md


def test_layer_b_comparison_marks_fallback_map_as_degraded(
    tmp_path: Path,
) -> None:
    condition_dir = tmp_path / "agent"
    case_dir = condition_dir / "layer_b_123_reward"
    _write_nifti(case_dir / "ale_maps" / "123_z.nii.gz")
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "s1", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
    _write_json(case_dir / "provenance_manifest.json", {"method": "agent"})
    _write_json(
        case_dir / "metrics.json",
        {
            "case_id": "neurometabench:123",
            "meta_pmid": "123",
            "n_coordinate_rows": 1,
            "n_included_studies": 1,
            "map_generation_status": "degraded_fallback",
            "map_generation_reason": "NiMARE ALE failed; fell back to Gaussian KDE",
        },
    )

    result = module.run_comparison(
        [module.ConditionInput("agent", condition_dir)],
        tmp_path / "out",
    )

    condition = result["conditions"][0]
    case = condition["cases"][0]
    assert case["map_generated"] is True
    assert case["degraded_fallback_map"] is True
    assert case["status"] == "degraded"
    assert "degraded fallback ALE map evidence" in case["status_reasons"]
    assert case["metric_layers"]["metric_contract"]["degraded_fallback_map"][
        "value"
    ] is True
    assert condition["status_counts"] == {"evaluable": 0, "degraded": 1, "failed": 0}


def test_layer_b_comparison_ignores_prompt_fallback_terms_in_provenance_command(
    tmp_path: Path,
) -> None:
    condition_dir = tmp_path / "agent"
    case_dir = condition_dir / "layer_b_123_reward"
    _write_nifti(case_dir / "ale_maps" / "123_z.nii.gz")
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "s1", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "commands_executed": [
                "opencode run # If ALE fails, mark degraded_fallback; "
                "do not write a synthetic map or hand-rolled ALE."
            ]
        },
    )
    _write_json(
        case_dir / "metrics.json",
        {
            "case_id": "neurometabench:123",
            "degraded_fallback_map": False,
            "fallback_map_generated": False,
            "map_generation_status": "nimare_ale_generated",
            "meta_pmid": "123",
            "n_coordinate_rows": 1,
            "n_included_studies": 1,
        },
    )
    (case_dir / "spatial_report.md").write_text(
        "\n".join(
            [
                "Degraded fallback: False",
                "Degraded fallback map: `False`",
                "degraded_fallback_map=false",
                "Preflight issue name only: ale_map_not_degraded_fallback",
                "Reproduction uses repository NiMARE code with no hand-rolled ALE.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.run_comparison(
        [module.ConditionInput("agent", condition_dir)],
        tmp_path / "out",
    )

    case = result["conditions"][0]["cases"][0]
    assert case["map_generated"] is True
    assert case["degraded_fallback_map"] is False
    assert case["status"] == "evaluable"


def test_layer_b_comparison_adds_exact_control_match_fields(tmp_path: Path) -> None:
    pure_dir = tmp_path / "pure_nimare" / "layer_b_123_reward"
    agent_dir = tmp_path / "agent" / "layer_b_123_reward"
    for case_dir in [pure_dir, agent_dir]:
        (case_dir / "ale_maps").mkdir(parents=True)
        (case_dir / "ale_maps" / "123_z.nii.gz").write_bytes(b"same-map")
        _write_csv(case_dir / "coordinate_table.csv", [{"x": "1", "y": "2", "z": "3"}])
        _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
        _write_json(case_dir / "provenance_manifest.json", {"ok": True})
        _write_json(
            case_dir / "metrics.json",
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "n_coordinate_rows": 1,
                "n_included_studies": 1,
            },
        )

    output_dir = tmp_path / "out"
    result = module.run_comparison(
        [
            module.ConditionInput("pure_nimare", tmp_path / "pure_nimare"),
            module.ConditionInput("agent", tmp_path / "agent"),
        ],
        output_dir,
    )

    agent_case = result["conditions"][1]["cases"][0]
    control = agent_case["control_comparison"]
    agent_layers = result["conditions"][1]["metric_layers"]
    contract = agent_case["metric_layers"]["metric_contract"]
    assert control["coordinate_rows_delta"] == 0
    assert control["included_studies_delta"] == 0
    assert control["coordinate_table_exact_match"] is True
    assert control["all_maps_exact_match"] is True
    assert control["coordinate_extraction_agreement"]["f1"] == 1.0
    assert control["coordinate_canonical_f1"]["f1"] == 1.0
    assert control["local_study_set_f1"]["f1"] == 1.0
    assert contract["coordinate_extraction_agreement"]["f1"] == 1.0
    assert contract["coordinate_canonical_f1"]["f1"] == 1.0
    assert contract["local_study_set_f1"]["f1"] == 1.0
    assert contract["ale_map_spatial_correlation"]["reason"].startswith(
        "map_load_failed"
    )
    assert agent_layers["deterministic_artifact"][
        "control_map_exact_match_rate"
    ] == 1.0
    assert agent_layers["deterministic_artifact"][
        "control_coordinate_table_exact_match_rate"
    ] == 1.0
    assert result["case_index"][0]["conditions"]["agent"][
        "control_all_maps_exact_match"
    ] is True
    assert result["case_index"][0]["conditions"]["agent"]["metric_layers"][
        "deterministic_artifact"
    ]["control_comparison"]["all_maps_exact_match"] is True

    md = (output_dir / "layer_b_comparison_summary.md").read_text(encoding="utf-8")
    assert "| agent | neurometabench:123 | evaluable | yes | 1 | 1 |  |  |  | True | True | yes |" in md


def test_layer_b_comparison_accepts_coordinate_alias_fields(tmp_path: Path) -> None:
    pure_dir = tmp_path / "pure_nimare" / "layer_b_123_reward"
    agent_dir = tmp_path / "agent" / "layer_b_123_reward"
    for case_dir in [pure_dir, agent_dir]:
        (case_dir / "ale_maps").mkdir(parents=True)
        (case_dir / "ale_maps" / "123_z.nii.gz").write_bytes(b"same-map")
        _write_csv(case_dir / "included_studies.csv", [{"study_id": "12345678"}])
        _write_json(case_dir / "provenance_manifest.json", {"ok": True})
        _write_json(
            case_dir / "metrics.json",
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "n_coordinate_rows": 1,
                "n_included_studies": 1,
            },
        )
    _write_csv(
        pure_dir / "coordinate_table.csv",
        [
            {
                "study_id": "12345678",
                "analysis_id": "12345678_1",
                "x": "5.18",
                "y": "68.07",
                "z": "25.07",
                "space": "MNI",
            }
        ],
    )
    _write_csv(
        agent_dir / "coordinate_table.csv",
        [
            {
                "study_id": "12345678",
                "contrast_id": "12345678_1",
                "x": "5.18",
                "y": "68.07",
                "z": "25.07",
                "source_space": "mni152_2mm",
            }
        ],
    )

    result = module.run_comparison(
        [
            module.ConditionInput("pure_nimare", tmp_path / "pure_nimare"),
            module.ConditionInput("agent", tmp_path / "agent"),
        ],
        tmp_path / "out",
    )

    agreement = result["conditions"][1]["cases"][0]["control_comparison"][
        "coordinate_extraction_agreement"
    ]
    assert agreement["f1"] == 1.0
    assert agreement["n_overlap"] == 1


def test_layer_b_local_study_ids_do_not_explode_source_aliases(
    tmp_path: Path,
) -> None:
    pure_dir = tmp_path / "pure_nimare" / "layer_b_123_reward"
    agent_dir = tmp_path / "agent" / "layer_b_123_reward"
    for case_dir in [pure_dir, agent_dir]:
        (case_dir / "ale_maps").mkdir(parents=True)
        (case_dir / "ale_maps" / "123_z.nii.gz").write_bytes(b"same-map")
        _write_csv(
            case_dir / "coordinate_table.csv",
            [
                {
                    "study_id": "s1",
                    "analysis_id": "a1",
                    "x": "1",
                    "y": "2",
                    "z": "3",
                    "space": "MNI",
                }
            ],
        )
        _write_json(case_dir / "provenance_manifest.json", {"ok": True})
        _write_json(
            case_dir / "metrics.json",
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "n_coordinate_rows": 1,
                "n_included_studies": 2,
            },
        )
    _write_csv(
        pure_dir / "included_studies.csv",
        [{"study_id": "s1"}, {"study_id": "s2"}],
    )
    _write_csv(
        agent_dir / "included_studies.csv",
        [
            {
                "study_id": "s1",
                "original_study_ids": "s1_alias_a; s1_alias_b",
                "source_study_ids": "source_s1_a source_s1_b",
            },
            {
                "study_id": "s2",
                "original_study_ids": "s2_alias_a|s2_alias_b",
                "source_study_ids": "source_s2_a,source_s2_b",
            },
        ],
    )

    result = module.run_comparison(
        [
            module.ConditionInput("pure_nimare", tmp_path / "pure_nimare"),
            module.ConditionInput("agent", tmp_path / "agent"),
        ],
        tmp_path / "out",
    )

    agreement = result["conditions"][1]["cases"][0]["control_comparison"][
        "local_study_set_f1"
    ]
    assert agreement["f1"] == 1.0
    assert agreement["n_pred"] == 2
    assert agreement["n_gold"] == 2


def test_layer_b_coordinate_strict_accepts_map_equivalent_tal_mni_transform(
    tmp_path: Path,
) -> None:
    pure_dir = tmp_path / "pure_nimare" / "layer_b_123_reward"
    agent_dir = tmp_path / "agent" / "layer_b_123_reward"
    for case_dir in [pure_dir, agent_dir]:
        _write_nifti(case_dir / "ale_maps" / "123_z.nii.gz")
        _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
        _write_json(case_dir / "provenance_manifest.json", {"ok": True})
        _write_json(
            case_dir / "metrics.json",
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "n_coordinate_rows": 1,
                "n_included_studies": 1,
            },
        )
    _write_csv(
        pure_dir / "coordinate_table.csv",
        [
            {
                "study_id": "s1",
                "analysis_id": "reward",
                "x": "1",
                "y": "2",
                "z": "3",
                "space": "Talairach",
            }
        ],
    )
    _write_csv(
        agent_dir / "coordinate_table.csv",
        [
            {
                "study_id": "s1",
                "analysis_id": "reward",
                "x": "2",
                "y": "4",
                "z": "6",
                "space": "MNI152",
            }
        ],
    )

    result = module.run_comparison(
        [
            module.ConditionInput("pure_nimare", tmp_path / "pure_nimare"),
            module.ConditionInput("agent", tmp_path / "agent"),
        ],
        tmp_path / "out",
    )

    agreement = result["conditions"][1]["cases"][0]["control_comparison"][
        "coordinate_canonical_f1"
    ]
    assert agreement["f1"] == 1.0
    assert agreement["raw_f1"] == 0.0
    assert agreement["reason"] == "spatial_map_equivalent_after_coordinate_transform"


def test_layer_b_comparison_includes_full_metric_contract_and_study_set_f1(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "agent" / "layer_b_123_reward"
    _write_csv(
        case_dir / "coordinate_table.csv",
        [
            {
                "study_id": "s1",
                "analysis_id": "a1",
                "x": "1",
                "y": "2",
                "z": "3",
                "space": "MNI",
            }
        ],
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "s1", "pmid": "10"}, {"study_id": "s2", "pmid": "30"}],
    )
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "condition_id": "agent",
            "runner": "codex_cli",
            "model_target": "gpt-5.5",
            "br_mode": "without_br",
            "source_assets_used": ["asset"],
            "commands_executed": ["cmd"],
            "start_timestamp": "start",
            "end_timestamp": "end",
            "repository_commit": "abc",
        },
    )
    _write_json(
        case_dir / "metrics.json",
        {
            "case_id": "neurometabench:123",
            "meta_pmid": "123",
            "n_coordinate_rows": 1,
            "n_included_studies": 2,
        },
    )
    (case_dir / "spatial_report.md").write_text(
        "ALE map used 1 coordinates from 2 studies.", encoding="utf-8"
    )
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps({"meta_pmid": "123", "gt_pmids": ["10", "20"]}) + "\n",
        encoding="utf-8",
    )

    result = module.run_comparison(
        [module.ConditionInput("agent", tmp_path / "agent")],
        tmp_path / "out",
        cases_path=cases_path,
    )

    contract = result["conditions"][0]["cases"][0]["metric_layers"]["metric_contract"]
    assert set(contract) == {
        "study_set_f1",
        "coordinate_extraction_agreement",
        "coordinate_canonical_f1",
        "local_study_set_f1",
        "map_generated",
        "degraded_fallback_map",
        "coordinate_rows",
        "study_rows",
        "exact_match_to_pure_nimare",
        "ale_map_spatial_correlation",
        "dice_top5",
        "pmid_study_reconciliation",
        "br_reconciliation_anchors",
        "provenance_completeness",
        "claim_consistency",
        "failure_diagnosis_quality",
    }
    assert contract["study_set_f1"]["precision"] == 0.5
    assert contract["study_set_f1"]["recall"] == 0.5
    assert contract["study_set_f1"]["f1"] == 0.5
    assert contract["map_generated"]["value"] is False
    assert contract["claim_consistency"]["score"] == 1.0


def test_layer_b_comparison_derives_study_pmids_from_numeric_study_ids(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "agent" / "layer_b_123_reward"
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "12345678", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [
            {
                "study_id": "12345678",
                "original_study_ids": "12345678-1|87654321-2",
                "sample_size_min": "12",
                "sample_size_max": "",
            },
            {
                "study_id": "23456789-1",
                "original_study_ids": "23456789-1",
                "sample_size_min": "",
                "sample_size_max": "20",
            },
        ],
    )
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "condition_id": "agent",
            "runner": "codex_cli",
            "model_target": "gpt-5.5",
            "br_mode": "without_br",
            "source_assets_used": ["asset"],
            "commands_executed": ["cmd"],
            "start_timestamp": "start",
            "end_timestamp": "end",
            "repository_commit": "abc",
        },
    )
    _write_json(
        case_dir / "metrics.json",
        {
            "case_id": "neurometabench:123",
            "meta_pmid": "123",
            "n_coordinate_rows": 1,
            "n_included_studies": 2,
        },
    )
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "meta_pmid": "123",
                "gt_pmids": ["12345678", "23456789", "99999999"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.run_comparison(
        [module.ConditionInput("agent", tmp_path / "agent")],
        tmp_path / "out",
        cases_path=cases_path,
    )

    case = result["conditions"][0]["cases"][0]
    contract = case["metric_layers"]["metric_contract"]
    reconciliation = contract["pmid_study_reconciliation"]
    assert contract["study_set_f1"]["n_pred"] == 3
    assert contract["study_set_f1"]["n_tp"] == 2
    assert contract["study_set_f1"]["recall"] == 2 / 3
    assert reconciliation["public_identifier_coverage"] == 1.0
    assert reconciliation["source_provenance_coverage"] == 1.0
    assert reconciliation["sample_size_coverage"] == 1.0


def test_layer_b_comparison_uses_summary_json_and_classifies_statuses(
    tmp_path: Path,
) -> None:
    degraded_dir = tmp_path / "coding_agent_only"
    _write_json(
        degraded_dir / "summary.json",
        {
            "cases": [
                {
                    "case_id": "neurometabench:456",
                    "meta_pmid": "456",
                    "n_coordinate_rows": 8,
                    "n_included_studies": 2,
                    "split_half_status": "skipped",
                }
            ]
        },
    )

    failed_case_dir = tmp_path / "br_assisted" / "layer_b_789_failed"
    _write_json(
        failed_case_dir / "metrics.json",
        {
            "case_id": "neurometabench:789",
            "meta_pmid": "789",
            "status": "failed",
            "error": "missing coordinate table",
        },
    )

    output_dir = tmp_path / "out"
    exit_code = module.main(
        [
            "--condition",
            f"coding_agent_only={degraded_dir}",
            f"br_assisted={tmp_path / 'br_assisted'}",
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "layer_b_comparison_summary.json").read_text(encoding="utf-8")
    )
    by_condition = {condition["name"]: condition for condition in summary["conditions"]}

    degraded_case = by_condition["coding_agent_only"]["cases"][0]
    assert degraded_case["status"] == "degraded"
    assert degraded_case["map_generated"] is False
    assert degraded_case["n_coordinate_rows"] == 8
    assert degraded_case["n_included_studies"] == 2
    assert by_condition["coding_agent_only"]["status_counts"] == {
        "evaluable": 0,
        "degraded": 1,
        "failed": 0,
    }

    failed_case = by_condition["br_assisted"]["cases"][0]
    assert failed_case["status"] == "failed"
    assert "reported status=failed" in failed_case["status_reasons"]
    assert by_condition["br_assisted"]["status_counts"] == {
        "evaluable": 0,
        "degraded": 0,
        "failed": 1,
    }

    md = (output_dir / "layer_b_comparison_summary.md").read_text(encoding="utf-8")
    assert "coding_agent_only" in md
    assert "br_assisted" in md
    assert "neurometabench:456" in md
    assert "neurometabench:789" in md


def test_layer_b_comparison_dedupes_numeric_case_id_summary_rows(
    tmp_path: Path,
) -> None:
    condition_dir = tmp_path / "agent"
    case_dir = condition_dir / "layer_b_123_reward"
    _write_json(
        condition_dir / "RUN_SUMMARY.json",
        {
            "cases": [
                {
                    "case_id": "123",
                    "meta_pmid": "123",
                    "output_dir": "layer_b_123_reward",
                    "n_coordinate_rows": 1,
                    "n_included_studies": 1,
                }
            ]
        },
    )
    _write_csv(case_dir / "coordinate_table.csv", [{"x": "1", "y": "2", "z": "3"}])
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
    _write_json(
        case_dir / "metrics.json",
        {
            "meta_pmid": "123",
            "n_coordinate_rows": 1,
            "n_included_studies": 1,
        },
    )

    result = module.run_comparison(
        [module.ConditionInput("agent", condition_dir)],
        tmp_path / "out",
    )

    condition = result["conditions"][0]
    assert condition["n_cases"] == 1
    assert condition["cases"][0]["case_id"] == "neurometabench:123"


def test_layer_b_comparison_can_run_normalizer_and_br_anchor_trace(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "agent" / "layer_b_123_reward"
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "12345678", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "12345678", "source_asset": "reward.json"}],
    )
    _write_json(
        case_dir / "provenance_manifest.json",
        {
            "br_calls_made": [
                {
                    "tool": "mcp__brain_researcher_prod__kg_search_nodes",
                    "purpose": "audit PMID 12345678",
                    "result": "PMID 12345678 came from reward.json",
                    "changed_bundle": True,
                }
            ]
        },
    )
    _write_json(
        case_dir / "br_reconciliation_anchors.json",
        {
            "anchors": [
                {
                    "target_artifact": "included_studies.csv",
                    "target_field": "study_pmid",
                    "canonical_value": "12345678",
                    "evidence_source": "BR MCP",
                    "evidence_summary": "PMID 12345678 came from reward.json",
                    "changed_bundle": True,
                }
            ]
        },
    )
    _write_json(
        case_dir / "metrics.json",
        {
            "case_id": "neurometabench:123",
            "meta_pmid": "123",
            "n_coordinate_rows": 1,
            "n_included_studies": 1,
        },
    )

    result = module.run_comparison(
        [module.ConditionInput("agent", tmp_path / "agent")],
        tmp_path / "out",
        normalize_artifacts=True,
        trace_br_anchors=True,
    )

    case = result["conditions"][0]["cases"][0]
    assert (case_dir / "normalized_artifacts" / "coordinate_table.normalized.csv").exists()
    assert (case_dir / "br_anchor_trace.json").exists()
    assert case["metric_layers"]["normalization"]["coordinate_table"][
        "coordinate_parseability"
    ] == 1.0
    assert case["metric_layers"]["br_relevant_audit"]["br_anchor_trace"][
        "br_effective_use_pass"
    ] is True
    assert case["metric_layers"]["metric_contract"]["br_reconciliation_anchors"][
        "pass"
    ] is True
    assert result["conditions"][0]["metric_layers"]["br_relevant_audit"][
        "total_br_calls"
    ] == 1
    assert result["postprocessing"] == {
        "normalize_artifacts": True,
        "trace_br_anchors": True,
    }
