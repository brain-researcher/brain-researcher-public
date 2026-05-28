from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from scripts.neurometabench_screening_pipeline import parse_screening_json
from scripts.neurometabench_v1.audit_nimads_assets import (
    run_audit as run_nimads_asset_audit,
)
from scripts.neurometabench_v1.br_screening_adapter import convert_br_screening_outputs
from scripts.neurometabench_v1.build_nimads_reproduction_manifest import build_manifest
from scripts.neurometabench_v1.criterion_alignment_judge import (
    judge_decision,
    judge_prediction_files,
)
from scripts.neurometabench_v1.evaluate_study_set import (
    build_closed_world_baseline_predictions,
    evaluate_prediction,
    evaluate_prediction_files,
    summarize,
)
from scripts.neurometabench_v1.export_cases import export_cases
from scripts.neurometabench_v1.layer_a_baselines import (
    build_layer_a_baseline_predictions,
    load_layer_a_candidate_pool,
)
from scripts.neurometabench_v1.neurosynth_baseline import (
    rank_case_pmids,
    select_neurosynth_terms,
)
from scripts.neurometabench_v1.neurovault_substrate_diagnostic import (
    run_diagnostic as run_neurovault_substrate_diagnostic,
)
from scripts.neurometabench_v1.retrieval_only import (
    build_br_llm_query,
    build_query_set,
    retrieval_diagnostic_row,
)
from scripts.neurometabench_v1.run_layer_a_batch import run_layer_a_batch
from scripts.neurometabench_v1.run_layer_a_experiment import run_layer_a_experiment
from scripts.neurometabench_v1.run_layer_c_diagnostics import run_layer_c_diagnostics
from scripts.neurometabench_v1.run_path_b_reproduction import (
    coordinate_rows,
    filter_studyset_by_analysis_ids,
    spatial_metrics,
    summarize_existing,
)
from scripts.neurometabench_v1.shared import (
    LAYER_C_DIAGNOSTIC_AUDIT,
    derive_year_cutoff,
    load_mixed_pool_candidates,
    read_jsonl,
    write_jsonl,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_export_cases_builds_normalized_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_csv(
        data_dir / "meta_datasets.csv",
        [
            {
                "inclusion_status": "Done",
                "pmid": "123",
                "year": "2022",
                "topic": "Reward",
                "first_author": "A",
                "number_of_studies": "2",
                "method": "ALE",
                "dates": "- 5/2020",
                "modality": "fMRI",
                "search": "reward fMRI",
                "additional_methods": "",
                "inclusion": "whole-brain reward studies",
                "exclusion": "ROI-only",
                "search_results_n": "100",
                "selected_n": "2",
                "analyses": "reward",
                "pmcid": "999",
                "data_contact": "",
            }
        ],
    )
    _write_csv(
        data_dir / "included_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "2", "doi": ""},
            {"meta_pmid": "123", "study_pmid": "1", "doi": ""},
        ],
    )
    _write_csv(
        data_dir / "all_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1", "status": "YES", "final_status": "YES"},
            {"meta_pmid": "123", "study_pmid": "2", "status": "YES", "final_status": "YES"},
            {"meta_pmid": "123", "study_pmid": "3", "status": "NO", "final_status": "NO"},
        ],
    )
    output = tmp_path / "cases.jsonl"

    summary = export_cases(data_dir, output)
    rows = read_jsonl(output)

    assert summary["n_cases"] == 1
    assert rows[0]["case_id"] == "neurometabench:123"
    assert rows[0]["year_cutoff"] == 2020
    assert rows[0]["gt_pmids"] == ["1", "2"]
    assert rows[0]["route"] == "pmc_fulltext"
    assert rows[0]["task_type"] == "screening_with_justification"
    assert rows[0]["primary_task_layer"] == "layer_a_screening_with_justification"
    assert LAYER_C_DIAGNOSTIC_AUDIT in rows[0]["task_layers"]
    assert rows[0]["layer_c_diagnostic_contract"]["headline_score"] is False
    assert summary["task_layers"][LAYER_C_DIAGNOSTIC_AUDIT] == 1
    assert rows[0]["screening_criteria"][0]["criterion_id"]


def test_year_cutoff_falls_back_to_search_text() -> None:
    row = {
        "year": "2022",
        "dates": "",
        "search": "MRI studies reporting structural alterations from 2002 to 2020",
        "additional_methods": "",
    }

    assert derive_year_cutoff(row) == 2020


