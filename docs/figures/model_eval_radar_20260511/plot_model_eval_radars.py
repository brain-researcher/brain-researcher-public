#!/usr/bin/env python3
"""Generate radar and heatmap figures for current model-evaluation evidence.

This is a documentation plot, not a benchmark runner. Missing or unavailable
result-bearing rows are encoded as 0.0 so the requested model set stays fixed.
"""

from __future__ import annotations

import csv
import math
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


OUT_DIR = Path(__file__).resolve().parent

MODELS = [
    "Claude Code Opus 4.7",
    "Codex GPT-5.5",
    "Gemini 3.1 Pro",
    "GLM 5.1",
    "DeepSeek v4 Pro",
    "Kimi K2.5",
    "Qwen 3.6 Plus",
]

COLORS = {
    "Claude Code Opus 4.7": "#4C78A8",
    "Codex GPT-5.5": "#F58518",
    "Gemini 3.1 Pro": "#54A24B",
    "GLM 5.1": "#E45756",
    "DeepSeek v4 Pro": "#72B7B2",
    "Kimi K2.5": "#B279A2",
    "Qwen 3.6 Plus": "#FF9DA6",
}

QSM_SOURCE = "benchmarks/tb-science-task/qsm_audit_br_sweep_20260506.md"
TOOL_SOURCE = "benchmarks/experiment_setup.md"
META_PILOT_SOURCE = (
    "benchmarks/neurometabench/experiments/agent_condition_matrix/"
    "layer_b_v2_harness_fix_pilot_isolated_20260505/"
    "LAYER_B_V2_PILOT_DIAGNOSTIC_AXES_SUMMARY.md"
)
META_TARGETED_SOURCE = (
    "benchmarks/neurometabench/experiments/agent_condition_matrix/"
    "layer_b_anchor_contract_targeted_smoke_v3_20260507/DIAGNOSTIC_AXES.md"
)


QSM_METRIC_ORDER = [
    ("NRMSE", "NRMSE quality"),
    ("dNRMSE", "dNRMSE quality"),
    ("dNRMSE_Tissue", "Tissue dNRMSE quality"),
    ("dNRMSE_Blood", "Blood dNRMSE quality"),
    ("dNRMSE_DGM", "DGM dNRMSE quality"),
    ("Slope Error", "Slope error quality"),
    ("CalcStreak", "Calc streak quality"),
    ("Calc Error", "Calc error quality"),
]

QSM_RAW = {
    "Claude Code Opus 4.7": {
        "condition": "audit-BR after smoke",
        "reward": 0.0,
        "NRMSE": 407.798,
        "dNRMSE": 1788.295,
        "dNRMSE_Tissue": 1258.722,
        "dNRMSE_Blood": 2564.331,
        "dNRMSE_DGM": 773.364,
        "Slope Error": 0.559,
        "CalcStreak": 0.141,
        "Calc Error": 53.012,
    },
    "Codex GPT-5.5": {
        "condition": "audit-BR expanded",
        "reward": 0.0,
        "NRMSE": 476.014,
        "dNRMSE": 1377.041,
        "dNRMSE_Tissue": 1903.059,
        "dNRMSE_Blood": 4318.081,
        "dNRMSE_DGM": 294.495,
        "Slope Error": 0.288,
        "CalcStreak": 0.376,
        "Calc Error": 51.569,
    },
    "Gemini 3.1 Pro": {
        "condition": "audit-BR",
        "reward": 0.0,
        "NRMSE": 92.481,
        "dNRMSE": 204.953,
        "dNRMSE_Tissue": 169.226,
        "dNRMSE_Blood": 3814.688,
        "dNRMSE_DGM": 146.142,
        "Slope Error": 0.289,
        "CalcStreak": math.nan,
        "Calc Error": 54.763,
    },
    "GLM 5.1": {
        "condition": "audit-BR expanded",
        "reward": 0.0,
        "NRMSE": 468.757,
        "dNRMSE": 1094.165,
        "dNRMSE_Tissue": 1071.869,
        "dNRMSE_Blood": 1219.822,
        "dNRMSE_DGM": 39679.376,
        "Slope Error": 0.788,
        "CalcStreak": 0.129,
        "Calc Error": 43.357,
    },
    "DeepSeek v4 Pro": {
        "condition": "audit-BR after smoke",
        "reward": 0.0,
        "NRMSE": 747.660,
        "dNRMSE": 5847.489,
        "dNRMSE_Tissue": 3383.983,
        "dNRMSE_Blood": 6504.266,
        "dNRMSE_DGM": 4557.596,
        "Slope Error": 0.180,
        "CalcStreak": 5.280,
        "Calc Error": 56.359,
    },
    "Kimi K2.5": {
        "condition": "audit-BR after smoke; no required QSM output",
        "reward": 0.0,
    },
    "Qwen 3.6 Plus": {
        "condition": "audit-BR after smoke",
        "reward": 0.0,
        "NRMSE": 1146.870,
        "dNRMSE": 4302.494,
        "dNRMSE_Tissue": 3338.693,
        "dNRMSE_Blood": 3287.220,
        "dNRMSE_DGM": 2542.537,
        "Slope Error": 1.684,
        "CalcStreak": 0.163,
        "Calc Error": 52.784,
    },
}

