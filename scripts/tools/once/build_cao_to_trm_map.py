#!/usr/bin/env python3
"""Generate CAO→TRM mapping based on taxonomy entities and TRM synonyms."""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process


# TODO: these files are all examples, please revise and see what should we use
# TODO: use full set of information in /app/brain_researcher/configs/neurokg to build this mapping
TAXONOMY = Path("brain_researcher/semantics/taxonomy/entities.json")
TRM_SYNS = Path("configs/legacy/mappings/concept_synonyms.yaml")
OUTPUT   = Path("configs/legacy/mappings/cao_to_trm.yaml")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.lower().strip().split())


def load_trm_lookup() -> dict[str, str]:
    entries = yaml.safe_load(TRM_SYNS.read_text(encoding="utf-8")) or []
    lookup: dict[str, str] = {}
    for entry in entries:
        canonical = normalize(entry.get("canonical"))
        concept_id = entry.get("concept_id")
        for alias in entry.get("synonyms") or []:
            key = normalize(alias)
            if key and concept_id:
                lookup.setdefault(key, concept_id)
        if canonical and concept_id:
            lookup.setdefault(canonical, concept_id)
    return lookup


def load_cao_labels() -> dict[str, list[str]]:
    data = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    entities = data.get("entities", {})
    out: dict[str, list[str]] = {}
    for item in entities.values():
        links = item.get("links") or {}
        cao_id = links.get("cogat")
        if isinstance(cao_id, str) and cao_id.upper().startswith("CAO_"):
            labels = [item.get("label")] + (item.get("alt_labels") or [])
            out[cao_id.upper()] = [normalize(lbl) for lbl in labels if normalize(lbl)]
    return out


def main() -> None:
    trm_lookup = load_trm_lookup()
    cao_labels = load_cao_labels()
    trm_keys = list(trm_lookup.keys())
    rows: list[dict] = []

    for cao_id, labels in cao_labels.items():
        matched = False
        for label in labels:
            if label in trm_lookup:
                rows.append({
                    "cao_id": cao_id,
                    "trm_id": trm_lookup[label],
                    "method": "exact",
                    "confidence": 0.99,
                    "label": label,
                })
                matched = True
                break
        if matched or not labels:
            continue
        guess, score, _ = process.extractOne(labels[0], trm_keys, scorer=fuzz.WRatio) or (None, 0, None)
        if guess and score >= 90:
            rows.append({
                "cao_id": cao_id,
                "trm_id": trm_lookup[guess],
                "method": "fuzzy",
                "confidence": round(score / 100, 2),
                "label": labels[0],
                "matched_label": guess,
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump(rows, OUTPUT.open("w", encoding="utf-8"))
    print(f"Wrote {len(rows)} CAO→TRM entries to {OUTPUT}")


if __name__ == "__main__":
    main()
