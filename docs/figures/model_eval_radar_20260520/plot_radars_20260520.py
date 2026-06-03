"""Per-metric paired radar charts (no-BR vs +BR) for the v7 canonical bundles.

Tool routing: 3 metrics × 3 budgets (@1, @3, @5) = 9 radars.
NIK: 3 metrics × 1 figure = 3 radars (top-50 BR-separation cut).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import rcParams

ROOT = Path(__file__).resolve().parent
TOOL_DIR = ROOT / "tool_routing"
NIK_DIR = ROOT / "neuroimage_knowledge"

TOOL_SRC = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher/benchmarks/UNIFIED_BENCHMARK_BUNDLE"
    "/tool_routing/eval/results/TOOL_SELECTION_TOP60_ACTION_BUDGET_METRICS_20260514.json"
)
NIK_SRC = Path(
    "${BRAIN_RESEARCHER_HOME}/projects/brain_researcher_benchmark/NeuroimageKnowledge/runs"
    "/full_groundable_answer_first_gated_with_br_20260514/top50_br_separation_metrics.json"
)

rcParams["font.family"] = ["Arial", "Liberation Sans", "DejaVu Sans"]
rcParams["font.size"] = 24
rcParams["axes.titlesize"] = 24
rcParams["axes.labelsize"] = 24
rcParams["xtick.labelsize"] = 24
rcParams["ytick.labelsize"] = 22
rcParams["legend.fontsize"] = 22
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
NIK_MODEL_DISPLAY = {
    "claude_opus47": "Claude",
    "codex_gpt55": "GPT",
    "opencode_gemini31_pro": "Gemini",
    "opencode_glm51": "GLM",
    "opencode_deepseek_v4_pro": "DeepSeek",
    "opencode_kimi25": "Kimi",
    "opencode_qwen36_plus": "Qwen",
}

TOOL_METRICS = [
    ("capability_score", "Capability (required capabilities covered)"),
    ("correct_rate", "Correct rate (all caps + no trap)"),
    ("execution_handoff_score", "Execution handoff score"),
]
TOOL_BUDGETS = [1, 3, 5]

NIK_METRICS = [
    (
        "verified_among_claimed_grounded",
        "Verified among claimed grounded (precision)",
        False,
    ),
    ("citation_cleanliness_rate", "Citation cleanliness (1 - spam rate)", False),
    ("answer_correctness_rate", "Answer correctness rate", False),
]


def load_tool_routing() -> dict[int, dict[str, dict[str, dict[str, float]]]]:
    payload = json.loads(TOOL_SRC.read_text())
    scores: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for row in payload["long_rows"]:
        model = TOOL_MODEL_DISPLAY.get(row["model_key"])
        if model is None:
            continue
        scores[row["budget"]][row["metric"]][model][row["mode"]] = row["value"]
    return scores


def load_nik() -> dict[str, dict[str, dict[str, float]]]:
    payload = json.loads(NIK_SRC.read_text())
    scores: dict = defaultdict(lambda: defaultdict(dict))
    for row in payload["by_model"]:
        model = NIK_MODEL_DISPLAY.get(row["model"])
        if model is None:
            continue
        with_block = row.get("with_grounding", {})
        without_block = row.get("without_grounding", {})
        with_corr = row.get("with_correctness", {})
        without_corr = row.get("without_correctness", {})
        for metric, _, _lower in NIK_METRICS:
            if metric == "answer_correctness_rate":
                wv = with_corr.get(metric)
                nv = without_corr.get(metric)
            elif metric == "citation_cleanliness_rate":
                wv_raw = with_block.get("citation_spam_rate")
                nv_raw = without_block.get("citation_spam_rate")
                wv = 1.0 - wv_raw if wv_raw is not None else None
                nv = 1.0 - nv_raw if nv_raw is not None else None
            else:
                wv = with_block.get(metric)
                nv = without_block.get(metric)
            scores[metric][model]["with_br"] = wv
            scores[metric][model]["without_br"] = nv
    return scores


def plot_radar(
    scores: dict[str, dict[str, float]],
    title: str,
    out_path: Path,
    *,
    lower_is_better: bool = False,
) -> None:
    n = len(MODEL_ORDER)
    angles = np.linspace(0.0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    no_br = [scores.get(m, {}).get("without_br", 0.0) or 0.0 for m in MODEL_ORDER]
    with_br = [scores.get(m, {}).get("with_br", 0.0) or 0.0 for m in MODEL_ORDER]
    no_br += no_br[:1]
    with_br += with_br[:1]

    vmax = max(max(no_br), max(with_br), 1e-3)
    ymax = min(1.0, vmax * 1.15) if vmax <= 1.0 else vmax * 1.15

    fig, ax = plt.subplots(figsize=(9.8, 9.8), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    ax.plot(angles, no_br, color=NO_BR_COLOR, linewidth=2.2, label="without BR")
    ax.fill(angles, no_br, color=NO_BR_COLOR, alpha=0.18)
    ax.plot(angles, with_br, color=BR_COLOR, linewidth=2.4, label="with BR")
    ax.fill(angles, with_br, color=BR_COLOR, alpha=0.20)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(MODEL_ORDER)
    ax.set_ylim(0, ymax)
    ax.set_yticks(np.linspace(0, ymax, 5)[1:])
    ax.set_yticklabels([f"{t:.2f}" for t in np.linspace(0, ymax, 5)[1:]], color="#555")
    ax.tick_params(axis="x", pad=20)
    ax.set_rlabel_position(180 / n)
    ax.grid(color="#cccccc", linewidth=0.8)

    subtitle = " (↓ lower is better)" if lower_is_better else ""
    ax.set_title(title + subtitle, pad=36, weight="bold")
    ax.legend(loc="upper right", bbox_to_anchor=(1.24, 1.1), frameon=False)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".png"), dpi=400, bbox_inches="tight")
    fig.savefig(out_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    tool_scores = load_tool_routing()
    tool_count = 0
    for budget in TOOL_BUDGETS:
        for metric, title in TOOL_METRICS:
            plot_radar(
                tool_scores[budget][metric],
                title=f"{title} @{budget}",
                out_path=TOOL_DIR / f"tool_routing_{metric}_at{budget}_radar_20260520",
            )
            tool_count += 1

    nik_scores = load_nik()
    for metric, title, lower in NIK_METRICS:
        plot_radar(
            nik_scores[metric],
            title=title,
            out_path=NIK_DIR / f"nik_{metric}_radar_20260520",
            lower_is_better=lower,
        )

    print(f"Wrote {tool_count} tool-routing radars to {TOOL_DIR}")
    print(f"Wrote {len(NIK_METRICS)} NIK radars to {NIK_DIR}")


if __name__ == "__main__":
    main()
