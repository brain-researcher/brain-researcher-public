#!/usr/bin/env python3
"""Build a combined cleanup guardrail claim-id list for task-panel cleanup."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claim-id-list",
        type=Path,
        action="append",
        required=True,
        help="Newline-delimited Claim.id input list. Can be repeated.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _load_claim_ids(path: Path) -> list[str]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Missing claim-id-list file: {resolved}")
    return [
        line.strip()
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    combined: set[str] = set()
    counts_by_source: Counter[str] = Counter()
    input_paths: list[str] = []
    for path in args.claim_id_list:
        resolved = path.expanduser().resolve()
        input_paths.append(str(resolved))
        claim_ids = _load_claim_ids(path)
        counts_by_source[str(resolved)] = len(claim_ids)
        combined.update(claim_ids)

    combined_list = sorted(combined)
    combined_path = output_dir / "cleanup_guardrail_claim_ids.txt"
    combined_path.write_text(
        "\n".join(combined_list) + ("\n" if combined_list else ""),
        encoding="utf-8",
    )
    summary = {
        "generated_at": _utc_now_iso(),
        "input_paths": input_paths,
        "counts_by_source": dict(counts_by_source),
        "counts": {
            "input_lists": len(input_paths),
            "combined_claim_ids": len(combined_list),
        },
        "artifacts": {
            "cleanup_guardrail_claim_ids_txt": str(combined_path),
        },
    }
    (output_dir / "cleanup_guardrail_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
