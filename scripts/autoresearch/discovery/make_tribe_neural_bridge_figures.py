#!/usr/bin/env python3
"""Render neural-bridge figures for the TRIBE stimulus-discovery line.

These figures are deliberately conservative. They map discovered stimulus
branches to predicted-response evidence tiers and ROI systems to test next, but
they do not render observed activation maps because subject/run-aligned HCP
LANGUAGE observed fMRI targets are not present in the current artifacts.
"""

from __future__ import annotations

import argparse
import csv
import os
import textwrap
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Rectangle


FIGURE_ROOT = Path("/data/brain_researcher/research/discovery/docs/operations/figures")
DEFAULT_OUT_ROOT = FIGURE_ROOT / "neural_bridge_figures_20260428"

INK = "#172033"
MUTED = "#667085"
GRID = "#E3E8EF"
GREEN = "#177D5A"
AMBER = "#C98200"
BLUE = "#2D6F94"
RED = "#B54708"
GRAY = "#98A2B3"
LIGHT = "#F8FAFC"

CLASS_COLOR = {
    "real_positive": GREEN,
    "model-tier positive": GREEN,
    "candidate_noisy": AMBER,
    "packaging_failure": BLUE,
}


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


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_figure(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out_dir / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)


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


def _status_color(status: str) -> str:
    if status in {"done_strong", "done_significant", "supported"}:
        return GREEN
    if status in {"candidate", "planned"}:
        return AMBER
    if status in {"done_not_stable", "negative_in_setup", "not_recovered"}:
        return BLUE
    if status in {"missing", "not_done"}:
        return RED
    return GRAY


def figure08_neural_validation_ladder(evidence_rows: list[dict[str, str]], out_root: Path) -> None:
    """Figure 8: neural evidence ladder and claim boundary."""
    style()
    fig, ax = plt.subplots(figsize=(10.6, 6.3))
    fig.subplots_adjust(left=0.08, right=0.98, top=0.80, bottom=0.13)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(evidence_rows) - 0.4)
    ax.axis("off")

    x0, x1 = 0.08, 0.88
    y_positions = np.arange(len(evidence_rows))[::-1]
    ax.plot([x0, x1], [y_positions[0], y_positions[-1]], alpha=0)

    # Vertical ladder backbone.
    ax.plot([0.19, 0.19], [y_positions[-1], y_positions[0]], color=GRID, lw=3, zorder=0)

    for y, row in zip(y_positions, evidence_rows):
        status = row["status"]
        color = _status_color(status)
        is_missing = status == "missing"
        face = "white" if is_missing else color
        ax.scatter(0.19, y, s=180, facecolor=face, edgecolor=color, linewidth=2.2, zorder=3)
        label = row["label"]
        p_label = row["p_label"]
        score = row["score"]
        p_value = row["p_value"]
        note_bits = []
        if score:
            note_bits.append(f"score/r={score}")
        if p_value:
            note_bits.append(f"p={p_value}")
        if p_label:
            note_bits.append(p_label)
        if row["note"]:
            note_bits.append(row["note"])
        note = "; ".join(note_bits)
        ax.text(0.25, y + 0.12, label, ha="left", va="center", fontsize=9.0, color=INK, weight="bold")
        ax.text(0.25, y - 0.18, wrap(note, 50), ha="left", va="center", fontsize=7.4, color=MUTED)
        ax.text(
            0.06,
            y,
            "missing" if is_missing else ("not stable" if status == "done_not_stable" else "done"),
            ha="right",
            va="center",
            fontsize=7.5,
            color=color,
            weight="bold",
        )

    # Evidence regions.
    ax.add_patch(
        FancyBboxPatch(
            (0.58, 4.55),
            0.34,
            2.95,
            boxstyle="round,pad=0.025,rounding_size=0.03",
            facecolor="#ECF7F1",
            edgecolor=GREEN,
            linewidth=1.1,
        )
    )
    ax.text(0.75, 6.05, "current support", ha="center", va="center", fontsize=10, color=GREEN, weight="bold")
    ax.text(0.75, 5.48, "item/model-feature\nand late-layer evidence", ha="center", va="center", fontsize=8.0, color=GREEN)

    ax.add_patch(
        FancyBboxPatch(
            (0.58, 1.55),
            0.34,
            1.9,
            boxstyle="round,pad=0.025,rounding_size=0.03",
            facecolor="#EFF6FB",
            edgecolor=BLUE,
            linewidth=1.1,
        )
    )
    ax.text(0.75, 2.75, "bridge not closed", ha="center", va="center", fontsize=10, color=BLUE, weight="bold")
    ax.text(0.75, 2.25, "predicted-fMRI fold\nstability was negative", ha="center", va="center", fontsize=8.0, color=BLUE)

    ax.add_patch(
        FancyBboxPatch(
            (0.58, -0.25),
            0.34,
            1.0,
            boxstyle="round,pad=0.025,rounding_size=0.03",
            facecolor="#FFF7ED",
            edgecolor=RED,
            linewidth=1.1,
        )
    )
    ax.text(0.75, 0.25, "observed fMRI missing", ha="center", va="center", fontsize=9.5, color=RED, weight="bold")

    fig.text(
        0.08,
        0.935,
        "Figure 8. Neural claim boundary for HCP language",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "The strongest current claim is item-level model-feature / predicted-response evidence; observed subject-level fMRI remains open.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.08,
        0.045,
        "Do not interpret this ladder as an observed activation map. It shows which neural-evidence tiers are complete, unstable, or missing.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure08_neural_validation_ladder_20260428"
    stem = "figure08_neural_validation_ladder_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 8. Neural validation ladder",
        "HCP language has strong item/model-feature and late-layer evidence, but the predicted-fMRI fold bridge is not stable and observed subject-level fMRI validation is missing.",
        "hcp_language_evidence.csv.",
        "This is a validation-tier figure, not an observed fMRI activation map.",
    )


