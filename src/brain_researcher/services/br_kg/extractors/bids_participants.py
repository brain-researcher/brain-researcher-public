from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

import yaml

from brain_researcher.config.paths import resolve_from_config

LEXICA_DIR = resolve_from_config("lexica")

# TODO CMD: expand diagnosis/medication/instrument lexica before large-scale scoring
#           (edit files under configs/lexica/ then rerun build_onvoc_mapping_rules.py).


def load_participant_profile(path: Path) -> dict[str, object]:
    """Return a normalised phenotype profile from a BIDS participants.tsv file."""

    if not path.exists():
        raise FileNotFoundError(f"participants.tsv not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        try:
            first_row = next(reader)
        except StopIteration as exc:  # empty file
            raise ValueError("participants.tsv is empty") from exc

    profile: dict[str, object] = {}
    profile["age"] = _to_float(first_row.get("age"))
    profile["sex"] = _normalise_sex(first_row.get("sex"))

    diagnosis_text = first_row.get("diagnosis", "")
    profile["diagnosis"] = _match_lexicon("diagnosis.yaml", diagnosis_text)

    medication_text = first_row.get("medication", "")
    profile["medication"] = _match_lexicon("medications.yaml", medication_text)

    instrument_text = first_row.get("instrument", "")
    profile["instrument"] = _match_lexicon("instruments.yaml", instrument_text)

    return profile


def _to_float(value: object) -> float | None:
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


def _match_lexicon(filename: str, text: str) -> list[str]:
    records = _load_lexicon(filename)
    lower = str(text or "").lower()
    matches: list[str] = []
    for label, entry in records.items():
        synonyms = entry.get("synonyms", [])
        for synonym in synonyms:
            if re.search(rf"\b{re.escape(synonym.lower())}\b", lower):
                matches.append(label)
                break
    return sorted(set(matches))


@cache
def _load_lexicon(filename: str) -> dict[str, dict[str, object]]:
    path = LEXICA_DIR / filename
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
