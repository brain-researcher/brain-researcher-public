#!/usr/bin/env python3
"""Hot-load live B2 conflict families and rebuild the bounded B2 task artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from scripts.tools.etl import build_claim_snapshot_v4_b2_conflict_expansion_pack as expansion
from scripts.tools.etl import build_claim_snapshot_v4_b2_split_manifest as split_builder
from scripts.tools.etl import build_claim_snapshot_v4_b2_task_manifest as task_builder
from scripts.tools.etl import run_claim_snapshot_v4_b2_baseline_eval as baseline

DEFAULT_EXCLUDE_PACK_JSONL = Path(
    "/app/brain_researcher/data/br-kg/raw/gabriel/eval/"
    "claim_snapshot_v4_b2_task_manifest/off400_reviewed_seed_conflict_expanded_20260314/"
    "claim_snapshot_v4_b2_examples.jsonl"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-id",
        action="append",
        required=True,
        help="Target id to hot-load one opposing-stanc e family from live Neo4j.",
    )
    parser.add_argument(
        "--run-label",
        required=True,
        help="Run label used to place artifacts under eval/claim_snapshot_v4_b2_*.",
    )
    parser.add_argument(
        "--eval-root",
        type=Path,
        default=Path("data/br-kg/raw/gabriel/eval"),
        help="Root eval directory under which hot-load artifacts should be written.",
    )
    parser.add_argument(
        "--exclude-pack-jsonl",
        type=Path,
        default=DEFAULT_EXCLUDE_PACK_JSONL,
        help=(
            "Reviewed seed/examples JSONL whose claim ids should be excluded from live "
            "hot-load mining."
        ),
    )
    parser.add_argument("--min-token-overlap", type=int, default=2)
    parser.add_argument("--min-jaccard", type=float, default=0.2)
    parser.add_argument("--top-k-per-target", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_label = str(args.run_label).strip()
    eval_root = args.eval_root.expanduser().resolve()
    exclude_pack_jsonl = args.exclude_pack_jsonl.expanduser().resolve()
    if not exclude_pack_jsonl.exists():
        raise SystemExit(
            "Fail-closed B2 hot-load mismatch: missing exclude-pack-jsonl "
            f"{exclude_pack_jsonl}"
        )

    expansion_dir = eval_root / "claim_snapshot_v4_b2_conflict_expansion" / run_label
    task_dir = eval_root / "claim_snapshot_v4_b2_task_manifest" / run_label
    split_dir = eval_root / "claim_snapshot_v4_b2_split" / run_label
    baseline_dir = eval_root / "claim_snapshot_v4_b2_baseline_eval" / run_label

    expansion.main(
        [
            "--output-dir",
            str(expansion_dir),
            *sum([["--target-id", target_id] for target_id in args.target_id], []),
            "--min-token-overlap",
            str(args.min_token_overlap),
            "--min-jaccard",
            str(args.min_jaccard),
            "--top-k-per-target",
            str(args.top_k_per_target),
            "--exclude-pack-jsonl",
            str(exclude_pack_jsonl),
        ]
    )

    extra_pack = expansion_dir / "claim_snapshot_v4_b2_conflict_expansion_pack.jsonl"
    task_builder.main(
        [
            "--output-dir",
            str(task_dir),
            "--extra-review-pack",
            f"hotload_conflict={extra_pack}",
        ]
    )

    task_manifest_json = task_dir / "claim_snapshot_v4_b2_task_manifest.json"
    split_builder.main(
        [
            "--task-manifest-json",
            str(task_manifest_json),
            "--output-dir",
            str(split_dir),
        ]
    )

    split_manifest_json = split_dir / "claim_snapshot_v4_b2_split_manifest.json"
    baseline.main(
        [
            "--split-manifest-json",
            str(split_manifest_json),
            "--output-dir",
            str(baseline_dir),
        ]
    )

    run_summary = {
        "generated_at": _utc_now_iso(),
        "run_label": run_label,
        "target_ids": list(args.target_id),
        "artifacts": {
            "exclude_pack_jsonl": str(exclude_pack_jsonl),
            "conflict_expansion_summary_json": str(
                expansion_dir / "claim_snapshot_v4_b2_conflict_expansion_summary.json"
            ),
            "task_summary_json": str(task_dir / "claim_snapshot_v4_b2_task_summary.json"),
            "split_summary_json": str(split_dir / "claim_snapshot_v4_b2_split_summary.json"),
            "baseline_summary_json": str(
                baseline_dir / "claim_snapshot_v4_b2_baseline_eval_summary.json"
            ),
        },
    }
    run_summary_path = eval_root / "claim_snapshot_v4_b2_hotload" / run_label / "run_summary.json"
    run_summary_path.parent.mkdir(parents=True, exist_ok=True)
    run_summary["artifacts"]["run_summary_json"] = str(run_summary_path)
    run_summary_path.write_text(json.dumps(run_summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
