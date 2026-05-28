"""Unit tests for the domain-grounded code review layer (Phase 1 — plan-time, no KG)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchLineDirective,
)
from brain_researcher.core.contracts.code_review import (
    CodeReviewBundle,
)
from brain_researcher.core.contracts.scientific_review import (
    CompletenessVerdict,
    CorrectnessVerdict,
    JudgmentVerdict,
    ScientificReviewVerdict,
)
from brain_researcher.services.review.rule_engine import ReviewRuleEngine
from brain_researcher.services.review.verdict_builder import produce_verdict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> ReviewRuleEngine:
    """Load the real review_rules.yaml."""
    rules_path = (
        Path(__file__).resolve().parents[3] / "configs" / "review_rules.yaml"
    )
    return ReviewRuleEngine.from_yaml(rules_path)


def _bundle(
    steps: list[dict] | None = None,
    modalities: list[str] | None = None,
    spaces: list[str] | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=steps or [],
        declared_modalities=modalities or [],
        declared_spaces=spaces or [],
    )


def _run_asl_quant_review(
    *,
    task_profile,
    method_contract,
    subject_summaries,
    cohort_summary=None,
):
    from brain_researcher.services.review.asl_quant_critic import (
        build_asl_quant_control,
        review_asl_quant,
    )

    verdict = review_asl_quant(
        task_profile=task_profile,
        method_contract=method_contract,
        subject_summaries=subject_summaries,
        cohort_summary=cohort_summary,
    )
    review_control = build_asl_quant_control(
        verdict=verdict,
        subject_summaries=subject_summaries,
    )
    return {
        "ok": True,
        **verdict.model_dump(),
        "review_control": review_control,
    }


# ---------------------------------------------------------------------------
# 1. Modality mismatch → block
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_eeg_volumetric_mni_is_blocked():
    engine = _make_engine()
    bundle = _bundle(
        steps=[{"tool": "atlas_apply", "params": {}, "step_id": "s1"}],
        modalities=["eeg"],
        spaces=["MNI152"],
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "block"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_MODALITY_MISMATCH" in rule_ids


# ---------------------------------------------------------------------------
# 2. Clean plan → approve
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_clean_plan_is_approved():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {"tool": "bet", "params": {}, "step_id": "s1"},
            {"tool": "fsl_flirt", "params": {}, "step_id": "s2"},
            {"tool": "nilearn_smooth_img", "params": {"fwhm": 6.0}, "step_id": "s3"},
            {"tool": "extract_timeseries", "params": {"tr": 2.0}, "step_id": "s4"},
        ],
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "approve"
    assert verdict.findings == []


# ---------------------------------------------------------------------------
# 3. FWHM too large → approve_with_warnings
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_large_fwhm_produces_warning():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {"tool": "nilearn_smooth_img", "params": {"fwhm": 15.0}, "step_id": "s1"},
        ],
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "approve_with_warnings"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_FWHM_OOB" in rule_ids


@pytest.mark.unit
def test_rule_tags_flow_into_reason_tags():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {"tool": "nilearn_smooth_img", "params": {"fwhm": 15.0}, "step_id": "s1"},
        ],
    )
    verdict = produce_verdict(bundle, engine=engine)
    finding = next(f for f in verdict.findings if f.rule_id == "REVIEW_FWHM_OOB")
    assert "smoothing" in finding.reason_tags
    assert "fmri" in finding.reason_tags


# ---------------------------------------------------------------------------
# 4. Tool order violation → revise or block
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_atlas_before_registration_is_rejected():
    engine = _make_engine()
    # atlas step comes before registration step
    bundle = _bundle(
        steps=[
            {"tool": "extract_timeseries", "params": {}, "step_id": "s1"},
            {"tool": "fsl_flirt", "params": {}, "step_id": "s2"},
        ],
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision in {"revise", "block"}
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_REGISTRATION_ORDER" in rule_ids


# ---------------------------------------------------------------------------
# 5. Empty plan → block
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_empty_plan_is_blocked():
    engine = _make_engine()
    bundle = _bundle(steps=[])
    verdict = produce_verdict(bundle, engine=engine)
    assert verdict.decision == "block"
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_NO_STEPS" in rule_ids


# ---------------------------------------------------------------------------
# 6. FWHM too small → block (severity=error, action=block)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fwhm_below_minimum_is_blocked():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {"tool": "fslmaths", "params": {"fwhm": 0.5}, "step_id": "s1"},
        ],
    )
    verdict = produce_verdict(bundle, engine=engine)
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_FWHM_LOW" in rule_ids
    # severity=error → revise (block requires critical or action=block handling)
    # The FWHM_LOW rule has action=block but severity=error.
    # Our roll-up treats severity=error → revise, so either revise or block is acceptable.
    assert verdict.decision in {"revise", "block"}


# ---------------------------------------------------------------------------
# 7. GLM without confound step → approve_with_warnings (severity=warn)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_glm_without_confounds_warns():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {"tool": "fsl_flirt", "params": {}, "step_id": "s1"},
            {"tool": "glm_first_level", "params": {}, "step_id": "s2"},
        ],
    )
    verdict = produce_verdict(bundle, engine=engine)
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_MISSING_CONFOUND_REGRESSION" in rule_ids
    assert verdict.decision in {"approve_with_warnings", "revise", "block"}


# ---------------------------------------------------------------------------
# 8. pipeline_plan_validate backward compat — response gains code_review key
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pipeline_plan_validate_has_code_review_key(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    # Minimal stubs so the server doesn't need Neo4j / toolspec registry
    monkeypatch.setattr(srv, "_get_toolspec_with_schema", lambda tool_id: None)
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: [])

    plan = {"steps": [{"tool": "fslmaths", "params": {}}]}
    result = srv.pipeline_plan_validate(plan)

    assert "ok" in result
    assert "code_review" in result


# ---------------------------------------------------------------------------
# 9. pipeline_plan_review MCP tool — missing registration step produces finding
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pipeline_plan_review_detects_atlas_before_registration(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_get_toolspec_with_schema", lambda tool_id: None)
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: [])

    # atlas step before registration
    plan = {
        "steps": [
            {"tool": "extract_timeseries", "params": {}},
            {"tool": "fsl_flirt", "params": {}},
        ]
    }
    result = srv.pipeline_plan_review(plan)

    assert result.get("ok") is True
    assert result.get("decision") != "approve"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "REVIEW_REGISTRATION_ORDER" in finding_ids


# ---------------------------------------------------------------------------
# 10. Checklist is populated before findings
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_checklist_generated_before_findings():
    engine = _make_engine()
    bundle = _bundle(
        steps=[{"tool": "fsl_flirt", "params": {"tr": 2.0}, "step_id": "s1"}],
    )
    verdict = produce_verdict(bundle, engine=engine)
    assert len(verdict.checklist_generated) > 0
    # Checklist should include step count info
    assert any("step" in item.lower() for item in verdict.checklist_generated)


# ---------------------------------------------------------------------------
# 11. KG context extraction for B1
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_plan_review_bundle_extracts_kg_context():
    from brain_researcher.services.review.bundle_builder import build_plan_review_bundle

    plan = SimpleNamespace(
        steps=[
            {
                "tool": "glm_first_level",
                "params": {
                    "task": "nback",
                    "study_id": "ds000001",
                    "high_pass": 0.015,
                    "design": "within-subject",
                    "test_type": "independent-samples t-test",
                },
                "step_id": "s1",
            }
        ]
    )

    bundle = build_plan_review_bundle(plan)

    assert bundle.kg_context["task"] == "nback"
    assert bundle.kg_context["study_id"] == "ds000001"
    assert bundle.kg_context["analysis_family"] == "glm"
    assert bundle.kg_context["design_type"] == "repeated_measures"
    assert bundle.kg_context["statistical_method"] == "independent_t_test"


# ---------------------------------------------------------------------------
# 12. use_kg=True can add contextual high-pass finding
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_use_kg_adds_contextual_high_pass_finding():
    engine = _make_engine()
    bundle = CodeReviewBundle(
        plan_steps=[
            {
                "tool": "glm_first_level",
                "params": {"high_pass": 0.015},
                "step_id": "s1",
            }
        ],
        kg_context={"task": "working memory"},
    )

    with patch(
        "brain_researcher.services.review.kg_parameter_grounding.get_glm_priors",
        return_value={
            "priors": {"high_pass": {"100": 1.0}},
            "coverage": {"high_pass": 1.0},
            "scope": "task",
        },
    ):
        verdict = produce_verdict(bundle, engine=engine, use_kg=True)

    finding_ids = [f.rule_id for f in verdict.findings]
    assert "REVIEW_HIGH_PASS_TOO_AGGRESSIVE" in finding_ids
    assert "REVIEW_HIGH_PASS_TOO_AGGRESSIVE" in verdict.kg_rules_consulted
    finding = next(f for f in verdict.findings if f.rule_id == "REVIEW_HIGH_PASS_TOO_AGGRESSIVE")
    assert finding.kg_evidence
    assert "contextual KG prior support" in finding.message


# ---------------------------------------------------------------------------
# 13. use_kg=True can clear a generic high-pass warning when KG supports it
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_use_kg_clears_supported_high_pass_warning():
    engine = _make_engine()
    bundle = CodeReviewBundle(
        plan_steps=[
            {
                "tool": "nilearn_clean_img",
                "params": {"high_pass": 128},
                "step_id": "s1",
            }
        ],
        kg_context={"task": "working memory"},
    )

    with patch(
        "brain_researcher.services.review.kg_parameter_grounding.get_glm_priors",
        return_value={
            "priors": {"high_pass": {"128": 1.0, "200": 0.2}},
            "coverage": {"high_pass": 1.0},
            "scope": "task",
        },
    ):
        verdict = produce_verdict(bundle, engine=engine, use_kg=True)

    assert all(f.rule_id != "REVIEW_HIGH_PASS_TOO_AGGRESSIVE" for f in verdict.findings)


# ---------------------------------------------------------------------------
# 14. pipeline_plan_review threads use_kg to verdict_builder
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pipeline_plan_review_use_kg_threads_through(monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "_get_toolspec_with_schema", lambda tool_id: None)
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: [])

    plan = {
        "steps": [
            {
                "tool": "glm_first_level",
                "params": {"task": "nback", "high_pass": 0.015},
            }
        ]
    }

    with patch(
        "brain_researcher.services.review.kg_parameter_grounding.get_glm_priors",
        return_value={
            "priors": {"high_pass": {"100": 1.0}},
            "coverage": {"high_pass": 1.0},
            "scope": "task",
        },
    ):
        without_kg = srv.pipeline_plan_review(plan, use_kg=False)
        with_kg = srv.pipeline_plan_review(plan, use_kg=True)

    without_ids = [f["rule_id"] for f in without_kg.get("findings", [])]
    with_ids = [f["rule_id"] for f in with_kg.get("findings", [])]
    assert "REVIEW_HIGH_PASS_TOO_AGGRESSIVE" not in without_ids
    assert "REVIEW_HIGH_PASS_TOO_AGGRESSIVE" in with_ids


# ---------------------------------------------------------------------------
# 14b. QSM anti-pitfall review catches total-field inversion
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pipeline_plan_review_rejects_qsm_total_field_direct_inversion():
    from brain_researcher.services.mcp import server as srv

    plan = {
        "steps": [
            "Compute inter-echo phase difference and convert to a total field.",
            "Run ADMM/TV dipole inversion directly on the total field.",
        ]
    }

    result = srv.pipeline_plan_review(
        plan,
        workflow_id="qsm_reconstruction",
        use_kg=False,
    )

    assert result.get("ok") is True
    assert result.get("decision") == "block"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "QSM_TOTAL_FIELD_DIRECT_INVERSION_FORBIDDEN" in finding_ids
    assert "QSM_LOCAL_FIELD_REQUIRED_BEFORE_DIPOLE_INVERSION" in finding_ids


@pytest.mark.unit
def test_pipeline_plan_review_rejects_structured_qsm_total_field_input():
    from brain_researcher.services.mcp import server as srv

    plan = {
        "steps": [
            {
                "tool": "phase_fit",
                "params": {
                    "operation": "Compute inter-echo phase difference and convert to total field"
                },
            },
            {
                "tool": "admm_tv_dipole_inversion",
                "params": {"input": "total field", "operation": "direct inversion"},
            },
        ]
    }

    result = srv.pipeline_plan_review(
        plan,
        workflow_id="qsm_reconstruction",
        use_kg=False,
    )

    assert result.get("ok") is True
    assert result.get("decision") == "block"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "QSM_TOTAL_FIELD_DIRECT_INVERSION_FORBIDDEN" in finding_ids


@pytest.mark.unit
def test_pipeline_plan_review_rejects_vague_qsm_local_field_dataflow():
    from brain_researcher.services.mcp import server as srv

    plan = {
        "steps": [
            {"name": "field_fitting", "description": "extract total field"},
            {"name": "background_or_local_field_removal"},
            {"name": "dipole_inversion"},
        ]
    }

    result = srv.pipeline_plan_review(
        plan,
        workflow_id="qsm_reconstruction",
        use_kg=False,
    )

    assert result.get("ok") is True
    assert result.get("decision") == "block"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "QSM_AMBIGUOUS_LOCAL_FIELD_DATAFLOW" in finding_ids


@pytest.mark.unit
def test_pipeline_plan_review_approves_qsm_local_field_dataflow():
    from brain_researcher.services.mcp import server as srv

    plan = {
        "steps": [
            "Compute phase differences using delta_TE and unwrap phase.",
            "Fit the total field from echo times.",
            "Run RESHARP/V-SHARP background removal to obtain a local field.",
            "Run TV/ADMM dipole inversion using the local field as input.",
        ]
    }

    result = srv.pipeline_plan_review(
        plan,
        workflow_id="qsm_reconstruction",
        use_kg=False,
    )

    assert result.get("ok") is True
    assert result.get("decision") == "approve"
    domain_review = result.get("domain_invariant_review", {})
    assert domain_review.get("task_type") == "qsm_reconstruction"
    assert domain_review.get("advice_mode") == "audit_only"
    assert domain_review.get("hard_constraints")
    assert domain_review.get("qc_protocol")


@pytest.mark.unit
def test_pipeline_plan_review_warns_qsm_tkd_contrast_loss():
    from brain_researcher.services.mcp import server as srv

    plan = {
        "steps": [
            "Use delta_TE phase processing.",
            "Run V-SHARP background removal to obtain local field.",
            "Use TKD inversion with the local field as input for the susceptibility map.",
        ]
    }

    result = srv.pipeline_plan_review(
        plan,
        workflow_id="qsm_reconstruction",
        use_kg=False,
    )

    assert result.get("ok") is True
    assert result.get("decision") == "revise"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "QSM_BARE_TKD_CONTRAST_LOSS_RISK" in finding_ids


@pytest.mark.unit
def test_pipeline_plan_review_requires_qsm_te_scaling_revision():
    from brain_researcher.services.mcp import server as srv

    plan = {
        "steps": [
            "Unwrap phase and fit the total field.",
            "Run RESHARP background removal to obtain local field.",
            "Run TV dipole inversion using local field as input.",
        ]
    }

    result = srv.pipeline_plan_review(
        plan,
        workflow_id="qsm_reconstruction",
        use_kg=False,
    )

    assert result.get("ok") is True
    assert result.get("decision") == "revise"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "QSM_PHASE_UNIT_TE_CONVERSION_CHECK_MISSING" in finding_ids


@pytest.mark.unit
def test_qsm_implementation_review_blocks_direct_field_inversion():
    from brain_researcher.services.mcp import server as srv

    code = """
