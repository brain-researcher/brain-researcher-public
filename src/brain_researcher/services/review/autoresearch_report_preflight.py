"""Deterministic report preflight for line-based autoresearch workspaces."""

from __future__ import annotations

from pathlib import Path

from brain_researcher.core.contracts.autoresearch_line import (
    LineReportPreflightIssueV1,
    LineReportPreflightV1,
)
from brain_researcher.services.review.autoresearch_bundle_builder import (
    _extract_claim_strength,
    _extract_self_critique_sections,
    _extract_validation_missing,
)
from brain_researcher.services.review.autoresearch_line_workspace import (
    resolve_autoresearch_workspace_layout,
)

_REQUIRED_SELF_CRITIQUE_SECTIONS = {
    "so_what": "so what",
    "method_sensitivity": "method sensitivity",
    "structured_exploratory_pass": "structured exploratory pass",
    "claim_strength_block": "claim strength",
}
_ACCEPTED_CLAIM_STRENGTHS = {
    "contract_satisfied",
    "internally_supported",
    "scientifically_convincing",
}


def _read_report(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return True, None


def run_autoresearch_report_preflight(
    autoresearch_dir: str | Path,
) -> LineReportPreflightV1:
    """Validate that a line report is structurally ready for scientific review."""

    layout = resolve_autoresearch_workspace_layout(autoresearch_dir)
    report_path = Path(layout.final_report_path)
    report_present, report_text = _read_report(report_path)

    if not report_present:
        return LineReportPreflightV1(
            report_path=str(report_path),
            report_present=False,
            parse_status="missing",
            issues=[
                LineReportPreflightIssueV1(
                    code="REPORT_MISSING",
                    message="final_report.md is missing.",
                    fix_hint="Write a synthesis or final report before scientific review.",
                )
            ],
            ready_for_review=False,
        )

    if report_text is None:
        return LineReportPreflightV1(
            report_path=str(report_path),
            report_present=True,
            parse_status="unreadable",
            issues=[
                LineReportPreflightIssueV1(
                    code="REPORT_UNREADABLE",
                    message="final_report.md exists but could not be read.",
                    fix_hint="Regenerate the report artifact or ensure it is valid UTF-8 text.",
                )
            ],
            ready_for_review=False,
        )

    report_text_lower = report_text.lower()
    seen_sections = set(_extract_self_critique_sections(report_text))
    required_blocks = {
        "pre_report_self_critique_checkpoint": (
            "pre-report self-critique checkpoint" in report_text_lower
        ),
        **{
            key: section_name in seen_sections
            for key, section_name in _REQUIRED_SELF_CRITIQUE_SECTIONS.items()
        },
    }
    claim_strength = _extract_claim_strength(report_text)
    validation_missing = _extract_validation_missing(report_text)
    final_stopping_condition_present = (
        "final_stopping_condition" in report_text
        or "stopping condition" in report_text_lower
    )
    semantic_checks = {
        "primary_analysis_declared": "primary analysis" in report_text_lower,
        "sensitivity_analysis_declared": "sensitivity analysis" in report_text_lower,
    }
    required_fields = {
        "claim_strength": claim_strength,
        "validation_missing": validation_missing,
        "final_stopping_condition": final_stopping_condition_present,
    }

    issues: list[LineReportPreflightIssueV1] = []
    for block_name, ok in required_blocks.items():
        if ok:
            continue
        issues.append(
            LineReportPreflightIssueV1(
                code=f"MISSING_BLOCK_{block_name.upper()}",
                message=f"Missing required report block: {block_name}.",
                fix_hint="Add the required self-critique/report section before review.",
            )
        )

    if claim_strength is None:
        issues.append(
            LineReportPreflightIssueV1(
                code="MISSING_CLAIM_STRENGTH",
                message="Report does not declare claim_strength.",
                fix_hint="Add a `claim_strength: ...` declaration in the report.",
            )
        )
    elif claim_strength not in _ACCEPTED_CLAIM_STRENGTHS:
        issues.append(
            LineReportPreflightIssueV1(
                code="INVALID_CLAIM_STRENGTH",
                message=f"Unsupported claim_strength value: {claim_strength}.",
                fix_hint="Use one of contract_satisfied, internally_supported, scientifically_convincing.",
            )
        )

    if not validation_missing and "validation_missing" not in report_text_lower:
        issues.append(
            LineReportPreflightIssueV1(
                code="MISSING_VALIDATION_DISCLOSURE",
                message="Report does not declare validation_missing.",
                fix_hint="Add a `validation_missing: ...` declaration even if the list is empty or none.",
            )
        )

    if not final_stopping_condition_present:
        issues.append(
            LineReportPreflightIssueV1(
                code="MISSING_FINAL_STOPPING_CONDITION",
                message="Report does not declare final_stopping_condition.",
                fix_hint="Add an explicit final_stopping_condition declaration.",
            )
        )

    for check_name, ok in semantic_checks.items():
        if ok:
            continue
        issues.append(
            LineReportPreflightIssueV1(
                code=f"MISSING_SEMANTIC_{check_name.upper()}",
                message=f"Report does not declare {check_name}.",
                fix_hint="Separate primary analysis from sensitivity analysis explicitly in the report text.",
            )
        )

    return LineReportPreflightV1(
        report_path=str(report_path),
        report_present=True,
        parse_status="ok",
        required_blocks=required_blocks,
        required_fields=required_fields,
        semantic_checks=semantic_checks,
        issues=issues,
        ready_for_review=not issues,
    )


__all__ = ["run_autoresearch_report_preflight"]
