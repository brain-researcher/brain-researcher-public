from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from brain_researcher.cli.main import app
from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchLineDirective,
)
from brain_researcher.core.contracts.scientific_review import (
    CompletenessVerdict,
    CorrectnessVerdict,
    JudgmentVerdict,
    ScientificReviewVerdict,
)

runner = CliRunner()


def _write_workspace(root: Path, *, report_text: str, line_type: str = "exploration") -> None:
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "runner_logs").mkdir(parents=True, exist_ok=True)
    (root / "loop_body_prompt.md").write_text("# loop\n", encoding="utf-8")
    (root / "predict.py").write_text(
        "def get_config():\n    return {}\n", encoding="utf-8"
    )
    (root / "experiments.jsonl").write_text(
        json.dumps(
            {
                "iteration": 1,
                "action_type": "final_report",
                "config": {"model": "Ridge", "terms": ["cov"]},
                "results": {"aggregate_mean_r": 0.1, "coverage_fraction": 1.0},
                "self_critique": {"verdict": "ADVANCE"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "outputs" / "final_report.md").write_text(report_text, encoding="utf-8")
    (root / "line_state.json").write_text(
        json.dumps(
            {
                "schema_version": "liu_component_line_state_v0",
                "line_type": line_type,
                "status": "active",
                "workspace": str(root),
                "loaded_modules": ["base", line_type],
                "training_backend": "cpu_local",
                "success_criterion": "do_the_next_thing_honestly",
            }
        ),
        encoding="utf-8",
    )


def _good_report() -> str:
    return """# Final Report

## Pre-Report Self-Critique Checkpoint

### So What
This result matters.

### Method Sensitivity
Primary analysis: baseline model.
Sensitivity analysis: repeated CV and robustness checks.

### Structured Exploratory Pass
We include null and exploratory outcomes.

### Claim Strength
claim_strength: internally_supported
validation_missing: none
final_stopping_condition: PASS
"""


def _review_verdict() -> ScientificReviewVerdict:
    return ScientificReviewVerdict(
        correctness=CorrectnessVerdict(decision="pass", findings=[]),
        judgment=JudgmentVerdict(decision="sound"),
        completeness=CompletenessVerdict(decision="complete", checklist={}),
        review_scope="autoresearch_loop",
        overall_decision="proceed",
        report_action="write_report",
        claim_strength="internally_supported",
        required_next_actions=[],
        validation_status={"structural_correctness": "ok"},
        line_directive=AutoresearchLineDirective(
            line_type="closeout",
            next_line_type=None,
            loaded_modules=["base"],
            forbidden_modules=[],
            training_backend="cpu_local",
            success_criterion="be_honest",
        ),
        rationale="cli test rationale",
    )


def test_line_preflight_json(monkeypatch, tmp_path: Path) -> None:
    _write_workspace(tmp_path, report_text=_good_report())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "brain_researcher.cli.commands.line_commands.console.print_json",
        lambda *, data, **kwargs: captured.setdefault("data", data),
    )

    result = runner.invoke(
        app,
        ["line", "preflight", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = captured["data"]
    assert payload["ready_for_review"] is True
    assert payload["required_fields"]["claim_strength"] == "internally_supported"


def test_line_preflight_accepts_line_state_path(monkeypatch, tmp_path: Path) -> None:
    _write_workspace(tmp_path, report_text=_good_report())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "brain_researcher.cli.commands.line_commands.console.print_json",
        lambda *, data, **kwargs: captured.setdefault("data", data),
    )

    result = runner.invoke(
        app,
        [
            "line",
            "preflight",
            str(tmp_path / "line_state.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = captured["data"]
    assert payload["report_present"] is True
    assert payload["ready_for_review"] is True


def test_line_advance_json_runs_review_and_persists(monkeypatch, tmp_path: Path) -> None:
    _write_workspace(tmp_path, report_text=_good_report(), line_type="validation")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "brain_researcher.cli.commands.line_commands.distill_autoresearch_scientific_review",
        lambda *args, **kwargs: _review_verdict(),
    )
    monkeypatch.setattr(
        "brain_researcher.cli.commands.line_commands.console.print_json",
        lambda *, data, **kwargs: captured.setdefault("data", data),
    )

    result = runner.invoke(
        app,
        ["line", "advance", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = captured["data"]
    assert payload["review_executed"] is True
    assert payload["decision"]["action"] == "accepted_closeout"
    assert payload["line_state"]["status"] == "completed"

    state_payload = json.loads((tmp_path / "line_state.json").read_text(encoding="utf-8"))
    assert state_payload["status"] == "completed"
    assert state_payload["closeout"]["outcome"] == "halt"


def test_line_run_skips_review_when_preflight_fails(monkeypatch, tmp_path: Path) -> None:
    _write_workspace(
        tmp_path,
        report_text="# Final Report\n\nclaim_strength: internally_supported\n",
    )
    captured: dict[str, object] = {}

    def _unexpected_review(*args, **kwargs):
        raise AssertionError("scientific review should be skipped when preflight fails")

    monkeypatch.setattr(
        "brain_researcher.cli.commands.line_commands.distill_autoresearch_scientific_review",
        _unexpected_review,
    )
    monkeypatch.setattr(
        "brain_researcher.cli.commands.line_commands.console.print_json",
        lambda *, data, **kwargs: captured.setdefault("data", data),
    )

    result = runner.invoke(
        app,
        ["line", "run", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = captured["data"]
    assert payload["review_executed"] is False
    assert payload["review_skipped_reason"] == "report_preflight_not_ready"
    assert payload["decision"]["action"] == "repair_report_preflight"
    assert payload["line_state"]["status"] == "active"