def test_evaluate_prediction_reports_absolute_and_corpus_normalized_metrics() -> None:
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Reward",
        "route": "pmc_fulltext",
        "gt_pmids": ["1", "2", "3"],
    }
    prediction = {
        "system": "test_system",
        "ranked_pmids": ["2", "4", "3"],
        "predicted_pmids": ["2", "4"],
        "corpus_name": "toy",
    }
    row = evaluate_prediction(case, prediction, corpus_pmids={"2", "3"})

    assert row["precision"] == pytest.approx(0.5)
    assert row["recall"] == pytest.approx(1 / 3)
    assert row["candidate_recall"] == pytest.approx(2 / 3)
    assert row["corpus_ceiling"] == pytest.approx(2 / 3)
    assert row["coverage_normalized_recall"] == pytest.approx(0.5)
    assert row["coverage_normalized_average_precision"] == pytest.approx((1 / 1 + 2 / 3) / 2)


def test_summarize_micro_and_macro_metrics() -> None:
    rows = [
        {
            "system": "s",
            "n_gt": 2,
            "n_predicted": 2,
            "n_candidate_tp": 2,
            "n_tp": 1,
            "candidate_recall": 1.0,
            "precision": 0.5,
            "recall": 0.5,
            "f1": 0.5,
            "average_precision": 0.5,
            "has_known_corpus": True,
            "n_gt_in_corpus": 1,
            "corpus_ceiling": 0.5,
            "coverage_normalized_recall": 1.0,
            "coverage_normalized_average_precision": 1.0,
        },
        {
            "system": "s",
            "n_gt": 2,
            "n_predicted": 1,
            "n_candidate_tp": 1,
            "n_tp": 1,
            "candidate_recall": 0.5,
            "precision": 1.0,
            "recall": 0.5,
            "f1": 2 / 3,
            "average_precision": 1.0,
            "has_known_corpus": True,
            "n_gt_in_corpus": 2,
            "corpus_ceiling": 1.0,
            "coverage_normalized_recall": 0.5,
            "coverage_normalized_average_precision": 0.5,
        },
    ]
    summary = summarize(rows)["systems"]["s"]

    assert summary["macro"]["recall"] == pytest.approx(0.5)
    assert summary["micro"]["precision"] == pytest.approx(2 / 3)
    assert summary["micro"]["recall"] == pytest.approx(0.5)
    assert summary["micro"]["candidate_recall"] == pytest.approx(3 / 4)
    assert summary["micro"]["corpus_ceiling"] == pytest.approx(3 / 4)


def test_neurosynth_term_selection_is_deterministic() -> None:
    case = {
        "topic": "Reward",
        "search": "reward decision making fMRI",
        "inclusion": "whole-brain studies of reward processing",
    }
    vocab = ["reward", "decision making", "visual", "functional magnetic", "studies"]
    terms = select_neurosynth_terms(case, vocab, max_terms=3)

    assert [term["term"] for term in terms] == ["reward", "decision making"]


def test_neurosynth_ranking_uses_terms_and_year_cutoff() -> None:
    sp = pytest.importorskip("scipy.sparse")
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Reward",
        "search": "reward",
        "inclusion": "reward studies",
        "year_cutoff": 2020,
    }
    metadata = [
        {"pmid": "10", "year": 2018},
        {"pmid": "20", "year": 2019},
        {"pmid": "30", "year": 2021},
    ]
    vocab = ["reward", "memory"]
    matrix = sp.csr_matrix(
        [
            [0.1, 0.0],
            [0.9, 0.0],
            [2.0, 0.0],
        ]
    )

    row = rank_case_pmids(case, metadata, vocab, matrix, top_k=5)

    assert row["ranked_pmids"] == ["20", "10"]
    assert row["predicted_pmids"] == ["20", "10"]


