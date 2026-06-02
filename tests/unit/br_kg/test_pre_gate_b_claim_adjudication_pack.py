from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "build"
    / "build_pre_gate_b_claim_adjudication_pack.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_pre_gate_b_claim_adjudication_pack", MODULE_PATH
)
assert SPEC and SPEC.loader
PACK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACK
SPEC.loader.exec_module(PACK)


def test_provenance_payload_prefers_run_loader_version() -> None:
    payload = PACK._provenance_payload(
        {
            "run": {
                "run_id": "r1",
                "loader_version": "gabriel-loader/v1",
                "raw_response_path": "/tmp/raw.json",
                "timestamp": "2026-03-10T00:00:00Z",
            }
        }
    )

    assert payload["loader_version"] == "gabriel-loader/v1"


def test_evidence_anchor_marks_title_only_low_rigor() -> None:
    record = {
        "paper": {"id": "pmid:1", "title": "Attention improves memory"},
        "claim": {"id": "claim:1"},
        "evidence": {
            "span_id": "evidence:1",
            "quote": "Attention improves memory",
            "section": "title",
            "page": None,
        },
        "run": {
            "run_id": "run-1",
            "loader_version": "gabriel-loader/v1",
            "raw_response_path": "/tmp/raw.json",
            "timestamp": "2026-03-10T00:00:00Z",
        },
    }
    source_record = {
        "path": "data/example.jsonl",
        "line_number": 1,
        "variables": {"method_rigor": 0.0},
    }

    anchor = PACK._evidence_anchor(
        "Attention improves memory",
        record,
        source_record,
    )

    assert anchor["evidence_depth"] == "title_only"
    assert "evidence_depth_title_only" in anchor["warnings"]
    assert "method_rigor_zero" in anchor["warnings"]
    assert "title_only_low_rigor_evidence" in anchor["warnings"]


def test_evidence_anchor_marks_semantic_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        PACK, "_semantic_text_similarity", lambda left, right: (0.05, "stub")
    )
    record = {
        "paper": {"id": "pmid:2", "title": "Cerebellar changes in NMOSD"},
        "claim": {"id": "claim:2"},
        "evidence": {
            "span_id": "evidence:2",
            "quote": "The cerebellum’s role in neuromyelitis optica spectrum disorder remains inadequately explored.",
            "section": "abstract",
            "page": None,
        },
        "run": {
            "run_id": "run-2",
            "loader_version": "gabriel-loader/v1",
            "raw_response_path": "/tmp/raw.json",
            "timestamp": "2026-03-10T00:00:00Z",
        },
    }
    source_record = {
        "path": "data/example.jsonl",
        "line_number": 2,
        "variables": {"method_rigor": 0.3},
    }

    anchor = PACK._evidence_anchor(
        "Attention effects are uniformly positive across the bounded bootstrap sample.",
        record,
        source_record,
    )

    assert anchor["semantic_similarity"] == 0.05
    assert anchor["semantic_check_backend"] == "stub"
    assert "claim_evidence_semantic_mismatch" in anchor["warnings"]


def test_infer_evidence_depth_marks_unverifiable_snippet() -> None:
    depth = PACK._infer_evidence_depth(
        {
            "paper": {"title": "Possible trend in executive control"},
            "evidence": {
                "quote": "Possibly related pattern.",
                "section": "discussion",
                "has_statistical_detail": False,
                "locatable": False,
                "direct_quote": False,
            },
        }
    )

    assert depth == "unverifiable_snippet"


def test_row_warnings_flag_structurally_invalid_conflicting() -> None:
    warnings, builder_checks = PACK._row_warnings(
        manifest_row={"expected_verdict": "conflicting"},
        source_records=[
            {"polarity": "refutes", "variables": {"method_rigor": 0.2}},
        ],
        anchors=[
            {
                "warnings": [],
                "evidence_depth": "abstract_or_summary",
                "provenance": {"loader_version": "gabriel-loader/v1"},
            }
        ],
    )

    assert "verdict_structural_prerequisite_unmet" in warnings
    assert "verdict_semantic_prerequisite_unmet" in warnings
    assert builder_checks["support_count"] == 0
    assert builder_checks["refute_count"] == 1
