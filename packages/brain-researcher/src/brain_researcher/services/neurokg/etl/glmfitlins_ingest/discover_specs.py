#!/usr/bin/env python3
"""Discover FitLins statsmodel specs and existing annotations."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

# import pdb; pdb.set_trace()
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
)

from brain_researcher.services.neurokg.utils.hashing import sha1sum

STATS_DIR = Path("llm_cogitive_function/openneuro_glmfitlins/statsmodel_specs")
ANNOT_DIR = Path("llm_cogitive_function/data/processed_with_direction")
MANIFEST = Path("data/etl_cache/glmfitlins_ingest/dataset_manifest.csv")


def discover_specs(
    stats_dir: Path = STATS_DIR,
    annot_dir: Path = ANNOT_DIR,
    manifest_path: Path = MANIFEST,
) -> list[dict[str, str]]:
    rows = []
    if not stats_dir.exists():
        return rows
    for spec in stats_dir.rglob("*.json"):
        dataset_id = spec.parent.name
        spec_hash = sha1sum(spec)
        ann_path = annot_dir / f"{dataset_id}_{spec_hash}_annotations_with_lit.json"
        rows.append(
            {
                "dataset_id": dataset_id,
                "spec_path": str(spec),
                "spec_hash": spec_hash,
                "annotation_path": str(ann_path) if ann_path.exists() else "",
            }
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, ["dataset_id", "spec_path", "spec_hash", "annotation_path"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover statsmodel specs")
    parser.add_argument("--stats-dir", type=Path, default=STATS_DIR)
    parser.add_argument("--annot-dir", type=Path, default=ANNOT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    discovered = discover_specs(args.stats_dir, args.annot_dir, args.manifest)
    print(f"Discovered {len(discovered)} specs")
