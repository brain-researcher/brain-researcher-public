from __future__ import annotations

import csv
from pathlib import Path
from typing import Set


def extract_hed_tags(events_tsv: Path) -> Set[str]:
    """Return a lower-cased set of HED tags from a BIDS events.tsv."""

    if not events_tsv.exists():
        return set()

    tags: Set[str] = set()
    with events_tsv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            raw = row.get("HED") or row.get("hed")
            if not raw:
                continue
            for tag in raw.split(","):
                tag = tag.strip()
                if tag:
                    tags.add(tag.lower())
    return tags


# TODO CMD: extend parsing for JSON sidecars or hierarchical HED schemas if needed for richer rules.
