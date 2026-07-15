"""Guards for the A1 public-evaluator source and environment boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
A1_PACK = REPO_ROOT / "reproducibility" / "bounded_autoresearch_a1"
HISTORICAL_HARNESS_SHA256 = (
    "3fe2eea1c1e20ab7e7630ac87e7b6e2b7cd5a2786a5351e8b410930f062962a1"
)
RECORDED_PREDICTOR_SHA256 = (
    "380cbb505a2e541ca10bfbfcf2711c952e5a6b1beeaf18246af71ce6891e017a"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a1_source_closure_keeps_historical_and_public_harnesses_distinct() -> None:
    closure = json.loads(
        (A1_PACK / "artifacts" / "evaluator_source_closure.json").read_text(
            encoding="utf-8"
        )
    )
    public_evaluator = A1_PACK / closure["public_light_rerun"]["evaluator_path"]

    assert closure["recorded_governed_run"]["harness_sha256"] == (
        HISTORICAL_HARNESS_SHA256
    )
    assert closure["recorded_governed_run"]["source_shipped_in_public_pack"] is False
    assert closure["public_light_rerun"]["role"] == "ported_public_evaluator"
    assert closure["public_light_rerun"]["evaluator_sha256"] == _sha256(
        public_evaluator
    )
    assert closure["public_light_rerun"]["evaluator_sha256"] != (
        HISTORICAL_HARNESS_SHA256
    )
    assert "does not claim a formal semantic-equivalence proof" in (
        closure["public_light_rerun"]["relationship_to_recorded_harness"]
    )


def test_a1_recorded_results_remain_bound_to_the_historical_harness() -> None:
    target_summary = json.loads(
        (A1_PACK / "artifacts" / "residualised_target_summary.json").read_text(
            encoding="utf-8"
        )
    )
    null_summary = json.loads(
        (A1_PACK / "artifacts" / "family_block_null_summary.json").read_text(
            encoding="utf-8"
        )
    )
    closure = json.loads(
        (A1_PACK / "artifacts" / "evaluator_source_closure.json").read_text(
            encoding="utf-8"
        )
    )

    assert target_summary["harness_sha256"] == HISTORICAL_HARNESS_SHA256
    assert (
        null_summary["frozen_pipeline"]["run_py_sha256"]
        == HISTORICAL_HARNESS_SHA256
    )
    assert _sha256(A1_PACK / "scripts" / "predict.py") == RECORDED_PREDICTOR_SHA256
    assert closure["predictor"] == {
        "public_path": "scripts/predict.py",
        "sha256": RECORDED_PREDICTOR_SHA256,
        "byte_identical_to_recorded_governed_predictor": True,
    }


def test_a1_public_instructions_name_the_port_and_source_boundary() -> None:
    instruction_paths = [
        A1_PACK / "README.md",
        A1_PACK / "REPRODUCTION.md",
        A1_PACK / "AGENTIC_REPRODUCTION.md",
        A1_PACK / "provenance_card.md",
        A1_PACK / "run_end_to_end.sh",
    ]
    instructions = "\n".join(
        path.read_text(encoding="utf-8") for path in instruction_paths
    )

    assert "public evaluator port" in instructions
    assert HISTORICAL_HARNESS_SHA256 in instructions
    assert "original frozen evaluator" not in instructions.lower()
    assert "public frozen predictor" not in instructions.lower()
    assert "immutable frozen evaluator" not in instructions.lower()


def test_a1_light_path_uses_exact_python311_lock() -> None:
    lock_path = A1_PACK / "requirements-py311.lock"
    locked = {
        line.strip()
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    expected = {
        "h5py==3.15.1",
        "joblib==1.5.2",
        "numpy==1.26.4",
        "pandas==1.5.3",
        "python-dateutil==2.9.0.post0",
        "pytz==2025.2",
        "scikit-learn==1.7.2",
        "scipy==1.14.1",
        "six==1.17.0",
        "threadpoolctl==3.6.0",
        "tzdata==2025.2",
    }
    run_script = (A1_PACK / "run_end_to_end.sh").read_text(encoding="utf-8")

    assert locked == expected
    assert all("==" in requirement for requirement in locked)
    assert 'LOCK_FILE="${PACK_ROOT}/requirements-py311.lock"' in run_script
    assert '--requirement "${LOCK_FILE}"' in run_script
    assert "sys.version_info[:2] != (3, 11)" in run_script
