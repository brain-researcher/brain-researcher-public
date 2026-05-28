"""Golden snapshot for n-back defaults and psyflow config mapping."""

from __future__ import annotations

from brain_researcher.behavior.catalog import nback


def test_nback_golden_spec_keys():
    spec = nback.build(None)
    payload = spec.model_dump(mode="json")
    # Composed shape: paradigm/psyflow knobs live on task_program.
    assert payload["task_program"]["canonical_task_id"] == "n_back"
    assert payload["task_program"]["engine"] == "psyflow"
    assert payload["task_program"]["observation_schema"] == "behavior-trial-v1"
    env = payload["task_program"]["environment_config"]
    assert env["n_trials"] == 60
    assert env["n_blocks"] == 3
    assert env["trial_duration_sec"] == 2.0
    assert env["iti_sec"] == 1.0
    assert env["conditions"] == ["0-back", "1-back", "2-back"]
    # BIDS/scanner stay at wrapper level
    assert "n_back_level" in payload["bids_columns"]
    assert payload["scanner"]["tr_sec"] == 2.0
    # Compatibility accessors match
    assert spec.paradigm == "n_back"
    assert spec.n_trials == 60


def test_nback_golden_psyflow_config():
    spec = nback.build(None)
    cfg = nback.to_psyflow_config(spec)
    assert cfg["task"]["paradigm"] == "n_back"
    assert cfg["task"]["family"] == "working_memory"
    assert cfg["timing"]["trial_duration_sec"] == 2.0
    assert cfg["timing"]["iti_sec"] == 1.0
    assert cfg["conditions"] == ["0-back", "1-back", "2-back"]
    assert cfg["scanner"]["tr_sec"] == 2.0
    assert "n_back_level" in cfg["bids"]["columns"]
