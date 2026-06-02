#!/usr/bin/env python3
"""
Generate the main paper figures (PNG) for the Imaging Neuroscience submission.

This script is intentionally *data-driven*: it reads the frozen CSV tables from
the story-pack folder and renders the same multi-panel figures deterministically.

Inputs (relative to --story_pack_dir):
  - tables/behavior_main.csv
  - tables/h1_native_deficit.csv
  - tables/routing_cross_subject_summary.csv
  - tables/routing_subj05_rescue_vs_sham_random.csv

Outputs (to --out_dir):
  - Fig1.png (behavioral anchor; panels A-C)
  - Fig2.png (Subj05 mechanistic core; panels A-C)
  - Fig3.png (cross-subject boundary conditions; panels A-B)
  - supplementary/Supp_S1.png (Subj05 all-ROI contrasts)
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return pd.read_csv(path)


def _subject_label(subj: int) -> str:
    return f"S{subj:02d}"


def _stage_display_name(stage: str) -> str:
    # Reader-facing names (avoid internal aliases in legends).
    mapping = {
        "rescue_ep50": "Rescue",
        "continue_train_50ep": "Continue-train",
        "sham_random_target": "Sham-random",
        "sham_label_shuffle_targets": "True sham (pair-breaking)",
        "native": "Native",
    }
    return mapping.get(stage, stage)


def _sig_stars(q: float) -> str:
    # Keep simple and consistent with the existing draft: q<0.05/*, q<0.01/**, q<0.001/***
    if q < 0.001:
        return "***"
    if q < 0.01:
        return "**"
    if q < 0.05:
        return "*"
    return ""


def _ensure_out_dir(story_pack_dir: Path, out_dir: Path | None) -> Path:
    if out_dir is not None:
        out = out_dir
    else:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = story_pack_dir / f"figures_regen_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "supplementary").mkdir(parents=True, exist_ok=True)
    return out


def make_fig1(story_pack_dir: Path, out_dir: Path, subjects: list[int]) -> Path:
    behavior = _load_csv(story_pack_dir / "tables" / "behavior_main.csv")
    h1 = _load_csv(story_pack_dir / "tables" / "h1_native_deficit.csv")

    # Panel A: native weak-minus-control effect with one-sided MW p-values.
    h1 = h1[h1["subject"].isin(subjects)].copy()
    h1["subj_label"] = h1["subject"].map(_subject_label)

    # Panel B: weak-class gain vs native across key stages.
    stages_b = [
        "rescue_ep50",
        "continue_train_50ep",
        "sham_random_target",
        "sham_label_shuffle_targets",
    ]
    beh = behavior[behavior["subject"].isin(subjects) & behavior["stage"].isin(stages_b + ["native"])].copy()
    beh["subj_label"] = beh["subject"].map(_subject_label)
    beh["stage_name"] = beh["stage"].map(_stage_display_name)

    # Panel C: pairing dependence = Rescue gain minus True sham gain (weak delta vs native).
    c_rows = []
    for subj in subjects:
        rescue = beh[(beh["subject"] == subj) & (beh["stage"] == "rescue_ep50")]["delta_weak_vs_native"].iloc[0]
        true_sham = beh[(beh["subject"] == subj) & (beh["stage"] == "sham_label_shuffle_targets")][
            "delta_weak_vs_native"
        ].iloc[0]
        c_rows.append({"subject": subj, "subj_label": _subject_label(subj), "pairing_dep": rescue - true_sham})
    pairing = pd.DataFrame(c_rows)

    fig = plt.figure(figsize=(16, 4), dpi=200)
    gs = fig.add_gridspec(1, 3, width_ratios=[1.1, 1.6, 1.0])

    # A
    ax = fig.add_subplot(gs[0, 0])
    colors = ["#808080" if p >= 0.05 else "#D55E00" for p in h1["mw_p_less"].to_list()]
    ax.bar(h1["subj_label"], h1["effect_weak_minus_control"], color=colors, edgecolor="none")
    ax.axhline(0, color="#333333", lw=1)
    ax.set_title("A  Native weak-class deficit", loc="left", fontsize=14, fontweight="bold")
    ax.set_ylabel("weak_mean − control_mean")
    # annotate p-values
    for x, y, p in zip(h1["subj_label"], h1["effect_weak_minus_control"], h1["mw_p_less"]):
        ax.text(x, y + (0.00025 if y >= 0 else -0.0012), f"p={p:.2g}", ha="center", va="bottom", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)

    # B
    ax = fig.add_subplot(gs[0, 1])
    subj_labels = [_subject_label(s) for s in subjects]
    x = np.arange(len(subjects))
    width = 0.18
    stage_order = stages_b
    stage_colors = {
        "rescue_ep50": "#0072B2",
        "continue_train_50ep": "#009E73",
        "sham_random_target": "#E69F00",
        "sham_label_shuffle_targets": "#CC79A7",
    }
    for i, stage in enumerate(stage_order):
        vals = []
        for subj in subjects:
            vals.append(
                beh[(beh["subject"] == subj) & (beh["stage"] == stage)]["delta_weak_vs_native"].iloc[0]
            )
        ax.bar(x + (i - 1.5) * width, vals, width=width, color=stage_colors[stage], label=_stage_display_name(stage))
    ax.set_xticks(x, subj_labels)
    ax.set_ylabel("Δ CLIP similarity (weak)")
    ax.set_title("B  Weak-class gain vs native", fontsize=14)
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)

    # C
    ax = fig.add_subplot(gs[0, 2])
    ax.bar(pairing["subj_label"], pairing["pairing_dep"], color="#0072B2")
    ax.set_title("C  Pairing dependence", fontsize=14)
    ax.set_ylabel("Rescue gain − True sham gain")
    for xlab, y in zip(pairing["subj_label"], pairing["pairing_dep"]):
        ax.text(xlab, y + 0.0006, f"{y:+.3f}", ha="center", va="bottom", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)

    out_path = out_dir / "Fig1.png"
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def make_fig2(story_pack_dir: Path, out_dir: Path) -> Path:
    routing = _load_csv(story_pack_dir / "tables" / "routing_cross_subject_summary.csv")
    roi = _load_csv(story_pack_dir / "tables" / "routing_subj05_rescue_vs_sham_random.csv")

    subj = 5
    r = routing[routing["subject"] == subj].iloc[0]

    canonical_rois = ["V1", "V2", "V3", "LO1", "V3B", "PH", "PHA1", "PHA2", "PHA3"]
    roi_c = roi[roi["roi"].isin(canonical_rois)].copy()
    roi_c["roi"] = pd.Categorical(roi_c["roi"], categories=canonical_rois, ordered=True)
    roi_c = roi_c.sort_values("roi")

    fig = plt.figure(figsize=(16, 4), dpi=200)
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 2.3, 1.1])

    # A: map-level summary (Subj05)
    ax = fig.add_subplot(gs[0, 0])
    ax.axis("off")
    ax.text(0.0, 0.95, "A  Map-level summary (S05)", fontsize=14, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, 0.70, "map corr (Rescue vs Sham-random)", fontsize=10, color="#555555", transform=ax.transAxes)
    ax.text(0.0, 0.58, f"{r['map_corr_rescue_vs_sham_random']:.3f}", fontsize=22, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, 0.38, "contrast abs mean", fontsize=10, color="#555555", transform=ax.transAxes)
    ax.text(0.0, 0.26, f"{r['contrast_abs_mean']:.4f}", fontsize=22, fontweight="bold", transform=ax.transAxes)
    ax.text(0.0, 0.06, "top-5 ROI Jaccard", fontsize=10, color="#555555", transform=ax.transAxes)
    ax.text(0.0, -0.06, f"{r['map_top5_roi_jaccard']:.3f}", fontsize=22, fontweight="bold", transform=ax.transAxes)

    # B: canonical ROI contrasts with CI and significance
    ax = fig.add_subplot(gs[0, 1])
    x = np.arange(len(canonical_rois))
    width = 0.34
    ax.bar(
        x - width / 2,
        roi_c["mean_delta_primary"],
        width=width,
        color="#0072B2",
        label="Rescue",
    )
    ax.bar(
        x + width / 2,
        roi_c["mean_delta_control"],
        width=width,
        color="#E69F00",
        label="Sham-random",
    )

    # Overlay contrast CI as points with error bars on a twin axis (matches existing draft).
    ax2 = ax.twinx()
    ax2.errorbar(
        x,
        roi_c["contrast_delta"],
        yerr=[
            roi_c["contrast_delta"] - roi_c["bootstrap_ci_low"],
            roi_c["bootstrap_ci_high"] - roi_c["contrast_delta"],
        ],
        fmt="o",
        color="#009E73",
        elinewidth=1.5,
        capsize=3,
        markersize=4,
        label="Contrast (CI95)",
    )
    ax.set_xticks(x, canonical_rois)
    ax.set_ylabel("Mean ROI score")
    ax2.set_ylabel("Contrast (Rescue − Sham-random)")
    ax.set_title("B  Key ROIs: Rescue vs Sham-random (S05)", fontsize=14)

    # Significance stars based on FDR q-values.
    for xi, q in zip(x, roi_c["wilcoxon_q"]):
        stars = _sig_stars(float(q))
        if stars:
            ax.text(xi, max(roi_c["mean_delta_primary"].max(), roi_c["mean_delta_control"].max()) * 0.98, stars,
                    ha="center", va="top", color="#009E73", fontsize=12, fontweight="bold")

    # Combined legend
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, frameon=False, fontsize=9, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    ax2.spines[["top"]].set_visible(False)

    # C: relative semantic bias (Early vs High-level)
    ax = fig.add_subplot(gs[0, 2])
    early = roi_c[roi_c["roi"].isin(["V1", "V2", "V3"])]["contrast_delta"].mean()
    high = roi_c[roi_c["roi"].isin(["LO1", "V3B", "PH", "PHA1", "PHA2", "PHA3"])]["contrast_delta"].mean()
    ratio = float(high / early) if early != 0 else float("nan")
    ax.bar(["Early", "High"], [early, high], color=["#808080", "#009E73"])
    ax.set_title("C  Relative semantic bias", fontsize=14)
    ax.set_ylabel("Mean contrast")
    ax.text(0.5, max(early, high) * 0.9, f"ratio = {ratio:.2f}", ha="center", va="center", fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)

    out_path = out_dir / "Fig2.png"
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def make_fig3(story_pack_dir: Path, out_dir: Path, subjects: list[int]) -> Path:
    routing = _load_csv(story_pack_dir / "tables" / "routing_cross_subject_summary.csv")
    routing = routing[routing["subject"].isin(subjects)].copy()
    routing["subj_label"] = routing["subject"].map(_subject_label)

    fig = plt.figure(figsize=(12, 4), dpi=200)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.2, 1.2])

    # A: map corr across subjects
    ax = fig.add_subplot(gs[0, 0])
    ax.bar(routing["subj_label"], routing["map_corr_rescue_vs_sham_random"], color="#0072B2")
    ax.set_ylim(0, 1.05)
    ax.set_title("A  Map similarity across subjects", fontsize=14)
    ax.set_ylabel("map corr (Rescue vs Sham-random)")
    ax.spines[["top", "right"]].set_visible(False)

    # B: canonical ROI contrasts across subjects
    ax = fig.add_subplot(gs[0, 1])
    rois = [("contrast_V1", "V1", "#808080"), ("contrast_LO1", "LO1", "#009E73"), ("contrast_V3B", "V3B", "#D55E00")]
    x = np.arange(len(subjects))
    width = 0.22
    for i, (col, name, color) in enumerate(rois):
        ax.bar(x + (i - 1) * width, routing[col], width=width, label=name, color=color)
    ax.axhline(0, color="#333333", lw=1)
    ax.set_xticks(x, [ _subject_label(s) for s in subjects ])
    ax.set_title("B  Canonical ROI contrasts", fontsize=14)
    ax.set_ylabel("ROI contrast (Rescue − Sham-random)")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)

    out_path = out_dir / "Fig3.png"
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def make_supp_s1(story_pack_dir: Path, out_dir: Path) -> Path:
    roi = _load_csv(story_pack_dir / "tables" / "routing_subj05_rescue_vs_sham_random.csv")
    roi = roi.copy()
    roi = roi.sort_values("contrast_delta", ascending=False)
    roi["rank"] = np.arange(len(roi))
    sig = roi["wilcoxon_q"] < 0.05

    fig, ax = plt.subplots(figsize=(12, 4), dpi=200)
    ax.scatter(roi.loc[~sig, "rank"], roi.loc[~sig, "contrast_delta"], s=18, color="#999999", label="q >= 0.05")
    ax.scatter(roi.loc[sig, "rank"], roi.loc[sig, "contrast_delta"], s=22, color="#D55E00", label="q < 0.05")
    ax.axhline(0, color="#333333", lw=1)
    ax.set_title("Supplementary S1: Subj05 all-ROI contrasts (rescue vs sham_random)")
    ax.set_xlabel("ROI rank by contrast (rescue − sham_random)")
    ax.set_ylabel("Contrast delta")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)

    out_path = out_dir / "supplementary" / "Supp_S1.png"
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--story_pack_dir",
        type=Path,
        default=Path("/data/brain_researcher_data/runs/paper_figs_imag_paperbanana_20260305"),
        help="Folder containing tables/ and notes/ for the paper story pack.",
    )
    parser.add_argument(
        "--out_dir",
        type=Path,
        default=None,
        help="Output directory. Default: <story_pack_dir>/figures_regen_<timestamp>/",
    )
    parser.add_argument(
        "--subjects",
        type=int,
        nargs="+",
        default=[1, 2, 5],
        help="Subjects to include in cross-subject figures.",
    )
    args = parser.parse_args()

    story_pack_dir: Path = args.story_pack_dir
    out_dir = _ensure_out_dir(story_pack_dir, args.out_dir)
    subjects = list(args.subjects)

    fig1 = make_fig1(story_pack_dir, out_dir, subjects)
    fig2 = make_fig2(story_pack_dir, out_dir)
    fig3 = make_fig3(story_pack_dir, out_dir, subjects)
    supp = make_supp_s1(story_pack_dir, out_dir)

    print("Wrote:")
    print(f"  {fig1}")
    print(f"  {fig2}")
    print(f"  {fig3}")
    print(f"  {supp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
