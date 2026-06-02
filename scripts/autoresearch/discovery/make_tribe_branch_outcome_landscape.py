#!/usr/bin/env python3
"""Render Figure 2: TRIBE branch outcome landscape.

This is a deterministic evidence figure, not an AI-generated schematic. It uses
the canonical branch outcome ledger to show how self-driven branches sorted into
model-tier positives, standard candidate/noisy branches, packaging-sensitive
non-recoveries, and representation-sensitive redesign candidates.
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
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")
DEFAULT_OUT_DIR = FIGURE_ROOT / "figure02_branch_outcomes_20260428"

INK = "#172033"
MUTED = "#667085"
GRID = "#E3E8EF"
WEAK_BG = "#F3F6FA"
CANDIDATE_BG = "#FFF6E5"
STRONG_BG = "#ECF7F1"

CLASS_LABEL = {
    "real_positive": "model-tier positive axis",
    "model-tier positive": "model-tier positive",
    "candidate_noisy": "candidate / noisy signal",
    "packaging_failure": "packaging non-recovery",
    "representation_sensitive_candidate": "motion-aware candidate",
}

CLASS_COLOR = {
    "real_positive": "#177D5A",
    "model-tier positive": "#177D5A",
    "candidate_noisy": "#C98200",
    "packaging_failure": "#2D6F94",
    "representation_sensitive_candidate": "#8A4FBA",
}

DECISION_MARKER = {
    "freeze": "o",
    "candidate": "D",
    "kill": "o",
    "redesign": "^",
    "kill/redesign": "^",
    "candidate/redesign": "s",
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

BRANCH_LABEL = {
    "HCP language": "HCP Language",
    "IBC ToM": "IBC Theory of Mind",
    "IBC auditory": "IBC Auditory",
    "IBC math": "IBC Math",
    "HCP social": "HCP Social",
    "IBC RSVP": "RSVP Language",
    "IBC biological motion": "Biological Motion",
}

DECISION_LABEL = {
    "freeze": "freeze / report",
    "candidate": "continue / validate",
    "kill": "kill",
    "redesign": "redesign",
    "kill/redesign": "kill / redesign",
    "candidate/redesign": "candidate / redesign",
}


@dataclass(frozen=True)
class BranchOutcome:
    branch: str
    round: int
    contrast: str
    score: float
    action: str
    decision: str
    hypothesis_class: str
    claim_level: str


def read_outcomes(path: Path) -> list[BranchOutcome]:
    rows: list[BranchOutcome] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                BranchOutcome(
                    branch=row["branch"],
                    round=int(row["round"]),
                    contrast=row["contrast"],
                    score=float(row["score"]),
                    action=row["action"],
                    decision=row["decision"],
                    hypothesis_class=row["hypothesis_class"],
                    claim_level=row["claim_level"],
                )
            )
    return rows


def latest_by_branch(rows: list[BranchOutcome]) -> list[BranchOutcome]:
    latest: dict[str, BranchOutcome] = {}
    for row in rows:
        if row.branch not in latest or row.round > latest[row.branch].round:
            latest[row.branch] = row
    return [latest[branch] for branch in BRANCH_ORDER if branch in latest]


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 300,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def log_score(score: float) -> float:
    return float(np.log10(score + 1e-4))


def fmt_score(score: float) -> str:
    if score >= 10:
        return f"{score:.3f}"
    if score >= 0.1:
        return f"{score:.2f}"
    if score >= 0.01:
        return f"{score:.4f}"
    return f"{score:.5f}"


def make_figure(rows: list[BranchOutcome]) -> plt.Figure:
    style()
    latest = latest_by_branch(rows)

    fig, ax = plt.subplots(figsize=(9.2, 5.7))
    fig.subplots_adjust(left=0.24, right=0.78, top=0.80, bottom=0.18)

    xmin = log_score(0.0008)
    xmax = log_score(30.0)
    ax.axvspan(log_score(0.0008), log_score(0.1), color=WEAK_BG, zorder=0)
    ax.axvspan(log_score(0.1), log_score(1.0), color=CANDIDATE_BG, zorder=0)
    ax.axvspan(log_score(1.0), xmax, color=STRONG_BG, zorder=0)

    for threshold in (0.1, 1.0):
        ax.axvline(log_score(threshold), color="#CDD5DF", lw=1.1, zorder=1)

    y = np.arange(len(latest))[::-1]
    zero = log_score(0.001)
    for yi, row in zip(y, latest):
        x = log_score(row.score)
        color = CLASS_COLOR[row.hypothesis_class]
        marker = DECISION_MARKER[row.decision]
        face = color if row.decision in {"freeze", "candidate", "candidate/redesign"} else "white"
        ax.hlines(yi, zero, x, color=color, lw=2.4, alpha=0.78, zorder=2)
        ax.scatter(
            x,
            yi,
            s=105,
            marker=marker,
            facecolor=face,
            edgecolor=color,
            linewidth=2.1,
            zorder=4,
        )
        ax.text(
            x + 0.055,
            yi + 0.06,
            fmt_score(row.score),
            ha="left",
            va="center",
            fontsize=8.5,
            color=INK,
            weight="bold",
        )
        ax.text(
            x + 0.055,
            yi - 0.18,
            DECISION_LABEL[row.decision],
            ha="left",
            va="center",
            fontsize=7.1,
            color=color,
        )

    ax.set_yticks(y)
    ax.set_yticklabels([BRANCH_LABEL[row.branch] for row in latest])
    ticks = [0.001, 0.01, 0.1, 1, 10]
    ax.set_xticks([log_score(t) for t in ticks])
    ax.set_xticklabels(["0.001", "0.01", "0.1", "1", "10"])
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(-0.7, len(latest) - 0.05)
    ax.grid(axis="x", color=GRID, linewidth=0.8, alpha=0.85)
    ax.set_xlabel("contrast score (log scale)")

    band_y = len(latest) - 0.25
    ax.text(log_score(0.015), band_y, "weak", color=MUTED, fontsize=8, ha="center", va="center")
    ax.text(log_score(0.35), band_y, "candidate", color=MUTED, fontsize=8, ha="center", va="center")
    ax.text(log_score(4.0), band_y, "strong", color=MUTED, fontsize=8, ha="center", va="center")

    fig.text(
        0.08,
        0.935,
        "Figure 2. Self-driven experiments sort stimulus contrasts into hypothesis classes",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Final branch states show 1 model-tier positive, 3 standard candidates, 2 packaging failures, and 1 motion-aware redesign candidate.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )

    seen_classes = []
    for row in latest:
        if row.hypothesis_class not in seen_classes:
            seen_classes.append(row.hypothesis_class)
    class_handles = [
        Patch(facecolor=CLASS_COLOR[key], edgecolor=CLASS_COLOR[key], label=CLASS_LABEL[key])
        for key in seen_classes
    ]
    marker_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=INK, markeredgecolor=INK, markersize=7, label="freeze / candidate"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="white", markeredgecolor=INK, markeredgewidth=1.8, markersize=7, label="kill"),
        Line2D([0], [0], marker="^", color="none", markerfacecolor="white", markeredgecolor=INK, markeredgewidth=1.8, markersize=7, label="redesign"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor=INK, markeredgecolor=INK, markersize=7, label="candidate / redesign"),
    ]
    leg1 = ax.legend(
        handles=class_handles,
        loc="upper left",
        bbox_to_anchor=(1.02, 0.98),
        frameon=False,
        title="Hypothesis class",
        fontsize=7.4,
        title_fontsize=7.7,
        handlelength=1.6,
        borderaxespad=0.0,
    )
    ax.add_artist(leg1)
    ax.legend(
        handles=marker_handles,
        loc="upper left",
        bbox_to_anchor=(1.02, 0.55),
        frameon=False,
        title="Decision marker",
        fontsize=7.4,
        title_fontsize=7.7,
        handlelength=1.6,
        borderaxespad=0.0,
    )

    fig.text(
        0.08,
        0.045,
        "Score is an automated representation / predicted-response separability measure, not a p-value or direct neural effect size.",
        ha="left",
        va="center",
        fontsize=7.8,
        color=MUTED,
        style="italic",
    )
    return fig


def write_caption(path: Path, source_data: Path, rows: list[BranchOutcome]) -> None:
    latest = latest_by_branch(rows)
    lines = [
        "# Figure 2. Branch outcome landscape",
        "",
        "Title: Self-driven experiments sort stimulus contrasts into hypothesis classes.",
        "",
        "Claim: The autonomous loop did not produce a single result; it sorted stimulus-contrast branches into one model-tier positive axis, three standard candidate/noisy branches, two packaging-sensitive non-recoveries, and one representation-sensitive redesign candidate.",
        "",
        f"Source data: `{source_data}`",
        "",
        "Rows shown use the latest terminal or current state per branch:",
    ]
    for row in latest:
        lines.append(
            f"- {BRANCH_LABEL[row.branch]}: contrast `{row.contrast}`, score {row.score:g}, decision `{row.decision}`, class `{CLASS_LABEL[row.hypothesis_class]}`."
        )
    lines.extend(
        [
            "",
            "Interpretation boundary: the contrast score is an automated representation / predicted-response separability measure. It is not a p-value and not a direct subject-level neural effect size.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-root", type=Path, default=FIGURE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    source_data = args.figure_root / "data" / "branch_outcomes.csv"
    rows = read_outcomes(source_data)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    fig = make_figure(rows)
    stem = "figure02_branch_outcome_landscape_20260428"
    for ext in ("png", "pdf", "svg"):
        fig.savefig(args.out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_caption(args.out_dir / f"{stem}_caption.md", source_data, rows)

    print(f"Wrote Figure 2 to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
