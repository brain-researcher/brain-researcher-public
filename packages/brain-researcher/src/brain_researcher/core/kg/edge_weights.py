"""Edge weight and utility scoring utilities."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

try:
    from statsmodels.stats.inter_rater import fleiss_kappa  # pragma: no cover
except Exception:  # pragma: no cover - optional dependency
    fleiss_kappa = None


# ---------------------------------------------------------------------------
# Metadata defaults (would normally live in persistent storage)
NPMI_MIN = -1.0
NPMI_MAX = 1.0
CSV_MED = 0.0
CSV_IQR = 1.0


# ---------------------------------------------------------------------------
def compute_llm_confidence(runs: list[dict[str, Any]]) -> float:
    """Return selection frequency of a concept across multiple LLM runs."""
    if not runs:
        return 0.0
    # Determine target concept from first run
    concept = runs[0].get("name") or runs[0].get("concept")
    if not concept:
        return 0.0
    concept = str(concept).lower()
    selected = 0
    for r in runs:
        name = r.get("name") or r.get("concept")
        constructs = r.get("constructs")
        if name and str(name).lower() == concept:
            selected += 1
        elif constructs and concept in [str(c).lower() for c in constructs]:
            selected += 1
    return selected / len(runs)


def compute_fleiss_kappa_matrix(runs: list[list[str]], concepts: list[str]) -> float:
    """Optional Fleiss' kappa for inter-run agreement."""
    if fleiss_kappa is None:
        return 0.0
    if not runs or not concepts:
        return 0.0
    matrix = np.zeros((len(concepts), len(runs)), dtype=int)
    concept_to_idx = {c.lower(): i for i, c in enumerate(concepts)}
    for col, run in enumerate(runs):
        seen = {c.lower() for c in run}
        for c, idx in concept_to_idx.items():
            if c in seen:
                matrix[idx, col] = 1
    return float(fleiss_kappa(matrix.T))


# ---------------------------------------------------------------------------
def _npmi(tc: float, t: float, c: float, total: float, alpha: float = 1.0) -> float:
    """Compute Normalized Pointwise Mutual Information with Laplace smoothing."""
    P_tc = (tc + alpha) / (total + alpha)
    P_t = (t + alpha) / (total + alpha)
    P_c = (c + alpha) / (total + alpha)
    if P_tc == 0 or P_t == 0 or P_c == 0:
        return -1.0
    numerator = math.log2(P_tc / (P_t * P_c))
    denominator = -math.log2(P_tc)
    return numerator / denominator


def compute_pubmed_score(
    task: str,
    concept: str,
    counts_lookup: dict[tuple[str, str], dict[str, int]] | None = None,
    npmi_min: float = NPMI_MIN,
    npmi_max: float = NPMI_MAX,
) -> float:
    """Compute literature-based score using cached counts or lookup."""
    task_l = task.lower()
    concept_l = concept.lower()
    if counts_lookup is None:
        return 0.0  # pragma: no cover - real lookup not implemented
    data = counts_lookup.get((task_l, concept_l))
    if not data:
        return 0.0
    tc = data.get("tc", 0)
    t = data.get("t", 0)
    c = data.get("c", 0)
    total = data.get("total", 1)
    npmi = _npmi(tc, t, c, total)
    # Scale to 0-1 range using stored min/max
    scaled = (npmi - npmi_min) / (npmi_max - npmi_min)
    return max(0.0, min(1.0, scaled))


# ---------------------------------------------------------------------------
def normalize_csv_weight(
    weight: float,
    median: float = CSV_MED,
    iqr: float = CSV_IQR,
) -> float:
    """Normalize GLM weight using robust scaling and logistic transform."""
    iqr = iqr or 1.0
    z = (weight - median) / iqr
    return 1 / (1 + math.exp(-z))


# ---------------------------------------------------------------------------
def compute_utility(csv_w: float, llm_conf: float, pubmed_npmi: float) -> float:
    """Combine three channels using harmonic mean."""
    # Clamp inputs to (0,1]
    eps = 1e-12
    u_csv = max(min(csv_w, 1.0), eps)
    u_llm = max(min(llm_conf, 1.0), eps)
    u_pub = max(min(pubmed_npmi, 1.0), eps)
    return 3.0 / ((1 / u_csv) + (1 / u_llm) + (1 / u_pub))


def build_edge_properties(
    csv_weight: float,
    llm_conf: float,
    pubmed_score: float,
    csv_med: float = CSV_MED,
    csv_iqr: float = CSV_IQR,
    npmi_min: float = NPMI_MIN,
    npmi_max: float = NPMI_MAX,
) -> dict[str, Any]:
    """Create edge property dict for HAS_CONCEPT relationships."""
    u_csv = normalize_csv_weight(csv_weight, csv_med, csv_iqr)
    u_pub = pubmed_score if 0 <= pubmed_score <= 1 else max(0.0, min(1.0, pubmed_score))
    utility = compute_utility(u_csv, llm_conf, u_pub)
    return {
        "csv_w": round(u_csv, 3),
        "llm_w": round(llm_conf, 3),
        "pubmed_w": round(u_pub, 3),
        "utility": round(utility, 3),
        "sources": ["llm", "csv", "pubmed"],
        "method": "harmonic_mean_scaled",
        "validated": False,
    }
