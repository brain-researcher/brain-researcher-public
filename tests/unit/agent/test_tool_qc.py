from types import SimpleNamespace

from brain_researcher.services.agent.tool_qc import (
    DEFAULT_QC_ESCALATION_MODEL,
    DEFAULT_QC_PRIMARY_MODEL,
    ToolQCAction,
    ToolQCVerdict,
    collect_qc_image_paths,
    evaluate_semantic_qc,
    evaluate_qc_for_execution,
    resolve_qc_spec,
)
from brain_researcher.services.tools.spec import (
    ToolQCJudgeConfig,
    ToolQCPrecheckConfig,
    ToolQCRenderContract,
    ToolQCRetryRule,
    ToolQCSpec,
)


def test_resolve_qc_spec_merges_tool_and_step_metadata():
    tool_spec = SimpleNamespace(
        name="fsl_bet",
        qc_spec=ToolQCSpec(
            artifact_output_keys=["qc_png"],
            checklist=["keep cortex", "keep brainstem"],
            failure_modes=["under_strip"],
            judge=ToolQCJudgeConfig(
                cheap_model=DEFAULT_QC_PRIMARY_MODEL,
                uncertain_model=DEFAULT_QC_ESCALATION_MODEL,
                uncertainty_confidence_threshold=0.8,
            ),
            retry_rules=[
                ToolQCRetryRule(
                    match_any_failure_modes=["under_strip"],
                    param_updates={"fractional_intensity": 0.4},
                )
            ],
            render_contract=ToolQCRenderContract(kind="mask_overlay"),
            prechecks=ToolQCPrecheckConfig(
                required_outputs={"mask": "mask_missing"}
            ),
        ),
        metadata={},
    )
    step_metadata = {
        "qc_spec": {
            "artifact_output_keys": ["preview_images"],
            "checklist": ["keep eyes", "keep cortex"],
            "failure_modes": ["over_strip"],
            "judge": {"cheap_model": "custom-lite"},
            "render_contract": {"layout": "tri_planar_montage"},
            "prechecks": {"required_artifacts": {"qc_png": "output_missing"}},
            "retry_rules": [
                {
                    "match_any_failure_modes": ["over_strip"],
                    "param_updates": {"fractional_intensity": 0.6},
                }
            ],
        }
    }

    resolved = resolve_qc_spec(tool_spec, step_metadata)

    assert resolved is not None
    assert resolved.artifact_output_keys == ["qc_png", "preview_images"]
    assert resolved.checklist == ["keep cortex", "keep brainstem", "keep eyes"]
    assert resolved.failure_modes == ["under_strip", "over_strip"]
    assert resolved.judge is not None
    assert resolved.judge.cheap_model == "custom-lite"
    assert resolved.judge.uncertain_model == DEFAULT_QC_ESCALATION_MODEL
    assert resolved.judge.uncertainty_confidence_threshold == 0.8
    assert resolved.render_contract is not None
    assert resolved.render_contract.kind == "mask_overlay"
    assert resolved.render_contract.layout == "tri_planar_montage"
    assert resolved.prechecks is not None
    assert resolved.prechecks.required_outputs == {"mask": "mask_missing"}
    assert resolved.prechecks.required_artifacts == {"qc_png": "output_missing"}
    assert len(resolved.retry_rules) == 2


def test_collect_qc_image_paths_finds_nested_outputs(tmp_path):
    qc_png = tmp_path / "brain_qc.png"
    qc_png.write_text("png", encoding="utf-8")
    qc_jpg = tmp_path / "registration.jpg"
    qc_jpg.write_text("jpg", encoding="utf-8")

    payload = {
        "result": {
            "outputs": {
                "qc_png": str(qc_png),
                "preview_images": [str(qc_jpg), str(qc_png)],
            }
        },
        "artifacts": [{"path": str(qc_jpg)}],
        "notes": "ignore me",
    }

    assets = collect_qc_image_paths(
        payload,
        qc_spec=ToolQCSpec(artifact_output_keys=["qc_png"]),
    )

    assert [asset.path for asset in assets] == [str(qc_png), str(qc_jpg)]
    assert assets[0].source_key == "qc_png"


def test_evaluate_qc_for_execution_escalates_and_accepts_after_second_judge(tmp_path):
    qc_png = tmp_path / "bet_qc.png"
    qc_png.write_text("png", encoding="utf-8")
    tool_spec = SimpleNamespace(
        name="fsl_bet",
        qc_spec=ToolQCSpec(
            artifact_output_keys=["qc_png"],
            checklist=["mask should include cerebellum"],
            failure_modes=["uncertain"],
            judge=ToolQCJudgeConfig(
                cheap_model=DEFAULT_QC_PRIMARY_MODEL,
                uncertain_model=DEFAULT_QC_ESCALATION_MODEL,
                uncertainty_confidence_threshold=0.7,
            ),
        ),
        metadata={},
    )
    call_models: list[str] = []

    def judge_fn(request):
        call_models.append(request.model)
        if len(call_models) == 1:
            return ToolQCVerdict(
                passed=False,
                confidence=0.35,
                uncertain=True,
                failure_modes=["uncertain"],
                evidence=["first pass is ambiguous"],
                summary="uncertain",
                judge_model=request.model,
            )
        return ToolQCVerdict(
            passed=True,
            confidence=0.92,
            uncertain=False,
            failure_modes=[],
            evidence=["mask looks correct"],
            summary="pass",
            judge_model=request.model,
        )

    decision = evaluate_qc_for_execution(
        tool_name="fsl_bet",
        current_params={"fractional_intensity": 0.5},
        tool_spec=tool_spec,
        step_metadata={"step_id": "step-1"},
        exec_result={
            "status": "success",
            "result": {"outputs": {"qc_png": str(qc_png)}},
        },
        context={"qc_judge_fn": judge_fn},
        attempt_index=0,
    )

    assert call_models == [DEFAULT_QC_PRIMARY_MODEL, DEFAULT_QC_ESCALATION_MODEL]
    assert decision.action == ToolQCAction.ACCEPT
    assert decision.verdict is not None
    assert decision.verdict.judge_model == DEFAULT_QC_ESCALATION_MODEL
    assert decision.image_paths[0].path == str(qc_png)


