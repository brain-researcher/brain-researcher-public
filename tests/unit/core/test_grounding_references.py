from __future__ import annotations

from brain_researcher.core.grounding_references import (
    anchors_from_gfs_hits,
    gate_evidence_basis,
    reference_kind,
    resolve_reference,
)


def test_gfs_hit_emits_typed_document_and_citation_anchors() -> None:
    anchors = anchors_from_gfs_hits(
        [
            {
                "doc_id": "fileSearchStores/papers/files/m4_pubget_papers_bundle_00012.txt",
                "title": "Reverse inference review",
                "snippet": "Reverse inference depends on selectivity.",
                "text": "Reverse inference depends on selectivity and base rates.",
                "doi": "10.1016/j.tics.2005.12.004",
                "pmid": "16406760",
                "score": 0.91,
            }
        ]
    )

    anchor_ids = [anchor["anchor_id"] for anchor in anchors]
    assert anchor_ids == [
        "doc:fileSearchStores/papers/files/m4_pubget_papers_bundle_00012.txt",
        "doi:10.1016/j.tics.2005.12.004",
        "pmid:16406760",
    ]
    assert anchors[0]["anchor_type"] == "retrieved_document"
    assert anchors[0]["doi"] == "10.1016/j.tics.2005.12.004"
    assert anchors[0]["pmid"] == "16406760"
    assert anchors[1]["anchor_type"] == "specific_citation"


def test_reference_kind_rejects_mixed_doi_pmid_string() -> None:
    assert (
        reference_kind("DOI:10.1016/j.tics.2005.12.004; PMID:16406760") == "malformed"
    )


def test_gate_keeps_resolved_anchor_and_downgrades_unresolved_doc() -> None:
    resolved_anchor = {
        "anchor_id": "doc:fileSearchStores/papers/files/doc-1.txt",
        "anchor_type": "retrieved_document",
        "support_text": (
            "Nested cross-validation prevents leakage. "
            "A copied doc anchor should determine the grounded type."
        ),
    }
    result = gate_evidence_basis(
        [
            {
                "claim": "Nested CV prevents leakage.",
                "basis_type": "retrieved_document",
                "reference": "doc:fileSearchStores/papers/files/doc-1.txt",
                "verifiable": True,
            },
            {
                "claim": "A missing document is not grounded.",
                "basis_type": "retrieved_document",
                "reference": "doc:fileSearchStores/papers/files/missing.txt",
                "verifiable": True,
            },
            {
                "claim": "A copied doc anchor should determine the grounded type.",
                "basis_type": "uncertain",
                "reference": "doc:fileSearchStores/papers/files/doc-1.txt",
                "verifiable": True,
            },
        ],
        anchors=[resolved_anchor],
    )

    assert result["ok"] is True
    assert result["evidence_basis"][0]["basis_type"] == "retrieved_document"
    assert result["evidence_basis"][1]["basis_type"] == "uncertain"
    assert result["evidence_basis"][1]["reference"] is None
    assert result["evidence_basis"][2]["basis_type"] == "retrieved_document"
    assert result["degraded_count"] == 1


def test_gate_blocks_malformed_grounded_reference() -> None:
    result = gate_evidence_basis(
        [
            {
                "claim": "Reverse inference needs selectivity.",
                "basis_type": "specific_citation",
                "reference": "DOI:10.1016/j.tics.2005.12.004; PMID:16406760",
                "verifiable": True,
            }
        ]
    )

    assert result["ok"] is False
    assert result["errors"][0]["error"] == "malformed_reference"


