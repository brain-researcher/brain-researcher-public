from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.neurometabench_v1.evaluate_study_set import (
    evaluate_prediction,
    evaluate_prediction_files,
    summarize,
)


def _case() -> dict[str, object]:
    return {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Reward",
        "route": "pmc_fulltext",
        "task_type": "screening_with_justification",
        "primary_task_layer": "layer_a_screening_with_justification",
        "gt_pmids": ["1", "2"],
        "has_gt": True,
    }


def test_eligibility_f1_uses_mixed_include_exclude_decision_records() -> None:
    prediction = {
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2", "3", "4"],
        "predicted_pmids": ["1", "3"],
        "decision_records": [
            {"pmid": "1", "decision": "include"},
            {"pmid": "2", "decision": "exclude"},
            {"pmid": "3", "include": True},
            {"pmid": "4", "include": False},
        ],
    }

    row = evaluate_prediction(_case(), prediction)

    assert row["eligibility_n_evaluable_decisions"] == 4
    assert row["eligibility_tp"] == 1
    assert row["eligibility_fp"] == 1
    assert row["eligibility_fn"] == 1
    assert row["eligibility_precision"] == pytest.approx(0.5)
    assert row["eligibility_recall"] == pytest.approx(0.5)
    assert row["eligibility_f1"] == pytest.approx(0.5)
    assert row["eligibility_F1"] == pytest.approx(0.5)
    assert row["include_only_n_predicted"] == 2
    assert row["include_only_n_tp"] == 1
    assert row["include_only_precision"] == pytest.approx(0.5)
    assert row["include_only_recall"] == pytest.approx(0.5)
    assert row["include_only_f1"] == pytest.approx(0.5)
    assert row["include_or_uncertain_predicted_to_gold_ratio"] == pytest.approx(1.0)
    assert row["n_predicted_to_gold_ratio"] == pytest.approx(1.0)
    assert row["include_only_predicted_to_gold_ratio"] == pytest.approx(1.0)
    assert row["over_conservatism_penalty"] == pytest.approx(0.5)
    assert row["over_conservatism_signal"] is False
    assert row["decision_include_count"] == 2
    assert row["decision_exclude_count"] == 2
    assert row["decision_uncertain_count"] == 0
    assert row["decision_include_rate"] == pytest.approx(0.5)

    summary = summarize([row])["systems"]["layer_a_test"]
    assert summary["macro"]["eligibility_F1"] == pytest.approx(0.5)
    assert summary["micro"]["eligibility_f1"] == pytest.approx(0.5)
    assert summary["micro"]["eligibility_F1"] == pytest.approx(0.5)
    assert summary["macro"]["include_only_f1"] == pytest.approx(0.5)
    assert summary["micro"]["include_only_f1"] == pytest.approx(0.5)
    assert summary["micro"]["over_conservatism_penalty"] == pytest.approx(0.5)
    assert summary["micro"]["decision_include_count"] == 2
    assert summary["micro"]["decision_exclude_count"] == 2
    assert summary["micro"]["decision_include_rate"] == pytest.approx(0.5)


def test_decision_distribution_tracks_uncertain_spam() -> None:
    prediction = {
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2", "3", "4"],
        "predicted_pmids": ["1", "2", "3", "4"],
        "decision_records": [
            {"pmid": "1", "decision": "uncertain"},
            {"pmid": "2", "decision": "uncertain"},
            {"pmid": "3", "decision": "uncertain"},
            {"pmid": "4", "decision": "exclude"},
        ],
    }

    row = evaluate_prediction(_case(), prediction)

    assert row["f1"] == pytest.approx(0.666667)
    assert row["include_only_f1"] is None
    assert row["decision_uncertain_count"] == 3
    assert row["decision_exclude_count"] == 1
    assert row["decision_uncertain_rate"] == pytest.approx(0.75)


def test_over_conservatism_signal_tracks_recall_collapse_after_candidate_recovery() -> None:
    prediction = {
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2", "3", "4"],
        "predicted_pmids": ["1"],
        "decision_records": [
            {"pmid": "1", "decision": "include"},
            {"pmid": "2", "decision": "exclude"},
            {"pmid": "3", "decision": "exclude"},
            {"pmid": "4", "decision": "exclude"},
        ],
    }

    row = evaluate_prediction(_case(), prediction)

    assert row["candidate_recall"] == pytest.approx(1.0)
    assert row["include_only_recall"] == pytest.approx(0.5)
    assert row["include_only_predicted_to_gold_ratio"] == pytest.approx(0.5)
    assert row["over_conservatism_penalty"] == pytest.approx(0.5)
    assert row["over_conservatism_signal"] is True


