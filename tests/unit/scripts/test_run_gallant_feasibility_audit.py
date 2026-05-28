"""Unit tests for scripts/mcp/run_gallant_feasibility_audit.py."""

from __future__ import annotations

from scripts.mcp.run_gallant_feasibility_audit import (
    GateOutcome,
    determine_final_verdict,
    evaluate_data_gate,
    evaluate_infra_gate,
    evaluate_model_gate,
    evaluate_novelty_gate,
    evaluate_ontology_gate,
)


def test_full_success_path_returns_feasible_now() -> None:
    infra = evaluate_infra_gate(
        server_info_ok=True,
        kg_first_class_ok=True,
        dataset_service_ok=True,
        concept_service_ok=True,
        route_mismatch_detected=False,
    )
    data = evaluate_data_gate(
        {
            "dataset_ref": "ds000114",
            "is_bids_available": True,
            "n_available_derivatives": 2,
            "readiness": {"ready": True},
        }
    )
    model = evaluate_model_gate(
        {
            "encoding": {"mean_r2": 0.12},
            "decoding": {"accuracy": 0.69, "pvalue": 0.01},
            "null_control": {"accuracy": 0.51},
            "thresholds": {"min_encoding_r2": 0.05, "min_decode_delta": 0.05},
        }
    )
    ontology = evaluate_ontology_gate(
        {"task_coverage": 1.0},
        has_mock_projection=False,
    )
    novelty = evaluate_novelty_gate(
        [{"novelty_class": "Adjacent"}, {"novelty_class": "Known"}]
    )

    gates = {
        infra.name: infra,
        data.name: data,
        model.name: model,
        ontology.name: ontology,
        novelty.name: novelty,
    }

    assert all(g.passed for g in gates.values())
    verdict = determine_final_verdict(
        gates,
        model_data_mode="provided_real_data",
        has_mock_projection=False,
    )
    assert verdict == "Feasible Now"


def test_metadata_only_dataset_fails_data_gate() -> None:
    gate = evaluate_data_gate(
        {
            "dataset_ref": "ds_meta_only",
            "is_bids_available": False,
            "n_available_derivatives": 0,
            "readiness": {"ready": False},
        }
    )
    assert gate.passed is False
    assert "Data gate failed" in gate.reason


def test_route_mismatch_fails_infra_gate() -> None:
    gate = evaluate_infra_gate(
        server_info_ok=True,
        kg_first_class_ok=True,
        dataset_service_ok=True,
        concept_service_ok=True,
        route_mismatch_detected=True,
    )
    assert gate.passed is False
    assert gate.evidence["route_mismatch_detected"] is True


def test_mock_projection_fails_ontology_gate() -> None:
    gate = evaluate_ontology_gate(
        {"task_coverage": 1.0},
        has_mock_projection=True,
    )
    assert gate.passed is False
    assert gate.evidence["has_mock_projection"] is True


def test_null_control_gap_fails_model_gate() -> None:
    gate = evaluate_model_gate(
        {
            "encoding": {"mean_r2": 0.09},
            "decoding": {"accuracy": 0.56, "pvalue": 0.03},
            "null_control": {"accuracy": 0.53},
            "thresholds": {"min_encoding_r2": 0.05, "min_decode_delta": 0.05},
        }
    )
    assert gate.passed is False
    assert gate.evidence["pass_components"]["delta"] is False


def test_verdict_caps_on_synthetic_data() -> None:
    gates = {
        "infra_gate": GateOutcome("infra_gate", True, "ok", {}),
        "data_gate": GateOutcome("data_gate", True, "ok", {}),
        "model_gate": GateOutcome("model_gate", True, "ok", {}),
        "ontology_gate": GateOutcome("ontology_gate", True, "ok", {}),
        "novelty_gate": GateOutcome("novelty_gate", True, "ok", {}),
    }
    verdict = determine_final_verdict(
        gates,
        model_data_mode="synthetic",
        has_mock_projection=False,
    )
    assert verdict == "Feasible with Remediation"
