"""Deterministic novelty-calibration questions for candidate card payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_ORIGIN_PATTERNS = {
    "bridge_disconnected_regions",
    "collapse_bottleneck",
    "resolve_contradiction_loop",
    "controlled_ood_search",
}

_PROBLEM_TARGETS = {
    "circular_validation",
    "population_generalization_failure",
    "measurement_invariance",
    "effect_size_inflation",
    "parcellation_dependence",
    "hrf_assumption_mismatch",
    "motion_confound_underreporting",
}

_CLAIM_SURFACES = {
    "mechanistic_framing",
    "experimental_design",
    "clinical_stratification",
    "analytic_method",
    "overall_combination",
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed != parsed:
        return default
    return parsed


def _truncate_text(value: Any, *, limit: int = 220) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_key(value: Any) -> str:
    text = _normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact_tokens(*values: Any) -> str:
    return " ".join(_normalize_key(value) for value in values if value).strip()


def _tokenize(*values: Any) -> list[str]:
    return [token for token in _compact_tokens(*values).split() if token]


def _contains_phrase(haystack: str, phrase: str) -> bool:
    normalized_phrase = _normalize_key(phrase)
    if not haystack or not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {haystack} "


def _contains_any_phrase(haystack: str, phrases: Sequence[str]) -> bool:
    return any(_contains_phrase(haystack, phrase) for phrase in phrases)


def _contains_token_prefix(tokens: Sequence[str], prefix: str) -> bool:
    normalized_prefix = _normalize_key(prefix)
    return any(token.startswith(normalized_prefix) for token in tokens)


def _infer_origin_pattern(card: Mapping[str, Any]) -> str:
    taste_axis = _normalize_key(card.get("taste_axis"))
    relation_hint = _normalize_key(
        (card.get("provenance") or {}).get("relation_hint")
        if isinstance(card.get("provenance"), Mapping)
        else ""
    )
    contradiction_probe = _normalize_key(card.get("contradiction_probe"))

    if "contradiction" in taste_axis or contradiction_probe:
        return "resolve_contradiction_loop"
    if "bridge" in taste_axis:
        return "bridge_disconnected_regions"
    if any(token in taste_axis for token in ("method", "signal", "bottleneck")):
        return "collapse_bottleneck"
    if any(token in taste_axis for token in ("ood", "workflow", "default")):
        return "controlled_ood_search"
    if relation_hint in {"maps to", "maps_to"}:
        return "collapse_bottleneck"
    return "controlled_ood_search"


def _infer_problem_target(
    query: str,
    card: Mapping[str, Any],
    *,
    origin_pattern: str,
) -> str:
    haystack = _compact_tokens(
        query,
        card.get("title"),
        card.get("hypothesis"),
        card.get("mechanism"),
        card.get("evidence_summary"),
        card.get("selection_reason"),
        card.get("why_this_is_not_just_a_bridge"),
        card.get("minimal_discriminating_test"),
        card.get("falsifier_hint"),
    )
    tokens = _tokenize(
        query,
        card.get("title"),
        card.get("hypothesis"),
        card.get("mechanism"),
        card.get("evidence_summary"),
        card.get("selection_reason"),
        card.get("why_this_is_not_just_a_bridge"),
        card.get("minimal_discriminating_test"),
        card.get("falsifier_hint"),
    )

    if _contains_any_phrase(haystack, ("effect size", "underpowered", "small sample")):
        return "effect_size_inflation"
    if _contains_phrase(haystack, "motion"):
        return "motion_confound_underreporting"
    if _contains_phrase(haystack, "hrf"):
        return "hrf_assumption_mismatch"
    if _contains_phrase(haystack, "parcellation"):
        return "parcellation_dependence"
    if _contains_any_phrase(
        haystack,
        (
            "circular validation",
            "same feature",
            "same signal",
            "validation leakage",
        ),
    ):
        return "circular_validation"
    if _contains_any_phrase(
        haystack,
        (
            "invariance",
            "equivalent",
            "same construct",
            "same task",
            "paradigm",
        ),
    ):
        return "measurement_invariance"
    if _contains_any_phrase(
        haystack,
        (
            "fatigue",
            "anergia",
            "psychomotor",
            "subtype",
            "subgroup",
            "boundary condition",
            "recovery",
            "challenge",
            "population",
        ),
    ) or _contains_token_prefix(tokens, "stratif"):
        return "population_generalization_failure"

    if origin_pattern == "resolve_contradiction_loop":
        return "measurement_invariance"
    if origin_pattern in {"bridge_disconnected_regions", "controlled_ood_search"}:
        return "population_generalization_failure"
    return "circular_validation"


def _infer_claim_surface(
    query: str,
    card: Mapping[str, Any],
    *,
    origin_pattern: str,
    problem_target: str,
) -> str:
    title = _normalize_text(card.get("title"))
    hypothesis = _normalize_text(card.get("hypothesis"))
    mechanism = _normalize_text(card.get("mechanism"))
    haystack = _compact_tokens(
        query,
        title,
        hypothesis,
        mechanism,
        card.get("evidence_summary"),
        card.get("selection_reason"),
        card.get("why_this_is_not_just_a_bridge"),
        card.get("minimal_discriminating_test"),
        card.get("falsifier_hint"),
    )
    tokens = _tokenize(
        query,
        title,
        hypothesis,
        mechanism,
        card.get("evidence_summary"),
        card.get("selection_reason"),
        card.get("why_this_is_not_just_a_bridge"),
        card.get("minimal_discriminating_test"),
        card.get("falsifier_hint"),
    )
    taste_axis = _normalize_key(card.get("taste_axis"))
    reframe_haystack = _compact_tokens(title, hypothesis, mechanism)

    if (
        origin_pattern in {"controlled_ood_search", "bridge_disconnected_regions"}
        and _contains_any_phrase(
            reframe_haystack,
            (
                "reframe",
                "framing",
                "frame as",
                "rather than",
                "instead of",
            ),
        )
    ):
        return "mechanistic_framing"

    if _contains_any_phrase(
        haystack,
        (
            "state transition",
            "dynamic",
            "sliding window",
            "hmm",
            "endpoint",
            "metric",
            "analysis",
            "slope",
        ),
    ) or _contains_phrase(taste_axis, "method"):
        return "analytic_method"
    if _contains_any_phrase(
        haystack,
        (
            "fatigue",
            "anergia",
            "psychomotor",
            "subtype",
            "subgroup",
            "severity",
        ),
    ) or _contains_token_prefix(tokens, "stratif"):
        return "clinical_stratification"
    if _contains_any_phrase(
        haystack,
        (
            "pre post",
            "pre challenge",
            "post challenge",
            "recovery",
            "challenge",
            "task",
            "condition",
            "protocol",
            "design",
            "block",
        ),
    ):
        return "experimental_design"
    if problem_target == "population_generalization_failure" and origin_pattern in {
        "controlled_ood_search",
        "bridge_disconnected_regions",
    }:
        return "mechanistic_framing"
    return "mechanistic_framing"


def _derive_novelty_claim_type(
    *,
    origin_pattern: str,
    problem_target: str,
    claim_surface: str,
) -> str:
    if claim_surface == "overall_combination":
        return "combinatorial_package_only"
    if origin_pattern in {"bridge_disconnected_regions", "controlled_ood_search"}:
        return "new_bridge_to_known_problem"
    if origin_pattern == "resolve_contradiction_loop":
        return "new_problem_reframing"
    if problem_target in {"measurement_invariance", "circular_validation"}:
        return "known_bridge_new_problem_target"
    return "new_problem_reframing"


def _kg_evidence_context(card: Mapping[str, Any], *, origin_pattern: str) -> str:
    provenance = card.get("provenance") if isinstance(card.get("provenance"), Mapping) else {}
    verification = (
        card.get("kg_verification") if isinstance(card.get("kg_verification"), Mapping) else {}
    )
    verdict = (
        _normalize_text(verification.get("verdict"))
        or _normalize_text(card.get("grounding_status"))
        or "unknown"
    )
    scope = (
        _normalize_text(verification.get("evidence_source_scope"))
        or _normalize_text(card.get("evidence_source_scope"))
        or "unknown"
    )
    relation_hint = _normalize_text(provenance.get("relation_hint")) or "unknown"
    candidate_kg_id = _normalize_text(provenance.get("candidate_kg_id")) or "unknown"
    base_context = (
        f"KG surfaced this via {origin_pattern}; relation_hint={relation_hint}; "
        f"candidate_kg_id={candidate_kg_id}; verification verdict={verdict}; "
        f"evidence scope={scope}."
    )
    rank = int(_safe_float(card.get("rank"), 0.0))
    if rank > 0:
        base_context = f"{base_context} rank={rank}."
    query_relevance = _safe_float(
        card.get("query_relevance_score")
        or provenance.get("query_relevance_score"),
        0.0,
    )
    if query_relevance > 0:
        base_context = f"{base_context} query_relevance_score={query_relevance:.2f}."
    deep_research_status = _normalize_text(card.get("deep_research_status"))
    if deep_research_status:
        base_context = f"{base_context} deep_research_status={deep_research_status}."
    evidence_summary = _truncate_text(card.get("evidence_summary"))
    if evidence_summary:
        return f"{base_context} Deep research summary: {evidence_summary}"
    supporting_titles = provenance.get("supporting_paper_titles")
    if isinstance(supporting_titles, Sequence) and not isinstance(supporting_titles, str):
        first_titles = [
            _normalize_text(item) for item in supporting_titles if _normalize_text(item)
        ][:2]
        if first_titles:
            return f"{base_context} Supporting papers include: {'; '.join(first_titles)}."
    return base_context


def _claim_subject(card: Mapping[str, Any]) -> str:
    title = _normalize_text(card.get("title"))
    if title:
        return title
    hypothesis = _normalize_text(card.get("hypothesis"))
    if hypothesis:
        return hypothesis
    return _normalize_text(card.get("card_id")) or "this candidate"


def _claim_focus(card: Mapping[str, Any]) -> str:
    provenance = card.get("provenance") if isinstance(card.get("provenance"), Mapping) else {}
    focus = _normalize_text(provenance.get("object_label"))
    if focus:
        return focus
    return _claim_subject(card)


def _card_priority_score(card: Mapping[str, Any], *, fallback_rank: int) -> float:
    provenance = card.get("provenance") if isinstance(card.get("provenance"), Mapping) else {}
    query_relevance = _safe_float(
        card.get("query_relevance_score")
        or provenance.get("query_relevance_score"),
        0.0,
    )
    raw_rank = int(_safe_float(card.get("rank"), float(fallback_rank)))
    rank = max(1, raw_rank if raw_rank > 0 else fallback_rank)
    rank_signal = 1.0 / float(rank)
    return round((0.65 * query_relevance) + (0.35 * rank_signal), 6)


def _priority_tier(priority_score: float) -> str:
    if priority_score >= 0.55:
        return "high"
    if priority_score >= 0.30:
        return "medium"
    return "low"


def _question_for_card(
    *,
    query: str,
    card: Mapping[str, Any],
    index: int,
    origin_pattern: str,
    problem_target: str,
    claim_surface: str,
    priority_score: float,
) -> dict[str, Any]:
    subject = _claim_subject(card)
    focus = _claim_focus(card)
    card_id = _normalize_text(card.get("card_id")) or f"cand_{index:02d}"
    tier = _priority_tier(priority_score)
    novelty_claim_type = _derive_novelty_claim_type(
        origin_pattern=origin_pattern,
        problem_target=problem_target,
        claim_surface=claim_surface,
    )

    if claim_surface == "experimental_design" and tier == "high":
        question = (
            f"The higher-priority card `{subject}` is tightly aligned to '{query}'. "
            f"Can you name a direct precedent that uses this exact design move as a "
            f"primary test rather than a secondary control? If the closest precedent "
            f"lives in an adjacent paradigm, where does transfer to this query break?"
        )
        why = (
            "For top-ranked design cards, the real novelty question is not whether the "
            "move exists somewhere, but whether it has already been used as the main "
            "test in this disease/problem framing."
        )
        challenge = "exact_design_precedent"
    elif claim_surface == "experimental_design":
        question = (
            f"The card `{subject}` suggests a design change surfaced via "
            f"`{origin_pattern}`. Is this protocol structure already standard in "
            f"adjacent paradigms for '{query}', or is the design move itself still unusual?"
        )
        why = (
            "If the structure is already standard nearby, the novelty claim weakens "
            "from new design to new application of an existing design."
        )
        challenge = "design_precedent"
    elif claim_surface == "clinical_stratification" and tier == "high":
        question = (
            f"The higher-priority card `{subject}` implies that `{focus}` should act as "
            f"a primary subtype axis for '{query}'. Can you name a direct precedent that "
            "already elevates this exact axis above symptom severity or global case-control "
            "status, rather than treating it as a secondary covariate?"
        )
        why = (
            "High-priority stratification cards should be challenged on whether the exact "
            "axis is already a first-class subtype definition, not merely mentioned in passing."
        )
        challenge = "exact_stratification_precedent"
    elif claim_surface == "clinical_stratification":
        question = (
            f"The card `{subject}` implies a subgrouping or clinical axis tied to "
            f"`{problem_target}`. Is this already an organized research direction, "
            f"or still scattered enough that a direct precedent would be hard to name?"
        )
        why = (
            "If established groups already use this axis, the study should be framed "
            "as a rigorous extension rather than a first-mover stratification."
        )
        challenge = "problem_precedent"
    elif claim_surface == "analytic_method" and tier == "high":
        question = (
            f"The higher-priority card `{subject}` implies an analytic endpoint that may "
            f"be central to '{query}'. Can you name papers that already use this exact "
            f"metric or state variable as a primary endpoint, not just an exploratory add-on? "
            "If not, what is the closest accepted proxy and why was this one left out?"
        )
        why = (
            "For high-priority analytic cards, reviewer pushback will focus on whether "
            "the metric is genuinely new and central, or only an exploratory embellishment."
        )
        challenge = "exact_method_precedent"
    elif claim_surface == "analytic_method":
        question = (
            f"The card `{subject}` implies an analytic shift for '{query}'. Is this "
            "a genuine methodological advance for the question, or mainly a more "
            "elaborate metric on the same underlying data?"
        )
        why = (
            "If the method is already standard or mostly cosmetic, reviewer risk rises "
            "while the novelty claim drops."
        )
        challenge = "method_precedent"
    elif tier == "high":
        question = (
            f"The higher-priority card `{subject}` centers `{focus}` as a mechanistic "
            f"driver for '{query}'. Can you name a direct precedent in the target literature "
            f"that already treats `{focus}` as a primary mechanistic mediator, not just a "
            "peripheral correlate or biomarker? If not, what is the closest near-precedent, "
            "and exactly where does it stop short?"
        )
        why = (
            "Top-ranked mechanistic cards should be stress-tested against the strongest "
            "possible near-precedent, not only against exact verbal matches."
        )
        challenge = "direct_or_near_precedent"
    else:
        question = (
            f"The KG surfaced `{subject}` via `{origin_pattern}`. Can you name a "
            f"direct precedent that already makes this kind of framing claim for "
            f"'{query}', or a functionally equivalent claim that would invalidate the novelty?"
        )
        why = (
            "If a direct precedent exists, the claim weakens from new framing to new "
            "evidence for an existing framing."
        )
        challenge = "direct_precedent"

    return {
        "id": f"ncq_{index:02d}",
        "targets_card_id": card_id,
        "origin_pattern": origin_pattern,
        "problem_target": problem_target,
        "claim_surface": claim_surface,
        "novelty_claim_type": novelty_claim_type,
        "priority_tier": tier,
        "priority_score": priority_score,
        "precedent_challenge_type": challenge,
        "question": question,
        "kg_evidence_context": _kg_evidence_context(
            card, origin_pattern=origin_pattern
        ),
        "why_this_matters": why,
    }


def build_novelty_calibration_context(
    query: str,
    candidate_cards: Sequence[Mapping[str, Any]] | None,
    summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cards = [dict(card) for card in candidate_cards or [] if isinstance(card, Mapping)]
    return {
        "query": _normalize_text(query),
        "candidate_cards": cards,
        "summary": dict(summary or {}),
    }


def generate_novelty_calibration_questions(
    context: Mapping[str, Any],
    *,
    max_questions: int = 4,
) -> dict[str, Any]:
    query = _normalize_text(context.get("query"))
    cards = [
        dict(card)
        for card in context.get("candidate_cards", [])
        if isinstance(card, Mapping)
    ]
    if max_questions < 1 or not cards:
        return {
            "novelty_calibration_questions": [],
            "novelty_calibration_meta": {
                "total_questions": 0,
                "dimensions_covered": [],
                "source": "candidate_cards_postprocess",
                "schema_version": "novelty-calibration-v1",
            },
        }

    card_limit = max(0, max_questions - 1)
    indexed_cards = list(enumerate(cards, start=1))
    ordered_cards = [
        item
        for _, item in sorted(
            indexed_cards,
            key=lambda pair: (
                0 if int(_safe_float(pair[1].get("rank"), 0.0)) > 0 else 1,
                int(_safe_float(pair[1].get("rank"), pair[0])),
                -_safe_float(pair[1].get("query_relevance_score"), 0.0),
                -_card_priority_score(pair[1], fallback_rank=pair[0]),
                _claim_subject(pair[1]),
            ),
        )
    ]
    selected_cards = ordered_cards[:card_limit]
    questions: list[dict[str, Any]] = []
    dimensions: list[str] = []

    for index, card in enumerate(selected_cards, start=1):
        priority_score = _card_priority_score(
            card,
            fallback_rank=index,
        )
        origin_pattern = _infer_origin_pattern(card)
        if origin_pattern not in _ORIGIN_PATTERNS:
            origin_pattern = "controlled_ood_search"
        problem_target = _infer_problem_target(
            query,
            card,
            origin_pattern=origin_pattern,
        )
        if problem_target not in _PROBLEM_TARGETS:
            problem_target = "population_generalization_failure"
        claim_surface = _infer_claim_surface(
            query,
            card,
            origin_pattern=origin_pattern,
            problem_target=problem_target,
        )
        if claim_surface not in _CLAIM_SURFACES:
            claim_surface = "mechanistic_framing"
        dimensions.append(claim_surface)
        questions.append(
            _question_for_card(
                query=query,
                card=card,
                index=index,
                origin_pattern=origin_pattern,
                problem_target=problem_target,
                claim_surface=claim_surface,
                priority_score=priority_score,
            )
        )

    dimensions.append("overall_combination")
    card_titles = [
        _claim_subject(card)
        for card in selected_cards[:3]
        if _claim_subject(card)
    ]
    combination_focus = ", ".join(card_titles) if card_titles else "the proposed package"
    questions.append(
        {
            "id": f"ncq_{len(questions) + 1:02d}",
            "targets_card_id": None,
            "origin_pattern": None,
            "problem_target": None,
            "claim_surface": "overall_combination",
            "novelty_claim_type": "combinatorial_package_only",
            "precedent_challenge_type": "combined_precedent",
            "question": (
                f"Setting aside each component, does the combination of {combination_focus} "
                "look like a coherent conceptual advance, or mainly a stack of ideas that "
                "are already known separately?"
            ),
            "kg_evidence_context": None,
            "why_this_matters": (
                "Combinatorial novelty is weaker than conceptual novelty. The answer changes "
                "how aggressively the work should be positioned."
            ),
        }
    )

    return {
        "novelty_calibration_questions": questions[:max_questions],
        "novelty_calibration_meta": {
            "total_questions": min(len(questions), max_questions),
            "dimensions_covered": list(dict.fromkeys(dimensions[:max_questions])),
            "priority_signal_used": True,
            "source": "candidate_cards_postprocess",
            "schema_version": "novelty-calibration-v1",
        },
    }
