"""Producer-side integration: a connectivity tool that records value-domain
diagnostics for a degenerate (singular) FC matrix lands a sidecar in the run
dir, which propagates through the real bundle builder into a blocking
``REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION`` finding on a *succeeded* run.

This mirrors the producer change proposed for
``services/tools/nilearn_connectivity_matrix_tool.py`` (returned as a diff):
after computing the matrix, the tool runs ``evaluate_value_domain`` for
``finite`` and ``well_conditioned`` with ``strict=False`` and a shared sink,
then ``write_value_domain_diagnostics(sink, output_dir)``. We reproduce that
exact recording sequence here against the *real* router, contracts, bundle
builder, and review detector, so the test still passes before the tool diff is
applied while exercising the full plumbing the diff relies on.
"""

from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.analysis.value_domain_router import (
    contracts_for,
    evaluate_value_domain,
    write_value_domain_diagnostics,
)
from brain_researcher.services.review.bundle_builder import (
    build_artifact_review_bundle,
)
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)


def _singular_connectivity_matrix() -> np.ndarray:
    """A rank-deficient correlation-like matrix (duplicate ROI) -> singular.

    Two identical rows/columns make the matrix exactly rank-deficient, so its
    smallest eigenvalue is ~0 and the condition number blows up: the kind of
    matrix that breaks a downstream precision/Mahalanobis inversion.
    """

    base = np.array(
        [
            [1.0, 0.9, 0.9],
            [0.9, 1.0, 1.0],
            [0.9, 1.0, 1.0],
        ]
    )
    return base


def _record_like_tool(matrix: np.ndarray, method: str) -> list[dict]:
    """Reproduce the producer recording the tool diff adds after fit_transform.

    Selects contracts via the declarative router (``contracts_for``) plus the
    always-on ``finite`` guard, exactly as the connectivity tool should.
    """

    sink: list[dict] = []
    evaluate_value_domain(
        "finite",
        matrix,
        f"{method}_connectivity_matrix",
        strict=False,
        sink=sink,
    )
    # Router maps "correlation"/"covariance"/"precision" connectivity to
    # well_conditioned; assert that wiring is real, not hardcoded in the test.
    assert "well_conditioned" in contracts_for("nilearn_connectivity_matrix_covariance")
    for contract in ("well_conditioned",):
        evaluate_value_domain(
            contract,
            matrix,
            f"{method}_connectivity_matrix",
            strict=False,
            sink=sink,
        )
    return sink


@pytest.mark.unit
def test_singular_connectivity_matrix_blocks_via_review_gate(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    matrix = _singular_connectivity_matrix()
    sink = _record_like_tool(matrix, method="correlation")

    # finite passes (ok=True), well_conditioned fails (ok=False, critical).
    by_contract = {entry["contract"]: entry for entry in sink}
    assert by_contract["finite"]["ok"] is True
    assert by_contract["well_conditioned"]["ok"] is False
    assert by_contract["well_conditioned"]["severity"] == "critical"

    sidecar = write_value_domain_diagnostics(sink, run_dir)
    assert sidecar.exists()
    assert sidecar.name == "value_domain_diagnostics.json"

    bundle = build_artifact_review_bundle("br_conn_run", run_dir=run_dir)
    assert isinstance(bundle.review_context.get("value_domain_diagnostics"), list)

    finding = value_domain_contract_violation_check(bundle)
    assert finding is not None
    assert finding.rule_id == "REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION"
    assert finding.severity == "critical"
    assert finding.action == "block"


@pytest.mark.unit
def test_well_conditioned_connectivity_matrix_records_no_violation(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # Diagonally dominant SPD matrix: finite + well-conditioned -> all ok.
    matrix = np.array(
        [
            [1.0, 0.2, 0.1],
            [0.2, 1.0, 0.15],
            [0.1, 0.15, 1.0],
        ]
    )
    sink = _record_like_tool(matrix, method="correlation")
    assert all(entry["ok"] for entry in sink)

    write_value_domain_diagnostics(sink, run_dir)
    bundle = build_artifact_review_bundle("br_conn_run_ok", run_dir=run_dir)
    assert value_domain_contract_violation_check(bundle) is None
