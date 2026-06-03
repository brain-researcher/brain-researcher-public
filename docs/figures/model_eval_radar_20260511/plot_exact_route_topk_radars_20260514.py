#!/usr/bin/env python3
"""Plot exact-routing top-k metrics from the current manual-curated v2 evals."""

from __future__ import annotations

import csv
import json
import math
import textwrap
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]
SOURCE_DIR = REPO_ROOT / "benchmarks" / "tool_routing_validation"
SCORES_CSV = OUT_DIR / "exact_route_topk_scores_20260514.csv"

SETUPS = [
    (
        "br_unified_full",
        "BR Unified\n440",
        SOURCE_DIR / "exact_eval_br_unified_manual_curated_v2.json",
        "#0F766E",
    ),
    (
        "codex_without_br",
        "Codex\nwithout BR\n22",
        SOURCE_DIR / "exact_eval_codex_only_manual_curated_v2.json",
        "#64748B",
    ),
    (
        "codex_with_br",
        "Codex\nwith BR\n22",
        SOURCE_DIR / "exact_eval_codex_plus_br_manual_curated_v2.json",
        "#D97706",
    ),
]

CODEX_CONDITIONS = [
    ("codex_without_br", "without BR", "#64748B"),
    ("codex_with_br", "with BR", "#D97706"),
]

TOPK_METRICS = [
    ("tool_recall_at_1", "Tool R@1"),
    ("tool_recall_at_3", "Tool R@3"),
    ("tool_recall_at_5", "Tool R@5"),
    ("family_recall_at_1", "Family R@1"),
    ("family_recall_at_3", "Family R@3"),
    ("family_recall_at_5", "Family R@5"),
    ("sequence_recall_at_1", "Sequence R@1"),
    ("sequence_recall_at_3", "Sequence R@3"),
    ("sequence_recall_at_5", "Sequence R@5"),
    ("top1_correct_tool", "Top1 correct"),
]

FAMILY_PANELS = [
    (
        "Tool recall",
        [
            ("tool_recall_at_1", "R@1"),
            ("tool_recall_at_3", "R@3"),
            ("tool_recall_at_5", "R@5"),
        ],
    ),
    (
        "Family recall",
        [
            ("family_recall_at_1", "R@1"),
            ("family_recall_at_3", "R@3"),
            ("family_recall_at_5", "R@5"),
        ],
    ),
    (
        "Sequence recall",
        [
            ("sequence_recall_at_1", "R@1"),
            ("sequence_recall_at_3", "R@3"),
            ("sequence_recall_at_5", "R@5"),
        ],
    ),
]


def clamp01(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def wrap_label(label: str, width: int = 11) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def read_scores() -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    for setup_id, setup_label, source, color in SETUPS:
        payload = json.loads(source.read_text())
        summary = payload["summary"]
        metrics = {name: clamp01(summary.get(name)) for name, _ in TOPK_METRICS}
        metrics["top1_correct_tool"] = 1.0 - clamp01(summary.get("wrong_tool_top1_rate"))
        scores[setup_id] = {
            "label": setup_label,
            "source": source,
            "color": color,
            "evaluated_tasks": int(summary.get("evaluated_tasks") or 0),
            "missing_predictions": int(summary.get("skipped_missing_predictions") or 0),
            "metrics": metrics,
        }
    return scores


def write_scores_csv(scores: dict[str, dict[str, Any]]) -> None:
    fieldnames = [
        "setup_id",
        "setup_label",
        "metric",
        "metric_label",
        "score",
        "evaluated_tasks",
        "missing_predictions",
        "source",
    ]
    with SCORES_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for setup_id, setup_label, source, _ in SETUPS:
            setup = scores[setup_id]
            for metric, metric_label in TOPK_METRICS:
                writer.writerow(
                    {
                        "setup_id": setup_id,
                        "setup_label": setup_label.replace("\n", " "),
                        "metric": metric,
                        "metric_label": metric_label,
                        "score": f"{setup['metrics'][metric]:.6f}",
                        "evaluated_tasks": setup["evaluated_tasks"],
                        "missing_predictions": setup["missing_predictions"],
                        "source": str(source.relative_to(REPO_ROOT)),
                    }
                )


def save_figure(fig, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def style_polar_axis(ax, angles, labels, *, label_size: float = 8.0) -> None:
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 1)
    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=label_size, color="#475569")
    ax.set_rlabel_position(0)
    ax.set_yticks([0.25, 0.50, 0.75, 1.0])
    ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.8, color="#64748B")
    ax.grid(color="#CBD5E1", linewidth=0.75, alpha=0.9)
    ax.spines["polar"].set_color("#94A3B8")


