"""Tests for the best-effort claim artifact-provenance producer.

Verifies that a claim whose evidence maps to a manifest artifact gets
``extra['artifact_provenance']`` carrying the manifest path + sha (and the
matching evidence item's ``provenance_ref`` is populated), while a claim with
no manifest match is honestly left unprovenanced.
"""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
from brain_researcher.core.contracts.evidence_item import EvidenceType
from brain_researcher.services.review.claim_provenance_producer import (
    attach_claim_artifact_provenance,
)

_MANIFEST = [
    {
        "role": "artifact",
        "path": "derivatives/fc/netmats1.npy",
        "checksum": "sha256:abc123def456",
    },
    {
        "role": "artifact",
        "path": "report/fig1.png",
        "checksum": "sha256:ffffffffffff",
    },
]

_PLAN_STEPS = [
    {
        "tool": "nilearn_connectivity_matrix",
        "step_id": "step_2",
        "params": {"output_dir": "derivatives/fc"},
    },
]


@pytest.mark.unit
def test_claim_with_matching_evidence_gets_artifact_provenance():
    evidence = EvidenceItemV1(
        evidence_id="ev1",
        type=EvidenceType.artifact,
        ref="derivatives/fc/netmats1.npy",
    )
    assert evidence.provenance_ref is None
    claim = ClaimV1(
        claim_id="c1",
        claim_text="Mean DMN FC = 0.42",
        evidence_ids=["ev1"],
    )

    summary = attach_claim_artifact_provenance(
        [claim],
        [evidence],
        file_manifest=_MANIFEST,
        plan_steps=_PLAN_STEPS,
    )

    prov = claim.extra.get("artifact_provenance")
    assert isinstance(prov, list) and len(prov) == 1
    record = prov[0]
    assert record["evidence_id"] == "ev1"
    assert record["artifact_path"] == "derivatives/fc/netmats1.npy"
    # sha256: prefix stripped, lower-cased, matches the manifest entry.
    assert record["artifact_sha256"] == "abc123def456"
    # code_ref derived from the producing plan step (params.output_dir match).
    assert record["code_ref"] == "nilearn_connectivity_matrix:step_2"

    # Evidence provenance_ref populated from the producing code ref.
    assert evidence.provenance_ref == "nilearn_connectivity_matrix:step_2"

    assert summary.claims_total == 1
    assert summary.claims_provenanced == 1
    assert summary.unprovenanced_claim_ids == []
    assert summary.evidence_refs_resolved == 1


@pytest.mark.unit
def test_claim_without_manifest_match_gets_no_provenance():
    evidence = EvidenceItemV1(
        evidence_id="ev_lit",
        type=EvidenceType.web,
        ref="https://example.org/paper",
    )
    claim = ClaimV1(
        claim_id="c_lit",
        claim_text="Prior work reports DMN hyperconnectivity",
        evidence_ids=["ev_lit"],
    )

    summary = attach_claim_artifact_provenance(
        [claim],
        [evidence],
        file_manifest=_MANIFEST,
        plan_steps=_PLAN_STEPS,
    )

    # No fabricated provenance for an unresolvable (web) reference.
    assert "artifact_provenance" not in claim.extra
    assert evidence.provenance_ref is None
    assert summary.claims_provenanced == 0
    assert summary.unprovenanced_claim_ids == ["c_lit"]
    assert summary.evidence_refs_resolved == 0


@pytest.mark.unit
def test_payload_ref_and_basename_resolution():
    # Evidence ref is a bare basename; resolves against the manifest basename key.
    evidence = EvidenceItemV1(
        evidence_id="ev_png",
        type=EvidenceType.file,
        ref="unrelated_label",
        payload_ref="fig1.png",
    )
    claim = ClaimV1(
        claim_id="c_fig",
        claim_text="Figure 1 shows the group map",
        evidence_ids=["ev_png"],
    )

    summary = attach_claim_artifact_provenance(
        [claim],
        [evidence],
        file_manifest=_MANIFEST,
        plan_steps=_PLAN_STEPS,
    )

    prov = claim.extra.get("artifact_provenance")
    assert isinstance(prov, list) and len(prov) == 1
    assert prov[0]["artifact_path"] == "report/fig1.png"
    assert prov[0]["artifact_sha256"] == "ffffffffffff"
    assert summary.claims_provenanced == 1


@pytest.mark.unit
def test_empty_manifest_leaves_all_claims_unprovenanced():
    evidence = EvidenceItemV1(
        evidence_id="ev1",
        type=EvidenceType.artifact,
        ref="derivatives/fc/netmats1.npy",
    )
    claim = ClaimV1(claim_id="c1", claim_text="x", evidence_ids=["ev1"])

    summary = attach_claim_artifact_provenance(
        [claim],
        [evidence],
        file_manifest=[],
        plan_steps=_PLAN_STEPS,
    )

    assert "artifact_provenance" not in claim.extra
    assert summary.unprovenanced_claim_ids == ["c1"]
    assert summary.claims_provenanced == 0
