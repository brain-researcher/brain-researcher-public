"""Tests for report-code claim traceability (P2.1)."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.review.claim_provenance import (
    build_claim_provenance_gate,
    ClaimProvenance,
    build_run_provenance_index,
    coerce_claims,
    RunProvenanceIndex,
    validate_claim_provenance,
)


def _index() -> RunProvenanceIndex:
    return RunProvenanceIndex(
        artifacts={"derivatives/fc/netmats1.npy": "abc123", "report/fig1.png": None},
        code_refs={"nilearn_connectivity_matrix", "nilearn_connectivity_matrix:step_2"},
    )


@pytest.mark.unit
def test_fully_traceable_claim_passes():
    claims = [
        ClaimProvenance(
            claim_id="c1",
            statement="Mean FC in DMN = 0.42",
            artifact_path="derivatives/fc/netmats1.npy",
            artifact_sha256="sha256:abc123",
            code_ref="nilearn_connectivity_matrix:step_2",
        )
    ]
    [v] = validate_claim_provenance(claims, _index())
    assert v.ok
    assert v.artifact_resolved and v.code_resolved
    assert v.artifact_hash_matches is True


@pytest.mark.unit
def test_missing_provenance_fails_under_require_full():
    claims = [ClaimProvenance(claim_id="c1", statement="x", artifact_path="derivatives/fc/netmats1.npy")]
    [v] = validate_claim_provenance(claims, _index(), require_full=True)
    assert not v.ok and not v.has_provenance
    assert any("code_ref" in i for i in v.issues)


@pytest.mark.unit
def test_claim_citing_unproduced_artifact_fails():
    claims = [
        ClaimProvenance(
            claim_id="c1",
            artifact_path="derivatives/fc/netmats_NEVER_RAN.npy",
            code_ref="nilearn_connectivity_matrix",
        )
    ]
    [v] = validate_claim_provenance(claims, _index())
    assert not v.ok and not v.artifact_resolved
    assert any("did not produce" in i for i in v.issues)


@pytest.mark.unit
def test_checksum_mismatch_fails():
    claims = [
        ClaimProvenance(
            claim_id="c1",
            artifact_path="derivatives/fc/netmats1.npy",
            artifact_sha256="deadbeef",  # ran abc123
            code_ref="nilearn_connectivity_matrix",
        )
    ]
    [v] = validate_claim_provenance(claims, _index())
    assert not v.ok and v.artifact_hash_matches is False
    assert any("checksum mismatch" in i for i in v.issues)


@pytest.mark.unit
def test_no_recorded_checksum_is_not_a_mismatch():
    claims = [
        ClaimProvenance(
            claim_id="c1",
            artifact_path="report/fig1.png",  # checksum None in index
            artifact_sha256="sha256:whatever",
            code_ref="nilearn_connectivity_matrix",
        )
    ]
    [v] = validate_claim_provenance(claims, _index())
    assert v.ok
    assert v.artifact_hash_matches is None


@pytest.mark.unit
def test_unknown_code_ref_fails():
    claims = [
        ClaimProvenance(
            claim_id="c1",
            artifact_path="derivatives/fc/netmats1.npy",
            code_ref="some_tool_that_never_ran",
        )
    ]
    [v] = validate_claim_provenance(claims, _index())
    assert not v.ok and not v.code_resolved


@pytest.mark.unit
def test_bare_tool_resolves_against_step_scoped_ref():
    claims = [
        ClaimProvenance(
            claim_id="c1",
            artifact_path="derivatives/fc/netmats1.npy",
            code_ref="nilearn_connectivity_matrix",  # index has tool:step_2 too
        )
    ]
    [v] = validate_claim_provenance(claims, _index())
    assert v.code_resolved and v.ok


@pytest.mark.unit
def test_require_full_false_allows_artifact_only():
    claims = [ClaimProvenance(claim_id="c1", artifact_path="derivatives/fc/netmats1.npy")]
    [v] = validate_claim_provenance(claims, _index(), require_full=False)
    assert v.has_provenance and v.ok


@pytest.mark.unit
def test_build_index_from_bundle():
    bundle = CodeReviewBundle(
        plan_steps=[{"tool": "nilearn_connectivity_matrix", "step_id": "step_2"}],
        observed_artifacts={
            "analysis_bundle": {
                "file_manifest": [
                    {
                        "role": "trace",
                        "path": "derivatives/fc/netmats1.npy",
                        "checksum": "sha256:ABC123",
                    }
                ]
            },
            "provenance": {
                "outputs": [{"uri": "report/fig1.png", "sha256": "sha256:def456"}]
            },
        },
    )
    index = build_run_provenance_index(bundle)
    assert index.artifacts["derivatives/fc/netmats1.npy"] == "abc123"  # normalized
    assert index.artifacts["report/fig1.png"] == "def456"
    assert index.resolves_code("nilearn_connectivity_matrix")
    assert "nilearn_connectivity_matrix:step_2" in index.code_refs


@pytest.mark.unit
def test_gate_returns_none_without_claims():
    assert build_claim_provenance_gate([], _index()) is None
    assert build_claim_provenance_gate(None, _index()) is None


@pytest.mark.unit
def test_gate_blocks_unsupported_claim_under_confirmatory():
    gate = build_claim_provenance_gate(
        [{"claim_id": "c1", "statement": "x", "artifact_path": "ghost.npy"}],
        _index(),
        claim_mode="confirmatory",
    )
    assert gate["blocked"] is True
    assert gate["unsupported_ids"] == ["c1"]
    assert "section_text" in gate
    assert gate["finding"]["rule_id"] == "REVIEW_CLAIM_PROVENANCE_UNVERIFIED"
    assert gate["finding"]["severity"] == "critical"
    assert gate["finding"]["action"] == "block"


@pytest.mark.unit
def test_gate_caveats_unsupported_claim_under_exploratory():
    gate = build_claim_provenance_gate(
        [{"claim_id": "c1", "artifact_path": "ghost.npy"}],
        _index(),
        claim_mode="exploratory",
    )
    assert gate["blocked"] is False
    assert "section_text" in gate  # still surfaced as a caveat
    assert "finding" not in gate  # but does not block


@pytest.mark.unit
def test_gate_require_flag_blocks_even_when_exploratory():
    gate = build_claim_provenance_gate(
        [{"claim_id": "c1", "artifact_path": "ghost.npy"}],
        _index(),
        claim_mode="exploratory",
        require_claim_provenance=True,
    )
    assert gate["blocked"] is True
    assert "finding" in gate


@pytest.mark.unit
def test_gate_passes_when_all_claims_traceable():
    gate = build_claim_provenance_gate(
        [
            {
                "claim_id": "c1",
                "artifact_path": "derivatives/fc/netmats1.npy",
                "artifact_sha256": "abc123",
                "code_ref": "nilearn_connectivity_matrix",
            }
        ],
        _index(),
        claim_mode="confirmatory",
    )
    assert gate["checked"] == 1
    assert gate["unsupported_ids"] == []
    assert gate["blocked"] is False
    assert "section_text" not in gate and "finding" not in gate


@pytest.mark.unit
def test_coerce_claims_handles_nested_provenance_and_missing_id():
    claims = coerce_claims(
        [
            {
                "statement": "x",
                "provenance": {
                    "artifact_path": "a.npy",
                    "code_ref": "tool_a",
                },
            },
            ClaimProvenance(claim_id="explicit", artifact_path="b.npy"),
        ]
    )
    assert claims[0].claim_id == "claim_0"
    assert claims[0].artifact_path == "a.npy" and claims[0].code_ref == "tool_a"
    assert claims[1].claim_id == "explicit"
