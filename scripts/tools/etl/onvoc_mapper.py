#!/usr/bin/env python3
"""Rule-based Task → ONVOC mapper driven entirely by configs.

This utility exposes three subcommands:

* slugify – populate Task.slug from bids_task/name using the project rules.
* propose – score unmapped Tasks against ONVOC anchors and emit proposals + review deck.
* apply – validate & materialize MAPS_TO edges from an accepted proposals CSV.

All weights / thresholds / toggles live in configs/mapping_rules.yaml and
configs/mapping_settings.yaml. The script merely orchestrates the flow.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import typer
import yaml
from neo4j import Driver, GraphDatabase


app = typer.Typer(help="Deterministic Task → ONVOC mapper")


BUILTIN_DEFAULTS: Dict[str, Any] = {
    "accept": {"min_score": 0.85, "min_margin": 0.10, "allow_multi": False},
    "weights": {
        "id_exact": 1.0,
        "slug_exact": 0.9,
        "bids_exact": 0.9,
        "hed_all": 0.45,
        "hed_any": 0.35,
        "keywords_all": 0.35,
        "keywords_any": 0.25,
        "regex": 0.25,
    },
}

STUDY_DESIGN_ONVOC = "ONVOC_0000007"
REQUIRES_MULTI_CHANNEL = {"slug_exact", "id_exact", "bids_exact"}
ONVOC_NODE_LABELS = ["ONVOC", "OnvocClass", "Concept", "OntologyConcept"]


def _onvoc_node_predicate(var_name: str) -> str:
    labels = ", ".join(f"'{label}'" for label in ONVOC_NODE_LABELS)
    return (
        f"any(lbl IN labels({var_name}) WHERE lbl IN [{labels}]) "
        f"AND (coalesce({var_name}.scheme, '') = 'ONVOC' OR {var_name}.id STARTS WITH 'ONVOC_')"
    )




@dataclass
class AcceptRules:
    min_score: float
    min_margin: float
    allow_multi: bool


@dataclass
class NormalizationSettings:
    ascii_fold: bool = True
    min_token_len: int = 2
    stopwords: Set[str] = field(default_factory=set)
    include_contrast_names: bool = True
    include_task_description: bool = True
    include_hed: bool = True


@dataclass
class ProposerSettings:
    only_unmapped: bool = True
    limit: Optional[int] = None
    sources: Optional[List[str]] = None


@dataclass
class ReviewSettings:
    borderline_delta: float = 0.10


@dataclass
class HierarchicalMappingSettings:
    mode: str = "l2_only"
    l2_threshold: float = 0.88
    l3_threshold: float = 0.90
    require_parent_consistency: bool = True
    max_l2_candidates: int = 25
    max_l3_candidates: int = 20


@dataclass
class MappingSettings:
    scoring_defaults: Dict[str, Any]
    normalization: NormalizationSettings
    proposer: ProposerSettings
    review: ReviewSettings
    hierarchical: HierarchicalMappingSettings


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        elif value is not None:
            result[key] = value
    return result


def load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _merge_anchor_lists(
    generated: Optional[Iterable[Dict[str, Any]]],
    manual: Optional[Iterable[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}

    def _merge_lists(existing: Optional[Iterable[Any]], incoming: Optional[Iterable[Any]]) -> List[Any]:
        out: List[Any] = []
        seen = set()
        for source in (existing or []), (incoming or []):
            for item in source:
                key = str(item)
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
        return out

    def _combine_anchors(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        combined = dict(base)

        if "seed_tasks" in override:
            combined["seed_tasks"] = _merge_lists(base.get("seed_tasks"), override.get("seed_tasks"))

        if "matchers" in override:
            merged_matchers = dict(base.get("matchers", {}))
            for key, values in override["matchers"].items():
                merged_matchers[key] = _merge_lists(merged_matchers.get(key), values)
            combined["matchers"] = merged_matchers

        for key, value in override.items():
            if key in {"seed_tasks", "matchers"}:
                continue
            combined[key] = value
        return combined

    def _ingest(items: Optional[Iterable[Dict[str, Any]]], replace: bool) -> None:
        if not items:
            return
        for anchor in items:
            if not isinstance(anchor, dict):
                continue
            uri = anchor.get("onvoc_uri")
            if not uri:
                continue
            if uri in index:
                if replace:
                    merged[index[uri]] = _combine_anchors(merged[index[uri]], anchor)
                continue
            index[uri] = len(merged)
            merged.append(anchor)

    _ingest(generated, replace=False)
    _ingest(manual, replace=True)
    return merged


def normalize_text(value: str, ascii_fold: bool) -> str:
    normalized = value.strip()
    if ascii_fold:
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def slugify_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = normalize_text(str(value), ascii_fold=True)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if slug.endswith("-task"):
        slug = slug[:-5] or slug
    elif slug.endswith("-test"):
        slug = slug[:-5] or slug
    return slug or None


def tokenize(text: str, min_len: int, stopwords: Set[str]) -> Set[str]:
    tokens = set()
    for chunk in re.split(r"[^a-z0-9]+", text):
        token = chunk.strip()
        if len(token) < min_len or token in stopwords:
            continue
        tokens.add(token)
    return tokens


def chunked(rows: Sequence[Dict[str, Any]], size: int = 500) -> Iterable[List[Dict[str, Any]]]:
    for idx in range(0, len(rows), size):
        yield rows[idx : idx + size]


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Anchor:
    onvoc_uri: str
    label: Optional[str]
    family_id: Optional[str]
    level: Optional[int]
    parent_l2: Optional[str]
    seed_ids: Set[str]
    slug_hits: Set[str]
    bids_hits: Set[str]
    hed_all: Set[str]
    hed_any: Set[str]
    keywords_any: List[str]
    keywords_all: List[str]
    regex_patterns: List[re.Pattern]
    exclude_keywords: List[str]
    exclude_regex: List[re.Pattern]
    weights: Dict[str, float]
    accept: AcceptRules

    def score(self, task: "TaskRecord") -> Optional["ScoreResult"]:
        evidence: List[Dict[str, Any]] = []
        matched_features: List[str] = []
        total = 0.0

        def register(channel: str, detail: Any) -> None:
            nonlocal total
            weight = self.weights.get(channel, 0.0)
            if weight <= 0:
                return
            total += weight
            evidence.append({"channel": channel, "detail": detail})
            matched_features.append(f"{channel}:{detail}")

        if self.seed_ids and task.id in self.seed_ids:
            register("id_exact", task.id)

        if task.slug and task.slug in self.slug_hits:
            register("slug_exact", task.slug)

        if task.bids_slug and task.bids_slug in self.bids_hits:
            register("bids_exact", task.bids_slug)

        task_hed = task.hed_tokens
        if self.hed_all and self.hed_all.issubset(task_hed):
            register("hed_all", sorted(self.hed_all))
        if self.hed_any and task_hed.intersection(self.hed_any):
            register("hed_any", sorted(task_hed.intersection(self.hed_any)))

        if self.keywords_all and task.contains_keywords(self.keywords_all):
            register("keywords_all", self.keywords_all)
        if self.keywords_any and task.contains_any_keyword(self.keywords_any):
            hits = [kw for kw in self.keywords_any if task.has_keyword(kw)]
            register("keywords_any", hits)

        if self.regex_patterns:
            regex_hits = []
            for pattern in self.regex_patterns:
                if pattern.search(task.raw_text):
                    regex_hits.append(pattern.pattern)
            if regex_hits:
                register("regex", regex_hits)

        if total <= 0:
            return None

        for bad_kw in self.exclude_keywords:
            if task.has_keyword(bad_kw):
                return None
        for bad_regex in self.exclude_regex:
            if bad_regex.search(task.raw_text):
                return None

        return ScoreResult(anchor=self, score=total, matched=matched_features, evidence=evidence)


@dataclass
class TaskRecord:
    id: str
    name: Optional[str]
    slug: Optional[str]
    bids_slug: Optional[str]
    source: Optional[str]
    description: Optional[str]
    definition: Optional[str]
    alias: Optional[str]
    aliases: List[str]
    metadata: Dict[str, Any]
    contrast_names: List[Optional[str]]
    hed_terms: List[str]
    normalization: NormalizationSettings
    raw_text: str = ""
    tokens: Set[str] = field(default_factory=set)
    hed_tokens: Set[str] = field(default_factory=set)

    def prepare(self) -> None:
        parts: List[str] = []

        def _extend(value: Any) -> None:
            if not value:
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    _extend(item)
            else:
                parts.append(str(value))

        _extend(self.name)
        _extend(self.alias)
        _extend(self.aliases)
        if self.normalization.include_task_description:
            _extend(self.description)
            _extend(self.definition)
        if self.normalization.include_contrast_names:
            _extend([name for name in self.contrast_names if name])
        if isinstance(self.metadata, dict):
            for key, value in self.metadata.items():
                if isinstance(value, (str, int, float)):
                    parts.append(f"{key}:{value}")
        if self.normalization.include_hed:
            _extend(self.hed_terms)

        joined = " ".join(parts)
        normalized = normalize_text(joined, self.normalization.ascii_fold)
        self.raw_text = normalized
        self.tokens = tokenize(
            normalized,
            self.normalization.min_token_len,
            self.normalization.stopwords,
        )
        hed_tokens: Set[str] = set()
        for term in self.hed_terms:
            if not term:
                continue
            normalized_term = normalize_text(str(term), True)
            if normalized_term:
                hed_tokens.add(normalized_term)
        self.hed_tokens = hed_tokens

    def has_keyword(self, keyword: str) -> bool:
        if not keyword:
            return False
        return f" {keyword} " in f" {self.raw_text} "

    def contains_keywords(self, keywords: List[str]) -> bool:
        return all(self.has_keyword(keyword) for keyword in keywords)

    def contains_any_keyword(self, keywords: List[str]) -> bool:
        return any(self.has_keyword(keyword) for keyword in keywords)


@dataclass
class ScoreResult:
    anchor: Anchor
    score: float
    matched: List[str]
    evidence: List[Dict[str, Any]]


def _passes_signal_policy(task: TaskRecord, result: ScoreResult) -> bool:
    """Require ≥2 matched channels unless a CA slug/id seed fired."""

    if len(result.matched) >= 2:
        return True

    def _channel(feature: str) -> str:
        return feature.split(":", 1)[0]

    seed_hit = any(_channel(feature) in REQUIRES_MULTI_CHANNEL for feature in result.matched)
    if seed_hit and (task.source or "").lower() == "cognitive_atlas":
        return True
    return False


def load_settings(
    rules_path: Path,
    settings_path: Optional[Path],
    generated_rules_path: Optional[Path] = None,
) -> Tuple[Dict[str, Any], MappingSettings]:
    rules_cfg = load_yaml_file(rules_path)
    if generated_rules_path:
        try:
            generated_cfg = load_yaml_file(generated_rules_path)
        except FileNotFoundError:
            generated_cfg = {}
        merged_anchors = _merge_anchor_lists(generated_cfg.get("anchors"), rules_cfg.get("anchors"))
        if merged_anchors:
            rules_cfg["anchors"] = merged_anchors
    settings_cfg = load_yaml_file(settings_path) if settings_path else {}

    scoring_defaults = _deep_merge(BUILTIN_DEFAULTS, settings_cfg.get("scoring_defaults", {}))
    scoring_defaults = _deep_merge(scoring_defaults, rules_cfg.get("defaults", {}))

    norm_cfg = settings_cfg.get("normalization", {})
    normalization = NormalizationSettings(
        ascii_fold=bool(norm_cfg.get("ascii_fold", True)),
        min_token_len=int(norm_cfg.get("min_token_len", 2)),
        stopwords={normalize_text(word, True) for word in norm_cfg.get("stopwords", [])},
        include_contrast_names=bool(norm_cfg.get("include_contrast_names", True)),
        include_task_description=bool(norm_cfg.get("include_task_description", True)),
        include_hed=bool(norm_cfg.get("include_hed", True)),
    )

    proposer_cfg = settings_cfg.get("proposer", {})
    proposer = ProposerSettings(
        only_unmapped=bool(proposer_cfg.get("only_unmapped", True)),
        limit=proposer_cfg.get("limit"),
        sources=proposer_cfg.get("sources"),
    )

    review_cfg = settings_cfg.get("review", {})
    review = ReviewSettings(
        borderline_delta=float(review_cfg.get("borderline_delta", 0.10)),
    )

    hierarchy_cfg = settings_cfg.get("hierarchical_mapping", {})
    hierarchical = HierarchicalMappingSettings(
        mode=str(hierarchy_cfg.get("mode", "l2_only")),
        l2_threshold=float(hierarchy_cfg.get("l2_threshold", 0.88)),
        l3_threshold=float(hierarchy_cfg.get("l3_threshold", 0.90)),
        require_parent_consistency=bool(hierarchy_cfg.get("require_parent_consistency", True)),
        max_l2_candidates=int(hierarchy_cfg.get("max_l2_candidates", 25)),
        max_l3_candidates=int(hierarchy_cfg.get("max_l3_candidates", 20)),
    )

    settings = MappingSettings(
        scoring_defaults=scoring_defaults,
        normalization=normalization,
        proposer=proposer,
        review=review,
        hierarchical=hierarchical,
    )
    return rules_cfg, settings


def build_anchor(cfg: Dict[str, Any], defaults: Dict[str, Any]) -> Anchor:
    accept_cfg = _deep_merge(defaults.get("accept", {}), cfg.get("accept", {}))
    weights = _deep_merge(defaults.get("weights", {}), cfg.get("weights", {}))

    seed_ids = {
        str(task.get("id")).strip()
        for task in cfg.get("seed_tasks", [])
        if task.get("id")
    }
    seed_slugs = {
        slugify_value(task.get("slug"))
        for task in cfg.get("seed_tasks", [])
        if slugify_value(task.get("slug"))
    }
    seed_bids = {
        slugify_value(task.get("bids"))
        for task in cfg.get("seed_tasks", [])
        if slugify_value(task.get("bids"))
    }

    matchers = cfg.get("matchers", {})
    matcher_slugs = {slugify_value(val) for val in matchers.get("slugs", []) if slugify_value(val)}
    matcher_bids = {slugify_value(val) for val in matchers.get("bids", []) if slugify_value(val)}
    hed_all = {normalize_text(val, True) for val in matchers.get("hed_all", []) if val}
    hed_any = {normalize_text(val, True) for val in matchers.get("hed_any", []) if val}

    def _normalize_keywords(items: Iterable[str]) -> List[str]:
        cleaned = []
        for item in items or []:
            norm = normalize_text(str(item), True)
            if norm:
                cleaned.append(norm)
        return cleaned

    keywords_any = _normalize_keywords(matchers.get("keywords_any", []))
    keywords_all = _normalize_keywords(matchers.get("keywords_all", []))

    regex_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in matchers.get("regex", [])]

    exclude_cfg = cfg.get("exclude", {})
    exclude_keywords = _normalize_keywords(exclude_cfg.get("keywords", []))
    exclude_regex = [re.compile(pattern, re.IGNORECASE) for pattern in exclude_cfg.get("regex", [])]

    slug_hits = {slug for slug in seed_slugs.union(matcher_slugs) if slug}
    bids_hits = {bid for bid in seed_bids.union(matcher_bids) if bid}

    accept = AcceptRules(
        min_score=float(accept_cfg.get("min_score", BUILTIN_DEFAULTS["accept"]["min_score"])),
        min_margin=float(accept_cfg.get("min_margin", BUILTIN_DEFAULTS["accept"]["min_margin"])),
        allow_multi=bool(accept_cfg.get("allow_multi", BUILTIN_DEFAULTS["accept"]["allow_multi"])),
    )

    return Anchor(
        onvoc_uri=str(cfg.get("onvoc_uri")),
        label=cfg.get("label"),
        family_id=cfg.get("family_id"),
        level=cfg.get("level"),
        parent_l2=None,
        seed_ids=seed_ids,
        slug_hits=slug_hits,
        bids_hits=bids_hits,
        hed_all=hed_all,
        hed_any=hed_any,
        keywords_any=keywords_any,
        keywords_all=keywords_all,
        regex_patterns=regex_patterns,
        exclude_keywords=exclude_keywords,
        exclude_regex=exclude_regex,
        weights=weights,
        accept=accept,
    )


def load_anchors(rules_cfg: Dict[str, Any], settings: MappingSettings) -> List[Anchor]:
    anchors_cfg = rules_cfg.get("anchors", [])
    anchors = [build_anchor(cfg, settings.scoring_defaults) for cfg in anchors_cfg if cfg.get("onvoc_uri")]
    return anchors


def build_driver(uri: Optional[str], user: Optional[str], password: Optional[str]) -> Driver:
    uri_val = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user_val = user or os.getenv("NEO4J_USER", "neo4j")
    password_val = password or os.getenv("NEO4J_PASSWORD", "neo4j")
    return GraphDatabase.driver(uri_val, auth=(user_val, password_val))


def fetch_tasks(
    driver: Driver,
    normalization: NormalizationSettings,
    only_unmapped: bool = True,
    limit: Optional[int] = None,
    sources: Optional[List[str]] = None,
    database: Optional[str] = None,
) -> List[TaskRecord]:
    clauses = ["MATCH (t:Task)"]
    where_parts = []
    if sources:
        where_parts.append("t.source IN $sources")
    if only_unmapped:
        where_parts.append(
            "NOT EXISTS { MATCH (t)-[:MAPS_TO]->(o) WHERE "
            + _onvoc_node_predicate("o")
            + " }"
        )
    if where_parts:
        clauses.append("WHERE " + " AND ".join(where_parts))
    clauses.append(
        """
    OPTIONAL MATCH (t)-[:HAS_CONTRAST]->(c:Contrast)
    OPTIONAL MATCH (t)-[:HASINDICATOR]->(ti:TaskIndicator)
    WITH t,
         collect(DISTINCT c.name) AS contrast_names,
         collect(DISTINCT ti.type) AS indicator_types
    RETURN t.id AS id,
           t.name AS name,
           t.slug AS slug,
           coalesce(t.bids_task, "") AS bids_task,
           t.source AS source,
           t.description AS description,
           t.definition AS definition,
           t.alias AS alias,
           t.aliases AS aliases,
           t.metadata AS metadata,
           contrast_names,
           indicator_types
    ORDER BY t.id
    {limit_clause}
    """
        .format(limit_clause=f"LIMIT {int(limit)}" if limit else "")
    )
    query = "\n".join(clauses)
    with driver.session(database=database) as session:
        params: Dict[str, Any] = {}
        if sources:
            params["sources"] = sources
        records = session.run(query, **params)
        tasks: List[TaskRecord] = []
        for record in records:
            aliases = record.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            metadata = record.get("metadata") or {}
            hed_terms = [term for term in record.get("indicator_types", []) if term]
            task = TaskRecord(
                id=record.get("id"),
                name=record.get("name"),
                slug=record.get("slug") or slugify_value(record.get("bids_task") or record.get("name")),
                bids_slug=slugify_value(record.get("bids_task")),
                source=record.get("source"),
                description=record.get("description"),
                definition=record.get("definition"),
                alias=record.get("alias"),
                aliases=aliases,
                metadata=metadata if isinstance(metadata, dict) else {},
                contrast_names=record.get("contrast_names", []),
                hed_terms=hed_terms,
                normalization=normalization,
            )
            task.prepare()
            tasks.append(task)
        return tasks



def fetch_onvoc_level2(
    driver: Driver,
    limit: Optional[int] = None,
    database: str = "neo4j",
) -> List[Dict[str, Any]]:
    """Return ONVOC level-2 concepts (id, label, definition)."""

    limit_clause = "LIMIT $limit" if limit else ""
    query = f"""
    MATCH (c)-[:CLASSIFIED_UNDER]->(root)
    WHERE {_onvoc_node_predicate("c")}
      AND {_onvoc_node_predicate("root")}
      AND root.is_top_concept = TRUE
    RETURN DISTINCT c.id AS onvoc_id,
           coalesce(c.label, c.id) AS label,
           c.definition AS definition
    ORDER BY label
    {limit_clause}
    """
    params: Dict[str, Any] = {}
    if limit:
        params["limit"] = int(limit)
    with driver.session(database=database) as session:
        rows = session.run(query, **params)
        return [dict(row) for row in rows]



def fetch_onvoc_children(
    driver: Driver,
    parent_onvoc_id: str,
    limit: Optional[int] = None,
    database: str = "neo4j",
) -> List[Dict[str, Any]]:
    """Return ONVOC level-3 children constrained by the provided L2 parent."""

    limit_clause = "LIMIT $limit" if limit else ""
    query = f"""
    MATCH (parent {{id:$parent_id}})
    WHERE {_onvoc_node_predicate("parent")}
    MATCH (child)-[:CLASSIFIED_UNDER*1..]->(parent)
    WHERE child.id <> parent.id
      AND {_onvoc_node_predicate("child")}
    RETURN DISTINCT child.id AS onvoc_id,
           coalesce(child.label, child.id) AS label,
           child.definition AS definition,
           parent.id AS parent_l2
    ORDER BY label
    {limit_clause}
    """
    params: Dict[str, Any] = {"parent_id": parent_onvoc_id}
    if limit:
        params["limit"] = int(limit)
    with driver.session(database=database) as session:
        rows = session.run(query, **params)
        return [dict(row) for row in rows]


def fetch_onvoc_hierarchy_map(
    driver: Driver, database: str = "neo4j"
) -> Dict[str, Dict[str, Any]]:
    """Return a dict of ONVOC id → level/parent metadata."""

    query = """
    MATCH (node)
    WHERE """
    query += _onvoc_node_predicate("node")
    query += """
    OPTIONAL MATCH path = (node)-[:CLASSIFIED_UNDER*0..]->(l2)-[:CLASSIFIED_UNDER]->(root)
    WHERE """
    query += _onvoc_node_predicate("l2")
    query += """
      AND """
    query += _onvoc_node_predicate("root")
    query += """
      AND root.is_top_concept = TRUE
    WITH node, l2, length(path) AS hops
    ORDER BY node.id, hops
    WITH node, collect({l2:l2, hops:hops}) AS candidates
    WITH node, [cand IN candidates WHERE cand.l2 IS NOT NULL] AS filtered
    WITH node, CASE WHEN size(filtered) = 0 THEN NULL ELSE filtered[0].l2 END AS parent_l2
    RETURN node.id AS id,
           coalesce(node.label, node.id) AS label,
           CASE
             WHEN node.is_top_concept = TRUE THEN 1
             WHEN parent_l2 IS NULL THEN 2
             WHEN node.id = parent_l2.id THEN 2
             ELSE 3
           END AS level,
           CASE WHEN parent_l2 IS NULL THEN NULL ELSE parent_l2.id END AS parent_l2_id,
           CASE WHEN parent_l2 IS NULL THEN NULL ELSE coalesce(parent_l2.label, parent_l2.id) END AS parent_l2_label
    """
    meta: Dict[str, Dict[str, Any]] = {}
    with driver.session(database=database) as session:
        for row in session.run(query):
            meta[row["id"]] = {
                "label": row["label"],
                "level": row["level"],
                "parent_l2": row["parent_l2_id"],
                "parent_l2_label": row["parent_l2_label"],
            }
    return meta


def annotate_anchor_hierarchy(anchors: List[Anchor], hierarchy: Dict[str, Dict[str, Any]]) -> None:
    for anchor in anchors:
        info = hierarchy.get(anchor.onvoc_uri)
        if not info:
            continue
        if anchor.level is None:
            anchor.level = info.get("level")
        anchor.parent_l2 = info.get("parent_l2")


def score_tasks(
    tasks: List[TaskRecord],
    anchors: List[Anchor],
    review_settings: ReviewSettings,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    proposals: List[Dict[str, Any]] = []
    borderline: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for task in tasks:
        scored: List[ScoreResult] = []
        for anchor in anchors:
            result = anchor.score(task)
            if result:
                scored.append(result)
        if not scored:
            continue

        scored.sort(key=lambda res: res.score, reverse=True)
        best = scored[0]
        runner = scored[1] if len(scored) > 1 else None
        if runner and best.anchor.onvoc_uri == STUDY_DESIGN_ONVOC and runner.anchor.onvoc_uri != STUDY_DESIGN_ONVOC and abs(best.score - runner.score) <= 1e-6:
            best, runner = runner, best
        runner_up_score = runner.score if runner else 0.0
        margin = best.score - runner_up_score
        accept = best.anchor.accept
        meets_score = best.score >= accept.min_score
        meets_margin = accept.allow_multi or margin >= accept.min_margin
        signals_ok = _passes_signal_policy(task, best)
        row = {
            "task_id": task.id,
            "task_name": task.name,
            "task_slug": task.slug,
            "task_source": task.source,
            "task_bids": task.bids_slug,
            "onvoc_uri": best.anchor.onvoc_uri,
            "onvoc_label": best.anchor.label,
            "score": round(best.score, 4),
            "margin": round(margin, 4),
            "method": "slug_rule_v1",
            "confidence": round(best.score, 4),
            "matched_features": ";".join(best.matched),
            "evidence_json": json.dumps(best.evidence, ensure_ascii=False),
            "timestamp": now_iso,
        }
        if meets_score and meets_margin and signals_ok:
            row["decision"] = "accept"
            proposals.append(row)
        else:
            row["decision"] = "review"
            threshold = accept.min_score - review_settings.borderline_delta
            if best.score >= threshold or not signals_ok:
                borderline.append(
                    {
                        **row,
                        "runner_up": scored[1].anchor.onvoc_uri if len(scored) > 1 else None,
                        "runner_up_score": runner_up_score,
                        "reason": _review_reason(meets_score, meets_margin, signals_ok, accept),
                    }
                )

    return proposals, borderline


def _review_reason(meets_score: bool, meets_margin: bool, signals_ok: bool, accept: AcceptRules) -> str:
    reasons = []
    if not meets_score:
        reasons.append(f"score<{accept.min_score}")
    if not meets_margin:
        reasons.append(f"margin<{accept.min_margin}")
    if not signals_ok:
        reasons.append("signals<2")
    return ",".join(reasons)


def write_proposals_csv(path: Path, proposals: List[Dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    fieldnames = [
        "task_id",
        "task_name",
        "task_slug",
        "task_bids",
        "task_source",
        "onvoc_uri",
        "onvoc_label",
        "score",
        "margin",
        "method",
        "confidence",
        "decision",
        "matched_features",
        "evidence_json",
        "timestamp",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in proposals:
            writer.writerow(row)


def write_review_md(path: Path, borderline: List[Dict[str, Any]], review_settings: ReviewSettings) -> None:
    if not borderline:
        return
    ensure_parent_dir(path)
    lines = [
        "# Task → ONVOC borderline review",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Borderline delta: {review_settings.borderline_delta}",
        "",
        "| task_id | task_name | best_onvoc | score | margin | runner_up | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in borderline:
        lines.append(
            "| {task_id} | {task_name} | {onvoc_uri} | {score:.3f} | {margin:.3f} | {runner_up} | {reason} |".format(
                task_id=row["task_id"],
                task_name=row.get("task_name") or "",
                onvoc_uri=row["onvoc_uri"],
                score=row["score"],
                margin=row["margin"],
                runner_up=row.get("runner_up") or "",
                reason=row.get("reason") or "",
            )
        )
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def read_proposals_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def apply_mappings(
    driver: Driver,
    proposals: List[Dict[str, Any]],
    loader_version: str,
    source: str = "onvoc_rule",
    database: Optional[str] = None,
) -> int:
    accepted = [row for row in proposals if (row.get("decision") or "").lower() in {"accept", "accepted", "apply", "true", "1"}]
    if not accepted:
        return 0

    database_name = _resolve_database(database)
    hierarchy = fetch_onvoc_hierarchy_map(driver, database_name or "neo4j")

    rows = []
    for row in accepted:
        try:
            evidence = json.loads(row.get("evidence_json") or "[]")
        except json.JSONDecodeError:
            evidence = []
        meta = hierarchy.get(row.get("onvoc_uri"), {})
        onvoc_level = meta.get("level", 2)
        parent_l2 = meta.get("parent_l2") if onvoc_level == 3 else None
        rows.append(
            {
                "task_id": row["task_id"],
                "onvoc_uri": row["onvoc_uri"],
                "score": float(row.get("score", 0.0)),
                "margin": float(row.get("margin", 0.0)),
                "method": row.get("method") or "slug_rule_v1",
                "matched": row.get("matched_features"),
                "evidence_json": json.dumps(evidence, ensure_ascii=False),
                "loader_version": loader_version,
                "source": source,
                "onvoc_level": onvoc_level,
                "parent_l2": parent_l2,
                "parent_score": min(float(row.get("score", 0.0)) + 0.02, 1.0) if parent_l2 else None,
                "needs_parent_edge": bool(parent_l2),
            }
        )

    query = """
    UNWIND $rows AS row
    MATCH (t:Task {id: row.task_id})
    MATCH (o {id: row.onvoc_uri})
    WHERE """
    query += _onvoc_node_predicate("o")
    query += """
    MERGE (t)-[r:MAPS_TO]->(o)
    SET r.source = row.source,
        r.method = row.method,
        r.vocab = "ONVOC",
        r.confidence = row.score,
        r.margin = row.margin,
        r.loader_version = row.loader_version,
        r.matched_features = row.matched,
        r.evidence_json = row.evidence_json,
        r.updated_at = datetime(),
        r.onvoc_level = coalesce(row.onvoc_level, 2),
        r.parent_l2 = CASE WHEN coalesce(row.onvoc_level, 2) = 3 THEN row.parent_l2 ELSE NULL END
    WITH row, t
    CALL {
        WITH row, t
        MATCH (parent {id: row.parent_l2})
        WHERE """
    query += _onvoc_node_predicate("parent")
    query += """
          AND row.needs_parent_edge
        MERGE (t)-[rp:MAPS_TO]->(parent)
        SET rp.source = row.source,
            rp.method = row.method,
            rp.vocab = "ONVOC",
            rp.confidence = coalesce(row.parent_score, row.score),
            rp.margin = row.margin,
            rp.loader_version = row.loader_version,
            rp.matched_features = row.matched,
            rp.evidence_json = row.evidence_json,
            rp.updated_at = datetime(),
            rp.onvoc_level = 2,
            rp.parent_l2 = row.parent_l2
        RETURN 0 AS _
    }
    RETURN count(*) AS applied
    """
    with driver.session(database=database_name) as session:
        session.run(query, rows=rows)
    return len(rows)


def _update_slugs(driver: Driver, database: Optional[str]) -> int:
    query = """
    MATCH (t:Task)
    RETURN t.id AS id, t.slug AS slug, coalesce(t.bids_task, "") AS bids_task, t.name AS name
    """
    updated: List[Dict[str, str]] = []
    with driver.session(database=database) as session:
        records = session.run(query)
        for record in records:
            basis = record.get("bids_task") or record.get("name")
            new_slug = slugify_value(basis)
            if not new_slug:
                continue
            if new_slug == record.get("slug"):
                continue
            updated.append({"id": record.get("id"), "slug": new_slug})
        if not updated:
            return 0
        for chunk in chunked(updated, 500):
            session.run(
                """
                UNWIND $rows AS row
                MATCH (t:Task {id: row.id})
                SET t.slug = row.slug
                """,
                rows=chunk,
            )
        session.run("CREATE INDEX task_slug IF NOT EXISTS FOR (t:Task) ON (t.slug)")
    return len(updated)


def _resolve_database(database: Optional[str]) -> Optional[str]:
    return database or os.getenv("NEO4J_DATABASE")


@app.command()
def slugify(
    uri: Optional[str] = typer.Option(None, help="Neo4j URI (defaults to $NEO4J_URI)"),
    user: Optional[str] = typer.Option(None, help="Neo4j user (defaults to $NEO4J_USER)"),
    password: Optional[str] = typer.Option(None, help="Neo4j password (defaults to $NEO4J_PASSWORD)"),
    database: Optional[str] = typer.Option(None, help="Neo4j database"),
) -> None:
    """Populate Task.slug using bids_task/name."""

    driver = build_driver(uri, user, password)
    try:
        count = _update_slugs(driver, _resolve_database(database))
    finally:
        driver.close()
    typer.echo(f"Updated {count} Task.slug values")


@app.command()
def propose(
    config: Path = typer.Option(..., exists=True, readable=True, help="Path to mapping_rules.yaml"),
    settings: Optional[Path] = typer.Option(None, exists=True, readable=True, help="Optional mapping_settings.yaml"),
    generated_rules: Optional[Path] = typer.Option(
        None,
        exists=False,
        readable=True,
        help="Optional generated rules file merged before manual anchors",
    ),
    uri: Optional[str] = typer.Option(None, help="Neo4j URI"),
    user: Optional[str] = typer.Option(None, help="Neo4j user"),
    password: Optional[str] = typer.Option(None, help="Neo4j password"),
    database: Optional[str] = typer.Option(None, help="Neo4j database"),
    out: Path = typer.Option(Path("outputs/mapping_proposals.csv"), help="CSV destination"),
    review: Path = typer.Option(Path("outputs/mapping_review.md"), help="Borderline review markdown"),
    sources: Optional[List[str]] = typer.Option(None, help="Restrict to Task.source values"),
) -> None:
    """Score Tasks vs ONVOC anchors and emit proposals + review deck."""

    rules_cfg, map_settings = load_settings(config, settings, generated_rules)
    anchors = load_anchors(rules_cfg, map_settings)
    driver = build_driver(uri, user, password)
    try:
        effective_sources = sources or map_settings.proposer.sources
        tasks = fetch_tasks(
            driver,
            normalization=map_settings.normalization,
            only_unmapped=map_settings.proposer.only_unmapped,
            limit=map_settings.proposer.limit,
            sources=effective_sources,
            database=_resolve_database(database),
        )
        proposals, borderline = score_tasks(tasks, anchors, map_settings.review)
    finally:
        driver.close()

    write_proposals_csv(out, proposals)
    write_review_md(review, borderline, map_settings.review)
    typer.echo(f"Wrote {len(proposals)} accepted proposals to {out}")
    if borderline:
        typer.echo(f"Borderline entries: {len(borderline)} (see {review})")


@app.command()
def apply(
    config: Path = typer.Option(..., exists=True, readable=True, help="Path to mapping_rules.yaml"),
    settings: Optional[Path] = typer.Option(None, exists=True, readable=True, help="Optional mapping_settings.yaml"),
    generated_rules: Optional[Path] = typer.Option(
        None,
        exists=False,
        readable=True,
        help="Optional generated rules file merged before manual anchors",
    ),
    proposals_path: Path = typer.Option(..., exists=True, readable=True, help="Proposals CSV from propose step"),
    loader_version: str = typer.Option("br/kg/onvoc_mapper", help="Loader version string"),
    uri: Optional[str] = typer.Option(None, help="Neo4j URI"),
    user: Optional[str] = typer.Option(None, help="Neo4j user"),
    password: Optional[str] = typer.Option(None, help="Neo4j password"),
    database: Optional[str] = typer.Option(None, help="Neo4j database"),
) -> None:
    """Materialize (:Task)-[:MAPS_TO]->(ONVOC concept) edges from accepted proposals."""

    rules_cfg, map_settings = load_settings(config, settings, generated_rules)
    anchors = {cfg.get("onvoc_uri"): build_anchor(cfg, map_settings.scoring_defaults) for cfg in rules_cfg.get("anchors", []) if cfg.get("onvoc_uri")}
    proposals = read_proposals_csv(proposals_path)

    filtered: List[Dict[str, Any]] = []
    for row in proposals:
        if (row.get("decision") or "").lower() not in {"accept", "accepted", "apply", "true", "1"}:
            continue
        anchor = anchors.get(row.get("onvoc_uri"))
        if not anchor:
            continue
        score_val = float(row.get("score", 0.0))
        margin_val = float(row.get("margin", 0.0))
        if score_val < anchor.accept.min_score:
            continue
        if not anchor.accept.allow_multi and margin_val < anchor.accept.min_margin:
            continue
        filtered.append(row)

    driver = build_driver(uri, user, password)
    try:
        applied = apply_mappings(
            driver,
            filtered,
            loader_version=loader_version,
            database=database,
        )
    finally:
        driver.close()
    typer.echo(f"Applied {applied} MAPS_TO edges")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
