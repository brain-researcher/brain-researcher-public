"""Deterministic epistemic integrity checks for claim artifacts."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from brain_researcher.core.contracts import (
    ClaimV1,
    EvidenceItemV1,
    EvidenceProvenanceV1,
)
from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding
from brain_researcher.core.epistemic_policy import (
    assess_claim_epistemics,
    validate_claim_epistemics,
)

logger = logging.getLogger(__name__)

_COORDINATE_COLUMNS = frozenset(
    {
        "mni",
        "mni coordinate",
        "mni_coordinates",
        "mni coordinates",
        "coordinate",
        "coordinates",
        "peak coordinate",
        "peak coordinates",
        "x",
        "y",
        "z",
    }
)
_GROUP_DIFFERENCE_COLUMNS = frozenset(
    {
        "group_difference",
        "group difference",
        "direct_comparison",
        "direct comparison",
        "between_group_difference",
        "between group difference",
    }
)
_DIRECTION_EXTRA_KEYS = (
    "predicted_direction",
    "direction",
    "comparison_direction",
    "contrast_direction",
)
_FAMILY_EXTRA_KEYS = (
    "hypothesis_id",
    "claim_family_id",
    "comparison_id",
    "target_region",
    "roi",
    "region",
    "task",
    "condition",
    "population",
    "context",
)
_ARROW_DIRECTION_RE = re.compile(
    r"\b(?P<lhs>[A-Za-z][A-Za-z0-9_/-]{0,39})\s*(?:>|&gt;)\s*(?P<rhs>[A-Za-z][A-Za-z0-9_/-]{0,39})\b"
)
_POSITIVE_DIRECTION_RE = re.compile(
    r"\b(?P<lhs>[A-Za-z][A-Za-z0-9_/-]{0,39})\b.{0,80}?\b"
    r"(?:greater|higher|stronger|larger|more|exceeds?)\b.{0,40}?\bthan\b\s+"
    r"(?P<rhs>[A-Za-z][A-Za-z0-9_/-]{0,39})\b",
    re.IGNORECASE,
)
_NEGATIVE_DIRECTION_RE = re.compile(
    r"\b(?P<lhs>[A-Za-z][A-Za-z0-9_/-]{0,39})\b.{0,80}?\b"
    r"(?:lower|weaker|less|smaller)\b.{0,40}?\bthan\b\s+"
    r"(?P<rhs>[A-Za-z][A-Za-z0-9_/-]{0,39})\b",
    re.IGNORECASE,
)
_NORMALIZE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _parse_claims(raw: Any) -> list[ClaimV1]:
    if not isinstance(raw, list):
        return []
    parsed: list[ClaimV1] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(ClaimV1.model_validate(item))
        except Exception:
            continue
    return parsed


def _parse_evidence_items(raw: Any) -> list[EvidenceItemV1]:
    if not isinstance(raw, list):
        return []
    parsed: list[EvidenceItemV1] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(EvidenceItemV1.model_validate(item))
        except Exception:
            continue
    return parsed


def _synthesized_claim_from_source_summary(bundle: CodeReviewBundle) -> list[ClaimV1]:
    summary = bundle.observed_artifacts.get("source_summary")
    if not isinstance(summary, dict):
        return []
    if not any(
        key in summary
        for key in (
            "claim_verdict",
            "evidence_provenance",
            "direct_statistical_test",
            "epistemic_confidence_tier",
        )
    ):
        return []

    claim_text = str(
        summary.get("claim_text")
        or summary.get("summary_text")
        or summary.get("top_contrast")
        or summary.get("task_label")
        or "external_review_claim"
    ).strip()
    if not claim_text:
        claim_text = "external_review_claim"

    try:
        claim = ClaimV1.model_validate(
            {
                "claim_id": "source_summary_claim",
                "claim_text": claim_text,
                "verdict": summary.get("claim_verdict"),
                "epistemic_confidence_tier": summary.get("epistemic_confidence_tier"),
                "evidence_provenance": summary.get("evidence_provenance"),
                "claim_scope": summary.get("claim_scope"),
                "raw_data_available": summary.get("raw_data_available"),
                "direct_statistical_test": summary.get("direct_statistical_test"),
                "evidence_ids": [],
            }
        )
    except Exception:
        return []
    return [claim]


def load_review_claims_and_evidence(
    bundle: CodeReviewBundle,
) -> tuple[list[ClaimV1], list[EvidenceItemV1], str]:
    claims = _parse_claims(bundle.observed_artifacts.get("quote_grounded_claims"))
    evidence_items = _parse_evidence_items(
        bundle.observed_artifacts.get("quote_grounded_evidence_items")
    )
    claim_source = "quote_grounded_claims"

    if not claims:
        claims = _synthesized_claim_from_source_summary(bundle)
        if claims:
            claim_source = "source_summary_synthesized"

    return claims, evidence_items, claim_source


def _normalize_token(value: Any) -> str:
    lowered = _NORMALIZE_TOKEN_RE.sub(" ", str(value or "").strip().lower())
    return " ".join(lowered.split())


def _iter_artifact_nodes(value: Any, path: str) -> list[tuple[str, Any]]:
    nodes: list[tuple[str, Any]] = [(path, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            nodes.extend(_iter_artifact_nodes(item, child_path))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            child_path = f"{path}[{idx}]"
            nodes.extend(_iter_artifact_nodes(item, child_path))
    return nodes


def _normalized_columns(node: Any) -> set[str]:
    columns: set[str] = set()
    if isinstance(node, dict):
        columns.update(_normalize_token(key) for key in node.keys())
        for key in ("columns", "headers", "fields"):
            raw = node.get(key)
            if isinstance(raw, list):
                columns.update(_normalize_token(item) for item in raw)
    elif isinstance(node, list):
        if node and all(isinstance(item, dict) for item in node[:3]):
            for row in node[:3]:
                columns.update(_normalize_token(key) for key in row.keys())
    return {column for column in columns if column}


def _node_mentions_group_difference_coordinate_table(node: Any) -> bool:
    if isinstance(node, str):
        lowered = _normalize_token(node)
        return (
            any(label in lowered for label in _GROUP_DIFFERENCE_COLUMNS)
            and any(label in lowered for label in ("mni", "coordinate", "coordinates"))
        )

    columns = _normalized_columns(node)
    if not columns:
        return False
    return bool(columns & _GROUP_DIFFERENCE_COLUMNS) and bool(columns & _COORDINATE_COLUMNS)


def find_cross_study_coordinate_comparison_paths(
    bundle: CodeReviewBundle,
    *,
    claims: list[ClaimV1] | None = None,
    evidence_items: list[EvidenceItemV1] | None = None,
) -> list[str]:
    review_claims = claims
    review_evidence = evidence_items
    if review_claims is None or review_evidence is None:
        review_claims, review_evidence, _ = load_review_claims_and_evidence(bundle)

    if not any(
        (
            assessment.evidence_provenance == EvidenceProvenanceV1.cross_study_inference
            and assessment.direct_statistical_test is not True
        )
        for assessment in (
            assess_claim_epistemics(claim, review_evidence) for claim in review_claims
        )
    ):
        return []

    paths: list[str] = []
    for artifact_name, payload in bundle.observed_artifacts.items():
        for path, node in _iter_artifact_nodes(payload, artifact_name):
            if _node_mentions_group_difference_coordinate_table(node):
                paths.append(path)
    return paths


def _extract_direction_expression(claim: ClaimV1) -> str | None:
    extra = claim.extra if isinstance(claim.extra, dict) else {}
    for key in _DIRECTION_EXTRA_KEYS:
        text = str(extra.get(key) or "").strip()
        if text:
            return text
    return claim.claim_text


def _parse_direction(value: str | None) -> tuple[str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None

    for pattern, reverse in (
        (_ARROW_DIRECTION_RE, False),
        (_POSITIVE_DIRECTION_RE, False),
        (_NEGATIVE_DIRECTION_RE, True),
    ):
        match = pattern.search(text)
        if not match:
            continue
        lhs = _normalize_token(match.group("lhs"))
        rhs = _normalize_token(match.group("rhs"))
        if not lhs or not rhs or lhs == rhs:
            return None
        if reverse:
            lhs, rhs = rhs, lhs
        return lhs, rhs
    return None


def _direction_family_key(claim: ClaimV1, winner: str, loser: str) -> str:
    extra = claim.extra if isinstance(claim.extra, dict) else {}
    family_parts = [
        _normalize_token(extra.get(key))
        for key in _FAMILY_EXTRA_KEYS
        if _normalize_token(extra.get(key))
    ]
    pair_key = "|".join(sorted([winner, loser]))
    if family_parts:
        return "|".join([pair_key, *family_parts])
    return pair_key


def find_directional_claim_conflicts(
    claims: list[ClaimV1],
    evidence_items: list[EvidenceItemV1],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for claim in claims:
        direction = _parse_direction(_extract_direction_expression(claim))
        if direction is None:
            continue
        winner, loser = direction
        family_key = _direction_family_key(claim, winner, loser)
        label = f"{winner} > {loser}"
        assessment = assess_claim_epistemics(claim, evidence_items)
        buckets[family_key][label].append(
            {
                "claim_id": claim.claim_id,
                "claim_text": claim.claim_text,
                "evidence_provenance": assessment.evidence_provenance.value,
                "direct_statistical_test": assessment.direct_statistical_test,
            }
        )

    conflicts: list[dict[str, Any]] = []
    for family_key, direction_rows in buckets.items():
        if len(direction_rows) <= 1:
            continue
        conflicts.append(
            {
                "family_key": family_key,
                "directions": dict(sorted(direction_rows.items())),
            }
        )
    return conflicts


def epistemic_claim_policy_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Reject over-strong verdict labels unsupported by evidence provenance."""

    claims, evidence_items, _ = load_review_claims_and_evidence(bundle)

    if not claims:
        return None

    issues: list[str] = []
    for claim in claims:
        issues.extend(validate_claim_epistemics(claim, evidence_items))

    if not issues:
        return None

    verdict_issue = any("uses verdict" in issue for issue in issues)
    return ReviewFinding(
        rule_id="REVIEW_EPISTEMIC_CLAIM_POLICY",
        severity="error" if verdict_issue else "warn",
        message=issues[0],
        suggested_fix=(
            "Downgrade the claim label to an allowed indirect/predictive verdict "
            "or attach direct single-study statistical evidence before using "
            "SUPPORTED/REFUTED language."
        ),
        kg_evidence=issues[:3],
    )