QSM_WITHOUT_BR_RAW = {
    "Claude Code Opus 4.7": {
        "condition": "May 13 no-BR baseline",
        "reward": 0.0,
        "NRMSE": 187.287,
        "dNRMSE": 240.368,
        "dNRMSE_Tissue": 232.967,
        "dNRMSE_Blood": 776.003,
        "dNRMSE_DGM": 78.725,
        "Slope Error": 1.716,
        "CalcStreak": 0.139,
        "Calc Error": 61.283,
    },
    "Gemini 3.1 Pro": {
        "condition": "baseline control",
        "reward": 0.0,
        "NRMSE": 235.889,
        "dNRMSE": 1095.401,
        "dNRMSE_Tissue": 1049.792,
        "dNRMSE_Blood": 1992.735,
        "dNRMSE_DGM": 323.404,
        "Slope Error": 0.600,
        "CalcStreak": 0.087,
        "Calc Error": 52.945,
    },
    "Kimi K2.5": {
        "condition": "May 13 no-BR baseline",
        "reward": 0.0,
        "NRMSE": 456.240,
        "dNRMSE": 768.420,
        "dNRMSE_Tissue": 734.460,
        "dNRMSE_Blood": 1139.062,
        "dNRMSE_DGM": 1142.306,
        "Slope Error": 0.543,
        "CalcStreak": 0.184,
        "Calc Error": 48.079,
    },
    "Qwen 3.6 Plus": {
        "condition": "May 13 no-BR baseline",
        "reward": 0.0,
        "NRMSE": 998.210,
        "dNRMSE": 69789.116,
        "dNRMSE_Tissue": 428370.636,
        "dNRMSE_Blood": 18224.647,
        "dNRMSE_DGM": 32468.651,
        "Slope Error": 1.027,
        "CalcStreak": 6.475,
        "Calc Error": 53.907,
    },
}

TOOL_ROUTING = {
    "Claude Code Opus 4.7": {
        "Cap no BR": 0.0,
        "Cap +BR": 0.0,
        "Acc no BR": 0.0,
        "Acc +BR": 0.0,
        "BR delta+": 0.0,
        "Clean pair": 0.0,
        "note": "Degraded or unavailable in tool-routing snapshot.",
    },
    "Codex GPT-5.5": {
        "Cap no BR": 0.733,
        "Cap +BR": 0.667,
        "Acc no BR": 0.40,
        "Acc +BR": 0.30,
        "BR delta+": 0.0,
        "Clean pair": 1.0,
        "note": "Clean-pair row; delta was negative, clipped to 0 for radar.",
    },
    "Gemini 3.1 Pro": {
        "Cap no BR": 0.550,
        "Cap +BR": 0.783,
        "Acc no BR": 0.20,
        "Acc +BR": 0.50,
        "BR delta+": 0.233,
        "Clean pair": 1.0,
        "note": "Clean-pair row.",
    },
    "GLM 5.1": {
        "Cap no BR": 0.333,
        "Cap +BR": 0.917,
        "Acc no BR": 0.00,
        "Acc +BR": 0.80,
        "BR delta+": 0.583,
        "Clean pair": 1.0,
        "note": "Clean-pair row.",
    },
    "DeepSeek v4 Pro": {
        "Cap no BR": 0.317,
        "Cap +BR": 0.667,
        "Acc no BR": 0.00,
        "Acc +BR": 0.50,
        "BR delta+": 0.350,
        "Clean pair": 1.0,
        "note": "Clean-pair row.",
    },
    "Kimi K2.5": {
        "Cap no BR": 0.0,
        "Cap +BR": 0.0,
        "Acc no BR": 0.0,
        "Acc +BR": 0.0,
        "BR delta+": 0.0,
        "Clean pair": 0.0,
        "note": "Zero-output timeouts in tool-routing snapshot.",
    },
    "Qwen 3.6 Plus": {
        "Cap no BR": 0.0,
        "Cap +BR": 0.0,
        "Acc no BR": 0.0,
        "Acc +BR": 0.0,
        "BR delta+": 0.0,
        "Clean pair": 0.0,
        "note": "Timeout or provider-balance failure in tool-routing snapshot.",
    },
}

