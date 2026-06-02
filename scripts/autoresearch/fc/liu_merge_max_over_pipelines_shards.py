#!/usr/bin/env python3
"""Merge sharded Liu max-over-pipelines permutation outputs.

Each shard is produced by ``liu_max_over_pipelines_permutation.py`` with a
disjoint seed range. This script writes a combined JSONL, summary JSON, and
markdown report without re-running any model fits.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


COMPONENT_ORDER = [
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_IllicitDrugUse",
    "ICA_MentalHealth",
]


def _load_runner() -> Any:
    runner_path = Path(__file__).with_name("liu_max_over_pipelines_permutation.py")
    spec = importlib.util.spec_from_file_location("liu_max_over_pipelines_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_perm_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "ok":
                rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--n-perm", type=int, required=True)
    parser.add_argument("--shard-dir", type=Path, action="append", required=True)
    parser.add_argument("--selected-config-hash", default="bfdbd2e7c675fa56")
    args = parser.parse_args()

    runner = _load_runner()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    shard_summaries = [
        _load_json(shard / "max_over_pipelines_summary.json")
        for shard in args.shard_dir
    ]
    first_summary = shard_summaries[0]
    first_family = first_summary["candidate_family"]
    candidate_hashes = list(first_family["candidate_hashes"])
    candidates = [{"config_hash": cand_hash} for cand_hash in candidate_hashes]
    skipped = [
        {
            "config_hash": row.get("config_hash"),
            "first_seen": row.get("first_seen"),
            "replayability": row.get("reason"),
        }
        for row in first_family.get("skipped", [])
    ]
    observed = _load_json(args.shard_dir[0] / "observed_candidates.json")

    rows_by_seed: dict[int, dict[str, Any]] = {}
    duplicate_seeds: list[int] = []
    for shard in args.shard_dir:
        for row in _load_perm_rows(shard / "max_over_pipelines_perm.jsonl"):
            seed = int(row["seed"])
            if seed in rows_by_seed:
                duplicate_seeds.append(seed)
            rows_by_seed[seed] = row

    perm_rows = [rows_by_seed[seed] for seed in sorted(rows_by_seed)]
    expected_seeds = set(range(1, int(args.n_perm) + 1))
    observed_seeds = set(rows_by_seed)
    missing_seeds = sorted(expected_seeds - observed_seeds)
    extra_seeds = sorted(observed_seeds - expected_seeds)

    perm_path = args.out_dir / "max_over_pipelines_perm.jsonl"
    with perm_path.open("w") as handle:
        for row in perm_rows:
            handle.write(json.dumps(row, default=runner._json_default) + "\n")
    (args.out_dir / "observed_candidates.json").write_text(
        json.dumps(observed, indent=2, default=runner._json_default) + "\n"
    )
    (args.out_dir / "candidate_selection_preview.json").write_text(
        json.dumps(
            {
                "source": "merged_shards",
                "n_replayable_candidates": len(candidates),
                "n_skipped_candidates": len(skipped),
                "candidate_hashes": candidate_hashes,
                "shard_dirs": [str(path) for path in args.shard_dir],
            },
            indent=2,
        )
        + "\n"
    )

    summary = runner._summarize(
        out_dir=args.out_dir,
        n_perm_requested=args.n_perm,
        selected_config_hash=args.selected_config_hash,
        candidates=candidates,
        skipped=skipped,
        observed=observed,
        perm_rows=perm_rows,
        component_order=COMPONENT_ORDER,
    )
    summary["merge_diagnostics"] = {
        "n_shards": len(args.shard_dir),
        "n_unique_perm_rows": len(perm_rows),
        "duplicate_seeds": sorted(set(duplicate_seeds)),
        "missing_seeds": missing_seeds,
        "extra_seeds": extra_seeds,
        "complete": not missing_seeds and not extra_seeds,
    }
    summary_path = args.out_dir / "max_over_pipelines_summary.json"
    report_path = args.out_dir / "max_over_pipelines_report.md"
    summary_path.write_text(json.dumps(summary, indent=2, default=runner._json_default) + "\n")
    runner._write_markdown(summary, report_path)
    print(
        json.dumps(
            {
                "n_perm_completed": len(perm_rows),
                "complete": summary["merge_diagnostics"]["complete"],
                "missing_seeds": missing_seeds[:20],
                "summary_json": str(summary_path),
                "summary_md": str(report_path),
            },
            indent=2,
        )
    )
    return 0 if summary["merge_diagnostics"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
