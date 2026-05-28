from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "taxonomy"
    / "build"
    / "aggregate.py"
)
if not MODULE_PATH.exists():
    pytest.skip(
        "taxonomy aggregate build script is not present in this checkout",
        allow_module_level=True,
    )

SPEC = importlib.util.spec_from_file_location("taxonomy_aggregate", MODULE_PATH)
assert SPEC and SPEC.loader
AGG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGG)


def _sample_families() -> list[dict[str, object]]:
    return [
        {
            "id": "tf_working_memory",
            "subfamilies": [
                {
                    "id": "n_back",
                    "paradigms": [
                        {
                            "name": "N-back Task",
                            "aliases": ["n-back", "nback"],
                        }
                    ],
                }
            ],
        }
    ]


def _canonical_entities() -> dict[str, object]:
    return {
        "task:stroop_task": {
            "label": "Stroop Task",
            "type": "Task",
            "alt_labels": ["stroop"],
            "source_aliases": {"taxonomy": ["Stroop Task", "stroop"]},
            "links": {},
            "measures": [],
            "domains": [],
        }
    }


def test_sync_entities_writes_generated_and_report_without_touching_canonical(tmp_path: Path) -> None:
    canonical_path = tmp_path / "entities.json"
    canonical_payload = {"entities": _canonical_entities()}
    canonical_path.write_text(json.dumps(canonical_payload), encoding="utf-8")

    generated_path = tmp_path / "entities.generated.json"
    report_path = tmp_path / "entities_sync_report.json"

    report = AGG.sync_entities_json(
        _sample_families(),
        canonical_path=canonical_path,
        output_path=generated_path,
        report_path=report_path,
        dry_run=False,
        apply=False,
        conflict_strategy="skip",
        source_index_hash="abc123",
    )

    canonical_after = json.loads(canonical_path.read_text(encoding="utf-8"))
    generated_after = json.loads(generated_path.read_text(encoding="utf-8"))

    assert canonical_after == canonical_payload
    assert "task:n_back_task" in generated_after["entities"]
    assert report["summary"]["added"] == 1
    assert report["summary"]["generated_total"] == 2
    assert report["applied_to_canonical"] is False
    assert report_path.exists()


def test_sync_entities_dry_run_only_writes_report(tmp_path: Path) -> None:
    canonical_path = tmp_path / "entities.json"
    canonical_payload = {"entities": _canonical_entities()}
    canonical_path.write_text(json.dumps(canonical_payload), encoding="utf-8")

    generated_path = tmp_path / "entities.generated.json"
    report_path = tmp_path / "entities_sync_report.json"

    report = AGG.sync_entities_json(
        _sample_families(),
        canonical_path=canonical_path,
        output_path=generated_path,
        report_path=report_path,
        dry_run=True,
        apply=True,
        conflict_strategy="skip",
        source_index_hash="abc123",
    )

    canonical_after = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert canonical_after == canonical_payload
    assert not generated_path.exists()
    assert report["dry_run"] is True
    assert report["applied_to_canonical"] is False
    assert report_path.exists()


def test_sync_entities_reports_label_collision(tmp_path: Path) -> None:
    canonical_path = tmp_path / "entities.json"
    canonical_payload = {
        "entities": {
            "task:stroop": {
                "label": "Stroop Task",
                "type": "Task",
                "alt_labels": ["stroop"],
                "source_aliases": {"taxonomy": ["Stroop Task", "stroop"]},
                "links": {},
                "measures": [],
                "domains": [],
            }
        }
    }
    canonical_path.write_text(json.dumps(canonical_payload), encoding="utf-8")

    generated_path = tmp_path / "entities.generated.json"
    report_path = tmp_path / "entities_sync_report.json"

    families = [
        {
            "id": "tf_conflict",
            "subfamilies": [
                {
                    "id": "conflict",
                    "paradigms": [{"name": "Stroop Task", "aliases": []}],
                }
            ],
        }
    ]

    report = AGG.sync_entities_json(
        families,
        canonical_path=canonical_path,
        output_path=generated_path,
        report_path=report_path,
        dry_run=False,
        apply=False,
        conflict_strategy="skip",
        source_index_hash="abc123",
    )

    assert report["summary"]["added"] == 0
    assert report["summary"]["skipped_existing_label"] == 1
    assert report["summary"]["conflicts"] == 1


def test_list_unindexed_family_files(monkeypatch, tmp_path: Path) -> None:
    taxonomy_root = tmp_path / "taxonomy"
    family_dir = taxonomy_root / "families"
    family_dir.mkdir(parents=True)
    (family_dir / "a.yaml").write_text("id: a\n", encoding="utf-8")
    (family_dir / "b.yaml").write_text("id: b\n", encoding="utf-8")

    monkeypatch.setattr(AGG, "TAXONOMY_ROOT", taxonomy_root)
    monkeypatch.setattr(AGG, "FAMILY_DIR", family_dir)

    index_data = {"superfamilies": [{"id": "a", "path": "families/a.yaml"}]}
    unindexed = AGG._list_unindexed_family_files(index_data)
    assert unindexed == ["families/b.yaml"]
