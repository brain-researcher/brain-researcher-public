#!/usr/bin/env python3
"""Load Neurosynth v7 metadata/coordinates into BR-KG."""

from __future__ import annotations

import argparse
import gzip
import logging
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

PUB_CYPHER = """
UNWIND $rows AS row
MERGE (p:Publication {pmid: row.pmid})
ON CREATE SET p.source = "neurosynth"
SET p.title = coalesce(row.title, p.title),
    p.journal = coalesce(row.journal, p.journal),
    p.year = coalesce(row.year, p.year),
    p.authors = coalesce(row.authors, p.authors),
    p.neurosynth_space = coalesce(row.space, p.neurosynth_space),
    p.neurosynth_id = row.pmid
"""

COORD_CYPHER = """
UNWIND $rows AS row
MERGE (p:Publication {pmid: row.pmid})
MERGE (c:Coordinate {id: row.coord_id})
SET c.x = row.x,
    c.y = row.y,
    c.z = row.z,
    c.space = row.space,
    c.source = "neurosynth"
MERGE (p)-[:HAS_COORDINATE]->(c)
MERGE (t:TemplateSpace {id: row.template_space_id})
ON CREATE SET t.name = row.template_space_name, t.source = "neuromaps"
MERGE (c)-[:IN_SPACE]->(t)
"""


SPACE_MAP = {
    "MNI": ("tpl:MNI152NLin2009cAsym_2mm", "MNI152 NLin2009c Asym 2mm"),
    "TAL": ("tpl:Talairach", "Talairach"),
}


class Neo4jBatchWriter:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    def close(self) -> None:
        self._driver.close()

    def run(self, cypher: str, rows: List[Dict]) -> None:
        if not rows:
            return
        with self._driver.session(database=self._database) as session:
            session.run(cypher, rows=rows)


def _read_tsv(path: Path) -> Iterator[Dict[str, str]]:
    with gzip.open(path, "rt") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            values = line.rstrip("\n").split("\t")
            if not values or len(values) != len(header):
                continue
            yield dict(zip(header, values))


def _normalize_pmid(value: str) -> str:
    return value.strip()


def ingest_publications(path: Path, writer: Neo4jBatchWriter, batch_size: int) -> None:
    buffer: List[Dict] = []
    for idx, row in enumerate(_read_tsv(path), 1):
        pmid = _normalize_pmid(row["id"])
        buffer.append(
            {
                "pmid": pmid,
                "title": row.get("title") or None,
                "authors": row.get("authors") or None,
                "journal": row.get("journal") or None,
                "year": int(row["year"]) if row.get("year") else None,
                "space": row.get("space") or None,
            }
        )
        if len(buffer) >= batch_size:
            writer.run(PUB_CYPHER, buffer)
            buffer.clear()
            if idx % (batch_size * 10) == 0:
                logger.info("Ingested %d publication rows", idx)
    if buffer:
        writer.run(PUB_CYPHER, buffer)
    logger.info("Finished ingesting publications")


def _normalize_space(value: Optional[str]) -> Dict[str, str]:
    if value is None:
        return {"space": None, "template_space_id": None, "template_space_name": None}
    value = value.upper()
    tpl_id, tpl_name = SPACE_MAP.get(value, ("tpl:Unknown", value))
    return {"space": value, "template_space_id": tpl_id, "template_space_name": tpl_name}


def ingest_coordinates(path: Path, writer: Neo4jBatchWriter, batch_size: int) -> None:
    buffer: List[Dict] = []
    for idx, row in enumerate(_read_tsv(path), 1):
        pmid = _normalize_pmid(row["id"])
        coord_id = f"coord:neurosynth:{row[table_id]}:{row[peak_id]}"
        space_info = _normalize_space(None)  # placeholder, actual mapping happens later
        payload = {
            "pmid": pmid,
            "coord_id": coord_id,
            "x": float(row.get("x") or 0.0),
            "y": float(row.get("y") or 0.0),
            "z": float(row.get("z") or 0.0),
            "space": row.get("space") or "MNI",
        }
        tpl = SPACE_MAP.get(payload["space"].upper(), ("tpl:MNI152NLin2009cAsym_2mm", "MNI152 NLin2009c Asym 2mm"))
        payload["template_space_id"] = tpl[0]
        payload["template_space_name"] = tpl[1]
        buffer.append(payload)

        if len(buffer) >= batch_size:
            writer.run(COORD_CYPHER, buffer)
            buffer.clear()
            if idx % (batch_size * 10) == 0:
                logger.info("Ingested %d coordinate rows", idx)
    if buffer:
        writer.run(COORD_CYPHER, buffer)
    logger.info("Finished ingesting coordinates")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=Path("data/neurosynth_nimare/neurosynth_v7"))
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--skip-coordinates", action="store_true")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    dataset_dir = args.dataset_dir
    metadata_path = dataset_dir / "data-neurosynth_version-7_metadata.tsv.gz"
    coordinates_path = dataset_dir / "data-neurosynth_version-7_coordinates.tsv.gz"

    if not metadata_path.exists():
        raise FileNotFoundError(metadata_path)
    if not args.skip_coordinates and not coordinates_path.exists():
        raise FileNotFoundError(coordinates_path)

    writer = Neo4jBatchWriter(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )
    try:
        ingest_publications(metadata_path, writer, args.batch_size)
        if not args.skip_coordinates:
            ingest_coordinates(coordinates_path, writer, args.batch_size)
    finally:
        writer.close()


if __name__ == "__main__":
    main()
