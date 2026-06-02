"""Build reusable idea cards from deep-research source packs and KGGEN output."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.wow_principle_controller import (
    rank_wow_candidates,
)
from brain_researcher.services.br_kg.etl.deep_research_bridge import (
    coerce_deep_research_result,
)

IDEA_CARD_VERSION = "deep-research-idea-cards/v1"
EPHEMERAL_SUBGRAPH_VERSION = "deep-research-subgraph/v1"
_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_PAREN_CONTENT_RE = re.compile(r"\([^)]*\)")
_QUERY_RELATION_RE = re.compile(
    r"(.+?)\b("
    r"influences?|affects?|impacts?|modulates?|shapes?|constrains?|"
    r"drives?|predicts?|alters?|changes?"
    r")\b(.+)",
    re.IGNORECASE,
)
_DISEASE_ANCHOR_RE = re.compile(
    r"\b("
    r"[A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*){0,4}\s+"
    r"(?:disorder|disease|syndrome|depression|schizophrenia|anxiety|autism)"
    r")\b",
    re.IGNORECASE,
)
_GENERIC_OBJECTS = {
    "action",
    "auc",
    "brain",
    "brains",
    "brain network",
    "brain networks",
    "choice",
    "choices",
    "data",
    "depression",
    "effect",
    "effects",
    "environment",
    "environments",
    "event",
    "events",
    "human",
    "humans",
    "parameter",
    "parameters",
    "result",
    "results",
    "rodent",
    "rodents",
    "species",
    "pnas",
    "task",
    "tasks",
    "trial",
    "trials",
    "variable",
    "variables",
}
_METHOD_HINTS = (
    "artifact",
    "artifacts",
    "baseline",
    "bin",
    "calculation",
    "confound",
    "correction",
    "covariate",
    "estimate",
    "estimates",
    "foreshortening",
    "gaze",
    "lme",
    "luminance",
    "mixed-effects",
    "mixed effects",
    "monitor",
    "parameter estimate",
    "preprocess",
    "preprocessing",
    "regression",
    "screen",
    "signal quality",
)
_PAPER_TITLE_PLACEHOLDERS = {
    "node",
    "article",
    "document",
    "untitled",
}
_PAPER_TITLE_BAD_PREFIXES = (
    "404",
    "403",
    "access denied",
    "error",
    "just a moment",
    "page not found",
    "this page could not be found",
)
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "brain",
    "brains",
    "effect",
    "effects",
    "health",
    "how",
    "in",
    "influences",
    "influence",
    "network",
    "networks",
    "of",
    "on",
    "or",
    "study",
    "test",
    "testing",
    "the",
    "whether",
}
_BIOENERGETIC_QUERY_TOKENS = {
    "atp",
    "bioenergetic",
    "bioenergetics",
    "energy",
    "lactate",
    "metabolic",
    "metabolism",
    "mitochondria",
    "mitochondrial",
    "oxidative",
    "phosphocreatine",
    "respiration",
}
_SPECIFIC_MECHANISM_TOKENS = {
    "atp",
    "depletion",
    "electron",
    "lactate",
    "mtdna",
    "mitochondria",
    "mitochondrial",
    "oxidative",
    "phosphocreatine",
    "protein",
    "pyruvate",
    "respiration",
}
_GENERIC_MECHANISM_TOKENS = {
    "activity",
    "energy",
    "function",
    "functions",
    "health",
    "level",
    "levels",
    "metabolic",
    "metabolism",
    "production",
    "signal",
    "signals",
    "state",
    "states",
}


@dataclass
class FlatRelation:
    paper_id: str
    paper_title: str
    paper_journal: str
    subject: str
    predicate: str
    object_label: str
    claim_text: str
    evidence_quote: str
    confidence: float
    evidence_quality: float


@dataclass
class ObjectCluster:
    object_label: str
    paper_ids: set[str] = field(default_factory=set)
    paper_titles: dict[str, str] = field(default_factory=dict)
    journals: set[str] = field(default_factory=set)
    subjects: Counter[str] = field(default_factory=Counter)
    predicates: Counter[str] = field(default_factory=Counter)
    quotes: list[str] = field(default_factory=list)
    claim_texts: list[str] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    evidence_qualities: list[float] = field(default_factory=list)


def _normalize_space(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def _normalize_key(value: Any) -> str:
    return _normalize_space(value).lower()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed != parsed:
        return default
    return parsed


def _truncate(text: str, *, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clean_report_title(value: Any) -> str | None:
    text = _normalize_space(value)
    if not text:
        return None
    text = text.replace("**", " ")
    text = text.lstrip("# ").strip()
    text = re.sub(r"\bKey Points\b.*$", "", text, flags=re.IGNORECASE).strip(" -:|")
    text = _normalize_space(text)
    return text or None


def _clean_paper_title(value: Any, fallback: str) -> str:
    text = _normalize_space(value).strip(" |:-")
    if not text:
        return fallback
    lower = text.lower()
    if lower in {
        "researchgate",
        "404 not found",
        "403 forbidden",
        "not found",
        "forbidden",
        "error",
        "biorxiv",
    }:
        return fallback
    if any(lower.startswith(prefix) for prefix in _PAPER_TITLE_BAD_PREFIXES):
        return fallback
    if "could not be found" in lower or "enable javascript and cookies" in lower:
        return fallback
    if lower.startswith("url:"):
        return fallback
    if lower.startswith(("http://", "https://", "doi:", "pmid:", "arxiv:")):
        return fallback
    if re.fullmatch(r"[a-z0-9._/\-]+", lower) and (
        any(ch.isdigit() for ch in lower) or "." in lower or "/" in lower
    ):
        return fallback
    if len(text) > 180:
        return fallback
    letters = sum(ch.isalpha() for ch in text)
    if letters and (letters / max(1, len(text))) < 0.45:
        return fallback
    return text


def _normalize_object_label(value: str) -> str:
    text = _normalize_space(value)
    text = re.sub(r"\s*\((?:19|20)\d{2}\s*/\s*[^)]+\)$", "", text)
    text = re.sub(
        r"\s*(?:\||/|-)\s*(?:bioRxiv|ResearchGate|ScienceDaily)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip(".,;:[]{}\"' ")
    if text.count("(") < text.count(")"):
        text = text.replace(")", "")
    while text.endswith("("):
        text = text[:-1].rstrip()
    return text


def _semantic_key(value: Any, *, strip_parenthetical: bool = False) -> str:
    text = _normalize_space(value).lower()
    if strip_parenthetical:
        text = _PAREN_CONTENT_RE.sub(" ", text)
    return _normalize_space(_NON_ALNUM_RE.sub(" ", text))


def _acronym(value: str | None) -> str | None:
    text = _normalize_space(value)
    if not text:
        return None
    words = [word for word in re.findall(r"[A-Za-z]+", text) if word]
    if not (2 <= len(words) <= 5):
        return None
    acronym = "".join(word[0].upper() for word in words)
    return acronym if len(acronym) >= 2 else None


def _semantic_tokens(value: Any, *, include_acronym: bool = False) -> set[str]:
    tokens = {
        token
        for token in _semantic_key(value).split()
        if token and token not in _QUERY_STOPWORDS
    }
    if include_acronym:
        acronym = _acronym(_normalize_space(value))
        if acronym:
            tokens.add(acronym.lower())
    return tokens


def _strip_query_lead_in(query_context: str) -> str:
    text = _normalize_space(query_context)
    for marker in (" whether ", " how "):
        idx = text.lower().find(marker)
        if idx >= 0:
            return _normalize_space(text[idx + len(marker) :])
    return text


def _extract_domain_anchor(query_context: str) -> str | None:
    text = _normalize_space(query_context)
    match = _DISEASE_ANCHOR_RE.search(text)
    if match:
        return _normalize_space(match.group(1))
    for acronym in ("MDD", "PTSD", "ADHD", "OCD", "ASD"):
        if re.search(rf"\b{acronym}\b", text):
            return acronym
    return None


def _extract_query_relation(query_context: str) -> tuple[str | None, str | None]:
    text = _strip_query_lead_in(query_context)
    match = _QUERY_RELATION_RE.search(text)
    if not match:
        return None, None
    left = _normalize_space(match.group(1)).strip(" ,.;:")
    right = _normalize_space(match.group(3)).strip(" ,.;:")
    if not left or not right:
        return None, None
    return left, right


def _is_query_echo_object(label: str, query_context: str) -> bool:
    label_key = _semantic_key(label)
    query_key = _semantic_key(query_context)
    if len(label_key.split()) >= 2 and label_key and label_key in query_key:
        return True
    label_base = _semantic_key(label, strip_parenthetical=True)
    query_base = _semantic_key(query_context, strip_parenthetical=True)
    return (
        len(label_base.split()) >= 2 and bool(label_base) and label_base in query_base
    )


def _looks_like_source_artifact(label: str) -> bool:
    text = _normalize_space(label)
    lower = text.lower()
    if not text:
        return True
    if re.fullmatch(r"[A-Z]{2,6}", text):
        return True
    if re.search(r"(?:19|20)\d{2}\s*/\s*[A-Za-z]", text):
        return True
    if any(marker in lower for marker in ("biorxiv", "researchgate", "sciencedaily")):
        return True
    if len(text.split()) >= 10:
        return True
    return False


def _should_skip_object_cluster(cluster: ObjectCluster, query_context: str) -> bool:
    label = cluster.object_label
    if _looks_like_source_artifact(label):
        return True
    if _is_query_echo_object(label, query_context):
        return True
    return False


def _curated_supporting_paper_titles(cluster: ObjectCluster) -> list[str]:
    preferred: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()
    for paper_id in sorted(cluster.paper_ids):
        title = _clean_paper_title(cluster.paper_titles.get(paper_id), "")
        if not title or title in seen:
            continue
        seen.add(title)
        lower = title.lower()
        if lower in _PAPER_TITLE_PLACEHOLDERS:
            continue
        if lower.startswith("deep research source "):
            fallback.append(title)
            continue
        preferred.append(title)
    return (preferred or fallback)[:5]


def _object_specificity_score(label: str) -> float:
    tokens = _semantic_tokens(label)
    if not tokens:
        return 0.0
    specific_hits = len(tokens & _SPECIFIC_MECHANISM_TOKENS)
    generic_hits = len(tokens & _GENERIC_MECHANISM_TOKENS)
    score = (
        0.10 * min(3, len(tokens))
        + 0.30 * min(2, specific_hits)
        - (0.20 if generic_hits and not specific_hits else 0.0)
        - (0.05 * max(0, generic_hits - 1))
    )
    return _clip01(score)


def _query_relevance_score(
    cluster: ObjectCluster,
    query_context: str,
    *,
    subject_labels: list[str],
    predicate_labels: list[str],
) -> float:
    object_tokens = _semantic_tokens(cluster.object_label)
    query_tokens = _semantic_tokens(query_context, include_acronym=True)
    left, right = _extract_query_relation(query_context)
    domain_anchor = _extract_domain_anchor(query_context)
    left_tokens = _semantic_tokens(left, include_acronym=True)
    right_tokens = _semantic_tokens(right, include_acronym=True)
    anchor_tokens = _semantic_tokens(domain_anchor, include_acronym=True)
    context_tokens: set[str] = set()
    for value in [
        cluster.object_label,
        *subject_labels,
        *predicate_labels,
        *cluster.claim_texts[:3],
        *cluster.quotes[:2],
    ]:
        context_tokens.update(_semantic_tokens(value, include_acronym=True))

    specificity = _object_specificity_score(cluster.object_label)
    left_match = min(
        1.0,
        len((object_tokens | context_tokens) & left_tokens) / max(1, len(left_tokens)),
    )
    right_match = min(
        1.0,
        len(context_tokens & right_tokens) / max(1, len(right_tokens)),
    )
    anchor_match = 1.0 if anchor_tokens and (context_tokens & anchor_tokens) else 0.0
    bio_query = bool(query_tokens & _BIOENERGETIC_QUERY_TOKENS)
    bio_specific = (
        1.0 if bio_query and (object_tokens & _SPECIFIC_MECHANISM_TOKENS) else 0.0
    )
    generic_only_penalty = (
        0.15
        if object_tokens
        and not (object_tokens & _SPECIFIC_MECHANISM_TOKENS)
        and (object_tokens & _GENERIC_MECHANISM_TOKENS)
        else 0.0
    )
    score = (
        0.45 * specificity
        + 0.20 * left_match
        + 0.15 * right_match
        + 0.15 * anchor_match
        + 0.10 * bio_specific
        - generic_only_penalty
    )
    return round(_clip01(score), 6)


def _compact_title_phrase(value: str, *, for_anchor: bool = False) -> str:
    text = _normalize_space(value)
    text = re.sub(r"\bbrain networks\b", "networks", text, flags=re.IGNORECASE)
    text = re.sub(r"\bbrain network\b", "network", text, flags=re.IGNORECASE)
    text = re.sub(r"\beffects on\b", "->", text, flags=re.IGNORECASE)
    if for_anchor:
        words = [word for word in re.findall(r"[A-Za-z]+", text) if word]
        if 2 <= len(words) <= 4 and any(
            words[-1].lower() == suffix
            for suffix in ("disorder", "disease", "syndrome", "depression")
        ):
            acronym = "".join(word[0].upper() for word in words)
            if len(acronym) >= 2:
                return acronym
    return text


def _build_mechanism_title(object_label: str, query_context: str) -> str:
    left, right = _extract_query_relation(query_context)
    domain_anchor = _extract_domain_anchor(query_context)
    object_title = _compact_title_phrase(object_label)
    short_anchor = _compact_title_phrase(domain_anchor or "", for_anchor=True)
    short_left = _compact_title_phrase(left or "")
    short_right = _compact_title_phrase(right or "")
    if left and right:
        title = f"Test {object_title}: {short_left} -> {short_right}"
    elif domain_anchor:
        title = f"Test {object_title} in {short_anchor or domain_anchor}"
    else:
        title = f"Test {object_title} as a mechanistic mediator"
    anchor_text = short_anchor or domain_anchor or ""
    if anchor_text and anchor_text.lower() not in title.lower():
        title = f"{title} in {anchor_text}"
    return _truncate(title, limit=96)


def _build_mechanism_hypothesis(
    object_label: str,
    query_context: str,
    *,
    subject_labels: list[str],
) -> str:
    left, right = _extract_query_relation(query_context)
    domain_anchor = _extract_domain_anchor(query_context)
    if left and right and domain_anchor:
        return (
            f"{object_label} may mechanistically link {left} to {right} in "
            f"{domain_anchor}, rather than acting as a passive correlate."
        )
    if left and right:
        return (
            f"{object_label} may mechanistically link {left} to {right}, rather than "
            "acting as a passive correlate."
        )
    subject_text = ", ".join(subject_labels[:2])
    if subject_text:
        return (
            f"{object_label} may help explain the core relationship in {query_context}, "
            f"with convergent evidence spanning {subject_text} across the cited "
            "deep-research sources."
        )
    return (
        f"{object_label} may help explain the core relationship described in "
        f"{query_context}, rather than acting as a passive correlate."
    )


def _build_mechanism_test(object_label: str, query_context: str) -> str:
    left, right = _extract_query_relation(query_context)
    if left and right:
        return (
            f"Test whether variation in {object_label} mediates or moderates the "
            f"relationship between {left} and {right} in at least two datasets or tasks."
        )
    return (
        f"Test whether variation in {object_label} mediates or moderates the core "
        f"relationship described in {query_context} across at least two datasets or tasks."
    )


def _build_mechanism_falsifier(object_label: str, query_context: str) -> str:
    left, right = _extract_query_relation(query_context)
    if left and right:
        return (
            f"Reject if variation in {object_label} does not reproducibly mediate or "
            f"moderate the relationship between {left} and {right}."
        )
    return (
        f"Reject if variation in {object_label} does not reproducibly explain the core "
        f"relationship described in {query_context}."
    )


def _is_generic_object(label: str) -> bool:
    norm = _normalize_key(label)
    if not norm:
        return True
    if len(norm) < 4:
        return True
    if norm in _GENERIC_OBJECTS:
        return True
    if norm.isdigit():
        return True
    return False


def _object_is_method_like(label: str, cluster: ObjectCluster) -> bool:
    haystacks = [label]
    haystacks.extend(cluster.predicates.keys())
    combined = " | ".join(_normalize_key(item) for item in haystacks if item)
    return any(hint in combined for hint in _METHOD_HINTS)


def _extract_interaction_id(result: Mapping[str, Any]) -> str | None:
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        value = _normalize_space(metadata.get("interaction_id"))
        if value:
            return value
    return None


def load_kggen_relation_rows(kggen_input: Path | str) -> list[FlatRelation]:
    """Flatten raw KGGEN manifest output into relation rows."""

    path = Path(kggen_input).expanduser().resolve()
    rows: list[FlatRelation] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                continue
            paper = payload.get("paper")
            relations = payload.get("relations")
            if not isinstance(paper, Mapping) or not isinstance(relations, list):
                continue
            paper_id = _normalize_space(paper.get("id"))
            if not paper_id:
                continue
            paper_title = _clean_paper_title(paper.get("title"), paper_id)
            paper_journal = _normalize_space(paper.get("journal"))
            for relation in relations:
                if not isinstance(relation, Mapping):
                    continue
                subject = _normalize_space(relation.get("subject"))
                predicate = _normalize_space(relation.get("predicate"))
                object_label = _normalize_object_label(
                    _normalize_space(relation.get("object"))
                )
                claim_text = _normalize_space(relation.get("claim_text"))
                evidence_quote = _normalize_space(relation.get("evidence_quote"))
                if not object_label or _is_generic_object(object_label):
                    continue
                rows.append(
                    FlatRelation(
                        paper_id=paper_id,
                        paper_title=paper_title,
                        paper_journal=paper_journal,
                        subject=subject,
                        predicate=predicate,
                        object_label=object_label,
                        claim_text=claim_text,
                        evidence_quote=evidence_quote,
                        confidence=_safe_float(relation.get("confidence"), 0.0),
                        evidence_quality=max(
                            0.0,
                            min(
                                1.0,
                                _safe_float(
                                    relation.get("evidence_quality_score")
                                    or relation.get("context_overlap")
                                    or relation.get("assertive_verb_ratio"),
                                    0.0,
                                ),
                            ),
                        ),
                    )
                )
    return rows


def _build_clusters(rows: Iterable[FlatRelation]) -> list[ObjectCluster]:
    clusters: dict[str, ObjectCluster] = {}
    for row in rows:
        key = _normalize_key(row.object_label)
        cluster = clusters.setdefault(key, ObjectCluster(object_label=row.object_label))
        cluster.paper_ids.add(row.paper_id)
        cluster.paper_titles[row.paper_id] = row.paper_title
        if row.paper_journal:
            cluster.journals.add(row.paper_journal)
        if row.subject:
            cluster.subjects[row.subject] += 1
        if row.predicate:
            cluster.predicates[row.predicate] += 1
        if row.evidence_quote and row.evidence_quote not in cluster.quotes:
            cluster.quotes.append(row.evidence_quote)
        if row.claim_text and row.claim_text not in cluster.claim_texts:
            cluster.claim_texts.append(row.claim_text)
        cluster.confidences.append(row.confidence)
        cluster.evidence_qualities.append(row.evidence_quality)
    return list(clusters.values())


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _top_items(counter: Counter[str], limit: int) -> list[str]:
    return [item for item, _ in counter.most_common(limit) if item]


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -_safe_float(candidate.get("query_relevance_score"), 0.0),
        -_safe_float(candidate.get("cluster_score"), 0.0),
        -_safe_float(candidate.get("publication_count"), 0.0),
        str(candidate.get("title") or ""),
    )


def _query_relevance_floor(candidates: list[dict[str, Any]], *, top_n: int) -> float:
    if not candidates:
        return 0.0
    top_score = max(
        _safe_float(item.get("query_relevance_score"), 0.0) for item in candidates
    )
    if top_score < 0.20:
        return 0.0
    return round(max(0.06, min(0.12, top_score * 0.12)), 6)


def _apply_query_relevance_floor(
    candidates: list[dict[str, Any]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    floor = _query_relevance_floor(candidates, top_n=top_n)
    if floor <= 0.0:
        return candidates
    filtered = [
        item
        for item in candidates
        if _safe_float(item.get("query_relevance_score"), 0.0) >= floor
    ]
    minimum_survivors = (
        1 if len(candidates) <= 2 else min(len(candidates), max(2, min(top_n, 3)))
    )
    if len(filtered) < minimum_survivors:
        return candidates
    return filtered


def _stable_id(prefix: str, *parts: Any) -> str:
    joined = "|".join(
        _normalize_space(part) for part in parts if _normalize_space(part)
    )
    digest = sha1(joined.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _infer_query_context(
    result: Mapping[str, Any],
    query: str | None,
) -> str:
    text = _normalize_space(query)
    if text:
        return text
    report_title = _clean_report_title(
        result.get("summary") or result.get("synthesis_full_text")
    )
    if report_title:
        return report_title
    summary = _normalize_space(
        result.get("summary") or result.get("synthesis_full_text")
    )
    if not summary:
        return "the deep-research problem"
    first_line = summary.split(".")[0].split(":")[0].strip(" #")
    return first_line or "the deep-research problem"


def _build_raw_candidate(
    cluster: ObjectCluster,
    *,
    query_context: str,
    interaction_id: str | None,
) -> dict[str, Any]:
    publication_count = len(cluster.paper_ids)
    subject_labels = _top_items(cluster.subjects, 3)
    predicate_labels = _top_items(cluster.predicates, 3)
    journals = sorted(cluster.journals)[:3]
    method_like = _object_is_method_like(cluster.object_label, cluster)
    query_relevance_score = _query_relevance_score(
        cluster,
        query_context,
        subject_labels=subject_labels,
        predicate_labels=predicate_labels,
    )

    support_score = min(1.0, publication_count / 4.0)
    subject_diversity = min(1.0, len(cluster.subjects) / 4.0)
    predicate_diversity = min(1.0, len(cluster.predicates) / 3.0)
    quality_score = max(_avg(cluster.confidences), _avg(cluster.evidence_qualities))
    cluster_score = round(
        min(
            1.0,
            (0.40 * support_score)
            + (0.20 * subject_diversity)
            + (0.15 * predicate_diversity)
            + (0.20 * quality_score)
            + (0.05 if method_like else 0.0),
        ),
        6,
    )

    top_subject = subject_labels[0] if subject_labels else "the primary outcome"
    subject_text = ", ".join(subject_labels) or "multiple source contexts"
    supporting_nodes = [{"node_type": "Concept", "label": cluster.object_label}]
    supporting_nodes.extend(
        {"node_type": "Publication", "label": title}
        for title in list(cluster.paper_titles.values())[:3]
    )
    if method_like:
        supporting_nodes.append({"node_type": "Method", "label": cluster.object_label})
        title = f"Model {cluster.object_label} explicitly"
        hypothesis = (
            f"In {query_context}, {cluster.object_label} may be a first-class explanatory "
            "variable rather than a nuisance adjustment."
        )
        minimal_test = (
            f"Fit matched models with and without an explicit {cluster.object_label} term "
            f"while keeping the main streak predictors fixed; compare held-out fit and "
            f"coefficient stability around {top_subject}."
        )
        falsifier = (
            f"Reject if adding {cluster.object_label} leaves the main streak effects and "
            "predictive fit essentially unchanged."
        )
        broken_default_assumption = (
            f"{cluster.object_label} can be safely treated as a nuisance covariate instead "
            "of a modeled signal."
        )
        taste_axis = "deep_research_method_signal"
    else:
        supporting_nodes.append(
            {"node_type": "Behavior", "label": cluster.object_label}
        )
        title = _build_mechanism_title(cluster.object_label, query_context)
        hypothesis = _build_mechanism_hypothesis(
            cluster.object_label,
            query_context,
            subject_labels=subject_labels,
        )
        minimal_test = _build_mechanism_test(cluster.object_label, query_context)
        falsifier = _build_mechanism_falsifier(cluster.object_label, query_context)
        broken_default_assumption = (
            f"the core relationship in {query_context} can be explained without explicitly modeling "
            f"{cluster.object_label}."
        )
        taste_axis = "deep_research_mechanism"

    card_id_src = f"{interaction_id or 'no-interaction'}|{cluster.object_label}"
    why_not_bridge = (
        f"This is grounded in {publication_count} deep-research sources that repeatedly connect "
        f"{cluster.object_label} to {subject_text}, not a single neighborhood bridge."
    )

    return {
        "card_id": f"dr_{sha1(card_id_src.encode('utf-8')).hexdigest()[:10]}",
        "title": title,
        "hypothesis": hypothesis,
        "taste_axis": taste_axis,
        "minimal_discriminating_test": minimal_test,
        "falsifier_hint": falsifier,
        "minimal_test": minimal_test,
        "falsifier": falsifier,
        "contradiction_score": round(max(subject_diversity, predicate_diversity), 6),
        "challengeability_score": round(support_score, 6),
        "publication_count": publication_count,
        "supporting_nodes": supporting_nodes,
        "touched_domains": journals,
        "seed_kg_ids": [f"deep_research:{_normalize_key(cluster.object_label)}"],
        "broken_default_assumption": broken_default_assumption,
        "why_this_is_not_just_a_bridge": why_not_bridge,
        "cluster_score": cluster_score,
        "query_relevance_score": query_relevance_score,
        "deep_research_status": "ok",
        "grounding_status": "grounded",
        "evidence_source_scope": (
            "cross_source" if publication_count > 1 else "single_source"
        ),
        "selection_reason": (
            f"Selected because {cluster.object_label} appears in {publication_count} sources "
            f"with {len(cluster.subjects)} subject contexts, {len(cluster.predicates)} predicate patterns, "
            f"and query relevance {query_relevance_score:.2f}."
        ),
        "provenance": {
            "generator_version": IDEA_CARD_VERSION,
            "interaction_id": interaction_id,
            "object_label": cluster.object_label,
            "supporting_paper_ids": sorted(cluster.paper_ids),
            "supporting_paper_titles": _curated_supporting_paper_titles(cluster),
            "top_subjects": subject_labels,
            "top_predicates": predicate_labels,
            "example_quotes": [
                _truncate(item, limit=220) for item in cluster.quotes[:3]
            ],
            "example_claims": [
                _truncate(item, limit=220) for item in cluster.claim_texts[:3]
            ],
            "journals": journals,
            "cluster_score": cluster_score,
            "query_relevance_score": query_relevance_score,
            "avg_confidence": round(_avg(cluster.confidences), 6),
            "avg_evidence_quality": round(_avg(cluster.evidence_qualities), 6),
        },
    }


def _compute_novelty_signals(card: Mapping[str, Any]) -> dict[str, float]:
    publication_count = int(_safe_float(card.get("publication_count"), 0.0))
    support_score = _clip01(publication_count / 4.0)
    bridge_gain = round(
        _clip01(
            (
                0.40
                * min(
                    1.0, len(card.get("provenance", {}).get("top_subjects", [])) / 3.0
                )
            )
            + (
                0.30
                * min(
                    1.0, len(card.get("provenance", {}).get("top_predicates", [])) / 3.0
                )
            )
            + (0.30 * support_score)
        ),
        6,
    )
    contradiction_gain = round(
        _clip01(
            max(
                _safe_float(card.get("contradiction_score"), 0.0),
                _safe_float(card.get("counterintuitiveness"), 0.0),
            )
        ),
        6,
    )
    path_cost_reduction = round(
        _clip01(
            (0.45 * _safe_float(card.get("cluster_score"), 0.0))
            + (0.35 * _safe_float(card.get("testability"), 0.0))
            + (
                0.20
                if "method" in _normalize_key(card.get("taste_axis") or "")
                else 0.05
            )
        ),
        6,
    )
    feasibility = round(
        _clip01(
            (0.45 * _safe_float(card.get("testability"), 0.0))
            + (0.35 * support_score)
            + (
                0.20
                * _safe_float(
                    card.get("provenance", {}).get("avg_evidence_quality"),
                    0.0,
                )
            )
        ),
        6,
    )
    controlled_ood_score = round(
        _clip01(
            (
                0.40 * _safe_float(card.get("wow_score"), 0.0)
                + 0.25 * bridge_gain
                + 0.20 * contradiction_gain
                + 0.15 * path_cost_reduction
            )
            * max(0.35, feasibility)
            * (1.0 - (0.45 * _safe_float(card.get("prior_art_obviousness"), 0.0)))
        ),
        6,
    )
    return {
        "bridge_gain": bridge_gain,
        "contradiction_gain": contradiction_gain,
        "path_cost_reduction": path_cost_reduction,
        "feasibility": feasibility,
        "controlled_ood_score": controlled_ood_score,
    }


def _rank_deep_research_candidates(
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ranked = rank_wow_candidates(candidates)
    ranked.sort(
        key=lambda item: (
            bool(item.get("vetoed")),
            -_safe_float(item.get("wow_score"), 0.0),
            -_safe_float(item.get("query_relevance_score"), 0.0),
            -_safe_float(item.get("cluster_score"), 0.0),
            -_safe_float(item.get("publication_count"), 0.0),
            str(
                item.get("title") or item.get("candidate_label") or item.get("id") or ""
            ),
        )
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
    return ranked


def _publication_rows(rows: Iterable[FlatRelation]) -> dict[str, list[FlatRelation]]:
    grouped: dict[str, list[FlatRelation]] = defaultdict(list)
    for row in rows:
        grouped[row.paper_id].append(row)
    return grouped


def _build_ephemeral_weighted_subgraph(
    *,
    ranked_cards: list[dict[str, Any]],
    relation_rows: list[FlatRelation],
    query_context: str,
    interaction_id: str | None,
) -> dict[str, Any]:
    rows_by_object: dict[str, list[FlatRelation]] = defaultdict(list)
    for row in relation_rows:
        rows_by_object[_normalize_key(row.object_label)].append(row)

    node_index: dict[str, dict[str, Any]] = {}
    edge_index: dict[str, dict[str, Any]] = {}
    card_subgraphs: list[dict[str, Any]] = []

    def ensure_node(
        node_type: str,
        label: str,
        *,
        weight: float,
        attrs: Mapping[str, Any] | None = None,
    ) -> str:
        node_id = _stable_id("drn", node_type, label)
        existing = node_index.get(node_id)
        if existing is None:
            node_index[node_id] = {
                "id": node_id,
                "label": label,
                "node_type": node_type,
                "weight": round(_clip01(weight), 6),
                "attrs": dict(attrs or {}),
            }
        else:
            existing["weight"] = round(
                max(_safe_float(existing.get("weight"), 0.0), _clip01(weight)),
                6,
            )
            if attrs:
                merged_attrs = dict(existing.get("attrs") or {})
                merged_attrs.update(
                    {k: v for k, v in attrs.items() if v not in (None, [], {})}
                )
                existing["attrs"] = merged_attrs
        return node_id

    def ensure_edge(
        source_id: str,
        target_id: str,
        edge_type: str,
        *,
        weight: float,
        evidence_strength: float,
        path_cost: float,
        feasibility: float,
        conditional_validity: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> str:
        edge_id = _stable_id("dre", source_id, edge_type, target_id)
        existing = edge_index.get(edge_id)
        if existing is None:
            edge_index[edge_id] = {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "edge_type": edge_type,
                "weight": round(_clip01(weight), 6),
                "evidence_strength": round(_clip01(evidence_strength), 6),
                "path_cost": round(_clip01(path_cost), 6),
                "feasibility": round(_clip01(feasibility), 6),
                "conditional_validity": dict(conditional_validity or {}),
                "provenance": dict(provenance or {}),
            }
        else:
            existing["weight"] = round(
                max(_safe_float(existing.get("weight"), 0.0), _clip01(weight)),
                6,
            )
            existing["evidence_strength"] = round(
                max(
                    _safe_float(existing.get("evidence_strength"), 0.0),
                    _clip01(evidence_strength),
                ),
                6,
            )
            existing["path_cost"] = round(
                min(_safe_float(existing.get("path_cost"), 1.0), _clip01(path_cost)),
                6,
            )
            existing["feasibility"] = round(
                max(
                    _safe_float(existing.get("feasibility"), 0.0), _clip01(feasibility)
                ),
                6,
            )
        return edge_id

    for card in ranked_cards:
        provenance = card.get("provenance", {})
        if not isinstance(provenance, Mapping):
            continue
        object_label = _normalize_space(provenance.get("object_label"))
        if not object_label:
            continue

        novelty_signals = _compute_novelty_signals(card)
        supporting_rows = rows_by_object.get(_normalize_key(object_label), [])
        supporting_paper_ids = set(provenance.get("supporting_paper_ids") or [])
        if supporting_paper_ids:
            supporting_rows = [
                row for row in supporting_rows if row.paper_id in supporting_paper_ids
            ]
        publication_rows = _publication_rows(supporting_rows)

        focus_node_type = (
            "Method"
            if "method" in _normalize_key(card.get("taste_axis") or "")
            else "Concept"
        )
        focus_node_id = ensure_node(
            focus_node_type,
            object_label,
            weight=max(
                _safe_float(card.get("wow_score"), 0.0),
                _safe_float(card.get("cluster_score"), 0.0),
            ),
            attrs={
                "interaction_id": interaction_id,
                "query_context": query_context,
                "grounding_status": card.get("grounding_status"),
            },
        )
        hypothesis_node_id = ensure_node(
            "Hypothesis",
            _normalize_space(card.get("title")) or object_label,
            weight=_safe_float(card.get("wow_score"), 0.0),
            attrs={
                "card_id": card.get("card_id"),
                "taste_axis": card.get("taste_axis"),
            },
        )

        node_ids = {focus_node_id, hypothesis_node_id}
        edge_ids: set[str] = set()

        concept_to_hypothesis_edge = ensure_edge(
            focus_node_id,
            hypothesis_node_id,
            "supports_hypothesis",
            weight=max(
                _safe_float(card.get("wow_score"), 0.0),
                novelty_signals["controlled_ood_score"],
            ),
            evidence_strength=max(
                _safe_float(provenance.get("avg_confidence"), 0.0),
                _safe_float(provenance.get("avg_evidence_quality"), 0.0),
            ),
            path_cost=max(0.05, 1.0 - novelty_signals["path_cost_reduction"]),
            feasibility=novelty_signals["feasibility"],
            conditional_validity={
                "source_scope": card.get("evidence_source_scope"),
                "supporting_paper_count": len(supporting_paper_ids),
                "journals": provenance.get("journals") or [],
            },
            provenance={"card_id": card.get("card_id")},
        )
        edge_ids.add(concept_to_hypothesis_edge)

        subject_labels = [
            _normalize_space(value)
            for value in (provenance.get("top_subjects") or [])
            if _normalize_space(value)
        ]
        for subject_label in subject_labels:
            subject_rows = [
                row
                for row in supporting_rows
                if _normalize_key(row.subject) == _normalize_key(subject_label)
            ]
            avg_confidence = _avg([row.confidence for row in subject_rows])
            avg_evidence_quality = _avg([row.evidence_quality for row in subject_rows])
            predicate_labels = []
            for row in subject_rows:
                if row.predicate and row.predicate not in predicate_labels:
                    predicate_labels.append(row.predicate)
            subject_node_id = ensure_node(
                "Observation",
                subject_label,
                weight=max(avg_confidence, avg_evidence_quality),
                attrs={
                    "predicate_labels": predicate_labels[:3],
                    "supporting_paper_count": len(
                        {row.paper_id for row in subject_rows}
                    ),
                },
            )
            node_ids.add(subject_node_id)
            subject_edge_id = ensure_edge(
                subject_node_id,
                focus_node_id,
                "context_supports",
                weight=max(
                    avg_confidence,
                    avg_evidence_quality,
                    novelty_signals["bridge_gain"],
                ),
                evidence_strength=max(avg_confidence, avg_evidence_quality),
                path_cost=max(0.05, 1.0 - novelty_signals["path_cost_reduction"]),
                feasibility=novelty_signals["feasibility"],
                conditional_validity={
                    "predicate_labels": predicate_labels[:3],
                    "source_scope": card.get("evidence_source_scope"),
                    "supporting_paper_count": len(
                        {row.paper_id for row in subject_rows}
                    ),
                },
                provenance={
                    "paper_ids": sorted({row.paper_id for row in subject_rows})[:5],
                    "example_quote": _truncate(
                        next(
                            (
                                row.evidence_quote
                                for row in subject_rows
                                if row.evidence_quote
                            ),
                            "",
                        ),
                        limit=180,
                    ),
                },
            )
            edge_ids.add(subject_edge_id)

        for paper_id, paper_rows in list(publication_rows.items())[:5]:
            paper_title = next(
                (row.paper_title for row in paper_rows if row.paper_title),
                paper_id,
            )
            paper_node_id = ensure_node(
                "Publication",
                paper_title,
                weight=max(
                    _avg([row.confidence for row in paper_rows]),
                    _avg([row.evidence_quality for row in paper_rows]),
                ),
                attrs={
                    "paper_id": paper_id,
                    "journal": next(
                        (row.paper_journal for row in paper_rows if row.paper_journal),
                        "",
                    ),
                },
            )
            node_ids.add(paper_node_id)
            paper_edge_id = ensure_edge(
                paper_node_id,
                hypothesis_node_id,
                "provides_evidence_for",
                weight=max(
                    _avg([row.confidence for row in paper_rows]),
                    _avg([row.evidence_quality for row in paper_rows]),
                ),
                evidence_strength=max(
                    _avg([row.confidence for row in paper_rows]),
                    _avg([row.evidence_quality for row in paper_rows]),
                ),
                path_cost=max(0.05, 1.0 - novelty_signals["path_cost_reduction"]),
                feasibility=novelty_signals["feasibility"],
                conditional_validity={
                    "supporting_claim_count": len(paper_rows),
                    "source_scope": "single_publication",
                },
                provenance={
                    "paper_id": paper_id,
                    "example_quote": _truncate(
                        next(
                            (
                                row.evidence_quote
                                for row in paper_rows
                                if row.evidence_quote
                            ),
                            "",
                        ),
                        limit=180,
                    ),
                },
            )
            edge_ids.add(paper_edge_id)

        card_subgraphs.append(
            {
                "card_id": card.get("card_id"),
                "title": card.get("title"),
                "focus_node_id": focus_node_id,
                "node_ids": sorted(node_ids),
                "edge_ids": sorted(edge_ids),
                "novelty_signals": novelty_signals,
                "explanation": (
                    f"Controlled OOD candidate grounded by {len(supporting_paper_ids)} "
                    f"sources around {object_label}, with explicit feasibility and path-cost signals."
                ),
            }
        )

    node_types = Counter(
        str(node.get("node_type") or "").strip() for node in node_index.values()
    )
    edge_types = Counter(
        str(edge.get("edge_type") or "").strip() for edge in edge_index.values()
    )
    return {
        "version": EPHEMERAL_SUBGRAPH_VERSION,
        "scope": "deep_research_session",
        "query": query_context,
        "interaction_id": interaction_id,
        "novelty_objective": {
            "mode": "controlled_ood_search",
            "description": (
                "Sample low-probability but structurally coherent ideas under "
                "mechanistic, evidence, and feasibility constraints."
            ),
            "score_fields": [
                "bridge_gain",
                "contradiction_gain",
                "path_cost_reduction",
                "feasibility",
                "controlled_ood_score",
            ],
        },
        "summary": {
            "node_count": len(node_index),
            "edge_count": len(edge_index),
            "card_subgraph_count": len(card_subgraphs),
            "node_type_counts": dict(node_types),
            "edge_type_counts": dict(edge_types),
        },
        "nodes": list(node_index.values()),
        "edges": list(edge_index.values()),
        "card_subgraphs": card_subgraphs,
    }


def build_deep_research_idea_cards(
    *,
    deep_research_result: Mapping[str, Any],
    kggen_input: Path | str,
    query: str | None = None,
    top_n: int = 5,
    min_supporting_papers: int = 2,
) -> dict[str, Any]:
    """Convert deep-research evidence plus KGGEN relations into ranked idea cards."""

    if top_n <= 0:
        raise ValueError("top_n must be > 0")
    if min_supporting_papers <= 0:
        raise ValueError("min_supporting_papers must be > 0")

    normalized_result = coerce_deep_research_result(dict(deep_research_result))
    relation_rows = load_kggen_relation_rows(kggen_input)
    interaction_id = _extract_interaction_id(normalized_result)
    query_context = _infer_query_context(normalized_result, query)

    clusters = [
        cluster
        for cluster in _build_clusters(relation_rows)
        if len(cluster.paper_ids) >= min_supporting_papers
        and not _should_skip_object_cluster(cluster, query_context)
    ]
    raw_candidates = [
        _build_raw_candidate(
            cluster,
            query_context=query_context,
            interaction_id=interaction_id,
        )
        for cluster in clusters
    ]
    raw_candidates = _apply_query_relevance_floor(raw_candidates, top_n=top_n)
    raw_candidates.sort(key=_candidate_sort_key)
    ranked = _rank_deep_research_candidates(raw_candidates)[:top_n]

    ephemeral_weighted_subgraph = _build_ephemeral_weighted_subgraph(
        ranked_cards=ranked,
        relation_rows=relation_rows,
        query_context=query_context,
        interaction_id=interaction_id,
    )
    card_subgraphs = {
        str(item.get("card_id")): item
        for item in ephemeral_weighted_subgraph.get("card_subgraphs", [])
        if isinstance(item, Mapping) and item.get("card_id") is not None
    }

    candidate_cards: list[dict[str, Any]] = []
    for card in ranked:
        topology_subgraph = card_subgraphs.get(str(card.get("card_id")))
        candidate_cards.append(
            {
                "card_id": card["card_id"],
                "rank": card.get("rank"),
                "title": card["title"],
                "hypothesis": card["hypothesis"],
                "taste_axis": card["taste_axis"],
                "minimal_discriminating_test": card["minimal_discriminating_test"],
                "falsifier_hint": card["falsifier_hint"],
                "selection_reason": card.get("selection_reason"),
                "contradiction_probe": (
                    f"Check whether {card['provenance']['object_label']} behaves consistently "
                    f"across {len(card['provenance']['top_predicates'])} relation patterns."
                ),
                "topology_shift_probe": (
                    f"Track whether {card['provenance']['object_label']} changes role between "
                    "experimental contexts or task regimes."
                ),
                "deep_research_status": "ok",
                "grounding_status": card.get("grounding_status"),
                "evidence_source_scope": card.get("evidence_source_scope"),
                "query_relevance_score": card.get("query_relevance_score"),
                "wow_score": card.get("wow_score"),
                "counterintuitiveness": card.get("counterintuitiveness"),
                "testability": card.get("testability"),
                "impact_radius": card.get("impact_radius"),
                "prior_art_obviousness": card.get("prior_art_obviousness"),
                "execution_gap_only": card.get("execution_gap_only"),
                "broken_default_assumption": card.get("broken_default_assumption"),
                "contradiction_signature": card.get("contradiction_signature"),
                "transfer_signature": card.get("transfer_signature"),
                "why_this_is_not_just_a_bridge": card.get(
                    "why_this_is_not_just_a_bridge"
                ),
                "novelty_signals": _compute_novelty_signals(card),
                "topology_subgraph": topology_subgraph,
                "supporting_paper_titles": card.get("provenance", {}).get(
                    "supporting_paper_titles", []
                ),
                "provenance": card.get("provenance", {}),
            }
        )

    return {
        "ok": True,
        "mode": "deep_research_idea_cards",
        "query": query_context,
        "deep_research": {
            "status": "ok",
            "interaction_id": interaction_id,
            "report_title": _clean_report_title(
                (
                    normalized_result.get("summary")
                    or normalized_result.get("synthesis_full_text")
                    or ""
                ).splitlines()[0]
            )
            or None,
            "documents_total": len(normalized_result.get("documents") or []),
        },
        "candidate_cards": candidate_cards,
        "ephemeral_weighted_subgraph": ephemeral_weighted_subgraph,
        "summary": {
            "n_relation_rows": len(relation_rows),
            "n_object_clusters": len(clusters),
            "n_candidate_cards": len(candidate_cards),
            "min_supporting_papers": min_supporting_papers,
            "weighted_subgraph_node_count": ephemeral_weighted_subgraph["summary"][
                "node_count"
            ],
            "weighted_subgraph_edge_count": ephemeral_weighted_subgraph["summary"][
                "edge_count"
            ],
        },
        "warnings": [] if candidate_cards else ["no_deep_research_idea_cards"],
    }


__all__ = [
    "IDEA_CARD_VERSION",
    "EPHEMERAL_SUBGRAPH_VERSION",
    "build_deep_research_idea_cards",
    "load_kggen_relation_rows",
]
