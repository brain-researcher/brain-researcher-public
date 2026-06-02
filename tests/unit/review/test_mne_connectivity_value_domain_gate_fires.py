"""Producer integration: ``params.mne_connectivity.run_mne_connectivity`` with a
non-spectral ``covariance`` method uses the unshrunk ``np.cov`` fallback, so a
duplicate-channel time series yields an exactly singular covariance matrix. The
tool records a value-domain violation into a sidecar (strict=False), the sidecar
propagates through the real bundle builder, and the review-gate detector raises a
blocking ``REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION`` finding on a *succeeded* run.

Mirrors ``test_connectivity_value_domain_gate_fires.py`` but drives the *real* MNE
connectivity helper end to end. Spectral methods (coherence/PLI/...) are bounded
and not inverted downstream, so the router attaches only the always-on ``finite``
guard to them; ``covariance`` routes to ``well_conditioned``.
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
from brain_researcher.services.tools.params.mne_connectivity import (
    MNEConnectivityParameters,
    run_mne_connectivity,
)


def _duplicate_channel_timeseries() -> np.ndarray:
    """(n_channels, n_times) with channel 2 == channel 1 -> singular cov."""

    rng = np.random.default_rng(0)
    ch0 = rng.standard_normal(200)
    ch1 = rng.standard_normal(200)
    return np.vstack([ch0, ch1, ch1])


@pytest.mark.unit
def test_singular_covariance_blocks_via_review_gate(tmp_path):
    # Router wiring is real: covariance connectivity -> well_conditioned.
    assert "well_conditioned" in contracts_for("connectivity_covariance")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ts_path = run_dir / "timeseries.npy"
    np.save(ts_path, _duplicate_channel_timeseries())

    params = MNEConnectivityParameters(
        output_dir=str(run_dir),
        methods=("covariance",),
        time_series=str(ts_path),
        save_matrix=True,
        save_plots=False,
    )
    result = run_mne_connectivity(params)

    sidecar = result["outputs"]["value_domain_diagnostics"]
    assert sidecar.endswith("value_domain_diagnostics.json")
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    by_contract = {e["contract"]: e for e in sink}
    assert by_contract["finite"]["ok"] is True
    assert by_contract["well_conditioned"]["ok"] is False
    assert by_contract["well_conditioned"]["severity"] == "critical"

    bundle = build_artifact_review_bundle("br_mne_conn", run_dir=run_dir)
    assert isinstance(bundle.review_context.get("value_domain_diagnostics"), list)

    finding = value_domain_contract_violation_check(bundle)
    assert finding is not None
    assert finding.rule_id == "REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION"
    assert finding.severity == "critical"
    assert finding.action == "block"


@pytest.mark.unit
def test_well_conditioned_covariance_records_no_violation(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rng = np.random.default_rng(1)
    # Three independent channels -> well-conditioned covariance.
    ts = rng.standard_normal((3, 400))
    ts_path = run_dir / "timeseries.npy"
    np.save(ts_path, ts)

    params = MNEConnectivityParameters(
        output_dir=str(run_dir),
        methods=("covariance",),
        time_series=str(ts_path),
        save_matrix=True,
        save_plots=False,
    )
    result = run_mne_connectivity(params)
    sink = json.loads(
        open(result["outputs"]["value_domain_diagnostics"], encoding="utf-8").read()
    )
    assert all(entry["ok"] for entry in sink)

    bundle = build_artifact_review_bundle("br_mne_conn_ok", run_dir=run_dir)
    assert value_domain_contract_violation_check(bundle) is None