def test_br_screening_anchor_metrics_require_decision_consumption() -> None:
    prediction = {
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2", "3", "4"],
        "predicted_pmids": ["1", "2"],
        "decision_records": [
            {"pmid": "1", "decision": "include"},
            {"pmid": "2", "decision": "uncertain"},
            {"pmid": "3", "decision": "exclude"},
            {"pmid": "4", "decision": "exclude"},
        ],
        "br_screening_anchors": [
            {
                "candidate_pmid": "1",
                "decision": "include",
                "supports_inclusion": True,
                "eligibility_criterion": "reward task",
                "evidence_source": "BR MCP",
                "evidence_summary": "Recovered task evidence.",
                "confidence": "high",
            },
            {
                "candidate_pmid": "2",
                "decision": "uncertain",
                "supports_inclusion": True,
                "eligibility_criterion": "reward task",
                "evidence_source": "BR MCP",
                "evidence_summary": "Plausible but incomplete.",
                "confidence": "medium",
            },
        ],
    }

    row = evaluate_prediction(_case(), prediction)

    assert row["br_screening_anchor_count"] == 2
    assert row["br_screening_anchor_candidate_count"] == 2
    assert row["br_screening_anchor_coverage"] == pytest.approx(0.5)
    assert row["br_screening_anchor_include_count"] == 1
    assert row["br_screening_anchor_uncertain_count"] == 1
    assert row["br_screening_anchor_consumed_count"] == 2
    assert row["br_screening_anchor_consumption_rate"] == pytest.approx(1.0)


def test_eligibility_metrics_are_none_without_evaluable_decision_records() -> None:
    prediction = {
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2"],
        "predicted_pmids": ["1"],
        "decision_records": [],
    }

    row = evaluate_prediction(_case(), prediction)

    assert row["eligibility_n_evaluable_decisions"] == 0
    assert row["eligibility_precision"] is None
    assert row["eligibility_recall"] is None
    assert row["eligibility_f1"] is None
    assert row["eligibility_F1"] is None


def test_explicit_empty_predictions_do_not_fall_back_to_ranked_candidates() -> None:
    ranked_only = evaluate_prediction(
        _case(),
        {
            "system": "layer_a_test",
            "ranked_pmids": ["1", "2"],
            "predicted_pmids": [],
            "decision_records": [],
        },
    )
    candidate_only = evaluate_prediction(
        _case(),
        {
            "system": "layer_a_test",
            "candidate_pmids": ["1", "2"],
            "decision_records": [],
        },
    )

    assert ranked_only["n_ranked"] == 2
    assert ranked_only["candidate_recall"] == pytest.approx(1.0)
    assert ranked_only["n_predicted"] == 0
    assert ranked_only["recall"] == pytest.approx(0.0)

    assert candidate_only["n_ranked"] == 2
    assert candidate_only["candidate_recall"] == pytest.approx(1.0)
    assert candidate_only["n_predicted"] == 0
    assert candidate_only["recall"] == pytest.approx(0.0)


def test_summarize_splits_mixed_and_all_gt_saturated_cases() -> None:
    mixed_row = evaluate_prediction(
        _case(),
        {
            "system": "layer_a_test",
            "ranked_pmids": ["1", "2", "3"],
            "predicted_pmids": ["1"],
            "decision_records": [{"pmid": "1", "decision": "include"}],
        },
    )
    saturated_row = evaluate_prediction(
        _case(),
        {
            "system": "layer_a_test",
            "ranked_pmids": ["1", "2"],
            "predicted_pmids": ["1", "2"],
            "decision_records": [
                {"pmid": "1", "decision": "include"},
                {"pmid": "2", "decision": "uncertain"},
            ],
        },
    )

    assert mixed_row["case_partition"] == "mixed_only"
    assert mixed_row["is_all_gt_saturated"] is False
    assert mixed_row["gt_candidate_ratio"] == pytest.approx(2 / 3)
    assert saturated_row["case_partition"] == "all_gt_saturated"
    assert saturated_row["is_all_gt_saturated"] is True
    assert saturated_row["gt_candidate_ratio"] == pytest.approx(1.0)

    summary = summarize([mixed_row, saturated_row])
    system = summary["systems"]["layer_a_test"]

    assert summary["headline_metric_policy"]["primary_subsets"] == ["mixed_only"]
    assert "include_only_f1" in summary["headline_metric_policy"]["primary_metrics"]
    assert summary["case_partitions"]["mixed_only"]["n_unique_cases"] == 1
    assert summary["case_partitions"]["all_gt_saturated"]["n_unique_cases"] == 1
    assert system["subsets"]["mixed_only"]["micro"]["f1"] == pytest.approx(2 / 3)
    assert system["subsets"]["all_gt_saturated"]["micro"]["f1"] == pytest.approx(1.0)
    assert system["micro"]["candidate_recall"] == pytest.approx(1.0)


