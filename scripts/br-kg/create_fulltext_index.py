#!/usr/bin/env python3
"""
Create the KG fulltext index used by query_service.
"""

from __future__ import annotations

import argparse
import logging
import os
import re

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_LABELS = [
    "Task",
    "TaskDef",
    "TaskSpec",
    "TaskAnalysis",
    "CognitiveConcept",
    "Construct",
    "CognitiveConstruct",
    "Concept",
    "Term",
    "ONVOC",
    "OnvocClass",
    "OntologyConcept",
    "Dataset",
    "DataResource",
    "Publication",
    "Paper",
    "Study",
    "Tool",
    "Software",
    "Contrast",
    "StatMap",
    "StatsMap",
    "CoordAnchor",
    "BrainRegion",
    "Region",
    "Atlas",
    "TemplateSpace",
    "Parcellation",
    "Parcel",
    "SubjectGroup",
    "Condition",
]

DEFAULT_FIELDS = [
    "name",
    "label",
    "title",
    "description",
    "definition",
    "abstract",
    "aliases",
    "alias",
    "synonyms",
    "keywords",
    "dataset_id",
    "id",
    "uid",
    "identifier",
    "accession",
    "openneuro_id",
    "dataset_uuid",
    "short_name",
    "task",
    "construct_id",
    "cognitive_atlas_id",
    "tool_id",
    "op_key",
    "atlas",
    "journal",
    "authors",
    "pmid",
    "doi",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Neo4j fulltext index for KG search")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "password"))
    parser.add_argument("--neo4j-database", default=os.getenv("NEO4J_DATABASE"))
    parser.add_argument("--index-name", default="kgNodeFulltext")
    parser.add_argument(
        "--labels",
        default=",".join(DEFAULT_LABELS),
        help="Comma-separated labels included in the fulltext index",
    )
    parser.add_argument(
        "--fields",
        default=",".join(DEFAULT_FIELDS),
        help="Comma-separated node properties included in the fulltext index",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    labels = [label.strip() for label in str(args.labels).split(",") if label.strip()]
    fields = [field.strip() for field in str(args.fields).split(",") if field.strip()]
    invalid_labels = [label for label in labels if not _IDENTIFIER_RE.match(label)]
    invalid_fields = [field for field in fields if not _IDENTIFIER_RE.match(field)]
    if invalid_labels:
        raise ValueError(f"Invalid labels: {invalid_labels}")
    if invalid_fields:
        raise ValueError(f"Invalid fields: {invalid_fields}")
    label_expr = "|".join(labels)
    field_expr = ",\n      ".join(f"n.{field}" for field in fields)

    cypher = f"""
    CREATE FULLTEXT INDEX {args.index_name} IF NOT EXISTS
    FOR (n:{label_expr})
    ON EACH [
      {field_expr}
    ]
    """

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session(database=args.neo4j_database) as session:
        session.run(cypher)
        logger.info(
            "Created/verified fulltext index: %s (labels=%d fields=%d)",
            args.index_name,
            len(labels),
            len(fields),
        )

    driver.close()


if __name__ == "__main__":
    main()
