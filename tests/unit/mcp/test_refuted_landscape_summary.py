from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from brain_researcher.services.mcp import runstore


def _configure_run_root(monkeypatch, tmp_path: Path):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    srv._ensure_dirs()
    return srv


def _tool_or_skip(monkeypatch, tmp_path: Path):
    srv = _configure_run_root(monkeypatch, tmp_path)
    if not hasattr(srv, "refuted_landscape_summary"):
        pytest.skip("refuted_landscape_summary not implemented yet")
    return srv


def _structured_findings() -> list[dict]:
    return [
        {
            "claim": "Any distance normalization improves kNN performance",
            "direction": "mutual_proximity_negative_control",
            "status": "refuted",
            "comparison": "vs baseline kNN on the same split",
            "reason": "balanced accuracy did not improve and hubness skew worsened",
            "evidence": [
                {
                    "type": "metric",
                    "label": "balanced_accuracy_delta",
                    "value": -0.012,
                },
                {
                    "type": "metric",
                    "label": "hubness_skewness_delta",
                    "value": 4.8,
                },
            ],
            "caveats": ["single dataset", "current MP implementation only"],
            "tags": ["h1", "hubness", "negative_control"],
        },
        {
            "claim": "Hubness reduction is specific to neighborhood-based classifiers",
            "direction": "linear_svm_reference",
            "status": "supported",
            "comparison": "vs local-scaling kNN and baseline linear SVM",
            "reason": "linear baseline remained flat while local-scaling kNN improved",
            "evidence": [
                {
                    "type": "metric",
                    "label": "linear_svm_balanced_accuracy_delta",
                    "value": 0.0,
                }
            ],
            "caveats": ["single held-out split"],
            "tags": ["h1", "reference"],
        },
        {
            "claim": "Generated connectomes preserve disease-specific directions",
            "direction": "gradient_shift_validation",
            "status": "inconclusive",
            "comparison": "train vs validation gradient-shift correlation",
            "reason": "validation sign flipped despite high global correlation",
            "evidence": [
                {
                    "type": "metric",
                    "label": "gradient_shift_corr_val",
                    "value": -0.265,
                }
            ],
            "caveats": ["coarse disease label", "possible label heterogeneity"],
            "tags": ["h2", "generative"],
        },
        {
            "claim": "Mutual Proximity is a drop-in hubness fix here",
            "direction": "mutual_proximity_drop_in",
            "status": "refuted",
            "comparison": "vs baseline kNN across matched rows",
            "reason": "paired tests never exceeded baseline and ordering inversion was observed",
            "evidence": [
                {
                    "type": "metric",
                    "label": "paired_win_count",
                    "value": 0,
                }
            ],
            "caveats": ["current implementation only"],
            "tags": ["h1", "appendix_c"],
        },
    ]


def test_refuted_landscape_rejects_missing_or_empty_findings(tmp_path, monkeypatch):
    srv = _tool_or_skip(monkeypatch, tmp_path)

    resp_none = srv.refuted_landscape_summary(findings=None)
    assert resp_none["ok"] is False

    resp_empty = srv.refuted_landscape_summary(findings=[])
    assert resp_empty["ok"] is False


def test_refuted_landscape_rejects_invalid_finding_rows(tmp_path, monkeypatch):
    srv = _tool_or_skip(monkeypatch, tmp_path)

    resp = srv.refuted_landscape_summary(
        findings=[
            {
                "claim": "Malformed row missing status",
                "direction": "broken_input",
                "comparison": "vs baseline",
                "reason": "schema incomplete",
            }
        ]
    )

    assert resp["ok"] is False


def test_refuted_landscape_counts_and_summary_are_deterministic(tmp_path, monkeypatch):
    srv = _tool_or_skip(monkeypatch, tmp_path)
    findings = _structured_findings()

    resp_a = srv.refuted_landscape_summary(findings=deepcopy(findings))
    resp_b = srv.refuted_landscape_summary(findings=deepcopy(findings))

    assert resp_a["ok"] is True
    assert resp_b["ok"] is True
    assert resp_a["counts"] == {
        "total": 4,
        "refuted": 2,
        "supported": 1,
        "inconclusive": 1,
    }
    assert resp_b["counts"] == resp_a["counts"]
    assert resp_b["refuted_landscape"]["paragraph"] == resp_a["refuted_landscape"][
        "paragraph"
    ]
    assert resp_b["refuted_landscape"]["rows"] == resp_a["refuted_landscape"]["rows"]


def test_refuted_landscape_rows_and_paragraph_come_from_structured_inputs(
    tmp_path, monkeypatch
):
    srv = _tool_or_skip(monkeypatch, tmp_path)

    resp = srv.refuted_landscape_summary(findings=_structured_findings(), top_k=8)

    assert resp["ok"] is True
    paragraph = resp["refuted_landscape"]["paragraph"]
    rows = resp["refuted_landscape"]["rows"]

    assert isinstance(paragraph, str)
    assert paragraph.strip()
    assert "4" in paragraph
    assert "2" in paragraph
    assert len(rows) == 4

    first_refuted = next(row for row in rows if row["direction"] == "mutual_proximity_drop_in")
    assert first_refuted["status"] == "refuted"
    assert "ordering inversion" in first_refuted["reason"]
    assert first_refuted["comparison"] == "vs baseline kNN across matched rows"
    assert any(
        "paired_win_count=0" == item for item in first_refuted["evidence_summary"]
    )
    assert first_refuted["caveats"] == ["current implementation only"]


def test_refuted_landscape_session_enrichment_does_not_change_counts_or_statuses(
    tmp_path, monkeypatch
):
    srv = _tool_or_skip(monkeypatch, tmp_path)
    findings = _structured_findings()

    base = srv.refuted_landscape_summary(findings=deepcopy(findings))
    assert base["ok"] is True

    def _fake_digest(*, session_id: str | None = None, run_id: str | None = None):
        assert session_id == "narrative-session-1"
        assert run_id is None
        return {
            "ok": True,
            "run_id": "attached_run",
            "digest": {
                "session_id": session_id,
                "done_items": ["captured refuted alternatives"],
                "open_items": ["add oversmoothing companion diagnostic"],
                "notes": [
                    {"content": "Use session metadata only for enrichment, not evidence."}
                ],
                "run_ids": ["attached_run", "aux_run"],
            },
        }

    monkeypatch.setattr(srv, "research_session_digest", _fake_digest)

    enriched = srv.refuted_landscape_summary(
        findings=deepcopy(findings),
        session_id="narrative-session-1",
    )

    assert enriched["ok"] is True
    assert enriched["counts"] == base["counts"]
    assert [row["status"] for row in enriched["refuted_landscape"]["rows"]] == [
        row["status"] for row in base["refuted_landscape"]["rows"]
    ]
    assert enriched["enrichment"] == {
        "session_id": "narrative-session-1",
        "run_ids": ["attached_run", "aux_run"],
        "done_items": ["captured refuted alternatives"],
        "open_items": ["add oversmoothing companion diagnostic"],
    }
