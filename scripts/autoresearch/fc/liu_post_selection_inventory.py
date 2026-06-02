#!/usr/bin/env python3
"""Inventory candidate pipelines for Liu-component post-selection correction.

A valid max-over-pipelines null needs the family of materially tried candidate
pipelines. This script scans autoresearch ledgers, hashes their logged configs,
and reports observed maxima across candidate rows. It does not claim to compute
post-selection p-values; it defines the candidate family and replayability gap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = Path("/data/brain_researcher/research/predictive/project")


def _json_default(obj: Any) -> Any:
    return str(obj)


def _config_hash(config: Any) -> str:
    payload = json.dumps(config or {}, sort_keys=True, default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _iter_ledger_rows(project: Path):
    for path in sorted(project.glob("autoresearch*/experiments.jsonl")):
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield path, line_no, row


def _result_payload(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("results") if isinstance(row.get("results"), dict) else row


def build_inventory(project: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_config: dict[str, dict[str, Any]] = {}
    component_max: dict[str, dict[str, Any]] = {}
    aggregate_max: dict[str, Any] | None = None

    for path, line_no, row in _iter_ledger_rows(project):
        result = _result_payload(row)
        config = row.get("config", {})
        config_hash = _config_hash(config)
        aggregate = result.get("aggregate_mean_r", row.get("aggregate_mean_r"))
        per_component = result.get("per_component", row.get("per_component", [])) or []
        record = {
            "ledger": str(path.relative_to(project)),
            "line_no": line_no,
            "iteration": row.get("iteration"),
            "timestamp_utc": row.get("timestamp_utc"),
            "action_type": row.get("action_type"),
            "config_hash": config_hash,
            "config": config,
            "aggregate_mean_r": aggregate if isinstance(aggregate, (int, float)) else None,
            "per_component_fold_mean_r": {
                comp.get("component"): comp.get("fold_mean_r")
                for comp in per_component
                if isinstance(comp, dict) and isinstance(comp.get("fold_mean_r"), (int, float))
            },
            "predict_sha256": row.get("predict_sha256"),
            "harness_sha256": row.get("harness_sha256"),
            "replayability": "ledger_config_only",
        }
        rows.append(record)

        if config_hash not in by_config:
            by_config[config_hash] = {
                "config_hash": config_hash,
                "first_seen": {
                    "ledger": record["ledger"],
                    "line_no": line_no,
                    "iteration": row.get("iteration"),
                    "timestamp_utc": row.get("timestamp_utc"),
                },
                "config": config,
                "n_rows": 0,
                "max_aggregate_mean_r": None,
                "max_per_component_fold_mean_r": {},
            }
        cfg = by_config[config_hash]
        cfg["n_rows"] += 1
        if isinstance(record["aggregate_mean_r"], (int, float)):
            if (
                cfg["max_aggregate_mean_r"] is None
                or record["aggregate_mean_r"] > cfg["max_aggregate_mean_r"]
            ):
                cfg["max_aggregate_mean_r"] = record["aggregate_mean_r"]
            if aggregate_max is None or record["aggregate_mean_r"] > aggregate_max["value"]:
                aggregate_max = {"value": record["aggregate_mean_r"], "row": record}
        for name, value in record["per_component_fold_mean_r"].items():
            current = cfg["max_per_component_fold_mean_r"].get(name)
            if current is None or value > current:
                cfg["max_per_component_fold_mean_r"][name] = value
            if name not in component_max or value > component_max[name]["value"]:
                component_max[name] = {"value": value, "row": record}

    return {
        "schema_version": "liu_post_selection_candidate_inventory_v1",
        "project": str(project),
        "n_ledger_rows": len(rows),
        "n_unique_logged_configs": len(by_config),
        "aggregate_observed_max": aggregate_max,
        "component_observed_max": component_max,
        "unique_configs": sorted(
            by_config.values(),
            key=lambda item: (
                item["max_aggregate_mean_r"]
                if item["max_aggregate_mean_r"] is not None
                else -999
            ),
            reverse=True,
        ),
        "post_selection_null_plan": {
            "status": "inventory_only_not_p_value",
            "recommended_family": (
                "all materially tried candidate configs from ledgers, with "
                "sensitivity-only and validation-target-specific rows optionally "
                "excluded only by a pre-specified rule"
            ),
            "required_for_p_value": (
                "For each label shuffle, rerun every replayable candidate config "
                "or replay the deterministic selection policy, then compute the "
                "max statistic over candidates and components."
            ),
            "current_replayability_gap": (
                "Many historical rows have ledger configs but not per-iteration "
                "predict.py snapshots. Before a true max-over-pipelines null, "
                "material configs need to be converted into runnable frozen "
                "workspace specs."
            ),
        },
    }


def write_markdown(inventory: dict[str, Any], path: Path) -> None:
    lines = [
        "# Liu Component Post-Selection Candidate Inventory",
        "",
        "This is an inventory for designing a max-over-pipelines null. It is not a post-selection p-value.",
        "",
        f"- Ledger rows scanned: {inventory['n_ledger_rows']}",
        f"- Unique logged configs: {inventory['n_unique_logged_configs']}",
        "",
        "## Observed Maxima",
        "",
    ]
    agg = inventory["aggregate_observed_max"]
    if agg:
        row = agg["row"]
        lines.append(
            f"- Aggregate max: {agg['value']:.6f} from `{row['ledger']}` "
            f"iteration `{row['iteration']}` action `{row['action_type']}`."
        )
    for name, payload in sorted(inventory["component_observed_max"].items()):
        row = payload["row"]
        lines.append(
            f"- {name}: max fold-r {payload['value']:.6f} from `{row['ledger']}` "
            f"iteration `{row['iteration']}` action `{row['action_type']}`."
        )
    lines.extend(["", "## Top Configs By Observed Aggregate", ""])
    lines.append("| Rank | Config hash | Max aggregate | Rows | First seen |")
    lines.append("|---:|---|---:|---:|---|")
    for rank, cfg in enumerate(inventory["unique_configs"][:25], start=1):
        first = cfg["first_seen"]
        max_agg = cfg["max_aggregate_mean_r"]
        max_text = "NA" if max_agg is None else f"{max_agg:.6f}"
        lines.append(
            f"| {rank} | `{cfg['config_hash']}` | {max_text} | {cfg['n_rows']} | "
            f"`{first['ledger']}` iter `{first['iteration']}` |"
        )
    plan = inventory["post_selection_null_plan"]
    lines.extend(
        [
            "",
            "## Post-Selection Null Plan",
            "",
            f"- Status: {plan['status']}.",
            f"- Recommended family: {plan['recommended_family']}.",
            f"- Required for p-value: {plan['required_for_p_value']}.",
            f"- Replayability gap: {plan['current_replayability_gap']}.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_PROJECT / "post_selection_candidate_inventory.json",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=DEFAULT_PROJECT / "POST_SELECTION_CANDIDATE_INVENTORY.md",
    )
    args = parser.parse_args()
    inventory = build_inventory(args.project)
    args.out_json.write_text(json.dumps(inventory, indent=2, default=_json_default) + "\n")
    write_markdown(inventory, args.out_md)
    print(
        json.dumps(
            {
                "n_ledger_rows": inventory["n_ledger_rows"],
                "n_unique_logged_configs": inventory["n_unique_logged_configs"],
                "out_json": str(args.out_json),
                "out_md": str(args.out_md),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
