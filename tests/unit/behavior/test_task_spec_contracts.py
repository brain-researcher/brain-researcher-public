"""Tests for brain_researcher.behavior.task_spec contracts + spec_digest.

The spec is now a thin wrapper composing a portable TaskProgramV1 (engine=
"psyflow") plus BR-specific fields. These tests exercise the composed
shape via the catalog and by direct construction with TaskProgramV1.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from brain_researcher.behavior.catalog import resolve_defaults
from brain_researcher.behavior.task_spec import (
    BehaviorReviewV1,
    BehaviorTaskSpecV1,
    PsyflowTaskBundleV1,
    ScannerProfile,
    spec_digest,
)
from brain_researcher.core.contracts.task_program import TaskProgramV1


def _minimal_spec(**overrides) -> BehaviorTaskSpecV1:
    """Minimal wrapper via the catalog, with optional overrides."""
    return resolve_defaults("n_back", overrides or None)


def _program(paradigm: str = "n_back", **env_overrides) -> TaskProgramV1:
    env = dict(
        n_trials=60,
        n_blocks=1,
        trial_duration_sec=2.0,
        iti_sec=1.0,
        conditions=[],
        response_keys=[],
        feedback=False,
        stimuli={},
        extras={},
    )
    env.update(env_overrides)
    return TaskProgramV1(
        program_id=f"psyflow::{paradigm}",
        canonical_task_id=paradigm,
        engine="psyflow",
        environment_id=f"psyflow:{paradigm}",
        environment_config=env,
        observation_schema="behavior-trial-v1",
    )


def test_behavior_task_spec_v1_minimal_construction():
    spec = _minimal_spec()
    assert spec.schema_id == "behavior-task-spec-v1"
    assert spec.paradigm == "n_back"
    assert spec.n_trials == 60
    assert spec.trial_duration_sec == 2.0
    assert spec.iti_sec == 1.0
    # TaskProgram is composed, engine is psyflow, observation is behavior-trial-v1
    assert spec.task_program.engine == "psyflow"
    assert spec.task_program.observation_schema == "behavior-trial-v1"
    assert spec.task_program.canonical_task_id == "n_back"


def test_behavior_task_spec_rejects_unknown_field():
    prog = _program()
    with pytest.raises(ValidationError):
        BehaviorTaskSpecV1(task_program=prog, not_a_field="oops")


def test_behavior_task_spec_rejects_empty_paradigm():
    prog = TaskProgramV1(
        program_id="psyflow::",
        canonical_task_id="   ",
        engine="psyflow",
        environment_id="psyflow:",
        environment_config={
            "n_trials": 1,
            "trial_duration_sec": 1.0,
            "iti_sec": 0.0,
        },
    )
    with pytest.raises((ValidationError, ValueError)):
        BehaviorTaskSpecV1(task_program=prog)


def test_behavior_task_spec_rejects_wrong_engine():
    prog = _program()
    prog_bad = prog.model_copy(update={"engine": "neurogym"})
    with pytest.raises((ValidationError, ValueError)):
        BehaviorTaskSpecV1(task_program=prog_bad)


def test_behavior_task_spec_rejects_wrong_observation_schema():
    prog = _program()
    prog_bad = prog.model_copy(update={"observation_schema": "not-behavior"})
    with pytest.raises((ValidationError, ValueError)):
        BehaviorTaskSpecV1(task_program=prog_bad)


def test_behavior_task_spec_requires_env_config_keys():
    prog_bad = TaskProgramV1(
        program_id="psyflow::x",
        canonical_task_id="x",
        engine="psyflow",
        environment_id="psyflow:x",
        environment_config={},  # missing required keys
    )
    with pytest.raises((ValidationError, ValueError)):
        BehaviorTaskSpecV1(task_program=prog_bad)


def test_spec_digest_is_deterministic():
    s1 = _minimal_spec()
    s2 = _minimal_spec()
    assert spec_digest(s1) == spec_digest(s2)
    assert len(spec_digest(s1)) == 64


def test_spec_digest_changes_with_env_config():
    s = _minimal_spec()
    d_base = spec_digest(s)
    s_bigger = _minimal_spec(n_trials=120)
    assert spec_digest(s_bigger) != d_base
    s_cond = _minimal_spec(conditions=["a", "b"])
    assert spec_digest(s_cond) != d_base


def test_scanner_profile_rejects_nonpositive_tr():
    with pytest.raises(ValidationError):
        ScannerProfile(tr_sec=0)
    with pytest.raises(ValidationError):
        ScannerProfile(tr_sec=-1.0)


def test_scanner_profile_rejects_bad_jitter():
    with pytest.raises(ValidationError):
        ScannerProfile(tr_sec=2.0, iti_jitter_sec=(-0.1, 1.0))
    with pytest.raises(ValidationError):
        ScannerProfile(tr_sec=2.0, iti_jitter_sec=(1.5, 0.5))


def test_scanner_profile_accepts_valid_jitter():
    sp = ScannerProfile(tr_sec=2.0, iti_jitter_sec=(0.0, 1.5))
    assert sp.iti_jitter_sec == (0.0, 1.5)


def test_scanner_profile_rejects_negative_dummy_scans():
    with pytest.raises(ValidationError):
        ScannerProfile(tr_sec=2.0, dummy_scans=-1)


def test_scanner_profile_rejects_duration_shorter_than_dummy_scan_budget():
    with pytest.raises(ValidationError):
        ScannerProfile(
            tr_sec=2.0,
            dummy_scans=4,
            planned_duration_sec=8.0,
        )


def test_scanner_profile_rejects_duration_exceeding_volume_budget():
    with pytest.raises(ValidationError):
        ScannerProfile(
            tr_sec=2.0,
            n_volumes=100,
            dummy_scans=4,
            planned_duration_sec=193.0,
        )


def test_scanner_profile_accepts_consistent_duration_and_volume_budget():
    sp = ScannerProfile(
        tr_sec=2.0,
        n_volumes=184,
        dummy_scans=4,
        planned_duration_sec=360.0,
    )
    assert sp.n_volumes == 184
    assert sp.dummy_scans == 4
    assert sp.planned_duration_sec == 360.0


def test_behavior_review_schema_id_and_fields():
    r = BehaviorReviewV1(spec_digest="a" * 64, approved=True, reviewer="alice")
    assert r.schema_id == "behavior-review-v1"
    assert r.approved is True


def test_psyflow_bundle_schema_id():
    b = PsyflowTaskBundleV1(
        spec_digest="a" * 64,
        paradigm="n_back",
        bundle_dir="/tmp/bundle",
        planned_dir="/tmp/bundle",
    )
    assert b.schema_id == "psyflow-task-bundle-v1"
    assert b.entrypoint == "main.py"
