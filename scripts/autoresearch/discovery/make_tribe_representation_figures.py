#!/usr/bin/env python3
"""Render representation-space figures for the TRIBE stimulus-discovery line.

The current local evidence contains layer-family contrast scores, not the raw
item-by-feature sidecar matrices. This script therefore renders a
representation-depth profile and family summary for HCP language, while clearly
labeling the figure as model-feature evidence rather than observed neural
activation or item-level embedding geometry.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch


FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")
DEFAULT_OUT_ROOT = FIGURE_ROOT / "representation_figures_20260428"

INK = "#172033"
MUTED = "#667085"
GRID = "#E3E8EF"
GREEN = "#177D5A"
AMBER = "#C98200"
BLUE = "#2D6F94"
RED = "#B54708"
LIGHT = "#F8FAFC"

FAMILY_COLOR = {
    "late_attn": GREEN,
    "early_attn": BLUE,
    "projectors": AMBER,
}

FAMILY_LABEL = {
    "late_attn": "late encoder attention\nlayers 10/12/14",
    "early_attn": "early encoder attention\nlayers 0/2/4",
    "projectors": "input projectors\ntext/audio",
}

FAMILY_ORDER = ["projectors", "early_attn", "late_attn"]


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 300,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 9.5,
            "xtick.labelsize": 8.2,
            "ytick.labelsize": 8.2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_layer_scores(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            layer = row["layer"]
            depth = _layer_depth(layer)
            rows.append(
                {
                    "family": row["family"],
                    "layer": layer,
                    "score": float(row["score"]),
                    "depth": depth,
                    "label": _short_layer_label(layer),
                }
            )
    return rows


def _layer_depth(layer: str) -> float:
    if layer == "projectors.text":
        return -2.0
    if layer == "projectors.audio":
        return -1.0
    match = re.search(r"encoder\.layers\.(\d+)\.1", layer)
    if not match:
        raise ValueError(f"Cannot infer layer depth from {layer!r}")
    return float(match.group(1))


def _short_layer_label(layer: str) -> str:
    if layer == "projectors.text":
        return "text\nproj"
    if layer == "projectors.audio":
        return "audio\nproj"
    match = re.search(r"encoder\.layers\.(\d+)\.1", layer)
    if match:
        return f"L{match.group(1)}"
    return layer


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_caption(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Figure 11. HCP language TRIBE representation profile",
                "",
                "Claim: The story-audio vs math-audio separation is strongest in late TRIBE encoder attention representations, not in raw audio/text projectors or early encoder layers.",
                "",
                "Source: `layer_scores.csv` containing the locked layer-family confirmatory scores for `projectors.audio`, `projectors.text`, and selected `encoder.layers.{0,2,4,10,12,14}.1` hooks.",
                "",
                "Interpretation boundary: This is item-level model-feature evidence. It is not an observed fMRI activation map, and it is not an item-level PCA/UMAP embedding because raw item-by-feature matrices are not present in the local workspace.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _family_means(rows: list[dict[str, object]]) -> dict[str, float]:
    means = {}
    for family in FAMILY_ORDER:
        values = [float(row["score"]) for row in rows if row["family"] == family]
        means[family] = float(np.mean(values))
    return means


def _draw_module_strip(ax: plt.Axes, rows: list[dict[str, object]]) -> None:
    ax.set_xlim(-2.8, 15.8)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("A  TRIBE representation hook points", loc="left", color=INK)

    blocks = [
        (-2.6, 0.35, 1.75, 0.30, "input\nprojectors", AMBER),
        (-0.2, 0.35, 5.0, 0.30, "early encoder\nattention", BLUE),
        (8.8, 0.35, 6.6, 0.30, "late encoder\nattention", GREEN),
    ]
    for x, y, w, h, label, color in blocks:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.03,rounding_size=0.06",
                facecolor=color + "16",
                edgecolor=color,
                linewidth=1.2,
            )
        )
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", color=color, fontsize=8.5, weight="bold")

    for row in rows:
        depth = float(row["depth"])
        color = FAMILY_COLOR[str(row["family"])]
        y = 0.22 if depth < 0 else 0.73
        ax.scatter(depth, y, s=70, facecolor=color, edgecolor="white", linewidth=0.8, zorder=3)
        ax.text(depth, y - 0.13 if depth < 0 else y + 0.12, str(row["label"]), ha="center", va="center", fontsize=7.4, color=INK)

    ax.annotate(
        "late blocks carry the confirmed separation",
        xy=(12.0, 0.80),
        xytext=(6.1, 0.93),
        ha="center",
        va="center",
        fontsize=8.0,
        color=GREEN,
        arrowprops={"arrowstyle": "->", "color": GREEN, "lw": 1.0},
    )


def _draw_depth_profile(ax: plt.Axes, rows: list[dict[str, object]]) -> None:
    ax.set_title("B  Contrast score across representation depth", loc="left", color=INK)
    rows_sorted = sorted(rows, key=lambda row: float(row["depth"]))
    x = [float(row["depth"]) for row in rows_sorted]
    y = [float(row["score"]) for row in rows_sorted]
    ax.plot(x, y, color="#CBD5E1", linewidth=2.0, zorder=1)
    for row in rows_sorted:
        color = FAMILY_COLOR[str(row["family"])]
        ax.scatter(float(row["depth"]), float(row["score"]), s=95, facecolor=color, edgecolor="white", linewidth=0.9, zorder=3)
        ax.text(float(row["depth"]), float(row["score"]) + 0.045, str(row["label"]).replace("\n", " "), ha="center", va="bottom", fontsize=7.3, color=INK)

    ax.set_ylabel("Representation contrast score")
    ax.set_xlabel("")
    ax.set_xticks([-2, -1, 0, 2, 4, 10, 12, 14])
    ax.set_xticklabels(["text proj", "audio proj", "L0", "L2", "L4", "L10", "L12", "L14"], rotation=28, ha="right")
    ax.set_ylim(0, 1.18)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.axvspan(9.2, 14.8, color=GREEN, alpha=0.06, zorder=0)
    ax.text(12.0, 1.10, "late encoder family", ha="center", va="center", fontsize=7.8, color=GREEN, weight="bold")


def _draw_family_summary(ax: plt.Axes, rows: list[dict[str, object]]) -> None:
    means = _family_means(rows)
    ax.set_title("C  Locked family-level effect", loc="left", color=INK)
    x = np.arange(len(FAMILY_ORDER))
    values = [means[family] for family in FAMILY_ORDER]
    colors = [FAMILY_COLOR[family] for family in FAMILY_ORDER]
    ax.bar(x, values, color=colors, width=0.56, edgecolor="white", linewidth=1.0)

    rng = np.random.default_rng(7)
    for idx, family in enumerate(FAMILY_ORDER):
        scores = [float(row["score"]) for row in rows if row["family"] == family]
        jitter = rng.uniform(-0.12, 0.12, len(scores))
        ax.scatter(np.full(len(scores), idx) + jitter, scores, s=32, color=INK, alpha=0.70, zorder=3, edgecolor="white", linewidth=0.4)
        ax.text(idx, values[idx] + 0.045, f"{values[idx]:.3f}", ha="center", va="bottom", fontsize=8.3, weight="bold", color=INK)

    delta = means["late_attn"] - means["early_attn"]
    y = max(values) + 0.20
    ax.plot([1, 1, 2, 2], [y - 0.03, y, y, y - 0.03], color=INK, lw=1.0)
    ax.text(1.5, y + 0.03, f"late - early = {delta:.3f}, p~5e-5", ha="center", va="bottom", fontsize=7.8, color=INK)

    ax.set_xticks(x)
    ax.set_xticklabels(["projectors\ntext/audio", "early attn\nL0/2/4", "late attn\nL10/12/14"])
    ax.set_ylabel("Mean score")
    ax.set_ylim(0, 1.30)
    ax.grid(axis="y", color=GRID, linewidth=0.8)


def _draw_boundary_box(ax: plt.Axes) -> None:
    ax.set_axis_off()
    ax.set_title("D  What this representation figure can and cannot show", loc="left", color=INK)
    boxes = [
        (0.04, 0.57, 0.42, 0.28, GREEN, "Supported now", "Layer-family contrast scores show\nlate encoder > early/projectors."),
        (0.54, 0.57, 0.42, 0.28, BLUE, "Not shown here", "No item-level PCA/UMAP because raw\nitem x feature matrices are not local."),
        (0.04, 0.18, 0.42, 0.28, AMBER, "Next plot if matrices arrive", "PCA/UMAP of story vs math items\nat L14/L10/L12 representations."),
        (0.54, 0.18, 0.42, 0.28, RED, "Neural boundary", "Still not subject-level observed fMRI\nor ROI activation evidence."),
    ]
    for x, y, w, h, color, title, body in boxes:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                transform=ax.transAxes,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                facecolor=color + "12",
                edgecolor=color,
                linewidth=1.2,
            )
        )
        ax.text(x + 0.03, y + h - 0.07, title, transform=ax.transAxes, ha="left", va="center", fontsize=8.8, weight="bold", color=color)
        ax.text(x + 0.03, y + h - 0.17, body, transform=ax.transAxes, ha="left", va="top", fontsize=7.5, color=MUTED, linespacing=1.25)


def figure11_representation_profile(rows: list[dict[str, object]], out_root: Path) -> None:
    style()
    fig = plt.figure(figsize=(11.0, 6.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[0.95, 1.75], hspace=0.56, wspace=0.34)
    fig.subplots_adjust(left=0.12, right=0.98, top=0.86, bottom=0.16)
    ax_strip = fig.add_subplot(gs[0, :])
    ax_profile = fig.add_subplot(gs[1, 0])
    ax_summary = fig.add_subplot(gs[1, 1])

    _draw_module_strip(ax_strip, rows)
    _draw_depth_profile(ax_profile, rows)
    _draw_family_summary(ax_summary, rows)

    fig.text(
        0.02,
        0.975,
        "Figure 11. HCP language representation profile in TRIBE",
        ha="left",
        va="top",
        fontsize=12.0,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.02,
        0.942,
        "Story-audio vs math-audio separation is strongest in late encoder attention features, not projector-level features.",
        ha="left",
        va="top",
        fontsize=8.8,
        color=MUTED,
    )
    fig.text(
        0.02,
        0.045,
        "Representation-space figure only. It summarizes locked layer scores; raw item x feature matrices are not local, so item-level PCA/UMAP is deferred. This is not observed fMRI activation.",
        ha="left",
        va="center",
        fontsize=7.4,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure11_representation_profile_20260428"
    stem = "figure11_representation_profile_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(out_dir / f"{stem}_caption.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-root", type=Path, default=FIGURE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    rows = read_layer_scores(args.figure_root / "data" / "layer_scores.csv")
    figure11_representation_profile(rows, args.out_root)
    print(f"Wrote representation Figure 11 to {args.out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
