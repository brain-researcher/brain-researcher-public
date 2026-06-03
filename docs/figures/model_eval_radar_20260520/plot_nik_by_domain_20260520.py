"""Per-domain bar plots for NIK (76 groundable subset), with and without BR.

Sources:
- with_br (all 7 models): UNIFIED_BENCHMARK_BUNDLE/neuroimage_knowledge/eval/results/{judgments,correctness}.json
- without_br (Claude): claude_code_cli_medium_clean_pair_full_20260506_201146/   (direct Claude CLI)
- without_br (others 6 models): paper_grade_fullset_20260506_170624/support_without_br_all.json
                              + model_matrix_groundable_all_models_without_br_20260503_225956/answer_correctness_scores.json
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import rcParams

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "neuroimage_knowledge"
BUNDLE = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher/benchmarks/UNIFIED_BENCHMARK_BUNDLE/neuroimage_knowledge"
)
NIK_RUNS = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher_benchmark/NeuroimageKnowledge/runs"
)

COMBINED_JUDGE = (
    NIK_RUNS
    / "paper_grade_fullset_with_claude_20260513_201327/gemini_support_judge_grounded_full_combined.json"
)
WITH_BR_CORRECTNESS = BUNDLE / "eval/results/answer_correctness_scores.json"
SOURCE_CSV = BUNDLE / "tasks/source_v3_canonical.csv"

CLAUDE_NOBR_CORRECTNESS = (
    NIK_RUNS
    / "claude_code_cli_medium_clean_pair_full_20260506_201146/answer_correctness_scores.json"
)
OTHERS_NOBR_CORRECTNESS = (
    NIK_RUNS
    / "model_matrix_groundable_all_models_without_br_20260503_225956/answer_correctness_scores.json"
)

rcParams["font.family"] = ["Arial", "Liberation Sans", "DejaVu Sans"]
rcParams["font.size"] = 20
rcParams["axes.titlesize"] = 20
rcParams["axes.labelsize"] = 20
rcParams["xtick.labelsize"] = 20
rcParams["ytick.labelsize"] = 20
rcParams["legend.fontsize"] = 20
rcParams["savefig.dpi"] = 400

NO_BR_COLOR = "#c2c6cb"
BR_COLOR = "#7ea2c4"

MODEL_ORDER = [
    "Claude",
    "GPT",
    "Gemini",
    "GLM",
    "DeepSeek",
    "Kimi",
    "Qwen",
]

# Accept: <key>__with_br_prefetched_answer_first_gated | <key>__with_br_prefetched | <key>__with_br_fast_gated | <key>__with_br | <key>__without_br
MODE_PATTERN = re.compile(
    r"^(.*?)__(with_br|without_br)(?:_prefetched(?:_answer_first_gated)?|_fast_gated)?$"
)
MODEL_KEY_TO_NAME = {
    "claude_opus47": "Claude",
    "opencode_claude_opus47": None,  # explicitly skip; CLI run is authoritative for Claude no-BR
    "codex_gpt55": "GPT",
    "opencode_gemini31_pro": "Gemini",
    "opencode_glm51": "GLM",
    "opencode_deepseek_v4_pro": "DeepSeek",
    "opencode_kimi25": "Kimi",
    "opencode_qwen36_plus": "Qwen",
}
GROUNDED_BASIS = {
    "specific_citation",
    "retrieved_document",
    "kg_fact",
    "session_memory",
}

DOMAIN_LABEL = {
    "STATS": "Stats",
    "BEST_PRACTICES": "Best practices",
    "INTERPRETATION": "Interpretation",
    "PREPROCESSING": "Preprocessing",
    "NEUROSCIENTIFIC_KNOWLEDGE": "Neuroscience knowledge",
    "TROUBLESHOOTING": "Troubleshooting",
    "METHODS": "Methods",
}
DOMAIN_ORDER = [
    "STATS",
    "BEST_PRACTICES",
    "INTERPRETATION",
    "PREPROCESSING",
    "NEUROSCIENTIFIC_KNOWLEDGE",
    "TROUBLESHOOTING",
    "METHODS",
]


def task_to_domain():
    out = {}
    for r in csv.DictReader(open(SOURCE_CSV)):
        out[f"NIK-{r['ID']}"] = r["Domain"]
    return out


def parse_mode(mode_str):
    m = MODE_PATTERN.match(mode_str)
    if not m:
        return None
    model_key, br = m.group(1), m.group(2)
    if model_key not in MODEL_KEY_TO_NAME:
        return None
    model = MODEL_KEY_TO_NAME[model_key]
    if model is None:
        return None
    return model, br


def aggregate_grounding(t2d):
    """Single combined Gemini judge file: rows[].mode + rows[].llm_judgment + rows[].basis_type."""
    payload = json.loads(COMBINED_JUDGE.read_text())
    counts = defaultdict(lambda: {"claimed": 0, "yes": 0, "spam": 0})
    for row in payload["rows"]:
        parsed = parse_mode(row.get("mode", ""))
        if parsed is None:
            continue
        model, br = parsed
        domain = t2d.get(row.get("task_id"))
        if domain is None:
            continue
        basis = row.get("basis_type")
        if basis not in GROUNDED_BASIS:
            continue
        key = (model, br, domain)
        counts[key]["claimed"] += 1
        j = row.get("llm_judgment")
        if j == "yes":
            counts[key]["yes"] += 1
        if j == "no_unrelated":
            counts[key]["spam"] += 1

    metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for (model, br, domain), c in counts.items():
        if c["claimed"] == 0:
            continue
        metrics["verified_among_claimed_grounded"][domain][model][br] = (
            c["yes"] / c["claimed"]
        )
        metrics["citation_cleanliness_rate"][domain][model][br] = (
            1.0 - c["spam"] / c["claimed"]
        )
    return metrics


def accumulate_correctness(path: Path, buckets, t2d):
    payload = json.loads(path.read_text())
    for row in payload["scores"]:
        parsed = parse_mode(row["mode"])
        if parsed is None:
            continue
        model, br = parsed
        domain = t2d.get(row["task_id"])
        if domain is None:
            continue
        buckets[(model, br, domain)].append(
            1.0 if row.get("correctness_label") == "yes" else 0.0
        )


def aggregate_correctness_all(t2d):
    buckets = defaultdict(list)
    accumulate_correctness(WITH_BR_CORRECTNESS, buckets, t2d)
    accumulate_correctness(CLAUDE_NOBR_CORRECTNESS, buckets, t2d)
    accumulate_correctness(OTHERS_NOBR_CORRECTNESS, buckets, t2d)
    out = defaultdict(lambda: defaultdict(dict))
    for (model, br, domain), vals in buckets.items():
        if not vals:
            continue
        out[domain][model][br] = float(np.mean(vals))
    return out


def plot_panel(domain_data, title, out_path, domain_counts):
    n_models = len(MODEL_ORDER)
    fig, axes = plt.subplots(
        nrows=2, ncols=4, figsize=(22, 10), sharey=True, constrained_layout=True
    )
    axes = axes.flatten()
    bar_width = 0.38
    x = np.arange(n_models)

    for ax, dom in zip(axes[: len(DOMAIN_ORDER)], DOMAIN_ORDER, strict=True):
        nb = [
            domain_data.get(dom, {}).get(m, {}).get("without_br", 0.0)
            for m in MODEL_ORDER
        ]
        wb = [
            domain_data.get(dom, {}).get(m, {}).get("with_br", 0.0) for m in MODEL_ORDER
        ]
        ax.bar(x - bar_width / 2, nb, bar_width, color=NO_BR_COLOR, label="without BR")
        ax.bar(x + bar_width / 2, wb, bar_width, color=BR_COLOR, label="with BR")
        ax.set_xticks(x)
        ax.set_xticklabels(MODEL_ORDER, rotation=35, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_title(
            f"{DOMAIN_LABEL[dom]} (n={domain_counts.get(dom, 0)})", weight="bold"
        )
        ax.grid(axis="y", linestyle=":", color="#cccccc", linewidth=0.7)
        ax.set_axisbelow(True)
    for ax in axes[len(DOMAIN_ORDER) :]:
        ax.set_visible(False)

    axes[0].set_ylabel("score")
    axes[4].set_ylabel("score")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.suptitle(title, weight="bold", y=1.06)
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 1.12),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".png"), dpi=400, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def main():
    t2d = task_to_domain()
    counts = defaultdict(int)
    for d in t2d.values():
        counts[d] += 1
    print("Domain task counts (76 groundable):")
    for d in DOMAIN_ORDER:
        print(f"  {DOMAIN_LABEL[d]:<25} {counts[d]}")

    grounding = aggregate_grounding(t2d)
    correctness = aggregate_correctness_all(t2d)

    plot_panel(
        grounding["verified_among_claimed_grounded"],
        "Verified among claimed grounded (precision) by domain",
        OUT_DIR / "nik_verified_among_claimed_grounded_by_domain_20260520",
        counts,
    )
    plot_panel(
        grounding["citation_cleanliness_rate"],
        "Citation cleanliness (1 - spam rate) by domain",
        OUT_DIR / "nik_citation_cleanliness_rate_by_domain_20260520",
        counts,
    )
    plot_panel(
        correctness,
        "Answer correctness rate by domain",
        OUT_DIR / "nik_answer_correctness_rate_by_domain_20260520",
        counts,
    )
    print(f"Wrote 3 by-domain bar plots to {OUT_DIR}")


if __name__ == "__main__":
    main()
