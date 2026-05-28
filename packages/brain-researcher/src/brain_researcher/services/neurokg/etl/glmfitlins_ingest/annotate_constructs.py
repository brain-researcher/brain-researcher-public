#!/usr/bin/env python3
"""Generate or reuse contrast annotations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

import requests

MANIFEST = Path("data/etl_cache/glmfitlins_ingest/dataset_manifest.csv")
CONTRASTS = Path("data/etl_cache/glmfitlins_ingest/contrasts_raw.csv")
VERSION_PROMPT = os.environ.get("LLM_PROMPT", "default-prompt")
MODEL_NAME = os.environ.get("LLM_MODEL", "mock-model")
CURRENT_HASH = hashlib.sha1(f"{MODEL_NAME}-{VERSION_PROMPT}".encode()).hexdigest()

ANNOT_DIR = Path("llm_cogitive_function/data/processed_with_direction")
LLM_API_URL = os.environ.get("LLM_API_URL", "http://localhost:8000")


def load_contrasts(contrasts_csv: Path = CONTRASTS) -> dict[str, list[dict[str, str]]]:
    data: dict[str, list[dict[str, str]]] = {}
    if not contrasts_csv.exists():
        return data
    with contrasts_csv.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.setdefault(row["dataset_id"], []).append(row)
    return data


def _classify(contrast_name: str, task_label: str, base_url: str = LLM_API_URL):
    url = f"{base_url.rstrip('/')}/llm/classify"
    try:
        resp = requests.post(
            url,
            json={"contrast_name": contrast_name, "task_label": task_label},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("constructs", data)
    except Exception as e:
        print(f"LLM classify failed for {contrast_name}: {e}")
        return []


def annotate_dataset(
    dataset_id: str,
    spec_hash: str,
    items: list[dict[str, str]],
    annot_dir: Path = ANNOT_DIR,
    base_url: str = LLM_API_URL,
) -> Path:
    out_path = annot_dir / f"{dataset_id}_{spec_hash}_annotations_with_lit.json"
    annotations = []
    for it in items:
        constructs = _classify(it["contrast_name"], it["task_label"], base_url)
        for c in constructs:
            llm = float(c.get("llm_confidence", 0) or 0)
            lit = float(c.get("literature_confidence", 0) or 0)
            c["overall_confidence"] = round(0.7 * llm + 0.3 * lit, 2)
        annotations.append(
            {
                "contrast_name": it["contrast_name"],
                "task_name": it["task_label"],
                "constructs": constructs,
            }
        )
    payload = {"version_hash": CURRENT_HASH, "annotations": annotations}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2)
    return out_path


def run(
    manifest_path: Path = MANIFEST,
    contrasts_csv: Path = CONTRASTS,
    annot_dir: Path = ANNOT_DIR,
    base_url: str = LLM_API_URL,
) -> None:
    contrasts = load_contrasts(contrasts_csv)
    if not manifest_path.exists():
        return
    with manifest_path.open() as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        dataset_id = row["dataset_id"]
        spec_hash = row["spec_hash"]
        ann_path = Path(row["annotation_path"])
        if ann_path.exists():
            try:
                with ann_path.open() as f:
                    data = json.load(f)
                if data.get("version_hash") == CURRENT_HASH:
                    continue
            except Exception:
                pass
        items = contrasts.get(dataset_id, [])
        new_path = annotate_dataset(dataset_id, spec_hash, items, annot_dir, base_url)
        row["annotation_path"] = str(new_path)
    # rewrite manifest with updated annotation paths
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Annotate contrasts with LLM")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--contrasts", type=Path, default=CONTRASTS)
    parser.add_argument("--annot-dir", type=Path, default=ANNOT_DIR)
    parser.add_argument("--llm-url", default=LLM_API_URL)
    args = parser.parse_args()
    run(args.manifest, args.contrasts, args.annot_dir, args.llm_url)
    print("Annotation step complete")