LAYER_B_PAIRED = {
    "Codex GPT-5.5": {
        "without": {
            "Strict": 5 / 6,
            "Normalized science": 1.000,
            "Local study F1": 0.944,
            "Coord F1": 0.833,
            "Spatial r": 1.000,
            "Dice": 1.000,
        },
        "with": {
            "Strict": 3 / 6,
            "Normalized science": 1.000,
            "Local study F1": 0.672,
            "Coord F1": 0.833,
            "Spatial r": 1.000,
            "Dice": 1.000,
        },
        "source": "benchmarks/neurometabench/NEUROMETABENCH_RESULTS_SUMMARY_20260507.md",
        "note": "paired meta-analysis medium-matrix row",
    },
    "Gemini 3.1 Pro": {
        "without": {
            "Strict": 1 / 6,
            "Normalized science": 0.333,
            "Local study F1": 0.500,
            "Coord F1": 0.500,
            "Spatial r": 1.000,
            "Dice": 1.000,
        },
        "with": {
            "Strict": 1 / 6,
            "Normalized science": 0.333,
            "Local study F1": 1.000,
            "Coord F1": 0.500,
            "Spatial r": 1.000,
            "Dice": 1.000,
        },
        "source": "benchmarks/neurometabench/NEUROMETABENCH_RESULTS_SUMMARY_20260507.md",
        "note": "paired meta-analysis medium-matrix row",
    },
    "GLM 5.1": {
        "without": {
            "Strict": 4 / 6,
            "Normalized science": 1.000,
            "Local study F1": 0.932,
            "Coord F1": 0.833,
            "Spatial r": 0.998,
            "Dice": 0.982,
        },
        "with": {
            "Strict": 2 / 6,
            "Normalized science": 0.778,
            "Local study F1": 0.657,
            "Coord F1": 0.794,
            "Spatial r": 0.765,
            "Dice": 0.790,
        },
        "source": "benchmarks/neurometabench/NEUROMETABENCH_RESULTS_SUMMARY_20260507.md",
        "note": "paired meta-analysis medium-matrix row",
    },
    "Claude Code Opus 4.7": {
        "with": {
            "Raw contract": 0.500,
            "Harness score": 0.500,
            "Norm science": 0.500,
            "Local study F1": 0.000,
            "Coord F1": 0.000,
            "Spatial r": 1.000,
            "Dice": 1.000,
            "Provenance": 1.000,
            "Claim match": 1.000,
            "ID coverage": 1.000,
            "Prov enrich": 1.000,
            "BR recon": 0.600,
        },
        "source": META_TARGETED_SOURCE,
        "note": "with-BR targeted smoke row; no matching without-BR row",
    },
    "DeepSeek v4 Pro": {
        "with": {
            "Raw contract": 1.000,
            "Harness score": 1.000,
            "Norm science": 0.833,
            "Local study F1": 1.000,
            "Coord F1": 0.485,
            "Spatial r": 0.786,
            "Dice": 0.968,
            "Provenance": 1.000,
            "Claim match": 1.000,
            "ID coverage": 0.333,
            "Prov enrich": 0.500,
            "BR recon": 0.664,
        },
        "source": META_TARGETED_SOURCE,
        "note": "with-BR targeted smoke row; no matching without-BR row",
    },
}

BR_BEHAVIOR = {
    "Claude Code Opus 4.7": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 1.0,
        "Reviewer approved": 1.0,
        "Output submitted": 1.0,
        "Verifier metrics": 1.0,
        "Route usable": 1.0,
    },
    "Codex GPT-5.5": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 1.0,
        "Reviewer approved": 1.0,
        "Output submitted": 1.0,
        "Verifier metrics": 1.0,
        "Route usable": 1.0,
    },
    "Gemini 3.1 Pro": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 1.0,
        "Reviewer approved": 1.0,
        "Output submitted": 1.0,
        "Verifier metrics": 1.0,
        "Route usable": 1.0,
    },
    "GLM 5.1": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 1.0,
        "Reviewer approved": 0.0,
        "Output submitted": 1.0,
        "Verifier metrics": 1.0,
        "Route usable": 1.0,
    },
    "DeepSeek v4 Pro": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 1.0,
        "Reviewer approved": 0.0,
        "Output submitted": 1.0,
        "Verifier metrics": 1.0,
        "Route usable": 1.0,
    },
    "Kimi K2.5": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 0.0,
        "Reviewer approved": 0.0,
        "Output submitted": 0.0,
        "Verifier metrics": 0.0,
        "Route usable": 1.0,
    },
    "Qwen 3.6 Plus": {
        "Direct BR calls": 1.0,
        "Plan review": 1.0,
        "Impl review": 1.0,
        "Reviewer approved": 1.0,
        "Output submitted": 1.0,
        "Verifier metrics": 1.0,
        "Route usable": 1.0,
    },
}

META_ANALYSIS = {
    "Claude Code Opus 4.7": {
        "Raw contract": 0.500,
        "Harness score": 0.500,
        "Norm science": 0.500,
        "Local study F1": 0.000,
        "Coord F1": 0.000,
        "Spatial r": 1.000,
        "Dice": 1.000,
        "Provenance": 1.000,
        "Claim match": 1.000,
        "ID coverage": 1.000,
        "Prov enrich": 1.000,
        "BR recon": 0.600,
        "source": META_TARGETED_SOURCE,
    },
    "Codex GPT-5.5": {
        "Raw contract": 1.000,
        "Harness score": 1.000,
        "Norm science": 1.000,
        "Local study F1": 0.744,
        "Coord F1": 1.000,
        "Spatial r": 1.000,
        "Dice": 1.000,
        "Provenance": 1.000,
        "Claim match": 1.000,
        "ID coverage": 0.444,
        "Prov enrich": 1.000,
        "BR recon": 0.797,
        "source": META_PILOT_SOURCE,
    },
    "Gemini 3.1 Pro": {
        "Raw contract": 1.000,
        "Harness score": 1.000,
        "Norm science": 1.000,
        "Local study F1": 0.944,
        "Coord F1": 0.333,
        "Spatial r": 0.968,
        "Dice": 1.000,
        "Provenance": 1.000,
        "Claim match": 1.000,
        "ID coverage": 0.389,
        "Prov enrich": 0.250,
        "BR recon": 0.443,
        "source": META_PILOT_SOURCE,
    },
    "GLM 5.1": {
        "Raw contract": 1.000,
        "Harness score": 1.000,
        "Norm science": 0.889,
        "Local study F1": 0.599,
        "Coord F1": 0.794,
        "Spatial r": 0.862,
        "Dice": 0.705,
        "Provenance": 1.000,
        "Claim match": 1.000,
        "ID coverage": 0.556,
        "Prov enrich": 0.708,
        "BR recon": 0.650,
        "source": META_PILOT_SOURCE,
    },
    "DeepSeek v4 Pro": {
        "Raw contract": 1.000,
        "Harness score": 1.000,
        "Norm science": 0.833,
        "Local study F1": 1.000,
        "Coord F1": 0.485,
        "Spatial r": 0.786,
        "Dice": 0.968,
        "Provenance": 1.000,
        "Claim match": 1.000,
        "ID coverage": 0.333,
        "Prov enrich": 0.500,
        "BR recon": 0.664,
        "source": META_TARGETED_SOURCE,
    },
    "Kimi K2.5": {"source": "no result-bearing meta-analysis row found"},
    "Qwen 3.6 Plus": {"source": "no result-bearing meta-analysis row found"},
}

