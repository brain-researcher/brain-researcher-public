"""Tests for the spec-digest-bound approval gate on generate_psyflow_task."""

from __future__ import annotations

from pathlib import Path

from brain_researcher.behavior.catalog import resolve_defaults
from brain_researcher.behavior.task_spec import spec_digest
from brain_researcher.services.tools.behavior_tools import (
    BehaviorGeneratePsyflowTaskTool,
)


def _spec_dict():
    return resolve_defaults("n_back").model_dump(mode="json")


def test_rejects_unapproved_review(tmp_path: Path):
    spec = _spec_dict()
    digest = spec_digest(resolve_defaults("n_back"))
    tool = BehaviorGeneratePsyflowTaskTool()
    review = {"spec_digest": digest, "approved": False}
    result = tool._run(spec=spec, out_dir=str(tmp_path), review=review)
    assert result.status == "error"
    assert "approval_gate_failed" in (result.error or "")


def test_rejects_digest_mismatch(tmp_path: Path):
    spec = _spec_dict()
    tool = BehaviorGeneratePsyflowTaskTool()
    review = {"spec_digest": "a" * 64, "approved": True}
    result = tool._run(spec=spec, out_dir=str(tmp_path), review=review)
    assert result.status == "error"
    assert "approval_gate_failed" in (result.error or "")


def test_accepts_matching_digest_and_writes_bundle(tmp_path: Path):
    parsed = resolve_defaults("n_back")
    spec = parsed.model_dump(mode="json")
    digest = spec_digest(parsed)
    tool = BehaviorGeneratePsyflowTaskTool()
    review = {"spec_digest": digest, "approved": True, "reviewer": "alice"}
    result = tool._run(spec=spec, out_dir=str(tmp_path), review=review)
    assert result.status == "success", result.error
    bundle = result.data["bundle"]
    assert bundle["spec_digest"] == digest
    planned = Path(bundle["planned_dir"])
    assert planned.exists()
    assert (planned / "config" / "config.yaml").exists()
    # psyflow extra not installed in unit-test environment -> skipped
    assert result.data["validate"]["status"] in {"skipped", "success", "error"}
