#!/usr/bin/env python3
"""
Hybrid screening baseline combining BM25 (title/abstract/concepts) and SBERT semantic similarity.

Pipeline
- Load screening-ready metas from inventory (neurometabench).
- Closed-world candidates come from neurometabench data/all_studies.csv.
- Fetch publication metadata via BR-KG GraphQL (batch) with PubMed fallback.
- Compute BM25 scores over tokenized documents and SBERT cosine similarity.
- Blend scores: score = alpha * bm25_norm + (1 - alpha) * sbert_norm.
- Rank and emit predictions JSONL for screening-eval.

Args
  --inventory PATH : neurometabench inventory (default benchmarks/neurometabench/inventory.public.json)
  --out PATH       : output predictions JSONL (default preds/hybrid_bm25_sbert.jsonl)
  --top-k INT      : number of docs to select (default 200)
  --model-name     : SBERT model (default sentence-transformers/all-MiniLM-L6-v2)
  --batch-size INT : SBERT encode batch size (default 64)
  --alpha FLOAT    : weight for BM25 (0..1). alpha=1 => BM25 only, alpha=0 => SBERT only. default 0.6
  --graphql-url    : BR-KG GraphQL endpoint or base URL

Requires: sentence-transformers, no extra deps (BM25 implemented locally).
BR-KG GraphQL defaults to `BR_KG_GRAPHQL_URL`, then `BR_KG_URL` /
`BR_KG_URL` / `BR_KG_API_URL`, and finally `http://localhost:5000/graphql`.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence

import requests
from sentence_transformers import SentenceTransformer, util

DEFAULT_GRAPHQL_URL = "http://localhost:5000/graphql"
CACHE_PATH = Path(".cache/br_kg_publications.json")
MAX_RETRIES = 3
BACKOFF = 1.0
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def resolve_graphql_url(raw: str | None = None) -> str:
    candidate = (
        raw
        or os.getenv("BR_KG_GRAPHQL_URL")
        or os.getenv("BR_KG_URL")
        or os.getenv("BR_KG_BASE_URL")
        or os.getenv("BR_KG_URL")
        or os.getenv("BR_KG_API_URL")
        or DEFAULT_GRAPHQL_URL
    ).strip()
    normalized = candidate.rstrip("/")
    if normalized.endswith("/graphql"):
        return normalized
    return f"{normalized}/graphql"


# ---------- Data loading ----------


def load_inventory(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_candidates(repo_root: Path, meta_pmid: str) -> List[str]:
    src = repo_root / "data" / "all_studies.csv"
    pmids: List[str] = []
    with src.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            if (row.get("meta_pmid") or "").strip() == meta_pmid:
                sp = (row.get("study_pmid") or "").strip()
                if sp:
                    pmids.append(sp)
    seen = set()
    out = []
    for p in pmids:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def load_meta_query(repo_root: Path, meta_pmid: str) -> str:
    src = repo_root / "data" / "meta_datasets.csv"
    with src.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            if (row.get("pmid") or "").strip() == meta_pmid:
                parts = [row.get("topic"), row.get("search"), row.get("inclusion")]
                q = " ".join(filter(None, parts)).strip()
                return q or "fMRI meta-analysis inclusion criteria"
    return "fMRI meta-analysis inclusion criteria"


# ---------- Cache helpers ----------


def load_cache() -> Dict[str, Dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: Dict[str, Dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Fetchers ----------


def fetch_publications_batch(pmids: List[str], graphql_url: str) -> Dict[str, Dict]:
    if not pmids:
        return {}
    query = """
    query($pmids:[String!]!){
      publicationsByPmids(pmids:$pmids){ pmid title abstract concepts }
    }
    """
    variables = {"pmids": pmids}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(graphql_url, json={"query": query, "variables": variables}, timeout=60)
            if r.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests")
            r.raise_for_status()
            items = (r.json().get("data") or {}).get("publicationsByPmids") or []
            out = {}
            for it in items:
                pmid = str(it.get("pmid") or "").strip()
                if not pmid:
                    continue
                out[pmid] = {
                    "pmid": pmid,
                    "title": it.get("title") or "",
                    "abstract": it.get("abstract") or "",
                    "concepts": it.get("concepts") or [],
                }
            return out
        except Exception:
            if attempt == MAX_RETRIES:
                break
            time.sleep(BACKOFF * attempt)
    return {}


def fetch_pubmed_fallback(pmid: str) -> Dict:
    try:
        params = {"db": "pubmed", "id": pmid, "retmode": "xml"}
        r = requests.get(PUBMED_EFETCH, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        article = root.find(".//Article")
        if article is None:
            return {}
        title = (article.findtext("ArticleTitle") or "").strip()
        abstract = " ".join(t.text or "" for t in article.findall(".//AbstractText")).strip()
        mesh_terms = [m.text.strip() for m in root.findall(".//MeshHeadingList/MeshHeading/DescriptorName") if m.text]
        return {"pmid": pmid, "title": title, "abstract": abstract, "concepts": mesh_terms}
    except Exception:
        return {}


# ---------- BM25 implementation ----------


TOKEN_RE = re.compile(r"[A-Za-z]{3,}")


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


class BM25:
    def __init__(self, corpus_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus_tokens
        self.doc_freq: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_len = [len(doc) for doc in corpus_tokens]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0
        self._build()

    def _build(self):
        N = len(self.corpus)
        for doc in self.corpus:
            for word in set(doc):
                self.doc_freq[word] = self.doc_freq.get(word, 0) + 1
        for word, df in self.doc_freq.items():
            self.idf[word] = math.log((N - df + 0.5) / (df + 0.5) + 1)

    def score(self, query_tokens: Sequence[str]) -> List[float]:
        scores: List[float] = []
        q_freq = Counter(query_tokens)
        for idx, doc in enumerate(self.corpus):
            score = 0.0
            doc_tf = Counter(doc)
            dl = self.doc_len[idx]
            for term, qf in q_freq.items():
                if term not in doc_tf:
                    continue
                idf = self.idf.get(term, 0.0)
                tf = doc_tf[term]
                num = tf * (self.k1 + 1)
                den = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl + 1e-9))
                score += idf * (num / den) * qf
            scores.append(score)
        return scores


def min_max_norm(vals: List[float]) -> List[float]:
    if not vals:
        return vals
    vmin, vmax = min(vals), max(vals)
    if math.isclose(vmin, vmax):
        return [0.0 for _ in vals]
    return [(v - vmin) / (vmax - vmin) for v in vals]


# ---------- Main ----------


def main():
    ap = argparse.ArgumentParser(description="Hybrid BM25+SBERT baseline for neurometabench screening")
    ap.add_argument("--inventory", type=Path, default=Path("benchmarks/neurometabench/inventory.public.json"))
    ap.add_argument("--out", type=Path, default=Path("preds/hybrid_bm25_sbert.jsonl"))
    ap.add_argument("--top-k", type=int, default=200)
    ap.add_argument("--model-name", type=str, default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--alpha", type=float, default=0.6, help="BM25 weight (0..1)")
    ap.add_argument(
        "--graphql-url",
        type=str,
        default=None,
        help="BR-KG GraphQL endpoint or base URL",
    )
    args = ap.parse_args()
    graphql_url = resolve_graphql_url(args.graphql_url)

    inv = load_inventory(args.inventory)
    repo_root = Path(inv["provenance"]["repo_root"])
    metas = [c for c in inv["cases"] if c.get("ready_screening_from_fulltext")]
    if not metas:
        raise SystemExit("No screening-ready cases in inventory.")

    cache = load_cache()
    model = SentenceTransformer(args.model_name)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    with args.out.open("w", encoding="utf-8") as outf:
        for meta in metas:
            meta_pmid = meta["pmid"]
            query_text = load_meta_query(repo_root, meta_pmid)
            query_emb = model.encode(query_text, convert_to_tensor=True, normalize_embeddings=True)
            query_tokens = tokenize(query_text)

            candidates = load_candidates(repo_root, meta_pmid)

            fetched = fetch_publications_batch(candidates, graphql_url)
            cache.update(fetched)

            docs: List[str] = []
            doc_tokens: List[List[str]] = []
            pmids_for_docs: List[str] = []

            for pmid in candidates:
                info = cache.get(pmid)
                if not info or not ((info.get("title") or "").strip()):
                    fb = fetch_pubmed_fallback(pmid)
                    if fb:
                        info = fb
                        cache[pmid] = info
                    else:
                        info = info or {"pmid": pmid, "title": "", "abstract": "", "concepts": []}

                title = (info.get("title") or "").strip()
                abstract = (info.get("abstract") or "").strip()
                concepts = info.get("concepts") or []
                doc_text = " ".join(filter(None, [title, abstract, " ".join(concepts)]))
                docs.append(doc_text)
                doc_tokens.append(tokenize(doc_text))
                pmids_for_docs.append(pmid)

            if not docs:
                continue

            # BM25
            bm25 = BM25(doc_tokens)
            bm25_scores = bm25.score(query_tokens)
            bm25_norm = min_max_norm(bm25_scores)

            # SBERT
            doc_embs = model.encode(
                docs,
                convert_to_tensor=True,
                batch_size=args.batch_size,
                normalize_embeddings=True,
            )
            sims = util.cos_sim(query_emb, doc_embs).cpu().tolist()[0]
            sbert_norm = min_max_norm(sims)

            alpha = max(0.0, min(1.0, args.alpha))
            blended = [alpha * b + (1 - alpha) * s for b, s in zip(bm25_norm, sbert_norm)]

            scored = list(zip(pmids_for_docs, blended))
            scored.sort(key=lambda x: x[1], reverse=True)
            selected = [pm for pm, _ in scored[: args.top_k]]

            outf.write(json.dumps({"pmid": meta_pmid, "selected_pmids": selected}, ensure_ascii=False) + "\n")

    save_cache(cache)
    print(f"Wrote predictions to {args.out}")
    print(
        "Eval:\n python -m benchmarks.neurometabench.runner --inventory benchmarks/neurometabench/inventory.public.json screening-eval --predictions",
        args.out,
    )


if __name__ == "__main__":
    main()
