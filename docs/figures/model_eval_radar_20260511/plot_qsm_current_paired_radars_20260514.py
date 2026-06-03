#!/usr/bin/env python3
"""Generate current paired QSM with/without BR radar figures.

This follows the scoring convention used by plot_model_eval_radars.py:
lower-is-better QSM metrics are converted to 0-1 quality scores as
best_observed_value / row_value. Missing, zero, or non-finite rows are encoded
as 0 so unavailable metric rows stay visible without being treated as good.
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
WIDE_CSV = REPO_ROOT / "docs/qsm_current_paired_metrics_wide_20260514.csv"
SOURCE_NOTE = "docs/qsm_current_paired_metrics_wide_20260514.csv"

MODEL_ORDER = [
    "Claude Code Opus 4.7",
    "Codex 5.5",
    "Gemini 3.1 Pro Preview",
    "GLM 5.1",
    "DeepSeek v4 Pro",
    "Kimi K2.5",
    "Qwen 3.6 Plus",
]

DISPLAY_MODEL = {
    "Claude Code Opus 4.7": "Claude Code\nOpus 4.7",
    "Codex 5.5": "Codex\n5.5",
    "Gemini 3.1 Pro Preview": "Gemini\n3.1 Pro",
    "GLM 5.1": "GLM\n5.1",
    "DeepSeek v4 Pro": "DeepSeek\nv4 Pro",
    "Kimi K2.5": "Kimi\nK2.5",
    "Qwen 3.6 Plus": "Qwen\n3.6 Plus",
}

COLORS = {
    "without_br": "#64748B",
    "with_br": "#D97706",
}

METRICS = [
    ("nrmse", "NRMSE"),
    ("dnrmse", "dNRMSE"),
    ("dnrmse_tissue", "Tissue dNRMSE"),
    ("dnrmse_blood", "Blood dNRMSE"),
    ("dnrmse_dgm", "DGM dNRMSE"),
    ("slope_error", "Slope error"),
    ("calcstreak", "CalcStreak"),
    ("calc_error", "Calc error"),
]


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def wrap_label(label: str, width: int = 11) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def read_rows() -> dict[str, dict[str, object]]:
    with WIDE_CSV.open(newline="") as handle:
        rows = {row["model"]: row for row in csv.DictReader(handle)}
    missing = [model for model in MODEL_ORDER if model not in rows]
    if missing:
        raise SystemExit(f"Missing models in {WIDE_CSV}: {missing}")
    return rows


def build_scores(rows: dict[str, dict[str, object]]):
    raw = {
        model: {
            condition: {
                metric_key: parse_float(rows[model].get(f"{condition}_{metric_key}"))
                for metric_key, _ in METRICS
            }
            for condition in ("without_br", "with_br")
        }
        for model in MODEL_ORDER
    }

    best_by_metric = {}
    for metric_key, _ in METRICS:
        values = [
            raw[model][condition][metric_key]
            for model in MODEL_ORDER
            for condition in ("without_br", "with_br")
            if raw[model][condition][metric_key] is not None
        ]
        best_by_metric[metric_key] = min(values) if values else None

    score = {
        model: {
            condition: {}
            for condition in ("without_br", "with_br")
        }
        for model in MODEL_ORDER
    }
    for model in MODEL_ORDER:
        for condition in ("without_br", "with_br"):
            for metric_key, _ in METRICS:
                value = raw[model][condition][metric_key]
                best = best_by_metric[metric_key]
                if value is None or best is None:
                    score[model][condition][metric_key] = 0.0
                else:
                    score[model][condition][metric_key] = max(0.0, min(1.0, best / value))
    return raw, score


def write_score_csv(raw, score):
    out = OUT_DIR / "qsm_current_paired_metric_scores_20260514.csv"
    fieldnames = [
        "model",
        "condition",
        "metric",
        "raw_value",
        "score",
        "score_method",
        "source",
    ]
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for model in MODEL_ORDER:
            for condition in ("without_br", "with_br"):
                for metric_key, metric_label in METRICS:
                    value = raw[model][condition][metric_key]
                    writer.writerow(
                        {
                            "model": model,
                            "condition": condition,
                            "metric": metric_label,
                            "raw_value": "" if value is None else f"{value:.6g}",
                            "score": f"{score[model][condition][metric_key]:.6f}",
                            "score_method": "best_observed_value / row_value; missing_or_nonfinite_to_0",
                            "source": SOURCE_NOTE,
                        }
                    )
    return out


def save_figure(fig, stem: str):
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def plot_by_model(score):
    """One panel per model; axes are QSM metrics; traces are without/with BR."""

    metric_labels = [label for _, label in METRICS]
    angles = np.linspace(0, 2 * np.pi, len(METRICS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 3
    nrows = math.ceil(len(MODEL_ORDER) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(14.0, 4.2 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(MODEL_ORDER):
        ax = axes[idx]
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([wrap_label(label, 9) for label in metric_labels], fontsize=7, color="#475569")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.5, color="#64748B")
        ax.grid(color="#CBD5E1", linewidth=0.75, alpha=0.9)
        ax.spines["polar"].set_color("#94A3B8")

        for condition, label in (("without_br", "without BR"), ("with_br", "with BR")):
            values = np.array([score[model][condition][metric_key] for metric_key, _ in METRICS])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(closed_angles, closed_values, color=COLORS[condition], linewidth=2.0, label=label)
            ax.fill(closed_angles, closed_values, color=COLORS[condition], alpha=0.14)

        ax.set_title(DISPLAY_MODEL[model].replace("\n", " "), fontsize=10.5, fontweight="bold", y=1.14)

    for ax in axes[len(MODEL_ORDER) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle("Current QSM Paired Metric Profiles", fontsize=17, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.026,
        "Each panel is one model; axes are QSM verifier metrics. Scores are 0-1 lower-is-better quality scores; missing/non-finite metrics are 0.",
        fontsize=8.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.915, bottom=0.09, wspace=0.32, hspace=0.50)
    save_figure(fig, "qsm_current_paired_by_model_radars_20260514")


def plot_by_metric(score):
    """One panel per metric; axes are models; traces are without/with BR."""

    angles = np.linspace(0, 2 * np.pi, len(MODEL_ORDER), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 3
    nrows = math.ceil(len(METRICS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(15.5, 4.25 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, (metric_key, metric_label) in enumerate(METRICS):
        ax = axes[idx]
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([DISPLAY_MODEL[model] for model in MODEL_ORDER], fontsize=7.2, color="#475569")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.5, color="#64748B")
        ax.grid(color="#CBD5E1", linewidth=0.75, alpha=0.9)
        ax.spines["polar"].set_color("#94A3B8")

        for condition, label in (("without_br", "without BR"), ("with_br", "with BR")):
            values = np.array([score[model][condition][metric_key] for model in MODEL_ORDER])
            closed_values = np.concatenate([values, [values[0]]])
            ax.plot(closed_angles, closed_values, color=COLORS[condition], linewidth=2.0, label=label)
            ax.fill(closed_angles, closed_values, color=COLORS[condition], alpha=0.14)

        ax.set_title(metric_label, fontsize=11.5, fontweight="bold", y=1.12)

    for ax in axes[len(METRICS) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle("Current QSM Metric x Model Paired BR Radars", fontsize=17, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.026,
        "Each panel is one verifier metric; axes are models. Scores use best_observed/value normalization across current with/without BR rows.",
        fontsize=8.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.915, bottom=0.09, wspace=0.34, hspace=0.48)
    save_figure(fig, "qsm_current_paired_by_metric_radars_20260514")


def main():
    rows = read_rows()
    raw, score = build_scores(rows)
    score_csv = write_score_csv(raw, score)
    plot_by_model(score)
    plot_by_metric(score)
    print(score_csv)
    print(OUT_DIR / "qsm_current_paired_by_model_radars_20260514.png")
    print(OUT_DIR / "qsm_current_paired_by_metric_radars_20260514.png")


if __name__ == "__main__":
    main()
