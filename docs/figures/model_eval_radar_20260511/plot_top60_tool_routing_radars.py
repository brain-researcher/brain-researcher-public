#!/usr/bin/env python3
"""Generate paired Top60 tool-calling radar figures.

The Top60 task slice is a tool-calling benchmark, so the visual comparison
should use two traces, without BR and with BR, rather than turning the two
conditions into separate radar axes.
"""

from __future__ import annotations

import csv
import json
import math
import textwrap
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

import plot_model_eval_radars as radar_base


OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]
SOURCE_JSON = (
    REPO_ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "TOOL_SELECTION_TOP60_PLUS_BR_MODEL_METRIC_BREAKDOWN_20260514.json"
)
SCORES_CSV = OUT_DIR / "top60_tool_calling_paired_scores.csv"
ROUTE_CORE_CSV = OUT_DIR / "top60_route_core_paired_scores.csv"


MODEL_NAME_MAP = {
    "Claude": "Claude Code Opus 4.7",
    "Codex": "Codex GPT-5.5",
    "Gemini": "Gemini 3.1 Pro",
    "GLM-5.1": "GLM 5.1",
    "Kimi": "Kimi K2.5",
    "Qwen": "Qwen 3.6 Plus",
    "DeepSeek": "DeepSeek v4 Pro",
}

CONDITIONS = [
    ("without_br", "without BR"),
    ("with_br", "with BR"),
]

CONDITION_COLORS = {
    "without_br": "#64748B",
    "with_br": "#D97706",
}

METRICS = [
    ("capability_score", "Capability"),
    ("correct_rate", "Correct route/tool"),
    ("trace_required_call_coverage", "Required-call trace"),
    ("execution_handoff_score", "Handoff score"),
    ("execution_handoff_ok_rate", "Handoff pass"),
]

ROUTE_CORE_METRICS = [
    ("capability_score", "Capability"),
    ("correct_rate", "Correct route/tool"),
]

SPLIT_METRIC_GROUPS = [
    (
        "Route-Core Quality",
        "top60_route_selection_quality_paired_by_model_radars",
        ROUTE_CORE_METRICS,
        "Route-core quality: capability and correct route/tool only. Trace, handoff, run-health, and with-BR-only metrics are excluded.",
    ),
    (
        "Execution-Handoff Quality",
        "top60_execution_handoff_quality_paired_by_model_radars",
        [
            ("trace_required_call_coverage", "Required-call trace"),
            ("execution_handoff_score", "Handoff score"),
            ("execution_handoff_ok_rate", "Handoff pass"),
        ],
        "Execution-handoff quality: required-call evidence plus handoff score/pass. Missing handoff fields are scored as 0.",
    ),
]


