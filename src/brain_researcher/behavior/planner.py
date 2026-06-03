"""Prompt-to-paradigm planner for the supported psyflow v1 task set."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from brain_researcher.semantics.taxonomy.matcher import normalize_text

_SUPPORTED_ENTITY_TO_PARADIGM = {
    "task:n-back": "n_back",
    "task:go_no-go": "go_no_go",
    "task:flanker": "flanker",
}

_SUPPORTED_ALIAS_MAP = {
    "n back": "n_back",
    "nback": "n_back",
    "0 back": "n_back",
    "1 back": "n_back",
    "2 back": "n_back",
    "3 back": "n_back",
    "2 back letter": "n_back",
    "2 back letter task": "n_back",
    "letter n back": "n_back",
    "letter n back task": "n_back",
    "letter nback": "n_back",
    "go no go": "go_no_go",
    "gonogo": "go_no_go",
    "gng": "go_no_go",
    "flanker": "flanker",
    "eriksen flanker": "flanker",
    "arrow flanker": "flanker",
    "letter flanker": "flanker",
}

_NBACK_LEVEL_RE = re.compile(
    r"\b(?P<level>[0-9]|zero|one|two|three)\s*[- ]\s*back\b",
    re.IGNORECASE,
)
_DURATION_MIN_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)\b",
    re.IGNORECASE,
)
_TR_RE = re.compile(
    r"\btr\s*=?\s*(?P<value>\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b",
    re.IGNORECASE,
)
_DUMMY_RE = re.compile(
    r"\b(?P<value>\d+)\s*(?:dummy\s*scans?|dummies)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
}


def _canonicalize_candidate_label(label: str) -> str | None:
    normalized = normalize_text(label)
    if not normalized:
        return None
    for alias, paradigm in _SUPPORTED_ALIAS_MAP.items():
        if normalized == alias or normalized.startswith(f"{alias} "):
            return paradigm
    return None


def _normalize_candidates(raw_candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in raw_candidates or []:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        if not label:
            continue
        paradigm = _canonicalize_candidate_label(label)
        if paradigm is None:
            continue
        engine = str(entry.get("engine") or "unknown")
        score = float(entry.get("score") or 0.0)
        if engine == "niclip" and score <= 0.0:
            continue
        dedupe_key = (paradigm, label.casefold(), engine)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "label": label,
                "score": score,
                "engine": engine,
                "paradigm": paradigm,
            }
        )
    return normalized


def _preferred_paradigms_for_query(query: str) -> list[str]:
    normalized = normalize_text(query)
    matches: list[str] = []
    for alias, paradigm in _SUPPORTED_ALIAS_MAP.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            if paradigm not in matches:
                matches.append(paradigm)
    return matches


def _parse_nback_level(query: str) -> int | None:
    match = _NBACK_LEVEL_RE.search(query)
    if not match:
        return None
    raw_level = str(match.group("level") or "").strip().casefold()
    if raw_level.isdigit():
        return int(raw_level)
    return _NUMBER_WORDS.get(raw_level)


def _parse_scanner_overrides(query: str) -> dict[str, Any]:
    scanner: dict[str, Any] = {}
    duration_match = _DURATION_MIN_RE.search(query)
    tr_match = _TR_RE.search(query)
    dummy_match = _DUMMY_RE.search(query)
    if duration_match:
        duration_sec = float(duration_match.group("value")) * 60.0
        scanner["planned_duration_sec"] = duration_sec
    if tr_match:
        scanner["tr_sec"] = float(tr_match.group("value"))
    if dummy_match:
        scanner["dummy_scans"] = int(dummy_match.group("value"))
    if (
        "planned_duration_sec" in scanner
        and "tr_sec" in scanner
    ):
        dummy_scans = int(scanner.get("dummy_scans", 0))
        scanner["n_volumes"] = int(
            math.ceil(float(scanner["planned_duration_sec"]) / float(scanner["tr_sec"]))
        ) + dummy_scans
    return scanner


def _overrides_for_query(query: str, paradigm: str) -> dict[str, Any]:
    normalized = normalize_text(query)
    overrides: dict[str, Any] = {}
    scanner = _parse_scanner_overrides(query)
    if scanner:
        overrides["scanner"] = scanner
    if paradigm == "n_back":
        level = _parse_nback_level(query)
        extras: dict[str, Any] = {}
        if level is not None:
            overrides["conditions"] = [f"{level}-back"]
            extras["target_level"] = level
        if "letter" in normalized or "verbal" in normalized:
            extras["stimulus_variant"] = "letters"
        elif "spatial" in normalized:
            extras["stimulus_variant"] = "spatial"
        if extras:
            overrides["extras"] = extras
    return overrides


def _clarifying_questions(paradigms: list[str]) -> list[str]:
    labels = {
        "n_back": "n-back",
        "go_no_go": "go/no-go",
        "flanker": "flanker",
    }
    rendered = [labels.get(item, item) for item in paradigms]
    if len(rendered) < 2:
        return []
    joined = " or ".join(rendered)
    return [f"Which paradigm do you want: {joined}?"]


def plan_task_from_prompt(
    query: str,
    *,
    raw_candidates: list[dict[str, Any]] | None = None,
    task_matcher: Any | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    query_text = str(query or "").strip()
    if not query_text:
        raise ValueError("query must be non-empty")

    direct_matches = _preferred_paradigms_for_query(query_text)
    if len(direct_matches) > 1:
        return {
            "resolution": "ambiguous",
            "paradigm": None,
            "reason": "multiple_supported_paradigms_detected",
            "clarifying_questions": _clarifying_questions(direct_matches),
            "candidates": [],
            "overrides": {},
        }

    matcher_candidates = raw_candidates
    if matcher_candidates is None:
        if task_matcher is None:
            raise ValueError(
                "plan_task_from_prompt requires either raw_candidates or a task_matcher"
            )
        matcher_candidates = task_matcher.match_candidates(query_text, top_k=top_k) or []

    normalized_candidates = _normalize_candidates(matcher_candidates)
    unique_candidate_paradigms: list[str] = []
    for candidate in normalized_candidates:
        paradigm = str(candidate["paradigm"])
        if paradigm not in unique_candidate_paradigms:
            unique_candidate_paradigms.append(paradigm)

    if direct_matches:
        paradigm = direct_matches[0]
    elif not unique_candidate_paradigms:
        return {
            "resolution": "abstain",
            "paradigm": None,
            "reason": "no_supported_paradigm_match",
            "clarifying_questions": [],
            "candidates": normalized_candidates,
            "overrides": {},
        }
    elif len(unique_candidate_paradigms) > 1:
        return {
            "resolution": "ambiguous",
            "paradigm": None,
            "reason": "multiple_supported_paradigm_candidates",
            "clarifying_questions": _clarifying_questions(unique_candidate_paradigms[:2]),
            "candidates": normalized_candidates,
            "overrides": {},
        }
    else:
        paradigm = unique_candidate_paradigms[0]

    overrides = _overrides_for_query(query_text, paradigm)
    prompt_provenance = {
        "query": query_text,
        "planner": "behavior.plan_task_from_prompt",
        "candidate_label": normalized_candidates[0]["label"] if normalized_candidates else paradigm,
        "resolved_overrides": overrides,
        "unresolved_fields": [],
    }
    if overrides:
        overrides = dict(overrides)
        overrides["prompt_provenance"] = prompt_provenance
    else:
        overrides = {"prompt_provenance": prompt_provenance}

    return {
        "resolution": "matched",
        "paradigm": paradigm,
        "reason": None,
        "clarifying_questions": [],
        "candidates": normalized_candidates,
        "overrides": overrides,
        "scanner_profile": overrides.get("scanner"),
    }


__all__ = ["plan_task_from_prompt"]