FAMILY_ORDERS = {
    "QSM continuous quality": [label for _, label in QSM_METRIC_ORDER],
    "QSM binary gate": ["Binary reward"],
    "Tool routing": [
        "Cap no BR",
        "Cap +BR",
        "Acc no BR",
        "Acc +BR",
        "BR delta+",
        "Clean pair",
    ],
    "Audit-BR behavior": [
        "Direct BR calls",
        "Plan review",
        "Impl review",
        "Reviewer approved",
        "Output submitted",
        "Verifier metrics",
        "Route usable",
    ],
    "QSM knowledge evidence": [
        "Local-field accepted",
        "Error metric strength",
        "Region stability",
        "Calcification handling",
        "Output contract",
        "Revision follow-through",
        "BR knowledge applied",
    ],
    "Meta-analysis": [
        "Raw contract",
        "Harness score",
        "Norm science",
        "Local study F1",
        "Coord F1",
        "Spatial r",
        "Dice",
        "Provenance",
        "Claim match",
        "ID coverage",
        "Prov enrich",
        "BR recon",
    ],
}

RADAR_FAMILIES = [
    "QSM continuous quality",
    "Tool routing",
    "Audit-BR behavior",
    "QSM knowledge evidence",
    "Meta-analysis",
]

TASK_PAIRED_ORDER = [
    "QSM continuous quality",
    "QSM binary reward",
    "Tool routing capability",
    "Tool routing accuracy",
    "Audit-BR behavior",
    "QSM knowledge evidence",
    "Meta-analysis",
]

MODEL_SHORT_LABELS = {
    "Claude Code Opus 4.7": "Claude\nOpus 4.7",
    "Codex GPT-5.5": "Codex\n5.5",
    "Gemini 3.1 Pro": "Gemini\n3.1 Pro",
    "GLM 5.1": "GLM\n5.1",
    "DeepSeek v4 Pro": "DeepSeek\nv4 Pro",
    "Kimi K2.5": "Kimi\nK2.5",
    "Qwen 3.6 Plus": "Qwen\n3.6 Plus",
}


def finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def add_record(records, model, family, metric, score, source, note=""):
    records.append(
        {
            "model": model,
            "family": family,
            "metric": metric,
            "score": f"{clamp01(float(score)):.6f}",
            "source": source,
            "note": note,
        }
    )


def build_score_records():
    records = []

    best_by_metric = {}
    for raw_metric, _ in QSM_METRIC_ORDER:
        values = []
        for model in MODELS:
            value = QSM_RAW.get(model, {}).get(raw_metric)
            if finite_positive(value):
                values.append(float(value))
        best_by_metric[raw_metric] = min(values) if values else None

    for model in MODELS:
        add_record(
            records,
            model,
            "QSM binary gate",
            "Binary reward",
            QSM_RAW.get(model, {}).get("reward", 0.0),
            QSM_SOURCE,
            "All requested QSM rows have reward 0.0 in the current audit table.",
        )
        for raw_metric, label in QSM_METRIC_ORDER:
            raw_value = QSM_RAW.get(model, {}).get(raw_metric)
            best = best_by_metric[raw_metric]
            if finite_positive(raw_value) and finite_positive(best):
                score = float(best) / float(raw_value)
                note = "lower-is-better raw metric scored as best_observed/model_value"
            else:
                score = 0.0
                note = "missing, zero, or nan raw metric encoded as 0"
            add_record(records, model, "QSM continuous quality", label, score, QSM_SOURCE, note)

    for model in MODELS:
        row = TOOL_ROUTING[model]
        for metric in FAMILY_ORDERS["Tool routing"]:
            add_record(records, model, "Tool routing", metric, row[metric], TOOL_SOURCE, row["note"])

    for model in MODELS:
        row = BR_BEHAVIOR[model]
        for metric in FAMILY_ORDERS["Audit-BR behavior"]:
            add_record(records, model, "Audit-BR behavior", metric, row[metric], QSM_SOURCE)

    qsm_lookup = {
        (row["model"], row["metric"]): float(row["score"])
        for row in records
        if row["family"] == "QSM continuous quality"
    }
    behavior_lookup = {
        (row["model"], row["metric"]): float(row["score"])
        for row in records
        if row["family"] == "Audit-BR behavior"
    }
    for model in MODELS:
        knowledge = {
            "Local-field accepted": behavior_lookup[(model, "Reviewer approved")],
            "Error metric strength": np.mean(
                [
                    qsm_lookup[(model, "NRMSE quality")],
                    qsm_lookup[(model, "dNRMSE quality")],
                ]
            ),
            "Region stability": np.mean(
                [
                    qsm_lookup[(model, "Tissue dNRMSE quality")],
                    qsm_lookup[(model, "Blood dNRMSE quality")],
                    qsm_lookup[(model, "DGM dNRMSE quality")],
                ]
            ),
            "Calcification handling": np.mean(
                [
                    qsm_lookup[(model, "Calc streak quality")],
                    qsm_lookup[(model, "Calc error quality")],
                ]
            ),
            "Output contract": np.mean(
                [
                    behavior_lookup[(model, "Output submitted")],
                    behavior_lookup[(model, "Verifier metrics")],
                ]
            ),
            "Revision follow-through": np.mean(
                [
                    behavior_lookup[(model, "Reviewer approved")],
                    behavior_lookup[(model, "Output submitted")],
                ]
            ),
            "BR knowledge applied": np.mean(
                [
                    behavior_lookup[(model, "Direct BR calls")],
                    behavior_lookup[(model, "Impl review")],
                ]
            ),
        }
        for metric, score in knowledge.items():
            add_record(
                records,
                model,
                "QSM knowledge evidence",
                metric,
                float(score),
                QSM_SOURCE,
                "derived from QSM verifier scores plus BR review and output flags",
            )

    for model in MODELS:
        row = META_ANALYSIS[model]
        source = row["source"]
        for metric in FAMILY_ORDERS["Meta-analysis"]:
            score = row.get(metric, 0.0)
            note = "" if metric in row else "no result-bearing row found; encoded as 0"
            add_record(records, model, "Meta-analysis", metric, score, source, note)

    return records


