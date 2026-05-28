"""
# Task Matchers

This repository includes a hybrid matcher that resolves task strings to
Cognitive Atlas task labels. The matcher first queries a NiCLIP embedding index,
then falls back to SBERT and finally RapidFuzz string matching.

Default thresholds:

- **NiCLIP**: similarity ≥ 0.85
- **SBERT**: similarity ≥ 0.80
- **Fuzzy**: ratio ≥ 85

The vocabulary is derived from Cognitive Atlas task definitions
(`neurokg/data/neurokg/raw/cognitive_tasks.json`) plus custom synonyms listed in
`data/ca_task_synonyms.tsv`.

```
from utils.task_matcher import TaskMatcher

matcher = TaskMatcher()
print(matcher.match_candidates("BART", top_k=3))
```

To extend the synonym list, edit `data/ca_task_synonyms.tsv` and rebuild the
indices with `python scripts/build/build_task_indices.py`.

Task Matcher Module

Hybrid matcher cascades NiCLIP embeddings, SBERT embeddings and RapidFuzz string
matching. Engine order and default thresholds:
 1. NiCLIP (>=0.85)
 2. SBERT (>=0.80)
 3. RapidFuzz ratio (>=85)

NiCLIP model hash: 2024-07-17-clip-vit-b32
SBERT model: sentence-transformers/all-MiniLM-L6-v2

The matcher loads Cognitive Atlas task labels from
``neurokg/data/neurokg/raw/cognitive_tasks.json`` and additional synonyms from
``data/ca_task_synonyms.tsv``. Indices are built using faiss HNSW.
"""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np
from rapidfuzz import fuzz, process
from sentence_transformers import SentenceTransformer

try:
    from niclip_text_encoder import TextEncoder as NiCLIPEncoder

    _NICLIP_AVAILABLE = True
except Exception:  # pragma: no cover - library optional
    _NICLIP_AVAILABLE = False
    NiCLIPEncoder = None


class TaskMatcher:
    """Hybrid task matcher using NiCLIP → SBERT → Fuzzy."""

    def __init__(
        self,
        niclip_threshold: float = 0.85,
        sbert_threshold: float = 0.80,
        fuzzy_threshold: int = 85,
    ) -> None:
        self.niclip_threshold = niclip_threshold
        self.sbert_threshold = sbert_threshold
        self.fuzzy_threshold = fuzzy_threshold

        self.labels, self.label_lookup = self._load_vocabulary()
        self._build_indices()

    # ------------------------------------------------------------------
    def _load_vocabulary(self) -> tuple[list[str], dict[str, str]]:
        labels = []
        lookup: dict[str, str] = {}

        ca_path = Path("neurokg/data/neurokg/raw/cognitive_tasks.json")
        if ca_path.exists():
            with open(ca_path) as f:
                data = json.load(f)
                for item in data:
                    name = item.get("name", "")
                    if name:
                        labels.append(name)
                        lookup[name.lower()] = name

        syn_path = Path("data/ca_task_synonyms.tsv")
        if syn_path.exists():
            with open(syn_path) as f:
                next(f, None)  # header
                for line in f:
                    if not line.strip():
                        continue
                    label, syn = line.rstrip().split("\t")[:2]
                    labels.append(syn)
                    lookup[syn.lower()] = label
                    if label not in lookup:
                        lookup[label.lower()] = label

        # Unique preserve order
        seen = set()
        uniq = []
        for lab in labels:
            if lab not in seen:
                uniq.append(lab)
                seen.add(lab)
        return uniq, lookup

    # ------------------------------------------------------------------
    def _build_indices(self) -> None:
        self.sbert_model = SentenceTransformer("all-MiniLM-L6-v2")
        self.sbert_embs = self.sbert_model.encode(
            self.labels, normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")

        dim_sbert = self.sbert_embs.shape[1]
        self.sbert_index = faiss.IndexHNSWFlat(dim_sbert, 32)
        self.sbert_index.hnsw.efConstruction = 40
        self.sbert_index.add(self.sbert_embs)

        self.niclip_encoder = None
        self.niclip_embs = None
        if _NICLIP_AVAILABLE:  # pragma: no cover - heavy optional dependency
            self.niclip_encoder = NiCLIPEncoder()
            self.niclip_embs = self.niclip_encoder.encode(
                self.labels, batch_size=32
            ).astype("float32")
            dim_n = self.niclip_embs.shape[1]
            self.niclip_index = faiss.IndexHNSWFlat(dim_n, 32)
            self.niclip_index.hnsw.efConstruction = 40
            self.niclip_index.add(self.niclip_embs)

    # ------------------------------------------------------------------
    def _encode_niclip(self, text: str) -> np.ndarray:
        if not self.niclip_encoder:
            raise RuntimeError("NiCLIP encoder unavailable")
        emb = self.niclip_encoder.encode([text])[0].astype("float32")
        return emb.reshape(1, -1)

    def _encode_sbert(self, text: str) -> np.ndarray:
        emb = self.sbert_model.encode(
            [text], normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")
        return emb.reshape(1, -1)

    # ------------------------------------------------------------------
    def match_candidates(
        self, task_string: str, top_k: int = 5
    ) -> list[dict[str, any]]:
        results: list[dict[str, any]] = []
        query = task_string.strip()

        if self.niclip_encoder:
            q = self._encode_niclip(query)
            D, I = self.niclip_index.search(q, top_k)
            for score, idx in zip(D[0], I[0], strict=False):
                label = self.labels[idx]
                results.append(
                    {"label": label, "score": float(score), "engine": "niclip"}
                )
            if results and results[0]["score"] >= self.niclip_threshold:
                return results

        q = self._encode_sbert(query)
        D, I = self.sbert_index.search(q, top_k)
        sbert_hits = []
        for score, idx in zip(D[0], I[0], strict=False):
            label = self.labels[idx]
            sbert_hits.append(
                {"label": label, "score": float(score), "engine": "sbert"}
            )
        results.extend(sbert_hits)
        if sbert_hits and sbert_hits[0]["score"] >= self.sbert_threshold:
            return results

        best = process.extractOne(query, self.labels, scorer=fuzz.ratio)
        if best:
            label, score, _ = best
            score_norm = score / 100.0
            results.append({"label": label, "score": score_norm, "engine": "fuzzy"})
            if score >= self.fuzzy_threshold:
                return results

        best_label = results[0]["label"] if results else ""
        best_score = results[0]["score"] if results else 0.0
        engine = results[0]["engine"] if results else "none"
        self._log_miss(query, best_label, best_score, engine)
        return results

    # ------------------------------------------------------------------
    def _log_miss(
        self, query: str, best_label: str, best_score: float, engine: str
    ) -> None:
        log_path = Path("logs/match_fails.tsv")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"{query}\t{best_label}\t{best_score:.3f}\t{engine}\n")


# ----------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover - manual test
    import argparse

    parser = argparse.ArgumentParser(description="Self test TaskMatcher")
    parser.add_argument("--self-test", action="store_true", help="run demo search")
    args = parser.parse_args()
    if args.self_test:
        matcher = TaskMatcher()
        demo = ["nback", "bart", "unknown task"]
        for q in demo:
            hits = matcher.match_candidates(q, top_k=3)
            print(q, "->", hits)
