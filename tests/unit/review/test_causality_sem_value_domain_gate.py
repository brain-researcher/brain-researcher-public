"""Record-or-raise integration for ``StructuralEquationModelingTool``.

The SEM fit-index site pinv-inverts the sample covariance to form the chi-square
statistic. It previously *only* raised on a near-singular covariance
(``validate_well_conditioned``); it now also RECORDS the violation (record-or-
raise, lenient). Unlike the FC matrix tools this tool returns a plain dict and
has no mandatory ``output_dir``, so it propagates diagnostics via the result
payload's ``value_domain_diagnostics`` key (merged into ``review_context`` by the
bundle builder), and additionally drops the standard sidecar when an
``output_dir`` IS supplied.

These tests assert: (a) router wiring is real (sem -> well_conditioned),
(b) a healthy covariance records no violation in the payload, (c) a singular
covariance records a ``critical`` violation in the payload while the run still
succeeds, and (d) when an ``output_dir`` is supplied the sidecar is written and
propagates through the real bundle builder into a blocking finding.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from brain_researcher.core.analysis.value_domain_router import contracts_for
from brain_researcher.services.review.bundle_builder import (
    build_artifact_review_bundle,
)
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)
from brain_researcher.services.tools.causality_analysis import (
    StructuralEquationModelingTool,
)


@pytest.mark.unit
def test_router_wiring_for_sem():
    assert "well_conditioned" in contracts_for("structural_equation_modeling")


@pytest.mark.unit
def test_healthy_covariance_records_no_violation():
    rng = np.random.default_rng(0)
    time_series = rng.standard_normal((200, 5))
    tool = StructuralEquationModelingTool()
    result = tool._run(time_series=time_series, lag_order=1)

    assert result["status"] == "success"
    diagnostics = result["value_domain_diagnostics"]
    assert isinstance(diagnostics, list) and diagnostics
    assert all(e["ok"] for e in diagnostics)
    contracts = {e["contract"] for e in diagnostics}
    assert {"finite", "well_conditioned"} <= contracts


@pytest.mark.unit
def test_singular_covariance_records_violation_in_payload():
    # Perfectly collinear regions -> rank-deficient sample covariance.
    base = np.linspace(-1.0, 1.0, 200)
    time_series = np.column_stack([base, base, base, base])
    tool = StructuralEquationModelingTool()
    result = tool._run(time_series=time_series, lag_order=1)

    # Record-or-raise (lenient): the run still SUCCEEDS.
    assert result["status"] == "success"
    diagnostics = result["value_domain_diagnostics"]
    violations = [e for e in diagnostics if not e["ok"]]
    assert any(v["contract"] == "well_conditioned" for v in violations)
    assert any(v.get("severity") == "critical" for v in violations)


@pytest.mark.unit
def test_singular_covariance_sidecar_propagates_and_blocks(tmp_path):
    base = np.linspace(-1.0, 1.0, 200)
    time_series = np.column_stack([base, base, base, base])
    tool = StructuralEquationModelingTool()
    result = tool._run(time_series=time_series, lag_order=1, output_dir=str(tmp_path))
    assert result["status"] == "success"

    sidecar = tmp_path / "value_domain_diagnostics.json"
    assert sidecar.exists()
    sink = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(not e["ok"] for e in sink)

    bundle = build_artifact_review_bundle("br_sem_singular", run_dir=tmp_path)
    finding = value_domain_contract_violation_check(bundle)
    assert finding is not None
    assert finding.action == "block"
    assert finding.severity == "critical"
