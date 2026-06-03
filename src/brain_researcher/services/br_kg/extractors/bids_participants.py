from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from brain_researcher.config.paths import resolve_from_config


LEXICA_DIR = resolve_from_config("lexica")

# TODO CMD: expand diagnosis/medication/instrument lexica before large-scale scoring
#           (edit files under configs/lexica/ then rerun build_onvoc_mapping_rules.py).


def load_participant_profile(path: Path) -> Dict[str, object]:
    """Return a normalised phenotype profile from a BIDS participants.tsv file."""

    if not path.exists():
        raise FileNotFoundError(f"participants.tsv not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        try:
            first_row = next(reader)
        except StopIteration as exc:  # empty file
            raise ValueError("participants.tsv is empty") from exc

    profile: Dict[str, object] = {}
    profile["age"] = _to_float(first_row.get("age"))
    profile["sex"] = _normalise_sex(first_row.get("sex"))

    diagnosis_text = first_row.get("diagnosis", "")
    profile["diagnosis"] = _match_lexicon("diagnosis.yaml", diagnosis_text)

    medication_text = first_row.get("medication", "")
    profile["medication"] = _match_lexicon("medications.yaml", medication_text)

    instrument_text = first_row.get("instrument", "")
    profile["instrument"] = _match_lexicon("instruments.yaml", instrument_text)

    return profile


def _to_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except ValueError:
        return None


def _normalise_sex(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"M", "MALE"}:
        return "M"
    if text in {"F", "FEMALE"}:
        return "F"
    return "X"


def _match_lexicon(filename: str, text: str) -> List[str]:
    records = _load_lexicon(filename)
    lower = str(text or "").lower()
    matches: List[str] = []
    for label, entry in records.items():
        synonyms = entry.get("synonyms", [])
        for synonym in synonyms:
            if re.search(rf"\b{re.escape(synonym.lower())}\b", lower):
                matches.append(label)
                break
    return sorted(set(matches))


@lru_cache(maxsize=None)
def _load_lexicon(filename: str) -> Dict[str, Dict[str, object]]:
    path = LEXICA_DIR / filename
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
