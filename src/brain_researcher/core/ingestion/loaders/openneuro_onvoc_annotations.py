"""Helpers for loading OpenNeuro ONVOC dataset annotation artifacts."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from brain_researcher.core.ingestion.loaders.onvoc_unified import OnvocUnifiedLoader

logger = logging.getLogger(__name__)


DEFAULT_ANNOTATIONS_PATH = Path(
    "data/ontologies/onvoc/datasets_openneuro_march18th.json"
)
DEFAULT_ONVOC_DIR = Path("data/ontologies/onvoc")

POSITIVE_ANNOTATION_FIELDS = ("keywords", "inclusionTerms")
NEGATIVE_ANNOTATION_FIELDS = ("exclusionTerms",)
ANNOTATION_FIELDS = POSITIVE_ANNOTATION_FIELDS + NEGATIVE_ANNOTATION_FIELDS

ONVOC_GRAPH_LABELS = ["ONVOC", "Concept", "OnvocClass", "OntologyConcept"]
POSITIVE_REL_TYPE = "HAS_ONVOC_ANNOTATION"
NEGATIVE_REL_TYPE = "EXCLUDES_ONVOC"
LEGACY_CONCEPT_LABELS = ["Concept", "LegacyOnvocTag"]
LEGACY_CONCEPT_PREFIX = "legacy_onvoc:"
LEGACY_CONCEPT_SCHEME = "ONVOC_LEGACY"
LEGACY_PUBLICATION_REL_TYPE = "DESCRIBES"


def normalize_onvoc_id(term_id: str | None) -> str | None:
    """Normalize legacy ONVOC identifiers to the graph's underscore form."""

    if not term_id:
        return None
    normalized = str(term_id).strip()
    if not normalized:
        return None
    if normalized.upper().startswith("ONVOC:"):
        return normalized.replace(":", "_", 1)
    return normalized


def legacy_onvoc_node_id(concept_id: str) -> str:
    """Return the graph node id used for legacy ONVOC labels."""

    return f"{LEGACY_CONCEPT_PREFIX}{concept_id}"


def canonical_openneuro_dataset_node_id(dataset_id: str) -> str:
    """Return the canonical Dataset node id used for OpenNeuro datasets."""

    return f"ds:openneuro:{dataset_id}"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


