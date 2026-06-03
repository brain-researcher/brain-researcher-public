"""Structural-integrity tests for the C01-C60 calibration case library.

The case library (``tests/fixtures/review/calibration_cases_c01_c60.yaml``) is
transcribed from section 6 ("Case Library C01-C60") of the S4 manuscript
``docs/overleaf/BrainResearcher/old_doc/Brain Researcher Manuscript (11).docx``.
Each case pairs an analysis scenario with the recommended default severity and
the failure-mode rule it should trigger.

These tests assert STRUCTURAL integrity only: 60 unique ids, valid severities,
and that every block/warn case names a rule. Running the actual rule engine
against each scenario is intentionally out of scope (tracked as a followup).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

VALID_SEVERITIES = {"allow", "warn", "block"}
VALID_NOVELTY_TAGS = {"prior_conflict"}
EXPECTED_CASE_COUNT = 60

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "review"
    / "calibration_cases_c01_c60.yaml"
)


def _load_cases() -> list[dict]:
    assert _FIXTURE_PATH.is_file(), f"missing fixture: {_FIXTURE_PATH}"
    with _FIXTURE_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), "top-level YAML must be a mapping"
    cases = data.get("cases")
    assert isinstance(cases, list), "'cases' must be a list"
    return cases


CASES = _load_cases()


def test_case_count_is_sixty() -> None:
    assert len(CASES) == EXPECTED_CASE_COUNT


def test_case_ids_are_unique_and_contiguous() -> None:
    ids = [c["id"] for c in CASES]
    assert len(set(ids)) == EXPECTED_CASE_COUNT, "case ids must be unique"
    expected = {f"C{n:02d}" for n in range(1, EXPECTED_CASE_COUNT + 1)}
    assert set(ids) == expected, "case ids must be exactly C01..C60"


def test_required_keys_present() -> None:
    required = {"id", "scenario", "expected_severity", "expected_rule", "novelty"}
    for case in CASES:
        missing = required - set(case)
        assert not missing, f"{case.get('id')} missing keys: {sorted(missing)}"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_structural_integrity(case: dict) -> None:
    cid = case["id"]

    # id shape
    assert isinstance(cid, str) and cid.startswith("C") and cid[1:].isdigit()

    # scenario is non-empty prose
    scenario = case["scenario"]
    assert isinstance(scenario, str) and scenario.strip(), f"{cid}: empty scenario"

    # severity in the controlled vocabulary
    severity = case["expected_severity"]
    assert severity in VALID_SEVERITIES, f"{cid}: bad severity {severity!r}"

    # rule typing
    rule = case["expected_rule"]
    assert rule is None or (
        isinstance(rule, str) and rule.strip()
    ), f"{cid}: expected_rule must be null or a non-empty string"

    # every block/warn case must name a rule
    if severity in {"block", "warn"}:
        assert rule, f"{cid}: {severity} case must name a rule"

    # novelty tag typing
    novelty = case["novelty"]
    assert novelty is None or novelty in VALID_NOVELTY_TAGS, (
        f"{cid}: bad novelty tag {novelty!r}"
    )


def test_each_severity_is_represented() -> None:
    seen = {c["expected_severity"] for c in CASES}
    assert seen == VALID_SEVERITIES, f"severities present: {sorted(seen)}"


def test_novelty_cases_are_prior_conflict() -> None:
    tagged = [c["id"] for c in CASES if c["novelty"] is not None]
    # The S4 manuscript flags four novelty/prior-conflict calibration cases.
    assert tagged, "expected at least one novelty-tagged case"
    for c in CASES:
        if c["novelty"] is not None:
            assert c["novelty"] == "prior_conflict"
