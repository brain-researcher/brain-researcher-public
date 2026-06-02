"""Producer integration for ``params.nilearn_analysis.run_connectivity_matrix``.

The real nilearn ``ConnectivityMeasure`` derives every matrix through a
LedoitWolf-shrinkage covariance estimator, so even rank-deficient inputs
(duplicate ROIs) come back finite and well-conditioned: the value-domain gate is
defense-in-depth here, not the common firing path. These tests therefore verify
(a) the producer emits the sidecar, (b) ``contracts_for`` actually routes
covariance/precision connectivity to ``well_conditioned`` (wiring is real, not
hardcoded), (c) the sidecar propagates through the real bundle builder, and
(d) on a healthy run no violation is recorded. The genuine *blocking* path
(unshrunk ``np.corrcoef``/``np.cov`` -> exactly singular) is exercised against
``mne_connectivity`` and ``connectivity_measures`` whose fallbacks do not
regularize.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("nilearn")

from brain_researcher.core.analysis.value_domain_router import contracts_for
from brain_researcher.services.review.bundle_builder import (
    build_artifact_review_bundle,
)
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)
from brain_researcher.services.tools.params.nilearn_analysis import (
    ConnectivityMatrixParameters,
    run_connectivity_matrix,
)


@pytest.mark.unit
def test_covariance_connectivity_emits_routed_sidecar(tmp_path):
    # The router must actually map covariance connectivity to well_conditioned;
    # assert the wiring rather than relying on a hardcoded contract list.
    assert "well_conditioned" in contracts_for("connectivity_matrix_covariance")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rng = np.random.default_rng(0)
    # Duplicate-ROI input: a raw covariance would be singular, but nilearn's
    # LedoitWolf shrinkage regularizes it, so the gate records ok=True.
    base = rng.standard_normal((200, 3))
    ts = np.column_stack([base[:, 0], base[:, 1], base[:, 1]])[np.newaxis, ...]
    ts_path = run_dir / "timeseries.npy"
    np.save(ts_path, ts)

    params = ConnectivityMatrixParameters(
        timeseries=str(ts_path),
        kind="covariance",
        fisher_z=False,
        output_file=str(run_dir / "connectivity_matrix.npy"),
    )
    result = run_connectivity_matrix(params)

    sidecar = result["outputs"]["value_domain_diagnostics"]
    assert sidecar.endswith("value_domain_diagnostics.json")
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    by_contract = {e["contract"]: e for e in sink}
    # Always-on finite guard ran, and the router-selected well_conditioned
    # contract actually ran on the per-subject square matrix.
    assert by_contract["finite"]["ok"] is True
    assert "well_conditioned" in by_contract

    # Sidecar propagates through the real bundle builder into review_context.
    bundle = build_artifact_review_bundle("br_nilearn_conn", run_dir=run_dir)
    assert isinstance(bundle.review_context.get("value_domain_diagnostics"), list)


@pytest.mark.unit
def test_well_conditioned_covariance_records_no_violation(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rng = np.random.default_rng(1)
    ts = rng.standard_normal((300, 4))[np.newaxis, ...]
    ts_path = run_dir / "timeseries.npy"
    np.save(ts_path, ts)

    params = ConnectivityMatrixParameters(
        timeseries=str(ts_path),
        kind="covariance",
        fisher_z=False,
        output_file=str(run_dir / "connectivity_matrix.npy"),
    )
    result = run_connectivity_matrix(params)
    sink = json.loads(
        open(result["outputs"]["value_domain_diagnostics"], encoding="utf-8").read()
    )
    assert all(entry["ok"] for entry in sink)

    bundle = build_artifact_review_bundle("br_nilearn_conn_ok", run_dir=run_dir)
    assert value_domain_contract_violation_check(bundle) is None