def cross_study_coordinate_comparison_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    paths = find_cross_study_coordinate_comparison_paths(bundle)
    if not paths:
        return None
    return ReviewFinding(
        rule_id="REVIEW_CROSS_STUDY_COORDINATE_COMPARISON",
        severity="error",
        artifact_name=paths[0],
        message=(
            "Cross-study inference is paired with a coordinate table that includes a "
            "group-difference column, which implies a direct contrast that was never tested."
        ),
        suggested_fix=(
            "Remove the faux group-difference column. Report each study's coordinates "
            "separately and state explicitly that no direct single-study comparison exists."
        ),
        kg_evidence=paths[:3],
    )


def directional_claim_contradiction_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    claims, evidence_items, _ = load_review_claims_and_evidence(bundle)
    conflicts = find_directional_claim_conflicts(claims, evidence_items)
    if not conflicts:
        return None
    top = conflicts[0]
    direction_labels = sorted(top["directions"].keys())
    evidence_lines = [
        f"{direction}: {', '.join(row['claim_id'] for row in rows[:3])}"
        for direction, rows in top["directions"].items()
    ]
    return ReviewFinding(
        rule_id="REVIEW_DIRECTIONAL_CLAIM_CONTRADICTION",
        severity="warn",
        message=(
            f"Directional claims disagree within the same hypothesis family "
            f"({top['family_key']}): {', '.join(direction_labels)}."
        ),
        suggested_fix=(
            "Present both directions explicitly, annotate the evidence provenance "
            "supporting each direction, and leave the direction unresolved unless a "
            "direct comparison adjudicates it."
        ),
        kg_evidence=evidence_lines[:3],
    )


