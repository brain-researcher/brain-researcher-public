"""Dataset→Task linking helpers for Neo4j."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, List

import yaml

try:  # pragma: no cover - optional dependency
    from rapidfuzz import fuzz, process
except Exception:  # pragma: no cover - optional dependency
    fuzz = None
    process = None

logger = logging.getLogger(__name__)

_NONWORD_RE = re.compile(r"[^\w\s]+")
_WS_RE = re.compile(r"\s+")
_SPLIT_ALIAS_RE = re.compile(r"[;,]")
_LEGACY_NORMALIZATION_ENV = "BR_TASK_LINKER_USE_LEGACY_NORMALIZATION"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


@dataclass
class TaskCandidate:
    task_id: str
    measures_count: int
    name: str


@dataclass
class KeywordRule:
    canonical: str
    patterns: list[re.Pattern[str]]
    confidence: float


@dataclass
class TaskMappingConfig:
    blacklist: set[str]
    remove_suffixes: list[str]
    replacements: list[tuple[re.Pattern, str]]
    fuzzy_threshold: float
    enable_fuzzy: bool = True
    ignore_blacklist: bool = False
    blacklist_terms: set[str] = field(default_factory=set)
    blacklist_patterns: list[re.Pattern[str]] = field(default_factory=list)
    keyword_rules: list[KeywordRule] = field(default_factory=list)


@dataclass
class TaskMatch:
    task_id: str
    method: str
    score: float
    normalized: str
    matched_label: str
    canonical: Optional[str] = None
    measures_count: int = 0
    confidence_hint: Optional[float] = None


@dataclass
class TaskIndex:
    name_to_candidates: dict[str, list[TaskCandidate]]
    name_choices: list[str]

    def resolve(self, normalized: str) -> Optional[TaskCandidate]:
        candidates = self.name_to_candidates.get(normalized)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        return max(candidates, key=lambda c: (c.measures_count, c.task_id))


def load_task_mapping_config(
    path: Path,
    *,
    enable_fuzzy: bool = True,
    ignore_blacklist: bool = False,
) -> TaskMappingConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    thresholds = data.get("thresholds", {}) if isinstance(data, dict) else {}
    fuzzy_threshold = float(thresholds.get("fuzzy_match", 0.8))

    norms = data.get("name_normalizations", {}) if isinstance(data, dict) else {}
    remove_suffixes = list(norms.get("remove_suffixes", []) or [])
    replacements_raw = norms.get("replacements", {}) or {}
    replacements: list[tuple[re.Pattern, str]] = []
    if isinstance(replacements_raw, dict):
        for pattern, repl in replacements_raw.items():
            try:
                replacements.append((re.compile(pattern, flags=re.IGNORECASE), str(repl)))
            except re.error:
                logger.warning("Invalid regex pattern in task_mapping.yaml: %s", pattern)

    config = TaskMappingConfig(
        blacklist=set(),
        remove_suffixes=remove_suffixes,
        replacements=replacements,
        fuzzy_threshold=fuzzy_threshold,
        enable_fuzzy=enable_fuzzy,
        ignore_blacklist=ignore_blacklist,
        keyword_rules=[],
    )

    if not ignore_blacklist:
        blacklist_raw = data.get("blacklist", []) if isinstance(data, dict) else []
        normalized_blacklist = set()
        for entry in blacklist_raw or []:
            normalized = normalize_task(entry, config)
            if normalized:
                normalized_blacklist.add(normalized)
        config.blacklist = normalized_blacklist

        blacklist_terms_raw = data.get("blacklist_terms", []) if isinstance(data, dict) else []
        for entry in blacklist_terms_raw or []:
            normalized = normalize_task(entry, config)
            if normalized:
                config.blacklist_terms.add(normalized)

        blacklist_regex_raw = data.get("blacklist_regex", []) if isinstance(data, dict) else []
        for pattern in blacklist_regex_raw or []:
            try:
                config.blacklist_patterns.append(re.compile(str(pattern), flags=re.IGNORECASE))
            except re.error:
                logger.warning("Invalid blacklist_regex pattern in task_mapping.yaml: %s", pattern)
    keyword_rules_raw = data.get("keyword_rules", []) if isinstance(data, dict) else []
    for entry in keyword_rules_raw or []:
        if not isinstance(entry, dict):
            continue
        canonical = entry.get("canonical")
        if not canonical:
            continue
        keywords = entry.get("keywords_any") or []
        regexes = entry.get("regex") or []
        patterns: list[re.Pattern[str]] = []
        for kw in keywords:
            kw_text = str(kw).strip()
            if not kw_text:
                continue
            try:
                patterns.append(re.compile(re.escape(kw_text), flags=re.IGNORECASE))
            except re.error:
                logger.warning("Invalid keyword entry in task_mapping.yaml: %s", kw_text)
        for regex_entry in regexes:
            try:
                patterns.append(re.compile(str(regex_entry), flags=re.IGNORECASE))
            except re.error:
                logger.warning("Invalid keyword regex in task_mapping.yaml: %s", regex_entry)
        if not patterns:
            continue
        confidence_value = float(entry.get("confidence", 0.55))
        config.keyword_rules.append(
            KeywordRule(canonical=canonical, patterns=patterns, confidence=confidence_value)
        )
    return config


def load_task_synonyms(path: Path, config: TaskMappingConfig) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        return {}

    alias_to_canonical: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        canonical = entry.get("canonical")
        if not canonical:
            continue
        _add_alias(alias_to_canonical, canonical, canonical, config)
        for alias in entry.get("synonyms") or []:
            _add_alias(alias_to_canonical, alias, canonical, config)
        source_aliases = entry.get("source_aliases") or {}
        if isinstance(source_aliases, dict):
            for aliases in source_aliases.values():
                if not aliases:
                    continue
                for alias in aliases:
                    _add_alias(alias_to_canonical, alias, canonical, config)
    return alias_to_canonical


def load_taxonomy_aliases(path: Path, config: TaskMappingConfig) -> dict[str, str]:
    """Load paradigm aliases from task family taxonomy exports."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    families = data.get("families") if isinstance(data, dict) else None
    if not isinstance(families, list):
        return {}

    alias_to_canonical: dict[str, str] = {}
    for family in families:
        if not isinstance(family, dict):
            continue
        subfamilies = family.get("subfamilies") or []
        if not isinstance(subfamilies, list):
            continue
        for subfamily in subfamilies:
            if not isinstance(subfamily, dict):
                continue
            paradigms = subfamily.get("paradigms") or []
            if not isinstance(paradigms, list):
                continue
            for paradigm in paradigms:
                if not isinstance(paradigm, dict):
                    continue
                name = paradigm.get("name")
                if not name:
                    continue
                _add_alias(alias_to_canonical, name, name, config)
                for alias in paradigm.get("aliases") or []:
                    _add_alias(alias_to_canonical, alias, name, config)
    return alias_to_canonical


