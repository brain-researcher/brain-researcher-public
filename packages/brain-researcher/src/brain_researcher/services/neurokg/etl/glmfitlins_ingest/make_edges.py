#!/usr/bin/env python3
"""Create CSVs for Neo4j bulk import."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

MANIFEST = Path("data/etl_cache/glmfitlins_ingest/dataset_manifest.csv")
CONTRASTS_RAW = Path("data/etl_cache/glmfitlins_ingest/contrasts_raw.csv")
OUT_DIR = Path("data/etl_cache/glmfitlins_ingest")


def load_datasets(manifest_path: Path = MANIFEST) -> dict[str, dict[str, Any]]:
    datasets: dict[str, dict[str, Any]] = {}
    if not manifest_path.exists():
        return datasets
    with manifest_path.open() as f:
        for row in csv.DictReader(f):
            datasets[row["dataset_id"]] = {
                "spec_hash": row["spec_hash"],
                "annotation_path": row["annotation_path"],
                "spec_path": row["spec_path"],
            }
    return datasets


def make_csvs(
    manifest_path: Path = MANIFEST,
    contrasts_path: Path = CONTRASTS_RAW,
    out_dir: Path = OUT_DIR,
) -> None:
    datasets = load_datasets(manifest_path)
    if not datasets:
        return

    # datasets.csv
    dataset_rows = []
    for ds, info in datasets.items():
        details_path = Path(info["spec_path"]).parent / f"{ds}_basic-details.json"
        doi = ""
        if details_path.exists():
            try:
                details = json.loads(details_path.read_text())
                # take first cite link if available
                tasks = details.get("Tasks", {})
                for t in tasks.values():
                    links = t.get("cite_links")
                    if links:
                        doi = links[0]
                        break
            except Exception:
                pass
        dataset_rows.append(
            {"id": ds, "name": ds, "doi": doi, "spec_hash": info["spec_hash"]}
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "datasets.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, ["id", "name", "doi", "spec_hash"])
        writer.writeheader()
        writer.writerows(dataset_rows)

    # contrasts.csv
    contrast_rows = []
    if contrasts_path.exists():
        with contrasts_path.open() as f:
            for row in csv.DictReader(f):
                contrast_rows.append(row)
    with (out_dir / "contrasts.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, ["dataset_id", "contrast_name", "task_label"])
        writer.writeheader()
        writer.writerows(contrast_rows)

    # measures_edges.csv
    edge_rows = []
    for ds, info in datasets.items():
        ann_path = Path(info["annotation_path"])
        if not ann_path.exists():
            continue
        try:
            data = json.loads(ann_path.read_text())
            version = data.get("version_hash", "")
            annotations = data.get(
                "annotations", data if isinstance(data, list) else []
            )
        except Exception:
            continue
        for ann in annotations:
            c_name = ann.get("contrast_name")
            for concept in ann.get("constructs", []):
                edge_rows.append(
                    {
                        "dataset_id": ds,
                        "contrast_name": c_name,
                        "concept_id": concept.get("id"),
                        "direction": concept.get("direction"),
                        "llm_confidence": concept.get("llm_confidence"),
                        "literature_confidence": concept.get("literature_confidence"),
                        "overall_confidence": concept.get("overall_confidence"),
                        "version_hash": version,
                    }
                )
    with (out_dir / "measures_edges.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            [
                "dataset_id",
                "contrast_name",
                "concept_id",
                "direction",
                "llm_confidence",
                "literature_confidence",
                "overall_confidence",
                "version_hash",
            ],
        )
        writer.writeheader()
        writer.writerows(edge_rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create CSVs for Neo4j import")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--contrasts", type=Path, default=CONTRASTS_RAW)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    make_csvs(args.manifest, args.contrasts, args.out_dir)
    print("Edge CSVs created")
