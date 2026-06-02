"""Producer integration for ``MultimodalFusionTool`` Mahalanobis similarity.

The Mahalanobis branch forms a covariance over the fused representation and
pinv-inverts it. The site previously *only* raised on a near-singular covariance
(``validate_well_conditioned``); it now also RECORDS the violation into a
``value_domain_diagnostics.json`` sidecar (record-or-raise, lenient) so the
violation propagates via the review-gate detector on a *succeeded* run instead
of only crashing.

These tests drive the *real* tool end to end and assert: (a) the sidecar is
emitted and listed in outputs, (b) a well-conditioned fused covariance records no
violation and propagates cleanly, (c) a rank-deficient fused covariance records a
``critical`` well_conditioned violation that the detector turns into a blocking
finding while the run still succeeds, and (d) the router wiring is real.
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
from brain_researcher.services.tools.multimodal_fusion_tool import (
    MultimodalFusionTool,
)


def _write_modalities(tmp_path, a: np.ndarray, b: np.ndarray) -> dict[str, str]:
    a_path = tmp_path / "mod_a.npy"
    b_path = tmp_path / "mod_b.npy"
    np.save(a_path, a)
    np.save(b_path, b)
    return {"a": str(a_path), "b": str(b_path)}


@pytest.mark.unit
def test_router_wiring_for_mahalanobis():
    assert "well_conditioned" in contracts_for("multimodal_fusion_mahalanobis")


@pytest.mark.unit
def test_healthy_mahalanobis_emits_sidecar_and_propagates(tmp_path):
    rng = np.random.default_rng(0)
    modality_files = _write_modalities(
        tmp_path,
        rng.standard_normal((40, 6)),
        rng.standard_normal((40, 6)),
    )
    tool = MultimodalFusionTool()
    result = tool._run(
        modality_files=modality_files,
        output_dir=str(tmp_path),
        method="concat",
        similarity_metric="mahalanobis",
        standardize=True,
    )
    assert result.status == "success"

    sidecar = result.data["outputs"]["value_domain_diagnostics"]
    assert sidecar.endswith("value_domain_diagnostics.json")
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    by_contract = {e["contract"]: e for e in sink}
    assert by_contract["finite"]["ok"] is True
    assert by_contract["well_conditioned"]["ok"] is True

    bundle = build_artifact_review_bundle("br_fusion_healthy", run_dir=tmp_path)
    assert value_domain_contract_violation_check(bundle) is None


@pytest.mark.unit
def test_singular_covariance_records_violation_and_blocks(tmp_path):
    # Build modalities whose concatenation has perfectly collinear columns so the
    # fused covariance is rank-deficient (near-singular).
    rng = np.random.default_rng(1)
    col = rng.standard_normal((30, 1))
    a = np.hstack([col, col, col])  # rank-1 block
    b = np.hstack([col, col, col])
    modality_files = _write_modalities(tmp_path, a, b)

    tool = MultimodalFusionTool()
    result = tool._run(
        modality_files=modality_files,
        output_dir=str(tmp_path),
        method="concat",
        similarity_metric="mahalanobis",
        standardize=False,
    )
    # Record-or-raise (lenient): the run still SUCCEEDS.
    assert result.status == "success"

    sidecar = result.data["outputs"]["value_domain_diagnostics"]
    sink = json.loads(open(sidecar, encoding="utf-8").read())
    violations = [e for e in sink if not e["ok"]]
    assert any(v["contract"] == "well_conditioned" for v in violations)
    assert any(v.get("severity") == "critical" for v in violations)

    bundle = build_artifact_review_bundle("br_fusion_singular", run_dir=tmp_path)
    finding = value_domain_contract_violation_check(bundle)
    assert finding is not None
    assert finding.action == "block"
    assert finding.severity == "critical"
