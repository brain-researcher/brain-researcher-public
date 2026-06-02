#!/usr/bin/env python3
"""Retrieval-only diagnostics for NeurometaBench v1.

This script measures whether candidate retrieval can find the ground-truth
study PMIDs before any LLM screening is run. It deliberately reports retrieval
coverage separately from screening quality.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    load_case_records,
    load_closed_world_candidates,
    load_mixed_pool_candidates,
    sort_pmids,
    write_jsonl,
)


QUERY_MODES = ("official_query", "br_llm_query", "broad_query", "union_query")

_REVIEW_RE = re.compile(
    r"\b(?:systematic\s+reviews?|meta-analys(?:is|es)|review\s+articles?|reviews?)\b",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;\n\t")


def _tokens(text: str) -> list[str]:
    stopwords = {
        "and",
        "article",
        "articles",
        "analyses",
        "analysis",
        "associated",
        "brain",
        "case",
        "completing",
        "control",
        "data",
        "english",
        "human",
        "humans",
        "imaging",
        "included",
        "language",
        "meta",
        "mri",
        "only",
        "original",
        "paper",
        "papers",
        "participant",
        "participants",
        "reported",
        "reporting",
        "review",
        "results",
        "scan",
        "studies",
        "study",
        "the",
        "while",
        "with",
        "was",
    }
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()):
        token = token.strip("-")
        if not token or token in stopwords or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def inclusion_requires_review(case: dict[str, Any]) -> bool:
    text = " ".join(
        _clean_text(case.get(field))
        for field in ("search", "inclusion", "additional_methods", "topic")
    ).lower()
    return bool(re.search(r"\breview(?:s)?\s+were\s+included\b|\bsystematic\s+review\b", text))


def _primary_study_filter(case: dict[str, Any]) -> str:
    if inclusion_requires_review(case):
        return ""
    return " NOT (Review[Publication Type] OR Meta-Analysis[Publication Type])"


def _strip_review_meta_terms(query: str) -> str:
    query = _REVIEW_RE.sub(" ", query)
    query = re.sub(r"\bOR\s+(?:AND|OR|NOT)\b", " ", query, flags=re.IGNORECASE)
    query = re.sub(r"\b(?:AND|OR|NOT)\s*$", " ", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query)
    query = re.sub(r"\(\s*\)", " ", query)
    return query.strip(" ;.")


def build_official_query(case: dict[str, Any]) -> str:
    return _clean_text(case.get("search"))


def build_br_llm_query(case: dict[str, Any]) -> str:
    """Deterministic high-recall replacement for the previous LLM query policy.

    The name is kept for diagnostics because this is the BR-reformulated query
    arm. It avoids the observed failure mode of forcing review/meta-analysis
    terms when the retrieval target is primary studies.
    """

    raw = _strip_review_meta_terms(build_official_query(case))
    if not raw:
        raw = " ".join(_clean_text(case.get(field)) for field in ("topic", "modality", "method"))
    return f"({raw}){_primary_study_filter(case)}"


def build_broad_query(case: dict[str, Any]) -> str:
    text = " ".join(
        _clean_text(case.get(field))
        for field in ("topic", "modality", "method", "inclusion", "additional_methods")
    )
    toks = _tokens(_strip_review_meta_terms(text))
    modality_terms: list[str] = []
    modality = _clean_text(case.get("modality")).lower()
    method = _clean_text(case.get("method")).lower()
    if "fmri" in modality or "functional" in modality:
        modality_terms.extend(["fMRI", '"functional MRI"', '"functional magnetic resonance imaging"'])
    elif "structural" in modality or "vbm" in method or "morphometr" in text.lower():
        modality_terms.extend(["MRI", '"voxel-based morphometry"', '"gray matter"', '"grey matter"'])
    elif "pet" in modality:
        modality_terms.extend(["PET", '"positron emission tomography"'])
    else:
        modality_terms.extend(["MRI", "fMRI", "PET"])

    topic_terms = toks[:8] or _tokens(_clean_text(case.get("topic")))[:4]
    groups: list[str] = []
    if modality_terms:
        groups.append("(" + " OR ".join(modality_terms) + ")")
    if topic_terms:
        groups.append("(" + " OR ".join(f'"{tok}"' for tok in topic_terms) + ")")
    query = " AND ".join(groups) if groups else build_br_llm_query(case)
    return f"{query}{_primary_study_filter(case)}"


def build_query_set(case: dict[str, Any]) -> dict[str, str]:
    official = build_official_query(case)
    br = build_br_llm_query(case)
    broad = build_broad_query(case)
    return {
        "official_query": official,
        "br_llm_query": br,
        "broad_query": broad,
        "union_query": " OR ".join(f"({query})" for query in (official, br, broad) if query),
    }


def pubmed_esearch(
    query: str,
    *,
    retmax: int,
    api_key: str | None = None,
    year_cutoff: int | None = None,
    email: str | None = None,
    timeout_s: int = 30,
) -> tuple[list[str], int]:
    params: dict[str, str] = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(retmax),
        "sort": "relevance",
        "tool": "brain_researcher_neurometabench_retrieval_only",
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    if year_cutoff is not None:
        params["datetype"] = "pdat"
        params["maxdate"] = f"{int(year_cutoff)}/12/31"
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout_s) as response:
        data = json.loads(response.read().decode("utf-8"))
    result = data.get("esearchresult", {})
    return [str(pmid) for pmid in result.get("idlist", [])], int(result.get("count") or 0)


def retrieval_diagnostic_row(
    case: dict[str, Any],
    *,
    query_mode: str,
    query: str,
    candidate_pmids: list[str],
    n_hits: int | None = None,
) -> dict[str, Any]:
    gt = set(str(pmid) for pmid in case.get("gt_pmids", []))
    candidates = set(str(pmid) for pmid in candidate_pmids)
    found = gt & candidates
    return {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "topic": case.get("topic"),
        "route": case.get("route"),
        "query_mode": query_mode,
        "query": query,
        "n_hits": n_hits if n_hits is not None else len(candidate_pmids),
        "n_candidates": len(candidates),
        "n_gt": len(gt),
        "n_gt_in_candidates": len(found),
        "candidate_recall": round(len(found) / len(gt), 6) if gt else None,
        "gt_missing_from_candidates": sort_pmids(gt - candidates),
        "candidate_pmids": sort_pmids(candidates),
    }


def run_retrieval_diagnostics(
    cases_path: Path,
    output: Path,
    *,
    retriever: str = "pubmed",
    data_dir: Path = DEFAULT_DATA_DIR,
    max_candidates: int = 500,
    max_cases: int | None = None,
    only_with_gt: bool = True,
    api_key: str | None = None,
    email: str | None = None,
    sleep_s: float = 0.34,
) -> dict[str, Any]:
    cases = load_case_records(cases_path)
    if only_with_gt:
        cases = [case for case in cases if case.get("has_gt")]
    if max_cases is not None:
        cases = cases[:max_cases]

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        queries = build_query_set(case)
        mode_candidates: dict[str, list[str]] = {}
        mode_hit_counts: dict[str, int] = {}
        for mode in ("official_query", "br_llm_query", "broad_query"):
            query = queries[mode]
            if retriever == "closed_world":
                candidates = load_closed_world_candidates(data_dir, str(case.get("meta_pmid") or ""))
                hit_count = len(candidates)
            elif retriever == "mixed_pool":
                candidates = load_mixed_pool_candidates(
                    data_dir,
                    str(case.get("meta_pmid") or ""),
                    max_total=max_candidates,
                )
                hit_count = len(candidates)
            else:
                try:
                    candidates, hit_count = pubmed_esearch(
                        query,
                        retmax=max_candidates,
                        api_key=api_key,
                        email=email,
                        year_cutoff=case.get("year_cutoff"),
                    )
                    time.sleep(sleep_s)
                except Exception as exc:
                    failures.append(
                        {
                            "case_id": case.get("case_id"),
                            "query_mode": mode,
                            "query": query,
                            "error": str(exc),
                        }
                    )
                    candidates, hit_count = [], 0
            mode_candidates[mode] = candidates if retriever in {"closed_world", "mixed_pool"} else candidates[:max_candidates]
            mode_hit_counts[mode] = hit_count
            rows.append(
                retrieval_diagnostic_row(
                    case,
                    query_mode=mode,
                    query=query,
                    candidate_pmids=mode_candidates[mode],
                    n_hits=hit_count,
                )
            )

        union_candidates = sort_pmids(
            pmid for mode in ("official_query", "br_llm_query", "broad_query") for pmid in mode_candidates[mode]
        )
        rows.append(
            retrieval_diagnostic_row(
                case,
                query_mode="union_query",
                query=queries["union_query"],
                candidate_pmids=union_candidates[:max_candidates],
                n_hits=sum(mode_hit_counts.values()),
            )
        )

    write_jsonl(rows, output)
    recall_values = [row["candidate_recall"] for row in rows if row["candidate_recall"] is not None]
    by_mode: dict[str, list[float]] = {}
    for row in rows:
        if row["candidate_recall"] is None:
            continue
        by_mode.setdefault(str(row["query_mode"]), []).append(float(row["candidate_recall"]))
    return {
        "output": str(output),
        "retriever": retriever,
        "n_cases": len(cases),
        "n_rows": len(rows),
        "n_failures": len(failures),
        "failures": failures,
        "macro_candidate_recall": (
            round(sum(recall_values) / len(recall_values), 6) if recall_values else None
        ),
        "macro_candidate_recall_by_mode": {
            mode: round(sum(values) / len(values), 6) for mode, values in sorted(by_mode.items())
        },
        "screening_gate": {
            "candidate_recall_threshold": 0.6,
            "passing_rows": sum(
                1 for row in rows if row["candidate_recall"] is not None and row["candidate_recall"] >= 0.6
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, default=Path("/tmp/neurometabench_v1/retrieval_diagnostics.jsonl"))
    parser.add_argument("--retriever", choices=["pubmed", "closed_world", "mixed_pool"], default="pubmed")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--max-candidates", type=int, default=500)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--include-empty-gt", action="store_true")
    parser.add_argument("--pubmed-api-key")
    parser.add_argument("--email")
    parser.add_argument("--sleep-s", type=float, default=0.34)
    args = parser.parse_args()
    summary = run_retrieval_diagnostics(
        args.cases,
        args.output,
        retriever=args.retriever,
        data_dir=args.data_dir,
        max_candidates=args.max_candidates,
        max_cases=args.max_cases,
        only_with_gt=not args.include_empty_gt,
        api_key=args.pubmed_api_key,
        email=args.email,
        sleep_s=args.sleep_s,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