ROI_COLUMNS = [
    "Auditory\nSTG/STS",
    "Language\nnetwork",
    "Frontoparietal\n/ IPS",
    "TPJ / mPFC\nToM",
    "pSTS social\nmotion",
    "hMT+/visual\nmotion",
    "Task timing\n/control",
]

ROI_ROWS = [
    ("HCP Language", "real_positive", [2, 2, 1, 0, 0, 0, 1], "story vs math audio"),
    ("HCP Social", "packaging_failure", [0, 0, 0, 2, 2, 2, 1], "social vs mechanical motion"),
    ("IBC Auditory", "candidate_noisy", [2, 0, 0, 0, 0, 0, 1], "speech vs sound controls"),
    ("IBC Math", "candidate_noisy", [0, 1, 2, 0, 0, 0, 1], "arithmetic with lexical controls"),
    ("IBC ToM", "candidate_noisy", [0, 0, 0, 2, 0, 0, 1], "belief vs physical question"),
    ("RSVP Language", "packaging_failure", [0, 2, 0, 0, 0, 0, 2], "timing/probe-preserving rerun"),
    ("Biological Motion", "packaging_failure", [0, 0, 0, 0, 1, 2, 1], "intact vs scrambled dynamic motion"),
]


def figure09_roi_target_map(out_root: Path) -> None:
    """Figure 9: ROI systems to test next, not confirmed activation."""
    style()
    fig, ax = plt.subplots(figsize=(11.0, 6.1))
    fig.subplots_adjust(left=0.18, right=0.98, top=0.79, bottom=0.18)
    n_rows = len(ROI_ROWS)
    n_cols = len(ROI_COLUMNS)
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(-0.5, n_rows - 0.5)
    ax.invert_yaxis()

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(ROI_COLUMNS)
    ax.xaxis.tick_top()
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([row[0] for row in ROI_ROWS])
    ax.tick_params(axis="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for y in range(n_rows):
        for x in range(n_cols):
            ax.add_patch(
                Rectangle(
                    (x - 0.5, y - 0.5),
                    1,
                    1,
                    facecolor=LIGHT if (x + y) % 2 else "white",
                    edgecolor=GRID,
                    linewidth=0.7,
                    zorder=0,
                )
            )

    for y, (_, cls, values, note) in enumerate(ROI_ROWS):
        color = CLASS_COLOR[cls]
        ax.text(-0.56, y + 0.30, note, ha="right", va="center", fontsize=6.8, color=MUTED)
        for x, value in enumerate(values):
            if value == 0:
                ax.scatter(x, y, s=18, facecolor="white", edgecolor="#D0D5DD", linewidth=0.8, zorder=2)
            elif value == 1:
                ax.scatter(x, y, s=72, facecolor=color + "45", edgecolor=color, linewidth=1.0, zorder=3)
            else:
                ax.scatter(x, y, s=150, facecolor=color, edgecolor="white", linewidth=1.0, zorder=4)

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=INK, markeredgecolor="white", markersize=7.5, label="primary target"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#98A2B355", markeredgecolor="#667085", markersize=6.0, label="secondary target"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="white", markeredgecolor="#D0D5DD", markersize=5.0, label="not primary"),
    ]
    ax.legend(handles=handles, frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.22), ncol=3, fontsize=7.8)

    fig.text(
        0.08,
        0.935,
        "Figure 9. Branch hypotheses map to ROI systems to test next",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "Dots are predeclared neural target systems for future validation, not observed activation strengths.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.08,
        0.045,
        "ROI targets are hypothesis targets derived from task constructs and report notes; no ROI-level subject fMRI statistic has been computed here.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure09_roi_target_map_20260428"
    stem = "figure09_roi_target_map_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 9. ROI target map",
        "The branch outcomes imply ROI systems to test next, especially auditory/language targets for HCP language and pSTS/TPJ/mPFC/motion targets for social and biological-motion redesigns.",
        "Curated branch outcomes plus report-specified ROI target families.",
        "Dots indicate target systems for future validation, not observed activation or ROI-level statistical significance.",
    )


