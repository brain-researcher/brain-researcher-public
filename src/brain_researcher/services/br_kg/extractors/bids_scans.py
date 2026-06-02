from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List


def extract_modalities(scans_tsv: Path) -> List[Dict[str, object]]:
    """Return modality descriptors from BIDS scans.tsv."""

    if not scans_tsv.exists():
        return []

    modalities: List[Dict[str, object]] = []
    with scans_tsv.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            modality = row.get("modality") or row.get("Modality")
            if not modality:
                continue
            entry: Dict[str, object] = {"modality": modality}
            manufacturer = row.get("manufacturer") or row.get("Manufacturer")
            if manufacturer:
                entry["manufacturer"] = manufacturer
            modalities.append(entry)
    return modalities


# TODO CMD: capture additional columns (e.g., sequence, flip angle) if future modality_rules require them.
