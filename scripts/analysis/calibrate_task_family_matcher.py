#!/usr/bin/env python3
"""Calibrate TaskFamilyMatcher thresholds against live Task labels."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.neurokg.task_family_matcher import TaskFamilyMatcher

_MAPPED_METHODS = {"exact_alias", "fuzzy_alias", "aggressive_fuzzy_guarded"}
_PROFILE_DEFAULTS: dict[str, dict[str, float]] = {
    "legacy": {
        "fuzzy_threshold": 0.86,
        "aggressive_primary_threshold": 0.72,
        "aggressive_secondary_threshold": 0.64,
        "ambiguity_margin": 0.04,
        "min_token_overlap": 1.0,
    },
    "calibrated_v1": {
        "fuzzy_threshold": 0.82,
        "aggressive_primary_threshold": 0.68,
        "aggressive_secondary_threshold": 0.60,
        "ambiguity_margin": 0.03,
        "min_token_overlap": 1.0,
    },
}


@dataclass
class EvalConfig:
    name: str
    fuzzy_threshold: float
    aggressive_primary_threshold: float
    aggressive_secondary_threshold: float
    ambiguity_margin: float
    min_token_overlap: int


def _parse_float_list(raw: str) -> list[float]:
    values: list[float] = []
    for token in str(raw or "").split(","):
        text = token.strip()
        if not text:
            continue
        values.append(float(text))
    return values


def _parse_int_list(raw: str) -> list[int]:
    values: list[int] = []
    for token in str(raw or "").split(","):
        text = token.strip()
        if not text:
            continue
        values.append(int(text))
    return values


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _fetch_task_labels(
    *,
    uri: str,
    user: str,
    password: str,
    database: str | None,
) -> list[dict[str, str]]:
    cypher = """
    MATCH (t:Task)
    RETURN coalesce(t.id, elementId(t)) AS id,
           coalesce(t.name, t.label, t.title, t.id, elementId(t)) AS label
    """
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database or None) as session:
            rows = session.run(cypher).data()
    out: list[dict[str, str]] = []
    for row in rows:
        task_id = str(row.get("id") or "").strip()
        label = str(row.get("label") or "").strip()
        if not task_id or not label:
            continue
        out.append({"id": task_id, "label": label})
    return out


def _build_grid_configs(args: argparse.Namespace) -> list[EvalConfig]:
    profiles = [token.strip() for token in str(args.profiles).split(",") if token.strip()]
    configs: list[EvalConfig] = []
    for name in profiles:
        defaults = _PROFILE_DEFAULTS.get(name)
        if defaults is None:
            continue
        configs.append(
            EvalConfig(
                name=f"profile:{name}",
                fuzzy_threshold=float(defaults["fuzzy_threshold"]),
                aggressive_primary_threshold=float(defaults["aggressive_primary_threshold"]),
                aggressive_secondary_threshold=float(defaults["aggressive_secondary_threshold"]),
                ambiguity_margin=float(defaults["ambiguity_margin"]),
                min_token_overlap=int(defaults["min_token_overlap"]),
            )
        )

    if not args.grid:
        return configs

    fuzzy_values = _parse_float_list(args.fuzzy_thresholds)
    primary_values = _parse_float_list(args.primary_thresholds)
    secondary_values = _parse_float_list(args.secondary_thresholds)
    margin_values = _parse_float_list(args.ambiguity_margins)
    overlap_values = _parse_int_list(args.min_token_overlaps)
    for fuzzy, primary, secondary, margin, overlap in product(
        fuzzy_values,
        primary_values,
        secondary_values,
        margin_values,
        overlap_values,
    ):
        name = (
            f"grid:f={fuzzy:.2f}|p={primary:.2f}|s={secondary:.2f}|"
            f"m={margin:.3f}|o={overlap}"
        )
        configs.append(
            EvalConfig(
                name=name,
                fuzzy_threshold=fuzzy,
                aggressive_primary_threshold=primary,
                aggressive_secondary_threshold=secondary,
                ambiguity_margin=margin,
                min_token_overlap=overlap,
            )
        )
    return configs


def _evaluate(
    *,
    config: EvalConfig,
    taxonomy_path: Path,
    alias_extensions_path: Path | None,
    tasks: list[dict[str, str]],
) -> dict[str, Any]:
    matcher = TaskFamilyMatcher(
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        fuzzy_threshold=config.fuzzy_threshold,
        enable_fuzzy=True,
        aggressive_mode=True,
        aggressive_primary_threshold=config.aggressive_primary_threshold,
        aggressive_secondary_threshold=config.aggressive_secondary_threshold,
        min_token_overlap=config.min_token_overlap,
        ambiguity_margin=config.ambiguity_margin,
    )
    method_counts: Counter[str] = Counter()
    mapped = 0
    for task in tasks:
        _record, method, _score = matcher.match(task["label"])
        method_counts[method] += 1
        if method in _MAPPED_METHODS:
            mapped += 1

    total = len(tasks)
    return {
        "config": asdict(config),
        "total_tasks": total,
        "mapped_tasks": mapped,
        "mapped_ratio": (float(mapped) / float(total)) if total else 0.0,
        "method_counts": dict(sorted(method_counts.items())),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "name",
        "fuzzy_threshold",
        "aggressive_primary_threshold",
        "aggressive_secondary_threshold",
        "ambiguity_margin",
        "min_token_overlap",
        "total_tasks",
        "mapped_tasks",
        "mapped_ratio",
        "exact_alias",
        "aggressive_fuzzy_guarded",
        "fuzzy_alias",
        "ambiguous_rejected",
        "guardrail_rejected",
        "noise_rejected",
        "unmapped",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            counts = row.get("method_counts") or {}
            cfg = row["config"]
            writer.writerow(
                {
                    "name": cfg["name"],
                    "fuzzy_threshold": cfg["fuzzy_threshold"],
                    "aggressive_primary_threshold": cfg["aggressive_primary_threshold"],
                    "aggressive_secondary_threshold": cfg["aggressive_secondary_threshold"],
                    "ambiguity_margin": cfg["ambiguity_margin"],
                    "min_token_overlap": cfg["min_token_overlap"],
                    "total_tasks": row["total_tasks"],
                    "mapped_tasks": row["mapped_tasks"],
                    "mapped_ratio": row["mapped_ratio"],
                    "exact_alias": counts.get("exact_alias", 0),
                    "aggressive_fuzzy_guarded": counts.get("aggressive_fuzzy_guarded", 0),
                    "fuzzy_alias": counts.get("fuzzy_alias", 0),
                    "ambiguous_rejected": counts.get("ambiguous_rejected", 0),
                    "guardrail_rejected": counts.get("guardrail_rejected", 0),
                    "noise_rejected": counts.get("noise_rejected", 0),
                    "unmapped": counts.get("unmapped", 0),
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--taxonomy-path",
        type=Path,
        default=Path("configs/taxonomy/exports/task_families_master.yaml"),
    )
    parser.add_argument(
        "--alias-extensions-path",
        type=Path,
        default=Path("configs/taxonomy/exports/task_family_alias_extensions.yaml"),
    )
    parser.add_argument("--sample-size", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profiles", default="legacy,calibrated_v1")
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--fuzzy-thresholds", default="0.80,0.82,0.84,0.86")
    parser.add_argument("--primary-thresholds", default="0.64,0.66,0.68,0.70,0.72")
    parser.add_argument("--secondary-thresholds", default="0.56,0.58,0.60,0.62,0.64")
    parser.add_argument("--ambiguity-margins", default="0.02,0.03,0.04")
    parser.add_argument("--min-token-overlaps", default="1")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_matcher_report.json"),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("tmp/task_family_calibration/task_family_matcher_report.csv"),
    )
    parser.add_argument("--top-k", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    tasks = _fetch_task_labels(
        uri=str(args.neo4j_uri),
        user=str(args.neo4j_user),
        password=str(args.neo4j_password),
        database=args.neo4j_database,
    )
    if args.sample_size > 0 and len(tasks) > args.sample_size:
        random.Random(args.seed).shuffle(tasks)
        tasks = tasks[: args.sample_size]

    taxonomy_path = args.taxonomy_path.expanduser().resolve()
    alias_path = args.alias_extensions_path.expanduser().resolve()
    alias_extensions_path = alias_path if alias_path.exists() else None

    configs = _build_grid_configs(args)
    if not configs:
        raise SystemExit("No configs to evaluate. Check --profiles / --grid settings.")

    rows = [
        _evaluate(
            config=cfg,
            taxonomy_path=taxonomy_path,
            alias_extensions_path=alias_extensions_path,
            tasks=tasks,
        )
        for cfg in configs
    ]
    rows.sort(
        key=lambda item: (
            float(item.get("mapped_ratio", 0.0)),
            int(item.get("mapped_tasks", 0)),
        ),
        reverse=True,
    )

    top_k = max(1, int(args.top_k))
    report = {
        "input": {
            "task_count": len(tasks),
            "sample_size": args.sample_size,
            "taxonomy_path": str(taxonomy_path),
            "alias_extensions_path": str(alias_extensions_path) if alias_extensions_path else None,
        },
        "results_total": len(rows),
        "top_results": rows[:top_k],
        "all_results": rows,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    _write_csv(args.output_csv, rows)

    best = rows[0]
    cfg = best["config"]
    print(
        "Best config:",
        cfg["name"],
        f"mapped={best['mapped_tasks']}/{best['total_tasks']}",
        f"ratio={best['mapped_ratio']:.4f}",
    )
    print(f"Wrote JSON: {args.output_json}")
    print(f"Wrote CSV: {args.output_csv}")


if __name__ == "__main__":
    main()
