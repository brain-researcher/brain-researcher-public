"""Clarification-flow helpers extracted from ui_api.py.

These pure helper functions manage the lifecycle of pending clarification
decisions: classifying decisions, normalising user replies, matching
resolution choices, queueing info-gap questions, and assembling the
effective user content after answers are recorded.

No Flask request context is accessed here.  All side-effects are mediated
through ``resolution_memory`` lazy-imported inside each function.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Module-level constants (used only by this cluster)
# ---------------------------------------------------------------------------

_DATASET_OR_SUBJECT_REF_RE = re.compile(
    r"(?:\bds\d{6}\b|\bopenneuro\b|\bsub-[a-z0-9]+\b|\bses-[a-z0-9]+\b|(?:^|[\s\"'(])(?:/|~\/|\./|\.\./)[^\s]+|[A-Za-z]:\\[^\s]+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _is_generic_clarification_decision(decision: dict[str, Any]) -> bool:
    return str(decision.get("kind") or "").strip() == "generic_clarification"


def _clarification_key(question: str, source: str) -> str:
    return f"{source}:{question.strip()}"


def _pending_question_text(decision: dict[str, Any]) -> str:
    return str(
        decision.get("question") or "I need a quick clarification before proceeding."
    )


def _normalize_resolution_reply(user_msg: str) -> str:
    return " ".join((user_msg or "").strip().lower().replace("_", " ").split())


def _match_resolution_choice(
    user_msg: str,
    decision: dict[str, Any],
) -> str | None:
    normalized = _normalize_resolution_reply(user_msg)
    if not normalized:
        return None

    options = [
        str(option).strip() for option in (decision.get("options") or []) if option
    ]
    normalized_options = {
        _normalize_resolution_reply(option): option for option in options
    }
    if normalized in normalized_options:
        return normalized_options[normalized]

    if normalized in {"default", "recommended", "use recommended"}:
        recommended = decision.get("recommended_choice")
        return str(recommended) if recommended else None

    if any(phrase in normalized for phrase in ("local nilearn", "use nilearn")):
        return "local_nilearn"
    if any(
        phrase in normalized
        for phrase in ("search more", "keep searching", "search again")
    ):
        return "search_more"

    return None


# ---------------------------------------------------------------------------
# Queuing / resolution-memory helpers
# ---------------------------------------------------------------------------


def _queue_generic_clarifications(
    ctx: dict[str, Any],
    questions: list[str],
    *,
    source: str,
) -> None:
    from brain_researcher.services.agent.resolution_memory import (
        add_pending_decision,
        get_generic_clarification_state,
        get_pending_decisions,
    )

    state = get_generic_clarification_state(ctx)
    answered_keys = {
        str(item).strip()
        for item in (state.get("answered_keys") or [])
        if str(item).strip()
    }
    pending_keys = {
        str(item.get("clarification_key") or "").strip()
        for item in get_pending_decisions(ctx)
        if isinstance(item, dict) and _is_generic_clarification_decision(item)
    }

    for raw_question in questions:
        question = str(raw_question or "").strip()
        if not question:
            continue
        clarification_key = _clarification_key(question, source)
        if clarification_key in answered_keys or clarification_key in pending_keys:
            continue
        add_pending_decision(
            ctx,
            {
                "kind": "generic_clarification",
                "source": source,
                "clarification_key": clarification_key,
                "question": question,
            },
        )
        pending_keys.add(clarification_key)


def _query_has_dataset_or_subject_reference(
    query: str,
    *,
    ctx: dict[str, Any],
) -> bool:
    from brain_researcher.services.agent.preflight import ensure_query_understanding

    text = str(query or "").strip()
    if not text:
        return False
    if _DATASET_OR_SUBJECT_REF_RE.search(text):
        return True

    qur = ensure_query_understanding(text, ctx)
    if qur is None:
        return False
    if getattr(qur, "resolved_datasets", None) or getattr(
        qur, "candidate_datasets", None
    ):
        return True
    for entity in getattr(qur, "entities", []) or []:
        if not isinstance(entity, dict):
            continue
        entity_type = str(entity.get("entity_type") or "").strip().lower()
        entity_text = str(entity.get("text") or "").strip()
        if entity_type in {"dataset", "subject_group"} and entity_text:
            return True
        if entity_text and _DATASET_OR_SUBJECT_REF_RE.search(entity_text):
            return True
    return False


def _legacy_info_gap_questions(
    query: str,
    *,
    ctx: dict[str, Any],
) -> list[str]:
    text = _normalize_resolution_reply(query)
    if not text:
        return []

    requests_execution = any(
        token in text
        for token in (
            "analy",
            "run ",
            "compute",
            "extract",
            "preprocess",
            "process",
            "fit ",
            "build",
            "generate",
            "visual",
            "decode",
            "reconstruct",
            "clean",
            "denoise",
            "glm",
            "workflow",
            "pipeline",
        )
    )
    references_specific_data = any(
        phrase in text
        for phrase in (
            "my dataset",
            "my data",
            "this dataset",
            "this data",
            "our dataset",
            "our data",
            "brain imaging dataset",
            "fmri dataset",
            "subject data",
        )
    )
    mentions_data_context = any(
        token in text
        for token in (
            "dataset",
            "data",
            "subject",
            "participant",
            "cohort",
            "scan",
            "bids",
            "timeseries",
            "time series",
            "contrast",
        )
    )

    if (
        references_specific_data or (requests_execution and mentions_data_context)
    ) and not _query_has_dataset_or_subject_reference(query, ctx=ctx):
        return ["What dataset or subject should I operate on?"]
    return []


# ---------------------------------------------------------------------------
# History / content assembly helpers
# ---------------------------------------------------------------------------


def _clarification_anchor_from_history(
    history: list[dict[str, str]],
    *,
    answered_count: int,
) -> tuple[str | None, int | None]:
    if not history:
        return None, None

    anchor_index = len(history) - (2 * max(0, answered_count) + 2)
    if 0 <= anchor_index < len(history):
        item = history[anchor_index]
        if item.get("role") == "user" and item.get("content"):
            return item["content"], anchor_index

    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if item.get("role") == "user" and item.get("content"):
            return item["content"], index
    return None, None


def _build_effective_clarified_user_content(
    *,
    anchor_content: str | None,
    fallback_content: str,
    ctx: dict[str, Any],
) -> str:
    from brain_researcher.services.agent.resolution_memory import (
        get_generic_clarification_state,
    )

    lines = [str(anchor_content or fallback_content or "").strip()]

    clarification_state = get_generic_clarification_state(ctx)
    clarification_answers = [
        item
        for item in (clarification_state.get("answers") or [])
        if isinstance(item, dict)
    ]
    if clarification_answers:
        lines.append("")
        lines.append("Clarifications:")
        for item in clarification_answers[-3:]:
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if question and answer:
                lines.append(f"- {question}: {answer}")
            elif answer:
                lines.append(f"- {answer}")

    decision = ctx.get("resolution_decision_applied")
    if isinstance(decision, dict):
        capability_intent = str(decision.get("capability_intent") or "").strip()
        choice = str(decision.get("choice") or "").strip()
        if capability_intent or choice:
            lines.append("")
            lines.append("Resolution choice:")
            if capability_intent and choice:
                lines.append(f"- {capability_intent}: {choice}")
            else:
                lines.append(f"- {capability_intent or choice}")

    return "\n".join(line for line in lines if line is not None).strip()


def _build_legacy_clarification_result(
    *,
    thread_id: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    question = _pending_question_text(decision)
    return {
        "thread_id": thread_id,
        "session_id": thread_id,
        "text": question,
        "message": {"role": "assistant", "content": question},
        "tool_calls": [],
        "artifacts": [],
        "metadata": {
            "type": "clarification",
            "questions": [question],
            "pending_decision": decision,
        },
    }


def _maybe_legacy_clarification_result(
    *,
    thread_id: str,
    user_msg: str,
    history: list[dict[str, str]],
    ctx: dict[str, Any],
    tool_mode: str,
) -> tuple[dict[str, Any] | None, str, list[dict[str, str]]]:
    from brain_researcher.services.agent.preflight import ensure_tool_candidates
    from brain_researcher.services.agent.resolution_memory import (
        clear_pending_decisions,
        get_generic_clarification_state,
        get_pending_decisions,
        pop_pending_decision,
        record_generic_clarification_answer,
        set_override,
    )

    effective_user_content = str(user_msg or "")
    effective_history = history

    pending_decisions = get_pending_decisions(ctx)
    if pending_decisions:
        clarification_state = get_generic_clarification_state(ctx)
        answered_count = len(clarification_state.get("answers") or [])
        anchor_content, anchor_index = _clarification_anchor_from_history(
            history,
            answered_count=answered_count,
        )
        first = pending_decisions[0]
        if _is_generic_clarification_decision(first):
            consumed = pop_pending_decision(ctx) or first
            record_generic_clarification_answer(ctx, consumed, user_msg)
            ctx["generic_clarification_applied"] = {
                "clarification_key": str(
                    consumed.get("clarification_key") or ""
                ).strip(),
                "question": str(consumed.get("question") or "").strip(),
                "answer": str(user_msg or "").strip(),
            }
        else:
            capability_intent = str(first.get("capability_intent") or "").strip()
            choice = _match_resolution_choice(user_msg, first)
            if choice:
                if choice == "search_more":
                    clear_pending_decisions(ctx, capability_intent)
                    ctx["_resolution_force_capability_lookup"] = capability_intent
                else:
                    set_override(ctx, capability_intent, choice)
                ctx["resolution_decision_applied"] = {
                    "capability_intent": capability_intent,
                    "choice": choice,
                }

        pending_decisions = get_pending_decisions(ctx)
        if pending_decisions:
            return (
                _build_legacy_clarification_result(
                    thread_id=thread_id,
                    decision=pending_decisions[0],
                ),
                effective_user_content,
                effective_history,
            )

        if ctx.get("generic_clarification_applied") or ctx.get(
            "resolution_decision_applied"
        ):
            effective_user_content = _build_effective_clarified_user_content(
                anchor_content=anchor_content,
                fallback_content=user_msg,
                ctx=ctx,
            )
            if anchor_index is not None:
                effective_history = history[:anchor_index]

    _queue_generic_clarifications(
        ctx,
        _legacy_info_gap_questions(effective_user_content, ctx=ctx),
        source="info_gap",
    )
    if tool_mode not in {"none", "off", "coding"}:
        ensure_tool_candidates(effective_user_content, ctx)

    pending_decisions = get_pending_decisions(ctx)
    if pending_decisions:
        return (
            _build_legacy_clarification_result(
                thread_id=thread_id,
                decision=pending_decisions[0],
            ),
            effective_user_content,
            effective_history,
        )

    return None, effective_user_content, effective_history
