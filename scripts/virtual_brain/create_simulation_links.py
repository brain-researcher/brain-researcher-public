#!/usr/bin/env python3
"""Generate PREDICTS_ACTIVATION edges from Virtual Brain simulations."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Iterable

from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client
from brain_researcher.core.ingestion.loaders.virtual_brain_loader import VirtualBrainLoader

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        default="data/virtual_brain/cache",
        help="Directory containing Virtual Brain simulation cache folders.",
    )
    parser.add_argument(
        "--topk",
        type=int,
        default=20,
        help="Maximum number of regions per simulation to link.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended operations without writing to the graph.",
    )
    return parser.parse_args()


def _confidence_from_metrics(metrics: Dict[str, float]) -> float | None:
    fc = metrics.get("fc_pearson")
    if fc is None:
        return None
    score = (float(fc) + 1.0) / 2.0
    return max(0.0, min(1.0, score))


def generate_links(cache_dir: Path, topk: int, dry_run: bool = False) -> Dict[str, int]:
    loader = VirtualBrainLoader(cache_dir, topk_regions=topk)
    db = None if dry_run else create_graph_client()

    stats = {"edges_created": 0, "simulations_processed": 0, "regions_missing": 0}

    try:
        for report in loader.iter_reports():
            sim_payload = report.get("simulation") or {}
            sim_id = sim_payload.get("id")
            if not sim_id:
                continue
            stats["simulations_processed"] += 1

            region_activity = report.get("region_activity") or []
            region_activity = sorted(
                region_activity, key=lambda item: item.get("mean_activity", 0.0), reverse=True
            )[:topk]

            metrics = sim_payload.get("metrics") or {}
            confidence = _confidence_from_metrics(metrics)

            for rank, entry in enumerate(region_activity, start=1):
                region_id = entry.get("region_id")
                score = entry.get("mean_activity")
                if region_id is None or score is None:
                    continue
                props = {
                    "score": float(score),
                    "rank": rank,
                    "method": sim_payload.get("model", "virtual_brain"),
                    "source": "virtual_brain",
                }
                if confidence is not None:
                    props["confidence"] = confidence

                if dry_run:
                    logger.info("DRY-RUN: %s -> %s %s", sim_id, region_id, json.dumps(props))
                    stats["edges_created"] += 1
                    continue

                if not db.find_nodes("Region", {"id": region_id}):  # type: ignore[attr-defined]
                    stats["regions_missing"] += 1
                    continue

                created = db.create_relationship(  # type: ignore[attr-defined]
                    sim_id,
                    region_id,
                    "PREDICTS_ACTIVATION",
                    props,
                )
                if created:
                    stats["edges_created"] += 1
    finally:
        if db and hasattr(db, "close"):
            db.close()

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    stats = generate_links(Path(args.cache_dir), topk=args.topk, dry_run=args.dry_run)
    logger.info("Simulation linking complete: %s", stats)


if __name__ == "__main__":
    main()
