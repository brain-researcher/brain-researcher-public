"""Per-domain bar plots for tool-routing v7 (6 domains).

For each metric × budget, one figure: grouped bars (7 models × 2 modes) faceted by domain.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import rcParams

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "tool_routing"

TOOL_SRC = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher/benchmarks/UNIFIED_BENCHMARK_BUNDLE"
    "/tool_routing/eval/results/TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_20260514.json"
)
TASK_SRC = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher/benchmarks/UNIFIED_BENCHMARK_BUNDLE"
    "/tool_routing/tasks/tasks_v7_canonical.jsonl"
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
TOOL_MODEL_DISPLAY = {
    "claude_code_opus47": "Claude",
    "codex_cli_gpt55": "GPT",
    "opencode_gemini_pro": "Gemini",
    "opencode_glm51": "GLM",
    "opencode_deepseek_v4_pro": "DeepSeek",
    "opencode_kimi_k25": "Kimi",
    "opencode_qwen36_plus": "Qwen",
}

DOMAIN_RULES = {
    "Functional & Connectivity": {
        "Workflow Family - Task GLM",
        "Workflow Family - Connectivity",
        "Workflow Family - Multimodal Connectivity",
        "Workflow Family - Local Activity",
        "Workflow Family - Naturalistic fMRI",
        "Workflow Family - Dynamics",
        "Connectivity",
    },
    "Structural & Diffusion": {
        "Workflow Family - Structural",
        "Workflow Family - Diffusion",
        "Workflow Family - Surface",
        "Workflow Family - Parcellation",
        "Workflow Family - Spatial Maps",
        "Workflow Family - Perfusion",
    },
    "Prediction & ML": {
        "Workflow Family - Prediction",
        "Machine Learning",
    },
    "Clinical & Longitudinal": {
        "Workflow Family - Clinical/Longitudinal",
    },
    "Behavioral interpretation": {
        "Workflow Family - Benchmarking",
        "Workflow Family - Interpretation",
    },
    "Other (Realtime / Ephys / QC)": {
        "Workflow Family - Realtime",
        "Workflow Family - Electrophysiology",
        "Workflow Family - Simulation",
        "Workflow Family - Reliability",
        "Workflow Family - Robustness",
        "Preprocessing",
        "Quality Control",
        "Data Harmonization",
    },
}
DOMAIN_ORDER = list(DOMAIN_RULES.keys())

METRICS = [
    ("capability_score", "Capability"),
    ("correct_rate", "Correct rate"),
    ("execution_handoff_score", "Execution handoff"),
]
BUDGETS = [1, 3, 5]


def load_task_domain() -> dict[str, str]:
    cat_to_domain = {cat: dom for dom, cats in DOMAIN_RULES.items() for cat in cats}
    out: dict[str, str] = {}
    unmapped = []
    for line in TASK_SRC.read_text().splitlines():
        t = json.loads(line)
        cat = t.get("category", "")
        dom = cat_to_domain.get(cat)
        if dom is None:
            unmapped.append((t["task_id"], cat))
            dom = "Other (Realtime / Ephys / QC)"
        out[t["task_id"]] = dom
    if unmapped:
        print(f"[warn] {len(unmapped)} tasks defaulted to Other:", unmapped[:5])
    return out


def aggregate(rows, task_domain):
    sums = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        )
    )
    for r in rows:
        model = TOOL_MODEL_DISPLAY.get(r["model_key"])
        if model is None:
            continue
        dom = task_domain.get(r["task_id"])
        if dom is None:
            continue
        for metric, _ in METRICS:
            val = r.get(metric)
            if val is None:
                continue
            sums[r["budget"]][metric][dom][model][r["mode"]].append(float(val))
    means = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    )
    for budget, m1 in sums.items():
        for metric, m2 in m1.items():
            for dom, m3 in m2.items():
                for model, m4 in m3.items():
                    for mode, vals in m4.items():
                        means[budget][metric][dom][model][mode] = float(np.mean(vals))
    return means


def domain_task_counts(task_domain):
    c = defaultdict(int)
    for dom in task_domain.values():
        c[dom] += 1
    return c


def plot_barplot(domain_data, title, out_path, domain_counts):
    n_models = len(MODEL_ORDER)
    fig, axes = plt.subplots(
        nrows=2, ncols=3, figsize=(18, 10), sharey=True, constrained_layout=True
    )
    axes = axes.flatten()
    bar_width = 0.38
    x = np.arange(n_models)

    for ax, dom in zip(axes, DOMAIN_ORDER, strict=True):
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
        ax.set_title(f"{dom} (n={domain_counts[dom]})", weight="bold")
        ax.grid(axis="y", linestyle=":", color="#cccccc", linewidth=0.7)
        ax.set_axisbelow(True)

    axes[0].set_ylabel("score")
    axes[3].set_ylabel("score")
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
    task_domain = load_task_domain()
    counts = domain_task_counts(task_domain)
    print("Domain counts:")
    for dom in DOMAIN_ORDER:
        print(f"  {dom:<35} {counts[dom]}")

    payload = json.loads(TOOL_SRC.read_text())
    means = aggregate(payload["row_budget_rows"], task_domain)

    n = 0
    for budget in BUDGETS:
        for metric, label in METRICS:
            plot_barplot(
                means[budget][metric],
                title=f"{label} @{budget} by domain",
                out_path=OUT_DIR
                / f"tool_routing_{metric}_at{budget}_by_domain_20260520",
                domain_counts=counts,
            )
            n += 1
    print(f"Wrote {n} bar plots to {OUT_DIR}")


if __name__ == "__main__":
    main()
