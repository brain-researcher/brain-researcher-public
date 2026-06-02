"""Export the cleaned micro‑tooling benchmark CSV to JSON.

Prerequisite: run `scripts/eval/prepare_micro_tooling_benchmark.py` so the
`BrainRearcherBenchmark_MicroTooling.clean.csv` file is up to date.

Output: writes a JSON array to
`docs/BrainRearcherBenchmark_MicroTooling.json`.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CLEAN_CSV = ROOT / "docs" / "BrainRearcherBenchmark_MicroTooling.clean.csv"
OUTPUT_JSON = ROOT / "docs" / "BrainRearcherBenchmark_MicroTooling.json"

# Columns that should be lists in the JSON output.
LIST_COLS = {
    "expected_capability_list",
    "acceptance_metrics_list",
    "evidence_required_list",
}


def _as_list(value: Any) -> List[str]:
    """Convert semicolon/str/list values into a list of strings."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        # Try to parse stringified Python list first.
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if str(v).strip()]
            except (SyntaxError, ValueError):
                pass
        # Fallback: split on semicolons.
        return [part.strip() for part in s.split(";") if part.strip()]
    return [str(value).strip()]


def main() -> None:
    if not CLEAN_CSV.exists():
        raise FileNotFoundError(
            "Clean benchmark CSV not found. Run prepare_micro_tooling_benchmark.py first."
        )

    df = pd.read_csv(CLEAN_CSV)

    records = []
    for _, row in df.iterrows():
        rec: dict[str, Any] = {}
        for col, val in row.items():
            if col in LIST_COLS:
                rec[col] = _as_list(val)
            else:
                # Preserve NaN as null in JSON.
                if isinstance(val, float) and pd.isna(val):
                    rec[col] = None
                else:
                    rec[col] = val
        records.append(rec)

    OUTPUT_JSON.write_text(json.dumps(records, indent=2))
    print(f"Wrote {len(records)} tasks -> {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
