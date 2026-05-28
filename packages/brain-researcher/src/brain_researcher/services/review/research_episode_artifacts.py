"""Helpers for building and persisting scientific-episode artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts import (
    CommitmentRecordV1,
    EpisodeOptionV1,
    OptionSetV1,
    ResearchEpisodeV1,
)
from brain_researcher.services.shared.planner.handoff import (
    build_handoff_from_plan_payload,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                output.append(stripped)
    return output


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _json_write(path: Path, payload: Any) -> None:
    if hasattr(payload, "model_dump_json"):
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        return

    def _default(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(exclude_none=True)
        raise TypeError(
            f"Object of type {value.__class__.__name__} is not JSON serializable"
        )

    path.write_text(json.dumps(payload, indent=2, default=_default), encoding="utf-8")


def _candidate_confidence(candidate: Mapping[str, Any]) -> float | None:
    score = _as_float(candidate.get("score"))
    if score is None:
        return None
    if 0.0 <= score <= 1.0:
        return score
    if 1.0 < score <= 100.0:
        return score / 100.0
    return None


def _candidate_rationale(candidate: Mapping[str, Any]) -> str | None:
    for key in ("reason", "rationale", "description", "selection_reason"):
        if text := _text(candidate.get(key)):
            return text
    return None


def _candidate_label(candidate: Mapping[str, Any], *, fallback_id: str) -> str:
    for key in ("tool_name", "label", "name", "tool_id"):
        if text := _text(candidate.get(key)):
            return text
    return fallback_id


def _candidate_id(candidate: Mapping[str, Any], *, index: int) -> str:
    for key in ("tool_id", "option_id", "name", "label"):
        if text := _text(candidate.get(key)):
            return text
    return f"option-{index + 1}"


def build_option_set_from_plan_payload(
    plan_payload: Mapping[str, Any] | None,
) -> OptionSetV1 | None:
    payload = _dict(plan_payload)
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    options: list[EpisodeOptionV1] = []
    for idx, row in enumerate(raw_candidates):
        if not isinstance(row, dict):
            continue
        option_id = _candidate_id(row, index=idx)
        risks = _string_list(row.get("risks"))
        if row.get("preflight_ok") is False and "preflight not ok" not in risks:
            risks.append("preflight not ok")
        prerequisites = _string_list(row.get("prerequisites"))
        if (
            row.get("requires_confirmation")
            and "human confirmation" not in prerequisites
        ):
            prerequisites.append("human confirmation")
        options.append(
            EpisodeOptionV1(
                option_id=option_id,
                label=_candidate_label(row, fallback_id=option_id),
                rationale=_candidate_rationale(row),
                expected_impact=_text(row.get("expected_impact")),
                risks=risks,
                prerequisites=prerequisites,
                confidence=_candidate_confidence(row),
                extra={"raw_candidate": dict(row)},
            )
        )

    chosen_tool = _text(payload.get("chosen_tool"))
    selected_option_id = None
    if chosen_tool:
        option_ids = {option.option_id for option in options}
        if chosen_tool in option_ids:
            selected_option_id = chosen_tool

    selection_rationale = _text(payload.get("selection_reason"))
    if selection_rationale is None:
        for row in payload.get("selection_reasons") or []:
            if isinstance(row, str) and row.strip():
                selection_rationale = row.strip()
                break
            if isinstance(row, dict):
                selection_rationale = _text(row.get("reason")) or _text(
                    row.get("message")
                )
                if selection_rationale:
                    break

    if not options and selected_option_id is None and selection_rationale is None:
        return None

    extra: dict[str, Any] = {}
    if isinstance(payload.get("selection_reasons"), list):
        extra["selection_reasons"] = payload.get("selection_reasons")
    if isinstance(payload.get("mask_reasons"), list):
        extra["mask_reasons"] = payload.get("mask_reasons")
    if isinstance(payload.get("planner_events"), list):
        extra["planner_events"] = payload.get("planner_events")

    return OptionSetV1(
        options=options,
        selected_option_id=selected_option_id,
        selection_rationale=selection_rationale,
        extra=extra,
    )


def build_research_episode_from_context(
    *,
    run_id: str | None,
    session_id: str | None,
    state: str | None,
    plan_payload: Mapping[str, Any] | None,
    run_card: Mapping[str, Any] | None = None,
    session_snapshot: Mapping[str, Any] | None = None,
    option_set: OptionSetV1 | None = None,
    commitments: list[CommitmentRecordV1] | None = None,
) -> ResearchEpisodeV1 | None:
    payload = _dict(plan_payload)
    run_card_dict = _dict(run_card)
    snapshot = _dict(session_snapshot)
    plan_context = _dict(payload.get("context"))
    run_summary = _dict(payload.get("run_summary"))

    question = (
        _text(snapshot.get("goal"))
        or _text(payload.get("query"))
        or _text(run_card_dict.get("description"))
        or _text(run_card_dict.get("title"))
    )
    objective = question or _text(run_summary.get("summary"))
    estimand = (
        _text(plan_context.get("estimand"))
        or _text(plan_context.get("analysis_goal"))
        or _text(_dict(run_card_dict.get("inputs")).get("analysis_goal"))
    )
    success_criteria = _string_list(payload.get("success_criteria"))
    stop_conditions = _string_list(payload.get("stop_conditions"))

    if not any((question, objective, estimand, success_criteria, option_set)):
        return None

    status_map = {
        "succeeded": "completed",
        "success": "completed",
        "completed": "completed",
        "failed": "archived",
        "error": "archived",
        "running": "active",
        "in_progress": "active",
        "queued": "draft",
        "pending": "draft",
    }
    normalized_state = (state or "").strip().lower()
    episode_status = status_map.get(normalized_state, "active" if state else "draft")
    created_at = _text(snapshot.get("created_at")) or _utc_now()
    updated_at = _utc_now()

    episode_id = (
        _text(payload.get("plan_id"))
        or _text(run_id)
        or _text(session_id)
        or "episode-unknown"
    )
    if not episode_id.startswith("episode:"):
        episode_id = f"episode:{episode_id}"

    context: dict[str, Any] = {}
    for key in (
        "chosen_tool",
        "selection_reason",
        "confidence_score",
        "plan_conf",
        "approval_level",
        "run_mode_hint",
    ):
        value = payload.get(key)
        if value is not None:
            context[key] = value
    if isinstance(payload.get("constraints"), dict):
        context["constraints"] = payload.get("constraints")
    if isinstance(payload.get("cross_stage_context"), dict):
        context["cross_stage_context"] = payload.get("cross_stage_context")
    elif isinstance(run_card_dict.get("cross_stage_context"), dict):
        context["cross_stage_context"] = run_card_dict.get("cross_stage_context")
    if isinstance(payload.get("loop_signals"), list):
        context["loop_signals"] = payload.get("loop_signals")
    elif isinstance(run_card_dict.get("loop_signals"), list):
        context["loop_signals"] = run_card_dict.get("loop_signals")
    if isinstance(snapshot.get("done"), list):
        context["snapshot_done"] = snapshot.get("done")
    if isinstance(snapshot.get("open"), list):
        context["snapshot_open"] = snapshot.get("open")
    if snapshot.get("next_command") is not None:
        context["next_command"] = snapshot.get("next_command")

    return ResearchEpisodeV1(
        episode_id=episode_id,
        run_id=_text(run_id),
        session_id=_text(session_id),
        title=_text(run_card_dict.get("title")) or question,
        research_question=question,
        objective=objective,
        estimand=estimand,
        success_criteria=success_criteria,
        stop_conditions=stop_conditions,
        status=episode_status,
        created_at=created_at,
        updated_at=updated_at,
        option_set=option_set,
        commitments=commitments or [],
        context=context,
    )


def build_commitments_from_plan_payload(
    plan_payload: Mapping[str, Any] | None,
    *,
    run_id: str | None = None,
    state: str | None = None,
    option_set: OptionSetV1 | None = None,
) -> list[CommitmentRecordV1]:
    payload = _dict(plan_payload)
    if not payload:
        return []

    try:
        handoff = _dict(build_handoff_from_plan_payload(payload))
    except Exception:
        handoff = {}

    chosen_tool = (
        (
            option_set.selected_option_id
            if option_set is not None and option_set.selected_option_id
            else None
        )
        or _text(handoff.get("chosen_tool"))
        or _text(payload.get("chosen_tool"))
    )

    selection_reason = _text(payload.get("selection_reason"))
    if selection_reason is None:
        for row in payload.get("selection_reasons") or []:
            if isinstance(row, str) and row.strip():
                selection_reason = row.strip()
                break
            if isinstance(row, dict):
                selection_reason = _text(row.get("reason")) or _text(row.get("message"))
                if selection_reason:
                    break

    approval_level = _text(handoff.get("approval_level")) or _text(
        payload.get("approval_level")
    )
    allowed_tools = _string_list(handoff.get("allowed_tools")) or _string_list(
        payload.get("allowed_tools")
    )
    run_mode_hint = _text(handoff.get("run_mode_hint")) or _text(
        payload.get("run_mode_hint")
    )
    if not allowed_tools and chosen_tool:
        allowed_tools = [chosen_tool]
    if approval_level is None and chosen_tool:
        approval_level = "confirm"
    if run_mode_hint is None and approval_level == "confirm":
        run_mode_hint = "confirm_before_execute"

    budget_envelope: dict[str, Any] = {}
    for source in (
        payload.get("budget_envelope"),
        _dict(payload.get("constraints")).get("budget_envelope"),
        _dict(payload.get("context")).get("budget_envelope"),
    ):
        if isinstance(source, dict):
            budget_envelope.update(source)

    stop_conditions = _string_list(payload.get("stop_conditions"))
    if not any(
        (chosen_tool, selection_reason, approval_level, allowed_tools, run_mode_hint)
    ):
        return []

    commitment_id = (
        _text(payload.get("plan_id")) or _text(run_id) or chosen_tool or "commitment-1"
    )
    if not commitment_id.startswith("commitment:"):
        commitment_id = f"commitment:{commitment_id}"

    if selection_reason and chosen_tool:
        commitment_text = f"Execute {chosen_tool}: {selection_reason}"
    elif chosen_tool:
        commitment_text = f"Execute {chosen_tool}"
    elif selection_reason:
        commitment_text = selection_reason
    else:
        commitment_text = "Proceed with the selected episode path."

    normalized_state = (state or "").strip().lower()
    fulfilled = normalized_state in {"succeeded", "success", "completed"}
    committed_at = _utc_now()

    return [
        CommitmentRecordV1(
            commitment_id=commitment_id,
            option_id=chosen_tool,
            commitment_text=commitment_text,
            approval_level=approval_level,
            approved_by=_text(_dict(payload.get("context")).get("approved_by")),
            allowed_tools=allowed_tools,
            run_mode_hint=run_mode_hint,
            budget_envelope=budget_envelope,
            stop_conditions=stop_conditions,
            committed_at=committed_at,
            fulfilled=fulfilled,
            fulfilled_at=committed_at if fulfilled else None,
            owner=(
                _text(_dict(payload.get("context")).get("owner"))
                or _text(payload.get("owner"))
                or _text(_dict(payload.get("metadata")).get("owner"))
            ),
            extra={
                "selection_reason": selection_reason,
                "plan_id": _text(payload.get("plan_id")),
                "run_id": _text(run_id),
            },
        )
    ]


def sync_research_episode_artifact(
    run_dir: Path,
    *,
    evidence_gate: Any | None = None,
    commitments: list[CommitmentRecordV1] | None = None,
    claim_report: Any | None = None,
    claim_updates: list[Any] | None = None,
) -> bool:
    episode_path = run_dir / "research_episode.json"
    raw = _read_json(episode_path)
    if not raw:
        return False

    try:
        episode = ResearchEpisodeV1.model_validate(raw)
    except Exception:
        return False

    changed = False
    if evidence_gate is not None:
        episode.evidence_gate = evidence_gate
        changed = True
    if commitments is not None:
        episode.commitments = commitments
        changed = True
    if claim_report is not None:
        episode.claim_report = claim_report
        changed = True
    if claim_updates is not None:
        episode.claim_updates = list(claim_updates)
        changed = True
    if not changed:
        return False

    episode.updated_at = _utc_now()
    _json_write(episode_path, episode)
    return True


def persist_research_episode_artifacts(
    run_dir: Path,
    *,
    run_id: str | None,
    session_id: str | None,
    state: str | None,
    plan_payload: Mapping[str, Any] | None,
    run_card: Mapping[str, Any] | None = None,
    session_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot = (
        _dict(session_snapshot)
        if session_snapshot is not None
        else _read_json(run_dir / "session_snapshot.json") or {}
    )
    option_set = build_option_set_from_plan_payload(plan_payload)
    commitments = build_commitments_from_plan_payload(
        plan_payload,
        run_id=run_id,
        state=state,
        option_set=option_set,
    )
    episode = build_research_episode_from_context(
        run_id=run_id,
        session_id=session_id,
        state=state,
        plan_payload=plan_payload,
        run_card=run_card,
        session_snapshot=snapshot,
        option_set=option_set,
        commitments=commitments,
    )

    written: dict[str, str] = {}
    if option_set is not None:
        option_path = run_dir / "option_set.json"
        _json_write(option_path, option_set)
        written["option_set_json"] = option_path.name
    if commitments:
        commitment_path = run_dir / "commitment.json"
        _json_write(commitment_path, commitments)
        written["commitment_json"] = commitment_path.name
    if episode is not None:
        episode_path = run_dir / "research_episode.json"
        _json_write(episode_path, episode)
        written["research_episode_json"] = episode_path.name
    return written


__all__ = [
    "build_commitments_from_plan_payload",
    "build_option_set_from_plan_payload",
    "build_research_episode_from_context",
    "persist_research_episode_artifacts",
    "sync_research_episode_artifact",
]
