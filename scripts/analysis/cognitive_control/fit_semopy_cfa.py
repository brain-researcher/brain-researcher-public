#!/usr/bin/env python3
"""Fit small CFA models for the cognitive-control pipeline via semopy.

This is a Python fallback for environments that do not have `Rscript` and
`lavaan`. It is intentionally narrow: the initial supported model is the
reduced DMCC one-factor measurement model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from semopy import Model, calc_stats


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_CSV = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "harmonized_behavior"
    / "dmcc_behavior_only"
    / "behavior_harmonized.csv"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "outputs"
    / "patrick_congnitive_control"
    / "semopy_cfa"
    / "dmcc_behavior_only"
)

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "dmcc_unity": {
        "required_columns": [
            "dmcc_stroop_v",
            "dmcc_axcpt_v",
            "dmcc_taskswitch_v",
            "dmcc_sternberg_v",
        ],
        "description": """
            cef =~ dmcc_stroop_v + dmcc_axcpt_v + dmcc_taskswitch_v + dmcc_sternberg_v
        """,
    }
}
MERGE_METADATA_COLUMNS = ["dataset", "participant_id", "session_id"]


def _clean_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _serialize_frame_dict(frame: pd.DataFrame) -> dict[str, Any]:
    if len(frame) != 1:
        raise ValueError("Expected a one-row DataFrame for stats serialization.")
    row = frame.iloc[0].to_dict()
    return {str(key): _clean_scalar(value) for key, value in row.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fit a reduced cognitive-control CFA model with semopy."
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help="Path to the harmonized behavioral CSV.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for CFA outputs.",
    )
    parser.add_argument(
        "--model-name",
        choices=sorted(MODEL_SPECS),
        default="dmcc_unity",
        help="Named CFA model to fit.",
    )
    args = parser.parse_args()

    input_csv = args.input_csv.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    spec = MODEL_SPECS[args.model_name]
    required_columns = list(spec["required_columns"])
    df = pd.read_csv(input_csv)
    complete_mask = df[required_columns].notna().all(axis=1)
    data = df.loc[complete_mask, required_columns].copy()
    if data.empty:
        raise RuntimeError("No complete cases remain after selecting required columns.")
    metadata_columns = [
        column for column in MERGE_METADATA_COLUMNS if column in df.columns
    ]
    metadata_frame = df.loc[complete_mask, metadata_columns].reset_index(drop=True)
    original_row_index = (
        df.loc[complete_mask].index.to_series(name="input_row_index").reset_index(drop=True)
    )

    model = Model(spec["description"])
    fit_result = model.fit(data)
    parameter_table = model.inspect(std_est=True).copy()
    fit_stats = calc_stats(model)

    try:
        factor_scores = model.predict_factors(data)
    except Exception:
        factor_scores = pd.DataFrame(index=data.index)
    factor_scores = factor_scores.reset_index(drop=True)
    if metadata_columns:
        factor_scores = pd.concat([metadata_frame, original_row_index, factor_scores], axis=1)
    elif not factor_scores.empty:
        factor_scores.insert(0, "input_row_index", original_row_index)

    params_path = output_root / "parameter_estimates.csv"
    parameter_table.to_csv(params_path, index=False)

    fit_stats_path = output_root / "fit_stats.json"
    fit_stats_path.write_text(
        json.dumps(_serialize_frame_dict(fit_stats), indent=2), encoding="utf-8"
    )

    sample_summary = {
        "model_name": args.model_name,
        "input_csv": str(input_csv),
        "n_rows_input": int(len(df)),
        "n_rows_complete_cases": int(len(data)),
        "required_columns": required_columns,
        "metadata_columns": metadata_columns,
        "fit_result": str(fit_result),
    }
    sample_summary_path = output_root / "sample_summary.json"
    sample_summary_path.write_text(
        json.dumps(sample_summary, indent=2), encoding="utf-8"
    )

    factor_scores_path = output_root / "factor_scores.csv"
    factor_scores.to_csv(factor_scores_path, index=False)

    manifest = {
        "model_name": args.model_name,
        "parameter_estimates_csv": str(params_path),
        "fit_stats_json": str(fit_stats_path),
        "sample_summary_json": str(sample_summary_path),
        "factor_scores_csv": str(factor_scores_path),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"status": "ok", "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
