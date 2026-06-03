from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import get_config_root

logger = logging.getLogger(__name__)


CONFIG_ROOT = get_config_root()
MATCHING_PROFILE_VERSION = "niclip_v2"

_ALIAS_CONFLICTS: dict[str, list[tuple[str, str, str]]] = {}


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load YAML from %s: %s", path, exc)
        return None


def _ascii_fold(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _ensure_lower_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [str(v).strip().lower() for v in values if str(v).strip()]


def _ensure_lower_set(values: list[str] | None) -> set[str]:
    return set(_ensure_lower_list(values))


def _compile_replacements(
    raw: dict[str, str] | None,
) -> list[tuple[re.Pattern[str], str]]:
    replacements: list[tuple[re.Pattern[str], str]] = []
    if not raw:
        return replacements
    for pattern, repl in raw.items():
        if not pattern:
            continue
        try:
            compiled = re.compile(str(pattern), flags=re.IGNORECASE)
        except re.error:
            compiled = re.compile(re.escape(str(pattern)), flags=re.IGNORECASE)
        replacements.append((compiled, str(repl)))
    return replacements


def _tokenize(text: str) -> list[str]:
    return [tok for tok in re.split(r"[^\w]+", text) if tok]


def _normalize_tokens(
    tokens: list[str], *, stopwords: set[str], min_token_len: int
) -> list[str]:
    out: list[str] = []
    for token in tokens:
        token_lower = token.lower().strip()
        if not token_lower:
            continue
        if token_lower in stopwords:
            continue
        if len(token_lower) < min_token_len:
            continue
        out.append(token_lower)
    return out


@dataclass(frozen=True)
class NormalizationRules:
    ascii_fold: bool = True
    min_token_len: int = 2
    stopwords: set[str] = field(default_factory=set)
    remove_suffixes: list[str] = field(default_factory=list)
    disallow_suffixes: list[str] = field(default_factory=list)
    replacements: list[tuple[re.Pattern[str], str]] = field(default_factory=list)
    blacklist: set[str] = field(default_factory=set)

    def normalize(self, label: str, alias_to_canonical: dict[str, str]) -> str:
        if not label:
            return ""

        working = label.strip()
        if self.ascii_fold:
            working = _ascii_fold(working)

        for pattern, repl in self.replacements:
            working = pattern.sub(repl, working)

        alias_key = working.strip().lower()
        canonical = alias_to_canonical.get(alias_key)
        if canonical:
            working = canonical

        normalized = working.strip().lower()
        if not normalized:
            return ""

        if self.disallow_suffixes:
            for suffix in self.disallow_suffixes:
                if normalized.endswith(suffix):
                    return ""

        if self.remove_suffixes:
            for suffix in self.remove_suffixes:
                if normalized.endswith(suffix):
                    normalized = normalized[: -len(suffix)].strip()
                    break

        while normalized and normalized[-1] in {".", ",", ";", ":"}:
            normalized = normalized[:-1].strip()

        if not normalized:
            return ""

        tokens = _tokenize(normalized)
        tokens = _normalize_tokens(
            tokens, stopwords=self.stopwords, min_token_len=self.min_token_len
        )
        normalized = " ".join(tokens).strip()

        if not normalized:
            return ""
        if normalized in self.blacklist:
            return ""

        return normalized


@dataclass(frozen=True)
class MatchingProfile:
    name: str
    entity_type: str
    normalization: NormalizationRules
    alias_to_canonical: dict[str, str]
    canonical_to_aliases: dict[str, list[str]]
    alias_to_canonical_soft: dict[str, str] = field(default_factory=dict)
    canonical_to_aliases_soft: dict[str, list[str]] = field(default_factory=dict)
    fuzzy_threshold: int = 85
    embed_threshold: float = 0.85

    def normalize_label(self, label: str, *, alias_mode: str = "strong") -> str:
        alias_map: dict[str, str] = {}
        if alias_mode in {"soft", "all"}:
            alias_map.update(self.alias_to_canonical_soft)
        if alias_mode in {"strong", "all"}:
            alias_map.update(self.alias_to_canonical)
        return self.normalization.normalize(label, alias_map)

    def embedding_label(self, label: str) -> str:
        if not label:
            return ""
        alias_key = label.strip().lower()
        canonical = self.alias_to_canonical.get(alias_key)
        return canonical or label

    def has_disallowed_suffix(self, label: str) -> bool:
        if not label or not self.normalization.disallow_suffixes:
            return False
        normalized = label.strip().lower()
        return any(
            normalized.endswith(suf) for suf in self.normalization.disallow_suffixes
        )

    def to_dict(self, *, include_aliases: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "entity_type": self.entity_type,
            "fuzzy_threshold": self.fuzzy_threshold,
            "embed_threshold": self.embed_threshold,
            "normalization": {
                "ascii_fold": self.normalization.ascii_fold,
                "min_token_len": self.normalization.min_token_len,
                "stopwords": sorted(self.normalization.stopwords),
                "remove_suffixes": self.normalization.remove_suffixes,
                "disallow_suffixes": self.normalization.disallow_suffixes,
                "blacklist": sorted(self.normalization.blacklist),
                "replacements": [
                    {"pattern": pattern.pattern, "replacement": repl}
                    for pattern, repl in self.normalization.replacements
                ],
            },
        }
        if include_aliases:
            payload["alias_to_canonical"] = self.alias_to_canonical
            payload["canonical_to_aliases"] = self.canonical_to_aliases
            payload["alias_to_canonical_soft"] = self.alias_to_canonical_soft
            payload["canonical_to_aliases_soft"] = self.canonical_to_aliases_soft
        return payload


def _add_alias(
    alias_to_canonical: dict[str, str],
    canonical_to_aliases: dict[str, set[str]],
    alias: str | None,
    canonical: str | None,
    *,
    conflicts: list[tuple[str, str, str]] | None = None,
) -> None:
    if not alias or not canonical:
        return
    alias_clean = str(alias).strip()
    canonical_clean = str(canonical).strip()
    if not alias_clean or not canonical_clean:
        return
    alias_key = alias_clean.lower()
    existing = alias_to_canonical.get(alias_key)
    if existing and existing.lower() != canonical_clean.lower():
        if conflicts is not None:
            conflicts.append((alias_clean, existing, canonical_clean))
        return
    alias_to_canonical[alias_key] = canonical_clean
    canonical_key = canonical_clean.lower()
    canonical_to_aliases.setdefault(canonical_key, set()).add(alias_clean)
    canonical_to_aliases.setdefault(canonical_key, set()).add(canonical_clean)


def _aliases_from_task_synonyms(
    path: Path,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    alias_to_canonical: dict[str, str] = {}
    canonical_to_aliases: dict[str, set[str]] = {}
    data = _load_yaml(path) or []
    if not isinstance(data, list):
        return alias_to_canonical, canonical_to_aliases
    for entry in data:
        if not isinstance(entry, dict):
            continue
        canonical = entry.get("canonical")
        for alias in entry.get("synonyms") or []:
            _add_alias(alias_to_canonical, canonical_to_aliases, alias, canonical)
        source_aliases = entry.get("source_aliases") or {}
        if isinstance(source_aliases, dict):
            for aliases in source_aliases.values():
                for alias in aliases or []:
                    _add_alias(
                        alias_to_canonical, canonical_to_aliases, alias, canonical
                    )
        _add_alias(alias_to_canonical, canonical_to_aliases, canonical, canonical)
    return alias_to_canonical, canonical_to_aliases


def _aliases_from_concept_synonyms(
    path: Path,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    alias_to_canonical: dict[str, str] = {}
    canonical_to_aliases: dict[str, set[str]] = {}
    data = _load_yaml(path) or []
    if not isinstance(data, list):
        return alias_to_canonical, canonical_to_aliases
    for entry in data:
        if not isinstance(entry, dict):
            continue
        canonical = entry.get("canonical")
        for alias in entry.get("synonyms") or []:
            _add_alias(alias_to_canonical, canonical_to_aliases, alias, canonical)
        source_aliases = entry.get("source_aliases") or {}
        if isinstance(source_aliases, dict):
            for aliases in source_aliases.values():
                for alias in aliases or []:
                    _add_alias(
                        alias_to_canonical, canonical_to_aliases, alias, canonical
                    )
        _add_alias(alias_to_canonical, canonical_to_aliases, canonical, canonical)
    return alias_to_canonical, canonical_to_aliases


def _aliases_from_task_families(
    path: Path,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    alias_to_canonical: dict[str, str] = {}
    canonical_to_aliases: dict[str, set[str]] = {}
    data = _load_yaml(path) or {}
    families = data.get("families") if isinstance(data, dict) else None
    if not isinstance(families, list):
        return alias_to_canonical, canonical_to_aliases
    for family in families:
        for subfamily in family.get("subfamilies", []) or []:
            for paradigm in subfamily.get("paradigms", []) or []:
                name = paradigm.get("name")
                if name:
                    _add_alias(alias_to_canonical, canonical_to_aliases, name, name)
                for alias in paradigm.get("aliases", []) or []:
                    _add_alias(alias_to_canonical, canonical_to_aliases, alias, name)
    return alias_to_canonical, canonical_to_aliases


def _load_alias_map_json(path: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    alias_to_canonical: dict[str, str] = {}
    canonical_to_aliases: dict[str, set[str]] = {}
    if not path.exists():
        return alias_to_canonical, canonical_to_aliases
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load alias map from %s: %s", path, exc)
        return alias_to_canonical, canonical_to_aliases
    if not isinstance(raw, dict):
        return alias_to_canonical, canonical_to_aliases
    for alias, canonical in raw.items():
        _add_alias(alias_to_canonical, canonical_to_aliases, alias, canonical)
    return alias_to_canonical, canonical_to_aliases


def _merge_alias_sets(
    items: list[tuple[dict[str, str], dict[str, set[str]]]],
) -> tuple[dict[str, str], dict[str, list[str]], list[tuple[str, str, str]]]:
    alias_to_canonical: dict[str, str] = {}
    canonical_to_aliases: dict[str, set[str]] = {}
    conflicts: list[tuple[str, str, str]] = []
    for alias_map, canonical_map in items:
        for alias_key, canonical in alias_map.items():
            _add_alias(
                alias_to_canonical,
                canonical_to_aliases,
                alias_key,
                canonical,
                conflicts=conflicts,
            )
        for canon_key, aliases in canonical_map.items():
            canonical_to_aliases.setdefault(canon_key, set()).update(aliases)
    if conflicts:
        logger.info("Matching profile alias conflicts (kept first): %d", len(conflicts))
    canonical_to_aliases_list = {
        canon: sorted({alias for alias in aliases if alias})
        for canon, aliases in canonical_to_aliases.items()
    }
    return alias_to_canonical, canonical_to_aliases_list, conflicts


@lru_cache(maxsize=1)
def load_matching_profiles(
    config_root: Path | None = None,
) -> dict[str, MatchingProfile]:
    global _ALIAS_CONFLICTS
    root = config_root or CONFIG_ROOT
    mapping_settings = _load_yaml(root / "mapping_settings.yaml") or {}
    task_mapping = _load_yaml(root / "legacy" / "task_mapping.yaml") or {}
    onvoc_tree_path = resolve_mapping_path(
        "onvoc_tree",
        fallback=root / "onvoc_tree.yaml",
        must_exist=False,
    )
    onvoc_tree = _load_yaml(onvoc_tree_path) or {}

    normalization_settings = (
        mapping_settings.get("normalization", {})
        if isinstance(mapping_settings, dict)
        else {}
    )
    base_stopwords = _ensure_lower_set(normalization_settings.get("stopwords"))
    min_token_len = int(normalization_settings.get("min_token_len", 2) or 2)
    ascii_fold = bool(normalization_settings.get("ascii_fold", True))

    onvoc_stopwords = set()
    if isinstance(onvoc_tree, dict):
        policy = onvoc_tree.get("policy", {})
        lexical = policy.get("lexical_affinity", {}) if isinstance(policy, dict) else {}
        onvoc_stopwords = _ensure_lower_set(lexical.get("stopwords"))

    task_remove_suffixes = _ensure_lower_list(
        (task_mapping.get("name_normalizations") or {}).get("remove_suffixes")
    )
    task_replacements = _compile_replacements(
        (task_mapping.get("name_normalizations") or {}).get("replacements")
    )
    task_blacklist = _ensure_lower_set(task_mapping.get("blacklist"))

    task_threshold = task_mapping.get("thresholds", {}).get("fuzzy_match")
    if task_threshold is None:
        task_threshold = (
            mapping_settings.get("scoring_defaults", {})
            .get("accept", {})
            .get("min_score", 0.85)
        )
    task_fuzzy_threshold = int(float(task_threshold) * 100)
    concept_threshold = (
        mapping_settings.get("scoring_defaults", {})
        .get("accept", {})
        .get("min_score", 0.85)
    )
    concept_fuzzy_threshold = int(float(concept_threshold) * 100)

    task_stopwords = base_stopwords | onvoc_stopwords
    concept_stopwords = set(base_stopwords)
    for disallowed in {"task", "tasks", "paradigm", "test", "study", "fmri"}:
        concept_stopwords.discard(disallowed)

    concept_disallow_suffixes = _ensure_lower_list(
        [
            " task",
            " tasks",
            " paradigm",
            " test",
            " experiment",
        ]
    )

    task_alias_to_canonical, task_canonical_to_aliases, task_conflicts_strong = (
        _merge_alias_sets(
            [
                _aliases_from_task_synonyms(
                    root / "legacy" / "mappings" / "task_synonyms.yaml"
                ),
                _load_alias_map_json(
                    root.parent
                    / "scripts"
                    / "neurostore_task"
                    / "taxonomy"
                    / "alias_map.json"
                ),
            ]
        )
    )
    (
        task_alias_to_canonical_soft,
        task_canonical_to_aliases_soft,
        task_conflicts_soft,
    ) = _merge_alias_sets(
        [
            _aliases_from_task_families(
                root / "taxonomy" / "exports" / "task_families_master.yaml"
            ),
        ]
    )
    (
        concept_alias_to_canonical,
        concept_canonical_to_aliases,
        concept_conflicts_strong,
    ) = _merge_alias_sets(
        [
            _aliases_from_concept_synonyms(
                root / "legacy" / "mappings" / "concept_synonyms.yaml"
            ),
        ]
    )
    _ALIAS_CONFLICTS = {
        "task_strong": task_conflicts_strong,
        "task_soft": task_conflicts_soft,
        "concept_strong": concept_conflicts_strong,
    }

    task_profile = MatchingProfile(
        name="task",
        entity_type="task",
        normalization=NormalizationRules(
            ascii_fold=ascii_fold,
            min_token_len=min_token_len,
            stopwords=task_stopwords,
            remove_suffixes=task_remove_suffixes,
            disallow_suffixes=[],
            replacements=task_replacements,
            blacklist=task_blacklist,
        ),
        alias_to_canonical=task_alias_to_canonical,
        canonical_to_aliases=task_canonical_to_aliases,
        alias_to_canonical_soft=task_alias_to_canonical_soft,
        canonical_to_aliases_soft=task_canonical_to_aliases_soft,
        fuzzy_threshold=task_fuzzy_threshold,
        embed_threshold=float(
            mapping_settings.get("scoring_defaults", {})
            .get("accept", {})
            .get("min_score", 0.85)
        ),
    )

    concept_profile = MatchingProfile(
        name="concept",
        entity_type="concept",
        normalization=NormalizationRules(
            ascii_fold=ascii_fold,
            min_token_len=min_token_len,
            stopwords=concept_stopwords,
            remove_suffixes=[],
            disallow_suffixes=concept_disallow_suffixes,
            replacements=[],
            blacklist=set(),
        ),
        alias_to_canonical=concept_alias_to_canonical,
        canonical_to_aliases=concept_canonical_to_aliases,
        alias_to_canonical_soft={},
        canonical_to_aliases_soft={},
        fuzzy_threshold=concept_fuzzy_threshold,
        embed_threshold=float(
            mapping_settings.get("scoring_defaults", {})
            .get("accept", {})
            .get("min_score", 0.85)
        ),
    )

    default_profile = MatchingProfile(
        name="default",
        entity_type="generic",
        normalization=NormalizationRules(
            ascii_fold=True,
            min_token_len=2,
            stopwords=set(),
            remove_suffixes=[" task", " tasks"],
            disallow_suffixes=[],
            replacements=[],
            blacklist=set(),
        ),
        alias_to_canonical={},
        canonical_to_aliases={},
        alias_to_canonical_soft={},
        canonical_to_aliases_soft={},
        fuzzy_threshold=85,
        embed_threshold=0.85,
    )

    return {
        "task": task_profile,
        "concept": concept_profile,
        "default": default_profile,
    }


def get_alias_conflicts() -> dict[str, list[tuple[str, str, str]]]:
    return _ALIAS_CONFLICTS.copy()


def export_matching_profiles(
    output_path: Path,
    profiles: dict[str, MatchingProfile] | None = None,
    conflicts_path: Path | None = None,
) -> None:
    profiles = profiles or load_matching_profiles()
    payload = {
        "version": MATCHING_PROFILE_VERSION,
        "profiles": {
            name: profile.to_dict(include_aliases=True)
            for name, profile in profiles.items()
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    if conflicts_path is not None:
        conflicts = get_alias_conflicts()
        conflicts_path.parent.mkdir(parents=True, exist_ok=True)
        conflicts_path.write_text(
            json.dumps(conflicts, indent=2, sort_keys=True), encoding="utf-8"
        )


def matching_profile_hash(profiles: dict[str, MatchingProfile] | None = None) -> str:
    profiles = profiles or load_matching_profiles()
    payload = {
        name: profile.to_dict(include_aliases=True)
        for name, profile in profiles.items()
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