def test_br_screening_adapter_accepts_single_case_output_dir(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "gt_pmids": ["1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    br_dir = tmp_path / "br_single"
    br_dir.mkdir()
    (br_dir / "results.json").write_text(json.dumps({"meta_pmid": "123"}), encoding="utf-8")
    (br_dir / "screening_decisions.jsonl").write_text(
        json.dumps(
            {
                "pmid": "1",
                "decision": "include",
                "criterion_ids": ["inc_whole_brain"],
                "evidence_spans": ["whole-brain reward task"],
                "reason": "Matches whole-brain reward criteria.",
                "confidence": 0.8,
            }
        )
        + "\n"
        + json.dumps({"pmid": "2", "decision": "exclude"})
        + "\n",
        encoding="utf-8",
    )
    (br_dir / "br_screening_anchors.json").write_text(
        json.dumps(
            {
                "anchors": [
                    {
                        "candidate_pmid": "1",
                        "decision": "include",
                        "supports_inclusion": True,
                        "eligibility_criterion": "inc_whole_brain",
                        "evidence_source": "BR MCP",
                        "evidence_summary": "Recovered whole-brain reward task evidence.",
                        "confidence": "high",
                        "consumed_by": ["screening_decisions.jsonl"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "predictions.jsonl"

    summary = convert_br_screening_outputs(cases_path, br_dir, output, candidate_source="union")
    rows = read_jsonl(output)

    assert summary["n_cases"] == 1
    assert summary["candidate_source"] == "union"
    assert rows[0]["candidate_source"] == "union"
    assert rows[0]["ranked_pmids"] == ["1", "2"]
    assert rows[0]["predicted_pmids"] == ["1"]
    assert rows[0]["decision_records"][0]["criterion_ids"] == ["inc_whole_brain"]
    assert rows[0]["decision_records"][0]["confidence"] == pytest.approx(0.8)
    assert rows[0]["br_screening_anchors"][0]["candidate_pmid"] == "1"


def test_retrieval_only_query_set_avoids_review_meta_analysis_terms() -> None:
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Substance Use",
        "modality": "Structural",
        "method": "ALE",
        "search": '("voxel-based morphometry" OR "gray matter volume") AND (alcohol OR nicotine); reviewing bibliographies of existing meta-analyses and review articles',
        "inclusion": "empirical English language MRI studies assessing GM volume differences",
        "gt_pmids": ["10", "20", "30"],
    }

    br_query = build_br_llm_query(case).lower()
    queries = build_query_set(case)
    row = retrieval_diagnostic_row(
        case,
        query_mode="union_query",
        query=queries["union_query"],
        candidate_pmids=["10", "20", "99"],
        n_hits=3,
    )

    assert "review OR meta-analysis".lower() not in br_query
    assert "review[publication type]" in br_query
    assert row["candidate_recall"] == pytest.approx(2 / 3)
    assert row["gt_missing_from_candidates"] == ["30"]


def test_closed_world_baselines_include_dumb_controls(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_csv(
        data_dir / "all_studies_annotated_wt.csv",
        [
            {
                "meta_pmid": "123",
                "study_pmid": "1",
                "title": "Reward processing during functional MRI",
                "author": "A",
            },
            {
                "meta_pmid": "123",
                "study_pmid": "2",
                "title": "Visual perception task",
                "author": "B",
            },
            {
                "meta_pmid": "123",
                "study_pmid": "3",
                "title": "Reward decision making in fMRI",
                "author": "C",
            },
        ],
    )
    case = {
        "case_id": "neurometabench:123",
        "meta_pmid": "123",
        "topic": "Reward",
        "search": "reward fMRI",
        "inclusion": "whole-brain reward studies",
        "method": "ALE",
        "modality": "fMRI",
        "selected_n": "2",
        "gt_pmids": ["1", "3"],
        "has_gt": True,
    }

    rows = build_closed_world_baseline_predictions(
        case,
        data_dir=data_dir,
        random_repeats=1,
        random_seed=7,
    )

    systems = [row["system"] for row in rows]
    bm25 = next(row for row in rows if row["system"] == "closed_world_keyword_bm25")
    assert systems == ["closed_world_include_all", "closed_world_keyword_bm25", "closed_world_random"]
    assert set(bm25["predicted_pmids"]) == {"1", "3"}


def test_evaluate_prediction_files_can_emit_closed_world_baselines(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "topic": "Reward",
                "search": "reward fMRI",
                "inclusion": "whole-brain reward studies",
                "method": "ALE",
                "modality": "fMRI",
                "selected_n": "1",
                "gt_pmids": ["1"],
                "has_gt": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        data_dir / "all_studies_annotated_wt.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1", "title": "Reward fMRI", "author": "A"},
            {"meta_pmid": "123", "study_pmid": "2", "title": "Vision", "author": "B"},
        ],
    )

    result = evaluate_prediction_files(
        cases_path,
        [],
        tmp_path / "eval",
        add_closed_world_baselines=True,
        data_dir=data_dir,
        random_repeats=0,
    )

    systems = result["summary"]["systems"]
    assert "closed_world_include_all" in systems
    assert "closed_world_keyword_bm25" in systems


def test_mixed_pool_candidates_use_gt_plus_noise(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_csv(
        data_dir / "included_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1", "doi": ""},
            {"meta_pmid": "123", "study_pmid": "2", "doi": ""},
            {"meta_pmid": "999", "study_pmid": "3", "doi": ""},
            {"meta_pmid": "999", "study_pmid": "4", "doi": ""},
            {"meta_pmid": "999", "study_pmid": "5", "doi": ""},
        ],
    )
    _write_csv(
        data_dir / "all_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "6", "status": "NO", "final_status": "NO"},
            {"meta_pmid": "123", "study_pmid": "7", "status": "NO", "final_status": "NO"},
        ],
    )

    pool = load_mixed_pool_candidates(data_dir, "123", noise_ratio=2, seed=0)
    capped_pool = load_mixed_pool_candidates(data_dir, "123", noise_ratio=2, seed=0, max_total=4)

    assert {"1", "2"}.issubset(set(pool))
    assert len(pool) == 6
    assert {"1", "2"}.issubset(set(capped_pool))
    assert len(capped_pool) == 4


def test_layer_a_baselines_emit_rule_and_asreview_predictions(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "topic": "Reward",
                "search": "reward fMRI",
                "inclusion": "whole-brain reward studies",
                "exclusion": "ROI-only",
                "method": "ALE",
                "modality": "fMRI",
                "selected_n": "2",
                "gt_pmids": ["1", "2"],
                "has_gt": True,
                "primary_task_layer": "layer_a_screening_with_justification",
                "screening_criteria": [
                    {"criterion_id": "inc_whole_brain", "polarity": "include", "text": "whole-brain reward"},
                    {"criterion_id": "exc_roi_only", "polarity": "exclude", "text": "ROI-only"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        data_dir / "included_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1", "doi": ""},
            {"meta_pmid": "123", "study_pmid": "2", "doi": ""},
        ],
    )
    _write_csv(
        data_dir / "included_studies_wt.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1", "title": "Reward fMRI task", "year": "2020", "author": "A"},
            {"meta_pmid": "123", "study_pmid": "2", "title": "Reward decision task", "year": "2020", "author": "B"},
        ],
    )
    _write_csv(
        data_dir / "all_studies.csv",
        [
            {"meta_pmid": "999", "study_pmid": "3", "status": "YES", "final_status": "YES"},
            {"meta_pmid": "999", "study_pmid": "4", "status": "NO", "final_status": "NO"},
        ],
    )
    _write_csv(
        data_dir / "all_studies_annotated_wt.csv",
        [
            {
                "meta_pmid": "999",
                "study_pmid": "3",
                "status": "YES",
                "final_status": "YES",
                "corrected_status": "YES",
                "reason": "",
                "SourceSheet": "YES",
                "posthoc_status": "",
                "posthoc_reason": "",
                "title": "Visual control task",
                "year": "2020",
                "author": "C",
            },
            {
                "meta_pmid": "999",
                "study_pmid": "4",
                "status": "NO",
                "final_status": "NO",
                "corrected_status": "NO",
                "reason": "",
                "SourceSheet": "NO",
                "posthoc_status": "",
                "posthoc_reason": "",
                "title": "Motor control task",
                "year": "2020",
                "author": "D",
            },
        ],
    )

    case = read_jsonl(cases_path)[0]
    source, candidates = load_layer_a_candidate_pool(
        case,
        data_dir=data_dir,
        candidate_source="mixed_pool",
        mixed_noise_ratio=1,
        mixed_seed=0,
        mixed_max_total=4,
    )
    output = tmp_path / "baselines.jsonl"
    summary = build_layer_a_baseline_predictions(
        cases_path,
        output,
        data_dir=data_dir,
        systems=["rule", "asreview_style"],
        candidate_source="mixed_pool",
        mixed_noise_ratio=1,
        mixed_seed=0,
        mixed_max_total=4,
    )
    rows = read_jsonl(output)
    asreview = next(row for row in rows if row["system"] == "layer_a_asreview_style_specialist")

    assert source == "mixed_pool"
    assert {candidate.pmid for candidate in candidates} == {"1", "2", "3", "4"}
    assert next(candidate for candidate in candidates if candidate.pmid == "3").label == "exclude"
    assert next(candidate for candidate in candidates if candidate.pmid == "1").row["title"] == "Reward fMRI task"
    assert summary["n_predictions"] == 2
    assert asreview["screening_budget"] == 2
    assert asreview["metadata"]["external_asreview_required"] is False


def test_layer_a_batch_generates_baselines_and_evaluates(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "case_id": "neurometabench:123",
                    "meta_pmid": "123",
                    "topic": "Reward",
                    "search": "reward",
                    "inclusion": "reward studies",
                    "method": "ALE",
                    "modality": "fMRI",
                    "selected_n": "1",
                    "gt_pmids": ["1"],
                    "has_gt": True,
                    "primary_task_layer": "layer_a_screening_with_justification",
                },
                {
                    "case_id": "neurometabench:456",
                    "meta_pmid": "456",
                    "topic": "Memory",
                    "search": "memory",
                    "inclusion": "memory studies",
                    "method": "ALE",
                    "modality": "fMRI",
                    "selected_n": "1",
                    "gt_pmids": ["9"],
                    "has_gt": True,
                    "primary_task_layer": "layer_a_screening_with_justification",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        data_dir / "included_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1", "doi": ""},
            {"meta_pmid": "456", "study_pmid": "9", "doi": ""},
        ],
    )
    _write_csv(
        data_dir / "included_studies_wt.csv",
        [{"meta_pmid": "123", "study_pmid": "1", "title": "Reward task", "year": "2020", "author": "A"}],
    )
    _write_csv(data_dir / "all_studies.csv", [{"meta_pmid": "999", "study_pmid": "2", "status": "NO", "final_status": "NO"}])

    summary = asyncio.run(
        run_layer_a_batch(
            cases_path=cases_path,
            data_dir=data_dir,
            output_root=tmp_path / "batch",
            meta_pmids=["123"],
            generate_baselines=True,
            baseline_only=True,
            candidate_source="mixed_pool",
            baseline_candidate_source="mixed_pool",
            mixed_pool_noise_ratio=1,
            max_candidates=2,
            retries=0,
            judge_mode="none",
        )
    )

    systems = summary["aggregate"]["evaluation"]["summary"]["systems"]
    assert summary["n_tasks"] == 0
    assert summary["aggregate"]["n_prediction_rows"] == 2
    assert "layer_a_rule_lexical" in systems
    assert "layer_a_asreview_style_specialist" in systems

    dry_run_summary = asyncio.run(
        run_layer_a_batch(
            cases_path=cases_path,
            data_dir=data_dir,
            output_root=tmp_path / "batch_dry_run",
            meta_pmids=["123"],
            generate_baselines=True,
            baseline_only=True,
            dry_run=True,
            judge_mode="none",
        )
    )
    assert dry_run_summary["status"] == "dry_run"
    assert dry_run_summary["aggregate"] is None


