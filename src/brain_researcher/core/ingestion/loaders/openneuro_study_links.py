"""Helpers for linking OpenNeuro datasets to existing Study nodes.

The linker is intentionally db-agnostic and only relies on the small graph
surface used by both the in-memory fake backend and the Neo4j adapter:
`find_nodes`, `find_relationships`, `create_relationship`, and `get_node`.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

DATASET_LABEL = "Dataset"
TASKSPEC_LABEL = "TaskSpec"
STUDY_LABEL = "Study"
PUBLICATION_LABELS = ("Publication", "Study")

DATASET_TASK_REL = "HAS_TASK"
DATASET_PUBLICATION_REL = "CITED_BY"
DATASET_STUDY_REL = "CITED_BY"

METHOD_PRIORITY = {
    "taskspec_cite_links": 3,
    "publication_bridge": 2,
    "dataset_fallback": 1,
}
METHOD_CONFIDENCE = {
    "taskspec_cite_links": 0.95,
    "publication_bridge": 0.9,
    "dataset_fallback": 0.75,
}

DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
PMID_RE = re.compile(r"(?:pmid[:\s]*|pubmed/)(\d+)", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"<>()]+", re.IGNORECASE)


@dataclass(frozen=True)
class _Resolution:
    study_id: str
    method: str


def _normalize_whitespace(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_doi(value: Any) -> str:
    text = _normalize_whitespace(value).lower()
    if not text:
        return ""
    text = re.sub(r"^(doi:\s*)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^https?://(dx\.)?doi\.org/?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^https?://www\.doi\.org/?", "", text, flags=re.IGNORECASE)
    return text.strip(" .;,)")


def _normalize_pmid(value: Any) -> str:
    text = _normalize_whitespace(value)
    if not text:
        return ""
    match = PMID_RE.search(text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    return ""


def _normalize_url(value: Any) -> str:
    text = _normalize_whitespace(value).lower()
    if not text:
        return ""
    return text.strip(" .;,)")


def _candidate_strings(value: Any) -> list[str]:
    text = _normalize_whitespace(value)
    if not text:
        return []
    candidates: list[str] = []

    doi = _normalize_doi(text)
    if doi:
        candidates.append(doi)

    pmid = _normalize_pmid(text)
    if pmid:
        candidates.append(pmid)

    url = _normalize_url(text)
    if url and url not in candidates:
        candidates.append(url)

    lowered = text.lower()
    if lowered and lowered not in candidates:
        candidates.append(lowered)

    return candidates


def _extract_candidates_from_blob(blob: Any) -> list[str]:
    text = _normalize_whitespace(blob)
    if not text:
        return []
    candidates: list[str] = []

    for match in DOI_RE.findall(text):
        candidate = _normalize_doi(match)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for match in PMID_RE.findall(text):
        candidate = _normalize_pmid(match)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for match in URL_RE.findall(text):
        candidate = _normalize_url(match)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    return candidates


def _get_node(db: Any, node_id: str) -> dict[str, Any] | None:
    if hasattr(db, "get_node"):
        node = db.get_node(node_id)
        if node is not None:
            return dict(node)

    matches = db.find_nodes(properties={"id": node_id})
    if matches:
        return dict(matches[0][1])
    return None


class _StudyIndex:
    def __init__(self) -> None:
        self._by_key: dict[str, set[str]] = {}

    @classmethod
    def from_db(cls, db: Any) -> _StudyIndex:
        index = cls()
        for study_id, props in db.find_nodes(STUDY_LABEL):
            index.add(study_id, props)
        return index

    def add(self, study_id: str, props: dict[str, Any]) -> None:
        values = [
            study_id,
            props.get("id"),
            props.get("doi"),
            props.get("pmid"),
            props.get("title"),
            props.get("name"),
            props.get("url"),
            props.get("reference"),
            props.get("primary_url"),
            props.get("source_url"),
            props.get("source_version"),
        ]
        for value in values:
            self._add_value(study_id, value)

    def _add_value(self, study_id: str, value: Any) -> None:
        text = _normalize_whitespace(value)
        if not text:
            return

        keys = {
            _normalize_url(text),
            _normalize_doi(text),
            _normalize_pmid(text),
            text.lower(),
        }
        for key in keys:
            if not key:
                continue
            self._by_key.setdefault(key, set()).add(study_id)

    def resolve(self, value: Any) -> _Resolution | None:
        for candidate in _candidate_strings(value):
            study_ids = self._by_key.get(candidate, set())
            if len(study_ids) == 1:
                return _Resolution(next(iter(study_ids)), candidate)
        return None

    def is_ambiguous(self, value: Any) -> bool:
        for candidate in _candidate_strings(value):
            study_ids = self._by_key.get(candidate, set())
            if len(study_ids) > 1:
                return True
        return False


class OpenNeuroStudyLinker:
    """Link OpenNeuro datasets to existing Study nodes via stable identifiers."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._study_index = _StudyIndex.from_db(db)

    def link_datasets(
        self,
        dataset_ids: Iterable[str] | None = None,
        *,
        limit: int | None = None,
    ) -> dict[str, int]:
        if hasattr(type(self.db), "_run"):
            return self._link_datasets_bulk(dataset_ids=dataset_ids, limit=limit)

        stats = Counter(
            {
                "datasets_seen": 0,
                "datasets_with_study_links": 0,
                "cite_link_candidates": 0,
                "cite_links_matched": 0,
                "cite_links_unresolved": 0,
                "publication_candidates": 0,
                "publication_bridge_matched": 0,
                "publication_bridge_unresolved": 0,
                "dataset_fallback_candidates": 0,
                "dataset_fallback_matched": 0,
                "dataset_fallback_unresolved": 0,
                "study_links_created": 0,
                "study_links_existing": 0,
            }
        )
        datasets = list(self._iter_datasets(dataset_ids=dataset_ids, limit=limit))

        for dataset_id, dataset in datasets:
            stats["datasets_seen"] += 1
            linked_studies: set[str] = set()
            cite_hits: set[str] = set()
            publication_hits: set[str] = set()
            fallback_hits: set[str] = set()

            for cite_link in self._taskspec_cite_links(dataset_id):
                stats["cite_link_candidates"] += 1
                resolution = self._study_index.resolve(cite_link)
                if resolution is not None:
                    cite_hits.add(resolution.study_id)
                else:
                    stats["cite_links_unresolved"] += 1

            for publication in self._dataset_publications(dataset_id):
                stats["publication_candidates"] += 1
                publication_resolution = self._study_index.resolve(publication)
                if publication_resolution is not None:
                    publication_hits.add(publication_resolution.study_id)
                else:
                    stats["publication_bridge_unresolved"] += 1

            fallback_values = self._dataset_fallback_values(dataset)
            if fallback_values:
                stats["dataset_fallback_candidates"] += len(fallback_values)
            for fallback in fallback_values:
                resolution = self._study_index.resolve(fallback)
                if resolution is not None:
                    fallback_hits.add(resolution.study_id)
                else:
                    stats["dataset_fallback_unresolved"] += 1

            stats["cite_links_matched"] += len(cite_hits)
            stats["publication_bridge_matched"] += len(publication_hits)
            stats["dataset_fallback_matched"] += len(fallback_hits)

            linked_studies.update(cite_hits)
            linked_studies.update(publication_hits)
            linked_studies.update(fallback_hits)

            for study_id in sorted(linked_studies):
                if self._ensure_dataset_study_link(dataset_id, study_id):
                    stats["study_links_created"] += 1
                else:
                    stats["study_links_existing"] += 1

            if linked_studies:
                stats["datasets_with_study_links"] += 1

        return dict(stats)

    def _link_datasets_bulk(
        self,
        *,
        dataset_ids: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, int]:
        dataset_id_list = [str(value) for value in (dataset_ids or []) if value]
        params = {
            "dataset_ids": dataset_id_list,
            "use_filter": bool(dataset_id_list),
            "limit": None if limit is None else max(0, int(limit)),
        }

        study_rows = [
            dict(row)
            for row in self.db._run(
                "MATCH (s:Study) RETURN s.id AS id, properties(s) AS props"
            )
        ]
        dataset_rows = [
            dict(row)
            for row in self.db._run(
                """
                MATCH (d:Dataset)
                WHERE (
                  d.id STARTS WITH 'ds:openneuro:'
                  OR toLower(coalesce(d.source, '')) IN ['openneuro', 'openfmri']
                  OR toLower(coalesce(d.source_repo, '')) IN ['openneuro', 'openfmri']
                  OR toLower(coalesce(d.source_repo_id, d.dataset_id, '')) =~ 'ds[0-9]{3,}.*'
                )
                  AND (NOT $use_filter OR d.id IN $dataset_ids)
                RETURN d.id AS dataset_id, properties(d) AS props
                ORDER BY d.id
                LIMIT coalesce($limit, 1000000)
                """,
                params,
            )
        ]
        taskspec_rows = [
            dict(row)
            for row in self.db._run(
                """
                MATCH (d:Dataset)-[:HAS_TASK]->(t:TaskSpec)
                WHERE (
                  d.id STARTS WITH 'ds:openneuro:'
                  OR toLower(coalesce(d.source, '')) IN ['openneuro', 'openfmri']
                  OR toLower(coalesce(d.source_repo, '')) IN ['openneuro', 'openfmri']
                  OR toLower(coalesce(d.source_repo_id, d.dataset_id, '')) =~ 'ds[0-9]{3,}.*'
                )
                  AND (NOT $use_filter OR d.id IN $dataset_ids)
                RETURN d.id AS dataset_id, collect(coalesce(t.cite_links, [])) AS cite_link_lists
                """,
                params,
            )
        ]
        publication_rows = [
            dict(row)
            for row in self.db._run(
                """
                MATCH (d:Dataset)-[:CITED_BY]->(p:Publication)
                WHERE (
                  d.id STARTS WITH 'ds:openneuro:'
                  OR toLower(coalesce(d.source, '')) IN ['openneuro', 'openfmri']
                  OR toLower(coalesce(d.source_repo, '')) IN ['openneuro', 'openfmri']
                  OR toLower(coalesce(d.source_repo_id, d.dataset_id, '')) =~ 'ds[0-9]{3,}.*'
                )
                  AND (NOT $use_filter OR d.id IN $dataset_ids)
                RETURN d.id AS dataset_id, collect(properties(p)) AS publications
                """,
                params,
            )
        ]

        index = _StudyIndex()
        for row in study_rows:
            index.add(str(row["id"]), dict(row["props"] or {}))

        dataset_map = {
            str(row["dataset_id"]): dict(row["props"] or {}) for row in dataset_rows
        }
        taskspec_map = {
            str(row["dataset_id"]): row.get("cite_link_lists") or []
            for row in taskspec_rows
        }
        publication_map = {
            str(row["dataset_id"]): row.get("publications") or []
            for row in publication_rows
        }

        stats = Counter(
            {
                "datasets_seen": 0,
                "datasets_with_study_links": 0,
                "cite_link_candidates": 0,
                "cite_links_matched": 0,
                "cite_links_unresolved": 0,
                "publication_candidates": 0,
                "publication_bridge_matched": 0,
                "publication_bridge_unresolved": 0,
                "dataset_fallback_candidates": 0,
                "dataset_fallback_matched": 0,
                "dataset_fallback_unresolved": 0,
                "study_links_created": 0,
                "study_links_existing": 0,
            }
        )
        link_methods: dict[tuple[str, str], set[str]] = defaultdict(set)

        for dataset_id, dataset in dataset_map.items():
            stats["datasets_seen"] += 1
            linked_any = False

            seen_cites: list[str] = []
            for cite_list in taskspec_map.get(dataset_id, []):
                for cite in cite_list or []:
                    normalized = _normalize_whitespace(cite)
                    if normalized and normalized not in seen_cites:
                        seen_cites.append(normalized)

            for cite in seen_cites:
                stats["cite_link_candidates"] += 1
                resolution = index.resolve(cite)
                if resolution is None:
                    stats["cite_links_unresolved"] += 1
                    continue
                stats["cite_links_matched"] += 1
                link_methods[(dataset_id, resolution.study_id)].add(
                    "taskspec_cite_links"
                )
                linked_any = True

            for publication in publication_map.get(dataset_id, []):
                publication_values: list[str] = []
                for key in (
                    "doi",
                    "pmid",
                    "title",
                    "name",
                    "reference",
                    "url",
                    "primary_url",
                ):
                    value = _normalize_whitespace((publication or {}).get(key))
                    if value and value not in publication_values:
                        publication_values.append(value)

                for value in publication_values:
                    stats["publication_candidates"] += 1
                    resolution = index.resolve(value)
                    if resolution is None:
                        stats["publication_bridge_unresolved"] += 1
                        continue
                    stats["publication_bridge_matched"] += 1
                    link_methods[(dataset_id, resolution.study_id)].add(
                        "publication_bridge"
                    )
                    linked_any = True

            fallback_values: list[str] = []
            for field in (
                "description",
                "url",
                "primary_url",
                "source_url",
                "source_version",
                "title",
                "name",
            ):
                for candidate in _extract_candidates_from_blob(dataset.get(field)):
                    if candidate not in fallback_values:
                        fallback_values.append(candidate)
            stats["dataset_fallback_candidates"] += len(fallback_values)

            for value in fallback_values:
                resolution = index.resolve(value)
                if resolution is None:
                    stats["dataset_fallback_unresolved"] += 1
                    continue
                stats["dataset_fallback_matched"] += 1
                link_methods[(dataset_id, resolution.study_id)].add("dataset_fallback")
                linked_any = True

            if linked_any:
                stats["datasets_with_study_links"] += 1

        rows: list[dict[str, Any]] = []
        for (dataset_id, study_id), methods in sorted(link_methods.items()):
            methods_sorted = sorted(methods, key=lambda m: (-METHOD_PRIORITY[m], m))
            primary_method = methods_sorted[0]
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "study_id": study_id,
                    "method": primary_method,
                    "methods": methods_sorted,
                    "confidence": METHOD_CONFIDENCE[primary_method],
                }
            )

        if not rows:
            return dict(stats)

        existing = self.db._run(
            """
            UNWIND $rows AS row
            OPTIONAL MATCH (:Dataset {id: row.dataset_id})-[r:CITED_BY]->(:Study {id: row.study_id})
            RETURN count(r) AS existing
            """,
            {"rows": rows},
        ).single()
        existing_count = int(
            existing["existing"]
            if existing and existing.get("existing") is not None
            else 0
        )

        self.db._run(
            """
            UNWIND $rows AS row
            MATCH (d:Dataset {id: row.dataset_id})
            MATCH (s:Study {id: row.study_id})
            MERGE (d)-[r:CITED_BY]->(s)
            SET r.source = 'openneuro_study_linker',
                r.method = row.method,
                r.methods = row.methods,
                r.confidence = row.confidence,
                r.confidence_tier = 'imported'
            RETURN count(r) AS total
            """,
            {"rows": rows},
        ).consume()

        stats["study_links_existing"] = existing_count
        stats["study_links_created"] = max(0, len(rows) - existing_count)
        return dict(stats)

    def _iter_datasets(
        self,
        *,
        dataset_ids: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        if dataset_ids is None:
            nodes = sorted(self.db.find_nodes(DATASET_LABEL), key=lambda item: item[0])
            count = 0
            for node_id, props in nodes:
                if not self._is_openneuro_dataset(node_id, props):
                    continue
                if limit is not None and count >= max(0, int(limit)):
                    break
                count += 1
                yield node_id, dict(props)
            return

        count = 0
        for dataset_id in dataset_ids:
            if limit is not None and count >= limit:
                break
            node = _get_node(self.db, str(dataset_id))
            if node is None:
                continue
            if not self._is_openneuro_dataset(str(dataset_id), node):
                continue
            count += 1
            yield str(dataset_id), node

    def _is_openneuro_dataset(self, dataset_id: str, dataset: dict[str, Any]) -> bool:
        dataset_id_norm = _normalize_whitespace(dataset_id).lower()
        if dataset_id_norm.startswith("ds:openneuro:"):
            return True

        source = _normalize_whitespace(dataset.get("source")).lower()
        source_repo = _normalize_whitespace(dataset.get("source_repo")).lower()
        repo_id = _normalize_whitespace(
            dataset.get("source_repo_id") or dataset.get("dataset_id")
        ).lower()
        if source in {"openneuro", "openfmri"} or source_repo in {
            "openneuro",
            "openfmri",
        }:
            return True
        return bool(re.match(r"^ds\d{3,}", repo_id))

    def _taskspec_cite_links(self, dataset_id: str) -> list[str]:
        cite_links: list[str] = []
        for _, taskspec_id, _ in self.db.find_relationships(
            start_node=dataset_id, rel_type=DATASET_TASK_REL
        ):
            task_node = _get_node(self.db, taskspec_id)
            if not task_node:
                continue
            for cite_link in task_node.get("cite_links") or []:
                normalized = _normalize_whitespace(cite_link)
                if normalized and normalized not in cite_links:
                    cite_links.append(normalized)
        return cite_links

    def _dataset_publications(self, dataset_id: str) -> list[str]:
        publications: list[str] = []
        for _, target_id, _ in self.db.find_relationships(
            start_node=dataset_id, rel_type=DATASET_PUBLICATION_REL
        ):
            publication = _get_node(self.db, target_id)
            if not publication:
                continue
            raw_values = [
                _normalize_whitespace(value)
                for value in self._publication_values(publication)
                if _normalize_whitespace(value)
            ]
            for candidate in raw_values:
                if candidate not in publications:
                    publications.append(candidate)
        return publications

    def _publication_values(self, publication: dict[str, Any]) -> list[str]:
        return [
            publication.get("doi"),
            publication.get("pmid"),
            publication.get("title"),
            publication.get("name"),
            publication.get("reference"),
            publication.get("url"),
            publication.get("primary_url"),
        ]

    def _dataset_fallback_values(self, dataset: dict[str, Any]) -> list[str]:
        values = [
            dataset.get("description"),
            dataset.get("url"),
            dataset.get("primary_url"),
            dataset.get("source_url"),
            dataset.get("source_version"),
            dataset.get("title"),
            dataset.get("name"),
        ]
        candidates: list[str] = []
        for value in values:
            for candidate in _extract_candidates_from_blob(value):
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _ensure_dataset_study_link(self, dataset_id: str, study_id: str) -> bool:
        existing = self.db.find_relationships(
            start_node=dataset_id, end_node=study_id, rel_type=DATASET_STUDY_REL
        )
        if existing:
            return False
        return bool(
            self.db.create_relationship(
                dataset_id,
                study_id,
                DATASET_STUDY_REL,
                {
                    "source": "openneuro_study_linker",
                    "method": "dataset_study_linking",
                },
            )
        )


def link_openneuro_dataset_studies(
    db: Any,
    dataset_ids: Iterable[str] | None = None,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    """Convenience wrapper for live backfills."""

    return OpenNeuroStudyLinker(db).link_datasets(dataset_ids=dataset_ids, limit=limit)
