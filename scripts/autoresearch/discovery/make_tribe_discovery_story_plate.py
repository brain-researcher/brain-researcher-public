#!/usr/bin/env python3
"""Render the TRIBE stimulus-discovery a-h story plate.

The plate is built from the existing discovery figure data tables. It is meant
to visualize the scientific story, not just raw scores:

a. Human question -> loop -> hypothesis classes
b. Branch outcome landscape
c. Branch trajectories
d. Score decomposition
e. Condition signature changes
f. Hypothesis-class map
g. Next-experiment design matrix
h. Claim boundary

The script uses local matplotlib only. Outputs are deterministic PNG, PDF, SVG,
plus a README describing the source data and limitations.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


DEFAULT_FIGURE_ROOT = Path(
    "/data/brain_researcher/research/discovery/docs/operations/figures"
)

INK = "#172033"
MUTED = "#667085"
GRID = "#D7DEE8"
PANEL_BG = "#F7F8FA"
BOUNDARY_RED = "#C0392B"

CLASS_COLOR = {
    "real_positive": "#1B7F5A",
    "model-tier positive": "#1B7F5A",
    "candidate_noisy": "#D9901A",
    "packaging_failure": "#31688E",
    "operational_rule": "#6B7280",
}

DECISION_MARKER = {
    "freeze": "o",
    "kill": "o",
    "candidate": "D",
    "redesign": "^",
    "kill/redesign": "^",
    "keep": "s",
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
    positive_conditions: str
    negative_conditions: str
    condition_signature: str
    failure_modes: str
    action: str
    decision: str
    hypothesis_class: str
    claim_level: str


def read_branch_rows(data_dir: Path) -> list[BranchRow]:
    rows: list[BranchRow] = []
    with (data_dir / "branch_outcomes.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            def ffloat(value: str) -> float | None:
                if value is None or value == "":
                    return None
                return float(value)

            rows.append(
                BranchRow(
                    branch=row["branch"],
                    round=int(row["round"]),
                    contrast=row["contrast"],
                    score=float(row["score"]),
                    diff_norm=ffloat(row["diff_norm"]),
                    cosine_gap=ffloat(row["cosine_gap"]),
                    positive_conditions=row["positive_conditions"],
                    negative_conditions=row["negative_conditions"],
                    condition_signature=row["condition_signature"],
                    failure_modes=row["failure_modes"],
                    action=row["action"],
                    decision=row["decision"],
                    hypothesis_class=row["hypothesis_class"],
                    claim_level=row["claim_level"],
                )
            )
    return rows


def read_manifest_deltas(data_dir: Path) -> list[dict]:
    return json.loads((data_dir / "manifest_deltas.json").read_text())["panels"]


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 220,
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 10,
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


def panel_label(ax, label: str, title: str) -> None:
    ax.text(
        0.0,
        1.04,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=11,
        color=INK,
        weight="bold",
    )
    ax.text(
        0.075,
        1.04,
        title,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9,
        color=INK,
        weight="bold",
    )


def rounded_box(ax, xy, w, h, text, *, face="white", edge=GRID, fs=8.0, weight="normal"):
    x, y = xy
    patch = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.035",
        facecolor=face,
        edgecolor=edge,
        linewidth=1.0,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK, weight=weight)


def arrow(ax, start, end, *, color=MUTED, lw=1.2):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=10,
            color=color,
            linewidth=lw,
        )
    )


def draw_panel_a(ax) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    panel_label(ax, "a", "Human question -> self-driven loop")

    rounded_box(
        ax,
        (0.18, 0.68),
        0.29,
        0.32,
        "Human questions\nstimulus axes?\nrepresentations?\nnew hypotheses?",
        face="#E9F3EE",
        edge=CLASS_COLOR["real_positive"],
        fs=7.6,
        weight="bold",
    )
    rounded_box(
        ax,
        (0.50, 0.68),
        0.27,
        0.32,
        "Encoding setup\nstimuli -> model\nrepresentation ->\npredicted response",
        face="#EEF2FF",
        edge="#31688E",
        fs=7.6,
        weight="bold",
    )
    rounded_box(
        ax,
        (0.82, 0.68),
        0.27,
        0.32,
        "Loop\npropose\nmaterialize\nscore\nfollow-up",
        face="#FFF4DF",
        edge="#C47A16",
        fs=7.6,
        weight="bold",
    )
    arrow(ax, (0.32, 0.68), (0.365, 0.68), color=INK)
    arrow(ax, (0.64, 0.68), (0.685, 0.68), color=INK)

    rounded_box(
        ax,
        (0.50, 0.24),
        0.78,
        0.22,
        "Hypothesis classes: real positive axes | packaging-sensitive failures | operational discovery rules",
        face="white",
        edge=GRID,
        fs=7.5,
        weight="bold",
    )
    arrow(ax, (0.82, 0.51), (0.58, 0.35), color=MUTED)


def draw_panel_b(ax, rows: list[BranchRow]) -> None:
    panel_label(ax, "b", "Branch outcome landscape")
    latest_by_branch: dict[str, BranchRow] = {}
    for row in rows:
        if row.branch not in latest_by_branch or row.round > latest_by_branch[row.branch].round:
            latest_by_branch[row.branch] = row

    ordered = [latest_by_branch[b] for b in BRANCH_ORDER if b in latest_by_branch]
    y = np.arange(len(ordered))[::-1]
    scores = np.asarray([r.score for r in ordered])
    x = np.log10(scores + 1e-4)

    ax.axvspan(np.log10(0.001 + 1e-4), np.log10(0.1 + 1e-4), color="#F3F6FA", zorder=0)
    ax.axvspan(np.log10(0.1 + 1e-4), np.log10(1.0 + 1e-4), color="#FFF8E8", zorder=0)
    ax.axvspan(np.log10(1.0 + 1e-4), np.log10(20.0 + 1e-4), color="#ECF7F1", zorder=0)
    ax.text(np.log10(0.003), len(ordered) - 0.35, "weak", color=MUTED, fontsize=7)
    ax.text(np.log10(0.22), len(ordered) - 0.35, "candidate", color=MUTED, fontsize=7)
    ax.text(np.log10(2.4), len(ordered) - 0.35, "strong", color=MUTED, fontsize=7)

    for yi, xi, row in zip(y, x, ordered):
        color = CLASS_COLOR[row.hypothesis_class]
        marker = DECISION_MARKER.get(row.decision, "o")
        face = color if row.decision not in {"kill", "redesign"} else "white"
        ax.hlines(yi, np.log10(0.001 + 1e-4), xi, color=color, linewidth=1.4, alpha=0.75)
        ax.scatter(
            xi,
            yi,
            s=70,
            marker=marker,
            facecolor=face,
            edgecolor=color,
            linewidth=1.6,
            zorder=3,
        )
        ax.text(xi + 0.055, yi, f"{row.score:g} / {row.decision}", va="center", fontsize=6.8, color=INK)

    ax.set_yticks(y)
    ax.set_yticklabels([r.branch.replace("IBC ", "") for r in ordered])
    ticks = [0.001, 0.01, 0.1, 1, 10]
    ax.set_xticks([np.log10(t + 1e-4) for t in ticks])
    ax.set_xticklabels([str(t) for t in ticks])
    ax.set_xlabel("representational separation score, log scale")
    ax.grid(axis="x", color=GRID, linewidth=0.8, alpha=0.65)
    ax.set_ylim(-0.7, len(ordered) - 0.1)


def draw_panel_c(ax) -> None:
    panel_label(ax, "c", "Branch trajectories, not single scores")
    trajectories = {
        "HCP language": ([1, 2], [15.154, 10.564], "freeze", "real_positive"),
        "HCP social": ([1, 2], [0.0349, 0.0152], "kill", "packaging_failure"),
        "Auditory": ([1, 2, 3, 4, 5, 6, 7], [0.19, 0.37, 0.39, 0.74, 0.88, 1.99, 0.30], "noisy", "candidate_noisy"),
        "Math": ([1, 2], [0.03, 0.32], "fixed", "candidate_noisy"),
        "ToM": ([1, 2], [0.18, 0.69], "question", "candidate_noisy"),
    }
    label_offsets = {
        "HCP language": (0.06, 0.05),
        "HCP social": (0.06, -0.09),
        "Auditory": (0.06, -0.02),
        "Math": (0.06, 0.03),
        "ToM": (0.06, 0.03),
    }
    for name, (xs, ys, label, cls) in trajectories.items():
        color = CLASS_COLOR[cls]
        ax.plot(xs, np.log10(np.asarray(ys) + 1e-4), marker="o", linewidth=1.8, color=color, label=name)
        dx, dy = label_offsets[name]
        ax.text(xs[-1] + dx, np.log10(ys[-1] + 1e-4) + dy, label, fontsize=6.8, color=color, va="center")
    ax.set_xlabel("round / follow-up step")
    ax.set_ylabel("log10(score)")
    ax.grid(color=GRID, linewidth=0.8, alpha=0.65)
    ax.legend(frameon=False, fontsize=6.5, loc="lower left", ncols=1)
    ax.text(
        0.98,
        0.05,
        "HCP social: weak -> valid follow-up -> weaker -> kill",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=6.8,
        color=INK,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": GRID, "linewidth": 0.7},
    )


def draw_panel_d(ax, rows: list[BranchRow]) -> None:
    panel_label(ax, "d", "Score decomposition")
    plotted = [r for r in rows if r.diff_norm is not None and r.cosine_gap is not None]
    ax.set_xlabel("diff_norm")
    ax.set_ylabel("cosine_gap")
    ax.grid(color=GRID, linewidth=0.8, alpha=0.65)
    ax.axhline(0.01, color=GRID, linestyle="--", linewidth=1)
    if plotted:
        for row in plotted:
            color = CLASS_COLOR[row.hypothesis_class]
            size = 320 * max(row.score, 0.015) / 0.05
            ax.scatter(row.diff_norm, row.cosine_gap, s=size, color=color, alpha=0.75, edgecolor=INK, linewidth=0.7)
            ax.text(
                row.diff_norm + 0.03,
                row.cosine_gap,
                f"{row.branch} r{row.round}\nscore={row.score:.4f}",
                fontsize=7,
                va="center",
                color=INK,
            )
    ax.set_xlim(0, 2.45)
    ax.set_ylim(0, 0.026)
    ax.text(
        0.04,
        0.92,
        "score = diff_norm * max(cosine_gap, 1e-6)\nlow score can mean directional collapse",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=7.0,
        color=INK,
        weight="bold",
        bbox={"boxstyle": "round,pad=0.28", "facecolor": "#F8FAFC", "edgecolor": GRID, "linewidth": 0.8},
    )


def draw_panel_e(ax, deltas: list[dict]) -> None:
    panel_label(ax, "e", "Condition signatures changed")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(deltas))
    ax.axis("off")

    def signature_text(conditions: dict) -> str:
        parts = [f"{short_condition_name(cond)}:{count}" for cond, count in conditions.items()]
        return "\n".join(parts)

    def signature_card(x: float, y: float, label: str, conditions: dict, face: str) -> None:
        patch = FancyBboxPatch(
            (x, y - 0.19),
            0.27,
            0.36,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor=face,
            edgecolor=GRID,
            linewidth=0.8,
        )
        ax.add_patch(patch)
        ax.text(x + 0.012, y + 0.125, label, fontsize=6.2, color=MUTED, va="top", ha="left")
        ax.text(
            x + 0.012,
            y + 0.055,
            signature_text(conditions),
            fontsize=6.1,
            color=INK,
            va="top",
            ha="left",
            linespacing=1.12,
        )

    def short_condition_name(name: str) -> str:
        replacements = {
            "social_animation": "social",
            "mechanical_motion": "mechanical",
            "control_lexical": "lexical ctl",
            "control": "control",
            "arithprin": "math principle",
            "belief_question": "belief q",
            "physical_question": "physical q",
            "belief_story": "belief story",
            "physical_story": "physical story",
        }
        return replacements.get(name, name.replace("_", " "))

    for idx, item in enumerate(deltas):
        y = len(deltas) - idx - 0.55
        ax.text(0.02, y + 0.13, item["branch"], fontsize=7.2, color=INK, weight="bold", va="top")
        signature_card(0.24, y, item["round_a"]["label"], item["round_a"]["conditions"], "#F8FAFC")
        signature_card(0.62, y, item["round_b"]["label"], item["round_b"]["conditions"], "#FFF8E8")
        arrow(ax, (0.53, y), (0.59, y), color=MUTED, lw=1.0)
        ax.text(0.24, y - 0.28, item["delta_note"], fontsize=5.9, color=MUTED, ha="left")
        ax.plot([0.02, 0.98], [y - 0.42, y - 0.42], color=GRID, linewidth=0.5)


def draw_panel_f(ax, rows: list[BranchRow]) -> None:
    panel_label(ax, "f", "Branch -> hypothesis class")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    latest: dict[str, BranchRow] = {}
    for row in rows:
        if row.branch not in latest or row.round > latest[row.branch].round:
            latest[row.branch] = row
    classes = {
        "real_positive": "real positive axis",
        "candidate_noisy": "candidate / noisy",
        "packaging_failure": "packaging-sensitive failure",
    }
    y_positions = {"real_positive": 0.78, "candidate_noisy": 0.50, "packaging_failure": 0.22}
    for cls, title in classes.items():
        rounded_box(ax, (0.72, y_positions[cls]), 0.44, 0.18, title, face=CLASS_COLOR[cls] + "22", edge=CLASS_COLOR[cls], fs=7.4, weight="bold")

    y_branch = np.linspace(0.86, 0.14, len(BRANCH_ORDER))
    for y, branch in zip(y_branch, BRANCH_ORDER):
        if branch not in latest:
            continue
        row = latest[branch]
        cls = row.hypothesis_class
        color = CLASS_COLOR[cls]
        ax.text(0.03, y, branch.replace("IBC ", ""), fontsize=6.9, color=INK, va="center")
        arrow(ax, (0.24, y), (0.50, y_positions[cls]), color=color, lw=1.0)
        ax.text(0.27, y + 0.018, row.decision, fontsize=5.8, color=color, weight="bold")
    ax.text(0.02, 0.03, "Each hypothesis is a branch trajectory, not one score.", fontsize=6.8, color=MUTED)


def draw_panel_g(ax) -> None:
    panel_label(ax, "g", "Next experiment design matrix")
    domains = [
        "HCP language",
        "HCP social",
        "Auditory",
        "Math",
        "ToM",
        "RSVP",
        "Biomotion",
    ]
    cols = ["replicate", "controls", "cross-modal", "timing", "motion", "larger N", "layer/ROI"]
    matrix = np.asarray(
        [
            [2, 2, 2, 0, 0, 1, 2],
            [0, 2, 0, 0, 2, 1, 1],
            [1, 2, 0, 0, 0, 2, 1],
            [1, 2, 0, 0, 0, 1, 1],
            [1, 2, 0, 0, 0, 1, 1],
            [0, 1, 0, 2, 0, 1, 1],
            [0, 1, 0, 0, 2, 1, 1],
        ],
        dtype=float,
    )
    cmap = matplotlib.colors.ListedColormap(["#ECEFF4", "#F7DFAF", "#1B7F5A"])
    ax.imshow(matrix, cmap=cmap, vmin=0, vmax=2, aspect="auto")
    ax.set_xticks(np.arange(len(cols)))
    ax.set_xticklabels(cols, rotation=35, ha="right")
    ax.set_yticks(np.arange(len(domains)))
    ax.set_yticklabels(domains)
    ax.tick_params(length=0)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            label = "" if matrix[i, j] == 0 else ("+" if matrix[i, j] == 1 else "++")
            ax.text(j, i, label, ha="center", va="center", fontsize=7, color=INK, weight="bold")
    for spine in ax.spines.values():
        spine.set_visible(False)


def draw_panel_h(ax) -> None:
    panel_label(ax, "h", "Claim boundary")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    rounded_box(
        ax,
        (0.28, 0.55),
        0.46,
        0.72,
        "Can claim\n\nHCP language is robust\nitem-level model-feature evidence\n\nHCP social is negative\nin current setup\n\nFailures reveal packaging\nand representation mismatch",
        face="#ECF7F1",
        edge=CLASS_COLOR["real_positive"],
        fs=7.1,
        weight="bold",
    )
    rounded_box(
        ax,
        (0.74, 0.55),
        0.46,
        0.72,
        "Cannot yet claim\n\nscore is a p-value\n\nlow score means no neural signal\n\nHCP language is purely language-specific\n\nsubject-level observed fMRI validation is done",
        face="#FFF1F1",
        edge=BOUNDARY_RED,
        fs=7.1,
        weight="bold",
    )
    ax.text(
        0.5,
        0.08,
        "Current boundary: model-feature / predicted-response evidence, not observed subject-level fMRI.",
        ha="center",
        va="center",
        fontsize=7.4,
        color=BOUNDARY_RED,
        style="italic",
        weight="bold",
    )


def make_plate(rows: list[BranchRow], deltas: list[dict]) -> plt.Figure:
    apply_style()
    fig = plt.figure(figsize=(18, 16), constrained_layout=False)
    gs = fig.add_gridspec(
        4,
        2,
        left=0.04,
        right=0.98,
        bottom=0.04,
        top=0.93,
        hspace=0.42,
        wspace=0.18,
    )
    axes = [fig.add_subplot(gs[i, j]) for i in range(4) for j in range(2)]
    draw_panel_a(axes[0])
    draw_panel_b(axes[1], rows)
    draw_panel_c(axes[2])
    draw_panel_d(axes[3], rows)
    draw_panel_e(axes[4], deltas)
    draw_panel_f(axes[5], rows)
    draw_panel_g(axes[6])
    draw_panel_h(axes[7])
    fig.suptitle(
        "Self-driven brain-encoding experiments convert stimulus contrasts into hypothesis classes",
        x=0.04,
        y=0.985,
        ha="left",
        fontsize=18,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.04,
        0.955,
        "Human questions -> self-driven loop -> branch trajectory -> hypothesis class -> next experiment.",
        ha="left",
        va="top",
        fontsize=10,
        color=MUTED,
    )
    return fig


def write_readme(out_dir: Path, figure_root: Path) -> Path:
    path = out_dir / "README.md"
    content = f"""# TRIBE stimulus-discovery story plate