def qsm_condition_scores():
    metric_names = [raw_metric for raw_metric, _ in QSM_METRIC_ORDER]
    best_by_metric = {}
    for metric in metric_names:
        values = []
        for raw_by_model in (QSM_WITHOUT_BR_RAW, QSM_RAW):
            for row in raw_by_model.values():
                value = row.get(metric)
                if finite_positive(value):
                    values.append(float(value))
        best_by_metric[metric] = min(values) if values else None

    def score_model(row):
        scores = []
        for metric in metric_names:
            value = row.get(metric)
            best = best_by_metric[metric]
            if finite_positive(value) and finite_positive(best):
                scores.append(float(best) / float(value))
            else:
                scores.append(0.0)
        return float(np.mean(scores)) if scores else 0.0

    without_scores = {}
    with_scores = {}
    for model in MODELS:
        without_scores[model] = score_model(QSM_WITHOUT_BR_RAW.get(model, {}))
        with_scores[model] = score_model(QSM_RAW.get(model, {}))
    return without_scores, with_scores


def layer_b_aggregate(condition_scores):
    values = [float(value) for value in condition_scores.values()]
    return float(np.mean(values)) if values else 0.0


def build_task_model_pair_rows(score_records):
    qsm_without, qsm_with = qsm_condition_scores()
    qsm_knowledge_with = {
        model: float(
            np.mean(
                [
                    float(row["score"])
                    for row in score_records
                    if row["model"] == model and row["family"] == "QSM knowledge evidence"
                ]
            )
        )
        for model in MODELS
    }
    audit_behavior_with = {
        model: float(
            np.mean(
                [
                    float(row["score"])
                    for row in score_records
                    if row["model"] == model and row["family"] == "Audit-BR behavior"
                ]
            )
        )
        for model in MODELS
    }

    rows = []

    def add_pair(task, model, without_score, with_score, source, note):
        without_score = clamp01(float(without_score))
        with_score = clamp01(float(with_score))
        rows.append(
            {
                "task": task,
                "model": model,
                "without_br_score": f"{without_score:.6f}",
                "with_br_score": f"{with_score:.6f}",
                "delta_with_minus_without": f"{with_score - without_score:.6f}",
                "source": source,
                "note": note,
            }
        )

    for model in MODELS:
        qsm_without_note = (
            "QSM no-BR baseline row present"
            if model in QSM_WITHOUT_BR_RAW
            else "no matching QSM no-BR row found; encoded as 0"
        )
        qsm_with_note = (
            "QSM with-BR row present"
            if any(metric in QSM_RAW.get(model, {}) for metric, _ in QSM_METRIC_ORDER)
            else "no matching QSM with-BR verifier row found; encoded as 0"
        )
        add_pair(
            "QSM continuous quality",
            model,
            qsm_without[model],
            qsm_with[model],
            QSM_SOURCE,
            f"{qsm_without_note}; {qsm_with_note}",
        )
        add_pair(
            "QSM binary reward",
            model,
            QSM_WITHOUT_BR_RAW.get(model, {}).get("reward", 0.0),
            QSM_RAW.get(model, {}).get("reward", 0.0),
            QSM_SOURCE,
            "binary reward is 0.0 for available requested rows; missing rows encoded as 0",
        )
        add_pair(
            "Tool routing capability",
            model,
            TOOL_ROUTING[model]["Cap no BR"],
            TOOL_ROUTING[model]["Cap +BR"],
            TOOL_SOURCE,
            TOOL_ROUTING[model]["note"],
        )
        add_pair(
            "Tool routing accuracy",
            model,
            TOOL_ROUTING[model]["Acc no BR"],
            TOOL_ROUTING[model]["Acc +BR"],
            TOOL_SOURCE,
            TOOL_ROUTING[model]["note"],
        )
        add_pair(
            "QSM knowledge evidence",
            model,
            0.0,
            qsm_knowledge_with[model],
            QSM_SOURCE,
            "with-BR evidence score derived from QSM verifier and BR-review flags; no-BR side is 0 because this family measures audit-BR evidence availability",
        )
        add_pair(
            "Audit-BR behavior",
            model,
            0.0,
            audit_behavior_with[model],
            QSM_SOURCE,
            "with-BR behavior score derived from direct BR calls, review stages, output, and verifier flags; no-BR side is 0 by definition",
        )

        layer_b_row = LAYER_B_PAIRED.get(model, {})
        without_layer_b = layer_b_aggregate(layer_b_row.get("without", {}))
        with_layer_b = layer_b_aggregate(layer_b_row.get("with", {}))
        if not layer_b_row:
            layer_note = "no result-bearing meta-analysis paired row found; encoded as 0"
            layer_source = "no result-bearing meta-analysis row found"
        else:
            layer_note = layer_b_row.get("note", "")
            layer_source = layer_b_row.get("source", "")
        add_pair(
            "Meta-analysis",
            model,
            without_layer_b,
            with_layer_b,
            layer_source,
            layer_note,
        )

    return rows


