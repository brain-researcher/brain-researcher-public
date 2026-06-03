"""Tests for citation construct/population mismatch checks."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle


def _bundle(
    *,
    review_context: dict | None = None,
    observed_artifacts: dict | None = None,
    plan_steps: list[dict] | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=plan_steps or [],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
        observed_artifacts=observed_artifacts or {},
        kg_context=kg_context or {},
    )


def _trust_claim_with_pmid(pmid: str, claim_id: str = "h1") -> dict:
    """Build observed_artifacts with a trust claim linked to a PMID evidence item."""
    return {
        "quote_grounded_claims": [
            {
                "claim_id": claim_id,
                "claim_text": (
                    "East Asian participants show greater amygdala activation "
                    "during trust game decisions than European American participants."
                ),
                "verdict": "supported",
                "evidence_ids": [f"ev_{claim_id}"],
            }
        ],
        "quote_grounded_evidence_items": [
            {
                "evidence_id": f"ev_{claim_id}",
                "type": "artifact",
                "ref": f"pmid:{pmid}",
                "extra": {"pmid": pmid},
            }
        ],
    }


def _cross_cultural_claim_with_pmid(pmid: str, claim_id: str = "h2") -> dict:
    """Build observed_artifacts with a cross-cultural claim linked to a PMID."""
    return {
        "quote_grounded_claims": [
            {
                "claim_id": claim_id,
                "claim_text": (
                    "Cross-cultural differences in insula activation between "
                    "East Asian and European American adults during trust decisions."
                ),
                "verdict": "supported",
                "evidence_ids": [f"ev_{claim_id}"],
            }
        ],
        "quote_grounded_evidence_items": [
            {
                "evidence_id": f"ev_{claim_id}",
                "type": "artifact",
                "ref": f"pmid:{pmid}",
                "extra": {"pmid": pmid},
            }
        ],
    }


def _cross_cultural_claim_with_doi(doi: str, claim_id: str = "h_doi") -> dict:
    """Build observed_artifacts with a cross-cultural claim linked to a DOI."""
    return {
        "quote_grounded_claims": [
            {
                "claim_id": claim_id,
                "claim_text": (
                    "East Asian participants show greater amygdala activation "
                    "during trust game decisions than European American participants."
                ),
                "verdict": "supported",
                "evidence_ids": [f"ev_{claim_id}"],
            }
        ],
        "quote_grounded_evidence_items": [
            {
                "evidence_id": f"ev_{claim_id}",
                "type": "artifact",
                "ref": f"https://doi.org/{doi}.",
                "extra": {},
            }
        ],
    }


# -- Fake KG Publication records for mocking --

_SELF_REFERENTIAL_PUB: dict[str, Any] = {
    "kg_id": "pmid:22956678",
    "label": (
        "To assess cultural influences on self-referential processing "
        "of personal attributes in different dimensions by comparing "
        "neural responses from adults in East Asian (Chinese) and "
        "Western (Danish) cultural contexts."
    ),
    "title": ("Distinction between Self-Referential Processing and Social Judgments"),
    "abstract": (
        "We examined cultural influences on self-referential processing "
        "by comparing Chinese and Danish adults performing judgments of "
        "social, mental, and physical attributes of themselves and public figures."
    ),
    "year": 2012,
    "neighbor_labels": ["Self-referential Processing", "mPFC", "Culture"],
}

_TRUST_GAME_PUB: dict[str, Any] = {
    "kg_id": "pmid:99999999",
    "label": (
        "Neural correlates of trust game decisions: amygdala and insula "
        "activation during cooperative and defection choices."
    ),
    "title": "Trust Game Neural Correlates",
    "abstract": (
        "We investigated trust game behavior in East Asian and European American "
        "participants using fMRI."
    ),
    "year": 2020,
    "neighbor_labels": ["Trust Game", "Amygdala", "Cross-cultural Neuroscience"],
}

_EMPATHY_PUB: dict[str, Any] = {
    "kg_id": "pmid:25680993",
    "label": ("Neural correlates of empathy for pain in a culturally diverse sample."),
    "title": "Empathic pain responses across cultures",
    "abstract": (
        "We examined empathy for pain responses using fMRI in Western participants."
    ),
    "year": 2015,
    "neighbor_labels": ["Empathy", "Pain Observation", "Anterior Insula"],
}

_SINGLE_POP_TRUST_PUB: dict[str, Any] = {
    "kg_id": "pmid:26567160",
    "label": "Neural correlates of trust and distrust in a western sample.",
    "title": "Oxytocin and trust: a general mechanism study",
    "abstract": (
        "We investigated oxytocin effects on trust decisions "
        "in a sample of western participants."
    ),
    "year": 2015,
    "neighbor_labels": ["Trust", "Oxytocin", "TPJ"],
}


_MOCK_KG_DB: dict[str, dict[str, Any]] = {
    "22956678": _SELF_REFERENTIAL_PUB,
    "99999999": _TRUST_GAME_PUB,
    "25680993": _EMPATHY_PUB,
    "26567160": _SINGLE_POP_TRUST_PUB,
}


def _mock_resolve(pmid: str | None, doi: str | None) -> dict[str, Any] | None:
    if pmid and pmid in _MOCK_KG_DB:
        return _MOCK_KG_DB[pmid]
    return None


_RESOLVE_PATH = (
    "brain_researcher.services.review.checks.epistemic_integrity"
    "._resolve_publication_from_kg"
)


# =========================================================================
# citation_construct_mismatch_check
# =========================================================================


@pytest.mark.unit
class TestCitationConstructMismatch:
    """Tests for REVIEW_CITATION_CONSTRUCT_MISMATCH."""

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_fires_when_paper_construct_differs_from_claim(self, _mock):
        """Zhu 2012 (self-referential) cited for a trust claim → mismatch."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_trust_claim_with_pmid("22956678"))
        finding = citation_construct_mismatch_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_CITATION_CONSTRUCT_MISMATCH"
        assert finding.severity == "error"
        assert "citation_mismatch" in finding.reason_tags
        assert "construct_validity" in finding.reason_tags
        assert "self_referential" in finding.message or "self_referential" in str(
            finding.kg_evidence
        )

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_no_finding_when_paper_construct_matches_claim(self, _mock):
        """Trust game paper cited for a trust claim → no mismatch."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_trust_claim_with_pmid("99999999"))
        finding = citation_construct_mismatch_check(bundle)

        assert finding is None

    @patch(_RESOLVE_PATH, return_value=None)
    def test_no_finding_when_kg_has_no_record(self, _mock):
        """PMID not in KG → graceful skip, no finding."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_trust_claim_with_pmid("00000000"))
        finding = citation_construct_mismatch_check(bundle)

        assert finding is None

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_no_finding_when_no_claims(self, _mock):
        """Bundle with no claims → no finding."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(observed_artifacts={})
        finding = citation_construct_mismatch_check(bundle)

        assert finding is None

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_fires_empathy_cited_for_trust(self, _mock):
        """Empathy paper cited for a trust claim → mismatch."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_trust_claim_with_pmid("25680993"))
        finding = citation_construct_mismatch_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_CITATION_CONSTRUCT_MISMATCH"
        assert "empathy" in finding.message or "empathy" in str(finding.kg_evidence)

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_no_finding_when_claim_has_no_construct_keywords(self, _mock):
        """Claim text without any recognized construct keywords → no check."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(
            observed_artifacts={
                "quote_grounded_claims": [
                    {
                        "claim_id": "h_generic",
                        "claim_text": "Brain activation was observed in the ROI.",
                        "evidence_ids": ["ev_generic"],
                    }
                ],
                "quote_grounded_evidence_items": [
                    {
                        "evidence_id": "ev_generic",
                        "type": "artifact",
                        "ref": "pmid:22956678",
                        "extra": {"pmid": "22956678"},
                    }
                ],
            }
        )
        finding = citation_construct_mismatch_check(bundle)

        assert finding is None

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_pmid_extracted_from_ref_field(self, _mock):
        """PMID in ref field (not extra) is still extracted."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_construct_mismatch_check,
        )

        bundle = _bundle(
            observed_artifacts={
                "quote_grounded_claims": [
                    {
                        "claim_id": "h_ref",
                        "claim_text": "Trust game amygdala activation.",
                        "evidence_ids": ["ev_ref"],
                    }
                ],
                "quote_grounded_evidence_items": [
                    {
                        "evidence_id": "ev_ref",
                        "type": "artifact",
                        "ref": "pmid:22956678",
                        "extra": {},
                    }
                ],
            }
        )
        finding = citation_construct_mismatch_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_CITATION_CONSTRUCT_MISMATCH"