Generated by `scripts/autoresearch/discovery/make_tribe_discovery_story_plate.py`.

Main output:

- `tribe_stimulus_discovery_story_plate_20260427.png`
- `tribe_stimulus_discovery_story_plate_20260427.pdf`
- `tribe_stimulus_discovery_story_plate_20260427.svg`

Source data:

- `{figure_root / 'data/branch_outcomes.csv'}`
- `{figure_root / 'data/manifest_deltas.json'}`
- Existing evidence tables in `{figure_root / 'data'}`

Interpretation boundary:

- The plate summarizes existing branch-level evidence and ledger-derived trajectory summaries.
- It does not add new subject-level fMRI validation.
- UMAP / decision-space panels are intentionally not included because they require an episode-level feature table.
"""
    path.write_text(content)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-root", type=Path, default=DEFAULT_FIGURE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    figure_root = args.figure_root
    out_dir = args.out_dir or figure_root / "story_plate_20260427"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_branch_rows(figure_root / "data")
    deltas = read_manifest_deltas(figure_root / "data")
    fig = make_plate(rows, deltas)

    stem = "tribe_stimulus_discovery_story_plate_20260427"
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    readme = write_readme(out_dir, figure_root)
    print(f"Wrote story plate to {out_dir}")
    print(f"Wrote README: {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
