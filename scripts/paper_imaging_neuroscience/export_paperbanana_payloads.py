#!/usr/bin/env python3
"""
Export PaperBanana (Nano Banana) payload JSONs from a story-pack folder.

We keep plot data payloads explicit (arrays + labels) so the figure generator
doesn't need to infer/compute values and we avoid any risk of hallucinated
numbers. These JSONs are meant to be passed verbatim as `data_json` into
`mcp__paperbanana__generate_plot`.

Expected inputs (relative to --story_pack_dir):
  - tables/behavior_main.csv
  - tables/h1_native_deficit.csv
  - tables/routing_cross_subject_summary.csv
  - tables/routing_subj05_rescue_vs_sham_random.csv

Outputs (to <story_pack_dir>/prompts):
  - Fig1_paperbanana_data.json
  - Fig3_paperbanana_data.json
  - Supp_S1_paperbanana_data.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return pd.read_csv(path)


def _subject_label(subj: int) -> str:
    return f"S{subj:02d}"


def export_fig1(story_pack_dir: Path, out_dir: Path, subjects: list[int]) -> Path:
    beh = _read_csv(story_pack_dir / "tables" / "behavior_main.csv")
    h1 = _read_csv(story_pack_dir / "tables" / "h1_native_deficit.csv")

    stage_order = [
        ("rescue_ep50", "Rescue"),
        ("continue_train_50ep", "Continue-train"),
        ("sham_random_target", "Sham-random"),
        ("sham_label_shuffle_targets", "True sham (pair-breaking)"),
    ]

    panel_a = []
    for subj in subjects:
        row = h1[h1["subject"] == subj].iloc[0]
        panel_a.append(
            {
                "subject": _subject_label(subj),
                "weak_minus_control": float(row["effect_weak_minus_control"]),
                "mw_p_less": float(row["mw_p_less"]),
            }
        )

    panel_b = {"subjects": [_subject_label(s) for s in subjects], "stages": [n for _, n in stage_order], "values": []}
    for subj in subjects:
        subj_vals = []
        for stage, _name in stage_order:
            val = beh[(beh["subject"] == subj) & (beh["stage"] == stage)]["delta_weak_vs_native"].iloc[0]
            subj_vals.append(float(val))
        panel_b["values"].append(subj_vals)

    panel_c = []
    for subj in subjects:
        rescue = beh[(beh["subject"] == subj) & (beh["stage"] == "rescue_ep50")]["delta_weak_vs_native"].iloc[0]
        true_sham = beh[(beh["subject"] == subj) & (beh["stage"] == "sham_label_shuffle_targets")][
            "delta_weak_vs_native"
        ].iloc[0]
        panel_c.append({"subject": _subject_label(subj), "rescue_minus_true_sham": float(rescue - true_sham)})

    payload = {
        "panelA_native_deficit": panel_a,
        "panelB_weak_gain_vs_native": panel_b,
        "panelC_pairing_dependence": panel_c,
        "notes": {
            "panelA_test": "one-sided Mann-Whitney U (weak < control), p-values shown",
            "panelB_metric": "delta_weak_vs_native",
            "panelC_metric": "Rescue delta_weak_vs_native minus True sham delta_weak_vs_native",
        },
    }

    out_path = out_dir / "Fig1_paperbanana_data.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    return out_path


def export_fig3(story_pack_dir: Path, out_dir: Path, subjects: list[int]) -> Path:
    routing = _read_csv(story_pack_dir / "tables" / "routing_cross_subject_summary.csv")
    routing = routing[routing["subject"].isin(subjects)].copy()

    panel_a = []
    panel_b = []
    for subj in subjects:
        row = routing[routing["subject"] == subj].iloc[0]
        panel_a.append({"subject": _subject_label(subj), "map_corr_rescue_vs_sham_random": float(row["map_corr_rescue_vs_sham_random"])})
        panel_b.append(
            {
                "subject": _subject_label(subj),
                "contrast_V1": float(row["contrast_V1"]),
                "contrast_LO1": float(row["contrast_LO1"]),
                "contrast_V3B": float(row["contrast_V3B"]),
            }
        )

    payload = {
        "panelA_map_similarity": panel_a,
        "panelB_canonical_roi_contrasts": panel_b,
        "notes": {
            "panelA_metric": "voxelwise map correlation between delta maps (Rescue vs Sham-random)",
            "panelB_metric": "ROI contrast = mean_delta_rescue - mean_delta_sham_random (canonical ROIs)",
        },
    }

    out_path = out_dir / "Fig3_paperbanana_data.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    return out_path


def export_supp_s1(story_pack_dir: Path, out_dir: Path) -> Path:
    roi = _read_csv(story_pack_dir / "tables" / "routing_subj05_rescue_vs_sham_random.csv")
    roi = roi.sort_values("contrast_delta", ascending=False).reset_index(drop=True)
    rows = []
    for i, row in roi.iterrows():
        rows.append(
            {
                "rank": int(i),
                "roi": str(row["roi"]),
                "contrast_delta": float(row["contrast_delta"]),
                "wilcoxon_q": float(row["wilcoxon_q"]),
            }
        )
    payload = {"points": rows, "notes": {"threshold_q": 0.05, "y_metric": "contrast_delta (Rescue - Sham-random)"}}
    out_path = out_dir / "Supp_S1_paperbanana_data.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--story_pack_dir",
        type=Path,
        required=True,
        help="Story-pack folder containing tables/.",
    )
    parser.add_argument(
        "--subjects",
        type=int,
        nargs="+",
        default=[1, 2, 5],
        help="Subjects to include in cross-subject payloads.",
    )
    args = parser.parse_args()

    story_pack_dir: Path = args.story_pack_dir
    out_dir = story_pack_dir / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)

    subjects = list(args.subjects)
    p1 = export_fig1(story_pack_dir, out_dir, subjects)
    p3 = export_fig3(story_pack_dir, out_dir, subjects)
    ps = export_supp_s1(story_pack_dir, out_dir)

    print("Wrote:")
    print(f"  {p1}")
    print(f"  {p3}")
    print(f"  {ps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
