#!/usr/bin/env python
"""
Lightweight retrieval benchmark runner for the 2B dataset produced by
`scripts/br-kg/br_kg_build_eval_sets.py`.

- Input: JSONL with fields {dataset_id, name, text, modalities, concept_ids, concept_buckets}
- Methods: TF‑IDF cosine kNN (default) or BM25 kNN; label transfer from top-k neighbors (train split).
- Metrics: Recall@k (labels), Macro-F1 (multi-label) overall + head/mid/tail slices; optional bootstrap CIs.

Usage:
    python scripts/br-kg/br_kg_eval_retrieval.py \
      --jsonl data/br-kg_exports/2B_retrieval_benchmark.jsonl \
      --topk 5 --test_frac 0.2 --seed 42 --bootstrap 0 --method tfidf

This is a dependency-light baseline (no external models). Swap vectorizer/similarity to plug in
stronger embeddings later.
"""
from __future__ import annotations

import argparse
import json
import random
import os
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import GroupShuffleSplit, train_test_split


def load_jsonl(path: Path) -> List[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def split_train_test(rows: Sequence[dict], test_frac: float, seed: int, group_field: str | None) -> Tuple[List[dict], List[dict]]:
    if not group_field:
        train, test = train_test_split(rows, test_size=test_frac, random_state=seed, shuffle=True)
        return list(train), list(test)

    groups = []
    for idx, r in enumerate(rows):
        g = r.get(group_field)
        if g is None:
            g = f"row-{idx}"
        groups.append(g)

    splitter = GroupShuffleSplit(n_splits=1, test_size=test_frac, random_state=seed)
    idx = np.arange(len(rows))
    train_idx, test_idx = next(splitter.split(idx, groups=groups))
    train = [rows[i] for i in train_idx]
    test = [rows[i] for i in test_idx]
    return train, test


def build_tfidf(train_rows: Sequence[dict]):
    texts = [r.get("text") or "" for r in train_rows]
    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2, norm="l2")
    mat = vec.fit_transform(texts)
    return vec, mat


def build_bm25(train_rows: Sequence[dict]):
    """Simple BM25 implementation on top of term counts (no external deps)."""

    texts = [r.get("text") or "" for r in train_rows]
    vec = TfidfVectorizer(
        max_features=30000,
        ngram_range=(1, 1),
        min_df=1,
        norm=None,
        use_idf=False,
    )
    tf = vec.fit_transform(texts).tocsr()  # term frequency counts (doc-term)
    df = np.asarray((tf > 0).sum(axis=0)).ravel()
    N = tf.shape[0]
    idf = np.log((N - df + 0.5) / (df + 0.5))
    idf = np.clip(idf, 0, None)  # BM25+ style floor at 0
    return vec, tf, idf


def build_gemini_embeddings(rows: Sequence[dict], model: str, api_key_env: str, batch_size: int = 64):
    """
    Build embeddings using Google Gemini embedding endpoint (File Search/Gemini API compatible).
    Requires `google-generativeai` >= 0.8 installed and an API key in the specified env var.
    """

    try:
        import google.generativeai as genai
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install google-generativeai to use --method gemini (pip install google-generativeai)") from exc

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key env var {api_key_env} for Gemini embeddings")

    genai.configure(api_key=api_key)

    texts = [r.get("text") or "" for r in rows]
    vectors: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = genai.embed_content(model=model, content=batch)
        # embed_content returns {"embedding": [...] } for single; for batches it returns list
        embs = response["embedding"] if isinstance(response, dict) and "embedding" in response else response
        vectors.extend(embs)

    mat = np.asarray(vectors, dtype=np.float32)
    # L2 normalize for cosine similarity
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
    mat = mat / norms
    return mat


def knn_predict_tfidf(vec, train_mat, train_rows, test_rows, topk: int) -> List[List[str]]:
    test_mat = vec.transform([r.get("text") or "" for r in test_rows])
    sims = test_mat @ train_mat.T  # cosine with L2-normalized tf-idf
    return _collect_labels(sims, train_rows, topk)


