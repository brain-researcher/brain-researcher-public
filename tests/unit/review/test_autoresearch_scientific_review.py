from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchReviewBundle,
    ValidationEvidenceItem,
)
from brain_researcher.core.contracts.scientific_review import (
    JudgmentVerdict,
    derive_verdict_metadata,
)
from brain_researcher.services.review.autoresearch_bundle_builder import (
    build_autoresearch_review_bundle,
)
from brain_researcher.services.review.autoresearch_judgment_critic import (
    run_autoresearch_judgment_critic,
)
from brain_researcher.services.review.autoresearch_scientific_review import (
    distill_autoresearch_scientific_review,
)


def _write_workspace(root: Path, *, claim_strength: str) -> None:
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (root / "predict.py").write_text(
        "def get_config():\n    return {'path': 'A'}\n",
        encoding="utf-8",
    )
    rows = [
        {
            "iteration": 0,
            "action_type": "baseline_replicate",
            "config": {"path": "A", "model": "Ridge", "terms": ["cov"]},
            "results": {
                "aggregate_mean_r": 0.12,
                "coverage_fraction": 0.8,
                "n_hit_mean": 4,
                "per_component": [
                    {
                        "component": "ICA_Cognition",
                        "fold_mean_r": 0.30,
                        "reference_mean_r": 0.215,
                        "reference_best_r": 0.42,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_TobaccoUse",
                        "fold_mean_r": 0.20,
                        "reference_mean_r": 0.143,
                        "reference_best_r": 0.357,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_PersonalityEmotion",
                        "fold_mean_r": 0.11,
                        "reference_mean_r": 0.084,
                        "reference_best_r": 0.245,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_IllicitDrugUse",
                        "fold_mean_r": 0.03,
                        "reference_mean_r": 0.010,
                        "reference_best_r": 0.199,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_MentalHealth",
                        "fold_mean_r": 0.01,
                        "reference_mean_r": 0.014,
                        "reference_best_r": 0.174,
                        "hit_mean": False,
                        "hit_best": False,
                    },
                ],
            },
            "self_critique": {"verdict": "ADVANCE"},
        },
        {
            "iteration": 1,
            "action_type": "final_report",
            "config": {"path": "B", "model": "PerComponentNestedRidge", "terms": ["dcorr"]},
            "results": {
                "aggregate_mean_r": 0.17,
                "coverage_fraction": 1.0,
                "n_hit_mean": 5,
                "per_component": [
                    {
                        "component": "ICA_Cognition",
                        "fold_mean_r": 0.35,
                        "reference_mean_r": 0.215,
                        "reference_best_r": 0.42,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_TobaccoUse",
                        "fold_mean_r": 0.22,
                        "reference_mean_r": 0.143,
                        "reference_best_r": 0.357,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_PersonalityEmotion",
                        "fold_mean_r": 0.18,
                        "reference_mean_r": 0.084,
                        "reference_best_r": 0.245,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_IllicitDrugUse",
                        "fold_mean_r": 0.05,
                        "reference_mean_r": 0.010,
                        "reference_best_r": 0.199,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                    {
                        "component": "ICA_MentalHealth",
                        "fold_mean_r": 0.05,
                        "reference_mean_r": 0.014,
                        "reference_best_r": 0.174,
                        "hit_mean": True,
                        "hit_best": False,
                    },
                ],
            },
            "self_critique": {"verdict": "ADVANCE"},
        },
    ]
    with (root / "experiments.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    final_report = f"""# Final Report

ICA_Cognition
ICA_TobaccoUse
ICA_PersonalityEmotion
ICA_IllicitDrugUse
ICA_MentalHealth

## Pre-Report Self-Critique Checkpoint

### So What
This result implies the benchmark is internally coherent and worth follow-up.

### Method Sensitivity
Primary analysis: per-component routing.
Sensitivity analysis: deterministic rerun and method comparison for fold dependence and sample size.

### Structured Exploratory Pass
These analyses are exploratory and include null outcomes with no signal for several metric swaps.

### Claim Strength
claim_strength: {claim_strength}
validation_missing: permutation baseline; alternate fold manifests / repeated CV; external cohort replication

final_stopping_condition: "PASS"
"""
    (outputs / "final_report.md").write_text(final_report, encoding="utf-8")


def test_autoresearch_bundle_detects_validation_artifact(tmp_path: Path) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    (tmp_path / "outputs" / "deterministic_audit_001.json").write_text(
        "{}",
        encoding="utf-8",
    )

    bundle = build_autoresearch_review_bundle(tmp_path)

    assert bundle.ledger_row_count == 2
    assert bundle.claim_strength_declared == "internally_supported"
    statuses = {item.name: item.status for item in bundle.validation_evidence}
    assert statuses["deterministic_audit"] == "present"


def test_autoresearch_scientific_review_proceeds_for_internally_supported(
    tmp_path: Path, monkeypatch
) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    # Two core validation artifacts → earns "internally_supported".
    (tmp_path / "outputs" / "deterministic_audit_001.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_path / "outputs" / "permutation_baseline_001.json").write_text(
        "{}", encoding="utf-8"
    )

    from brain_researcher.services.review import autoresearch_scientific_review as mod

    monkeypatch.setattr(
        mod,
        "run_autoresearch_judgment_critic",
        lambda bundle: JudgmentVerdict(decision="sound"),
    )

    verdict = distill_autoresearch_scientific_review(
        tmp_path,
        use_judgment_critic=True,
        force_recompute=True,
    )

    assert verdict.overall_decision == "proceed"
    assert verdict.report_action == "write_report"
    assert verdict.claim_strength == "internally_supported"
    assert verdict.line_directive is not None
    assert verdict.line_directive.line_type == "closeout"
    assert verdict.line_directive.next_line_type is None
    assert verdict.line_directive.loaded_modules == ["base"]


def test_autoresearch_scientific_review_rejects_unvalidated_scientifically_convincing(
    tmp_path: Path, monkeypatch
) -> None:
    _write_workspace(tmp_path, claim_strength="scientifically_convincing")

    from brain_researcher.services.review import autoresearch_scientific_review as mod

    monkeypatch.setattr(
        mod,
        "run_autoresearch_judgment_critic",
        lambda bundle: JudgmentVerdict(decision="sound"),
    )

    verdict = distill_autoresearch_scientific_review(
        tmp_path,
        use_judgment_critic=True,
        force_recompute=True,
    )

    # New stricter behavior: declared "scientifically_convincing" without any
    # validation artifacts triggers AUTORESEARCH_CLAIM_STRENGTH_OVERREACH and
    # the rollup turns into a structural block.
    assert verdict.overall_decision == "stop_with_rationale"
    assert verdict.report_action == "revise_report"
    assert verdict.claim_strength is None
    assert verdict.line_directive is not None
    assert verdict.line_directive.line_type == "validation"
    assert verdict.line_directive.next_line_type == "validation"
    assert any(
        f.rule_id == "AUTORESEARCH_CLAIM_STRENGTH_OVERREACH"
        for f in verdict.correctness.findings
    )
    assert verdict.validation_status["validation:permutation_baseline"] != "present"


def test_autoresearch_scientific_review_tolerates_judge_transport_failure_when_complete(
    tmp_path: Path, monkeypatch
) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    (tmp_path / "outputs" / "deterministic_audit_001.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (tmp_path / "outputs" / "permutation_baseline_001.json").write_text(
        "{}",
        encoding="utf-8",
    )

    from brain_researcher.services.review import autoresearch_scientific_review as mod

    monkeypatch.setattr(
        mod,
        "run_autoresearch_judgment_critic",
        lambda bundle: JudgmentVerdict(
            decision="questionable",
            judgment_status="parse_failed",
            judge_transport_error="empty response",
            issues=["autoresearch_judgment_critic unavailable: empty response"],
        ),
    )

    verdict = distill_autoresearch_scientific_review(
        tmp_path,
        use_judgment_critic=True,
        force_recompute=True,
    )

    assert verdict.overall_decision == "proceed"
    assert verdict.report_action == "write_report"
    assert verdict.judgment.judgment_status == "parse_failed"
    assert "transport failed" in verdict.rationale.lower()


class _SequenceRouter:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.kwargs_history: list[dict[str, object]] = []

    def route_chat(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.kwargs_history.append(kwargs)
        if not self._responses:
            raise RuntimeError("no more responses")
        return SimpleNamespace(text=self._responses.pop(0))


def test_autoresearch_judgment_critic_accepts_mixed_text_json(tmp_path: Path) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    bundle = build_autoresearch_review_bundle(tmp_path)
    router = _SequenceRouter(
        [
            'Reviewer note:\n```json\n{"decision":"sound","estimand_complete":true,'
            '"method_defensible":true,"issues":[],"reviewer_questions":[]}\n```'
        ]
    )

    verdict = run_autoresearch_judgment_critic(
        bundle,
        model="gemini-3-flash-preview",
        router=router,  # type: ignore[arg-type]
    )

    assert router.calls == 1
    assert verdict.decision == "sound"
    assert verdict.judgment_status == "ok"
    assert verdict.raw_response_text is not None
    assert "Reviewer note" in verdict.raw_response_text


def test_autoresearch_judgment_critic_repairs_once_on_parse_failure(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    bundle = build_autoresearch_review_bundle(tmp_path)
    router = _SequenceRouter(
        [
            "decision=sound",
            '{"decision":"sound","estimand_complete":true,'
            '"method_defensible":true,"issues":[],"reviewer_questions":[]}',
        ]
    )

    verdict = run_autoresearch_judgment_critic(
        bundle,
        model="gemini-3-flash-preview",
        router=router,  # type: ignore[arg-type]
    )

    assert router.calls == 2
    assert verdict.decision == "sound"
    assert verdict.judgment_status == "ok"
    assert verdict.raw_response_text is not None
    assert verdict.raw_response_text.startswith('{"decision":"sound"')


def test_autoresearch_judgment_critic_marks_parse_failed_after_bad_repair(
    tmp_path: Path,
) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    bundle = build_autoresearch_review_bundle(tmp_path)
    router = _SequenceRouter(["not json", "still not json"])

    verdict = run_autoresearch_judgment_critic(
        bundle,
        model="gemini-3-flash-preview",
        router=router,  # type: ignore[arg-type]
    )

    assert router.calls == 2
    assert verdict.decision == "questionable"
    assert verdict.judgment_status == "parse_failed"
    assert verdict.judge_transport_error is not None
    assert "repair_failed" in verdict.judge_transport_error
    assert verdict.raw_response_text == "still not json"


def test_autoresearch_judgment_critic_gemini_locks_provider(tmp_path: Path) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    bundle = build_autoresearch_review_bundle(tmp_path)
    router = _SequenceRouter(
        [
            '{"decision":"sound","estimand_complete":true,'
            '"method_defensible":true,"issues":[],"reviewer_questions":[]}'
        ]
    )

    verdict = run_autoresearch_judgment_critic(
        bundle,
        model="gemini-3-flash-preview",
        router=router,  # type: ignore[arg-type]
    )

    assert verdict.decision == "sound"
    assert router.kwargs_history
    assert router.kwargs_history[0]["provider_lock"] == "gemini"


def test_autoresearch_bundle_tolerates_markdown_field_variants(tmp_path: Path) -> None:
    _write_workspace(tmp_path, claim_strength="internally_supported")
    report = """# Final Report

## Pre-Report Self-Critique Checkpoint

## So What
Signal is interesting.

**Method Sensitivity**:
Primary analysis: ridge.
Sensitivity analysis: deterministic rerun.

- **Structured Exploratory Pass**:
These analyses are exploratory.

### Claim Strength
**claim_strength**: scientifically_convincing
- **validation_missing**: permutation baseline; alternate fold manifests / repeated CV
"""
    (tmp_path / "outputs" / "final_report.md").write_text(report, encoding="utf-8")

    bundle = build_autoresearch_review_bundle(tmp_path)

    assert bundle.claim_strength_declared == "scientifically_convincing"
    assert bundle.validation_missing_declared == [
        "permutation baseline",
        "alternate fold manifests / repeated CV",
    ]
    assert set(bundle.self_critique_sections) == {
        "so what",
        "method sensitivity",
        "structured exploratory pass",
        "claim strength",
    }


# ---------------------------------------------------------------------------
# Claim-strength clamping & helper-adoption tests (P2)
# ---------------------------------------------------------------------------


_VALIDATION_NAMES = (
    "permutation_baseline",
    "alternate_folds",
    "deterministic_audit",
    "alternate_parcellation_or_gsr",
    "external_cohort_replication",
)


def _make_bundle(
    *,
    claim_strength_declared: str | None,
    present_categories: tuple[str, ...] = (),
    final_report_text: str = "stub report",
) -> AutoresearchReviewBundle:
    """Construct a minimally-populated synthetic AutoresearchReviewBundle."""

    validation_evidence = [
        ValidationEvidenceItem(
            name=name,
            status="present" if name in present_categories else "missing",
            artifact_paths=["/tmp/x"] if name in present_categories else [],
            report_mentions=[],
            summary="",
        )
        for name in _VALIDATION_NAMES
    ]
    return AutoresearchReviewBundle(
        task_id="test_task",
        autoresearch_dir="/tmp/auto",
        logs_dir=None,
        fingerprint="deadbeef",
        final_report_present=True,
        ledger_row_count=1,
        latest_iteration=0,
        best_iteration=0,
        latest_summary=None,
        best_summary=None,
        recent_iterations=[],
        component_summaries=[],
        quality_summary={},
        claim_strength_declared=claim_strength_declared,
        validation_missing_declared=[],
        validation_evidence=validation_evidence,
        self_critique_sections=["so what", "method sensitivity", "structured exploratory pass", "claim strength"],
        final_report_text=final_report_text,
        review_context={},
    )


def _write_workspace_with_evidence(
    root: Path,
    *,
    claim_strength: str,
    extra_artifacts: tuple[str, ...] = (),
) -> None:
    _write_workspace(root, claim_strength=claim_strength)
    outputs = root / "outputs"
    for name in extra_artifacts:
        (outputs / name).write_text("{}", encoding="utf-8")


class TestAutoresearchClaimStrengthClamping:
    def test_no_validation_evidence_yields_contract_satisfied_ceiling(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace(tmp_path, claim_strength="contract_satisfied")
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        assert verdict.overall_decision == "proceed"
        assert verdict.claim_strength == "contract_satisfied"
        assert not any(
            f.rule_id == "AUTORESEARCH_CLAIM_STRENGTH_OVERREACH"
            for f in verdict.correctness.findings
        )

    def test_two_core_validation_items_yields_internally_supported_ceiling(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace_with_evidence(
            tmp_path,
            claim_strength="internally_supported",
            extra_artifacts=(
                "deterministic_audit_001.json",
                "permutation_baseline_001.json",
            ),
        )
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        assert verdict.overall_decision == "proceed"
        assert verdict.claim_strength == "internally_supported"

    def test_replication_plus_validation_yields_scientifically_convincing_ceiling(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace_with_evidence(
            tmp_path,
            claim_strength="scientifically_convincing",
            extra_artifacts=(
                "deterministic_audit_001.json",
                "permutation_baseline_001.json",
                # Bundle builder matches "external cohort" / "replication cohort"
                # / "heldout cohort" substrings against the filename, so the
                # filename needs to contain one of those literal phrases (with
                # the space) for the artifact to register as 'present'.
                "external cohort replication.json",
            ),
        )
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        assert verdict.overall_decision == "proceed"
        assert verdict.claim_strength == "scientifically_convincing"

    def test_declared_scientifically_convincing_without_evidence_blocks_with_overreach_finding(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace(tmp_path, claim_strength="scientifically_convincing")
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        overreach = [
            f
            for f in verdict.correctness.findings
            if f.rule_id == "AUTORESEARCH_CLAIM_STRENGTH_OVERREACH"
        ]
        assert overreach, "expected overreach finding"
        assert overreach[0].action == "block"
        assert verdict.correctness.decision == "block"
        assert verdict.claim_strength is None

    def test_declared_internally_supported_with_only_one_core_validation_blocks(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace_with_evidence(
            tmp_path,
            claim_strength="internally_supported",
            extra_artifacts=("deterministic_audit_001.json",),
        )
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        assert verdict.correctness.decision == "block"
        assert any(
            f.rule_id == "AUTORESEARCH_CLAIM_STRENGTH_OVERREACH"
            for f in verdict.correctness.findings
        )

    def test_declared_matches_earned_no_finding(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace(tmp_path, claim_strength="contract_satisfied")
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        assert not any(
            f.rule_id == "AUTORESEARCH_CLAIM_STRENGTH_OVERREACH"
            for f in verdict.correctness.findings
        )
        assert verdict.claim_strength == "contract_satisfied"

    def test_helper_adoption_populates_report_action_and_required_next_actions(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace_with_evidence(
            tmp_path,
            claim_strength="internally_supported",
            extra_artifacts=(
                "deterministic_audit_001.json",
                "permutation_baseline_001.json",
            ),
        )
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        helper_claim, helper_action, helper_actions, helper_status = (
            derive_verdict_metadata(
                verdict.correctness,
                verdict.judgment,
                verdict.completeness,
                verdict.overall_decision,
                scope="autoresearch_loop",
                validation_evidence_present=True,
                replication_evidence_present=False,
            )
        )

        assert verdict.report_action == helper_action
        # All helper-derived actions appear in the verdict's required_next_actions.
        for action in helper_actions:
            assert action in verdict.required_next_actions
        # Helper-derived validation_status keys are present in the verdict.
        for key in helper_status:
            assert key in verdict.validation_status

    def test_autoresearch_validation_actions_merged_with_helper_actions(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace(tmp_path, claim_strength="contract_satisfied")
        # Force a questionable judgment so overall_decision becomes explore_more
        # and the autoresearch action mapping kicks in.
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(
                decision="questionable",
                issues=["needs more validation"],
                reviewer_questions=["did you run permutation?"],
            ),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        assert verdict.overall_decision == "explore_more"
        # Autoresearch-specific validation action present.
        assert "run_permutation_baseline" in verdict.required_next_actions
        # Helper-derived "answer reviewer question" action present.
        assert any(
            a.startswith("Answer reviewer question:")
            for a in verdict.required_next_actions
        )
        # No duplicates.
        assert len(verdict.required_next_actions) == len(
            set(verdict.required_next_actions)
        )

    def test_validation_status_contains_per_item_and_category_entries(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from brain_researcher.services.review import (
            autoresearch_scientific_review as mod,
        )

        _write_workspace_with_evidence(
            tmp_path,
            claim_strength="internally_supported",
            extra_artifacts=(
                "deterministic_audit_001.json",
                "permutation_baseline_001.json",
            ),
        )
        monkeypatch.setattr(
            mod,
            "run_autoresearch_judgment_critic",
            lambda bundle: JudgmentVerdict(decision="sound"),
        )

        verdict = distill_autoresearch_scientific_review(
            tmp_path,
            use_judgment_critic=True,
            force_recompute=True,
        )

        # Helper-derived top-level keys.
        assert "validation_evidence" in verdict.validation_status
        assert verdict.validation_status["validation_evidence"] == "ok"
        # Per-item category keys (prefixed).
        assert "validation:permutation_baseline" in verdict.validation_status
        assert verdict.validation_status["validation:permutation_baseline"] == "present"
        assert "validation:external_cohort_replication" in verdict.validation_status