CLAIM_ROWS = [
    ("HCP Language", "real_positive", ["supported", "supported", "supported", "not_recovered", "missing"], "robust item-level hypothesis; neural upgrade open"),
    ("HCP Social", "packaging_failure", ["not_recovered", "not_recovered", "not_done", "not_done", "missing"], "negative in current pipeline; redesign before neural claim"),
    ("IBC Auditory", "candidate_noisy", ["candidate", "candidate", "not_done", "not_done", "missing"], "candidate; needs acoustic/ROI validation"),
    ("IBC Math", "candidate_noisy", ["candidate", "candidate", "not_done", "not_done", "missing"], "candidate after lexical fix"),
    ("IBC ToM", "candidate_noisy", ["candidate", "candidate", "not_done", "not_done", "missing"], "question contrast candidate"),
    ("RSVP Language", "packaging_failure", ["not_recovered", "not_recovered", "not_done", "not_done", "missing"], "packaging failure; timing-preserving rerun"),
    ("Biological Motion", "packaging_failure", ["not_recovered", "not_recovered", "not_done", "not_done", "missing"], "motion-aware representation needed"),
]

CLAIM_COLS = [
    "model-feature\nseparation",
    "predicted-response\nseparation",
    "layer-family\nsupport",
    "predicted-fMRI\nfold bridge",
    "observed fMRI\nROI/subject",
]

STATUS_LABEL = {
    "supported": "supported",
    "candidate": "candidate",
    "not_recovered": "not recovered",
    "not_done": "not done",
    "missing": "missing",
}