def clamp01(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def wrap_label(label: str, width: int = 10) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def model_label(model: str) -> str:
    return radar_base.MODEL_SHORT_LABELS.get(model, model)


def score_for(row: dict[str, Any], metric: str) -> float:
    return clamp01(row.get(metric))


def read_scores() -> dict[str, dict[str, dict[str, float]]]:
    payload = json.loads(SOURCE_JSON.read_text())
    scores = {
        model: {
            condition: {metric: 0.0 for metric, _ in METRICS}
            for condition, _ in CONDITIONS
        }
        for model in radar_base.MODELS
    }

    for row in payload["mode_rows"]:
        model = MODEL_NAME_MAP[row["model"]]
        condition = row["mode"]
        for metric, _ in METRICS:
            scores[model][condition][metric] = score_for(row, metric)
    return scores


def write_score_csv(scores: dict[str, dict[str, dict[str, float]]]) -> None:
    fieldnames = ["model", "condition", "metric", "score", "source", "note"]
    with SCORES_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for model in radar_base.MODELS:
            for condition, condition_label in CONDITIONS:
                for metric, metric_label in METRICS:
                    writer.writerow(
                        {
                            "model": model,
                            "condition": condition_label,
                            "metric": metric_label,
                            "score": f"{scores[model][condition][metric]:.6f}",
                            "source": str(SOURCE_JSON.relative_to(REPO_ROOT)),
                            "note": metric,
                        }
                    )


def write_route_core_csv(scores: dict[str, dict[str, dict[str, float]]]) -> None:
    fieldnames = ["model", "condition", "metric", "score", "source", "note"]
    with ROUTE_CORE_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for model in radar_base.MODELS:
            for condition, condition_label in CONDITIONS:
                for metric, metric_label in ROUTE_CORE_METRICS:
                    writer.writerow(
                        {
                            "model": model,
                            "condition": condition_label,
                            "metric": metric_label,
                            "score": f"{scores[model][condition][metric]:.6f}",
                            "source": str(SOURCE_JSON.relative_to(REPO_ROOT)),
                            "note": "route_core_only",
                        }
                    )


def save_figure(fig, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def style_polar_axis(ax, angles, labels, *, label_size: float = 7.2) -> None:
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 1)
    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=label_size, color="#475569")
    ax.set_rlabel_position(0)
    ax.set_yticks([0.25, 0.50, 0.75, 1.0])
    ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.5, color="#64748B")
    ax.grid(color="#CBD5E1", linewidth=0.75, alpha=0.9)
    ax.spines["polar"].set_color("#94A3B8")


