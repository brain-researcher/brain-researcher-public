#!/usr/bin/env python3
"""Generate current task/aspect x model paired BR radar figures.

This plot is deliberately high-level: every panel is one task family or
evaluation aspect, axes are the fixed model set, and the two traces compare
without BR versus with BR. All source metrics are already normalized to 0-1
quality scores where larger is better.
"""

from __future__ import annotations

import csv
import math
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[2]

QSM_SCORES = OUT_DIR / "qsm_current_paired_metric_scores_20260514.csv"
QSM_WIDE = REPO_ROOT / "docs/qsm_current_paired_metrics_wide_20260514.csv"
TOOL_SCORES = OUT_DIR / "top60_tool_calling_paired_scores.csv"
META_SCORES = OUT_DIR / "meta_analysis_radar_scores.csv"
KNOWLEDGE_SCORES = OUT_DIR / "neuroimage_knowledge_radar_scores.csv"

OUT_CSV = OUT_DIR / "task_model_paired_quality_scores_20260514.csv"

MODELS = [
    "Claude Code Opus 4.7",
    "Codex 5.5",
    "Gemini 3.1 Pro",
    "GLM 5.1",
    "DeepSeek v4 Pro",
    "Kimi K2.5",
    "Qwen 3.6 Plus",
]

MODEL_LABELS = {
    "Claude Code Opus 4.7": "Claude\nOpus 4.7",
    "Codex 5.5": "Codex\n5.5",
    "Gemini 3.1 Pro": "Gemini\n3.1 Pro",
    "GLM 5.1": "GLM\n5.1",
    "DeepSeek v4 Pro": "DeepSeek\nv4 Pro",
    "Kimi K2.5": "Kimi\nK2.5",
    "Qwen 3.6 Plus": "Qwen\n3.6 Plus",
}

MODEL_ALIASES = {
    "Claude Code Opus": "Claude Code Opus 4.7",
    "Claude Code Opus 4.7": "Claude Code Opus 4.7",
    "Codex 5.5": "Codex 5.5",
    "Codex GPT-5.5": "Codex 5.5",
    "Codex CLI GPT-5.5": "Codex 5.5",
    "Gemini 3.1 Pro": "Gemini 3.1 Pro",
    "Gemini 3.1 Pro Preview": "Gemini 3.1 Pro",
    "OpenCode Gemini 3.1 Pro Preview": "Gemini 3.1 Pro",
    "GLM 5.1": "GLM 5.1",
    "OpenCode GLM 5.1": "GLM 5.1",
    "DeepSeek v4 Pro": "DeepSeek v4 Pro",
    "OpenCode DeepSeek V4 Pro": "DeepSeek v4 Pro",
    "Kimi K2.5": "Kimi K2.5",
    "OpenCode Kimi K2.5": "Kimi K2.5",
    "Qwen 3.6 Plus": "Qwen 3.6 Plus",
    "OpenCode Qwen3.6 Plus": "Qwen 3.6 Plus",
}

TASK_ORDER = [
    "QSM binary reward",
    "QSM global fidelity",
    "QSM regional fidelity",
    "QSM calcification",
    "Tool routing",
    "Knowledge grounding",
    "Meta-analysis comparable",
    "Meta-analysis BR anchors",
]

TASK_NOTES = {
    "QSM binary reward": "QSM reward gate; all current rows are 0 because no model passed the binary verifier.",
    "QSM global fidelity": "Mean of NRMSE, dNRMSE, and slope-error quality scores.",
    "QSM regional fidelity": "Mean of tissue, blood, and DGM dNRMSE quality scores.",
    "QSM calcification": "Mean of CalcStreak and Calc Error quality scores.",
    "Tool routing": "Mean of Top60 capability, route/tool correctness, required-call trace, and clean-row coverage.",
    "Knowledge grounding": "Mean of NeuroimageKnowledge correctness, grounding, and citation-quality metrics.",
    "Meta-analysis comparable": "Mean of current comparable with/without-BR meta-analysis metrics.",
    "Meta-analysis BR anchors": "With-BR-only anchor/audit metrics; without-BR side is set to 0 by design.",
}

WITHOUT_COLOR = "#64748B"
WITH_COLOR = "#D97706"
DELTA_CMAP = "RdBu"


def canonical_model(name: str) -> str | None:
    return MODEL_ALIASES.get(name)


def parse_score(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    try:
        parsed = float(value)
    except ValueError:
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, min(1.0, parsed))


