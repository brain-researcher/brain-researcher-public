#!/usr/bin/env python
"""Quick plotting helper for BR-KG retrieval benchmarks.

Generates two PNGs under data/br-kg_exports/plots:
- recall_macro.png: Recall@5 and Macro-F1 for random vs grouped splits.
- tail_recall.png: Tail Recall@5 comparison (random vs grouped).
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import pathlib

OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "br_kg_exports" / "plots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Hard-coded results (top-5) from runs on 2025-12-14
random_results = {
    "TF-IDF": {"recall": 0.861, "macro_f1": 0.263, "tail_recall": 0.40},
    "BM25": {"recall": 0.458, "macro_f1": 0.062, "tail_recall": 0.00},
    "Gemini": {"recall": 0.944, "macro_f1": 0.381, "tail_recall": 0.60},
}

grouped_results = {
    "TF-IDF": {"recall": 0.096, "macro_f1": 0.009, "tail_recall": 0.00},
    "Gemini": {"recall": 0.117, "macro_f1": 0.028, "tail_recall": 0.00},
}


def plot_overall():
    fig, ax = plt.subplots(figsize=(8, 4))
    models_random = list(random_results.keys())
    models_grouped = list(grouped_results.keys())

    def add_bars(models, results, x_offset, color, label_prefix):
        recalls = [results[m]["recall"] for m in models]
        f1s = [results[m]["macro_f1"] for m in models]
        positions = [i + x_offset for i in range(len(models))]
        ax.bar(positions, recalls, width=0.18, color=color, alpha=0.8, label=f"{label_prefix} Recall@5")
        ax.bar([p + 0.18 for p in positions], f1s, width=0.18, color=color, alpha=0.4, label=f"{label_prefix} Macro-F1")
        return positions

    pos_random = add_bars(models_random, random_results, 0.0, "#1f77b4", "Random")
    pos_grouped = add_bars(models_grouped, grouped_results, len(models_random) + 0.8, "#ff7f0e", "Grouped")

    ticks = pos_random + pos_grouped
    labels = models_random + models_grouped
    ax.set_xticks([t + 0.09 for t in ticks])
    ax.set_xticklabels(labels, rotation=20)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Top-5 Recall and Macro-F1 (Random vs Grouped splits)")
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "recall_macro.png", dpi=200)
    plt.close(fig)


def plot_tail():
    fig, ax = plt.subplots(figsize=(6, 3))
    models = ["TF-IDF", "BM25", "Gemini"]
    tail_random = [random_results[m]["tail_recall"] for m in models]
    tail_grouped = [grouped_results.get(m, {"tail_recall": 0}).get("tail_recall", 0) for m in models]

    x = range(len(models))
    ax.bar([i - 0.15 for i in x], tail_random, width=0.3, color="#1f77b4", alpha=0.8, label="Random tail Recall@5")
    ax.bar([i + 0.15 for i in x], tail_grouped, width=0.3, color="#ff7f0e", alpha=0.8, label="Grouped tail Recall@5")
    ax.set_xticks(list(x))
    ax.set_xticklabels(models)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Tail Recall@5")
    ax.set_title("Tail (long-tail) performance")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "tail_recall.png", dpi=200)
    plt.close(fig)


def main():
    plot_overall()
    plot_tail()
    print("Saved plots to", OUT_DIR)


if __name__ == "__main__":
    main()
