#!/usr/bin/env python3
"""Generate NeuroimageKnowledge radar figures.

This mirrors the plotting style in plot_model_eval_radars.py, but uses only the
selected NeuroimageKnowledge comparison rows. All displayed axes are 0-1 and
higher-is-better.
"""

from __future__ import annotations

import csv
import json
import math
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).resolve().parent
BENCHMARK_RUN = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher_benchmark/"
    "NeuroimageKnowledge/runs/full_groundable_answer_first_gated_with_br_20260514"
)
SOURCE_JSON = BENCHMARK_RUN / "top50_br_separation_metrics.json"
SOURCE_NOTE = "NeuroimageKnowledge selected comparison metrics"

MODELS = [
    "Claude Code Opus 4.7",
    "Codex GPT-5.5",
    "Gemini 3.1 Pro",
    "GLM 5.1",
    "DeepSeek v4 Pro",
    "Kimi K2.5",
    "Qwen 3.6 Plus",
]

MODEL_KEY_TO_LABEL = {
    "claude_opus47": "Claude Code Opus 4.7",
    "codex_gpt55": "Codex GPT-5.5",
    "opencode_gemini31_pro": "Gemini 3.1 Pro",
    "opencode_glm51": "GLM 5.1",
    "opencode_deepseek_v4_pro": "DeepSeek v4 Pro",
    "opencode_kimi25": "Kimi K2.5",
    "opencode_qwen36_plus": "Qwen 3.6 Plus",
}

MODEL_SHORT_LABELS = {
    "Claude Code Opus 4.7": "Claude\nOpus 4.7",
    "Codex GPT-5.5": "Codex\n5.5",
    "Gemini 3.1 Pro": "Gemini\n3.1 Pro",
    "GLM 5.1": "GLM\n5.1",
    "DeepSeek v4 Pro": "DeepSeek\nv4 Pro",
    "Kimi K2.5": "Kimi\nK2.5",
    "Qwen 3.6 Plus": "Qwen\n3.6 Plus",
}

COLORS = {
    "Claude Code Opus 4.7": "#4C78A8",
    "Codex GPT-5.5": "#F58518",
    "Gemini 3.1 Pro": "#54A24B",
    "GLM 5.1": "#E45756",
    "DeepSeek v4 Pro": "#72B7B2",
    "Kimi K2.5": "#B279A2",
    "Qwen 3.6 Plus": "#FF9DA6",
}

WITHOUT_COLOR = "#6B7280"
WITH_COLOR = "#0072B2"