def test_gate_requires_citation_to_come_from_anchor_set_when_available() -> None:
    result = gate_evidence_basis(
        [
            {
                "claim": "Anchored citation is grounded.",
                "basis_type": "specific_citation",
                "reference": "doi:10.1016/j.tics.2005.12.004",
                "verifiable": True,
            },
            {
                "claim": "Freehand citation is downgraded.",
                "basis_type": "specific_citation",
                "reference": "doi:10.1016/j.neuroimage.2008.09.050",
                "verifiable": True,
            },
        ],
        anchors=[
            {
                "anchor_id": "doi:10.1016/j.tics.2005.12.004",
                "anchor_type": "specific_citation",
                "support_text": "Anchored citation is grounded. Reverse inference depends on selectivity.",
            }
        ],
    )

    assert result["ok"] is True
    assert result["evidence_basis"][0]["basis_type"] == "specific_citation"
    assert result["evidence_basis"][1]["basis_type"] == "uncertain"
    assert result["resolutions"][1]["error"] == "reference_not_from_anchor_set"


def test_gate_downgrades_resolved_anchor_when_claim_does_not_match_support() -> None:
    result = gate_evidence_basis(
        [
            {
                "claim": "Nested cross-validation prevents train-test leakage.",
                "basis_type": "retrieved_document",
                "reference": "doc:fileSearchStores/papers/files/doc-1.txt",
                "verifiable": True,
            },
            {
                "claim": "Amygdala activation proves fear is present.",
                "basis_type": "retrieved_document",
                "reference": "doc:fileSearchStores/papers/files/doc-2.txt",
                "verifiable": True,
            },
        ],
        anchors=[
            {
                "anchor_id": "doc:fileSearchStores/papers/files/doc-1.txt",
                "anchor_type": "retrieved_document",
                "support_text": "Nested cross-validation prevents leakage across train and test data.",
            },
            {
                "anchor_id": "doc:fileSearchStores/papers/files/doc-2.txt",
                "anchor_type": "retrieved_document",
                "support_text": "Cluster correction controls family-wise error in fMRI analyses.",
            },
        ],
    )

    assert result["ok"] is True
    assert result["evidence_basis"][0]["basis_type"] == "retrieved_document"
    assert result["evidence_basis"][1]["basis_type"] == "uncertain"
    assert result["evidence_basis"][1]["reference"] is None
    assert (
        result["evidence_basis"][1]["gate_note"]
        == "claim was not supported by anchor text"
    )
    assert result["alignment"]["checked"] == 2
    assert result["alignment"]["yes"] == 1
    assert result["alignment"]["no_unrelated"] == 1
    assert result["alignment"]["downgraded_by_alignment"] == 1
    assert result["coverage"]["grounded_in"] == 2
    assert result["coverage"]["grounded_out"] == 1


def test_gate_can_mark_partial_alignment_unverifiable_instead_of_downgrading() -> None:
    result = gate_evidence_basis(
        [
            {
                "claim": "Nested cross-validation prevents optimistic leakage.",
                "basis_type": "retrieved_document",
                "reference": "doc:fileSearchStores/papers/files/doc-1.txt",
                "verifiable": True,
            }
        ],
        anchors=[
            {
                "anchor_id": "doc:fileSearchStores/papers/files/doc-1.txt",
                "anchor_type": "retrieved_document",
                "support_text": "Nested models require held-out evaluation.",
            }
        ],
        partial_action="mark_unverifiable",
    )

    assert result["ok"] is True
    assert result["evidence_basis"][0]["basis_type"] == "retrieved_document"
    assert result["evidence_basis"][0]["verifiable"] is False
    assert result["evidence_basis"][0]["gate_note"] == "partial claim-anchor overlap"
    assert result["alignment"]["partial"] == 1
    assert result["alignment"]["downgraded_by_alignment"] == 0


def test_resolve_kg_and_session_refs_from_maps() -> None:
    kg = resolve_reference(
        "kg:reverse_inference_region_process_many_to_many",
        kg_resolver={
            "kg:reverse_inference_region_process_many_to_many": (
                "Region-process mappings are many-to-many."
            )
        },
    )
    session = resolve_reference(
        "session:claim_card_abc123",
        session_resolver={"session:claim_card_abc123": "Prior claim support text."},
    )

    assert kg["resolved"] is True
    assert kg["support_text"] == "Region-process mappings are many-to-many."
    assert session["resolved"] is True
    assert session["support_text"] == "Prior claim support text."


