#!/usr/bin/env python3
"""Build MAPS_TO links for tasks that lack MEASURES."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

# let repo root imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.dataset_task_linker import (
    TaskMappingConfig,
    load_task_mapping_config,
    load_taxonomy_aliases,
    load_task_synonyms,
    normalize_task,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logger = logging.getLogger(__name__)

DEFAULT_TASK_MAPPING = Path("configs/legacy/task_mapping.yaml")
DEFAULT_SYNONYMS = Path("configs/legacy/mappings/task_synonyms.yaml")
DEFAULT_TAXONOMY = Path("configs/taxonomy/exports/task_families_master.yaml")
DEFAULT_MAPPING_RULES = Path("configs/mapping_rules.generated.yaml")

# Conservative overrides when common names in the KG don't have MEASURES but a
# closely-aligned canonical task does.
_CANONICAL_OVERRIDE_BY_NORMALIZED: dict[str, str] = {
    "episodic memory retrieval": "episodic recall",
}


@dataclass
class AliasMap:
    alias_to_canonical: dict[str, str]


@dataclass
class KeywordRule:
    canonical: str
    patterns: list[re.Pattern[str]]


def _compile_patterns(values: Iterable[str]) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for value in values:
        if not value:
            continue
        try:
            patterns.append(re.compile(value, re.IGNORECASE))
        except re.error:
            escaped = re.escape(value)
            patterns.append(re.compile(escaped, re.IGNORECASE))
    return patterns


def _load_family_matchers(path: Path, family_id: str) -> tuple[list[str], list[str]]:
    if not path.exists():
        return [], []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        entries = data.get("anchors") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    if not isinstance(entries, list):
        return [], []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("family_id") != family_id:
            continue
        matchers = entry.get("matchers") or {}
        keywords = matchers.get("keywords_any") or []
        regex = matchers.get("regex") or []
        if isinstance(keywords, list) and isinstance(regex, list):
            return [str(v) for v in keywords], [str(v) for v in regex]
    return [], []


def _build_alias_map() -> AliasMap:
    config = load_task_mapping_config(DEFAULT_TASK_MAPPING, enable_fuzzy=False)
    alias_to_canonical = load_task_synonyms(DEFAULT_SYNONYMS, config)
    taxonomy_aliases = load_taxonomy_aliases(DEFAULT_TAXONOMY, config)
    for alias, canonical in taxonomy_aliases.items():
        alias_to_canonical.setdefault(alias, canonical)
    return AliasMap(alias_to_canonical=alias_to_canonical)


def _build_keyword_rules() -> list[KeywordRule]:
    rules: list[KeywordRule] = []
    config = load_task_mapping_config(DEFAULT_TASK_MAPPING, enable_fuzzy=False)
    for rule in config.keyword_rules:
        canonical_norm = normalize_task(rule.canonical, config)
        if not canonical_norm:
            continue
        rules.append(KeywordRule(canonical=rule.canonical, patterns=rule.patterns))

    localizer_keywords, localizer_regex = _load_family_matchers(
        DEFAULT_MAPPING_RULES, "tf_localizers_baseline"
    )
    neurofeedback_keywords, neurofeedback_regex = _load_family_matchers(
        DEFAULT_MAPPING_RULES, "tf_neurofeedback"
    )
    retinotopy_keywords = ["retinotopy", "retinotopic", "retmap", "retinotopic mapping"]

    def _filter_localizer_terms(values: Iterable[str]) -> list[str]:
        keep: list[str] = []
        for value in values:
            lower = value.lower()
            if any(
                token in lower
                for token in (
                    "localizer",
                    "localiser",
                    "retinotop",
                    "tonotop",
                    "somatotop",
                    "checkerboard",
                )
            ):
                keep.append(value)
        return keep

    localizer_terms = _filter_localizer_terms([*localizer_keywords, *localizer_regex])
    if "localizer" not in " ".join(term.lower() for term in localizer_terms):
        localizer_terms.append(r"\blocali[sz]er(s)?\b")
    localizer_patterns = _compile_patterns(localizer_terms)
    neurofeedback_patterns = _compile_patterns(
        [*neurofeedback_keywords, *neurofeedback_regex, "neurofeedback"]
    )
    retinotopy_patterns = _compile_patterns(retinotopy_keywords)

    if localizer_patterns:
        rules.append(KeywordRule(canonical="functional localizer fMRI tasks", patterns=localizer_patterns))
    if retinotopy_patterns:
        rules.append(KeywordRule(canonical="retinotopic mapping task", patterns=retinotopy_patterns))
    if neurofeedback_patterns:
        # Only useful if the KG contains a neurofeedback Task with MEASURES; otherwise this rule is a no-op.
        rules.append(KeywordRule(canonical="Neurofeedback Paradigm", patterns=neurofeedback_patterns))
    return rules


def _normalize(text: str, config: TaskMappingConfig) -> str:
    return normalize_task(text, config)


def _iter_canonical_tasks(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (t:Task)-[r:MEASURES]->(:Concept)
    WITH t, count(r) AS measures_count
    RETURN DISTINCT t.id AS id, t.name AS name, measures_count
    """
    return [dict(row) for row in db._run(cypher)]


