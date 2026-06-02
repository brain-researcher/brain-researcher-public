#!/usr/bin/env python3
"""
Dataset Catalog -> Neo4j Loader
--------------------------------

Reads the canonical dataset catalog JSONL (configs/datasets/catalog.v1.jsonl by
default) and upserts Dataset nodes plus supporting Repository/Consortium/
Modality/Species nodes into Neo4j.

Usage (CLI):
    python -m brain_researcher.services.br_kg.etl.loaders.dataset_catalog_loader \\
        --catalog configs/datasets/catalog.v1.jsonl \\
        --neo4j-uri bolt://localhost:7687 --neo4j-user neo4j --neo4j-password password
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from pathlib import Path

from brain_researcher.core.datasets.catalog import (
    DEFAULT_CATALOG_PATH,
    DatasetRecord,
    load_catalog,
)
from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)


def _normalize_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    return [str(v).strip() for v in values if str(v).strip()]


class DatasetCatalogNeo4jLoader:
    """Load dataset catalog rows into Neo4j as Dataset graph nodes."""

    def __init__(
        self,
        db: Neo4jGraphDB,
        *,
        dataset_label: str = "Dataset",
        dataset_extra_labels: tuple[str, ...] = ("DataResource",),
    ) -> None:
        self.db = db
        self.dataset_label = dataset_label
        self.dataset_extra_labels = dataset_extra_labels

        # Ensure uniqueness on dataset id
        self.db.create_constraint(self.dataset_label, "id")

    def load(self, records: Iterable[DatasetRecord]) -> dict[str, int]:
        stats = {
            "datasets_upserted": 0,
            "repositories_upserted": 0,
            "consortia_upserted": 0,
            "modalities_upserted": 0,
            "species_upserted": 0,
            "relationships_created": 0,
            "resource_aliases_canonicalized": 0,
        }

        for rec in records:
            stats["datasets_upserted"] += 1
            self._upsert_dataset(rec)
            stats[
                "resource_aliases_canonicalized"
            ] += self._canonicalize_legacy_data_resource_alias(rec.dataset_id)

            stats["repositories_upserted"] += self._upsert_repository(rec, stats)
            stats["consortia_upserted"] += self._upsert_consortium(rec, stats)
            stats["modalities_upserted"] += self._upsert_modalities(rec, stats)
            stats["species_upserted"] += self._upsert_species(rec, stats)

        logger.info(
            "Ingestion complete: %(datasets_upserted)s datasets, %(repositories_upserted)s repositories, "
            "%(consortia_upserted)s consortia, %(modalities_upserted)s modalities, %(species_upserted)s species",
            stats,
        )
        return stats

    # --- Upsert helpers -------------------------------------------------
    def _dataset_labels(self) -> list[str]:
        return [self.dataset_label, *self.dataset_extra_labels]

    def _upsert_dataset(self, rec: DatasetRecord) -> str:
        props = {
            "id": rec.dataset_id,
            "dataset_id": rec.dataset_id,
            "resource_id": rec.dataset_id,
            "name": rec.name,
            "short_name": rec.short_name,
            "description": rec.description,
            "category": rec.category,
            "modalities": _normalize_list(rec.modalities),
            "acquisitions": _normalize_list(rec.acquisitions),
            "subjects_count": rec.subjects_count,
            "sessions_count": rec.sessions_count,
            "alias": _normalize_list(rec.alias),
            "species": _normalize_list(rec.species),
            "age_range": rec.age_range.model_dump() if rec.age_range else None,
            "disease_flags": _normalize_list(rec.disease_flags),
            "center": rec.center,
            "principal_investigator": rec.principal_investigator,
            "consortium": rec.consortium,
            "source_repo": rec.source_repo,
            "source_repo_id": rec.source_repo_id,
            "source_repo_bucket": (
                "OpenNeuro" if rec.source_repo == "OpenNeuro" else "Non-OpenNeuro"
            ),
            "is_openneuro": rec.source_repo == "OpenNeuro",
            "primary_url": str(rec.primary_url),
            "access_type": rec.access_type,
            "license": rec.license,
            "approx_size_bytes": rec.approx_size_bytes,
            "size_human": rec.size_human,
            "tags": _normalize_list(rec.tags),
            "tasks": _normalize_list(rec.tasks),
            "modalities_notes": rec.modalities_notes,
            "has_derivatives": rec.has_derivatives,
            "preview_media": [pm.dict() for pm in rec.preview_media],
            "created_from": rec.created_from,
            "source_version": rec.source_version,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
            "category_source": rec.category,
            "search_blob": rec.search_blob,
        }

        node_id = self.db.create_node(
            self._dataset_labels(), props, node_id=rec.dataset_id
        )
        return node_id

    def _canonicalize_legacy_data_resource_alias(self, dataset_id: str) -> int:
        """Fold old DataResource(resource_id=...) aliases into the canonical Dataset node."""
        if not hasattr(self.db, "_run"):
            return 0

        self.db._run(
            """
            MATCH (d:Dataset {id: $dataset_id})
            SET d:DataResource
            SET d.resource_id = coalesce(d.resource_id, $dataset_id),
                d.dataset_id = coalesce(d.dataset_id, $dataset_id)
            """,
            {"dataset_id": dataset_id},
        ).consume()

        alias_rows = list(
            self.db._run(
                """
                MATCH (legacy:DataResource {resource_id: $dataset_id})
                WHERE coalesce(legacy.id, '') <> $dataset_id
                RETURN elementId(legacy) AS element_id
                """,
                {"dataset_id": dataset_id},
            )
        )

        canonicalized = 0
        for row in alias_rows:
            element_id = row.get("element_id")
            if not element_id:
                continue

            incoming = list(
                self.db._run(
                    """
                    MATCH (src)-[r]->(legacy)
                    WHERE elementId(legacy) = $element_id
                    RETURN src.id AS node_id, type(r) AS rel_type, properties(r) AS props
                    """,
                    {"element_id": element_id},
                )
            )
            for rel in incoming:
                node_id = rel.get("node_id")
                rel_type = rel.get("rel_type")
                if not node_id or not rel_type:
                    continue
                self.db.create_relationship(
                    str(node_id),
                    dataset_id,
                    str(rel_type),
                    dict(rel.get("props") or {}),
                )

            outgoing = list(
                self.db._run(
                    """
                    MATCH (legacy)-[r]->(dst)
                    WHERE elementId(legacy) = $element_id
                    RETURN dst.id AS node_id, type(r) AS rel_type, properties(r) AS props
                    """,
                    {"element_id": element_id},
                )
            )
            for rel in outgoing:
                node_id = rel.get("node_id")
                rel_type = rel.get("rel_type")
                if not node_id or not rel_type:
                    continue
                self.db.create_relationship(
                    dataset_id,
                    str(node_id),
                    str(rel_type),
                    dict(rel.get("props") or {}),
                )

            self.db._run(
                """
                MATCH (legacy)
                WHERE elementId(legacy) = $element_id
                DETACH DELETE legacy
                """,
                {"element_id": element_id},
            ).consume()
            canonicalized += 1

        return canonicalized

    def _upsert_repository(self, rec: DatasetRecord, stats: dict[str, int]) -> int:
        repo_name = (rec.source_repo or "").strip()
        if not repo_name:
            return 0
        repo_id = f"repo:{repo_name.lower().replace(' ', '_')}"
        self.db.create_node("Repository", {"id": repo_id, "name": repo_name})
        self.db.create_relationship(rec.dataset_id, repo_id, "HOSTED_AT")
        stats["relationships_created"] += 1
        return 1

    def _upsert_consortium(self, rec: DatasetRecord, stats: dict[str, int]) -> int:
        consortium = (rec.consortium or "").strip()
        if not consortium:
            return 0
        cons_id = f"consortium:{consortium.lower().replace(' ', '_')}"
        self.db.create_node("Consortium", {"id": cons_id, "name": consortium})
        self.db.create_relationship(rec.dataset_id, cons_id, "PART_OF")
        stats["relationships_created"] += 1
        return 1

    def _upsert_modalities(self, rec: DatasetRecord, stats: dict[str, int]) -> int:
        count = 0
        for mod in _normalize_list(rec.modalities):
            mod_id = f"modality:{mod.lower()}"
            self.db.create_node("Modality", {"id": mod_id, "name": mod})
            self.db.create_relationship(rec.dataset_id, mod_id, "HAS_MODALITY")
            stats["relationships_created"] += 1
            count += 1
        return count

    def _upsert_species(self, rec: DatasetRecord, stats: dict[str, int]) -> int:
        count = 0
        for sp in _normalize_list(rec.species):
            sp_id = f"species:{sp.lower()}"
            self.db.create_node("Species", {"id": sp_id, "name": sp})
            self.db.create_relationship(rec.dataset_id, sp_id, "INVOLVES_SPECIES")
            stats["relationships_created"] += 1
            count += 1
        return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Load dataset catalog into Neo4j")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="Path to dataset catalog JSONL (default: configs/datasets/catalog.v1.jsonl)",
    )
    parser.add_argument(
        "--neo4j-uri", required=True, help="Neo4j bolt URI, e.g., bolt://localhost:7687"
    )
    parser.add_argument("--neo4j-user", required=True, help="Neo4j username")
    parser.add_argument("--neo4j-password", required=True, help="Neo4j password")
    parser.add_argument(
        "--neo4j-database", default=None, help="Neo4j database name (optional)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional limit on rows for testing"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    if not args.catalog.exists():
        raise FileNotFoundError(f"Catalog file not found: {args.catalog}")

    logger.info("Loading catalog from %s", args.catalog)
    records = load_catalog(args.catalog)
    if args.limit:
        records = records[: args.limit]
        logger.info("Limiting ingestion to first %s records", args.limit)

    db = Neo4jGraphDB(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_password,
        database=args.neo4j_database,
        preload_cache=False,
    )
    loader = DatasetCatalogNeo4jLoader(db)
    stats = loader.load(records)
    logger.info("Done. Stats: %s", stats)


if __name__ == "__main__":
    main()