def test_resolve_kg_and_session_refs_from_lookup_callbacks() -> None:
    kg = resolve_reference(
        "kg:node-123",
        kg_lookup=lambda kg_id: {
            "support_text": f"KG node {kg_id}",
            "provenance": {"resolver": "test_kg_lookup"},
        },
    )
    session = resolve_reference(
        "session:claim-card-123",
        session_lookup=lambda card_ref: f"Session support for {card_ref}",
    )

    assert kg["resolved"] is True
    assert kg["support_text"] == "KG node node-123"
    assert kg["provenance"]["resolver"] == "test_kg_lookup"
    assert session["resolved"] is True
    assert session["support_text"] == "Session support for claim-card-123"
    assert session["provenance"]["resolver"] == "session_lookup"


# --- alignment_mode="judge": semantic gate (spam-resistant) ---

# Claim heavily echoes the support tokens -> lexical judge_parity scores "yes" and KEEPS it.
# This lets us prove the semantic judge mode OVERRIDES the lexical decision.
_JUDGE_EB = [
    {
        "claim": "Double dipping uses the same data for selection and selective analysis yielding invalid inference.",
        "basis_type": "retrieved_document",
        "reference": "doc:fileSearchStores/papers/files/doc-dd.txt",
        "verifiable": True,
    }
]
_JUDGE_ANCHORS = [
    {
        "anchor_id": "doc:fileSearchStores/papers/files/doc-dd.txt",
        "anchor_type": "retrieved_document",
        "support_text": (
            "Double dipping is the use of the same data for selection and selective analysis, "
            "which yields invalid statistical inference under the null hypothesis."
        ),
    }
]


def test_gate_lexical_keeps_high_overlap_claim() -> None:
    # baseline: lexical judge_parity keeps the high-overlap claim
    res = gate_evidence_basis(
        _JUDGE_EB, anchors=_JUDGE_ANCHORS, alignment_mode="judge_parity"
    )
    assert res["evidence_basis"][0]["basis_type"] == "retrieved_document"


def test_gate_judge_mode_downgrades_when_judge_rejects() -> None:
    res = gate_evidence_basis(
        _JUDGE_EB,
        anchors=_JUDGE_ANCHORS,
        alignment_mode="judge",
        alignment_judge=lambda claim, support: "no_unrelated",
    )
    assert res["alignment"]["mode"] == "judge"
    assert res["evidence_basis"][0]["basis_type"] == "uncertain"
    assert res["evidence_basis"][0]["reference"] is None
    assert res["alignment"]["downgraded_by_alignment"] == 1
    assert res["alignment"]["per_row"][0]["alignment_source"] == "llm_judge"


def test_gate_judge_mode_keeps_when_judge_accepts() -> None:
    res = gate_evidence_basis(
        _JUDGE_EB,
        anchors=_JUDGE_ANCHORS,
        alignment_mode="judge",
        alignment_judge=lambda claim, support: "yes",
    )
    assert res["evidence_basis"][0]["basis_type"] == "retrieved_document"
    assert res["alignment"]["per_row"][0]["alignment_source"] == "llm_judge"


def test_gate_judge_mode_falls_back_to_lexical_without_judge() -> None:
    res = gate_evidence_basis(_JUDGE_EB, anchors=_JUDGE_ANCHORS, alignment_mode="judge")
    assert res["alignment"]["mode"] == "judge_parity"  # no judge supplied -> lexical
    assert res["evidence_basis"][0]["basis_type"] == "retrieved_document"


def test_gate_judge_mode_never_crashes_when_judge_raises() -> None:
    def boom(claim: str, support: str) -> str:
        raise RuntimeError("judge down")

    res = gate_evidence_basis(
        _JUDGE_EB,
        anchors=_JUDGE_ANCHORS,
        alignment_mode="judge",
        alignment_judge=boom,
    )
    # gate must still return; failed judge falls back to lexical for the label and records the error
    assert "evidence_basis" in res
    assert any(
        "alignment_judge_failed" in str(e.get("error", "")) for e in res["errors"]
    )
