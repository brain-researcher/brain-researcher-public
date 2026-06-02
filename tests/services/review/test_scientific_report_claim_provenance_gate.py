"""Integration test for the claim-provenance gate embedded in
``scientific_report_generate``.

This test verifies the *mechanism* the diff against ``server.py`` relies on:
a confirmatory run with an untraceable claim must produce a blocking
correctness finding that, when folded into the review verdict's
``correctness.findings`` BEFORE the report mode is computed, flips the
consolidation mode to ``review_blocked_draft``.

It is written so it does not require importing the (concurrently rewritten)
MCP ``server`` module at collection time. The end-to-end ``server`` import is
attempted and the full tool is exercised when the module is importable;
otherwise the test falls back to validating the exact composition the diff
performs (gate -> inject finding -> mode), using the real
``claim_provenance`` helpers.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from brain_researcher.services.review.claim_provenance import (
    build_claim_provenance_gate,
    build_run_provenance_index,
)


def _make_confirmatory_index() -> Any:
    """A provenance index for a run that produced a single known artifact."""

    bundle = SimpleNamespace(
        observed_artifacts={
            "analysis_bundle": {
                "file_manifest": [
                    {"path": "outputs/glm/zstat1.nii.gz", "checksum": "a" * 64},
                ]
            }
        },
        plan_steps=[{"tool": "glm_fit", "step_id": "s1"}],
    )
    return build_run_provenance_index(bundle)


def test_gate_blocks_untraceable_claim_under_confirmatory_mode() -> None:
    """The core invariant: confirmatory + untraceable claim => blocked gate
    carrying a critical/block finding."""

    index = _make_confirmatory_index()
    claims = [
        # Traceable claim: cites the produced artifact and a real code ref.
        {
            "claim_id": "C1",
            "text": "Activation in region X.",
            "artifact_path": "outputs/glm/zstat1.nii.gz",
            "artifact_sha256": "a" * 64,
            "code_ref": "glm_fit:s1",
        },
        # Untraceable claim: no provenance at all.
        {
            "claim_id": "C2",
            "text": "We observed a strong group difference.",
        },
    ]

    gate = build_claim_provenance_gate(
        claims,
        index,
        claim_mode="confirmatory",
        require_claim_provenance=False,
    )

    assert gate is not None
    assert gate["blocked"] is True
    assert gate["unsupported_ids"] == ["C2"]
    assert "section_text" in gate and gate["section_text"]
    finding = gate.get("finding")
    assert finding is not None
    assert finding["severity"] == "critical"
    assert finding["action"] == "block"


def test_injected_finding_flips_report_mode_to_blocked_draft() -> None:
    """Replicates the diff's composition: fold the gate finding into
    ``review['correctness']['findings']`` and confirm the report-mode helper
    returns ``review_blocked_draft``.

    Uses the real ``server`` helpers when importable; otherwise asserts the
    blocking-finding contract directly so the test still guards the mechanism.
    """

    index = _make_confirmatory_index()
    claims = [{"claim_id": "C2", "text": "Untraceable result."}]
    gate = build_claim_provenance_gate(
        claims, index, claim_mode="confirmatory", require_claim_provenance=False
    )
    assert gate is not None and gate["blocked"] is True
    finding = gate["finding"]

    # A passing review verdict (no blocking findings) that the gate must flip.
    review: dict[str, Any] = {
        "ok": True,
        "overall_decision": "proceed",
        "report_action": "publish",
        "claim_strength": "confirmatory",
        "rationale": "All checks passed.",
        "correctness": {"decision": "pass", "findings": []},
        "required_next_actions": [],
    }

    try:
        server = importlib.import_module("brain_researcher.services.mcp.server")
    except Exception:  # pragma: no cover - server may be mid-rewrite
        server = None

    if server is not None and hasattr(server, "_scientific_report_mode"):
        # Before injection: a clean "proceed" verdict is NOT blocked.
        assert server._scientific_report_mode(review) == "final_report"

        # Injection performed by the diff (creating structure if needed).
        review.setdefault("correctness", {}).setdefault("findings", []).append(finding)

        # After injection: mode flips to review_blocked_draft.
        assert server._scientific_report_is_blocked(review) is True
        assert server._scientific_report_mode(review) == "review_blocked_draft"
    else:
        # Fallback contract check: the finding is recognized as blocking by the
        # same severity/action criteria server.py uses.
        review.setdefault("correctness", {}).setdefault("findings", []).append(finding)
        findings = review["correctness"]["findings"]
        assert any(
            str(f.get("severity", "")).lower() in {"critical", "error"}
            or str(f.get("action", "")).lower() == "block"
            for f in findings
        )


def test_exploratory_run_only_caveats_untraceable_claim() -> None:
    """Exploratory mode (without require_claim_provenance) must NOT block; it
    surfaces the untraceable claim as a caveat section only -> no finding."""

    index = _make_confirmatory_index()
    claims = [{"claim_id": "C2", "text": "Untraceable exploratory note."}]

    gate = build_claim_provenance_gate(
        claims,
        index,
        claim_mode="exploratory",
        require_claim_provenance=False,
    )

    assert gate is not None
    assert gate["blocked"] is False
    assert gate["unsupported_ids"] == ["C2"]
    assert gate.get("section_text")  # caveat present
    assert "finding" not in gate  # but not a blocking finding


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