METRICS = [
    ("mean_correctness", "Mean correctness"),
    ("answer_correctness", "Correct answer rate"),
    ("grounded_claim_share", "Grounded claim share"),
    ("verified_groundedness", "Verified groundedness"),
    ("verified_among_claimed", "Verified/claimed"),
    ("supportable_among_claimed", "Supportable/claimed"),
    ("citation_precision", "Citation precision"),
    ("judgeable_rate", "Judgeable refs"),
]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def wrap_label(label: str, width: int = 13) -> str:
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def save_figure(fig, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def condition_scores(correctness: dict, grounding: dict) -> dict[str, float]:
    total_evidence = float(grounding.get("total_evidence_items") or 0.0)
    claimed_grounded = float(grounding.get("claimed_grounded_items") or 0.0)
    return {
        "mean_correctness": clamp01(correctness.get("mean_correctness_score", 0.0)),
        "answer_correctness": clamp01(correctness.get("answer_correctness_rate", 0.0)),
        "grounded_claim_share": clamp01(claimed_grounded / total_evidence if total_evidence else 0.0),
        "verified_groundedness": clamp01(grounding.get("verified_groundedness_rate", 0.0)),
        "verified_among_claimed": clamp01(grounding.get("verified_among_claimed_grounded", 0.0)),
        "supportable_among_claimed": clamp01(grounding.get("supportable_among_claimed_grounded", 0.0)),
        "citation_precision": clamp01(1.0 - grounding.get("citation_spam_rate", 0.0)),
        "judgeable_rate": clamp01(1.0 - grounding.get("cannot_judge_rate", 0.0)),
    }


def build_records() -> tuple[list[dict[str, str]], dict[str, dict[str, dict[str, float]]], dict[str, dict[str, float]]]:
    data = json.loads(SOURCE_JSON.read_text())
    records: list[dict[str, str]] = []
    model_scores: dict[str, dict[str, dict[str, float]]] = {}

    aggregate_scores = {
        "without": condition_scores(
            data["aggregate_correctness"]["without"],
            data["aggregate_grounding"]["without"],
        ),
        "with": condition_scores(
            data["aggregate_correctness"]["with"],
            data["aggregate_grounding"]["with"],
        ),
    }

    for condition, scores in aggregate_scores.items():
        for metric_key, metric_label in METRICS:
            records.append(
                {
                    "scope": "aggregate",
                    "model": "All models",
                    "condition": "with_br" if condition == "with" else "without_br",
                    "metric": metric_label,
                    "score": f"{scores[metric_key]:.6f}",
                    "source": SOURCE_NOTE,
                }
            )

    for row in data["by_model"]:
        model = MODEL_KEY_TO_LABEL[row["model"]]
        model_scores[model] = {
            "without": condition_scores(row["without_correctness"], row["without_grounding"]),
            "with": condition_scores(row["with_correctness"], row["with_grounding"]),
        }
        for condition in ("without", "with"):
            for metric_key, metric_label in METRICS:
                records.append(
                    {
                        "scope": "model",
                        "model": model,
                        "condition": "with_br" if condition == "with" else "without_br",
                        "metric": metric_label,
                        "score": f"{model_scores[model][condition][metric_key]:.6f}",
                        "source": SOURCE_NOTE,
                    }
                )

    return records, model_scores, aggregate_scores


def write_scores_csv(records: list[dict[str, str]]) -> None:
    with (OUT_DIR / "neuroimage_knowledge_radar_scores.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["scope", "model", "condition", "metric", "score", "source"],
        )
        writer.writeheader()
        writer.writerows(records)


def setup_polar(ax, labels: list[str], label_width: int = 13) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 1)
    ax.set_xticks(angles)
    ax.set_xticklabels([wrap_label(label, label_width) for label in labels], fontsize=8, color="#374151")
    ax.set_rlabel_position(0)
    ax.set_yticks([0.25, 0.50, 0.75, 1.0])
    ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=7, color="#6B7280")
    ax.grid(color="#CBD5E1", linewidth=0.75, alpha=0.9)
    ax.spines["polar"].set_color("#94A3B8")
    return angles