def plot_by_model(scores: dict[str, dict[str, dict[str, float]]]) -> None:
    """One panel per model; axes are metrics; traces are without/with BR."""

    angles = np.linspace(0, 2 * np.pi, len(METRICS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    metric_labels = [wrap_label(label, 10) for _, label in METRICS]

    ncols = 3
    nrows = math.ceil(len(radar_base.MODELS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(14.0, 4.2 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(radar_base.MODELS):
        ax = axes[idx]
        style_polar_axis(ax, angles, metric_labels)
        for condition, condition_label in CONDITIONS:
            values = np.array([scores[model][condition][metric] for metric, _ in METRICS])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(
                closed_angles,
                closed_values,
                color=CONDITION_COLORS[condition],
                linewidth=2.0,
                label=condition_label,
            )
            ax.fill(closed_angles, closed_values, color=CONDITION_COLORS[condition], alpha=0.14)
        ax.set_title(
            model,
            fontsize=10.5,
            fontweight="bold",
            color=radar_base.COLORS.get(model, "#334155"),
            y=1.14,
        )

    for ax in axes[len(radar_base.MODELS) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle("Top60 Tool-Calling Paired Profiles", fontsize=17, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.026,
        "Each panel is one model; traces compare without BR versus with BR. Scores are 0-1 paired quality metrics; run-health and with-BR-only metrics are excluded.",
        fontsize=8.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.91, bottom=0.09, wspace=0.32, hspace=0.50)
    save_figure(fig, "top60_tool_calling_paired_by_model_radars")


def plot_split_group_by_model(
    scores: dict[str, dict[str, dict[str, float]]],
    group_title: str,
    stem: str,
    metrics: list[tuple[str, str]],
    footnote: str,
) -> None:
    """One panel per model for a focused metric group."""

    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    metric_labels = [wrap_label(label, 10) for _, label in metrics]

    ncols = 3
    nrows = math.ceil(len(radar_base.MODELS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(14.0, 4.2 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(radar_base.MODELS):
        ax = axes[idx]
        style_polar_axis(ax, angles, metric_labels)
        for condition, condition_label in CONDITIONS:
            values = np.array([scores[model][condition][metric] for metric, _ in metrics])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(
                closed_angles,
                closed_values,
                color=CONDITION_COLORS[condition],
                linewidth=2.0,
                label=condition_label,
            )
            ax.fill(closed_angles, closed_values, color=CONDITION_COLORS[condition], alpha=0.14)
        ax.set_title(
            model,
            fontsize=10.5,
            fontweight="bold",
            color=radar_base.COLORS.get(model, "#334155"),
            y=1.14,
        )

    for ax in axes[len(radar_base.MODELS) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle(f"Top60 {group_title}", fontsize=17, fontweight="bold", y=0.995)
    fig.text(0.02, 0.026, footnote, fontsize=8.5, color="#475569")
    fig.subplots_adjust(left=0.035, right=0.98, top=0.91, bottom=0.09, wspace=0.32, hspace=0.50)
    save_figure(fig, stem)


def plot_by_metric(scores: dict[str, dict[str, dict[str, float]]]) -> None:
    """One panel per metric; axes are models; traces are without/with BR."""

    angles = np.linspace(0, 2 * np.pi, len(radar_base.MODELS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    model_labels = [model_label(model) for model in radar_base.MODELS]

    ncols = 2
    nrows = math.ceil(len(METRICS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(14.0, 5.0 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, (metric, metric_label) in enumerate(METRICS):
        ax = axes[idx]
        style_polar_axis(ax, angles, model_labels, label_size=7.0)
        for condition, condition_label in CONDITIONS:
            values = np.array([scores[model][condition][metric] for model in radar_base.MODELS])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(
                closed_angles,
                closed_values,
                color=CONDITION_COLORS[condition],
                linewidth=2.0,
                label=condition_label,
            )
            ax.fill(closed_angles, closed_values, color=CONDITION_COLORS[condition], alpha=0.14)
        ax.set_title(metric_label, fontsize=12, fontweight="bold", y=1.13)

    for ax in axes[len(METRICS) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle("Top60 Tool-Calling Metrics by Model", fontsize=17, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.026,
        "Each panel is one metric; axes are models. Traces compare without BR versus with BR on the same Top60 rows.",
        fontsize=8.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.90, bottom=0.09, wspace=0.30, hspace=0.42)
    save_figure(fig, "top60_tool_calling_paired_by_metric_radars")


def plot_route_core_by_metric(scores: dict[str, dict[str, dict[str, float]]]) -> None:
    """Focused by-metric figure for capability and correct route/tool only."""

    angles = np.linspace(0, 2 * np.pi, len(radar_base.MODELS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    model_labels = [model_label(model) for model in radar_base.MODELS]

    fig, axes = plt.subplots(
        1,
        len(ROUTE_CORE_METRICS),
        figsize=(13.5, 5.6),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, (metric, metric_label) in enumerate(ROUTE_CORE_METRICS):
        ax = axes[idx]
        style_polar_axis(ax, angles, model_labels, label_size=7.0)
        for condition, condition_label in CONDITIONS:
            values = np.array([scores[model][condition][metric] for model in radar_base.MODELS])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(
                closed_angles,
                closed_values,
                color=CONDITION_COLORS[condition],
                linewidth=2.2,
                label=condition_label,
            )
            ax.fill(closed_angles, closed_values, color=CONDITION_COLORS[condition], alpha=0.16)
        ax.set_title(metric_label, fontsize=13, fontweight="bold", y=1.13)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.02),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    fig.suptitle("Top60 Route-Core Metrics by Model", fontsize=17, fontweight="bold", y=0.985)
    fig.text(
        0.02,
        0.035,
        "Each panel is one route-core metric; axes are models. Trace, handoff, run-health, and with-BR-only metrics are excluded.",
        fontsize=8.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.045, right=0.98, top=0.82, bottom=0.16, wspace=0.30)
    save_figure(fig, "top60_route_core_paired_by_metric_radars")


def main() -> None:
    scores = read_scores()
    write_score_csv(scores)
    write_route_core_csv(scores)
    plot_by_model(scores)
    plot_by_metric(scores)
    plot_route_core_by_metric(scores)
    for group_title, stem, metrics, footnote in SPLIT_METRIC_GROUPS:
        plot_split_group_by_model(scores, group_title, stem, metrics, footnote)


if __name__ == "__main__":
    main()