def knn_predict_bm25(vec, tf_train, idf, train_rows, test_rows, topk: int, k1: float = 1.5, b: float = 0.75) -> List[List[str]]:
    test_tf = vec.transform([r.get("text") or "" for r in test_rows]).tocsr()
    tf_train = tf_train.tocsr()
    dl = np.asarray(tf_train.sum(axis=1)).ravel()
    avgdl = dl.mean() or 1.0

    scores = np.zeros((test_tf.shape[0], tf_train.shape[0]), dtype=float)
    for qi in range(test_tf.shape[0]):
        row = test_tf.getrow(qi)
        for term_idx, qtf in zip(row.indices, row.data):
            idf_term = idf[term_idx]
            if idf_term == 0:
                continue
            col = tf_train.getcol(term_idx)
            tf_d = col.data
            doc_idx = col.indices
            denom = tf_d + k1 * (1 - b + b * dl[doc_idx] / avgdl)
            score = idf_term * (tf_d * (k1 + 1)) / (denom + 1e-9)
            scores[qi, doc_idx] += score * qtf
    return _collect_labels(scores, train_rows, topk)


def knn_predict_dense(train_embeds: np.ndarray, test_embeds: np.ndarray, train_rows, topk: int) -> List[List[str]]:
    sims = test_embeds @ train_embeds.T  # both already normalized
    return _collect_labels(sims, train_rows, topk)


def _collect_labels(sims, train_rows, topk: int) -> List[List[str]]:
    preds: List[List[str]] = []
    for i in range(sims.shape[0]):
        if hasattr(sims, "getrow"):
            row = sims.getrow(i)
            data = row.data
            indices = row.indices
        else:
            data = sims[i]
            indices = np.arange(len(data))
        idx = np.asarray(np.argsort(data)[::-1])
        nn_indices = indices[idx][:topk]
        labels: List[str] = []
        seen = set()
        for j in nn_indices:
            for cid in train_rows[j].get("concept_ids", []):
                if cid not in seen:
                    seen.add(cid)
                    labels.append(cid)
        preds.append(labels)
    return preds


def recall_at_k(preds: List[List[str]], golds: List[List[str]]) -> float:
    hits = 0
    total = 0
    for p, g in zip(preds, golds):
        gset = set(g)
        total += len(gset)
        hits += len(gset.intersection(p))
    return hits / total if total else 0.0


def macro_f1(preds: List[List[str]], golds: List[List[str]]) -> float:
    # Flatten into multi-hot label matrix
    all_labels = sorted({lbl for g in golds for lbl in g} | {lbl for p in preds for lbl in p})
    if not all_labels:
        return 0.0
    label_to_idx = {lbl: i for i, lbl in enumerate(all_labels)}
    y_true = np.zeros((len(golds), len(all_labels)), dtype=int)
    y_pred = np.zeros_like(y_true)
    for i, g in enumerate(golds):
        for lbl in g:
            y_true[i, label_to_idx[lbl]] = 1
    for i, p in enumerate(preds):
        for lbl in p:
            y_pred[i, label_to_idx[lbl]] = 1
    _, _, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    return f1


def slice_by_bucket(rows: Sequence[dict], preds: List[List[str]], bucket_name: str) -> Tuple[List[List[str]], List[List[str]]]:
    sel_pred, sel_gold = [], []
    for row, p in zip(rows, preds):
        gold = row.get("concept_ids", [])
        buckets = row.get("concept_buckets", [])
        keep = [cid for cid, b in zip(gold, buckets) if b == bucket_name]
        if not keep:
            continue
        sel_gold.append(keep)
        sel_pred.append([cid for cid in p if cid in set(keep)])
    return sel_pred, sel_gold


