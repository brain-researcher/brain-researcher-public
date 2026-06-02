#!/usr/bin/env python3
"""Backfill evidence/provenance fields for P0 relationships."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.br_kg.quality.confidence import (
    compute_diversity,
    compute_prov_base_conf,
    compute_support_counts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_REL_TYPES = [
    "MAPS_TO",
    "MEASURES",
    "HAS_TASK",
    "USES_TASK",
    "GENERATED_FROM",
    "COMPUTED_WITH",
    "DERIVED_FROM",
    "RELATED_TO",
    "IMPLEMENTS_FAMILY",
    "SUGGESTS_MEASURES",
]

METHOD_MAP = {
    "name_lookup": "string_match",
    "alias_lookup": "string_match",
    "alias_match": "string_match",
    "string_match": "string_match",
    "fuzzy": "fuzzy_match",
    "fuzzy_match": "fuzzy_match",
    "embedding": "embedding_match",
    "embedding_match": "embedding_match",
    "niclip": "embedding_match",
    "assertion": "curated_manual",
    "manual": "curated_manual",
    "curated": "curated_manual",
    "exact": "exact_id",
    "exact_id": "exact_id",
}

SOURCE_MAP = {
    "cognitive_atlas": "major_ontology",
    "cogatlas": "major_ontology",
    "cognitiveatlas": "major_ontology",
    "openneuro": "aggregator_db",
    "openneuro_glmfitlins": "aggregator_db",
    "neurostore": "aggregator_db",
    "niclip": "aggregator_db",
}


def _normalize_method(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = str(value).lower().strip()
    return METHOD_MAP.get(key, key)


def _normalize_source(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = str(value).lower().strip()
    return SOURCE_MAP.get(key, key)


def _derive_evidence_type(props: Dict[str, Any], rel_type: str) -> str:
    for key in ("evidence_type", "type", "relationship"):
        val = props.get(key)
        if val:
            return str(val)
    return rel_type.lower()


def _parse_rel_types(raw: str) -> List[str]:
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(",", " ").split():
        if chunk.strip():
            parts.append(chunk.strip())
    return parts


def backfill(rel_types: List[str], limit: Optional[int], dry_run: bool) -> None:
    db = require_neo4j_db(preload_cache=False)
    logger.info("Connected to graph backend: %s", type(db).__name__)

    try:
        for rel_type in rel_types:
            rels = db.find_relationships(rel_type=rel_type)
            if limit:
                rels = rels[:limit]
            logger.info("Processing %s relationships for %s", len(rels), rel_type)

            updated = 0
            skipped = 0

            for start_id, end_id, props in rels:
                updates: Dict[str, Any] = {}

                provenance = props.get("provenance")
                provenance_map = provenance if isinstance(provenance, dict) else {}
                prov_source = props.get("prov_source") or provenance_map.get("source")
                if not prov_source:
                    prov_source = _normalize_source(props.get("source"))
                prov_method = props.get("prov_method") or provenance_map.get("method")
                if not prov_method:
                    prov_method = _normalize_method(props.get("method"))

                if "prov_source" not in props and prov_source:
                    updates["prov_source"] = prov_source
                if "prov_method" not in props and prov_method:
                    updates["prov_method"] = prov_method

                evidence_items = props.get("evidence") or props.get("supports") or []
                if "support_count_raw" not in props or "support_count_unique" not in props:
                    raw_count, unique_count = compute_support_counts(evidence_items)
                    if raw_count == 0 and unique_count == 0:
                        raw_count = 1
                        unique_count = 1
                    if "support_count_raw" not in props:
                        updates["support_count_raw"] = raw_count
                    if "support_count_unique" not in props:
                        updates["support_count_unique"] = unique_count

                if "source_diversity" not in props or "evidence_type_diversity" not in props:
                    source_div, type_div = compute_diversity(evidence_items)
                    if source_div == 0 and prov_source:
                        source_div = 1
                    evidence_type = _derive_evidence_type(props, rel_type)
                    if type_div == 0 and evidence_type:
                        type_div = 1
                    if "source_diversity" not in props:
                        updates["source_diversity"] = source_div
                    if "evidence_type_diversity" not in props:
                        updates["evidence_type_diversity"] = type_div
                    if "evidence_type" not in props and evidence_type:
                        updates["evidence_type"] = evidence_type

                if "prov_base_conf" not in props:
                    base_conf = compute_prov_base_conf(prov_source, prov_method)
                    updates["prov_base_conf"] = base_conf

                if not updates:
                    skipped += 1
                    continue

                updates["computed_at"] = datetime.now(timezone.utc).isoformat()

                if dry_run:
                    logger.info(
                        "[DRY RUN] %s (%s -> %s) updates=%s",
                        rel_type,
                        start_id,
                        end_id,
                        list(updates.keys()),
                    )
                else:
                    db.update_relationship(start_id, end_id, rel_type, updates)
                updated += 1

            logger.info("Finished %s: updated=%s skipped=%s", rel_type, updated, skipped)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill provenance/evidence fields for confidence scoring")
    parser.add_argument(
        "--rel-types",
        type=str,
        default=" ".join(DEFAULT_REL_TYPES),
        help="Relationship types to update (comma or space separated)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit relationships per type")
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates")

    args = parser.parse_args()
    rel_types = _parse_rel_types(args.rel_types)

    backfill(rel_types, args.limit, args.dry_run)


if __name__ == "__main__":
    main()
