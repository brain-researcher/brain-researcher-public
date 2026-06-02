"""Shared helpers for predictive FC gate evaluation."""

from __future__ import annotations

from typing import Any


def score_of(record: dict[str, Any]) -> float | None:
    return record.get("scores", {}).get("gold_r2")


def term_index_of(record: dict[str, Any]) -> int | None:
    return record.get("config", {}).get("hyperparameters", {}).get("term_index")


def term_name_of(record: dict[str, Any]) -> str | None:
    hyper = record.get("config", {}).get("hyperparameters", {})
    term_name = hyper.get("term_name")
    if term_name:
        return str(term_name)
    return record.get("config", {}).get("fc_metric")


__all__ = ["score_of", "term_index_of", "term_name_of"]
