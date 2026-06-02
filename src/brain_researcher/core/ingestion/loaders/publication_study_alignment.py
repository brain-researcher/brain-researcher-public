"""Helpers for aligning Publication nodes to Study nodes.

The linker is intentionally conservative: it only creates an alignment when a
Publication resolves to exactly one Study through DOI, then PMID, then a
normalized URL match. No fuzzy matching is used.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

PUBLICATION_LABEL = "Publication"
STUDY_LABEL = "Study"
ALIGNMENT_REL = "ALIGNS_WITH"

METHOD_CONFIDENCE = {"doi_exact": 1.0, "pmid_exact": 1.0, "url_exact": 1.0}

DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
PMID_RE = re.compile(r"(?:pmid[:\s]*|pubmed/)(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class _Resolution:
    study_id: str
    method: str
    matched_value: str


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


def _canonical_doi_url(doi: str) -> str:
    doi = _normalize_doi(doi)
    return f"https://doi.org/{doi}" if doi else ""


def _canonical_pubmed_url(pmid: str) -> str:
    pmid = _normalize_pmid(pmid)
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""


def _looks_like_doi(value: Any) -> bool:
    text = _normalize_whitespace(value).lower()
    if not text:
        return False
    if DOI_RE.search(text):
        return True
    return text.startswith(
        (
            "doi:",
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
            "https://www.doi.org/",
            "http://www.doi.org/",
        )
    )


def _looks_like_pmid(value: Any) -> bool:
    text = _normalize_whitespace(value).lower()
    if not text:
        return False
    return bool(text.isdigit() or "pmid" in text or "pubmed" in text)


def _looks_like_url(value: Any) -> bool:
    text = _normalize_whitespace(value).lower()
    return text.startswith(("http://", "https://"))


def _get_node(db: Any, node_id: str) -> dict[str, Any] | None:
    if hasattr(db, "get_node"):
        node = db.get_node(node_id)
        if node is not None:
            return dict(node)

    matches = db.find_nodes(properties={"id": node_id})
    if matches:
        return dict(matches[0][1])
    return None


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _is_supported_publication(node_id: str, props: dict[str, Any]) -> bool:
    label_hint = _normalize_whitespace(props.get("source")).lower()
    if label_hint in {"pubmed", "scholarly_metadata", "pubmed_api", "openneuro"}:
        return True
    return node_id.startswith(("pmid:", "doi:", "paper:")) or bool(
        _normalize_whitespace(props.get("doi") or props.get("pmid") or props.get("url"))
    )


class _NodeIndex:
    def __init__(self) -> None:
        self._by_key: dict[str, set[str]] = defaultdict(set)

    @classmethod
    def from_db(cls, db: Any, label: str) -> _NodeIndex:
        index = cls()
        for node_id, props in db.find_nodes(label):
            index.add(str(node_id), dict(props))
        return index

    def add(self, node_id: str, props: dict[str, Any]) -> None:
        self._register(node_id, node_id)
        for field in (
            "id",
            "doi",
            "pmid",
            "url",
            "primary_url",
            "source_url",
            "title",
            "name",
            "label",
            "reference",
        ):
            self._register_field(node_id, field, props.get(field))

    def _register_field(self, node_id: str, field: str, value: Any) -> None:
        text = _normalize_whitespace(value)
        if not text:
            return
        pattern_fields = {"id", "title", "name", "label", "reference"}
        if field == "doi" or (field in pattern_fields and _looks_like_doi(text)):
            doi = _normalize_doi(text)
            if doi:
                self._register(node_id, doi)
                self._register(node_id, _canonical_doi_url(doi))
        if field == "pmid" or (field in pattern_fields and _looks_like_pmid(text)):
            pmid = _normalize_pmid(text)
            if pmid:
                self._register(node_id, pmid)
                self._register(node_id, _canonical_pubmed_url(pmid))
        if field in {"url", "primary_url", "source_url"} or (
            field in pattern_fields and _looks_like_url(text)
        ):
            url = _normalize_url(text)
            if url:
                self._register(node_id, url)

    def _register(self, node_id: str, value: Any) -> None:
        text = _normalize_whitespace(value)
        if text:
            self._by_key[text.lower()].add(node_id)

    def lookup(self, value: Any) -> set[str]:
        candidate = _normalize_whitespace(value)
        if not candidate:
            return set()
        key = candidate.lower()
        return set(self._by_key.get(key, set()))


class PublicationStudyAlignmentLinker:
    """Link Publication nodes to Study nodes via exact identifiers."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._study_index = _NodeIndex.from_db(db, STUDY_LABEL)

    def link_publications(
        self,
        publication_ids: Iterable[str] | None = None,
        *,
        limit: int | None = None,
    ) -> dict[str, int]:
        if hasattr(type(self.db), "_run"):
            return self._link_publications_bulk(
                publication_ids=publication_ids, limit=limit
            )

        stats = Counter(
            {
                "publications_seen": 0,
                "publications_with_alignment": 0,
                "doi_candidates": 0,
                "doi_matched": 0,
                "doi_unresolved": 0,
                "doi_ambiguous": 0,
                "pmid_candidates": 0,
                "pmid_matched": 0,
                "pmid_unresolved": 0,
                "pmid_ambiguous": 0,
                "url_candidates": 0,
                "url_matched": 0,
                "url_unresolved": 0,
                "url_ambiguous": 0,
                "alignment_edges_created": 0,
                "alignment_edges_existing": 0,
            }
        )

        publications = list(
            self._iter_publications(publication_ids=publication_ids, limit=limit)
        )
        for publication_id, publication in publications:
            stats["publications_seen"] += 1

            resolution = self._resolve_publication(publication, stats)
            if resolution is None:
                continue

            if self._ensure_alignment(
                publication_id,
                resolution.study_id,
                resolution.method,
                resolution.matched_value,
                publication,
            ):
                stats["alignment_edges_created"] += 1
            else:
                stats["alignment_edges_existing"] += 1

            stats["publications_with_alignment"] += 1

        return dict(stats)

    def _resolve_publication(
        self, publication: dict[str, Any], stats: Counter[str]
    ) -> _Resolution | None:
        groups = (
            ("doi", "doi_exact", ("doi", "id", "title", "name", "label")),
            ("pmid", "pmid_exact", ("pmid", "id", "title", "name", "label")),
            (
                "url",
                "url_exact",
                ("url", "primary_url", "source_url", "id", "title", "name", "label"),
            ),
        )

        for field_name, method, fields in groups:
            candidates: list[str] = []
            for field in fields:
                candidates.extend(
                    self._normalize_candidates(
                        field_name, field, publication.get(field)
                    )
                )
            candidates = _dedupe(candidates)
            if not candidates:
                continue

            stats[f"{field_name}_candidates"] += len(candidates)
            unique_study_ids: set[str] = set()
            matched_value = ""
            saw_ambiguous = False

            for candidate in candidates:
                node_ids = self._study_index.lookup(candidate)
                if not node_ids:
                    continue
                if len(node_ids) > 1:
                    saw_ambiguous = True
                    continue
                unique_study_ids.update(node_ids)
                matched_value = candidate

            if len(unique_study_ids) == 1:
                stats[f"{field_name}_matched"] += 1
                return _Resolution(next(iter(unique_study_ids)), method, matched_value)

            if len(unique_study_ids) > 1 or saw_ambiguous:
                stats[f"{field_name}_ambiguous"] += 1
            else:
                stats[f"{field_name}_unresolved"] += 1

        return None

    def _normalize_candidates(
        self, field_name: str, source_field: str, value: Any
    ) -> list[str]:
        text = _normalize_whitespace(value)
        if not text:
            return []

        if field_name == "doi":
            if source_field != "doi" and not _looks_like_doi(text):
                return []
            doi = _normalize_doi(text)
            return [doi] if doi else []
        if field_name == "pmid":
            if source_field != "pmid" and not _looks_like_pmid(text):
                return []
            pmid = _normalize_pmid(text)
            return [pmid] if pmid else []

        if source_field not in {
            "url",
            "primary_url",
            "source_url",
        } and not _looks_like_url(text):
            return []
        url = _normalize_url(text)
        return [url] if url else []

    def _ensure_alignment(
        self,
        publication_id: str,
        study_id: str,
        method: str,
        matched_value: str,
        publication: dict[str, Any],
    ) -> bool:
        existing = self.db.find_relationships(
            start_node=publication_id, end_node=study_id, rel_type=ALIGNMENT_REL
        )
        if existing:
            return False

        source = _normalize_whitespace(publication.get("source")).lower()
        if not source:
            source = "scholarly_metadata"

        props = {
            "source": source,
            "method": method,
            "methods": [method],
            "confidence": METHOD_CONFIDENCE[method],
            "confidence_tier": "imported",
            "match_field": method.split("_", 1)[0],
            "match_value": matched_value,
        }
        return bool(
            self.db.create_relationship(publication_id, study_id, ALIGNMENT_REL, props)
        )

    def _link_publications_bulk(
        self,
        *,
        publication_ids: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, int]:
        publication_id_list = [str(value) for value in (publication_ids or []) if value]
        params = {
            "publication_ids": publication_id_list,
            "use_filter": bool(publication_id_list),
            "limit": None if limit is None else max(0, int(limit)),
        }

        study_rows = [
            dict(row)
            for row in self.db._run(
                "MATCH (s:Study) RETURN s.id AS node_id, properties(s) AS props"
            )
        ]
        study_index = _NodeIndex()
        for row in study_rows:
            study_index.add(str(row["node_id"]), dict(row["props"] or {}))
        self._study_index = study_index

        publication_rows = [
            dict(row)
            for row in self.db._run(
                """
                MATCH (p:Publication)
                WHERE (NOT $use_filter OR p.id IN $publication_ids)
                RETURN p.id AS node_id, properties(p) AS props
                ORDER BY p.id
                LIMIT coalesce($limit, 1000000)
                """,
                params,
            )
        ]

        stats = Counter(
            {
                "publications_seen": 0,
                "publications_with_alignment": 0,
                "doi_candidates": 0,
                "doi_matched": 0,
                "doi_unresolved": 0,
                "doi_ambiguous": 0,
                "pmid_candidates": 0,
                "pmid_matched": 0,
                "pmid_unresolved": 0,
                "pmid_ambiguous": 0,
                "url_candidates": 0,
                "url_matched": 0,
                "url_unresolved": 0,
                "url_ambiguous": 0,
                "alignment_edges_created": 0,
                "alignment_edges_existing": 0,
            }
        )
        link_rows: list[dict[str, Any]] = []

        for row in publication_rows:
            publication_id = str(row["node_id"])
            publication = dict(row.get("props") or {})
            stats["publications_seen"] += 1
            resolution = self._resolve_publication(publication, stats)
            if resolution is None:
                continue

            source = _normalize_whitespace(publication.get("source")).lower()
            if not source:
                source = "scholarly_metadata"

            link_rows.append(
                {
                    "publication_id": publication_id,
                    "study_id": resolution.study_id,
                    "props": {
                        "source": source,
                        "method": resolution.method,
                        "methods": [resolution.method],
                        "confidence": METHOD_CONFIDENCE[resolution.method],
                        "confidence_tier": "imported",
                        "match_field": resolution.method.split("_", 1)[0],
                        "match_value": resolution.matched_value,
                    },
                }
            )
            stats["publications_with_alignment"] += 1

        if not link_rows:
            return dict(stats)

        existing = self.db._run(
            """
            UNWIND $rows AS row
            OPTIONAL MATCH (:Publication {id: row.publication_id})-[r:ALIGNS_WITH]->(:Study {id: row.study_id})
            RETURN count(r) AS existing
            """,
            {"rows": link_rows},
        ).single()
        existing_count = int(
            existing["existing"]
            if existing and existing.get("existing") is not None
            else 0
        )

        self.db._run(
            """
            UNWIND $rows AS row
            MATCH (p:Publication {id: row.publication_id})
            MATCH (s:Study {id: row.study_id})
            MERGE (p)-[r:ALIGNS_WITH]->(s)
            SET r += row.props
            RETURN count(r) AS total
            """,
            {"rows": link_rows},
        ).consume()

        stats["alignment_edges_existing"] = existing_count
        stats["alignment_edges_created"] = max(0, len(link_rows) - existing_count)
        return dict(stats)

    def _iter_publications(
        self,
        *,
        publication_ids: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        if publication_ids is None:
            nodes = sorted(
                self.db.find_nodes(PUBLICATION_LABEL), key=lambda item: item[0]
            )
            count = 0
            for node_id, props in nodes:
                if not _is_supported_publication(node_id, dict(props)):
                    continue
                if limit is not None and count >= max(0, int(limit)):
                    break
                count += 1
                yield str(node_id), dict(props)
            return

        count = 0
        for publication_id in publication_ids:
            if limit is not None and count >= limit:
                break
            node = _get_node(self.db, str(publication_id))
            if node is None:
                continue
            if not _is_supported_publication(str(publication_id), node):
                continue
            count += 1
            yield str(publication_id), node


def link_publication_study_alignments(
    db: Any,
    publication_ids: Iterable[str] | None = None,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    """Convenience wrapper for backfills and ingestion hooks."""

    return PublicationStudyAlignmentLinker(db).link_publications(
        publication_ids=publication_ids, limit=limit
    )
