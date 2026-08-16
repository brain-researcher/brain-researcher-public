#!/usr/bin/env python3
"""Redraw Figure 6 from the public TRIBE speech–tools derived tables.

This is deliberately a *derived-data replay*: it validates and redraws the
frozen summary tables shipped with this pack.  It does not load audio,
representations, model checkpoints, or any private research archive.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


PACK_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PACK_ROOT / "source"
STEM = "figure6_tribe_speech_tools"

INK = "#22292F"
MUTED = "#667179"
GRID = "#D8DEE0"
PALE_TEAL = "#E8F4F1"
LIGHT_GRAY = "#C3CBCE"
NAVY = "#244E5A"
AMBER = "#E89C2B"
TEAL = "#2A9D8F"
VIOLET = "#7563B8"

X_LIM = (-1.12, 0.30)
Y_LIM = (-1.03, 1.06)
X_LABEL = "Normalized separation change, ΔS"
Y_LABEL = "Late directional alignment, C"

COLLECTION_COLORS = {
    "AudioSet": NAVY,
    "BBC": AMBER,
    "FreeSound": TEAL,
    "SoundBible": VIOLET,
}
PANEL_MARKERS = {"1": "o", "2": "s", "3": "^"}
NEW_MARKERS = {"DCASE": "o", "SINGA:PURA": "s", "SONYC-UST": "^", "STARSS23": "D"}


def read_csv_rows(name: str) -> list[dict[str, str]]:
    with (SOURCE_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(name: str) -> dict[str, Any]:
    return json.loads((SOURCE_DIR / name).read_text(encoding="utf-8"))


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _validate_rows(
    discovery: list[dict[str, str]],
    selection: list[dict[str, str]],
    recurring: list[dict[str, str]],
    panel_summary: list[dict[str, str]],
    new_collections: list[dict[str, str]],
    new_summary: dict[str, Any],
) -> None:
    """Fail before rendering if the public summary is incomplete or altered."""

    if len(discovery) != 15:
        raise ValueError("Expected all 15 open-screen sound-category pairs")
    if [int(row["rank"]) for row in discovery] != list(range(1, 16)):
        raise ValueError("Discovery ranks must be the complete 1--15 sequence")
    if len(selection) != 8:
        raise ValueError("Expected four exploratory folds for each of two contrasts")
    if len(recurring) != 12 or len(panel_summary) != 3:
        raise ValueError("Expected 12 recurring cells and three panel summaries")
    if len(new_collections) != 4:
        raise ValueError("Expected four new-collection cells")
    if new_summary.get("primary_endpoint_status") != "not_supported":
        raise ValueError("Unexpected frozen new-collection primary-endpoint status")
    if new_summary.get("trajectory_outcome") != "inconclusive_or_conflicting":
        raise ValueError("Unexpected frozen new-collection trajectory outcome")


def load_data() -> dict[str, Any]:
    """Load the public-safe, frozen source tables used by the figure."""

    discovery = read_csv_rows("discovery_pairs.csv")
    selection = read_csv_rows("selection_diagnostic.csv")
    recurring = read_csv_rows("recurring_cells.csv")
    panel_summary = read_csv_rows("recurring_panel_summary.csv")
    new_collections = read_csv_rows("new_collection_cells.csv")
    new_summary = read_json("new_collection_summary.json")
    protocol = read_json("frozen_protocol.json")
    _validate_rows(
        discovery, selection, recurring, panel_summary, new_collections, new_summary
    )
    return {
        "discovery": discovery,
        "selection": selection,
        "recurring": recurring,
        "panel_summary": panel_summary,
        "new_collections": new_collections,
        "new_summary": new_summary,
        "protocol": protocol,
    }


def configure_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.0,
            "axes.titlesize": 8.1,
            "axes.labelsize": 7.0,
            "xtick.labelsize": 6.2,
            "ytick.labelsize": 6.2,
            "legend.fontsize": 5.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "axes.unicode_minus": False,
        }
    )


def clean_axes(ax: plt.Axes, *, show_left: bool = True) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_visible(show_left)
    ax.spines["bottom"].set_color(MUTED)
    if show_left:
        ax.spines["left"].set_color(MUTED)
    ax.tick_params(length=2.4, pad=2, color=MUTED)


def phase_axes(ax: plt.Axes, *, show_ylabel: bool) -> None:
    ax.add_patch(
        Rectangle(
            (X_LIM[0], 0),
            -X_LIM[0],
            Y_LIM[1],
            facecolor=PALE_TEAL,
            edgecolor="none",
            zorder=0,
        )
    )
    ax.axvline(0, color=INK, linewidth=0.7, zorder=1)
    ax.axhline(0, color=INK, linewidth=0.7, zorder=1)
    ax.grid(color=GRID, linewidth=0.45, zorder=0)
    ax.set_xlim(*X_LIM)
    ax.set_ylim(*Y_LIM)
    ax.set_xticks([-1.0, -0.5, 0.0])
    ax.set_yticks([-1.0, -0.5, 0.0, 0.5, 1.0])
    ax.set_xlabel(X_LABEL, labelpad=2)
    ax.set_ylabel(Y_LABEL if show_ylabel else "", labelpad=2)
    clean_axes(ax)


def panel_heading(
    ax: plt.Axes, label: str, title: str, *, fontsize: float = 8.1
) -> None:
    ax.set_title(
        f"{label}  {title}",
        loc="left",
        fontsize=fontsize,
        fontweight="bold",
        color=INK,
        pad=5,
    )


def draw_open_screen(ax: plt.Axes, rows: list[dict[str, str]]) -> None:
    ordered = sorted(rows, key=lambda row: int(row["rank"]))
    positions = list(range(len(ordered)))
    ax.axvline(0, color=INK, linewidth=0.7, zorder=1)
    ax.grid(axis="x", color=GRID, linewidth=0.45, zorder=0)
    for position, row in zip(positions, ordered):
        value = _float(row, "delta_auc")
        contrast = row["contrast_id"]
        color, face, edge, size = LIGHT_GRAY, LIGHT_GRAY, LIGHT_GRAY, 18
        if contrast == "tools_vs_voice":
            color, face, edge, size = NAVY, "white", NAVY, 34
        elif contrast == "speech_vs_tools":
            color, face, edge, size = AMBER, AMBER, INK, 38
        elif int(row["rank"]) == 2:
            color, face, edge, size = MUTED, "white", MUTED, 25
        ax.hlines(position, min(value, 0), max(value, 0), color=color, linewidth=0.9, zorder=2)
        ax.scatter(value, position, s=size, facecolor=face, edgecolor=edge, linewidth=0.8, zorder=3)
        ax.text(-0.57, position, row["display_label"], fontsize=5.35, color=INK, ha="left", va="center")
    ax.set_xlim(-0.585, 0.20)
    ax.set_ylim(len(ordered) - 0.35, -0.65)
    ax.set_xticks([-0.4, -0.2, 0.0, 0.2])
    ax.set_yticks([])
    ax.set_xlabel("Change in category distinguishability\n(late − early)", labelpad=2)
    clean_axes(ax, show_left=False)
    panel_heading(ax, "A", "Open discovery and exploratory selection")


def draw_selection(
    ax: plt.Axes,
    rows: list[dict[str, str]],
    contrast_id: str,
    title: str,
    color: str,
    *,
    show_xlabel: bool,
) -> None:
    phase_axes(ax, show_ylabel=False)
    ax.set_ylabel("")
    if not show_xlabel:
        ax.set_xlabel("")
        ax.tick_params(labelbottom=False)
    points = [row for row in rows if row["contrast_id"] == contrast_id]
    for index, row in enumerate(points, start=1):
        x = _float(row, "delta_s")
        y = _float(row, "late_directional_alignment_c")
        ax.scatter(x, y, s=31, facecolor=color, edgecolor="white", linewidth=0.55, zorder=3)
        ax.text(x + 0.035, y + 0.05, str(index), fontsize=5.0, color=color, fontweight="bold")
    ax.set_title(title, loc="left", fontsize=6.7, color=color, fontweight="bold", pad=3)


def draw_recurring(ax: plt.Axes, rows: list[dict[str, str]]) -> None:
    phase_axes(ax, show_ylabel=True)
    panel_heading(ax, "B", "Prospective new-item geometry")
    for row in rows:
        collection = row["collection"]
        ax.scatter(
            _float(row, "delta_s"),
            _float(row, "late_directional_alignment_c"),
            s=34,
            marker=PANEL_MARKERS[row["panel"]],
            facecolor=COLLECTION_COLORS[collection],
            edgecolor=COLLECTION_COLORS[collection],
            linewidth=0.55,
            zorder=3,
        )
    collection_handles = [
        Line2D([0], [0], marker="o", linestyle="none", markerfacecolor=color, markeredgecolor="white", markersize=4.8, label=name)
        for name, color in COLLECTION_COLORS.items()
    ]
    panel_handles = [
        Line2D([0], [0], marker=marker, linestyle="none", markerfacecolor="white", markeredgecolor=INK, markersize=4.6, label=f"Panel {panel}")
        for panel, marker in PANEL_MARKERS.items()
    ]
    first_legend = ax.legend(
        handles=collection_handles,
        loc="lower left",
        bbox_to_anchor=(0.01, 0.18),
        ncol=2,
        frameon=False,
        handletextpad=0.25,
        columnspacing=0.65,
        borderaxespad=0,
    )
    ax.add_artist(first_legend)
    ax.legend(
        handles=panel_handles,
        loc="lower left",
        bbox_to_anchor=(0.01, 0.04),
        ncol=3,
        frameon=False,
        handletextpad=0.25,
        columnspacing=0.55,
        borderaxespad=0,
    )


def draw_panel_means(ax: plt.Axes, rows: list[dict[str, str]]) -> None:
    ordered = sorted(rows, key=lambda row: int(row["panel"]))
    y_positions = list(reversed(range(len(ordered))))
    ax.axvline(0, color=INK, linewidth=0.7, zorder=1)
    ax.grid(axis="x", color=GRID, linewidth=0.45, zorder=0)
    for y, row in zip(y_positions, ordered):
        value = _float(row, "aggregate_delta_s")
        ax.scatter(value, y, s=38, marker="D", facecolor=TEAL, edgecolor=INK, linewidth=0.6, zorder=3)
    ax.set_xlim(-1.05, 0.20)
    ax.set_ylim(-0.55, 2.65)
    ax.set_xticks([-1.0, -0.5, 0.0])
    ax.set_yticks(y_positions, [f"Panel {row['panel']}" for row in ordered])
    ax.set_xlabel("Mean ΔS", labelpad=2)
    ax.set_title("Panel means", loc="left", fontsize=6.6, color=MUTED, fontweight="bold", pad=5)
    clean_axes(ax, show_left=False)
    ax.tick_params(axis="y", length=0, pad=2)


def draw_new_collections(ax: plt.Axes, rows: list[dict[str, str]]) -> None:
    phase_axes(ax, show_ylabel=False)
    panel_heading(ax, "C", "Extension to four new collections", fontsize=7.0)
    offsets = {
        "DCASE": (-0.24, 0.08),
        "SINGA:PURA": (-0.31, -0.20),
        "SONYC-UST": (-0.39, 0.10),
        "STARSS23": (-0.28, 0.17),
    }
    for row in rows:
        collection = row["collection"]
        x = _float(row, "delta_s")
        y = _float(row, "late_directional_alignment_c")
        ax.scatter(x, y, s=38, marker=NEW_MARKERS[collection], facecolor="white", edgecolor=MUTED, linewidth=1.1, zorder=3)
        dx, dy = offsets[collection]
        ax.annotate(
            collection,
            xy=(x, y),
            xytext=(x + dx, y + dy),
            fontsize=4.9,
            color=MUTED,
            ha="left",
            va="center",
            arrowprops={"arrowstyle": "-", "color": LIGHT_GRAY, "linewidth": 0.55},
        )


def render(output_dir: Path) -> tuple[Path, Path, Path]:
    """Render vector and raster Figure 6 outputs into ``output_dir``."""

    data = load_data()
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_style()
    fig = plt.figure(figsize=(6.30, 5.65), facecolor="white")
    outer = fig.add_gridspec(
        2,
        1,
        height_ratios=[2.3, 2.15],
        left=0.055,
        right=0.985,
        top=0.95,
        bottom=0.105,
        hspace=0.42,
    )
    top = outer[0, 0].subgridspec(1, 2, width_ratios=[1.50, 1.00], wspace=0.27)
    ax_screen = fig.add_subplot(top[0, 0])
    diag = top[0, 1].subgridspec(2, 1, hspace=0.40)
    ax_tools = fig.add_subplot(diag[0, 0])
    ax_speech = fig.add_subplot(diag[1, 0])
    ax_diag_label = fig.add_subplot(top[0, 1], frameon=False)
    ax_diag_label.set_xticks([])
    ax_diag_label.set_yticks([])
    ax_diag_label.patch.set_visible(False)
    ax_diag_label.set_ylabel(Y_LABEL, labelpad=18)
    lower = outer[1, 0].subgridspec(1, 2, width_ratios=[1.55, 0.96], wspace=0.30)
    recurring = lower[0, 0].subgridspec(1, 2, width_ratios=[3.0, 1.05], wspace=0.14)
    ax_recurring = fig.add_subplot(recurring[0, 0])
    ax_means = fig.add_subplot(recurring[0, 1])
    ax_new = fig.add_subplot(lower[0, 1])

    draw_open_screen(ax_screen, data["discovery"])
    draw_selection(ax_tools, data["selection"], "tools_vs_voice", "Tools–Voice · ranked #1", NAVY, show_xlabel=False)
    draw_selection(ax_speech, data["selection"], "speech_vs_tools", "Speech–Tools · adopted target", AMBER, show_xlabel=True)
    draw_recurring(ax_recurring, data["recurring"])
    draw_panel_means(ax_means, data["panel_summary"])
    draw_new_collections(ax_new, data["new_collections"])

    paths = tuple(output_dir / f"{STEM}.{extension}" for extension in ("pdf", "svg", "png"))
    for path in paths:
        fig.savefig(path, dpi=300, facecolor="white")
    plt.close(fig)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory for figure6_tribe_speech_tools.{pdf,svg,png}.",
    )
    args = parser.parse_args()
    for path in render(args.output_dir):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
