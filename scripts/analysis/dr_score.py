import json
import math
import os
import sys
import time

import requests

CACHE_PATH = "cache_pubmed.json"

# 1. PubMed API hit count


def get_pubmed_hits(
    query: str, cache: dict[str, int] | None = None, retry: int = 3
) -> int:
    if cache is not None and query in cache:
        return cache[query]
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {"db": "pubmed", "retmode": "json", "term": query, "rettype": "count"}
    for attempt in range(retry):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            count = int(data["esearchresult"]["count"])
            if cache is not None:
                cache[query] = count
            time.sleep(0.3)
            return count
        except Exception as e:
            if attempt == retry - 1:
                print(f"[PubMed] Failed for query '{query}': {e}")
                return 0
            time.sleep(1)
    return 0


# 2. Neurosynth/NiMARE term count


def get_neurosynth_hits(term: str, ns_index: dict[str, int]) -> int:
    return ns_index.get(term.lower(), 0)


# 3. DR score (log_hits)


def dr_score(
    task: str,
    construct: str,
    ns_index: dict[str, int],
    cache: dict[tuple[str, str], float],
    pubmed_cache: dict[str, int] | None = None,
) -> float:
    query = f'"{task}" AND "{construct}"'
    cache_key = (task, construct)
    if cache_key in cache:
        return cache[cache_key]
    pubmed_hits = get_pubmed_hits(query, pubmed_cache)
    ns_hits = get_neurosynth_hits(construct, ns_index)
    raw = pubmed_hits + ns_hits
    log_hits = math.log10(1 + raw)
    cache[cache_key] = log_hits
    return log_hits


# 4. Task-level normalization


def normalise_by_task(
    log_hit_dict: dict[tuple[str, str], float],
) -> dict[tuple[str, str], float]:
    # Group by task
    task2vals: dict[str, list[float]] = {}
    for (task, construct), val in log_hit_dict.items():
        task2vals.setdefault(task, []).append(val)
    out = {}
    for (task, construct), val in log_hit_dict.items():
        maxval = max(task2vals[task]) if task2vals[task] else 0
        if maxval > 0:
            out[(task, construct)] = round(val / maxval, 2)
        else:
            out[(task, construct)] = 0.1
    return out


# 5. CLI


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python scripts/analysis/dr_score.py annotations.json ns_counts.json dr_out.json"
        )
        sys.exit(1)
    ann_path, ns_path, out_path = sys.argv[1:4]
    with open(ann_path) as f:
        ann_blocks = json.load(f)
    with open(ns_path) as f:
        ns_index = json.load(f)
    # Load or create cache
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            pubmed_cache = json.load(f)
    else:
        pubmed_cache = {}

    # Flatten keys for cache
    def parse_key(k):
        if isinstance(k, str) and "|||" in k:
            return tuple(k.split("|||", 1))
        return k

    pubmed_cache = {parse_key(k): v for k, v in pubmed_cache.items()}
    log_hit_dict = {}
    for block in ann_blocks:
        task = block["task_name"]
        for c in block["constructs"]:
            cid = c["id"]
            key = (task, cid)
            log_hit = dr_score(task, cid, ns_index, log_hit_dict, pubmed_cache)
            log_hit_dict[key] = log_hit
    # Save cache (convert tuple keys to string)
    cache_to_save = {
        f"{k[0]}|||{k[1]}" if isinstance(k, tuple) else k: v
        for k, v in pubmed_cache.items()
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache_to_save, f, indent=2)
    # Normalize
    dr_norm_dict = normalise_by_task(log_hit_dict)
    # Write output: add DR_norm to each construct
    for block in ann_blocks:
        task = block["task_name"]
        for c in block["constructs"]:
            cid = c["id"]
            c["DR_norm"] = dr_norm_dict.get((task, cid), 0.1)
    with open(out_path, "w") as f:
        json.dump(ann_blocks, f, indent=2)
    print(f"Wrote DR_norm to {out_path}")


if __name__ == "__main__":
    main()
