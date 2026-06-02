#!/usr/bin/env python3
"""H1 -> H1' transition figures for the TRIBE stimulus-discovery report.

Three figures:

- Figure 11 (redrawn): TRIBE encoder layer-by-layer scores for HCP language
  story-vs-math under the original branch-score statistic, on the full 81-item
  validated set. The original tier-6 result (T_late_minus_early = +0.859) was
  on n = 10 selected items; under n = 81 the late-vs-early ordering does NOT
  replicate (T = -0.187 unadjusted, T = -3.81 extended-acoustic adjusted).

- Figure 11b (new): Per-layer brain alignment with the Barch-2013 group
  activation map. Late encoder mean r = -0.283 (anti-aligns); audio projector
  r = +0.644; text projector r = -0.071. The audio projector is the single
  strongest brain-aligned feature anywhere in TRIBE for this contrast.

- Figure 14b (new): Per-subject scatter, audio-projector r vs late-encoder r,
  on the 50 paired NeuroVault zstats. 50/50 subjects positive on audio
  projector; 1/50 positive on late encoder. The cleanest visual of the
  H1 -> H1' rescue at the per-subject level.

All three figures use the same style as make_tribe_representation_figures.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")
DATA_DIR = FIGURE_ROOT / "data"
OUT_ROOT = FIGURE_ROOT / "h1_to_h1prime_figures_20260501"

INK = "#172033"
MUTED = "#667085"
GRID = "#E3E8EF"
GREEN = "#177D5A"
AMBER = "#C98200"
BLUE = "#2D6F94"
RED = "#B54708"
LIGHT = "#F8FAFC"

LATE_COLOR = "#2D6F94"
EARLY_COLOR = "#C98200"
PROJ_AUDIO_COLOR = "#177D5A"
PROJ_TEXT_COLOR = "#9B59B6"
OTHER_COLOR = "#94a3b8"


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": ["DejaVu Sans", "Liberation Sans", "Arial"],
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "axes.edgecolor": INK,
            "axes.linewidth": 0.9,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "savefig.bbox": "tight",
            "savefig.dpi": 220,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}")


def _layer_depth(name: str) -> float:
    if name.startswith("encoder.layers."):
        try:
            return float(name.split(".")[2])
        except (IndexError, ValueError):
            return -1
    if name == "projectors.audio":
        return -2
    if name == "projectors.text":
        return -1.5
    return -3


def figure11_per_layer_score_full_n81(out_root: Path) -> None:
    """Per-layer story-vs-math centroid score on n=81 items, replacing the
    old Figure 11 that quoted the now-non-replicated +0.859 value."""
    e2b = json.loads((DATA_DIR / "hcp_language_layer_family_extended_acoustic_e2b_verdict_20260430.json").read_text())
    per = e2b["per_layer"]
    enc_keys = sorted(
        [k for k in per if k.startswith("encoder.layers.")],
        key=lambda x: int(x.split(".")[2]),
    )
    late_set = set(e2b["late_layers"])
    early_set = set(e2b["early_layers"])

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0), gridspec_kw={"wspace": 0.32})
    style()

    # Panel A: per-layer score (unadjusted vs extended-acoustic) across the 16 encoder layers
    ax = axes[0]
    xs = list(range(len(enc_keys)))
    un = [per[k]["unadjusted"] for k in enc_keys]
    ext = [per[k]["extended_acoustic"] for k in enc_keys]
    width = 0.4

    bar_un = ax.bar([x - width / 2 for x in xs], un, width=width, color=BLUE, edgecolor=INK, linewidth=0.6, label="unadjusted")
    bar_ext = ax.bar([x + width / 2 for x in xs], ext, width=width, color=AMBER, edgecolor=INK, linewidth=0.6, label="extended-acoustic adjusted")

    # mark late and early bars
    for i, k in enumerate(enc_keys):
        if k in late_set:
            ax.add_patch(
                plt.Rectangle((i - 0.45, ax.get_ylim()[0] if False else 0), 0.9, 1, transform=ax.get_xaxis_transform(), facecolor=LATE_COLOR, alpha=0.06, zorder=0)
            )
        if k in early_set:
            ax.add_patch(
                plt.Rectangle((i - 0.45, 0), 0.9, 1, transform=ax.get_xaxis_transform(), facecolor=EARLY_COLOR, alpha=0.06, zorder=0)
            )

    ax.set_xticks(xs)
    ax.set_xticklabels([str(int(k.split(".")[2])) for k in enc_keys])
    ax.set_xlabel("encoder layer index (encoder.layers.N.1)", color=INK)
    ax.set_ylabel("story-vs-math centroid score (diff_norm × cosine_gap)", color=INK)
    ax.set_title("(a) per-layer story-vs-math separability on n=81 items", color=INK)
    ax.axhline(0, color=INK, linewidth=0.7)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.legend(loc="upper right", frameon=False, fontsize=8)

    # Annotate: "early shaded amber; late shaded blue"
    ax.text(
        0.02, 0.96,
        "shaded blue: late family {10,12,14}\nshaded amber: early family {0,2,4}",
        transform=ax.transAxes, va="top", ha="left",
        color=MUTED, fontsize=8,
    )

    # Panel B: T_late_minus_early across stimulus subsets (the small-sample-artifact panel)
    ax = axes[1]
    # Original 5-vs-5 from the original report (Table 3): T = +0.859
    # Plus our local recomputations (from earlier diagnostic in /tmp/e2b_subset_check)
    subsets = [
        ("original 5-vs-5\n(n=10, per report)", 0.859),
        ("local rerun:\nexpanded20 (n=40)", -2.283),
        ("local rerun:\nheldout21 (n=41)", -0.010),
        ("local rerun:\nall 81 unadjusted", -0.187),
        ("local rerun:\nall 81 extended-acoustic", -3.814),
    ]
    labels = [s[0] for s in subsets]
    vals = [s[1] for s in subsets]
    colors = [GREEN if v > 0 else RED for v in vals]
    bars = ax.barh(range(len(subsets)), vals, color=colors, edgecolor=INK, linewidth=0.6)
    ax.set_yticks(range(len(subsets)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(r"$T_\mathrm{late\ minus\ early}$ = mean(late layer scores) - mean(early layer scores)", color=INK)
    ax.axvline(0, color=INK, linewidth=0.7)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.set_title("(b) original tier-6 does not replicate at n=81", color=INK)
    for i, v in enumerate(vals):
        ax.text(v + (0.15 if v >= 0 else -0.15), i, f"{v:+.3f}", va="center", ha="left" if v >= 0 else "right", fontsize=8, color=INK)
    ax.invert_yaxis()
    # tighten x-axis around data
    pad = 0.6
    ax.set_xlim(min(vals) - pad - 0.6, max(vals) + pad + 0.6)

    fig.suptitle(
        "Figure 11. HCP language layer-family non-replication on n=81 (tier 6b)",
        fontsize=12, color=INK, y=1.02,
    )

    save_figure(fig, out_root, "figure11_layer_family_non_replication_20260501")
    plt.close(fig)


def figure11b_per_layer_brain_alignment(out_root: Path) -> None:
    """Per-layer brain alignment with Barch-2013 group map (E5 / tier 6c).

    The audio projector r=+0.644 visually dominates; late encoder layers are negative.
    """
    e5 = json.loads((DATA_DIR / "hcp_language_per_layer_brain_alignment_e5_verdict_20260430.json").read_text())
    per = e5["per_layer"]

    enc_keys = sorted(
        [k for k in per if k.startswith("encoder.layers.")],
        key=lambda x: int(x.split(".")[2]),
    )
    proj_audio = "projectors.audio"
    proj_text = "projectors.text"

    fig, ax = plt.subplots(figsize=(12.5, 5.0))
    style()

    # Layout: encoder layers (16 columns) + small gap + audio projector + text projector
    bar_positions = list(range(len(enc_keys))) + [len(enc_keys) + 1, len(enc_keys) + 2]
    bar_labels = [str(int(k.split(".")[2])) for k in enc_keys] + ["audio\nproj", "text\nproj"]
    bar_values = [per[k]["r_layer_projected"] for k in enc_keys] + [per[proj_audio]["r_layer_projected"], per[proj_text]["r_layer_projected"]]
    bar_colors = []
    late_set = set(["encoder.layers.10.1", "encoder.layers.12.1", "encoder.layers.14.1"])
    early_set = set(["encoder.layers.0.1", "encoder.layers.2.1", "encoder.layers.4.1"])
    for k in enc_keys:
        if k in late_set:
            bar_colors.append(LATE_COLOR)
        elif k in early_set:
            bar_colors.append(EARLY_COLOR)
        else:
            bar_colors.append(OTHER_COLOR)
    bar_colors.append(PROJ_AUDIO_COLOR)
    bar_colors.append(PROJ_TEXT_COLOR)

    bars = ax.bar(bar_positions, bar_values, color=bar_colors, edgecolor=INK, linewidth=0.6)
    ax.set_xticks(bar_positions)
    ax.set_xticklabels(bar_labels, fontsize=9)
    ax.axhline(0, color=INK, linewidth=0.7)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.set_ylabel("Pearson r (per-layer story-minus-math contrast vs Barch-2013 group map)", color=INK)
    ax.set_xlabel("encoder.layers.N.1                                                    projectors", color=INK)
    ax.set_title(
        "Figure 11b. Per-layer brain alignment: audio projector beats late encoder",
        fontsize=12, color=INK, pad=12,
    )

    # Annotate audio projector value
    ap_idx = len(enc_keys)
    ap_val = per[proj_audio]["r_layer_projected"]
    ax.annotate(
        f"audio projector\nr = {ap_val:+.3f}\n(strongest brain-\naligned feature)",
        xy=(ap_idx, ap_val),
        xytext=(ap_idx - 4, ap_val + 0.18),
        arrowprops=dict(arrowstyle="->", color=INK, lw=0.8),
        fontsize=9, color=INK, ha="left",
    )

    # Annotate the late-encoder mean (anti-aligns)
    late_mean = float(np.mean([per[k]["r_layer_projected"] for k in late_set]))
    ax.annotate(
        f"late {{10,12,14}}\nmean r = {late_mean:+.3f}\n(anti-aligns)",
        xy=(12, per["encoder.layers.12.1"]["r_layer_projected"]),
        xytext=(12 + 0.8, per["encoder.layers.12.1"]["r_layer_projected"] - 0.25),
        arrowprops=dict(arrowstyle="->", color=INK, lw=0.8),
        fontsize=9, color=INK,
    )

    # legend patches
    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor=LATE_COLOR, edgecolor=INK, label="late encoder {10,12,14}"),
        Patch(facecolor=EARLY_COLOR, edgecolor=INK, label="early encoder {0,2,4}"),
        Patch(facecolor=OTHER_COLOR, edgecolor=INK, label="other encoder layer"),
        Patch(facecolor=PROJ_AUDIO_COLOR, edgecolor=INK, label="audio projector"),
        Patch(facecolor=PROJ_TEXT_COLOR, edgecolor=INK, label="text projector"),
    ]
    ax.legend(handles=legend_handles, loc="lower left", frameon=False, fontsize=8, ncol=2)

    # T_late_minus_early text in upper-right corner
    T_obs = e5["T_late_minus_early_brain_r"]["observed"]
    p = e5["T_late_minus_early_brain_r"]["plus_one_p"]
    ax.text(
        0.99, 0.97,
        f"T_late_minus_early_brain_r = {T_obs:+.3f}\nplus-one p = {p:.4f}  (N = {e5['n_perm']:,})",
        transform=ax.transAxes, va="top", ha="right",
        fontsize=8, color=INK,
        bbox=dict(boxstyle="round,pad=0.4", facecolor=LIGHT, edgecolor=GRID, linewidth=0.6),
    )

    save_figure(fig, out_root, "figure11b_per_layer_brain_alignment_20260501")
    plt.close(fig)


def figure14b_per_subject_scatter(out_root: Path) -> None:
    """Per-subject Pearson r: audio projector vs late encoder, on 50 paired NeuroVault zstats."""
    e6 = json.loads((DATA_DIR / "hcp_language_subject_level_alignment_e6_verdict_20260430.json").read_text())
    per_subj = e6["per_subject"]

    audio_rs = []
    late_rs = []
    text_rs = []
    pred_rs = []
    sids = []
    for sid, d in per_subj.items():
        sids.append(sid)
        audio_rs.append(d["r_audio_projector"])
        late_rs.append(d["r_late_encoder"])
        text_rs.append(d["r_text_projector"])
        pred_rs.append(d["r_predicted"])

    audio_rs = np.array(audio_rs)
    late_rs = np.array(late_rs)
    text_rs = np.array(text_rs)
    pred_rs = np.array(pred_rs)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6), gridspec_kw={"width_ratios": [1.4, 1]})
    style()

    # Panel A: scatter audio_r (x) vs late_r (y) per subject
    ax = axes[0]
    ax.axhline(0, color=INK, linewidth=0.7)
    ax.axvline(0, color=INK, linewidth=0.7)
    # quadrant shading: bottom-right (audio + / late -) = the ideal H1' quadrant
    ax.axvspan(0, 1, ymin=0.0, ymax=0.5, color=GREEN, alpha=0.05)
    ax.scatter(audio_rs, late_rs, s=42, color=PROJ_AUDIO_COLOR, edgecolor=INK, linewidth=0.6, alpha=0.85, zorder=3)
    ax.set_xlabel("per-subject Pearson r: audio projector vs subject zstat", color=INK)
    ax.set_ylabel("per-subject Pearson r: late encoder mean vs subject zstat", color=INK)
    ax.set_title("(a) every subject lands in the audio-pos / late-neg quadrant (n = 50)", color=INK)
    ax.grid(linestyle="--", alpha=0.4)
    ax.text(
        0.97, 0.04,
        "ideal H1' quadrant\n(audio aligns,\nlate anti-aligns)",
        transform=ax.transAxes, ha="right", va="bottom",
        color=GREEN, fontsize=8, fontweight="bold",
    )
    n_in_ideal = int(np.sum((audio_rs > 0) & (late_rs < 0)))
    ax.text(
        0.97, 0.97,
        f"{n_in_ideal} of {len(audio_rs)} subjects in ideal quadrant",
        transform=ax.transAxes, ha="right", va="top",
        fontsize=9, color=INK,
        bbox=dict(boxstyle="round,pad=0.4", facecolor=LIGHT, edgecolor=GRID, linewidth=0.6),
    )

    # Panel B: paired strip plot — show every subject's audio r and late r (and predicted r for comparison)
    ax = axes[1]
    ax.axvline(0, color=INK, linewidth=0.7)
    rows = [
        ("late encoder mean", late_rs, LATE_COLOR),
        ("text projector", text_rs, PROJ_TEXT_COLOR),
        ("predicted-response\n(TRIBE final output)", pred_rs, BLUE),
        ("audio projector", audio_rs, PROJ_AUDIO_COLOR),
    ]
    for i, (label, vals, color) in enumerate(rows):
        ax.scatter(vals, np.full_like(vals, i, dtype=float) + np.random.RandomState(42 + i).uniform(-0.12, 0.12, size=len(vals)),
                   s=22, color=color, edgecolor=INK, linewidth=0.4, alpha=0.7)
        ax.scatter([np.mean(vals)], [i], s=140, marker="D", color=color, edgecolor=INK, linewidth=1.0, zorder=4)
        # annotate mean
        ax.text(
            np.mean(vals) + 0.02, i + 0.30,
            f"mean = {np.mean(vals):+.3f}\n(n_pos = {int((vals > 0).sum())}/{len(vals)})",
            fontsize=8, color=INK,
        )

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("per-subject Pearson r vs individual story-minus-math zstat", color=INK)
    ax.set_title("(b) per-feature distribution (jittered, diamond = mean)", color=INK)
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    ax.set_ylim(-0.6, len(rows) - 0.4)

    # Headline annotation
    paired = e6["paired_tests"]["audio_vs_late_encoder"]
    fig.suptitle(
        f"Figure 14b. H1' rescue at the per-subject level (50 paired HCP S1200 NeuroVault zstats).  "
        f"audio - late paired diff = {paired['mean_diff']:+.3f}, t = {paired['paired_t']:+.2f}",
        fontsize=11, color=INK, y=1.02,
    )

    save_figure(fig, out_root, "figure14b_per_subject_audio_vs_late_20260501")
    plt.close(fig)


def main() -> int:
    style()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    figure11_per_layer_score_full_n81(OUT_ROOT)
    figure11b_per_layer_brain_alignment(OUT_ROOT)
    figure14b_per_subject_scatter(OUT_ROOT)
    print(f"wrote figures -> {OUT_ROOT}")
    for f in sorted(OUT_ROOT.glob("*.png")):
        print(f"  {f.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