def test_citation_hallucination_categories_are_conservative() -> None:
    prediction = {
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2", "3", "4"],
        "predicted_pmids": ["1"],
        "decision_records": [
            {"pmid": "1", "decision": "include", "citation_pmids": ["1"]},
            {"pmid": "2", "decision": "exclude", "citation_pmids": ["1"]},
            {"pmid": "3", "decision": "exclude", "citation_pmids": ["4"]},
            {"pmid": "3", "decision": "exclude", "citation_pmids": ["999"]},
        ],
    }

    row = evaluate_prediction(_case(), prediction, corpus_pmids={"1", "2", "3", "4"})

    assert row["citation_count"] == 4
    assert row["citation_hallucination_count"] == 3
    assert row["citation_hallucination_rate"] == pytest.approx(0.75)
    assert row["citation_non_retrievable_count"] == 1
    assert row["citation_wrong_source_count"] == 1
    assert row["citation_retrievable_unsupported_count"] == 1
    assert row["citation_non_retrievable"] == pytest.approx(0.25)
    assert row["citation_wrong_source"] == pytest.approx(0.25)
    assert row["citation_retrievable_unsupported"] == pytest.approx(0.25)

    summary = summarize([row])["systems"]["layer_a_test"]["micro"]
    assert summary["citation_hallucination_count"] == 3
    assert summary["citation_hallucination_rate"] == pytest.approx(0.75)


def test_new_metrics_are_written_to_csv_and_json_outputs(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    output_dir = tmp_path / "eval"
    prediction = {
        "case_id": "neurometabench:1",
        "system": "layer_a_test",
        "ranked_pmids": ["1", "2"],
        "predicted_pmids": ["1"],
        "decision_records": [
            {"pmid": "1", "decision": "include", "citation_pmids": ["1"]},
        ],
    }
    cases_path.write_text(json.dumps(_case()) + "\n", encoding="utf-8")
    predictions_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")

    evaluate_prediction_files(cases_path, [predictions_path], output_dir)

    with (output_dir / "study_set_metrics.csv").open(
        encoding="utf-8", newline=""
    ) as fh:
        fieldnames = csv.DictReader(fh).fieldnames
    assert fieldnames is not None
    for field in (
        "gt_candidate_ratio",
        "n_predicted_to_gold_ratio",
        "include_or_uncertain_predicted_to_gold_ratio",
        "case_partition",
        "is_all_gt_saturated",
        "include_only_n_predicted",
        "include_only_n_tp",
        "include_only_predicted_to_gold_ratio",
        "include_only_precision",
        "include_only_recall",
        "include_only_f1",
        "over_conservatism_penalty",
        "over_conservatism_signal",
        "decision_include_count",
        "decision_uncertain_count",
        "decision_exclude_count",
        "decision_other_count",
        "decision_include_rate",
        "decision_uncertain_rate",
        "decision_exclude_rate",
        "decision_other_rate",
        "br_screening_anchor_count",
        "br_screening_anchor_coverage",
        "br_screening_anchor_consumption_rate",
        "eligibility_precision",
        "eligibility_recall",
        "eligibility_f1",
        "eligibility_F1",
        "citation_hallucination_rate",
        "citation_non_retrievable",
        "citation_retrievable_unsupported",
        "citation_wrong_source",
    ):
        assert field in fieldnames

    rows = json.loads(
        (output_dir / "study_set_metrics.json").read_text(encoding="utf-8")
    )
    assert rows[0]["eligibility_F1"] == pytest.approx(1.0)
    assert rows[0]["citation_hallucination_rate"] == pytest.approx(0.0)
    assert rows[0]["case_partition"] == "all_gt_saturated"

    summary = json.loads(
        (output_dir / "study_set_summary.json").read_text(encoding="utf-8")
    )
    assert summary["headline_metric_policy"]["primary_subsets"] == ["mixed_only"]
    assert "all_gt_saturated" in summary["case_partitions"]

    with (output_dir / "study_set_subset_summary.csv").open(
        encoding="utf-8", newline=""
    ) as fh:
        subset_rows = list(csv.DictReader(fh))
    assert subset_rows
    assert {
        "system",
        "subset",
        "role",
        "include_only_f1",
        "eligibility_F1",
        "average_precision",
        "candidate_recall",
        "n_predicted_to_gold_ratio",
        "over_conservatism_penalty",
    } <= set(subset_rows[0])
    assert any(
        row["subset"] == "all_gt_saturated" and row["role"] == "diagnostic"
        for row in subset_rows
    )