def write_qsm_raw_csv():
    fieldnames = [
        "model",
        "br_condition",
        "condition",
        "reward",
        "NRMSE",
        "dNRMSE",
        "dNRMSE_Tissue",
        "dNRMSE_Blood",
        "dNRMSE_DGM",
        "Slope Error",
        "CalcStreak",
        "Calc Error",
        "source",
    ]
    with (OUT_DIR / "qsm_raw_metrics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for br_condition, raw_by_model in (
            ("without_br", QSM_WITHOUT_BR_RAW),
            ("with_br", QSM_RAW),
        ):
            for model in MODELS:
                row = {name: "" for name in fieldnames}
                row.update(raw_by_model.get(model, {}))
                row["model"] = model
                row["br_condition"] = br_condition
                row["source"] = QSM_SOURCE
                writer.writerow(row)


def write_scores_csv(records):
    with (OUT_DIR / "model_eval_scores.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model", "family", "metric", "score", "source", "note"])
        writer.writeheader()
        writer.writerows(records)


def write_domain_scores_csv(records):
    rows = []
    for model in MODELS:
        for family in FAMILY_ORDERS:
            vals = [
                float(row["score"])
                for row in records
                if row["model"] == model and row["family"] == family
            ]
            if vals:
                rows.append(
                    {
                        "model": model,
                        "family": family,
                        "mean_score": f"{float(np.mean(vals)):.6f}",
                        "metric_count": len(vals),
                    }
                )
    with (OUT_DIR / "model_domain_scores.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model", "family", "mean_score", "metric_count"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def write_task_model_pair_scores_csv(rows):
    with (OUT_DIR / "task_model_br_pair_scores.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "task",
                "model",
                "without_br_score",
                "with_br_score",
                "delta_with_minus_without",
                "source",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def lookup_scores(records, family, metrics):
    return {
        model: [
            float(
                next(
                    (
                        row["score"]
                        for row in records
                        if row["model"] == model and row["family"] == family and row["metric"] == metric
                    ),
                    0.0,
                )
            )
            for metric in metrics
        ]
        for model in MODELS
    }


def wrap_label(label, width=13):
    return "\n".join(textwrap.wrap(label, width=width, break_long_words=False))


def save_figure(fig, stem):
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def plot_radar(records, family, stem, title):
    metrics = FAMILY_ORDERS[family]
    scores = lookup_scores(records, family, metrics)
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    fig, ax = plt.subplots(figsize=(10.5, 8.0), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    for model in MODELS:
        vals = np.array(scores[model], dtype=float)
        closed_vals = np.concatenate([vals, [vals[0]]])
        color = COLORS[model]
        ax.plot(closed_angles, closed_vals, color=color, linewidth=2.0, label=model)
        ax.fill(closed_angles, closed_vals, color=color, alpha=0.055)

    ax.set_ylim(0, 1)
    ax.set_xticks(angles)
    ax.set_xticklabels([wrap_label(metric) for metric in metrics], fontsize=9)
    ax.set_yticks([0.25, 0.50, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], fontsize=8)
    ax.grid(color="#C9CED6", linewidth=0.8, alpha=0.9)
    ax.spines["polar"].set_color("#6B7280")
    ax.set_title(title, fontsize=15, pad=28, fontweight="bold")
    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.08, 0.5),
        frameon=False,
        fontsize=9,
    )
    fig.text(
        0.02,
        0.02,
        "Scores are 0-1; missing or unavailable result rows are encoded as 0.",
        fontsize=8,
        color="#4B5563",
    )
    save_figure(fig, stem)


def plot_faceted_radar(records, family, stem, title):
    """Small-multiple radar chart following the Python Graph Gallery pattern."""

    metrics = FAMILY_ORDERS[family]
    scores = lookup_scores(records, family, metrics)
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 3
    nrows = math.ceil(len(MODELS) / ncols)
    fig_height = 3.8 * nrows if len(metrics) <= 8 else 4.4 * nrows
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(13.5, fig_height),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(MODELS):
        ax = axes[idx]
        values = np.array(scores[model], dtype=float)
        closed_values = np.concatenate([values, [values[0]]])
        color = COLORS[model]

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([wrap_label(metric, 9) for metric in metrics], fontsize=7, color="#4B5563")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6, color="#6B7280")
        ax.grid(color="#CBD5E1", linewidth=0.7, alpha=0.85)
        ax.spines["polar"].set_color("#94A3B8")
        ax.plot(closed_angles, closed_values, color=color, linewidth=2.0)
        ax.fill(closed_angles, closed_values, color=color, alpha=0.28)
        ax.set_title(model, color=color, fontsize=10.5, fontweight="bold", y=1.13)

    for ax in axes[len(MODELS) :]:
        ax.set_axis_off()

    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.012,
        "Faceted radar style follows the Python Graph Gallery recommendation for many groups; scores are 0-1 and missing rows are 0.",
        fontsize=8,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.04, right=0.98, top=0.92, bottom=0.06, wspace=0.34, hspace=0.46)
    save_figure(fig, stem)


