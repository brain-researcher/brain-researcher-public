import json
from pathlib import Path

import pytest

from brain_researcher.core.contracts.gate_rule import GateRule
from brain_researcher.core.gates.engine import GateEngine


@pytest.fixture
def sample_rules():
    return [
        GateRule(
            rule_id="QC_MISSING_T1W",
            description="Missing T1w",
            applies_to="step",
            stage="preflight",
            metric="inputs.t1w_present",
            comparator="eq",
            threshold=False,
            severity="critical",
            action="block",
            message="No T1w",
        ),
        GateRule(
            rule_id="QC_MOTION",
            description="High FD",
            applies_to="step",
            stage="postcheck",
            metric="qc.motion.mean_fd",
            comparator="gt",
            threshold=0.5,
            severity="error",
            action="warn",
            message="Motion high",
        ),
    ]


def test_gate_engine_preflight_block(sample_rules):
    engine = GateEngine(sample_rules)
    ctx = {"inputs": {"t1w_present": False}}
    evals = engine.evaluate(ctx, stage="preflight", component="worker", step_id="s1")
    violations = [e.violation for e in evals if e.violation]
    assert len(violations) == 1
    v = violations[0]
    assert v.code == "QC_MISSING_T1W"
    assert v.blocking is True
    assert v.where.stage == "preflight"
    assert v.where.step_id == "s1"


def test_gate_engine_postcheck_warn(sample_rules):
    engine = GateEngine(sample_rules)
    ctx = {"qc": {"motion": {"mean_fd": 0.8}}}
    evals = engine.evaluate(ctx, stage="postcheck")
    violations = [e.violation for e in evals if e.violation]
    assert len(violations) == 1
    v = violations[0]
    assert v.blocking is False
    assert v.severity == "error"


def test_gate_engine_missing_metric_is_safe(sample_rules):
    engine = GateEngine(sample_rules)
    ctx = {}
    evals = engine.evaluate(ctx, stage="postcheck")
    violations = [e.violation for e in evals if e.violation]
    assert violations == []


def test_gate_engine_from_yaml(tmp_path: Path, sample_rules):
    cfg = {"rules": [r.model_dump() for r in sample_rules]}
    yaml_path = tmp_path / "gates.yaml"
    yaml_path.write_text(json.dumps(cfg))
    engine = GateEngine.from_yaml(yaml_path)
    assert len(engine.rules) == 2