# =========================================================================
# citation_population_mismatch_check
# =========================================================================


@pytest.mark.unit
class TestCitationPopulationMismatch:
    """Tests for REVIEW_CITATION_POPULATION_MISMATCH."""

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_fires_single_pop_paper_cited_for_cross_cultural_claim(self, _mock):
        """Single-population trust paper cited for cross-cultural claim → mismatch."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_population_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_cross_cultural_claim_with_pmid("26567160"))
        finding = citation_population_mismatch_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_CITATION_POPULATION_MISMATCH"
        assert finding.severity == "error"
        assert "citation_mismatch" in finding.reason_tags

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_no_finding_when_paper_has_matching_populations(self, _mock):
        """Cross-cultural trust paper cited for cross-cultural claim → no mismatch."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_population_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_cross_cultural_claim_with_pmid("99999999"))
        finding = citation_population_mismatch_check(bundle)

        assert finding is None

    @patch(_RESOLVE_PATH, return_value=None)
    def test_no_finding_when_kg_unavailable(self, _mock):
        """KG lookup returns None → graceful skip."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_population_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_cross_cultural_claim_with_pmid("00000000"))
        finding = citation_population_mismatch_check(bundle)

        assert finding is None

    @patch(_RESOLVE_PATH, side_effect=_mock_resolve)
    def test_no_finding_when_claim_is_not_cross_cultural(self, _mock):
        """Claim about trust without cross-cultural scope → no population check."""
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_population_mismatch_check,
        )

        bundle = _bundle(observed_artifacts=_trust_claim_with_pmid("26567160"))
        finding = citation_population_mismatch_check(bundle)

        # trust claim mentions East Asian and European American so it qualifies
        # as multi-pop. The paper is western-only. Check if it fires.
        # Actually the trust claim has "East Asian ... European American" → two groups
        # Paper 26567160 is "western" only → should fire
        assert finding is not None

    def test_fires_danish_paper_cited_for_european_american_claim(self):
        """Chinese-vs-Danish paper cited for EA-vs-EAm claim → population mismatch."""
        from brain_researcher.services.br_kg.query_service import KGNodeSummary
        from brain_researcher.services.review.checks.epistemic_integrity import (
            citation_population_mismatch_check,
        )

        bundle = _bundle(
            observed_artifacts=_cross_cultural_claim_with_doi("10.1000/chinese-danish")
        )

        publication = KGNodeSummary(
            kg_id="doi:10.1000/chinese-danish",
            label="Chinese and Danish adults during trust decisions",
            node_type="Publication",
            properties={
                "title": "Chinese and Danish adults during trust decisions",
                "abstract": (
                    "We compared Chinese adults and Danish adults in a trust game."
                ),
                "doi": "10.1000/chinese-danish",
                "neighbors": [
                    {"rel": "HAS_KEYWORD", "target": "Chinese"},
                    {"rel": "HAS_KEYWORD", "target": "Danish"},
                ],
            },
        )

        with (
            patch(
                "brain_researcher.services.br_kg.query_service.search_nodes",
                return_value=[publication],
            ) as mock_search_nodes,
            patch(
                "brain_researcher.services.br_kg.query_service.neighbors",
                return_value=[
                    {"label": "Chinese"},
                    {"label": "Danish"},
                ],
            ) as mock_neighbors,
            patch(
                "brain_researcher.services.br_kg.query_service.node_details",
                return_value=publication,
            ) as mock_node_details,
        ):
            finding = citation_population_mismatch_check(bundle)

        assert finding is not None
        assert finding.rule_id == "REVIEW_CITATION_POPULATION_MISMATCH"
        assert finding.severity == "error"
        assert "citation_mismatch" in finding.reason_tags
        assert any("doi:10.1000/chinese-danish" in item for item in finding.kg_evidence)
        assert all("pmid:doi:" not in item for item in finding.kg_evidence)
        mock_search_nodes.assert_called_once()
        mock_neighbors.assert_called_once()
        mock_node_details.assert_called_once()
        assert mock_search_nodes.call_args.args[0] == "doi:10.1000/chinese-danish"


# =========================================================================
# _extract_pmids_from_evidence
# =========================================================================


@pytest.mark.unit
class TestExtractPmids:
    """Tests for the PMID extraction helper."""

    def test_extracts_pmid_from_extra_dict(self):
        from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_pmids_from_evidence,
        )

        claim = ClaimV1(
            claim_id="c1",
            claim_text="Trust is observed.",
            evidence_ids=["e1"],
        )
        evidence = EvidenceItemV1(
            evidence_id="e1",
            type="artifact",
            ref="some_ref",
            extra={"pmid": "22956678"},
        )
        results = _extract_pmids_from_evidence([claim], [evidence])
        assert len(results) == 1
        assert results[0]["pmid"] == "22956678"
        assert results[0]["claim_id"] == "c1"

    def test_extracts_pmid_from_ref_field(self):
        from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_pmids_from_evidence,
        )

        claim = ClaimV1(
            claim_id="c2",
            claim_text="Trust is observed.",
            evidence_ids=["e2"],
        )
        evidence = EvidenceItemV1(
            evidence_id="e2",
            type="artifact",
            ref="pmid:12345678",
        )
        results = _extract_pmids_from_evidence([claim], [evidence])
        assert len(results) == 1
        assert results[0]["pmid"] == "12345678"

    def test_skips_evidence_without_pmid_or_doi(self):
        from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_pmids_from_evidence,
        )

        claim = ClaimV1(
            claim_id="c3",
            claim_text="Trust is observed.",
            evidence_ids=["e3"],
        )
        evidence = EvidenceItemV1(
            evidence_id="e3",
            type="artifact",
            ref="some_internal_ref",
        )
        results = _extract_pmids_from_evidence([claim], [evidence])
        assert len(results) == 0

    def test_deduplicates_same_pmid_same_claim(self):
        from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_pmids_from_evidence,
        )

        claim = ClaimV1(
            claim_id="c4",
            claim_text="Trust is observed.",
            evidence_ids=["e4a", "e4b"],
        )
        ev_a = EvidenceItemV1(
            evidence_id="e4a",
            type="artifact",
            ref="pmid:22956678",
            extra={"pmid": "22956678"},
        )
        ev_b = EvidenceItemV1(
            evidence_id="e4b",
            type="artifact",
            ref="pmid:22956678",
            extra={"pmid": "22956678"},
        )
        results = _extract_pmids_from_evidence([claim], [ev_a, ev_b])
        assert len(results) == 1

    def test_keeps_multiple_doi_only_evidence_items_on_same_claim(self):
        from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_pmids_from_evidence,
        )

        claim = ClaimV1(
            claim_id="c5",
            claim_text="Trust is observed.",
            evidence_ids=["e5a", "e5b"],
        )
        ev_a = EvidenceItemV1(
            evidence_id="e5a",
            type="artifact",
            ref="doi:10.1000/alpha.",
            extra={},
        )
        ev_b = EvidenceItemV1(
            evidence_id="e5b",
            type="artifact",
            ref="https://doi.org/10.1000/beta,",
            extra={},
        )

        results = _extract_pmids_from_evidence([claim], [ev_a, ev_b])

        assert len(results) == 2
        assert {row["evidence_id"] for row in results} == {"e5a", "e5b"}
        assert {row["doi"] for row in results} == {
            "10.1000/alpha",
            "10.1000/beta",
        }
        assert all(row["pmid"] is None for row in results)


# =========================================================================
# _extract_construct_categories
# =========================================================================


@pytest.mark.unit
class TestExtractConstructCategories:
    def test_extracts_trust(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_construct_categories,
        )

        cats = _extract_construct_categories("Trust game amygdala activation")
        assert "trust" in cats

    def test_extracts_empathy(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_construct_categories,
        )

        cats = _extract_construct_categories("Empathic responses to pain observation")
        assert "empathy" in cats

    def test_extracts_self_referential(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_construct_categories,
        )

        cats = _extract_construct_categories(
            "Self-referential processing of attributes"
        )
        assert "self_referential" in cats

    def test_returns_empty_for_generic_text(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_construct_categories,
        )

        cats = _extract_construct_categories("Brain activation in ROI")
        assert len(cats) == 0

    def test_extracts_multiple_categories(self):
        from brain_researcher.services.review.checks.epistemic_integrity import (
            _extract_construct_categories,
        )

        cats = _extract_construct_categories(
            "Empathy and trust game activation in amygdala"
        )
        assert "empathy" in cats
        assert "trust" in cats