def closed(values: list[float], angles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.concatenate([angles, [angles[0]]]), np.concatenate([values, [values[0]]])


def metric_values(scores: dict[str, float]) -> list[float]:
    return [scores[key] for key, _ in METRICS]


def plot_aggregate_radar(aggregate_scores: dict[str, dict[str, float]]) -> None:
    labels = [label for _, label in METRICS]
    fig, ax = plt.subplots(figsize=(8.8, 7.2), subplot_kw={"projection": "polar"})
    angles = setup_polar(ax, labels, label_width=12)

    for condition, color, label in [
        ("without", WITHOUT_COLOR, "without BR"),
        ("with", WITH_COLOR, "+BR fixed prompt/gate"),
    ]:
        theta, vals = closed(metric_values(aggregate_scores[condition]), angles)
        ax.plot(theta, vals, color=color, linewidth=2.4, label=label)
        ax.fill(theta, vals, color=color, alpha=0.13)

    ax.set_title("NeuroimageKnowledge: Aggregate Profile", fontsize=15, fontweight="bold", pad=24)
    ax.legend(loc="center left", bbox_to_anchor=(1.07, 0.5), frameon=False, fontsize=9)
    fig.text(
        0.02,
        0.015,
        "NeuroimageKnowledge comparison; all axes are 0-1 and higher-is-better.",
        fontsize=8,
        color="#4B5563",
    )
    save_figure(fig, "neuroimage_knowledge_aggregate_radar")


def plot_model_faceted_radar(model_scores: dict[str, dict[str, dict[str, float]]]) -> None:
    labels = [label for _, label in METRICS]
    ncols = 3
    nrows = math.ceil(len(MODELS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(13.5, 4.2 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(MODELS):
        ax = axes[idx]
        angles = setup_polar(ax, labels, label_width=9)
        for condition, color, label, alpha in [
            ("without", WITHOUT_COLOR, "without BR", 0.08),
            ("with", COLORS[model], "+BR", 0.24),
        ]:
            theta, vals = closed(metric_values(model_scores[model][condition]), angles)
            ax.plot(theta, vals, color=color, linewidth=2.0, label=label)
            ax.fill(theta, vals, color=color, alpha=alpha)
        ax.set_title(model, color=COLORS[model], fontsize=10.5, fontweight="bold", y=1.13)
        if idx == 0:
            ax.legend(loc="upper right", bbox_to_anchor=(1.32, 1.20), frameon=False, fontsize=7.5)

    for ax in axes[len(MODELS) :]:
        ax.set_axis_off()

    fig.suptitle("NeuroimageKnowledge: Model Profiles", fontsize=16, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.012,
        "NeuroimageKnowledge comparison. Gray is without BR; colored trace is fixed +BR.",
        fontsize=8,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.04, right=0.98, top=0.92, bottom=0.06, wspace=0.34, hspace=0.48)
    save_figure(fig, "neuroimage_knowledge_model_faceted_radar")


def plot_metric_by_model_paired_radar(model_scores: dict[str, dict[str, dict[str, float]]]) -> None:
    ncols = 4
    nrows = math.ceil(len(METRICS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(15.0, 4.1 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)
    labels = [MODEL_SHORT_LABELS[model] for model in MODELS]

    for idx, (metric_key, metric_label) in enumerate(METRICS):
        ax = axes[idx]
        angles = setup_polar(ax, labels, label_width=8)
        without_vals = [model_scores[model]["without"][metric_key] for model in MODELS]
        with_vals = [model_scores[model]["with"][metric_key] for model in MODELS]
        for vals, color, label, alpha in [
            (without_vals, WITHOUT_COLOR, "without BR", 0.10),
            (with_vals, WITH_COLOR, "+BR fixed", 0.17),
        ]:
            theta, closed_vals = closed(vals, angles)
            ax.plot(theta, closed_vals, color=color, linewidth=2.0, label=label)
            ax.fill(theta, closed_vals, color=color, alpha=alpha)
        ax.set_title(metric_label, fontsize=10.5, fontweight="bold", y=1.13)
        if idx == 0:
            ax.legend(loc="upper right", bbox_to_anchor=(1.36, 1.22), frameon=False, fontsize=7.5)

    for ax in axes[len(METRICS) :]:
        ax.set_axis_off()

    fig.suptitle("NeuroimageKnowledge: Paired Metrics Across Models", fontsize=16, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.012,
        "Each panel is one metric; axes are models. All metrics are transformed so higher is better.",
        fontsize=8,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.04, right=0.98, top=0.88, bottom=0.08, wspace=0.42, hspace=0.52)
    save_figure(fig, "neuroimage_knowledge_metric_by_model_paired_radar")


def main() -> None:
    records, model_scores, aggregate_scores = build_records()
    write_scores_csv(records)
    plot_aggregate_radar(aggregate_scores)
    plot_model_faceted_radar(model_scores)
    plot_metric_by_model_paired_radar(model_scores)


if __name__ == "__main__":
    main()
