#!/usr/bin/env python3
"""Regenerate Figure 8.4 for the bounded autoresearch case report.

The figure is intentionally schematic: it shows the true research trajectory
as a compact evidence map rather than a generic agent loop.
"""

from __future__ import annotations

from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch


ROOT = Path("/data/brain_researcher/research/predictive/project")
OUT_PNG = ROOT / "figures" / "fig02_true_autoresearch_trajectory.png"
OUT_PDF = ROOT / "figures" / "fig02_true_autoresearch_trajectory.pdf"


COLORS = {
    "blue": "#1f77b4",
    "blue_fill": "#e8f2fb",
    "green": "#2ca02c",
    "green_fill": "#e9f7ea",
    "orange": "#ff7f0e",
    "orange_fill": "#fff1df",
    "red": "#d62728",
    "red_fill": "#fde7e5",
    "gray": "#7f7f7f",
    "gray_fill": "#f3f3f3",
    "teal": "#17becf",
    "teal_fill": "#e8f7fa",
    "dark": "#222222",
    "light_line": "#c9c9c9",
}


def add_track(ax, points, *, color, lw=4.0, zorder=1, dashed=False):
    xs, ys = zip(*points)
    ax.plot(
        xs,
        ys,
        color=color,
        lw=lw,
        solid_capstyle="round",
        zorder=zorder,
        linestyle=(0, (5, 4)) if dashed else "solid",
    )


def add_arrow(ax, start, end, *, color, lw=2.0, rad=0.0, dashed=False):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=lw,
            color=color,
            shrinkA=7,
            shrinkB=7,
            connectionstyle=f"arc3,rad={rad}",
            linestyle=(0, (5, 4)) if dashed else "solid",
            zorder=3,
        )
    )


def add_node(
    ax,
    x,
    y,
    title,
    detail="",
    *,
    color,
    fill,
    width=1.30,
    height=0.58,
    fontsize=8.0,
    dashed=False,
    title_weight="bold",
):
    box = FancyBboxPatch(
        (x - width / 2, y - height / 2),
        width,
        height,
        boxstyle="round,pad=0.055,rounding_size=0.08",
        facecolor=fill,
        edgecolor=color,
        linewidth=1.6,
        linestyle=(0, (5, 4)) if dashed else "solid",
        zorder=5,
    )
    ax.add_patch(box)
    if detail:
        ax.text(
            x,
            y + height * 0.16,
            title,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight=title_weight,
            color=COLORS["dark"],
            zorder=6,
        )
        ax.text(
            x,
            y - height * 0.17,
            detail,
            ha="center",
            va="center",
            fontsize=fontsize - 0.5,
            color=COLORS["dark"],
            linespacing=1.05,
            zorder=6,
        )
    else:
        ax.text(
            x,
            y,
            title,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight=title_weight,
            color=COLORS["dark"],
            linespacing=1.05,
            zorder=6,
        )
    return box


def add_station(ax, x, y, *, color, fill="white", radius=0.06):
    ax.add_patch(
        Circle(
            (x, y),
            radius=radius,
            facecolor=fill,
            edgecolor=color,
            linewidth=1.7,
            zorder=4,
        )
    )


def add_lane_label(ax, y, label, color):
    ax.text(
        0.35,
        y,
        label,
        ha="left",
        va="center",
        fontsize=9.4,
        fontweight="bold",
        color=color,
    )


