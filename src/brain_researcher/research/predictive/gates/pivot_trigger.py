"""Pivot-trigger gate for predictive FC term discovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import score_of, term_index_of, term_name_of


def detect_unexpected_winners(
    rows: list[dict[str, Any]],
    leader: dict[str, Any],
    comparator: dict[str, Any] | None,
    defaults: Mapping[str, float],
) -> list[dict[str, Any]]:
    leader_score = float(leader["best_gold_r2"])
    leader_key = (leader["term_index"], leader["backbone"])
    winners: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str | None]] = set()

    if (
        leader_score >= float(defaults["unexpected_winner_min_r2"])
        and comparator is not None
        and (
            leader["backbone"] != comparator["backbone"]
            or leader["term_index"] != comparator["term_index"]
        )
    ):
        winners.append(
            {
                "term_index": leader["term_index"],
                "term_name": leader["term_name"],
                "backbone": leader["backbone"],
                "score": leader["best_gold_r2"],
                "run_id": leader["run_id"],
                "why_unexpected": "Current winner displaced the prior simple comparator/incumbent on a different term or backbone.",
            }
        )
        seen.add(leader_key)

    ranked = sorted(
        rows,
        key=lambda record: score_of(record) if score_of(record) is not None else float("-inf"),
        reverse=True,
    )
    min_score = float(defaults["unexpected_winner_min_r2"])
    margin = float(defaults["unexpected_winner_margin_r2"])
    for record in ranked:
        score = score_of(record)
        term_index = term_index_of(record)
        backbone = record.get("config", {}).get("backbone")
        if score is None or term_index is None or backbone is None:
            continue
        key = (term_index, backbone)
        if key in seen or key == leader_key:
            continue
        if score < min_score and score < leader_score - margin:
            continue
        winners.append(
            {
                "term_index": term_index,
                "term_name": term_name_of(record),
                "backbone": backbone,
                "score": score,
                "run_id": record.get("run_id"),
                "why_unexpected": "Non-incumbent term/backbone pair remained unexpectedly competitive with the current target leader.",
            }
        )
        seen.add(key)
        if len(winners) >= 2:
            break

    return winners


def build_pivot_trigger(
    rows: list[dict[str, Any]],
    leader: dict[str, Any],
    comparator: dict[str, Any] | None,
    defaults: Mapping[str, float],
) -> dict[str, Any]:
    unexpected_winners = detect_unexpected_winners(rows, leader, comparator, defaults)
    return {
        "unexpected_winners": unexpected_winners,
        "required_next_step": (
            "probe_unexpected_winner" if unexpected_winners else "broaden_term_search"
        ),
        "pass": bool(unexpected_winners),
    }


__all__ = ["build_pivot_trigger", "detect_unexpected_winners"]
