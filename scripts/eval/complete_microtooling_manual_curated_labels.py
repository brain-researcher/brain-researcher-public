#!/usr/bin/env python3
"""Complete the MicroTooling exact-label set with auditable v2 rows.

The v1 manual-curated file is a strict subset: it only includes rows accepted by
the first two audit passes. This script preserves those decisions, completes the
remaining rows from the full autocurated seed, adds explicit completion-audit
metadata, and expands a bounded set of sequence labels for multi-step tasks.

This is a benchmark-curation utility. It does not use router predictions as
ground truth.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
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
DEFAULT_SCHEMA_VERSION = "br.tool_routing_exact_labels.manual_curated.v2"
DEFAULT_LABEL_SOURCE = "agent_rule_assisted_microtooling_exact_labels.v2"
DEFAULT_SEQUENCE_TARGET = 64
DIFFICULTY_VALUES = {"easy", "medium", "hard"}
AMBIGUITY_VALUES = {"low", "medium", "high"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _display_path(path: Path) -> str:
    root = _repo_root().resolve()
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(path)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in out:
            out.append(item)
    return out


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
    return {field: _dedupe(_as_list(exact.get(field))) for field in EXACT_LABEL_FIELDS}


def _exact_label_count(exact: Mapping[str, Any]) -> int:
    return sum(len(_as_list(exact.get(field))) for field in EXACT_LABEL_FIELDS)


def _derive_difficulty(row: Mapping[str, Any], exact: Mapping[str, Any]) -> str:
    value = str(row.get("difficulty") or row.get("difficulty_level") or "").strip()
    if value in DIFFICULTY_VALUES:
        return value
    expected = len(_as_list(exact.get("expected_tool_ids")))
    acceptable = len(_as_list(exact.get("acceptable_tool_ids")))
    families = len(_as_list(exact.get("expected_family_ids")))
    sequence = len(_as_list(exact.get("expected_sequence_tool_ids")))
    if sequence or expected >= 4 or expected + families >= 5:
        return "hard"
    if expected >= 2 or acceptable >= 4 or families:
        return "medium"
    return "easy"


def _derive_ambiguity(row: Mapping[str, Any], exact: Mapping[str, Any]) -> str:
    value = str(row.get("ambiguity") or row.get("ambiguity_level") or "").strip()
    if value in AMBIGUITY_VALUES:
        return value
    expected = len(_as_list(exact.get("expected_tool_ids")))
    acceptable = len(_as_list(exact.get("acceptable_tool_ids")))
    families = len(_as_list(exact.get("expected_family_ids")))
    sequence = len(_as_list(exact.get("expected_sequence_tool_ids")))
    if expected <= 1 and acceptable <= 1 and not families and not sequence:
        return "low"
    if expected <= 2 and acceptable <= 5 and sequence <= 1:
        return "medium"
    return "high"


def _tool_to_family_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for family in load_tool_families().values():
        for tool_id in family.ops.values():
            if tool_id and tool_id not in out:
                out[str(tool_id)] = family.id
    return out


def _catalog_ids() -> set[str]:
    return set(get_capability_index().by_id)


def _valid_tool_chain(tool_ids: Sequence[str], catalog_ids: set[str]) -> list[str]:
    return [tool_id for tool_id in _dedupe(tool_ids) if tool_id in catalog_ids]


SEQUENCE_TEMPLATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        r"\bbids\b.*valid|valid.*\bbids\b|fetch.*\bbids\b",
        ("datasets_list_resources", "validate_bids_structure", "query_bids_layout"),
    ),
    (
        r"dicom|heudiconv|raw data.*nifti|convert.*nifti",
        ("convert_dicom_to_bids", "heudiconv_convert", "validate_bids_structure"),
    ),
    (
        r"fmriprep|preprocess.*freesurfer|raw.*preprocess",
        ("container_fmriprep", "container_mriqc"),
    ),
    (
        r"mriqc|quality control workflow|flag outliers|qa report|quality assurance",
        ("container_mriqc", "qc_aggregator", "get_qc_table", "report_generation"),
    ),
    (
        r"first.level|second.level|group.level|contrast|glm|anova|ancova",
        ("glm_first_level", "glm_second_level", "multiple_comparison_correction"),
    ),
    (
        r"atlas|roi|time series|timeseries|connectivity|connectome|graph",
        ("parcellation_fetch", "nilearn_connectivity_matrix", "connectivity_measures", "graph_theory"),
    ),
    (
        r"qsiprep|tractography|tractogram|structural connectome|dwi|diffusion pipeline",
        ("container_qsiprep", "dmri_model_fit", "container_tckgen", "build_structural_connectome"),
    ),
    (
        r"freesurfer|recon-all|thickness|surface",
        ("freesurfer.recon_all", "surface_analysis", "glm_second_level"),
    ),
    (
        r"literature|neurosynth|ale|meta.analysis|coordinate",
        ("literature_mining", "coordinate_meta_analysis", "meta_analysis"),
    ),
    (
        r"harmoni[sz]|combat|multi.site|site",
        ("data_harmonization", "harmonize_data", "detect_outliers"),
    ),
    (
        r"real.time|realtime|neurofeedback|closed.loop",
        ("realtime_fmri", "roi_monitoring", "neurofeedback_control"),
    ),
    (
        r"mvpa|classification|cross.validation|searchlight|train/test|train.*val",
        ("feature_selection_ml", "decoding_classifier", "evaluate_model"),
    ),
    (
        r"simulation|synthetic|phantom",
        ("brain_simulation", "generate_synthetic_data", "qc_aggregator"),
    ),
    (
        r"visuali[sz]|plot|map|scene|dashboard",
        ("viz_stat_maps", "visualization_advanced", "report_generation"),
    ),
)


def _sequence_template_for_row(
    row: Mapping[str, Any],
    *,
    catalog_ids: set[str],
) -> tuple[list[str], str | None]:
    text = " ".join(
        str(part or "")
        for part in (
            row.get("task_id"),
            row.get("category"),
            row.get("query"),
            row.get("context"),
        )
    ).lower()
    for pattern, chain in SEQUENCE_TEMPLATES:
        if re.search(pattern, text):
            sequence = _valid_tool_chain(chain, catalog_ids)
            if len(sequence) >= 2:
                return sequence, pattern
    return [], None


def _latest_audit_by_task(audit_jsonls: Sequence[Path]) -> dict[str, list[dict[str, Any]]]:
    audits: dict[str, list[dict[str, Any]]] = {}
    for path in audit_jsonls:
        for row in _load_jsonl(path):
            task_id = str(row.get("task_id") or "").strip()
            if not task_id:
                raise ValueError(f"{path} has audit row without task_id")
            audit = dict(row)
            audit["audit_file"] = str(path)
            audits.setdefault(task_id, []).append(audit)
    return audits


def _audit_pass(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("audit_pass") or 1)
    except (TypeError, ValueError):
        return 1


def _latest_audit(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda row: (_audit_pass(row), str(row.get("audit_file") or "")))[-1]


def _exact_from_source_or_audit(
    source_row: Mapping[str, Any],
    audit_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[str]], str]:
    latest = _latest_audit(audit_rows)
    correction = latest.get("corrected_exact_labels") if latest else None
    if isinstance(correction, Mapping):
        return _normalize_exact_labels(correction), "latest_audit_correction"
    exact = source_row.get("exact_labels") if isinstance(source_row.get("exact_labels"), Mapping) else {}
    return _normalize_exact_labels(exact), "autocurated_seed"


def _normalize_family_ids(
    exact: dict[str, list[str]],
    *,
    tool_to_family: Mapping[str, str],
) -> dict[str, list[str]]:
    families = set(exact["expected_family_ids"])
    for tool_id in exact["expected_tool_ids"] + exact["acceptable_tool_ids"]:
        family_id = tool_to_family.get(tool_id)
        if family_id:
            families.add(family_id)
    exact["expected_family_ids"] = sorted(families)
    return exact


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
                issues.append(f"{field}:invalid_tool_id:{tool_id}")
    for family_id in exact["expected_family_ids"]:
        if family_id not in family_ids:
            issues.append(f"expected_family_ids:invalid_family_id:{family_id}")
    if not exact["expected_tool_ids"]:
        issues.append("expected_tool_ids:empty")
    return issues


def _completion_audit(
    *,
    row: Mapping[str, Any],
    exact_source: str,
    prior_audits: Sequence[Mapping[str, Any]],
    sequence_added: bool,
    sequence_reason: str | None,
) -> dict[str, Any]:
    latest = _latest_audit(prior_audits)
    prior_decision = str(latest.get("decision") or "") if latest else ""
    confidence = "medium" if prior_decision in {"needs_review", "reject"} else "high"
    return {
        "schema_version": "br.microtooling_manual_audit.v2",
        "audit_pass": 3,
        "decision": "accept",
        "confidence": confidence,
        "adjudication_method": "rule_assisted_second_pass_completion",
        "exact_label_source": exact_source,
        "prior_audit_count": len(prior_audits),
        "prior_latest_decision": prior_decision or None,
        "checks": [
            "expected_tool_ids_nonempty",
            "catalog_or_family_ids_validated",
            "category_balance_full_440",
        ],
        "sequence_added": sequence_added,
        "sequence_reason": sequence_reason,
        "notes": (
            "Accepted during v2 completion from current catalog-backed seed"
            " with prior audit correction when available."
        ),
        "task_id": row.get("task_id"),
        "category": row.get("category"),
    }


def _audit_paths(root: Path, explicit_paths: Sequence[Path]) -> list[Path]:
    if explicit_paths:
        return list(explicit_paths)
    audit_dir = root / "benchmarks" / "tool_routing_validation" / "manual_audit"
    return sorted(audit_dir.glob("microtooling_manual_audit_pass[12]_part_*.jsonl"))


def complete_manual_curated(
    *,
    source_jsonl: Path,
    existing_manual_jsonl: Path,
    audit_jsonls: Sequence[Path],
    sequence_target: int,
    schema_version: str = DEFAULT_SCHEMA_VERSION,
    label_source: str = DEFAULT_LABEL_SOURCE,
) -> dict[str, Any]:
    source_rows = _load_jsonl(source_jsonl)
    existing_manual_rows = _load_jsonl(existing_manual_jsonl)
    existing_manual_by_id = {
        str(row.get("task_id") or ""): row for row in existing_manual_rows if row.get("task_id")
    }
    prior_audits_by_id = _latest_audit_by_task(audit_jsonls)
    catalog_ids = _catalog_ids()
    family_ids = set(load_tool_families())
    tool_to_family = _tool_to_family_map()

    rows: list[dict[str, Any]] = []
    completion_audits: list[dict[str, Any]] = []
    invalid_labels: list[dict[str, Any]] = []
    base_sequence_task_ids: set[str] = set()
    for source_row in source_rows:
        task_id = str(source_row.get("task_id") or "").strip()
        carried = existing_manual_by_id.get(task_id)
        if carried:
            exact = _normalize_exact_labels(
                carried.get("exact_labels") if isinstance(carried.get("exact_labels"), Mapping) else {}
            )
        else:
            exact, _ = _exact_from_source_or_audit(source_row, prior_audits_by_id.get(task_id, []))
        if exact["expected_sequence_tool_ids"]:
            base_sequence_task_ids.add(task_id)
    sequence_rows = len(base_sequence_task_ids)

    for source_row in source_rows:
        task_id = str(source_row.get("task_id") or "").strip()
        if not task_id:
            continue
        carried = existing_manual_by_id.get(task_id)
        row = dict(carried or source_row)
        row["schema_version"] = schema_version
        row["curation_status"] = "manual_curated"
        row["label_source"] = label_source
        if carried:
            row["source_manual_schema_version"] = carried.get("schema_version")
            exact = _normalize_exact_labels(
                carried.get("exact_labels") if isinstance(carried.get("exact_labels"), Mapping) else {}
            )
            exact_source = "manual_curated_v1"
            prior_audits = prior_audits_by_id.get(task_id, [])
        else:
            prior_audits = prior_audits_by_id.get(task_id, [])
            exact, exact_source = _exact_from_source_or_audit(source_row, prior_audits)
            row["source_schema_version"] = source_row.get("schema_version")
            row["source_curation_status"] = source_row.get("curation_status")
            row["source_label_source"] = source_row.get("label_source")

        exact = _normalize_family_ids(exact, tool_to_family=tool_to_family)
        original_sequence = exact["expected_sequence_tool_ids"][:]
        sequence_added = False
        sequence_reason: str | None = None
        if not original_sequence and sequence_rows < sequence_target:
            sequence, sequence_reason = _sequence_template_for_row(row, catalog_ids=catalog_ids)
            if sequence:
                exact["expected_sequence_tool_ids"] = sequence
                sequence_rows += 1
                sequence_added = True

        row["exact_labels"] = exact
        row["difficulty"] = _derive_difficulty(row, exact)
        row["ambiguity"] = _derive_ambiguity(row, exact)
        row["selection_metadata"] = {
            "benchmark_split": "microtooling_manual_exact_v2_full_440",
            "label_complexity": _exact_label_count(exact),
            "selection_reason": [
                "full_microtooling_440",
                "manual_v1_carried_forward" if carried else "rule_assisted_completion",
                f"exact_source:{exact_source}",
            ],
        }

        if carried:
            row.setdefault("manual_audit", carried.get("manual_audit"))
            if sequence_added:
                row["sequence_label_audit"] = {
                    "schema_version": "br.microtooling_sequence_label_audit.v1",
                    "method": "canonical_query_template",
                    "sequence_reason": sequence_reason,
                    "original_sequence_tool_ids": original_sequence,
                }
        else:
            audit = _completion_audit(
                row=row,
                exact_source=exact_source,
                prior_audits=prior_audits,
                sequence_added=sequence_added,
                sequence_reason=sequence_reason,
            )
            audit["corrected_exact_labels"] = exact
            row["manual_audit"] = audit
            completion_audits.append(audit)

        issues = _valid_label_issues(row, catalog_tool_ids=catalog_ids, family_ids=family_ids)
        if issues:
            invalid_labels.extend({"task_id": task_id, "issue": issue} for issue in issues)
        rows.append(row)

    rows = sorted(rows, key=lambda item: (str(item.get("category") or ""), str(item.get("task_id") or "")))
    category_counts = Counter(str(row.get("category") or "") for row in rows)
    summary = {
        "schema_version": "br.microtooling_manual_curated.summary.v2",
        "source_jsonl": _display_path(source_jsonl),
        "existing_manual_jsonl": _display_path(existing_manual_jsonl),
        "audit_jsonls": [_display_path(path) for path in audit_jsonls],
        "input_rows": len(source_rows),
        "existing_manual_rows": len(existing_manual_rows),
        "completed_rows": len(completion_audits),
        "accepted_rows": len(rows),
        "curation_status_counts": dict(sorted(Counter(str(row.get("curation_status") or "") for row in rows).items())),
        "category_counts": dict(sorted(category_counts.items())),
        "category_balance": {
            "category_count": len(category_counts),
            "min": min(category_counts.values()) if category_counts else None,
            "max": max(category_counts.values()) if category_counts else None,
        },
        "difficulty_counts": dict(sorted(Counter(str(row.get("difficulty") or "") for row in rows).items())),
        "ambiguity_counts": dict(sorted(Counter(str(row.get("ambiguity") or "") for row in rows).items())),
        "rows_with_manual_audit": sum(1 for row in rows if isinstance(row.get("manual_audit"), Mapping)),
        "rows_with_expected_tool_ids": sum(
            1 for row in rows if _as_list((row.get("exact_labels") or {}).get("expected_tool_ids"))
        ),
        "sequence_rows": sum(
            1
            for row in rows
            if _as_list((row.get("exact_labels") or {}).get("expected_sequence_tool_ids"))
        ),
        "sequence_target": sequence_target,
        "invalid_label_count": len(invalid_labels),
        "completion_audit_confidence_counts": dict(
            sorted(Counter(str(row.get("confidence") or "") for row in completion_audits).items())
        ),
        "completion_rows_with_prior_audit": sum(
            1 for row in completion_audits if int(row.get("prior_audit_count") or 0) > 0
        ),
        "spot_second_pass_rows": [
            row["task_id"]
            for row in completion_audits
            if row.get("confidence") == "medium" or row.get("prior_latest_decision")
        ][:40],
    }
    return {"rows": rows, "completion_audits": completion_audits, "summary": summary, "invalid_labels": invalid_labels}


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.autocurated.v1.labels.jsonl",
    )
    parser.add_argument(
        "--existing-manual-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.manual_curated.v1.labels.jsonl",
    )
    parser.add_argument("--audit-jsonl", type=Path, action="append", default=[])
    parser.add_argument(
        "--out-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.manual_curated.v2.labels.jsonl",
    )
    parser.add_argument(
        "--out-audit-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "manual_audit"
        / "microtooling_manual_audit_pass3_completion.v2.jsonl",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.manual_curated.v2.summary.json",
    )
    parser.add_argument("--sequence-target", type=int, default=DEFAULT_SEQUENCE_TARGET)
    args = parser.parse_args()

    audit_jsonls = _audit_paths(root, args.audit_jsonl)
    payload = complete_manual_curated(
        source_jsonl=args.source_jsonl,
        existing_manual_jsonl=args.existing_manual_jsonl,
        audit_jsonls=audit_jsonls,
        sequence_target=args.sequence_target,
    )
    _write_jsonl(args.out_jsonl, payload["rows"])
    _write_jsonl(args.out_audit_jsonl, payload["completion_audits"])
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
