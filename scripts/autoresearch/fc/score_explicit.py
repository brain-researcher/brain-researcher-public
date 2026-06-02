#!/usr/bin/env python3
"""Explicit side-effect-free scorer for the live FC weak-target ledger.

Inputs:
- --ledger: path to experiments.jsonl
- --output: optional JSON output path

Outputs:
- prints a JSON score payload to stdout
- optionally writes the same payload to --output

This scorer is intentionally standalone so it can run on a worker without
depending on the brain_researcher package import path being configured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def compute_score(
    ledger_path: Path,
    *,
    weak_targets: tuple[str, ...],
    phase: str,
    baseline: float,
    reference: float,
    min_nulls: int,
    min_replicates: int,
) -> dict[str, Any]:
    rows = _read_jsonl(ledger_path)
    phase_rows = [row for row in rows if row.get("phase") == phase]

    best_r2 = {target: baseline for target in weak_targets}
    null_counts = {target: 0 for target in weak_targets}
    replicate_counts = {target: 0 for target in weak_targets}
    exploratory_terms: dict[str, set[int]] = {target: set() for target in weak_targets}

    for row in phase_rows:
        target = row.get("config", {}).get("target")
        if target not in weak_targets:
            continue
        score = row.get("scores", {}).get("gold_r2")
        if score is None:
            continue
        tags = set(row.get("tags") or [])
        hyper = row.get("config", {}).get("hyperparameters", {})
        term_index = hyper.get("term_index")
        is_null = "label-shuffle-control" in tags
        is_replicate = hyper.get("replicate_id") is not None
        if is_null:
            null_counts[target] += 1
            continue
        if is_replicate:
            replicate_counts[target] += 1
        if isinstance(term_index, int):
            exploratory_terms[target].add(term_index)
        if float(score) > best_r2[target]:
            best_r2[target] = float(score)

    mean_r2 = sum(best_r2.values()) / len(weak_targets) if weak_targets else baseline
    score = max(0.0, min(1.0, (mean_r2 - baseline) / (reference - baseline)))
    contract_satisfied = all(
        null_counts[target] >= min_nulls and replicate_counts[target] >= min_replicates
        for target in weak_targets
    )
    return {
        "scorer_name": "predictive_weak_targets",
        "scored_at_utc": _utc_now(),
        "ledger_path": str(ledger_path),
        "ledger_sha256": _sha256(ledger_path),
        "phase": phase,
        "weak_targets": list(weak_targets),
        "phase_rows": len(phase_rows),
        "target_scores": {target: round(value, 6) for target, value in best_r2.items()},
        "mean_r2_weak_targets": round(mean_r2, 6),
        "null_counts": null_counts,
        "replicate_counts": replicate_counts,
        "exploratory_term_counts": {
            target: len(indices) for target, indices in exploratory_terms.items()
        },
        "contract_satisfied": contract_satisfied,
        "score": round(score, 4),
        "baseline": baseline,
        "reference": reference,
        "minimum_nulls": min_nulls,
        "minimum_replicates": min_replicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--weak-target",
        action="append",
        default=[],
        help="Repeatable weak target override. Defaults to PicSeq/ListSort.",
    )
    parser.add_argument(
        "--phase",
        default="phase9_weak_target_term_discovery",
    )
    parser.add_argument("--baseline", type=float, default=-0.005)
    parser.add_argument("--reference", type=float, default=0.040)
    parser.add_argument("--min-nulls", type=int, default=4)
    parser.add_argument("--min-replicates", type=int, default=4)
    args = parser.parse_args()

    ledger_path = args.ledger.expanduser().resolve()
    weak_targets = tuple(args.weak_target) or ("PicSeq_Unadj", "ListSort_Unadj")
    payload = compute_score(
        ledger_path,
        weak_targets=weak_targets,
        phase=args.phase,
        baseline=args.baseline,
        reference=args.reference,
        min_nulls=args.min_nulls,
        min_replicates=args.min_replicates,
    )

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output_path = args.output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
