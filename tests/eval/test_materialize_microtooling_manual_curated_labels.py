"""Regression tests for materializing adjudicated MicroTooling labels."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "materialize_microtooling_manual_curated_labels.py"
SPEC = importlib.util.spec_from_file_location(
    "materialize_microtooling_manual_curated_labels",
    SCRIPT_PATH,
)
assert SPEC is not None
assert SPEC.loader is not None
materializer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = materializer
SPEC.loader.exec_module(materializer)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _patch_catalog(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        materializer,
        "get_capability_index",
        lambda: SimpleNamespace(by_id={"tool.a": object(), "tool.b": object(), "tool.c": object()}),
    )
    monkeypatch.setattr(
        materializer,
        "load_tool_families",
        lambda: {"family.alpha": object()},
    )


def test_materialize_accepts_only_confident_audited_rows(tmp_path: Path, monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)
    source = tmp_path / "source.jsonl"
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(
        source,
        [
            {
                "schema_version": "br.tool_routing_exact_labels.curated.v1",
                "task_id": "A-001",
                "category": "Alpha",
                "curation_status": "curated_candidate",
                "label_source": "candidate",
                "exact_labels": {
                    "expected_tool_ids": ["tool.a"],
                    "acceptable_tool_ids": [],
                    "expected_family_ids": [],
                    "expected_sequence_tool_ids": [],
                },
            },
            {
                "schema_version": "br.tool_routing_exact_labels.curated.v1",
                "task_id": "A-002",
                "category": "Alpha",
                "curation_status": "curated_candidate",
                "label_source": "candidate",
                "exact_labels": {
                    "expected_tool_ids": ["tool.b"],
                    "acceptable_tool_ids": [],
                    "expected_family_ids": [],
                    "expected_sequence_tool_ids": [],
                },
            },
        ],
    )
    _write_jsonl(
        audit,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "decision": "accept",
                "confidence": "high",
                "notes": "primary tool matches query",
            },
            {
                "task_id": "A-002",
                "category": "Alpha",
                "decision": "accept",
                "confidence": "low",
                "notes": "uncertain",
            },
        ],
    )

    payload = materializer.materialize_manual_curated(
        source_jsonl=source,
        audit_jsonls=[audit],
        min_confidence="medium",
        require_all_accept=True,
    )

    assert [row["task_id"] for row in payload["rows"]] == ["A-001"]
    row = payload["rows"][0]
    assert row["curation_status"] == "manual_curated"
    assert row["source_curation_status"] == "curated_candidate"
    assert row["manual_audit"]["audit_count"] == 1
    assert payload["summary"]["accepted_rows"] == 1
    assert payload["summary"]["exclusion_reasons"] == {"not_accepted:accept": 1}


def test_materialize_applies_corrected_exact_labels(tmp_path: Path, monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)
    source = tmp_path / "source.jsonl"
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(
        source,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "curation_status": "curated_candidate",
                "label_source": "candidate",
                "exact_labels": {
                    "expected_tool_ids": ["tool.a"],
                    "acceptable_tool_ids": [],
                    "expected_family_ids": [],
                    "expected_sequence_tool_ids": [],
                },
            }
        ],
    )
    _write_jsonl(
        audit,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "decision": "accept",
                "confidence": "medium",
                "notes": "accept with better primary",
                "corrected_exact_labels": {
                    "expected_tool_ids": ["tool.c"],
                    "acceptable_tool_ids": ["tool.a"],
                    "expected_family_ids": ["family.alpha"],
                    "expected_sequence_tool_ids": [],
                },
            }
        ],
    )

    payload = materializer.materialize_manual_curated(
        source_jsonl=source,
        audit_jsonls=[audit],
        min_confidence="medium",
        require_all_accept=True,
    )

    assert payload["summary"]["invalid_label_count"] == 0
    assert payload["rows"][0]["exact_labels"] == {
        "expected_tool_ids": ["tool.c"],
        "acceptable_tool_ids": ["tool.a"],
        "expected_family_ids": ["family.alpha"],
        "expected_sequence_tool_ids": [],
    }


def test_materialize_rejects_invalid_corrections(tmp_path: Path, monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)
    source = tmp_path / "source.jsonl"
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(
        source,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "curation_status": "curated_candidate",
                "label_source": "candidate",
                "exact_labels": {"expected_tool_ids": ["tool.a"]},
            }
        ],
    )
    _write_jsonl(
        audit,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "decision": "accept",
                "confidence": "high",
                "notes": "bad correction",
                "corrected_exact_labels": {"expected_tool_ids": ["missing.tool"]},
            }
        ],
    )

    payload = materializer.materialize_manual_curated(
        source_jsonl=source,
        audit_jsonls=[audit],
        min_confidence="medium",
        require_all_accept=True,
    )

    assert payload["rows"] == []
    assert payload["summary"]["invalid_label_count"] == 1
    assert payload["summary"]["exclusion_reasons"]["invalid_label_after_correction"] == 1


def test_materialize_latest_pass_can_promote_corrected_review_row(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _patch_catalog(monkeypatch)
    source = tmp_path / "source.jsonl"
    pass1 = tmp_path / "pass1.jsonl"
    pass2 = tmp_path / "pass2.jsonl"
    _write_jsonl(
        source,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "curation_status": "curated_candidate",
                "label_source": "candidate",
                "exact_labels": {"expected_tool_ids": ["tool.a"]},
            }
        ],
    )
    _write_jsonl(
        pass1,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "decision": "needs_review",
                "confidence": "high",
                "notes": "too broad before correction",
            }
        ],
    )
    _write_jsonl(
        pass2,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "audit_pass": 2,
                "decision": "accept",
                "confidence": "medium",
                "notes": "corrected labels are focused",
                "corrected_exact_labels": {"expected_tool_ids": ["tool.b"]},
            }
        ],
    )

    payload = materializer.materialize_manual_curated(
        source_jsonl=source,
        audit_jsonls=[pass1, pass2],
        min_confidence="medium",
        require_all_accept=True,
        decision_policy="latest_pass",
    )

    assert [row["task_id"] for row in payload["rows"]] == ["A-001"]
    assert payload["rows"][0]["exact_labels"]["expected_tool_ids"] == ["tool.b"]
    assert payload["rows"][0]["manual_audit"]["decision_policy"] == "latest_pass"
    assert payload["rows"][0]["manual_audit"]["adjudicating_audit_count"] == 1
