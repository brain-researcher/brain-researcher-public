"""P1.4: value_domain_diagnostics sidecar -> review_context -> blocking finding."""

from __future__ import annotations

import numpy as np
import pytest

from brain_researcher.core.analysis.value_domain_router import (
    evaluate_value_domain,
    write_value_domain_diagnostics,
)
from brain_researcher.services.review.bundle_builder import (
    _discover_review_sidecars,
    _extract_review_context,
    build_artifact_review_bundle,
)
from brain_researcher.services.review.checks.value_domain import (
    value_domain_contract_violation_check,
)


def _seed_sidecar(run_dir):
    """Record a violation leniently and write it as a run-dir sidecar."""

    sink: list[dict] = []
    evaluate_value_domain(
        "well_conditioned",
        np.array([[1.0, 2.0], [2.0, 1.0]]),  # indefinite -> negative eigenvalue
        "sem_sample_covariance",
        strict=False,
        sink=sink,
    )
    return write_value_domain_diagnostics(sink, run_dir)


@pytest.mark.unit
def test_sidecar_is_discovered_and_merged_into_review_context(tmp_path):
    _seed_sidecar(tmp_path)

    discovered = _discover_review_sidecars(tmp_path)
    assert "value_domain_diagnostics" in discovered
    assert discovered["value_domain_diagnostics"][0]["name"] == "sem_sample_covariance"

    review_context = _extract_review_context(discovered)
    assert review_context["value_domain_diagnostics"][0]["ok"] is False


@pytest.mark.unit
def test_sidecar_propagates_through_real_bundle_builder_to_blocking_finding(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _seed_sidecar(run_dir)

    bundle = build_artifact_review_bundle("br_test_run", run_dir=run_dir)

    assert isinstance(bundle.review_context.get("value_domain_diagnostics"), list)

    finding = value_domain_contract_violation_check(bundle)
    assert finding is not None
    assert finding.rule_id == "REVIEW_VALUEDOMAIN_CONTRACT_VIOLATION"
    assert finding.severity == "critical"
    assert finding.action == "block"


@pytest.mark.unit
def test_no_sidecar_means_no_finding(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bundle = build_artifact_review_bundle("br_test_run", run_dir=run_dir)
    assert value_domain_contract_violation_check(bundle) is None
