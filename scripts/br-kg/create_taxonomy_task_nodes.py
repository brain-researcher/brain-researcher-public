#!/usr/bin/env python3
"""Create Task nodes from taxonomy paradigms if missing."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import yaml

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_researcher.services.br_kg.etl.dataset_task_linker import (
    TaskMappingConfig,
    build_task_index,
    load_task_mapping_config,
    normalize_task,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TAXONOMY = Path("configs/taxonomy/exports/task_families_master.yaml")
DEFAULT_TASK_MAPPING = Path("configs/legacy/task_mapping.yaml")

_NONWORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class TaxonomyParadigm:
    family_id: str
    family_label: str
    subfamily_id: str
    subfamily_label: str
    name: str
    aliases: list[str]


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = _NONWORD_RE.sub("-", text).strip("-")
    return text or "unknown"


def _load_taxonomy_paradigms(path: Path) -> list[TaxonomyParadigm]:
    if not path.exists():
        raise FileNotFoundError(f"Taxonomy file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    families = data.get("families") if isinstance(data, dict) else None
    if not isinstance(families, list):
        return []

    paradigms: list[TaxonomyParadigm] = []
    for family in families:
        if not isinstance(family, dict):
            continue
        family_id = str(family.get("id") or "")
        family_label = str(family.get("label") or "")
        subfamilies = family.get("subfamilies") or []
        if not isinstance(subfamilies, list):
            continue
        for subfamily in subfamilies:
            if not isinstance(subfamily, dict):
                continue
            subfamily_id = str(subfamily.get("id") or "")
            subfamily_label = str(subfamily.get("label") or "")
            paradigms_raw = subfamily.get("paradigms") or []
            if not isinstance(paradigms_raw, list):
                continue
            for paradigm in paradigms_raw:
                if not isinstance(paradigm, dict):
                    continue
                name = paradigm.get("name")
                if not name:
                    continue
                aliases = [str(a) for a in (paradigm.get("aliases") or []) if a]
                paradigms.append(
                    TaxonomyParadigm(
                        family_id=family_id,
                        family_label=family_label,
                        subfamily_id=subfamily_id,
                        subfamily_label=subfamily_label,
                        name=str(name),
                        aliases=aliases,
                    )
                )
    return paradigms


def _iter_task_rows(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (t:Task)
    OPTIONAL MATCH (t)-[r:MEASURES]->()
    WITH t, count(r) AS measures_count
    RETURN t.id AS id, t.name AS name, t.alias AS alias, t.aliases AS aliases, measures_count
    """
    return [dict(row) for row in db._run(cypher)]


def _matches_existing(
    paradigm: TaxonomyParadigm,
    index,
    config: TaskMappingConfig,
) -> bool:
    normalized = normalize_task(paradigm.name, config)
    if normalized and index.resolve(normalized):
        return True
    for alias in paradigm.aliases:
        norm_alias = normalize_task(alias, config)
        if norm_alias and index.resolve(norm_alias):
            return True
    return False


def _build_task_props(
    paradigm: TaxonomyParadigm,
    task_id: str,
    *,
    taxonomy_path: Path,
) -> dict:
    aliases = [paradigm.name] + paradigm.aliases
    alias_str = ", ".join(paradigm.aliases)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": task_id,
        "name": paradigm.name,
        "label": paradigm.name,
        "aliases": aliases,
        "alias": alias_str,
        "source": "task_families",
        "family_id": paradigm.family_id,
        "family_label": paradigm.family_label,
        "subfamily_id": paradigm.subfamily_id,
        "subfamily_label": paradigm.subfamily_label,
        "created_from": str(taxonomy_path),
        "created_at": now,
        "updated_at": now,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Task nodes from taxonomy paradigms")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=DEFAULT_TAXONOMY,
        help="Path to task_families_master.yaml",
    )
    parser.add_argument(
        "--task-mapping",
        type=Path,
        default=DEFAULT_TASK_MAPPING,
        help="Path to task_mapping.yaml (for normalization)",
    )
    parser.add_argument(
        "--id-prefix",
        type=str,
        default="tf_paradigm",
        help="Prefix for created Task ids",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit paradigms for testing")
    parser.add_argument("--dry-run", action="store_true", help="Do not write updates")

    args = parser.parse_args()

    config = load_task_mapping_config(args.task_mapping, enable_fuzzy=False)
    paradigms = _load_taxonomy_paradigms(args.taxonomy)
    if args.limit:
        paradigms = paradigms[: args.limit]

    db = require_neo4j_db(preload_cache=False)
    try:
        rows = _iter_task_rows(db)
        index = build_task_index(rows, config)
        logger.info("Loaded %s Task nodes for matching", len(rows))

        created = 0
        skipped = 0

        for paradigm in paradigms:
            if _matches_existing(paradigm, index, config):
                skipped += 1
                continue

            base = _slugify(paradigm.name)
            family = _slugify(paradigm.family_id or "family")
            subfamily = _slugify(paradigm.subfamily_id or "subfamily")
            task_id = f"{args.id_prefix}:{family}__{subfamily}__{base}"
            props = _build_task_props(paradigm, task_id, taxonomy_path=args.taxonomy)

            if args.dry_run:
                logger.info("[DRY RUN] create Task %s (%s)", task_id, paradigm.name)
            else:
                db.create_node("Task", props, node_id=task_id)
            created += 1

        logger.info("Done. created=%s skipped=%s", created, skipped)
    finally:
        db.close()


if __name__ == "__main__":
    main()
