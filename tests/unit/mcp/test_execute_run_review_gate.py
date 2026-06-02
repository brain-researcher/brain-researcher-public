"""Unit tests for the post-execution scientific-review gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_researcher.services.mcp import server as mcp_server


def _fake_verdict(*, blocking: bool = True, warnings: bool = False) -> dict:
    findings = []
    if blocking:
        findings.append(
            {
                "rule_id": "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC",
                "severity": "error",
                "action": "block",
                "message": "missing full_pipeline_permutation_null",
            }
        )
    if warnings:
        findings.append(
            {
                "rule_id": "REVIEW_GOVERNANCE_WARNING",
                "severity": "warn",
                "action": "warn",
                "message": "caveat-only",
            }
        )
    return {
        "ok": True,
        "overall_decision": "stop_with_rationale" if blocking else "proceed",
        "correctness": {
            "decision": "flag" if blocking else "pass",
            "findings": findings,
        },
    }


def _severity_only_block_verdict() -> dict:
    return {
        "ok": True,
        "overall_decision": "stop_with_rationale",
        "correctness": {
            "decision": "flag",
            "findings": [
                {
                    "rule_id": "REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN",
                    "severity": "error",
                    "action": "diagnose",
                    "message": "input domain does not permit Fisher-z",
                }
            ],
        },
    }


def _critical_block_verdict() -> dict:
    return {
        "ok": True,
        "overall_decision": "stop_with_rationale",
        "correctness": {
            "decision": "flag",
            "findings": [
                {
                    "rule_id": "REVIEW_VALUEDOMAIN_FISHER_Z_INPUT",
                    "severity": "critical",
                    "action": "block",
                    "message": "netmats values outside [-1, 1]; silent repair refused",
                }
            ],
        },
    }


def _seed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, claim_mode: str
) -> str:
    run_id = f"test_run_{claim_mode}"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mcp_server, "_find_run_dir", lambda _id: run_dir)

    analysis_bundle = {
        "review_context": {
            "claim_contract": {"confirmatory_or_exploratory": claim_mode},
        }
    }
    (run_dir / "analysis_bundle.json").write_text(
        json.dumps(analysis_bundle), encoding="utf-8"
    )

    record = mcp_server.RunRecord(
        run_id=run_id,
        created_at=mcp_server._utc_iso(),
        status="succeeded",
    )
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    saved: dict[str, mcp_server.RunRecord] = {"current": record}

    def fake_load(_run_id: str) -> mcp_server.RunRecord:
        return saved["current"]

    def fake_save(
        updated: mcp_server.RunRecord, *, run_dir: Path | None = None
    ) -> None:
        saved["current"] = updated

    monkeypatch.setattr(mcp_server, "_load_run", fake_load)
    monkeypatch.setattr(mcp_server, "_save_run", fake_save)
    return run_id


def _claim_contract(run_id: str) -> dict:
    bundle = json.loads(
        (mcp_server._find_run_dir(run_id) / "analysis_bundle.json").read_text(
            encoding="utf-8"
        )
    )
    return bundle["review_context"]["claim_contract"]


@pytest.mark.unit
def test_gate_blocks_confirmatory_run_with_block_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_id = _seed_run(monkeypatch, tmp_path, claim_mode="confirmatory")
    monkeypatch.setattr(
        mcp_server,
        "run_scientific_review",
        lambda _id, **kw: _fake_verdict(blocking=True),
    )
    monkeypatch.delenv("BR_DISABLE_EXECUTION_REVIEW_GATE", raising=False)

    mcp_server._run_post_execution_review_gate(run_id)

    record = mcp_server._load_run(run_id)
    assert record.status == "review_blocked"
    assert record.error == "review_blocked_by_correctness_findings"
    assert record.progress["scientific_review_blocking_findings"][0]["rule_id"] == (
        "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
    )
    assert (mcp_server._find_run_dir(run_id) / "scientific_review.json").exists()
    claim_contract = _claim_contract(run_id)
    assert claim_contract["report_allowed"] is False
    assert claim_contract["report_gate_status"] == "blocked"
    assert claim_contract["scientific_review_decision"] == "stop_with_rationale"
    assert claim_contract["review_artifact_path"] == "scientific_review.json"
    assert claim_contract["blocking_findings"] == [
        {
            "rule_id": "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC",
            "severity": "error",
            "action": "block",
            "message": "missing full_pipeline_permutation_null",
        }
    ]


@pytest.mark.unit
def test_gate_keeps_exploratory_run_succeeded_with_caveats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_id = _seed_run(monkeypatch, tmp_path, claim_mode="exploratory")
    monkeypatch.setattr(
        mcp_server,
        "run_scientific_review",
        lambda _id, **kw: _fake_verdict(blocking=True, warnings=True),
    )
    monkeypatch.delenv("BR_DISABLE_EXECUTION_REVIEW_GATE", raising=False)

    mcp_server._run_post_execution_review_gate(run_id)

    record = mcp_server._load_run(run_id)
    assert record.status == "succeeded"
    assert "scientific_review_blocking_findings" not in record.progress
    claim_contract = _claim_contract(run_id)
    assert claim_contract["report_allowed"] is True
    assert claim_contract["report_gate_status"] == "caveated"
    assert claim_contract["blocking_findings"][0]["rule_id"] == (
        "REVIEW_GOVERNANCE_MISSING_DIAGNOSTIC"
    )
    assert claim_contract["warning_findings"] == [
        {
            "rule_id": "REVIEW_GOVERNANCE_WARNING",
            "severity": "warn",
            "action": "warn",
            "message": "caveat-only",
        }
    ]


@pytest.mark.unit
def test_gate_blocks_exploratory_run_with_critical_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A critical correctness finding blocks regardless of claim mode.

    A corrupted result (e.g. silently-repaired out-of-range netmats) is invalid
    whether the claim is confirmatory or exploratory, so the exploratory
    downgrade must not apply to ``critical`` severity findings.
    """

    run_id = _seed_run(monkeypatch, tmp_path, claim_mode="exploratory")
    monkeypatch.setattr(
        mcp_server,
        "run_scientific_review",
        lambda _id, **kw: _critical_block_verdict(),
    )
    monkeypatch.delenv("BR_DISABLE_EXECUTION_REVIEW_GATE", raising=False)

    mcp_server._run_post_execution_review_gate(run_id)

    record = mcp_server._load_run(run_id)
    assert record.status == "review_blocked"
    assert record.error == "review_blocked_by_correctness_findings"
    assert record.progress["scientific_review_blocking_findings"][0]["rule_id"] == (
        "REVIEW_VALUEDOMAIN_FISHER_Z_INPUT"
    )
    claim_contract = _claim_contract(run_id)
    assert claim_contract["report_allowed"] is False
    assert claim_contract["report_gate_status"] == "blocked"


