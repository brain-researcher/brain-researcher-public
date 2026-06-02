"""Query-context augmentation helpers for the UI API.

Pure helper functions responsible for normalising conversation history and
injecting structured Studio context (plan/repair snapshots) into user queries
before they reach the LLM.  No Flask request/response objects; no route
decorators; no module-level mutable state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _truncate_text(value: Any, limit: int = 280) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_history_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _resolve_history_from_payload_or_thread(
    *,
    thread_id: str,
    payload_messages: list[dict[str, Any]],
    last_user_content: str,
) -> list[dict[str, str]]:
    from brain_researcher.services.agent.ui_api import _get_thread_store  # noqa: F401

    history, _ = _resolve_history_from_payload_or_thread_with_source(
        thread_id=thread_id,
        payload_messages=payload_messages,
        last_user_content=last_user_content,
    )
    return history


def _resolve_history_from_payload_or_thread_with_source(
    *,
    thread_id: str,
    payload_messages: list[dict[str, Any]],
    last_user_content: str,
) -> tuple[list[dict[str, str]], str]:
    from brain_researcher.services.agent.ui_api import _get_thread_store

    payload_history = _normalize_history_messages(payload_messages[:-1])
    if payload_history:
        return payload_history[-8:], "payload"

    try:
        store = _get_thread_store()
        thread_messages = store.get_messages(thread_id) or []
        history = _normalize_history_messages(
            [m if isinstance(m, dict) else m.to_dict() for m in thread_messages]
        )
        if (
            history
            and history[-1]["role"] == "user"
            and history[-1]["content"] == last_user_content
        ):
            history = history[:-1]
        if history:
            return history[-8:], "thread_store"
        return [], "empty"
    except Exception:
        logger.exception("Failed to resolve thread history for /api/chat*")
        return [], "empty"


def _extract_plan_context(ctx: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ctx, dict):
        return {}
    plan_context = ctx.get("plan_context")
    if isinstance(plan_context, dict):
        return plan_context
    return {}


def _extract_repair_context(ctx: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ctx, dict):
        return {}
    repair_context = ctx.get("repair_context")
    if isinstance(repair_context, dict):
        return repair_context
    return {}


def _format_plan_context_lines(
    plan_context: dict[str, Any],
    *,
    user_content: str,
) -> list[str]:
    lines: list[str] = []
    dataset_id = plan_context.get("dataset_id")
    dataset_version = plan_context.get("dataset_version")
    pipeline_id = plan_context.get("pipeline_id")
    parameters = plan_context.get("parameters") or plan_context.get("parameter_values")
    dataset_resource_summary = plan_context.get("dataset_resource_summary")

    if dataset_id:
        lines.append(f"- Dataset: {dataset_id}")
    if dataset_version:
        lines.append(f"- Dataset version: {dataset_version}")
    if pipeline_id:
        lines.append(f"- Pipeline: {pipeline_id}")

    if isinstance(parameters, dict) and parameters:
        top_params = []
        for key in sorted(parameters.keys())[:8]:
            top_params.append(f"{key}={_truncate_text(parameters.get(key), 80)}")
        if top_params:
            lines.append(f"- Parameters: {', '.join(top_params)}")

    if isinstance(dataset_resource_summary, dict):
        subjects = dataset_resource_summary.get("subjectsCount")
        matched_files = dataset_resource_summary.get("totalMatchedFiles")
        readiness = dataset_resource_summary.get("readinessStatus")
        bucket_check_state = dataset_resource_summary.get("bucketCheckState")
        version_check_mode = dataset_resource_summary.get("versionCheckMode")
        resolved_version = dataset_resource_summary.get("resolvedVersion")
        s3_uri = dataset_resource_summary.get("s3Uri")
        openneuro_url = dataset_resource_summary.get("openneuroUrl")
        source_repo_url = dataset_resource_summary.get("sourceRepoUrl")
        if subjects is not None:
            lines.append(f"- Subjects (summary): {subjects}")
        if matched_files is not None:
            lines.append(f"- Matched files (summary): {matched_files}")
        if readiness:
            lines.append(f"- Resource readiness: {readiness}")
        if bucket_check_state:
            lines.append(f"- Bucket check state: {bucket_check_state}")
        if version_check_mode:
            lines.append(f"- Version verification mode: {version_check_mode}")
        if resolved_version:
            lines.append(f"- Resolved source version: {resolved_version}")
        if s3_uri:
            lines.append(f"- S3 mount hint: {s3_uri}")
        if openneuro_url:
            lines.append(f"- OpenNeuro URL: {openneuro_url}")
        if source_repo_url:
            lines.append(f"- Source URL: {source_repo_url}")

    user_text = (user_content or "").lower()
    has_atlas_hint = "atlas" in user_text or "parcellation" in user_text
    if not has_atlas_hint and isinstance(parameters, dict):
        has_atlas_hint = "atlas" in {str(k).lower() for k in parameters.keys()}
    if has_atlas_hint:
        lines.append(
            "- Terminology: interpret 'atlas' as a neuroimaging brain atlas/parcellation unless the user explicitly asks about geographic atlases."
        )

    if dataset_id:
        lines.append(
            "- If the user asks about dataset files, mounts, versions, or subject counts, call tools `datasets.describe_resources` (summary) and `datasets.list_resources` (mount/readiness trace) using this dataset."
        )
        lines.append(
            "- For exploratory dataset asset questions, browse first with `list_dataset_assets`; only call `resolve_dataset_asset` after the asset kind or selectors are specific enough."
        )

    return lines


def _repair_examples_block() -> str:
    studio_fix = json.dumps(
        {
            "plan_patch": {
                "parameter_overrides": {
                    "subject_subset": ["sub-02"],
                    "smoothing_fwhm": 4,
                }
            },
            "recipe_patch_preview": "Limit validation to sub-02 and lower smoothing_fwhm before rerunning fitlins.",
            "validation_intent": "Re-validate on a smaller subject subset that has the required confounds file.",
            "handoff": {"required": False, "reason": None},
        },
        ensure_ascii=False,
        indent=2,
    )
    external_fix = json.dumps(
        {
            "plan_patch": None,
            "recipe_patch_preview": "Install the missing dependency or update the execution environment outside Studio before rerunning.",
            "validation_intent": "Do not re-validate in Studio until the environment issue is resolved.",
            "handoff": {
                "required": True,
                "reason": "Environment/dependency change required outside Studio.",
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        "Repair response protocol:\n"
        "1. Start with a short diagnosis and the smallest Studio-side fix.\n"
        "2. If the fix can be expressed as plan/config changes, append exactly one fenced json block.\n"
        "3. Use handoff.required=true only when the fix needs environment, dependency, or external code changes.\n\n"
        "Example Studio-side fix:\n"
        "Diagnosis: Missing confounds.tsv for the chosen subject subset. Restrict validation to a subject that has confounds and keep the same pipeline.\n"
        "```json\n"
        f"{studio_fix}\n"
        "```\n\n"
        "Example external handoff:\n"
        "Diagnosis: The package import is missing in the execution environment. Studio can diagnose it, but the environment must be updated outside Studio.\n"
        "```json\n"
        f"{external_fix}\n"
        "```"
    )


def _augment_query_with_context(
    user_content: str,
    *,
    history: list[dict[str, str]] | None = None,
    ctx: dict[str, Any] | None = None,
) -> str:
    blocks: list[str] = []
    plan_context = _extract_plan_context(ctx)
    repair_context = _extract_repair_context(ctx)

    if plan_context:
        plan_lines = _format_plan_context_lines(plan_context, user_content=user_content)
        if plan_lines:
            blocks.append("Studio plan context:\n" + "\n".join(plan_lines))

    if repair_context:
        repair_lines: list[str] = []
        run_id = repair_context.get("run_id")
        analysis_id = repair_context.get("analysis_id")
        tool_name = repair_context.get("tool_name")
        error_type = repair_context.get("error_type")
        error_message = repair_context.get("error_message")
        repair_attempt_count = repair_context.get("repair_attempt_count")
        failing_step = repair_context.get("failing_step")
        diagnosis = repair_context.get("diagnosis")
        primary_violation = repair_context.get("primary_violation")
        diagnostics_codes = repair_context.get("diagnostics_codes")
        sample_errors = repair_context.get("sample_errors")
        plan_snapshot = repair_context.get("plan_snapshot")
        input_artifacts = repair_context.get("input_artifacts")
        log_tail = repair_context.get("log_tail")

        if run_id:
            repair_lines.append(f"- Run/job ID: {run_id}")
        if analysis_id:
            repair_lines.append(f"- Analysis ID: {analysis_id}")
        if tool_name:
            repair_lines.append(f"- Tool: {tool_name}")
        if error_type:
            repair_lines.append(f"- Error type: {error_type}")
        if error_message:
            repair_lines.append(
                f"- Error message: {_truncate_text(error_message, 220)}"
            )
        if repair_attempt_count is not None:
            repair_lines.append(f"- Repair attempts so far: {repair_attempt_count}")

        if isinstance(failing_step, dict):
            step_id = failing_step.get("id")
            step_name = failing_step.get("name")
            step_tool = failing_step.get("tool")
            step_status = failing_step.get("status")
            step_error = failing_step.get("error")
            if step_name or step_id:
                repair_lines.append(f"- Failing step: {step_name or step_id}")
            if step_tool:
                repair_lines.append(f"- Failing step tool: {step_tool}")
            if step_status:
                repair_lines.append(f"- Failing step status: {step_status}")
            if step_error:
                repair_lines.append(
                    f"- Failing step error: {_truncate_text(step_error, 220)}"
                )

        if isinstance(primary_violation, dict):
            code = primary_violation.get("code")
            message = primary_violation.get("message")
            severity = primary_violation.get("severity")
            suggested_fix = primary_violation.get("suggested_fix")
            where = (
                primary_violation.get("where")
                if isinstance(primary_violation.get("where"), dict)
                else {}
            )
            where_label = ", ".join(
                [
                    _truncate_text(where.get("step_id"), 80)
                    for _ in [0]
                    if where.get("step_id")
                ]
                + [
                    _truncate_text(where.get("stage"), 80)
                    for _ in [0]
                    if where.get("stage")
                ]
                + [
                    _truncate_text(where.get("component"), 80)
                    for _ in [0]
                    if where.get("component")
                ]
            )
            if code or message:
                suffix = f" ({where_label})" if where_label else ""
                repair_lines.append(
                    f"- Primary violation: {_truncate_text(code or 'violation', 120)}: {_truncate_text(message or '', 220)}{suffix}".rstrip()
                )
            if severity:
                repair_lines.append(f"- Violation severity: {severity}")
            if suggested_fix:
                repair_lines.append(
                    f"- Violation suggested fix: {_truncate_text(suggested_fix, 220)}"
                )

        if isinstance(diagnostics_codes, list):
            for code in diagnostics_codes[:6]:
                if isinstance(code, str) and code.strip():
                    repair_lines.append(
                        f"- Top diagnostic code: {_truncate_text(code, 160)}"
                    )

        if isinstance(sample_errors, list):
            for sample in sample_errors[:4]:
                if isinstance(sample, str) and sample.strip():
                    repair_lines.append(
                        f"- Sample error: {_truncate_text(sample, 220)}"
                    )

        if isinstance(diagnosis, dict):
            title = diagnosis.get("title")
            message = diagnosis.get("message")
            what_happened = diagnosis.get("what_happened")
            suggested_actions = diagnosis.get("suggested_actions")
            if title:
                repair_lines.append(f"- Diagnosis title: {title}")
            if message:
                repair_lines.append(
                    f"- Diagnosis summary: {_truncate_text(message, 220)}"
                )
            if isinstance(what_happened, list):
                for item in what_happened[:6]:
                    if item:
                        repair_lines.append(
                            f"- What happened: {_truncate_text(item, 220)}"
                        )
            if isinstance(suggested_actions, list):
                for item in suggested_actions[:6]:
                    if item:
                        repair_lines.append(
                            f"- Suggested action: {_truncate_text(item, 220)}"
                        )

        if isinstance(plan_snapshot, dict):
            snapshot_lines = _format_plan_context_lines(
                plan_snapshot,
                user_content=user_content,
            )
            if snapshot_lines:
                repair_lines.append("- Current Studio plan snapshot:")
                repair_lines.extend(
                    [
                        f"  {line[2:]}" if line.startswith("- ") else f"  {line}"
                        for line in snapshot_lines
                    ]
                )

        if isinstance(input_artifacts, list):
            for artifact in input_artifacts[:5]:
                if not isinstance(artifact, dict):
                    continue
                artifact_name = artifact.get("name") or artifact.get("uri")
                artifact_type = artifact.get("type")
                if artifact_name:
                    if artifact_type:
                        repair_lines.append(
                            f"- Input artifact: {artifact_name} ({artifact_type})"
                        )
                    else:
                        repair_lines.append(f"- Input artifact: {artifact_name}")

        if isinstance(log_tail, list):
            lines = [
                _truncate_text(line, 220)
                for line in log_tail[-8:]
                if isinstance(line, str) and line.strip()
            ]
            if lines:
                repair_lines.append("Recent log tail:")
                repair_lines.extend([f"  {line}" for line in lines])

        repair_lines.extend(
            [
                "- Repair objective: prefer the smallest Studio-side fix that can be re-validated in place.",
                "- Only recommend external IDE handoff when the issue needs environment, dependency, or external code changes.",
                "- If you can express the fix as plan/config changes, append exactly one fenced json block with keys plan_patch, recipe_patch_preview, validation_intent, and handoff.",
            ]
        )
        blocks.append(
            "Studio repair context:\n"
            + "\n".join(repair_lines)
            + "\n\n"
            + _repair_examples_block()
        )

    if history:
        rendered: list[str] = []
        for item in history[-6:]:
            role = "User" if item.get("role") == "user" else "Assistant"
            rendered.append(f"{role}: {_truncate_text(item.get('content', ''), 220)}")
        if rendered:
            blocks.append("Recent conversation:\n" + "\n".join(rendered))

    if not blocks:
        return user_content

    return (
        f"{user_content}\n\n"
        "Use the following context to ground your answer and avoid generic responses.\n"
        + "\n\n".join(blocks)
    )
