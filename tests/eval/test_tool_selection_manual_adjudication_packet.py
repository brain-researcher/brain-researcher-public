"""Tests for tool-selection manual adjudication packet diagnostics."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "build_tool_selection_manual_adjudication_packet.py"
SPEC = importlib.util.spec_from_file_location("build_tool_selection_manual_adjudication_packet", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
packet = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = packet
SPEC.loader.exec_module(packet)


def test_list_dataset_assets_validate_bids_claims_validation() -> None:
    action = {
        "index": 4,
        "action_type": "recipe_tool",
        "target": "list_dataset_assets",
        "raw": {
            "input": {
                "tool_id": "list_dataset_assets",
                "params": {"validate_bids": True, "use_pybids_layout": True},
            }
        },
    }

    evidence = packet.claimed_capability_evidence(
        action, {"dataset_access", "bids_validation"}
    )

    assert {item["capability"] for item in evidence} == {
        "dataset_access",
        "bids_validation",
    }


def test_workflow_task_glm_group_claims_first_level_glm_stack() -> None:
    action = {
        "index": 4,
        "action_type": "recipe_tool",
        "target": "workflow_task_glm_group",
        "raw": {"input": {"tool_id": "workflow_task_glm_group"}},
    }

    evidence = packet.claimed_capability_evidence(
        action, {"first_level_glm", "hrf_modeling", "contrast_estimation"}
    )

    assert {item["capability"] for item in evidence} == {
        "first_level_glm",
        "hrf_modeling",
        "contrast_estimation",
    }


def test_local_commands_claim_common_without_br_capabilities() -> None:
    actions = [
        {
            "index": 1,
            "action_type": "bash_cmd",
            "target": "randomise -i input.nii.gz -o out -d design.mat -t design.con -n 10000 -T",
        },
        {
            "index": 2,
            "action_type": "bash_cmd",
            "target": "python -c 'from neuroHarmonize import harmonizationLearn'",
        },
        {
            "index": 3,
            "action_type": "py_import",
            "target": "neuroHarmonize",
        },
        {
            "index": 4,
            "action_type": "bash_cmd",
            "target": "mriqc /data/haxby /out/mriqc group -m bold T1w",
        },
    ]

    claims, tools, evidence = packet.claim_summary(
        actions,
        {
            "permutation_inference",
            "multiple_comparison_control",
            "site_harmonization",
            "image_quality_metrics",
            "qc_reporting",
        },
    )

    assert claims == {
        "permutation_inference",
        "multiple_comparison_control",
        "site_harmonization",
        "image_quality_metrics",
        "qc_reporting",
    }
    assert "randomise -i input.nii.gz -o out -d design.mat -t design.con -n 10000 -T" in tools
    assert len(evidence) == 5


def test_bare_python_import_does_not_claim_full_recipe_contract() -> None:
    action = {"index": 1, "action_type": "py_import", "target": "mriqc"}

    evidence = packet.claimed_capability_evidence(
        action, {"image_quality_metrics", "qc_reporting"}
    )

    assert {item["capability"] for item in evidence} == {"image_quality_metrics"}


def test_build_packet_rows_adds_claim_gap_columns(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    episode_dir = run_dir / "episodes" / "claude_code_opus47_with_br" / "DATA-001"
    episode_dir.mkdir(parents=True)
    tasks_path = tmp_path / "tasks.jsonl"
    tasks_path.write_text(
        json.dumps(
            {
                "task_id": "DATA-001",
                "query": "Fetch and validate BIDS structure",
                "category": "Data Management",
                "template_id": "bids_dataset_access",
                "required_capabilities": ["dataset_access", "bids_validation"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "condition_id": "claude_code_opus47_with_br",
                        "task_id": "DATA-001",
                        "status": "captured_stop",
                        "parsed_action_count": 2,
                        "non_neutral_action_count": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "score_rows.jsonl").write_text(
        json.dumps(
            {
                "condition": "claude_code_opus47_with_br",
                "task_id": "DATA-001",
                "required_capabilities": ["dataset_access", "bids_validation"],
                "capabilities_covered": ["dataset_access"],
                "missing_capabilities": ["bids_validation"],
                "selected_actions": [
                    {"index": 1, "action_type": "mcp_tool", "target": "dataset_get_resources"},
                    {"index": 2, "action_type": "recipe_tool", "target": "list_dataset_assets"},
                ],
                "capability_score": 0.5,
                "correct": False,
                "no_action": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (episode_dir / "parsed_actions.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "index": 1,
                        "action_type": "mcp_tool",
                        "target": "dataset_get_resources",
                    }
                ),
                json.dumps(
                    {
                        "index": 2,
                        "action_type": "recipe_tool",
                        "target": "list_dataset_assets",
                        "raw": {
                            "input": {
                                "tool_id": "list_dataset_assets",
                                "params": {"validate_bids": True},
                            }
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (episode_dir / "stdout.jsonl").write_text("", encoding="utf-8")

    rows = packet.build_packet_rows(run_dir, tasks_path)

    assert len(rows) == 1
    row = rows[0]
    assert row["parser_detected_capabilities"] == "dataset_access"
    assert row["claimed_capabilities_selected"] == "bids_validation;dataset_access"
    assert row["missing_but_claimed_selected"] == "bids_validation"
    assert row["adjudication_cluster_hint"] == "with_br_recipe_or_tool_claim_gap"