field_ppm = compute_inter_echo_field(phase, echo_times)
chi = admm_tv_dipole_inversion(field_ppm)
"""

    result = srv.qsm_implementation_review(code, filename="run_qsm.py")

    assert result.get("ok") is True
    assert result.get("decision") == "block"
    finding_ids = [f["rule_id"] for f in result.get("findings", [])]
    assert "QSM_IMPLEMENTATION_DIRECT_FIELD_INVERSION" in finding_ids
    assert result.get("domain_invariant_review", {}).get("advice_mode") == "audit_only"


@pytest.mark.unit
def test_qsm_implementation_review_approves_explicit_local_field_inversion():
    from brain_researcher.services.mcp import server as srv

    code = """
total_field = fit_total_field(phase, echo_times)
local_field = resharp_background_removal(total_field, mask)
chi = admm_tv_dipole_inversion(local_field)
qc = {"finite": True, "highpass": "checked"}
"""

    result = srv.qsm_implementation_review(code, filename="run_qsm.py")

    assert result.get("ok") is True
    assert result.get("decision") == "approve"


# ---------------------------------------------------------------------------
# 15. ASL quant second-pass critic
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_asl_quant_review_approves_consistent_payload():
    result = _run_asl_quant_review(
        task_profile="asl_mixed_quant_v1",
        method_contract={
            "separate_single_and_multi_pld": True,
            "uses_joint_multi_pld_fit": True,
            "averages_single_pld_cbf_across_plds": False,
            "uses_bids_pld_convention": True,
            "uses_slice_timing_for_2d": True,
            "applies_m0_scale_factor": True,
        },
        subject_summaries=[
            {
                "subject_id": "sub-01",
                "subject_type": "synthetic",
                "regime": "multi_pld",
                "acquisition_type": "3d",
                "brain_p99": 120.0,
                "gm_mean_proxy": 61.0,
                "wm_mean_proxy": 22.0,
                "gm_wm_ratio_proxy": 2.1,
            },
            {
                "subject_id": "sub-19861",
                "subject_type": "real",
                "regime": "single_pld",
                "acquisition_type": "3d",
                "m0_scale_factor_present": True,
                "gm_mean_proxy": 61.0,
                "wm_mean_proxy": 45.0,
                "gm_wm_ratio_proxy": 1.36,
            },
        ],
        cohort_summary={
            "real_gm_mean": 62.0,
            "real_gm_cv": 0.18,
            "real_gm_ratio_std": 0.21,
        },
    )

    assert result["ok"] is True
    assert result["decision"] == "approve"
    assert result["findings"] == []
    assert result["review_control"]["should_revise"] is False
    assert result["review_control"]["rewrite_scope"] == "none"


@pytest.mark.unit
def test_asl_quant_review_blocks_multi_pld_single_formula_averaging():
    result = _run_asl_quant_review(
        task_profile="asl_mixed_quant_v1",
        method_contract={
            "separate_single_and_multi_pld": True,
            "uses_joint_multi_pld_fit": False,
            "averages_single_pld_cbf_across_plds": True,
            "uses_bids_pld_convention": False,
            "applies_m0_scale_factor": True,
        },
        subject_summaries=[
            {
                "subject_id": "sub-01",
                "subject_type": "synthetic",
                "regime": "multi_pld",
                "acquisition_type": "3d",
                "brain_p99": 118.0,
                "gm_mean_proxy": 58.0,
                "wm_mean_proxy": 21.0,
                "gm_wm_ratio_proxy": 2.0,
            }
        ],
    )

    finding_ids = [f["rule_id"] for f in result["findings"]]
    assert result["ok"] is True
    assert result["decision"] == "block"
    assert "ASL_MULTI_PLD_REQUIRES_JOINT_FIT" in finding_ids
    assert "ASL_MULTI_PLD_SINGLE_FORMULA_AVERAGING" in finding_ids
    assert "ASL_BIDS_PLD_CONVENTION_REQUIRED" in finding_ids
    assert result["review_control"]["should_revise"] is True
    assert result["review_control"]["rewrite_scope"] == "block"


@pytest.mark.unit
def test_asl_quant_review_flags_numeric_outliers_and_cohort_drift():
    result = _run_asl_quant_review(
        task_profile="asl_mixed_quant_v1",
        method_contract={
            "separate_single_and_multi_pld": True,
            "uses_joint_multi_pld_fit": True,
            "averages_single_pld_cbf_across_plds": False,
            "uses_bids_pld_convention": True,
            "uses_slice_timing_for_2d": True,
            "applies_m0_scale_factor": True,
        },
        subject_summaries=[
            {
                "subject_id": "sub-03",
                "subject_type": "synthetic",
                "regime": "multi_pld",
                "acquisition_type": "3d",
                "brain_p99": 240.0,
                "gm_mean_proxy": 101.0,
                "wm_mean_proxy": 48.0,
                "gm_wm_ratio_proxy": 2.1,
                "fit_curve_corr_proxy": 0.996,
                "fit_curve_nrmse_proxy": 0.011,
                "delta_m_curve_means": [0.91, 0.88, 0.73],
                "predicted_delta_m_curve_means": [0.90, 0.87, 0.72],
            }
        ],
        cohort_summary={
            "real_gm_mean": 77.0,
            "real_gm_cv": 0.08,
            "real_gm_ratio_std": 0.18,
        },
    )

    finding_ids = [f["rule_id"] for f in result["findings"]]
    assert result["ok"] is True
    assert result["decision"] == "approve_with_warnings"
    assert "ASL_SYNTHETIC_P99_TOO_HIGH" in finding_ids
    assert "ASL_SYNTHETIC_GM_MEAN_OUT_OF_RANGE" in finding_ids
    assert "ASL_SYNTHETIC_WM_MEAN_OUT_OF_RANGE" in finding_ids
    assert "ASL_REAL_GM_CV_OUT_OF_RANGE" in finding_ids
    assert "ASL_REAL_GM_MEAN_OUT_OF_RANGE" in finding_ids
    assert result["review_control"]["should_revise"] is True
    assert result["review_control"]["rewrite_scope"] == "amplitude_only"
    assert "pld_att_convention" in result["review_control"]["forbidden_changes"]
    assert "cbf_prefactor_units" in result["review_control"]["targeted_checks"]


@pytest.mark.unit
def test_asl_quant_review_revises_on_low_fit_observables():
    result = _run_asl_quant_review(
        task_profile="asl_mixed_quant_v1",
        method_contract={
            "separate_single_and_multi_pld": True,
            "uses_joint_multi_pld_fit": True,
            "averages_single_pld_cbf_across_plds": False,
            "uses_bids_pld_convention": True,
            "uses_slice_timing_for_2d": True,
            "applies_m0_scale_factor": True,
        },
        subject_summaries=[
            {
                "subject_id": "sub-02",
                "subject_type": "synthetic",
                "regime": "multi_pld",
                "acquisition_type": "2d",
                "has_slice_timing": True,
                "slice_timing_applied": False,
                "effective_pld_span_s": 0.0,
                "fit_curve_corr_proxy": 0.81,
                "fit_curve_nrmse_proxy": 0.34,
                "delta_m_curve_means": [0.91, 0.88, 0.73],
                "predicted_delta_m_curve_means": [0.22, 0.45, 0.89],
            }
        ],
    )

    finding_ids = [f["rule_id"] for f in result["findings"]]
    assert result["ok"] is True
    assert result["decision"] == "revise"
    assert "ASL_MULTI_PLD_FIT_CORRELATION_LOW" in finding_ids
    assert "ASL_MULTI_PLD_FIT_NRMSE_HIGH" in finding_ids
    assert "ASL_MULTI_PLD_DELTA_M_CURVE_MISMATCH" in finding_ids
    assert "ASL_2D_EFFECTIVE_PLD_NOT_APPLIED" in finding_ids
    assert "ASL_2D_EFFECTIVE_PLD_SPAN_ZERO" in finding_ids
    assert result["review_control"]["should_revise"] is True
    assert result["review_control"]["rewrite_scope"] == "fit_model"


@pytest.mark.unit
def test_asl_quant_review_blocks_missing_m0_scaling_for_scaled_subjects():
    result = _run_asl_quant_review(
        task_profile="asl_mixed_quant_v1",
        method_contract={
            "separate_single_and_multi_pld": True,
            "uses_joint_multi_pld_fit": True,
            "averages_single_pld_cbf_across_plds": False,
            "uses_bids_pld_convention": True,
            "uses_slice_timing_for_2d": False,
            "applies_m0_scale_factor": False,
        },
        subject_summaries=[
            {
                "subject_id": "sub-02",
                "subject_type": "synthetic",
                "regime": "multi_pld",
                "acquisition_type": "2d",
                "has_slice_timing": True,
                "m0_scale_factor_present": True,
                "brain_p99": 118.0,
                "gm_mean_proxy": 59.0,
                "wm_mean_proxy": 21.0,
                "gm_wm_ratio_proxy": 2.0,
            }
        ],
    )

    finding_ids = [f["rule_id"] for f in result["findings"]]
    assert result["ok"] is True
    assert result["decision"] == "block"
    assert "ASL_M0_SCALE_FACTOR_IGNORED" in finding_ids
    assert result["review_control"]["should_revise"] is True
    assert result["review_control"]["rewrite_scope"] == "block"
    assert "ASL_2D_SLICE_TIMING_MISSING" in finding_ids


# ---------------------------------------------------------------------------
# 16. Method appropriateness seed — repeated-measures vs independent t-test
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_method_appropriateness_flags_repeated_measures_independent_ttest():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {
                "tool": "scipy_ttest_ind",
                "params": {
                    "design": "within-subject",
                    "test_type": "independent-samples t-test",
                },
                "step_id": "s1",
            }
        ],
    )

    verdict = produce_verdict(bundle, engine=engine)
    rule_ids = [f.rule_id for f in verdict.findings]
    assert "REPEATED_MEASURES_BLOCKS_INDEPENDENT_T_TEST" in rule_ids
    finding = next(
        f for f in verdict.findings if f.rule_id == "REPEATED_MEASURES_BLOCKS_INDEPENDENT_T_TEST"
    )
    assert finding.severity == "error"
    assert finding.action == "block"
    assert finding.kg_evidence


@pytest.mark.unit
def test_method_appropriateness_allows_paired_ttest_for_repeated_measures():
    engine = _make_engine()
    bundle = _bundle(
        steps=[
            {
                "tool": "scipy_ttest_rel",
                "params": {
                    "design": "within-subject",
                    "test_type": "paired t-test",
                },
                "step_id": "s1",
            }
        ],
    )

    verdict = produce_verdict(bundle, engine=engine)
    assert all(
        f.rule_id != "REPEATED_MEASURES_BLOCKS_INDEPENDENT_T_TEST"
        for f in verdict.findings
    )


@pytest.mark.unit
def test_method_appropriateness_uses_graph_backed_compatibility(monkeypatch):
    import networkx as nx

    from brain_researcher.services.neurokg import query_service

    engine = _make_engine()
    graph = nx.MultiDiGraph()
    graph.add_node(
        "design:repeated_measures",
        id="design:repeated_measures",
        name="Repeated measures",
        labels=["ExperimentalDesign"],
        aliases=["within-subject"],
    )
    graph.add_node(
        "method:independent_t_test",
        id="method:independent_t_test",
        name="Independent samples t-test",
        labels=["StatisticalMethod"],
        aliases=["independent-samples t-test"],
    )
    graph.add_edge(
        "design:repeated_measures",
        "method:independent_t_test",
        type="INCOMPATIBLE_WITH",
    )
    monkeypatch.setattr(
        query_service,
        "get_default_db",
        lambda: SimpleNamespace(graph=graph),
    )

    bundle = _bundle(
        steps=[
            {
                "tool": "scipy_ttest_ind",
                "params": {
                    "design": "within-subject",
                    "test_type": "independent-samples t-test",
                },
                "step_id": "s1",
            }
        ],
    )

    verdict = produce_verdict(bundle, engine=engine)
    finding = next(
        f for f in verdict.findings if f.rule_id == "REPEATED_MEASURES_BLOCKS_INDEPENDENT_T_TEST"
    )
    assert any("relationship_type=INCOMPATIBLE_WITH" in item for item in finding.kg_evidence)
    assert any(item == "graph" for item in finding.kg_evidence)


# ---------------------------------------------------------------------------
# Review handoff directive
# ---------------------------------------------------------------------------

class TestReviewHandoffDirective:
    def test_scientific_handoff_emitted_on_diagnose(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        verdict_dict = {
            "overall_decision": "diagnose",
            "correctness": {
                "decision": "flag",
                "findings": [
                    {"rule_id": "REVIEW_CONDITION_NUMBER_HIGH", "message": "condition number 5000"},
                ],
            },
            "judgment": {
                "decision": "questionable",
                "reviewer_questions": ["Is the confound model sufficient?"],
                "issues": ["method may not match design"],
            },
            "completeness": {
                "decision": "incomplete",
                "checklist": {"atlas_pinned": False},
                "missing_caveats": ["atlas version not specified"],
            },
        }
        directive = _build_review_handoff_directive(verdict_dict, review_type="scientific_review")
        assert directive is not None
        assert directive["protocol"] == "br.review_handoff.directive.v1"
        assert directive["review_type"] == "scientific_review"
        assert directive["inner_verdict"]["overall_decision"] == "diagnose"
        assert directive["inner_verdict"]["missing_caveats"] == ["atlas version not specified"]
        assert directive["inner_verdict"]["missing_checklist_items"] == ["atlas_pinned"]
        assert len(directive["findings_summary"]) == 2
        assert "REVIEW_CONDITION_NUMBER_HIGH" in directive["findings_summary"][0]
        assert "COMPLETENESS: atlas version not specified" in directive["findings_summary"][1]
        assert "Is the confound model sufficient?" in directive["reviewer_questions"]
        assert "method may not match design" in directive["reviewer_questions"]
        assert "scientific review flagged methodological or specification issues" in (
            directive["actions"][0]["prompt"]
        )
        assert len(directive["actions"]) == 2

    def test_scientific_handoff_absent_on_proceed(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        verdict_dict = {
            "overall_decision": "proceed",
            "correctness": {"decision": "pass", "findings": []},
            "judgment": {"decision": "sound", "reviewer_questions": [], "issues": []},
            "completeness": {"decision": "complete"},
        }
        assert _build_review_handoff_directive(verdict_dict, review_type="scientific_review") is None

    def test_scientific_handoff_findings_truncated(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        findings = [
            {"rule_id": f"RULE_{i}", "message": f"finding {i}"} for i in range(10)
        ]
        verdict_dict = {
            "overall_decision": "stop_with_rationale",
            "correctness": {"decision": "block", "findings": findings},
            "judgment": {"decision": "sound", "reviewer_questions": [], "issues": []},
            "completeness": {"decision": "complete"},
        }
        directive = _build_review_handoff_directive(verdict_dict, review_type="scientific_review")
        assert directive is not None
        assert len(directive["findings_summary"]) == 5

    def test_scientific_handoff_includes_completeness_details_when_no_findings(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        verdict_dict = {
            "overall_decision": "explore_more",
            "correctness": {"decision": "pass", "findings": []},
            "judgment": {"decision": "sound", "reviewer_questions": [], "issues": []},
            "completeness": {
                "decision": "incomplete",
                "checklist": {"confounds_declared": False, "atlas_pinned": False},
                "missing_caveats": ["confound model not specified"],
            },
        }
        directive = _build_review_handoff_directive(verdict_dict, review_type="scientific_review")
        assert directive is not None
        assert directive["findings_summary"] == ["COMPLETENESS: confound model not specified"]
        assert directive["inner_verdict"]["missing_checklist_items"] == [
            "confounds_declared",
            "atlas_pinned",
        ]

    def test_scientific_handoff_reviewer_questions_passed_through(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        questions = ["Q1?", "Q2?", "Q3?"]
        verdict_dict = {
            "overall_decision": "explore_more",
            "correctness": {"decision": "pass", "findings": []},
            "judgment": {"decision": "questionable", "reviewer_questions": questions, "issues": []},
            "completeness": {"decision": "incomplete"},
        }
        directive = _build_review_handoff_directive(verdict_dict, review_type="scientific_review")
        assert directive is not None
        for q in questions:
            assert q in directive["reviewer_questions"]

    def test_scientific_handoff_includes_line_directive(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        verdict_dict = {
            "overall_decision": "explore_more",
            "correctness": {"decision": "pass", "findings": []},
            "judgment": {"decision": "questionable", "reviewer_questions": [], "issues": []},
            "completeness": {"decision": "complete", "checklist": {}},
            "line_directive": {
                "line_type": "validation",
                "next_line_type": "validation",
                "loaded_modules": ["base", "robustness", "confound"],
                "forbidden_modules": ["model_scaling"],
                "training_backend": "cpu_local",
                "success_criterion": "establish_internal_support_for_top_components",
            },
        }
        directive = _build_review_handoff_directive(
            verdict_dict, review_type="scientific_review"
        )
        assert directive is not None
        assert directive["inner_verdict"]["line_directive"]["line_type"] == "validation"
        assert directive["inner_verdict"]["line_directive"]["loaded_modules"] == [
            "base",
            "robustness",
            "confound",
        ]

    def test_code_review_handoff_on_block(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        verdict_dict = {
            "decision": "block",
            "risk_level": "high",
            "findings": [
                {"rule_id": "REVIEW_SCRUBBING_RATE_HIGH", "message": ">20% volumes scrubbed"},
            ],
        }
        directive = _build_review_handoff_directive(verdict_dict, review_type="code_review")
        assert directive is not None
        assert directive["inner_verdict"]["decision"] == "block"
        assert len(directive["findings_summary"]) == 1
        assert "code review flagged artifact, QC, or execution issues" in (
            directive["actions"][0]["prompt"]
        )
        assert "QC or artifact issues" in directive["reviewer_questions"][0]

    def test_code_review_handoff_absent_on_approve(self):
        from brain_researcher.services.mcp.server import _build_review_handoff_directive

        verdict_dict = {"decision": "approve", "risk_level": "low", "findings": []}
        assert _build_review_handoff_directive(verdict_dict, review_type="code_review") is None



@pytest.mark.unit
def test_run_autoresearch_scientific_review_returns_line_directive_and_handoff(
    monkeypatch,
):
    from brain_researcher.services.mcp.server import run_autoresearch_scientific_review

    verdict = ScientificReviewVerdict(
        correctness=CorrectnessVerdict(decision="pass", findings=[]),
        judgment=JudgmentVerdict(
            decision="questionable",
            reviewer_questions=["Need one more validation pass?"],
        ),
        completeness=CompletenessVerdict(decision="complete", checklist={}),
        review_scope="autoresearch_loop",
        overall_decision="explore_more",
        claim_strength="internally_supported",
        report_action="continue_loop",
        required_next_actions=["run_alternate_parcellation_or_gsr_sensitivity"],
        validation_status={"validation:alternate_parcellation_or_gsr": "missing"},
        line_directive=AutoresearchLineDirective(
            line_type="sensitivity",
            next_line_type="sensitivity",
            loaded_modules=["base", "robustness", "representation_scaling", "confound"],
            forbidden_modules=["model_scaling", "generalization", "foundation_transfer"],
            training_backend="cpu_local",
            success_criterion="stress_test_whether_the_claim_survives_sensitive_design_choices",
        ),
        rationale="Need one more sensitivity line before closeout.",
    )

    def _fake_distill(*args, **kwargs):
        return verdict

    monkeypatch.setattr(
        "brain_researcher.services.review.autoresearch_scientific_review.distill_autoresearch_scientific_review",
        _fake_distill,
    )

    result = run_autoresearch_scientific_review(
        "/tmp/fake-autoresearch",
        logs_dir="/tmp/fake-logs",
        task_id="default",
        use_judgment_critic=True,
        force_recompute=True,
    )

    assert result["ok"] is True
    assert result["line_directive"]["line_type"] == "sensitivity"
    assert result["line_directive"]["next_line_type"] == "sensitivity"
    assert result["_agent_directive"]["review_handoff"]["inner_verdict"]["line_directive"][
        "line_type"
    ] == "sensitivity"
