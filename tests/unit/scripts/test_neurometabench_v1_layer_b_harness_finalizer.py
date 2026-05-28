from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.neurometabench_v1.layer_b_harness_finalizer import (
    finalize_layer_b_episode,
    _coordinate_parseable,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_layer_b_finalizer_injects_provenance_report_and_preflight(
    tmp_path: Path,
) -> None:
    producer = tmp_path / "producer" / "cond"
    case_dir = producer / "layer_b_123"
    input_root = tmp_path / "inputs"
    (input_root / "layer_b_123").mkdir(parents=True)
    (input_root / "layer_b_123" / "input_manifest.json").write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "nimads_assets": {"raw_jsons": ["/tmp/source.json"]},
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "12345678", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(
        case_dir / "included_studies.csv",
        [{"study_id": "12345678", "study_pmid": "12345678"}],
    )
    (case_dir / "metrics.json").parent.mkdir(parents=True, exist_ok=True)
    (case_dir / "metrics.json").write_text("{}", encoding="utf-8")
    (case_dir / "provenance_manifest.json").write_text(
        json.dumps(
            {
                "br_calls_made": [
                    {
                        "tool": "mcp__brain_researcher_prod__kg_search_nodes",
                        "purpose": "audit PMID 12345678",
                        "result": "PMID 12345678",
                        "changed_bundle": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = finalize_layer_b_episode(
        producer_output_dir=producer,
        input_root=input_root,
        meta_pmids=["123"],
        condition_metadata={
            "condition_id": "cond",
            "runner": "codex_cli",
            "model_target": "gpt-5.5",
            "br_mode": "with_br_required",
        },
        command=["codex", "exec"],
        started_at="start",
        ended_at="end",
        repo_root=tmp_path,
        episode_dir=None,
    )

    provenance = json.loads(
        (case_dir / "provenance_manifest.json").read_text(encoding="utf-8")
    )
    preflight = json.loads(
        (case_dir / "artifact_preflight.json").read_text(encoding="utf-8")
    )
    assert provenance["condition_id"] == "cond"
    assert provenance["source_assets_used"] == ["/tmp/source.json"]
    assert provenance["harness_finalizer"]["applied"] is True
    assert (case_dir / "provenance_manifest.agent_raw.json").exists()
    assert (case_dir / "spatial_report.md").exists()
    assert preflight["checks"]["provenance_required_fields"] is True
    assert preflight["checks"]["coordinate_table_parseable"] is True
    assert summary["cases"][0]["br_required_pass"] is True
    assert summary["all_br_required_pass"] is True


def test_layer_b_finalizer_appends_contract_report_to_incomplete_agent_report(
    tmp_path: Path,
) -> None:
    producer = tmp_path / "producer" / "cond"
    case_dir = producer / "layer_b_123"
    input_root = tmp_path / "inputs"
    (input_root / "layer_b_123").mkdir(parents=True)
    (input_root / "layer_b_123" / "input_manifest.json").write_text(
        json.dumps({"case_id": "neurometabench:123", "meta_pmid": "123"}),
        encoding="utf-8",
    )
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "s1", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
    (case_dir / "ale_maps").mkdir(parents=True)
    (case_dir / "ale_maps" / "123_z.nii.gz").write_bytes(b"not-a-real-nifti")
    (case_dir / "spatial_report.md").write_text(
        "Agent report: ALE completed.", encoding="utf-8"
    )

    finalize_layer_b_episode(
        producer_output_dir=producer,
        input_root=input_root,
        meta_pmids=["123"],
        condition_metadata={
            "condition_id": "cond",
            "runner": "opencode",
            "model_target": "model",
            "br_mode": "without_br",
        },
        command=["opencode", "run"],
        started_at="start",
        ended_at="end",
        repo_root=tmp_path,
        episode_dir=None,
    )

    report = (case_dir / "spatial_report.md").read_text(encoding="utf-8")
    preflight = json.loads((case_dir / "artifact_preflight.json").read_text(encoding="utf-8"))
    assert (case_dir / "spatial_report.agent_raw.md").exists()
    assert "Agent report: ALE completed." in report
    assert "## Harness Contract Addendum" in report
    assert "123_z.nii.gz" in report
    assert preflight["checks"]["report_mentions_coordinate_count"] is True
    assert preflight["checks"]["report_mentions_study_count"] is True
    assert preflight["checks"]["report_mentions_map_output_path"] is True


def test_layer_b_finalizer_flags_degraded_fallback_map_evidence(
    tmp_path: Path,
) -> None:
    producer = tmp_path / "producer" / "cond"
    case_dir = producer / "layer_b_123"
    input_root = tmp_path / "inputs"
    (input_root / "layer_b_123").mkdir(parents=True)
    (input_root / "layer_b_123" / "input_manifest.json").write_text(
        json.dumps({"case_id": "neurometabench:123", "meta_pmid": "123"}),
        encoding="utf-8",
    )
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "s1", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
    (case_dir / "ale_maps").mkdir(parents=True)
    (case_dir / "ale_maps" / "123_z.nii.gz").write_bytes(b"not-a-real-nifti")
    (case_dir / "metrics.json").write_text(
        json.dumps(
            {
                "map_generation_status": "degraded_fallback",
                "map_generation_reason": (
                    "NiMARE ALE failed with tuple index out of range; "
                    "fell back to Gaussian KDE"
                ),
            }
        ),
        encoding="utf-8",
    )

    summary = finalize_layer_b_episode(
        producer_output_dir=producer,
        input_root=input_root,
        meta_pmids=["123"],
        condition_metadata={
            "condition_id": "cond",
            "runner": "opencode",
            "model_target": "model",
            "br_mode": "without_br",
        },
        command=["opencode", "run"],
        started_at="start",
        ended_at="end",
        repo_root=tmp_path,
        episode_dir=None,
    )

    preflight = json.loads((case_dir / "artifact_preflight.json").read_text(encoding="utf-8"))
    assert preflight["checks"]["ale_map_not_degraded_fallback"] is False
    assert "ale_map_not_degraded_fallback" in preflight["failure_reasons"]
    assert preflight["fallback_map_check"]["detected"] is True
    assert summary["all_preflight_pass"] is False


def test_layer_b_finalizer_ignores_prompt_fallback_terms_in_command(
    tmp_path: Path,
) -> None:
    producer = tmp_path / "producer" / "cond"
    case_dir = producer / "layer_b_123"
    input_root = tmp_path / "inputs"
    (input_root / "layer_b_123").mkdir(parents=True)
    (input_root / "layer_b_123" / "input_manifest.json").write_text(
        json.dumps({"case_id": "neurometabench:123", "meta_pmid": "123"}),
        encoding="utf-8",
    )
    _write_csv(
        case_dir / "coordinate_table.csv",
        [{"study_id": "s1", "analysis_id": "a1", "x": "1", "y": "2", "z": "3"}],
    )
    _write_csv(case_dir / "included_studies.csv", [{"study_id": "s1"}])
    (case_dir / "metrics.json").parent.mkdir(parents=True, exist_ok=True)
    (case_dir / "metrics.json").write_text(
        json.dumps(
            {
                "degraded_fallback_map": False,
                "fallback_map_generated": False,
                "map_generation_status": "nimare_ale_generated",
            }
        ),
        encoding="utf-8",
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

    finalize_layer_b_episode(
        producer_output_dir=producer,
        input_root=input_root,
        meta_pmids=["123"],
        condition_metadata={
            "condition_id": "cond",
            "runner": "opencode",
            "model_target": "model",
            "br_mode": "without_br",
        },
        command=[
            "opencode",
            "run",
            "If ALE fails, mark map_generation_status=degraded_fallback; "
            "do not write a synthetic map or hand-rolled ALE.",
        ],
        started_at="start",
        ended_at="end",
        repo_root=tmp_path,
        episode_dir=None,
    )

    preflight = json.loads((case_dir / "artifact_preflight.json").read_text(encoding="utf-8"))
    assert preflight["checks"]["ale_map_not_degraded_fallback"] is True
    assert preflight["fallback_map_check"]["detected"] is False


def test_layer_b_finalizer_accepts_mni_suffix_coordinate_aliases(
    tmp_path: Path,
) -> None:
    coordinate_table = tmp_path / "coordinate_table.csv"
    _write_csv(
        coordinate_table,
        [
            {
                "study_id": "study-1",
                "x_tal": "8",
                "y_tal": "9",
                "z_tal": "10",
                "x_mni": "1.5",
                "y_mni": "-2",
                "z_mni": "3",
            }
        ],
    )

    assert _coordinate_parseable(coordinate_table) is True
