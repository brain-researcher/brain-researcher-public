"""Create a cleaned version of the micro-tooling benchmark CSV.

Transforms applied:
- Drop rows without a task_id (the file includes blank separators).
- Fix column typos: task catefory -> task_category, evidence required -> evidence_required,
  expeted_tool_chain -> expected_tool_chain.
- Trim whitespace in text columns.
- Split multi-value fields (semicolon-delimited) into list columns with *_list suffix.

Usage:
    python scripts/eval/prepare_micro_tooling_benchmark.py

Outputs cleaned CSV beside the source file with an ASCII-only name ending in `.clean.csv`.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
# Source file currently stored without spaces to avoid filesystem encoding hiccups.
SOURCE = ROOT / "docs" / "BrainRearcherBenchmark-Micro‑Tooling.csv"
OUTPUT = ROOT / "docs" / "BrainRearcherBenchmark_MicroTooling.clean.csv"

COLUMN_MAP = {
    "task catefory": "task_category",
    "evidence required": "evidence_required",
    "expeted_tool_chain": "expected_tool_chain",
}
TEXT_COLS = [
    "task_id",
    "task_category",
    "mode",
    "user_prompt",
    "input_data_ref",
    "data_key",
    "context_block",
    "expected_capability",
    "acceptance_metrics",
    "evidence_required",
    "gold_ref",
    "notes",
    "expected_tool_chain",
]
MULTI_VALUE_COLS = [
    "expected_capability",
    "acceptance_metrics",
    "evidence_required",
]


def _split_multi(value: object) -> List[str]:
    """Split a semicolon-delimited string into a trimmed list."""
    if pd.isna(value):
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Source CSV not found: {SOURCE}")

    df = pd.read_csv(SOURCE)
    df = df.rename(columns=COLUMN_MAP)

    # Remove blank separator rows
    df = df.dropna(subset=["task_id"]).copy()

    # Trim whitespace in all text columns
    for col in TEXT_COLS:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

    # Add normalized list columns for multi-value fields
    for col in MULTI_VALUE_COLS:
        if col in df.columns:
            df[f"{col}_list"] = df[col].apply(_split_multi)

    df.to_csv(OUTPUT, index=False)
    print(f"Wrote {len(df)} rows -> {OUTPUT}")


if __name__ == "__main__":
    main()