# ---------------------------------------------------------------------------
# Citation mismatch detection — review-time KG lookup
# ---------------------------------------------------------------------------

_PMID_EXTRACT_RE = re.compile(r"(?:pmid[:\s]*)(\d{7,8})", re.IGNORECASE)
_DOI_EXTRACT_RE = re.compile(r"(10\.\d{4,9}/\S+)")
_TRAILING_DOI_PUNCTUATION = ".,;:!?)]}"

# Domain construct categories for alignment checking.
# Each key is a canonical category; values are lowercase phrases that signal it.
_CONSTRUCT_CATEGORIES: dict[str, frozenset[str]] = {
    "trust": frozenset({
        "trust", "trustworthiness", "distrust", "trust game",
        "cooperation", "defection", "reciprocity",
    }),
    "empathy": frozenset({
        "empathy", "empathic", "compassion", "pain observation",
        "vicarious pain", "perspective taking",
    }),
    "self_referential": frozenset({
        "self-referential", "self referential", "self-concept",
        "self concept", "self-reflection", "self reflection",
        "self-other distinction",
    }),
    "fear": frozenset({
        "fear", "threat", "fear conditioning", "anxiety", "aversive",
    }),
    "reward": frozenset({
        "reward", "reinforcement", "incentive", "monetary",
        "gambling", "reward processing",
    }),
    "memory": frozenset({
        "memory", "encoding", "retrieval", "recognition memory",
        "recall", "working memory",
    }),
    "attention": frozenset({
        "attention", "attentional", "vigilance", "alerting", "orienting",
    }),
    "language": frozenset({
        "language", "semantic processing", "syntactic", "reading",
        "speech", "sentence comprehension",
    }),
    "motor": frozenset({
        "motor", "movement", "action execution", "grasping", "saccade",
    }),
    "emotion_regulation": frozenset({
        "emotion regulation", "reappraisal", "suppression",
        "cognitive control of emotion",
    }),
    "face_processing": frozenset({
        "face perception", "face recognition", "other-race",
        "other race", "own-race", "own race", "face processing",
    }),
    "decision_making": frozenset({
        "decision making", "decision-making", "choice",
        "risk taking", "risk-taking", "gambling task",
    }),
}

