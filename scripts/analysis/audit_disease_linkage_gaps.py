#!/usr/bin/env python3
"""Audit linkage gaps for ONVOC disease concepts.

This script combines:
1) ONVOC disease subtree from Neo4j (root ONVOC_0000003),
2) disease entities list endpoint payload,
3) per-concept disease summary endpoint payload,
4) batched Neo4j-mediated dataset candidate counts, and
5) alias/acronym override coverage.

It writes ranked gap reports to docs/audits in JSON, CSV, and Markdown.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

ONVOC_CONCEPT_LABELS = ["ONVOC", "Concept", "OnvocClass", "OntologyConcept"]
DATASET_LABELS = ["DataResource", "Dataset", "OpenNeuroDataset"]
PAPER_LABELS = ["Publication", "Paper"]
STUDY_LABELS = ["Study", "Experiment"]
TASK_LABELS = ["Task", "TaskSpec", "TaskDef", "TaskAnalysis", "TaskFamily"]
STATMAP_LABELS = ["StatMap", "StatsMap", "StatisticalMap"]
FEATURE_KEYS = [
    "statmaps",
    "coords",
    "timeseries",
    "datasets",
    "papers",
    "tasks",
    "contrasts",
    "tools",
    "studies",
]
TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class DiseaseNode:
    concept_id: str
    label: str
    depth: int
    parent_count: int
    child_count: int


@dataclass(frozen=True)
class SummaryInfo:
    status: str
    label: str
    features: dict[str, int]
    ontology_parents: int
    ontology_children: int
    error: str


@dataclass(frozen=True)
class AliasInfo:
    aliases: list[str]
    acronyms: list[str]


def _find_repo_root(start: Path | None = None) -> Path:
    start_path = (start or Path.cwd()).resolve()
    for parent in [start_path, *start_path.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return start_path


def _read_dotenv_value(repo_root: Path, key: str) -> str | None:
    for filename in (".env.local", ".env"):
        path = repo_root / filename
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            env_key, env_value = line.split("=", 1)
            if env_key.strip() != key:
                continue
            value = env_value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value or None
    return None


def _env(repo_root: Path, key: str, default: str | None = None) -> str | None:
    return os.getenv(key) or _read_dotenv_value(repo_root, key) or default


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _normalize_alias(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _normalize_acronym(text: Any) -> str:
    token = "".join(ch for ch in str(text or "").upper() if ch.isalnum())
    return token.strip()


def _http_backoff_sleep(backoff_base: float, attempt: int) -> None:
    sleep_s = min(10.0, backoff_base * (2**attempt)) + random.uniform(0.0, 0.2)
    time.sleep(max(0.0, sleep_s))


def _fetch_json(
    url: str,
    *,
    timeout_s: float,
    retries: int,
    backoff_base: float,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "brain-researcher-disease-gap-audit/1.0",
                },
            )
            with urlopen(request, timeout=timeout_s) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except HTTPError as exc:
            if exc.code == 404:
                return {"_http_status": 404}
            if exc.code not in TRANSIENT_HTTP_CODES or attempt >= retries:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                detail = body[:240].strip()
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"HTTP {exc.code} for {url}{suffix}") from exc
            last_error = exc
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                raise RuntimeError(f"request failed for {url}: {exc}") from exc

        _http_backoff_sleep(backoff_base, attempt)

    if last_error is not None:
        raise RuntimeError(f"request failed for {url}: {last_error}")
    raise RuntimeError(f"request failed for {url}: unknown error")


def _neo4j_query(
    driver: Any,
    query: str,
    params: dict[str, Any],
    *,
    database: str | None,
    query_timeout_s: float,
    retries: int,
    backoff_base: float,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with driver.session(database=database) as session:
                result = session.run(query, params, timeout=query_timeout_s)
                return result.data()
        except (ServiceUnavailable, SessionExpired) as exc:
            last_error = exc
        except Neo4jError as exc:
            last_error = exc
            code = str(getattr(exc, "code", "") or "")
            transient = code.startswith("Neo.TransientError")
            if not transient or attempt >= retries:
                raise RuntimeError(f"neo4j query failed ({code or 'neo4j_error'}): {exc}") from exc

        if attempt < retries:
            _http_backoff_sleep(backoff_base, attempt)

    if last_error is not None:
        raise RuntimeError(f"neo4j query failed: {last_error}") from last_error
    raise RuntimeError("neo4j query failed: unknown error")


def load_disease_subtree(
    driver: Any,
    *,
    database: str | None,
    root_id: str,
    scheme_filter: str,
    query_timeout_s: float,
    retries: int,
    backoff_base: float,
) -> list[DiseaseNode]:
    rows = _neo4j_query(
        driver,
        """
        MATCH (root)
        WHERE coalesce(root.id, elementId(root)) = $root_id
          AND any(lbl IN labels(root) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(root.scheme, '') = $scheme_filter
            OR toString(coalesce(root.id, '')) STARTS WITH 'ONVOC_'
          )
        MATCH path=(n)-[:CLASSIFIED_UNDER*0..8]->(root)
        WHERE n.id IS NOT NULL
          AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
          AND (
            $scheme_filter IS NULL
            OR coalesce(n.scheme, '') = $scheme_filter
            OR toString(coalesce(n.id, '')) STARTS WITH 'ONVOC_'
          )
        WITH n, min(length(path)) AS depth
        RETURN coalesce(n.id, elementId(n)) AS id,
               coalesce(n.label, n.name, n.title, n.id) AS label,
               depth,
               size([(n)-[:CLASSIFIED_UNDER]->() | 1]) AS parent_count,
               size([(n)<-[:CLASSIFIED_UNDER]-() | 1]) AS child_count
        ORDER BY depth, label
        """,
        {
            "root_id": root_id,
            "seed_labels": ONVOC_CONCEPT_LABELS,
            "scheme_filter": scheme_filter,
        },
        database=database,
        query_timeout_s=query_timeout_s,
        retries=retries,
        backoff_base=backoff_base,
    )

    return [
        DiseaseNode(
            concept_id=str(row.get("id") or ""),
            label=str(row.get("label") or row.get("id") or ""),
            depth=_safe_int(row.get("depth")),
            parent_count=_safe_int(row.get("parent_count")),
            child_count=_safe_int(row.get("child_count")),
        )
        for row in rows
        if str(row.get("id") or "").strip()
    ]


def load_disease_entities_from_api(
    *,
    base_url: str,
    limit: int,
    timeout_s: float,
    retries: int,
    backoff_base: float,
) -> dict[str, dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/api/kg/lens/disease/entities?limit={int(limit)}"
    payload = _fetch_json(
        url,
        timeout_s=timeout_s,
        retries=retries,
        backoff_base=backoff_base,
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected entities response shape for {url}")

    entities: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        concept_id = str(item.get("id") or "").strip()
        if not concept_id:
            continue
        counts = item.get("counts") if isinstance(item.get("counts"), dict) else {}
        entities[concept_id] = {
            "label": str(item.get("label") or concept_id),
            "datasets": _safe_int(counts.get("datasets")),
            "connected_score": _safe_int(item.get("connected_score")),
        }
    return entities


def fetch_summary_for_concept(
    *,
    base_url: str,
    concept_id: str,
    timeout_s: float,
    retries: int,
    backoff_base: float,
) -> SummaryInfo:
    url = (
        f"{base_url.rstrip('/')}/api/kg/lens/disease/entity/"
        f"{quote(concept_id, safe='')}/summary"
    )
    payload = _fetch_json(
        url,
        timeout_s=timeout_s,
        retries=retries,
        backoff_base=backoff_base,
    )
    if isinstance(payload, dict) and payload.get("_http_status") == 404:
        return SummaryInfo(
            status="MISSING",
            label=concept_id,
            features={key: 0 for key in FEATURE_KEYS},
            ontology_parents=0,
            ontology_children=0,
            error="404",
        )

    if not isinstance(payload, dict):
        return SummaryInfo(
            status="ERROR",
            label=concept_id,
            features={key: 0 for key in FEATURE_KEYS},
            ontology_parents=0,
            ontology_children=0,
            error="invalid response payload",
        )

    features_raw = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    ontology_raw = payload.get("ontology") if isinstance(payload.get("ontology"), dict) else {}
    return SummaryInfo(
        status="OK",
        label=str(payload.get("label") or concept_id),
        features={key: _safe_int(features_raw.get(key)) for key in FEATURE_KEYS},
        ontology_parents=_safe_int(ontology_raw.get("parents")),
        ontology_children=_safe_int(ontology_raw.get("children")),
        error="",
    )


def load_summaries(
    *,
    base_url: str,
    concept_ids: list[str],
    timeout_s: float,
    retries: int,
    backoff_base: float,
    workers: int,
) -> dict[str, SummaryInfo]:
    out: dict[str, SummaryInfo] = {}
    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                fetch_summary_for_concept,
                base_url=base_url,
                concept_id=concept_id,
                timeout_s=timeout_s,
                retries=retries,
                backoff_base=backoff_base,
            ): concept_id
            for concept_id in concept_ids
        }
        for future in as_completed(futures):
            concept_id = futures[future]
            try:
                out[concept_id] = future.result()
            except Exception as exc:
                out[concept_id] = SummaryInfo(
                    status="ERROR",
                    label=concept_id,
                    features={key: 0 for key in FEATURE_KEYS},
                    ontology_parents=0,
                    ontology_children=0,
                    error=str(exc),
                )
    return out


def _chunks(values: list[str], size: int) -> list[list[str]]:
    chunk_size = max(1, size)
    return [values[idx : idx + chunk_size] for idx in range(0, len(values), chunk_size)]


def load_mediated_dataset_candidate_counts(
    driver: Any,
    *,
    database: str | None,
    concept_ids: list[str],
    scheme_filter: str,
    batch_size: int,
    query_timeout_s: float,
    retries: int,
    backoff_base: float,
) -> dict[str, dict[str, int]]:
    defaults = {
        "mediated_dataset_candidates": 0,
        "direct_dataset_candidates": 0,
        "via_paper_dataset_candidates": 0,
        "via_study_dataset_candidates": 0,
        "via_task_dataset_candidates": 0,
        "via_statmap_dataset_candidates": 0,
    }
    counts = {concept_id: dict(defaults) for concept_id in concept_ids}

    for batch in _chunks(concept_ids, batch_size):
        rows = _neo4j_query(
            driver,
            """
            UNWIND $entity_ids AS entity_id
            MATCH (n)
            WHERE coalesce(n.id, elementId(n)) = entity_id
              AND any(lbl IN labels(n) WHERE lbl IN $seed_labels)
              AND (
                $scheme_filter IS NULL
                OR coalesce(n.scheme, '') = $scheme_filter
                OR toString(coalesce(n.id, '')) STARTS WITH 'ONVOC_'
              )
            CALL {
              WITH n
              OPTIONAL MATCH (n)-[]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS direct_ids
            }
            CALL {
              WITH n
              OPTIONAL MATCH (n)-[]-(p)
              WHERE any(lbl IN labels(p) WHERE lbl IN $paper_labels)
              OPTIONAL MATCH (p)-[]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              WITH d
              WHERE d IS NOT NULL
              RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS paper_ids
            }
            CALL {
              WITH n
              OPTIONAL MATCH (n)-[]-(s)
              WHERE any(lbl IN labels(s) WHERE lbl IN $study_labels)
              OPTIONAL MATCH (s)-[]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              WITH d
              WHERE d IS NOT NULL
              RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS study_ids
            }
            CALL {
              WITH n
              OPTIONAL MATCH (n)-[]-(t)
              WHERE any(lbl IN labels(t) WHERE lbl IN $task_labels)
              OPTIONAL MATCH (t)-[]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              WITH d
              WHERE d IS NOT NULL
              RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS task_ids
            }
            CALL {
              WITH n
              OPTIONAL MATCH (n)-[]-(m)
              WHERE any(lbl IN labels(m) WHERE lbl IN $statmap_labels)
              OPTIONAL MATCH (m)-[]-(d)
              WHERE any(lbl IN labels(d) WHERE lbl IN $dataset_labels)
              WITH d
              WHERE d IS NOT NULL
              RETURN collect(DISTINCT coalesce(d.id, elementId(d))) AS map_ids
            }
            WITH coalesce(n.id, elementId(n)) AS id,
                 direct_ids,
                 paper_ids,
                 study_ids,
                 task_ids,
                 map_ids,
                 direct_ids + paper_ids + study_ids + task_ids + map_ids AS all_ids
            UNWIND CASE WHEN size(all_ids) = 0 THEN [NULL] ELSE all_ids END AS dataset_id
            WITH id,
                 direct_ids,
                 paper_ids,
                 study_ids,
                 task_ids,
                 map_ids,
                 collect(DISTINCT dataset_id) AS dedup_ids
            RETURN id,
                   size([x IN dedup_ids WHERE x IS NOT NULL]) AS mediated_dataset_candidates,
                   size([x IN direct_ids WHERE x IS NOT NULL]) AS direct_dataset_candidates,
                   size([x IN paper_ids WHERE x IS NOT NULL]) AS via_paper_dataset_candidates,
                   size([x IN study_ids WHERE x IS NOT NULL]) AS via_study_dataset_candidates,
                   size([x IN task_ids WHERE x IS NOT NULL]) AS via_task_dataset_candidates,
                   size([x IN map_ids WHERE x IS NOT NULL]) AS via_statmap_dataset_candidates
            """,
            {
                "entity_ids": batch,
                "seed_labels": ONVOC_CONCEPT_LABELS,
                "scheme_filter": scheme_filter,
                "dataset_labels": DATASET_LABELS,
                "paper_labels": PAPER_LABELS,
                "study_labels": STUDY_LABELS,
                "task_labels": TASK_LABELS,
                "statmap_labels": STATMAP_LABELS,
            },
            database=database,
            query_timeout_s=query_timeout_s,
            retries=retries,
            backoff_base=backoff_base,
        )
        for row in rows:
            concept_id = str(row.get("id") or "").strip()
            if not concept_id:
                continue
            counts[concept_id] = {
                "mediated_dataset_candidates": _safe_int(
                    row.get("mediated_dataset_candidates")
                ),
                "direct_dataset_candidates": _safe_int(row.get("direct_dataset_candidates")),
                "via_paper_dataset_candidates": _safe_int(
                    row.get("via_paper_dataset_candidates")
                ),
                "via_study_dataset_candidates": _safe_int(
                    row.get("via_study_dataset_candidates")
                ),
                "via_task_dataset_candidates": _safe_int(
                    row.get("via_task_dataset_candidates")
                ),
                "via_statmap_dataset_candidates": _safe_int(
                    row.get("via_statmap_dataset_candidates")
                ),
            }

    return counts


def load_alias_info(path: Path) -> dict[str, AliasInfo]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    raw_map = payload.get("concept_aliases")
    if not isinstance(raw_map, dict):
        return {}

    out: dict[str, AliasInfo] = {}
    for concept_id, node in raw_map.items():
        if not isinstance(node, dict):
            continue
        aliases_raw = node.get("aliases")
        acronyms_raw = node.get("acronyms")

        aliases_seen: set[str] = set()
        aliases: list[str] = []
        for value in aliases_raw if isinstance(aliases_raw, list) else []:
            normalized = _normalize_alias(value)
            if normalized and normalized not in aliases_seen:
                aliases_seen.add(normalized)
                aliases.append(normalized)

        acronyms_seen: set[str] = set()
        acronyms: list[str] = []
        for value in acronyms_raw if isinstance(acronyms_raw, list) else []:
            normalized = _normalize_acronym(value)
            if normalized and normalized not in acronyms_seen:
                acronyms_seen.add(normalized)
                acronyms.append(normalized)

        out[str(concept_id)] = AliasInfo(aliases=aliases, acronyms=acronyms)
    return out


def _clinical_bucket(node: DiseaseNode, root_id: str) -> tuple[int, str]:
    if node.concept_id == root_id:
        return 2, "root"
    if node.child_count > 0:
        return 1, "taxonomy_internal"
    return 0, "clinical_leaf"


def _alias_coverage_label(alias_count: int, acronym_count: int) -> str:
    if alias_count > 0 and acronym_count > 0:
        return "aliases_and_acronyms"
    if alias_count > 0:
        return "aliases_only"
    if acronym_count > 0:
        return "acronyms_only"
    return "none"


def _build_gap_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row["summary_status"] != "OK":
        reasons.append("summary_unavailable")
        return reasons

    if row["summary_datasets"] == 0:
        if row["mediated_dataset_candidates"] > 0:
            reasons.append("summary_missing_mediated_datasets")
        else:
            reasons.append("no_dataset_links")
    elif row["summary_datasets"] < row["mediated_dataset_candidates"]:
        reasons.append("summary_below_mediated_candidates")

    if row["list_present"] and row["list_datasets"] < row["summary_datasets"]:
        reasons.append("entity_list_dataset_undercount")
    if not row["list_present"]:
        reasons.append("missing_from_entities_endpoint")

    if row["summary_datasets"] == 0 and row["alias_coverage"] == "none":
        reasons.append("no_alias_or_acronym_override")
    elif row["summary_datasets"] == 0 and row["alias_coverage"] in {
        "aliases_only",
        "acronyms_only",
    }:
        reasons.append("partial_alias_or_acronym_override")

    return reasons


def _gap_score(row: dict[str, Any]) -> int:
    reasons = set(row.get("gap_reasons") or [])
    score = 0
    if "summary_unavailable" in reasons:
        score += 120

    if "summary_missing_mediated_datasets" in reasons:
        score += 100
        score += min(40, row["mediated_dataset_candidates"] * 4)

    if "no_dataset_links" in reasons:
        score += 70
        signal = 0
        signal += min(12, row["summary_papers"] // 20)
        signal += min(8, row["summary_tasks"] * 2)
        signal += min(8, row["summary_statmaps"] * 2)
        score += signal

    if "summary_below_mediated_candidates" in reasons:
        delta = max(0, row["mediated_dataset_candidates"] - row["summary_datasets"])
        score += 60 + min(30, delta * 5)

    if "entity_list_dataset_undercount" in reasons:
        delta = max(0, row["summary_datasets"] - row["list_datasets"])
        score += 40 + min(20, delta * 3)

    if "missing_from_entities_endpoint" in reasons:
        score += 20

    if "no_alias_or_acronym_override" in reasons:
        score += 15
    elif "partial_alias_or_acronym_override" in reasons:
        score += 8
    return score


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank",
        "concept_id",
        "label",
        "clinical_priority",
        "depth",
        "parent_count",
        "child_count",
        "gap_score",
        "gap_reasons",
        "summary_status",
        "summary_datasets",
        "summary_papers",
        "summary_tasks",
        "summary_statmaps",
        "summary_total_evidence",
        "mediated_dataset_candidates",
        "direct_dataset_candidates",
        "via_paper_dataset_candidates",
        "via_study_dataset_candidates",
        "via_task_dataset_candidates",
        "via_statmap_dataset_candidates",
        "list_present",
        "list_datasets",
        "list_connected_score",
        "alias_count",
        "acronym_count",
        "alias_coverage",
        "aliases_sample",
        "acronyms_sample",
        "summary_error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_markdown(path: Path, report: dict[str, Any], top_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Disease Linkage Gap Audit",
        "",
        f"- Generated (UTC): `{report['generated_at']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Root concept: `{report['root_id']}`",
        f"- Subtree concepts scanned: `{summary['subtree_concepts']}`",
        f"- Entities endpoint rows: `{summary['entities_endpoint_rows']}`",
        f"- Summaries OK: `{summary['summary_ok']}`",
        f"- Summaries missing: `{summary['summary_missing']}`",
        f"- Summaries errors: `{summary['summary_error']}`",
        f"- Ranked gaps: `{summary['ranked_gaps']}`",
        "",
        "## Top Ranked Gaps",
        "",
        "| rank | concept_id | label | clinical_priority | gap_score | reasons | summary_datasets | mediated_candidates | list_datasets | alias_coverage |",
        "| ---: | --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]

    if not top_rows:
        lines.append("|  | (none) |  |  |  |  |  |  |  |  |")
    else:
        for row in top_rows:
            lines.append(
                "| "
                f"{row['rank']} | {row['concept_id']} | {row['label']} | "
                f"{row['clinical_priority']} | {row['gap_score']} | "
                f"{row['gap_reasons']} | {row['summary_datasets']} | "
                f"{row['mediated_dataset_candidates']} | {row['list_datasets']} | "
                f"{row['alias_coverage']} |"
            )

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    repo_root = _find_repo_root(Path(__file__).resolve().parent)
    default_base_url = (
        _env(repo_root, "BR_KG_API_URL")
        or _env(repo_root, "PUBLIC_BR_KG_URL")
        or "https://brain-researcher.com/kg"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=default_base_url,
        help="Base URL for disease lens endpoints.",
    )
    parser.add_argument(
        "--root-id",
        default="ONVOC_0000003",
        help="ONVOC disease root concept id.",
    )
    parser.add_argument(
        "--entities-limit",
        type=int,
        default=2000,
        help="Limit for /api/kg/lens/disease/entities endpoint.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Top-N rows for markdown summary (default: 20).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Neo4j batch size for mediated candidate counting.",
    )
    parser.add_argument(
        "--summary-workers",
        type=int,
        default=12,
        help="Concurrent workers for summary endpoint calls.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds for HTTP and Neo4j queries.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry count for transient HTTP and Neo4j failures.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=0.35,
        help="Exponential retry backoff base in seconds.",
    )
    parser.add_argument(
        "--neo4j-uri",
        default=_env(repo_root, "NEO4J_URI"),
        help="Neo4j URI (defaults to env/.env).",
    )
    parser.add_argument(
        "--neo4j-user",
        default=_env(repo_root, "NEO4J_USER"),
        help="Neo4j username (defaults to env/.env).",
    )
    parser.add_argument(
        "--neo4j-password",
        default=_env(repo_root, "NEO4J_PASSWORD"),
        help="Neo4j password (defaults to env/.env).",
    )
    parser.add_argument(
        "--neo4j-database",
        default=_env(repo_root, "NEO4J_DATABASE", "neo4j"),
        help="Neo4j database name.",
    )
    parser.add_argument(
        "--alias-map",
        default="configs/legacy/mappings/disease_alias_overrides.yaml",
        help="Alias/acronym override YAML path.",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/audits",
        help="Output directory for audit reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.neo4j_uri or not args.neo4j_user or args.neo4j_password is None:
        raise RuntimeError(
            "Missing Neo4j config. Provide --neo4j-uri/--neo4j-user/--neo4j-password "
            "or set NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD."
        )
    if args.top_n <= 0:
        raise ValueError("--top-n must be > 0")

    scheme_filter = "ONVOC"
    timeout_s = max(1.0, float(args.timeout))
    retries = max(0, int(args.retries))
    backoff_base = max(0.0, float(args.retry_backoff))

    driver = GraphDatabase.driver(
        args.neo4j_uri,
        auth=(args.neo4j_user, args.neo4j_password),
        connection_timeout=timeout_s,
    )

    try:
        subtree_nodes = load_disease_subtree(
            driver,
            database=args.neo4j_database,
            root_id=args.root_id,
            scheme_filter=scheme_filter,
            query_timeout_s=timeout_s,
            retries=retries,
            backoff_base=backoff_base,
        )
        if not subtree_nodes:
            raise RuntimeError(
                f"no disease concepts found under root {args.root_id} in Neo4j"
            )

        concept_ids = [node.concept_id for node in subtree_nodes]
        entities_payload = load_disease_entities_from_api(
            base_url=args.base_url,
            limit=max(1, int(args.entities_limit)),
            timeout_s=timeout_s,
            retries=retries,
            backoff_base=backoff_base,
        )
        summaries = load_summaries(
            base_url=args.base_url,
            concept_ids=concept_ids,
            timeout_s=timeout_s,
            retries=retries,
            backoff_base=backoff_base,
            workers=max(1, int(args.summary_workers)),
        )
        mediated_counts = load_mediated_dataset_candidate_counts(
            driver,
            database=args.neo4j_database,
            concept_ids=concept_ids,
            scheme_filter=scheme_filter,
            batch_size=max(1, int(args.batch_size)),
            query_timeout_s=timeout_s,
            retries=retries,
            backoff_base=backoff_base,
        )
    finally:
        driver.close()

    alias_map = load_alias_info(Path(args.alias_map))

    rows: list[dict[str, Any]] = []
    for node in subtree_nodes:
        summary = summaries.get(
            node.concept_id,
            SummaryInfo(
                status="ERROR",
                label=node.label,
                features={key: 0 for key in FEATURE_KEYS},
                ontology_parents=0,
                ontology_children=0,
                error="missing summary payload",
            ),
        )
        list_row = entities_payload.get(node.concept_id)
        list_present = list_row is not None

        alias_info = alias_map.get(node.concept_id, AliasInfo(aliases=[], acronyms=[]))
        alias_count = len(alias_info.aliases)
        acronym_count = len(alias_info.acronyms)
        alias_coverage = _alias_coverage_label(alias_count, acronym_count)

        counts = mediated_counts.get(
            node.concept_id,
            {
                "mediated_dataset_candidates": 0,
                "direct_dataset_candidates": 0,
                "via_paper_dataset_candidates": 0,
                "via_study_dataset_candidates": 0,
                "via_task_dataset_candidates": 0,
                "via_statmap_dataset_candidates": 0,
            },
        )
        clinical_bucket, clinical_priority = _clinical_bucket(node, args.root_id)
        summary_total_evidence = sum(
            _safe_int(summary.features.get(key)) for key in FEATURE_KEYS
        )

        row = {
            "concept_id": node.concept_id,
            "label": summary.label or node.label,
            "clinical_bucket": clinical_bucket,
            "clinical_priority": clinical_priority,
            "depth": node.depth,
            "parent_count": node.parent_count,
            "child_count": node.child_count,
            "summary_status": summary.status,
            "summary_error": summary.error,
            "summary_datasets": _safe_int(summary.features.get("datasets")),
            "summary_papers": _safe_int(summary.features.get("papers")),
            "summary_tasks": _safe_int(summary.features.get("tasks")),
            "summary_statmaps": _safe_int(summary.features.get("statmaps")),
            "summary_total_evidence": summary_total_evidence,
            "ontology_parents": summary.ontology_parents,
            "ontology_children": summary.ontology_children,
            "list_present": list_present,
            "list_datasets": _safe_int((list_row or {}).get("datasets")),
            "list_connected_score": _safe_int((list_row or {}).get("connected_score")),
            "alias_count": alias_count,
            "acronym_count": acronym_count,
            "alias_coverage": alias_coverage,
            "aliases_sample": ";".join(alias_info.aliases[:5]),
            "acronyms_sample": ";".join(alias_info.acronyms[:5]),
            **counts,
        }
        row["gap_reasons"] = _build_gap_reasons(row)
        row["gap_score"] = _gap_score(row)
        rows.append(row)

    ranked = [
        row
        for row in rows
        if row["gap_reasons"]
    ]
    ranked.sort(
        key=lambda row: (
            row["clinical_bucket"],
            -row["gap_score"],
            -row["mediated_dataset_candidates"],
            -row["summary_papers"],
            row["label"].lower(),
            row["concept_id"],
        )
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        row["gap_reasons"] = ",".join(row["gap_reasons"])

    top_rows = ranked[: args.top_n]
    generated_at = dt.datetime.now(dt.timezone.utc)
    stamp = generated_at.strftime("%Y%m%d_%H%M%SZ")

    summary_ok = sum(1 for row in rows if row["summary_status"] == "OK")
    summary_missing = sum(1 for row in rows if row["summary_status"] == "MISSING")
    summary_error = sum(1 for row in rows if row["summary_status"] == "ERROR")
    report = {
        "generated_at": generated_at.isoformat(),
        "base_url": args.base_url.rstrip("/"),
        "root_id": args.root_id,
        "inputs": {
            "entities_limit": int(args.entities_limit),
            "top_n": int(args.top_n),
            "batch_size": int(args.batch_size),
            "summary_workers": int(args.summary_workers),
            "timeout_seconds": timeout_s,
            "retries": retries,
            "retry_backoff": backoff_base,
            "alias_map": str(args.alias_map),
            "neo4j_database": args.neo4j_database,
        },
        "summary": {
            "subtree_concepts": len(rows),
            "entities_endpoint_rows": len(entities_payload),
            "summary_ok": summary_ok,
            "summary_missing": summary_missing,
            "summary_error": summary_error,
            "ranked_gaps": len(ranked),
            "clinical_leaf_gaps": sum(
                1 for row in ranked if row["clinical_priority"] == "clinical_leaf"
            ),
            "taxonomy_internal_gaps": sum(
                1 for row in ranked if row["clinical_priority"] == "taxonomy_internal"
            ),
            "root_gaps": sum(1 for row in ranked if row["clinical_priority"] == "root"),
            "summary_dataset_zero": sum(1 for row in rows if row["summary_datasets"] == 0),
            "entity_list_dataset_undercount": sum(
                1
                for row in rows
                if row["list_present"] and row["list_datasets"] < row["summary_datasets"]
            ),
        },
        "top_ranked_gaps": top_rows,
        "ranked_gaps": ranked,
    }

    out_dir = Path(args.out_dir)
    json_path = out_dir / f"disease_linkage_gap_audit_{stamp}.json"
    csv_path = out_dir / f"disease_linkage_gap_audit_{stamp}.csv"
    md_path = out_dir / f"disease_linkage_gap_audit_{stamp}.md"

    _write_json(json_path, report)
    _write_csv(csv_path, ranked)
    _write_markdown(md_path, report, top_rows)

    print(
        json.dumps(
            {
                "status": "ok",
                "subtree_concepts": len(rows),
                "ranked_gaps": len(ranked),
                "top_n": len(top_rows),
                "outputs": {
                    "json": str(json_path),
                    "csv": str(csv_path),
                    "markdown": str(md_path),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
