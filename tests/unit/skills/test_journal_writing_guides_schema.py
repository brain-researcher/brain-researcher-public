from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
GUIDES_PATH = (
    ROOT / "skills" / "journal-writing-guidelines" / "references" / "journal_writing_guides.yaml"
)
SCHEMA_PATH = (
    ROOT
    / "skills"
    / "journal-writing-guidelines"
    / "references"
    / "journal_writing_guide_schema.json"
)


def test_all_guides_include_required_fields() -> None:
    guides_payload = yaml.safe_load(GUIDES_PATH.read_text(encoding="utf-8")) or {}
    schema_payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    journals = guides_payload.get("journals", {})
    assert isinstance(journals, dict)
    assert len(journals) == 9

    required_fields = set(schema_payload["$defs"]["journalGuide"]["required"])
    for journal_id, cfg in journals.items():
        assert isinstance(cfg, dict), f"{journal_id} should be a mapping"
        missing = required_fields - set(cfg.keys())
        assert not missing, f"{journal_id} missing fields: {sorted(missing)}"