_POPULATION_CROSS_CULTURAL_TERMS = frozenset({
    "cross-cultural", "cross cultural", "cultural comparison",
    "cultural differences", "intercultural", "cultural neuroscience",
})
_POPULATION_GROUP_TERMS: dict[str, frozenset[str]] = {
    "east_asian": frozenset({
        "east asian", "chinese", "japanese", "korean", "asian participants",
    }),
    "european_american": frozenset({
        "european american", "caucasian", "white american",
    }),
    "danish": frozenset({"danish", "denmark"}),
    "western": frozenset({"western participants", "western subjects", "western adults"}),
}


def _extract_construct_categories(text: str) -> set[str]:
    """Return the set of construct category names mentioned in *text*."""
    lowered = text.lower()
    return {
        cat for cat, keywords in _CONSTRUCT_CATEGORIES.items()
        if any(kw in lowered for kw in keywords)
    }


def _extract_population_groups(text: str) -> set[str]:
    """Return population group labels mentioned in *text*."""
    lowered = text.lower()
    groups: set[str] = set()
    for group, terms in _POPULATION_GROUP_TERMS.items():
        if any(t in lowered for t in terms):
            groups.add(group)
    return groups


def _text_implies_cross_cultural(text: str) -> bool:
    lowered = text.lower()
    return any(t in lowered for t in _POPULATION_CROSS_CULTURAL_TERMS)


def _extract_pmids_from_evidence(
    claims: list[ClaimV1],
    evidence_items: list[EvidenceItemV1],
) -> list[dict[str, Any]]:
    """Extract ``(pmid, doi, claim_id, claim_text)`` from claim→evidence links."""
    evidence_map = {e.evidence_id: e for e in evidence_items}
    results: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for claim in claims:
        for eid in claim.evidence_ids:
            ev = evidence_map.get(eid)
            if ev is None:
                continue
            pmid: str | None = None
            doi: str | None = None

            extra = ev.extra if isinstance(ev.extra, dict) else {}
            raw_pmid = str(extra.get("pmid", "")).strip()
            if raw_pmid:
                pmid = raw_pmid
            raw_doi = _normalize_doi(extra.get("doi"))
            if raw_doi:
                doi = raw_doi

            if not pmid and ev.ref:
                m = _PMID_EXTRACT_RE.search(ev.ref)
                if m:
                    pmid = m.group(1)
            if not doi and ev.ref:
                m = _DOI_EXTRACT_RE.search(ev.ref)
                if m:
                    doi = _normalize_doi(m.group(1))

            if not pmid and not doi:
                continue
            citation_key = pmid or doi or ""
            pair_key = (citation_key, claim.claim_id)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            results.append({
                "pmid": pmid,
                "doi": doi,
                "claim_id": claim.claim_id,
                "claim_text": claim.claim_text,
                "evidence_id": eid,
                "claim_extra": claim.extra if isinstance(claim.extra, dict) else {},
            })

    return results


