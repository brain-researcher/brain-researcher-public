#!/usr/bin/env python3
"""Plot toolong action-budget metrics as by-metric paired radars."""

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
    / "TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_20260514.json"
)
SCORES_CSV = OUT_DIR / "toolong_action_budget_radar_scores_20260514.csv"

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

ROUTE_CORE_METRICS = [
    ("capability_score", "Capability"),
    ("correct_rate", "Correct route/tool"),
]

QUALITY_METRICS = [
    ("capability_score", "Capability"),
    ("correct_rate", "Correct route/tool"),
    ("execution_handoff_score", "Handoff score"),
]


def wrap_label(label: str, width: int = 10) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def model_label(model: str) -> str:
    return radar_base.MODEL_SHORT_LABELS.get(model, model)


def load_metric_rows() -> list[dict[str, Any]]:
    payload = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    return payload["long_rows"]


def metric_key(metric: str, budget: int) -> str:
    return f"{metric}@{budget}"


def build_score_table(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    table: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        budget = row.get("budget")
        if not isinstance(budget, int):
            continue
        model = MODEL_NAME_MAP[str(row["model"])]
        condition = str(row["mode"])
        key = metric_key(str(row["metric"]), budget)
        table.setdefault(key, {}).setdefault(condition, {})[model] = float(row["plot_value"])
    return table


def write_scores_csv(rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "model",
        "condition",
        "metric",
        "budget",
        "panel_label",
        "score",
        "known_n",
        "expected_n",
        "source",
    ]
    with SCORES_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            budget = row.get("budget")
            if not isinstance(budget, int):
                continue
            writer.writerow(
                {
                    "model": MODEL_NAME_MAP[str(row["model"])],
                    "condition": "with BR" if row["mode"] == "with_br" else "without BR",
                    "metric": row["metric"],
                    "budget": budget,
                    "panel_label": f"{row['metric_label']} @{budget}",
                    "score": f"{float(row['plot_value']):.6f}",
                    "known_n": row["known_n"],
                    "expected_n": row["expected_n"],
                    "source": str(SOURCE_JSON.relative_to(REPO_ROOT)),
                }
            )


def save_figure(fig, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def style_polar_axis(ax, angles, labels, *, label_size: float = 7.0) -> None:
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


def plot_by_metric(
    *,
    score_table: dict[str, dict[str, dict[str, float]]],
    metric_specs: list[tuple[str, str]],
    budgets: list[int],
    stem: str,
    title: str,
    footnote: str,
    ncols: int,
) -> None:
    panels = [(metric, label, budget) for metric, label in metric_specs for budget in budgets]
    angles = np.linspace(0, 2 * np.pi, len(radar_base.MODELS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    model_labels = [model_label(model) for model in radar_base.MODELS]

    nrows = math.ceil(len(panels) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(3.95 * ncols, 4.55 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, (metric, label, budget) in enumerate(panels):
        ax = axes[idx]
        style_polar_axis(ax, angles, model_labels, label_size=6.8)
        key = metric_key(metric, budget)
        for condition, condition_label in CONDITIONS:
            values = np.array(
                [
                    score_table.get(key, {}).get(condition, {}).get(model, 0.0)
                    for model in radar_base.MODELS
                ]
            )
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(
                closed_angles,
                closed_values,
                color=CONDITION_COLORS[condition],
                linewidth=2.0,
                label=condition_label,
            )
            ax.fill(closed_angles, closed_values, color=CONDITION_COLORS[condition], alpha=0.14)
        ax.set_title(f"{label} @{budget}", fontsize=11.0, fontweight="bold", y=1.13)

    for ax in axes[len(panels) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle(title, fontsize=18, fontweight="bold", y=0.995)
    fig.text(0.02, 0.026, footnote, fontsize=8.5, color="#475569")
    fig.subplots_adjust(left=0.035, right=0.985, top=0.91, bottom=0.09, wspace=0.28, hspace=0.40)
    save_figure(fig, stem)


def main() -> None:
    rows = load_metric_rows()
    write_scores_csv(rows)
    score_table = build_score_table(rows)
    budgets = [1, 3, 5]
    plot_by_metric(
        score_table=score_table,
        metric_specs=ROUTE_CORE_METRICS,
        budgets=budgets,
        stem="toolong_action_budget_route_core_by_metric_radars_20260514",
        title="Toolong Action-Budget Route-Core Metrics",
        footnote=(
            "Each panel is one action-budget metric. Axes are models; traces compare without BR versus with BR. "
            "Action budget k means up to the first k non-neutral trajectory actions."
        ),
        ncols=3,
    )
    plot_by_metric(
        score_table=score_table,
        metric_specs=QUALITY_METRICS,
        budgets=budgets,
        stem="toolong_action_budget_quality_by_metric_radars_20260514",
        title="Toolong Action-Budget Quality Metrics",
        footnote=(
            "Each panel is one action-budget metric. Missing/unavailable handoff diagnostics are plotted as 0."
        ),
        ncols=3,
    )


if __name__ == "__main__":
    main()
