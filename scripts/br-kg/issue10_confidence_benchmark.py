#!/usr/bin/env python3
"""Run Issue #10 confidence scoring benchmark on real KG samples.

This script compares legacy v1 confidence against v2 conflict/uncertainty-aware
confidence on publication-claim evidence collected from Neo4j.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from brain_researcher.services.br_kg import query_service
from brain_researcher.services.br_kg.scoring.confidence_v2 import (
    EvidenceSignal,
    compute_confidence_v2,
)


@dataclass(frozen=True)
class ScoredCase:
    case_id: str
    confidence_v1: float
    confidence_v2: float
    delta_v2_minus_v1: float
    contradiction_density: float
    uncertainty_density: float
    n_evidence: int
    silver_label: str
    predicted_label: str
    support_count: int
    conflict_count: int
    uncertain_count: int
    focus_bucket: str = "baseline"


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_polarity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"supports", "support", "positive"}:
        return "support"
    if text in {"refutes", "refute", "negative", "conflict"}:
        return "conflict"
    if text in {"mixed", "uncertain"}:
        return "uncertain"
    return "neutral"


def _legacy_confidence(signals: list[EvidenceSignal], max_evidence: int) -> float:
    support = sum(s.strength for s in signals if s.direction == "support")
    conflict = sum(s.strength for s in signals if s.direction == "conflict")
    signal = support + conflict
    if signal <= 0:
        return 0.0
    dominance = abs(support - conflict) / max(signal, 1e-6)
    coverage = min(1.0, signal / max(1.0, float(max_evidence) * 0.35))
    confidence = 0.55 * coverage + 0.45 * dominance
    if support > 0 and conflict > 0:
        confidence *= 0.8
    return round(_clip01(confidence), 4)


def _strength_from_row(row: dict[str, Any]) -> float:
    claim_strength = _clip01(float(row.get("claim_strength") or 0.0))
    method_rigor = _clip01(float(row.get("method_rigor") or 0.0))
    quality = _clip01(float(row.get("evidence_quality_score") or 0.0))
    provenance = _clip01(float(row.get("provenance_completeness") or 0.0))
    if quality <= 0.0:
        quality = 0.60
    return _clip01(
        0.35 * claim_strength + 0.25 * method_rigor + 0.25 * quality + 0.15 * provenance
    )


def _source_reliability_from_row(row: dict[str, Any]) -> float:
    source_text = " ".join(
        [
            str(row.get("journal") or ""),
            str(row.get("pmid") or ""),
            str(row.get("doi") or ""),
        ]
    ).lower()
    if any(token in source_text for token in {"pmid", "doi", "neuroimage", "journal"}):
        return 0.90
    return 0.75


def _silver_label(
    support_strength: float,
    conflict_strength: float,
    uncertainty_density: float,
) -> str:
    if (
        support_strength >= 2.0 * max(conflict_strength, 1e-6)
        and uncertainty_density < 0.35
    ):
        return "supported_proxy"
    if (
        conflict_strength >= 2.0 * max(support_strength, 1e-6)
        and uncertainty_density < 0.35
    ):
        return "conflicted_proxy"
    return "uncertain_proxy"


def _predicted_label(signals: list[EvidenceSignal]) -> str:
    support = sum(s.strength for s in signals if s.direction == "support")
    conflict = sum(s.strength for s in signals if s.direction == "conflict")
    uncertain = sum(s.strength for s in signals if s.direction == "uncertain")
    if support > conflict and support > uncertain:
        return "supported_proxy"
    if conflict > support and conflict > uncertain:
        return "conflicted_proxy"
    return "uncertain_proxy"


def _safe_precision(rows: list[tuple[str, str]]) -> float | None:
    if not rows:
        return None
    hits = sum(1 for pred, gold in rows if pred == gold)
    return hits / len(rows)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_case_rows(limit: int) -> list[dict[str, Any]]:
    db = query_service.get_default_db()
    cypher = """
    MATCH (p:Publication)-[rc:REPORTS_CLAIM]->(c:Claim)
    OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
    WITH p, c, rc, e, sup
    RETURN coalesce(p.id, elementId(p)) AS publication_id,
           coalesce(c.id, elementId(c)) AS claim_id,
           coalesce(c.claim_polarity, rc.claim_polarity, 'uncertain') AS claim_polarity,
           coalesce(c.claim_strength, rc.claim_strength, 0.0) AS claim_strength,
           coalesce(c.method_rigor, rc.method_rigor, e.method_rigor, 0.0) AS method_rigor,
           coalesce(e.evidence_quality_score, sup.evidence_quality_score, 0.0) AS evidence_quality_score,
           coalesce(c.provenance_completeness, rc.provenance_completeness, e.provenance_completeness, sup.provenance_completeness, 0.0) AS provenance_completeness,
           coalesce(p.journal, '') AS journal,
           coalesce(p.pmid, '') AS pmid,
           coalesce(p.doi, '') AS doi
    LIMIT $limit
    """
    return list(db._run(cypher, {"limit": int(limit)}))


def score_cases(rows: list[dict[str, Any]], max_evidence: int) -> list[ScoredCase]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        case_id = str(row.get("publication_id") or "").strip()
        if not case_id:
            continue
        grouped[case_id].append(dict(row))

    scored: list[ScoredCase] = []
    for case_id, items in grouped.items():
        signals: list[EvidenceSignal] = []
        support_count = 0
        conflict_count = 0
        uncertain_count = 0
        for item in items:
            direction = _normalize_polarity(item.get("claim_polarity"))
            if direction == "support":
                support_count += 1
            elif direction == "conflict":
                conflict_count += 1
            elif direction == "uncertain":
                uncertain_count += 1
            signals.append(
                EvidenceSignal(
                    direction=direction,
                    strength=_strength_from_row(item),
                    quality=_clip01(float(item.get("evidence_quality_score") or 0.60)),
                    source_reliability=_source_reliability_from_row(item),
                )
            )
        if not signals:
            continue
        v1 = _legacy_confidence(signals, max_evidence=max_evidence)
        v2 = compute_confidence_v2(signals)
        silver = _silver_label(
            support_strength=v2.support_strength,
            conflict_strength=v2.conflict_strength,
            uncertainty_density=v2.uncertainty_density,
        )
        scored.append(
            ScoredCase(
                case_id=case_id,
                confidence_v1=v1,
                confidence_v2=round(v2.confidence, 4),
                delta_v2_minus_v1=round(v2.confidence - v1, 4),
                contradiction_density=round(v2.contradiction_density, 4),
                uncertainty_density=round(v2.uncertainty_density, 4),
                n_evidence=v2.n_evidence,
                silver_label=silver,
                predicted_label=_predicted_label(signals),
                support_count=support_count,
                conflict_count=conflict_count,
                uncertain_count=uncertain_count,
            )
        )
    return scored


def _select_top_cases(
    pool: list[ScoredCase],
    *,
    limit: int,
    key_fields: tuple[str, ...],
) -> list[ScoredCase]:
    if limit <= 0 or not pool:
        return []

    def _sort_key(item: ScoredCase) -> tuple[float, ...]:
        values: list[float] = []
        for field in key_fields:
            values.append(float(getattr(item, field)))
        values.append(float(item.n_evidence))
        return tuple(values)

    ranked = sorted(pool, key=_sort_key, reverse=True)
    return ranked[:limit]


def stratified_targeted_sample(
    scored_cases: list[ScoredCase],
    *,
    target_conflict_cases: int,
    target_uncertainty_cases: int,
    target_baseline_cases: int,
) -> tuple[list[ScoredCase], dict[str, int]]:
    conflict_pool = [
        case
        for case in scored_cases
        if case.support_count > 0 and case.conflict_count > 0 and case.n_evidence >= 2
    ]
    uncertainty_pool = [
        case
        for case in scored_cases
        if case.uncertain_count > 0 and case.n_evidence >= 1
    ]

    selected: dict[str, ScoredCase] = {}

    for case in _select_top_cases(
        conflict_pool,
        limit=max(0, target_conflict_cases),
        key_fields=("contradiction_density", "uncertainty_density"),
    ):
        selected[case.case_id] = ScoredCase(
            **{**case.__dict__, "focus_bucket": "conflict"}
        )

    residual_uncertainty_pool = [
        case for case in uncertainty_pool if case.case_id not in selected
    ]
    for case in _select_top_cases(
        residual_uncertainty_pool,
        limit=max(0, target_uncertainty_cases),
        key_fields=("uncertainty_density", "contradiction_density"),
    ):
        selected[case.case_id] = ScoredCase(
            **{**case.__dict__, "focus_bucket": "uncertainty"}
        )

    residual_pool = [case for case in scored_cases if case.case_id not in selected]
    baseline_pool = [
        case
        for case in residual_pool
        if case.support_count == 0 or case.conflict_count == 0
    ]
    for case in _select_top_cases(
        baseline_pool,
        limit=max(0, target_baseline_cases),
        key_fields=("confidence_v2", "n_evidence"),
    ):
        selected[case.case_id] = ScoredCase(
            **{**case.__dict__, "focus_bucket": "baseline"}
        )

    # Backfill if any quota cannot be met.
    total_target = (
        max(0, target_conflict_cases)
        + max(0, target_uncertainty_cases)
        + max(0, target_baseline_cases)
    )
    if len(selected) < total_target:
        remaining = [case for case in scored_cases if case.case_id not in selected]
        fallback = _select_top_cases(
            remaining,
            limit=total_target - len(selected),
            key_fields=("contradiction_density", "uncertainty_density"),
        )
        for case in fallback:
            selected[case.case_id] = ScoredCase(
                **{**case.__dict__, "focus_bucket": "backfill"}
            )

    sampled = list(selected.values())
    sample_stats = {
        "available_conflict_cases": len(conflict_pool),
        "available_uncertainty_cases": len(uncertainty_pool),
        "available_baseline_cases": len(
            [
                case
                for case in scored_cases
                if case.support_count == 0 or case.conflict_count == 0
            ]
        ),
        "selected_conflict_cases": sum(
            1 for case in sampled if case.focus_bucket == "conflict"
        ),
        "selected_uncertainty_cases": sum(
            1 for case in sampled if case.focus_bucket == "uncertainty"
        ),
        "selected_baseline_cases": sum(
            1 for case in sampled if case.focus_bucket == "baseline"
        ),
        "selected_backfill_cases": sum(
            1 for case in sampled if case.focus_bucket == "backfill"
        ),
        "selected_total_cases": len(sampled),
        "target_total_cases": total_target,
    }
    return sampled, sample_stats


def _precision_top_fraction(
    scored_cases: list[ScoredCase], *, version: str, fraction: float = 0.1
) -> tuple[float | None, int]:
    if not scored_cases:
        return None, 0
    ratio = max(0.01, min(1.0, float(fraction)))
    n = max(1, int(round(len(scored_cases) * ratio)))
    if version == "v1":
        ranked = sorted(scored_cases, key=lambda c: c.confidence_v1, reverse=True)
    else:
        ranked = sorted(scored_cases, key=lambda c: c.confidence_v2, reverse=True)
    top = ranked[:n]
    return _safe_precision([(c.predicted_label, c.silver_label) for c in top]), len(top)


def summarize(
    scored_cases: list[ScoredCase],
    *,
    high_conf_threshold: float,
    sample_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    sample_stats = sample_stats or {}
    if not scored_cases:
        return {
            "n_cases": 0,
            "high_conf_threshold": high_conf_threshold,
            "high_conf_precision_v1": None,
            "high_conf_precision_v2": None,
            "n_high_conf_v1": 0,
            "n_high_conf_v2": 0,
            "top_decile_precision_v1": None,
            "top_decile_precision_v2": None,
            "n_top_decile": 0,
            "median_delta_high_conflict": None,
            "median_delta_high_uncertainty": None,
            "median_delta_sampled_conflict_bucket": None,
            "median_delta_sampled_uncertainty_bucket": None,
            "median_delta_sampled_baseline_bucket": None,
            "median_confidence_v2_uncertain_only": None,
            "n_uncertain_only": 0,
            "sample_stats": sample_stats,
            "top_shift_cases": [],
        }

    # Build precision sets with a silver proxy label.
    high_conf_rows_v1: list[tuple[str, str]] = []
    high_conf_rows_v2: list[tuple[str, str]] = []
    for case in scored_cases:
        if case.confidence_v1 >= high_conf_threshold:
            high_conf_rows_v1.append((case.predicted_label, case.silver_label))
        if case.confidence_v2 >= high_conf_threshold:
            high_conf_rows_v2.append((case.predicted_label, case.silver_label))

    top_decile_precision_v1, n_top_decile = _precision_top_fraction(
        scored_cases, version="v1", fraction=0.1
    )
    top_decile_precision_v2, _ = _precision_top_fraction(
        scored_cases, version="v2", fraction=0.1
    )

    high_conflict_deltas = [
        case.delta_v2_minus_v1
        for case in scored_cases
        if case.support_count > 0 and case.conflict_count > 0 and case.n_evidence >= 2
    ]
    high_uncertainty_deltas = [
        case.delta_v2_minus_v1
        for case in scored_cases
        if case.uncertainty_density >= 0.25 and case.n_evidence >= 1
    ]
    sampled_conflict_deltas = [
        case.delta_v2_minus_v1
        for case in scored_cases
        if case.focus_bucket == "conflict"
    ]
    sampled_uncertainty_deltas = [
        case.delta_v2_minus_v1
        for case in scored_cases
        if case.focus_bucket == "uncertainty"
    ]
    sampled_baseline_deltas = [
        case.delta_v2_minus_v1
        for case in scored_cases
        if case.focus_bucket == "baseline"
    ]
    uncertain_only_conf_v2 = [
        case.confidence_v2
        for case in scored_cases
        if case.support_count == 0
        and case.conflict_count == 0
        and case.uncertain_count > 0
    ]

    top_shift_cases = sorted(
        scored_cases,
        key=lambda item: abs(item.delta_v2_minus_v1),
        reverse=True,
    )[:20]

    return {
        "n_cases": len(scored_cases),
        "high_conf_threshold": high_conf_threshold,
        "high_conf_precision_v1": _safe_precision(high_conf_rows_v1),
        "high_conf_precision_v2": _safe_precision(high_conf_rows_v2),
        "n_high_conf_v1": len(high_conf_rows_v1),
        "n_high_conf_v2": len(high_conf_rows_v2),
        "top_decile_precision_v1": top_decile_precision_v1,
        "top_decile_precision_v2": top_decile_precision_v2,
        "n_top_decile": n_top_decile,
        "median_delta_high_conflict": (
            float(median(high_conflict_deltas)) if high_conflict_deltas else None
        ),
        "median_delta_high_uncertainty": (
            float(median(high_uncertainty_deltas)) if high_uncertainty_deltas else None
        ),
        "median_delta_sampled_conflict_bucket": (
            float(median(sampled_conflict_deltas)) if sampled_conflict_deltas else None
        ),
        "median_delta_sampled_uncertainty_bucket": (
            float(median(sampled_uncertainty_deltas))
            if sampled_uncertainty_deltas
            else None
        ),
        "median_delta_sampled_baseline_bucket": (
            float(median(sampled_baseline_deltas)) if sampled_baseline_deltas else None
        ),
        "median_confidence_v2_uncertain_only": (
            float(median(uncertain_only_conf_v2)) if uncertain_only_conf_v2 else None
        ),
        "n_uncertain_only": len(uncertain_only_conf_v2),
        "sample_stats": sample_stats,
        "top_shift_cases": [
            {
                "case_id": item.case_id,
                "delta_v2_minus_v1": item.delta_v2_minus_v1,
                "confidence_v1": item.confidence_v1,
                "confidence_v2": item.confidence_v2,
                "contradiction_density": item.contradiction_density,
                "uncertainty_density": item.uncertainty_density,
                "n_evidence": item.n_evidence,
                "focus_bucket": item.focus_bucket,
            }
            for item in top_shift_cases
        ],
    }


def evaluate_independent_slice(
    path: Path,
    *,
    high_conf_threshold: float,
    max_evidence: int,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "missing",
            "path": str(path),
            "n_cases": 0,
            "n_non_supported": 0,
            "independent_accuracy_v1": None,
            "independent_accuracy_v2": None,
            "independent_non_supported_high_conf_rate_v1": None,
            "independent_non_supported_high_conf_rate_v2": None,
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", []) if isinstance(payload, dict) else []
    if not isinstance(raw_cases, list):
        raw_cases = []

    n_cases = 0
    n_non_supported = 0
    correct_v1 = 0
    correct_v2 = 0
    non_supported_high_conf_v1 = 0
    non_supported_high_conf_v2 = 0

    for raw in raw_cases:
        if not isinstance(raw, dict):
            continue
        evidence_rows = raw.get("evidence")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            continue
        signals: list[EvidenceSignal] = []
        for row in evidence_rows:
            if not isinstance(row, dict):
                continue
            count = max(1, int(row.get("count") or 1))
            signal = EvidenceSignal(
                direction=_normalize_polarity(row.get("direction")),
                strength=_clip01(float(row.get("strength") or 0.0)),
                quality=_clip01(float(row.get("quality") or 0.0)),
                source_reliability=_clip01(float(row.get("source_reliability") or 0.0)),
            )
            signals.extend([signal] * count)
        if not signals:
            continue

        n_cases += 1
        v1 = _legacy_confidence(signals, max_evidence=max(1, max_evidence))
        v2 = compute_confidence_v2(signals).confidence

        support_strength = sum(
            signal.strength for signal in signals if signal.direction == "support"
        )
        conflict_strength = sum(
            signal.strength for signal in signals if signal.direction == "conflict"
        )
        uncertain_strength = sum(
            signal.strength for signal in signals if signal.direction == "uncertain"
        )

        predict_supported_v1 = (
            v1 >= high_conf_threshold
            and support_strength > conflict_strength
            and support_strength > uncertain_strength
        )
        predict_supported_v2 = (
            v2 >= high_conf_threshold
            and support_strength > conflict_strength
            and support_strength > uncertain_strength
        )
        gold_supported = str(raw.get("gold_label") or "").strip().lower() == "supported"

        if predict_supported_v1 == gold_supported:
            correct_v1 += 1
        if predict_supported_v2 == gold_supported:
            correct_v2 += 1

        if not gold_supported:
            n_non_supported += 1
            if v1 >= high_conf_threshold:
                non_supported_high_conf_v1 += 1
            if v2 >= high_conf_threshold:
                non_supported_high_conf_v2 += 1

    return {
        "status": "ok",
        "path": str(path),
        "n_cases": n_cases,
        "n_non_supported": n_non_supported,
        "independent_accuracy_v1": (correct_v1 / n_cases) if n_cases else None,
        "independent_accuracy_v2": (correct_v2 / n_cases) if n_cases else None,
        "independent_non_supported_high_conf_rate_v1": (
            non_supported_high_conf_v1 / n_non_supported if n_non_supported else None
        ),
        "independent_non_supported_high_conf_rate_v2": (
            non_supported_high_conf_v2 / n_non_supported if n_non_supported else None
        ),
    }


def evaluate_thresholds(
    *,
    profile: str,
    summary_sampled: dict[str, Any],
    sample_stats: dict[str, int],
    independent_eval: dict[str, Any],
    target_conflict_cases: int,
    target_uncertainty_cases: int,
    target_baseline_cases: int,
) -> dict[str, Any]:
    if profile != "issue10_strong":
        raise ValueError(f"Unsupported threshold profile: {profile}")

    checks: list[dict[str, Any]] = []

    def _record(
        *,
        name: str,
        passed: bool,
        value: float | int | None,
        criterion: str,
        required: bool = True,
        reason: str | None = None,
    ) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "required": bool(required),
                "value": value,
                "criterion": criterion,
                "reason": reason,
            }
        )

    _record(
        name="coverage_conflict",
        passed=sample_stats.get("selected_conflict_cases", 0)
        >= int(round(0.9 * max(0, target_conflict_cases))),
        value=sample_stats.get("selected_conflict_cases"),
        criterion=f">= 90% of target ({target_conflict_cases})",
    )
    _record(
        name="coverage_uncertainty",
        passed=sample_stats.get("selected_uncertainty_cases", 0)
        >= int(round(0.9 * max(0, target_uncertainty_cases))),
        value=sample_stats.get("selected_uncertainty_cases"),
        criterion=f">= 90% of target ({target_uncertainty_cases})",
    )
    _record(
        name="coverage_baseline",
        passed=sample_stats.get("selected_baseline_cases", 0)
        >= int(round(0.9 * max(0, target_baseline_cases))),
        value=sample_stats.get("selected_baseline_cases"),
        criterion=f">= 90% of target ({target_baseline_cases})",
    )

    conflict_delta = summary_sampled.get("median_delta_sampled_conflict_bucket")
    _record(
        name="effect_conflict_delta",
        passed=conflict_delta is not None and float(conflict_delta) <= -0.02,
        value=conflict_delta,
        criterion="<= -0.02",
    )
    uncertainty_delta = summary_sampled.get("median_delta_sampled_uncertainty_bucket")
    _record(
        name="effect_uncertainty_delta",
        passed=uncertainty_delta is not None and float(uncertainty_delta) <= 0.0,
        value=uncertainty_delta,
        criterion="<= 0.00",
    )
    uncertain_only_v2 = summary_sampled.get("median_confidence_v2_uncertain_only")
    n_uncertain_only = int(summary_sampled.get("n_uncertain_only") or 0)
    if n_uncertain_only > 0:
        _record(
            name="effect_uncertain_only_v2",
            passed=uncertain_only_v2 is not None and float(uncertain_only_v2) <= 0.02,
            value=uncertain_only_v2,
            criterion="<= 0.02",
        )
    else:
        _record(
            name="effect_uncertain_only_v2",
            passed=True,
            required=False,
            value=uncertain_only_v2,
            criterion="<= 0.02",
            reason="skipped (no uncertain-only samples)",
        )
    baseline_delta = summary_sampled.get("median_delta_sampled_baseline_bucket")
    _record(
        name="effect_baseline_guardrail",
        passed=baseline_delta is not None and float(baseline_delta) >= 0.05,
        value=baseline_delta,
        criterion=">= +0.05",
    )

    high_conf_v1 = summary_sampled.get("high_conf_precision_v1")
    high_conf_v2 = summary_sampled.get("high_conf_precision_v2")
    n_high_conf_v1 = int(summary_sampled.get("n_high_conf_v1") or 0)
    n_high_conf_v2 = int(summary_sampled.get("n_high_conf_v2") or 0)
    if n_high_conf_v1 > 0 and n_high_conf_v2 == 0:
        _record(
            name="stability_high_conf_precision",
            passed=False,
            value=None,
            criterion="v2 >= v1 - 0.02",
            reason="v2 has zero high-confidence outputs while v1 has non-zero outputs",
        )
    elif n_high_conf_v2 > 0:
        baseline_precision = high_conf_v1 if high_conf_v1 is not None else high_conf_v2
        _record(
            name="stability_high_conf_precision",
            passed=baseline_precision is not None
            and high_conf_v2 is not None
            and float(high_conf_v2) >= float(baseline_precision) - 0.02,
            value=None
            if baseline_precision is None or high_conf_v2 is None
            else float(high_conf_v2) - float(baseline_precision),
            criterion="v2 >= v1 - 0.02",
        )
    else:
        _record(
            name="stability_high_conf_precision",
            passed=True,
            required=False,
            value=None,
            criterion="v2 >= v1 - 0.02",
            reason="skipped (insufficient high-confidence denominator)",
        )

    top_decile_v1 = summary_sampled.get("top_decile_precision_v1")
    top_decile_v2 = summary_sampled.get("top_decile_precision_v2")
    if summary_sampled.get("n_top_decile", 0) > 0:
        _record(
            name="stability_top_decile_precision",
            passed=top_decile_v1 is not None
            and top_decile_v2 is not None
            and float(top_decile_v2) >= float(top_decile_v1) - 0.02,
            value=None
            if top_decile_v1 is None or top_decile_v2 is None
            else float(top_decile_v2) - float(top_decile_v1),
            criterion="v2 >= v1 - 0.02",
        )
    else:
        _record(
            name="stability_top_decile_precision",
            passed=True,
            required=False,
            value=None,
            criterion="v2 >= v1 - 0.02",
            reason="skipped (empty top-decile denominator)",
        )

    if (
        independent_eval.get("status") != "ok"
        or independent_eval.get("n_cases", 0) <= 0
    ):
        _record(
            name="independent_eval_available",
            passed=False,
            value=independent_eval.get("status"),
            criterion="independent eval slice must be available and non-empty",
        )
    else:
        _record(
            name="independent_eval_available",
            passed=True,
            value=independent_eval.get("status"),
            criterion="independent eval slice must be available and non-empty",
        )
        acc_v1 = independent_eval.get("independent_accuracy_v1")
        acc_v2 = independent_eval.get("independent_accuracy_v2")
        _record(
            name="independent_accuracy",
            passed=acc_v1 is not None
            and acc_v2 is not None
            and float(acc_v2) >= float(acc_v1) - 0.02,
            value=None
            if acc_v1 is None or acc_v2 is None
            else float(acc_v2) - float(acc_v1),
            criterion="v2 >= v1 - 0.02",
        )
        rate_v1 = independent_eval.get("independent_non_supported_high_conf_rate_v1")
        rate_v2 = independent_eval.get("independent_non_supported_high_conf_rate_v2")
        target_rate = None if rate_v1 is None else max(0.0, float(rate_v1) - 0.05)
        _record(
            name="independent_non_supported_high_conf_rate",
            passed=target_rate is not None
            and rate_v2 is not None
            and float(rate_v2) <= float(target_rate),
            value=None
            if rate_v1 is None or rate_v2 is None
            else float(rate_v2) - float(rate_v1),
            criterion="v2 <= max(0, v1 - 0.05)",
        )

    passed = all(check["passed"] for check in checks if check["required"])
    return {
        "profile": profile,
        "passed": passed,
        "checks": checks,
    }


def write_markdown(
    path: Path,
    *,
    summary_all: dict[str, Any],
    summary_sampled: dict[str, Any],
    independent_eval: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_stats = summary_sampled.get("sample_stats", {}) or {}
    lines = [
        "# Issue #10 Confidence Benchmark Report",
        "",
        f"- Generated at: `{_utc_now()}`",
        f"- Cases scored (all): `{summary_all['n_cases']}`",
        f"- Cases scored (sampled): `{summary_sampled['n_cases']}`",
        f"- High-confidence threshold: `{summary_sampled['high_conf_threshold']}`",
        "",
        "## Sampling Coverage",
        "",
        f"- Available conflict cases: `{sample_stats.get('available_conflict_cases')}`",
        f"- Available uncertainty cases: `{sample_stats.get('available_uncertainty_cases')}`",
        f"- Available baseline cases: `{sample_stats.get('available_baseline_cases')}`",
        f"- Selected conflict cases: `{sample_stats.get('selected_conflict_cases')}`",
        f"- Selected uncertainty cases: `{sample_stats.get('selected_uncertainty_cases')}`",
        f"- Selected baseline cases: `{sample_stats.get('selected_baseline_cases')}`",
        f"- Selected backfill cases: `{sample_stats.get('selected_backfill_cases')}`",
        "",
        "## Key Metrics (Sampled)",
        "",
        f"- High-confidence precision (v1): `{summary_sampled['high_conf_precision_v1']}` "
        + f"(n={summary_sampled['n_high_conf_v1']})",
        f"- High-confidence precision (v2): `{summary_sampled['high_conf_precision_v2']}` "
        + f"(n={summary_sampled['n_high_conf_v2']})",
        f"- Top-decile precision (v1): `{summary_sampled['top_decile_precision_v1']}` "
        + f"(n={summary_sampled['n_top_decile']})",
        f"- Top-decile precision (v2): `{summary_sampled['top_decile_precision_v2']}` "
        + f"(n={summary_sampled['n_top_decile']})",
        f"- Median Δ(v2-v1) on high-conflict set: `{summary_sampled['median_delta_high_conflict']}`",
        f"- Median Δ(v2-v1) on high-uncertainty set: `{summary_sampled['median_delta_high_uncertainty']}`",
        f"- Median Δ(v2-v1) on sampled conflict bucket: `{summary_sampled['median_delta_sampled_conflict_bucket']}`",
        f"- Median Δ(v2-v1) on sampled uncertainty bucket: `{summary_sampled['median_delta_sampled_uncertainty_bucket']}`",
        f"- Median Δ(v2-v1) on sampled baseline bucket: `{summary_sampled['median_delta_sampled_baseline_bucket']}`",
        f"- Median v2 confidence on uncertain-only cases: `{summary_sampled['median_confidence_v2_uncertain_only']}`",
        "",
        "## Key Metrics (All Cases)",
        "",
        f"- High-confidence precision (v1): `{summary_all['high_conf_precision_v1']}` "
        + f"(n={summary_all['n_high_conf_v1']})",
        f"- High-confidence precision (v2): `{summary_all['high_conf_precision_v2']}` "
        + f"(n={summary_all['n_high_conf_v2']})",
        f"- Top-decile precision (v1): `{summary_all['top_decile_precision_v1']}` "
        + f"(n={summary_all['n_top_decile']})",
        f"- Top-decile precision (v2): `{summary_all['top_decile_precision_v2']}` "
        + f"(n={summary_all['n_top_decile']})",
        f"- Median Δ(v2-v1) on high-conflict set: `{summary_all['median_delta_high_conflict']}`",
        f"- Median Δ(v2-v1) on high-uncertainty set: `{summary_all['median_delta_high_uncertainty']}`",
        "",
        "## Independent Eval Slice",
        "",
        f"- Status: `{independent_eval.get('status')}`",
        f"- Cases: `{independent_eval.get('n_cases')}`",
        f"- Non-supported cases: `{independent_eval.get('n_non_supported')}`",
        f"- Independent accuracy (v1): `{independent_eval.get('independent_accuracy_v1')}`",
        f"- Independent accuracy (v2): `{independent_eval.get('independent_accuracy_v2')}`",
        "- Independent non-supported high-conf rate (v1): "
        + f"`{independent_eval.get('independent_non_supported_high_conf_rate_v1')}`",
        "- Independent non-supported high-conf rate (v2): "
        + f"`{independent_eval.get('independent_non_supported_high_conf_rate_v2')}`",
    ]
    if thresholds:
        lines.extend(["## Threshold Checks", ""])
        lines.append(f"- Profile: `{thresholds.get('profile')}`")
        lines.append(f"- Passed: `{thresholds.get('passed')}`")
        for check in thresholds.get("checks", []):
            suffix = f" (reason={check['reason']})" if check.get("reason") else ""
            lines.append(
                "- "
                + f"{check.get('name')}: pass={check.get('passed')} required={check.get('required')} "
                + f"value={check.get('value')} criterion={check.get('criterion')}{suffix}"
            )
        lines.append("")
        lines.append("## Top Shift Cases")
        lines.append("")
    else:
        lines.extend(["", "## Top Shift Cases", ""])

    for item in summary_sampled.get("top_shift_cases", [])[:10]:
        lines.append(
            "- "
            + f"`{item['case_id']}` Δ={item['delta_v2_minus_v1']} "
            + f"(v1={item['confidence_v1']}, v2={item['confidence_v2']}, "
            + f"conflict={item['contradiction_density']}, uncertainty={item['uncertainty_density']}, "
            + f"n={item['n_evidence']}, bucket={item.get('focus_bucket', 'na')})"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue #10 confidence benchmark on real KG."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50000,
        help="Maximum publication-claim rows to sample.",
    )
    parser.add_argument(
        "--max-evidence",
        type=int,
        default=60,
        help="Legacy v1 max_evidence parameter for confidence computation.",
    )
    parser.add_argument(
        "--high-conf-threshold",
        type=float,
        default=0.70,
        help="Threshold used for high-confidence precision comparison.",
    )
    parser.add_argument(
        "--target-conflict-cases",
        type=int,
        default=120,
        help="Target number of conflict-focused cases in stratified sample.",
    )
    parser.add_argument(
        "--target-uncertainty-cases",
        type=int,
        default=120,
        help="Target number of uncertainty-focused cases in stratified sample.",
    )
    parser.add_argument(
        "--target-baseline-cases",
        type=int,
        default=200,
        help="Target number of baseline cases in stratified sample.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("artifacts/br_kg/issue10/benchmark_raw.json"),
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("artifacts/br_kg/issue10/benchmark_report.md"),
    )
    parser.add_argument(
        "--independent-eval-slice",
        type=Path,
        default=Path("tests/fixtures/br-kg/issue10_independent_eval_slice.json"),
        help="Path to frozen independent evaluation slice fixture.",
    )
    parser.add_argument(
        "--threshold-profile",
        type=str,
        default="issue10_strong",
        help="Threshold profile name for pass/fail gating.",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail with non-zero exit code when benchmark thresholds do not pass.",
    )
    args = parser.parse_args()

    rows = load_case_rows(limit=max(1, int(args.limit)))
    scored_cases_all = score_cases(rows, max_evidence=max(1, int(args.max_evidence)))
    sampled_cases, sample_stats = stratified_targeted_sample(
        scored_cases_all,
        target_conflict_cases=max(0, int(args.target_conflict_cases)),
        target_uncertainty_cases=max(0, int(args.target_uncertainty_cases)),
        target_baseline_cases=max(0, int(args.target_baseline_cases)),
    )
    summary_all = summarize(
        scored_cases_all,
        high_conf_threshold=float(args.high_conf_threshold),
        sample_stats={},
    )
    summary_sampled = summarize(
        sampled_cases,
        high_conf_threshold=float(args.high_conf_threshold),
        sample_stats=sample_stats,
    )
    independent_eval = evaluate_independent_slice(
        Path(args.independent_eval_slice),
        high_conf_threshold=float(args.high_conf_threshold),
        max_evidence=max(1, int(args.max_evidence)),
    )
    thresholds = evaluate_thresholds(
        profile=str(args.threshold_profile),
        summary_sampled=summary_sampled,
        sample_stats=sample_stats,
        independent_eval=independent_eval,
        target_conflict_cases=max(0, int(args.target_conflict_cases)),
        target_uncertainty_cases=max(0, int(args.target_uncertainty_cases)),
        target_baseline_cases=max(0, int(args.target_baseline_cases)),
    )
    payload = {
        "generated_at": _utc_now(),
        "input_rows": len(rows),
        "all_cases": len(scored_cases_all),
        "sampled_cases": len(sampled_cases),
        "summary_all_cases": summary_all,
        "summary_sampled_cases": summary_sampled,
        "independent_eval": independent_eval,
        "thresholds": thresholds,
        "cases": [case.__dict__ for case in sampled_cases],
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown(
        args.output_report,
        summary_all=summary_all,
        summary_sampled=summary_sampled,
        independent_eval=independent_eval,
        thresholds=thresholds,
    )
    print(str(args.output_json))
    print(str(args.output_report))
    if bool(args.enforce_thresholds) and not thresholds.get("passed", False):
        print("threshold checks failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
