#!/usr/bin/env python
"""Generate Fig 5 — UC3: ParadigmCraft (Experiment Design).

This is a schematic figure intended for papers/slides, illustrating how retrieved
knowledge can be translated into experimental design decisions.

Panels:
  (a) Input: competing hypotheses + constraints
  (b) Candidate designs (top-3)
  (c) Scorecard (5 dimensions)
  (d) Recommended design + diverging predictions + minimal analysis skeleton

Default output:
  - docs/figures/fig5_paradigmcraft.svg

Run:
  python scripts/plot_fig5_paradigmcraft.py
  python scripts/plot_fig5_paradigmcraft.py --png
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

BLUE: Final[str] = "#1f77b4"
ORANGE: Final[str] = "#ff7f0e"
TEXT_DARK: Final[str] = "#1b1b1b"
TEXT_MUTED: Final[str] = "#555555"
BORDER: Final[str] = "#c9c9c9"
BG_SOFT: Final[str] = "#f7f7f7"
BG_PANEL: Final[str] = "#ffffff"


@dataclass(frozen=True)
class Candidate:
    key: str
    title: str
    subtitle: str
    template_type: str
    template_color: str


@dataclass(frozen=True)
class Cell:
    score: float
    evidence: str
    evidence_id: int


def _set_rcparams() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "svg.fonttype": "none",  # keep text as text in SVG
        }
    )


def _round_box(
    ax,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    fc: str = BG_SOFT,
    ec: str = BORDER,
    lw: float = 1.0,
    pad: float = 0.012,
    rounding: float = 0.02,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad={pad},rounding_size={rounding}",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(patch)
    return patch


def _panel_label(ax, label: str, title: str) -> None:
    ax.text(
        0.0,
        1.02,
        f"({label}) {title}",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=12,
        fontweight="bold",
        color=TEXT_DARK,
    )


def _wrap(s: str, width: int) -> str:
    words = s.split()
    lines: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur_len + add > width:
            lines.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


def _draw_input(ax) -> None:
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    _panel_label(ax, "a", "Input")

    _round_box(ax, x=0.02, y=0.60, w=0.96, h=0.30, fc=BG_PANEL, ec=BORDER)
    ax.text(
        0.05,
        0.86,
        "Competing hypotheses",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_MUTED,
    )

    _round_box(ax, x=0.05, y=0.70, w=0.90, h=0.13, fc="#eef5ff", ec=BLUE, lw=1.2)
    ax.text(
        0.07,
        0.795,
        "H1 (blue):",
        ha="left",
        va="center",
        fontsize=10,
        fontweight="bold",
        color=BLUE,
    )
    ax.text(
        0.22,
        0.795,
        "Performance variability driven by arousal fluctuations",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_DARK,
    )

    _round_box(ax, x=0.05, y=0.63, w=0.90, h=0.13, fc="#fff3e6", ec=ORANGE, lw=1.2)
    ax.text(
        0.07,
        0.705,
        "H2 (orange):",
        ha="left",
        va="center",
        fontsize=10,
        fontweight="bold",
        color=ORANGE,
    )
    ax.text(
        0.25,
        0.705,
        "…driven by executive control lapses",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_DARK,
    )

    _round_box(ax, x=0.02, y=0.07, w=0.96, h=0.46, fc=BG_PANEL, ec=BORDER)
    ax.text(
        0.05,
        0.49,
        "Constraints",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_MUTED,
    )
    constraints = [
        "human participants",
        "fMRI (3T)",
        "≤ 45 min total",
        "healthy young adults",
    ]
    y = 0.41
    for c in constraints:
        ax.text(0.07, y, f"• {c}", ha="left", va="center", fontsize=10, color=TEXT_DARK)
        y -= 0.09


def _draw_candidates(ax, candidates: list[Candidate]) -> None:
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    _panel_label(ax, "b", "Candidate Designs (Top-3)")

    card_w = 0.96
    card_h = 0.25
    x0 = 0.02
    y0 = 0.68
    gap = 0.06

    for i, cand in enumerate(candidates):
        y = y0 - i * (card_h + gap)
        _round_box(ax, x=x0, y=y, w=card_w, h=card_h, fc=BG_PANEL, ec=BORDER, lw=1.0)
        ax.add_patch(
            Rectangle(
                (x0 + 0.01, y + 0.02),
                0.02,
                card_h - 0.04,
                facecolor=cand.template_color,
                edgecolor="none",
            )
        )
        ax.text(
            x0 + 0.05,
            y + card_h - 0.07,
            cand.key,
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=TEXT_DARK,
        )
        ax.text(
            x0 + 0.12,
            y + card_h - 0.07,
            cand.title,
            ha="left",
            va="center",
            fontsize=10,
            color=TEXT_DARK,
        )
        ax.text(
            x0 + 0.12,
            y + card_h - 0.14,
            cand.subtitle,
            ha="left",
            va="center",
            fontsize=9,
            color=TEXT_MUTED,
        )

        pill_w = 0.35
        pill_h = 0.07
        pill_x = x0 + card_w - pill_w - 0.03
        pill_y = y + card_h - pill_h - 0.05
        _round_box(
            ax,
            x=pill_x,
            y=pill_y,
            w=pill_w,
            h=pill_h,
            fc="#f0f0f0",
            ec="none",
            lw=0.0,
            pad=0.01,
            rounding=0.03,
        )
        ax.text(
            pill_x + pill_w / 2,
            pill_y + pill_h / 2,
            cand.template_type,
            ha="center",
            va="center",
            fontsize=8.5,
            color=TEXT_MUTED,
        )


def _draw_scorecard(
    ax, *, dims: list[str], rows: list[Candidate], table: dict[str, dict[str, Cell]]
) -> None:
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    _panel_label(ax, "c", "Scorecard")

    means: dict[str, float] = {}
    for r in rows:
        vals = [table[r.key][d].score for d in dims]
        means[r.key] = sum(vals) / max(1, len(vals))
    winner = max(means.items(), key=lambda kv: kv[1])[0]

    x0, y0, w, h = 0.02, 0.06, 0.96, 0.88
    header_h = 0.17
    body_h = h - header_h
    row_h = body_h / len(rows)
    col_widths = [0.20] + [0.80 / len(dims)] * len(dims)

    _round_box(ax, x=x0, y=y0, w=w, h=h, fc=BG_PANEL, ec=BORDER, lw=1.0, rounding=0.02)

    cx = x0
    cy = y0 + h - header_h
    for j, cw in enumerate(col_widths):
        ax.add_patch(
            Rectangle(
                (cx, cy),
                cw * w,
                header_h,
                facecolor="#f2f2f2",
                edgecolor=BORDER,
                linewidth=1.0,
            )
        )
        label = "Candidate" if j == 0 else dims[j - 1]
        ax.text(
            cx + (cw * w) / 2,
            cy + header_h / 2,
            _wrap(label, 16),
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color=TEXT_DARK,
        )
        cx += cw * w

    for i, r in enumerate(rows):
        row_y = y0 + h - header_h - (i + 1) * row_h

        if r.key == winner:
            ax.add_patch(
                Rectangle(
                    (x0, row_y),
                    w,
                    row_h,
                    facecolor="none",
                    edgecolor="#000000",
                    linewidth=2.2,
                )
            )

        cx = x0
        ax.add_patch(
            Rectangle(
                (cx, row_y),
                col_widths[0] * w,
                row_h,
                facecolor="#fbfbfb",
                edgecolor=BORDER,
                linewidth=1.0,
            )
        )
        ax.text(
            cx + 0.012,
            row_y + row_h / 2,
            r.key,
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=TEXT_DARK,
        )
        ax.text(
            cx + 0.085,
            row_y + row_h / 2,
            _wrap(r.title, 16),
            ha="left",
            va="center",
            fontsize=8.7,
            color=TEXT_MUTED,
        )
        cx += col_widths[0] * w

        for j, d in enumerate(dims):
            cell = table[r.key][d]
            cw = col_widths[j + 1] * w
            shade = 1.0 - min(max((cell.score - 1.0) / 4.0, 0.0), 1.0) * 0.22
            face = (shade, shade, shade)
            ax.add_patch(
                Rectangle(
                    (cx, row_y),
                    cw,
                    row_h,
                    facecolor=face,
                    edgecolor=BORDER,
                    linewidth=1.0,
                )
            )
            ax.text(
                cx + 0.012,
                row_y + row_h / 2,
                f"{cell.score:.1f}  {cell.evidence}",
                ha="left",
                va="center",
                fontsize=8.8,
                color=TEXT_DARK,
            )
            ax.text(
                cx + cw - 0.008,
                row_y + row_h - 0.03,
                str(cell.evidence_id),
                ha="right",
                va="top",
                fontsize=7,
                color=TEXT_MUTED,
            )
            cx += cw

    ax.text(
        x0,
        y0 - 0.02,
        "Thick outline = highest overall score",
        ha="left",
        va="top",
        fontsize=8.5,
        color=TEXT_MUTED,
    )


def _draw_recommended(ax, *, h1_color: str = BLUE, h2_color: str = ORANGE) -> None:
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    _panel_label(ax, "d", "Recommended Output")

    _round_box(ax, x=0.02, y=0.08, w=0.96, h=0.86, fc=BG_PANEL, ec=BORDER, lw=1.0)
    ax.text(
        0.05,
        0.90,
        "Recommended: D2 — Flanker × Arousal manipulation",
        ha="left",
        va="center",
        fontsize=11,
        fontweight="bold",
        color=TEXT_DARK,
    )

    left_x0, left_y0, left_w, left_h = 0.05, 0.18, 0.58, 0.64
    _round_box(ax, x=left_x0, y=left_y0, w=left_w, h=left_h, fc=BG_SOFT, ec=BORDER, lw=1.0)
    ax.text(
        left_x0 + 0.02,
        left_y0 + left_h - 0.06,
        "Diverging predictions",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_MUTED,
    )

    bx = left_x0 + left_w * 0.50
    by = left_y0 + left_h * 0.60
    ax.text(
        bx,
        by + 0.10,
        "H1 vs H2",
        ha="center",
        va="center",
        fontsize=9,
        color=TEXT_MUTED,
    )

    ax.add_patch(
        FancyArrowPatch(
            (bx, by),
            (left_x0 + left_w * 0.18, left_y0 + left_h * 0.25),
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=2.0,
            color=h1_color,
        )
    )
    ax.text(
        left_x0 + left_w * 0.05,
        left_y0 + left_h * 0.22,
        _wrap("If H1: pupil diameter predicts RT variability ⊥ conflict level", 34),
        ha="left",
        va="center",
        fontsize=9.3,
        color=h1_color,
        fontweight="bold",
    )

    ax.add_patch(
        FancyArrowPatch(
            (bx, by),
            (left_x0 + left_w * 0.82, left_y0 + left_h * 0.25),
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=2.0,
            color=h2_color,
        )
    )
    ax.text(
        left_x0 + left_w * 0.55,
        left_y0 + left_h * 0.22,
        _wrap("If H2: ACC activation predicts variability ⊥ arousal state", 30),
        ha="left",
        va="center",
        fontsize=9.3,
        color=h2_color,
        fontweight="bold",
    )

    right_x0, right_y0, right_w, right_h = 0.66, 0.18, 0.29, 0.64
    _round_box(ax, x=right_x0, y=right_y0, w=right_w, h=right_h, fc=BG_SOFT, ec=BORDER, lw=1.0)
    ax.text(
        right_x0 + 0.02,
        right_y0 + right_h - 0.06,
        "Analysis skeleton",
        ha="left",
        va="center",
        fontsize=10,
        color=TEXT_MUTED,
    )

    steps = ["Preprocess", "Compute RT-variability", "Model comparison"]
    sy = right_y0 + right_h - 0.18
    box_h = 0.12
    box_gap = 0.09
    centers: list[tuple[float, float]] = []
    for s in steps:
        _round_box(
            ax,
            x=right_x0 + 0.05,
            y=sy - box_h,
            w=right_w - 0.10,
            h=box_h,
            fc=BG_PANEL,
            ec=BORDER,
            lw=1.0,
            rounding=0.03,
            pad=0.01,
        )
        ax.text(
            right_x0 + right_w / 2,
            sy - box_h / 2,
            s,
            ha="center",
            va="center",
            fontsize=9.3,
            color=TEXT_DARK,
        )
        centers.append((right_x0 + right_w / 2, sy - box_h))
        sy -= box_h + box_gap

    for (cx, cy_top), (_, cy_next) in zip(centers, centers[1:]):
        ax.add_patch(
            FancyArrowPatch(
                (cx, cy_top - 0.01),
                (cx, cy_next + 0.11),
                arrowstyle="-|>",
                mutation_scale=10,
                linewidth=1.4,
                color=TEXT_MUTED,
            )
        )

    ax.text(
        right_x0 + 0.05,
        right_y0 + 0.06,
        _wrap("Test conditional independence implied by H1/H2.", 26),
        ha="left",
        va="bottom",
        fontsize=8.5,
        color=TEXT_MUTED,
    )


def _build_default_content():
    candidates = [
        Candidate(
            key="D1",
            title="Psychomotor Vigilance + Pupillometry",
            subtitle="Single paradigm (sustained attention / arousal proxy)",
            template_type="Single template",
            template_color="#2ca02c",
        ),
        Candidate(
            key="D2",
            title="Flanker × Arousal manipulation",
            subtitle="Decoupled factors (conflict × arousal)",
            template_type="Decouple / crossed design",
            template_color="#9467bd",
        ),
        Candidate(
            key="D3",
            title="Multi-task + physiological monitoring",
            subtitle="Orthogonal manipulation (task demands + physiology)",
            template_type="Orthogonal template",
            template_color="#8c564b",
        ),
    ]

    dims = [
        "Construct Validity",
        "Sensitivity",
        "Specificity / Confound Risk",
        "Discriminability",
        "Feasibility",
    ]

    table: dict[str, dict[str, Cell]] = {
        "D1": {
            dims[0]: Cell(4.0, "sustained attn", 1),
            dims[1]: Cell(4.5, "pupil/RT", 2),
            dims[2]: Cell(2.5, "fatigue", 3),
            dims[3]: Cell(3.0, "weak split", 4),
            dims[4]: Cell(4.5, "simple", 5),
        },
        "D2": {
            dims[0]: Cell(4.5, "conflict+arousal", 6),
            dims[1]: Cell(4.0, "interaction", 7),
            dims[2]: Cell(3.5, "controls", 8),
            dims[3]: Cell(4.8, "crossed test", 9),
            dims[4]: Cell(4.0, "≤45 min", 10),
        },
        "D3": {
            dims[0]: Cell(3.8, "broad", 11),
            dims[1]: Cell(4.2, "multi-signal", 12),
            dims[2]: Cell(3.0, "task switch", 13),
            dims[3]: Cell(4.0, "orthogonal", 14),
            dims[4]: Cell(3.0, "complex", 15),
        },
    }

    return candidates, dims, table


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--outdir",
        type=Path,
        default=Path("docs") / "figures",
        help="Output directory (default: docs/figures)",
    )
    ap.add_argument(
        "--basename",
        type=str,
        default="fig5_paradigmcraft",
        help="Output basename without extension",
    )
    ap.add_argument(
        "--png",
        action="store_true",
        help="Also export a high-DPI PNG alongside SVG",
    )
    ap.add_argument(
        "--with-caption",
        action="store_true",
        help="Embed a caption under the figure (off by default)",
    )
    return ap.parse_args()


def main() -> None:
    _set_rcparams()
    args = _parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    candidates, dims, table = _build_default_content()

    fig = plt.figure(figsize=(14.5, 8.2))
    gs = fig.add_gridspec(
        nrows=2,
        ncols=3,
        height_ratios=[1.0, 1.15],
        width_ratios=[1.0, 1.1, 1.25],
        hspace=0.30,
        wspace=0.28,
    )

    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[0, 2])
    ax_d = fig.add_subplot(gs[1, :])

    _draw_input(ax_a)
    _draw_candidates(ax_b, candidates)
    _draw_scorecard(ax_c, dims=dims, rows=candidates, table=table)
    _draw_recommended(ax_d)

    if args.with_caption:
        caption = (
            "ParadigmCraft: given competing hypotheses and constraints (a), the system "
            "retrieves and scores candidate designs (b, c) and recommends the most "
            "discriminative paradigm with explicit diverging predictions (d)."
        )
        fig.text(
            0.5,
            0.01,
            caption,
            ha="center",
            va="bottom",
            fontsize=9,
            color=TEXT_MUTED,
        )

    out_svg = args.outdir / f"{args.basename}.svg"
    fig.savefig(out_svg, bbox_inches="tight")
    print("Saved:", out_svg)

    if args.png:
        out_png = args.outdir / f"{args.basename}.png"
        fig.savefig(out_png, dpi=300, bbox_inches="tight")
        print("Saved:", out_png)

    plt.close(fig)


if __name__ == "__main__":
    main()
