"""
BR-KG Finder API - Natural Language to Structured Filters
Implements the Finder + Explain + Atlas system for dataset discovery
"""

import logging
import os
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Tuple

import numpy as np
import spacy
from flask import Blueprint, jsonify, request
from neo4j import GraphDatabase

finder_bp = Blueprint("finder", __name__, url_prefix="/kg")
logger = logging.getLogger(__name__)

LEGACY_ONVOC_SCHEMES = ["ONVOC", "ONVOC_LEGACY"]
LEGACY_ONVOC_ID_PREFIXES = ["ONVOC_", "legacy_onvoc:"]
LEGACY_ONVOC_LABELS = ["Concept", "OnvocClass", "OntologyConcept", "LegacyOnvocTag"]

SPACY_MODEL = "en_core_web_sm"


def load_spacy_pipeline():
    """Load the preferred spaCy pipeline, falling back to a blank tokenizer."""
    try:
        return spacy.load(SPACY_MODEL)
    except OSError:
        logger.warning(
            "spaCy model %s not installed; using blank English pipeline", SPACY_MODEL
        )
        return spacy.blank("en")


nlp = load_spacy_pipeline()


def _normalize_citation_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[-_/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _citation_dedupe_key(item: Mapping[str, Any]) -> str:
    aligned_study_id = str(item.get("aligned_study_id") or "").strip().lower()
    if aligned_study_id:
        return f"aligned_study:{aligned_study_id}"
    aligned_publication_id = (
        str(item.get("aligned_publication_id") or "").strip().lower()
    )
    if aligned_publication_id:
        return f"aligned_publication:{aligned_publication_id}"
    pmid = str(item.get("pmid") or "").strip().lower()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(item.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    title = _normalize_citation_text(item.get("title"))
    if title:
        return f"title:{title}"
    citation_id = str(item.get("id") or "").strip().lower()
    if citation_id:
        return f"id:{citation_id}"
    return f"raw:{_normalize_citation_text(str(dict(item)))}"


def _citation_priority(item: Mapping[str, Any]) -> tuple[int, int, int, str]:
    source_rank = 0 if str(item.get("source_type") or "") == "publication" else 1
    citation_count = -int(item.get("citation_count") or 0)
    year = -int(item.get("year") or 0)
    label = _normalize_citation_text(
        item.get("title") or item.get("doi") or item.get("pmid") or item.get("id")
    )
    return (source_rank, citation_count, year, label)


def _dedupe_citations(
    items: List[Mapping[str, Any]],
    *,
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    deduped: dict[str, Dict[str, Any]] = {}
    for raw in items:
        item = dict(raw)
        key = _citation_dedupe_key(item)
        existing = deduped.get(key)
        if existing is None or _citation_priority(item) < _citation_priority(existing):
            deduped[key] = item
    ordered = sorted(deduped.values(), key=_citation_priority)
    if limit is not None:
        return ordered[:limit]
    return ordered


class FilterOperator(Enum):
    EQUALS = "="
    GREATER_THAN = ">"
    GREATER_EQUAL = ">="
    LESS_THAN = "<"
    LESS_EQUAL = "<="
    CONTAINS = "contains"
    IN = "in"


@dataclass
class Filter:
    facet: str
    value: Any
    op: str = "="


class NLPFilterParser:
    """Parse natural language queries into structured filters"""

    # Keywords for different facets
    MODALITY_KEYWORDS = {
        "fmri": ["fmri", "functional mri", "task-fmri", "rest-fmri", "resting state"],
        "structural": ["structural", "t1", "t2", "anatomical", "mprage"],
        "dwi": ["dwi", "diffusion", "dti", "tractography"],
        "meg": ["meg", "magnetoencephalography"],
        "eeg": ["eeg", "electroencephalography"],
        "pet": ["pet", "positron emission"],
    }

    TASK_KEYWORDS = {
        "motor": ["motor", "finger tapping", "movement"],
        "visual": ["visual", "checkerboard", "retinotopy"],
        "language": ["language", "semantic", "word", "sentence"],
        "memory": ["memory", "recall", "recognition", "encoding"],
        "emotion": ["emotion", "affective", "faces", "emotional"],
        "rest": ["rest", "resting state", "rs-fmri"],
        "attention": ["attention", "stroop", "flanker"],
        "decision": ["decision", "gambling", "choice"],
        "social": ["social", "theory of mind", "mentalizing"],
    }

    POPULATION_KEYWORDS = {
        "older_adults": ["older adults", "elderly", "aging", "senior"],
        "children": ["children", "pediatric", "child", "kids"],
        "adolescents": ["adolescent", "teenager", "teen", "youth"],
        "young_adults": ["young adults", "college age"],
        "patients": ["patients", "clinical", "disorder"],
        "healthy": ["healthy", "control", "typical", "normal"],
    }

    CONSTRUCT_KEYWORDS = {
        "executive": ["executive", "cognitive control", "inhibition"],
        "attention": ["attention", "vigilance", "sustained attention"],
        "memory": ["memory", "working memory", "episodic memory"],
        "language": ["language", "syntax", "semantics", "phonology"],
        "perception": ["perception", "sensory", "perceptual"],
        "motor": ["motor", "motor control", "action"],
        "emotion": ["emotion", "affect", "mood"],
        "social": ["social cognition", "mentalizing", "empathy"],
    }

    def parse(self, text: str) -> List[Filter]:
        """Parse natural language text into filters"""
        filters = []
        text_lower = text.lower()
        doc = nlp(text_lower)

        # Check for modality
        for modality, keywords in self.MODALITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                filters.append(Filter(facet="modality", value=modality))
                break

        # Check for tasks
        for task, keywords in self.TASK_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                filters.append(Filter(facet="task", value=task))

        # Check for population
        for pop, keywords in self.POPULATION_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                filters.append(Filter(facet="population", value=pop))

        # Check for constructs
        for construct, keywords in self.CONSTRUCT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                filters.append(Filter(facet="construct", value=construct))

        # Parse age ranges
        age_patterns = [
            (r"(\d+)\s*-\s*(\d+)\s*years?\s*old", "range"),
            (r"older than\s*(\d+)", "min"),
            (r"younger than\s*(\d+)", "max"),
            (r"over\s*(\d+)", "min"),
            (r"under\s*(\d+)", "max"),
            (r"(\d+)\s*years?\s*old", "exact"),
            (r"age\s*>=?\s*(\d+)", "min"),
            (r"age\s*<=?\s*(\d+)", "max"),
        ]

        for pattern, age_type in age_patterns:
            match = re.search(pattern, text_lower)
            if match:
                if age_type == "range":
                    filters.append(
                        Filter(facet="age", value=int(match.group(1)), op=">=")
                    )
                    filters.append(
                        Filter(facet="age", value=int(match.group(2)), op="<=")
                    )
                elif age_type == "min":
                    filters.append(
                        Filter(facet="age", value=int(match.group(1)), op=">=")
                    )
                elif age_type == "max":
                    filters.append(
                        Filter(facet="age", value=int(match.group(1)), op="<=")
                    )
                elif age_type == "exact":
                    filters.append(Filter(facet="age", value=int(match.group(1))))
                break

        # Parse sample size
        n_patterns = [
            (r"n\s*>=?\s*(\d+)", "min"),
            (r"at least\s*(\d+)\s*subjects?", "min"),
            (r"more than\s*(\d+)\s*subjects?", "min"),
            (r"n\s*<=?\s*(\d+)", "max"),
            (r"less than\s*(\d+)\s*subjects?", "max"),
        ]

        for pattern, n_type in n_patterns:
            match = re.search(pattern, text_lower)
            if match:
                if n_type == "min":
                    filters.append(
                        Filter(facet="n", value=int(match.group(1)), op=">=")
                    )
                elif n_type == "max":
                    filters.append(
                        Filter(facet="n", value=int(match.group(1)), op="<=")
                    )

        # Parse year ranges
        year_patterns = [
            (r"(20\d{2})\s*-\s*(20\d{2})", "range"),
            (r"after\s*(20\d{2})", "min"),
            (r"before\s*(20\d{2})", "max"),
            (r"since\s*(20\d{2})", "min"),
            (r"from\s*(20\d{2})", "min"),
        ]

        for pattern, year_type in year_patterns:
            match = re.search(pattern, text_lower)
            if match:
                if year_type == "range":
                    filters.append(
                        Filter(facet="year", value=int(match.group(1)), op=">=")
                    )
                    filters.append(
                        Filter(facet="year", value=int(match.group(2)), op="<=")
                    )
                elif year_type == "min":
                    filters.append(
                        Filter(facet="year", value=int(match.group(1)), op=">=")
                    )
                elif year_type == "max":
                    filters.append(
                        Filter(facet="year", value=int(match.group(1)), op="<=")
                    )
                break  # Stop after first match to avoid duplicates

        # Parse MRI parameters
        tr_match = re.search(r"tr\s*=?\s*([\d.]+)", text_lower)
        if tr_match:
            filters.append(Filter(facet="tr", value=float(tr_match.group(1))))

        # Parse quality flags
        if "bids" in text_lower:
            filters.append(Filter(facet="bids", value=True))
        if "qc" in text_lower or "quality control" in text_lower:
            filters.append(Filter(facet="qc_ok", value=True))

        # Parse data sources
        sources = ["openneuro", "hcp", "abcd", "uk biobank", "adni", "neurovault"]
        for source in sources:
            if source in text_lower:
                filters.append(Filter(facet="source", value=source))

        return filters


class FacetCounter:
    """Count facet values for filtered results"""

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    def count_facets(self, filters: List[Filter]) -> Dict[str, List[Dict]]:
        """Get facet counts for current filter set"""
        with self.driver.session() as session:
            # Build the WHERE clause from filters
            where_clauses = []
            params = {}

            for i, f in enumerate(filters):
                param_name = f"param_{i}"
                if f.facet == "modality":
                    where_clauses.append(f"d.modality = ${param_name}")
                elif f.facet == "task":
                    where_clauses.append(
                        "EXISTS { MATCH (d)-[:HAS_TASK|USES_TASK|USES_PARADIGM]->(t) "
                        f"WHERE coalesce(t.name, t.task, t.label) = ${param_name} "
                        "AND any(lbl IN labels(t) WHERE lbl IN ['Task', 'TaskDef', 'TaskSpec']) }"
                    )
                elif f.facet == "n":
                    where_clauses.append(f"d.n {f.op} ${param_name}")
                elif f.facet == "age":
                    where_clauses.append(f"d.age_mean {f.op} ${param_name}")
                elif f.facet == "year":
                    where_clauses.append(f"d.year {f.op} ${param_name}")
                elif f.facet == "source":
                    where_clauses.append(f"d.source = ${param_name}")
                params[param_name] = f.value

            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

            facets = {}

            # Count modalities
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause}
            RETURN d.modality as value, count(d) as count
            ORDER BY count DESC
            """
            result = session.run(query, params)
            facets["modality"] = [
                {"value": r["value"], "count": r["count"]} for r in result if r["value"]
            ]

            # Count tasks
            query = f"""
            MATCH (d:Dataset)-[:HAS_TASK|USES_TASK|USES_PARADIGM]->(t)
            WHERE {where_clause}
              AND any(lbl IN labels(t) WHERE lbl IN ['Task', 'TaskDef', 'TaskSpec'])
            RETURN coalesce(t.name, t.task, t.label) as value, count(DISTINCT d) as count
            ORDER BY count DESC
            LIMIT 20
            """
            result = session.run(query, params)
            facets["task"] = [
                {"value": r["value"], "count": r["count"]} for r in result
            ]

            # Count age ranges (bucketed)
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause} AND d.age_mean IS NOT NULL
            RETURN 
                CASE 
                    WHEN d.age_mean < 18 THEN 'children'
                    WHEN d.age_mean < 30 THEN 'young_adults'
                    WHEN d.age_mean < 60 THEN 'adults'
                    ELSE 'older_adults'
                END as value,
                count(d) as count
            ORDER BY count DESC
            """
            result = session.run(query, params)
            facets["population"] = [
                {"value": r["value"], "count": r["count"]} for r in result
            ]

            # Count sample size ranges
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause} AND d.n IS NOT NULL
            RETURN 
                CASE 
                    WHEN d.n < 20 THEN '<20'
                    WHEN d.n < 50 THEN '20-50'
                    WHEN d.n < 100 THEN '50-100'
                    WHEN d.n < 500 THEN '100-500'
                    ELSE '500+'
                END as value,
                count(d) as count
            ORDER BY count DESC
            """
            result = session.run(query, params)
            facets["n_range"] = [
                {"value": r["value"], "count": r["count"]} for r in result
            ]

            # Count years
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause} AND d.year IS NOT NULL
            RETURN d.year as value, count(d) as count
            ORDER BY value DESC
            LIMIT 10
            """
            result = session.run(query, params)
            facets["year"] = [
                {"value": r["value"], "count": r["count"]} for r in result
            ]

            # Count sources
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause}
            RETURN d.source as value, count(d) as count
            ORDER BY count DESC
            """
            result = session.run(query, params)
            facets["source"] = [
                {"value": r["value"], "count": r["count"]} for r in result if r["value"]
            ]

            # Count quality flags
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause}
            RETURN 
                sum(CASE WHEN d.bids = true THEN 1 ELSE 0 END) as bids_count,
                sum(CASE WHEN d.qc_ok = true THEN 1 ELSE 0 END) as qc_count,
                count(d) as total
            """
            result = session.run(query, params).single()
            if result:
                facets["quality"] = [
                    {"value": "BIDS", "count": result["bids_count"]},
                    {"value": "QC_OK", "count": result["qc_count"]},
                ]

            return facets


