from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from brain_researcher.core.datasets.catalog import DatasetRecord, load_catalog
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)


@dataclass
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str | None = None


class DatasetNeo4jLoader:
    def __init__(self, db: Neo4jGraphDB, *, dry_run: bool = False) -> None:
        self.db = db
        self.dry_run = dry_run

    def ensure_schema(self) -> None:
        if self.dry_run:
            logger.info("[dry-run] Skipping schema creation")
            return
        self.db.create_constraint("Dataset", "dataset_id")
        for label, prop in (
            ("Dataset", "name"),
            ("Dataset", "source_repo"),
            ("Repository", "name"),
            ("Center", "name"),
            ("Consortium", "name"),
        ):
            self.db.create_index(label, prop)

    def upsert_all(self, records: Iterable[DatasetRecord]) -> None:
        self.ensure_schema()
        for record in records:
            self._upsert_dataset(record)

    def _upsert_dataset(self, record: DatasetRecord) -> None:
        dataset_props = record.model_dump()
        dataset_props.update(
            {
                "dataset_id": record.dataset_id,
                "search_blob": record.search_blob,
            }
        )
        node_id = record.dataset_id
        logger.info("Upserting dataset %s", node_id)
        if not self.dry_run:
            self.db.create_node("Dataset", dataset_props, node_id=node_id)
        self._relate_repository(record)
        self._relate_center(record)
        self._relate_consortium(record)
        self._relate_modalities(record)
        self._relate_acquisitions(record)
        self._relate_species(record)

    def _relate_repository(self, record: DatasetRecord) -> None:
        repo_name = record.source_repo
        repo_id = f"repo::{repo_name.lower()}"
        props = {"name": repo_name}
        if not self.dry_run:
            self.db.create_node("Repository", props, node_id=repo_id)
            self.db.create_relationship(record.dataset_id, repo_id, "HOSTED_AT", {})

    def _relate_center(self, record: DatasetRecord) -> None:
        if not record.center:
            return
        center_id = f"center::{record.center.lower()}"
        props = {"name": record.center, "principal_investigator": record.principal_investigator}
        if not self.dry_run:
            self.db.create_node("Center", props, node_id=center_id)
            self.db.create_relationship(record.dataset_id, center_id, "COLLECTED_BY", {})

    def _relate_consortium(self, record: DatasetRecord) -> None:
        if not record.consortium:
            return
        cons_id = f"consortium::{record.consortium.lower()}"
        props = {"name": record.consortium}
        if not self.dry_run:
            self.db.create_node("Consortium", props, node_id=cons_id)
            self.db.create_relationship(record.dataset_id, cons_id, "PART_OF", {})

    def _relate_modalities(self, record: DatasetRecord) -> None:
        for modality in record.modalities:
            name = str(modality)
            mod_id = f"modality::{name.lower()}"
            props = {"name": name}
            if not self.dry_run:
                self.db.create_node("Modality", props, node_id=mod_id)
                self.db.create_relationship(record.dataset_id, mod_id, "HAS_MODALITY", {})

    def _relate_acquisitions(self, record: DatasetRecord) -> None:
        for acquisition in record.acquisitions:
            name = str(acquisition)
            acq_id = f"acquisition::{name.lower()}"
            props = {"name": name}
            if not self.dry_run:
                self.db.create_node("AcquisitionType", props, node_id=acq_id)
                self.db.create_relationship(record.dataset_id, acq_id, "HAS_ACQUISITION_TYPE", {})

    def _relate_species(self, record: DatasetRecord) -> None:
        for species in record.species:
            spec_id = f"species::{species.lower()}"
            props = {"name": species}
            if not self.dry_run:
                self.db.create_node("Species", props, node_id=spec_id)
                self.db.create_relationship(record.dataset_id, spec_id, "INVOLVES_SPECIES", {})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load dataset catalog into Neo4j")
    parser.add_argument("--catalog", type=Path, default=None, help="Path to catalog JSONL file")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "neo4j"))
    parser.add_argument("--database", default=os.environ.get("NEO4J_DATABASE"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    records = load_catalog(args.catalog)
    if args.dry_run:
        logger.info("Loaded %s dataset rows (dry-run)", len(records))
        return
    db = Neo4jGraphDB(args.uri, args.user, args.password, database=args.database)
    try:
        loader = DatasetNeo4jLoader(db)
        loader.upsert_all(records)
        logger.info("Ingested %s dataset nodes", len(records))
    finally:
        db.close()


if __name__ == "__main__":
    main()