def _add_alias(
    alias_to_canonical: dict[str, str],
    alias: Optional[str],
    canonical: Optional[str],
    config: TaskMappingConfig,
) -> None:
    if not alias or not canonical:
        return
    alias_str = str(alias).strip()
    canonical_clean = str(canonical).strip()
    if not alias_str or not canonical_clean:
        return
    alias_norm = normalize_task(alias_str, config)
    canonical_norm = normalize_task(canonical_clean, config)
    if not alias_norm or not canonical_norm:
        return
    alias_to_canonical.setdefault(alias_norm, canonical_clean)


@lru_cache(maxsize=1)
def _load_task_matching_profile() -> object | None:
    try:
        from brain_researcher.services.neurokg.utils.matching_profile import (
            load_matching_profiles,
        )
    except Exception:
        return None

    try:
        profiles = load_matching_profiles()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Task matching profile unavailable; using legacy normalization fallback (%s)", exc
        )
        return None

    if not isinstance(profiles, dict):
        return None
    return profiles.get("task")


def _normalize_task_legacy(text: str | None, config: TaskMappingConfig) -> str:
    if text is None:
        return ""
    value = str(text).strip().lower()
    if not value:
        return ""
    for pattern, repl in config.replacements:
        value = pattern.sub(repl, value)
    value = _NONWORD_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    if not value:
        return ""
    for suffix in config.remove_suffixes:
        suffix_clean = str(suffix).strip().lower()
        if suffix_clean and value.endswith(suffix_clean):
            value = value[: -len(suffix_clean)].strip()
            value = _WS_RE.sub(" ", value).strip()
    return value


def _normalize_task_with_profile(text: str | None) -> str:
    if text is None:
        return ""
    value = str(text).strip()
    if not value:
        return ""

    profile = _load_task_matching_profile()
    if profile is None:
        return ""

    normalization = getattr(profile, "normalization", None)
    if normalization is None:
        return ""
    normalize = getattr(normalization, "normalize", None)
    if normalize is None:
        return ""

    try:
        normalized = normalize(value, {})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Task matching profile normalization failed; using legacy fallback (%s)", exc
        )
        return ""

    return str(normalized or "").strip()