def eval_split(train_rows: List[dict], test_rows: List[dict], topk: int, method: str, gemini_model: str | None = None, gemini_key_env: str | None = None) -> Dict[str, float]:
    if method == "tfidf":
        vec, train_mat = build_tfidf(train_rows)
        preds = knn_predict_tfidf(vec, train_mat, train_rows, test_rows, topk)
    elif method == "bm25":
        vec, tf_train, idf = build_bm25(train_rows)
        preds = knn_predict_bm25(vec, tf_train, idf, train_rows, test_rows, topk)
    elif method == "gemini":
        if not gemini_model or not gemini_key_env:
            raise ValueError("gemini method requires --gemini_model and --gemini_api_key_env")
        train_embeds = build_gemini_embeddings(train_rows, gemini_model, gemini_key_env)
        test_embeds = build_gemini_embeddings(test_rows, gemini_model, gemini_key_env)
        preds = knn_predict_dense(train_embeds, test_embeds, train_rows, topk)
    else:
        raise ValueError(f"Unknown method: {method}")
    golds = [r.get("concept_ids", []) for r in test_rows]

    metrics = {
        "recall_at_k": recall_at_k(preds, golds),
        "macro_f1": macro_f1(preds, golds),
    }
    for bucket in ("head", "mid", "tail"):
        bp, bg = slice_by_bucket(test_rows, preds, bucket)
        if bg:
            metrics[f"recall_at_k_{bucket}"] = recall_at_k(bp, bg)
            metrics[f"macro_f1_{bucket}"] = macro_f1(bp, bg)
        else:
            metrics[f"recall_at_k_{bucket}"] = float("nan")
            metrics[f"macro_f1_{bucket}"] = float("nan")
    return metrics


def bootstrap_metrics(train_rows: List[dict], test_rows: List[dict], topk: int, method: str, n_boot: int, seed: int, gemini_model: str | None, gemini_key_env: str | None) -> Dict[str, Dict[str, float]]:
    rng = random.Random(seed)
    metrics_list: List[Dict[str, float]] = []
    for _ in range(n_boot):
        sample_indices = [rng.randrange(len(test_rows)) for _ in range(len(test_rows))]
        sample_rows = [test_rows[i] for i in sample_indices]
        metrics_list.append(eval_split(train_rows, sample_rows, topk, method, gemini_model, gemini_key_env))

    # aggregate percentiles
    agg: Dict[str, Dict[str, float]] = {}
    keys = metrics_list[0].keys()
    for k in keys:
        vals = np.array([m[k] for m in metrics_list], dtype=float)
        agg[k] = {
            "p2.5": float(np.nanpercentile(vals, 2.5)),
            "p50": float(np.nanpercentile(vals, 50)),
            "p97.5": float(np.nanpercentile(vals, 97.5)),
        }
    return agg


def main():
    ap = argparse.ArgumentParser(description="Run 2B retrieval baseline (TF-IDF or BM25 kNN)")
    ap.add_argument("--jsonl", required=True, type=Path, help="Path to 2B_retrieval_benchmark.jsonl")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--test_frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--method", choices=["tfidf", "bm25", "gemini"], default="tfidf")
    ap.add_argument("--bootstrap", type=int, default=0, help="Number of bootstrap resamples on test set (0 to disable)")
    ap.add_argument("--group_field", type=str, default="group", help="Grouping field for leakage-safe splits (empty to disable)")
    ap.add_argument("--gemini_model", type=str, default="text-embedding-004", help="Gemini embedding model name (for --method gemini)")
    ap.add_argument("--gemini_api_key_env", type=str, default="GOOGLE_API_KEY", help="Env var holding Gemini API key")
    args = ap.parse_args()

    rows = load_jsonl(args.jsonl)
    if not rows:
        raise SystemExit("Empty benchmark file")

    random.seed(args.seed)
    np.random.seed(args.seed)

    group_field = args.group_field or None
    train_rows, test_rows = split_train_test(rows, args.test_frac, args.seed, group_field)
    metrics = eval_split(train_rows, test_rows, args.topk, args.method, args.gemini_model, args.gemini_api_key_env)

    output = {
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "topk": args.topk,
        "method": args.method,
        "group_field": group_field,
        **metrics,
    }

    if args.bootstrap > 0:
        output["bootstrap"] = bootstrap_metrics(train_rows, test_rows, args.topk, args.method, args.bootstrap, args.seed, args.gemini_model, args.gemini_api_key_env)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
