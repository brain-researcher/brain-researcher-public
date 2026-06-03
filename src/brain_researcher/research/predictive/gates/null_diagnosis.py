"""Null-diagnosis gate for predictive FC term discovery."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .common import score_of, term_index_of


def best_score_by_term(rows: list[dict[str, Any]]) -> dict[int, float]:
    best: dict[int, float] = {}
    for record in rows:
        term_index = term_index_of(record)
        score = score_of(record)
        if term_index is None or score is None:
            continue
        incumbent = best.get(term_index)
        if incumbent is None or score > incumbent:
            best[term_index] = score
    return best


def best_score_by_backbone(rows: list[dict[str, Any]]) -> dict[str, float]:
    best: dict[str, float] = {}
    for record in rows:
        backbone = record.get("config", {}).get("backbone")
        score = score_of(record)
        if backbone is None or score is None:
            continue
        incumbent = best.get(backbone)
        if incumbent is None or score > incumbent:
            best[backbone] = score
    return best


def shared_term_spread(rows: list[dict[str, Any]]) -> tuple[float, int | None]:
    by_term: dict[int, list[float]] = defaultdict(list)
    for record in rows:
        term_index = term_index_of(record)
        score = score_of(record)
        if term_index is None or score is None:
            continue
        by_term[term_index].append(score)
    best_spread = 0.0
    best_term: int | None = None
    for term_index, scores in by_term.items():
        if len(scores) < 2:
            continue
        spread = max(scores) - min(scores)
        if spread > best_spread:
            best_spread = spread
            best_term = term_index
    return best_spread, best_term


def backbone_term_range(
    rows: list[dict[str, Any]],
    backbone: str,
) -> tuple[float, dict[int, float]]:
    term_scores: dict[int, float] = {}
    for record in rows:
        if record.get("config", {}).get("backbone") != backbone:
            continue
        term_index = term_index_of(record)
        score = score_of(record)
        if term_index is None or score is None:
            continue
        incumbent = term_scores.get(term_index)
        if incumbent is None or score > incumbent:
            term_scores[term_index] = score
    if not term_scores:
        return 0.0, {}
    return max(term_scores.values()) - min(term_scores.values()), term_scores


def build_null_diagnosis(
    rows: list[dict[str, Any]],
    leader: dict[str, Any],
    defaults: Mapping[str, float],
) -> dict[str, Any]:
    pipeline_spread, spread_term_index = shared_term_spread(rows)
    term_range, leader_term_scores = backbone_term_range(rows, leader["backbone"])
    positive_terms = sorted(
        term_index
        for term_index, score in best_score_by_term(rows).items()
        if score > 0
    )
    positive_backbones = sorted(
        backbone
        for backbone, score in best_score_by_backbone(rows).items()
        if score > 0
    )
    evidence: list[str] = []

    if pipeline_spread >= float(defaults["pipeline_spread_threshold_r2"]):
        axis = "pipeline"
        evidence.append(
            f"At least one shared term shows large backbone sensitivity (max spread {pipeline_spread:.6f} on term {spread_term_index})."
        )
        action = "change_pipeline_axis"
    elif term_range >= float(defaults["term_signal_range_threshold_r2"]):
        axis = "term"
        evidence.append(
            f"The current leader backbone `{leader['backbone']}` changes materially across terms (range {term_range:.6f})."
        )
        action = "change_term_axis"
    else:
        axis = "measure"
        evidence.append(
            "Changing terms and backbones has not opened a convincing effect; treat this as a measure-resolution problem before blaming one specific term."
        )
        action = "change_measure_axis"

    evidence.append(f"Positive terms observed so far: {positive_terms or 'none'}")
    evidence.append(
        f"Positive backbones observed so far: {positive_backbones or 'none'}"
    )
    if leader_term_scores:
        ranked_terms = sorted(
            leader_term_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:4]
        evidence.append(
            "Top leader-backbone terms: "
            + ", ".join(f"{term}:{score:.6f}" for term, score in ranked_terms)
        )

    return {
        "axis": axis,
        "next_axis_to_change": action,
        "pipeline_spread_r2": pipeline_spread,
        "pipeline_spread_term_index": spread_term_index,
        "leader_term_range_r2": term_range,
        "evidence": evidence,
    }


__all__ = [
    "backbone_term_range",
    "best_score_by_backbone",
    "best_score_by_term",
    "build_null_diagnosis",
    "shared_term_spread",
]
