import math
import os
import sys

# import pdb; pdb.set_trace()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from brain_researcher.core.utils.edge_weights import (
    build_edge_properties,
    compute_llm_confidence,
    compute_pubmed_score,
    compute_utility,
    normalize_csv_weight,
)

# Synthetic counts for PubMed/Neurosynth co-occurrence
COUNTS = {
    ("stroop", "memory"): {"tc": 20, "t": 200, "c": 500, "total": 10000},
    ("driving", "attention"): {"tc": 5, "t": 10, "c": 15, "total": 10000},
}


def test_llm_confidence_simple():
    runs = [{"name": "memory"} for _ in range(4)] + [{"name": "attention"}]
    conf = compute_llm_confidence([r for r in runs if r["name"] == "memory"])
    assert math.isclose(conf, 1.0)


def test_pubmed_npmi_bounds():
    score = compute_pubmed_score("stroop", "memory", COUNTS)
    assert 0 <= score <= 1
    raw_npmi = compute_pubmed_score(
        "stroop", "memory", COUNTS, npmi_min=-1.0, npmi_max=1.0
    )
    assert -1 < (raw_npmi * 2 - 1) < 1


def test_utility_monotonic():
    llm_conf = 0.6
    pubmed_score_mem = compute_pubmed_score("stroop", "memory", COUNTS)
    pubmed_score_drive = compute_pubmed_score("driving", "attention", COUNTS)
    csv_mem = normalize_csv_weight(0.2)
    csv_drive = normalize_csv_weight(0.1)

    util_mem = compute_utility(csv_mem, llm_conf, pubmed_score_mem)
    util_drive = compute_utility(csv_drive, llm_conf, pubmed_score_drive)

    assert 0 <= util_mem <= 1
    assert 0 <= util_drive <= 1
    # Rare but relevant pair should not be penalized heavily
    assert util_drive >= util_mem or pubmed_score_drive >= pubmed_score_mem

    props = build_edge_properties(0.2, llm_conf, pubmed_score_mem)
    assert 0 <= props["utility"] <= 1
