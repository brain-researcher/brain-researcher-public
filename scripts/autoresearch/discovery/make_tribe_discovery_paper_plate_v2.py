#!/usr/bin/env python3
"""Render a cleaner paper-style TRIBE stimulus-discovery figure plate.

This v2 plate is intentionally less encyclopedic than the first a-h storyboard.
It avoids decorative UMAP-style placeholders and focuses on the visual argument:

human question -> discovery-line branch manager -> branch verdicts -> strongest
positive evidence -> failure/design lessons -> claim boundary.
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")

INK = "#111827"
MUTED = "#667085"
GRID = "#E5E7EB"
GREEN = "#177D5A"
AMBER = "#C98200"
BLUE = "#2D6F94"
RED = "#B42318"
LIGHT_GREEN = "#EAF7F1"
LIGHT_AMBER = "#FFF5DA"
LIGHT_BLUE = "#EAF3F8"
LIGHT_RED = "#FFF0EE"

CLASS_COLOR = {
    "real_positive": GREEN,
    "model-tier positive": GREEN,
    "candidate_noisy": AMBER,
    "packaging_failure": BLUE,
    "operational_rule": "#6B7280",
}

BRANCH_ORDER = [
    "HCP language",
    "IBC ToM",
    "IBC auditory",
    "IBC math",
    "HCP social",
    "IBC RSVP",
    "IBC biological motion",
]


@dataclass(frozen=True)
class BranchRow:
    branch: str
    round: int
    contrast: str
    score: float
    diff_norm: float | None
    cosine_gap: float | None
    decision: str
    hypothesis_class: str
    claim_level: str


def _float_or_none(value: str) -> float | None:
    return None if value == "" else float(value)


def read_branches(data_dir: Path) -> list[BranchRow]:
    rows: list[BranchRow] = []
    with (data_dir / "branch_outcomes.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                BranchRow(
                    branch=row["branch"],
                    round=int(row["round"]),
                    contrast=row["contrast"],
                    score=float(row["score"]),
                    diff_norm=_float_or_none(row["diff_norm"]),
                    cosine_gap=_float_or_none(row["cosine_gap"]),
                    decision=row["decision"],
                    hypothesis_class=row["hypothesis_class"],
                    claim_level=row["claim_level"],
                )
            )
    return rows


def read_evidence(data_dir: Path) -> list[dict[str, str]]:
    with (data_dir / "hcp_language_evidence.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def read_layer_scores(data_dir: Path) -> dict[str, list[float]]:
    scores: dict[str, list[float]] = {}
    with (data_dir / "layer_scores.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            scores.setdefault(row["family"], []).append(float(row["score"]))
    return scores


def latest_rows(rows: list[BranchRow]) -> list[BranchRow]:
    latest: dict[str, BranchRow] = {}
    for row in rows:
        if row.branch not in latest or row.round > latest[row.branch].round:
            latest[row.branch] = row
    return [latest[b] for b in BRANCH_ORDER if b in latest]


def setup_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 260,
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.titleweight": "bold",
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def panel_title(ax, label: str, title: str) -> None:
    ax.text(-0.02, 1.08, label, transform=ax.transAxes, ha="left", va="bottom", fontsize=12, weight="bold", color=INK)
    ax.text(0.06, 1.08, title, transform=ax.transAxes, ha="left", va="bottom", fontsize=9, weight="bold", color=INK)


def add_card(ax, xy, w, h, text, face, edge, *, fs=7.1, weight="bold", align="center") -> None:
    x, y = xy
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.010,rounding_size=0.018",
        facecolor=face,
        edgecolor=edge,
        linewidth=1.1,
    )
    ax.add_patch(patch)
    ax.text(
        x + (w / 2 if align == "center" else 0.025),
        y + h / 2,
        text,
        ha=align,
        va="center",
        fontsize=fs,
        color=INK,
        weight=weight,
        linespacing=1.15,
    )


def add_arrow(ax, start, end, color=MUTED, lw=1.2) -> None:
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=11, linewidth=lw, color=color))


def draw_spine(ax) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    panel_title(ax, "a", "Discovery line: hypothesis generator + branch manager")

    steps = [
        ("Human question", "stimulus axes\nrepresentations\nnext experiments", LIGHT_GREEN, GREEN),
        ("Branch manager", "propose\nmaterialize\nfollow up", "#F4F0FF", "#6D4AFF"),
        ("Evidence gate", "score\nvalidate\nstress-test", LIGHT_AMBER, AMBER),
        ("Verdict", "freeze\ncandidate\nredesign", LIGHT_BLUE, BLUE),
    ]
    xs = [0.05, 0.30, 0.55, 0.79]
    for i, (title, body, face, edge) in enumerate(steps):
        add_card(ax, (xs[i], 0.54), 0.16, 0.18, title, face, edge, fs=7.0)
        ax.text(
            xs[i] + 0.08,
            0.43,
            body.replace("\n", " / "),
            ha="center",
            va="center",
            fontsize=5.8,
            color=MUTED,
        )
        if i < len(steps) - 1:
            add_arrow(ax, (xs[i] + 0.17, 0.63), (xs[i + 1] - 0.014, 0.63), color=INK, lw=1.0)
    ax.text(
        0.03,
        0.20,
        "Output classes",
        fontsize=7.0,
        color=MUTED,
        weight="bold",
        ha="left",
    )
    chips = [("real positive axis", GREEN), ("candidate / noisy", AMBER), ("packaging-sensitive failure", BLUE)]
    x = 0.20
    for text, color in chips:
        add_card(ax, (x, 0.13), 0.18, 0.12, text, "white", color, fs=6.2)
        x += 0.205
    ax.text(0.98, 0.20, "Reward searches; validation sets belief.", ha="right", va="center", fontsize=6.7, color=MUTED, style="italic")


def draw_branch_outcomes(ax, rows: list[BranchRow]) -> None:
    panel_title(ax, "b", "Branch verdicts after follow-up")
    ordered = latest_rows(rows)
    y = np.arange(len(ordered))[::-1]
    scores = np.array([r.score for r in ordered])
    x = np.log10(scores + 1e-4)

    ax.axvline(np.log10(0.1 + 1e-4), color=GRID, lw=1.2)
    ax.axvline(np.log10(1.0 + 1e-4), color=GRID, lw=1.2)
    ax.text(np.log10(0.015), len(ordered) - 0.35, "weak", color=MUTED, fontsize=6.6, ha="center")
    ax.text(np.log10(0.35), len(ordered) - 0.35, "candidate", color=MUTED, fontsize=6.6, ha="center")
    ax.text(np.log10(3.5), len(ordered) - 0.35, "strong", color=MUTED, fontsize=6.6, ha="center")

    for yi, xi, row in zip(y, x, ordered):
        color = CLASS_COLOR[row.hypothesis_class]
        ax.hlines(yi, np.log10(0.001 + 1e-4), xi, color=color, lw=2.0, alpha=0.75)
        face = color if row.decision not in {"kill", "redesign"} else "white"
        marker = "o" if row.decision in {"freeze", "kill"} else ("D" if row.decision == "candidate" else "^")
        ax.scatter(xi, yi, s=74, marker=marker, facecolor=face, edgecolor=color, lw=1.8, zorder=3)
        ax.text(xi + 0.045, yi, f"{row.score:g}", va="center", fontsize=6.8, color=INK)

    ax.set_yticks(y)
    ax.set_yticklabels([r.branch.replace("IBC ", "") for r in ordered])
    ticks = [0.001, 0.01, 0.1, 1, 10]
    ax.set_xticks([np.log10(t + 1e-4) for t in ticks])
    ax.set_xticklabels([str(t) for t in ticks])
    ax.set_xlabel("score, log scale")
    ax.grid(axis="x", color=GRID, lw=0.7, alpha=0.6)
    ax.set_ylim(-0.65, len(ordered) - 0.05)
    ax.set_xlim(np.log10(0.0008 + 1e-4), np.log10(18))


def draw_language_ladder(ax, evidence: list[dict[str, str]]) -> None:
    panel_title(ax, "c", "HCP language evidence ladder")
    display = [
        ("Original", "15.154; p=0.00794", GREEN),
        ("Expanded", "10.564; p~5e-5", GREEN),
        ("Held-out", "p=0.0002", GREEN),
        ("Acoustic", "significant", GREEN),
        ("Late-layer", "p~5e-5", GREEN),
        ("Fold bridge", "r=0.098; p=0.449", RED),
        ("Observed fMRI", "missing", "#98A2B3"),
    ]
    y = np.arange(len(display))[::-1]
    ax.plot([0] * len(y), y, color=GRID, lw=2, zorder=0)
    for yi, (label, detail, color) in zip(y, display):
        ax.scatter(0, yi, s=90, color=color, edgecolor="white", lw=1.2, zorder=2)
        ax.text(0.10, yi + 0.10, label, fontsize=7.2, color=INK, weight="bold", va="center")
        ax.text(0.10, yi - 0.16, detail, fontsize=6.3, color=MUTED, va="center")
    ax.set_xlim(-0.18, 1.35)
    ax.set_ylim(-0.65, len(display) - 0.35)
    ax.axis("off")
    ax.text(
        0.02,
        -0.48,
        "Strong item-level model-feature evidence; neural validation remains open.",
        fontsize=6.7,
        color=RED,
        weight="bold",
    )


def draw_layer_family(ax, layer_scores: dict[str, list[float]]) -> None:
    panel_title(ax, "d", "Layer-family confirmation")
    labels = ["late attn", "early attn", "projectors"]
    keys = ["late_attn", "early_attn", "projectors"]
    means = [float(np.mean(layer_scores[k])) for k in keys]
    colors = [GREEN, "#9CA3AF", "#CBD5E1"]
    ax.barh(np.arange(3)[::-1], means, color=colors, height=0.48)
    for yi, mean in zip(np.arange(3)[::-1], means):
        ax.text(mean + 0.035, yi, f"{mean:.3f}", va="center", fontsize=7.0, color=INK, weight="bold")
    ax.set_yticks(np.arange(3)[::-1])
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("mean separation")
    ax.grid(axis="x", color=GRID, lw=0.7, alpha=0.65)
    ax.text(
        0.98,
        0.06,
        "late > early > projectors",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7.0,
        color=GREEN,
        weight="bold",
    )


def draw_trajectories(ax) -> None:
    panel_title(ax, "e", "Why branches freeze or stop")
    trajectories = {
        "HCP language": ([1, 2], [15.154, 10.564], GREEN, "freeze"),
        "HCP social": ([1, 2], [0.0349, 0.0152], BLUE, "kill"),
        "Auditory": ([1, 2, 3, 4, 5, 6, 7], [0.19, 0.37, 0.39, 0.74, 0.88, 1.99, 0.30], AMBER, "noisy"),
    }
    for name, (xs, ys, color, label) in trajectories.items():
        ax.plot(xs, np.log10(np.asarray(ys) + 1e-4), marker="o", lw=2, color=color, label=name)
        ax.text(xs[-1] + 0.08, np.log10(ys[-1] + 1e-4), label, fontsize=6.7, color=color, va="center", weight="bold")
    ax.set_xlabel("round")
    ax.set_ylabel("log10(score)")
    ax.grid(color=GRID, lw=0.7, alpha=0.65)
    ax.legend(frameon=False, fontsize=6.4, loc="lower left")
    ax.text(4.0, -1.78, "weak -> real follow-up -> weaker", fontsize=6.5, color=BLUE, weight="bold")


def draw_failure_design(ax) -> None:
    panel_title(ax, "f", "Failures become design rules")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    cards = [
        ("HCP social", "motion-matched\nsocial/mechanical videos", LIGHT_BLUE, BLUE),
        ("RSVP", "preserve timing\nand probe structure", LIGHT_AMBER, AMBER),
        ("Biomotion", "motion-aware\nvideo representation", LIGHT_BLUE, BLUE),
    ]
    for i, (title, body, face, edge) in enumerate(cards):
        y = 0.70 - i * 0.28
        add_card(ax, (0.04, y), 0.30, 0.16, title, "white", edge, fs=7.0)
        add_arrow(ax, (0.36, y + 0.08), (0.49, y + 0.08), color=edge, lw=1.1)
        add_card(ax, (0.52, y), 0.42, 0.16, body, face, edge, fs=6.8)
    ax.text(0.05, 0.05, "Low score is not a biological null; it is a redesign signal.", fontsize=6.8, color=MUTED)


def draw_boundary(ax) -> None:
    panel_title(ax, "g", "Current claim boundary")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    add_card(
        ax,
        (0.04, 0.50),
        0.42,
        0.34,
        "Supported\n\nHCP language: robust\nitem-level model-feature axis\n\nHCP social: negative\nin this setup",
        LIGHT_GREEN,
        GREEN,
        fs=6.8,
    )
    add_card(
        ax,
        (0.54, 0.50),
        0.42,
        0.34,
        "Not yet supported\n\nobserved fMRI\nnot done\n\nlanguage specificity\nneeds controls",
        LIGHT_RED,
        RED,
        fs=6.6,
    )
    add_card(
        ax,
        (0.04, 0.12),
        0.92,
        0.18,
        "Next: subject/run HCP LANGUAGE targets + locked subject/fold validation.",
        "white",
        GRID,
        fs=6.8,
    )


def make_plate(rows: list[BranchRow], evidence: list[dict[str, str]], layer_scores: dict[str, list[float]]) -> plt.Figure:
    setup_style()
    fig = plt.figure(figsize=(14.5, 10.0), constrained_layout=False)
    gs = fig.add_gridspec(
        3,
        3,
        height_ratios=[0.62, 1.85, 1.65],
        width_ratios=[1.35, 1.00, 1.00],
        left=0.055,
        right=0.985,
        top=0.86,
        bottom=0.075,
        hspace=0.55,
        wspace=0.36,
    )
    ax_a = fig.add_subplot(gs[0, :])
    ax_b = fig.add_subplot(gs[1, 0])
    ax_c = fig.add_subplot(gs[1, 1])
    ax_d = fig.add_subplot(gs[1, 2])
    ax_e = fig.add_subplot(gs[2, 0])
    ax_f = fig.add_subplot(gs[2, 1])
    ax_g = fig.add_subplot(gs[2, 2])

    draw_spine(ax_a)
    draw_branch_outcomes(ax_b, rows)
    draw_language_ladder(ax_c, evidence)
    draw_layer_family(ax_d, layer_scores)
    draw_trajectories(ax_e)
    draw_failure_design(ax_f)
    draw_boundary(ax_g)

    fig.text(
        0.055,
        0.965,
        "TRIBE stimulus-discovery line: branch trajectories become bounded hypotheses",
        ha="left",
        va="top",
        fontsize=13.5,
        color=INK,
        weight="bold",
    )
    fig.text(
        0.055,
        0.925,
        "A paper-style summary of the human question, discovery loop, evidence classes, validation boundary, and next experiments.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    return fig


def write_readme(out_dir: Path, figure_root: Path) -> None:
    (out_dir / "README.md").write_text(
        f"""# TRIBE stimulus-discovery paper plate v2