def add_pill(ax, x, y, text, *, width=1.18):
    pill = FancyBboxPatch(
        (x - width / 2, y - 0.16),
        width,
        0.32,
        boxstyle="round,pad=0.025,rounding_size=0.16",
        facecolor=COLORS["gray_fill"],
        edgecolor="#9a9a9a",
        linewidth=1.0,
        zorder=5,
    )
    ax.add_patch(pill)
    ax.text(x, y, text, ha="center", va="center", fontsize=7.1, color="#333333", zorder=6)


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    fig, ax = plt.subplots(figsize=(15.6, 8.4), dpi=300)
    ax.set_xlim(0, 15.6)
    ax.set_ylim(0, 8.2)
    ax.axis("off")

    # Title block.
    ax.text(
        0.35,
        8.00,
        "True autoresearch trajectory",
        ha="left",
        va="top",
        fontsize=17,
        fontweight="bold",
        color=COLORS["dark"],
    )
    ax.text(
        0.35,
        7.66,
        "Historical breadth shaped the search; validation and support-boundary work determine the final claim.",
        ha="left",
        va="top",
        fontsize=10.5,
        color="#444444",
    )

    # Light lane backgrounds.
    lane_specs = [
        (6.45, 0.76, "#f7fbff", "Validation branch"),
        (5.08, 0.88, "#f7fbff", "Parent trunk"),
        (3.72, 0.86, "#f7fff7", "Confirmatory / sensitivity"),
        (2.08, 0.86, "#fafafa", "Historical breadth"),
    ]
    for y, h, face, _ in lane_specs:
        ax.add_patch(
            FancyBboxPatch(
                (0.18, y - h / 2),
                15.05,
                h,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                linewidth=0,
                facecolor=face,
                zorder=0,
            )
        )

    add_lane_label(ax, 6.78, "Self-correction", COLORS["red"])
    add_lane_label(ax, 5.42, "Authoritative parent trunk", COLORS["blue"])
    add_lane_label(ax, 4.05, "Internal statistical support", COLORS["green"])
    add_lane_label(ax, 2.70, "Historical exploration breadth", COLORS["gray"])

    # Parent trunk as a subway line.
    main_y = 5.05
    main_x = [1.35, 3.00, 4.70, 6.55, 8.20]
    add_track(ax, [(x, main_y) for x in main_x], color=COLORS["blue"], lw=4.5)
    for x in main_x:
        add_station(ax, x, main_y, color=COLORS["blue"])

    add_node(ax, 1.35, main_y, "Baseline", "replication", color=COLORS["blue"], fill=COLORS["blue_fill"], width=1.1)
    add_node(
        ax,
        3.00,
        main_y,
        "Path A best",
        "r=0.151\n4/5 hit_mean",
        color=COLORS["blue"],
        fill=COLORS["blue_fill"],
        width=1.25,
    )
    add_node(
        ax,
        4.70,
        main_y,
        "Path B routing",
        "component-specific",
        color=COLORS["blue"],
        fill=COLORS["blue_fill"],
        width=1.34,
    )
    add_node(
        ax,
        6.55,
        main_y,
        "Parent closeout",
        "5/5 hit_mean\n0/5 hit_best",
        color=COLORS["blue"],
        fill=COLORS["blue_fill"],
        width=1.36,
    )
    add_node(
        ax,
        8.20,
        main_y,
        "Frozen Path B",
        "claim candidate",
        color=COLORS["teal"],
        fill=COLORS["teal_fill"],
        width=1.28,
    )

    # Validation branch.
    val_y = 6.42
    val_points = [(6.55, main_y + 0.34), (7.05, val_y), (8.45, val_y), (9.95, val_y), (11.15, val_y)]
    add_track(ax, val_points, color=COLORS["orange"], lw=3.8)
    add_arrow(ax, (10.55, val_y), (11.02, val_y), color=COLORS["red"], lw=2.2)
    add_node(ax, 7.05, val_y, "KG sequel", "prior-guided", color=COLORS["orange"], fill=COLORS["orange_fill"], width=1.05)
    add_node(
        ax,
        8.45,
        val_y,
        "wPLI / IDU",
        "tempting lead",
        color=COLORS["orange"],
        fill=COLORS["orange_fill"],
        width=1.14,
    )
    add_node(
        ax,
        9.95,
        val_y,
        "Validation",
        "1000 permutations",
        color=COLORS["orange"],
        fill=COLORS["orange_fill"],
        width=1.26,
    )
    add_node(
        ax,
        11.15,
        val_y,
        "Lead rejected",
        "p=0.1998",
        color=COLORS["red"],
        fill=COLORS["red_fill"],
        width=1.22,
    )

    # Confirmatory/sensitivity branch.
    conf_y = 3.72
    conf_points = [(8.20, main_y - 0.34), (8.75, conf_y), (10.15, conf_y), (11.80, conf_y)]
    add_track(ax, conf_points, color=COLORS["green"], lw=4.0)
    add_node(
        ax,
        8.75,
        conf_y,
        "Family-block null",
        "n_perm=1000",
        color=COLORS["green"],
        fill=COLORS["green_fill"],
        width=1.34,
    )
    add_node(
        ax,
        10.15,
        conf_y,
        "Aggregate support",
        "p=0.000999",
        color=COLORS["green"],
        fill=COLORS["green_fill"],
        width=1.38,
    )
    add_node(
        ax,
        11.55,
        conf_y,
        "Sensitivity verdict",
        "COG/TOB/PE retained\nMH caveated; IDU downgraded",
        color=COLORS["orange"],
        fill=COLORS["orange_fill"],
        width=1.66,
        height=0.70,
        fontsize=7.5,
    )

    # Historical breadth as compact non-authoritative pills.
    hist_y1, hist_y2 = 2.22, 1.68
    add_track(ax, [(1.10, hist_y1), (5.05, hist_y1), (6.15, 4.55)], color=COLORS["gray"], lw=2.6, dashed=True)
    add_pill(ax, 1.20, hist_y1, "proto traces\n47 rows", width=1.18)
    add_pill(ax, 2.45, hist_y1, "exploration\n40 rows", width=1.18)
    add_pill(ax, 3.70, hist_y1, "model scaling\n22 rows", width=1.20)
    add_pill(ax, 4.95, hist_y1, "data scaling\n15 rows", width=1.18)
    add_pill(ax, 6.15, hist_y2, "metric redundancy", width=1.22)
    add_pill(ax, 7.38, hist_y2, "foundation transfer\nblocked", width=1.30)
    add_pill(ax, 8.70, hist_y2, "generalization", width=1.16)
    add_pill(ax, 9.92, hist_y2, "blind replication", width=1.20)
    add_pill(ax, 11.18, hist_y2, "PE disambiguation", width=1.30)
    add_pill(ax, 12.48, hist_y2, "older KG prior", width=1.16)

    ax.text(
        0.45,
        1.18,
        "Non-authoritative lines are not discarded: they constrain what was tried, what failed, and where the final claim boundary should sit.",
        ha="left",
        va="center",
        fontsize=9.4,
        color="#444444",
    )

    # Support boundary at right.
    boundary = FancyBboxPatch(
        (12.95, 3.08),
        2.26,
        2.72,
        boxstyle="round,pad=0.08,rounding_size=0.08",
        facecolor="#ffffff",
        edgecolor="#333333",
        linewidth=1.3,
        zorder=2,
    )
    ax.add_patch(boundary)
    ax.text(
        14.08,
        5.52,
        "Current support boundary",
        ha="center",
        va="center",
        fontsize=9.0,
        fontweight="bold",
        color=COLORS["dark"],
        zorder=6,
    )
    add_node(
        ax,
        14.08,
        4.85,
        "Inside",
        "frozen-pipeline\ninternal support",
        color=COLORS["green"],
        fill=COLORS["green_fill"],
        width=1.55,
        height=0.56,
        fontsize=7.5,
    )
    add_node(
        ax,
        14.08,
        4.06,
        "Pending / blocked",
        "post-selection\nexternal cohorts\nGSR / alt-parc / motion",
        color=COLORS["gray"],
        fill=COLORS["gray_fill"],
        width=1.66,
        height=0.82,
        fontsize=7.2,
        dashed=True,
    )
    add_arrow(ax, (12.20, conf_y), (12.95, 4.45), color=COLORS["green"], lw=1.4, rad=-0.12)

    # Ledger accounting footer.
    footer = FancyBboxPatch(
        (0.35, 0.36),
        14.85,
        0.43,
        boxstyle="round,pad=0.04,rounding_size=0.05",
        facecolor="#f7f7f7",
        edgecolor="none",
        zorder=0,
    )
    ax.add_patch(footer)
    ax.text(
        0.55,
        0.575,
        "Ledger accounting: 18 workspaces / 248 rows; the current branch carries the claim, while historical/scaffold lines define what was tried or blocked.",
        ha="left",
        va="center",
        fontsize=9.4,
        fontweight="bold",
        color=COLORS["dark"],
    )

    # Small date axis.
    axis_y = 0.16
    ax.plot([0.75, 13.65], [axis_y, axis_y], color=COLORS["light_line"], lw=1.2)
    for x, label in [
        (1.15, "Apr 13"),
        (3.25, "Apr 15"),
        (4.85, "Apr 17"),
        (6.55, "Apr 18"),
        (8.20, "Apr 22"),
        (10.15, "Apr 23"),
        (12.30, "Apr 25-26"),
    ]:
        ax.plot([x, x], [axis_y - 0.04, axis_y + 0.04], color="#999999", lw=1.0)
        ax.text(x, axis_y - 0.09, label, ha="center", va="top", fontsize=7.3, color="#555555")

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight", pad_inches=0.05)
    fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.05)
    print(OUT_PNG)
    print(OUT_PDF)


if __name__ == "__main__":
    main()