def plot_metric_panels(scores: dict[str, dict[str, Any]]) -> None:
    """One panel per exact metric; axes are exact-routing setups."""

    angles = np.linspace(0, 2 * np.pi, len(SETUPS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    setup_labels = [scores[setup_id]["label"] for setup_id, _, _, _ in SETUPS]

    ncols = 5
    nrows = math.ceil(len(TOPK_METRICS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(18.0, 4.3 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, (metric, metric_label) in enumerate(TOPK_METRICS):
        ax = axes[idx]
        style_polar_axis(ax, angles, setup_labels, label_size=7.7)
        values = np.array(
            [scores[setup_id]["metrics"][metric] for setup_id, _, _, _ in SETUPS]
        )
        closed_values = np.concatenate([values, [values[0]]])
        ax.plot(closed_angles, closed_values, color="#0F172A", linewidth=2.0)
        ax.fill(closed_angles, closed_values, color="#0EA5E9", alpha=0.16)
        for angle, value, (_, _, _, color) in zip(angles, values, SETUPS):
            ax.scatter([angle], [value], color=color, s=28, zorder=4)
        ax.set_title(metric_label, fontsize=11.0, fontweight="bold", y=1.14)

    for ax in axes[len(TOPK_METRICS) :]:
        ax.set_axis_off()

    fig.suptitle(
        "Exact Route Top-k Metrics Split Out",
        fontsize=20,
        fontweight="bold",
        y=0.995,
    )
    fig.text(
        0.5,
        0.035,
        "Each panel is one raw exact-routing metric. Axes are current manual-curated v2 setups. "
        "Top1 correct is 1 - wrong_tool_top1_rate; higher is better.",
        ha="center",
        fontsize=9.5,
        color="#475569",
    )
    save_figure(fig, "exact_route_topk_by_metric_radars_20260514")


def plot_codex_family_panels(scores: dict[str, dict[str, Any]]) -> None:
    """Codex-only paired view; axes are top-k thresholds."""

    angles = np.linspace(0, 2 * np.pi, 3, endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    fig, axes = plt.subplots(
        1,
        len(FAMILY_PANELS),
        figsize=(13.5, 4.6),
        subplot_kw={"projection": "polar"},
    )

    for ax, (panel_title, metrics) in zip(axes, FAMILY_PANELS):
        style_polar_axis(ax, angles, [label for _, label in metrics], label_size=8.5)
        for setup_id, condition_label, color in CODEX_CONDITIONS:
            values = np.array([scores[setup_id]["metrics"][metric] for metric, _ in metrics])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(closed_angles, closed_values, color=color, linewidth=2.3, label=condition_label)
            ax.fill(closed_angles, closed_values, color=color, alpha=0.14)
        ax.set_title(panel_title, fontsize=12.0, fontweight="bold", y=1.15)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10.0)
    fig.suptitle(
        "Codex Exact Route Top-k Paired Metrics",
        fontsize=19,
        fontweight="bold",
        y=1.03,
    )
    fig.text(
        0.5,
        0.04,
        "Manual-curated v2 exact-label subset, same 22 Codex predictions per condition. Higher is better.",
        ha="center",
        fontsize=9.5,
        color="#475569",
    )
    fig.subplots_adjust(bottom=0.18, top=0.80, wspace=0.35)
    save_figure(fig, "exact_route_topk_codex_paired_family_radars_20260514")


def main() -> None:
    scores = read_scores()
    write_scores_csv(scores)
    plot_metric_panels(scores)
    plot_codex_family_panels(scores)


if __name__ == "__main__":
    main()
