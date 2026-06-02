#!/usr/bin/env python3
"""Render the Liu/HCP bounded-autoresearch paper-plate figures.

This script intentionally avoids external figure-generation services. It reads
the frozen-pipeline confirmatory artifacts and the wPLI/IllicitDrugUse
validation artifact, then writes a compact five-figure plate:

1. Graphical abstract
2. Evidence-flow alluvial
3. Frozen-pipeline forest scorecard
4. Supported-vs-killed permutation nulls
5. Support-boundary matrix

Default inputs point at the local project artifact tree. Outputs are
deterministic PNG, PDF, SVG, a unified PDF, and a short README.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.path import Path as MplPath
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, PathPatch, Rectangle


DEFAULT_ROOT = Path("/data/brain_researcher/research/predictive/project")

COMPONENT_ORDER = [
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_MentalHealth",
    "ICA_IllicitDrugUse",
]

COMPONENT_SHORT = {
    "ICA_Cognition": "Cognition",
    "ICA_TobaccoUse": "TobaccoUse",
    "ICA_PersonalityEmotion": "PersonalityEmotion",
    "ICA_MentalHealth": "MentalHealth",
    "ICA_IllicitDrugUse": "IllicitDrugUse",
}

STATUS = {
    "ICA_Cognition": "retained",
    "ICA_TobaccoUse": "retained",
    "ICA_PersonalityEmotion": "retained",
    "ICA_MentalHealth": "caveated",
    "ICA_IllicitDrugUse": "downgraded",
}

STATUS_COLOR = {
    "retained": "#1B7F5A",
    "caveated": "#C47A16",
    "downgraded": "#B23B3B",
    "supported": "#1B7F5A",
    "not_done": "#B8BDC7",
    "blocked": "#6B7280",
    "reward": "#31688E",
}

INK = "#172033"
MUTED = "#667085"
GRID = "#D7DEE8"
PANEL_BG = "#F7F8FA"


@dataclass(frozen=True)
class ComponentStats:
    component: str
    observed: float
    fold_std: float
    ci_low: float
    ci_high: float
    r2: float
    ref_mean: float
    ref_best: float
    max_t_p: float
    status: str


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def bootstrap_ci(values: Iterable[float], *, n: int = 1000, seed: int = 12345) -> tuple[float, float]:
    arr = np.asarray(list(values), dtype=float)
    rng = np.random.default_rng(seed)
    means = [rng.choice(arr, size=arr.size, replace=True).mean() for _ in range(n)]
    return tuple(np.percentile(means, [2.5, 97.5]))


def load_data(root: Path) -> tuple[list[ComponentStats], np.ndarray, dict, np.ndarray, dict]:
    confirm_dir = (
        root
        / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
        / "outputs"
        / "confirmatory_family_block_null"
    )
    real = read_json(confirm_dir / "real_result.json")
    summary = read_json(confirm_dir / "confirmatory_permutation_summary.json")
    perms = read_jsonl(confirm_dir / "confirmatory_family_block_perm.jsonl")
    wpli = read_json(
        root
        / "autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139"
        / "outputs"
        / "validation"
        / "wpli_illicit_permutation_1000.json"
    )

    p_by_component = {
        component: float(row["max_t_fwer_plus_one_p"])
        for component, row in summary["per_component"].items()
    }
    per_component_real = {row["component"]: row for row in real["per_component"]}
    stats: list[ComponentStats] = []
    for component in COMPONENT_ORDER:
        row = per_component_real[component]
        ci_low, ci_high = bootstrap_ci(row["per_fold_r"])
        stats.append(
            ComponentStats(
                component=component,
                observed=float(row["fold_mean_r"]),
                fold_std=float(np.std(row["per_fold_r"], ddof=1)),
                ci_low=float(ci_low),
                ci_high=float(ci_high),
                r2=float(row["fold_mean_r"]) ** 2,
                ref_mean=float(row["reference_mean_r"]),
                ref_best=float(row["reference_best_r"]),
                max_t_p=p_by_component[component],
                status=STATUS[component],
            )
        )

    aggregate_null = np.asarray([float(p["aggregate_mean_r"]) for p in perms], dtype=float)
    wpli_null = np.asarray(wpli["perm_fold_mean_r_values"], dtype=float)
    return stats, aggregate_null, summary, wpli_null, wpli


def set_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 240,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 12,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def rounded_box(ax, xy, width, height, text, *, face="white", edge=INK, color=INK,
                fontsize=9, weight="normal", radius=0.03):
    x, y = xy
    patch = FancyBboxPatch(
        (x - width / 2, y - height / 2),
        width,
        height,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        linewidth=1.0,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, color=color, weight=weight)
    return patch


def arrow(ax, start, end, *, color=MUTED, lw=1.3, mutation_scale=13, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            color=color,
            linewidth=lw,
            mutation_scale=mutation_scale,
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def add_panel_label(ax, label: str, title: str) -> None:
    ax.text(0.0, 1.04, label, transform=ax.transAxes, ha="left", va="bottom",
            fontsize=11, weight="bold", color=INK)
    ax.text(0.065, 1.04, title, transform=ax.transAxes, ha="left", va="bottom",
            fontsize=10, color=INK)


def fig01_graphical_abstract() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12.5, 5.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(PANEL_BG)
    fig.suptitle(
        "Figure 1. Discovery lines generate hypotheses; validation calibrates claims",
        x=0.02,
        y=0.98,
        ha="left",
        fontsize=14,
        weight="bold",
        color=INK,
    )

    col_x = [0.18, 0.50, 0.82]
    headers = [
        "Bounded task",
        "Discovery line",
        "Calibrated claim",
    ]
    sublabels = [
        "HCP rs-FC\n5 Liu ICA targets\nfixed references\nexecutable actions",
        "generate hypotheses\nmanage branches\nroute follow-ups\nsend to validation",
        "3 retained\n1 caveated\n1 downgraded\nnot external biomarker",
    ]
    faces = ["#E9F3EE", "#EEF2FF", "#FFF4DF"]
    edges = ["#1B7F5A", "#31688E", "#C47A16"]
    for x, h, sub, fc, ec in zip(col_x, headers, sublabels, faces, edges):
        rounded_box(ax, (x, 0.58), 0.25, 0.42, sub, face=fc, edge=ec, fontsize=12, weight="bold")
        ax.text(x, 0.84, h, ha="center", va="center", fontsize=11, weight="bold", color=INK)

    arrow(ax, (0.31, 0.58), (0.37, 0.58), color=INK, lw=1.6)
    arrow(ax, (0.63, 0.58), (0.69, 0.58), color=INK, lw=1.6)

    tags = [
        (0.18, "bounded task"),
        (0.30, "clear reward"),
        (0.42, "hypothesis cards"),
        (0.54, "branch manager"),
        (0.66, "review gate"),
        (0.78, "validation"),
        (0.90, "claim boundary"),
    ]
    for x, tag in tags:
        rounded_box(ax, (x, 0.19), 0.105, 0.08, tag, face="white", edge=GRID, fontsize=8)
    ax.plot([0.125, 0.955], [0.19, 0.19], color=GRID, linewidth=1.0, zorder=-1)
    ax.text(
        0.5,
        0.065,
        "Discovery proposes and routes; validation determines belief.",
        ha="center",
        va="center",
        fontsize=12,
        color=INK,
        weight="bold",
    )
    return fig


def ribbon(ax, x0, y0, x1, y1, width, color, *, alpha=0.72):
    c = (x1 - x0) * 0.48
    verts = [
        (x0, y0 + width / 2),
        (x0 + c, y0 + width / 2),
        (x1 - c, y1 + width / 2),
        (x1, y1 + width / 2),
        (x1, y1 - width / 2),
        (x1 - c, y1 - width / 2),
        (x0 + c, y0 - width / 2),
        (x0, y0 - width / 2),
        (x0, y0 + width / 2),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.LINETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CLOSEPOLY,
    ]
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color, edgecolor="none", alpha=alpha))


def fig02_evidence_flow(stats: list[ComponentStats]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12.5, 6.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.suptitle(
        "Figure 2. Discovery-line branch management turns reward success into calibrated verdicts",
        x=0.02,
        y=0.98,
        ha="left",
        fontsize=14,
        weight="bold",
        color=INK,
    )

    x_reward, x_discovery, x_validation, x_final = 0.12, 0.39, 0.66, 0.90
    stages = [
        (x_reward, "Exploratory\nreward"),
        (x_discovery, "Discovery line\nbranch manager"),
        (x_validation, "Sensitivity /\nvalidation"),
        (x_final, "Final verdict"),
    ]
    for x, label in stages:
        ax.text(x, 0.88, label, ha="center", va="center", fontsize=10, weight="bold", color=INK)
        ax.plot([x, x], [0.18, 0.82], color=GRID, linewidth=1.0)

    y_reward = dict(zip(COMPONENT_ORDER, [0.72, 0.60, 0.48, 0.36, 0.24]))
    y_discovery = {
        "ICA_Cognition": 0.72,
        "ICA_TobaccoUse": 0.60,
        "ICA_PersonalityEmotion": 0.48,
        "ICA_MentalHealth": 0.36,
        "ICA_IllicitDrugUse": 0.24,
    }
    y_validation = {
        "ICA_Cognition": 0.72,
        "ICA_TobaccoUse": 0.60,
        "ICA_PersonalityEmotion": 0.48,
        "ICA_MentalHealth": 0.35,
        "ICA_IllicitDrugUse": 0.22,
    }
    y_final = y_validation

    for s in stats:
        color = STATUS_COLOR[s.status]
        ribbon(ax, x_reward, y_reward[s.component], x_discovery, y_discovery[s.component], 0.055, STATUS_COLOR["reward"], alpha=0.44)
        ribbon(ax, x_discovery, y_discovery[s.component], x_validation, y_validation[s.component], 0.055, color, alpha=0.58)
        ribbon(ax, x_validation, y_validation[s.component], x_final, y_final[s.component], 0.055, color, alpha=0.78)

    for s in stats:
        name = COMPONENT_SHORT[s.component]
        ax.text(x_reward - 0.035, y_reward[s.component], name, ha="right", va="center", fontsize=8.5, color=INK)
        if s.status == "retained":
            discovery_label = "retain candidate\nFWER p=" + f"{s.max_t_p:.3g}"
        elif s.status == "caveated":
            discovery_label = "caveat branch\nFWER p=" + f"{s.max_t_p:.3g}"
        else:
            discovery_label = "route to kill-test\nunsupported"
        ax.text(
            x_discovery + 0.025,
            y_discovery[s.component],
            discovery_label,
            ha="left",
            va="center",
            fontsize=7.3,
            color=INK,
            linespacing=0.95,
        )
        verdict = "retained" if s.status == "retained" else s.status
        ax.text(x_final + 0.035, y_final[s.component], verdict, ha="left", va="center",
                fontsize=8.5, color=STATUS_COLOR[s.status], weight="bold")

    ax.text(x_reward, 0.10, "5/5 hit_mean\n0/5 hit_best", ha="center", va="center", fontsize=9, color=STATUS_COLOR["reward"], weight="bold")
    ax.text(
        x_discovery,
        0.10,
        "Hypothesis generator\n+ branch manager",
        ha="center",
        va="center",
        fontsize=9,
        color=INK,
        weight="bold",
    )
    ax.text(x_final, 0.10, "Reward is the start.\nVerdict is post-validation.", ha="center", va="center", fontsize=9, color=INK, weight="bold")
    return fig


def fig03_forest_scorecard(stats: list[ComponentStats]) -> plt.Figure:
    fig = plt.figure(figsize=(12.5, 6.0))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.65, 1.0], wspace=0.05)
    ax = fig.add_subplot(gs[0, 0])
    ax_tbl = fig.add_subplot(gs[0, 1])
    fig.suptitle(
        "Figure 3. Frozen-pipeline component evidence under family-block permutation",
        x=0.02,
        y=0.98,
        ha="left",
        fontsize=14,
        weight="bold",
        color=INK,
    )

    y = np.arange(len(stats))[::-1]
    for yi, s in zip(y, stats):
        color = STATUS_COLOR[s.status]
        ax.hlines(yi, s.ci_low, s.ci_high, color=color, linewidth=3.0, alpha=0.82)
        ax.scatter(s.observed, yi, s=60, color=color, edgecolor="white", linewidth=0.8, zorder=3)
        ax.scatter(s.ref_mean, yi - 0.20, s=32, facecolor="white", edgecolor=INK, linewidth=0.9, zorder=3)
        ax.scatter(s.ref_best, yi - 0.20, s=38, marker="x", color=INK, linewidth=1.1, zorder=3)
        ax.text(0.006, yi + 0.18, COMPONENT_SHORT[s.component], ha="left", va="bottom", fontsize=9, color=INK, weight="bold")

    ax.axvline(0, color=GRID, linewidth=1.0)
    ax.set_xlim(-0.13, 0.47)
    ax.set_ylim(-0.65, len(stats) - 0.25)
    ax.set_yticks([])
    ax.set_xlabel("Fold-mean Pearson r with bootstrap 95% CI")
    ax.grid(axis="x", color=GRID, linewidth=0.8, alpha=0.75)
    ax.text(0.29, -0.47, "open dot: Liu ref_mean    x: Liu ref_best", fontsize=8, color=MUTED)

    ax_tbl.axis("off")
    headers = ["max-T p", "R2", "verdict"]
    xcols = [0.04, 0.31, 0.57]
    for x, h in zip(xcols, headers):
        ax_tbl.text(x, 0.90, h, fontsize=9, weight="bold", color=INK, ha="left")
    for idx, s in enumerate(stats):
        yy = 0.78 - idx * 0.15
        color = STATUS_COLOR[s.status]
        ax_tbl.add_patch(Rectangle((0.0, yy - 0.055), 0.94, 0.09, facecolor="#FBFCFD", edgecolor=GRID, linewidth=0.5))
        p_text = "<0.001" if s.max_t_p < 0.0015 else f"{s.max_t_p:.3f}"
        ax_tbl.text(xcols[0], yy, p_text, fontsize=9, color=INK, ha="left", va="center")
        ax_tbl.text(xcols[1], yy, f"{s.r2:.3f}", fontsize=9, color=INK, ha="left", va="center")
        ax_tbl.text(xcols[2], yy, s.status, fontsize=9, color=color, ha="left", va="center", weight="bold")
    ax_tbl.set_xlim(0, 1)
    ax_tbl.set_ylim(0, 1)
    return fig


def plot_null(ax, values: np.ndarray, observed: float, *, title: str, p_text: str, color: str):
    ax.hist(values, bins=38, color="#DDE5EE", edgecolor="white", linewidth=0.5)
    ax.axvline(np.mean(values), color=MUTED, linewidth=1.1, linestyle="--", label="null mean")
    ax.axvline(np.percentile(values, 95), color="#9AA5B1", linewidth=1.1, linestyle=":", label="95th")
    ax.axvline(observed, color=color, linewidth=2.2, label="observed")
    ax.set_title(title, fontsize=10, color=INK, loc="left", weight="bold")
    ax.set_xlabel("Fold-mean r")
    ax.set_ylabel("Permutation count")
    ax.grid(axis="y", color=GRID, alpha=0.55)
    ax.text(0.98, 0.92, p_text, transform=ax.transAxes, ha="right", va="top", fontsize=10, color=color, weight="bold")
    ax.legend(frameon=False, fontsize=7, loc="upper left")


def fig04_permutation_separation(aggregate_null: np.ndarray, summary: dict, wpli_null: np.ndarray, wpli: dict) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2), sharey=False)
    fig.suptitle(
        "Figure 4. Permutation tests separate supported signal from tempting false positives",
        x=0.02,
        y=0.98,
        ha="left",
        fontsize=14,
        weight="bold",
        color=INK,
    )
    aggregate = summary["aggregate_all_five"]
    plot_null(
        axes[0],
        aggregate_null,
        float(aggregate["observed_mean_fold_r"]),
        title="A. Frozen aggregate predictor supported",
        p_text="observed r=0.190\nplus-one p=0.000999",
        color=STATUS_COLOR["retained"],
    )
    plot_null(
        axes[1],
        wpli_null,
        float(wpli["real_fold_mean_r"]),
        title="B. wPLI / IllicitDrugUse lead rejected",
        p_text="observed r=0.046\nplus-one p=0.1998",
        color=STATUS_COLOR["downgraded"],
    )
    axes[0].text(0.02, -0.24, "Positive evidence: frozen pipeline beats family-block null.", transform=axes[0].transAxes,
                 ha="left", va="top", fontsize=8.5, color=INK)
    axes[1].text(0.02, -0.24, "Negative evidence: the KG-generated lead does not survive its null.", transform=axes[1].transAxes,
                 ha="left", va="top", fontsize=8.5, color=INK)
    return fig


def fig05_support_boundary() -> plt.Figure:
    rows = [
        "Aggregate",
        "Cognition",
        "TobaccoUse",
        "PersonalityEmotion",
        "MentalHealth",
        "IllicitDrugUse",
    ]
    cols = [
        "Exploratory\nreward",
        "Frozen-pipeline\ninference",
        "Sensitivity /\nvalidation",
        "Post-selection\ninference",
        "External\nvalidation",
    ]
    state = {
        "Aggregate": ["supported", "supported", "supported", "not_done", "not_done"],
        "Cognition": ["supported", "supported", "supported", "not_done", "not_done"],
        "TobaccoUse": ["supported", "supported", "supported", "not_done", "not_done"],
        "PersonalityEmotion": ["supported", "supported", "supported", "not_done", "not_done"],
        "MentalHealth": ["supported", "caveated", "caveated", "not_done", "not_done"],
        "IllicitDrugUse": ["supported", "downgraded", "downgraded", "not_done", "not_done"],
    }
    color = {
        "supported": STATUS_COLOR["retained"],
        "caveated": STATUS_COLOR["caveated"],
        "downgraded": STATUS_COLOR["downgraded"],
        "not_done": STATUS_COLOR["not_done"],
    }
    label = {
        "supported": "supported",
        "caveated": "caveated",
        "downgraded": "rejected",
        "not_done": "not done",
    }

    fig, ax = plt.subplots(figsize=(12.5, 6.1))
    fig.suptitle(
        "Figure 5. Current support boundary: internally supported, not externally validated",
        x=0.02,
        y=0.98,
        ha="left",
        fontsize=14,
        weight="bold",
        color=INK,
    )
    ax.set_xlim(0, len(cols))
    ax.set_ylim(0, len(rows))
    ax.invert_yaxis()
    ax.set_xticks(np.arange(len(cols)) + 0.5)
    ax.set_xticklabels(cols, fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks(np.arange(len(rows)) + 0.5)
    ax.set_yticklabels(rows, fontsize=9)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for i, row in enumerate(rows):
        for j, col in enumerate(cols):
            s = state[row][j]
            ax.add_patch(Rectangle((j + 0.04, i + 0.08), 0.92, 0.84, facecolor=color[s], edgecolor="white", linewidth=1.4, alpha=0.9))
            txt_color = "white" if s in {"supported", "caveated", "downgraded"} else INK
            ax.text(j + 0.5, i + 0.5, label[s], ha="center", va="center", fontsize=8, color=txt_color, weight="bold")

    ax.text(
        0.0,
        len(rows) + 0.44,
        "Boundary: n=1000 family-block null supports the frozen predictor, but full adaptive-search correction and external cohorts remain open.",
        ha="left",
        va="top",
        fontsize=9,
        color=INK,
    )
    return fig


def save(fig: plt.Figure, out_dir: Path, stem: str) -> list[Path]:
    paths: list[Path] = []
    for ext in ("png", "pdf", "svg"):
        path = out_dir / f"{stem}.{ext}"
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        paths.append(path)
    return paths


def write_readme(out_dir: Path, root: Path, stems: list[str]) -> Path:
    readme = out_dir / "README.md"
    lines = [
        "# Liu/HCP bounded-autoresearch paper-plate figures",
        "",
        "Generated by `scripts/autoresearch/fc/make_liu_paper_plate_figures.py`.",
        "",
        "This plate replaces the broader concept-heavy storyboard with five figures organized by evidence transformation:",
        "",
        "1. Graphical abstract: bounded task -> discovery line -> calibrated claim.",
        "2. Evidence-flow alluvial: the discovery line acts as hypothesis generator and branch manager before validation.",
        "3. Forest scorecard: frozen component effects, bootstrap CI, Liu references, max-T p, R2, verdict.",
        "4. Permutation separation: supported aggregate null beside killed wPLI/IllicitDrugUse null.",
        "5. Support-boundary matrix: what is supported, caveated, rejected, and still not done.",
        "",
        "Data sources:",
        "",
        f"- `{root / 'autoresearch_confirmatory_permutation_line_20260425_shared_null/outputs/confirmatory_family_block_null/real_result.json'}`",
        f"- `{root / 'autoresearch_confirmatory_permutation_line_20260425_shared_null/outputs/confirmatory_family_block_null/confirmatory_permutation_summary.json'}`",
        f"- `{root / 'autoresearch_confirmatory_permutation_line_20260425_shared_null/outputs/confirmatory_family_block_null/confirmatory_family_block_perm.jsonl'}`",
        f"- `{root / 'autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139/outputs/validation/wpli_illicit_permutation_1000.json'}`",
        "",
        "Outputs:",
        "",
    ]
    for stem in stems:
        lines.append(f"- `{stem}.png`, `{stem}.pdf`, `{stem}.svg`")
    lines.append("- `liu_hcp_bounded_autoresearch_paper_plate_20260427.pdf`")
    lines.append("")
    lines.append("No generated figure should be read as external validation or full adaptive-search post-selection correction.")
    readme.write_text("\n".join(lines) + "\n")
    return readme


def build_figures(root: Path, out_dir: Path) -> list[tuple[str, plt.Figure]]:
    stats, aggregate_null, summary, wpli_null, wpli = load_data(root)
    return [
        ("fig01_graphical_abstract", fig01_graphical_abstract()),
        ("fig02_evidence_flow_alluvial", fig02_evidence_flow(stats)),
        ("fig03_component_forest_scorecard", fig03_forest_scorecard(stats)),
        ("fig04_permutation_separation", fig04_permutation_separation(aggregate_null, summary, wpli_null, wpli)),
        ("fig05_support_boundary_matrix", fig05_support_boundary()),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    root = args.root
    out_dir = args.out_dir or root / "figures" / "paper_plate_20260427"
    out_dir.mkdir(parents=True, exist_ok=True)
    set_style()

    figures = build_figures(root, out_dir)
    stems: list[str] = []
    unified = out_dir / "liu_hcp_bounded_autoresearch_paper_plate_20260427.pdf"
    with PdfPages(unified) as pdf:
        for stem, fig in figures:
            save(fig, out_dir, stem)
            pdf.savefig(fig, bbox_inches="tight", facecolor="white")
            stems.append(stem)
            plt.close(fig)
    readme = write_readme(out_dir, root, stems)
    print(f"Wrote {len(stems)} figures to {out_dir}")
    print(f"Wrote unified PDF: {unified}")
    print(f"Wrote README: {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