class OpenNeuroOnvocAnnotationLoader:
    """Loads and validates dataset-level ONVOC annotation exports."""

    def __init__(
        self,
        annotations_path: str | Path | None = None,
        onvoc_dir: str | Path | None = None,
    ) -> None:
        self.annotations_path = Path(annotations_path or DEFAULT_ANNOTATIONS_PATH)
        self.onvoc_dir = Path(onvoc_dir or DEFAULT_ONVOC_DIR)

    def _load_json(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(f"Required annotation artifact missing: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _normalize_terms(
        self, terms: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        normalized_terms: list[dict[str, Any]] = []
        for term in terms or []:
            raw_id = _clean_text(term.get("id"))
            concept_id = normalize_onvoc_id(raw_id)
            if not raw_id or not concept_id:
                continue
            normalized_terms.append(
                {
                    "raw_id": raw_id,
                    "concept_id": concept_id,
                    "label": _clean_text(term.get("label")),
                    "comment": _clean_text(term.get("comment")),
                    "text": _clean_text(term.get("text")),
                }
            )
        return normalized_terms

    def load_records(self) -> list[dict[str, Any]]:
        payload = self._load_json(self.annotations_path)
        if not isinstance(payload, list):
            raise ValueError(
                f"Annotation payload must be a list of records: {self.annotations_path}"
            )

        records: list[dict[str, Any]] = []
        for row in payload:
            dataset_id = _clean_text(row.get("id"))
            if not dataset_id:
                continue
            records.append(
                {
                    "dataset_id": dataset_id,
                    "accession_number": _clean_text(row.get("accessionNumber"))
                    or dataset_id,
                    "label": _clean_text(row.get("label")) or dataset_id,
                    "description": _clean_text(row.get("description")),
                    "authors": [
                        str(author) for author in (row.get("authors") or []) if author
                    ],
                    "doi": _clean_text(row.get("doi")),
                    "license": _clean_text(row.get("license")),
                    "keywords": self._normalize_terms(row.get("keywords")),
                    "inclusionTerms": self._normalize_terms(row.get("inclusionTerms")),
                    "exclusionTerms": self._normalize_terms(row.get("exclusionTerms")),
                    "keywordProvenance": row.get("keywordProvenance") or {},
                    "inclusionTermProvenance": row.get("inclusionTermProvenance") or {},
                    "exclusionTermProvenance": row.get("exclusionTermProvenance") or {},
                }
            )
        logger.info(
            "Loaded %d OpenNeuro ONVOC annotation records from %s",
            len(records),
            self.annotations_path,
        )
        return records

    def load_reference_concepts(self) -> dict[str, str]:
        concepts = OnvocUnifiedLoader(self.onvoc_dir).load_concepts()
        return {
            str(concept["id"]): _clean_text(concept.get("label"))
            for concept in concepts
            if concept.get("id")
        }

    def build_dataset_properties(self, record: dict[str, Any]) -> dict[str, Any]:
        keywords = record.get("keywords") or []
        inclusion_terms = record.get("inclusionTerms") or []
        exclusion_terms = record.get("exclusionTerms") or []

        keyword_ids = [term["concept_id"] for term in keywords]
        inclusion_ids = [term["concept_id"] for term in inclusion_terms]
        exclusion_ids = [term["concept_id"] for term in exclusion_terms]

        keyword_labels = [term["label"] for term in keywords if term.get("label")]
        inclusion_labels = [
            term["label"] for term in inclusion_terms if term.get("label")
        ]
        exclusion_labels = [
            term["label"] for term in exclusion_terms if term.get("label")
        ]

        return {
            "id": record["dataset_id"],
            "dataset_id": record["dataset_id"],
            "source_repo_id": record["accession_number"],
            "name": record["label"],
            "title": record["label"],
            "description": record["description"] or None,
            "url": f"https://openneuro.org/datasets/{record['dataset_id']}",
            "source": "openneuro",
            "authors": record["authors"],
            "doi": record["doi"] or None,
            "license": record["license"] or None,
            "onvoc_annotation_label": record["label"],
            "onvoc_annotation_description": record["description"] or None,
            "onvoc_annotation_source": "openneuro_onvoc_annotation",
            "onvoc_annotation_source_path": str(self.annotations_path),
            "onvoc_keyword_ids": _dedupe_preserve_order(keyword_ids),
            "onvoc_keyword_labels": _dedupe_preserve_order(keyword_labels),
            "onvoc_inclusion_term_ids": _dedupe_preserve_order(inclusion_ids),
            "onvoc_inclusion_term_labels": _dedupe_preserve_order(inclusion_labels),
            "onvoc_exclusion_term_ids": _dedupe_preserve_order(exclusion_ids),
            "onvoc_exclusion_term_labels": _dedupe_preserve_order(exclusion_labels),
            "onvoc_keyword_count": len(keyword_ids),
            "onvoc_inclusion_term_count": len(inclusion_ids),
            "onvoc_exclusion_term_count": len(exclusion_ids),
            "onvoc_keywords_json": json.dumps(keywords, sort_keys=True),
            "onvoc_inclusion_terms_json": json.dumps(inclusion_terms, sort_keys=True),
            "onvoc_exclusion_terms_json": json.dumps(exclusion_terms, sort_keys=True),
            "onvoc_keyword_provenance_json": json.dumps(
                record.get("keywordProvenance") or {}, sort_keys=True
            ),
            "onvoc_inclusion_term_provenance_json": json.dumps(
                record.get("inclusionTermProvenance") or {}, sort_keys=True
            ),
            "onvoc_exclusion_term_provenance_json": json.dumps(
                record.get("exclusionTermProvenance") or {}, sort_keys=True
            ),
        }

    def build_legacy_concept_properties(self, row: dict[str, Any]) -> dict[str, Any]:
        annotation_labels = _dedupe_preserve_order(
            [str(label) for label in row.get("annotation_labels") or [] if label]
        )
        label = annotation_labels[0] if annotation_labels else row["concept_id"]
        return {
            "id": legacy_onvoc_node_id(row["concept_id"]),
            "legacy_onvoc_id": row["concept_id"],
            "label": label,
            "name": label,
            "description": (
                "Legacy ONVOC label observed in the OpenNeuro March 18 annotation "
                "export but missing from the current ONVOC reference snapshot."
            ),
            "scheme": LEGACY_CONCEPT_SCHEME,
            "source": "openneuro_onvoc_annotation",
            "reference_status": "missing_from_current_onvoc",
            "annotation_labels": annotation_labels,
            "aliases": annotation_labels,
            "synonyms": annotation_labels,
            "annotation_fields": row.get("fields") or [],
            "legacy_raw_ids": row.get("raw_ids") or [],
            "dataset_count": int(row.get("dataset_count") or 0),
            "dataset_ids": row.get("dataset_ids") or [],
            "onvoc_annotation_source": "openneuro_onvoc_annotation",
            "onvoc_annotation_source_path": str(self.annotations_path),
        }

    def build_positive_relationships(
        self, record: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return self._build_relationship_payloads(
            record,
            POSITIVE_ANNOTATION_FIELDS,
            POSITIVE_REL_TYPE,
        )

    def build_negative_relationships(
        self, record: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return self._build_relationship_payloads(
            record,
            NEGATIVE_ANNOTATION_FIELDS,
            NEGATIVE_REL_TYPE,
        )

    def _build_relationship_payloads(
        self,
        record: dict[str, Any],
        fields: tuple[str, ...],
        rel_type: str,
    ) -> dict[str, dict[str, Any]]:
        relationships: dict[str, dict[str, Any]] = {}
        provenance_field_map = {
            "keywords": "keywordProvenance",
            "inclusionTerms": "inclusionTermProvenance",
            "exclusionTerms": "exclusionTermProvenance",
        }

        for field_name in fields:
            provenance_map = record.get(provenance_field_map[field_name]) or {}
            for term in record.get(field_name) or []:
                concept_id = term["concept_id"]
                entry = {
                    "field": field_name,
                    "raw_id": term["raw_id"],
                    "concept_id": concept_id,
                    "label": term.get("label") or "",
                    "comment": term.get("comment") or "",
                    "text": term.get("text") or "",
                    "provenance": provenance_map.get(term["raw_id"])
                    or provenance_map.get(concept_id)
                    or [],
                }
                payload = relationships.setdefault(
                    concept_id,
                    {
                        "rel_type": rel_type,
                        "entries": [],
                    },
                )
                payload["entries"].append(entry)

        normalized: dict[str, dict[str, Any]] = {}
        for concept_id, payload in relationships.items():
            entries = payload["entries"]
            normalized[concept_id] = {
                "source": "openneuro_onvoc_annotation",
                "prov_source": str(self.annotations_path),
                "method": "openneuro_onvoc_annotation",
                "confidence": 1.0,
                "confidence_tier": "verified",
                "annotation_fields": _dedupe_preserve_order(
                    [entry["field"] for entry in entries]
                ),
                "annotation_labels": _dedupe_preserve_order(
                    [entry["label"] for entry in entries if entry["label"]]
                ),
                "annotation_texts": _dedupe_preserve_order(
                    [entry["text"] for entry in entries if entry["text"]]
                ),
                "annotation_comments": _dedupe_preserve_order(
                    [entry["comment"] for entry in entries if entry["comment"]]
                ),
                "annotation_entries_json": json.dumps(entries, sort_keys=True),
            }
        return normalized

    def validate_records(
        self,
        records: list[dict[str, Any]] | None = None,
        reference_concepts: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        records = records or self.load_records()
        reference_concepts = reference_concepts or self.load_reference_concepts()

        missing_terms: dict[str, dict[str, Any]] = {}
        label_mismatches: dict[str, dict[str, Any]] = {}

        for record in records:
            for field_name in ANNOTATION_FIELDS:
                for term in record.get(field_name) or []:
                    concept_id = term["concept_id"]
                    annotation_label = term.get("label") or ""
                    current_label = reference_concepts.get(concept_id)

                    if current_label is None:
                        payload = missing_terms.setdefault(
                            concept_id,
                            {
                                "annotation_labels": set(),
                                "dataset_ids": set(),
                                "fields": set(),
                                "raw_ids": set(),
                            },
                        )
                        payload["annotation_labels"].add(annotation_label)
                        payload["dataset_ids"].add(record["dataset_id"])
                        payload["fields"].add(field_name)
                        payload["raw_ids"].add(term["raw_id"])
                        continue

                    if annotation_label and annotation_label != current_label:
                        payload = label_mismatches.setdefault(
                            concept_id,
                            {
                                "annotation_labels": set(),
                                "current_label": current_label,
                                "dataset_ids": set(),
                                "fields": set(),
                            },
                        )
                        payload["annotation_labels"].add(annotation_label)
                        payload["dataset_ids"].add(record["dataset_id"])
                        payload["fields"].add(field_name)

        def _finalize(payload: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for concept_id, values in sorted(payload.items()):
                rows.append(
                    {
                        "concept_id": concept_id,
                        "annotation_labels": sorted(values["annotation_labels"]),
                        "current_label": values.get("current_label"),
                        "dataset_ids": sorted(values["dataset_ids"]),
                        "dataset_count": len(values["dataset_ids"]),
                        "fields": sorted(values["fields"]),
                        "raw_ids": sorted(values.get("raw_ids", [])),
                    }
                )
            return rows

        return {
            "records": len(records),
            "missing_terms": _finalize(missing_terms),
            "label_mismatches": _finalize(label_mismatches),
        }


class OpenNeuroOnvocAnnotationApplier:
    """Applies OpenNeuro ONVOC annotations to a graph database."""

    def __init__(
        self,
        db: Any,
        loader: OpenNeuroOnvocAnnotationLoader | None = None,
    ) -> None:
        self.db = db
        self.loader = loader or OpenNeuroOnvocAnnotationLoader()

    def _build_dataset_index(self) -> dict[str, Any]:
        dataset_nodes = self.db.find_nodes("Dataset")
        exact_ids: dict[str, str] = {}
        by_source_repo: dict[str, list[str]] = {}
        for node_id, properties in dataset_nodes:
            exact_ids[str(node_id)] = str(node_id)
            source_repo_id = _clean_text(
                properties.get("source_repo_id")
                or properties.get("dataset_id")
                or properties.get("accession")
            )
            if source_repo_id:
                by_source_repo.setdefault(source_repo_id, []).append(str(node_id))
        return {
            "existing_ids": set(exact_ids.keys()),
            "by_source_repo": by_source_repo,
        }

    def _resolve_dataset_node_id(
        self,
        record: dict[str, Any],
        dataset_index: dict[str, Any],
    ) -> str:
        dataset_id = record["dataset_id"]
        source_repo_id = _clean_text(record.get("accession_number")) or dataset_id
        candidates = list(dataset_index["by_source_repo"].get(source_repo_id) or [])
        canonical_id = canonical_openneuro_dataset_node_id(source_repo_id)
        if canonical_id in candidates:
            return canonical_id
        if dataset_id in candidates:
            return dataset_id
        if candidates:
            candidates.sort(
                key=lambda value: (
                    0 if value.startswith("ds:openneuro:") else 1,
                    0 if value == source_repo_id else 1,
                    value,
                )
            )
            return candidates[0]
        return canonical_id

    def _graph_has_node(self, node_id: str) -> bool:
        return bool(self.db.find_nodes(properties={"id": node_id}))

    def _graph_concepts(self) -> dict[str, str]:
        try:
            run_query = getattr(self.db, "_run")
        except Exception:
            run_query = None

        if callable(run_query):
            result = run_query(
                """
                MATCH (o)
                WHERE any(lbl IN labels(o) WHERE lbl IN $labels)
                  AND (
                    coalesce(o.scheme, '') = 'ONVOC'
                    OR coalesce(o.id, '') STARTS WITH 'ONVOC_'
                  )
                RETURN o.id AS id, coalesce(o.label, o.name, o.id) AS label
                """,
                {"labels": ONVOC_GRAPH_LABELS},
            )
            concepts = {
                str(record["id"]): _clean_text(record.get("label"))
                for record in result
                if record.get("id")
            }
            try:
                result.close()
            except Exception:
                pass
            return concepts

        concepts: dict[str, str] = {}
        for node_id, properties in self.db.find_nodes():
            node_labels = set(properties.get("labels", []))
            if not node_labels.intersection(ONVOC_GRAPH_LABELS):
                continue
            concept_id = properties.get("id") or node_id or properties.get("concept_id")
            if not concept_id:
                continue
            concept_id = str(concept_id)
            scheme = _clean_text(properties.get("scheme"))
            if not (scheme == "ONVOC" or concept_id.startswith("ONVOC_")):
                continue
            concepts[concept_id] = _clean_text(
                properties.get("label") or properties.get("name") or concept_id
            )
        return concepts

    def _upsert_legacy_concepts(
        self,
        missing_terms: list[dict[str, Any]],
    ) -> dict[str, str]:
        legacy_graph_nodes: dict[str, str] = {}
        for row in missing_terms:
            concept_id = row["concept_id"]
            node_id = legacy_onvoc_node_id(concept_id)
            properties = self.loader.build_legacy_concept_properties(row)
            self.db.create_node(LEGACY_CONCEPT_LABELS, properties, node_id=node_id)
            legacy_graph_nodes[concept_id] = node_id
        return legacy_graph_nodes

    def _project_legacy_publications(self) -> int:
        try:
            run_query = getattr(self.db, "_run")
        except Exception:
            run_query = None
        if not callable(run_query):
            return 0
        result = run_query(
            f"""
            MATCH (d:Dataset)-[:{POSITIVE_REL_TYPE}]->(legacy:LegacyOnvocTag)
            MATCH (d)-[:CITED_BY]->(p:Publication)
            WITH
              p,
              legacy,
              collect(DISTINCT coalesce(d.source_repo_id, d.dataset_id, d.id)) AS dataset_ids
            MERGE (p)-[rel:{LEGACY_PUBLICATION_REL_TYPE}]->(legacy)
            ON CREATE SET
              rel.source = 'openneuro_onvoc_annotation',
              rel.method = 'dataset_citation_projection',
              rel.prov_source = $prov_source,
              rel.confidence = 0.6,
              rel.confidence_tier = 'imported'
            SET
              rel.dataset_ids = dataset_ids,
              rel.dataset_count = size(dataset_ids)
            RETURN count(rel) AS total
            """,
            {"prov_source": str(self.loader.annotations_path)},
        )
        row = result.single()
        try:
            result.close()
        except Exception:
            pass
        return int(row["total"] if row else 0)

    def _upsert_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any],
    ) -> int:
        existing = self.db.find_relationships(
            start_node=start_node,
            end_node=end_node,
            rel_type=rel_type,
        )
        self.db.create_relationship(start_node, end_node, rel_type, properties)
        return 0 if existing else 1

    def apply(
        self,
        records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        records = records or self.loader.load_records()
        reference_concepts = self.loader.load_reference_concepts()
        validation = self.loader.validate_records(
            records=records,
            reference_concepts=reference_concepts,
        )
        graph_concepts = self._graph_concepts()
        dataset_index = self._build_dataset_index()
        existing_dataset_ids = set(dataset_index["existing_ids"])
        legacy_graph_nodes = self._upsert_legacy_concepts(validation["missing_terms"])

        stats = {
            "records_processed": 0,
            "datasets_created": 0,
            "datasets_upserted": 0,
            "positive_links_created": 0,
            "exclusion_links_created": 0,
            "legacy_concepts_upserted": len(legacy_graph_nodes),
            "legacy_publication_links_created": 0,
            "missing_reference_terms": validation["missing_terms"],
            "label_mismatches": validation["label_mismatches"],
            "missing_graph_terms": [],
        }

        missing_graph_terms: dict[str, dict[str, Any]] = {}

        for record in records:
            stats["records_processed"] += 1
            source_dataset_id = record["dataset_id"]
            dataset_node_id = self._resolve_dataset_node_id(record, dataset_index)

            if dataset_node_id not in existing_dataset_ids:
                stats["datasets_created"] += 1
                existing_dataset_ids.add(dataset_node_id)
                dataset_index["by_source_repo"].setdefault(
                    record["accession_number"], []
                ).append(dataset_node_id)

            dataset_properties = self.loader.build_dataset_properties(record)
            dataset_properties["id"] = dataset_node_id
            dataset_properties["dataset_id"] = source_dataset_id
            self.db.create_node("Dataset", dataset_properties, node_id=dataset_node_id)
            stats["datasets_upserted"] += 1

            for concept_id, rel_props in self.loader.build_positive_relationships(
                record
            ).items():
                target_node_id = None
                if concept_id in graph_concepts:
                    target_node_id = concept_id
                elif concept_id in legacy_graph_nodes:
                    target_node_id = legacy_graph_nodes[concept_id]
                    rel_props = dict(rel_props)
                    rel_props["legacy_onvoc_id"] = concept_id
                    rel_props["target_scheme"] = LEGACY_CONCEPT_SCHEME
                if not target_node_id:
                    payload = missing_graph_terms.setdefault(
                        concept_id,
                        {
                            "dataset_ids": set(),
                            "fields": set(),
                        },
                    )
                    payload["dataset_ids"].add(source_dataset_id)
                    payload["fields"].update(rel_props.get("annotation_fields") or [])
                    continue
                stats["positive_links_created"] += self._upsert_relationship(
                    dataset_node_id,
                    target_node_id,
                    POSITIVE_REL_TYPE,
                    rel_props,
                )

            for concept_id, rel_props in self.loader.build_negative_relationships(
                record
            ).items():
                target_node_id = None
                if concept_id in graph_concepts:
                    target_node_id = concept_id
                elif concept_id in legacy_graph_nodes:
                    target_node_id = legacy_graph_nodes[concept_id]
                    rel_props = dict(rel_props)
                    rel_props["legacy_onvoc_id"] = concept_id
                    rel_props["target_scheme"] = LEGACY_CONCEPT_SCHEME
                if not target_node_id:
                    payload = missing_graph_terms.setdefault(
                        concept_id,
                        {
                            "dataset_ids": set(),
                            "fields": set(),
                        },
                    )
                    payload["dataset_ids"].add(source_dataset_id)
                    payload["fields"].update(rel_props.get("annotation_fields") or [])
                    continue
                stats["exclusion_links_created"] += self._upsert_relationship(
                    dataset_node_id,
                    target_node_id,
                    NEGATIVE_REL_TYPE,
                    rel_props,
                )

        stats["legacy_publication_links_created"] = self._project_legacy_publications()
        stats["missing_graph_terms"] = [
            {
                "concept_id": concept_id,
                "dataset_ids": sorted(values["dataset_ids"]),
                "dataset_count": len(values["dataset_ids"]),
                "fields": sorted(values["fields"]),
            }
            for concept_id, values in sorted(missing_graph_terms.items())
        ]
        return stats
