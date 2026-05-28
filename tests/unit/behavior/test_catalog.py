"""Tests for the behavior paradigm defaults catalog."""

from __future__ import annotations

import pytest

from brain_researcher.behavior.catalog import (
    psyflow_config_for,
    resolve_defaults,
)


def test_resolve_nback_defaults():
    spec = resolve_defaults("n_back")
    assert spec.paradigm == "n_back"
    assert spec.n_trials == 60
    assert spec.n_blocks == 3
    assert "2-back" in spec.conditions
    assert spec.scanner is not None
    assert spec.scanner.tr_sec == 2.0


def test_resolve_go_no_go_defaults():
    spec = resolve_defaults("go_no_go")
    assert spec.paradigm == "go_no_go"
    assert set(spec.conditions) == {"go", "nogo"}
    assert "inhibition_success" in spec.bids_columns


def test_resolve_flanker_defaults():
    spec = resolve_defaults("flanker")
    assert spec.paradigm == "flanker"
    assert "congruent" in spec.conditions
    assert spec.response_keys == ["left", "right"]


def test_overrides_are_applied():
    spec = resolve_defaults("n_back", {"n_trials": 120, "iti_sec": 0.5})
    assert spec.n_trials == 120
    assert spec.iti_sec == 0.5


def test_alias_keys_work():
    assert resolve_defaults("nback").paradigm == "n_back"
    assert resolve_defaults("gonogo").paradigm == "go_no_go"
    assert resolve_defaults("N-Back").paradigm == "n_back"


def test_unknown_paradigm_raises():
    with pytest.raises(KeyError):
        resolve_defaults("does_not_exist")


def test_psyflow_config_sections_present():
    spec = resolve_defaults("n_back")
    cfg = psyflow_config_for(spec)
    for key in ("task", "timing", "conditions", "response", "scanner", "bids"):
        assert key in cfg
    assert cfg["task"]["paradigm"] == "n_back"
    assert cfg["scanner"]["tr_sec"] == 2.0
    assert cfg["bids"]["columns"]
