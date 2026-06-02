#!/usr/bin/env python3
"""Render the remaining deterministic TRIBE stimulus-discovery figures.

The figures are evidence/story plots derived from the curated discovery ledger
tables under ``docs/operations/figures/data``. They intentionally avoid UMAP or
layer/ROI result claims because those require denser episode-level or neural
target tables than are currently available.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import FixedLocator, NullFormatter


FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")
DEFAULT_OUT_ROOT = FIGURE_ROOT / "remaining_figures_20260428"

INK = "#172033"
MUTED = "#667085"
GRID = "#E3E8EF"
WEAK_BG = "#F3F6FA"
CANDIDATE_BG = "#FFF6E5"
STRONG_BG = "#ECF7F1"
BOUNDARY_RED = "#B54708"

CLASS_LABEL = {
    "real_positive": "robust positive axis",
    "model-tier positive": "model-tier positive axis",
    "candidate_noisy": "candidate / noisy signal",
    "packaging_failure": "packaging-sensitive failure",
}

CLASS_COLOR = {
    "real_positive": "#177D5A",
    "model-tier positive": "#177D5A",
    "candidate_noisy": "#C98200",
    "packaging_failure": "#2D6F94",
    "invalid_or_fix": "#8792A2",
}

BRANCH_LABEL = {
    "HCP language": "HCP Language",
    "IBC ToM": "IBC Theory of Mind",
    "IBC auditory": "IBC Auditory",
    "IBC math": "IBC Math",
    "HCP social": "HCP Social",
    "IBC RSVP": "RSVP Language",
    "IBC biological motion": "Biological Motion",
}


@dataclass(frozen=True)
class BranchOutcome:
    branch: str
    round: int
    contrast: str
    score: float
    diff_norm: float | None
    cosine_gap: float | None
    action: str
    decision: str
    hypothesis_class: str
    claim_level: str


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 300,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def read_branch_outcomes(path: Path) -> list[BranchOutcome]:
    rows: list[BranchOutcome] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            diff_norm = row["diff_norm"].strip()
            cosine_gap = row["cosine_gap"].strip()
            rows.append(
                BranchOutcome(
                    branch=row["branch"],
                    round=int(row["round"]),
                    contrast=row["contrast"],
                    score=float(row["score"]),
                    diff_norm=float(diff_norm) if diff_norm else None,
                    cosine_gap=float(cosine_gap) if cosine_gap else None,
                    action=row["action"],
                    decision=row["decision"],
                    hypothesis_class=row["hypothesis_class"],
                    claim_level=row["claim_level"],
                )
            )
    return rows


def write_caption(path: Path, title: str, claim: str, source: str, boundary: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"Claim: {claim}",
                "",
                f"Source: {source}",
                "",
                f"Interpretation boundary: {boundary}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fmt_score(score: float) -> str:
    if score >= 10:
        return f"{score:.3f}"
    if score >= 0.1:
        return f"{score:.2f}"
    if score >= 0.01:
        return f"{score:.4f}"
    return f"{score:.5f}"


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


def latest_by_branch(rows: list[BranchOutcome]) -> dict[str, BranchOutcome]:
    latest: dict[str, BranchOutcome] = {}
    for row in rows:
        if row.branch not in latest or row.round > latest[row.branch].round:
            latest[row.branch] = row
    return latest


def figure03_branch_trajectories(rows: list[BranchOutcome], out_root: Path) -> None:
    """Figure 3: trajectories, not isolated scores."""
    style()
    latest = latest_by_branch(rows)

    # Auditory item-rotation values come from the curated experiment ledger notes.
    # Other branches use branch_outcomes.csv, with invalid/no-op events plotted as
    # qualitative event markers rather than fabricated scores.
    trajectories = [
        {
            "label": "HCP Language",
            "scores": [15.154, 10.564],
            "events": ["seed", "expanded"],
            "class": "real_positive",
            "note": "freeze",
        },
        {
            "label": "HCP Social",
            "scores": [0.03494, 0.01523],
            "events": ["r1", "follow-up"],
            "class": "packaging_failure",
            "note": "kill",
        },
        {
            "label": "IBC Auditory",
            "scores": [0.19, 0.37, 0.39, 0.74, 0.88, 1.99, 0.30],
            "events": ["rot1", "rot2", "rot3", "rot4", "rot5", "rot6", "rot7"],
            "class": "candidate_noisy",
            "note": "smooth",
        },
        {
            "label": "IBC Math",
            "scores": [latest["IBC math"].score],
            "events": ["fixed"],
            "class": "candidate_noisy",
            "note": "after lexical fix",
        },
        {
            "label": "IBC ToM",
            "scores": [latest["IBC ToM"].score],
            "events": ["question"],
            "class": "candidate_noisy",
            "note": "question contrast",
        },
        {
            "label": "RSVP Language",
            "scores": [latest["IBC RSVP"].score],
            "events": ["collapsed"],
            "class": "packaging_failure",
            "note": "redesign",
        },
        {
            "label": "Biological Motion",
            "scores": [latest["IBC biological motion"].score],
            "events": ["static"],
            "class": "packaging_failure",
            "note": "redesign",
        },
    ]

    fig, axes = plt.subplots(4, 2, figsize=(9.4, 7.0), sharey=False)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.83, bottom=0.12, hspace=0.55, wspace=0.22)

    y_min, y_max = 0.001, 25
    for ax in axes.flat:
        ax.set_yscale("log")
        ax.set_ylim(y_min, y_max)
        ax.yaxis.set_major_locator(FixedLocator([0.001, 0.01, 0.1, 1, 10]))
        ax.yaxis.set_major_formatter(NullFormatter())
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.minorticks_off()
        ax.axhspan(y_min, 0.1, color=WEAK_BG, zorder=0)
        ax.axhspan(0.1, 1.0, color=CANDIDATE_BG, zorder=0)
        ax.axhspan(1.0, y_max, color=STRONG_BG, zorder=0)
        ax.axhline(0.1, color="#CDD5DF", lw=0.8)
        ax.axhline(1.0, color="#CDD5DF", lw=0.8)
        ax.grid(axis="y", color=GRID, lw=0.6, alpha=0.7)
        ax.tick_params(axis="x", labelsize=7.2)
        ax.tick_params(axis="y", labelsize=7.2)

    for ax, traj in zip(axes.flat, trajectories):
        color = CLASS_COLOR[traj["class"]]
        scores = np.asarray(traj["scores"], dtype=float)
        x = np.arange(len(scores))
        if len(scores) > 1:
            ax.plot(x, scores, color=color, lw=2.0, alpha=0.75, zorder=2)
        ax.scatter(x, scores, s=48, color=color, edgecolor="white", linewidth=0.9, zorder=3)
        ax.set_xlim(-0.35, max(len(scores) - 1, 1) + 0.35)
        ax.set_xticks(x)
        ax.set_xticklabels(traj["events"], rotation=0)
        ax.set_title(traj["label"], loc="left", fontsize=8.8, color=color, weight="bold", pad=3)
        ax.text(
            0.98,
            0.86,
            traj["note"],
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=7.4,
            color=color,
            weight="bold",
        )
        if len(scores) == 1:
            ax.text(x[0] + 0.05, scores[0] * 1.12, fmt_score(scores[0]), fontsize=7.0, color=color, weight="bold")
        else:
            ax.text(x[0], scores[0] * 1.12, fmt_score(scores[0]), fontsize=6.7, color=color, ha="center")
            ax.text(x[-1], scores[-1] * 1.12, fmt_score(scores[-1]), fontsize=6.7, color=color, ha="center")

    legend_ax = axes.flat[-1]
    legend_ax.cla()
    legend_ax.axis("off")
    handles = [Line2D([0], [0], color=CLASS_COLOR[k], lw=3, label=v) for k, v in CLASS_LABEL.items()]
    legend_ax.legend(handles=handles, frameon=False, loc="upper left", bbox_to_anchor=(0.02, 0.86), fontsize=8.0)

    axes[1, 0].set_ylabel("contrast score (log scale)")

    fig.text(
        0.08,
        0.935,
        "Figure 3. Hypotheses emerge from branch trajectories, not isolated scores",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Strong clean separation freezes; weak-after-follow-up kills; noisy branches require smoothing or redesign.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.08,
        0.045,
        "Single-point branches mark terminal/current branch states; no-op/fix steps without audited scores are not assigned fake values.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure03_branch_trajectories_20260428"
    stem = "figure03_branch_trajectories_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 3. Branch trajectories",
        "Branch decisions are trajectory-dependent: HCP language freezes, HCP social weakens after follow-up and is killed, and auditory remains noisy rather than cleanly reportable.",
        "branch_outcomes.csv plus curated auditory item-rotation scores from the experiment ledger.",
        "This figure is a branch-decision summary, not a statistical validation plot or direct neural effect-size plot.",
    )


def figure04_score_decomposition(rows: list[BranchOutcome], out_root: Path) -> None:
    """Figure 4: diff_norm x cosine_gap score decomposition."""
    style()
    plotted = [r for r in rows if r.diff_norm is not None and r.cosine_gap is not None]

    fig, ax = plt.subplots(figsize=(8.2, 5.8))
    fig.subplots_adjust(left=0.12, right=0.78, top=0.78, bottom=0.16)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.05, 5)
    ax.set_ylim(0.001, 1)

    x_split = 1.0
    y_split = 0.05
    ax.axvline(x_split, color="#9AA4B2", linestyle="--", linewidth=1)
    ax.axhline(y_split, color="#9AA4B2", linestyle="--", linewidth=1)
    ax.add_patch(Rectangle((x_split, y_split), 5 - x_split, 1 - y_split, color=CLASS_COLOR["real_positive"], alpha=0.06, zorder=0))
    ax.add_patch(Rectangle((x_split, 0.001), 5 - x_split, y_split - 0.001, color=CLASS_COLOR["packaging_failure"], alpha=0.08, zorder=0))
    ax.add_patch(Rectangle((0.05, y_split), x_split - 0.05, 1 - y_split, color=CLASS_COLOR["candidate_noisy"], alpha=0.06, zorder=0))
    ax.add_patch(Rectangle((0.05, 0.001), x_split - 0.05, y_split - 0.001, color="#98A2B3", alpha=0.06, zorder=0))

    xs = np.geomspace(0.05, 5, 240)
    for score in (0.01, 0.1, 1.0):
        ys = score / xs
        mask = (ys >= 0.001) & (ys <= 1)
        ax.plot(xs[mask], ys[mask], color="#7A8699", linestyle=":", linewidth=0.9, alpha=0.7)
        if mask.any():
            i = np.where(mask)[0][-1]
            ax.text(xs[i] * 0.92, ys[i] * 1.08, f"score={score:g}", fontsize=7.2, color="#7A8699", ha="right")

    ax.text(2.5, 0.35, "high distance\nhigh direction", color=CLASS_COLOR["real_positive"], ha="center", va="center", fontsize=8.2, weight="bold")
    ax.text(2.5, 0.006, "directional collapse\nhigh distance, tiny gap", color=CLASS_COLOR["packaging_failure"], ha="center", va="center", fontsize=8.2, weight="bold")
    ax.text(0.2, 0.35, "small but coherent", color=CLASS_COLOR["candidate_noisy"], ha="center", va="center", fontsize=8.2, weight="bold")
    ax.text(0.2, 0.006, "weak / packaging fail", color=MUTED, ha="center", va="center", fontsize=8.2, weight="bold")

    for row in plotted:
        color = CLASS_COLOR[row.hypothesis_class]
        size = 170 + 80 * min(row.score, 1)
        ax.scatter(row.diff_norm, row.cosine_gap, s=size, facecolor="white", edgecolor=color, linewidth=2.4, zorder=4)
        ax.scatter(row.diff_norm, row.cosine_gap, s=45, color=color, zorder=5)
        ax.annotate(
            f"{BRANCH_LABEL.get(row.branch, row.branch)}\nscore={fmt_score(row.score)}",
            xy=(row.diff_norm, row.cosine_gap),
            xytext=(22, 14),
            textcoords="offset points",
            fontsize=8.2,
            color=color,
            weight="bold",
            arrowprops={"arrowstyle": "-", "color": color, "alpha": 0.75},
        )

    ax.set_xlabel("diff_norm (centroid distance, log scale)")
    ax.set_ylabel("cosine_gap (directional separation, log scale)")
    ax.grid(color=GRID, lw=0.7, alpha=0.65)

    fig.text(
        0.08,
        0.935,
        "Figure 4. Low score can mean directional collapse, not zero distance",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Score = diff_norm x max(cosine_gap, 1e-6). HCP Social has distance but almost no stable direction.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.80,
        0.65,
        wrap(
            f"Data availability: {len(plotted)} branch state currently exposes both score components. Other branches need component extraction before fair decomposition.",
            30,
        ),
        ha="left",
        va="center",
        fontsize=7.8,
        color=BOUNDARY_RED,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": BOUNDARY_RED, "linewidth": 0.8},
    )
    fig.text(
        0.08,
        0.045,
        "Component-level decomposition is available for HCP Social follow-up only; missing components are not imputed.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure04_score_decomposition_20260428"
    stem = "figure04_score_decomposition_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 4. Score decomposition",
        "HCP social did not fail because the centroid distance was zero; it failed because directional separation was tiny after a valid follow-up.",
        "branch_outcomes.csv fields diff_norm and cosine_gap.",
        "Only branch states with audited score components are plotted; absent components are not inferred.",
    )


def _condition_palette(conditions: list[str]) -> dict[str, str]:
    palette = [
        "#177D5A",
        "#2D6F94",
        "#C98200",
        "#7C5FB3",
        "#D65F5F",
        "#4E9F9F",
        "#8792A2",
        "#B76E00",
    ]
    return {cond: palette[i % len(palette)] for i, cond in enumerate(conditions)}


def _stacked_condition_bar(ax: plt.Axes, x0: float, y: float, width: float, conditions: dict[str, int], colors: dict[str, str]) -> None:
    total = sum(conditions.values())
    cursor = x0
    for cond, count in conditions.items():
        w = width * count / total if total else 0
        ax.add_patch(Rectangle((cursor, y - 0.15), w, 0.3, facecolor=colors[cond], edgecolor="white", linewidth=0.7))
        if w > 0.42:
            ax.text(cursor + w / 2, y, str(count), ha="center", va="center", fontsize=7, color="white", weight="bold")
        cursor += w


def figure05_condition_signatures(manifest_path: Path, out_root: Path) -> None:
    """Figure 5: manifest signatures before/after follow-up."""
    style()
    panels = json.loads(manifest_path.read_text(encoding="utf-8"))["panels"]
    fig, ax = plt.subplots(figsize=(10.2, 5.9))
    fig.subplots_adjust(left=0.05, right=0.98, top=0.82, bottom=0.14)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.7, len(panels) - 0.2)
    ax.axis("off")

    ax.text(0.16, len(panels) - 0.45, "before", ha="center", va="center", fontsize=8.8, weight="bold", color=INK)
    ax.text(0.49, len(panels) - 0.45, "change", ha="center", va="center", fontsize=8.8, weight="bold", color=INK)
    ax.text(0.78, len(panels) - 0.45, "after", ha="center", va="center", fontsize=8.8, weight="bold", color=INK)

    for i, panel in enumerate(panels[::-1]):
        y = i
        all_conditions = list(dict.fromkeys([*panel["round_a"]["conditions"], *panel["round_b"]["conditions"]]))
        colors = _condition_palette(all_conditions)
        ax.text(0.02, y, panel["branch"], ha="left", va="center", fontsize=9, weight="bold", color=INK)
        _stacked_condition_bar(ax, 0.16, y, 0.22, panel["round_a"]["conditions"], colors)
        _stacked_condition_bar(ax, 0.67, y, 0.22, panel["round_b"]["conditions"], colors)
        ax.text(0.27, y + 0.24, panel["round_a"]["label"], fontsize=7.1, color=MUTED, ha="center")
        ax.text(0.78, y + 0.24, panel["round_b"]["label"], fontsize=7.1, color=MUTED, ha="center")
        arrow_color = BOUNDARY_RED if panel.get("is_no_op") else CLASS_COLOR["real_positive"]
        ax.annotate("", xy=(0.62, y), xytext=(0.40, y), arrowprops={"arrowstyle": "->", "lw": 1.8, "color": arrow_color})
        ax.text(0.51, y + 0.19, "NO-OP" if panel.get("is_no_op") else "real delta", ha="center", va="bottom", fontsize=7.5, weight="bold", color=arrow_color)
        ax.text(0.51, y - 0.23, wrap(panel["delta_note"], 38), ha="center", va="top", fontsize=7.2, color=MUTED)
        legend_x = 0.905
        for j, cond in enumerate(all_conditions[:4]):
            ax.add_patch(Rectangle((legend_x, y + 0.18 - j * 0.13), 0.014, 0.07, facecolor=colors[cond], edgecolor="none"))
            ax.text(legend_x + 0.018, y + 0.215 - j * 0.13, cond, fontsize=6.8, color=MUTED, va="center")

    fig.text(
        0.08,
        0.935,
        "Figure 5. A follow-up only counts if the condition signature changes",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Before/after condition bars show when controller actions became real stimulus interventions.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.08,
        0.045,
        "Counts are condition-signature summaries for interpretability; they are not new validation sample-size claims.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure05_condition_signatures_20260428"
    stem = "figure05_condition_signatures_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 5. Condition signature changes",
        "Real scientific follow-ups require manifest-level condition changes; math, auditory, ToM, and HCP social illustrate corrected or valid deltas.",
        "manifest_deltas.json curated from the experiment ledger.",
        "This is an operational validity figure, not a claim that the corrected branches are fully validated neuroscience findings.",
    )


FINDING_ROWS = [
    (
        "HCP Language",
        "Strong story-vs-math audio separation",
        "Robust auditory language/story axis in current TRIBE evidence",
        "freeze / report",
        "Subject/run-aligned observed HCP LANGUAGE validation; cross-modal text/audio check",
        "real_positive",
    ),
    (
        "HCP Social",
        "Weak after valid follow-up",
        "Current setup misses social-motion axis",
        "kill / redesign",
        "Motion-energy matched social/mechanical videos with motion-aware features",
        "packaging_failure",
    ),
    (
        "IBC Auditory",
        "Nonzero but noisy",
        "Speech/natural-sound axis is sample-sensitive",
        "continue / validate",
        "Larger item budget plus acoustic voice/music/nonspeech controls",
        "candidate_noisy",
    ),
    (
        "IBC Math",
        "Nonzero after lexical fix",
        "Arithmetic principle separable only with lexical controls kept",
        "continue / validate",
        "Difficulty, lexical, visual, and syntactic-control validation",
        "candidate_noisy",
    ),
    (
        "IBC ToM",
        "Question contrast improved interpretability",
        "Belief-vs-physical question axis is more promising than story-only",
        "continue / validate",
        "Matched belief vs physical question battery",
        "candidate_noisy",
    ),
    (
        "RSVP Language",
        "Low under flattened packaging",
        "Timing/probe structure likely lost",
        "redesign",
        "Timing/probe-preserving RSVP trial manifest",
        "packaging_failure",
    ),
    (
        "Biological Motion",
        "Near-zero under current representation",
        "Motion structure not captured by static/motion-poor packaging",
        "redesign",
        "Dynamic intact vs scrambled motion videos with motion-aware representation",
        "packaging_failure",
    ),
]


def figure06_finding_matrix(out_root: Path) -> None:
    """Figure 6: finding -> hypothesis -> next experiment matrix."""
    style()
    n = len(FINDING_ROWS)
    fig, ax = plt.subplots(figsize=(12.0, 6.1))
    fig.subplots_adjust(left=0.035, right=0.99, top=0.83, bottom=0.08)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, n - 0.1)
    ax.axis("off")

    cols = [
        (0.02, 0.14, "Branch"),
        (0.16, 0.31, "Finding"),
        (0.34, 0.52, "Hypothesis"),
        (0.55, 0.66, "Decision"),
        (0.69, 0.98, "Next experiment"),
    ]
    for x0, x1, label in cols:
        ax.text(x0, n - 0.35, label, fontsize=8.8, weight="bold", color=INK, ha="left")

    for i, row in enumerate(FINDING_ROWS[::-1]):
        branch, finding, hypothesis, decision, next_exp, cls = row
        y = i
        color = CLASS_COLOR[cls]
        face = color + "18"
        ax.add_patch(Rectangle((0.0, y - 0.36), 1.0, 0.72, facecolor="#FBFCFE" if i % 2 else "white", edgecolor="none"))
        ax.add_patch(FancyBboxPatch((0.02, y - 0.19), 0.115, 0.38, boxstyle="round,pad=0.015,rounding_size=0.025", facecolor=face, edgecolor=color, linewidth=1.1))
        ax.text(0.077, y, wrap(branch, 14), ha="center", va="center", fontsize=7.8, color=color, weight="bold")
        ax.text(0.16, y, wrap(finding, 28), ha="left", va="center", fontsize=7.7, color=INK)
        ax.text(0.34, y, wrap(hypothesis, 31), ha="left", va="center", fontsize=7.7, color=INK)
        ax.text(0.55, y, wrap(decision, 16), ha="left", va="center", fontsize=7.7, color=color, weight="bold")
        ax.text(0.69, y, wrap(next_exp, 42), ha="left", va="center", fontsize=7.7, color=INK)

    fig.text(
        0.08,
        0.935,
        "Figure 6. The loop output is a hypothesis map, not just a score table",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Each branch is mapped from finding to bounded hypothesis, terminal decision, and next experiment.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )

    out_dir = out_root / "figure06_finding_hypothesis_matrix_20260428"
    stem = "figure06_finding_hypothesis_matrix_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 6. Finding-hypothesis-next experiment matrix",
        "The discovery loop produces bounded hypothesis classes and concrete next experiments, not only raw branch scores.",
        "Curated synthesis of branch_outcomes.csv, manifest_deltas.json, and locked follow-up manifest specs.",
        "Hypotheses in this matrix remain bounded by the validation status described in the report.",
    )


ROADMAP_ROWS = [
    ("HCP Language", "real_positive", [2, 2, 2, 0, 0, 1, 2]),
    ("HCP Social", "packaging_failure", [0, 2, 0, 0, 2, 1, 1]),
    ("IBC Auditory", "candidate_noisy", [1, 2, 0, 0, 0, 2, 1]),
    ("IBC Math", "candidate_noisy", [1, 2, 0, 0, 0, 1, 1]),
    ("IBC ToM", "candidate_noisy", [1, 2, 0, 0, 0, 1, 1]),
    ("RSVP Language", "packaging_failure", [0, 1, 0, 2, 0, 1, 1]),
    ("Biological Motion", "packaging_failure", [0, 2, 0, 0, 2, 1, 1]),
]

ROADMAP_COLS = [
    "replicate",
    "matched\ncontrols",
    "cross-modal",
    "preserve\ntiming",
    "motion-aware\nfeatures",
    "larger N /\nsmoothing",
    "layer/ROI/\nfMRI bridge",
]


def figure07_redesign_roadmap(out_root: Path) -> None:
    """Figure 7: next-experiment design priorities."""
    style()
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    fig.subplots_adjust(left=0.16, right=0.98, top=0.80, bottom=0.17)
    n_rows = len(ROADMAP_ROWS)
    n_cols = len(ROADMAP_COLS)
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(-0.5, n_rows - 0.5)
    ax.invert_yaxis()

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(ROADMAP_COLS)
    ax.xaxis.tick_top()
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([r[0] for r in ROADMAP_ROWS])
    ax.tick_params(axis="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for y in range(n_rows):
        for x in range(n_cols):
            ax.add_patch(Rectangle((x - 0.5, y - 0.5), 1, 1, facecolor="#FBFCFE" if (x + y) % 2 else "white", edgecolor=GRID, linewidth=0.7, zorder=0))

    for y, (_, cls, values) in enumerate(ROADMAP_ROWS):
        color = CLASS_COLOR[cls]
        for x, value in enumerate(values):
            if value == 0:
                ax.scatter(x, y, s=22, facecolor="white", edgecolor="#D0D5DD", linewidth=0.8, zorder=2)
            elif value == 1:
                ax.scatter(x, y, s=78, facecolor=color + "55", edgecolor=color, linewidth=1.0, zorder=3)
            else:
                ax.scatter(x, y, s=170, facecolor=color, edgecolor="white", linewidth=1.0, zorder=4)

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#172033", markeredgecolor="white", markersize=8, label="priority"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#98A2B355", markeredgecolor="#667085", markersize=6, label="useful"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="white", markeredgecolor="#D0D5DD", markersize=5, label="not primary"),
    ]
    ax.legend(handles=handles, frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.20), ncol=3, fontsize=7.7)

    fig.text(
        0.08,
        0.935,
        "Figure 7. Autonomous findings become a stimulus redesign roadmap",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Priorities distinguish replication, controls, temporal structure, motion-aware features, and neural-validation bridges.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.08,
        0.045,
        "Dots encode recommended next-experiment priorities, not completed evidence.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure07_redesign_roadmap_20260428"
    stem = "figure07_redesign_roadmap_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 7. Stimulus redesign roadmap",
        "Positive, noisy, and packaging-sensitive branches imply different next experiments rather than a single rerun policy.",
        "Curated synthesis of branch outcome classes and locked follow-up manifest specs.",
        "The roadmap is a plan/prioritization surface, not evidence that these future experiments have already run.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-root", type=Path, default=FIGURE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    source_data = args.figure_root / "data"
    branch_rows = read_branch_outcomes(source_data / "branch_outcomes.csv")
    manifest_path = source_data / "manifest_deltas.json"

    figure03_branch_trajectories(branch_rows, args.out_root)
    figure04_score_decomposition(branch_rows, args.out_root)
    figure05_condition_signatures(manifest_path, args.out_root)
    figure06_finding_matrix(args.out_root)
    figure07_redesign_roadmap(args.out_root)

    print(f"Wrote Figures 3-7 to {args.out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