def _legacy_normalization_enabled() -> bool:
    raw_value = os.getenv(_LEGACY_NORMALIZATION_ENV, "")
    return raw_value.strip().lower() in _TRUTHY_ENV_VALUES


def normalize_task(text: str | None, config: TaskMappingConfig) -> str:
    if _legacy_normalization_enabled():
        return _normalize_task_legacy(text, config)

    normalized = _normalize_task_with_profile(text)
    if normalized:
        return normalized

    return _normalize_task_legacy(text, config)


def build_task_index(
    rows: Iterable[dict[str, object]],
    config: TaskMappingConfig,
) -> TaskIndex:
    name_to_candidates: dict[str, list[TaskCandidate]] = {}
    for row in rows:
        task_id = row.get("id")
        name = row.get("name") or row.get("label")
        measures_count = int(row.get("measures_count") or 0)
        if not task_id or not name:
            continue
        candidate = TaskCandidate(task_id=str(task_id), measures_count=measures_count, name=str(name))
        for alias in iter_aliases(name, row.get("alias"), row.get("aliases")):
            normalized = normalize_task(alias, config)
            if not normalized:
                continue
            name_to_candidates.setdefault(normalized, []).append(candidate)
    name_choices = list(name_to_candidates.keys())
    return TaskIndex(name_to_candidates=name_to_candidates, name_choices=name_choices)


def iter_aliases(*values: object) -> Iterable[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            for entry in value:
                if entry is None:
                    continue
                yield from iter_aliases(entry)
            continue
        text = str(value).strip()
        if not text:
            continue
        if _SPLIT_ALIAS_RE.search(text):
            for chunk in _SPLIT_ALIAS_RE.split(text):
                chunk = chunk.strip()
                if chunk:
                    yield chunk
        else:
            yield text


def match_task(
    raw_task: str,
    alias_to_canonical: dict[str, str],
    index: TaskIndex,
    config: TaskMappingConfig,
) -> Optional[TaskMatch]:
    normalized = normalize_task(raw_task, config)
    if not normalized:
        return None
    if is_blacklisted_task(raw_task=raw_task, normalized=normalized, config=config):
        return None

    canonical = alias_to_canonical.get(normalized)
    if canonical:
        canonical_norm = normalize_task(canonical, config)
        candidate = index.resolve(canonical_norm)
        if candidate:
            return TaskMatch(
                task_id=candidate.task_id,
                method="alias_match",
                score=1.0,
                normalized=normalized,
                matched_label=canonical_norm,
                canonical=canonical,
                measures_count=candidate.measures_count,
            )

    for rule in config.keyword_rules:
        if any(pattern.search(normalized) for pattern in rule.patterns):
            canonical_norm = normalize_task(rule.canonical, config)
            candidate = index.resolve(canonical_norm)
            if candidate:
                return TaskMatch(
                    task_id=candidate.task_id,
                    method="keyword_rule",
                    score=rule.confidence,
                    normalized=normalized,
                    matched_label=canonical_norm,
                    canonical=rule.canonical,
                    measures_count=candidate.measures_count,
                    confidence_hint=rule.confidence,
                )

    candidate = index.resolve(normalized)
    if candidate:
        return TaskMatch(
            task_id=candidate.task_id,
            method="name_match",
            score=1.0,
            normalized=normalized,
            matched_label=normalized,
            measures_count=candidate.measures_count,
        )

    if config.enable_fuzzy and process is not None and fuzz is not None:
        match = process.extractOne(normalized, index.name_choices, scorer=fuzz.ratio)
        if match:
            match_label, score, _ = match
            if score >= config.fuzzy_threshold * 100:
                candidate = index.resolve(match_label)
                if candidate:
                    return TaskMatch(
                        task_id=candidate.task_id,
                        method="fuzzy_match",
                        score=float(score) / 100.0,
                        normalized=normalized,
                        matched_label=match_label,
                        measures_count=candidate.measures_count,
                    )

    return None


def is_blacklisted_task(*, raw_task: str, normalized: str, config: TaskMappingConfig) -> bool:
    if config.ignore_blacklist:
        return False
    if normalized in config.blacklist:
        return True
    if config.blacklist_terms and any(term in normalized for term in config.blacklist_terms):
        return True
    raw_lower = str(raw_task).strip().lower()
    for pattern in config.blacklist_patterns:
        if pattern.search(raw_lower):
            return True
    return False


__all__ = [
    "TaskCandidate",
    "TaskIndex",
    "TaskMappingConfig",
    "TaskMatch",
    "build_task_index",
    "iter_aliases",
    "load_task_mapping_config",
    "load_task_synonyms",
    "load_taxonomy_aliases",
    "match_task",
    "normalize_task",
]