def test_evaluate_qc_for_execution_maps_failure_mode_to_retry_rule(tmp_path):
    qc_png = tmp_path / "bet_qc.png"
    qc_png.write_text("png", encoding="utf-8")
    tool_spec = SimpleNamespace(
        name="fsl_bet",
        qc_spec=ToolQCSpec(
            artifact_output_keys=["qc_png"],
            checklist=["mask should include frontal cortex"],
            failure_modes=["under_strip"],
            retry_rules=[
                ToolQCRetryRule(
                    match_any_failure_modes=["under_strip"],
                    param_updates={
                        "fractional_intensity": 0.4,
                        "robust_center": True,
                    },
                    notes="lower threshold",
                )
            ],
        ),
        metadata={},
    )

    def judge_fn(request):
        return ToolQCVerdict(
            passed=False,
            confidence=0.91,
            uncertain=False,
            failure_modes=["under_strip"],
            evidence=["brainstem missing"],
            summary="under strip",
            judge_model=request.model,
        )

    decision = evaluate_qc_for_execution(
        tool_name="fsl_bet",
        current_params={"fractional_intensity": 0.5},
        tool_spec=tool_spec,
        step_metadata={"step_id": "step-1"},
        exec_result={
            "status": "success",
            "result": {"outputs": {"qc_png": str(qc_png)}},
        },
        context={"qc_judge_fn": judge_fn},
        attempt_index=0,
    )

    assert decision.action == ToolQCAction.RETRY
    assert decision.parameter_patch["fractional_intensity"] == 0.4
    assert decision.parameter_patch["robust_center"] is True
    assert decision.verdict is not None
    assert decision.verdict.failure_modes == ["under_strip"]


def test_evaluate_qc_for_execution_uses_fallback_rule(tmp_path):
    qc_png = tmp_path / "flirt_qc.png"
    qc_png.write_text("png", encoding="utf-8")
    tool_spec = SimpleNamespace(
        name="fsl_flirt",
        qc_spec=ToolQCSpec(
            artifact_output_keys=["qc_png"],
            checklist=["alignment should match template"],
            failure_modes=["misregistration"],
            retry_rules=[
                ToolQCRetryRule(
                    match_any_failure_modes=["misregistration"],
                    fallback_tool="ants_registration",
                    notes="switch tool",
                )
            ],
        ),
        metadata={},
    )

    def judge_fn(request):
        return ToolQCVerdict(
            passed=False,
            confidence=0.84,
            uncertain=False,
            failure_modes=["misregistration"],
            evidence=["overlay is shifted"],
            summary="misregistered",
            judge_model=request.model,
        )

    decision = evaluate_qc_for_execution(
        tool_name="fsl_flirt",
        current_params={"dof": 12},
        tool_spec=tool_spec,
        step_metadata={"step_id": "step-2"},
        exec_result={
            "status": "success",
            "result": {"outputs": {"qc_png": str(qc_png)}},
        },
        context={"qc_judge_fn": judge_fn},
        attempt_index=0,
    )

    assert decision.action == ToolQCAction.FALLBACK
    assert decision.fallback_tool == "ants_registration"
    assert decision.verdict is not None


def test_evaluate_semantic_qc_precheck_failure_short_circuits_judge(tmp_path):
    qc_png = tmp_path / "bet_qc.png"
    qc_png.write_text("png", encoding="utf-8")
    judge_called = {"value": False}

    def judge_fn(_request):
        judge_called["value"] = True
        raise AssertionError("judge should not run when deterministic precheck fails")

    evaluation = evaluate_semantic_qc(
        tool_name="fsl_bet",
        parameters={"fractional_intensity": 0.5},
        payload={"outputs": {"qc_png": str(qc_png)}},
        qc_spec=ToolQCSpec(
            artifact_output_keys=["qc_png"],
            failure_modes=["mask_missing", "output_missing"],
            prechecks=ToolQCPrecheckConfig(
                required_outputs={"mask": "mask_missing"}
            ),
            retry_rules=[
                ToolQCRetryRule(
                    match_any_failure_modes=["mask_missing"],
                    param_updates={"robust_center": True},
                )
            ],
        ),
        attempt_index=0,
        context={"semantic_qc_enabled": True, "qc_judge_fn": judge_fn},
    )

    assert judge_called["value"] is False
    assert evaluation.status == "fail"
    assert evaluation.judge_result is not None
    assert evaluation.judge_result.judge_model == "deterministic_precheck"
    assert evaluation.judge_result.failure_modes == ["mask_missing"]
    assert evaluation.retry_decision is not None
    assert evaluation.retry_decision.adjusted_params == {
        "fractional_intensity": 0.5,
        "robust_center": True,
    }


def test_evaluate_semantic_qc_without_prechecks_preserves_skip_behavior():
    evaluation = evaluate_semantic_qc(
        tool_name="fsl_bet",
        parameters={"fractional_intensity": 0.5},
        payload={"outputs": {}},
        qc_spec=ToolQCSpec(artifact_output_keys=["qc_png"]),
        attempt_index=0,
        context={"semantic_qc_enabled": True},
    )

    assert evaluation.status == "skip"
    assert evaluation.skip_reason == "no_qc_artifacts"
