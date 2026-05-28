"""Coverage check for legacy task synonym canonicals in taxonomy entities."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_all_legacy_task_synonym_canonicals_exist_as_task_labels() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    synonyms_path = repo_root / "configs/legacy/mappings/task_synonyms.yaml"
    entities_path = repo_root / "src/brain_researcher/semantics/taxonomy/entities.json"

    synonym_rows = yaml.safe_load(synonyms_path.read_text(encoding="utf-8"))
    entities = json.loads(entities_path.read_text(encoding="utf-8"))["entities"]

    task_labels = {
        (entry.get("label") or "").strip().casefold()
        for entry in entities.values()
        if entry.get("type") == "Task"
    }

    canonical_labels = {}
    for row in synonym_rows:
        canonical = (row.get("canonical") or "").strip()
        if canonical:
            canonical_labels.setdefault(canonical.casefold(), canonical)

    missing = sorted(
        canonical_labels[label]
        for label in canonical_labels
        if label not in task_labels
    )

    assert not missing, (
        "Legacy task synonym canonicals missing from Task labels in entities.json: "
        + ", ".join(missing)
    )