def test_layer_a_batch_resumes_completed_cases(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "topic": "Reward",
                "gt_pmids": ["1"],
                "has_gt": True,
                "primary_task_layer": "layer_a_screening_with_justification",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_root = tmp_path / "batch"
    case_dir = output_root / "layer_a_123_mixed_pool"
    case_dir.mkdir(parents=True)
    write_jsonl(
        [
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "system": "codex_plus_br",
                "ranked_pmids": ["1", "2"],
                "predicted_pmids": ["1"],
                "decision_records": [],
            }
        ],
        case_dir / "predictions.jsonl",
    )
    (case_dir / "experiment_summary.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")

    summary = asyncio.run(
        run_layer_a_batch(
            cases_path=cases_path,
            output_root=output_root,
            meta_pmids=["123"],
            candidate_source="mixed_pool",
            retries=0,
            judge_mode="none",
        )
    )

    assert summary["n_skipped_completed"] == 1
    assert summary["aggregate"]["n_prediction_rows"] == 1
    assert "codex_plus_br" in summary["aggregate"]["evaluation"]["summary"]["systems"]


def test_evaluate_prediction_reports_rationale_completeness() -> None:
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Reward",
        "route": "pmc_fulltext",
        "task_type": "screening_with_justification",
        "primary_task_layer": "layer_a_screening_with_justification",
        "gt_pmids": ["1"],
    }
    prediction = {
        "system": "test_system",
        "ranked_pmids": ["1", "2"],
        "predicted_pmids": ["1"],
        "decision_records": [
            {
                "pmid": "1",
                "decision": "include",
                "criterion_ids": ["inc_whole_brain"],
                "evidence_spans": ["whole-brain reward task"],
                "reason": "Matches criteria.",
                "confidence": 0.9,
            },
            {"pmid": "2", "decision": "exclude", "criterion_ids": [], "evidence_spans": [], "reason": ""},
        ],
    }

    row = evaluate_prediction(case, prediction)

    assert row["task_type"] == "screening_with_justification"
    assert row["n_decision_records"] == 2
    assert row["reason_coverage"] == pytest.approx(0.5)
    assert row["criterion_coverage"] == pytest.approx(0.5)
    assert row["evidence_span_coverage"] == pytest.approx(0.5)
    assert row["confidence_coverage"] == pytest.approx(0.5)