def figure10_hypothesis_neural_status(out_root: Path) -> None:
    """Figure 10: hypothesis outcome x neural claim status matrix."""
    style()
    fig, ax = plt.subplots(figsize=(11.0, 5.9))
    fig.subplots_adjust(left=0.18, right=0.98, top=0.80, bottom=0.17)
    n_rows = len(CLAIM_ROWS)
    n_cols = len(CLAIM_COLS)
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(-0.5, n_rows - 0.5)
    ax.invert_yaxis()
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(CLAIM_COLS)
    ax.xaxis.tick_top()
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([row[0] for row in CLAIM_ROWS])
    ax.tick_params(axis="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for y in range(n_rows):
        for x in range(n_cols):
            ax.add_patch(Rectangle((x - 0.5, y - 0.5), 1, 1, facecolor=LIGHT if (x + y) % 2 else "white", edgecolor=GRID, linewidth=0.7, zorder=0))

    for y, (_, cls, statuses, note) in enumerate(CLAIM_ROWS):
        ax.text(-0.56, y + 0.30, note, ha="right", va="center", fontsize=6.8, color=MUTED)
        for x, status in enumerate(statuses):
            color = _status_color(status)
            if status in {"missing", "not_done"}:
                ax.scatter(x, y, s=92, marker="s", facecolor="white", edgecolor=color, linewidth=1.7, zorder=3)
            elif status == "not_recovered":
                ax.scatter(x, y, s=112, marker="x", color=color, linewidth=2.2, zorder=4)
            else:
                face = color if status == "supported" else color + "55"
                ax.scatter(x, y, s=150 if status == "supported" else 100, marker="o", facecolor=face, edgecolor=color, linewidth=1.1, zorder=4)
            ax.text(x, y + 0.28, STATUS_LABEL[status], ha="center", va="center", fontsize=5.9, color=color)

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=GREEN, markeredgecolor=GREEN, markersize=7.5, label="supported"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=AMBER + "55", markeredgecolor=AMBER, markersize=7.0, label="candidate"),
        Line2D([0], [0], marker="x", color=BLUE, markersize=7.0, label="not recovered"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="white", markeredgecolor=RED, markersize=7.0, label="missing/not done"),
    ]
    ax.legend(handles=handles, frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.20), ncol=4, fontsize=7.8)

    fig.text(
        0.08,
        0.935,
        "Figure 10. Hypothesis outcomes and neural claim status",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.08,
        0.895,
        "The loop found branch-level hypotheses, but most neural/ROI tiers remain future validation work.",
        ha="left",
        va="top",
        fontsize=8.6,
        color=MUTED,
    )
    fig.text(
        0.08,
        0.045,
        "Matrix separates discovered hypotheses from neural confirmation. Missing observed fMRI means no subject-level activation claim yet.",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure10_hypothesis_neural_status_20260428"
    stem = "figure10_hypothesis_neural_status_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 10. Hypothesis neural-status matrix",
        "HCP language is supported at model-feature/predicted-response/layer-family tiers, while subject-level observed fMRI and most branch-level ROI claims remain missing or not done.",
        "Curated synthesis of branch_outcomes.csv, hcp_language_evidence.csv, and report claim boundaries.",
        "This matrix confirms hypothesis and evidence status; it does not provide new observed neural evidence.",
    )


BOUNDARY_CELLS = [
    (
        "Item-level\nvalidation",
        "supported",
        "expanded + held-out\npermutation checks",
        "supports H1 as a\nmodel-feature finding",
    ),
    (
        "Layer-family\nconfirmation",
        "supported",
        "late encoder > early\nand projector features",
        "supports the locked\nrepresentation family",
    ),
    (
        "Predicted-response\nfold bridge",
        "rejected",
        "expanded20 vs heldout21\nr = 0.098, p = 0.449",
        "blocks neural-map\nupgrade",
    ),
    (
        "Barch-2013\ngroup-map gate",
        "blocked",
        "preflight ready;\ngroup map missing",
        "cheap Sec. 5.1 test\nnot yet run",
    ),
    (
        "Observed subject\nfMRI validation",
        "missing",
        "requires subject/run\nHCP LANGUAGE targets",
        "Sec. 5.2 only if\nSec. 5.1 passes",
    ),
]

