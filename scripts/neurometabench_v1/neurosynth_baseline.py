#!/usr/bin/env python3
"""Neurosynth v7 Track 1 baseline for NeurometaBench study-set reconstruction."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_NEUROSYNTH_DATA_DIR,
    load_case_records,
    sort_pmids,
    write_jsonl,
)


STOPWORDS = {
    "about",
    "adult",
    "analysis",
    "and",
    "brain",
    "case",
    "control",
    "controls",
    "data",
    "effect",
    "effects",
    "english",
    "fmri",
    "from",
    "functional",
    "human",
    "humans",
    "image",
    "imaging",
    "included",
    "including",
    "language",
    "magnetic",
    "meta",
    "mni",
    "mri",
    "only",
    "original",
    "paper",
    "papers",
    "participant",
    "participants",
    "pet",
    "reported",
    "reporting",
    "resonance",
    "results",
    "review",
    "reviews",
    "roi",
    "studies",
    "study",
    "task",
    "the",
    "using",
    "whole",
    "with",
}


def normalize_text(text: str) -> str:
    text = text.lower().replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _valid_term(term: str) -> bool:
    tokens = term.split()
    if not tokens:
        return False
    if not any(re.search(r"[a-z]", tok) for tok in tokens):
        return False
    if len(tokens) == 1:
        tok = tokens[0]
        return len(tok) > 2 and tok not in STOPWORDS
    return any(tok not in STOPWORDS and len(tok) > 2 for tok in tokens)


def load_vocabulary(neurosynth_dir: Path) -> list[str]:
    vocab_path = neurosynth_dir / "data-neurosynth_version-7_vocab-terms_vocabulary.txt"
    with vocab_path.open("r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def load_neurosynth_metadata(neurosynth_dir: Path) -> list[dict[str, Any]]:
    metadata_path = neurosynth_dir / "data-neurosynth_version-7_metadata.tsv.gz"
    records: list[dict[str, Any]] = []
    with gzip.open(metadata_path, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            year_raw = (row.get("year") or "").strip()
            records.append(
                {
                    "pmid": (row.get("id") or "").strip(),
                    "doi": (row.get("doi") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "year": int(year_raw) if year_raw.isdigit() else None,
                }
            )
    return records


def load_feature_matrix(neurosynth_dir: Path, n_studies: int, n_terms: int):
    try:
        import scipy.sparse as sp
    except ImportError as exc:  # pragma: no cover - exercised only in minimal envs
        raise RuntimeError("scipy is required to load Neurosynth feature matrices") from exc

    features_path = neurosynth_dir / "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz"
    matrix = sp.load_npz(features_path)
    if matrix.shape == (n_terms, n_studies):
        matrix = matrix.T
    if matrix.shape[0] != n_studies or matrix.shape[1] != n_terms:
        raise ValueError(
            f"Feature matrix shape {matrix.shape} does not match metadata/vocab "
            f"({n_studies}, {n_terms})"
        )
    return matrix.tocsr()


def _case_source_text(case: dict[str, Any], query_fields: list[str]) -> str:
    return " ".join(str(case.get(field) or "") for field in query_fields)


def select_neurosynth_terms(
    case: dict[str, Any],
    vocabulary: list[str],
    *,
    max_terms: int = 12,
    query_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    query_fields = query_fields or ["topic", "search", "inclusion"]
    source_norm = normalize_text(_case_source_text(case, query_fields))
    topic_norm = normalize_text(str(case.get("topic") or ""))
    source_padded = f" {source_norm} "
    topic_padded = f" {topic_norm} "

    selected: list[dict[str, Any]] = []
    for idx, raw_term in enumerate(vocabulary):
        term_norm = normalize_text(raw_term)
        if not _valid_term(term_norm):
            continue
        term_padded = f" {term_norm} "
        score = 0.0
        if term_padded in source_padded:
            score += 4.0
        elif len(term_norm.split()) == 1 and term_norm in source_norm.split():
            score += 2.0
        if term_padded in topic_padded:
            score += 3.0
        if score <= 0:
            continue
        tokens = term_norm.split()
        score += min(len(tokens), 4) * 0.25
        score += min(len(term_norm), 40) / 200.0
        selected.append({"term": raw_term, "term_index": idx, "match_score": round(score, 4)})

    selected.sort(key=lambda item: (-item["match_score"], str(item["term"])))
    return selected[:max_terms]


def rank_case_pmids(
    case: dict[str, Any],
    metadata: list[dict[str, Any]],
    vocabulary: list[str],
    feature_matrix: Any,
    *,
    top_k: int = 500,
    max_terms: int = 12,
    query_fields: list[str] | None = None,
) -> dict[str, Any]:
    selected_terms = select_neurosynth_terms(
        case,
        vocabulary,
        max_terms=max_terms,
        query_fields=query_fields,
    )
    year_cutoff = case.get("year_cutoff") or case.get("year")
    if not selected_terms:
        return {
            "case_id": case["case_id"],
            "meta_pmid": case["meta_pmid"],
            "system": "neurosynth_v7_term_rank",
            "selected_terms": [],
            "ranked_pmids": [],
            "predicted_pmids": [],
            "pmid_scores": {},
            "year_cutoff": year_cutoff,
            "n_ranked_positive": 0,
        }

    term_indices = [int(item["term_index"]) for item in selected_terms]
    weights = np.asarray([float(item["match_score"]) for item in selected_terms], dtype=float)
    submatrix = feature_matrix[:, term_indices]
    scores = np.asarray(submatrix.dot(weights)).ravel()

    ranked: list[tuple[str, float, int | None]] = []
    for idx, score in enumerate(scores):
        if not math.isfinite(float(score)) or float(score) <= 0:
            continue
        record = metadata[idx]
        pmid = record.get("pmid")
        if not pmid:
            continue
        year = record.get("year")
        if year_cutoff is not None and year is not None and int(year) > int(year_cutoff):
            continue
        ranked.append((str(pmid), float(score), year))

    ranked.sort(key=lambda item: (-item[1], item[2] if item[2] is not None else 9999, item[0]))
    ranked_pmids = [pmid for pmid, _, _ in ranked]
    predicted_pmids = ranked_pmids[:top_k] if top_k > 0 else ranked_pmids
    return {
        "case_id": case["case_id"],
        "meta_pmid": case["meta_pmid"],
        "system": "neurosynth_v7_term_rank",
        "selected_terms": selected_terms,
        "ranked_pmids": ranked_pmids,
        "predicted_pmids": predicted_pmids,
        "pmid_scores": {pmid: round(score, 8) for pmid, score, _ in ranked[: max(top_k, 100)]},
        "year_cutoff": year_cutoff,
        "n_ranked_positive": len(ranked_pmids),
    }


def run_neurosynth_baseline(
    cases_path: Path,
    neurosynth_dir: Path,
    output: Path,
    *,
    top_k: int = 500,
    max_terms: int = 12,
    only_with_gt: bool = True,
    query_fields: list[str] | None = None,
) -> dict[str, Any]:
    cases = load_case_records(cases_path)
    if only_with_gt:
        cases = [case for case in cases if case.get("has_gt")]

    vocabulary = load_vocabulary(neurosynth_dir)
    metadata = load_neurosynth_metadata(neurosynth_dir)
    feature_matrix = load_feature_matrix(neurosynth_dir, len(metadata), len(vocabulary))

    corpus_pmids = sort_pmids(record["pmid"] for record in metadata if record.get("pmid"))
    corpus_path = output.with_name("neurosynth_v7_corpus_pmids.txt")
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_path.write_text("\n".join(corpus_pmids) + "\n", encoding="utf-8")

    predictions = []
    for case in cases:
        row = rank_case_pmids(
            case,
            metadata,
            vocabulary,
            feature_matrix,
            top_k=top_k,
            max_terms=max_terms,
            query_fields=query_fields,
        )
        row["corpus_name"] = "neurosynth_v7"
        row["corpus_pmids_file"] = str(corpus_path)
        row["corpus_size"] = len(corpus_pmids)
        predictions.append(row)

    write_jsonl(predictions, output)
    return {
        "output": str(output),
        "corpus_pmids_file": str(corpus_path),
        "n_cases": len(predictions),
        "top_k": top_k,
        "max_terms": max_terms,
        "neurosynth_dir": str(neurosynth_dir),
    }


def _parse_query_fields(value: str) -> list[str]:
    return [field.strip() for field in value.split(",") if field.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--neurosynth-dir", type=Path, default=DEFAULT_NEUROSYNTH_DATA_DIR)
    parser.add_argument("--output", type=Path, default=Path("/tmp/neurometabench_v1/neurosynth_predictions.jsonl"))
    parser.add_argument("--top-k", type=int, default=500)
    parser.add_argument("--max-terms", type=int, default=12)
    parser.add_argument("--query-fields", default="topic,search,inclusion")
    parser.add_argument("--include-empty-gt", action="store_true")
    args = parser.parse_args()
    summary = run_neurosynth_baseline(
        args.cases,
        args.neurosynth_dir,
        args.output,
        top_k=args.top_k,
        max_terms=args.max_terms,
        only_with_gt=not args.include_empty_gt,
        query_fields=_parse_query_fields(args.query_fields),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