def test_criterion_alignment_judge_scores_span_to_criterion_overlap(tmp_path: Path) -> None:
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "screening_criteria": [
            {
                "criterion_id": "inc_whole_brain",
                "polarity": "include",
                "text": "whole-brain reward fMRI studies",
            }
        ],
    }
    decision = {
        "pmid": "10",
        "decision": "include",
        "criterion_ids": ["inc_whole_brain"],
        "evidence_spans": ["whole-brain reward processing during fMRI"],
        "reason": "The paper matches the whole-brain reward criterion.",
    }

    item = judge_decision(case, decision)

    assert item["label"] == "yes"
    assert item["alignment_score"] > 0

    cases_path = tmp_path / "cases.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    output = tmp_path / "judge.json"
    cases_path.write_text(json.dumps(case) + "\n", encoding="utf-8")
    predictions_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:1",
                "system": "test",
                "decision_records": [decision],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = judge_prediction_files(cases_path, [predictions_path], output)
    assert result["summary"]["label_counts"]["yes"] == 1


def test_build_nimads_reproduction_manifest_selects_layer_b_cases(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    output = tmp_path / "manifest.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:321",
                "meta_pmid": "321",
                "topic": "Reward",
                "route": "nimads_brainmap",
                "task_layers": ["layer_b_end_to_end_reproduction"],
                "task_type": "end_to_end_reproduction",
                "n_gt": 3,
                "screening_criteria": [],
                "nimads_assets": {
                    "project_key": "reward",
                    "project_dir": "/tmp/reward",
                    "raw_jsons": ["/tmp/reward/a.json"],
                    "merged_studyset": "/tmp/reward/merged/nimads_studyset.json",
                    "merged_annotation": "/tmp/reward/merged/nimads_annotation.json",
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "route": "pmc_fulltext",
                "task_layers": ["layer_a_screening_with_justification"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_manifest(cases_path, output)
    rows = read_jsonl(output)

    assert summary["n_cases"] == 1
    assert rows[0]["task_layer"] == "layer_b_end_to_end_reproduction"
    assert "nimare_ale_map" in rows[0]["expected_outputs"]


def test_nimads_asset_audit_distinguishes_case_gt_from_coordinate_gt(tmp_path: Path) -> None:
    studyset = tmp_path / "nimads_studyset.json"
    annotation = tmp_path / "nimads_annotation.json"
    cases_path = tmp_path / "cases.jsonl"
    manifest_path = tmp_path / "manifest.jsonl"
    output_json = tmp_path / "audit.json"
    output_md = tmp_path / "audit.md"

    studyset.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "id": "12345678",
                        "analyses": [
                            {
                                "id": "a1",
                                "metadata": {"sample_sizes": [24]},
                                "points": [{"space": "MNI", "coordinates": [1, 2, 3]}],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    annotation.write_text(
        json.dumps(
            {
                "note_keys": {"whole_brain": "boolean"},
                "notes": [{"analysis": "a1", "note": {"whole_brain": True}}],
            }
        ),
        encoding="utf-8",
    )
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:999",
                "meta_pmid": "999",
                "topic": "Toy",
                "route": "nimads_brainmap",
                "gt_pmids": ["12345678"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:999",
                "meta_pmid": "999",
                "topic": "Toy",
                "project_key": "toy",
                "raw_jsons": [],
                "merged_studyset": str(studyset),
                "merged_annotation": str(annotation),
                "n_gt": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_nimads_asset_audit(cases_path, manifest_path, output_json, output_md)
    row = result["cases"][0]

    assert result["summary"]["n_cases_with_case_gt_pmids"] == 1
    assert result["summary"]["n_cases_with_coordinate_gt"] == 1
    assert row["case_gt_pmids_n"] == 1
    assert row["studyset"]["n_points"] == 1
    assert row["annotation"]["analysis_coverage_rate"] == pytest.approx(1.0)
    assert row["gt_overlap_with_nimads_study_ids_n"] == 1
    assert row["path_b_status"] == "map_ready"


def test_path_b_coordinate_rows_and_filtering() -> None:
    studyset = {
        "studies": [
            {
                "id": "12345678",
                "name": "Study A",
                "analyses": [
                    {
                        "id": "a1",
                        "name": "contrast one",
                        "metadata": {"sample_sizes": [12]},
                        "points": [{"space": "MNI", "coordinates": [1, 2, 3]}],
                    },
                    {
                        "id": "a2",
                        "name": "contrast two",
                        "points": [{"space": "MNI", "coordinates": [4, 5, 6]}],
                    },
                ],
            }
        ]
    }

    rows = coordinate_rows(studyset)
    filtered = filter_studyset_by_analysis_ids(studyset, {"a2"})

    assert len(rows) == 2
    assert rows[0]["sample_size"] == 12
    assert filtered["studies"][0]["analyses"][0]["id"] == "a2"
    assert len(studyset["studies"][0]["analyses"]) == 2


def test_path_b_spatial_metrics_on_toy_maps(tmp_path: Path) -> None:
    affine = np.eye(4)
    a = np.zeros((4, 4, 4), dtype=float)
    b = np.zeros((4, 4, 4), dtype=float)
    a[0, 0, 0] = 3
    a[1, 1, 1] = 2
    b[0, 0, 0] = 3
    b[2, 2, 2] = 2
    map_a = tmp_path / "a.nii.gz"
    map_b = tmp_path / "b.nii.gz"
    nib.Nifti1Image(a, affine).to_filename(map_a)
    nib.Nifti1Image(b, affine).to_filename(map_b)

    metrics = spatial_metrics(map_a, map_b)

    assert metrics["n_union_positive_voxels"] == 3
    assert metrics["dice_top5_positive"] == pytest.approx(1.0)
    assert metrics["pearson_union_positive"] is not None


def test_path_b_summarize_existing_requires_real_map_paths(tmp_path: Path) -> None:
    case_dir = tmp_path / "layer_b_123_toy"
    maps_dir = case_dir / "ale_maps"
    maps_dir.mkdir(parents=True)
    z_map = maps_dir / "123_z.nii.gz"
    nib.Nifti1Image(np.ones((2, 2, 2)), np.eye(4)).to_filename(z_map)
    (case_dir / "metrics.json").write_text(
        json.dumps(
            {
                "meta_pmid": "123",
                "topic": "Toy",
                "n_coordinate_rows": 8,
                "outputs": {"output_dir": str(case_dir)},
                "ale": {"map_paths": {"z": str(z_map)}},
                "split_half": {"status": "computed"},
            }
        ),
        encoding="utf-8",
    )

    result = summarize_existing(tmp_path)

    assert result["summary"]["n_cases"] == 1
    assert result["summary"]["n_cases_with_maps"] == 1
    assert result["summary"]["n_cases_split_half_computed"] == 1


def test_screening_json_parser_recovers_common_near_json() -> None:
    raw = """{
      "decision": "include",
      "criterion_ids": ["inc_whole_brain"],
      "evidence_spans": ["functional magnetic resonance imaging ("fMRI") task"],
      "reason": "Includes whole-brain fMRI task evidence.",
      "confidence": 0.8
    }"""

    parsed = parse_screening_json(raw)

    assert parsed["decision"] == "include"
    assert parsed["criterion_ids"] == ["inc_whole_brain"]
    assert parsed["parse_recovered"] is True


def test_layer_a_experiment_runner_reuses_existing_screening_output(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "topic": "Reward",
                "route": "pmc_fulltext",
                "primary_task_layer": "layer_a_screening_with_justification",
                "task_type": "screening_with_justification",
                "gt_pmids": ["1", "2"],
                "screening_criteria": [
                    {
                        "criterion_id": "inc_whole_brain",
                        "polarity": "include",
                        "text": "whole-brain reward task",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    screening_dir = tmp_path / "screening"
    screening_dir.mkdir()
    (screening_dir / "results.json").write_text(json.dumps({"meta_pmid": "123"}), encoding="utf-8")
    (screening_dir / "screening_decisions.jsonl").write_text(
        json.dumps(
            {
                "pmid": "1",
                "decision": "include",
                "criterion_ids": ["inc_whole_brain"],
                "evidence_spans": ["whole-brain reward task"],
                "reason": "Matches the target criterion.",
                "confidence": 0.9,
            }
        )
        + "\n"
        + json.dumps(
            {
                "pmid": "3",
                "decision": "exclude",
                "criterion_ids": ["inc_whole_brain"],
                "evidence_spans": ["not a whole-brain task"],
                "reason": "Does not match.",
                "confidence": 0.8,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    judge_json = tmp_path / "judge.json"
    judge_json.write_text(
        json.dumps(
            {
                "items": [],
                "summary": {
                    "n_items": 2,
                    "label_counts": {"yes": 2},
                    "mean_alignment_score": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_layer_a_experiment(
        meta_pmid="123",
        cases_path=cases_path,
        data_dir=tmp_path / "data",
        output_root=tmp_path / "experiments",
        screening_output_dir=screening_dir,
        candidate_source="mixed_pool",
        mixed_pool_noise_ratio=5,
        mixed_pool_seed=0,
        max_candidates=10,
        min_candidate_recall_to_screen=0.6,
        llm_model="gemini-2.5-flash",
        run_screening=False,
        judge_mode="none",
        judge_json=judge_json,
        judge_model="gemini-2.5-flash",
        judge_repeat=2,
    )
    summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))

    assert result["summary"]["precision"] == pytest.approx(1.0)
    assert result["summary"]["recall"] == pytest.approx(0.5)
    assert summary["confusion_matrix"]["tp"] == 1
    assert summary["confusion_matrix"]["fn"] == 1
    assert summary["criterion_alignment"]["label_counts"]["yes"] == 2


def test_neurovault_substrate_diagnostic_reports_meta_and_gt_coverage(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    metadata_csv = tmp_path / "metadata.csv"
    collections_csv = tmp_path / "neurovault_collections.csv"
    images_csv = tmp_path / "neurovault_images.csv"
    output_jsonl = tmp_path / "coverage.jsonl"
    output_summary = tmp_path / "coverage_summary.json"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "neurometabench:123",
                "meta_pmid": "123",
                "pmcid": "PMC100",
                "topic": "Reward",
                "route": "pmc_fulltext",
                "primary_task_layer": "layer_a_screening_with_justification",
                "task_type": "screening_with_justification",
                "gt_pmids": ["1", "2"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        metadata_csv,
        [
            {"pmid": "1", "pmcid": "200"},
            {"pmid": "2", "pmcid": ""},
            {"pmid": "123", "pmcid": "100"},
        ],
    )
    _write_csv(
        collections_csv,
        [
            {"pmcid": "100", "collection_id": "10"},
            {"pmcid": "200", "collection_id": "20"},
        ],
    )
    _write_csv(images_csv, [{"pmcid": "200", "image_id": "30"}])

    result = run_neurovault_substrate_diagnostic(
        cases_path=cases_path,
        metadata_csv=metadata_csv,
        neurovault_collections_csv=collections_csv,
        neurovault_images_csv=images_csv,
        output_jsonl=output_jsonl,
        output_summary=output_summary,
    )
    rows = read_jsonl(output_jsonl)

    assert result["summary"]["overall"]["n_cases_meta_neurovault_collection"] == 1
    assert rows[0]["meta_neurovault_collection_ids"] == ["10"]
    assert rows[0]["gt_pmcid_coverage"] == pytest.approx(0.5)
    assert rows[0]["gt_neurovault_collection_coverage"] == pytest.approx(0.5)
    assert rows[0]["gt_neurovault_image_coverage"] == pytest.approx(0.5)


def test_layer_c_diagnostics_runs_cross_cutting_audits(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    data_dir = tmp_path / "data"
    metadata_csv = tmp_path / "metadata.csv"
    collections_csv = tmp_path / "neurovault_collections.csv"
    images_csv = tmp_path / "neurovault_images.csv"
    studyset = tmp_path / "nimads_studyset.json"
    annotation = tmp_path / "nimads_annotation.json"
    nimads_manifest = tmp_path / "nimads_manifest.jsonl"
    output_root = tmp_path / "layer_c"

    cases_path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "case_id": "neurometabench:123",
                    "meta_pmid": "123",
                    "pmcid": "PMC100",
                    "topic": "Reward",
                    "route": "pmc_fulltext",
                    "primary_task_layer": "layer_a_screening_with_justification",
                    "task_layers": ["layer_a_screening_with_justification", LAYER_C_DIAGNOSTIC_AUDIT],
                    "task_type": "screening_with_justification",
                    "gt_pmids": ["1", "2"],
                    "has_gt": True,
                    "n_gt": 2,
                },
                {
                    "case_id": "neurometabench:321",
                    "meta_pmid": "321",
                    "pmcid": "PMC300",
                    "topic": "Face",
                    "route": "nimads_brainmap",
                    "primary_task_layer": "layer_b_end_to_end_reproduction",
                    "task_layers": ["layer_b_end_to_end_reproduction", LAYER_C_DIAGNOSTIC_AUDIT],
                    "task_type": "end_to_end_reproduction",
                    "gt_pmids": [],
                    "has_gt": False,
                    "n_gt": 0,
                },
                {
                    "case_id": "neurometabench:999",
                    "meta_pmid": "999",
                    "topic": "Diagnostic",
                    "route": "pmc_fulltext",
                    "primary_task_layer": LAYER_C_DIAGNOSTIC_AUDIT,
                    "task_layers": [LAYER_C_DIAGNOSTIC_AUDIT],
                    "task_type": "diagnostic_audit",
                    "gt_pmids": [],
                    "has_gt": False,
                    "n_gt": 0,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_csv(
        data_dir / "all_studies.csv",
        [
            {"meta_pmid": "123", "study_pmid": "1"},
            {"meta_pmid": "123", "study_pmid": "2"},
            {"meta_pmid": "123", "study_pmid": "3"},
        ],
    )
    _write_csv(
        metadata_csv,
        [
            {"pmid": "1", "pmcid": "200"},
            {"pmid": "123", "pmcid": "100"},
            {"pmid": "321", "pmcid": "300"},
        ],
    )
    _write_csv(collections_csv, [{"pmcid": "100", "collection_id": "10"}])
    _write_csv(images_csv, [{"pmcid": "200", "image_id": "20"}])
    studyset.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "id": "study-a",
                        "analyses": [{"id": "a1", "points": [{"space": "MNI", "coordinates": [1, 2, 3]}]}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    annotation.write_text(
        json.dumps({"note_keys": {"all": "boolean"}, "notes": [{"analysis": "a1", "note": {"all": True}}]}),
        encoding="utf-8",
    )
    write_jsonl(
        [
            {
                "case_id": "neurometabench:321",
                "meta_pmid": "321",
                "topic": "Face",
                "project_key": "face",
                "raw_jsons": [],
                "merged_studyset": str(studyset),
                "merged_annotation": str(annotation),
                "n_gt": 0,
            }
        ],
        nimads_manifest,
    )

    result = run_layer_c_diagnostics(
        cases_path=cases_path,
        data_dir=data_dir,
        output_root=output_root,
        retrievers=("closed_world",),
        max_candidates=10,
        metadata_csv=metadata_csv,
        neurovault_collections_csv=collections_csv,
        neurovault_images_csv=images_csv,
        nimads_manifest=nimads_manifest,
    )
    manifest_rows = read_jsonl(output_root / "layer_c_manifest.jsonl")

    assert result["headline_score"] is False
    assert result["manifest_summary"]["n_cases"] == 3
    assert result["manifest_summary"]["primary_task_layer_counts"][LAYER_C_DIAGNOSTIC_AUDIT] == 1
    assert result["retrieval"]["closed_world"]["health"]["union_macro_candidate_recall"] == pytest.approx(1.0)
    assert result["neurovault"]["health"]["n_cases"] == 3
    assert result["nimads"]["health"]["n_cases"] == 1
    assert manifest_rows[0]["layer"] == LAYER_C_DIAGNOSTIC_AUDIT
    assert (output_root / "layer_c_diagnostic_summary.md").exists()
