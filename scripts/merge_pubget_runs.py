#!/usr/bin/env python
"""Merge multiple pubget runs by PMCID, keeping the first occurrence per PMCID.

This script is designed for combining overlapping pubget queries. It:
  - uses metadata.csv to compute new PMCIDs for each run
  - writes merged CSVs for all known extracted files
  - preserves all rows for a PMCID within the first run that contains it
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set

EXPECTED_FILES = [
    "metadata.csv",
    "text.csv",
    "coordinates.csv",
    "authors.csv",
    "links.csv",
    "tables.csv",
    "coordinate_space.csv",
    "neurovault_images.csv",
    "neurovault_collections.csv",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_pmcids(metadata_csv: Path) -> Set[str]:
    _configure_csv_limits()
    with metadata_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        out: Set[str] = set()
        for row in reader:
            pmcid = (row.get("pmcid") or "").strip()
            if pmcid:
                out.add(pmcid)
        return out


def _iter_rows(csv_path: Path) -> Iterable[Dict[str, str]]:
    _configure_csv_limits()
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def _configure_csv_limits() -> None:
    """Raise CSV field size limit to accommodate large PMC bodies."""
    max_int = sys.maxsize
    while True:
        try:
            csv.field_size_limit(max_int)
            return
        except OverflowError:
            max_int = max_int // 10
            if max_int < 1024 * 1024:
                raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-alias", required=True, help="Existing pubget alias to treat as base.")
    ap.add_argument(
        "--input-alias",
        action="append",
        required=True,
        help="Additional pubget alias to merge (can be passed multiple times).",
    )
    ap.add_argument(
        "--out-alias",
        required=True,
        help="Output alias to write under data/pubget/<out-alias>.",
    )
    args = ap.parse_args()

    root = _repo_root()
    out_root = root / "data" / "pubget" / args.out_alias
    out_extracted = out_root / "subset_allArticles_extractedData"
    out_extracted.mkdir(parents=True, exist_ok=True)

    run_aliases = [args.base_alias] + args.input_alias

    included_pmcids: Set[str] = set()
    run_stats: List[Dict[str, int]] = []

    writers: Dict[str, csv.DictWriter] = {}
    handles: Dict[str, object] = {}
    files_written: Set[str] = set()
    row_counts: Dict[str, int] = {name: 0 for name in EXPECTED_FILES}

    for alias in run_aliases:
        run_dir = root / "data" / "pubget" / alias / "subset_allArticles_extractedData"
        metadata_csv = run_dir / "metadata.csv"
        if not metadata_csv.exists():
            raise SystemExit(f"Missing metadata.csv for alias: {alias}")

        run_pmcids = _load_pmcids(metadata_csv)
        new_pmcids = run_pmcids - included_pmcids
        run_stats.append(
            {
                "pmcids_total": len(run_pmcids),
                "pmcids_new": len(new_pmcids),
            }
        )

        if not new_pmcids:
            included_pmcids |= run_pmcids
            continue

        for fname in EXPECTED_FILES:
            src = run_dir / fname
            if not src.exists():
                continue

            if fname not in writers:
                # Initialize writer with header from the first source file that exists.
                with src.open(newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    header = reader.fieldnames or []
                out_path = out_extracted / fname
                out_file = out_path.open("w", newline="", encoding="utf-8")
                writer = csv.DictWriter(out_file, fieldnames=header)
                writer.writeheader()
                writers[fname] = writer
                handles[fname] = out_file
                files_written.add(fname)

            writer = writers[fname]
            for row in _iter_rows(src):
                pmcid = (row.get("pmcid") or "").strip()
                if pmcid and pmcid in new_pmcids:
                    writer.writerow(row)
                    row_counts[fname] += 1

        included_pmcids |= new_pmcids

    # Close output files.
    for handle in handles.values():
        handle.close()

    info = {
        "base_alias": args.base_alias,
        "input_aliases": args.input_alias,
        "unique_pmcids": len(included_pmcids),
        "files_written": sorted(files_written),
        "row_counts": row_counts,
        "run_stats": run_stats,
    }
    (out_root / "merge_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    print(f"Done. Output: {out_root}")
    print(f"Unique PMCIDs: {len(included_pmcids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