@pytest.mark.unit
def test_env_disable_bypasses_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    run_id = _seed_run(monkeypatch, tmp_path, claim_mode="confirmatory")
    called: dict[str, bool] = {"yes": False}

    def boom(_id, **kw):
        called["yes"] = True
        return _fake_verdict(blocking=True)

    monkeypatch.setattr(mcp_server, "run_scientific_review", boom)
    monkeypatch.setenv("BR_DISABLE_EXECUTION_REVIEW_GATE", "1")

    mcp_server._run_post_execution_review_gate(run_id)

    assert called["yes"] is False
    record = mcp_server._load_run(run_id)
    assert record.status == "succeeded"


@pytest.mark.unit
def test_gate_does_not_block_when_no_findings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_id = _seed_run(monkeypatch, tmp_path, claim_mode="confirmatory")
    monkeypatch.setattr(
        mcp_server,
        "run_scientific_review",
        lambda _id, **kw: _fake_verdict(blocking=False),
    )
    monkeypatch.delenv("BR_DISABLE_EXECUTION_REVIEW_GATE", raising=False)

    mcp_server._run_post_execution_review_gate(run_id)

    record = mcp_server._load_run(run_id)
    assert record.status == "succeeded"
    claim_contract = _claim_contract(run_id)
    assert claim_contract["report_allowed"] is True
    assert claim_contract["report_gate_status"] == "passed"


@pytest.mark.unit
def test_gate_blocks_confirmatory_run_with_error_severity_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_id = _seed_run(monkeypatch, tmp_path, claim_mode="confirmatory")
    monkeypatch.setattr(
        mcp_server,
        "run_scientific_review",
        lambda _id, **kw: _severity_only_block_verdict(),
    )
    monkeypatch.delenv("BR_DISABLE_EXECUTION_REVIEW_GATE", raising=False)

    mcp_server._run_post_execution_review_gate(run_id)

    record = mcp_server._load_run(run_id)
    assert record.status == "review_blocked"
    claim_contract = _claim_contract(run_id)
    assert claim_contract["report_allowed"] is False
    assert claim_contract["blocking_findings"] == [
        {
            "rule_id": "REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN",
            "severity": "error",
            "action": "diagnose",
            "message": "input domain does not permit Fisher-z",
        }
    ]
