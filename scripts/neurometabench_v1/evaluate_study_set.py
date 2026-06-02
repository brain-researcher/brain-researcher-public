#!/usr/bin/env python3
"""Evaluate NeurometaBench Track 1 PMID predictions."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    case_lookup,
    load_case_records,
    load_closed_world_candidate_rows,
    read_jsonl,
    sort_pmids,
)

DEFAULT_KS = (10, 25, 50, 100, 250, 500)
ALL_GT_SATURATED = "all_gt_saturated"
MIXED_ONLY = "mixed_only"
NO_GT = "no_gt"
HEADLINE_METRIC_POLICY = {
    "primary_subsets": [MIXED_ONLY],
    "diagnostic_subsets": [ALL_GT_SATURATED],
    "primary_metrics": [
        "include_only_f1",
        "eligibility_F1",
        "average_precision",
        "candidate_recall",
        "n_predicted_to_gold_ratio",
        "include_or_uncertain_predicted_to_gold_ratio",
        "include_only_predicted_to_gold_ratio",
        "over_conservatism_penalty",
    ],
    "diagnostic_metrics": ["precision", "recall", "f1"],
    "notes": [
        "Do not use include-or-uncertain f1 as the sole headline metric.",
        "All-GT-saturated cases contain no effective negatives and are reported as diagnostics.",
        "Report candidate_recall with screening metrics to separate retrieval ceiling from screening quality.",
    ],
}
PMID_TEXT_RE = re.compile(
    r"\b(?:pmid|pubmed(?:\s+id)?)\s*[:#]?\s*(\d{1,10})\b", re.IGNORECASE
)
STANDALONE_PMID_RE = re.compile(r"(?<!\d)(\d{5,10})(?!\d)")
CITATION_FIELDS = (
    "citation_pmids",
    "cited_pmids",
    "citations",
    "reference_pmids",
    "referenced_pmids",
)
SUPPORT_CITATION_FIELDS = (
    "supporting_pmids",
    "support_pmids",
    "source_pmid",
    "source_pmids",
    "evidence_pmids",
)


def _extract_pmids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if isinstance(value, dict):
        value = [value]
    pmids: list[str] = []
    for item in value:
        if isinstance(item, dict):
            pmid = item.get("pmid") or item.get("study_pmid") or item.get("id")
        else:
            pmid = item
        if pmid is not None and str(pmid).strip():
            pmids.append(str(pmid).strip())
    return pmids


def _dedupe_pmids(pmids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for pmid in pmids:
        cleaned = str(pmid).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _pmids_from_explicit_value(value: Any) -> list[str]:
    """Extract PMID-like values from structured citation fields.

    This is intentionally broader than free-text extraction because fields such
    as ``citation_pmids`` and ``supporting_pmids`` are already typed as citation
    slots by the prediction contract.
    """

    if value is None:
        return []
    if isinstance(value, dict):
        pmids: list[str] = []
        for key in (
            "pmid",
            "study_pmid",
            "source_pmid",
            "citation_pmid",
            "cited_pmid",
            "id",
            "pmids",
            "citation_pmids",
            "cited_pmids",
            "supporting_pmids",
        ):
            if key in value:
                pmids.extend(_pmids_from_explicit_value(value.get(key)))
        return _dedupe_pmids(pmids)
    if isinstance(value, list | tuple | set):
        pmids = []
        for item in value:
            pmids.extend(_pmids_from_explicit_value(item))
        return _dedupe_pmids(pmids)

    text = str(value).strip()
    if not text:
        return []
    pmids: list[str] = []
    for match in PMID_TEXT_RE.finditer(text):
        pmids.append(match.group(1))
    for token in re.split(r"[\s,;|]+", text):
        cleaned = token.strip().strip("[](){}.,:;")
        if cleaned.isdigit():
            pmids.append(cleaned)
    return _dedupe_pmids(pmids)


def _pmids_from_text(value: Any) -> list[str]:
    """Extract PMID mentions from free text without treating years as PMIDs."""

    if value is None:
        return []
    if isinstance(value, dict):
        text = " ".join(
            str(v)
            for v in value.values()
            if not isinstance(v, list | tuple | set | dict)
        )
    elif isinstance(value, list | tuple | set):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value)
    pmids = [match.group(1) for match in PMID_TEXT_RE.finditer(text)]
    pmids.extend(match.group(1) for match in STANDALONE_PMID_RE.finditer(text))
    return _dedupe_pmids(pmids)


def _pmids_from_evidence_spans(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        pmids: list[str] = []
        for field in (
            "pmid",
            "study_pmid",
            "source_pmid",
            "citation_pmid",
            "cited_pmid",
            "supporting_pmids",
        ):
            if field in value:
                pmids.extend(_pmids_from_explicit_value(value.get(field)))
        for field in ("text", "span", "quote", "evidence", "reason"):
            if field in value:
                pmids.extend(_pmids_from_text(value.get(field)))
        return _dedupe_pmids(pmids)
    if isinstance(value, list | tuple | set):
        pmids = []
        for item in value:
            pmids.extend(_pmids_from_evidence_spans(item))
        return _dedupe_pmids(pmids)
    return _pmids_from_text(value)


def _record_pmid(record: dict[str, Any]) -> str | None:
    for field in ("pmid", "study_pmid", "record_pmid"):
        values = _pmids_from_explicit_value(record.get(field))
        if values:
            return values[0]
    return None


def prediction_pmids(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    ranked = _extract_pmids(row.get("ranked_pmids"))
    candidate_pmids = _extract_pmids(row.get("candidate_pmids"))

    predicted: list[str] = []
    has_explicit_prediction_field = False
    for field in (
        "predicted_pmids",
        "included_pmids",
        "selected_pmids",
        "study_pmids",
        "pmids",
    ):
        if field in row:
            predicted = _extract_pmids(row.get(field))
            has_explicit_prediction_field = True
            break

    if not ranked and candidate_pmids:
        ranked = candidate_pmids
    if not ranked:
        ranked = predicted
    if not has_explicit_prediction_field and not candidate_pmids:
        predicted = ranked
    elif not has_explicit_prediction_field:
        predicted = []
    return ranked, predicted


def include_only_pmids(prediction: dict[str, Any]) -> list[str]:
    """Extract PMIDs with explicit include decisions from decision_records."""

    records = prediction.get("decision_records")
    if not isinstance(records, list):
        return []
    pmids: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if _record_include_decision(record) is True:
            pmid = _record_pmid(record)
            if pmid:
                pmids.append(pmid)
    return _dedupe_pmids(pmids)


def _anchor_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("anchors")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _anchor_candidate_pmid(anchor: dict[str, Any]) -> str | None:
    for field in ("candidate_pmid", "pmid", "study_pmid"):
        values = _pmids_from_explicit_value(anchor.get(field))
        if values:
            return values[0]
    return None


def _anchor_decision(anchor: dict[str, Any]) -> str | None:
    decision = str(anchor.get("decision") or "").strip().lower()
    if decision in {"include", "exclude", "uncertain"}:
        return decision
    return None


def br_screening_anchor_metrics(
    prediction: dict[str, Any], *, ranked_pmids: list[str]
) -> dict[str, Any]:
    """Summarize optional Layer A BR screening anchors carried in prediction rows."""

    anchors = _anchor_list(prediction.get("br_screening_anchors"))
    ranked_set = set(ranked_pmids)
    decision_by_pmid: dict[str, str] = {}
    records = prediction.get("decision_records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            pmid = _record_pmid(record)
            raw_decision = str(record.get("decision") or "").strip().lower()
            if pmid and raw_decision in {"include", "exclude", "uncertain"}:
                decision_by_pmid[pmid] = raw_decision

    anchored_pmids: set[str] = set()
    include = exclude = uncertain = consumed = outside_candidates = 0
    for anchor in anchors:
        pmid = _anchor_candidate_pmid(anchor)
        decision = _anchor_decision(anchor)
        if pmid:
            anchored_pmids.add(pmid)
            if ranked_set and pmid not in ranked_set:
                outside_candidates += 1
        if decision == "include":
            include += 1
        elif decision == "exclude":
            exclude += 1
        elif decision == "uncertain":
            uncertain += 1
        if pmid and decision and decision_by_pmid.get(pmid) == decision:
            consumed += 1

    return {
        "br_screening_anchor_count": len(anchors),
        "br_screening_anchor_candidate_count": len(anchored_pmids),
        "br_screening_anchor_coverage": _rate(len(anchored_pmids & ranked_set), len(ranked_set)),
        "br_screening_anchor_include_count": include,
        "br_screening_anchor_uncertain_count": uncertain,
        "br_screening_anchor_exclude_count": exclude,
        "br_screening_anchor_outside_candidate_count": outside_candidates,
        "br_screening_anchor_consumed_count": consumed,
        "br_screening_anchor_consumption_rate": _rate(consumed, len(anchors)),
    }


def _load_corpus(
    row: dict[str, Any], prediction_path: Path | None = None
) -> set[str] | None:
    if isinstance(row.get("corpus_pmids"), list):
        return set(_extract_pmids(row["corpus_pmids"]))
    corpus_file = row.get("corpus_pmids_file")
    if not corpus_file:
        return None
    path = Path(str(corpus_file))
    if not path.is_absolute() and prediction_path is not None:
        path = prediction_path.parent / path
    if not path.exists():
        return None
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def average_precision(ranked_pmids: list[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    seen: set[str] = set()
    hits = 0
    precision_sum = 0.0
    for rank, pmid in enumerate(ranked_pmids, 1):
        if pmid in seen:
            continue
        seen.add(pmid)
        if pmid in relevant:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / len(relevant)


def _rate(num: int, denom: int) -> float | None:
    return round(num / denom, 6) if denom else None


def _selected_n(case: dict[str, Any], fallback: int) -> int:
    raw = str(case.get("selected_n") or "").strip()
    match = re.search(r"\d+", raw)
    if not match:
        return fallback
    return max(1, min(int(match.group()), fallback))


def _lexical_tokens(text: str) -> list[str]:
    stopwords = {
        "and",
        "brain",
        "control",
        "controls",
        "data",
        "english",
        "functional",
        "human",
        "humans",
        "imaging",
        "included",
        "language",
        "magnetic",
        "meta",
        "mri",
        "only",
        "original",
        "paper",
        "papers",
        "participant",
        "participants",
        "resonance",
        "review",
        "reviews",
        "studies",
        "study",
        "the",
        "with",
    }
    out: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()):
        token = token.strip("-")
        if not token or token in stopwords or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _candidate_text(row: dict[str, str]) -> str:
    return " ".join(
        str(row.get(field) or "")
        for field in ("title", "Author", "author", "reason", "posthoc_reason")
    )


def _case_query_text(case: dict[str, Any]) -> str:
    return " ".join(
        str(case.get(field) or "")
        for field in (
            "topic",
            "search",
            "inclusion",
            "additional_methods",
            "method",
            "modality",
        )
    )


def _keyword_score(query_tokens: set[str], candidate_row: dict[str, str]) -> float:
    doc_tokens = _lexical_tokens(_candidate_text(candidate_row))
    if not doc_tokens:
        return 0.0
    score = 0.0
    for token in doc_tokens:
        if token in query_tokens:
            score += 1.0
        elif any(token in query or query in token for query in query_tokens):
            score += 0.25
    title = (candidate_row.get("title") or "").lower()
    for phrase in (
        "functional mri",
        "voxel-based morphometry",
        "gray matter",
        "grey matter",
    ):
        if phrase in title and any(part in query_tokens for part in phrase.split()):
            score += 0.5
    return score


def build_closed_world_baseline_predictions(
    case: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    random_repeats: int = 20,
    random_seed: int = 0,
) -> list[dict[str, Any]]:
    rows = load_closed_world_candidate_rows(data_dir, str(case.get("meta_pmid") or ""))
    candidate_pmids = [
        str(row.get("study_pmid") or "").strip()
        for row in rows
        if str(row.get("study_pmid") or "").strip()
    ]
    if not candidate_pmids:
        return []

    top_n = _selected_n(case, len(candidate_pmids))
    predictions: list[dict[str, Any]] = [
        {
            "case_id": case["case_id"],
            "meta_pmid": case.get("meta_pmid"),
            "system": "closed_world_include_all",
            "candidate_source": "closed_world_all_studies",
            "ranked_pmids": candidate_pmids,
            "predicted_pmids": candidate_pmids,
            "baseline": True,
        }
    ]

    query_tokens = set(_lexical_tokens(_case_query_text(case)))
    scored = [
        (
            str(row.get("study_pmid") or "").strip(),
            _keyword_score(query_tokens, row),
        )
        for row in rows
        if str(row.get("study_pmid") or "").strip()
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    bm25_ranked = [pmid for pmid, _ in scored]
    predictions.append(
        {
            "case_id": case["case_id"],
            "meta_pmid": case.get("meta_pmid"),
            "system": "closed_world_keyword_bm25",
            "candidate_source": "closed_world_all_studies_annotated",
            "ranked_pmids": bm25_ranked,
            "predicted_pmids": bm25_ranked[:top_n],
            "baseline": True,
            "query_tokens": sorted(query_tokens),
        }
    )

    for repeat in range(max(0, random_repeats)):
        rng = random.Random(f"{random_seed}:{case.get('case_id')}:{repeat}")
        ranked = list(candidate_pmids)
        rng.shuffle(ranked)
        predictions.append(
            {
                "case_id": case["case_id"],
                "meta_pmid": case.get("meta_pmid"),
                "system": "closed_world_random",
                "candidate_source": "closed_world_all_studies",
                "ranked_pmids": ranked,
                "predicted_pmids": ranked[:top_n],
                "baseline": True,
                "random_repeat": repeat,
                "random_seed": random_seed,
            }
        )
    return predictions


def rationale_completeness(prediction: dict[str, Any]) -> dict[str, Any]:
    records = prediction.get("decision_records")
    if not isinstance(records, list) or not records:
        return {
            "n_decision_records": 0,
            "reason_coverage": None,
            "criterion_coverage": None,
            "evidence_span_coverage": None,
            "confidence_coverage": None,
        }

    n = len(records)
    n_reason = 0
    n_criterion = 0
    n_evidence = 0
    n_confidence = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("reason") or "").strip():
            n_reason += 1
        if record.get("criterion_ids"):
            n_criterion += 1
        if record.get("evidence_spans"):
            n_evidence += 1
        if isinstance(record.get("confidence"), int | float):
            n_confidence += 1
    return {
        "n_decision_records": n,
        "reason_coverage": _rate(n_reason, n),
        "criterion_coverage": _rate(n_criterion, n),
        "evidence_span_coverage": _rate(n_evidence, n),
        "confidence_coverage": _rate(n_confidence, n),
    }


def _record_include_decision(record: dict[str, Any]) -> bool | None:
    include_value = record.get("include")
    if isinstance(include_value, bool):
        return include_value
    if include_value is not None:
        include_text = str(include_value).strip().lower()
        if include_text in {"1", "true", "yes", "y", "include", "included", "selected"}:
            return True
        if include_text in {"0", "false", "no", "n", "exclude", "excluded", "rejected"}:
            return False

    decision = str(record.get("decision") or "").strip().lower()
    if decision in {
        "include",
        "included",
        "yes",
        "accept",
        "accepted",
        "selected",
        "keep",
    }:
        return True
    if decision in {"exclude", "excluded", "no", "reject", "rejected", "drop", "omit"}:
        return False
    return None


def decision_distribution_metrics(prediction: dict[str, Any]) -> dict[str, Any]:
    """Count explicit include/uncertain/exclude behavior in decision_records."""

    records = prediction.get("decision_records")
    if not isinstance(records, list):
        records = []

    include = exclude = uncertain = other = 0
    for record in records:
        if not isinstance(record, dict):
            other += 1
            continue
        include_decision = _record_include_decision(record)
        raw_decision = str(record.get("decision") or "").strip().lower()
        if include_decision is True:
            include += 1
        elif include_decision is False:
            exclude += 1
        elif raw_decision in {
            "uncertain",
            "maybe",
            "unknown",
            "ambiguous",
            "unclear",
            "insufficient_evidence",
        }:
            uncertain += 1
        else:
            other += 1

    n = len(records)
    return {
        "decision_include_count": include,
        "decision_uncertain_count": uncertain,
        "decision_exclude_count": exclude,
        "decision_other_count": other,
        "decision_include_rate": _rate(include, n),
        "decision_uncertain_rate": _rate(uncertain, n),
        "decision_exclude_rate": _rate(exclude, n),
        "decision_other_rate": _rate(other, n),
    }


def eligibility_decision_metrics(
    prediction: dict[str, Any], included_pmids: set[str]
) -> dict[str, Any]:
    """Score include/exclude decisions in ``decision_records`` against GT included PMIDs.

    Only records with both a PMID and an evaluable include/exclude decision are
    included. Included is the positive class. Missing records are not treated as
    negatives here; retrieval coverage remains the job of the study-set metrics.
    """

    records = prediction.get("decision_records")
    if not isinstance(records, list):
        records = []

    tp = fp = fn = 0
    n_evaluable = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        pmid = _record_pmid(record)
        decision = _record_include_decision(record)
        if not pmid or decision is None:
            continue
        n_evaluable += 1
        is_gt_include = pmid in included_pmids
        if decision and is_gt_include:
            tp += 1
        elif decision and not is_gt_include:
            fp += 1
        elif not decision and is_gt_include:
            fn += 1

    precision = _rate(tp, tp + fp) if n_evaluable else None
    recall = _rate(tp, tp + fn) if n_evaluable else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall > 0:
        f1 = round(2 * precision * recall / (precision + recall), 6)
    else:
        f1 = 0.0

    return {
        "eligibility_n_evaluable_decisions": n_evaluable,
        "eligibility_tp": tp,
        "eligibility_fp": fp,
        "eligibility_fn": fn,
        "eligibility_precision": precision,
        "eligibility_recall": recall,
        "eligibility_f1": f1,
        "eligibility_F1": f1,
    }


def _citation_pmids_for_record(record: dict[str, Any]) -> tuple[list[str], set[str]]:
    citations: list[str] = []
    supported: list[str] = []

    for field in CITATION_FIELDS:
        citations.extend(_pmids_from_explicit_value(record.get(field)))

    for field in SUPPORT_CITATION_FIELDS:
        pmids = _pmids_from_explicit_value(record.get(field))
        citations.extend(pmids)
        supported.extend(pmids)

    evidence_pmids = _pmids_from_evidence_spans(record.get("evidence_spans"))
    citations.extend(evidence_pmids)
    supported.extend(evidence_pmids)

    citations.extend(_pmids_from_text(record.get("reason")))
    return _dedupe_pmids(citations), set(_dedupe_pmids(supported))


def citation_hallucination_metrics(
    prediction: dict[str, Any],
    *,
    ranked_pmids: list[str],
    predicted_pmids: list[str],
    corpus_pmids: set[str] | None,
) -> dict[str, Any]:
    """Classify citation PMIDs from decision records with a conservative policy.

    Non-retrievable citations are not present in the corpus, ranked PMIDs,
    predicted PMIDs, or decision-record PMIDs. Wrong-source is reserved for an
    unsupported citation attached to one decision record that points at another
    decision record's retrievable PMID. Retrievable-unsupported covers other
    retrievable citations that lack self-citation or an explicit support field
    such as ``supporting_pmids``, ``source_pmid``, or ``evidence_spans``.
    """

    records = prediction.get("decision_records")
    if not isinstance(records, list):
        records = []
    decision_pmids = {
        pmid
        for record in records
        if isinstance(record, dict)
        for pmid in [_record_pmid(record)]
        if pmid
    }
    prediction_corpus_pmids = set(
        _pmids_from_explicit_value(prediction.get("corpus_pmids"))
    )
    retrievable_pmids = (
        set(ranked_pmids)
        | set(predicted_pmids)
        | decision_pmids
        | prediction_corpus_pmids
    )
    if corpus_pmids is not None:
        retrievable_pmids |= set(corpus_pmids)

    counts = {
        "citation_non_retrievable_count": 0,
        "citation_retrievable_unsupported_count": 0,
        "citation_wrong_source_count": 0,
    }
    citation_count = 0

    for record in records:
        if not isinstance(record, dict):
            continue
        record_pmid = _record_pmid(record)
        citations, supported_pmids = _citation_pmids_for_record(record)
        for cited_pmid in citations:
            citation_count += 1
            if cited_pmid not in retrievable_pmids:
                counts["citation_non_retrievable_count"] += 1
            elif cited_pmid == record_pmid or cited_pmid in supported_pmids:
                continue
            elif (
                record_pmid
                and cited_pmid in decision_pmids
                and cited_pmid != record_pmid
            ):
                counts["citation_wrong_source_count"] += 1
            else:
                counts["citation_retrievable_unsupported_count"] += 1

    hallucination_count = sum(counts.values())
    return {
        "citation_count": citation_count,
        "citation_hallucination_count": hallucination_count,
        "citation_hallucination_rate": _rate(hallucination_count, citation_count),
        "citation_non_retrievable": _rate(
            counts["citation_non_retrievable_count"], citation_count
        ),
        "citation_retrievable_unsupported": _rate(
            counts["citation_retrievable_unsupported_count"],
            citation_count,
        ),
        "citation_wrong_source": _rate(
            counts["citation_wrong_source_count"], citation_count
        ),
        **counts,
    }


def evaluate_prediction(
    case: dict[str, Any],
    prediction: dict[str, Any],
    *,
    corpus_pmids: set[str] | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict[str, Any]:
    gt = {str(pmid) for pmid in case.get("gt_pmids", [])}
    ranked_pmids, predicted_pmids = prediction_pmids(prediction)
    ranked_set = set(ranked_pmids)
    predicted_set = set(predicted_pmids)
    include_only_set = set(include_only_pmids(prediction))
    candidate_tp = gt & ranked_set
    gt_candidate_ratio = _rate(len(candidate_tp), len(ranked_set))
    if not gt:
        case_partition = NO_GT
    elif ranked_set and len(candidate_tp) == len(ranked_set):
        case_partition = ALL_GT_SATURATED
    else:
        case_partition = MIXED_ONLY
    tp = gt & predicted_set
    include_only_tp = gt & include_only_set
    rationale = rationale_completeness(prediction)
    decision_distribution = decision_distribution_metrics(prediction)
    eligibility = eligibility_decision_metrics(prediction, gt)
    br_anchors = br_screening_anchor_metrics(prediction, ranked_pmids=ranked_pmids)
    citation_metrics = citation_hallucination_metrics(
        prediction,
        ranked_pmids=ranked_pmids,
        predicted_pmids=predicted_pmids,
        corpus_pmids=corpus_pmids,
    )

    precision = _rate(len(tp), len(predicted_set))
    recall = _rate(len(tp), len(gt))
    if precision is None or recall is None:
        f1 = None
    elif (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 6)
    else:
        f1 = 0.0
    include_only_precision = _rate(len(include_only_tp), len(include_only_set))
    include_only_recall = _rate(len(include_only_tp), len(gt))
    if include_only_precision is None or include_only_recall is None:
        include_only_f1 = None
    elif include_only_precision + include_only_recall > 0:
        include_only_f1 = round(
            2
            * include_only_precision
            * include_only_recall
            / (include_only_precision + include_only_recall),
            6,
        )
    else:
        include_only_f1 = 0.0
    include_or_uncertain_predicted_to_gold_ratio = _rate(len(predicted_set), len(gt))
    include_only_predicted_to_gold_ratio = _rate(len(include_only_set), len(gt))
    if not gt:
        over_conservatism_penalty = None
        over_conservatism_signal = False
    else:
        include_only_recall_for_penalty = (
            include_only_recall if include_only_recall is not None else 0.0
        )
        candidate_recall = _rate(len(candidate_tp), len(gt))
        over_conservatism_penalty = (
            round(max(0.0, candidate_recall - include_only_recall_for_penalty), 6)
            if candidate_recall is not None
            else None
        )
        over_conservatism_signal = bool(
            over_conservatism_penalty is not None
            and over_conservatism_penalty >= 0.25
            and (
                include_only_predicted_to_gold_ratio is None
                or include_only_predicted_to_gold_ratio < 1.0
            )
        )

    corpus_gt = gt & corpus_pmids if corpus_pmids is not None else set()
    row: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "topic": case.get("topic"),
        "route": case.get("route"),
        "system": prediction.get("system", "unknown"),
        "candidate_source": prediction.get("candidate_source"),
        "task_type": case.get("task_type"),
        "primary_task_layer": case.get("primary_task_layer"),
        "n_gt": len(gt),
        "n_predicted": len(predicted_set),
        "n_ranked": len(ranked_set),
        "n_candidate_tp": len(candidate_tp),
        "gt_candidate_ratio": gt_candidate_ratio,
        "n_predicted_to_gold_ratio": include_or_uncertain_predicted_to_gold_ratio,
        "include_or_uncertain_predicted_to_gold_ratio": (
            include_or_uncertain_predicted_to_gold_ratio
        ),
        "case_partition": case_partition,
        "is_all_gt_saturated": case_partition == ALL_GT_SATURATED,
        "candidate_recall": _rate(len(candidate_tp), len(gt)),
        "n_tp": len(tp),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "include_only_n_predicted": len(include_only_set),
        "include_only_n_tp": len(include_only_tp),
        "include_only_predicted_to_gold_ratio": include_only_predicted_to_gold_ratio,
        "include_only_precision": include_only_precision,
        "include_only_recall": include_only_recall,
        "include_only_f1": include_only_f1,
        "over_conservatism_penalty": over_conservatism_penalty,
        "over_conservatism_signal": over_conservatism_signal,
        "average_precision": (
            round(average_precision(ranked_pmids, gt), 6)
            if average_precision(ranked_pmids, gt) is not None
            else None
        ),
        "has_known_corpus": corpus_pmids is not None,
        "corpus_name": prediction.get("corpus_name"),
        "n_corpus": len(corpus_pmids) if corpus_pmids is not None else None,
        "n_gt_in_corpus": len(corpus_gt) if corpus_pmids is not None else None,
        "n_tp_in_corpus": len(tp & corpus_gt) if corpus_pmids is not None else None,
        "corpus_ceiling": (
            _rate(len(corpus_gt), len(gt)) if corpus_pmids is not None else None
        ),
        "coverage_normalized_recall": (
            _rate(len(tp & corpus_gt), len(corpus_gt))
            if corpus_pmids is not None
            else None
        ),
        "coverage_normalized_average_precision": (
            round(average_precision(ranked_pmids, corpus_gt), 6)
            if corpus_pmids is not None
            and average_precision(ranked_pmids, corpus_gt) is not None
            else None
        ),
        "tp_pmids": sort_pmids(tp),
        "include_only_tp_pmids": sort_pmids(include_only_tp),
        "missed_pmids": sort_pmids(gt - predicted_set),
        **rationale,
        **decision_distribution,
        **eligibility,
        **br_anchors,
        **citation_metrics,
    }

    for k in ks:
        topk = set(ranked_pmids[:k])
        topk_tp = gt & topk
        row[f"precision_at_{k}"] = _rate(len(topk_tp), len(topk))
        row[f"recall_at_{k}"] = _rate(len(topk_tp), len(gt))
    return row


def _avg(values: list[Any]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return round(mean(nums), 6) if nums else None


SUMMARY_METRIC_NAMES = [
    "precision",
    "recall",
    "f1",
    "n_predicted_to_gold_ratio",
    "include_or_uncertain_predicted_to_gold_ratio",
    "include_only_predicted_to_gold_ratio",
    "include_only_precision",
    "include_only_recall",
    "include_only_f1",
    "over_conservatism_penalty",
    "eligibility_precision",
    "eligibility_recall",
    "eligibility_f1",
    "eligibility_F1",
    "candidate_recall",
    "average_precision",
    "corpus_ceiling",
    "coverage_normalized_recall",
    "coverage_normalized_average_precision",
    "reason_coverage",
    "criterion_coverage",
    "evidence_span_coverage",
    "confidence_coverage",
    "decision_include_rate",
    "decision_uncertain_rate",
    "decision_exclude_rate",
    "decision_other_rate",
    "br_screening_anchor_coverage",
    "br_screening_anchor_consumption_rate",
    "citation_hallucination_rate",
    "citation_non_retrievable",
    "citation_retrievable_unsupported",
    "citation_wrong_source",
]


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall > 0:
        return round(2 * precision * recall / (precision + recall), 6)
    return 0.0


def _summarize_system_rows(system_rows: list[dict[str, Any]]) -> dict[str, Any]:
    eval_rows = [row for row in system_rows if row.get("n_gt", 0) > 0]
    total_gt = sum(int(row["n_gt"]) for row in eval_rows)
    total_pred = sum(int(row["n_predicted"]) for row in eval_rows)
    total_ranked = sum(int(row.get("n_ranked") or 0) for row in eval_rows)
    total_tp = sum(int(row["n_tp"]) for row in eval_rows)
    total_include_only_pred = sum(
        int(row.get("include_only_n_predicted") or 0) for row in eval_rows
    )
    total_include_only_tp = sum(
        int(row.get("include_only_n_tp") or 0) for row in eval_rows
    )
    total_candidate_tp = sum(int(row.get("n_candidate_tp") or 0) for row in eval_rows)
    total_eligibility_evaluable = sum(
        int(row.get("eligibility_n_evaluable_decisions") or 0) for row in eval_rows
    )
    total_br_screening_anchor_count = sum(
        int(row.get("br_screening_anchor_count") or 0) for row in eval_rows
    )
    total_br_screening_anchor_candidate_count = sum(
        int(row.get("br_screening_anchor_candidate_count") or 0) for row in eval_rows
    )
    total_br_screening_anchor_consumed_count = sum(
        int(row.get("br_screening_anchor_consumed_count") or 0) for row in eval_rows
    )
    total_decision_include = sum(
        int(row.get("decision_include_count") or 0) for row in eval_rows
    )
    total_decision_uncertain = sum(
        int(row.get("decision_uncertain_count") or 0) for row in eval_rows
    )
    total_decision_exclude = sum(
        int(row.get("decision_exclude_count") or 0) for row in eval_rows
    )
    total_decision_other = sum(
        int(row.get("decision_other_count") or 0) for row in eval_rows
    )
    total_decisions = (
        total_decision_include
        + total_decision_uncertain
        + total_decision_exclude
        + total_decision_other
    )
    total_eligibility_tp = sum(
        int(row.get("eligibility_tp") or 0) for row in eval_rows
    )
    total_eligibility_fp = sum(
        int(row.get("eligibility_fp") or 0) for row in eval_rows
    )
    total_eligibility_fn = sum(
        int(row.get("eligibility_fn") or 0) for row in eval_rows
    )
    total_citation_count = sum(
        int(row.get("citation_count") or 0) for row in eval_rows
    )
    total_citation_hallucination_count = sum(
        int(row.get("citation_hallucination_count") or 0) for row in eval_rows
    )
    total_citation_non_retrievable_count = sum(
        int(row.get("citation_non_retrievable_count") or 0) for row in eval_rows
    )
    total_citation_retrievable_unsupported_count = sum(
        int(row.get("citation_retrievable_unsupported_count") or 0)
        for row in eval_rows
    )
    total_citation_wrong_source_count = sum(
        int(row.get("citation_wrong_source_count") or 0) for row in eval_rows
    )
    total_gt_in_corpus = sum(
        int(row.get("n_gt_in_corpus") or 0)
        for row in eval_rows
        if row.get("has_known_corpus")
    )
    total_tp_in_corpus = sum(
        int(row.get("n_tp_in_corpus") or 0)
        for row in eval_rows
        if row.get("has_known_corpus")
    )
    system_summary: dict[str, Any] = {
        "n_cases": len(system_rows),
        "n_cases_with_gt": len(eval_rows),
        "macro": {
            metric: _avg([row.get(metric) for row in eval_rows])
            for metric in SUMMARY_METRIC_NAMES
        },
        "micro": {
            "n_gt": total_gt,
            "n_predicted": total_pred,
            "n_tp": total_tp,
            "n_candidate_tp": total_candidate_tp,
            "candidate_recall": _rate(total_candidate_tp, total_gt),
            "n_predicted_to_gold_ratio": _rate(total_pred, total_gt),
            "include_or_uncertain_predicted_to_gold_ratio": _rate(total_pred, total_gt),
            "precision": _rate(total_tp, total_pred),
            "recall": _rate(total_tp, total_gt),
            "include_only_n_predicted": total_include_only_pred,
            "include_only_n_tp": total_include_only_tp,
            "include_only_predicted_to_gold_ratio": _rate(
                total_include_only_pred, total_gt
            ),
            "include_only_precision": _rate(
                total_include_only_tp, total_include_only_pred
            ),
            "include_only_recall": _rate(total_include_only_tp, total_gt),
        },
    }
    micro = system_summary["micro"]
    micro["f1"] = _f1(micro["precision"], micro["recall"])
    micro["include_only_f1"] = _f1(
        micro["include_only_precision"], micro["include_only_recall"]
    )
    micro["over_conservatism_penalty"] = (
        round(
            max(
                0.0,
                (micro["candidate_recall"] or 0.0)
                - (micro["include_only_recall"] or 0.0),
            ),
            6,
        )
        if total_gt
        else None
    )
    micro["over_conservatism_signal"] = bool(
        micro["over_conservatism_penalty"] is not None
        and micro["over_conservatism_penalty"] >= 0.25
        and (
            micro["include_only_predicted_to_gold_ratio"] is None
            or micro["include_only_predicted_to_gold_ratio"] < 1.0
        )
    )
    micro["eligibility_n_evaluable_decisions"] = total_eligibility_evaluable
    micro["br_screening_anchor_count"] = total_br_screening_anchor_count
    micro["br_screening_anchor_candidate_count"] = total_br_screening_anchor_candidate_count
    micro["br_screening_anchor_coverage"] = _rate(
        total_br_screening_anchor_candidate_count, total_ranked
    )
    micro["br_screening_anchor_consumed_count"] = total_br_screening_anchor_consumed_count
    micro["br_screening_anchor_consumption_rate"] = _rate(
        total_br_screening_anchor_consumed_count, total_br_screening_anchor_count
    )
    micro["decision_include_count"] = total_decision_include
    micro["decision_uncertain_count"] = total_decision_uncertain
    micro["decision_exclude_count"] = total_decision_exclude
    micro["decision_other_count"] = total_decision_other
    micro["decision_include_rate"] = _rate(total_decision_include, total_decisions)
    micro["decision_uncertain_rate"] = _rate(total_decision_uncertain, total_decisions)
    micro["decision_exclude_rate"] = _rate(total_decision_exclude, total_decisions)
    micro["decision_other_rate"] = _rate(total_decision_other, total_decisions)
    micro["eligibility_tp"] = total_eligibility_tp
    micro["eligibility_fp"] = total_eligibility_fp
    micro["eligibility_fn"] = total_eligibility_fn
    micro["eligibility_precision"] = _rate(
        total_eligibility_tp,
        total_eligibility_tp + total_eligibility_fp,
    )
    micro["eligibility_recall"] = _rate(
        total_eligibility_tp,
        total_eligibility_tp + total_eligibility_fn,
    )
    micro["eligibility_f1"] = _f1(
        micro["eligibility_precision"], micro["eligibility_recall"]
    )
    micro["eligibility_F1"] = micro["eligibility_f1"]
    micro["citation_count"] = total_citation_count
    micro["citation_hallucination_count"] = total_citation_hallucination_count
    micro["citation_hallucination_rate"] = _rate(
        total_citation_hallucination_count,
        total_citation_count,
    )
    micro["citation_non_retrievable_count"] = total_citation_non_retrievable_count
    micro["citation_retrievable_unsupported_count"] = (
        total_citation_retrievable_unsupported_count
    )
    micro["citation_wrong_source_count"] = total_citation_wrong_source_count
    micro["citation_non_retrievable"] = _rate(
        total_citation_non_retrievable_count,
        total_citation_count,
    )
    micro["citation_retrievable_unsupported"] = _rate(
        total_citation_retrievable_unsupported_count,
        total_citation_count,
    )
    micro["citation_wrong_source"] = _rate(
        total_citation_wrong_source_count,
        total_citation_count,
    )
    if any(row.get("has_known_corpus") for row in eval_rows):
        micro["n_gt_in_corpus"] = total_gt_in_corpus
        micro["n_tp_in_corpus"] = total_tp_in_corpus
        micro["corpus_ceiling"] = _rate(total_gt_in_corpus, total_gt)
        micro["coverage_normalized_recall"] = _rate(
            total_tp_in_corpus, total_gt_in_corpus
        )
    return system_summary


def _case_partition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    partitions: dict[str, dict[str, Any]] = {}
    for row in rows:
        partition = str(row.get("case_partition") or "unknown")
        case_key = str(row.get("case_id") or row.get("meta_pmid") or "")
        meta_pmid = str(row.get("meta_pmid") or "")
        entry = partitions.setdefault(
            partition,
            {"n_rows": 0, "case_ids": set(), "meta_pmids": set()},
        )
        entry["n_rows"] += 1
        if case_key:
            entry["case_ids"].add(case_key)
        if meta_pmid:
            entry["meta_pmids"].add(meta_pmid)
    return {
        partition: {
            "n_rows": entry["n_rows"],
            "n_unique_cases": len(entry["case_ids"]),
            "case_ids": sorted(entry["case_ids"]),
            "meta_pmids": sorted(entry["meta_pmids"]),
        }
        for partition, entry in sorted(partitions.items())
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_system.setdefault(str(row.get("system") or "unknown"), []).append(row)

    out: dict[str, Any] = {
        "n_rows": len(rows),
        "headline_metric_policy": HEADLINE_METRIC_POLICY,
        "case_partitions": _case_partition_summary(rows),
        "systems": {},
    }
    for system, system_rows in by_system.items():
        system_summary = _summarize_system_rows(system_rows)
        subsets: dict[str, Any] = {}
        for partition in (MIXED_ONLY, ALL_GT_SATURATED, NO_GT):
            subset_rows = [
                row for row in system_rows if row.get("case_partition") == partition
            ]
            if subset_rows:
                subsets[partition] = _summarize_system_rows(subset_rows)
        system_summary["subsets"] = subsets
        out["systems"][system] = system_summary
    return out


def _subset_role(subset: str) -> str:
    if subset in HEADLINE_METRIC_POLICY["primary_subsets"]:
        return "primary"
    if subset in HEADLINE_METRIC_POLICY["diagnostic_subsets"]:
        return "diagnostic"
    return "context"


def write_subset_summary_csv(summary: dict[str, Any], output_dir: Path) -> None:
    """Write a compact system-by-subset table for paper/result reporting."""

    fieldnames = [
        "system",
        "subset",
        "role",
        "n_cases",
        "n_cases_with_gt",
        "n_gt",
        "n_predicted",
        "n_tp",
        "n_predicted_to_gold_ratio",
        "include_or_uncertain_predicted_to_gold_ratio",
        "precision",
        "recall",
        "f1",
        "include_only_predicted_to_gold_ratio",
        "include_only_precision",
        "include_only_recall",
        "include_only_f1",
        "over_conservatism_penalty",
        "over_conservatism_signal",
        "eligibility_F1",
        "average_precision",
        "candidate_recall",
        "br_screening_anchor_coverage",
        "br_screening_anchor_consumption_rate",
        "decision_include_rate",
        "decision_uncertain_rate",
        "decision_exclude_rate",
    ]
    rows: list[dict[str, Any]] = []
    for system, system_summary in sorted(summary.get("systems", {}).items()):
        for subset, subset_summary in {
            "overall": system_summary,
            **system_summary.get("subsets", {}),
        }.items():
            micro = subset_summary.get("micro", {})
            macro = subset_summary.get("macro", {})
            rows.append(
                {
                    "system": system,
                    "subset": subset,
                    "role": _subset_role(subset),
                    "n_cases": subset_summary.get("n_cases"),
                    "n_cases_with_gt": subset_summary.get("n_cases_with_gt"),
                    "n_gt": micro.get("n_gt"),
                    "n_predicted": micro.get("n_predicted"),
                    "n_tp": micro.get("n_tp"),
                    "n_predicted_to_gold_ratio": micro.get("n_predicted_to_gold_ratio"),
                    "include_or_uncertain_predicted_to_gold_ratio": micro.get(
                        "include_or_uncertain_predicted_to_gold_ratio"
                    ),
                    "precision": micro.get("precision"),
                    "recall": micro.get("recall"),
                    "f1": micro.get("f1"),
                    "include_only_predicted_to_gold_ratio": micro.get(
                        "include_only_predicted_to_gold_ratio"
                    ),
                    "include_only_precision": micro.get("include_only_precision"),
                    "include_only_recall": micro.get("include_only_recall"),
                    "include_only_f1": micro.get("include_only_f1"),
                    "over_conservatism_penalty": micro.get(
                        "over_conservatism_penalty"
                    ),
                    "over_conservatism_signal": micro.get("over_conservatism_signal"),
                    "eligibility_F1": micro.get("eligibility_F1"),
                    "average_precision": macro.get("average_precision"),
                    "candidate_recall": micro.get("candidate_recall"),
                    "br_screening_anchor_coverage": micro.get(
                        "br_screening_anchor_coverage"
                    ),
                    "br_screening_anchor_consumption_rate": micro.get(
                        "br_screening_anchor_consumption_rate"
                    ),
                    "decision_include_rate": micro.get("decision_include_rate"),
                    "decision_uncertain_rate": micro.get("decision_uncertain_rate"),
                    "decision_exclude_rate": micro.get("decision_exclude_rate"),
                }
            )

    with (output_dir / "study_set_subset_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_prediction_files(
    cases_path: Path,
    prediction_paths: list[Path],
    output_dir: Path,
    *,
    add_closed_world_baselines: bool = False,
    data_dir: Path = DEFAULT_DATA_DIR,
    random_repeats: int = 20,
    random_seed: int = 0,
) -> dict[str, Any]:
    cases = case_lookup(load_case_records(cases_path))
    rows: list[dict[str, Any]] = []
    for prediction_path in prediction_paths:
        for prediction in read_jsonl(prediction_path):
            key = str(prediction.get("case_id") or prediction.get("meta_pmid") or "")
            case = cases.get(key)
            if case is None:
                continue
            corpus = _load_corpus(prediction, prediction_path)
            rows.append(evaluate_prediction(case, prediction, corpus_pmids=corpus))

    if add_closed_world_baselines:
        seen_case_ids = {
            str(case.get("case_id"))
            for case in cases.values()
            if case.get("case_id") and case.get("has_gt")
        }
        for case_id in sorted(seen_case_ids):
            case = cases[case_id]
            for prediction in build_closed_world_baseline_predictions(
                case,
                data_dir=data_dir,
                random_repeats=random_repeats,
                random_seed=random_seed,
            ):
                rows.append(evaluate_prediction(case, prediction))

    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    (output_dir / "study_set_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "study_set_metrics.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    write_subset_summary_csv(summary, output_dir)
    csv_path = output_dir / "study_set_metrics.csv"
    fieldnames = [
        "system",
        "candidate_source",
        "case_id",
        "meta_pmid",
        "topic",
        "route",
        "task_type",
        "primary_task_layer",
        "n_gt",
        "n_predicted",
        "n_ranked",
        "n_candidate_tp",
        "gt_candidate_ratio",
        "n_predicted_to_gold_ratio",
        "include_or_uncertain_predicted_to_gold_ratio",
        "case_partition",
        "is_all_gt_saturated",
        "n_tp",
        "candidate_recall",
        "precision",
        "recall",
        "f1",
        "include_only_n_predicted",
        "include_only_n_tp",
        "include_only_predicted_to_gold_ratio",
        "include_only_precision",
        "include_only_recall",
        "include_only_f1",
        "over_conservatism_penalty",
        "over_conservatism_signal",
        "eligibility_n_evaluable_decisions",
        "eligibility_tp",
        "eligibility_fp",
        "eligibility_fn",
        "eligibility_precision",
        "eligibility_recall",
        "eligibility_f1",
        "eligibility_F1",
        "average_precision",
        "corpus_name",
        "n_gt_in_corpus",
        "n_tp_in_corpus",
        "corpus_ceiling",
        "coverage_normalized_recall",
        "coverage_normalized_average_precision",
        "n_decision_records",
        "reason_coverage",
        "criterion_coverage",
        "evidence_span_coverage",
        "confidence_coverage",
        "decision_include_count",
        "decision_uncertain_count",
        "decision_exclude_count",
        "decision_other_count",
        "decision_include_rate",
        "decision_uncertain_rate",
        "decision_exclude_rate",
        "decision_other_rate",
        "br_screening_anchor_count",
        "br_screening_anchor_candidate_count",
        "br_screening_anchor_coverage",
        "br_screening_anchor_include_count",
        "br_screening_anchor_uncertain_count",
        "br_screening_anchor_exclude_count",
        "br_screening_anchor_outside_candidate_count",
        "br_screening_anchor_consumed_count",
        "br_screening_anchor_consumption_rate",
        "citation_count",
        "citation_hallucination_count",
        "citation_hallucination_rate",
        "citation_non_retrievable",
        "citation_retrievable_unsupported",
        "citation_wrong_source",
        "citation_non_retrievable_count",
        "citation_retrievable_unsupported_count",
        "citation_wrong_source_count",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
    return {"summary": summary, "output_dir": str(output_dir), "n_rows": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--predictions", type=Path, action="append", default=[])
    parser.add_argument(
        "--output-dir", type=Path, default=Path("/tmp/neurometabench_v1/eval")
    )
    parser.add_argument("--add-closed-world-baselines", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--random-repeats", type=int, default=20)
    parser.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args()
    if not args.predictions and not args.add_closed_world_baselines:
        parser.error("provide --predictions or --add-closed-world-baselines")
    print(
        json.dumps(
            evaluate_prediction_files(
                args.cases,
                args.predictions,
                args.output_dir,
                add_closed_world_baselines=args.add_closed_world_baselines,
                data_dir=args.data_dir,
                random_repeats=args.random_repeats,
                random_seed=args.random_seed,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
