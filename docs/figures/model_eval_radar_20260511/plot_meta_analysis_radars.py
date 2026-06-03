#!/usr/bin/env python3
"""Generate meta-analysis with/without-BR radar figures.

This is a documentation plot. It reads the current meta-analysis summary table
and does not rerun agents or evaluators.
"""

from __future__ import annotations

import csv
import math
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]
META_ANALYSIS_DIR = REPO_ROOT / "benchmarks/neurometabench/experiments/agent_condition_matrix"
SOURCE_NOTE = "current meta-analysis fallback-fix metrics table"

MODELS = [
    "Claude Code Opus",
    "Codex CLI GPT-5.5",
    "OpenCode Gemini 3.1 Pro Preview",
    "OpenCode GLM 5.1",
    "OpenCode DeepSeek V4 Pro",
    "OpenCode Kimi K2.5",
    "OpenCode Qwen3.6 Plus",
]

MODEL_SHORT_LABELS = {
    "Claude Code Opus": "Claude\nOpus",
    "Codex CLI GPT-5.5": "Codex\n5.5",
    "OpenCode Gemini 3.1 Pro Preview": "Gemini\n3.1 Pro",
    "OpenCode GLM 5.1": "GLM\n5.1",
    "OpenCode DeepSeek V4 Pro": "DeepSeek\nv4 Pro",
    "OpenCode Kimi K2.5": "Kimi\nK2.5",
    "OpenCode Qwen3.6 Plus": "Qwen\n3.6 Plus",
}

COLORS = {
    "Claude Code Opus": "#4C78A8",
    "Codex CLI GPT-5.5": "#F58518",
    "OpenCode Gemini 3.1 Pro Preview": "#54A24B",
    "OpenCode GLM 5.1": "#E45756",
    "OpenCode DeepSeek V4 Pro": "#72B7B2",
    "OpenCode Kimi K2.5": "#B279A2",
    "OpenCode Qwen3.6 Plus": "#FF9DA6",
}

WITHOUT_BR_COLOR = "#64748B"
WITH_BR_COLOR = "#D97706"

COMPARABLE_METRICS = [
    ("Strict reproduction", "correct_strict_rate"),
    ("Science equivalent", "science_equivalent_rate"),
    ("Local study F1", "local_study_set_f1_mean"),
    ("Coordinate canonical F1", "coordinate_canonical_f1_mean"),
    ("Identifier coverage", "identifier_coverage_score_mean"),
    ("Provenance enrichment", "provenance_enrichment_score_mean"),
    ("Source traceability", "source_traceability_score_mean"),
    ("Coordinate-space documentation", "coordinate_space_documentation_score_mean"),
    ("Sample-size documentation", "sample_size_documentation_score_mean"),
    ("Public-ID documentation", "public_identifier_documentation_score_mean"),
    ("Final artifact quality", "final_artifact_quality_score_mean"),
]