def plot_domain_faceted_radar(domain_rows):
    metrics = list(FAMILY_ORDERS)
    scores = {
        model: [
            float(
                next(
                    row["mean_score"]
                    for row in domain_rows
                    if row["model"] == model and row["family"] == family
                )
            )
            for family in metrics
        ]
        for model in MODELS
    }
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])

    ncols = 3
    nrows = math.ceil(len(MODELS) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(13.5, 3.9 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    for idx, model in enumerate(MODELS):
        ax = axes[idx]
        values = np.array(scores[model], dtype=float)
        closed_values = np.concatenate([values, [values[0]]])
        color = COLORS[model]

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([wrap_label(metric, 10) for metric in metrics], fontsize=7, color="#4B5563")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6, color="#6B7280")
        ax.grid(color="#CBD5E1", linewidth=0.7, alpha=0.85)
        ax.spines["polar"].set_color("#94A3B8")
        ax.plot(closed_angles, closed_values, color=color, linewidth=2.0)
        ax.fill(closed_angles, closed_values, color=color, alpha=0.28)
        ax.set_title(model, color=color, fontsize=10.5, fontweight="bold", y=1.13)

    for ax in axes[len(MODELS) :]:
        ax.set_axis_off()

    fig.suptitle("Model Domain Profiles", fontsize=16, fontweight="bold", y=0.995)
    fig.text(
        0.02,
        0.012,
        "Each axis is a metric-family mean. Missing or unavailable result rows are encoded as 0.",
        fontsize=8,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.04, right=0.98, top=0.92, bottom=0.06, wspace=0.34, hspace=0.46)
    save_figure(fig, "model_domain_scores_faceted_radar")


def paired_lookup(pair_rows, task, condition):
    score_key = "with_br_score" if condition == "with" else "without_br_score"
    return [
        float(
            next(
                row[score_key]
                for row in pair_rows
                if row["task"] == task and row["model"] == model
            )
        )
        for model in MODELS
    ]


def plot_task_model_paired_radars(pair_rows):
    angles = np.linspace(0, 2 * np.pi, len(MODELS), endpoint=False)
    closed_angles = np.concatenate([angles, [angles[0]]])
    ncols = 3
    nrows = math.ceil(len(TASK_PAIRED_ORDER) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(15.5, 4.4 * nrows),
        subplot_kw={"projection": "polar"},
    )
    axes = np.array(axes).reshape(-1)

    without_color = "#64748B"
    with_color = "#D97706"

    for idx, task in enumerate(TASK_PAIRED_ORDER):
        ax = axes[idx]
        without_values = np.array(paired_lookup(pair_rows, task, "without"), dtype=float)
        with_values = np.array(paired_lookup(pair_rows, task, "with"), dtype=float)
        closed_without = np.concatenate([without_values, [without_values[0]]])
        closed_with = np.concatenate([with_values, [with_values[0]]])

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 1)
        ax.set_xticks(angles)
        ax.set_xticklabels([MODEL_SHORT_LABELS[model] for model in MODELS], fontsize=7.5, color="#4B5563")
        ax.set_rlabel_position(0)
        ax.set_yticks([0.25, 0.50, 0.75, 1.0])
        ax.set_yticklabels([".25", ".50", ".75", "1"], fontsize=6.5, color="#64748B")
        ax.grid(color="#CBD5E1", linewidth=0.7, alpha=0.85)
        ax.spines["polar"].set_color("#94A3B8")

        ax.plot(closed_angles, closed_without, color=without_color, linewidth=1.8, label="without BR")
        ax.fill(closed_angles, closed_without, color=without_color, alpha=0.10)
        ax.plot(closed_angles, closed_with, color=with_color, linewidth=2.1, label="with BR")
        ax.fill(closed_angles, closed_with, color=with_color, alpha=0.18)
        ax.set_title(task, fontsize=11.5, fontweight="bold", y=1.12)

    for ax in axes[len(TASK_PAIRED_ORDER) :]:
        ax.set_axis_off()

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=10)
    fig.suptitle("Task x Model Paired BR Radars", fontsize=17, fontweight="bold", y=0.99)
    fig.text(
        0.02,
        0.025,
        "Each panel is one task family; axes are models. Missing/unavailable paired rows are encoded as 0, not as model-quality evidence.",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.subplots_adjust(left=0.035, right=0.98, top=0.92, bottom=0.08, wspace=0.34, hspace=0.48)
    save_figure(fig, "task_model_paired_br_radars")


def plot_task_model_delta_heatmap(pair_rows):
    matrix = np.array(
        [
            [
                float(
                    next(
                        row["delta_with_minus_without"]
                        for row in pair_rows
                        if row["task"] == task and row["model"] == model
                    )
                )
                for model in MODELS
            ]
            for task in TASK_PAIRED_ORDER
        ]
    )
    fig, ax = plt.subplots(figsize=(11.8, 5.8))
    im = ax.imshow(matrix, cmap="RdBu", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(MODELS)))
    ax.set_xticklabels([MODEL_SHORT_LABELS[model].replace("\n", " ") for model in MODELS], rotation=30, ha="right")
    ax.set_yticks(range(len(TASK_PAIRED_ORDER)))
    ax.set_yticklabels(TASK_PAIRED_ORDER)
    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            value = matrix[row_idx, col_idx]
            text_color = "white" if abs(value) > 0.45 else "#111827"
            ax.text(col_idx, row_idx, f"{value:+.2f}", ha="center", va="center", color=text_color, fontsize=8)
    ax.set_title("With BR Minus Without BR Delta", fontsize=15, fontweight="bold", pad=12)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cbar.set_label("Delta in 0-1 task score", fontsize=9)
    fig.tight_layout()
    save_figure(fig, "task_model_br_delta_heatmap")


