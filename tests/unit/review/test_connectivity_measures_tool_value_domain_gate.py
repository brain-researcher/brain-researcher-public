"""Producer integration for the ``ConnectivityMeasuresTool`` (sensor-space EEG
connectivity via MNE-Connectivity).

The tool computes a dense connectivity matrix from real MNE ``Epochs`` and emits
a ``value_domain_diagnostics.json`` sidecar after the matrix is computed. Its
default method (PLI) is bounded in ``[0, 1]`` and is never inverted downstream,
so the declarative router attaches only the always-on ``finite`` guard to it
(``covariance``/``precision`` methods would additionally route to
``well_conditioned``). These tests drive the *real* tool end to end and assert:
(a) the sidecar is emitted and listed in outputs, (b) it propagates through the
real bundle builder into ``review_context``, (c) a healthy PLI matrix records no
violation, and (d) the router wiring is real (pli -> only finite; covariance ->
well_conditioned).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("mne")
pytest.importorskip("mne_connectivity")

import mne

from brain_researcher.core.analysis.value_domain_router import contracts_for
from brain_researcher.services.review.bundle_builder import (
    build_artifact_review_bundle,
)
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)
from brain_researcher.services.tools.connectivity_measures_tool import (
    ConnectivityMeasuresTool,
)


def _write_epochs(path) -> None:
    sfreq = 100.0
    rng = np.random.default_rng(0)
    data = rng.standard_normal((8, 4, 200)) * 1e-6
    info = mne.create_info([f"EEG{i}" for i in range(4)], sfreq, "eeg")
    epochs = mne.EpochsArray(data, info, verbose=False)
    epochs.save(str(path), overwrite=True, verbose=False)


@pytest.mark.unit
def test_router_wiring_for_connectivity_measures_methods():
    # PLI is bounded and not inverted -> only the always-on finite guard.
    assert contracts_for("connectivity_measures_pli") == ()
    # A covariance-style method would additionally require conditioning.
    assert "well_conditioned" in contracts_for("connectivity_measures_covariance")


@pytest.mark.unit
def test_pli_matrix_emits_sidecar_and_propagates(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    epochs_path = run_dir / "synthetic-epo.fif"
    _write_epochs(epochs_path)

    tool = ConnectivityMeasuresTool()
    result = tool._run(
        epochs=str(epochs_path),
        method="pli",
        output_dir=str(run_dir),
    )
    assert result.status == "success"

    sidecar = result.data["outputs"]["value_domain_diagnostics"]
    assert sidecar.endswith("value_domain_diagnostics.json")
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    by_contract = {e["contract"]: e for e in sink}
    # finite guard ran and passed; PLI is in [0, 1] so it is finite.
    assert by_contract["finite"]["ok"] is True
    # No well_conditioned entry: PLI is not router-mapped to it.
    assert "well_conditioned" not in by_contract

    bundle = build_artifact_review_bundle("br_conn_measures", run_dir=run_dir)
    assert isinstance(bundle.review_context.get("value_domain_diagnostics"), list)
    # Healthy run -> no blocking finding.
    assert value_domain_contract_violation_check(bundle) is None
