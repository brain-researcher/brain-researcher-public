#!/usr/bin/env python
"""Fetch PMC Open Access full text (XML→text) via pubget.

This is a thin wrapper around `pubget run` that:
  - loads `.env` so `NCBI_API_KEY` is picked up without putting it on the CLI
  - provides repo-friendly defaults for output/log locations

Example (10k fMRI-ish articles, 2015–2025):
  python scripts/fetch_pmc_oa_fulltext_pubget.py --n-docs 10000 --n-jobs 16
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    root = _repo_root()
    load_dotenv(root / ".env")
    load_dotenv(root / ".env.local", override=False)


def main() -> int:
    _load_dotenv()

    root = _repo_root()
    default_query = root / "scripts/pubget_queries/fmri_open_2015_2025.query.txt"
    default_out = root / "data/pubget"
    default_logs = root / "logs/pubget"

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--query-file",
        type=Path,
        default=default_query,
        help="Path to a PMC query file (E-utilities syntax).",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=default_out,
        help="Directory to store pubget outputs (query subdirs will be created).",
    )
    ap.add_argument(
        "--alias",
        type=str,
        default="fmri_oa_2015_2025_10k",
        help="Human-readable alias for this run (symlink in out-dir).",
    )
    ap.add_argument(
        "--n-docs",
        type=int,
        default=10_000,
        help="Approx. max number of articles (rounded up to nearest 500 by pubget).",
    )
    ap.add_argument(
        "--n-jobs",
        type=int,
        default=16,
        help="Parallelism for pubget steps (-1 = all cores).",
    )
    ap.add_argument(
        "--log-dir",
        type=Path,
        default=default_logs,
        help="Directory to store pubget log files.",
    )
    args = ap.parse_args()

    if not args.query_file.exists():
        raise SystemExit(f"Query file not found: {args.query_file}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)

    # pubget reads NCBI_API_KEY from env; do not echo secrets in command-line args.
    if not os.environ.get("NCBI_API_KEY"):
        print("Warning: NCBI_API_KEY not set; pubget will run with lower rate limits.")

    cmd = [
        "pubget",
        "run",
        str(args.out_dir),
        "-f",
        str(args.query_file),
        "--alias",
        args.alias,
        "--n_docs",
        str(args.n_docs),
        "--n_jobs",
        str(args.n_jobs),
        "--log_dir",
        str(args.log_dir),
    ]

    proc = subprocess.run(cmd, check=False)
    if proc.returncode not in (0, 1):
        raise SystemExit(proc.returncode)
    if proc.returncode == 1:
        print(
            "Note: pubget exited with status 1 (typically means download incomplete "
            "because you limited --n-docs, or some batches failed). Re-run the same "
            "command to resume missing batches."
        )
    print(f"Done. Output: {args.out_dir / args.alias}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