def plot_domain_heatmap(domain_rows):
    families = list(FAMILY_ORDERS)
    matrix = np.array(
        [
            [
                float(
                    next(
                        row["mean_score"]
                        for row in domain_rows
                        if row["model"] == model and row["family"] == family
                    )
                )
                for family in families
            ]
            for model in MODELS
        ]
    )
    fig, ax = plt.subplots(figsize=(10.8, 5.6))
    im = ax.imshow(matrix, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(families)))
    ax.set_xticklabels([wrap_label(family, 16) for family in families], rotation=30, ha="right", fontsize=9)
    ax.set_yticks(range(len(MODELS)))
    ax.set_yticklabels(MODELS, fontsize=9)
    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            value = matrix[row_idx, col_idx]
            text_color = "white" if value < 0.45 else "#111827"
            ax.text(col_idx, row_idx, f"{value:.2f}", ha="center", va="center", color=text_color, fontsize=8)
    ax.set_title("Mean Score By Metric Family", fontsize=15, fontweight="bold", pad=12)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cbar.set_label("Mean 0-1 score", fontsize=9)
    fig.tight_layout()
    save_figure(fig, "model_domain_scores_heatmap")


def plot_all_metric_heatmap(records):
    columns = []
    for family in FAMILY_ORDERS:
        for metric in FAMILY_ORDERS[family]:
            columns.append((family, metric))
    matrix = np.array(
        [
            [
                float(
                    next(
                        (
                            row["score"]
                            for row in records
                            if row["model"] == model and row["family"] == family and row["metric"] == metric
                        ),
                        0.0,
                    )
                )
                for family, metric in columns
            ]
            for model in MODELS
        ]
    )
    fig_width = max(16.0, len(columns) * 0.38)
    fig, ax = plt.subplots(figsize=(fig_width, 5.8))
    im = ax.imshow(matrix, cmap="magma", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([wrap_label(metric, 10) for _, metric in columns], rotation=65, ha="right", fontsize=7)
    ax.set_yticks(range(len(MODELS)))
    ax.set_yticklabels(MODELS, fontsize=9)
    ax.set_title("All Metric Scores", fontsize=15, fontweight="bold", pad=12)

    boundaries = []
    offset = 0
    for family in FAMILY_ORDERS:
        offset += len(FAMILY_ORDERS[family])
        boundaries.append(offset - 0.5)
    for boundary in boundaries[:-1]:
        ax.axvline(boundary, color="white", linewidth=1.2, alpha=0.9)

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("0-1 score", fontsize=9)
    fig.tight_layout()
    save_figure(fig, "all_metric_scores_heatmap")


def main():
    records = build_score_records()
    write_qsm_raw_csv()
    write_scores_csv(records)
    domain_rows = write_domain_scores_csv(records)
    pair_rows = build_task_model_pair_rows(records)
    write_task_model_pair_scores_csv(pair_rows)

    plot_radar(
        records,
        "QSM continuous quality",
        "qsm_continuous_quality_radar",
        "QSM Continuous Quality",
    )
    plot_radar(records, "Tool routing", "tool_routing_radar", "Tool Routing")
    plot_radar(records, "Audit-BR behavior", "audit_br_behavior_radar", "Audit-BR Behavior")
    plot_radar(
        records,
        "QSM knowledge evidence",
        "qsm_knowledge_evidence_radar",
        "QSM Knowledge Evidence",
    )
    plot_radar(
        records,
        "Meta-analysis",
        "meta_analysis_radar",
        "Meta-analysis",
    )
    plot_faceted_radar(
        records,
        "QSM continuous quality",
        "qsm_continuous_quality_faceted_radar",
        "QSM Continuous Quality",
    )
    plot_faceted_radar(records, "Tool routing", "tool_routing_faceted_radar", "Tool Routing")
    plot_faceted_radar(
        records,
        "Audit-BR behavior",
        "audit_br_behavior_faceted_radar",
        "Audit-BR Behavior",
    )
    plot_faceted_radar(
        records,
        "QSM knowledge evidence",
        "qsm_knowledge_evidence_faceted_radar",
        "QSM Knowledge Evidence",
    )
    plot_faceted_radar(
        records,
        "Meta-analysis",
        "meta_analysis_faceted_radar",
        "Meta-analysis",
    )
    plot_domain_faceted_radar(domain_rows)
    plot_task_model_paired_radars(pair_rows)
    plot_task_model_delta_heatmap(pair_rows)
    plot_domain_heatmap(domain_rows)
    plot_all_metric_heatmap(records)


if __name__ == "__main__":
    main()
