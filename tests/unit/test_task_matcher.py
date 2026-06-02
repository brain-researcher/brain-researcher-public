import os
import sys

import pandas as pd

# import pdb; pdb.set_trace()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from brain_researcher.services.br_kg.utils.task_matcher import TaskMatcher


def test_benchmark_recall():
    matcher = TaskMatcher()
    df = pd.read_csv("tests/fixtures/task_match_benchmark.tsv", sep="\t")
    hits = 0
    hits_niclip = 0
    for _, row in df.iterrows():
        cand = matcher.match_candidates(row["input"], top_k=1)
        if cand and cand[0]["label"].lower() == row["label"].lower():
            hits += 1
            if cand[0]["engine"] == "niclip":
                hits_niclip += 1
    recall = hits / len(df)
    niclip_recall = hits_niclip / len(df)
    assert recall >= 0.95
    assert niclip_recall >= 0.90
