#!/usr/bin/env python3
"""Materialize agent-adjudicated MicroTooling exact labels.

This script keeps the candidate benchmark immutable. It reads the
``curated_candidate`` label file plus one or more manual-audit JSONL files, then
emits a separate exact-label JSONL containing only rows accepted by the audit.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.planner.catalog_loader import get_capability_index
from brain_researcher.services.agent.tool_router import load_tool_families

EXACT_LABEL_FIELDS = (
    "expected_tool_ids",
    "acceptable_tool_ids",
    "expected_family_ids",
    "expected_sequence_tool_ids",
)
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
DECISION_POLICIES = ("all_accept", "any_accept", "latest_pass")
DEFAULT_SCHEMA_VERSION = "br.tool_routing_exact_labels.manual_curated.v1"
DEFAULT_LABEL_SOURCE = "agent_adjudicated_microtooling_exact_labels.v1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _normalize_exact_labels(exact: Mapping[str, Any] | None) -> dict[str, list[str]]:
    exact = exact or {}
    return {field: _as_list(exact.get(field)) for field in EXACT_LABEL_FIELDS}


def _has_exact_labels(row: Mapping[str, Any]) -> bool:
    exact = row.get("exact_labels")
    if not isinstance(exact, Mapping):
        return False
    return any(_normalize_exact_labels(exact).values())


def _valid_label_issues(
    row: Mapping[str, Any],
    *,
    catalog_tool_ids: set[str],
    family_ids: set[str],
) -> list[str]:
    exact = _normalize_exact_labels(row.get("exact_labels") if isinstance(row.get("exact_labels"), Mapping) else {})
    issues: list[str] = []
    for field in ("expected_tool_ids", "acceptable_tool_ids", "expected_sequence_tool_ids"):
        for tool_id in exact[field]:
            if tool_id not in catalog_tool_ids:
                issues.append(f"invalid_tool_id:{tool_id}")
    for family_id in exact["expected_family_ids"]:
        if family_id not in family_ids:
            issues.append(f"invalid_family_id:{family_id}")
    return issues


def _audit_paths(root: Path, explicit_paths: Sequence[Path]) -> list[Path]:
    if explicit_paths:
        return list(explicit_paths)
    audit_dir = root / "benchmarks" / "tool_routing_validation" / "manual_audit"
    return sorted(audit_dir.glob("microtooling_manual_audit_pass*.jsonl"))


def _load_audits(paths: Sequence[Path]) -> dict[str, list[dict[str, Any]]]:
    audits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        for row in _load_jsonl(path):
            task_id = str(row.get("task_id") or "").strip()
            if not task_id:
                raise ValueError(f"{path} has audit row without task_id")
            audit = dict(row)
            audit["audit_file"] = str(path)
            audits[task_id].append(audit)
    return dict(audits)


def _audit_pass(audit: Mapping[str, Any]) -> int:
    try:
        return int(audit.get("audit_pass") or 1)
    except (TypeError, ValueError):
        return 1


def _adjudicating_audits(
    audit_rows: Sequence[Mapping[str, Any]],
    *,
    decision_policy: str,
) -> list[Mapping[str, Any]]:
    if decision_policy != "latest_pass":
        return list(audit_rows)
    latest_pass = max(_audit_pass(audit) for audit in audit_rows)
    return [audit for audit in audit_rows if _audit_pass(audit) == latest_pass]


def _audit_accepts(
    audit_rows: Sequence[Mapping[str, Any]],
    *,
    min_confidence: str,
    decision_policy: str,
) -> bool:
    if not audit_rows:
        return False
    threshold = CONFIDENCE_RANK[min_confidence]
    accepted = 0
    for audit in audit_rows:
        decision = str(audit.get("decision") or "").strip().lower()
        confidence = str(audit.get("confidence") or "").strip().lower()
        if decision != "accept":
            if decision_policy in {"all_accept", "latest_pass"}:
                return False
            continue
        if CONFIDENCE_RANK.get(confidence, -1) < threshold:
            if decision_policy in {"all_accept", "latest_pass"}:
                return False
            continue
        accepted += 1
    return accepted == len(audit_rows) if decision_policy in {"all_accept", "latest_pass"} else accepted > 0


def _apply_correction(source_row: Mapping[str, Any], audits: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    exact = _normalize_exact_labels(
        source_row.get("exact_labels") if isinstance(source_row.get("exact_labels"), Mapping) else {}
    )
    corrections = [
        audit.get("corrected_exact_labels")
        for audit in audits
        if isinstance(audit.get("corrected_exact_labels"), Mapping)
    ]
    if not corrections:
        return exact
    correction = corrections[-1]
    return _normalize_exact_labels(correction if isinstance(correction, Mapping) else exact)


def materialize_manual_curated(
    *,
    source_jsonl: Path,
    audit_jsonls: Sequence[Path],
    min_confidence: str,
    require_all_accept: bool,
    decision_policy: str = "all_accept",
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    label_source: str = DEFAULT_LABEL_SOURCE,
) -> dict[str, Any]:
    if decision_policy not in DECISION_POLICIES:
        raise ValueError(f"Unsupported decision_policy: {decision_policy}")
    if decision_policy == "any_accept" and require_all_accept:
        decision_policy = "all_accept"
    if decision_policy == "all_accept" and not require_all_accept:
        decision_policy = "any_accept"

    source_rows = _load_jsonl(source_jsonl)
    audits = _load_audits(audit_jsonls)
    catalog_tool_ids = set(get_capability_index().by_id)
    family_ids = set(load_tool_families())
    accepted_rows: list[dict[str, Any]] = []
    invalid_labels: list[dict[str, str]] = []
    exclusion_reasons: Counter[str] = Counter()

    for row in source_rows:
        task_id = str(row.get("task_id") or "").strip()
        audit_rows = audits.get(task_id, [])
        if not audit_rows:
            exclusion_reasons["missing_audit"] += 1
            continue
        adjudicating_audits = _adjudicating_audits(
            audit_rows,
            decision_policy=decision_policy,
        )
        if not _audit_accepts(
            adjudicating_audits,
            min_confidence=min_confidence,
            decision_policy=decision_policy,
        ):
            decisions = sorted(
                {str(audit.get("decision") or "unknown") for audit in adjudicating_audits}
            )
            exclusion_reasons["not_accepted:" + "|".join(decisions)] += 1
            continue

        manual_row = dict(row)
        manual_row["schema_version"] = schema_version
        manual_row["curation_status"] = "manual_curated"
        manual_row["label_source"] = label_source
        manual_row["source_schema_version"] = row.get("schema_version")
        manual_row["source_curation_status"] = row.get("curation_status")
        manual_row["source_label_source"] = row.get("label_source")
        manual_row["exact_labels"] = _apply_correction(row, adjudicating_audits)
        manual_row["manual_audit"] = {
            "schema_version": "br.microtooling_manual_audit.v1",
            "audit_count": len(audit_rows),
            "adjudicating_audit_count": len(adjudicating_audits),
            "min_confidence": min_confidence,
            "decision_policy": decision_policy,
            "decisions": [
                {
                    "decision": audit.get("decision"),
                    "confidence": audit.get("confidence"),
                    "audit_pass": _audit_pass(audit),
                    "notes": audit.get("notes"),
                    "audit_file": audit.get("audit_file"),
                }
                for audit in audit_rows
            ],
        }
        if not _has_exact_labels(manual_row):
            exclusion_reasons["empty_exact_after_correction"] += 1
            continue
        issues = _valid_label_issues(
            manual_row,
            catalog_tool_ids=catalog_tool_ids,
            family_ids=family_ids,
        )
        if issues:
            for issue in issues:
                invalid_labels.append({"task_id": task_id, "issue": issue})
            exclusion_reasons["invalid_label_after_correction"] += 1
            continue
        accepted_rows.append(manual_row)

    accepted_rows = sorted(
        accepted_rows,
        key=lambda item: (str(item.get("category") or ""), str(item.get("task_id") or "")),
    )
    return {
        "rows": accepted_rows,
        "summary": {
            "schema_version": "br.microtooling_manual_curated.summary.v1",
            "source_jsonl": str(source_jsonl),
            "audit_jsonls": [str(path) for path in audit_jsonls],
            "input_rows": len(source_rows),
            "audited_task_count": len(audits),
            "accepted_rows": len(accepted_rows),
            "invalid_label_count": len(invalid_labels),
            "min_confidence": min_confidence,
            "decision_policy": decision_policy,
            "category_counts": dict(
                sorted(Counter(str(row.get("category") or "") for row in accepted_rows).items())
            ),
            "exclusion_reasons": dict(sorted(exclusion_reasons.items())),
        },
        "invalid_labels": invalid_labels,
    }


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.curated.v1.labels.jsonl",
    )
    parser.add_argument("--audit-jsonl", type=Path, action="append", default=[])
    parser.add_argument(
        "--out-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.manual_curated.v1.labels.jsonl",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.manual_curated.v1.summary.json",
    )
    parser.add_argument("--min-confidence", choices=sorted(CONFIDENCE_RANK), default="medium")
    parser.add_argument("--decision-policy", choices=DECISION_POLICIES, default="latest_pass")
    parser.add_argument(
        "--allow-any-accept",
        action="store_true",
        help="Deprecated shorthand for --decision-policy any_accept.",
    )
    args = parser.parse_args()

    audit_jsonls = _audit_paths(root, args.audit_jsonl)
    if not audit_jsonls:
        raise SystemExit("No audit JSONL files found.")
    payload = materialize_manual_curated(
        source_jsonl=args.source_jsonl,
        audit_jsonls=audit_jsonls,
        min_confidence=args.min_confidence,
        require_all_accept=not args.allow_any_accept,
        decision_policy="any_accept" if args.allow_any_accept else args.decision_policy,
    )
    _write_jsonl(args.out_jsonl, payload["rows"])
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(
        json.dumps(payload["summary"], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    if payload["invalid_labels"]:
        print(json.dumps({"invalid_labels": payload["invalid_labels"][:20]}, indent=2))
    return 1 if payload["invalid_labels"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