ANCHOR_METRICS = [
    ("BR actual use", "br_actual_use_pass_rate"),
    ("BR effective use", "br_effective_use_pass_rate"),
    ("Anchor contract pass", "br_reconciliation_anchor_pass_rate"),
    ("Valid anchor rate", "valid_br_anchor_rate"),
    ("Consumed valid anchor rate", "consumed_valid_br_anchor_rate"),
    ("BR anchor score", "br_reconciliation_anchor_score_mean"),
]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def parse_score(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    try:
        number = float(value)
    except ValueError:
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return clamp01(number)


def wrap_label(label: str, width: int = 11) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def load_model_rows() -> dict[tuple[str, str], dict[str, str]]:
    candidates = sorted(META_ANALYSIS_DIR.glob("MODEL_BY_BR_METRICS_*_fallbackfix_20260514.csv"))
    if not candidates:
        raise FileNotFoundError("No current meta-analysis fallback-fix metrics table found.")
    with candidates[-1].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {(row["system"], row["br_condition"]): row for row in rows}


def save_figure(fig, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def write_radar_scores(rows: dict[tuple[str, str], dict[str, str]]) -> None:
    out = OUT_DIR / "meta_analysis_radar_scores.csv"
    fieldnames = ["model", "br_condition", "metric_group", "metric", "score", "source", "note"]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for model in MODELS:
            for br_condition in ("without_br", "with_br"):
                row = rows[(model, br_condition)]
                for metric, field in COMPARABLE_METRICS:
                    writer.writerow(
                        {
                            "model": model,
                            "br_condition": br_condition,
                            "metric_group": "comparable_meta_analysis",
                            "metric": metric,
                            "score": f"{parse_score(row.get(field)):.6f}",
                            "source": SOURCE_NOTE,
                            "note": "Comparable with/without-BR meta-analysis metric.",
                        }
                    )
            with_row = rows[(model, "with_br")]
            for metric, field in ANCHOR_METRICS:
                writer.writerow(
                    {
                        "model": model,
                        "br_condition": "with_br",
                        "metric_group": "with_br_anchor_audit",
                        "metric": metric,
                        "score": f"{parse_score(with_row.get(field)):.6f}",
                        "source": SOURCE_NOTE,
                        "note": "With-BR-only anchor/audit metric; no without-BR capability baseline.",
                    }
                )


def plot_model_faceted_with_without(rows: dict[tuple[str, str], dict[str, str]]) -> None:
    """One panel per model; axes are comparable meta-analysis metrics."""
    labels = [metric for metric, _field in COMPARABLE_METRICS]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 3
    nrows = math.ceil(len(MODELS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(15.5, 4.65 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(MODELS):
        ax = axes[idx]
        without_values = np.array(
            [parse_score(rows[(model, "without_br")].get(field)) for _metric, field in COMPARABLE_METRICS],
            dtype=float,
        )
        with_values = np.array(
            [parse_score(rows[(model, "with_br")].get(field)) for _metric, field in COMPARABLE_METRICS],
            dtype=float,
        )
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([wrap_label(label, 10) for label in labels], fontsize=6.7, color="#4B5563")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6, color="#64748B")
        ax.grid(color="#CBD5E1", linewidth=0.7, alpha=0.85)
        ax.spines["polar"].set_color("#94A3B8")

        closed_without = np.concatenate([without_values, [without_values[0]]])
        closed_with = np.concatenate([with_values, [with_values[0]]])
        ax.plot(closed_angles, closed_without, color=WITHOUT_BR_COLOR, linewidth=1.8, label="without BR")
        ax.fill(closed_angles, closed_without, color=WITHOUT_BR_COLOR, alpha=0.10)
        ax.plot(closed_angles, closed_with, color=WITH_BR_COLOR, linewidth=2.1, label="with BR")
        ax.fill(closed_angles, closed_with, color=WITH_BR_COLOR, alpha=0.18)
        ax.set_title(model, color=COLORS[model], fontsize=10.5, fontweight="bold", y=1.15)

    for ax in axes[len(MODELS) :]:
        ax.set_axis_off()

    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle(
        "Meta-analysis: Comparable With/Without-BR Metrics",
        fontsize=17,
        fontweight="bold",
        y=0.992,
    )
    fig.text(
        0.025,
        0.022,
        "Each panel is one model. Axes are comparable 0-1 meta-analysis metrics; Qwen targeted retry is applied.",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.91, bottom=0.08, wspace=0.34, hspace=0.52)
    save_figure(fig, "meta_analysis_model_faceted_with_without_radar")


def plot_metric_faceted_by_model(rows: dict[tuple[str, str], dict[str, str]]) -> None:
    """One panel per metric; axes are models with paired with/without traces."""
    angles = np.linspace(0, 2 * np.pi, len(MODELS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 3
    nrows = math.ceil(len(COMPARABLE_METRICS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(15.8, 4.25 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, (metric, field) in enumerate(COMPARABLE_METRICS):
        ax = axes[idx]
        without_values = np.array(
            [parse_score(rows[(model, "without_br")].get(field)) for model in MODELS],
            dtype=float,
        )
        with_values = np.array(
            [parse_score(rows[(model, "with_br")].get(field)) for model in MODELS],
            dtype=float,
        )
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([MODEL_SHORT_LABELS[model] for model in MODELS], fontsize=7.1, color="#4B5563")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.5, color="#64748B")
        ax.grid(color="#CBD5E1", linewidth=0.7, alpha=0.85)
        ax.spines["polar"].set_color("#94A3B8")

        closed_without = np.concatenate([without_values, [without_values[0]]])
        closed_with = np.concatenate([with_values, [with_values[0]]])
        ax.plot(closed_angles, closed_without, color=WITHOUT_BR_COLOR, linewidth=1.8, label="without BR")
        ax.fill(closed_angles, closed_without, color=WITHOUT_BR_COLOR, alpha=0.10)
        ax.plot(closed_angles, closed_with, color=WITH_BR_COLOR, linewidth=2.1, label="with BR")
        ax.fill(closed_angles, closed_with, color=WITH_BR_COLOR, alpha=0.18)
        ax.set_title(metric, fontsize=11, fontweight="bold", y=1.12)

    for ax in axes[len(COMPARABLE_METRICS) :]:
        ax.set_axis_off()

    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle(
        "Meta-analysis: Metric x Model Paired BR Radars",
        fontsize=17,
        fontweight="bold",
        y=0.992,
    )
    fig.text(
        0.025,
        0.022,
        "Each panel is one comparable metric; axes are models. BR-only anchor metrics are excluded from this paired comparison.",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.925, bottom=0.065, wspace=0.34, hspace=0.48)
    save_figure(fig, "meta_analysis_metric_faceted_with_without_radar")


def plot_with_br_anchor_audit(rows: dict[tuple[str, str], dict[str, str]]) -> None:
    labels = [metric for metric, _field in ANCHOR_METRICS]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    fig, ax = plt.subplots(figsize=(10.5, 8.0), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    for model in MODELS:
        values = np.array(
            [parse_score(rows[(model, "with_br")].get(field)) for _metric, field in ANCHOR_METRICS],
            dtype=float,
        )
        closed_values = np.concatenate([values, [values[0]]])
        color = COLORS[model]
        ax.plot(closed_angles, closed_values, color=color, linewidth=2.0, label=model)
        ax.fill(closed_angles, closed_values, color=color, alpha=0.055)

    ax.set_ylim(0, 1)
    ax.set_xticks(angles)
    ax.set_xticklabels([wrap_label(label, 12) for label in labels], fontsize=9)
    ax.set_yticks([0.25, 0.50, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=8)
    ax.grid(color="#C9CED6", linewidth=0.8, alpha=0.9)
    ax.spines["polar"].set_color("#6B7280")
    ax.set_title("Meta-analysis: With-BR Anchor/Audit Metrics", fontsize=15, pad=28, fontweight="bold")
    ax.legend(loc="center left", bbox_to_anchor=(1.08, 0.5), frameon=False, fontsize=9)
    fig.text(
        0.02,
        0.02,
        "With-BR-only anchor/audit metrics. These do not have a capability-comparable without-BR baseline.",
        fontsize=8,
        color="#4B5563",
    )
    save_figure(fig, "meta_analysis_with_br_anchor_audit_radar")


def main() -> None:
    rows = load_model_rows()
    write_radar_scores(rows)
    plot_model_faceted_with_without(rows)
    plot_metric_faceted_by_model(rows)
    plot_with_br_anchor_audit(rows)


if __name__ == "__main__":
    main()
