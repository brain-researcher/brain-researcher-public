import csv
import os
import sys
import tempfile
from pathlib import Path

# import pdb; pdb.set_trace()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from brain_researcher.core.kg.matching import (
    cal_score,
    exact_fuzzy_match,
    prune_rank,
)


def test_cal_score_formula():
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "merged.csv"
        with open(inp, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "dataset_id",
                    "contrast_name",
                    "concept_id",
                    "exact_conf",
                    "fuzzy_conf",
                    "embed_conf",
                    "llm_conf",
                    "ns_z",
                    "methods",
                    "direction",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "dataset_id": "ds",
                    "contrast_name": "c",
                    "concept_id": "x",
                    "exact_conf": 1.0,
                    "fuzzy_conf": 0,
                    "embed_conf": 0,
                    "llm_conf": 0.8,
                    "ns_z": 6,
                    "methods": "exact+llm",
                    "direction": "1",
                }
            )
        outp = Path(tmp) / "scored.csv"
        cal_score.cal_score(inp, outp)
        with open(outp) as f:
            rows = list(csv.DictReader(f))
        score = float(rows[0]["overall_confidence"])
        assert abs(score - (0.5 * 1.0 + 0.3 * 0.8 + 0.2 * 1.0)) < 1e-6


def test_prune_rank_top_k():
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "scored.csv"
        fields = ["dataset_id", "contrast_name", "concept_id", "overall_confidence"]
        with open(inp, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for i in range(15):
                writer.writerow(
                    {
                        "dataset_id": "ds",
                        "contrast_name": "c",
                        "concept_id": str(i),
                        "overall_confidence": 1 - i * 0.05,
                    }
                )
        outp = Path(tmp) / "pruned.csv"
        prune_rank.prune_rank(inp, outp, min_conf=0.5, top_k=10)
        with open(outp) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 10
        assert rows[0]["concept_id"] == "0"
        assert rows[-1]["concept_id"] == "9"


def test_exact_fuzzy_basic():
    with tempfile.TemporaryDirectory() as tmp:
        contrasts = Path(tmp) / "contrasts.csv"
        with open(contrasts, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["dataset_id", "contrast_name"])
            writer.writeheader()
            writer.writerow({"dataset_id": "d", "contrast_name": "Memory"})
        aliases = Path(tmp) / "aliases.tsv"
        with open(aliases, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["concept_id", "label", "alias"], delimiter="\t"
            )
            writer.writeheader()
            writer.writerow({"concept_id": "c1", "label": "memory", "alias": ""})
            writer.writerow({"concept_id": "c2", "label": "attention", "alias": "attn"})
        outp = Path(tmp) / "out.csv"
        exact_fuzzy_match.exact_fuzzy_match(contrasts, aliases, outp)
        with open(outp) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["concept_id"] == "c1"
        assert rows[0]["method"] == "exact"
