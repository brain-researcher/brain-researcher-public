#!/usr/bin/env python3
"""Draw the manuscript Figure 1 closed-loop workflow as a deterministic schematic.

This replaces prompt-generated raster art with a controlled vector-style figure.
Outputs PNG, SVG, and PDF in manuscript/figures by default.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


PALETTE = {
    "ink": "#263238",
    "muted": "#6B7280",
    "grid": "#D6DBDF",
    "panel": "#F8FAFC",
    "before": "#B85C5C",
    "before_fill": "#F8EDED",
    "br": "#2A6F97",
    "br_fill": "#EAF4F8",
    "kg": "#4C956C",
    "kg_fill": "#ECF7EF",
    "tool": "#7B61A3",
    "tool_fill": "#F3EFFA",
    "audit": "#C77D2B",
    "audit_fill": "#FFF4E6",
    "human": "#1F4E79",
    "human_fill": "#EAF1F8",
    "evidence_fill": "#F5F7FA",
}


def add_box(
    ax,
    x,
    y,
    w,
    h,
    text,
    *,
    fc,
    ec,
    fontsize=10,
    weight="normal",
    radius=0.018,
    lw=1.4,
    wrap=20,
    z=2,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.010,rounding_size={radius}",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
        zorder=z,
    )
    ax.add_patch(patch)
    label = "\n".join(textwrap.wrap(text, width=wrap))
    ax.text(
        x + w / 2,
        y + h / 2,
        label,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=PALETTE["ink"],
        fontweight=weight,
        linespacing=1.15,
        zorder=z + 1,
    )
    return patch


def add_arrow(ax, start, end, *, color, lw=1.8, style="-|>", rad=0.0, alpha=1.0, z=1, ls="-"):
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle=style,
        mutation_scale=12,
        linewidth=lw,
        color=color,
        alpha=alpha,
        linestyle=ls,
        connectionstyle=f"arc3,rad={rad}",
        shrinkA=4,
        shrinkB=4,
        zorder=z,
    )
    ax.add_patch(arr)
    return arr


def add_human_tag(ax, x, y, label):
    add_box(
        ax,
        x,
        y,
        0.105,
        0.044,
        label,
        fc=PALETTE["human_fill"],
        ec=PALETTE["human"],
        fontsize=7.7,
        weight="bold",
        radius=0.012,
        lw=1.0,
        wrap=15,
        z=5,
    )


def draw(output_dir: Path, basename: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(16, 9), dpi=240)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # Title and subtitle.
    ax.text(
        0.040,
        0.955,
        "Brain Researcher: closed-loop neuroimaging research",
        ha="left",
        va="top",
        fontsize=18,
        fontweight="bold",
        color=PALETTE["ink"],
    )
    ax.text(
        0.040,
        0.918,
        "The contribution is not faster chat; it is a provenance-bearing research loop that links evidence, design, execution, audit, and memory.",
        ha="left",
        va="top",
        fontsize=9.2,
        color=PALETTE["muted"],
    )

    # Main panels.
    add_box(ax, 0.040, 0.115, 0.300, 0.760, "", fc="#FFFFFF", ec=PALETTE["grid"], lw=1.2, radius=0.018)
    add_box(ax, 0.370, 0.115, 0.590, 0.760, "", fc=PALETTE["panel"], ec=PALETTE["grid"], lw=1.2, radius=0.018)

    ax.text(0.065, 0.835, "Fragmented workflow", ha="left", va="center", fontsize=12, fontweight="bold", color=PALETTE["before"])
    ax.text(0.395, 0.835, "Brain Researcher closed loop", ha="left", va="center", fontsize=12, fontweight="bold", color=PALETTE["br"])

    # Left: disconnected workflow.
    before_steps = [
        "Literature search",
        "Dataset selection",
        "Analysis design",
        "Execution",
        "Robustness check",
        "Interpretation",
        "Reporting",
    ]
    bx, bw, bh = 0.075, 0.230, 0.060
    ys = [0.740, 0.650, 0.560, 0.470, 0.380, 0.290, 0.200]
    for i, (label, y) in enumerate(zip(before_steps, ys)):
        add_box(ax, bx, y, bw, bh, label, fc=PALETTE["before_fill"], ec=PALETTE["before"], fontsize=9.2, wrap=22)
        if i < len(ys) - 1:
            add_arrow(
                ax,
                (bx + bw / 2, y - 0.006),
                (bx + bw / 2, ys[i + 1] + bh + 0.006),
                color="#A8A8A8",
                lw=1.2,
                alpha=0.75,
                ls=(0, (2, 3)),
                style="-",
            )

    ax.text(
        0.065,
        0.155,
        "Evidence, assumptions, and failures often move by handoff rather than by reusable research objects.",
        ha="left",
        va="top",
        fontsize=7.9,
        color=PALETTE["muted"],
        wrap=True,
    )

    # Right: closed-loop nodes.
    nodes = {
        "question": (0.430, 0.690, 0.138, 0.070, "Question\nframing"),
        "ground": (0.628, 0.705, 0.150, 0.070, "Evidence grounding\nBR-KG"),
        "design": (0.805, 0.600, 0.118, 0.070, "Analysis\ndesign"),
        "execute": (0.760, 0.380, 0.150, 0.070, "Constrained\nexecution"),
        "audit": (0.595, 0.265, 0.155, 0.070, "Audit object\nrun bundle"),
        "memory": (0.425, 0.380, 0.150, 0.070, "Knowledge\nupdate"),
    }
    for key, (x, y, w, h, label) in nodes.items():
        if key == "ground":
            fc, ec = PALETTE["kg_fill"], PALETTE["kg"]
        elif key == "execute":
            fc, ec = PALETTE["tool_fill"], PALETTE["tool"]
        elif key == "audit":
            fc, ec = PALETTE["audit_fill"], PALETTE["audit"]
        else:
            fc, ec = PALETTE["br_fill"], PALETTE["br"]
        add_box(ax, x, y, w, h, label, fc=fc, ec=ec, fontsize=8.1, weight="bold", wrap=18)

    def center(name):
        x, y, w, h, _ = nodes[name]
        return (x + w / 2, y + h / 2)

    # Explicit route connectors. Use edge-to-edge anchors so the loop reads at
    # manuscript scale instead of depending on subtle background curves.
    loop_arrows = [
        ((0.568, 0.725), (0.628, 0.740), 0.04),
        ((0.778, 0.740), (0.805, 0.650), -0.18),
        ((0.865, 0.600), (0.835, 0.450), -0.10),
        ((0.760, 0.405), (0.750, 0.300), -0.10),
        ((0.595, 0.300), (0.575, 0.405), -0.10),
        ((0.500, 0.450), (0.500, 0.690), -0.23),
    ]
    for start, end, rad in loop_arrows:
        add_arrow(ax, start, end, color=PALETTE["br"], lw=2.0, rad=rad, z=3)

    # Central substrate and bridge.
    add_box(
        ax,
        0.575,
        0.500,
        0.170,
        0.080,
        "Scientific constraints\nand provenance",
        fc="#FFFFFF",
        ec="#3E7C59",
        fontsize=8.1,
        weight="bold",
        wrap=20,
        lw=1.5,
    )
    add_arrow(ax, (0.660, 0.580), center("ground"), color=PALETTE["kg"], lw=1.3, rad=-0.08)
    add_arrow(ax, (0.705, 0.500), center("execute"), color=PALETTE["tool"], lw=1.3, rad=0.08)

    add_box(
        ax,
        0.840,
        0.265,
        0.090,
        0.085,
        "Typed tool\nrouting",
        fc=PALETTE["tool_fill"],
        ec=PALETTE["tool"],
        fontsize=7.6,
        weight="bold",
        wrap=13,
    )
    add_arrow(ax, center("execute"), (0.840, 0.310), color=PALETTE["tool"], lw=1.5, rad=0.05)

    # Human checkpoints.
    add_human_tag(ax, 0.405, 0.770, "human\nframes")
    add_human_tag(ax, 0.830, 0.685, "plan\napproval")
    add_human_tag(ax, 0.770, 0.235, "scientific\nreview")
    add_human_tag(ax, 0.405, 0.470, "final\ninterpretation")

    # Evidence lanes.
    lane_y = 0.145
    lane_h = 0.055
    add_box(
        ax,
        0.405,
        lane_y,
        0.245,
        lane_h,
        "Evidence lane A: flagship science result",
        fc=PALETTE["evidence_fill"],
        ec="#8795A1",
        fontsize=8.8,
        weight="bold",
        wrap=38,
    )
    add_box(
        ax,
        0.675,
        lane_y,
        0.245,
        lane_h,
        "Evidence lane B: collaborator cohort",
        fc=PALETTE["evidence_fill"],
        ec="#8795A1",
        fontsize=8.8,
        weight="bold",
        wrap=36,
    )
    add_arrow(ax, center("audit"), (0.525, lane_y + lane_h), color=PALETTE["audit"], lw=1.4, rad=0.08)
    add_arrow(ax, center("audit"), (0.800, lane_y + lane_h), color=PALETTE["audit"], lw=1.4, rad=-0.10)

    ax.text(
        0.405,
        0.222,
        "Outputs are reusable: plans, constraints, tool calls, traces, review verdicts, and memory writebacks.",
        ha="left",
        va="center",
        fontsize=8.0,
        color=PALETTE["muted"],
    )

    png = output_dir / f"{basename}.png"
    svg = output_dir / f"{basename}.svg"
    pdf = output_dir / f"{basename}.pdf"
    fig.savefig(png, dpi=240)
    fig.savefig(svg)
    fig.savefig(pdf)
    plt.close(fig)

    print(png)
    print(svg)
    print(pdf)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="manuscript/figures")
    parser.add_argument("--basename", default="story_fig1_graphical_abstract_closed_loop")
    args = parser.parse_args()
    draw(Path(args.output_dir), args.basename)


if __name__ == "__main__":
    main()
