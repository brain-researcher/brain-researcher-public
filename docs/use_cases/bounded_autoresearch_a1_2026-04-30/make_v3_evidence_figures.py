#!/usr/bin/env python3
"""Generate v3 manuscript evidence figures for the bounded-autoresearch report.

The v3 plate intentionally avoids another broad conceptual schematic. It uses
deterministic, on-disk artifacts to produce the report-facing evidence figures:

- Fig. 2: evidence flow from reward success to final component verdicts
- Fig. 3: frozen-pipeline component forest scorecard
- Fig. 4: permutation support versus KG-lead rejection
- Fig. 5: current support-boundary matrix

Outputs are written as both PNG and PDF under ``figures/v3``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patches
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch


ROOT = Path("/data/brain_researcher/research/predictive/project")
OUT_DIR = ROOT / "figures" / "v3"
CONFIRM_DIR = (
    ROOT
    / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
    / "outputs"
    / "confirmatory_family_block_null"
)
CONFIRM_REAL = CONFIRM_DIR / "real_result.json"
CONFIRM_SUMMARY = CONFIRM_DIR / "confirmatory_permutation_summary.json"
CONFIRM_PERMS = CONFIRM_DIR / "confirmatory_family_block_perm.jsonl"
WPLI_VALIDATION = (
    ROOT
    / "autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139"
    / "outputs"
    / "validation"
    / "wpli_illicit_permutation_1000.json"
)


COLORS = {
    "text": "#111827",
    "muted": "#64748b",
    "grid": "#e5e7eb",
    "line": "#cbd5e1",
    "supported": "#2ca02c",
    "caveated": "#ff7f0e",
    "rejected": "#d62728",
    "blocked": "#7f7f7f",
}

COMPONENTS = [
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_MentalHealth",
    "ICA_IllicitDrugUse",
]

SHORT = {
    "ICA_Cognition": "Cognition",
    "ICA_TobaccoUse": "TobaccoUse",
    "ICA_PersonalityEmotion": "PersonalityEmotion",
    "ICA_MentalHealth": "MentalHealth",
    "ICA_IllicitDrugUse": "IllicitDrugUse",
}

COMP_COLORS = {
    "ICA_Cognition": "#0072B2",
    "ICA_TobaccoUse": "#009E73",
    "ICA_PersonalityEmotion": "#CC79A7",
    "ICA_MentalHealth": "#E69F00",
    "ICA_IllicitDrugUse": "#D55E00",
}

VERDICTS = {
    "ICA_Cognition": ("retained", COLORS["supported"]),
    "ICA_TobaccoUse": ("retained", COLORS["supported"]),
    "ICA_PersonalityEmotion": ("retained", COLORS["supported"]),
    "ICA_MentalHealth": ("caveated", COLORS["caveated"]),
    "ICA_IllicitDrugUse": ("downgraded", COLORS["rejected"]),
}

# Bootstrap 95% CIs over the ten fold-level r values, generated with seed=12345
# and documented in the report's fused headline table.
BOOT_CI = {
    "ICA_Cognition": (0.3229, 0.4260),
    "ICA_TobaccoUse": (0.1913, 0.3438),
    "ICA_PersonalityEmotion": (0.0763, 0.2412),
    "ICA_MentalHealth": (0.0362, 0.2082),
    "ICA_IllicitDrugUse": (-0.1038, 0.1392),
}


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.5,
            "axes.titlesize": 8.5,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
        }
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def save_figure(fig: plt.Figure, stem: str) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUT_DIR / f"{stem}.png"
    pdf = OUT_DIR / f"{stem}.pdf"
    fig.savefig(png, dpi=450, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(png)
    print(pdf)
    return {"png": str(png), "pdf": str(pdf)}


def component_entries(real: dict) -> list[dict]:
    by_name = {entry["component"]: entry for entry in real["per_component"]}
    return [by_name[name] for name in COMPONENTS]


def p_text(value: float) -> str:
    if value <= 0.0015:
        return "0.001"
    return f"{value:.3f}"


def smooth_ribbon(ax, x0: float, y0: float, x1: float, y1: float, color: str, lw: float = 7.0) -> None:
    dx = x1 - x0
    verts = [
        (x0, y0),
        (x0 + 0.45 * dx, y0),
        (x1 - 0.45 * dx, y1),
        (x1, y1),
    ]
    path = MplPath(verts, [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4])
    patch = PathPatch(
        path,
        facecolor="none",
        edgecolor=color,
        lw=lw,
        alpha=0.50,
        capstyle="round",
        joinstyle="round",
        zorder=1,
    )
    ax.add_patch(patch)


def rounded_label(
    ax,
    x: float,
    y: float,
    text: str,
    edge: str,
    face: str = "white",
    width: float = 0.16,
    height: float = 0.070,
    fontsize: float = 6.7,
    weight: str = "normal",
) -> None:
    ax.add_patch(
        patches.FancyBboxPatch(
            (x - width / 2, y - height / 2),
            width,
            height,
            boxstyle="round,pad=0.010,rounding_size=0.015",
            facecolor=face,
            edgecolor=edge,
            lw=1.0,
            zorder=4,
        )
    )
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight=weight,
        color=COLORS["text"],
        zorder=5,
    )


def make_fig02_evidence_flow() -> dict[str, str]:
    real = read_json(CONFIRM_REAL)
    summary = read_json(CONFIRM_SUMMARY)
    entries = component_entries(real)
    component_y = {
        "ICA_Cognition": 0.80,
        "ICA_TobaccoUse": 0.65,
        "ICA_PersonalityEmotion": 0.50,
        "ICA_MentalHealth": 0.35,
        "ICA_IllicitDrugUse": 0.20,
    }
    xs = {
        "components": 0.08,
        "reward": 0.33,
        "inference": 0.60,
        "verdict": 0.88,
    }

    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0.06, 0.96)
    ax.axis("off")

    headings = [
        ("components", "Five targets"),
        ("reward", "Benchmark reward"),
        ("inference", "Frozen + validation"),
        ("verdict", "Internal verdict"),
    ]
    for key, title in headings:
        ax.text(
            xs[key],
            0.93,
            title,
            ha="center",
            va="center",
            fontsize=8.2,
            fontweight="bold",
            color=COLORS["text"],
        )
        ax.plot([xs[key], xs[key]], [0.13, 0.88], color=COLORS["line"], lw=0.8, zorder=0)

    for entry in entries:
        comp = entry["component"]
        y = component_y[comp]
        color = COMP_COLORS[comp]
        smooth_ribbon(ax, xs["components"], y, xs["reward"], y, color)
        smooth_ribbon(ax, xs["reward"], y, xs["inference"], y, color)
        smooth_ribbon(ax, xs["inference"], y, xs["verdict"], y, color)
        ax.scatter(xs["components"], y, s=52, color=color, edgecolor="white", lw=0.8, zorder=6)
        ax.text(xs["components"] - 0.026, y, SHORT[comp], ha="right", va="center", fontsize=7.4, color=COLORS["text"])

    ax.add_patch(
        patches.FancyBboxPatch(
            (xs["reward"] - 0.092, 0.17),
            0.184,
            0.66,
            boxstyle="round,pad=0.013,rounding_size=0.018",
            facecolor="#f8fafc",
            edgecolor="#94a3b8",
            lw=1.0,
            zorder=2,
        )
    )
    ax.text(
        xs["reward"],
        0.50,
        "Benchmark\nmean-vs-mean: 5/5\nbest-vs-best: 5/5",
        ha="center",
        va="center",
        fontsize=6.8,
        fontweight="bold",
        color=COLORS["text"],
        zorder=6,
    )

    status = {
        "ICA_Cognition": "max-T p=0.001",
        "ICA_TobaccoUse": "max-T p=0.001",
        "ICA_PersonalityEmotion": "max-T p=0.018",
        "ICA_MentalHealth": "positive,\ncaveated",
        "ICA_IllicitDrugUse": "unsupported\n+ wPLI killed",
    }
    for entry in entries:
        comp = entry["component"]
        y = component_y[comp]
        verdict, verdict_col = VERDICTS[comp]
        rounded_label(
            ax,
            xs["inference"],
            y,
            status[comp],
            edge=verdict_col,
            width=0.150,
            height=0.076 if "\n" in status[comp] else 0.058,
            fontsize=6.1,
            weight="bold" if comp in {"ICA_Cognition", "ICA_TobaccoUse"} else "normal",
        )
        rounded_label(
            ax,
            xs["verdict"],
            y,
            verdict,
            edge=verdict_col,
            face="#ffffff",
            width=0.130,
            height=0.058,
            fontsize=6.5,
            weight="bold",
        )

    ax.text(
        0.50,
        0.085,
        "Benchmark success starts the trace; Figure 5 reports the cheap-gate decision.",
        ha="center",
        va="center",
        fontsize=8.4,
        fontweight="bold",
        color=COLORS["text"],
    )
    ax.text(
        0.50,
        0.035,
        (
            f"Frozen aggregate: r={summary['aggregate_all_five']['observed_mean_fold_r']:.3f}, "
            f"p={summary['aggregate_all_five']['plus_one_p']:.6f}; "
            "KG wPLI / IllicitDrugUse validation: p=0.1998."
        ),
        ha="center",
        va="bottom",
        fontsize=6.5,
        color=COLORS["muted"],
    )
    return save_figure(fig, "fig02_evidence_flow_alluvial_v3")


def make_fig03_forest_scorecard() -> dict[str, str]:
    real = read_json(CONFIRM_REAL)
    summary = read_json(CONFIRM_SUMMARY)
    entries = component_entries(real)

    y = np.arange(len(entries))
    vals = np.array([entry["fold_mean_r"] for entry in entries])
    fold_best = np.array([max(entry["per_fold_r"]) for entry in entries])
    best_fold = np.array([int(np.argmax(entry["per_fold_r"])) for entry in entries])
    ref_mean = np.array([entry["reference_mean_r"] for entry in entries])
    ref_best = np.array([entry["reference_best_r"] for entry in entries])
    ci_low = np.array([BOOT_CI[entry["component"]][0] for entry in entries])
    ci_high = np.array([BOOT_CI[entry["component"]][1] for entry in entries])

    fig = plt.figure(figsize=(8.8, 3.70))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.58, 1.32], wspace=0.05)
    ax = fig.add_subplot(gs[0, 0])
    tab = fig.add_subplot(gs[0, 1], sharey=ax)

    ax.set_title("A  Fold-mean r with bootstrap uncertainty", loc="left", fontweight="bold", fontsize=10.5, pad=6)
    ax.axhspan(-0.5, 2.5, color="#ecfdf5", zorder=0)
    ax.axhspan(2.5, 3.5, color="#fff7ed", zorder=0)
    ax.axhspan(3.5, 4.5, color="#fee2e2", zorder=0)
    ax.axvline(0, color="#334155", lw=0.8, zorder=1)

    for i, entry in enumerate(entries):
        comp = entry["component"]
        color = COMP_COLORS[comp]
        ax.hlines(i, ci_low[i], ci_high[i], color=color, lw=2.4, zorder=3)
        ax.plot([ci_low[i], ci_low[i]], [i - 0.095, i + 0.095], color=color, lw=1.2, zorder=3)
        ax.plot([ci_high[i], ci_high[i]], [i - 0.095, i + 0.095], color=color, lw=1.2, zorder=3)
        ax.scatter(vals[i], i, s=54, color=color, edgecolor="white", lw=0.7, zorder=5)
        ax.scatter(
            fold_best[i],
            i + 0.19,
            s=30,
            marker="^",
            facecolor="white",
            edgecolor=color,
            lw=1.1,
            zorder=4,
        )
        ax.scatter(ref_mean[i], i - 0.19, s=23, facecolor="white", edgecolor="#475569", lw=1.0, zorder=4)
        ax.scatter(ref_best[i], i - 0.19, s=25, marker="x", color="#475569", lw=1.2, zorder=4)

    ax.set_yticks(y)
    ax.set_yticklabels([SHORT[entry["component"]] for entry in entries])
    ax.invert_yaxis()
    ax.set_xlim(-0.14, 0.50)
    ax.set_xlabel("Fold-mean Pearson r")
    ax.grid(axis="x", color=COLORS["grid"], lw=0.7)
    ax.text(
        -0.137,
        -0.70,
        "refs: o=Liu mean, x=Liu best; triangle=fold max diagnostic; bar=bootstrap 95% CI",
        ha="left",
        va="center",
        fontsize=5.6,
        color=COLORS["muted"],
    )

    tab.set_title("B  Inference scorecard", loc="left", fontweight="bold", fontsize=10.5, pad=6)
    tab.set_xlim(0, 1)
    tab.set_ylim(ax.get_ylim())
    tab.axis("off")
    columns = [(0.02, "mean\nr"), (0.19, "fold\nmax"), (0.39, "max-T\np"), (0.57, "R2"), (0.72, "verdict")]
    for x, label in columns:
        tab.text(x, -0.70, label, ha="left", va="center", fontsize=5.8, fontweight="bold", color=COLORS["muted"])
    for i, entry in enumerate(entries):
        comp = entry["component"]
        pval = summary["per_component"][comp]["max_t_fwer_plus_one_p"]
        verdict, vcol = VERDICTS[comp]
        row = [
            (0.02, f"{entry['fold_mean_r']:.3f}", COLORS["text"], "normal"),
            (0.19, f"{max(entry['per_fold_r']):.3f}", COLORS["text"], "normal"),
            (0.39, p_text(float(pval)), COLORS["text"], "normal"),
            (0.57, f"{entry['fold_mean_r'] ** 2:.3f}", COLORS["text"], "normal"),
            (0.72, verdict, vcol, "bold"),
        ]
        for x, txt, col, weight in row:
            tab.text(
                x,
                i,
                txt,
                ha="left",
                va="center",
                fontsize=7.0,
                color=col,
                fontweight=weight,
                fontfamily="DejaVu Sans Mono" if x < 0.70 else "DejaVu Sans",
            )
        tab.plot([0.00, 0.98], [i + 0.42, i + 0.42], color="#f1f5f9", lw=0.6, zorder=0)

    fig.text(
        0.51,
        0.008,
        "CI resamples the ten held-out folds; fold max is diagnostic only; R2 is a descriptive ceiling, not variance decomposition.",
        ha="center",
        va="bottom",
        fontsize=6.5,
        color=COLORS["muted"],
    )
    fig.subplots_adjust(left=0.145, right=0.99, top=0.90, bottom=0.16)
    return save_figure(fig, "fig03_component_forest_scorecard_v3")


def make_fig04_permutation_split() -> dict[str, str]:
    summary = read_json(CONFIRM_SUMMARY)
    perms = read_jsonl(CONFIRM_PERMS)
    wpli = read_json(WPLI_VALIDATION)

    aggregate_null = np.array([row["aggregate_mean_r"] for row in perms], dtype=float)
    aggregate_obs = float(summary["aggregate_all_five"]["observed_mean_fold_r"])
    aggregate_p = float(summary["aggregate_all_five"]["plus_one_p"])
    aggregate_z = float(summary["aggregate_all_five"]["effect_vs_null"]["permutation_z"])
    wpli_null = np.array(wpli["perm_fold_mean_r_values"], dtype=float)
    wpli_obs = float(wpli["real_fold_mean_r"])
    wpli_p = float(wpli["p_value_plus_one"])

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.35), sharex=True)
    panels = [
        (
            axes[0],
            aggregate_null,
            aggregate_obs,
            COLORS["supported"],
            "A  Supported aggregate",
            f"observed r = {aggregate_obs:.3f}\np = {aggregate_p:.6f}\nz = {aggregate_z:.2f}",
            "supported",
        ),
        (
            axes[1],
            wpli_null,
            wpli_obs,
            COLORS["rejected"],
            "B  Killed KG lead",
            f"observed r = {wpli_obs:.3f}\np = {wpli_p:.4f}\n95th null = {np.percentile(wpli_null, 95):.3f}",
            "lead rejected",
        ),
    ]
    for ax, null, obs, color, title, annotation, verdict in panels:
        q95 = np.percentile(null, 95)
        ax.hist(null, bins=40, density=True, color="#dbe4ee", edgecolor="white", lw=0.45)
        ax.axvline(q95, color="#475569", lw=1.2, ls=(0, (3, 2)))
        ax.axvline(obs, color=color, lw=2.2)
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_xlabel("Fold-mean Pearson r")
        ax.grid(axis="x", color=COLORS["grid"], lw=0.65)
        ax.text(
            0.96,
            0.92,
            annotation,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=7.0,
            fontfamily="DejaVu Sans Mono",
            color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor=color, lw=1.0),
        )
        ax.text(
            0.05,
            0.88,
            verdict,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=7.4,
            fontweight="bold",
            color=color,
        )
    axes[0].set_ylabel("Null density")
    axes[0].set_xlim(-0.18, 0.215)
    fig.text(
        0.51,
        0.012,
        "The same permutation machinery supports the frozen predictor and rejects the tempting wPLI / IllicitDrugUse lead.",
        ha="center",
        va="bottom",
        fontsize=6.7,
        fontweight="bold",
        color=COLORS["text"],
    )
    fig.subplots_adjust(left=0.075, right=0.985, top=0.90, bottom=0.18, wspace=0.18)
    return save_figure(fig, "fig04_permutation_split_v3")


def make_fig05_support_boundary() -> dict[str, str]:
    rows = [
        "Aggregate predictor",
        "Cognition (H1)",
        "TobaccoUse (H2)",
        "PersonalityEmotion (H3)",
        "MentalHealth (H4)",
        "IllicitDrugUse (H5)",
        "Adaptive procedure",
        "External generalisation",
    ]
    cols = [
        "Exploratory\nreward",
        "Frozen-pipeline\ninference",
        "Cheap gate §5.1\n(extended cov.)",
        "Post-selection\n(aggregate)",
        "Post-selection\n(max-T per-comp.)",
        "A1 redesign §3.7\n(intel.-resid.)",
        "External\nvalidation (§5.2)",
    ]
    # Verdict labels:
    #   supported = yes      caveated = caveat   rejected = no
    #   na        = —         deferred = deferred (§5.2 not booked)
    matrix = [
        # Aggregate predictor
        ["supported", "supported", "rejected",  "supported", "na",         "supported", "deferred"],
        # Cognition (H1)
        ["supported", "supported", "rejected",  "supported", "supported",  "supported", "deferred"],
        # TobaccoUse (H2)
        ["supported", "supported", "rejected",  "supported", "supported",  "na",        "deferred"],
        # PersonalityEmotion (H3)
        ["supported", "supported", "supported", "supported", "rejected",   "na",        "deferred"],
        # MentalHealth (H4)
        ["supported", "caveated",  "caveated",  "caveated",  "caveated",   "na",        "deferred"],
        # IllicitDrugUse (H5)
        ["supported", "rejected",  "na",        "rejected",  "rejected",   "na",        "deferred"],
        # Adaptive procedure
        ["na",        "na",        "na",        "supported", "supported",  "supported", "deferred"],
        # External generalisation
        ["na",        "na",        "na",        "na",        "na",         "na",        "deferred"],
    ]
    labels = {
        "supported": "yes",
        "caveated": "caveat",
        "rejected": "no",
        "blocked": "not done",
        "na": "—",
        "deferred": "deferred",
    }
    cell_colors = {
        "supported": COLORS["supported"],
        "caveated": COLORS["caveated"],
        "rejected": COLORS["rejected"],
        "blocked": COLORS["blocked"],
        "na": "#cbd5e1",
        "deferred": "#fbbf24",
    }
    cell_alpha = {
        "supported": 0.84,
        "caveated": 0.84,
        "rejected": 0.84,
        "blocked": 0.44,
        "na": 0.40,
        "deferred": 0.78,
    }

    fig, ax = plt.subplots(figsize=(10.6, 5.20))
    ax.set_xlim(-2.30, len(cols) + 0.14)
    ax.set_ylim(-1.95, len(rows) + 1.45)
    ax.invert_yaxis()
    ax.axis("off")

    # Top caption (visually at the top; ax has y inverted)
    ax.text(
        len(cols) / 2 - 0.5,
        -1.78,
        "Cheap gate §5.1 killed raw H1/H2; the A1 in-house redesign (§3.7) recovered an intelligence-orthogonal H1' under the same family-aware null --- §5.2 external compute is therefore deferred and now carries H1'.",
        ha="center",
        va="center",
        fontsize=6.6,
        fontweight="bold",
        color=COLORS["text"],
    )

    # Legend strip just under the caption
    legend_x = -2.28
    legend_y = -1.30
    legend_entries = [
        ("supported", "supported"),
        ("caveated", "caveated"),
        ("rejected", "rejected / fail"),
        ("deferred", "deferred (§5.2 not booked)"),
        ("na", "n/a"),
    ]
    for k, (state, label) in enumerate(legend_entries):
        x = legend_x + k * 1.66
        ax.add_patch(
            patches.Rectangle(
                (x, legend_y - 0.12),
                0.16,
                0.20,
                facecolor=cell_colors[state],
                alpha=cell_alpha[state],
                edgecolor="none",
            )
        )
        ax.text(x + 0.21, legend_y - 0.02, label, ha="left", va="center", fontsize=6.2, color=COLORS["muted"])

    ax.text(
        -2.28,
        -0.55,
        "Claim",
        ha="left",
        va="center",
        fontsize=7.5,
        fontweight="bold",
        color=COLORS["muted"],
    )
    for j, col in enumerate(cols):
        ax.text(
            j + 0.5,
            -0.55,
            col,
            ha="center",
            va="center",
            fontsize=6.6,
            fontweight="bold",
            color=COLORS["text"],
        )

    for i, row in enumerate(rows):
        weight = "bold" if i <= 5 else "normal"
        ax.text(-2.08, i + 0.5, row, ha="left", va="center", fontsize=7.0, fontweight=weight, color=COLORS["text"])
        for j, state in enumerate(matrix[i]):
            fc = cell_colors[state]
            alpha = cell_alpha[state]
            ax.add_patch(
                patches.FancyBboxPatch(
                    (j + 0.05, i + 0.13),
                    0.90,
                    0.74,
                    boxstyle="round,pad=0.015,rounding_size=0.025",
                    facecolor=fc,
                    alpha=alpha,
                    edgecolor="white",
                    lw=0.9,
                )
            )
            text_color = "#475569" if state == "na" else "white"
            ax.text(
                j + 0.5,
                i + 0.5,
                labels[state],
                ha="center",
                va="center",
                fontsize=6.0,
                fontweight="bold",
                color=text_color,
            )

    ax.plot([-2.30, len(cols) + 0.05], [6.0, 6.0], color="#94a3b8", lw=0.9, ls=(0, (2, 2)))

    # Bottom blocker-badges strip (below the table)
    ax.text(
        -2.28,
        len(rows) + 0.55,
        "Missing-data blockers (not yet claimed):",
        ha="left",
        va="center",
        fontsize=6.6,
        fontweight="bold",
        color=COLORS["muted"],
    )
    blockers = [
        "Motion (FD/DVARS)",
        "GSR features",
        "Schaefer-200/400",
        "External cohort §5.2",
    ]
    blocker_y = len(rows) + 1.05
    for k, label in enumerate(blockers):
        x = -2.28 + k * 2.06
        ax.add_patch(
            patches.FancyBboxPatch(
                (x, blocker_y - 0.18),
                1.95,
                0.36,
                boxstyle="round,pad=0.018,rounding_size=0.04",
                facecolor="#e2e8f0",
                edgecolor="#94a3b8",
                lw=0.7,
            )
        )
        ax.text(
            x + 0.10,
            blocker_y,
            label,
            ha="left",
            va="center",
            fontsize=6.0,
            color="#334155",
        )
    return save_figure(fig, "fig05_support_boundary_matrix_v3")


def main() -> None:
    configure_style()
    outputs = {
        "fig02": make_fig02_evidence_flow(),
        "fig03": make_fig03_forest_scorecard(),
        "fig04": make_fig04_permutation_split(),
        "fig05": make_fig05_support_boundary(),
    }
    manifest = {
        "description": "v3 deterministic report evidence figures",
        "inputs": {
            "confirm_real": str(CONFIRM_REAL),
            "confirm_summary": str(CONFIRM_SUMMARY),
            "confirm_permutations": str(CONFIRM_PERMS),
            "wpli_validation": str(WPLI_VALIDATION),
        },
        "outputs": outputs,
    }
    manifest_path = OUT_DIR / "v3_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(manifest_path)


if __name__ == "__main__":
    main()
