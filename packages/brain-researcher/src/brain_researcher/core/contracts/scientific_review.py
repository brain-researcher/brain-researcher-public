"""Contracts for three-verdict scientific review (Phase 3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchLineDirective,
)
from brain_researcher.core.contracts.code_review import ReviewFinding


class CorrectnessVerdict(BaseModel):
    """Deterministic structural correctness verdict."""

    decision: Literal["pass", "flag", "block"]
    findings: list[ReviewFinding] = Field(default_factory=list)


class JudgmentVerdict(BaseModel):
    """LLM-based scientific judgment verdict (Phase 3b)."""

    decision: Literal["sound", "questionable", "unsound"]
    estimand_complete: bool = True
    method_defensible: bool = True
    issues: list[str] = Field(default_factory=list)
    reviewer_questions: list[str] = Field(default_factory=list)
    judgment_status: Literal["ok", "parse_failed", "provider_failed"] = "ok"
    judge_transport_error: str | None = None
    raw_response_text: str | None = None


class CompletenessVerdict(BaseModel):
    """Checklist-based completeness verdict."""

    decision: Literal["complete", "incomplete"]
    checklist: dict[str, bool] = Field(default_factory=dict)
    missing_caveats: list[str] = Field(default_factory=list)


class ScientificReviewVerdict(BaseModel):
    """Composite of all three verdict cards."""

    correctness: CorrectnessVerdict
    judgment: JudgmentVerdict
    completeness: CompletenessVerdict
    review_scope: Literal["pipeline_run", "autoresearch_loop"] = "pipeline_run"
    overall_decision: Literal[
        "proceed", "diagnose", "explore_more", "stop_with_rationale"
    ]
    claim_strength: (
        Literal[
            "contract_satisfied",
            "internally_supported",
            "scientifically_convincing",
        ]
        | None
    ) = None
    report_action: Literal["write_report", "revise_report", "continue_loop"] | None = (
        None
    )
    required_next_actions: list[str] = Field(default_factory=list)
    validation_status: dict[str, str] = Field(default_factory=dict)
    line_directive: AutoresearchLineDirective | None = None
    rationale: str = ""


def judgment_verdict_llm_schema() -> dict[str, Any]:
    """Return the model-facing schema for judgment critics.

    Internal transport/debugging fields on ``JudgmentVerdict`` are intentionally
    excluded so the critic only emits scientific content, while the caller fills
    diagnostics such as raw transport payloads or parse failure status.
    """

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "decision",
            "estimand_complete",
            "method_defensible",
            "issues",
            "reviewer_questions",
        ],
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["sound", "questionable", "unsound"],
            },
            "estimand_complete": {"type": "boolean"},
            "method_defensible": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "reviewer_questions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def roll_up_scientific_decision(
    correctness: CorrectnessVerdict,
    judgment: JudgmentVerdict,
    completeness: CompletenessVerdict,
) -> tuple[str, str]:
    """Return (overall_decision, rationale) from the three verdict cards.

    Priority:
      correctness block  → stop/diagnose regardless
      judgment unsound   → diagnose
      judgment questionable → explore_more
      completeness missing → explore_more
      otherwise          → proceed
    """
    rationale_parts: list[str] = []

    if correctness.decision == "block":
        rationale_parts.append(
            "Structural correctness block: "
            + ", ".join(f.rule_id for f in correctness.findings[:3])
        )
        return "stop_with_rationale", " | ".join(rationale_parts)

    if judgment.decision == "unsound":
        rationale_parts.append("Scientific judgment: method unsound")
        if not judgment.estimand_complete:
            rationale_parts.append("estimand incomplete")
        if not judgment.method_defensible:
            rationale_parts.append("method not defensible")
        return "diagnose", " | ".join(rationale_parts)

    if judgment.decision == "questionable":
        rationale_parts.append("Scientific judgment: additional review needed")
        if judgment.issues:
            rationale_parts.append(", ".join(judgment.issues[:2]))
        return "explore_more", " | ".join(rationale_parts)

    if completeness.decision == "incomplete":
        missing = [k for k, v in completeness.checklist.items() if not v]
        rationale_parts.append(f"Completeness gaps: {', '.join(missing[:5])}")
        return "explore_more", " | ".join(rationale_parts)

    if correctness.decision == "flag":
        rationale_parts.append(
            "Structural flags: "
            + ", ".join(f.rule_id for f in correctness.findings[:3])
        )
        return "diagnose", " | ".join(rationale_parts)

    return "proceed", "All three verdict cards pass."


def derive_verdict_metadata(
    correctness: CorrectnessVerdict,
    judgment: JudgmentVerdict,
    completeness: CompletenessVerdict,
    overall_decision: str,
    *,
    scope: Literal["pipeline_run", "autoresearch_loop"] = "pipeline_run",
    validation_evidence_present: bool = False,
    replication_evidence_present: bool = False,
) -> tuple[
    Literal["contract_satisfied", "internally_supported", "scientifically_convincing"]
    | None,
    Literal["write_report", "revise_report", "continue_loop"] | None,
    list[str],
    dict[str, str],
]:
    """Derive ``(claim_strength, report_action, required_next_actions, validation_status)``.

    This is the single source of truth that both the native pipeline distill path
    and the autoresearch distill path should consult when populating the non-
    structural fields of :class:`ScientificReviewVerdict`. It is pure, deterministic,
    and derives everything from the three verdict cards plus the already-rolled-up
    ``overall_decision`` and two optional validation-evidence flags that only the
    autoresearch path currently knows how to set.
    """

    # --- report_action ------------------------------------------------------
    report_action: (
        Literal["write_report", "revise_report", "continue_loop"] | None
    ) = None
    if overall_decision == "stop_with_rationale" or judgment.decision == "unsound":
        report_action = "revise_report"
    elif overall_decision in ("diagnose", "explore_more"):
        report_action = "continue_loop"
    elif overall_decision == "proceed":
        report_action = "write_report"

    # --- claim_strength -----------------------------------------------------
    claim_strength: (
        Literal[
            "contract_satisfied",
            "internally_supported",
            "scientifically_convincing",
        ]
        | None
    ) = None
    all_clean = (
        overall_decision == "proceed"
        and correctness.decision != "block"
        and judgment.decision != "unsound"
    )
    if all_clean:
        claim_strength = "contract_satisfied"
        if validation_evidence_present:
            claim_strength = "internally_supported"
            if replication_evidence_present:
                claim_strength = "scientifically_convincing"

    # --- required_next_actions ---------------------------------------------
    actions: list[str] = []

    # 1. Blocking correctness findings (cap at 5).
    blocking = [
        f
        for f in correctness.findings
        if getattr(f, "action", None) == "block" or getattr(f, "severity", None) == "critical"
    ]
    for finding in blocking[:5]:
        fix = finding.suggested_fix or finding.message
        actions.append(f"Resolve blocking rule {finding.rule_id}: {fix}")

    # 2. Missing completeness checklist keys (cap at 5).
    missing_keys = [k for k, v in completeness.checklist.items() if not v]
    for key in missing_keys[:5]:
        actions.append(f"Declare review_context field: {key}")

    # 3. Unsound judgment prepends an overarching action.
    if judgment.decision == "unsound":
        actions.insert(
            0,
            "Judgment critic flagged method as unsound — revise analysis before continuing.",
        )

    # 4. Questionable judgment appends the first two reviewer questions.
    if judgment.decision == "questionable":
        for question in list(judgment.reviewer_questions)[:2]:
            actions.append(f"Answer reviewer question: {question}")

    # --- validation_status --------------------------------------------------
    validation_status: dict[str, str] = {}

    # Structural correctness.
    if correctness.decision == "block":
        validation_status["structural_correctness"] = "failed"
    elif correctness.decision == "flag":
        validation_status["structural_correctness"] = "missing"
    else:
        validation_status["structural_correctness"] = "ok"

    # Scientific judgment.
    if judgment.judgment_status != "ok":
        validation_status["scientific_judgment"] = "missing"
    elif judgment.decision == "unsound":
        validation_status["scientific_judgment"] = "failed"
    elif judgment.decision == "questionable":
        validation_status["scientific_judgment"] = "missing"
    else:
        validation_status["scientific_judgment"] = "ok"

    # Declared completeness.
    if completeness.decision == "incomplete":
        validation_status["declared_completeness"] = "missing"
    else:
        validation_status["declared_completeness"] = "ok"

    # Validation / replication evidence (only the autoresearch path flips
    # these; the native path leaves them as "missing").
    validation_status["validation_evidence"] = (
        "ok" if validation_evidence_present else "missing"
    )
    validation_status["replication_evidence"] = (
        "ok" if replication_evidence_present else "missing"
    )

    # Aggregate reason-tag signals from correctness findings.
    for finding in correctness.findings:
        for tag in getattr(finding, "reason_tags", []) or []:
            key = f"issue:{tag}"
            is_block = getattr(finding, "action", None) == "block"
            new_status = "failed" if is_block else "missing"
            current = validation_status.get(key)
            if current == "failed":
                continue
            validation_status[key] = new_status

    return claim_strength, report_action, actions, validation_status


__all__ = [
    "CorrectnessVerdict",
    "JudgmentVerdict",
    "CompletenessVerdict",
    "ScientificReviewVerdict",
    "derive_verdict_metadata",
    "judgment_verdict_llm_schema",
    "roll_up_scientific_decision",
]
