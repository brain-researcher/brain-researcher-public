from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
_DATASET_ACCESSION_RE = re.compile(r"\bds\d{6}[a-z]?\b", re.IGNORECASE)
_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class DatasetPublicationSeed:
    kg_id: str
    dataset_id: str
    source_repo_id: str
    title: str
    aliases: tuple[str, ...]
    openneuro_dois: tuple[str, ...]
    primary_url: str | None = None


@dataclass(frozen=True)
class PublicationSearchPlan:
    strategy: str
    query: str
    rationale: str


@dataclass(frozen=True)
class RawPublicationCandidate:
    title: str
    url: str
    candidate_kind: str
    match_confidence: float
    rationale: str
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    year: int | None = None
    journal: str | None = None
    legacy_accession: str | None = None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\x00", " ").split()).strip()


def normalize_doi(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    lowered = lowered.replace("https://doi.org/", "")
    lowered = lowered.replace("http://doi.org/", "")
    lowered = lowered.replace("doi:", "")
    match = _DOI_RE.search(lowered)
    if not match:
        return None
    return match.group(0).rstrip(").,;").lower()


def normalize_title(value: Any) -> str:
    text = _clean_text(value).lower()
    if not text:
        return ""
    return " ".join(_TITLE_TOKEN_RE.findall(text))


def _tokenize_title(value: str) -> set[str]:
    return {
        token
        for token in _TITLE_TOKEN_RE.findall(value.lower())
        if token and token not in _STOPWORDS
    }


def extract_dataset_accessions(*values: Any) -> tuple[str, ...]:
    accessions: set[str] = set()
    for value in values:
        text = _clean_text(value).lower()
        if not text:
            continue
        for match in _DATASET_ACCESSION_RE.findall(text):
            accessions.add(match)
    return tuple(sorted(accessions))


def build_publication_seed(
    *,
    kg_id: str,
    label: str | None,
    properties: Mapping[str, Any] | None,
) -> DatasetPublicationSeed:
    props = dict(properties or {})
    dataset_id = (
        _clean_text(props.get("dataset_id"))
        or _clean_text(props.get("id"))
        or _clean_text(kg_id)
    )
    source_repo_id = _clean_text(props.get("source_repo_id"))
    accessions = extract_dataset_accessions(
        dataset_id,
        source_repo_id,
        props.get("primary_url"),
        props.get("doi"),
        props.get("source_version"),
    )
    if not source_repo_id and accessions:
        source_repo_id = accessions[0]

    title_candidates = [
        _clean_text(label),
        _clean_text(props.get("name")),
        _clean_text(props.get("title")),
    ]
    aliases_raw = props.get("aliases") or props.get("alias") or []
    if isinstance(aliases_raw, str):
        aliases = (_clean_text(aliases_raw),)
    else:
        aliases = tuple(
            value for value in (_clean_text(item) for item in aliases_raw) if value
        )
    title_candidates.extend(aliases)
    title = next((value for value in title_candidates if value), dataset_id)

    doi_values = [
        props.get("doi"),
        props.get("source_version"),
        props.get("primary_url"),
    ]
    openneuro_dois: list[str] = []
    seen_dois: set[str] = set()
    for value in doi_values:
        normalized = normalize_doi(value)
        if normalized and normalized not in seen_dois:
            seen_dois.add(normalized)
            openneuro_dois.append(normalized)

    return DatasetPublicationSeed(
        kg_id=_clean_text(kg_id),
        dataset_id=dataset_id,
        source_repo_id=source_repo_id or dataset_id,
        title=title,
        aliases=tuple(dict.fromkeys(alias for alias in aliases if alias != title)),
        openneuro_dois=tuple(openneuro_dois),
        primary_url=_clean_text(props.get("primary_url")) or None,
    )


def build_search_plans(
    seed: DatasetPublicationSeed,
) -> list[PublicationSearchPlan]:
    plans: list[PublicationSearchPlan] = []
    for doi in seed.openneuro_dois[:2]:
        plans.append(
            PublicationSearchPlan(
                strategy="exact_openneuro_doi",
                query=f'"{doi}" "{seed.source_repo_id}" publication OR paper OR preprint',
                rationale="Use the exact OpenNeuro DOI as the highest-precision anchor.",
            )
        )

    quoted_title = f'"{seed.title}"'
    plans.append(
        PublicationSearchPlan(
            strategy="exact_title_match",
            query=(
                f'{quoted_title} "{seed.source_repo_id}" '
                "publication OR paper OR preprint"
            ),
            rationale="Look for descriptor papers with the same or near-identical title.",
        )
    )
    plans.append(
        PublicationSearchPlan(
            strategy="legacy_openfmri_match",
            query=(
                f'{quoted_title} "{seed.source_repo_id}" '
                '(OpenfMRI OR "Open fMRI") publication OR paper'
            ),
            rationale="Search for legacy OpenfMRI accession/title matches.",
        )
    )
    plans.append(
        PublicationSearchPlan(
            strategy="related_descriptor",
            query=(
                f'{quoted_title} "{seed.source_repo_id}" '
                '(dataset OR descriptor OR "data paper" OR "Data in Brief")'
            ),
            rationale="Search for dataset descriptor papers.",
        )
    )
    plans.append(
        PublicationSearchPlan(
            strategy="related_analysis",
            query=(
                f'{quoted_title} "{seed.source_repo_id}" '
                "(analysis OR decoding OR fmri OR representation)"
            ),
            rationale="Search for closely related analysis papers built on the dataset.",
        )
    )
    return plans


def _candidate_key(candidate: RawPublicationCandidate) -> str:
    doi = normalize_doi(candidate.doi)
    if doi:
        return f"doi:{doi}"
    pmid = _clean_text(candidate.pmid)
    if pmid:
        return f"pmid:{pmid}"
    return f"title:{normalize_title(candidate.title)}"


def _candidate_kind_weight(kind: str) -> float:
    return {
        "exact_openneuro_doi": 0.84,
        "exact_title_match": 0.8,
        "legacy_openfmri_match": 0.68,
        "related_descriptor": 0.56,
        "related_analysis": 0.48,
    }.get(str(kind or "").strip(), 0.35)


def _title_overlap(seed: DatasetPublicationSeed, title: str) -> float:
    seed_tokens = _tokenize_title(seed.title)
    cand_tokens = _tokenize_title(title)
    if not seed_tokens or not cand_tokens:
        return 0.0
    return len(seed_tokens.intersection(cand_tokens)) / max(len(seed_tokens), 1)


def _score_candidate(seed: DatasetPublicationSeed, merged: dict[str, Any]) -> float:
    match_reasons = merged.get("match_reasons") or []
    base = max(
        (_candidate_kind_weight(reason) for reason in match_reasons), default=0.3
    )
    title = _clean_text(merged.get("title"))
    overlap = _title_overlap(seed, title)
    exact_title = normalize_title(title) == normalize_title(seed.title)
    confidence = float(merged.get("best_match_confidence") or 0.0)

    score = base
    score += min(overlap * 0.18, 0.18)
    if exact_title:
        score += 0.12
    if normalize_doi(merged.get("doi")):
        score += 0.08
    if _clean_text(merged.get("pmid")):
        score += 0.05
    if _clean_text(merged.get("legacy_accession")):
        score += 0.04
    score += min(confidence * 0.12, 0.12)
    return round(min(score, 0.99), 4)


def build_candidate_report(
    seed: DatasetPublicationSeed,
    plan_hits: Mapping[str, Sequence[RawPublicationCandidate]],
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    plan_summaries: list[dict[str, Any]] = []

    for plan in build_search_plans(seed):
        hits = list(plan_hits.get(plan.strategy) or [])
        plan_summaries.append(
            {
                "strategy": plan.strategy,
                "query": plan.query,
                "rationale": plan.rationale,
                "n_hits": len(hits),
            }
        )
        for hit in hits:
            key = _candidate_key(hit)
            entry = merged.get(key)
            if entry is None:
                entry = {
                    "title": _clean_text(hit.title),
                    "doi": normalize_doi(hit.doi),
                    "pmid": _clean_text(hit.pmid) or None,
                    "pmcid": _clean_text(hit.pmcid) or None,
                    "year": hit.year,
                    "journal": _clean_text(hit.journal) or None,
                    "url": _clean_text(hit.url),
                    "legacy_accession": _clean_text(hit.legacy_accession) or None,
                    "match_reasons": [],
                    "search_strategies": [],
                    "best_match_confidence": 0.0,
                    "evidence": [],
                }
                merged[key] = entry
            if not entry.get("doi"):
                entry["doi"] = normalize_doi(hit.doi)
            if not entry.get("pmid"):
                entry["pmid"] = _clean_text(hit.pmid) or None
            if not entry.get("pmcid"):
                entry["pmcid"] = _clean_text(hit.pmcid) or None
            if entry.get("year") is None and hit.year is not None:
                entry["year"] = hit.year
            if not entry.get("journal"):
                entry["journal"] = _clean_text(hit.journal) or None
            if not entry.get("legacy_accession"):
                entry["legacy_accession"] = _clean_text(hit.legacy_accession) or None
            if not entry.get("url"):
                entry["url"] = _clean_text(hit.url)
            if _clean_text(hit.title) and (
                not entry.get("title")
                or len(_clean_text(hit.title)) > len(_clean_text(entry.get("title")))
            ):
                entry["title"] = _clean_text(hit.title)

            reason = str(hit.candidate_kind or plan.strategy).strip() or plan.strategy
            if reason not in entry["match_reasons"]:
                entry["match_reasons"].append(reason)
            if plan.strategy not in entry["search_strategies"]:
                entry["search_strategies"].append(plan.strategy)
            confidence = max(0.0, min(float(hit.match_confidence), 1.0))
            if confidence > float(entry["best_match_confidence"]):
                entry["best_match_confidence"] = round(confidence, 4)
            entry["evidence"].append(
                {
                    "strategy": plan.strategy,
                    "query": plan.query,
                    "url": _clean_text(hit.url),
                    "rationale": _clean_text(hit.rationale),
                    "match_confidence": round(confidence, 4),
                }
            )

    candidates = []
    for entry in merged.values():
        entry["title_overlap"] = round(
            _title_overlap(seed, entry.get("title") or ""), 4
        )
        entry["score"] = _score_candidate(seed, entry)
        entry["match_reasons"] = sorted(entry["match_reasons"])
        entry["search_strategies"] = sorted(entry["search_strategies"])
        entry["evidence"] = sorted(
            entry["evidence"],
            key=lambda item: (
                -float(item.get("match_confidence") or 0.0),
                str(item.get("strategy") or ""),
                str(item.get("url") or ""),
            ),
        )
        candidates.append(entry)

    candidates.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -float(item.get("best_match_confidence") or 0.0),
            str(item.get("title") or ""),
        )
    )
    return {
        "dataset_kg_id": seed.kg_id,
        "dataset_id": seed.dataset_id,
        "source_repo_id": seed.source_repo_id,
        "title": seed.title,
        "aliases": list(seed.aliases),
        "openneuro_dois": list(seed.openneuro_dois),
        "primary_url": seed.primary_url,
        "search_plans": plan_summaries,
        "candidates": candidates,
        "summary": {
            "n_plans": len(plan_summaries),
            "n_candidates": len(candidates),
        },
    }