BOUNDARY_STATUS = {
    "supported": (GREEN, "#ECFDF3", "SUPPORTED"),
    "rejected": (BLUE, "#EFF6FB", "REJECTED"),
    "blocked": (AMBER, "#FFFAEB", "BLOCKED"),
    "missing": (RED, "#FFF1F3", "MISSING"),
}


def figure14_hcp_support_boundary(out_root: Path) -> None:
    """Figure 14: compact support-boundary cells for the HCP worked example."""
    style()
    fig, ax = plt.subplots(figsize=(11.0, 3.7))
    fig.subplots_adjust(left=0.035, right=0.99, top=0.76, bottom=0.18)
    ax.set_xlim(0, len(BOUNDARY_CELLS))
    ax.set_ylim(0, 1)
    ax.axis("off")

    for idx, (title, status, evidence, consequence) in enumerate(BOUNDARY_CELLS):
        color, face, status_label = BOUNDARY_STATUS[status]
        ax.add_patch(
            FancyBboxPatch(
                (idx + 0.05, 0.10),
                0.90,
                0.78,
                boxstyle="round,pad=0.025,rounding_size=0.035",
                facecolor=face,
                edgecolor=color,
                linewidth=1.4,
            )
        )
        ax.text(idx + 0.50, 0.80, title, ha="center", va="top", fontsize=9.0, color=INK, weight="bold")
        ax.text(idx + 0.50, 0.61, status_label, ha="center", va="center", fontsize=7.2, color=color, weight="bold")
        ax.text(idx + 0.50, 0.44, evidence, ha="center", va="center", fontsize=7.3, color=INK, linespacing=1.15)
        ax.text(idx + 0.50, 0.22, consequence, ha="center", va="center", fontsize=6.9, color=MUTED, linespacing=1.12)
        if idx < len(BOUNDARY_CELLS) - 1:
            ax.annotate(
                "",
                xy=(idx + 1.02, 0.49),
                xytext=(idx + 0.95, 0.49),
                arrowprops={"arrowstyle": "->", "color": GRAY, "lw": 1.1},
            )

    fig.text(
        0.035,
        0.94,
        "Figure 14. HCP language support boundary after the cheap-tier audit",
        ha="left",
        va="top",
        fontsize=12.5,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.035,
        0.885,
        "The worked-example brain claim is supported at item/model tiers, rejected at the predicted-map bridge, and blocked before observed fMRI until Sec. 5.1 assets are supplied.",
        ha="left",
        va="top",
        fontsize=8.4,
        color=MUTED,
    )
    fig.text(
        0.035,
        0.055,
        "This boundary matrix is a claim-status figure. It intentionally separates model-feature support, cheap-gate readiness, and missing subject-level neural validation.",
        ha="left",
        va="center",
        fontsize=7.4,
        color=MUTED,
        style="italic",
    )

    out_dir = out_root / "figure14_hcp_language_support_boundary_20260428"
    stem = "figure14_hcp_language_support_boundary_20260428"
    save_figure(fig, out_dir, stem)
    write_caption(
        out_dir / f"{stem}_caption.md",
        "Figure 14. HCP language support boundary",
        "The HCP language worked example is supported by item-level and layer-family evidence, but the predicted-response fold bridge is negative and observed fMRI validation remains gated by the Barch-2013 group-map test.",
        "Curated synthesis of the validation ladder, fold-stability rerun, and Sec. 5.1 preflight status.",
        "This is a claim-status matrix, not new neural evidence.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure-root", type=Path, default=FIGURE_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    source_data = args.figure_root / "data"
    evidence_rows = read_csv(source_data / "hcp_language_evidence.csv")

    figure08_neural_validation_ladder(evidence_rows, args.out_root)
    figure09_roi_target_map(args.out_root)
    figure10_hypothesis_neural_status(args.out_root)
    figure14_hcp_support_boundary(args.out_root)

    print(f"Wrote neural bridge Figures 8-10 and 14 to {args.out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