Generated by `scripts/autoresearch/discovery/make_tribe_discovery_paper_plate_v2.py`.

Outputs:

- `tribe_stimulus_discovery_paper_plate_v2_20260427.pdf`
- `tribe_stimulus_discovery_paper_plate_v2_20260427.png`
- `tribe_stimulus_discovery_paper_plate_v2_20260427.svg`

Source data:

- `{figure_root / 'data/branch_outcomes.csv'}`
- `{figure_root / 'data/hcp_language_evidence.csv'}`
- `{figure_root / 'data/layer_scores.csv'}`

Design choices:

- This version removes the text-heavy a-h storyboard layout.
- It does not include UMAP or latent decision-space panels because those require an episode-level feature table.
- It does not add subject-level observed fMRI validation; the boundary is shown explicitly.
"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-root", type=Path, default=FIGURE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or args.figure_root / "story_plate_v2_20260427"
    out_dir.mkdir(parents=True, exist_ok=True)

    data_dir = args.figure_root / "data"
    rows = read_branches(data_dir)
    evidence = read_evidence(data_dir)
    layer_scores = read_layer_scores(data_dir)
    fig = make_plate(rows, evidence, layer_scores)

    stem = "tribe_stimulus_discovery_paper_plate_v2_20260427"
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_readme(out_dir, args.figure_root)
    print(f"Wrote v2 plate to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