def _iter_needs_measures(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (t:Task)
    WHERE NOT EXISTS { (t)-[:MEASURES]->() }
      AND NOT EXISTS { (t)-[:MAPS_TO]->() }
    RETURN t.id AS id, t.name AS name, t.alias AS alias, t.aliases AS aliases
    """
    return [dict(row) for row in db._run(cypher)]


def _iter_needs_measures_dataset_targets(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (:Dataset)-[r:HAS_TASK|USES_TASK]->(t:Task)
    WHERE NOT EXISTS {
      MATCH (t)-[:MAPS_TO*0..1]->(:Task)-[:MEASURES]->(:Concept)
    }
    WITH t,
         collect(DISTINCT r.raw_task)[0..10] AS raw_tasks,
         collect(DISTINCT r.normalized_task)[0..10] AS normalized_tasks
    RETURN DISTINCT t.id AS id,
                    t.name AS name,
                    t.alias AS alias,
                    t.aliases AS aliases,
                    raw_tasks,
                    normalized_tasks
    """
    return [dict(row) for row in db._run(cypher)]


def _choose_canonical(
    normalized: str,
    lookup: dict[str, str],
    keyword_rules: list[KeywordRule],
) -> str | None:
    override = _CANONICAL_OVERRIDE_BY_NORMALIZED.get(normalized)
    if override:
        return override
    canonical = lookup.get(normalized)
    if canonical:
        canonical_lower = canonical.strip().lower()
        # Common placeholder tasks that do not directly exist as Concept-measuring tasks in
        # the KG, but have close canonical variants that do.
        if canonical_lower == "resting state":
            # Prefer explicit eyes-open/closed mentions when present, otherwise default
            # to eyes-open (and keep confidence conservative via prov_base_conf).
            if "closed" in normalized:
                return "rest eyes closed"
            if "open" in normalized:
                return "rest eyes open"
            return "rest eyes open"
        if canonical_lower == "reward processing":
            return "monetary incentive delay task"
        return canonical
    for rule in keyword_rules:
        for pattern in rule.patterns:
            if pattern.search(normalized):
                return rule.canonical
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Link needs-measures tasks to canonical tasks")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write MAPS_TO relationships",
    )
    parser.add_argument(
        "--scope",
        choices=("dataset", "all"),
        default="dataset",
        help="Which tasks to consider for MAPS_TO (default: dataset targets only)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Confidence floor for alias matches (unused placeholder)",
    )
    args = parser.parse_args()

    config = load_task_mapping_config(DEFAULT_TASK_MAPPING, enable_fuzzy=False)
    alias_map = _build_alias_map()
    keyword_rules = _build_keyword_rules()

    db = require_neo4j_db(preload_cache=False)
    try:
        canonical_rows = _iter_canonical_tasks(db)
        canonical_lookup: dict[str, list[tuple[int, str]]] = {}
        name_to_id: dict[str, str] = {}
        for row in canonical_rows:
            name = row.get("name") or ""
            if not name:
                continue
            normalized = normalize_task(name, config)
            if normalized:
                existing = canonical_lookup.setdefault(normalized, [])
                candidate = (int(row.get("measures_count") or 0), str(row["id"]))
                if candidate not in existing:
                    existing.append(candidate)
            name_to_id[name.lower()] = row["id"]

        if args.scope == "dataset":
            needs_measures = _iter_needs_measures_dataset_targets(db)
        else:
            needs_measures = _iter_needs_measures(db)
        logger.info("Found %s needs_measures tasks", len(needs_measures))
        created = 0

        for row in needs_measures:
            candidates = [row.get("name") or ""]
            aliases = []
            for key in (row.get("alias") or "", row.get("aliases")):
                if isinstance(key, list):
                    aliases.extend(key)
                elif key:
                    aliases.append(key)
            raw_tasks = row.get("raw_tasks") or []
            normalized_tasks = row.get("normalized_tasks") or []
            if isinstance(raw_tasks, list):
                aliases.extend(str(v) for v in raw_tasks if v)
            if isinstance(normalized_tasks, list):
                aliases.extend(str(v) for v in normalized_tasks if v)
            candidates.extend(aliases)
            for cand in candidates:
                normalized = normalize_task(cand, config)
                if not normalized:
                    continue
                canonical_name = _choose_canonical(normalized, alias_map.alias_to_canonical, keyword_rules)
                candidate_ids = canonical_lookup.get(normalized, [])
                if canonical_name:
                    canonical_norm = normalize_task(canonical_name, config)
                    candidate_ids = canonical_lookup.get(canonical_norm, candidate_ids)
                if not candidate_ids:
                    continue
                canonical_id = max(candidate_ids, key=lambda item: (item[0], item[1]))[1]
                if args.dry_run:
                    logger.info("[DRY RUN] MAPS_TO %s -> %s (%s)", row["id"], canonical_id, normalized)
                else:
                    cypher = """
                    MATCH (a:Task {id:$src})
                    MATCH (b:Task {id:$dst})
                    MERGE (a)-[r:MAPS_TO]->(b)
                    SET r += {
                      prov_source: 'task_canonicalizer',
                      prov_method: 'alias_match',
                      prov_base_conf: 0.55,
                      normalized_name: $normalized,
                      computed_at: datetime()
                    }
                    RETURN r
                    """
                    db._run(cypher, {"src": row["id"], "dst": canonical_id, "normalized": normalized}).consume()
                created += 1
                break
        logger.info("Created %s MAPS_TO links", created)
    finally:
        db.close()


if __name__ == "__main__":
    main()
