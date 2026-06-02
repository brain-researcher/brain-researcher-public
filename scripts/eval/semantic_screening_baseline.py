#!/usr/bin/env python3
"""
Semantic screening baseline using sentence-transformers on BR-KG publications.

Pipeline:
- Load screening-ready metas from inventory.
- Use neurometabench all_studies.csv as closed-world candidates.
- Fetch publication titles from BR-KG GraphQL (one-by-one; schema exposes pmid/title).
- Encode query (meta topic/search/inclusion) and candidate titles with SBERT.
- Rank by cosine similarity, output predictions JSONL for screening-eval.

Args:
  --inventory PATH (default benchmarks/neurometabench/inventory.public.json)
  --out PATH (default preds/semantic_sbert.jsonl)
  --top-k INT (default 200)
  --model-name NAME (default sentence-transformers/all-MiniLM-L6-v2)
  --batch-size INT (default 64)
  --graphql-url URL (default env-driven; falls back to localhost BR-KG)

Requires: sentence-transformers, requests.
BR-KG GraphQL defaults to `BR_KG_GRAPHQL_URL`, then `BR_KG_URL` /
`BR_KG_URL` / `BR_KG_API_URL`, and finally `http://localhost:5000/graphql`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Dict, List

import requests
from sentence_transformers import SentenceTransformer, util
import time
import xml.etree.ElementTree as ET

DEFAULT_GRAPHQL_URL = "http://localhost:5000/graphql"
CACHE_PATH = Path(".cache/br_kg_publications.json")
MAX_RETRIES = 3
BACKOFF = 1.0  # seconds
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
    # dedupe preserve order
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


def fetch_publications_batch(pmids: List[str], graphql_url: str) -> Dict[str, Dict]:
    """Batch fetch via publicationsByPmids."""
    if not pmids:
        return {}
    query = """
    query($pmids:[String!]!){
      publicationsByPmids(pmids:$pmids){
        pmid
        title
        abstract
        concepts
      }
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
    """Fetch title/abstract from PubMed EFetch as a fallback."""
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
        return {"pmid": pmid, "title": title, "abstract": abstract, "concepts": []}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="Semantic SBERT baseline for neurometabench screening.")
    ap.add_argument("--inventory", type=Path, default=Path("benchmarks/neurometabench/inventory.public.json"))
    ap.add_argument("--out", type=Path, default=Path("preds/semantic_sbert.jsonl"))
    ap.add_argument("--top-k", type=int, default=200)
    ap.add_argument("--model-name", type=str, default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--batch-size", type=int, default=64)
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

            candidates = load_candidates(repo_root, meta_pmid)

            # One batch call to BR-KG, with retries handled inside.
            fetched = fetch_publications_batch(candidates, graphql_url)
            cache.update(fetched)

            docs: List[str] = []
            pmids_for_docs: List[str] = []

            for pmid in candidates:
                info = cache.get(pmid)

                # Fallback to PubMed if KG lacks title/abstract.
                if not info or not ((info.get("title") or "").strip()):
                    fallback = fetch_pubmed_fallback(pmid)
                    if fallback:
                        info = fallback
                        cache[pmid] = info
                    else:
                        info = info or {"pmid": pmid, "title": "", "abstract": "", "concepts": []}

                title = (info.get("title") or "").strip()
                abstract = (info.get("abstract") or "").strip()
                concepts = info.get("concepts") or []

                doc = " ".join(filter(None, [title, abstract, " ".join(concepts)]))
                if not doc:
                    # Keep placeholder so ranks align; embedding an empty string is acceptable but low-signal.
                    doc = ""

                docs.append(doc)
                pmids_for_docs.append(pmid)

            if not docs:
                continue

            doc_embs = model.encode(
                docs,
                convert_to_tensor=True,
                batch_size=args.batch_size,
                normalize_embeddings=True,
            )
            sims = util.cos_sim(query_emb, doc_embs).cpu().tolist()[0]

            scored = list(zip(pmids_for_docs, sims))
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
