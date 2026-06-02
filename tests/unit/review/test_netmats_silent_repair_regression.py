"""End-to-end regression for the HCP netmats1 silent-repair incident.

Original failure: out-of-[-1, 1] netmats values were silently "repaired"
before a Fisher-z transform, and the resulting review finding never propagated
into the generated report. This pins all three failure surfaces in one chain:

1. Missing input precondition / silent repair -> the execution-gate contract
   ``validate_for_fisher_z`` / ``safe_fisher_z`` now *raises* instead of
   repairing out-of-range correlations.
2. Detection -> the real ``predictive_fisher_z_input_domain_check`` emits a
   blocking finding from the recorded out-of-range state.
3. Propagation -> ``scientific_report_generate`` turns that finding into a
   blocked draft instead of a final report.
"""

from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.analysis.connectivity_contracts import (
    safe_fisher_z,
    validate_for_fisher_z,
)
from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.services.mcp import server as srv
from brain_researcher.services.review.checks.predictive_integrity import (
    predictive_fisher_z_input_domain_check,
)

# A netmats1-shaped matrix with values outside the valid correlation domain
# (e.g. partial-correlation netmats stored on a non-[-1, 1] scale).
_OUT_OF_RANGE_NETMATS = np.array(
    [
        [1.0, 1.8, -2.3],
        [1.8, 1.0, 0.4],
        [-2.3, 0.4, 1.0],
    ]
)


@pytest.mark.unit
def test_execution_gate_refuses_to_silently_repair_out_of_range_netmats():
    """Surface 1+2: the contract raises rather than clipping/repairing."""

    with pytest.raises(ValueError, match=r"outside \[-1, 1\]|raw Pearson"):
        validate_for_fisher_z(_OUT_OF_RANGE_NETMATS, "netmats1")

    # safe_fisher_z must not quietly return a "repaired" array either.
    with pytest.raises(ValueError):
        safe_fisher_z(_OUT_OF_RANGE_NETMATS, "netmats1")


def _blocking_fisher_z_finding():
    """Run the real review check against the recorded out-of-range state."""

    outside_fraction = float((np.abs(_OUT_OF_RANGE_NETMATS) > 1.0).mean())
    bundle = CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context={
            "scientific_review_profile": "predictive_model_review",
            "preprocessing": {
                "fisher_z_applied": True,
                "outside_unit_interval_fraction": outside_fraction,
            },
        },
    )
    return predictive_fisher_z_input_domain_check(bundle)


@pytest.mark.unit
def test_recorded_out_of_range_state_produces_blocking_review_finding():
    """Surface 2: the recorded diagnostics drive a real blocking finding."""

    finding = _blocking_fisher_z_finding()

    assert finding is not None
    assert finding.rule_id == "REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN"
    assert finding.action == "block"
    assert finding.severity == "error"


@pytest.mark.unit
def test_blocking_finding_propagates_into_blocked_report_draft(monkeypatch):
    """Surface 3: the finding blocks report generation; no final report."""

    finding = _blocking_fisher_z_finding()
    assert finding is not None

    def fake_review(*args, **kwargs):
        return {
            "ok": True,
            "review_scope": "pipeline_run",
            "overall_decision": "proceed",
            "report_action": "continue_loop",
            "claim_strength": "final",
            "rationale": "Otherwise permissive review.",
            "correctness": {
                "decision": "pass",
                "findings": [
                    {
                        "rule_id": finding.rule_id,
                        "severity": finding.severity,
                        "action": finding.action,
                        "message": finding.message,
                    }
                ],
            },
            "judgment": {"decision": "ok", "judgment_status": "ok"},
            "completeness": {"decision": "complete", "checklist": {}},
        }

    captured: dict = {}

    def fake_render(**kwargs):
        captured["render_args"] = kwargs
        return {"ok": True, "run_id": "br_report", "artifacts": {}}

    monkeypatch.setattr(srv, "run_scientific_review", fake_review)
    monkeypatch.setattr(srv, "latex_report_render", fake_render)

    resp = srv.scientific_report_generate(run_id="br_netmats_blocked")

    assert resp["ok"] is True
    assert resp["consolidation"]["mode"] == "review_blocked_draft"
    assert resp["consolidation"]["mode"] != "final_report"

    sections = captured["render_args"]["sections"]
    blocked_section_title = "Analysis blocked by scientific review finding"
    assert next(iter(sections)) == blocked_section_title
    assert "REVIEW_PREDICTIVE_FISHER_Z_INPUT_DOMAIN" in sections[blocked_section_title]
    assert (
        "Do not interpret this report as final scientific conclusions"
        in sections["Consolidated Conclusion"]
    )
