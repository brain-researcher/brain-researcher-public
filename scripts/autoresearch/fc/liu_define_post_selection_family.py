#!/usr/bin/env python3
"""Define an accepted-branch Liu post-selection candidate family.

This helper is intentionally inspection-only. It reads the post-selection
candidate inventory plus project ledgers, applies explicit workspace/action
selection rules, and writes JSON/Markdown manifests for a future
max-over-pipelines correction. It does not import run.py/predict.py or execute
model fits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = Path("/data/brain_researcher/research/predictive/project")
DEFAULT_INVENTORY = DEFAULT_PROJECT / "post_selection_candidate_inventory.json"
DEFAULT_OUT_JSON = (
    DEFAULT_PROJECT / "manifests" / "liu_post_selection_accepted_branch_family.json"
)
DEFAULT_OUT_MD = (
    DEFAULT_PROJECT / "manifests" / "LIU_POST_SELECTION_ACCEPTED_BRANCH_FAMILY.md"
)

DEFAULT_ACCEPTED_BRANCH_WORKSPACES = (
    "autoresearch",
    "autoresearch_representation_scaling_line_kg_grounded_prior_20260422_120650",
    "autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139",
    "autoresearch_sensitivity_line_sensitivity_gsr_altparc_altfolds_20260422_180853",
)
DEFAULT_EXCLUDE_ACTION_TYPES = ("final_report", "synthesize")
DEFAULT_EXCLUDE_CONFIG_KEYWORDS = (
    "external_cohort",
    "external validation",
    "blind_replication",
    "global_signal",
    "gsr",
    "schaefer200",
    "schaefer-200",
    "schaefer400",
    "schaefer-400",
    "alternate_parcellation",
    "alt_parcellation",
    "altparc",
)


def _json_default(obj: Any) -> str:
    return str(obj)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_hash(config: Any) -> str:
    payload = json.dumps(config or {}, sort_keys=True, default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_ledger_rows(project: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(project.glob("autoresearch*/experiments.jsonl")):
        workspace = path.parent.name
        for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                rows.append(
                    {
                        "workspace": workspace,
                        "ledger": str(path.relative_to(project)),
                        "line_no": line_no,
                        "parse_error": "json_decode_error",
                    }
                )
                continue
            config = row.get("config", {})
            rows.append(
                {
                    "workspace": workspace,
                    "ledger": str(path.relative_to(project)),
                    "line_no": line_no,
                    "iteration": row.get("iteration"),
                    "timestamp_utc": row.get("timestamp_utc"),
                    "action_type": row.get("action_type"),
                    "config_hash": _config_hash(config),
                    "config": config,
                    "predict_sha256": row.get("predict_sha256"),
                    "harness_sha256": row.get("harness_sha256"),
                    "run_py_sha256": row.get("run_py_sha256"),
                }
            )
    return rows


def _workspace_matches(
    workspace: str,
    *,
    exact: set[str],
    regexes: list[re.Pattern[str]],
) -> bool:
    return workspace in exact or any(pattern.search(workspace) for pattern in regexes)


def _compile_regexes(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in patterns]


def _stringify_config(config: Any) -> str:
    return json.dumps(config or {}, sort_keys=True, default=_json_default).lower()


def _row_exclusion_reasons(
    row: dict[str, Any],
    *,
    include_workspaces: set[str],
    include_workspace_regexes: list[re.Pattern[str]],
    exclude_workspaces: set[str],
    exclude_workspace_regexes: list[re.Pattern[str]],
    exclude_action_types: set[str],
    exclude_config_keywords: tuple[str, ...],
) -> list[str]:
    reasons: list[str] = []
    workspace = str(row.get("workspace") or "")
    action_type = row.get("action_type")
    if not _workspace_matches(
        workspace,
        exact=include_workspaces,
        regexes=include_workspace_regexes,
    ):
        reasons.append("workspace_not_in_included_family")
    if _workspace_matches(
        workspace,
        exact=exclude_workspaces,
        regexes=exclude_workspace_regexes,
    ):
        reasons.append("workspace_excluded_by_rule")
    if action_type in exclude_action_types:
        reasons.append("action_type_excluded_by_rule")
    config_text = _stringify_config(row.get("config"))
    matched_keywords = [
        keyword for keyword in exclude_config_keywords if keyword in config_text
    ]
    if matched_keywords:
        reasons.append(
            "config_keyword_excluded_by_rule:" + ",".join(sorted(matched_keywords))
        )
    if row.get("parse_error"):
        reasons.append(str(row["parse_error"]))
    return reasons


def _workspace_replayability(project: Path, workspace: str) -> dict[str, Any]:
    workspace_path = project / workspace
    run_py = workspace_path / "run.py"
    predict_py = workspace_path / "predict.py"
    output_py_files = sorted(
        str(path.relative_to(workspace_path))
        for path in (workspace_path / "outputs").glob("**/*.py")
        if path.is_file()
    ) if (workspace_path / "outputs").exists() else []
    gaps: list[str] = []
    if not workspace_path.exists():
        gaps.append("workspace_directory_missing")
    if not run_py.exists():
        gaps.append("run_py_missing")
    if not predict_py.exists():
        gaps.append("predict_py_missing")
    gaps.append("per_iteration_code_snapshot_not_verified")
    return {
        "workspace": workspace,
        "workspace_path": str(workspace_path),
        "workspace_exists": workspace_path.exists(),
        "run_py_exists": run_py.exists(),
        "predict_py_exists": predict_py.exists(),
        "current_run_py_sha256": _sha256(run_py),
        "current_predict_py_sha256": _sha256(predict_py),
        "output_python_artifacts_count": len(output_py_files),
        "sample_output_python_artifacts": output_py_files[:10],
        "gaps": gaps,
    }


def _inventory_by_hash(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["config_hash"]): item
        for item in inventory.get("unique_configs", [])
        if isinstance(item, dict) and item.get("config_hash")
    }


def build_manifest(
    *,
    project: Path,
    inventory_path: Path,
    include_workspace: tuple[str, ...],
    include_workspace_regex: tuple[str, ...],
    exclude_workspace: tuple[str, ...],
    exclude_workspace_regex: tuple[str, ...],
    exclude_action_type: tuple[str, ...],
    exclude_config_keyword: tuple[str, ...],
) -> dict[str, Any]:
    inventory = _read_json(inventory_path)
    inventory_configs = _inventory_by_hash(inventory)
    ledger_rows = _iter_ledger_rows(project)
    include_regexes = _compile_regexes(list(include_workspace_regex))
    exclude_regexes = _compile_regexes(list(exclude_workspace_regex))
    include_workspaces = set(include_workspace)
    exclude_workspaces = set(exclude_workspace)
    exclude_action_types = set(exclude_action_type)

    rows_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    accepted_rows_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exclusion_reasons_by_hash: dict[str, Counter[str]] = defaultdict(Counter)
    row_exclusions: list[dict[str, Any]] = []

    for row in ledger_rows:
        config_hash = row.get("config_hash")
        if not config_hash:
            continue
        rows_by_hash[str(config_hash)].append(row)
        reasons = _row_exclusion_reasons(
            row,
            include_workspaces=include_workspaces,
            include_workspace_regexes=include_regexes,
            exclude_workspaces=exclude_workspaces,
            exclude_workspace_regexes=exclude_regexes,
            exclude_action_types=exclude_action_types,
            exclude_config_keywords=exclude_config_keyword,
        )
        if reasons:
            for reason in reasons:
                exclusion_reasons_by_hash[str(config_hash)][reason] += 1
            row_exclusions.append(
                {
                    "config_hash": config_hash,
                    "workspace": row.get("workspace"),
                    "ledger": row.get("ledger"),
                    "line_no": row.get("line_no"),
                    "iteration": row.get("iteration"),
                    "action_type": row.get("action_type"),
                    "reasons": reasons,
                }
            )
        else:
            accepted_rows_by_hash[str(config_hash)].append(row)

    accepted_candidates: list[dict[str, Any]] = []
    accepted_workspaces: set[str] = set()
    for config_hash, rows in sorted(accepted_rows_by_hash.items()):
        inv = inventory_configs.get(config_hash, {})
        workspaces = sorted({str(row["workspace"]) for row in rows})
        accepted_workspaces.update(workspaces)
        action_types = sorted({str(row.get("action_type")) for row in rows})
        first_row = min(
            rows,
            key=lambda row: (
                str(row.get("timestamp_utc") or ""),
                str(row.get("ledger") or ""),
                int(row.get("line_no") or 0),
            ),
        )
        replayability = {
            "row_code_hashes_logged": any(
                row.get("predict_sha256") or row.get("run_py_sha256") for row in rows
            ),
            "workspace_current_code_available": all(
                (project / workspace / "run.py").exists()
                and (project / workspace / "predict.py").exists()
                for workspace in workspaces
            ),
            "gaps": [],
        }
        if not replayability["row_code_hashes_logged"]:
            replayability["gaps"].append("ledger_rows_do_not_log_per_iteration_code_hashes")
        if not replayability["workspace_current_code_available"]:
            replayability["gaps"].append("current_workspace_code_missing")
        replayability["gaps"].append(
            "current_run_py_predict_py_may_not_match_historical_iteration_state"
        )
        accepted_candidates.append(
            {
                "config_hash": config_hash,
                "workspaces": workspaces,
                "action_types": action_types,
                "n_accepted_rows": len(rows),
                "n_total_ledger_rows_for_config": len(rows_by_hash.get(config_hash, [])),
                "first_accepted_row": {
                    key: first_row.get(key)
                    for key in (
                        "workspace",
                        "ledger",
                        "line_no",
                        "iteration",
                        "timestamp_utc",
                        "action_type",
                    )
                },
                "inventory_first_seen": inv.get("first_seen"),
                "max_aggregate_mean_r": inv.get("max_aggregate_mean_r"),
                "max_per_component_fold_mean_r": inv.get(
                    "max_per_component_fold_mean_r", {}
                ),
                "config": inv.get("config") or rows[0].get("config"),
                "replayability": replayability,
            }
        )

    accepted_candidates.sort(
        key=lambda item: (
            item["max_aggregate_mean_r"]
            if isinstance(item["max_aggregate_mean_r"], (int, float))
            else -999.0,
            item["config_hash"],
        ),
        reverse=True,
    )

    all_hashes = set(inventory_configs) | set(rows_by_hash)
    accepted_hashes = {item["config_hash"] for item in accepted_candidates}
    excluded_configs = []
    for config_hash in sorted(all_hashes - accepted_hashes):
        inv = inventory_configs.get(config_hash, {})
        excluded_configs.append(
            {
                "config_hash": config_hash,
                "n_ledger_rows": len(rows_by_hash.get(config_hash, [])),
                "max_aggregate_mean_r": inv.get("max_aggregate_mean_r"),
                "workspaces": sorted(
                    {str(row["workspace"]) for row in rows_by_hash.get(config_hash, [])}
                ),
                "reason_counts": dict(exclusion_reasons_by_hash.get(config_hash, {})),
            }
        )

    replayability_by_workspace = [
        _workspace_replayability(project, workspace)
        for workspace in sorted(accepted_workspaces)
    ]
    replayability_gap_counts = Counter(
        gap
        for workspace_payload in replayability_by_workspace
        for gap in workspace_payload["gaps"]
    )
    replayability_gap_counts.update(
        gap
        for item in accepted_candidates
        for gap in item["replayability"]["gaps"]
    )
    exclusion_reason_counts = Counter(
        reason for item in row_exclusions for reason in item["reasons"]
    )

    return {
        "schema_version": "liu_post_selection_accepted_branch_family_v1",
        "generated_at_utc": _utc_now(),
        "purpose": (
            "Define a frozen accepted-branch candidate family for later "
            "post-selection/max-over-pipelines correction. This manifest is "
            "selection metadata only, not a p-value and not a model execution."
        ),
        "no_model_fits_executed": True,
        "project": str(project),
        "inputs": {
            "inventory_path": str(inventory_path),
            "inventory_sha256": _sha256(inventory_path),
            "inventory_schema_version": inventory.get("schema_version"),
            "inventory_unique_configs": inventory.get("n_unique_logged_configs"),
            "inventory_ledger_rows": inventory.get("n_ledger_rows"),
        },
        "selection_rules": {
            "family_label": "accepted_branch",
            "include_workspace": list(include_workspace),
            "include_workspace_regex": list(include_workspace_regex),
            "exclude_workspace": list(exclude_workspace),
            "exclude_workspace_regex": list(exclude_workspace_regex),
            "exclude_action_type": list(exclude_action_type),
            "exclude_config_keyword": list(exclude_config_keyword),
            "out_of_scope_note": (
                "GSR/Schaefer data staging and external validation are not "
                "selected here. Matching configs are excluded by keyword rules; "
                "this helper also performs no data staging."
            ),
        },
        "summary": {
            "n_project_ledger_rows_seen": len(ledger_rows),
            "n_unique_configs_seen_in_ledgers": len(rows_by_hash),
            "n_accepted_unique_configs": len(accepted_candidates),
            "n_accepted_rows": sum(
                item["n_accepted_rows"] for item in accepted_candidates
            ),
            "n_excluded_unique_configs": len(excluded_configs),
            "exclusion_reason_counts": dict(exclusion_reason_counts),
            "accepted_workspace_counts": dict(
                Counter(
                    workspace
                    for item in accepted_candidates
                    for workspace in item["workspaces"]
                )
            ),
            "replayability_gap_counts": dict(replayability_gap_counts),
        },
        "accepted_candidates": accepted_candidates,
        "replayability_by_workspace": replayability_by_workspace,
        "excluded_configs": excluded_configs,
        "row_exclusion_audit": row_exclusions,
    }


def write_markdown(manifest: dict[str, Any], path: Path) -> None:
    summary = manifest["summary"]
    lines = [
        "# Liu Post-Selection Accepted-Branch Family",
        "",
        "This manifest defines the candidate family for a future max-over-pipelines correction.",
        "It is not a post-selection p-value and did not execute model fits.",
        "",
        "## Summary",
        "",
        f"- Accepted unique configs: {summary['n_accepted_unique_configs']}",
        f"- Accepted ledger rows: {summary['n_accepted_rows']}",
        f"- Excluded unique configs: {summary['n_excluded_unique_configs']}",
        f"- Project ledger rows inspected: {summary['n_project_ledger_rows_seen']}",
        "",
        "## Selection Rules",
        "",
    ]
    rules = manifest["selection_rules"]
    for key in (
        "include_workspace",
        "include_workspace_regex",
        "exclude_workspace",
        "exclude_workspace_regex",
        "exclude_action_type",
        "exclude_config_keyword",
    ):
        value = rules[key]
        lines.append(f"- {key}: `{json.dumps(value)}`")
    lines.extend(["", f"- Out-of-scope note: {rules['out_of_scope_note']}", ""])

    lines.extend(["## Accepted Candidates", ""])
    lines.append("| Rank | Config hash | Max aggregate r | Rows | Workspaces | Actions |")
    lines.append("|---:|---|---:|---:|---|---|")
    for rank, item in enumerate(manifest["accepted_candidates"], start=1):
        max_r = item["max_aggregate_mean_r"]
        max_text = "NA" if max_r is None else f"{max_r:.6f}"
        lines.append(
            f"| {rank} | `{item['config_hash']}` | {max_text} | "
            f"{item['n_accepted_rows']} | `{', '.join(item['workspaces'])}` | "
            f"`{', '.join(item['action_types'])}` |"
        )

    lines.extend(["", "## Replayability Gaps", ""])
    if summary["replayability_gap_counts"]:
        for gap, count in sorted(summary["replayability_gap_counts"].items()):
            lines.append(f"- {gap}: {count}")
    else:
        lines.append("- None detected.")
    lines.extend(
        [
            "",
            "Interpretation: current workspace `run.py`/`predict.py` files are useful",
            "for freezing runnable specs, but the ledgers generally do not prove that",
            "current code exactly matches every historical iteration.",
            "",
            "## Exclusion Counts",
            "",
        ]
    )
    if summary["exclusion_reason_counts"]:
        for reason, count in sorted(summary["exclusion_reason_counts"].items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- None.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect post_selection_candidate_inventory.json and project ledgers "
            "to define an accepted-branch candidate family manifest."
        )
    )
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument(
        "--include-workspace",
        action="append",
        default=[],
        help=(
            "Exact workspace to include. If omitted, the documented final "
            "accepted branch workspaces are used."
        ),
    )
    parser.add_argument(
        "--include-workspace-regex",
        action="append",
        default=[],
        help="Regex workspace include rule. May be repeated.",
    )
    parser.add_argument(
        "--exclude-workspace",
        action="append",
        default=[],
        help="Exact workspace to exclude after include rules. May be repeated.",
    )
    parser.add_argument(
        "--exclude-workspace-regex",
        action="append",
        default=[],
        help="Regex workspace exclude rule. May be repeated.",
    )
    parser.add_argument(
        "--exclude-action-type",
        action="append",
        default=[],
        help=(
            "Action type to exclude. Defaults to final_report and synthesize; "
            "repeat to add or use --no-default-action-exclusions."
        ),
    )
    parser.add_argument(
        "--no-default-action-exclusions",
        action="store_true",
        help="Do not exclude final_report/synthesize action rows by default.",
    )
    parser.add_argument(
        "--exclude-config-keyword",
        action="append",
        default=[],
        help=(
            "Case-insensitive JSON-config substring exclusion. Defaults cover "
            "GSR/Schaefer staging and external validation terms."
        ),
    )
    parser.add_argument(
        "--no-default-config-keyword-exclusions",
        action="store_true",
        help="Do not apply the default out-of-scope config keyword exclusions.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.include_workspace or args.include_workspace_regex:
        include_workspaces = tuple(args.include_workspace)
    else:
        include_workspaces = DEFAULT_ACCEPTED_BRANCH_WORKSPACES
    exclude_action_types = tuple(args.exclude_action_type)
    if not args.no_default_action_exclusions:
        exclude_action_types = DEFAULT_EXCLUDE_ACTION_TYPES + exclude_action_types
    exclude_config_keywords = tuple(keyword.lower() for keyword in args.exclude_config_keyword)
    if not args.no_default_config_keyword_exclusions:
        exclude_config_keywords = DEFAULT_EXCLUDE_CONFIG_KEYWORDS + exclude_config_keywords

    manifest = build_manifest(
        project=args.project.expanduser().resolve(),
        inventory_path=args.inventory.expanduser().resolve(),
        include_workspace=include_workspaces,
        include_workspace_regex=tuple(args.include_workspace_regex),
        exclude_workspace=tuple(args.exclude_workspace),
        exclude_workspace_regex=tuple(args.exclude_workspace_regex),
        exclude_action_type=exclude_action_types,
        exclude_config_keyword=exclude_config_keywords,
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    write_markdown(manifest, args.out_md)
    print(
        json.dumps(
            {
                "out_json": str(args.out_json),
                "out_md": str(args.out_md),
                **manifest["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
