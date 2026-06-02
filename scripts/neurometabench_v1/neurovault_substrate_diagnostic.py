#!/usr/bin/env python3
"""NeuroVault substrate coverage diagnostics for NeuroMetaBench cases.

This experiment answers a narrow, auditable question before any BR reasoning is
evaluated: given local PubGet metadata and NeuroVault extraction tables, which
NeuroMetaBench meta-analysis papers and ground-truth included studies have a
NeuroVault collection/image substrate available?

It does not score BR. It estimates the NeuroVault substrate ceiling that BR can
build on top of.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import DEFAULT_CASES_PATH, load_case_records, sort_pmids, write_jsonl


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PUBGET_DIR = REPO_ROOT / "data" / "pubget" / "fmri_oa_1990_2025_dedup" / "subset_allArticles_extractedData"
DEFAULT_METADATA_CSV = DEFAULT_PUBGET_DIR / "metadata.csv"
DEFAULT_NEUROVAULT_COLLECTIONS_CSV = DEFAULT_PUBGET_DIR / "neurovault_collections.csv"
DEFAULT_NEUROVAULT_IMAGES_CSV = DEFAULT_PUBGET_DIR / "neurovault_images.csv"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _normalize_pmcid(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.removeprefix("PMC").removeprefix("pmc")
    return "".join(ch for ch in text if ch.isdigit())


def _normalize_pmid(value: Any) -> str:
    text = str(value or "").strip()
    return "".join(ch for ch in text if ch.isdigit())


def load_pmid_to_pmcid(metadata_csv: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in _read_csv(metadata_csv):
        pmid = _normalize_pmid(row.get("pmid"))
        pmcid = _normalize_pmcid(row.get("pmcid"))
        if pmid and pmcid:
            mapping.setdefault(pmid, pmcid)
    return mapping


def load_neurovault_links(collections_csv: Path, images_csv: Path) -> dict[str, dict[str, list[str]]]:
    links: dict[str, dict[str, list[str]]] = {}
    for row in _read_csv(collections_csv):
        pmcid = _normalize_pmcid(row.get("pmcid"))
        collection_id = str(row.get("collection_id") or "").strip()
        if pmcid and collection_id:
            links.setdefault(pmcid, {"collection_ids": [], "image_ids": []})["collection_ids"].append(collection_id)
    for row in _read_csv(images_csv):
        pmcid = _normalize_pmcid(row.get("pmcid"))
        image_id = str(row.get("image_id") or "").strip()
        if pmcid and image_id:
            links.setdefault(pmcid, {"collection_ids": [], "image_ids": []})["image_ids"].append(image_id)
    for value in links.values():
        value["collection_ids"] = sorted(set(value["collection_ids"]), key=lambda x: (int(x), x) if x.isdigit() else (10**20, x))
        value["image_ids"] = sorted(set(value["image_ids"]), key=lambda x: (int(x), x) if x.isdigit() else (10**20, x))
    return links


def _rate(num: int, denom: int) -> float | None:
    return round(num / denom, 6) if denom else None


def case_diagnostic(
    case: dict[str, Any],
    *,
    pmid_to_pmcid: dict[str, str],
    neurovault_links: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    meta_pmid = _normalize_pmid(case.get("meta_pmid"))
    meta_pmcid = _normalize_pmcid(case.get("pmcid")) or pmid_to_pmcid.get(meta_pmid, "")
    meta_links = neurovault_links.get(meta_pmcid, {"collection_ids": [], "image_ids": []}) if meta_pmcid else {"collection_ids": [], "image_ids": []}

    gt_pmids = sort_pmids(case.get("gt_pmids", []))
    gt_rows: list[dict[str, Any]] = []
    gt_with_pmcid = 0
    gt_with_collection = 0
    gt_with_image = 0
    for pmid in gt_pmids:
        pmcid = pmid_to_pmcid.get(_normalize_pmid(pmid), "")
        links = neurovault_links.get(pmcid, {"collection_ids": [], "image_ids": []}) if pmcid else {"collection_ids": [], "image_ids": []}
        has_collection = bool(links["collection_ids"])
        has_image = bool(links["image_ids"])
        gt_with_pmcid += int(bool(pmcid))
        gt_with_collection += int(has_collection)
        gt_with_image += int(has_image)
        if pmcid or has_collection or has_image:
            gt_rows.append(
                {
                    "pmid": pmid,
                    "pmcid": pmcid or None,
                    "collection_ids": links["collection_ids"],
                    "image_ids": links["image_ids"],
                }
            )

    return {
        "case_id": case.get("case_id"),
        "meta_pmid": meta_pmid,
        "topic": case.get("topic"),
        "route": case.get("route"),
        "primary_task_layer": case.get("primary_task_layer"),
        "task_type": case.get("task_type"),
        "meta_pmcid": meta_pmcid or None,
        "meta_has_neurovault_collection": bool(meta_links["collection_ids"]),
        "meta_has_neurovault_image": bool(meta_links["image_ids"]),
        "meta_neurovault_collection_ids": meta_links["collection_ids"],
        "meta_neurovault_image_ids": meta_links["image_ids"],
        "n_gt": len(gt_pmids),
        "n_gt_with_pmcid": gt_with_pmcid,
        "n_gt_with_neurovault_collection": gt_with_collection,
        "n_gt_with_neurovault_image": gt_with_image,
        "gt_pmcid_coverage": _rate(gt_with_pmcid, len(gt_pmids)),
        "gt_neurovault_collection_coverage": _rate(gt_with_collection, len(gt_pmids)),
        "gt_neurovault_image_coverage": _rate(gt_with_image, len(gt_pmids)),
        "covered_gt_examples": gt_rows[:20],
    }


def _avg(values: list[Any]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return round(mean(nums), 6) if nums else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_layer.setdefault(str(row.get("primary_task_layer") or "unknown"), []).append(row)

    def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        n_gt = sum(int(row.get("n_gt") or 0) for row in items)
        n_gt_pmcid = sum(int(row.get("n_gt_with_pmcid") or 0) for row in items)
        n_gt_collections = sum(int(row.get("n_gt_with_neurovault_collection") or 0) for row in items)
        n_gt_images = sum(int(row.get("n_gt_with_neurovault_image") or 0) for row in items)
        return {
            "n_cases": len(items),
            "n_cases_with_gt": sum(1 for row in items if int(row.get("n_gt") or 0) > 0),
            "n_cases_meta_pmcid": sum(1 for row in items if row.get("meta_pmcid")),
            "n_cases_meta_neurovault_collection": sum(1 for row in items if row.get("meta_has_neurovault_collection")),
            "n_cases_meta_neurovault_image": sum(1 for row in items if row.get("meta_has_neurovault_image")),
            "micro_gt_pmcid_coverage": _rate(n_gt_pmcid, n_gt),
            "micro_gt_neurovault_collection_coverage": _rate(n_gt_collections, n_gt),
            "micro_gt_neurovault_image_coverage": _rate(n_gt_images, n_gt),
            "macro_gt_pmcid_coverage": _avg([row.get("gt_pmcid_coverage") for row in items]),
            "macro_gt_neurovault_collection_coverage": _avg([row.get("gt_neurovault_collection_coverage") for row in items]),
            "macro_gt_neurovault_image_coverage": _avg([row.get("gt_neurovault_image_coverage") for row in items]),
        }

    return {
        "overall": _summary(rows),
        "by_layer": {layer: _summary(items) for layer, items in sorted(by_layer.items())},
        "routes": dict(Counter(str(row.get("route") or "unknown") for row in rows)),
    }


def run_diagnostic(
    *,
    cases_path: Path,
    metadata_csv: Path,
    neurovault_collections_csv: Path,
    neurovault_images_csv: Path,
    output_jsonl: Path,
    output_summary: Path,
) -> dict[str, Any]:
    pmid_to_pmcid = load_pmid_to_pmcid(metadata_csv)
    neurovault_links = load_neurovault_links(neurovault_collections_csv, neurovault_images_csv)
    rows = [
        case_diagnostic(case, pmid_to_pmcid=pmid_to_pmcid, neurovault_links=neurovault_links)
        for case in load_case_records(cases_path)
    ]
    summary = summarize(rows)
    write_jsonl(rows, output_jsonl)
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {
        "output_jsonl": str(output_jsonl),
        "output_summary": str(output_summary),
        "n_cases": len(rows),
        "n_metadata_pmids_with_pmcid": len(pmid_to_pmcid),
        "n_pmcids_with_neurovault_links": len(neurovault_links),
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--metadata-csv", type=Path, default=DEFAULT_METADATA_CSV)
    parser.add_argument("--neurovault-collections-csv", type=Path, default=DEFAULT_NEUROVAULT_COLLECTIONS_CSV)
    parser.add_argument("--neurovault-images-csv", type=Path, default=DEFAULT_NEUROVAULT_IMAGES_CSV)
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("benchmarks/neurometabench/experiments/neurovault_substrate_coverage.jsonl"),
    )
    parser.add_argument(
        "--output-summary",
        type=Path,
        default=Path("benchmarks/neurometabench/experiments/neurovault_substrate_coverage_summary.json"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run_diagnostic(
                cases_path=args.cases,
                metadata_csv=args.metadata_csv,
                neurovault_collections_csv=args.neurovault_collections_csv,
                neurovault_images_csv=args.neurovault_images_csv,
                output_jsonl=args.output_jsonl,
                output_summary=args.output_summary,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
