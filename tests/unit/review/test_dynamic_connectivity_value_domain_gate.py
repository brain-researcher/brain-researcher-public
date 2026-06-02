"""Producer integration for the dynamic-connectivity fallback tool.

``run_dynamic_connectivity`` slices a ROI time-series into sliding windows and
computes a per-window correlation matrix that downstream state clustering treats
as a covariance, so each window must be finite and well-conditioned. The tool now
emits a ``value_domain_diagnostics.json`` sidecar after the window stack is built.

These tests drive the *real* helper end to end and assert: (a) the sidecar is
emitted and listed in outputs, (b) a healthy stack records no violation and
propagates cleanly through the real bundle builder, (c) a degenerate (constant)
window stack records a ``critical`` well_conditioned / finite violation that the
detector turns into a blocking finding on a *succeeded* run, and (d) the router
wiring is real (correlation -> well_conditioned).
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
from brain_researcher.services.tools.params.dynamic_connectivity import (
    dynamic_connectivity_from_payload,
    run_dynamic_connectivity,
)


def _run(tmp_path, timeseries: np.ndarray, method: str = "covariance"):
    ts_path = tmp_path / "timeseries.npy"
    np.save(ts_path, timeseries)
    params = dynamic_connectivity_from_payload(
        {
            "timeseries_file": str(ts_path),
            "output_dir": str(tmp_path),
            "connectivity_method": method,
            "window_length": 20,
            "window_overlap": 0.5,
            "n_states": 2,
            "random_state": 0,
        }
    )
    return run_dynamic_connectivity(params)


@pytest.mark.unit
def test_router_wiring_for_dynamic_connectivity_methods():
    # A covariance-style window matrix is inverted downstream -> conditioning.
    assert "well_conditioned" in contracts_for("dynamic_connectivity_covariance")
    # Bounded correlation is router-mapped to the always-on finite guard only,
    # matching the nilearn/mne precedent (correlation is not in the well_-
    # conditioned route).
    assert contracts_for("dynamic_connectivity_correlation") == ()


@pytest.mark.unit
def test_healthy_stack_emits_sidecar_and_propagates(tmp_path):
    rng = np.random.default_rng(0)
    timeseries = rng.standard_normal((100, 5))
    result = _run(tmp_path, timeseries)

    sidecar = result["outputs"]["value_domain_diagnostics"]
    assert sidecar.endswith("value_domain_diagnostics.json")
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    contracts = {e["contract"] for e in sink}
    assert "finite" in contracts
    assert "well_conditioned" in contracts
    # Healthy random data -> every recorded entry passed.
    assert all(e["ok"] for e in sink)

    bundle = build_artifact_review_bundle("br_dynfc_healthy", run_dir=tmp_path)
    assert isinstance(bundle.review_context.get("value_domain_diagnostics"), list)
    assert value_domain_contract_violation_check(bundle) is None


@pytest.mark.unit
def test_degenerate_window_records_violation_and_blocks(tmp_path):
    # Two perfectly collinear ROIs -> singular per-window correlation matrix.
    base = np.linspace(0.0, 1.0, 100)
    timeseries = np.column_stack([base, base, base])
    result = _run(tmp_path, timeseries)

    # The run still SUCCEEDS (record-or-raise, lenient).
    assert result["summary"]["used_full_backend"] is False

    sidecar = result["outputs"]["value_domain_diagnostics"]
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    violations = [e for e in sink if not e["ok"]]
    assert violations, "expected at least one recorded value-domain violation"
    assert any(v["contract"] == "well_conditioned" for v in violations)
    assert any(v.get("severity") == "critical" for v in violations)

    bundle = build_artifact_review_bundle("br_dynfc_degenerate", run_dir=tmp_path)
    finding = value_domain_contract_violation_check(bundle)
    assert finding is not None
    assert finding.action == "block"
    assert finding.severity == "critical"