class DatasetSearcher:
    """Search and rank datasets based on filters"""

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    def calculate_readiness(self, dataset: Dict) -> Tuple[str, List[str]]:
        """Calculate dataset readiness score"""
        issues = []
        score = 100

        # Check BIDS compliance
        if not dataset.get("bids"):
            issues.append("Not BIDS compliant")
            score -= 30

        # Check QC
        if not dataset.get("qc_ok"):
            issues.append("QC not passed")
            score -= 20

        # Check sample size
        n = dataset.get("n", 0)
        if n < 20:
            issues.append(f"Small sample size (n={n})")
            score -= 15

        # Check MRI parameters
        tr = dataset.get("tr")
        if not tr or tr > 3.0:
            issues.append(f"Non-standard TR ({tr}s)" if tr else "TR not specified")
            score -= 10

        # Determine color
        if score >= 80:
            color = "green"
        elif score >= 60:
            color = "yellow"
        else:
            color = "red"

        return color, issues

    def search(
        self,
        filters: List[Filter],
        sort: str = "n_desc",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict:
        """Search datasets with filters and pagination"""
        with self.driver.session() as session:
            # Build WHERE clause
            where_clauses = []
            params = {}

            for i, f in enumerate(filters):
                param_name = f"param_{i}"
                if f.facet == "modality":
                    where_clauses.append(f"d.modality = ${param_name}")
                elif f.facet == "task":
                    where_clauses.append(
                        "EXISTS { MATCH (d)-[:HAS_TASK|USES_TASK|USES_PARADIGM]->(t) "
                        f"WHERE coalesce(t.name, t.task, t.label) = ${param_name} "
                        "AND any(lbl IN labels(t) WHERE lbl IN ['Task', 'TaskDef', 'TaskSpec']) }"
                    )
                elif f.facet == "construct":
                    where_clauses.append(
                        "EXISTS { MATCH (d)-[:MEASURES|INVOLVES_CONSTRUCT]->(c) "
                        f"WHERE coalesce(c.name, c.label) = ${param_name} "
                        "AND any(lbl IN labels(c) WHERE lbl IN ['Construct', 'CognitiveConstruct', 'Concept']) }"
                    )
                elif f.facet == "population":
                    # Map population to age ranges
                    if f.value == "older_adults":
                        where_clauses.append("d.age_mean >= 60")
                    elif f.value == "children":
                        where_clauses.append("d.age_mean < 18")
                    elif f.value == "adolescents":
                        where_clauses.append("d.age_mean >= 12 AND d.age_mean < 18")
                    elif f.value == "young_adults":
                        where_clauses.append("d.age_mean >= 18 AND d.age_mean < 30")
                    continue  # Don't add to params
                elif f.facet == "n":
                    where_clauses.append(f"d.n {f.op} ${param_name}")
                elif f.facet == "age":
                    where_clauses.append(f"d.age_mean {f.op} ${param_name}")
                elif f.facet == "year":
                    where_clauses.append(f"d.year {f.op} ${param_name}")
                elif f.facet == "source":
                    where_clauses.append(f"d.source = ${param_name}")
                elif f.facet == "bids":
                    where_clauses.append(f"d.bids = ${param_name}")
                elif f.facet == "qc_ok":
                    where_clauses.append(f"d.qc_ok = ${param_name}")
                elif f.facet == "tr":
                    where_clauses.append(f"d.tr {f.op} ${param_name}")

                if f.facet not in [
                    "population"
                ]:  # Skip population as it's handled above
                    params[param_name] = f.value

            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

            # Determine sort order
            order_by = {
                "n_desc": "d.n DESC",
                "n_asc": "d.n ASC",
                "recency": "d.year DESC",
                "relevance": "d.n DESC",  # Can be improved with scoring
            }.get(sort, "d.n DESC")

            # Count total results
            count_query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause}
            RETURN count(d) as total
            """
            total = session.run(count_query, params).single()["total"]

            # Get paginated results with related data
            skip = (page - 1) * page_size
            query = f"""
            MATCH (d:Dataset)
            WHERE {where_clause}
            OPTIONAL MATCH (d)-[:HAS_TASK|USES_TASK|USES_PARADIGM]->(t)
            OPTIONAL MATCH (d)-[:MEASURES|INVOLVES_CONSTRUCT]->(c)
            OPTIONAL MATCH (d)-[:CITED_BY]->(p)
            OPTIONAL MATCH (d)-[rin:IN_ONVOC|HAS_ONVOC_ANNOTATION]-(o)
            WHERE any(lbl IN labels(o) WHERE lbl IN $onvoc_labels)
              AND (
                coalesce(o.scheme, '') IN $onvoc_schemes
                OR any(prefix IN $onvoc_id_prefixes WHERE toUpper(coalesce(o.id, '')) STARTS WITH prefix)
              )
            WITH d,
                 [x IN collect(DISTINCT CASE
                     WHEN any(lbl IN labels(t) WHERE lbl IN ['Task', 'TaskDef', 'TaskSpec'])
                     THEN coalesce(t.name, t.task, t.label)
                 END) WHERE x IS NOT NULL] as tasks,
                 [x IN collect(DISTINCT CASE
                     WHEN any(lbl IN labels(c) WHERE lbl IN ['Construct', 'CognitiveConstruct', 'Concept'])
                     THEN coalesce(c.name, c.label)
                 END) WHERE x IS NOT NULL] as constructs,
                 [x IN collect(DISTINCT CASE
                     WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Study'])
                     THEN {{
                         id: coalesce(p.id, p.pmid, p.doi, elementId(p)),
                         pmid: p.pmid,
                         doi: p.doi,
                         title: p.title,
                         year: p.year,
                         citation_count: coalesce(p.citation_count, 0),
                         source_type: CASE
                           WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                             THEN 'publication'
                           ELSE 'study'
                         END,
                         aligned_study_id: CASE
                           WHEN any(lbl IN labels(p) WHERE lbl = 'Study')
                             THEN coalesce(p.id, elementId(p))
                           ELSE head([
                             (p)-[:ALIGNS_WITH]->(aligned_study:Study) |
                             coalesce(aligned_study.id, elementId(aligned_study))
                           ])
                         END,
                         aligned_publication_id: CASE
                           WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                             THEN coalesce(p.id, p.pmid, p.doi, elementId(p))
                           ELSE head([
                             (aligned_publication)-[:ALIGNS_WITH]->(p)
                             WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                             coalesce(
                               aligned_publication.id,
                               aligned_publication.pmid,
                               aligned_publication.doi,
                               elementId(aligned_publication)
                             )
                           ])
                         END
                     }}
                 END) WHERE x IS NOT NULL] as citations,
                 collect(DISTINCT {{id:o.id, label:o.label}}) as onvoc_links
            RETURN d {{.*,
                    tasks: tasks,
                    constructs: constructs,
                    citations: citations[..3],
                    onvoc_links: onvoc_links,
                    primary_onvoc_id: d.primary_onvoc_id,
                    primary_onvoc_confidence: d.primary_onvoc_confidence}} as dataset
            ORDER BY {order_by}
            SKIP $skip
            LIMIT $limit
            """
            params["skip"] = skip
            params["limit"] = page_size
            params["onvoc_labels"] = LEGACY_ONVOC_LABELS
            params["onvoc_schemes"] = LEGACY_ONVOC_SCHEMES
            params["onvoc_id_prefixes"] = LEGACY_ONVOC_ID_PREFIXES

            results = session.run(query, params)

            items = []
            for record in results:
                dataset = dict(record["dataset"])
                dataset["citations"] = _dedupe_citations(
                    list(dataset.get("citations", []) or []),
                    limit=3,
                )

                # Calculate readiness
                readiness, readiness_issues = self.calculate_readiness(dataset)

                # Build "why" explanations
                why = []
                for f in filters:
                    if f.facet == "task" and f.value in dataset.get("tasks", []):
                        # Find citation evidence for this task
                        evidence = [
                            c for c in dataset.get("citations", []) if c.get("title")
                        ][:1]
                        why.append(
                            {"type": "task", "value": f.value, "evidence": evidence}
                        )
                    elif f.facet == "construct" and f.value in dataset.get(
                        "constructs", []
                    ):
                        why.append({"type": "construct", "value": f.value})
                    elif f.facet == "population":
                        why.append({"type": "population", "value": f.value})

                # Format age statistics
                age_stats = None
                if dataset.get("age_mean"):
                    age_stats = {
                        "mean": dataset.get("age_mean"),
                        "sd": dataset.get("age_sd", 0),
                        "min": dataset.get("age_min"),
                        "max": dataset.get("age_max"),
                    }

                # Format MRI parameters
                mri = None
                if dataset.get("tr"):
                    mri = {
                        "TR": dataset.get("tr"),
                        "voxel": dataset.get("voxel_size", []),
                    }

                # Build item
                item = {
                    "id": dataset.get("id"),
                    "title": dataset.get("title", dataset.get("id")),
                    "source": dataset.get("source", "Unknown"),
                    "n": dataset.get("n"),
                    "ageStats": age_stats,
                    "tasks": dataset.get("tasks", []),
                    "mri": mri,
                    "flags": {
                        "bids": dataset.get("bids", False),
                        "qc_ok": dataset.get("qc_ok", False),
                    },
                    "why": why,
                    "readiness": readiness,
                    "readiness_issues": readiness_issues,
                }
                items.append(item)

            return {
                "items": items,
                "total": total,
                "page": page,
                "pageSize": page_size,
                "filters": [asdict(f) for f in filters],
            }


# Initialize components
parser = NLPFilterParser()
facet_counter = None
searcher = None
explainer = None


def init_finder(
    neo4j_uri: str = None, neo4j_user: str = None, neo4j_password: str = None
):
    """Initialize finder components with database connection"""
    global facet_counter, searcher, explainer

    if not (neo4j_uri and neo4j_user and neo4j_password):
        logger.error("Neo4j connection details are required for Finder.")
        return

    try:
        facet_counter = FacetCounter(neo4j_uri, neo4j_user, neo4j_password)
        searcher = DatasetSearcher(neo4j_uri, neo4j_user, neo4j_password)
        logger.info("Using Neo4j database: %s", neo4j_uri)
    except Exception as e:
        logger.error("Failed to connect to Neo4j: %s", e)


@finder_bp.route("/suggestFilters", methods=["POST"])
def suggest_filters():
    """Parse natural language query into structured filters"""
    data = request.get_json()
    text = data.get("text", "")

    if not text:
        return jsonify({"filters": []})

    filters = parser.parse(text)
    return jsonify({"filters": [asdict(f) for f in filters]})


@finder_bp.route("/facets", methods=["POST"])
def get_facets():
    """Get facet counts for current filter set"""
    data = request.get_json()
    filter_dicts = data.get("filters", [])

    # Convert dicts back to Filter objects
    filters = [Filter(**f) for f in filter_dicts]

    if not facet_counter:
        return jsonify({"error": "Finder not initialized"}), 500

    facets = facet_counter.count_facets(filters)
    return jsonify({"facets": facets})


@finder_bp.route("/searchDatasets", methods=["POST"])
def search_datasets():
    """Search datasets with filters and pagination"""
    data = request.get_json()
    filter_dicts = data.get("filters", [])
    sort = data.get("sort", "n_desc")
    page = data.get("page", 1)
    page_size = data.get("pageSize", 20)

    # Convert dicts back to Filter objects
    filters = [Filter(**f) for f in filter_dicts]

    if not searcher:
        return jsonify({"error": "Finder not initialized"}), 500

    results = searcher.search(filters, sort, page, page_size)
    return jsonify(results)


@finder_bp.route("/explain/<dataset_id>", methods=["GET"])
def explain_dataset(dataset_id: str):
    """Get detailed explanation and evidence for a dataset"""

    # Use explainer if available
    if explainer:
        result = explainer.explain(dataset_id)
        if not result:
            return jsonify({"error": "Dataset not found"}), 404
        return jsonify(result)

    # Fall back to Neo4j implementation if available
    if searcher and hasattr(searcher, "driver"):
        with searcher.driver.session() as session:
            # Get dataset with all relationships
            query = """
            MATCH (d:Dataset {id: $id})
            OPTIONAL MATCH (d)-[:HAS_TASK|USES_TASK|USES_PARADIGM]->(t)
            OPTIONAL MATCH (d)-[:MEASURES|INVOLVES_CONSTRUCT]->(c)
            OPTIONAL MATCH (d)-[:CITED_BY]->(p)
            OPTIONAL MATCH (d)-[rin:IN_ONVOC|HAS_ONVOC_ANNOTATION]-(o)
            WHERE any(lbl IN labels(o) WHERE lbl IN $onvoc_labels)
              AND (
                coalesce(o.scheme, '') IN $onvoc_schemes
                OR any(prefix IN $onvoc_id_prefixes WHERE toUpper(coalesce(o.id, '')) STARTS WITH prefix)
              )
            OPTIONAL MATCH path = shortestPath((d)-[*..3]-(related:Dataset))
            WHERE related.id <> d.id
            WITH d,
                 [x IN collect(DISTINCT CASE
                     WHEN any(lbl IN labels(t) WHERE lbl IN ['Task', 'TaskDef', 'TaskSpec'])
                     THEN t
                 END) WHERE x IS NOT NULL] as tasks,
                 [x IN collect(DISTINCT CASE
                     WHEN any(lbl IN labels(c) WHERE lbl IN ['Construct', 'CognitiveConstruct', 'Concept'])
                     THEN c
                 END) WHERE x IS NOT NULL] as constructs,
                 [x IN collect(DISTINCT CASE
                     WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Study'])
                     THEN {
                         id: coalesce(p.id, p.pmid, p.doi, elementId(p)),
                         pmid: p.pmid,
                         doi: p.doi,
                         title: p.title,
                         year: p.year,
                         authors: p.authors,
                         citation_count: coalesce(p.citation_count, 0),
                         source_type: CASE
                           WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                             THEN 'publication'
                           ELSE 'study'
                         END,
                         aligned_study_id: CASE
                           WHEN any(lbl IN labels(p) WHERE lbl = 'Study')
                             THEN coalesce(p.id, elementId(p))
                           ELSE head([
                             (p)-[:ALIGNS_WITH]->(aligned_study:Study) |
                             coalesce(aligned_study.id, elementId(aligned_study))
                           ])
                         END,
                         aligned_publication_id: CASE
                           WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                             THEN coalesce(p.id, p.pmid, p.doi, elementId(p))
                           ELSE head([
                             (aligned_publication)-[:ALIGNS_WITH]->(p)
                             WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                             coalesce(
                               aligned_publication.id,
                               aligned_publication.pmid,
                               aligned_publication.doi,
                               elementId(aligned_publication)
                             )
                           ])
                         END
                     }
                 END) WHERE x IS NOT NULL] as publications,
                 collect(DISTINCT {id:o.id, label:o.label, confidence:rin.confidence}) AS onvoc_links,
                 collect(DISTINCT related)[..5] as related_datasets
            RETURN d, tasks, constructs, publications, onvoc_links, related_datasets
            """

            result = session.run(
                query,
                {
                    "id": dataset_id,
                    "onvoc_labels": LEGACY_ONVOC_LABELS,
                    "onvoc_schemes": LEGACY_ONVOC_SCHEMES,
                    "onvoc_id_prefixes": LEGACY_ONVOC_ID_PREFIXES,
                },
            ).single()
            if not result:
                return jsonify({"error": "Dataset not found"}), 404

            dataset = dict(result["d"])
            tasks = [dict(t) for t in result["tasks"]]
            constructs = [dict(c) for c in result["constructs"]]
            publications = _dedupe_citations(
                [dict(p) for p in result["publications"]],
            )
            onvoc_links = result.get("onvoc_links") or []

        # Generate summary
        summary_parts = []
        if dataset.get("modality"):
            summary_parts.append(f"{dataset['modality'].upper()} dataset")
        if tasks:
            task_names = [t["name"] for t in tasks[:3]]
            summary_parts.append(f"with {', '.join(task_names)} task(s)")
        if dataset.get("n"):
            summary_parts.append(f"n={dataset['n']}")
        if dataset.get("age_mean"):
            summary_parts.append(f"mean age {dataset['age_mean']:.1f}")

        summary = "; ".join(summary_parts) + "."

        # Get top citations
        top_citations = _dedupe_citations(publications, limit=5)

        # Build mini graph (subset of nodes and edges)
        nodes = [
            {
                "id": dataset_id,
                "type": "Dataset",
                "label": dataset.get("title", dataset_id),
            }
        ]
        edges = []

        # Add task nodes
        for t in tasks[:3]:
            nodes.append(
                {"id": f"task:{t['name']}", "type": "Task", "label": t["name"]}
            )
            edges.append(
                {
                    "src": dataset_id,
                    "dst": f"task:{t['name']}",
                    "rel": "hasTask",
                    "weight": 0.8,
                }
            )

        # Add construct nodes
        for c in constructs[:3]:
            nodes.append(
                {
                    "id": f"construct:{c['name']}",
                    "type": "Construct",
                    "label": c["name"],
                }
            )
            edges.append(
                {
                    "src": dataset_id,
                    "dst": f"construct:{c['name']}",
                    "rel": "measures",
                    "weight": 0.7,
                }
            )

        # Simple force-directed layout positions (placeholder - would use real layout algorithm)
        positions = []
        for i, node in enumerate(nodes):
            angle = (2 * np.pi * i) / len(nodes)
            r = 10 if i == 0 else 20
            positions.append(
                {"id": node["id"], "x": r * np.cos(angle), "y": r * np.sin(angle)}
            )

        return jsonify(
            {
                "summary": summary,
                "onvoc": {
                    "links": onvoc_links,
                    "primary_onvoc_id": dataset.get("primary_onvoc_id"),
                    "primary_onvoc_confidence": dataset.get("primary_onvoc_confidence"),
                },
                "topCitations": [
                    {"doi": p.get("doi"), "title": p.get("title")}
                    for p in top_citations
                ],
                "miniGraph": {"nodes": nodes, "edges": edges, "positions": positions},
                "details": {
                    "tasks": [t["name"] for t in tasks],
                    "constructs": [c["name"] for c in constructs],
                    "publications": len(publications),
                },
            }
        )


@finder_bp.route("/graph/sample", methods=["GET"])
def get_graph_sample():
    """Get a sample of the knowledge graph for visualization"""
    limit = request.args.get("limit", 100, type=int)
    node_type = request.args.get("type", None)

    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    neo4j_database = os.getenv("NEO4J_DATABASE")

    if not neo4j_uri or not neo4j_password:
        return jsonify({"error": "Neo4j not configured"}), 500

    if node_type and not re.match(r"^[A-Za-z0-9_]+$", node_type):
        return jsonify({"error": "Invalid node type"}), 400

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session(database=neo4j_database) as session:
            if node_type:
                cypher = f"MATCH (n:`{node_type}`) RETURN n LIMIT $limit"
            else:
                cypher = "MATCH (n) RETURN n LIMIT $limit"
            result = session.run(cypher, {"limit": limit})

            nodes = []
            node_ids = []
            for record in result:
                node = record["n"]
                node_id = node.get("id") or node.element_id
                labels = list(node.labels)
                props = dict(node)
                nodes.append(
                    {
                        "id": node_id,
                        "label": props.get("name", props.get("title", node_id)),
                        "type": labels[0] if labels else "Unknown",
                        "properties": props,
                    }
                )
                node_ids.append(node.element_id)

            edges = []
            if node_ids:
                edge_query = """
                    MATCH (a)-[r]->(b)
                    WHERE elementId(a) IN $ids AND elementId(b) IN $ids
                    RETURN a, r, b
                    LIMIT $limit
                """
                for record in session.run(edge_query, {"ids": node_ids, "limit": 500}):
                    a = record["a"]
                    b = record["b"]
                    rel = record["r"]
                    edges.append(
                        {
                            "id": rel.element_id,
                            "source": a.get("id") or a.element_id,
                            "target": b.get("id") or b.element_id,
                            "type": rel.type,
                            "properties": dict(rel),
                        }
                    )

        return jsonify(
            {
                "nodes": nodes,
                "edges": edges,
                "metadata": {
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "node_limit": limit,
                },
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        driver.close()


# Export for testing
__all__ = [
    "finder_bp",
    "init_finder",
    "NLPFilterParser",
    "FacetCounter",
    "DatasetSearcher",
]
