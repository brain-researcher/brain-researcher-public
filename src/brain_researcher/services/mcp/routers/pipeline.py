"""Pipeline plan validation / review MCP tools.

Carved out of ``mcp/server.py`` as part of splitting that monolith into
per-domain router modules. Importing this module registers the
``pipeline_plan_validate`` / ``pipeline_plan_review`` tools on the shared
FastMCP instance via the ``@mcp.tool()`` decorator (an import side effect), so
``server.py`` imports it for its effect.

Only the read-only plan validation/review tools live here. ``pipeline_execute``
is intentionally left in server: it is run-orchestration (RunRecord / _save_run
/ _execute_run / _run_dir + the run-store helpers) and belongs with the
run-store substrate extraction, not this leaf carve.

The plan-coercion / normalization / QSM-review helpers stay in ``server`` (they
have other callers, incl. pipeline_execute) and are imported back here.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.services.mcp.server import (
    _QSM_FORBIDDEN_GUIDANCE,
    _QSM_HARD_CONSTRAINTS,
    _QSM_NON_DISPLACEMENT_NOTICE,
    _QSM_QC_PROTOCOL,
    _clone_jsonable,
    _coerce_plan,
    _critic_feedback_from_issues,
    _extract_policy_issues_from_issue_list,
    _new_run_id,
    _normalize_plan_for_run,
    mcp,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    merge_verdicts as _merge_qsm_review_verdicts,
)
from brain_researcher.services.review.qsm_pitfall_critic import (
    review_qsm_plan_payload,
)


@mcp.tool()
def pipeline_plan_validate(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate/normalize a pipeline plan (no execution)."""
    try:
        parsed = _coerce_plan(plan)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    run_id = _new_run_id()
    original_params_by_step = {
        (step.step_id or f"s{idx}"): _clone_jsonable(step.params)
        for idx, step in enumerate(parsed.steps, start=1)
    }
    normalized, issues, run_workspace, run_tag = _normalize_plan_for_run(parsed, run_id)
    policy_issues = _extract_policy_issues_from_issue_list(issues)
    ok = not any(i.get("level") == "error" for i in issues)
    run_workspace_str = str(run_workspace) if run_workspace is not None else None
    normalized_params_by_step = {
        (step.step_id or f"s{idx}"): _clone_jsonable(step.params)
        for idx, step in enumerate(normalized.steps, start=1)
    }
    critic_feedback = []
    for step_id, original_params in original_params_by_step.items():
        step_issues = [
            issue for issue in issues if str(issue.get("step_id") or "") == step_id
        ]
        feedback = _critic_feedback_from_issues(
            step_issues,
            original_params=(
                original_params if isinstance(original_params, dict) else None
            ),
            current_params=normalized_params_by_step.get(step_id),
        )
        if feedback:
            critic_feedback.append({"step_id": step_id, **feedback})
    resp: dict[str, Any] = {
        "ok": ok,
        "run_id_hint": run_id,
        "run_workspace": run_workspace_str,
        "normalized_plan": {
            "project_root": normalized.project_root,
            "run_tag": run_tag,
            "run_workspace": run_workspace_str,
            "steps": [
                {
                    "step_id": s.step_id,
                    "tool": s.tool,
                    "params": s.params,
                    "work_dir": s.work_dir,
                    "output_dir": s.output_dir,
                }
                for s in normalized.steps
            ],
        },
        "issues": issues,
    }
    if policy_issues:
        resp["policy_issues"] = policy_issues
    if critic_feedback:
        resp["critic_feedback"] = critic_feedback
    try:
        from brain_researcher.services.review.bundle_builder import (
            build_plan_review_bundle,
        )
        from brain_researcher.services.review.rule_engine import get_engine
        from brain_researcher.services.review.verdict_builder import produce_verdict

        _review_bundle = build_plan_review_bundle(
            normalized, workflow_id=None, run_id=run_id
        )
        _verdict = produce_verdict(_review_bundle, engine=get_engine(), use_kg=False)
        resp["code_review"] = _verdict.model_dump()
    except Exception as _review_exc:
        resp["code_review"] = {"error": str(_review_exc)}
    return resp


@mcp.tool()
def pipeline_plan_review(
    plan: dict[str, Any],
    workflow_id: str | None = None,
    use_kg: bool = True,
) -> dict[str, Any]:
    """Domain-grounded review of a pipeline plan before execution.

    Checks tool ordering (registration before atlas analysis, skull-stripping before
    registration, confound regression before GLM), parameter ranges (TR, FWHM),
    modality/space compatibility, and plan completeness.

    Returns a CodeReviewVerdict with decision, risk_level, findings, and a checklist
    generated independently before rule evaluation.
    """
    qsm_verdict = review_qsm_plan_payload(plan, workflow_id=workflow_id)
    try:
        parsed = _coerce_plan(plan)
    except Exception as exc:
        if qsm_verdict is not None:
            payload = qsm_verdict.model_dump()
            payload["domain_invariant_review"] = {
                "task_type": "qsm_reconstruction",
                "advice_mode": "audit_only",
                "hard_constraints": _QSM_HARD_CONSTRAINTS,
                "non_displacement_notice": _QSM_NON_DISPLACEMENT_NOTICE,
                "qc_protocol": _QSM_QC_PROTOCOL,
                "forbidden_guidance": _QSM_FORBIDDEN_GUIDANCE,
                "schema_parse_error": str(exc),
            }
            return {"ok": True, **payload}
        return {"ok": False, "error": str(exc)}
    try:
        from brain_researcher.services.review.bundle_builder import (
            build_plan_review_bundle,
        )
        from brain_researcher.services.review.rule_engine import get_engine
        from brain_researcher.services.review.verdict_builder import produce_verdict

        bundle = build_plan_review_bundle(parsed, workflow_id=workflow_id, run_id=None)
        verdict = produce_verdict(bundle, engine=get_engine(), use_kg=use_kg)
        verdict = _merge_qsm_review_verdicts(verdict, qsm_verdict)
        response = {"ok": True, **verdict.model_dump()}
        if qsm_verdict is not None:
            response["domain_invariant_review"] = {
                "task_type": "qsm_reconstruction",
                "advice_mode": "audit_only",
                "decision": qsm_verdict.decision,
                "risk_level": qsm_verdict.risk_level,
                "hard_constraints": _QSM_HARD_CONSTRAINTS,
                "non_displacement_notice": _QSM_NON_DISPLACEMENT_NOTICE,
                "qc_protocol": _QSM_QC_PROTOCOL,
                "forbidden_guidance": _QSM_FORBIDDEN_GUIDANCE,
            }
        return response
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
