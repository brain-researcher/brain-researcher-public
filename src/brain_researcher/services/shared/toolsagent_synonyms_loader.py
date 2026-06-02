"""Intent synonym loader for catalog-driven planner (shared core).

This module loads synonym mappings from YAML files and provides intent matching
functionality to map natural language phrases to canonical operators.

Synonym files are loaded in priority order:
1. op_synonyms.yaml (highest priority - operator-specific)
2. task_synonyms.yaml
3. concept_synonyms.yaml
4. roi_synonyms.yaml (lowest priority)

If the same phrase appears in multiple files, the highest priority mapping wins.

Modality scoping:
- Operators can be scoped to modalities using `@` syntax: `connectome@fmri`
- When matching with a modality, scoped operators get bonus weight
- Unscoped operators match all modalities

Relocated from ``services/agent/planner/synonyms_loader`` into the shared layer
so that the lower ``services/tools`` layer can depend on the pure synonym-map
helpers without importing from ``services/agent``. The ``match_intents_from_text``
function remains in the agent module because it depends on the agent-internal
capability catalog. The agent module re-exports everything here for callers.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import resolve_from_config

# Regex to remove punctuation
RE_WORD = re.compile(r"[^\w\s@]+")  # Keep @ for modality scoping


def _clean(text: str) -> str:
    """Normalize text: lowercase + strip punctuation + collapse whitespace.

    Args:
        text: Input text to normalize

    Returns:
        Normalized text string

    Examples:
        >>> _clean("Skull-Strip!")
        'skull strip'
        >>> _clean("  fMRI   connectivity  ")
        'fmri connectivity'
    """
    # Remove punctuation but keep @ for modality scoping
    normalized = RE_WORD.sub(" ", text.lower())
    # Collapse whitespace
    return " ".join(normalized.split())


def _load_yaml(path: Path) -> dict[str, list[str]]:
    """Load YAML file and return dict of canonical → phrases.

    Handles two formats:
    1. op_synonyms.yaml format: dict with canonical → list of phrases
    2. task/concept/roi format: list of dicts with 'canonical' and 'synonyms' keys

    Args:
        path: Path to YAML file

    Returns:
        Dict mapping canonical names to lists of synonym phrases
        Returns empty dict if file doesn't exist
    """
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data:
        return {}

    # Handle op_synonyms.yaml format (dict → list)
    if isinstance(data, dict):
        return data

    # Handle task/concept/roi format (list of dicts)
    if isinstance(data, list):
        result = {}
        for item in data:
            if isinstance(item, dict) and "canonical" in item and "synonyms" in item:
                canonical = item["canonical"]
                synonyms = item["synonyms"]
                result[canonical] = (
                    synonyms if isinstance(synonyms, list) else [synonyms]
                )
        return result

    return {}


def get_mappings_dir() -> Path:
    """Get the directory containing synonym mapping files.

    Returns:
        Path to configs/legacy/mappings/ directory
    """
    return resolve_mapping_path(
        "legacy_mappings_dir",
        fallback=resolve_from_config("legacy", "mappings"),
        must_exist=False,
    )


@lru_cache(maxsize=1)
def load_synonym_map() -> dict[str, str]:
    """Build phrase → canonical operator map from multiple YAML files.

    Files are loaded in priority order (highest priority first):
    1. op_synonyms.yaml - operator-specific synonyms (highest priority)
    2. intent_synonyms.yaml - intent-level synonyms (catalog-aligned)
    3. task_synonyms.yaml - task name synonyms
    4. concept_synonyms.yaml - cognitive concept synonyms
    5. roi_synonyms.yaml - brain region synonyms (lowest priority)

    For overlapping phrases, the highest priority file wins.

    Returns:
        Dict mapping normalized phrases to canonical operator names

    Examples:
        >>> map = load_synonym_map()
        >>> map.get("skull strip")
        'skull_strip'
        >>> map.get("functional connectivity")
        'connectome@fmri'
    """
    legacy_dir = get_mappings_dir()

    # Define sources in REVERSE priority order (we use setdefault, which keeps first)
    # So we load lowest priority first
    sources = [
        legacy_dir / "roi_synonyms.yaml",
        legacy_dir / "concept_synonyms.yaml",
        legacy_dir / "task_synonyms.yaml",
        legacy_dir / "intent_synonyms.yaml",
        legacy_dir / "op_synonyms.yaml",  # Highest priority - loaded last
    ]

    phrase_to_op: dict[str, str] = {}

    # Process files in reverse order so op_synonyms has precedence
    for src in reversed(sources):
        data = _load_yaml(src)
        for canonical, phrases in data.items():
            if not phrases:
                continue
            for phrase in phrases:
                if not phrase:
                    continue
                key = _clean(phrase)
                if not key:
                    continue
                # Keep first-seen (higher priority sources are iterated first)
                phrase_to_op.setdefault(key, canonical)

    return phrase_to_op


def match_intents(text: str, modality: str | None = None) -> list[str]:
    """Return probable operators (ordered by confidence) for the given text.

    Matches work as follows:
    1. Clean and tokenize the input text
    2. Look up each token/phrase in the synonym map
    3. Filter by modality if specified
    4. Rank by match quality (exact modality scope > general match)
    5. Return unique operators in ranked order

    Args:
        text: Natural language intent text (e.g., "skull strip the T1 image")
        modality: Optional modality filter (e.g., "fmri", "smri", "dmri")

    Returns:
        List of canonical operator names, ranked by confidence

    Examples:
        >>> match_intents("Please skull strip the T1 image")
        ['skull_strip']
        >>> match_intents("compute functional connectivity", modality="fmri")
        ['connectome@fmri', 'seed_connectivity']
        >>> match_intents("register and align images")
        ['registration', 'linear_registration']
    """
    cleaned = _clean(text)

    # Generate tokens: full text + individual words
    tokens: set[str] = {cleaned}
    tokens.update(cleaned.split())

    # Also try bigrams and trigrams for better phrase matching
    words = cleaned.split()
    for i in range(len(words) - 1):
        tokens.add(" ".join(words[i : i + 2]))  # bigrams
    for i in range(len(words) - 2):
        tokens.add(" ".join(words[i : i + 3]))  # trigrams

    synonym_map = load_synonym_map()
    matches: list[tuple[str, int]] = []  # (operator, weight)
    seen: set[str] = set()

    for token in tokens:
        canon = synonym_map.get(token)
        if not canon:
            continue

        # Parse modality scope if present
        if "@" in canon:
            op, op_modality = canon.split("@", 1)
            # If user specified modality and it doesn't match, skip
            if modality and op_modality and op_modality != modality.lower():
                continue
            # Bonus weight for exact modality match
            weight = 2
            result_op = op  # Return unscoped operator name
        else:
            op = canon
            weight = 1
            result_op = op

        # Avoid duplicates
        if result_op not in seen:
            matches.append((result_op, weight))
            seen.add(result_op)

    # Sort by weight (descending) then alphabetically for stability; prefer longer phrases by secondary length sort
    matches.sort(key=lambda x: (-x[1], -len(x[0]), x[0]))

    # Deduplicate while preserving order
    ranked_ops: list[str] = []
    seen_ops: set[str] = set()
    for op, _ in matches:
        if op in seen_ops:
            continue
        ranked_ops.append(op)
        seen_ops.add(op)

    # Heuristic: prefer python GLM over generic/glm containers
    if "glm_first_level_py" in ranked_ops:
        ranked_ops = [
            op for op in ranked_ops if op not in {"glm", "glm_first_level"}
        ] + ["glm_first_level_py"]
    elif "glm_first_level" in ranked_ops and "glm" in ranked_ops:
        ranked_ops = [op for op in ranked_ops if op != "glm"]

    return ranked_ops


def get_operator_synonyms(operator: str) -> list[str]:
    """Get all synonym phrases for a given operator.

    Args:
        operator: Canonical operator name

    Returns:
        List of synonym phrases that map to this operator

    Examples:
        >>> get_operator_synonyms("skull_strip")
        ['skull strip', 'brain extraction', 'bet', ...]
    """
    synonym_map = load_synonym_map()
    # Reverse lookup
    synonyms = [phrase for phrase, op in synonym_map.items() if op == operator]
    return sorted(synonyms)


# Convenience function for testing
def clear_cache():
    """Clear the LRU cache for synonym map.

    Useful for testing when YAML files are modified.
    """
    load_synonym_map.cache_clear()


# ========================================
# Intent-level synonyms (runtime-agnostic)
# ========================================


@lru_cache(maxsize=1)
def _load_intent_synonym_map() -> dict[str, list[str]]:
    """Load intent → phrases mapping from configs/legacy/mappings/intent_synonyms.yaml."""
    path = get_mappings_dir() / "intent_synonyms.yaml"
    if not path.exists():
        return {}
    data = _load_yaml(path)
    # Normalize phrases to lowercase for matching
    return {
        intent_id: [p.lower() for p in phrases] for intent_id, phrases in data.items()
    }


__all__ = [
    "RE_WORD",
    "get_mappings_dir",
    "load_synonym_map",
    "match_intents",
    "get_operator_synonyms",
    "clear_cache",
]
