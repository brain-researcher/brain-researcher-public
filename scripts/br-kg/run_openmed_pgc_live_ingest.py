#!/usr/bin/env python3
"""Run live OpenMed/PGC metadata ingest into Neo4j.

Usage:
    python scripts/br-kg/run_openmed_pgc_live_ingest.py
    python scripts/br-kg/run_openmed_pgc_live_ingest.py --dataset-id OpenMed/pgc-bipolar

Requirements:
    - Repo-root `.env` or process env must define `NEO4J_URI` and `NEO4J_PASSWORD`.
    - Neo4j must be reachable.

Outputs:
    - Prints a JSON summary including snapshot size, upsert counts, materialization
      summary, and before/after Neo4j counts.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from brain_researcher.core.utils.env_loader import ensure_env_loaded
from brain_researcher.services.br_kg.etl.loaders.gwas_catalog_top_loci_loader import (
    TOP_LOCI_SOURCE,
    fetch_top_loci_snapshot,
)
from brain_researcher.services.br_kg.etl.loaders.openmed_pgc_hf_loader import (
    openmed_pgc_snapshot_to_graph_inputs,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.spatial.disease_trait_region_materializer import (
    materialize_disease_trait_region_associations,
)


OPENMED_SOURCE = "openmed_pgc_hf_loader"
OPENMED_STUDY_PREFIX = "study:openmed_pgc_"


def _scalar(db: Any, cypher: str, params: dict[str, Any] | None = None) -> int:
    record = db._run(cypher, params or {}).single()
    if record is None:
        return 0
    value = record[0]
    return int(value or 0)


def _collect_counts(db: Any) -> dict[str, int]:
    return {
        "study_nodes": _scalar(
            db,
            "MATCH (n:Study:GWASStudy) WHERE n.source = $source RETURN count(n)",
            {"source": OPENMED_SOURCE},
        ),
        "disease_trait_nodes": _scalar(
            db,
            "MATCH (n:DiseaseTrait) WHERE n.source = $source RETURN count(n)",
            {"source": OPENMED_SOURCE},
        ),
        "population_nodes": _scalar(
            db,
            "MATCH (n:Population) WHERE n.source = $source RETURN count(n)",
            {"source": OPENMED_SOURCE},
        ),
        "risk_locus_nodes": _scalar(
            db,
            "MATCH (n:RiskLocus) WHERE n.source = $source RETURN count(n)",
            {"source": TOP_LOCI_SOURCE},
        ),
        "associated_with_edges": _scalar(
            db,
            "MATCH ()-[r:ASSOCIATED_WITH]->() WHERE r.source = $source RETURN count(r)",
            {"source": TOP_LOCI_SOURCE},
        ),
        "has_lead_locus_edges": _scalar(
            db,
            "MATCH ()-[r:HAS_LEAD_LOCUS]->() WHERE r.source = $source RETURN count(r)",
            {"source": TOP_LOCI_SOURCE},
        ),
        "legacy_study_cohort_population_nodes": _scalar(
            db,
            (
                "MATCH (n:Population) "
                "WHERE n.source = $source AND n.population_type = 'study_cohort' "
                "RETURN count(n)"
            ),
            {"source": OPENMED_SOURCE},
        ),
        "publication_nodes": _scalar(
            db,
            "MATCH (n:Publication) WHERE n.source = $source RETURN count(n)",
            {"source": OPENMED_SOURCE},
        ),
        "studies_edges": _scalar(
            db,
            "MATCH ()-[r:STUDIES]->() WHERE r.source = $source RETURN count(r)",
            {"source": OPENMED_SOURCE},
        ),
        "has_population_edges": _scalar(
            db,
            "MATCH ()-[r:HAS_POPULATION]->() WHERE r.source = $source RETURN count(r)",
            {"source": OPENMED_SOURCE},
        ),
        "aligns_with_edges": _scalar(
            db,
            "MATCH ()-[r:ALIGNS_WITH]->() WHERE r.source = $source RETURN count(r)",
            {"source": OPENMED_SOURCE},
        ),
        "derived_region_edges_for_openmed": _scalar(
            db,
            (
                "MATCH (:DiseaseTrait)-[r]->(:BrainRegion) "
                "WHERE type(r) = 'ASSOCIATED_WITH' "
                "AND r.source = $source "
                "AND any(study_id IN coalesce(r.supporting_study_ids, []) "
                "WHERE study_id STARTS WITH $study_prefix) "
                "RETURN count(r)"
            ),
            {
                "source": "disease_trait_region_materializer",
                "study_prefix": OPENMED_STUDY_PREFIX,
            },
        ),
    }


def _delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: after.get(key, 0) - before.get(key, 0) for key in after}


def _ingest_snapshot(db: Any, snapshot: Any) -> dict[str, int]:
    nodes_written = 0
    relationships_written = 0
    for node in snapshot.node_rows:
        # Support both structured {node_id, labels, properties} and flat dict formats
        if "properties" in node:
            node_id = node["node_id"]
            labels = node["labels"]
            props = node["properties"]
        else:
            node_id = node.get("node_id") or node.get("id")
            labels = node.get("labels", [])
            props = {k: v for k, v in node.items() if k not in ("node_id", "labels", "type")}
        db.create_node(labels, props, node_id=node_id)
        nodes_written += 1
    for rel in snapshot.relationship_rows:
        # Support both {start_id, end_id, rel_type, properties} and flat dict formats
        if "properties" in rel:
            start_id = rel["start_id"]
            end_id = rel["end_id"]
            rel_type = rel["rel_type"]
            props = rel["properties"]
        else:
            start_id = rel.get("start_id") or rel.get("source_id")
            end_id = rel.get("end_id") or rel.get("target_id")
            rel_type = rel["rel_type"]
            props = {k: v for k, v in rel.items() if k not in ("start_id", "end_id", "source_id", "target_id", "rel_type")}
        if db.create_relationship(start_id, end_id, rel_type, props):
            relationships_written += 1
    return {
        "nodes_written": nodes_written,
        "relationships_written": relationships_written,
    }


def _cleanup_legacy_study_cohort_nodes(db: Any) -> int:
    count = _scalar(
        db,
        (
            "MATCH (n:Population) "
            "WHERE n.source = $source AND n.population_type = 'study_cohort' "
            "RETURN count(n)"
        ),
        {"source": OPENMED_SOURCE},
    )
    if count:
        db._run(
            (
                "MATCH (n:Population) "
                "WHERE n.source = $source AND n.population_type = 'study_cohort' "
                "DETACH DELETE n"
            ),
            {"source": OPENMED_SOURCE},
        ).consume()
    return count


def _study_ids_by_pmid(db: Any) -> dict[str, tuple[str, ...]]:
    rows = db._run(
        (
            "MATCH (s:Study:GWASStudy) "
            "WHERE s.source = $source AND s.pmid IS NOT NULL "
            "RETURN s.pmid AS pmid, collect(s.id) AS study_ids"
        ),
        {"source": OPENMED_SOURCE},
    )
    mapping: dict[str, tuple[str, ...]] = {}
    for row in rows:
        pmid = str(row["pmid"]).strip()
        study_ids = tuple(
            sorted(
                {
                    str(study_id).strip()
                    for study_id in (row["study_ids"] or [])
                    if str(study_id).strip()
                }
            )
        )
        if pmid and study_ids:
            mapping[pmid] = study_ids
    return mapping


def _cleanup_top_loci_layer(db: Any) -> dict[str, int]:
    counts = {
        "risk_locus_nodes_deleted": _scalar(
            db,
            "MATCH (n:RiskLocus) WHERE n.source = $source RETURN count(n)",
            {"source": TOP_LOCI_SOURCE},
        ),
        "associated_with_edges_deleted": _scalar(
            db,
            "MATCH ()-[r:ASSOCIATED_WITH]->() WHERE r.source = $source RETURN count(r)",
            {"source": TOP_LOCI_SOURCE},
        ),
        "has_lead_locus_edges_deleted": _scalar(
            db,
            "MATCH ()-[r:HAS_LEAD_LOCUS]->() WHERE r.source = $source RETURN count(r)",
            {"source": TOP_LOCI_SOURCE},
        ),
    }
    if counts["risk_locus_nodes_deleted"]:
        db._run(
            "MATCH (n:RiskLocus) WHERE n.source = $source DETACH DELETE n",
            {"source": TOP_LOCI_SOURCE},
        ).consume()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-id",
        action="append",
        default=[],
        help="Optional explicit dataset id(s), e.g. OpenMed/pgc-bipolar.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for Hugging Face metadata fetches.",
    )
    parser.add_argument(
        "--skip-top-loci",
        action="store_true",
        default=False,
        help="Skip GWAS Catalog top loci fetch (faster, metadata-only run).",
    )
    parser.add_argument(
        "--max-loci-per-disorder",
        type=int,
        default=500,
        help="Max associations per disorder fetched from GWAS Catalog.",
    )
    args = parser.parse_args()

    ensure_env_loaded()
    db = require_neo4j_db(preload_cache=False)
    try:
        before = _collect_counts(db)
        cleanup_deleted = _cleanup_legacy_study_cohort_nodes(db)
        snapshot = openmed_pgc_snapshot_to_graph_inputs(
            timeout=args.timeout,
            explicit_dataset_ids=tuple(args.dataset_id) or None,
        )
        ingest_summary = _ingest_snapshot(db, snapshot)
        disease_trait_ids = [
            row["node_id"]
            for row in snapshot.node_rows
            if "DiseaseTrait" in row.get("labels", [])
        ]
        materialize_summary = materialize_disease_trait_region_associations(
            db,
            disease_trait_ids=disease_trait_ids,
        ).to_dict()

        # Top loci from GWAS Catalog
        top_loci_summary: dict[str, Any] = {"skipped": True}
        if not args.skip_top_loci:
            print("Fetching top loci from GWAS Catalog...", flush=True)
            study_ids_by_pmid = _study_ids_by_pmid(db)
            loci_snapshot = fetch_top_loci_snapshot(
                study_ids_by_pmid=study_ids_by_pmid,
                max_associations_per_disorder=args.max_loci_per_disorder,
                timeout=args.timeout,
            )
            top_loci_cleanup = _cleanup_top_loci_layer(db)
            loci_ingest = _ingest_snapshot(db, loci_snapshot)
            top_loci_summary = {
                "skipped": False,
                "risk_locus_nodes": len(loci_snapshot.node_rows),
                "associated_with_edges": sum(
                    1
                    for rel in loci_snapshot.relationship_rows
                    if rel["rel_type"] == "ASSOCIATED_WITH"
                ),
                "has_lead_locus_edges": sum(
                    1
                    for rel in loci_snapshot.relationship_rows
                    if rel["rel_type"] == "HAS_LEAD_LOCUS"
                ),
                "cleanup": top_loci_cleanup,
                "stats": loci_snapshot.stats,
                "ingest": loci_ingest,
            }

        after = _collect_counts(db)

        payload = {
            "env_loaded": True,
            "dataset_ids": list(snapshot.collection_metadata.dataset_ids),
            "snapshot": {
                "dataset_count": len(snapshot.collection_metadata.datasets),
                "node_rows": len(snapshot.node_rows),
                "relationship_rows": len(snapshot.relationship_rows),
            },
            "cleanup": {
                "legacy_study_cohort_nodes_deleted": cleanup_deleted,
            },
            "ingest": ingest_summary,
            "top_loci": top_loci_summary,
            "materialization": materialize_summary,
            "neo4j_counts_before": before,
            "neo4j_counts_after": after,
            "neo4j_count_delta": _delta(before, after),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
