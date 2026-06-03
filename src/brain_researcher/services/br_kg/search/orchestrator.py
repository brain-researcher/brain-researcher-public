"""Search orchestrator that fuses KG retrieval with GFS evidence."""

from __future__ import annotations

import datetime as _dt
import importlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from brain_researcher.core.literature.gfs_store import search_gfs_auto
from brain_researcher.services.br_kg.scoring.confidence_v2 import (
    ConfidenceSignals,
    EvidenceSignal,
    compute_confidence_v2,
)

logger = logging.getLogger(__name__)

_WEAK_ALIAS_TOKENS = {
    "task",
    "study",
    "dataset",
    "analysis",
    "method",
    "model",
    "signal",
    "noise",
    "filter",
    "motion",
    "regressor",
    "contrast",
}

_POSITIVE_CONTEXT = {
    "recommend",
    "recommended",
    "default",
    "standard",
    "pipeline",
    "we used",
    "we applied",
    "implemented",
    "parameter",
    "regressor",
    "confound",
    "set to",
    "set at",
    "threshold",
    "preprocess",
    "preprocessing",
    "filtering",
}

_NEGATIVE_CONTEXT = {
    "not recommended",
    "do not use",
    "not used",
    "did not use",
    "avoid",
    "deprecated",
    "removed",
    "obsolete",
    "limitation",
    "future work",
    "unrelated",
}

_UNCERTAINTY_CONTEXT = {
    "may",
    "might",
    "possible",
    "possibly",
    "unclear",
    "inconclusive",
    "uncertain",
    "mixed",
}

_DOC_ROLE_RELIABILITY = {
    "foundation": 0.95,
    "guideline": 0.90,
    "tooling_spec": 0.85,
    "empirical": 0.80,
}

_TOOLING_HINTS = (
    "fmriprep",
    "fitlins",
    "bids",
    "nilearn",
    "spm",
    "afni",
    "fsl",
    "release",
    "version",
    "tool",
)

_GUIDELINE_HINTS = (
    "guideline",
    "best practice",
    "recommendation",
    "consensus",
    "cobidas",
    "standard",
)


@dataclass
class EvidenceHit:
    title: Optional[str]
    pmcid: Optional[str]
    pmid: Optional[str]
    doi: Optional[str]
    doc_id: Optional[str]
    snippet: str
    score: float
    normalized_score: float
    doc_role: str
    year: Optional[int]
    decay: float
    matched_aliases: list[str]
    match_strength: str
    support_context: bool
    direction: str


@dataclass
class OrchestratedResult:
    node_id: str
    node_type: str
    label: str
    score: float
    base_score: float
    evidence_score: float
    properties: dict[str, Any]
    matched_aliases: list[str] = field(default_factory=list)
    evidence: list[EvidenceHit] = field(default_factory=list)
    score_breakdown: dict[str, Any] | None = None
    confidence_signals: ConfidenceSignals | None = None


def _query_service_module():
    return importlib.import_module("brain_researcher.services.br_kg.query_service")


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, tuple):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v is not None]
        except Exception:
            pass
        return [stripped]
    return [str(value)]


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _alias_in_text(text_norm: str, alias_norm: str) -> bool:
    if not alias_norm:
        return False
    if len(alias_norm) <= 3:
        pattern = rf"(?:^|\\s){re.escape(alias_norm)}(?:\\s|$)"
        return re.search(pattern, text_norm) is not None
    return alias_norm in text_norm


def _alias_strength(alias_norm: str) -> str:
    if not alias_norm:
        return "weak"
    if alias_norm in _WEAK_ALIAS_TOKENS:
        return "weak"
    if len(alias_norm) <= 3:
        return "weak"
    return "strong"


def _has_support_context(text_norm: str) -> bool:
    if any(neg in text_norm for neg in _NEGATIVE_CONTEXT):
        return False
    return any(pos in text_norm for pos in _POSITIVE_CONTEXT)


def _evidence_direction(text_norm: str) -> str:
    if any(neg in text_norm for neg in _NEGATIVE_CONTEXT):
        return "conflict"
    if any(tok in text_norm for tok in _UNCERTAINTY_CONTEXT):
        return "uncertain"
    if any(pos in text_norm for pos in _POSITIVE_CONTEXT):
        return "support"
    return "neutral"


def _extract_aliases(properties: dict[str, Any]) -> dict[str, list[str]]:
    alias_map: dict[str, list[str]] = {}
    if not properties:
        return alias_map

    candidates: list[str] = []
    for key in (
        "aliases",
        "alias",
        "synonyms",
        "keywords",
        "name",
        "label",
        "title",
        "dataset_id",
        "id",
        "tool_id",
        "op_key",
    ):
        candidates.extend(_coerce_list(properties.get(key)))

    for alias in candidates:
        norm = _normalize_text(alias)
        if not norm:
            continue
        alias_map.setdefault(norm, [])
        if alias not in alias_map[norm]:
            alias_map[norm].append(alias)
    return alias_map


