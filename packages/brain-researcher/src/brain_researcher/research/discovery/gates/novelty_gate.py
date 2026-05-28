"""Novelty and next-step decisions for TRIBE branch state synthesis."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from brain_researcher.research.discovery.hypothesis_schema import (
    HypothesisEntryV1,
    summarize_hypothesis_ledger,
)

KgContextBuilder = Callable[..., dict[str, Any]]


def _branch_decision_from_ledger(
    branch_id: str,
    ledger_entries: Sequence[HypothesisEntryV1] | None,
) -> tuple[str | None, str | None]:
    if not ledger_entries:
        return None, None

    summary = summarize_hypothesis_ledger(ledger_entries, branch_id=branch_id)
    latest = summary["latest"]
    if latest is None:
        return None, None

    decision = str(latest.decision or "").strip()
    if not decision:
        return None, None

    rationale_bits: list[str] = []
    if latest.posterior_confidence is not None:
        rationale_bits.append(f"posterior={latest.posterior_confidence:.2f}")
    if latest.failure_modes:
        rationale_bits.append(f"failure_modes={','.join(latest.failure_modes)}")
    rationale = "; ".join(rationale_bits) if rationale_bits else None
    return decision, rationale


def _branch_kg_context(
    *,
    manifest: dict[str, Any],
    kg_context: dict[str, Any] | None = None,
    db: Any | None = None,
    kg_context_builder: KgContextBuilder | None = None,
) -> dict[str, Any]:
    if kg_context_builder is None:
        return {}

    payload: dict[str, Any] = {}
    manifest_context = manifest.get("kg_context")
    if isinstance(manifest_context, dict):
        payload.update(manifest_context)

    for key in ("task", "contrast", "region", "design", "method", "study_id"):
        value = manifest.get(key)
        if value is None and kg_context is not None:
            value = kg_context.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()

    if kg_context:
        payload.update({key: value for key, value in kg_context.items() if value is not None})

    if not payload:
        return {}

    return kg_context_builder(
        task=str(payload.get("task") or "") or None,
        contrast=str(payload.get("contrast") or "") or None,
        region=str(payload.get("region") or "") or None,
        design=str(payload.get("design") or "") or None,
        method=str(payload.get("method") or "") or None,
        study_id=str(payload.get("study_id") or "") or None,
        db=db,
    )


def decision_and_rationale(
    *,
    branch_id: str,
    manifest: dict[str, Any],
    best_score: float,
    contrast_rows: list[dict[str, Any]],
    failure_modes: list[str],
    ledger_entries: Sequence[HypothesisEntryV1] | None = None,
    kg_context: dict[str, Any] | None = None,
    db: Any | None = None,
    kg_context_builder: KgContextBuilder | None = None,
) -> tuple[str, str]:
    priority = str(manifest.get("priority", ""))
    is_follow_up = priority.startswith("targeted_") or priority.startswith(
        "closed_loop_round"
    )

    ledger_decision, ledger_rationale = _branch_decision_from_ledger(
        branch_id, ledger_entries
    )
    if ledger_decision:
        if ledger_decision in {"freeze", "frozen"}:
            return (
                "freeze",
                ledger_rationale or "Latest typed hypothesis ledger entry froze this branch.",
            )
        if ledger_decision in {"kill", "killed"}:
            return (
                "kill",
                ledger_rationale or "Latest typed hypothesis ledger entry retired this branch.",
            )
        if ledger_decision in {"pivot_baseline", "pivot_stimulus_family"}:
            return (
                ledger_decision,
                ledger_rationale or "Latest typed hypothesis ledger entry requested a pivot.",
            )

    structured_kg_context = _branch_kg_context(
        manifest=manifest,
        kg_context=kg_context,
        db=db,
        kg_context_builder=kg_context_builder,
    )

    method_compatibility = structured_kg_context.get("method_compatibility")
    if isinstance(method_compatibility, dict) and method_compatibility.get(
        "compatible"
    ) is False:
        design = method_compatibility.get("design", {}).get("canonical")
        method = method_compatibility.get("method", {}).get("canonical")
        return (
            "pivot_baseline",
            (
                "KG method-compatibility lookup marks "
                f"{design or 'this design'} vs {method or 'this method'} as incompatible."
            ),
        )

    if not contrast_rows:
        effect_size_priors = structured_kg_context.get("effect_size_priors")
        if isinstance(effect_size_priors, dict):
            priors = effect_size_priors.get("priors") or {}
            summary = priors.get("cohens_d") if isinstance(priors, dict) else {}
            if isinstance(summary, dict):
                max_abs_d = float(summary.get("max_abs_d", 0.0) or 0.0)
                n_mentions = int(summary.get("n_mentions", 0) or 0)
                if max_abs_d >= 0.5 and n_mentions >= 3:
                    return (
                        "probe_component",
                        "KG effect-size priors are strong enough to probe a component rather than stopping.",
                    )
        return (
            "continue",
            "No usable contrast findings were generated for this branch yet.",
        )

    failures = set(failure_modes)
    if branch_id == "auditory" and "overbroad_auditory_axis" in failures:
        return (
            "pivot_stimulus_family",
            "Auditory follow-up still over-collapses human-vocal and nonhuman conditions.",
        )
    if branch_id in {"math", "rsvp_language"} and {
        "visual_format_confound",
        "lexical_confound",
        "no_clean_double_dissociation",
    } & failures:
        return (
            "pivot_baseline",
            "Current baselines are still too confounded to support a clean branch claim.",
        )
    if branch_id == "tom" and "story_not_question_driven" in failures:
        return (
            "probe_component",
            "Theory-of-mind signal is still story-dominated rather than question-driven.",
        )
    if branch_id == "biological_motion" and "format_mismatch" in failures:
        return (
            "pivot_stimulus_family",
            "Biological motion still looks under-specified and needs a cleaner control family.",
        )

    effect_size_priors = structured_kg_context.get("effect_size_priors")
    if isinstance(effect_size_priors, dict):
        priors = effect_size_priors.get("priors") or {}
        summary = priors.get("cohens_d") if isinstance(priors, dict) else {}
        if isinstance(summary, dict):
            max_abs_d = float(summary.get("max_abs_d", 0.0) or 0.0)
            n_mentions = int(summary.get("n_mentions", 0) or 0)
            if best_score < 0.10 and max_abs_d >= 0.5 and n_mentions >= 3:
                return (
                    "probe_component",
                    "KG effect-size priors support re-specification rather than killing a weak branch outright.",
                )

    if is_follow_up and "weak_effect" in failures and best_score < 0.10:
        return (
            "kill",
            "A follow-up round still failed to produce a usable separation signal.",
        )
    if not failure_modes and best_score >= 0.60:
        return (
            "freeze",
            "This branch now has a stable automated signal without obvious failure tags.",
        )
    return (
        "continue",
        "The branch has usable signal but still needs one focused follow-up before freezing.",
    )


def status_for_decision(decision: str) -> str:
    if decision == "freeze":
        return "frozen"
    if decision == "kill":
        return "killed"
    return "open"


def global_recommendation(
    branches: list[dict[str, Any]],
    *,
    open_branch_priority: Sequence[str],
) -> dict[str, Any]:
    open_branch_ids = [
        branch["branch_id"] for branch in branches if branch["status"] == "open"
    ]
    if open_branch_ids:
        ordered = [
            branch_id for branch_id in open_branch_priority if branch_id in open_branch_ids
        ]
        return {
            "mode": "continue_open_branches",
            "priority_branch_ids": ordered,
        }
    return {
        "mode": "freeze_summarized_branches",
        "priority_branch_ids": [],
    }


__all__ = [
    "KgContextBuilder",
    "decision_and_rationale",
    "global_recommendation",
    "status_for_decision",
]