def _citation_label(pmid: str | None, doi: str | None) -> str:
    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    return "citation:?"


def _normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", cleaned, flags=re.I)
    cleaned = cleaned.rstrip(_TRAILING_DOI_PUNCTUATION)
    return cleaned or None


def _neighbor_text_candidates(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            texts.append(text)
        return texts

    if isinstance(value, dict):
        for key in (
            "label",
            "name",
            "title",
            "target_label",
            "target_name",
            "neighbor_label",
            "node_label",
            "display_name",
            "type",
            "rel",
            "relationship",
            "target",
            "target_id",
            "id",
            "kg_id",
        ):
            raw = value.get(key)
            if isinstance(raw, str):
                text = raw.strip()
                if text:
                    texts.append(text)
            elif raw is not None and not isinstance(raw, dict | list | tuple | set):
                text = str(raw).strip()
                if text:
                    texts.append(text)

        for nested_key in ("properties", "target_properties", "neighbor", "node", "target"):
            nested = value.get(nested_key)
            if isinstance(nested, dict):
                texts.extend(_neighbor_text_candidates(nested))
        return texts

    if isinstance(value, list):
        for item in value:
            texts.extend(_neighbor_text_candidates(item))
        return texts

    text = str(value).strip()
    if text:
        texts.append(text)
    return texts


def _resolve_publication_from_kg(
    pmid: str | None,
    doi: str | None,
) -> dict[str, Any] | None:
    """Look up a publication in BR-KG by PMID or DOI.

    Returns a dict with ``label``, ``title``, ``abstract``, ``kg_id``,
    ``neighbors`` (list of neighbor labels) or *None* if not found.
    Fails silently on connection errors so review checks degrade gracefully.
    """
    try:
        from brain_researcher.services.neurokg.query_service import (
            neighbors,
            node_details,
            search_nodes,
        )
    except Exception:
        return None

    doi = _normalize_doi(doi)
    queries = []
    if pmid:
        queries.append(f"pmid:{pmid}")
    if doi:
        queries.append(f"doi:{doi}")
    if not queries:
        return None

    hits = None
    for query in queries:
        try:
            hits = search_nodes(
                query,
                node_types=["Publication"],
                limit=1,
                timeout_s=10.0,
            )
        except Exception:
            logger.debug("KG search_nodes unavailable for citation check", exc_info=True)
            return None
        if hits:
            break

    if not hits:
        return None

    node = hits[0]
    props = node.properties or {}

    # Fetch neighbors for richer construct context.
    neighbor_labels: list[str] = []
    try:
        graph_neighbors = neighbors(node.kg_id, limit=25, timeout_s=10.0)
        neighbor_labels = [
            str(item.get("label", "")).strip()
            for item in graph_neighbors
            if isinstance(item, dict) and str(item.get("label", "")).strip()
        ]
    except Exception:
        neighbor_labels = []

    try:
        detail = node_details(node.kg_id, timeout_s=10.0, include_neighbors=True)
        if detail and detail.properties:
            props = detail.properties
        if not neighbor_labels:
            raw_neighbors = props.get("neighbors")
            if raw_neighbors is None:
                raw_neighbors = props.get("_neighbors")
            neighbor_labels = [
                text
                for text in (
                    _neighbor_text_candidates(raw_neighbors)
                    if raw_neighbors is not None
                    else []
                )
                if text
            ]
    except Exception:
        pass

    return {
        "kg_id": node.kg_id,
        "label": node.label or "",
        "title": str(props.get("title", "") or ""),
        "abstract": str(props.get("abstract", "") or ""),
        "year": props.get("year"),
        "neighbor_labels": neighbor_labels,
    }


def _paper_text_blob(pub: dict[str, Any]) -> str:
    """Combine all text fields from a resolved publication for matching."""
    parts = [
        pub.get("label", ""),
        pub.get("title", ""),
        pub.get("abstract", ""),
    ]
    parts.extend(pub.get("neighbor_labels", []))
    return " ".join(p for p in parts if p)


def citation_construct_mismatch_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Detect when cited papers do not actually study the construct claimed."""
    claims, evidence_items, _ = load_review_claims_and_evidence(bundle)
    if not claims:
        return None

    refs = _extract_pmids_from_evidence(claims, evidence_items)
    if not refs:
        return None

    mismatches: list[str] = []
    for ref in refs:
        claim_constructs = _extract_construct_categories(ref["claim_text"])
        if not claim_constructs:
            continue

        pub = _resolve_publication_from_kg(ref["pmid"], ref["doi"])
        if pub is None:
            continue

        paper_text = _paper_text_blob(pub)
        paper_constructs = _extract_construct_categories(paper_text)

        if not paper_constructs:
            continue

        if not claim_constructs & paper_constructs:
            cite_label = _citation_label(ref["pmid"], ref["doi"])
            mismatch_msg = (
                f"{cite_label} studies {', '.join(sorted(paper_constructs))} "
                f"but claim '{ref['claim_id']}' is about "
                f"{', '.join(sorted(claim_constructs))}"
            )
            mismatches.append(mismatch_msg)

    if not mismatches:
        return None

    return ReviewFinding(
        rule_id="REVIEW_CITATION_CONSTRUCT_MISMATCH",
        severity="error",
        message=(
            f"Cited publication construct does not match claim: {mismatches[0]}"
        ),
        suggested_fix=(
            "Replace the citation with a paper that actually studies the "
            "claimed construct, or rewrite the claim to match what the "
            "cited paper found."
        ),
        reason_tags=["citation_mismatch", "construct_validity"],
        kg_evidence=mismatches[:5],
    )


def citation_population_mismatch_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Detect when cited papers' population does not match the claim scope."""
    claims, evidence_items, _ = load_review_claims_and_evidence(bundle)
    if not claims:
        return None

    refs = _extract_pmids_from_evidence(claims, evidence_items)
    if not refs:
        return None

    mismatches: list[str] = []
    for ref in refs:
        claim_text = ref["claim_text"]
        claim_cross = _text_implies_cross_cultural(claim_text)
        claim_pops = _extract_population_groups(claim_text)
        if not claim_cross and len(claim_pops) < 2:
            continue

        pub = _resolve_publication_from_kg(ref["pmid"], ref["doi"])
        if pub is None:
            continue

        paper_text = _paper_text_blob(pub)
        paper_pops = _extract_population_groups(paper_text)
        paper_cross = _text_implies_cross_cultural(paper_text)

        if not paper_pops:
            if claim_cross and not paper_cross:
                paper_scope = "single population"
                cite_label = _citation_label(ref["pmid"], ref["doi"])
                mismatches.append(
                    f"{cite_label} is a {paper_scope} study but claim "
                    f"'{ref['claim_id']}' asserts a cross-cultural contrast"
                )
            continue

        if claim_cross:
            if paper_pops != claim_pops:
                cite_label = _citation_label(ref["pmid"], ref["doi"])
                mismatches.append(
                    f"{cite_label} studies {', '.join(sorted(paper_pops))} but claim "
                    f"'{ref['claim_id']}' is about {', '.join(sorted(claim_pops))}"
                )
            continue

        if len(claim_pops) >= 2 and paper_pops != claim_pops:
            cite_label = _citation_label(ref["pmid"], ref["doi"])
            mismatches.append(
                f"{cite_label} studies {', '.join(sorted(paper_pops))} but claim "
                f"'{ref['claim_id']}' is about {', '.join(sorted(claim_pops))}"
            )

    if not mismatches:
        return None

    return ReviewFinding(
        rule_id="REVIEW_CITATION_POPULATION_MISMATCH",
        severity="error",
        message=(
            f"Cited publication population does not match claim: {mismatches[0]}"
        ),
        suggested_fix=(
            "Acknowledge the population mismatch explicitly or replace the "
            "citation with a study that matches the claimed population."
        ),
        reason_tags=["citation_mismatch"],
        kg_evidence=mismatches[:5],
    )


__all__ = [
    "citation_construct_mismatch_check",
    "citation_population_mismatch_check",
    "cross_study_coordinate_comparison_check",
    "directional_claim_contradiction_check",
    "epistemic_claim_policy_check",
    "find_cross_study_coordinate_comparison_paths",
    "find_directional_claim_conflicts",
    "load_review_claims_and_evidence",
]