def mean_score(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return float(np.mean(vals))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def add_pair(
    rows: list[dict[str, str]],
    task: str,
    model: str,
    without_score: float,
    with_score: float,
    metrics: list[str],
    source: str,
    note: str = "",
) -> None:
    without_score = parse_score(str(without_score))
    with_score = parse_score(str(with_score))
    rows.append(
        {
            "task": task,
            "model": model,
            "without_br_score": f"{without_score:.6f}",
            "with_br_score": f"{with_score:.6f}",
            "delta_with_minus_without": f"{with_score - without_score:.6f}",
            "metrics_included": "; ".join(metrics),
            "source": source,
            "note": note,
        }
    )


def build_qsm_rows(rows: list[dict[str, str]]) -> None:
    qsm = defaultdict(lambda: defaultdict(dict))
    for row in read_csv(QSM_SCORES):
        model = canonical_model(row["model"])
        if model is None:
            continue
        qsm[model][row["condition"]][row["metric"]] = parse_score(row["score"])

    rewards = {model: {"without_br": 0.0, "with_br": 0.0} for model in MODELS}
    for row in read_csv(QSM_WIDE):
        model = canonical_model(row["model"])
        if model is None:
            continue
        rewards[model]["without_br"] = parse_score(row.get("without_br_reward"))
        rewards[model]["with_br"] = parse_score(row.get("with_br_reward"))

    groups = {
        "QSM global fidelity": ["NRMSE", "dNRMSE", "Slope error"],
        "QSM regional fidelity": ["Tissue dNRMSE", "Blood dNRMSE", "DGM dNRMSE"],
        "QSM calcification": ["CalcStreak", "Calc error"],
    }

    for model in MODELS:
        add_pair(
            rows,
            "QSM binary reward",
            model,
            rewards[model]["without_br"],
            rewards[model]["with_br"],
            ["reward"],
            str(QSM_WIDE.relative_to(REPO_ROOT)),
            TASK_NOTES["QSM binary reward"],
        )
        for task, metrics in groups.items():
            add_pair(
                rows,
                task,
                model,
                mean_score(qsm[model]["without_br"].get(metric, 0.0) for metric in metrics),
                mean_score(qsm[model]["with_br"].get(metric, 0.0) for metric in metrics),
                metrics,
                str(QSM_SCORES.relative_to(REPO_ROOT)),
                TASK_NOTES[task],
            )


def build_tool_rows(rows: list[dict[str, str]]) -> None:
    scores = defaultdict(lambda: defaultdict(dict))
    metrics: list[str] = []
    for row in read_csv(TOOL_SCORES):
        model = canonical_model(row["model"])
        if model is None:
            continue
        condition = "with_br" if row["condition"] == "with BR" else "without_br"
        metric = row["metric"]
        if metric not in metrics:
            metrics.append(metric)
        scores[model][condition][metric] = parse_score(row["score"])

    for model in MODELS:
        add_pair(
            rows,
            "Tool routing",
            model,
            mean_score(scores[model]["without_br"].get(metric, 0.0) for metric in metrics),
            mean_score(scores[model]["with_br"].get(metric, 0.0) for metric in metrics),
            metrics,
            str(TOOL_SCORES.relative_to(REPO_ROOT)),
            TASK_NOTES["Tool routing"],
        )


def build_knowledge_rows(rows: list[dict[str, str]]) -> None:
    scores = defaultdict(lambda: defaultdict(dict))
    metrics: list[str] = []
    for row in read_csv(KNOWLEDGE_SCORES):
        if row.get("scope") != "model":
            continue
        model = canonical_model(row["model"])
        if model is None:
            continue
        metric = row["metric"]
        if metric not in metrics:
            metrics.append(metric)
        scores[model][row["condition"]][metric] = parse_score(row["score"])

    for model in MODELS:
        add_pair(
            rows,
            "Knowledge grounding",
            model,
            mean_score(scores[model]["without_br"].get(metric, 0.0) for metric in metrics),
            mean_score(scores[model]["with_br"].get(metric, 0.0) for metric in metrics),
            metrics,
            str(KNOWLEDGE_SCORES.relative_to(REPO_ROOT)),
            TASK_NOTES["Knowledge grounding"],
        )


def build_meta_rows(rows: list[dict[str, str]]) -> None:
    comparable = defaultdict(lambda: defaultdict(dict))
    anchors = defaultdict(dict)
    comparable_metrics: list[str] = []
    anchor_metrics: list[str] = []

    for row in read_csv(META_SCORES):
        model = canonical_model(row["model"])
        if model is None:
            continue
        metric = row["metric"]
        if row["metric_group"] == "comparable_meta_analysis":
            if metric not in comparable_metrics:
                comparable_metrics.append(metric)
            comparable[model][row["br_condition"]][metric] = parse_score(row["score"])
        elif row["metric_group"] == "with_br_anchor_audit":
            if metric not in anchor_metrics:
                anchor_metrics.append(metric)
            anchors[model][metric] = parse_score(row["score"])

    for model in MODELS:
        add_pair(
            rows,
            "Meta-analysis comparable",
            model,
            mean_score(comparable[model]["without_br"].get(metric, 0.0) for metric in comparable_metrics),
            mean_score(comparable[model]["with_br"].get(metric, 0.0) for metric in comparable_metrics),
            comparable_metrics,
            str(META_SCORES.relative_to(REPO_ROOT)),
            TASK_NOTES["Meta-analysis comparable"],
        )
        add_pair(
            rows,
            "Meta-analysis BR anchors",
            model,
            0.0,
            mean_score(anchors[model].get(metric, 0.0) for metric in anchor_metrics),
            anchor_metrics,
            str(META_SCORES.relative_to(REPO_ROOT)),
            TASK_NOTES["Meta-analysis BR anchors"],
        )


def build_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    build_qsm_rows(rows)
    build_tool_rows(rows)
    build_knowledge_rows(rows)
    build_meta_rows(rows)
    return rows


def write_scores_csv(rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "task",
        "model",
        "without_br_score",
        "with_br_score",
        "delta_with_minus_without",
        "metrics_included",
        "source",
        "note",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def wrap_label(label: str, width: int = 12) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def score_lookup(rows: list[dict[str, str]], task: str, model: str, condition: str) -> float:
    key = "with_br_score" if condition == "with_br" else "without_br_score"
    for row in rows:
        if row["task"] == task and row["model"] == model:
            return parse_score(row[key])
    return 0.0


def save_figure(fig, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def plot_task_model_radars(rows: list[dict[str, str]]) -> None:
    angles = np.linspace(0, 2 * np.pi, len(MODELS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 4
    nrows = math.ceil(len(TASK_ORDER) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(17.6, 4.35 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, task in enumerate(TASK_ORDER):
        ax = axes[idx]
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([MODEL_LABELS[model] for model in MODELS], fontsize=7.1, color="#475569")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.3, color="#64748B")
        ax.grid(color="#CBD5E1", linewidth=0.75, alpha=0.9)
        ax.spines["polar"].set_color("#94A3B8")

        without_values = np.array([score_lookup(rows, task, model, "without_br") for model in MODELS])
        with_values = np.array([score_lookup(rows, task, model, "with_br") for model in MODELS])
        ax.plot(
            closed_angles,
            np.concatenate([without_values, [without_values[0]]]),
            color=WITHOUT_COLOR,
            linewidth=1.8,
            label="without BR",
        )
        ax.fill(
            closed_angles,
            np.concatenate([without_values, [without_values[0]]]),
            color=WITHOUT_COLOR,
            alpha=0.10,
        )
        ax.plot(
            closed_angles,
            np.concatenate([with_values, [with_values[0]]]),
            color=WITH_COLOR,
            linewidth=2.1,
            label="with BR",
        )
        ax.fill(
            closed_angles,
            np.concatenate([with_values, [with_values[0]]]),
            color=WITH_COLOR,
            alpha=0.18,
        )
        ax.set_title(wrap_label(task, 18), fontsize=10.7, fontweight="bold", y=1.13)

    for ax in axes[len(TASK_ORDER) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.052),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    fig.suptitle("Task/Aspect x Model Paired BR Quality Radars", fontsize=17, fontweight="bold", y=0.99)
    fig.text(
        0.018,
        0.018,
        "Every axis is a model. Scores are 0-1 and higher is better. Missing/not-run/unavailable rows stay at 0; BR-anchor panel is with-BR-only by design.",
        fontsize=8.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.035, right=0.985, top=0.88, bottom=0.145, wspace=0.36, hspace=0.52)
    save_figure(fig, "task_model_paired_quality_radars_20260514")


def plot_delta_heatmap(rows: list[dict[str, str]]) -> None:
    matrix = np.array(
        [
            [
                float(
                    next(
                        row["delta_with_minus_without"]
                        for row in rows
                        if row["task"] == task and row["model"] == model
                    )
                )
                for model in MODELS
            ]
            for task in TASK_ORDER
        ]
    )

    fig, ax = plt.subplots(figsize=(12.4, 6.5))
    im = ax.imshow(matrix, cmap=DELTA_CMAP, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(MODELS)))
    ax.set_xticklabels([MODEL_LABELS[model].replace("\n", " ") for model in MODELS], rotation=30, ha="right")
    ax.set_yticks(range(len(TASK_ORDER)))
    ax.set_yticklabels([wrap_label(task, 24) for task in TASK_ORDER], fontsize=9)

    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            value = matrix[row_idx, col_idx]
            text_color = "white" if abs(value) > 0.45 else "#111827"
            ax.text(col_idx, row_idx, f"{value:+.2f}", ha="center", va="center", color=text_color, fontsize=8)

    ax.set_title("With BR Minus Without BR Quality Delta", fontsize=15, fontweight="bold", pad=12)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cbar.set_label("Delta in 0-1 score", fontsize=9)
    fig.text(
        0.01,
        0.012,
        "Positive values favor with-BR. Negative values favor without-BR. BR-anchor deltas are not capability-comparable because no-BR has no BR-anchor surface.",
        fontsize=8.3,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.98))
    save_figure(fig, "task_model_paired_quality_delta_heatmap_20260514")


def main() -> None:
    rows = build_rows()
    write_scores_csv(rows)
    plot_task_model_radars(rows)
    plot_delta_heatmap(rows)
    print(OUT_CSV)
    print(OUT_DIR / "task_model_paired_quality_radars_20260514.png")
    print(OUT_DIR / "task_model_paired_quality_delta_heatmap_20260514.png")


if __name__ == "__main__":
    main()