def _extract_year(text: str) -> Optional[int]:
    if not text:
        return None
    header_match = re.search(
        r"^year\\s*:\\s*(\\d{4})", text, re.MULTILINE | re.IGNORECASE
    )
    if header_match:
        return int(header_match.group(1))
    match = re.search(r"\\b(19|20)\\d{2}\\b", text)
    if match:
        return int(match.group(0))
    return None


def _infer_doc_role(title: str, snippet: str) -> str:
    text = f"{title} {snippet}".lower()
    if any(hint in text for hint in _TOOLING_HINTS):
        return "tooling_spec"
    if any(hint in text for hint in _GUIDELINE_HINTS):
        return "guideline"
    return "empirical"


def _decay_factor(role: str, year: Optional[int]) -> float:
    if role == "foundation":
        return 1.0
    if not year:
        return 1.0
    now_year = _dt.datetime.now().year
    age = max(0.0, float(now_year - year))
    half_life = {
        "tooling_spec": 1.5,
        "guideline": 4.0,
        "empirical": 6.0,
    }.get(role, 5.0)
    if half_life <= 0:
        return 1.0
    return math.pow(0.5, age / half_life)


def _normalize_scores(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    min_val = min(values)
    max_val = max(values)
    if max_val <= min_val:
        return [1.0 for _ in values]
    return [(v - min_val) / (max_val - min_val) for v in values]


def _rank_scores(count: int) -> list[float]:
    if count <= 0:
        return []
    raw = [1.0 / (idx + 1) for idx in range(count)]
    return _normalize_scores(raw)


def _normalize_scoring_version(value: str | None) -> str:
    version = str(value or "v2").strip().lower()
    if version in {"v1", "legacy"}:
        return "v1"
    return "v2"


class SearchOrchestrator:
    """Fuse KG retrieval with literature evidence scoring."""

    def __init__(
        self,
        *,
        alpha: float = 0.65,
        max_nodes: int = 30,
        evidence_limit: int = 3,
    ) -> None:
        self.alpha = alpha
        self.max_nodes = max_nodes
        self.evidence_limit = evidence_limit

    def search(
        self,
        query: str,
        *,
        node_types: Optional[Sequence[str]] = None,
        limit: int = 20,
        gfs_top_k: int = 10,
        gfs_store: Optional[str] = None,
        gfs_model: Optional[str] = None,
        include_score_breakdown: bool = False,
        confidence_scoring_version: str = "v2",
    ) -> tuple[list[OrchestratedResult], dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return [], {"evidence_status": "none", "reason": "empty_query"}
        scoring_version = _normalize_scoring_version(confidence_scoring_version)

        query_service = _query_service_module()
        kg_nodes = query_service.search_nodes(
            query,
            node_types=node_types,
            limit=max(limit * 2, self.max_nodes),
        )
        if not kg_nodes:
            return [], {"evidence_status": "none", "reason": "no_kg_hits"}

        base_scores = [float(node.score or 0.0) for node in kg_nodes]
        base_norms = _normalize_scores(base_scores)

        gfs_result = search_gfs_auto(
            query,
            top_k=gfs_top_k,
            store=gfs_store,
            model=gfs_model,
            gfs_enabled=True,
            weak_evidence=True,
            max_calls=2,
        )
        status = gfs_result.get("status")
        hits = gfs_result.get("hits") or []
        store = gfs_result.get("store")

        if status != "ok":
            meta = {
                "evidence_status": status or "error",
                "evidence_store": store,
                "evidence_stores_hit": list(gfs_result.get("stores_hit") or []),
                "gfs_reason": gfs_result.get("reason"),
                "gfs_call_count": int(gfs_result.get("call_count") or 0),
                "evidence_n_docs": len(hits),
                "error": gfs_result.get("error") or gfs_result.get("reason"),
                "confidence_scoring_version": scoring_version,
            }
            results = [
                OrchestratedResult(
                    node_id=node.kg_id,
                    node_type=node.node_type,
                    label=node.label,
                    score=base_norms[idx],
                    base_score=base_norms[idx],
                    evidence_score=0.0,
                    properties=node.properties or {},
                    score_breakdown={"base_norm": base_norms[idx], "evidence_norm": 0.0}
                    if include_score_breakdown
                    else None,
                )
                for idx, node in enumerate(kg_nodes)
            ]
            return results[:limit], meta

        hit_scores = [float(hit.get("score") or 0.0) for hit in hits]
        if any(score > 0 for score in hit_scores):
            hit_norms = _normalize_scores(hit_scores)
        else:
            hit_norms = _rank_scores(len(hits))

        evidence_scores: list[float] = []
        results: list[OrchestratedResult] = []
        confidence_inputs: list[list[EvidenceSignal]] = []

        for idx, node in enumerate(kg_nodes):
            properties = node.properties or {}
            alias_map = _extract_aliases(properties)
            alias_norms = list(alias_map.keys())
            text_matches: list[EvidenceHit] = []
            matched_aliases: list[str] = []
            text_norm_hits = [
                _normalize_text(
                    f"{hit.get('title') or ''} {hit.get('text') or hit.get('snippet') or ''}"
                )
                for hit in hits
            ]

            for hit_idx, hit in enumerate(hits):
                text_norm = text_norm_hits[hit_idx]
                strong_matches: list[str] = []
                weak_matches: list[str] = []
                for alias_norm in alias_norms:
                    if not _alias_in_text(text_norm, alias_norm):
                        continue
                    aliases = alias_map.get(alias_norm, [])
                    if _alias_strength(alias_norm) == "strong":
                        strong_matches.extend(aliases)
                    else:
                        weak_matches.extend(aliases)

                support_context = _has_support_context(text_norm)
                direction = _evidence_direction(text_norm)
                matched = strong_matches or (
                    weak_matches
                    if direction in {"support", "conflict", "uncertain"}
                    else []
                )
                if not matched:
                    continue

                title = hit.get("title")
                snippet = hit.get("snippet") or ""
                doc_role = _infer_doc_role(title or "", hit.get("text") or snippet)
                year = _extract_year(hit.get("text") or snippet)
                decay = _decay_factor(doc_role, year)
                match_strength = "strong" if strong_matches else "weak"
                weight = 1.0 if strong_matches else 0.6
                if direction == "support":
                    weight *= 1.1
                elif direction == "uncertain":
                    weight *= 0.85
                hit_score = hit_norms[hit_idx] * decay * weight
                evidence_hit = EvidenceHit(
                    title=title,
                    pmcid=hit.get("pmcid"),
                    pmid=hit.get("pmid"),
                    doi=hit.get("doi"),
                    doc_id=hit.get("doc_id"),
                    snippet=snippet,
                    score=hit_score,
                    normalized_score=hit_norms[hit_idx],
                    doc_role=doc_role,
                    year=year,
                    decay=decay,
                    matched_aliases=sorted(set(matched)),
                    match_strength=match_strength,
                    support_context=support_context,
                    direction=direction,
                )
                text_matches.append(evidence_hit)
                matched_aliases.extend(matched)

            text_matches.sort(key=lambda h: h.score, reverse=True)
            text_matches = text_matches[: self.evidence_limit]
            evidence_score = sum(hit.score for hit in text_matches)
            evidence_scores.append(evidence_score)
            confidence_inputs.append(
                [
                    EvidenceSignal(
                        direction=hit.direction,
                        strength=hit.score,
                        quality=hit.normalized_score,
                        source_reliability=_DOC_ROLE_RELIABILITY.get(
                            hit.doc_role, 0.70
                        ),
                    )
                    for hit in text_matches
                ]
            )

            results.append(
                OrchestratedResult(
                    node_id=node.kg_id,
                    node_type=node.node_type,
                    label=node.label,
                    score=0.0,
                    base_score=base_norms[idx],
                    evidence_score=evidence_score,
                    properties=properties,
                    matched_aliases=sorted(set(matched_aliases)),
                    evidence=text_matches,
                    score_breakdown={},
                )
            )

        evidence_norms = _normalize_scores(evidence_scores)
        for idx, result in enumerate(results):
            evidence_norm = evidence_norms[idx] if idx < len(evidence_norms) else 0.0
            confidence_signals = (
                compute_confidence_v2(confidence_inputs[idx])
                if scoring_version == "v2"
                else None
            )
            confidence_multiplier = (
                confidence_signals.confidence if confidence_signals is not None else 1.0
            )
            final_score = (
                result.base_score + self.alpha * evidence_norm * confidence_multiplier
            )
            result.score = final_score
            result.confidence_signals = confidence_signals
            if include_score_breakdown:
                breakdown = {
                    "base_norm": result.base_score,
                    "evidence_norm": evidence_norm,
                    "alpha": self.alpha,
                    "scoring_version": scoring_version,
                    "confidence_multiplier": confidence_multiplier,
                }
                if confidence_signals is not None:
                    breakdown.update(confidence_signals.as_dict())
                result.score_breakdown = breakdown
            else:
                result.score_breakdown = None

        results.sort(key=lambda r: r.score, reverse=True)
        meta = {
            "evidence_status": "ok" if hits else "none",
            "evidence_store": store,
            "evidence_stores_hit": list(gfs_result.get("stores_hit") or []),
            "gfs_reason": gfs_result.get("reason"),
            "gfs_call_count": int(gfs_result.get("call_count") or 0),
            "evidence_n_docs": len(hits),
            "model": gfs_result.get("model"),
            "query_used": gfs_result.get("query_used") or gfs_result.get("query"),
            "confidence_scoring_version": scoring_version,
        }
        return results[:limit], meta


__all__ = ["SearchOrchestrator", "OrchestratedResult", "EvidenceHit"]
