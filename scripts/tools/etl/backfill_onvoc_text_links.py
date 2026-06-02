#!/usr/bin/env python3
"""Backfill lightweight ONVOC evidence links from text matches.

This script is intended for sparse concepts that have weak crosswalk coverage.
It materializes direct concept edges for explorer categories using a small set
of phrase/acronym terms.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase
import yaml


ONVOC_CONCEPT_LABELS = ["ONVOC", "Concept", "OnvocClass", "OntologyConcept"]
MIN_TEXT_TERM_CHARS = 3


@dataclass(frozen=True)
class EntitySpec:
    name: str
    labels: list[str]
    rel: str
    fields: list[str]


ENTITY_SPECS: dict[str, EntitySpec] = {
    "statmaps": EntitySpec(
        name="statmaps",
        labels=["StatMap", "StatsMap", "StatisticalMap"],
        rel="IN_ONVOC",
        fields=["name", "title", "label", "description", "task", "contrast"],
    ),
    "datasets": EntitySpec(
        name="datasets",
        labels=["Dataset", "DataResource", "OpenNeuroDataset"],
        rel="ABOUT",
        fields=["name", "title", "label", "description", "source_repo_id"],
    ),
    "papers": EntitySpec(
        name="papers",
        labels=["Publication", "Paper"],
        rel="ABOUT",
        fields=["title", "abstract"],
    ),
    "tasks": EntitySpec(
        name="tasks",
        labels=["Task", "TaskSpec", "TaskDef", "TaskAnalysis"],
        rel="IN_ONVOC",
        fields=["name", "title", "label", "description", "task", "bids_task"],
    ),
    "contrasts": EntitySpec(
        name="contrasts",
        labels=["Contrast", "ContrastSpec"],
        rel="IN_ONVOC",
        fields=["name", "title", "label", "description", "contrast", "contrast_name"],
    ),
    "tools": EntitySpec(
        name="tools",
        labels=["Tool", "ToolVersion"],
        rel="ABOUT",
        fields=["name", "title", "label", "description", "tool_name"],
    ),
    "studies": EntitySpec(
        name="studies",
        labels=["Study", "Experiment"],
        rel="ABOUT",
        fields=["name", "title", "label", "description", "study_id"],
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument("--concept-id", required=True)
    parser.add_argument(
        "--categories",
        default="statmaps,datasets,papers,tasks,contrasts,tools,studies",
        help="Comma-separated category keys",
    )
    parser.add_argument(
        "--term",
        action="append",
        default=[],
        help="Literal match term (case-insensitive, can repeat)",
    )
    parser.add_argument(
        "--acronym",
        action="append",
        default=[],
        help="Word-boundary acronym regex term, e.g. DMN (can repeat)",
    )
    parser.add_argument("--source", default="config_text_backfill")
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument(
        "--alias-map",
        type=Path,
        default=None,
        help="Optional YAML file with concept-specific term/acronym overrides",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _text_expr(node_alias: str, fields: list[str]) -> str:
    parts = [f"toLower(coalesce(toString({node_alias}.`{field}`), ''))" for field in fields]
    return " + ' ' + ".join(parts)


def _build_acronym_regex(acronyms: list[str]) -> str:
    cleaned = []
    for raw in acronyms:
        token = (raw or "").strip()
        if not token:
            continue
        cleaned.append(re.escape(token))
    if not cleaned:
        return ""
    # Build one regex so Neo4j evaluates it once per row.
    return "(?i).*(?:" + "|".join([rf"\\b{token}\\b" for token in cleaned]) + ").*"


def _has_minimum_text_term_length(term: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", term.lower())
    return len(compact) >= MIN_TEXT_TERM_CHARS


def _build_term_regex(terms: list[str]) -> str:
    cleaned = []
    for raw in terms:
        token = (raw or "").strip()
        if not token or not _has_minimum_text_term_length(token):
            continue
        cleaned.append(re.escape(token))
    if not cleaned:
        return ""
    # Match configured text terms as complete lexical spans, not substrings.
    boundary_left = r"(?<![A-Za-z0-9_])"
    boundary_right = r"(?![A-Za-z0-9_])"
    return (
        "(?i).*(?:"
        + "|".join([rf"{boundary_left}{token}{boundary_right}" for token in cleaned])
        + ").*"
    )


def _normalize_terms(terms: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for raw in terms:
        val = (raw or "").strip().lower()
        if not val or val in seen:
            continue
        if not _has_minimum_text_term_length(val):
            continue
        seen.add(val)
        out.append(val)
    return out


def _load_alias_overrides(path: Path | None, concept_id: str) -> tuple[list[str], list[str]]:
    if path is None:
        return [], []
    if not path.exists():
        raise FileNotFoundError(f"Alias map not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return [], []

    concept_aliases = payload.get("concept_aliases")
    if isinstance(concept_aliases, dict):
        node = concept_aliases.get(concept_id)
    else:
        node = payload.get(concept_id)

    if not isinstance(node, dict):
        return [], []

    raw_terms: list[str] = []
    for key in ("terms", "aliases"):
        value = node.get(key)
        if isinstance(value, list):
            raw_terms.extend(str(item) for item in value if item is not None)

    raw_acronyms: list[str] = []
    value = node.get("acronyms")
    if isinstance(value, list):
        raw_acronyms.extend(str(item) for item in value if item is not None)
    return raw_terms, raw_acronyms


def _resolve_concept_label(driver, concept_id: str, database: str | None) -> str:
    cypher = """
    MATCH (c {id:$concept_id})
    WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
    RETURN coalesce(c.label, c.name, c.id) AS label
    LIMIT 1
    """
    with driver.session(database=database) as session:
        record = session.run(
            cypher,
            {
                "concept_id": concept_id,
                "concept_labels": ONVOC_CONCEPT_LABELS,
            },
        ).single()
    if not record:
        raise RuntimeError(f"ONVOC concept not found: {concept_id}")
    return str(record["label"] or concept_id)


def _run_for_category(
    driver,
    database: str | None,
    concept_id: str,
    spec: EntitySpec,
    terms: list[str],
    acronym_regex: str,
    source: str,
    confidence: float,
    dry_run: bool,
) -> dict[str, Any]:
    concept_match = """
    MATCH (c {id:$concept_id})
    WHERE any(lbl IN labels(c) WHERE lbl IN $concept_labels)
      AND (coalesce(c.scheme, '') = 'ONVOC' OR c.id STARTS WITH 'ONVOC_')
    """
    text_expr = _text_expr("n", spec.fields)
    term_regex = _build_term_regex(terms)
    where_expr = """
    WHERE ($term_regex <> '' AND txt =~ $term_regex)
       OR ($acronym_regex <> '' AND txt =~ $acronym_regex)
    """

    if dry_run:
        cypher = (
            concept_match
            + """
            MATCH (n)
            WHERE any(lbl IN labels(n) WHERE lbl IN $node_labels)
            WITH c, n, """
            + text_expr
            + """ AS txt
            """
            + where_expr
            + """
            RETURN count(DISTINCT n) AS matched
            """
        )
        with driver.session(database=database) as session:
            row = session.run(
                cypher,
                {
                    "concept_id": concept_id,
                    "concept_labels": ONVOC_CONCEPT_LABELS,
                    "node_labels": spec.labels,
                    "terms": terms,
                    "term_regex": term_regex,
                    "acronym_regex": acronym_regex,
                },
            ).single()
        return {
            "category": spec.name,
            "relationship": spec.rel,
            "matched": int((row or {}).get("matched") or 0),
            "created": 0,
        }

    cypher = (
        concept_match
        + """
        MATCH (n)
        WHERE any(lbl IN labels(n) WHERE lbl IN $node_labels)
        WITH c, n, """
        + text_expr
        + """ AS txt
        """
        + where_expr
        + f"""
        WITH c, n, exists{{ (n)-[:{spec.rel}]->(c) }} AS already_linked
        MERGE (n)-[r:{spec.rel}]->(c)
        ON CREATE SET
          r.source = $source,
          r.confidence = $confidence,
          r.created_at = timestamp(),
          r.match_terms = $terms
        RETURN count(DISTINCT n) AS matched,
               sum(CASE WHEN already_linked THEN 0 ELSE 1 END) AS created
        """
    )
    with driver.session(database=database) as session:
        row = session.run(
            cypher,
            {
                "concept_id": concept_id,
                "concept_labels": ONVOC_CONCEPT_LABELS,
                "node_labels": spec.labels,
                "terms": terms,
                "term_regex": term_regex,
                "acronym_regex": acronym_regex,
                "source": source,
                "confidence": confidence,
            },
        ).single()
    return {
        "category": spec.name,
        "relationship": spec.rel,
        "matched": int((row or {}).get("matched") or 0),
        "created": int((row or {}).get("created") or 0),
    }


def main() -> None:
    args = parse_args()
    selected = [token.strip().lower() for token in args.categories.split(",") if token.strip()]
    unknown = [key for key in selected if key not in ENTITY_SPECS]
    if unknown:
        raise ValueError(f"Unsupported categories: {', '.join(sorted(set(unknown)))}")

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        concept_label = _resolve_concept_label(driver, args.concept_id, args.neo4j_database)
        alias_terms, alias_acronyms = _load_alias_overrides(args.alias_map, args.concept_id)
        terms = _normalize_terms([*(args.term or []), *alias_terms])
        if not terms:
            terms = _normalize_terms([concept_label])
        acronym_regex = _build_acronym_regex([*(args.acronym or []), *alias_acronyms])
        if not terms and not acronym_regex:
            raise ValueError("No usable --term/--acronym or concept label.")

        results = []
        for key in selected:
            result = _run_for_category(
                driver=driver,
                database=args.neo4j_database,
                concept_id=args.concept_id,
                spec=ENTITY_SPECS[key],
                terms=terms,
                acronym_regex=acronym_regex,
                source=args.source,
                confidence=args.confidence,
                dry_run=args.dry_run,
            )
            results.append(result)

        report = {
            "concept_id": args.concept_id,
            "concept_label": concept_label,
            "terms": terms,
            "acronym_regex": acronym_regex,
            "dry_run": args.dry_run,
            "results": results,
            "totals": {
                "matched": int(sum(item["matched"] for item in results)),
                "created": int(sum(item["created"] for item in results)),
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
