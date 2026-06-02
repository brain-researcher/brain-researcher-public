#!/usr/bin/env python3
"""Parse FitLins statsmodel specs to extract contrasts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

MANIFEST = Path("data/etl_cache/glmfitlins_ingest/dataset_manifest.csv")
OUT_CSV = Path("data/etl_cache/glmfitlins_ingest/contrasts_raw.csv")


def find_contrasts(obj: Any) -> list[str]:
    """Recursively collect contrast names from a statsmodel spec."""
    results: list[str] = []
    if isinstance(obj, dict):
        if "Contrasts" in obj and isinstance(obj["Contrasts"], list):
            for c in obj["Contrasts"]:
                if isinstance(c, dict) and "Name" in c:
                    results.append(c["Name"])
        for v in obj.values():
            results.extend(find_contrasts(v))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_contrasts(item))
    return results


def parse_spec(spec_path: Path) -> list[str]:
    data = json.loads(spec_path.read_text())
    return find_contrasts(data)


def parse_statsmodels(
    manifest_path: Path = MANIFEST, out_csv: Path = OUT_CSV
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not manifest_path.exists():
        return rows
    with manifest_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            spec_path = Path(row["spec_path"])
            dataset_id = row["dataset_id"]
            task_label = spec_path.stem.replace(dataset_id + "-", "").replace(
                "_specs", ""
            )
            try:
                contrast_names = parse_spec(spec_path)
            except Exception as e:
                print(f"Failed to parse {spec_path}: {e}")
                continue
            for name in contrast_names:
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "contrast_name": name,
                        "task_label": task_label,
                    }
                )
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, ["dataset_id", "contrast_name", "task_label"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse statsmodel specs")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    args = parser.parse_args()
    contrasts = parse_statsmodels(args.manifest, args.out)
    print(f"Parsed {len(contrasts)} contrasts")
